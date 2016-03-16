import os
import time
import sys
import os.path
import stat
import re
import socket
import uuid
import ast
from uuid import UUID
from jarray import array

import distutils.dir_util
from subprocess import call

from java.lang import Boolean
from java.nio import ByteBuffer
from java.io import File
from java.io import FileOutputStream
from java.util.zip import ZipFile
from java.util.zip import ZipEntry
from java.util.zip import ZipInputStream

from com.datasynapse.fabric.util import ContainerUtils
from com.datasynapse.fabric.common import RuntimeContextVariable
from com.datasynapse.fabric.common import ActivationInfo
from com.datasynapse.fabric.common import ArchiveActivationInfo
from com.datasynapse.fabric.container import ArchiveDetail


class DockerSwarm:
    
    def __init__(self, additionalVariables):
        " initialize Docker Swarm"
     
        self.__swarmid = getVariableValue("DOCKER_SWARM_UUID")
        if not self.__swarmid:
            raise Exception("DOCKER_SWARM_UUID is required and must be a UUID")
        elif not isUUID(self.__swarmid):
            raise Exception("DOCKER_SWARM_ID provided is not a valid UUID")
        
        self.__bootDockerSock = getVariableValue("DOCKER_BOOTSTRAP_SOCK")
        if not self.__bootDockerSock:
            raise Exception("DOCKER_BOOTSTRAP_SOCK is required")

        discoveryKeyStore = getVariableValue("DISCOVERY_KEY_STORE")
        if not discoveryKeyStore:
            raise Exception("DISCOVERY_KEY_STORE is required")
        
        self.__discoveryService = getVariableValue("DISCOVERY_SERVICE")
        if not self.__discoveryService:
            raise Exception("DISCOVERY_SERVICE is required")
        
        if str(discoveryKeyStore).endswith("/"):
            discoveryKeyStore = discoveryKeyStore[:-1]
        self.__discoveryKeyStore = discoveryKeyStore + "/" + self.__swarmid
         
        listenAddress = getVariableValue("LISTEN_ADDRESS")
        
        self.__mountVolumes=['', '']
    
        self.__dockerContainerName=["swarm_join", "swarm_manage", "swarm_registrator"]
        
        self.__dockerImage = ["swarm"]
        self.__command = ["join"]
        dockerPort = ":"+ getVariableValue("DOCKER_PORT", "2375")
        self.__dockerAddr = listenAddress + dockerPort
        args = ["--advertise",  self.__dockerAddr, self.__discoveryKeyStore]
        self.__commandArgs = [list2str(args)]
        self.__networkMode = ['--net=host']
        
        self.__dockerImage.append("swarm")
        self.__command.append("manage")
        managePort = getVariableValue("MANAGE_PORT", "4000")
        self.__manageAddr  = listenAddress + ":"+ managePort
        strategy = getVariableValue("DOCKER_SWARM_STRATEGY", "spread")
        if strategy not in ["spread", "binpack", "random"]:
            strategy = "spread"
                
        args = ["-H",  ":"+ managePort,  "--strategy",  strategy," --replication",  "--advertise", self.__manageAddr, self.__discoveryKeyStore]
        self.__commandArgs.append(list2str(args))
        self.__networkMode.append('--net=host')
                
        registrator = getVariableValue("DOCKER_IMAGE_REGISTRATOR")
        if registrator:
            self.__dockerImage.append(registrator)
            self.__networkMode.append('--net=host')
            self.__mountVolumes.append('--volume=/var/run/docker.sock:/tmp/docker.sock')
            self.__command.append(self.__discoveryService)
            self.__commandArgs.append('')
            
        self.__basedir = getVariableValue("CONTAINER_WORK_DIR")
         
        self.__running = [False, False, False]
        self.__stats = []
        self.__dockerStats = {}
        self.__runningContainers=[]
        
        self.__dockerLog = getVariableValue("DOCKER_CONTAINER_LOGS")
        if not self.__dockerLog:
            self.__dockerLog = os.path.join(self.__basedir , "docker.log")
       
        self.__sudo = Boolean.parseBoolean(getVariableValue("USE_SUDO", "false"))
        
        self.__compName = proxy.container.currentDomain.name
        self.__compName = re.sub("[\s]+", "", self.__compName)
        self.__dockerCompose = getVariableValue("DOCKER_COMPOSE_PATH")
        self.__detachSwarm = Boolean.parseBoolean(getVariableValue("DETACH_SWARM_ON_SHUTDOWN", "false"))
        self.__forceReconfig = Boolean.parseBoolean(getVariableValue("FORCE_RECONFIG", "true"))
       
        self.__deploydir=os.path.join(getVariableValue("COMPOSE_DEPLOY_DIRECTORY", self.__basedir), self.__swarmid)
     
        self.__swarmNetwork=getVariableValue("DOCKER_SWARM_NETWORK")
          
        self.__lockExpire = int(getVariableValue("LOCK_EXPIRE", "300000"))
        self.__lockWait = int(getVariableValue("LOCK_WAIT", "30000"))
        self.__role = "replica"
        
        self.__lockExpire = int(getVariableValue("LOCK_EXPIRE", "300000"))
        self.__lockWait = int(getVariableValue("LOCK_WAIT", "30000"))
   
    
    def __configureDockerDaemon(self):
        logger.info("Enter __configureDockerDaemon")
        try:
            self.__lock()
            os.environ["CLUSTER_STORE"]=getVariableValue("DISCOVERY_KEY_STORE").replace("/", "\/")
            os.environ["CLUSTER_ADVERTISE"]=self.__dockerAddr
            bindir=os.path.join(self.__basedir, "bin")
            changePermissions(bindir)
            cmd=os.path.join(bindir, "configure-daemon.sh")
            if os.path.isfile(cmd):
                cmdList=[cmd]
                logger.info("Executing:" + list2str(cmdList))
                retcode = call(cmdList)
                logger.info("Return code:" + `retcode`)
                if retcode != 0:
                    raise Exception("Main Docker daemon configuration failed for cluster-store")
        finally:
            self.__unlock()
            
        logger.info("Exit __configureDockerDaemon")

    def __swarmNetworkExists(self):
        file=None
        networkExists = False
        logger.info("Enter __swarmNetworkExists")
        try:
            self.__lock()
            path=os.path.join(self.__basedir, "network.ls")
            file = open(path, "w")
            cmdList=["docker", "-H", self.__manageAddr, "network", "ls", "--filter", "name="+ self.__swarmNetwork]
            logger.info("Executing:" + list2str(cmdList))
            retcode = call(cmdList, stdout=file)
            logger.info("Return code:" + str(retcode))
            file.close()
            file=open(path, "r")
            lines=file.readlines()
            networkExists = (lines and len(lines) > 1)
        finally:
            self.__unlock()
            if file:
                file.close()
                
        logger.info("Exit __swarmNetworkExists")
        return networkExists
    
    def __createSwarmNetwork(self):
        logger.info("Enter __createSwarmNetwork")
        try:
            self.__lock()
            if not self.__swarmNetworkExists():
                cmdList=["docker", "-H", self.__manageAddr, "network", "create"]
                options=getVariableValue("DOCKER_SWARM_NETWORK_OPTIONS")
                if options:
                    optionsList=options.split()
                    cmdList.extend(optionsList)
                cmdList.append(self.__swarmNetwork)
                    
                logger.info("Executing:" + list2str(cmdList))
                etcode = call(cmdList)
                logger.info("Return code:" + str(retcode))
                if retcode != 0:
                    raise Exception("Swarm network creation failed")
        finally:
            self.__unlock()
                
        logger.info("Exit __createSwarmNetwork")
            
    def __lock(self):
        "get global lock"
        self.__locked = ContainerUtils.acquireGlobalLock(self.__swarmid, self.__lockExpire, self.__lockWait)
        if not self.__locked:
            raise "Unable to acquire global lock:" + self.__swarmid
    
    def __unlock(self):
        "unlock global lock"
        if self.__locked:
            ContainerUtils.releaseGlobalLock(self.__swarmid)
            self.__locked = None
    
    def __writeStats(self):
        "write running container stats output"
        
        file = None
        try:
            for rc in self.__runningContainers:
                cid=rc["Id"]
                path=os.path.join(self.__basedir, cid+".stats")
                file = open(path, "w")
            
                cmdList = ["docker", "-H", self.__dockerAddr, "stats", "--no-stream=true", cid]
                if self.__sudo:
                    cmdList.insert(0, "sudo")
                    retcode = call(cmdList, stdout=file)
        finally:
            if file:
                file.close()

    def __readStats(self):
        "read stats output"
        file = None
        
        try:
            self.__dockerStats["Docker CPU Usage %"] = float(0)
            self.__dockerStats["Docker Memory Usage (MB)"] = float(0)
            self.__dockerStats["Docker Memory Limit (MB)"] = float(0)
            self.__dockerStats["Docker Memory Usage %"] = float(0)
            self.__dockerStats["Docker Network Input (MB)"] = float(0)
            self.__dockerStats["Docker Network Output (MB)"] = float(0)
            self.__dockerStats["Docker Block Input (MB)"] = float(0)
            self.__dockerStats["Docker Block Output (MB)"] = float(0)
            
            for rc in self.__runningContainers:
                cid=rc["Id"]
                path=os.path.join(self.__basedir, cid+".stats")
                
                if os.path.isfile(path):
                    file = open(path, "r")
                    lines = file.readlines()
                    for line in lines:
                        row = line.replace('%','').replace('/','').split()
                        if row and len(row) == 15:
                            self.__dockerStats["Docker CPU Usage %"] += float(row[1])
                            self.__dockerStats["Docker Memory Usage (MB)"] += convertToMB(row[2], row[3])
                            self.__dockerStats["Docker Memory Limit (MB)"] = max(self.__dockerStats["Docker Memory Limit (MB)"], convertToMB(row[4], row[5]))
                            self.__dockerStats["Docker Memory Usage %"] += float(row[6])
                            self.__dockerStats["Docker Network Input (MB)"] += convertToMB(row[7], row[8])
                            self.__dockerStats["Docker Network Output (MB)"] += convertToMB(row[9], row[10])
                            self.__dockerStats["Docker Block Input (MB)"] += convertToMB(row[11], row[12])
                            self.__dockerStats["Docker Block Output (MB)"] += convertToMB(row[13], row[14])
        finally:
            if file:
                file.close()
                
    def __run(self, index):
        "run docker container"
        
        logger.info("Enter __run")
        cmdList = ["docker", "-H", self.__bootDockerSock,"run", "--detach=true"]
        
        network = listItem(self.__networkMode, index)
        if network:
            cmdList.append(network)
            
        mountVolumes = listItem(self.__mountVolumes, index)
        if mountVolumes:
            cmdList = cmdList + mountVolumes.split()
            
        cmdList.append("--name=" + listItem(self.__dockerContainerName, index))
       
        image = listItem(self.__dockerImage, index)
        
        cmdList.append(image)
    
        command = listItem(self.__command, index)
        if command:
            cmdList.append(command)
            
        commandArgs = listItem(self.__commandArgs, index)
        if commandArgs:
            args = commandArgs.split()
            if args:
                cmdList.extend(args)
      
        if self.__sudo:
            cmdList.insert(0, "sudo")
            
        logger.info("Run Docker container:" + list2str(cmdList))
        retcode = call(cmdList)
        logger.info("Run Docker container return code:" + `retcode`)
        
        if retcode != 0:
            raise Exception("Error return code:" + str(retcode))
            
        logger.info("Exit __run")
        
    def __stop(self, index):
        "stop docker container"
        
        logger.info("Enter __stop")
        cmdList = ["docker", "-H", self.__bootDockerSock,"stop"]
       
        options = getVariableValue("DOCKER_STOP_OPTIONS")
        if options:
            options = options.split()
            cmdList = cmdList + options
        
        cmdList.append(listItem(self.__dockerContainerName, index))
        
        if self.__sudo:
            cmdList.insert(0, "sudo")
        
        logger.info("Stop docker container:" + list2str(cmdList))
        retcode = call(cmdList)
        logger.info("Stop docker container return code:" + `retcode`)
        
        logger.info("Exit __stop")
    
    def __rm(self, index):
        "remove docker container"
        
        logger.info("Enter __rm")
        cmdList = ["docker", "-H", self.__bootDockerSock, "rm", "--force", "--volumes" ]
        
        cmdList.append(listItem(self.__dockerContainerName, index))
        
        if self.__sudo:
            cmdList.insert(0, "sudo")
            
        logger.info("Remove Docker container:" + list2str(cmdList))
        retcode = call(cmdList)
        logger.info("Remove Docker container return code:" + `retcode`)
        logger.info("Exit __rm")
        
    def start(self):
        "start enabler"
        
        logger.info("Enter start")
      
        copyContainerEnvironment()
        self.__configureDockerDaemon()
        llen = len(self.__dockerContainerName)
       
        for index in range(llen):
            if  (not self.__isBootContainerRunning(index)):
                self.__rm(index)
                self.__run(index)
            else:
                if (not self.__isBootContainerValid(index)):
                    if self.__forceReconfig:
                        self.__rm(index)
                        self.__run(index)
                    else:
                        raise Exception("FORCE_RECONFIG is not 'true' and running Swarm container is not using current key store")
                else:
                    logger.info("Using running container:" + listItem(self.__dockerContainerName, index))
        
        if self.__swarmNetwork:
            self.__createSwarmNetwork()
        
        logger.info("Exit start")
    
    def stop(self):
        "stop enabler"
        logger.info("Enter stop")
        
        if not self.__detachSwarm:
            copyContainerEnvironment()
            for index in range(len(self.__dockerContainerName) - 1, -1, -1):
                self.__stop(index)
            
        logger.info("Exit stop")
         
    def cleanup(self):
        "cleanup"
        
        logger.info("Enter cleanup")
        if not self.__detachSwarm:
            copyContainerEnvironment()
            for index in range(len(self.__dockerContainerName) - 1, -1, -1):
                self.__rm(index)
            
        logger.info("Exit cleanup")
    
    def __isSwarmContainerRunning(self, cid):

        file = None
        file2=None
        running=False
        try:
            path = os.path.join(self.__basedir , "curl.out")
            file2 = open(path, "w")
        
            path = os.path.join(self.__basedir , "project.container")
            file = open(path, "w")
                
            cmdList = ["curl", "http://" + self.__manageAddr +"/containers/"+str(cid)+"/json"]
      
            if self.__sudo:
                cmdList.insert(0,"sudo")
            
            logger.fine("Executing:"+ list2str(cmdList))
            retcode = call(cmdList, stdout=file, stderr=file2)
            logger.fine("Return code:"+ str(retcode))
            
            file.close()
            file = open(path, "r")
            lines = file.readlines()
            
            if lines and len(lines) >0:
                json = lines[0]
                container=parseJson(json)
                state=container["State"]
                running= state["Running"]
        except:
            running = False
            type, value, traceback = sys.exc_info()
            logger.severe("__isSwarmContainerRunning error:" + `value`)
        finally:
            if file:
                file.close()
            if file2:
                file2.close()
        return running
                
   
                
    def isRunning(self):
        copyContainerEnvironment()  
        
        running = True
        try:
            llen = len(self.__dockerContainerName)
            for index in range(llen):
                if not self.__isBootContainerRunning(index):
                    running = False
                    break
            
            logger.fine("isRunning:" + `running`)
            
            if running:
                self.__getLocalRunningContainers()
                self.__writeStats()
                self.__readStats()
                info = proxy.container.getActivationInfo()
                self.__updateActivationInfo(info, update=True)
        except:
            running=False
            type, value, traceback = sys.exc_info()
            logger.warning("isRunning error:" + `value`)
        
        return running

    def __isBootContainerValid(self, index):
        valid = False
        file = None
        try:
            path = os.path.join(self.__basedir , "docker.inspect")
            file = open(path, "w")
            cmdList = ["docker", "-H",   self.__bootDockerSock, "inspect",  listItem(self.__dockerContainerName, index) ]
      
            if self.__sudo:
                cmdList.insert(0, "sudo")
                
            logger.fine("Executing:" + list2str(cmdList))
            retcode = call(cmdList, stdout=file)
            logger.fine("Return code:" + `retcode`)
            file.close()
            
            file = open(path, "r")
            lines = file.readlines()
            
            for line in lines:
                valid = (index < 2 and line.find(self.__discoveryKeyStore) >= 0) or (index == 2 and line.find(self.__discoveryService) >= 0)
                if valid:
                    break;
        except:
            type, value, traceback = sys.exc_info()
            logger.warning("__isBootContainerValid error:" + `value`)
        finally:
            if file:
                file.close()
            
        return  valid
    
    def __isBootContainerRunning(self, index):
        self.__running[index] = False
        file = None
        try:
            path = os.path.join(self.__basedir , "docker.ps")
            file = open(path, "w")
            cmdList = ["docker", "-H",   self.__bootDockerSock, "ps", "--filter", "name="+ listItem(self.__dockerContainerName, index) ]
      
            if self.__sudo:
                cmdList.insert(0, "sudo")
                
            logger.fine("Executing:" + list2str(cmdList))
            retcode = call(cmdList, stdout=file)
            logger.fine("Return code:" + `retcode`)
            file.close()
            
            file = open(path, "r")
            lines = file.readlines()
            self.__running[index]=len(lines) > 1
        finally:
            if file:
                file.close()
            
        return  self.__running[index]
    
    def hasStarted(self):
        copyContainerEnvironment()  
        
        started = True
        try:
            llen = len(self.__dockerContainerName)
            for index in range(llen):
                if not self.__isBootContainerRunning(index):
                    running = False
                    break
        except:
            started=False
            type, value, traceback = sys.exc_info()
            logger.warning("hasStarted error:" + `value`)
        
        return started
    
    def __updateActivationInfo(self, info, update=False):
        
        file = None
        file2=None
        try:
            path = os.path.join(self.__basedir , "curl.out")
            file2 = open(path, "w")
        
            path = os.path.join(self.__basedir , "swarm.info")
            file = open(path, "w")
            
            cmdList = ["curl", "http://" + self.__manageAddr +"/info"]
      
            if self.__sudo:
                cmdList.insert(0,"sudo")
            retcode = call(cmdList, stdout=file, stderr=file2)
            file.close()
            file = open(path, "r")
            lines = file.readlines()
           
            if lines and len(lines) >0:
                json = lines[0]
                jsonDict=parseJson(json)
                needUpdate = False
                
                curValue = info.getProperty("DockerSwarmContainers")
                newValue = str(jsonDict['Containers'])
                if curValue != newValue:
                    info.setProperty("DockerSwarmContainers", newValue)
                    needUpdate = True
                
                curValue = info.getProperty("DockerSwarmContainersRunning")
                newValue = str(jsonDict['ContainersRunning'])
                if curValue != newValue:
                    info.setProperty("DockerSwarmContainersRunning", newValue)
                    needUpdate = True
                
                curValue = info.getProperty("DockerSwarmContainersStopped")
                newValue = str(jsonDict['ContainersStopped'])
                if curValue != newValue:
                    info.setProperty("DockerSwarmContainersStopped", newValue)
                    needUpdate = True
                
                curValue = info.getProperty("DockerSwarmImages")
                newValue = str(jsonDict['Images'])
                if curValue != newValue:
                    info.setProperty("DockerSwarmImages", newValue)
                    needUpdate = True
                
                selectList=["Role", "Primary"]
                for key in selectList:
                    output=[]
                    parseJsonDictionary(jsonDict, key, output)
                    propKey = "DockerSwarm" + key
                    curValue = info.getProperty(propKey)
                    if output:
                        if key == "Role":
                            self.__role = output[0]
                            
                        if output[0] != curValue:
                            info.setProperty(propKey, output[0])
                            needUpdate = True
                    elif curValue:
                        info.setProperty(propKey, '')
                        needUpdate = True
                
                oldinfo=info.getProperty("DockerContainerInfo")
                newinfo=str(self.__runningContainers)
                if oldinfo != newinfo:
                    info.setProperty("DockerContainerInfo", str(self.__runningContainers))
                    needUpdate = True
                    
                if update and needUpdate:
                    proxy.container.updateActivationInfoProperties(info)
        except:
            type, value, traceback = sys.exc_info()
            logger.severe("update activation info error:" + `value`)
        finally:
            if file:
                file.close()
            if file2:
                file2.close()
                
            
    def installActivationInfo(self, info):
        "install activation info"
        list = self.__discoveryKeyStore.split("/")
        info.setProperty("DockerSwarmUUID", self.__discoveryKeyStore.split("/")[-1])
        
        if self.__swarmNetwork:
            info.setProperty("DockerSwarmNetwork", self.__swarmNetwork)
        
        listenAddress = getVariableValue("LISTEN_ADDRESS")
        host = getVariableValue("ENGINE_USERNAME")
        
        if self.__manageAddr:
            httpEndpoint = "http://" + self.__manageAddr.replace(listenAddress, host) + "/"
            info.setProperty("DockerSwarmManage", httpEndpoint)
            
        self.__updateActivationInfo(info, update=False)
        
    
    def __getLocalRunningContainers(self):        
        file = None
        file2=None
        try:
            self.__runningContainers=[]
            path = os.path.join(self.__basedir , "curl.out")
            file2 = open(path, "w")
        
            path = os.path.join(self.__basedir , "running.containers")
            file = open(path, "w")
           
            cmdList = ["curl", "http://" + self.__dockerAddr +"/containers/json"]
      
            if self.__sudo:
                cmdList.insert(0,"sudo")
            retcode = call(cmdList, stdout=file, stderr=file2)
            
            file.close()
            file = open(path, "r")
            lines = file.readlines()
            if lines and len(lines) >0:
                json = lines[0]
                containerList=parseJson(json)
                keys=["Id", "Names", "Image",  "Ports"]
                for container in containerList: 
                    info={}
                    for key in keys:
                        info[key]=container[key]
                    ipaddr=[]
                    parseJsonDictionary(container, "IPAddress", ipaddr)
                    info["IPAddress"]=ipaddr[0]
                    self.__runningContainers.append(info)
        except:
            type, value, traceback = sys.exc_info()
            logger.severe("getRunningContainers error:" + `value`)
        finally:
            if file:
                file.close()
            if file2:
                file2.close()
                
    def archiveDeploy(self, archiveName, archiveLocators, properties):
        
        try:
            if self.__role != "primary":
                raise Exception("Not a primary Swam manage node")
            
            archiveZip = str(ContainerUtils.retrieveAndConfigureArchiveFile(proxy.container, archiveName, archiveLocators,  properties))
            
            if archiveZip[-4:] != ".zip":
                 raise Exception("Archive must be a ZIP file containing Docker Compose project")
             
            logger.info("Deploying archive:" + archiveZip)
            project = getArchiveDeployProperty("project-name", properties,  None)
            
            if not project:
                raise Exception("project-name is required: Must be unique within this Docker swarm cluster")
            
            dir = os.path.join(self.__deploydir,  archiveName, project)
            
            if os.path.isdir(dir):
                raise Exception("Archive is already deployed")
            
            extractZip(archiveZip, dir)
            
            composeFile=getDockerComposeFile(dir)
            
            copyContainerEnvironment()
            os.environ["DOCKER_HOST"] = "tcp://" + self.__manageAddr
            os.environ["COMPOSE_HTTP_TIMEOUT"] = "300"
           
            cmdlist = [self.__dockerCompose, "--file", composeFile, "--project-name", project, "create", "--force-recreate"]
            logger.info("Executing:"+ list2str(cmdlist))
            retcode = call(cmdlist)
            logger.info("Return code:" + str(retcode))
            if retcode != 0:
                try:
                    self.archiveUndeploy(archiveName, properties)
                except:
                    pass
                finally:
                    if os.path.isdir(dir):
                        distutils.dir_util.remove_tree(dir)
                        path = os.path.join(self.__deploydir,  archiveName)
                        os.rmdir(path)
                raise Exception("Archive deploy failed:" + archiveName)
            
        except:
            type, value, traceback = sys.exc_info()
            logger.severe("archiveDeploy error:" + `value`)
            raise
     
            
    def archiveUndeploy(self, archiveName,  properties):
        try:
            if self.__role != "primary":
                raise Exception("Not a primary Swam manage node")

            logger.info("Undeploying archive:" + archiveName)
            project = getArchiveDeployProperty("project-name", properties,  None)
            
            if not project:
                raise Exception("project-name is required: Must be unique within this Docker swarm cluster")
            
         
            dir = os.path.join(self.__deploydir,  archiveName, project )

            if os.path.isdir(dir):
                composeFile=getDockerComposeFile(dir)
                cmdlist=[self.__dockerCompose, "--file", composeFile, "--project-name", project , "down"]
                
                removeImages =  getArchiveDeployProperty("remove-images", properties, False, True)
                removeVolumes = getArchiveDeployProperty("remove-volumes", properties, False, True)
                if removeImages:
                    cmdlist.extend(["--rmi", "all"])
                if removeVolumes:
                    cmdlist.append("--volumes")
                
                logger.info("Executing:"+ list2str(cmdlist))
                copyContainerEnvironment()
                os.environ["DOCKER_HOST"] = "tcp://" + self.__manageAddr
                os.environ["COMPOSE_HTTP_TIMEOUT"] = "300"
                retcode = call(cmdlist)
                logger.info("Return code:" + str(retcode))
                if retcode == 0:
                    distutils.dir_util.remove_tree(dir)
                    path = os.path.join(self.__deploydir,  archiveName)
                    os.rmdir(path)
                else:
                    raise Exception("Archive undeploy failed:" + archiveName)
        except:
            type, value, traceback = sys.exc_info()
            logger.severe("archiveUndeploy error:" + `value`)
            raise
      
        
    def archiveStart(self, archiveName,  properties):
        
        archiveActivationInfo = None
        try:
            if self.__role != "primary":
                raise Exception("Not a primary Swam manage node")
            
            logger.info("Starting archive:" + archiveName)
            project = getArchiveDeployProperty("project-name", properties,  None)
            if not project:
                raise Exception("project-name is required: Must be unique within this Docker swarm cluster")
          
            dir = os.path.join(self.__deploydir,  archiveName, project)
            if not os.path.isdir(dir):
                raise Exception("Cannot start archive because archive is not deployed:" + archiveName)
             
            composeFile=getDockerComposeFile(dir)
                    
            cmdlist=[self.__dockerCompose, "--file", composeFile, "--project-name", project, "start"]
            logger.info("Executing:"+ list2str(cmdlist))
            copyContainerEnvironment()
            os.environ["DOCKER_HOST"] = "tcp://" + self.__manageAddr
            os.environ["COMPOSE_HTTP_TIMEOUT"] = "300"
            retcode = call(cmdlist)
            logger.info("Return code:" + str(retcode))
            if retcode == 0:
                archiveActivationInfo = ArchiveActivationInfo(archiveName, project)
            else:
                raise Exception("Archive start failed:" + archiveName)
          
        except:
            type, value, traceback = sys.exc_info()
            logger.severe("archiveStart error:" + `value`)
            raise
        
        return archiveActivationInfo
        
    def archiveStop(self, archiveName,  archiveId, properties):
        try:
            if self.__role != "primary":
               raise Exception("Not a primary Swam manage node")
            
            logger.info("Stopping archive:" + archiveName +":"+ archiveId)
            project = archiveId
          
            dir = os.path.join(self.__deploydir,  archiveName, project)
            if os.path.isdir(dir):
                composeFile=getDockerComposeFile(dir)
                cmdlist = [self.__dockerCompose, "--file", composeFile, "--project-name", project, "stop"]
                logger.info("Executing:"+ list2str(cmdlist))
                os.environ["COMPOSE_HTTP_TIMEOUT"] = "300"
                os.environ["DOCKER_HOST"] = "tcp://" + self.__manageAddr
                retcode = call(cmdlist)
                logger.info("Return code:" + str(retcode))
                if retcode != 0:
                    raise Exception("Archive stop failed:" + archiveName)
        except:
            type, value, traceback = sys.exc_info()
            logger.severe("archiveStop error:" + `value`)
            raise
    
    def archiveDetect(self):
        archiveDetail=[]
        try:
            if self.__role == "primary":
                archives=[ name for name in os.listdir(self.__deploydir) if os.path.isdir(os.path.join(self.__deploydir, name)) ]
                for archive in archives:
                    dir = os.path.join(self.__deploydir, archive)
                    if os.path.isdir(dir):
                        projects=[ name for name in os.listdir(dir) if os.path.isdir(os.path.join(dir, name)) ]
                        for project in projects:
                            projectdir=os.path.join(dir, project)
                            running = self.__isProjectRunning(projectdir)
                            logger.fine("Detected deployed archive:"+ archive +":"+ project +":running:"+ str(running))
                            archiveDetail.append(ArchiveDetail(archive, running, False, project))
        except:
            type, value, traceback = sys.exc_info()
            logger.severe("archiveDetect error:" + `value`)
        
        return array(archiveDetail, ArchiveDetail)
    
    def __isProjectRunning(self, projectdir):
        file=None
        running=True
        try:
            composeFile=getDockerComposeFile(projectdir)
            cmdlist=[self.__dockerCompose, "--file", composeFile, "ps", "-q"]
            logger.fine("Executing:"+ list2str(cmdlist))
            os.environ["DOCKER_HOST"] = "tcp://" + self.__manageAddr
            os.environ["COMPOSE_HTTP_TIMEOUT"] = "300"
            path = os.path.join(self.__basedir, "ps.out")
            file=open(path, "w")
            retcode = call(cmdlist, stdout=file)
            logger.fine("Return code:" + str(retcode))
            file.close()
            path=os.path.join(self.__basedir, "ps.out")
            file=open(path, "r")
            lines=file.readlines()
            if lines and len(lines) > 0:
                for line in lines:
                    if not self.__isSwarmContainerRunning(line.strip()):
                        running = False
                        break
            else:
                running = False
        except:
            running = False
            type, value, traceback = sys.exc_info()
            logger.severe("isProjectRunning error" + `value`)
        finally:
            if file:
                file.close()
                
        return running
    
   
    def getStat(self, statName):
        " get statistic"
        return self.__dockerStats[statName]

