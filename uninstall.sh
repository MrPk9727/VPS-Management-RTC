#!/bin/bash

# RathamCloud VPS Bot Uninstaller
# Target: Ubuntu/Debian

set -e

echo "🗑️ Starting RathamCloud Bot Uninstallation..."

# 1. Stop and Disable Service
echo "🛑 Stopping and disabling RathamCloud service..."
sudo systemctl stop rathamcloud || true
sudo systemctl disable rathamcloud || true

# 2. Remove Systemd Service File
echo "📄 Removing systemd service file..."
sudo rm -f /etc/systemd/system/rathamcloud.service
sudo systemctl daemon-reload

# 3. Remove RTC Wrapper
echo "🔧 Removing RTC wrapper..."
sudo rm -f /usr/local/bin/RTC

# 4. Remove Installation Directory
INSTALL_DIR="/opt/rathamcloud-bot"
if [ -d "$INSTALL_DIR" ]; then
    echo "📂 Installation directory found at $INSTALL_DIR"
    read -p "⚠️ Do you want to delete all bot files, including VPS data and logs? (y/N): " confirm
    if [[ $confirm == [yY] || $confirm == [yY][eE][sS] ]]; then
        sudo rm -rf "$INSTALL_DIR"
        echo "✅ Bot files and data removed."
    else
        echo "ℹ️ Skipping directory removal. You can delete it manually with: sudo rm -rf $INSTALL_DIR"
    fi
fi

# 5. Optional LXD removal
read -p "❓ Do you also want to uninstall LXD? (y/N): " remove_lxd
if [[ $remove_lxd == [yY] || $remove_lxd == [yY][eE][sS] ]]; then
    echo "📦 Removing LXD via snap..."
    sudo snap remove lxd
    echo "✅ LXD removed."
fi

echo "✨ Uninstallation process finished!"