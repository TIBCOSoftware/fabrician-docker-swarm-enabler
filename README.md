### Docker Swarm Enabler User Guide

### Introduction
--------------------------------------
Docker Swarm Enabler is used in conjunction with TIBCO Silver Fabric to create and manage a Docker Swarm cluster.

This Enabler was developed and tested using Docker version 1.10.1. However, it is expected to  work  with 
other compatible versions of Docker. This Enabler supports the use of  Docker Compose with the Docker Swarm cluster managed by this Enabler. 
This Enabler has only been tested with Docker Compose version 2.0. 

### Solution Architecture
---------------------------------------------------

A diagram of the solution architecture implemented by this Enabler is shown below.

![Alt text](images/solution-architecture.png "Solution Architecture")

This Enabler creates and manages a multiple host Docker Swarm cluster. Docker Swarm requires the use of a *cluster key store*, therefore, this Enabler 
requires a cluster key store. For production use, a cluster key store is expected to be running
in a highly available configuration. For development use, the cluster key store may comprise of a single node. 

The solution architecture implemented by this Enabler requires a *discovery service* so that the Docker services  running in the Docker Swarm cluster can be automatically registered and unregistered  
with the discovery service. This allows easy discovery of the services running in the various Docker containers on the Docker Swarm cluster.

*Consul Enabler* can be used in conjunction with this enabler to provide a highly-available cluster key store and 
discovery service. Alternatively, *etcd Enabler* can be used for cluster key store and *Consul Enabler* can be
used for discovery service.

At a point in time, this Enabler assumes that a given host is part of a *single* Docker Swarm cluster.
For each host in the Docker Swarm cluster, this Enabler requires two different Docker daemons running on the host:

1. Bootstrap Docker Daemon
2. Main Docker Daemon

The Bootstrap Docker Daemon is used to run following Docker containers:

1.  `swarm join` container that joins the given host to the given Swarm cluster
2.  `swarm manage` container that creates a Swarm manager replica on the host
3.  `registrator` container that monitors the Main Docker daemon socket for published ports and registers and unregisters  services with the discovery service, such as Consul

The `swarm` bootstrap containers use the cluster key store and the `registrator` key store uses the discovery service. 

At the time of the Silver Fabric Component startup, if any of the Bootstrap Docker containers listed above is already running
but is using a cluster key store other than the current cluster key store, and if `FORCE_RECONFIG` is set to `true` in the
Silver Fabric Component, the running container is forcibly stopped by this Enabler and a new container is created and started, otherwise, a startup
error is raised.

All the containers using the Bootstrap Docker Daemon use `host` networking.

At the time of the Silver Fabric Component startup, if the Main Docker Daemon is not configured to use any cluster key store, 
this Enabler  reconfigures the Main Docker Daemon to use the current cluster key store and restarts the Main Docker Daemon. 
The Main Docker Daemon reconfiguration and restart is done via a  shell script, [`configure-dameon.sh`] (src/main/resources/content/bin/configure-daemon.sh).
This shell script may need to be customized depending on how Docker has been enabled on a host.

At the time of the Silver Fabric Component startup, if the Main Docker Daemon on a host is already 
using a cluster key store other than the current cluster key store, and if the Silver Fabric Component is configured with `FORCE_RECONFIG` set to '`true`, 
the Main Docker Daemon is automatically reconfigured by this Enabler to point to current cluster key store and restarted, otherwise,
 a startup error is raised. `FORCE_RECONFIG`  default value is set to `true`, which is suitable for development use, but not recommended for production use..

In the Silver Fabric Component using this Enabler, if `DETACH_SWARM_ON_SHUTDOWN` variable is set to `true`,
 the Docker Swarm cluster is not effected when the Silver Fabric Component is gracefully or ungracefully shutdown. 
 This configuration is recommended for production use. The default value of `DETACH_SWARM_ON_SHUTDOWN` is `false`, which is suitable for 
 development use.
 
This Enabler, by default,  automatically creates a Docker **overlay** network named `swarm_network`. See [Docker Multi-host Networking] for details on *overlay* networks.]

### Building the Enabler
--------------------------------------
This Enabler project builds a `Silver Fabric Enabler Grid Library`. The Enabler Grid Library can be built using Maven. 
The Grid Library file is created under target directory created by Maven.

### Installing the Enabler
--------------------------------------
Installation of the `Docker Swarm Enabler` is done by copying the `Docker Swarm Enabler Grid Library` from the `target` 
project folder to the `SF_HOME/webapps/livecluster/deploy/resources/gridlib` folder on the Silver Fabric Broker. 

### Enabling Docker on the Silver Fabric Engine host
--------------------------------------------------------------------
Silver Fabric Engine host needs to be `Docker enabled` before it can run Silver Fabric Components that use this Enabler. 
The main steps for Docker enabling a Silver Fabric Engine host are as follows:

