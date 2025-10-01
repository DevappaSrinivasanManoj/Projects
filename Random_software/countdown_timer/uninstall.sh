#!/bin/bash

# Check if script is run with sudo
if [ "$EUID" -ne 0 ]; then
  echo "Please run as root or with sudo"
  exit 1
fi

# Remove application files
echo "Removing application files..."
rm -f /usr/local/bin/countdown_timer.py
rm -f /usr/local/share/countdown_timer/timer_icon.xbm
rm -f /usr/share/applications/countdown_timer.desktop

# Remove directories if empty
rmdir --ignore-fail-on-non-empty /usr/local/share/countdown_timer

echo "Uninstallation complete!"
