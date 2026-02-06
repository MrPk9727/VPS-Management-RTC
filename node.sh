#!/bin/bash

# RathamCloud Node Setup Script
# This script installs Node.js on a new VPS instance

set -e

NODE_VERSION=20

echo "🌐 Setting up Node.js v$NODE_VERSION on this VPS..."

# 1. Update and install prerequisites
sudo apt update
sudo apt install -y curl build-essential

# 2. Install NodeSource Repository
echo "📥 Downloading NodeSource setup script..."
curl -fsSL https://deb.nodesource.com/setup_${NODE_VERSION}.x | sudo -E bash -

# 3. Install Node.js
sudo apt install -y nodejs

echo "✅ Node.js installation complete!"
echo "📦 Node version: $(node -v)"
echo "📦 NPM version:  $(npm -v)"