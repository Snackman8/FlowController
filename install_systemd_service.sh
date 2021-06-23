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
sudo cp ./FlowControllerSampleConfig.service /etc/systemd/system/
sudo chown root:root /etc/systemd/system/FlowControllerSampleConfig.service
sudo chmod 644 /etc/systemd/system/FlowControllerSampleConfig.service
sudo systemctl daemon-reload
sudo systemctl enable FlowControllerSampleConfig
sudo systemctl restart FlowControllerSampleConfig

sudo cp ./FlowControllerWebApp.service /etc/systemd/system/
sudo chown root:root /etc/systemd/system/FlowControllerWebApp.service
sudo chmod 644 /etc/systemd/system/FlowControllerWebApp.service
sudo systemctl daemon-reload
sudo systemctl enable FlowControllerWebApp
sudo systemctl restart FlowControllerWebApp
