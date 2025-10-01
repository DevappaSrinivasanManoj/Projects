#!/bin/bash

# Check if script is run with sudo
if [ "$EUID" -ne 0 ]; then
  echo "Please run as root or with sudo"
  exit 1
fi

# Install dependencies
echo "Installing dependencies..."
apt-get update
apt-get install -y python3 python3-tk

# Try to install plyer for notifications (optional)
pip3 install plyer || echo "Plyer installation failed, notifications may not work"

# Create directories
echo "Creating application directories..."
mkdir -p /usr/local/bin
mkdir -p /usr/local/share/countdown_timer
mkdir -p /usr/share/applications

# Copy files
echo "Installing application files..."
cp countdown_timer.py /usr/local/bin/
cp timer_icon.xbm /usr/local/share/countdown_timer/
cp countdown_timer.desktop /usr/share/applications/

# Make executable
chmod +x /usr/local/bin/countdown_timer.py

echo "Installation complete!"
echo "You can now launch the Countdown Timer from your applications menu"
echo "or by running 'python3 /usr/local/bin/countdown_timer.py' in a terminal."
