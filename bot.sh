#!/bin/bash

# RathamCloud VPS Bot Installer
# Target: Ubuntu/Debian

set -e

echo "🚀 Starting RathamCloud Bot Installation..."

# 1. Update System
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv git curl

# 2. Setup Directory
INSTALL_DIR="/opt/rathamcloud-bot"
sudo mkdir -p $INSTALL_DIR
sudo chown $USER:$USER $INSTALL_DIR

# 3. Clone Repository
if [ -d "$INSTALL_DIR/.git" ]; then
    echo "📂 Repository already exists, pulling latest changes..."
    cd $INSTALL_DIR
    git pull
else
    echo "📥 Cloning repository..."
    git clone https://github.com/MrPk9727/VPS-Management-RTC.git $INSTALL_DIR
    cd $INSTALL_DIR
fi

# 4. Setup Virtual Environment
echo "🐍 Setting up Python virtual environment..."
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 5. Configuration
echo "⚙️ Configuration Setup"
read -p "Enter Discord Bot Token: " DISCORD_TOKEN
read -p "Enter Main Admin Discord ID: " ADMIN_ID

# Create a local environment file for the service to read
cat <<EOF > $INSTALL_DIR/.env
DISCORD_TOKEN=$DISCORD_TOKEN
MAIN_ADMIN_ID=$ADMIN_ID
VPS_USER_ROLE_ID=$ADMIN_ID
DEFAULT_STORAGE_POOL=default
EOF

# 6. Setup Systemd Service
echo "🛠️ Configuring Systemd Service..."
sudo cp rathamcloud.service /etc/systemd/system/rathamcloud.service

# Update the service file to point to the correct environment file if needed
# or ensure the service file uses the variables correctly.

sudo systemctl daemon-reload
sudo systemctl enable rathamcloud
sudo systemctl restart rathamcloud

echo "✅ Installation Complete!"
echo "📊 Check logs with: journalctl -u rathamcloud -f"
echo "🤖 Bot status: $(systemctl is-active rathamcloud)"