1. Install `Docker 1.10.0` or later runtime on Silver Fabric Engine host
    * See [Install Docker] for details
2. Configure `Password-less sudo` or non-root Docker access for the OS user running Silver Fabric Engine so the OS user running Silver Fabric Engine is able to run Docker CLI commands without password prompting:
    * If sudo is not required, the password-less requirement still holds
3. Configure `Docker Remote API` to run on a TCP port
    * See [Configure Docker Remote API] for details
4. Configure `Docker Daemon storage-driver Option`
    * Configure Docker dameon `storage-driver` option to use a non-looback driver
    * See [Docker Daemon reference] for details
    * See [Docker Storage blog] for additional details
5. Configure `Docker Daemon selinux-enabled Option`
    * Configure Docker dameon selinux-enabled appropriately. During the development and testing of this Enabler, `--selinux-enabled=false` options was used. 
    * See [Docker and SELinux] for additional information

After you have completed the steps noted above, restart Silver Fabric Engine Daemon so that it will register the host with Silver Fabric Broker as `Docker Enabled`. 
It is recommended that you setup and enable `systemd` services for Silver Fabric Engine Daemon and Docker Daemon 
so both these services automatically startup when the host operating system is booted up.

### Configuring Main Docker Daemon on the Silver Fabric Engine host
------------------------------------------------------------------------------------------

Create a file [`/etc/sysconfig/docker`](scripts/docker) and specify Docker OPTIONS in this file.

Note the name of the default bridge in the Docker OPTIONS is set to `sfdocker0` and not `docker0`. The reason for this is that the default `docker0` name interferes
with Silver Fabric Engine Daemon startup, which, by default, is configured to use the first network interface available in the alphabetical order. 
To avoid this interference, one solution is to create a network bridge named `sfdocker0` using following commands (tested
on Centos 7):

* sudo brctl addbr sfdocker0
* sudo ip addr add 172.17.0.1/16  dev sfdocker0
* sudo ip link set dev sfdocker0 up

To make this bridge persistent on reboot, create a file named [`/etc//sysconfig/network-scripts/ifcfg-sfdocker0`] (scripts/ifcfg-sfdocker0)

In [`/usr/lib/systemd/system/docker.service`](scripts/docker.service)  file add  `/etc/sysconfig/docker` as the `EnviornmentFile`.
Enable Main Docker daemon service using the command shown below:

* sudo systemctl enable docker.service

### Enabling Bootstrap Docker on the Silver Fabric Engine host
--------------------------------------------------------------------------------
The steps for enabling the Bootstrap Docker daemon are described below.

1. Create [`/etc/sysconfig/docker-bootstrap`](scripts/docker-bootstrap) file to specify Bootstrap Docker daemon OPTIONS 
2. Create [`/usr/lib/systemd/system/docker-bootstrap.socket`](scripts/docker-bootstrap.socket).
3. Create [`/usr/lib/systemd/system/docker-bootstrap.service`](scripts/docker-bootstrap.service).

Enable Bootstrap Docker Daemon `systemd` service using the command shown below:

* sudo systemctl enable docker-bootstrap.service

### Docker Swarm Feature Support
---------------------------------------------------
This Docker Enabler does not restrict any native Docker Swarm  features.

### Configuring Silver Fabric Engine Resource Preference
-------------------------------------------------------------------------

Since not all Silver Fabric Engine hosts managed by a single Silver Fabric Broker may be Docker enabled, a [Resource Preference rule] using `Docker Enabled` engine property must be configured in any Silver Fabric Component using this Enabler. This enables Silver Fabric Broker to allocate Components that are based on this Enabler exclusively to Docker enabled hosts. 
Failure to use the suggested [Resource Preference rule] may result in the Components to be allocated to hosts that are not Docker enabled, 
resulting in Silver Fabric Component activation failure. In addition, you may optionally use the `Docker VersionInfo` engine property to 
select Docker enabled hosts with a specific Docker version.

### Silver Fabric Enabler Features
--------------------------------------------
This Enabler supports following Silver Fabric Enabler features:

* Application Logging Support
* Archive Management Support

The archive management feature supports  `deploy`, `undeploy`, `start` and `stop` of Docker Compose project Zip archives, 
using Silver Fabric continuous deployment (CD) REST API. See [Silver Fabric Cloud Administration Guide] for details on Silver Fabric CD REST API.

Silver Fabric CD target criteria must be specified as follows:

* `ActivationInfoProperty(DockerSwarmRole)=primary`
* `ActivationInfoProperty(DockerSwarmUUID)=<Swarm cluster UUID configured in Silver Fabric Component>`

Silver Fabric CD deployment properties are shown below:

* project-name=*name of project, e.g. webappV2*
* remove-images=*true or false*
* remove-volumes=*true or false*

