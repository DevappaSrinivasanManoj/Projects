# Countdown Timer - Installation and Usage Guide

## Overview

The Countdown Timer is a simple, user-friendly application that allows you to set and track countdown timers. It features a clean interface with hours, minutes, and seconds inputs, and provides visual and audio notifications when the timer completes.

## Features

- Set countdown times with hours, minutes, and seconds
- Start, pause, and reset functionality
- Visual timer display with large, easy-to-read font
- Status indicator showing the current timer state
- Visual and audio alerts when timer completes
- Desktop notifications (if supported by your system)
- Keyboard shortcuts for common actions

## System Requirements

- Linux operating system
- Python 3.6 or higher
- Tkinter (python3-tk package)
- Optional: plyer library for enhanced notifications

## Installation

### Option 1: Using the Installation Script (Recommended)

1. Extract the countdown_timer.zip file to a location of your choice:
   ```
   unzip countdown_timer.zip -d ~/countdown_timer
   ```

2. Navigate to the extracted directory:
   ```
   cd ~/countdown_timer
   ```

3. Run the installation script with sudo privileges:
   ```
   sudo ./install.sh
   ```

4. The application will be installed system-wide and will be available in your applications menu.

### Option 2: Running Without Installation

If you prefer not to install the application system-wide, you can run it directly:

1. Extract the countdown_timer.zip file:
   ```
   unzip countdown_timer.zip -d ~/countdown_timer
   ```

2. Navigate to the extracted directory:
   ```
   cd ~/countdown_timer
   ```

3. Make the script executable:
   ```
   chmod +x countdown_timer.py
   ```

4. Run the application:
   ```
   python3 countdown_timer.py
   ```

## Usage

### Starting the Application

- If installed system-wide, find "Countdown Timer" in your applications menu
- Alternatively, run `python3 /usr/local/bin/countdown_timer.py` in a terminal

### Setting a Timer

1. Use the spinbox controls to set hours, minutes, and seconds
2. Click the "Start" button to begin the countdown
3. The timer display will show the remaining time in HH:MM:SS format

### Controlling the Timer

- **Start**: Begin or resume the countdown
- **Pause**: Temporarily stop the countdown
- **Reset**: Stop the countdown and reset to initial state

### Keyboard Shortcuts

- **Space**: Start/Pause the timer
- **R**: Reset the timer
- **Esc**: Quit the application

### Timer Completion

When the timer reaches zero:
- The display will flash red and white
- A system beep will sound
- A desktop notification will appear (if supported)
- The status will change to "Finished!"

## Uninstallation

If you installed the application using the installation script, you can uninstall it using the provided uninstall script:

```
sudo ./uninstall.sh
```

## Troubleshooting

### Missing Dependencies

If you encounter errors about missing modules:

1. Ensure Python 3 is installed:
   ```
   python3 --version
   ```

2. Install Tkinter if missing:
   ```
   sudo apt-get install python3-tk
   ```

3. Install plyer for enhanced notifications (optional):
   ```
   pip3 install plyer
   ```

### Display Issues

If the application window appears too small or elements are misaligned:
- The window is resizable; try adjusting its size
- Ensure your display settings are set to a standard resolution

## Support

For issues or questions, please refer to the documentation or contact the developer.
