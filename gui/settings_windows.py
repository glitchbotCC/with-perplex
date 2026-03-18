# smart_farm/gui/settings_windows.py

import tkinter as tk
from tkinter import ttk, messagebox
import datetime
from .. import utils

class AppSettingsWindow(tk.Toplevel):
    """A Toplevel window for managing application-wide settings like virtual sunrise/sunset and weather simulation."""
    def __init__(self, master_app):
        super().__init__(master_app.root)
        self.master_app = master_app
        self.transient(master_app.root)
        self.title("⚙️ Application Settings")
        self.geometry("500x300")
        self.resizable(False, False)
        self.grab_set()

        self.sunrise_var = tk.StringVar(value=self.master_app.settings.get("virtual_sunrise_time"))
        self.sunset_var = tk.StringVar(value=self.master_app.settings.get("virtual_sunset_time"))
        self.enable_rain_skip_var = tk.BooleanVar(value=self.master_app.settings.get("enable_rain_skip"))

        self.configure(bg=self.master_app.style.lookup(".", "background"))
        self._setup_ui()
        self.sunrise_entry.focus_set()

    def _setup_ui(self):
        """Sets up the UI components (labels, entries, buttons) for the AppSettingsWindow."""
        main_frame = ttk.Frame(self, padding=20, style="TFrame")
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="Manual Sunrise Time (HH:MM):", style="TLabel").grid(row=0, column=0, padx=5, pady=8, sticky="w")
        self.sunrise_entry = ttk.Entry(main_frame, textvariable=self.sunrise_var, width=10, style="TEntry")
        self.sunrise_entry.grid(row=0, column=1, padx=5, pady=8, sticky="ew")
        utils.tooltip(self.sunrise_entry, "Set a fallback time for 'Sunrise' if the API fails.")

        ttk.Label(main_frame, text="Manual Sunset Time (HH:MM):", style="TLabel").grid(row=1, column=0, padx=5, pady=8, sticky="w")
        self.sunset_entry = ttk.Entry(main_frame, textvariable=self.sunset_var, width=10, style="TEntry")
        self.sunset_entry.grid(row=1, column=1, padx=5, pady=8, sticky="ew")
        utils.tooltip(self.sunset_entry, "Set a fallback time for 'Sunset' if the API fails.")

        ttk.Label(main_frame, text="(Sunrise/Sunset are now set automatically by location)", font=('Segoe UI', 8, 'italic')).grid(row=2, column=0, columnspan=2, pady=(0, 10))

        self.rain_skip_check = ttk.Checkbutton(main_frame, text="Enable Rain Skip for Schedules", variable=self.enable_rain_skip_var, style="TCheckbutton")
        self.rain_skip_check.grid(row=3, column=0, columnspan=2, padx=5, pady=10, sticky="w")
        utils.tooltip(self.rain_skip_check, "If checked, schedules will not run if live weather is 'Rainy'.")

        main_frame.columnconfigure(1, weight=1)

        button_frame = ttk.Frame(main_frame, style="TFrame")
        button_frame.grid(row=4, column=0, columnspan=2, pady=20, sticky="ew")

        save_btn = ttk.Button(button_frame, text="💾 Save Settings", command=self._save_app_settings, style="Accent.TButton", compound=tk.LEFT)
        save_btn.pack(side=tk.RIGHT, padx=5)
        cancel_btn = ttk.Button(button_frame, text="Cancel", command=self.destroy, style="TButton")
        cancel_btn.pack(side=tk.RIGHT, padx=5)

    def _validate_time_format(self, time_str):
        """Validates if the given string is in HH:MM format."""
        try:
            datetime.datetime.strptime(time_str, "%H:%M")
            return True
        except ValueError:
            return False

    def _save_app_settings(self):
        """Validates and saves the application settings entered by the user."""
        sunrise = self.sunrise_var.get()
        sunset = self.sunset_var.get()
        rain_skip = self.enable_rain_skip_var.get()

        if not self._validate_time_format(sunrise) or not self._validate_time_format(sunset):
            messagebox.showerror("Invalid Time", "Please enter Sunrise/Sunset times in HH:MM format.", parent=self)
            return

        self.master_app.settings.set("virtual_sunrise_time", sunrise)
        self.master_app.settings.set("virtual_sunset_time", sunset)
        self.master_app.settings.set("enable_rain_skip", rain_skip)

        self.master_app.log(f"App settings updated: Fallback Sunrise {sunrise}, Fallback Sunset {sunset}, Rain Skip {rain_skip}")
        self.master_app.notify("Application settings saved.", duration=2000)
        self.master_app.update_dashboard()
        self.destroy()

class ValveSettingsWindow(tk.Toplevel):
    """A Toplevel window for setting valve-specific properties like flow rate."""
    def __init__(self, master_app, valve_index):
        super().__init__(master_app.root)
        self.master_app = master_app
        self.valve_index = valve_index
        self.valve_data = self.master_app.valves[valve_index]

        self.transient(master_app.root)
        self.title(f"⚙️ Settings: {self.valve_data['name']}")
        self.geometry("400x200")
        self.resizable(False, False)
        self.grab_set()

        self.flow_rate_var = tk.StringVar(value=str(self.valve_data.get("flow_rate_lpm", 0.0)))

        self.configure(bg=self.master_app.style.lookup(".", "background"))
        self._setup_ui()
        self.flow_rate_entry.focus_set()
        self.flow_rate_entry.select_range(0, tk.END)

    def _setup_ui(self):
        """Sets up UI components for the ValveSettingsWindow."""
        main_frame = ttk.Frame(self, padding=20, style="TFrame")
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text=f"Settings for Valve: {self.valve_data['name']}", style="TLabel", font=('Segoe UI', 11, 'bold')).pack(pady=(0, 15))

        flow_frame = ttk.Frame(main_frame, style="TFrame")
        flow_frame.pack(fill=tk.X, pady=5)
        ttk.Label(flow_frame, text="Est. Flow Rate (Liters/Min):", style="TLabel").pack(side=tk.LEFT, padx=(0, 10))
        self.flow_rate_entry = ttk.Entry(flow_frame, textvariable=self.flow_rate_var, width=10, style="TEntry")
        self.flow_rate_entry.pack(side=tk.LEFT)
        utils.tooltip(self.flow_rate_entry, "Enter the estimated flow rate for this valve (e.g., 10.5) to track water usage.")

        button_frame = ttk.Frame(main_frame, style="TFrame")
        button_frame.pack(pady=20, fill=tk.X, side=tk.BOTTOM)

        save_btn = ttk.Button(button_frame, text="💾 Save", command=self._save_valve_settings, style="Accent.TButton", compound=tk.LEFT)
        save_btn.pack(side=tk.RIGHT, padx=5)
        cancel_btn = ttk.Button(button_frame, text="Cancel", command=self.destroy, style="TButton")
        cancel_btn.pack(side=tk.RIGHT, padx=5)

    def _save_valve_settings(self):
        """Validates and saves the valve-specific settings."""
        try:
            flow_rate = float(self.flow_rate_var.get())
            if flow_rate < 0:
                raise ValueError("Flow rate cannot be negative.")
        except ValueError:
            messagebox.showerror("Invalid Input", "Please enter a valid non-negative number for flow rate.", parent=self)
            return

        self.master_app.valves[self.valve_index]["flow_rate_lpm"] = flow_rate
        self.master_app.save_state()
        self.master_app.log(f"Flow rate for valve '{self.valve_data['name']}' set to {flow_rate:.2f} LPM.")
        self.master_app.notify(f"Settings saved for valve '{self.valve_data['name']}'.", duration=2000)
        self.destroy()