The project Zip archive must contain a project folder with a docker-compose.yml file. 
In addition to the docker compose file, the project folder must contain any relevant build files.  
Here is an [example compose project](compose/projects/webapp). To deploy this project via Silver Fabric CD REST API, 
you must first create a Zip archive by compressing the `webapp` project folder to create a Zip archive `webapp.zip`, 
with `webapp` as the top-level folder within the Zip archive.

### Silver Fabric Enabler Statistics
-------------------------------------------

Components using this Enabler can track following Docker container statistics for each Swarm node:

| Docker Container Statistic|Description|
|---------|-----------|
|`Docker CPU Usage %`|Docker CPU usage percentage|
|`Docker Memory Usage %`|Docker memory usage percentage|
|`Docker Memory Usage (MB)`|Docker memory usage (MB)|
|`Docker Memory Limit (MB)`|Docker Memory Limit (MB)|
|`Docker Network Input (MB)`|Docker network input (MB)|
|`Docker Network Output (MB)`|Docker network output (MB)|
|`Docker Block Output (MB)`|Docker block device output (MB)|
|`Docker Block Input (MB)`|Docker block device input (MB)|

The Enabler statistics contain a sum of the statistics from all the Docker containers managed by the Main Docker Daemon
on a given Swarm node. 

### Silver Fabric Runtime Context Variables
--------------------------------------------------------

The Enabler provides following Silver Fabric runtime variables.

### Runtime Variable List:
--------------------------------

|Variable Name|Default Value|Type|Description|Export|Auto Increment|
|---|---|---|---|---|---|
|`DOCKER_SWARM_UUID`|| String| Unique UUID for this Docker Swarm. |false|None|
|`DOCKER_BOOTSTRAP_SOCK`|unix:///var/run/docker-bootstrap.sock| String| Docker daemon socket for running Swarm containers is required: This is not the Main Docker Daemon. |false|None|
|`DISCOVERY_KEY_STORE`|| String| Discovery key store used by Swarm cluster and Docker overlay network |false|None|
|`DISCOVERY_SERVICE`|| String| Discovery service for registering and unregistering Docker services |false|None|
|`DETACH_SWARM_ON_SHUTDOWN`|false| String| Whether to detach Docker Swarm on shutdown of component. If true, Swarm cluster is not stopped when component is shutdown. |false|None|
|`FORCE_RECONFIG`|true| Environment| Force reconfiguration and restart of main docker daemon if it is not using current cluster store |false|None|
|`DOCKER_COMPOSE_PATH`|/usr/local/bin/docker-compose| String| Docker compose executable path on host Docker services |false|None|
|`DOCKER_CONFIG_PATH`|/usr/local/bin/docker-compose| String| Docker daemon config file containing OPTIONS='<daemon options>' |false|None|
|`DOCKER_SWARM_STRATEGY`|spread| String| Docker swarm strategy: 'spread', 'binpack' or 'random' |false|None|
|`DOCKER_SWARM_NETWORK`|spread| String| Docker swarm network using overlay driver |false|None|
|`COMPOSE_DEPLOY_DIRECTORY`|| String| Compose deploy directory. Must be a shared NFS directory |false|None|
|`DOCKER_PORT`|2375| String| Main Docker daemon TCP port |false|None|
|`MANAGE_PORT`|4000| String| Swarm manage replica TCP port |false|None|
|`USE_SUDO`|false| String| Run Docker with 'sudo'. The 'sudo' command must not prompt for password! |false|None|

### Component Examples
------------------------
Below is an example Docker Swarm cluster Component and associated Stack. Note the use of imported variable `${CONSUL_ADDRESS}`, which is imported
from the Consul Component due to the dependency rules expressed in the Stack. In this example, it is assumed the 
Consul Component is defined separately and run in its own Stack. Typically, the Consul key store would be run as a 
separate Silver Fabric utility Component in its own stack that is used by other Stacks, as is the case in the example Stack below.

* [Docker Swarm Component](images/docker-swarm-component.png)
* [Docker Swarm Stack](images/docker-swarm-stack.png)

[Install Docker]:<https://docs.docker.com/installation/>
[Docker Multi-host Networking]:<https://docs.docker.com/engine/userguide/networking/get-started-overlay/>
[Configure Docker Remote API]:http://www.virtuallyghetto.com/2014/07/quick-tip-how-to-enable-docker-remote-api.html
[Docker and SELinux]:<http://www.projectatomic.io/docs/docker-and-selinux/>
[Resource Preference rule]:<https://github.com/fabrician/docker-enabler/blob/master/src/main/resources/images/docker_resource_preference.gif>
[Docker Daemon reference]:<https://docs.docker.com/engine/reference/commandline/daemon/>
[Docker Storage blog]:<http://www.projectatomic.io/blog/2015/06/notes-on-fedora-centos-and-docker-storage-drivers/>
[Silver Fabric Cloud Administration Guide]:<https://docs.tibco.com/pub/silver_fabric/5.7.1/doc/pdf/TIB_silver_fabric_5.7.1_cloud_administration.pdf>