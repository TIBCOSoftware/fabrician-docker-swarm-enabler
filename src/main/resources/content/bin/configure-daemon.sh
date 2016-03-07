#!/bin/sh

exitCode=0
cat "$DOCKER_CONFIG_PATH"

if grep -q "cluster-store=$CLUSTER_STORE" "$DOCKER_CONFIG_PATH"; then
	echo "$DOCKER_CONFIG_PATH is already configured with current cluster-store"
elif ! grep -q "cluster-store=" "$DOCKER_CONFIG_PATH"; then
	echo "Adding --cluster-store to $DOCKER_CONFIG_PATH"
	sed "s/OPTIONS='/OPTIONS='--cluster-store=$CLUSTER_STORE  --cluster-advertise=$CLUSTER_ADVERTISE /1"  "$DOCKER_CONFIG_PATH"  > /tmp/docker.config
	if [ $? -eq 0 ]; then
		sudo cp  /tmp/docker.config $DOCKER_CONFIG_PATH
		sudo rm /tmp/docker.config

		echo "sudo systemctl stop docker"
		sudo systemctl stop docker

		sleep 5

		echo "sudo systemctl start docker"
		sudo systemctl start docker
	else
		exitCode=1
	fi

elif [ "$FORCE_RECONFIG" = "true" ]; then
	echo "Force reconfiguration of main docker daemon"
	sed "s/--cluster-store=\([a-zA-Z0-9\/:\/\.]\)*//1"  "$DOCKER_CONFIG_PATH" > /tmp/docker.config.1
	sed "s/--cluster-advertise=\([0-9:\.]\)*//1"  /tmp/docker.config.1 > /tmp/docker.config.2
	sed "s/OPTIONS='/OPTIONS='--cluster-store=$CLUSTER_STORE  --cluster-advertise=$CLUSTER_ADVERTISE /1"  /tmp/docker.config.2 > /tmp/docker.config.3

	if [ $? -eq 0 ]; then
		sudo cp  /tmp/docker.config.3 $DOCKER_CONFIG_PATH
		sudo rm /tmp/docker.config.*

		echo "sudo systemctl stop docker"
		sudo systemctl stop docker
		
		sleep 5
		echo "sudo systemctl start docker"	
		sudo systemctl start docker
	else
		exitCode=1
	fi
else
	echo "Docker daemon is using a different cluster-store and FORCE_RECONFIG is not set to 'true'"
	exitCode=1
fi


cat "$DOCKER_CONFIG_PATH"
exit $exitCode