#!/bin/bash

# RathamCloud VPS Bot Installer
# Target: Ubuntu/Debian

set -e

echo "🚀 Starting RathamCloud Bot Installation..."

ORIGINAL_DIR=$(pwd)
# Ensure snap binaries are in the path for this session
export PATH=$PATH:/snap/bin

# 1. Update System
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv git curl snapd lxc lxc-utils bridge-utils uidmap

# Ensure snapd is enabled and running
sudo systemctl enable --now snapd.socket

# Debian compatibility: Create symlink for snap if it doesn't exist
[ -d /var/lib/snapd/snap ] && [ ! -L /snap ] && sudo ln -s /var/lib/snapd/snap /snap

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

# 3.5 Install LXD and Create RTC Wrapper
echo "📦 Checking for LXD/LXC..."
# Ensure snapd is fully initialized before proceeding
echo "⏳ Waiting for snap system to be ready..."
sudo snap wait system seed.loaded || true

if ! snap list lxd &> /dev/null; then
    echo "📥 Installing LXD via snap..."
    sudo snap install lxd
fi

# Add current user to lxd group
sudo usermod -aG lxd $USER || true
sudo usermod -aG kvm $USER || true

# Ensure LXD is initialized and storage pool exists
echo "⚙️ Initializing LXD and Storage..."
# Explicitly start LXD to ensure the socket is created
sudo snap start lxd

# Wait for LXD socket to be available
MAX_RETRIES=30
RETRY_COUNT=0
while [ ! -e /var/snap/lxd/common/lxd/unix.socket ]; do
    if [ $RETRY_COUNT -ge $MAX_RETRIES ]; then
        echo "❌ Error: LXD socket not found after 60 seconds. Checking service status..."
        sudo snap services lxd
        exit 1
    fi
    echo "Waiting for LXD socket ($RETRY_COUNT/$MAX_RETRIES)..."
    sleep 2
    ((RETRY_COUNT++))
done

sudo lxd init --auto || true

if ! sudo lxc storage show default &> /dev/null; then
    echo "🔨 Creating 'default' storage pool..."
    sudo lxc storage create default dir || echo "⚠️ Storage pool creation failed or already exists."
fi

# Pre-pull the default image to prevent timeouts during first VPS creation
echo "🚚 Pre-pulling Ubuntu 22.04 image..."
sudo lxc image copy images:ubuntu/22.04 local: --alias ubuntu:22.04 --quiet || true

echo "🔧 Creating RTC wrapper for LXC..."
# Find the absolute path to lxc to avoid wrapper loops
REAL_LXC=$(which lxc || echo "/snap/bin/lxc")

cat <<EOF | sudo tee /usr/local/bin/RTC > /dev/null
#!/bin/bash
# RathamCloud RTC Wrapper for LXC (Direct Path)
$REAL_LXC "\$@"
EOF

sudo chmod +x /usr/local/bin/RTC
echo "✅ RTC command installed to /usr/local/bin/RTC"

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
