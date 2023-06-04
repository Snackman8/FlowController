#!/bin/sh

# add user
sudo useradd -r -s /bin/false FlowController

# make directories
sudo mkdir -p /var/log/FlowController/joblogs
sudo chown FlowController:FlowController /var/log/FlowController/joblogs
sudo mkdir -p /var/local/FlowController/ledgers
sudo chown FlowController:FlowController /var/local/FlowController/ledgers
sudo mkdir -p /var/lib/FlowController/sample_configs_and_jobs
sudo chown FlowController:FlowController /var/lib/FlowController/sample_configs_and_jobs
sudo mkdir -p /var/lib/FlowController/configs
sudo chown FlowController:FlowController /var/lib/FlowController/configs

# copy sample configs
sudo cp -r sample_cfgs_and_jobs/* /var/lib/FlowController/sample_configs_and_jobs
sudo chown -R FlowController:FlowController /var/lib/FlowController/sample_configs_and_jobs

# install to systemd
sudo cp ./FlowControllerSimpleExample.service /etc/systemd/system/
sudo chown root:root /etc/systemd/system/FlowControllerSimpleExample.service
sudo chmod 644 /etc/systemd/system/FlowControllerSimpleExample.service
sudo systemctl daemon-reload
sudo systemctl enable FlowControllerSimpleExample.service
sudo systemctl restart FlowControllerSimpleExample.service

sudo cp ./FlowControllerSignalTestExample.service /etc/systemd/system/
sudo chown root:root /etc/systemd/system/FlowControllerSignalTestExample.service
sudo chmod 644 /etc/systemd/system/FlowControllerSignalTestExample.service
sudo systemctl daemon-reload
sudo systemctl enable FlowControllerSignalTestExample.service
sudo systemctl restart FlowControllerSignalTestExample.service

sudo cp ./FlowControllerWebApp.service /etc/systemd/system/
sudo chown root:root /etc/systemd/system/FlowControllerWebApp.service
sudo chmod 644 /etc/systemd/system/FlowControllerWebApp.service
sudo systemctl daemon-reload
sudo systemctl enable FlowControllerWebApp
sudo systemctl restart FlowControllerWebApp
