#!/bin/bash

# ----------------------------------------
#   General Configuration
# ----------------------------------------
APP_NAME=Flowcontroller
SERVICE_NAME=FlowControllerWebApp.service
SERVICE_NAME_EXAMPLE1=FlowControllerSimpleExample.service
SERVICE_NAME_EXAMPLE2=FlowControllerSignalTestExample.service
# location where all pipx apps are installed
PIPX_HOME_DIR="/usr/local/pipx"


# ----------------------------------------
#   PipX Configuration
# ----------------------------------------
# Check if pipx is installed
if ! command -v pipx &> /dev/null; then
    echo "Error: pipx is not installed."
    exit 1
fi

# Find the full path of the pipx binary
PIPX_BIN=$(command -v pipx)

# Extract the directory containing pipx
PIPX_BIN_DIR=$(dirname "$PIPX_BIN")

# Check if we successfully got the directory
if [[ -z "$PIPX_BIN_DIR" ]]; then
    echo "Error: Could not determine pipx binary directory."
    exit 1
fi


# ----------------------------------------
#   SimpleMessageQueue
# ----------------------------------------
if ! systemctl is-active --quiet "SimpleMessageQueue"; then
    echo "SimpleMessageQueue service is NOT running.  Check to make sure SimpleMessageQueue is installed and service is working.  Exiting..."
    exit 1
fi


# ----------------------------------------
#   Create User
# ----------------------------------------
sudo useradd -r -s /bin/false FlowController


# ----------------------------------------
#   Uninstall
# ----------------------------------------
if [[ "$1" == "--uninstall" ]]; then
    echo "Uninstalling ${APP_NAME}..."

    echo "Stopping and disabling systemd service..."
    sudo systemctl stop $SERVICE_NAME
    sudo systemctl disable $SERVICE_NAME
    sudo systemctl stop $SERVICE_NAME_EXAMPLE1
    sudo systemctl disable $SERVICE_NAME_EXAMPLE1
    sudo systemctl stop $SERVICE_NAME_EXAMPLE2
    sudo systemctl disable $SERVICE_NAME_EXAMPLE2

    echo "Removing systemd service file..."
    sudo rm -f /etc/systemd/system/$SERVICE_NAME
    sudo rm -f /etc/systemd/system/$SERVICE_NAME_EXAMPLE1
    sudo rm -f /etc/systemd/system/$SERVICE_NAME_EXAMPLE2
    sudo systemctl daemon-reload

    echo "Uninstalling the app using pipx..."
    sudo PIPX_HOME=$PIPX_HOME_DIR PIPX_BIN_DIR=$PIPX_BIN_DIR ${PIPX_BIN_DIR}/pipx uninstall ${APP_NAME}

    echo "Uninstallation complete."
    exit 0
fi


# ----------------------------------------
#   Install
# ----------------------------------------
echo "Installing ${APP_NAME} using pipx..."
sudo PIPX_HOME=$PIPX_HOME_DIR PIPX_BIN_DIR=$PIPX_BIN_DIR ${PIPX_BIN_DIR}/pipx install .. --include-deps

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
sudo cp -r ../sample_cfgs_and_jobs/* /var/lib/FlowController/sample_configs_and_jobs
sudo chown -R FlowController:FlowController /var/lib/FlowController/sample_configs_and_jobs

echo "Copying systemd service file..."
sudo cp $SERVICE_NAME /etc/systemd/system/
sudo cp $SERVICE_NAME_EXAMPLE1 /etc/systemd/system/
sudo cp $SERVICE_NAME_EXAMPLE2 /etc/systemd/system/

echo "Setting correct permissions for the service file..."
sudo chmod 644 /etc/systemd/system/$SERVICE_NAME
sudo chmod 644 /etc/systemd/system/$SERVICE_NAME_EXAMPLE1
sudo chmod 644 /etc/systemd/system/$SERVICE_NAME_EXAMPLE2

echo "Reloading systemd daemon..."
sudo systemctl daemon-reload

echo "Enabling and starting the service..."
sudo systemctl enable $SERVICE_NAME
sudo systemctl restart $SERVICE_NAME
sudo systemctl enable $SERVICE_NAME_EXAMPLE1
sudo systemctl restart $SERVICE_NAME_EXAMPLE1
sudo systemctl enable $SERVICE_NAME_EXAMPLE2
sudo systemctl restart $SERVICE_NAME_EXAMPLE2

echo "Installation of ${APP_NAME} complete."
