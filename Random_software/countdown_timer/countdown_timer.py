#!/usr/bin/env python3

"""
Countdown Timer Application
A simple countdown timer with a graphical user interface built using Tkinter.
"""

import tkinter as tk
from tkinter import ttk
import time
import os
import platform

class CountdownTimer:
    def __init__(self, root):
        self.root = root
        self.root.title("Countdown Timer")
        self.root.geometry("400x300")
        self.root.configure(bg="#f0f0f0")
        self.root.resizable(True, True)
        self.root.minsize(350, 250)
        
        # Add window icon if running on Linux
        if platform.system() == "Linux":
            try:
                self.root.iconbitmap("@timer_icon.xbm")
            except:
                pass  # Icon not found, use default
        
        # Timer state variables
        self.hours = tk.IntVar(value=0)
        self.minutes = tk.IntVar(value=0)
        self.seconds = tk.IntVar(value=0)
        self.is_running = False
        self.remaining_time = 0
        self.timer_id = None
        
        # Create the main timer display
        self.create_timer_display()
        
        # Create input fields
        self.create_input_fields()
        
        # Create control buttons
        self.create_control_buttons()
        
        # Create status indicator
        self.create_status_indicator()
        
        # Set up keyboard shortcuts
        self.setup_keyboard_shortcuts()
    
    def create_timer_display(self):
        """Create the main timer display"""
        display_frame = tk.Frame(self.root, bg="#f0f0f0")
        display_frame.pack(pady=20, fill=tk.BOTH, expand=True)
        
        self.time_display = tk.Label(
            display_frame, 
            text="00:00:00", 
            font=("Courier New", 48),
            bg="white",
            fg="black",
            width=8,
            relief=tk.RAISED,
            borderwidth=2
        )
        self.time_display.pack(expand=True)
    
    def create_input_fields(self):
        """Create input fields for hours, minutes, and seconds"""
        input_frame = tk.Frame(self.root, bg="#f0f0f0")
        input_frame.pack(pady=10, fill=tk.X)
        
        # Configure grid columns to be evenly spaced
        for i in range(3):
            input_frame.columnconfigure(i, weight=1)
        
        # Hours input
        hours_label = tk.Label(input_frame, text="Hours:", bg="#f0f0f0")
        hours_label.grid(row=0, column=0, padx=5)
        hours_spinbox = ttk.Spinbox(
            input_frame, 
            from_=0, 
            to=99, 
            width=5, 
            textvariable=self.hours,
            wrap=True
        )
        hours_spinbox.grid(row=1, column=0, padx=5)
        
        # Minutes input
        minutes_label = tk.Label(input_frame, text="Minutes:", bg="#f0f0f0")
        minutes_label.grid(row=0, column=1, padx=5)
        minutes_spinbox = ttk.Spinbox(
            input_frame, 
            from_=0, 
            to=59, 
            width=5, 
            textvariable=self.minutes,
            wrap=True
        )
        minutes_spinbox.grid(row=1, column=1, padx=5)
        
        # Seconds input
        seconds_label = tk.Label(input_frame, text="Seconds:", bg="#f0f0f0")
        seconds_label.grid(row=0, column=2, padx=5)
        seconds_spinbox = ttk.Spinbox(
            input_frame, 
            from_=0, 
            to=59, 
            width=5, 
            textvariable=self.seconds,
            wrap=True
        )
        seconds_spinbox.grid(row=1, column=2, padx=5)
    
    def create_control_buttons(self):
        """Create control buttons (start, pause, reset)"""
        button_frame = tk.Frame(self.root, bg="#f0f0f0")
        button_frame.pack(pady=10, fill=tk.X)
        
        # Configure grid columns to be evenly spaced
        for i in range(3):
            button_frame.columnconfigure(i, weight=1)
        
        # Start button
        self.start_button = tk.Button(
            button_frame,
            text="Start",
            command=self.start_timer,
            bg="#4CAF50",
            fg="white",
            width=8,
            relief=tk.RAISED,
            borderwidth=2
        )
        self.start_button.grid(row=0, column=0, padx=10)
        
        # Pause button
        self.pause_button = tk.Button(
            button_frame,
            text="Pause",
            command=self.pause_timer,
            bg="#FFC107",
            fg="black",
            width=8,
            state=tk.DISABLED,
            relief=tk.RAISED,
            borderwidth=2
        )
        self.pause_button.grid(row=0, column=1, padx=10)
        
        # Reset button
        self.reset_button = tk.Button(
            button_frame,
            text="Reset",
            command=self.reset_timer,
            bg="#F44336",
            fg="white",
            width=8,
            relief=tk.RAISED,
            borderwidth=2
        )
        self.reset_button.grid(row=0, column=2, padx=10)
    
    def create_status_indicator(self):
        """Create status indicator"""
        status_frame = tk.Frame(self.root, bg="#f0f0f0")
        status_frame.pack(pady=10, fill=tk.X)
        
        status_label = tk.Label(status_frame, text="Status:", bg="#f0f0f0")
        status_label.pack(side=tk.LEFT, padx=(10, 0))
        
        self.status_text = tk.StringVar(value="Ready")
        self.status_display = tk.Label(
            status_frame,
            textvariable=self.status_text,
            bg="#2196F3",
            fg="white",
            width=10,
            padx=5,
            pady=2,
            relief=tk.SUNKEN,
            borderwidth=1
        )
        self.status_display.pack(side=tk.LEFT, padx=5)
    
    def setup_keyboard_shortcuts(self):
        """Set up keyboard shortcuts for the application"""
        self.root.bind("<space>", lambda event: self.toggle_timer())
        self.root.bind("r", lambda event: self.reset_timer())
        self.root.bind("<Escape>", lambda event: self.confirm_quit())
    
    def toggle_timer(self):
        """Toggle between start and pause based on current state"""
        if self.is_running:
            self.pause_timer()
        else:
            self.start_timer()
    
    def confirm_quit(self):
        """Confirm before quitting the application"""
        if tk.messagebox.askokcancel("Quit", "Do you want to quit the application?"):
            self.root.destroy()
    
    def calculate_total_seconds(self):
        """Calculate total seconds from hours, minutes, and seconds"""
        return self.hours.get() * 3600 + self.minutes.get() * 60 + self.seconds.get()
    
    def update_display(self, seconds_left):
        """Update the timer display with the remaining time"""
        if seconds_left <= 0:
            self.time_display.config(text="00:00:00")
            return
        
        hours = seconds_left // 3600
        minutes = (seconds_left % 3600) // 60
        seconds = seconds_left % 60
        
        time_string = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        self.time_display.config(text=time_string)
    
    def countdown(self):
        """Update the countdown timer"""
        if self.remaining_time <= 0:
            self.timer_complete()
            return
        
        self.update_display(self.remaining_time)
        self.remaining_time -= 1
        self.timer_id = self.root.after(1000, self.countdown)
    
    def start_timer(self):
        """Start the countdown timer"""
        if self.is_running:
            return
        
        # If timer was not paused, get time from input fields
        if self.remaining_time <= 0:
            self.remaining_time = self.calculate_total_seconds()
            
            # Check if timer value is valid
            if self.remaining_time <= 0:
                tk.messagebox.showwarning("Invalid Time", "Please enter a time greater than zero.")
                return
        
        self.is_running = True
        self.status_text.set("Running")
        self.status_display.config(bg="#4CAF50")
        
        # Update button states
        self.start_button.config(state=tk.DISABLED)
        self.pause_button.config(state=tk.NORMAL)
        
        # Start the countdown
        self.countdown()
    
    def pause_timer(self):
        """Pause the countdown timer"""
        if not self.is_running:
            return
        
        self.is_running = False
        self.status_text.set("Paused")
        self.status_display.config(bg="#FFC107")
        
        # Update button states
        self.start_button.config(state=tk.NORMAL)
        self.pause_button.config(state=tk.DISABLED)
        
        # Cancel the scheduled countdown
        if self.timer_id:
            self.root.after_cancel(self.timer_id)
            self.timer_id = None
    
    def reset_timer(self):
        """Reset the countdown timer"""
        # Cancel any running timer
        if self.timer_id:
            self.root.after_cancel(self.timer_id)
            self.timer_id = None
        
        # Reset state
        self.is_running = False
        self.remaining_time = 0
        
        # Reset display
        self.time_display.config(text="00:00:00")
        
        # Reset status
        self.status_text.set("Ready")
        self.status_display.config(bg="#2196F3")
        
        # Reset button states
        self.start_button.config(state=tk.NORMAL)
        self.pause_button.config(state=tk.DISABLED)
    
    def timer_complete(self):
        """Handle timer completion"""
        self.is_running = False
        self.remaining_time = 0
        
        # Update status
        self.status_text.set("Finished!")
        self.status_display.config(bg="#F44336")
        
        # Reset button states
        self.start_button.config(state=tk.NORMAL)
        self.pause_button.config(state=tk.DISABLED)
        
        # Flash the display to indicate completion
        self.flash_display()
        
        # Play alert sound (system beep)
        self.root.bell()
        
        # Show notification
        try:
            self.show_notification()
        except:
            pass  # Notification failed, continue without it
    
    def flash_display(self, count=5):
        """Flash the timer display to indicate completion"""
        if count <= 0:
            self.time_display.config(bg="white", fg="black")
            return
        
        current_bg = self.time_display.cget("background")
        current_fg = self.time_display.cget("foreground")
        
        # Toggle colors
        new_bg = "red" if current_bg == "white" else "white"
        new_fg = "white" if current_fg == "black" else "black"
        
        self.time_display.config(bg=new_bg, fg=new_fg)
        self.root.after(500, lambda: self.flash_display(count - 1))
    
    def show_notification(self):
        """Show desktop notification when timer completes"""
        try:
            from plyer import notification
            notification.notify(
                title="Countdown Timer",
                message="Timer has completed!",
                app_name="Countdown Timer",
                timeout=10
            )
        except ImportError:
            # Plyer not available, try alternative methods
            if platform.system() == "Linux":
                try:
                    os.system('notify-send "Countdown Timer" "Timer has completed!"')
                except:
                    pass

def main():
    root = tk.Tk()
    app = CountdownTimer(root)
    root.mainloop()

if __name__ == "__main__":
    main()