def changePermissions(dir):
    logger.info("chmod:" + dir)
    os.chmod(dir, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
      
    for dirpath, dirnames, filenames in os.walk(dir):
        for dirname in dirnames:
            dpath = os.path.join(dirpath, dirname)
            os.chmod(dpath, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
           
        for filename in filenames:
               filePath = os.path.join(dirpath, filename)
               os.chmod(filePath, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
                
def getDockerComposeFile(dir):
    composeFile=os.path.join(dir, "docker-compose.yml")
    if not os.path.isfile(composeFile):
        composeFile=os.path.join(dir, "docker-compose.yaml")
        if not composeFile:
            raise Exception("No docker-compose.yml or docker-compose.yaml file found in:" + str(dir))
    return composeFile
                
def convertToMB(value, unit):
    unit = unit.lower()
    value = float(value)
    if unit == "gb":
        value = value * 1000.0
    elif unit == "b":
        value = value / 1000.0
        
    return value
    
def parseJson(json):
    json=json.replace('null','None')
    json=json.replace('false','False')
    json=json.replace('true','True')
    jsonObject=ast.literal_eval(json.strip())
    return jsonObject
    
def parseJsonDictionary(map, select, output):
    for key,value in map.iteritems():
        if key == select:
            output.append(value)
        elif type(value) is dict:
            parseJsonDictionary(value,select, output)
        elif type(value) is list:
            parseJsonList(value, select, output)

def parseJsonList(itemlist, select, output):
           
    for item in itemlist:
        if type(item) is dict:
            parseJsonDictionary(item, select, output)
        elif type(item) is list:
            parseJsonList(item, select, output)
        else:
            if len(itemlist) == 2:
                if itemlist[0] == select:
                    output.append(itemlist[1])
                break

def getArchiveDeployProperty(name, properties, default, parse=False):
    value = default
    
    try:
        if properties:
            value = properties.getProperty(name)
            if value and parse:
                value = Boolean.parseBoolean(value)
    except:
        pass
    
    return value

def extractZip(zip, dest):
    "extract zip archive to dest directory"
    
    logger.info("Begin extracting:" + zip + " --> " +dest)
    mkdir_p(dest)
    zipfile = ZipFile(zip)

    entries = zipfile.entries()
    while entries.hasMoreElements():
        entry = entries.nextElement()

        if entry.isDirectory():
            mkdir_p(os.path.join(dest, entry.name))
        else:
            newFile = File(dest, entry.name)
            mkdir_p(newFile.parent)
            zis = zipfile.getInputStream(entry)
            fos = FileOutputStream(newFile)
            nread = 0
            buffer = ByteBuffer.allocate(1024)
            while True:
                nread = zis.read(buffer.array(), 0, 1024)
                if nread <= 0:
                        break
                fos.write(buffer.array(), 0, nread)

            fos.close()
            zis.close()

    logger.info("End extracting:" + str(zip) + " --> " + str(dest))
     
     
def isUUID(uuid_string):
    valid = False
    try:
        val = UUID(uuid_string)
        valid = True
    except ValueError:
        valid = False

    return valid

def ping(host, port):
    success = False
    s = None
    try:
        s = socket.socket()
        s.connect((host, int(port)))
        success = True
    except:
        type, value, traceback = sys.exc_info()
        logger.fine("ping failed:" + `value`)
    finally:
        if s:
            s.close()
    
    return success
    
def listItem(list, index, useDefault=False):
    item = None
    if list:
        llen = len(list)
        if llen > index:
            item = list[index].strip()
        elif useDefault and llen == 1:
            item = list[0].strip()
    
    return item

def list2str(list):
    content = str(list).strip('[]')
    content =content.replace(",", " ")
    content =content.replace("u'", "")
    content =content.replace("'", "")
    return content

def mkdir_p(path, mode=0700):
    if not os.path.isdir(path):
        logger.info("Creating directory:" + path)
        os.makedirs(path, mode)
        
def copyContainerEnvironment():
    count = runtimeContext.variableCount
    for i in range(0, count, 1):
        rtv = runtimeContext.getVariable(i)
        if rtv.type == "Environment":
            os.environ[rtv.name] = rtv.value
    
    os.unsetenv("LD_LIBRARY_PATH")
    os.unsetenv("LD_PRELOAD")
    
def getVariableValue(name, value=None):
    "get runtime variable value"
    var = runtimeContext.getVariable(name)
    if var != None:
        value = var.value
    
    return value

def doInit(additionalVariables):
    "do init"
    docker = DockerSwarm(additionalVariables)
             
    # save mJMX MBean server as a runtime context variable
    dockerRcv = RuntimeContextVariable("DOCKER_SWARM_OBJECT", docker, RuntimeContextVariable.OBJECT_TYPE)
    runtimeContext.addVariable(dockerRcv)


def doStart():
    docker = getVariableValue("DOCKER_SWARM_OBJECT")
        
    if docker:
        docker.start()
    
def doShutdown():
    try:
        docker = getVariableValue("DOCKER_SWARM_OBJECT")
        
        if docker:
            docker.stop()
    except:
        type, value, traceback = sys.exc_info()
        logger.severe("Unexpected error in DockerSwarm:doShutdown:" + `value`)
    finally:
        proxy.doShutdown()
    
def hasContainerStarted():
    started = False
    try:
        docker = getVariableValue("DOCKER_SWARM_OBJECT")
        
        if docker:
            started = docker.hasStarted()
            if started:
                logger.info("Docker container has started!")
            else:
                logger.info("Docker container starting...")
    except:
        type, value, traceback = sys.exc_info()
        logger.severe("Unexpected error in DockerSwarm:hasContainerStarted:" + `value`)
    
    return started

def cleanupContainer():
    try:
        docker = getVariableValue("DOCKER_SWARM_OBJECT")
        
        if docker:
            docker.cleanup()
    except:
        type, value, traceback = sys.exc_info()
        logger.severe("Unexpected error in DockerSwarm:cleanup:" + `value`)
    finally:
        proxy.cleanupContainer()
            
    
def isContainerRunning():
    running = False
    try:
        docker = getVariableValue("DOCKER_SWARM_OBJECT")
        if docker:
            running = docker.isRunning()
    except:
        type, value, traceback = sys.exc_info()
        logger.severe("Unexpected error in DockerSwarm:isContainerRunning:" + `value`)
    
    return running

def doInstall(info):
    " do install of activation info"

    logger.info("doInstall:Enter")
    try:
        docker = getVariableValue("DOCKER_SWARM_OBJECT")
        if docker:
            docker.installActivationInfo(info)
    except:
        type, value, traceback = sys.exc_info()
        logger.severe("Unexpected error in DockerSwarm:doInstall:" + `value`)
    finally:
        proxy.doInstall(info)
        
    logger.info("doInstall:Exit")
    
def getContainerStartConditionPollPeriod():
    poll = getVariableValue("START_POLL_PERIOD", "10000")
    return int(poll)
    
def getContainerRunningConditionPollPeriod():
    poll = getVariableValue("RUNNING_POLL_PERIOD", "60000")
    return int(poll)


def archiveDeploy(name, locators,properties):
    "archive deploy"

    logger.info("archiveDeploy:Enter")
    docker = getVariableValue("DOCKER_SWARM_OBJECT")
    if docker:
        docker.archiveDeploy(name, locators, properties)
        
    logger.info("archiveDeploy::Exit")
    
def archiveUndeploy(name, properties):
    "archive deploy"

    logger.info("archiveUndeploy:Enter")
    docker = getVariableValue("DOCKER_SWARM_OBJECT")
    if docker:
         docker.archiveUndeploy(name, properties)
  
    logger.info("archiveUndeploy::Exit")
    
def archiveStart(name, properties):
    "archive start"

    docker = getVariableValue("DOCKER_SWARM_OBJECT")
    if docker:
        return docker.archiveStart(name, properties)
    
def archiveDetect():
    "archive detect"

    docker = getVariableValue("DOCKER_SWARM_OBJECT")
    if docker:
        return docker.archiveDetect()
        
def archiveStop(name, id, properties):
    "archive stop"

    logger.info("archiveStart:Enter")
    docker = getVariableValue("DOCKER_SWARM_OBJECT")
    if docker:
        docker.archiveStop(name, id, properties)
        
    logger.info("archiveStop::Exit")


def getStatistic(statName):
    stat = None
    try:
        docker = getVariableValue("DOCKER_SWARM_OBJECT")
        if docker:
            stat = docker.getStat(statName)
    except:
        type, value, traceback = sys.exc_info()
        logger.severe("Unexpected error in DockerSwarm:getStatistic:" + `value`)
    return stat

