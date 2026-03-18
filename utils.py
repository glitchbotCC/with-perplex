# smart_farm/utils.py

import os
import sys
import datetime
import tkinter as tk
from tkinter import ttk

def resource_path(relative_path):
    """ Get the absolute path to a resource, works for dev and for PyInstaller. """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        # Get the directory of the currently running script and go up to the project root.
        # __file__ is the path to this file (utils.py)
        # The first dirname gets the 'smart_farm' directory.
        # The second dirname gets the project root folder (e.g., 'with perplex').
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        
    return os.path.join(base_path, relative_path)

def format_duration(seconds):
    """ Formats a duration in seconds into a human-readable HH:MM:SS string. """
    if seconds is None or not isinstance(seconds, (int, float)) or seconds < 0:
        return "N/A"
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"

def tooltip(widget, text):
    """ Attaches a tooltip popup to a Tkinter widget. """
    tip_window = None

    def show_tip(_=None):
        nonlocal tip_window
        if tip_window or not text:
            return

        x = widget.winfo_pointerx() + 15
        y = widget.winfo_pointery() + 10

        tip_window = tk.Toplevel(widget)
        tip_window.wm_overrideredirect(True)

        label = ttk.Label(tip_window, text=text, justify=tk.LEFT,
                          background="#3b4252", foreground="#e5e9f0",
                          relief=tk.SOLID, borderwidth=1,
                          font=("Segoe UI", 9, "normal"), padding=(5, 3))
        label.pack()
        tip_window.update_idletasks()

        tip_width = tip_window.winfo_width()
        tip_height = tip_window.winfo_height()
        screen_width = widget.winfo_screenwidth()
        screen_height = widget.winfo_screenheight()

        if x + tip_width > screen_width: x = screen_width - tip_width - 5
        if x < 0: x = 5
        if y + tip_height > screen_height: y = widget.winfo_pointery() - tip_height - 10
        if y < 0: y = 5

        tip_window.wm_geometry(f"+{int(x)}+{int(y)}")

    def hide_tip(_=None):
        nonlocal tip_window
        if tip_window:
            tip_window.destroy()
        tip_window = None

    widget.bind("<Enter>", show_tip, add="+")
    widget.bind("<Leave>", hide_tip, add="+")
