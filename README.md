# FlowController

<img width=600 src="https://github.com/Snackman8/FlowController/raw/main/docs/FlowControllerSimpleExample.png">

<img width=600 src="https://github.com/Snackman8/FlowController/raw/main/docs/FlowControllerSignalTestExample.png">

## Install on an Ubuntu Linux System
Update the packages in the package manager before installing
```
sudo apt-get update
sudo apt-get install python3-pip
```

The FlowController project depends on two other projects, please install these projects first
```
https://github.com/Snackman8/SimpleMessageQueue
^ Make sure to install the systemd services for SimpleMessageQueue or Flowcontroller will not work
```

Clone the project into your home directory
```
cd ~
git clone https://github.com/Snackman8/FlowController
```

Install the FlowController packge

The FlowcControllerWebApp and two sample flows will be installed

Two sample flow controllers are provided
* FlowControllerSimpleExample
* FlowControllerSignalTestExample

```
cd ~/FlowController/deployment
sudo ./install_with_pipx_systemd.sh
```

To view the webapp, open the url below
```
http://localhost:7010
```

Use the sample Flows provided at ~/FlowController/sample_cfgs_and_jobs as the basis for your own flows
```
~/FlowController/sample_cfgs_and_jobs
```

To check the status of the service, stop, or start use the commands below
```
sudo systemctl status FlowControllerWebApp
sudo systemctl stop FlowControllerWebApp
sudo systemctl start FlowControllerWebApp

sudo systemctl status FlowControllerSimpleExample
sudo systemctl stop FlowControllerSimpleExample
sudo systemctl start FlowControllerSimpleExample

sudo systemctl status FlowControllerSignalTestExample
sudo systemctl stop FlowControllerSignalTestExample
sudo systemctl start FlowControllerSignalTestExample

```

To view the logs for the service
```
sudo journalctl -u FlowControllerSimpleExample
sudo journalctl -u FlowControllerSignalTestExample
```
