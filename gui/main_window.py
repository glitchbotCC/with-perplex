# smart_farm/gui/main_window.py

# Standard library imports
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
from PIL import Image, ImageTk
import json
import datetime
import os
import sys
import time
import re
import random
import requests
import hashlib
import math
from queue import Queue


# Local application imports
from .. import constants, utils
from ..settings_manager import PersistentSettings
from ..hardware_manager import HardwareManager
from .mqtt_manager import MqttManager

# GUI window imports
from .settings_windows import AppSettingsWindow, ValveSettingsWindow
from .scheduler_window import SchedulerWindow
from .automation_window import AutomationWindow
from .log_window import LogWindow
from .auth_dialog import AuthDialog
from .valve_manager import ValveManagerMixin
from .scheduler_manager import SchedulerManagerMixin
from .automation_manager import AutomationManagerMixin
from .map_manager import MapManagerMixin, AssignValveDialog



class MainWindow(ValveManagerMixin, SchedulerManagerMixin, AutomationManagerMixin, MapManagerMixin):
    """Main application class for Smart Farm Valve Control."""
    def __init__(self, root):
        self.log_window = None
        self.root = root
        self.settings = PersistentSettings()
        self.hardware = HardwareManager()

        # --- Load settings and initialize state ---
        self.logs = self.settings.get("logs", [])
        
        self.theme = self.settings.get("theme", "dark")
        self.location = self.settings.get("location", "London,UK")
        self.api_key = constants.API_KEY
        
        # Auth and Lock state
        self.is_config_locked = tk.BooleanVar(value=self.settings.get("config_locked", False))
        self.admin_user = self.settings.get("admin_user")
        self.admin_pass_hash = self.settings.get("admin_pass_hash")

        # This section now safely loads data from your settings file
        # Copy lists so the runtime state does not share references directly with persistent data
        self.valves = [v.copy() for v in self.settings.get("valves", [])]
        self.aux_controls = [a.copy() for a in self.settings.get("aux_controls", [])]
        self.automation_rules = [r.copy() for r in self.settings.get("automation_rules", [])]
        self.schedule_history = [s.copy() for s in self.settings.get("schedule_history", [])]

        self._migrate_schedule_data()

        for v in self.valves:
            self._initialize_valve_data(v)

        default_aux_controls = [{"id": f"aux_{i}", "name": f"AUX {i+1}", "pin": pin, "status": False, "schedules": []} for i, pin in enumerate(constants.EXTRA_GPIO_PINS)]
        loaded_aux = self.settings.get("aux_controls")
        valid_pins = True
        if isinstance(loaded_aux, list) and len(loaded_aux) == len(constants.EXTRA_GPIO_PINS):
            loaded_pin_set = {c.get("pin") for c in loaded_aux}
            default_pin_set = set(constants.EXTRA_GPIO_PINS)
            if loaded_pin_set != default_pin_set:
                valid_pins = False
        else:
            valid_pins = False
        if valid_pins:
            self.aux_controls = loaded_aux
        else:
            if loaded_aux is not None: self.log("Invalid 'aux_controls' in settings, resetting to defaults.")
            self.aux_controls = default_aux_controls

        self.layout_mode = self.settings.get("layout_mode", "comfortable")  # new: comfortable / compact
        self.side_panel_visible = self.settings.get("side_panel_visible", True)

        self.undo_stack = []
        self.style = ttk.Style()
        self.scheduled_jobs = {}
        self.filtered_valves = []
        self.log_window = None
        self.scheduler_window = None
        self.log_queue = Queue()
        self.status_queue = Queue()

        # --- Tkinter Variables ---
        self.search_var = tk.StringVar()
        self.valve_count_var = tk.StringVar(value="1")
        self.location_var = tk.StringVar(value=f"Location: {self.location}")
        self.system_time_var = tk.StringVar(value="Time: --:--:--")
        self.live_weather_var = tk.StringVar(value="Weather: Fetching...")
        self.mqtt_status_var = tk.StringVar(value="MQTT: Initializing...")
        self.sensor_temp_c = tk.StringVar(value="N/A")
        self.sensor_humidity = tk.StringVar(value="N/A")
        self.sensor_temp_c_dht11 = tk.StringVar(value="N/A")
        self.sensor_humidity_dht11 = tk.StringVar(value="N/A")
        self.sensor_moisture = tk.StringVar(value="N/A")
        self.sensor_light = tk.StringVar(value="N/A")
        self.sensor_pressure = tk.StringVar(value="N/A")

        # --- Initial Setup Calls ---
        self.apply_theme()
        self.setup_ui()
        self.bind_shortcuts()

        self.root.title(f"🌱 {constants.APP_NAME} v{constants.APP_VERSION}")
        self.root.geometry("1350x850")
        self.root.minsize(1100, 700)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
       
        self.mqtt_manager = MqttManager(self)
        self.process_log_queue()
        self.process_status_queue()
        
        self._activate_all_schedules()
        self.filter_valves()
        self.update_aux_controls_ui()
        self.update_dashboard()
        self._start_status_dot_animations()
        self.update_system_clock()
        self.update_sensor_readings()
        self.update_location_data()
        self.check_automation_rules()
        self.log("Application initialized successfully.")
        self.update_lock_status_ui()
    
    def set_mqtt_status(self, status, color):
        """Thread-safe method to request a status update. Puts the update
        request into a queue to be processed by the main GUI thread."""
        self.status_queue.put((status, color))

    def _set_mqtt_status_ui(self, status, color):
        """
        Private method that performs the actual UI update for the MQTT status.
        Should only be called from the main thread.
        """
        if hasattr(self, 'mqtt_status_var') and hasattr(self, 'mqtt_status_label'):
            self.mqtt_status_var.set(f"MQTT: {status}")

            dark_colors = {"green": "#81C784", "red": "#E57373", "orange": "#FFB74D", "grey": "#90A4AE"}
            light_colors = {"green": "#4CAF50", "red": "#D32F2F", "orange": "#FFA726", "grey": "#546E7A"}

            theme_colors = dark_colors if self.theme == "dark" else light_colors

            self.mqtt_status_label.config(foreground=theme_colors.get(color, self.style.lookup("TLabel", "foreground")))
  
    def _hash_password(self, password):
        """Hashes a password using SHA-256."""
        return hashlib.sha256(password.encode('utf-8')).hexdigest()
    
    def _process_mqtt_command(self, command, data):
        """Processes a command received from the MqttManager."""
        if command == "toggle_valve":
            if "index" in data and 0 <= data["index"] < len(self.valves):
                self.toggle_valve(data["index"])

        elif command == "toggle_aux":
            if "index" in data and 0 <= data["index"] < len(self.aux_controls):
                self.toggle_aux_control(data["index"])

        elif command == "add_valves":
            if not self.is_config_locked.get():
                count = data.get("count", 1)
                self.valve_count_var.set(str(count))
                self.add_valves()
            else:
                self.log("MQTT command 'add_valves' blocked: Configuration is locked.")

        elif command == "remove_valve":
            if not self.is_config_locked.get() and "index" in data:
                idx = data["index"]
                if 0 <= idx < len(self.valves):
                    self.clear_all_schedules_for_item("valve", idx)
                    valve = self.valves[idx]
                    self.hardware.set_pin_state(valve['pin'], False)
                    rem_copy = self.valves.pop(idx)
                    self.undo_stack.append(rem_copy.copy())
                    self.log(f"Valve '{rem_copy['name']}' removed via web UI.")
                    self.save_state()
                    self.filter_valves()
                    self.update_dashboard()

        elif command == "rename_item":
            if not self.is_config_locked.get() and "type" in data and "index" in data and "newName" in data:
                item_list = self.valves if data['type'] == 'valve' else self.aux_controls
                idx = data['index']
                if 0 <= idx < len(item_list):
                    item_list[idx]['name'] = data['newName']
                    self.save_state()
                    if data['type'] == 'valve':
                        self.filter_valves()
                    else:
                        self.update_aux_controls_ui()

        elif command == "edit_note":
            if "index" in data and "newNote" in data and 0 <= data['index'] < len(self.valves):
                self.valves[data['index']]['note'] = data['newNote']
                self.save_state()
                self.filter_valves()

        elif command == "toggle_valve_lock":
            if "index" in data and 0 <= data['index'] < len(self.valves):
                self.toggle_lock(data['index'])

        elif command == "emergency_stop":
            self.turn_all_systems_off(from_web=True)

        elif command == "set_schedule":
            if "item_type" in data and "item_idx" in data and "details" in data:
                self.log(f"Received web command to set schedule for {data['item_type']} at index {data['item_idx']}")
                self.set_schedule_for_item(item_type=data['item_type'], item_idx=data['item_idx'], schedule_id=None, details=data['details'])

        elif command == "remove_schedule":
            if "id" in data and data["id"]:
                self.log(f"Received web command to remove schedule ID: {data['id']}")
                self.clear_schedule_by_id(data['id'])

        elif command == "add_automation_rule":
            if isinstance(data, dict):
                self.log("Received web command to add automation rule.")
                self.automation_rules.append(data)
                self.save_state()

        elif command == "remove_automation_rule":
            if "index" in data and isinstance(data["index"], int):
                index = data["index"]
                if 0 <= index < len(self.automation_rules):
                    self.log(f"Received web command to remove automation rule at index: {index}")
                    self.automation_rules.pop(index)
                    self.save_state()
                else:
                    self.log(f"Invalid index for remove_automation_rule: {index}")

        elif command == "toggle_lock":
            if self.is_config_locked.get():
                password = data.get("password")
                if password and self._hash_password(password) == self.admin_pass_hash:
                    self.is_config_locked.set(False)
                    self.settings.set("config_locked", False)
                    self.log("Configuration Unlocked via web UI.")
                else:
                    self.log("Failed web UI unlock attempt.")
            else:
                if data.get("is_setting_credentials"):
                    self.admin_user = data.get("username")
                    self.admin_pass_hash = self._hash_password(data.get("password", ""))
                    self.settings.set("admin_user", self.admin_user)
                    self.settings.set("admin_pass_hash", self.admin_pass_hash)
                    self.log("Admin credentials set via web UI.")
                self.is_config_locked.set(True)
                self.settings.set("config_locked", True)
                self.log("Configuration Locked via web UI.")
            self.update_lock_status_ui()

    def _get_current_state_as_dict(self):
        """Aggregates the entire application state into a single dictionary for publishing."""
        valves_copy = [v.copy() for v in self.valves]
        for v in valves_copy:
            v.pop("timer_var", None)

        sensors_data = {
            'Temp (DHT22)': self.sensor_temp_c.get(),
            'Humidity (DHT22)': self.sensor_humidity.get(),
            'Temp (DHT11)': self.sensor_temp_c_dht11.get(),
            'Humidity (DHT11)': self.sensor_humidity_dht11.get(),
            'Soil Moisture': self.sensor_moisture.get()
        }

        settings_data = {
            'location': self.location,
            'virtual_sunrise_time': self.settings.get("virtual_sunrise_time"),
            'virtual_sunset_time': self.settings.get("virtual_sunset_time"),
            'enable_rain_skip': self.settings.get("enable_rain_skip"),
            'config_locked': self.is_config_locked.get(),
            'admin_user': self.admin_user,
        }

        return {
            "valves": valves_copy,
            "aux_controls": self.aux_controls,
            "automation_rules": self.automation_rules,
            "schedule_history": self.schedule_history,
            "logs": self.logs[-100:],
            "settings": settings_data,
            "sensors": sensors_data,
            "live_weather": self.live_weather_var.get(),
            "system_time": self.system_time_var.get(),
            "theme": self.theme
        }

    def toggle_configuration_lock(self):
        """Handles the logic for locking or unlocking the configuration."""
        if self.is_config_locked.get():
            # UNLOCKING
            if not self.admin_user:
                self.notify("No credentials set. Cannot unlock.", 4000)
                return

            dialog = AuthDialog(self, is_setting_credentials=False)
            creds = dialog.result

            if creds and creds["username"] == self.admin_user and self._hash_password(creds["password"]) == self.admin_pass_hash:
                self.is_config_locked.set(False)
                self.settings.set("config_locked", False)
                self.log("Configuration Unlocked.")
                self.notify("Configuration Unlocked.", 3000)
            elif creds:
                messagebox.showerror("Authentication Failed", "Invalid username or password.", parent=self.root)
                self.log("Failed unlock attempt.")
        else:
            # LOCKING
            if not self.admin_user:
                if messagebox.askyesno("Set Credentials", "No admin credentials found. Do you want to set them now to lock the configuration?", parent=self.root):
                    dialog = AuthDialog(self, is_setting_credentials=True)
                    creds = dialog.result
                    if creds:
                        self.admin_user = creds["username"]
                        self.admin_pass_hash = self._hash_password(creds["password"])
                        self.settings.set("admin_user", self.admin_user)
                        self.settings.set("admin_pass_hash", self.admin_pass_hash)
                        self.log("Admin credentials set.")
                    else:
                        return # User cancelled setting credentials
            
            self.is_config_locked.set(True)
            self.settings.set("config_locked", True)
            self.log("Configuration Locked.")
            self.notify("Configuration Locked.", 3000)
        
        self.update_lock_status_ui()
        
    def update_lock_status_ui(self):
        """Updates the UI elements based on the lock state."""
        is_locked = self.is_config_locked.get()
        lock_text = "Unlock Config 🔓" if is_locked else "Lock Config 🔒"
        lock_tip = "Unlock the configuration" if is_locked else "Lock the configuration to prevent adding/removing valves"
        
        # Update the lock button in the footer
        if hasattr(self, 'lock_btn_footer'):
            self.lock_btn_footer.config(text=lock_text)
            utils.tooltip(self.lock_btn_footer, lock_tip)

        # Enable/disable relevant widgets
        state = "disabled" if is_locked else "normal"
        if hasattr(self, 'valve_entry'):
            self.valve_entry.config(state=state)
            self.add_valves_btn.config(state=state)
            self.reset_valves_btn.config(state=state)
            # Also disable remove buttons on individual valve cards
            self.filter_valves() # Re-render to apply disabled state

    def _initialize_valve_data(self, valve_dict):
        """Sets default keys and the timer variable for a valve dictionary."""
        valve_dict.setdefault("flow_rate_lpm", 0.0)
        valve_dict.setdefault("estimated_water_usage_liters", 0.0)
        valve_dict.setdefault("total_on_time_seconds", 0)
        valve_dict.setdefault("last_on_timestamp", None)
        valve_dict.setdefault("last_on_duration_seconds", None)
        valve_dict.setdefault("current_on_start_time", None)
        valve_dict.setdefault("schedules", [])
        valve_dict.setdefault("history", [])
        valve_dict.setdefault("note", "")
        valve_dict.setdefault("locked", False)
        valve_dict.setdefault("icon", "💧")
        valve_dict["timer_var"] = tk.StringVar(value="")

    def _migrate_schedule_data(self):
        """One-time migration of old schedule_str to new schedules list."""
        migrated = False
        for item in self.valves + self.aux_controls:
            if "schedule_str" in item and item["schedule_str"]:
                migrated = True
                schedule_str = item.pop("schedule_str")
                skip_rainy = item.pop("schedule_skip_rainy", False)
                item.setdefault("schedules", [])

                try:
                    new_schedule = None
                    if schedule_str.startswith("CYCLE"):
                        match = re.match(r"CYCLE:\s*ON\s*(\d+)\s*m,\s*OFF\s*(\d+)\s*m,\s*x(\d+|∞)\s*at\s*(\d{2}:\d{2})", schedule_str)
                        if match:
                            on_dur, off_dur, count_str, time_part = match.groups()
                            new_schedule = {
                                "id": f"sched_{int(time.time() * 1000)}_{random.randint(100, 999)}",
                                "type": "Cycle", "time": time_part, "on_m": int(on_dur),
                                "off_m": int(off_dur), "count": 0 if count_str == "∞" else int(count_str),
                                "skip_rainy": skip_rainy
                            }
                    else: 
                        action, time_part = SchedulerWindow._parse_schedule_string(schedule_str)
                        if action and time_part:
                            new_schedule = {
                                "id": f"sched_{int(time.time() * 1000)}_{random.randint(100, 999)}",
                                "type": "Fixed Time", "action": action, "time": time_part,
                                "skip_rainy": skip_rainy
                            }
                    if new_schedule:
                        item["schedules"].append(new_schedule)
                except Exception as e:
                    self.log(f"Could not migrate schedule '{schedule_str}': {e}")
            item.setdefault("schedules", [])
        if migrated:
            self.log("Migrated old schedule data to new format.")
            self.save_state()

    def _start_status_dot_animations(self):
        self._animate_status_dots()

    def _animate_status_dots(self):
        if not hasattr(self, 'root') or not self.root.winfo_exists():
            return

        for i, valve_data in enumerate(self.valves):
            if i < len(self.valve_status_labels) and self.valve_status_labels[i].winfo_exists():
                label = self.valve_status_labels[i]
                if valve_data.get("status"):
                    current_fg = str(label.cget("foreground"))
                    pulse_color_1 = "#81C784" 
                    pulse_color_2 = "#A5D6A7"
                    try:
                        label.config(foreground=pulse_color_2 if current_fg == pulse_color_1 else pulse_color_1)
                    except tk.TclError:
                        label.config(foreground=pulse_color_1)
        self.root.after(750, self._animate_status_dots)

    def open_app_settings_window(self):
        AppSettingsWindow(self)

    def open_scheduler_window(self):
        if self.scheduler_window and self.scheduler_window.winfo_exists():
            self.scheduler_window._populate_items_for_scheduling()
            self.scheduler_window._populate_all_schedule_views()
            self.scheduler_window.deiconify()
            self.scheduler_window.lift()
        else:
            self.scheduler_window = SchedulerWindow(self)

    def open_valve_settings_window(self, valve_index):
        ValveSettingsWindow(self, valve_index)

    def open_automation_window(self):
        AutomationWindow(self)

    def open_log_window(self):
        if self.log_window and self.log_window.winfo_exists():
            self.log_window.lift()
        else:
            self.log_window = LogWindow(self)

    def bind_shortcuts(self):
        self.root.bind("<Control-n>", lambda _: self.add_valves())
        self.root.bind("<Control-r>", lambda _: self.reset_valves())
        self.root.bind("<Control-e>", lambda _: self.export_config())
        self.root.bind("<Control-i>", lambda _: self.import_config())
        self.root.bind("<Control-t>", lambda _: self.toggle_theme())
        self.root.bind("<Control-Alt-s>", lambda _: self.open_scheduler_window())
        self.root.bind("<Control-Shift-C>", lambda _: self.open_app_settings_window())
        self.root.bind("<Control-Shift-S>", lambda _: self.save_log_manually())
        self.root.bind("<Control-f>", lambda _: self.focus_search())
        self.root.bind("<Control-z>", lambda _: self.undo_remove())

    def toggle_theme(self):
        selected_tab = None
        if hasattr(self, 'notebook') and self.notebook.index("end") > 0:
            try:
                selected_tab = self.notebook.index(self.notebook.select())
            except Exception:
                selected_tab = None

        self.theme = "dark" if self.theme == "light" else "light"
        self.settings.set("theme", self.theme)
        self.apply_theme()
        self.setup_ui()

        if selected_tab is not None and hasattr(self, 'notebook'):
            try:
                if selected_tab < self.notebook.index("end"):
                    self.notebook.select(selected_tab)
            except Exception:
                pass

        self.filter_valves() 
        self.update_aux_controls_ui()
        self.update_dashboard()
        self.update_lock_status_ui()

    def toggle_layout_mode(self):
        self.layout_mode = "compact" if self.layout_mode == "comfortable" else "comfortable"
        self.settings.set("layout_mode", self.layout_mode)
        if hasattr(self, 'layout_toggle_btn'):
            self.layout_toggle_btn.config(text="Compact View" if self.layout_mode == "comfortable" else "Comfort View")
        self.render_valves_grid()

    def apply_theme(self):
        self.style.theme_use("clam")

        # Friendly ambient palette: soft, approachable, high readability
        slate_bg = "#1F2A38"            # dark background
        slate_card_bg = "#2B3C52"       # dark card container
        slate_text = "#DCE7F2"          # light text on dark
        slate_border = "#4A5F7E"        # subtle border
        slate_accent_green = "#4CABDB"   # friendly blue accent
        slate_accent_fg = "#FFFFFF"      # accent text for dark
        slate_error_red = "#F0575D"     # softer danger

        slate_light_bg = "#F1F4F8"      # light background
        slate_light_card_bg = "#FFFFFF"  # light cards
        slate_light_text = "#2D3E50"    # dark text on light
        slate_light_border = "#CCE0F2"  # light border
        slate_light_accent_green = "#5C96D5" # calm accent
        slate_light_accent_fg = "#FFFFFF"   # accent text
        slate_light_error_red = "#DD5B64"  # soften red

        if self.theme == "dark":
            bg, fg, frame_bg, border = slate_bg, slate_text, slate_card_bg, slate_border
            accent, accent_fg = slate_accent_green, slate_accent_fg
            emergency, emergency_fg = slate_error_red, slate_light_accent_fg
            locked_bg = "#212b30"
            entry_bg, entry_fg, entry_insert = "#455A64", fg, accent
            tree_bg, tree_fg, tree_sel_bg = slate_card_bg, fg, "#546E7A"
            btn_bg, btn_fg, btn_active_bg = slate_card_bg, fg, "#455A64"
        else: 
            bg, fg, frame_bg, border = slate_light_bg, slate_light_text, slate_light_card_bg, slate_light_border
            accent, accent_fg = slate_light_accent_green, slate_light_accent_fg
            emergency, emergency_fg = slate_light_error_red, slate_light_accent_fg
            locked_bg = "#CFD8DC"
            entry_bg, entry_fg, entry_insert = slate_light_card_bg, fg, accent
            tree_bg, tree_fg, tree_sel_bg = slate_light_card_bg, fg, "#C8E6C9"
            btn_bg, btn_fg, btn_active_bg = "#B0BEC5", fg, "#90A4AE"

        self.style.configure(".", background=bg, foreground=fg, bordercolor=border, font=('Segoe UI', 10))
        self.style.configure("TFrame", background=bg)
        self.style.configure("TLabel", background=bg, foreground=fg)
        self.style.configure("Header.TLabel", font=("Segoe UI Semibold", 26), background=bg, foreground=fg)
        self.style.configure("Subheader.TLabel", font=("Segoe UI", 13), background=bg, foreground=fg)
        
        self.style.configure("TButton", background=btn_bg, foreground=btn_fg, borderwidth=0, relief="flat", font=('Segoe UI', 10, 'bold'), padding=(10, 7))
        self.style.map("TButton", background=[('active', btn_active_bg), ('pressed', btn_active_bg)])

        self.style.configure("Accent.TButton", background=accent, foreground=accent_fg, borderwidth=0, relief="flat", font=('Segoe UI', 10, 'bold'), padding=(10, 7))
        self.style.map("Accent.TButton", background=[('active', accent), ('pressed', accent)])

        self.style.configure("Emergency.TButton", background=emergency, foreground=emergency_fg, borderwidth=0, relief="flat", font=('Segoe UI', 10, 'bold'), padding=(10, 7))
        self.style.map("Emergency.TButton", background=[('active', emergency), ('pressed', emergency)])

        # apply softer button aesthetics for friendly UI
        self.style.configure("Modern.TButton", background="#5C96D5", foreground="#FFFFFF", borderwidth=0, relief="flat", padding=(8, 6), font=('Segoe UI', 10, 'bold'))
        self.style.map("Modern.TButton", background=[('active', '#4A84B9'), ('pressed', '#3E6C97')])

        self.style.configure("Valve.Toggle.TButton", background="#5C96D5", foreground="#FFFFFF", borderwidth=1, relief="solid", padding=(8, 6), font=('Segoe UI', 10, 'bold'))
        self.style.map("Valve.Toggle.TButton", 
                       background=[('active', '#4A84B9'), ('pressed', '#3E6C97')],
                       bordercolor=[('active', '#6AA9D8'), ('!active', '#5C96D5')])

        # Note: ttk doesn't support real rounded corners in many themes; we simulate softer edges
        self.style.configure("Card.TFrame", background=frame_bg, borderwidth=0, relief="flat", bordercolor=border, padding=12)
        self.style.map("Card.TFrame", background=[('active', frame_bg)])
        self.style.configure("Card.TFrame.Label", background=frame_bg, foreground=fg, font=('Segoe UI Semibold', 11))

        self.style.configure("Rounded.TFrame", background=frame_bg, borderwidth=0, relief="flat", padding=12)

        # Modern mode styling
        self.style.configure("Modern.TFrame", background=frame_bg)
        self.style.configure("Modern.TLabel", background=frame_bg, foreground=fg, font=('Segoe UI', 11))
        self.style.configure("Modern.Header.TLabel", font=('Segoe UI Semibold', 28), background=frame_bg, foreground=fg)
        self.style.configure("Modern.Subheader.TLabel", font=('Segoe UI', 13), background=frame_bg, foreground=fg)

        self.style.configure("Modern.TButton", background="#388E3C", foreground="#FFFFFF", borderwidth=0, padding=(10, 8), font=('Segoe UI', 10, 'bold'))
        self.style.map("Modern.TButton", background=[('active', '#2E7D32'), ('pressed', '#1B5E20')])

        self.style.configure("TEntry", fieldbackground=entry_bg, foreground=entry_fg, insertcolor=entry_insert, borderwidth=0, relief="flat", font=('Segoe UI', 10), padding=6)
        self.style.map("TEntry", fieldbackground=[('focus', '#ffffff')], foreground=[('focus', '#000000')])

        self.style.configure("TCombobox", fieldbackground=entry_bg, background=entry_bg, foreground=entry_fg, borderwidth=0, relief="flat", padding=6)
        self.style.map("TCombobox", fieldbackground=[('readonly', '#ffffff'), ('!readonly', entry_bg)])

        self.style.configure("TScrollbar", troughcolor=bg, background=frame_bg, arrowcolor=fg, borderwidth=0, relief="flat")
        self.style.configure("TRadiobutton", background=frame_bg, foreground=fg, font=('Segoe UI', 10))
        self.style.map("TRadiobutton", indicatorcolor=[('selected', accent), ('!selected', border)], background=[('active', frame_bg)])
        self.style.configure("TCheckbutton", background=frame_bg, foreground=fg)
        self.style.map("TCheckbutton", indicatorcolor=[('selected', accent), ('!selected', border)], background=[('active', frame_bg)])
        
        self.style.configure("Treeview", background=tree_bg, foreground=tree_fg, fieldbackground=tree_bg, font=('Segoe UI', 10), rowheight=28, borderwidth=0, relief='flat')
        self.style.map("Treeview", background=[('selected', tree_sel_bg)], foreground=[('selected', accent_fg if self.theme == 'dark' else fg)])
        self.style.configure("Treeview.Heading", background=bg, foreground=fg, relief="flat", borderwidth=0, padding=5)

        self.style.configure("TCombobox", fieldbackground=entry_bg, background=btn_bg, foreground=entry_fg, arrowcolor=fg, insertcolor=entry_insert, bordercolor=border)
        self.style.map('TCombobox', selectbackground=[('readonly', tree_sel_bg)], selectforeground=[('readonly', fg)])

        self.style.configure("TNotebook", background=bg, borderwidth=0, relief='flat')
        self.style.configure("TNotebook.Tab", background=frame_bg, foreground=fg, borderwidth=0, relief='flat', padding=(12, 8), font=('Segoe UI', 10, 'bold'))
        self.style.map("TNotebook.Tab",
                       background=[('selected', accent), ('!selected', frame_bg)],
                       foreground=[('selected', accent_fg), ('!selected', fg)])

        self.style.configure("Valve.Card.TFrame", background=frame_bg, borderwidth=1, relief="solid")
        self.style.map("Valve.Card.TFrame", bordercolor=[('!focus', accent), ('active', accent)])
        self.style.configure("Locked.Valve.Card.TFrame", background=locked_bg, bordercolor=emergency)

        if hasattr(self, 'root'):
            self.root.configure(bg=bg)

    def setup_ui(self):
        for widget in self.root.winfo_children():
            widget.destroy()
        self.root.configure(bg=self.style.lookup(".", "background"))

        self.setup_menu()

        top_frame = ttk.Frame(self.root, style="Modern.TFrame", padding=(30, 15, 30, 10))
        top_frame.pack(fill=tk.X, side=tk.TOP)

        header = ttk.Frame(top_frame, style="Modern.TFrame")
        header.pack(fill=tk.X, pady=(5, 2))
        ttk.Label(header, text="👨‍🌾", font=("Segoe UI Emoji", 36), style="Modern.Header.TLabel").pack(side=tk.LEFT, padx=(0, 15), pady=10)
        title_frame = ttk.Frame(header, style="Modern.TFrame")
        title_frame.pack(side=tk.LEFT, pady=10, anchor="w")
        ttk.Label(title_frame, text=constants.APP_NAME, style="Modern.Header.TLabel").pack(anchor="w")
        ttk.Label(title_frame, text="Automate and Monitor Your Irrigation System", style="Modern.Subheader.TLabel").pack(anchor="w")

        dash = ttk.Frame(top_frame, style="TFrame")
        dash.pack(fill=tk.X, pady=(15, 10))
        dash_font = ('Segoe UI Semibold', 11)
        self.dash_valves = ttk.Label(dash, text="Valves: -", style="TLabel", font=dash_font)
        self.dash_valves.pack(side=tk.LEFT, padx=10)
        self.dash_on = ttk.Label(dash, text="ON: -", style="TLabel", font=dash_font)
        self.dash_on.pack(side=tk.LEFT, padx=10)
        self.dash_logs = ttk.Label(dash, text="Logs: -", style="TLabel", font=dash_font)
        self.dash_logs.pack(side=tk.LEFT, padx=10)
        dash_right_frame = ttk.Frame(dash)
        dash_right_frame.pack(side=tk.RIGHT)
        # <-- Add the MQTT status label here
        self.mqtt_status_label = ttk.Label(dash_right_frame, textvariable=self.mqtt_status_var, font=dash_font)
        self.mqtt_status_label.pack(anchor='e')
        ttk.Label(dash_right_frame, textvariable=self.location_var, font=dash_font).pack(anchor='e')
        ttk.Label(dash_right_frame, textvariable=self.live_weather_var, font=dash_font).pack(anchor='e')
        ttk.Label(dash_right_frame, textvariable=self.system_time_var, font=dash_font).pack(anchor='e')

        top_controls_card = ttk.Labelframe(top_frame, text="System Controls & Search", style="Card.TFrame", padding=(15, 10))
        top_controls_card.pack(pady=10, fill=tk.X)
        add_search_frame = ttk.Frame(top_controls_card)
        add_search_frame.pack(pady=8, padx=8, fill=tk.X)
        add_frame = ttk.Frame(add_search_frame)
        add_frame.pack(side=tk.LEFT, padx=(0, 20))
        ttk.Label(add_frame, text=f"Valves to add (1-{constants.MAX_VALVES}):").pack(side=tk.LEFT, pady=(0, 3))
        self.valve_entry = ttk.Entry(add_frame, textvariable=self.valve_count_var, width=5, style="TEntry", font=('Segoe UI', 10))
        self.valve_entry.pack(side=tk.LEFT, padx=7)
        self.add_valves_btn = ttk.Button(add_frame, text="Add", command=self.add_valves, style="Accent.TButton")
        self.add_valves_btn.pack(side=tk.LEFT)
        utils.tooltip(self.add_valves_btn, "Add new valves (Ctrl+N)")
        search_frame = ttk.Frame(add_search_frame)
        search_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(search_frame, text="🔍 Search:", font=("Segoe UI Emoji", 12)).pack(side=tk.LEFT)
        self.search_entry = ttk.Entry(search_frame, textvariable=self.search_var, width=35, style="TEntry", font=('Segoe UI', 10))
        self.search_entry.pack(side=tk.LEFT, padx=6, fill=tk.X, expand=True)
        utils.tooltip(self.search_entry, "Search by name, note, 'on', 'off', or 'pin:X' (Ctrl+F)")
        self.search_entry.bind("<KeyRelease>", lambda _: self.filter_valves())
        btn_group_frame = ttk.Frame(top_controls_card)
        btn_group_frame.pack(pady=(8, 8), padx=8, fill=tk.X, expand=True)
        
        self.scheduler_btn = ttk.Button(btn_group_frame, text="Scheduler 📅", command=self.open_scheduler_window, style="Modern.TButton")
        self.scheduler_btn.pack(side=tk.LEFT, padx=5, pady=3, fill=tk.X, expand=True)
        utils.tooltip(self.scheduler_btn, "Ctrl+Alt+S")

        self.reset_valves_btn = ttk.Button(btn_group_frame, text="Reset All ♻️", command=self.reset_valves, style="Modern.TButton")
        self.reset_valves_btn.pack(side=tk.LEFT, padx=5, pady=3, fill=tk.X, expand=True)
        utils.tooltip(self.reset_valves_btn, "Ctrl+R")
        
        self.layout_toggle_btn = ttk.Button(btn_group_frame, text="Compact View" if self.layout_mode == "comfortable" else "Comfort View", command=self.toggle_layout_mode, style="Modern.TButton")
        self.layout_toggle_btn.pack(side=tk.LEFT, padx=5, pady=3, fill=tk.X, expand=True)
        utils.tooltip(self.layout_toggle_btn, "Toggle layout mode")

        self.emergency_off_btn = ttk.Button(btn_group_frame, text="🚨 Turn All Systems OFF", command=self.turn_all_systems_off, style="Emergency.TButton")
        self.emergency_off_btn.pack(side=tk.LEFT, padx=5, pady=3, fill=tk.X, expand=True)
        utils.tooltip(self.emergency_off_btn, "Immediately turns OFF all valves and aux controls.")

        # Modern style sticky controls
        self.add_valves_btn.config(style="Modern.TButton")
        self.valve_entry.configure(style="TEntry")
        self.search_entry.configure(style="TEntry")


        # Create a PanedWindow to hold the main content and the right-side panel
        self.main_pane = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL, style="TPanedwindow")
        self.main_pane.pack(fill=tk.BOTH, expand=True, padx=30, pady=(0, 10))
        
        # --- Create a Notebook (Tabs) for the main left-side view ---
        self.notebook = ttk.Notebook(self.main_pane, style="TNotebook")
        self.main_pane.add(self.notebook, weight=1)

        # --- Tab 1: Card View ---
        card_view_frame = ttk.Frame(self.notebook, style="TFrame", padding=10)
        self.notebook.add(card_view_frame, text=" 💳 Card View ")
        card_view_frame.rowconfigure(0, weight=1)
        card_view_frame.columnconfigure(0, weight=1)

        self.valve_canvas = tk.Canvas(card_view_frame, bg=self.style.lookup("Card.TFrame", "background"), highlightthickness=0)
        self.valve_vbar = ttk.Scrollbar(card_view_frame, orient="vertical", command=self.valve_canvas.yview)
        self.valve_canvas.configure(yscrollcommand=self.valve_vbar.set)
        self.valve_card_frame = ttk.Frame(self.valve_canvas, style="TFrame") # This frame holds the valve cards
        self.canvas_frame_id = self.valve_canvas.create_window((0, 0), window=self.valve_card_frame, anchor="nw")
        
        self.valve_vbar.grid(row=0, column=1, sticky="ns")
        self.valve_canvas.grid(row=0, column=0, sticky="nsew")
        self.valve_canvas.bind("<Configure>", self.on_valve_canvas_configure)
        self.valve_card_frame.bind("<Configure>", self.on_valve_frame_configure)
        self.valve_canvas.bind_all("<MouseWheel>", lambda e: self.valve_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))
        self.valve_canvas.bind_all("<Button-4>", lambda e: self.valve_canvas.yview_scroll(-1, "units"))
        self.valve_canvas.bind_all("<Button-5>", lambda e: self.valve_canvas.yview_scroll(1, "units"))
        self.valve_status_labels = []

        # --- Tab 2: Map View ---
        # Call the setup method we created, which returns the map frame
        if hasattr(self, 'map_view_frame') and self.map_view_frame and self.map_view_frame.winfo_exists():
            map_view_frame = self.map_view_frame
        else:
            map_view_frame = self._setup_map_view()
        self.notebook.add(map_view_frame, text=" 🗺️ Map View ")

        right_column_frame = ttk.Frame(self.main_pane, style="TFrame")
        self.main_pane.add(right_column_frame, weight=0)
        right_column_frame.pack_propagate(False)
        right_column_frame.rowconfigure(0, weight=1)
        right_column_frame.columnconfigure(0, weight=1)
        right_column_frame.columnconfigure(1, weight=1)
        aux_lf = ttk.Labelframe(right_column_frame, text="Auxiliary Controls", style="Card.TFrame", padding=10)
        aux_lf.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        self.aux_buttons_ui_elements = []
        for i, aux_data in enumerate(self.aux_controls):
            btn = ttk.Button(aux_lf, text="", command=lambda idx=i: self.toggle_aux_control(idx), compound=tk.LEFT)
            btn.pack(pady=5, padx=5, fill=tk.X, ipady=3)
            btn.bind("<Button-3>", lambda e, idx=i: self.rename_aux_control(idx))
            utils.tooltip(btn, f"Controls {aux_data['name']}. Right-click to rename. Schedule via Master Scheduler.")
            self.aux_buttons_ui_elements.append(btn)
        sensor_lf = ttk.Labelframe(right_column_frame, text="🌿 Live Sensor Data", style="Card.TFrame", padding=10)
        sensor_lf.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        sensor_lf.columnconfigure(1, weight=1)
        sensor_labels = [
            ("Temp (DHT22):", self.sensor_temp_c), ("Humidity (DHT22):", self.sensor_humidity),
            ("Temp (DHT11):", self.sensor_temp_c_dht11), ("Humidity (DHT11):", self.sensor_humidity_dht11),
            ("Soil Moisture:", self.sensor_moisture)
        ]
        for i, (text, var) in enumerate(sensor_labels):
            ttk.Label(sensor_lf, text=text, font=('Segoe UI', 10)).grid(row=i, column=0, sticky="w", padx=5, pady=4)
            ttk.Label(sensor_lf, textvariable=var, font=('Segoe UI', 10, 'bold')).grid(row=i, column=1, sticky="w", padx=5, pady=4)
        if not self.hardware.is_pi:
            ttk.Label(sensor_lf, text="(Simulation Mode)", font=('Segoe UI', 8, 'italic')).grid(row=len(sensor_labels), column=0, columnspan=2, pady=10)

        self.footer = ttk.Frame(self.root, style="TFrame", padding=(30, 5))
        self.footer.pack(fill=tk.X, side=tk.BOTTOM, pady=(5, 10))
        self.footer.columnconfigure(0, weight=1)
        self.footer_label = ttk.Label(self.footer, text="System Ready.", anchor="w", font=('Segoe UI', 10))
        self.footer_label.pack(side=tk.LEFT)
        
        self.lock_btn_footer = ttk.Button(self.footer, text="Lock Config 🔒", command=self.toggle_configuration_lock, style="TButton")
        self.lock_btn_footer.pack(side=tk.RIGHT, padx=5)
        
        theme_btn_footer = ttk.Button(self.footer, text="🌗 Theme", command=self.toggle_theme, style="TButton")
        theme_btn_footer.pack(side=tk.RIGHT, padx=5)
        utils.tooltip(theme_btn_footer, "Toggle Dark/Light Theme (Ctrl+T)")

        self.root.after(100, self._set_initial_sash)

    def _set_initial_sash(self):
        try:
            initial_pos = int(self.main_pane.winfo_width() * 0.7)
            self.main_pane.sashpos(0, initial_pos)
        except (tk.TclError, AttributeError):
            if hasattr(self, 'root') and self.root.winfo_exists():
                self.root.after(200, self._set_initial_sash)

    def setup_menu(self):
        
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Save Settings Now", command=self.save_state)
        file_menu.add_command(label="Import Config", command=self.import_config, accelerator="Ctrl+I")
        file_menu.add_command(label="Export Config", command=self.export_config, accelerator="Ctrl+E")
        file_menu.add_command(label="Save Log", command=self.save_log_manually, accelerator="Ctrl+Shift+S")
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.on_close)
        system_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="System", menu=system_menu)
        system_menu.add_command(label="Automation Rules", command=self.open_automation_window)
        system_menu.add_separator()
        system_menu.add_command(label="Application Settings", command=self.open_app_settings_window, accelerator="Ctrl+Shift+C")
        system_menu.add_command(label="System Logs", command=self.open_log_window)
        system_menu.add_separator()
        system_menu.add_command(label="Undo Remove", command=self.undo_remove, accelerator="Ctrl+Z")
        location_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Location", menu=location_menu)
        location_menu.add_command(label="Set Location...", command=self.set_location)
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="Sensor Connection Guide", command=self.show_sensor_connection_info)
        help_menu.add_command(label="About", command=self.show_about)

    def update_sensor_readings(self):
        temp_c, humidity = self.hardware.read_dht22()
        if isinstance(temp_c, (float, int)):
            self.sensor_temp_c.set(f"{temp_c:.1f}°C")
            self.sensor_humidity.set(f"{humidity:.1f}%")
        else:
            self.sensor_temp_c.set(str(temp_c))
            self.sensor_humidity.set(str(humidity))
        temp_c_dht11, humidity_dht11 = self.hardware.read_dht11()
        if isinstance(temp_c_dht11, (float, int)):
            self.sensor_temp_c_dht11.set(f"{temp_c_dht11:.1f}°C")
            self.sensor_humidity_dht11.set(f"{humidity_dht11:.1f}%")
        else:
            self.sensor_temp_c_dht11.set(str(temp_c_dht11))
            self.sensor_humidity_dht11.set(str(humidity_dht11))
        moisture_status = self.hardware.read_moisture()
        if moisture_status == "Wet": self.sensor_moisture.set(f"💧 Wet")
        elif moisture_status == "Dry": self.sensor_moisture.set(f"🔥 Dry")
        else: self.sensor_moisture.set(moisture_status)

        if hasattr(self, 'root') and self.root.winfo_exists():
            self.root.after(2000, self.update_sensor_readings)

    def show_sensor_connection_info(self):
        win = tk.Toplevel(self.root)
        win.title("Sensor Connection and Integration Guide")
        win.geometry("700x550")
        win.resizable(False, True)
        win.grab_set()

        bg = self.style.lookup(".", "background")
        fg = self.style.lookup(".", "foreground")
        win.configure(bg=bg)

        text_widget = tk.Text(win, wrap="word", font=("Segoe UI", 10), relief="flat",
                               bg=bg, fg=fg, bd=0, highlightthickness=0, padx=15, pady=15)
        text_widget.pack(expand=True, fill="both")

        text_widget.tag_configure("h1", font=("Segoe UI", 14, "bold"), spacing3=10)
        text_widget.tag_configure("h2", font=("Segoe UI", 11, "bold"), spacing1=15, spacing3=5)
        text_widget.tag_configure("code", font=("Consolas", 9), background=self.style.lookup("TEntry", "fieldbackground"))
        text_widget.tag_configure("pin", font=("Consolas", 9, "bold"), foreground=self.style.lookup("Accent.TButton", "background"))
        text_widget.tag_configure("lib", font=("Consolas", 9, "italic"))
        text_widget.tag_configure("sep", overstrike=True)

        text_widget.insert("end", "Farm Sensor Integration Guide\n", "h1")
        text_widget.insert("end", "This guide provides connection details for common sensors on a Raspberry Pi (BCM Pinout).\n\n")
        text_widget.insert("end", "--------------------------------------------------------------------------------------------------\n", "sep")
        text_widget.insert("end", "1. DHT11 / DHT22 (Temperature & Humidity)\n", "h2")
        text_widget.insert("end", " • VCC / + Pin: ", "code"); text_widget.insert("end", " Connect to 3.3V Power (Pin 1)\n")
        text_widget.insert("end", f" • Data Out (DHT22):", "code"); text_widget.insert("end", f" Connect to GPIO {constants.TEMP_HUMIDITY_SENSOR_PIN} (Pin 7)\n", "pin")
        text_widget.insert("end", f" • Data Out (DHT11):", "code"); text_widget.insert("end", f" Connect to GPIO {constants.TEMP_HUMIDITY_SENSOR_PIN_DHT11} (Pin 37)\n", "pin")
        text_widget.insert("end", " • GND / - Pin:  ", "code"); text_widget.insert("end", " Connect to Ground (e.g., Pin 9)\n")
        text_widget.insert("end", " • Library: ", "lib"); text_widget.insert("end", " pip install adafruit-circuitpython-dht\n")
        text_widget.insert("end", "Note: A 10kΩ pull-up resistor between the VCC and Data lines is recommended for stability.\n")
        text_widget.insert("end", "--------------------------------------------------------------------------------------------------\n", "sep")
        text_widget.insert("end", "2. Capacitive Soil Moisture Sensor\n", "h2")
        text_widget.insert("end", " • VCC Pin: ", "code"); text_widget.insert("end", " Connect to 3.3V Power (Pin 17)\n")
        text_widget.insert("end", f" • DO Pin (Digital):", "code"); text_widget.insert("end", f" Connect to GPIO {constants.MOISTURE_SENSOR_PIN} (Pin 38)\n", "pin")
        text_widget.insert("end", " • GND Pin: ", "code"); text_widget.insert("end", " Connect to Ground (e.g., Pin 20)\n")
        text_widget.insert("end", "Note: The threshold for the digital output (DO) can be adjusted using the onboard potentiometer.\n")

        text_widget.config(state="disabled")

    def turn_all_systems_off(self):
        if not messagebox.askyesno("Confirm Emergency Stop", "Turn OFF all valves and auxiliary controls immediately?\n\nSchedules remain unaffected.", icon='warning', parent=self.root): return
        off_count = 0
        for items, item_type_name in [(self.valves, "Valve"), (self.aux_controls, "Auxiliary Control")]:
            for item_idx, item in enumerate(items):
                if item.get("status"):
                    item["status"] = False
                    self.hardware.set_pin_state(item['pin'], False)
                    if item_type_name == "Valve": self._update_valve_on_time_end(item_idx)
                    ts = datetime.datetime.now().isoformat(sep=' ', timespec='seconds')
                    if item_type_name == "Valve": item.setdefault("history", []).append((ts, "Emergency System Stop OFF"))
                    self.log(f"{item_type_name} '{item['name']}' turned OFF by emergency stop.")
                    off_count += 1
        if off_count > 0:
            self.save_state()
            self.filter_valves()
            self.update_aux_controls_ui()
            self.update_dashboard()
            self.notify(f"Emergency Stop: {off_count} system(s) turned OFF.", duration=5000)
        else:
            self.notify("Emergency Stop: No systems were active.", duration=3000)

    def on_valve_canvas_configure(self, event):
        canvas_width = event.width
        self.valve_canvas.itemconfig(self.canvas_frame_id, width=canvas_width)
        if hasattr(self, '_resize_job'):
            self.root.after_cancel(self._resize_job)
        self._resize_job = self.root.after(50, self.render_valves_grid)

    def on_valve_frame_configure(self, event):
        self.valve_canvas.configure(scrollregion=self.valve_canvas.bbox("all"))

    def render_valves_grid(self):
        self.valve_status_labels.clear()
        for widget in self.valve_card_frame.winfo_children():
            widget.destroy()

        # layout style switching
        if self.layout_mode == "compact":
            card_padding = 8
            font_base = ('Segoe UI', 10)
            label_font = ('Segoe UI', 9)
            info_font = ('Segoe UI', 8)
        else:
            card_padding = 12
            font_base = ('Segoe UI', 12)
            label_font = ('Segoe UI', 10)
            info_font = ('Segoe UI', 9)

        if not self.filtered_valves:
            no_valves_frame = ttk.Frame(self.valve_card_frame, style="TFrame")
            no_valves_frame.pack(padx=20, pady=40)
            ttk.Label(no_valves_frame, text="📭", font=("Segoe UI Emoji", 48)).pack()
            ttk.Label(no_valves_frame, text="No valves configured or matching search.", font=('Segoe UI', 12, 'italic')).pack(pady=10)
        else:
            card_min_width = 260
            canvas_width = self.valve_canvas.winfo_width()
            num_columns = max(1, canvas_width // card_min_width)
            for idx, valve_data in enumerate(self.filtered_valves):
                try:
                    orig_idx = self.valves.index(valve_data)
                except ValueError:
                    self.log(f"Warn: Valve data inconsistency during render: {valve_data.get('name')}")
                    continue

                row, col = divmod(idx, num_columns)
                card_style = "Locked.Valve.Card.TFrame" if valve_data.get("locked") else "Valve.Card.TFrame"
                card = ttk.Frame(self.valve_card_frame, style=card_style, padding=card_padding)
                card.grid(row=row, column=col, padx=10, pady=10, sticky="nsew")
                self.valve_card_frame.columnconfigure(col, weight=1)

                is_on = valve_data.get("status")
                icon = valve_data.get("icon", "💧")
                status_txt = "🟢" if is_on else ("🔴" if valve_data.get("locked") and is_on else "⚪")
                status_color = "#81C784" if is_on else ("#E57373" if valve_data.get("locked") else self.style.lookup("TLabel", "foreground"))

                header_frame = ttk.Frame(card, style=card_style.replace("Valve.Card", "T"))
                header_frame.pack(fill=tk.X, pady=(0, 8))
                status_lbl = ttk.Label(header_frame, text=status_txt, style="TLabel", foreground=status_color, font=("Segoe UI Emoji", 16 if self.layout_mode == "comfortable" else 14))
                status_lbl.pack(side=tk.LEFT, padx=(0, 8))
                utils.tooltip(status_lbl, f"Valve ON" if is_on else f"Valve OFF { '(Locked)' if valve_data.get('locked') else ''}")
                self.valve_status_labels.append(status_lbl)
                ttk.Label(header_frame, text=f"{icon} {valve_data['name']}", font=(font_base[0], font_base[1] + 2, 'bold')).pack(side=tk.LEFT, anchor="w")

                ttk.Button(card, text="Toggle Status", command=lambda i=orig_idx: self.toggle_valve(i), style="Valve.Toggle.TButton").pack(fill=tk.X, pady=(0, 10))
                ttk.Label(card, textvariable=valve_data["timer_var"], font=('Segoe UI', 9, 'italic'), foreground=self.style.lookup("Accent.TButton", "background")).pack(anchor="w")

                info_frame = ttk.Frame(card, style=card_style.replace("Valve.Card", "T"))
                info_frame.pack(fill=tk.X, pady=(5, 10))
                ttk.Label(info_frame, text=f"Pin: {valve_data['pin']}", font=label_font).pack(anchor="w")
                num_schedules = len(valve_data.get('schedules', []))
                sched_txt = f"⏰ {num_schedules} schedule(s) set" if num_schedules > 0 else "⏰ Not Scheduled"
                sl = ttk.Label(info_frame, text=sched_txt, font=(info_font[0], info_font[1], "italic"), anchor="w", wraplength=180)
                sl.pack(anchor="w", fill=tk.X)
                utils.tooltip(sl, "Open Master Scheduler to view/edit schedules")
                note = valve_data.get('note', '')
                if note:
                    nl = ttk.Label(info_frame, text=f"📝 {note[:25]}{'...' if len(note)>25 else ''}", font=(info_font[0], info_font[1], "italic"), foreground="#B0BEC5" if self.theme == "dark" else "#78909C", anchor="w")
                    nl.pack(anchor="w", fill=tk.X)
                    utils.tooltip(nl, f"Note: {note}")

                btns_frame = ttk.Frame(card, style=card_style.replace("Valve.Card", "T"))
                btns_frame.pack(fill=tk.X, pady=(5, 0))
                
                remove_btn_state = "disabled" if self.is_config_locked.get() else "normal"

                action_buttons = [
                    ("✏️", lambda i=orig_idx: self.rename_valve(i), "Rename", "normal"), 
                    ("🗑️", lambda i=orig_idx: self.remove_valve(i), "Remove", remove_btn_state),
                    ("🔒" if not valve_data.get("locked") else "🔓", lambda i=orig_idx: self.toggle_lock(i), "Lock/Unlock", "normal"),
                    ("📝", lambda i=orig_idx: self.edit_note(i), "Note", "normal"), 
                    ("📋", lambda i=orig_idx: self.copy_valve(i), "Copy Cfg", "normal"),
                    ("📈", lambda i=orig_idx: self.show_valve_history(i), "History", "normal"), 
                    ("⚙️", lambda i=orig_idx: self.open_valve_settings_window(i), "Settings", "normal"),
                    ("📊", lambda i=orig_idx: self.show_valve_stats(i), "Stats", "normal")
                ]
                for txt, cmd, tip, state in action_buttons:
                    b = ttk.Button(btns_frame, text=txt, command=cmd, width=4, style="TButton", state=state)
                    b.pack(side=tk.LEFT, padx=2, pady=2, fill=tk.X, expand=True)
                    utils.tooltip(b, tip)

        self.valve_card_frame.update_idletasks()
        self.valve_canvas.config(scrollregion=self.valve_canvas.bbox("all"))

    def show_valve_stats(self, idx):
        valve = self.valves[idx]
        total_on_s = valve.get("total_on_time_seconds", 0)
        last_on_ts_iso = valve.get("last_on_timestamp")
        last_on_dur_s = valve.get("last_on_duration_seconds")
        last_on_str = datetime.datetime.fromisoformat(last_on_ts_iso).strftime("%Y-%m-%d %H:%M:%S") if last_on_ts_iso else "N/A"
        flow_rate = float(valve.get("flow_rate_lpm", 0.0))
        est_usage = (total_on_s / 60.0) * flow_rate if flow_rate > 0 else 0.0
        msg = (f"📊 Stats for {valve['name']} (Pin {valve['pin']})\n{'-'*50}\n"
               f"Total ON Time: {utils.format_duration(total_on_s)}\n"
               f"Last ON: {last_on_str}\nLast ON Duration: {utils.format_duration(last_on_dur_s)}\n"
               f"Est. Flow Rate: {flow_rate:.2f} L/min\nTotal Est. Water Used: {est_usage:.2f} Liters")
        messagebox.showinfo(f"Stats: {valve['name']}", msg, parent=self.root)

    def update_aux_controls_ui(self):
        for i, aux_data in enumerate(self.aux_controls):
            if i < len(self.aux_buttons_ui_elements):
                btn = self.aux_buttons_ui_elements[i]
                state = aux_data.get("status", False)
                dot = "🟢" if state else "⚪"
                num_schedules = len(aux_data.get('schedules', []))
                sched_txt = f"\n⏰ {num_schedules} schedule(s)" if num_schedules > 0 else ""
                btn_txt = f"{dot} {aux_data['name']} (Pin {aux_data['pin']}){sched_txt}"
                btn.config(text=btn_txt)
                btn.config(style="Accent.TButton" if state else "TButton")


    def add_valves(self):
        if self.is_config_locked.get():
            self.notify("Configuration is locked. Cannot add valves.", 4000)
            return
        try:
            count = int(self.valve_count_var.get())
            if not (1 <= count <= constants.MAX_VALVES):
                raise ValueError
        except ValueError:
            self.notify(f"Invalid input. Please enter a number (1-{constants.MAX_VALVES}).")
            return

        if len(self.valves) + count > constants.MAX_VALVES:
            self.notify(f"Cannot add {count} valve(s). Max is {constants.MAX_VALVES}.")
            return

        used_pins = {v["pin"] for v in self.valves}
        avail_pins = [p for p in constants.GPIO_PINS if p not in used_pins]

        if len(avail_pins) < count:
            self.notify(f"Not enough unique GPIO pins available.")
            return

        for _ in range(count):
            pin_to_assign = avail_pins.pop(0)
            existing_names = {v["name"] for v in self.valves}
            valve_num = 1
            new_valve_name = f"Valve {valve_num}"
            while new_valve_name in existing_names:
                valve_num += 1
                new_valve_name = f"Valve {valve_num}"

            new_valve = {"name": new_valve_name, "pin": pin_to_assign}
            self._initialize_valve_data(new_valve)
            for plant, emoji in constants.PLANT_EMOJIS.items():
                if plant in new_valve_name.lower():
                    new_valve["icon"] = emoji
                    break
            self.valves.append(new_valve)
            self.log(f"Added Valve: {new_valve_name} (Pin {pin_to_assign})")

        self.save_state()
        self.filter_valves()
        self.notify(f"Successfully added {count} valve(s).")
        self.update_dashboard()

    def reset_valves(self):
        if self.is_config_locked.get():
            self.notify("Configuration is locked. Cannot reset valves.", 4000)
            return
        if not self.valves or not messagebox.askyesno("Reset All", "Remove ALL valves & schedules?", icon='warning'):
            return
        self.clear_all_pending_schedules()
        for v_data in self.valves:
            self.hardware.set_pin_state(v_data['pin'], False)
        self.log("Resetting all valves.")
        self.valves.clear()
        self.undo_stack.clear()
        self.save_state()
        self.filter_valves()
        self.notify("All valves removed.")
        self.update_dashboard()

    def export_config(self):
        fp = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")], title="Export Config")
        if not fp: return
        try:
            valves_to_export = [v.copy() for v in self.valves]
            for v in valves_to_export: v.pop("timer_var", None)
            data = {"valves": valves_to_export, "aux_controls": self.aux_controls, "automation_rules": self.automation_rules,
                    "schedule_history": self.schedule_history, "logs": self.logs, "theme": self.theme,
                    "location": self.location, "enable_rain_skip": self.settings.get("enable_rain_skip")}
            with open(fp, "w", encoding='utf-8') as f: json.dump(data, f, indent=4)
            self.notify(f"Config exported to {os.path.basename(fp)}")
        except Exception as e:
            self.notify(f"Export failed: {e}")

    def import_config(self):
        if self.is_config_locked.get():
            self.notify("Configuration is locked. Cannot import.", 4000)
            return
        if (self.valves or self.aux_controls) and not messagebox.askyesno("Import Config", "Overwrite current config?", icon='warning'):
            return
        fp = filedialog.askopenfilename(filetypes=[("JSON", "*.json")], title="Import Config")
        if not fp: return
        try:
            with open(fp, "r", encoding='utf-8') as f: data = json.load(f)

            self.clear_all_pending_schedules()
            for item in self.valves + self.aux_controls: self.hardware.set_pin_state(item['pin'], False)

            self.valves = data.get("valves", [])
            for v in self.valves: self._initialize_valve_data(v)

            self.aux_controls = data.get("aux_controls", [])
            self.automation_rules = data.get("automation_rules", [])
            self.schedule_history = data.get("schedule_history", [])
            self.location = data.get("location", "London,UK")
            self.settings.set("location", self.location)
            self.settings.set("enable_rain_skip", data.get("enable_rain_skip", True))
            new_theme = data.get("theme", self.theme)

            self.save_state()
            self.log(f"Config imported from {os.path.basename(fp)}.")
            if self.theme != new_theme:
                self.theme = new_theme
                self.apply_theme()

            self.setup_ui()
            self.update_location_data()
            self._activate_all_schedules()
            self.filter_valves()
            self.update_aux_controls_ui()
            self.update_dashboard()
            self.notify(f"Config imported from {os.path.basename(fp)}")
        except Exception as e:
            self.notify(f"Import failed: {e}")

    def rename_valve(self, idx):
        valve = self.valves[idx]
        old_name = valve["name"]
        new_name = simpledialog.askstring("Rename Valve", f"New name for '{old_name}':", initialvalue=old_name, parent=self.root)
        if new_name and new_name.strip() and new_name.strip() != old_name:
            new_name = new_name.strip()[:32]
            if new_name in [v["name"] for v in self.valves if v is not valve]:
                self.notify(f"Error: Name '{new_name}' is already in use.", duration=4000)
                return
            valve["name"] = new_name
            for plant, emoji in constants.PLANT_EMOJIS.items():
                if plant in valve["name"].lower(): valve["icon"] = emoji; break
            else: valve["icon"] = '💧'
            self.save_state()
            self.filter_valves()
            self.notify(f"Valve '{old_name}' renamed.")

    def _setup_schedule_logic(self, item_obj, schedule_obj):
        job_id = schedule_obj['id']
        if job_id in self.scheduled_jobs:
            try: self.root.after_cancel(self.scheduled_jobs[job_id])
            except (tk.TclError, KeyError): pass

        is_cycle = schedule_obj['type'] == 'Cycle'
        turn_on = schedule_obj.get('action') == 'ON' if not is_cycle else True
        h, m = map(int, schedule_obj['time'].split(':'))
        schedule_skip_rainy = schedule_obj['skip_rainy']

        def runner():
            current_item_obj = self.find_item_by_pin(item_obj['pin'])
            if not current_item_obj:
                self.log(f"Scheduled task for pin {item_obj['pin']} skipped: item no longer exists.")
                if job_id in self.scheduled_jobs: del self.scheduled_jobs[job_id]
                return

            now = datetime.datetime.now()
            is_rainy = "rain" in self.live_weather_var.get().lower()
            if (turn_on or is_cycle) and schedule_skip_rainy and self.settings.get("enable_rain_skip") and is_rainy:
                self.log(f"Schedule for {current_item_obj['name']} skipped due to Rainy weather.")
            elif now.hour == h and now.minute == m:
                if not current_item_obj.get("locked"):
                    if is_cycle:
                        self.log(f"Cycle for '{current_item_obj['name']}' started.")
                        item_idx = self.valves.index(current_item_obj) if "flow_rate_lpm" in current_item_obj else self.aux_controls.index(current_item_obj)
                        self.toggle_item(item_idx, "valve" if "flow_rate_lpm" in current_item_obj else "aux", is_on=True)

                    elif current_item_obj["status"] != turn_on:
                        item_idx = self.valves.index(current_item_obj) if "flow_rate_lpm" in current_item_obj else self.aux_controls.index(current_item_obj)
                        self.toggle_item(item_idx, "valve" if "flow_rate_lpm" in current_item_obj else "aux", is_on=turn_on)

                self.log(f"Fixed time event for '{current_item_obj['name']}' fired. Removing schedule.")
                self.clear_schedule_by_id(job_id, reason="executed")
                return 
            self.scheduled_jobs[job_id] = self.root.after(constants.SCHEDULER_CHECK_INTERVAL_S * 1000, runner)
        self.scheduled_jobs[job_id] = self.root.after(1000, runner)
        self.log(f"Schedule armed for '{item_obj['name']}': {self.format_schedule_for_display(schedule_obj)}")

    def _update_valve_on_time_start(self, valve_idx):
        self.valves[valve_idx]["current_on_start_time"] = time.time()

    def _update_valve_on_time_end(self, valve_idx):
        valve = self.valves[valve_idx]
        if valve.get("current_on_start_time"):
            on_duration = time.time() - valve["current_on_start_time"]
            valve["total_on_time_seconds"] = valve.get("total_on_time_seconds", 0) + on_duration
            valve["last_on_duration_seconds"] = on_duration
            valve["last_on_timestamp"] = datetime.datetime.now().isoformat()
            flow_rate = float(valve.get("flow_rate_lpm", 0.0))
            if flow_rate > 0:
                water_used = (on_duration / 60.0) * flow_rate
                valve["estimated_water_usage_liters"] = valve.get("estimated_water_usage_liters", 0.0) + water_used
            valve["current_on_start_time"] = None

    def _activate_all_schedules(self):
        self.log("Startup: Activating stored schedules...")
        self.scheduled_jobs = {}
        count = 0
        for item in self.valves + self.aux_controls:
            for schedule in item.get("schedules", []):
                try:
                    self._setup_schedule_logic(item, schedule)
                    count += 1
                except Exception as e:
                    self.log(f"Error re-activating schedule {schedule.get('id')} for '{item.get('name')}': {e}")
        self.log(f"Re-activated {count} schedule(s).")

    def set_schedule_for_item(self, item_type, item_idx, schedule_id, details):
        target_list = self.valves if item_type == "valve" else self.aux_controls
        item_obj = target_list[item_idx]

        try:
            if details['type'] == "Fixed Time":
                time_str = details['time_str']
                if details['time_preset'] != "Custom": time_str = self.settings.get(f"virtual_{details['time_preset'].lower()}_time")
                h, m = map(int, time_str.split(':'))
                if not (0 <= h <= 23 and 0 <= m <= 59): raise ValueError("Invalid time")
                new_schedule = {"type": "Fixed Time", "action": details['action'], "time": f"{h:02d}:{m:02d}", "skip_rainy": details['skip_rainy']}
            elif details['type'] == "Cycle":
                start_time = details['cycle_start_time']
                if details['cycle_start_preset'] != "Custom": start_time = self.settings.get(f"virtual_{details['cycle_start_preset'].lower()}_time")
                h, m = map(int, start_time.split(':'))
                on_m, off_m, count = int(details['cycle_on_min']), int(details['cycle_off_min']), int(details['cycle_count'])
                if not (0 <= h <= 23 and 0 <= m <= 59 and on_m > 0 and off_m > 0 and count >= 0): raise ValueError("Invalid cycle params")
                new_schedule = {"type": "Cycle", "time": f"{h:02d}:{m:02d}", "on_m": on_m, "off_m": off_m, "count": count, "skip_rainy": details['cycle_skip_rainy']}
            else: return False
        except (ValueError, TypeError): return False

        if schedule_id: 
            for i, sched in enumerate(item_obj["schedules"]):
                if sched['id'] == schedule_id: new_schedule['id'] = schedule_id; item_obj["schedules"][i] = new_schedule; break
        else: 
            new_schedule['id'] = f"sched_{int(time.time() * 1000)}_{random.randint(100, 999)}"
            item_obj.setdefault("schedules", []).append(new_schedule)

        self._setup_schedule_logic(item_obj, new_schedule)
        self.save_state()
        if item_type == "valve": self.filter_valves()
        else: self.update_aux_controls_ui()
        if self.scheduler_window and self.scheduler_window.winfo_exists(): self.scheduler_window._populate_all_schedule_views()
        return True

    def clear_schedule_by_id(self, schedule_id, reason="manual"):
        schedule_obj, item_obj = self.find_schedule_by_id(schedule_id)
        if schedule_obj and item_obj:
            if reason == "executed":
                history_entry = {"name": item_obj['name'], "details": self.format_schedule_for_display(schedule_obj), "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
                self.schedule_history.insert(0, history_entry)
                if len(self.schedule_history) > 200: self.schedule_history = self.schedule_history[:200]
            if schedule_id in self.scheduled_jobs:
                try: self.root.after_cancel(self.scheduled_jobs.pop(schedule_id))
                except (tk.TclError, KeyError): pass
            item_obj["schedules"] = [s for s in item_obj["schedules"] if s['id'] != schedule_id]
            self.log(f"Schedule '{schedule_id}' for '{item_obj['name']}' cleared.")
            self.save_state()
            self.filter_valves()
            self.update_aux_controls_ui()
            return True
        return False

    def clear_all_schedules_for_item(self, item_type, item_idx):
        target_list = self.valves if item_type == "valve" else self.aux_controls
        item_obj = target_list[item_idx]
        for schedule in list(item_obj.get("schedules", [])): self.clear_schedule_by_id(schedule['id'])

    def clear_all_pending_schedules(self):
        for item in self.valves + self.aux_controls:
            for schedule in list(item.get("schedules", [])): self.clear_schedule_by_id(schedule['id'])
        self.log("Cleared all pending schedules from all devices.")

    def toggle_aux_control(self, idx):
        self.toggle_item(idx, "aux")

    def toggle_item(self, idx, item_type, is_on=None, duration_min=None):
        item_list = self.valves if item_type == "valve" else self.aux_controls
        item = item_list[idx]

        if item.get("locked"): self.notify(f"'{item['name']}' is locked."); return
        new_status = not item.get("status", False) if is_on is None else is_on
        item["status"] = new_status
        self.hardware.set_pin_state(item['pin'], new_status)
        action_str = "ON" if new_status else "OFF"
        log_msg = f"Manual {action_str}"

        if item_type == "valve":
            if new_status:
                self._update_valve_on_time_start(idx)
                if duration_min:
                    duration_ms = duration_min * 60 * 1000
                    self.root.after(duration_ms, lambda: self.toggle_valve_off_by_rule(idx))
                    log_msg = f"Auto ON for {duration_min} min by Rule"
            else: self._update_valve_on_time_end(idx)
            ts = datetime.datetime.now().isoformat(sep=' ', timespec='seconds')
            item.setdefault("history", []).append((ts, log_msg))
        self.log(f"{item_type.title()} '{item['name']}' (Pin {item['pin']}) toggled {action_str}.")
        self.save_state()
        if item_type == "valve": self.filter_valves()
        else: self.update_aux_controls_ui()
        self.update_dashboard()

        # If the map view exists, redraw it to reflect the status change
        if hasattr(self, 'map_canvas') and self.map_canvas.winfo_exists():
            self._draw_map_sections()

    def rename_aux_control(self, idx):
        aux = self.aux_controls[idx]
        old_name = aux['name']
        new_name = simpledialog.askstring("Rename Aux", f"New name for '{old_name}':", initialvalue=old_name, parent=self.root)
        if new_name and new_name.strip() and new_name.strip() != old_name:
            new_name = new_name.strip()[:32]
            if new_name in [a["name"] for a in self.aux_controls if a is not aux]:
                self.notify(f"Error: Name '{new_name}' is already in use.", duration=4000)
                return
            aux['name'] = new_name
            self.save_state()
            self.update_aux_controls_ui()
            self.log(f"Aux control renamed to '{new_name}'.")

    def save_state(self):
        """Prepares a clean copy of the data and saves it to the settings file."""
        # Create a deep copy of the valves list to avoid modifying the live UI data.
        valves_to_save = [v.copy() for v in self.valves]
        
        # IMPORTANT: Remove the non-serializable 'timer_var' from each valve's copy.
        for v in valves_to_save:
            v.pop("timer_var", None)
            
        # Now, set the sanitized data in the settings object.
        self.settings.set("valves", valves_to_save)
        self.settings.set("aux_controls", self.aux_controls)
        self.settings.set("automation_rules", self.automation_rules)
        self.settings.set("schedule_history", self.schedule_history)
        self.settings.set("logs", self.logs)

    def on_close(self):
        self.log("Application closing. Saving state.")
        self.save_state()
        self.hardware.cleanup()
        for job_id in self.root.tk.call('after', 'info'):
            self.root.after_cancel(job_id)
        self.root.destroy()

    def toggle_valve(self, idx, duration_min=None):
        self.toggle_item(idx, "valve", duration_min=duration_min)

    def toggle_valve_off_by_rule(self, idx):
        if self.valves[idx].get("status"):
            self.toggle_item(idx, "valve", is_on=False)
            self.log(f"Valve '{self.valves[idx]['name']}' automatically turned OFF by rule.")

    def toggle_lock(self, idx):
        valve = self.valves[idx]
        valve["locked"] = not valve.get("locked", False)
        status = "locked" if valve["locked"] else "unlocked"
        self.log(f"Valve '{valve['name']}' is {status}.")
        self.save_state()
        self.filter_valves()
        self.notify(f"Valve '{valve['name']}' {status}.")

    def remove_valve(self, idx):
        if self.is_config_locked.get():
            self.notify("Configuration is locked. Cannot remove valves.", 4000)
            return
        valve = self.valves[idx]
        if not messagebox.askyesno("Remove", f"Remove '{valve['name']}' & all its schedules?", icon='warning'): return
        self.clear_all_schedules_for_item("valve", idx)
        self.hardware.set_pin_state(valve['pin'], False)
        rem_copy = self.valves.pop(idx)
        self.undo_stack.append(rem_copy.copy())
        self.log(f"Valve '{rem_copy['name']}' removed.")
        self.save_state()
        self.filter_valves()
        self.notify(f"Valve '{rem_copy['name']}' removed.")
        self.update_dashboard()

    def undo_remove(self):
        if self.is_config_locked.get():
            self.notify("Configuration is locked. Cannot undo.", 4000)
            return
        if not self.undo_stack: self.notify("Nothing to undo."); return
        if len(self.valves) >= constants.MAX_VALVES: self.notify(f"Max valves reached. Cannot restore."); return
        valve_to_restore = self.undo_stack.pop()
        current_pins = {v['pin'] for v in self.valves}
        if valve_to_restore['pin'] in current_pins:
            available_pins = [p for p in constants.GPIO_PINS if p not in current_pins]
            if not available_pins:
                self.notify(f"Cannot restore '{valve_to_restore['name']}': Pin taken and no free pins.", duration=4000)
                self.undo_stack.append(valve_to_restore) 
                return
            valve_to_restore['pin'] = available_pins[0]
        
        self.valves.append(valve_to_restore)
        self._initialize_valve_data(valve_to_restore)
        
        self._activate_all_schedules()
        self.save_state()
        self.filter_valves()
        self.notify(f"Valve '{valve_to_restore['name']}' restored.")
        self.update_dashboard()

    def edit_note(self, idx):
        valve = self.valves[idx]
        new_note = simpledialog.askstring("Edit Note", f"Note for '{valve['name']}':", initialvalue=valve.get("note", ""), parent=self.root)
        if new_note is not None and new_note.strip() != valve.get("note", ""):
            valve["note"] = new_note.strip()[:128]
            self.log(f"Note for '{valve['name']}' updated.")
            self.save_state()
            self.filter_valves()
            self.notify(f"Note for '{valve['name']}' updated.")

    def copy_valve(self, idx):
        valve = self.valves[idx]
        try:
            valve_copy = valve.copy()
            valve_copy.pop("timer_var", None)
            v_json = json.dumps(valve_copy, indent=2)
            self.root.clipboard_clear()
            self.root.clipboard_append(v_json)
            self.notify(f"Config for '{valve['name']}' copied to clipboard.")
        except Exception as e:
            self.notify("Copy failed."); self.log(f"Error copying valve config: {e}")

    def show_valve_history(self, idx):
        valve = self.valves[idx]
        hist = valve.get("history", [])
        msg = f"History for {valve['name']} (Pin {valve['pin']}):\n{'-'*50}\n\n"
        if not hist: msg += "No history entries."
        else: msg += "\n".join([f"• {ts}: {ev}" for ts, ev in reversed(hist[-25:])])
        if len(hist) > 25: msg += f"\n\n(...and {len(hist)-25} older entries not shown)"
        messagebox.showinfo(f"History: {valve['name']}", msg, parent=self.root)

    def save_log_manually(self):
        if not self.logs: self.notify("No logs to save."); return
        fp = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Text", "*.txt")], title="Save Logs")
        if not fp: return
        try:
            with open(fp, "w", encoding='utf-8') as f: f.write("\n".join(self.logs))
            self.notify("Logs saved to " + os.path.basename(fp))
        except Exception as e:
            self.notify(f"Failed to save logs: {e}")

    def focus_search(self):
        self.search_entry.focus_set()
        self.search_entry.select_range(0, tk.END)

    def filter_valves(self, _=None):
        q = self.search_var.get().strip().lower()
        if not q: self.filtered_valves = self.valves[:]
        else:
            self.filtered_valves = [v for v in self.valves if q in v["name"].lower() or
                                    (q == "on" and v.get("status")) or (q == "off" and not v.get("status")) or
                                    q in v.get("note", "").lower() or (f"pin:{v['pin']}" == q)]
        self.render_valves_grid()
        self.update_dashboard()

    # ADD THESE THREE METHODS
    def process_log_queue(self):
        """Processes messages from the thread-safe log queue."""
        try:
            while not self.log_queue.empty():
                msg = self.log_queue.get_nowait()
                self._log_to_ui(msg)  
        except Exception:
            pass # Ignore if queue is empty
        self.root.after(100, self.process_log_queue)


    def process_status_queue(self):
        """Processes status updates from the thread-safe status queue."""
        try:
            while not self.status_queue.empty():
                status, color = self.status_queue.get_nowait()
                self._set_mqtt_status_ui(status, color)
        except Exception:
            pass # Ignore if queue is empty
        self.root.after(200, self.process_status_queue)

    def log(self, msg):
        """
        Thread-safe logging method. Puts a message into a queue
        to be processed by the main GUI thread.
        """
        self.log_queue.put(msg)

    def _log_to_ui(self, msg):
        """
        The original log logic, now private. It should only be called
        by the main thread via process_log_queue.
        """
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = f"[{ts}] {msg}"
        self.logs.append(entry)
        if len(self.logs) > 500: self.logs = self.logs[-300:]
        if self.log_window and self.log_window.winfo_exists():
            self.log_window.add_log_entry(entry)
        if hasattr(self, 'dash_logs') and self.dash_logs.winfo_exists():
            self.update_dashboard()

    def notify(self, msg, duration=3500):
            if not hasattr(self, 'footer_label') or not self.footer_label.winfo_exists(): return
            self.footer_label.config(text=f"🔔 {msg}", foreground=self.style.lookup("Accent.TButton", "background"))
            if hasattr(self, '_notify_job_id'): self.root.after_cancel(self._notify_job_id)
            self._notify_job_id = self.root.after(duration, self._clear_notify_message)

    def _clear_notify_message(self):
        if hasattr(self, 'footer_label') and self.footer_label.winfo_exists():
            self.footer_label.config(text="System Ready.", foreground=self.style.lookup("TLabel", "foreground"))

    def update_dashboard(self):
        if not hasattr(self, 'dash_valves') or not self.dash_valves.winfo_exists(): return
        v_on = sum(1 for v in self.valves if v.get("status"))
        aux_on = sum(1 for a in self.aux_controls if a.get("status"))
        self.dash_valves.config(text=f"Valves: {len(self.valves)}")
        self.dash_on.config(text=f"Total ON: {v_on + aux_on} (Valves: {v_on}, Aux: {aux_on})")
        self.dash_logs.config(text=f"Log Entries: {len(self.logs)}")
        for v in self.valves:
            if v.get("status") and v.get("current_on_start_time"):
                elapsed = time.time() - v["current_on_start_time"]
                v["timer_var"].set(f"ON for: {utils.format_duration(elapsed)}")
            else: v["timer_var"].set("")

    def check_automation_rules(self):
        now = time.time()
        for i, rule in enumerate(self.automation_rules):
            if rule.get("last_triggered") and (now - rule["last_triggered"] < 300): continue 
            current_value, triggered = None, False
            if rule['sensor'] == 'Soil Moisture': current_value = self.sensor_moisture.get().split(' ')[-1]
            elif rule['sensor'] == 'Temp (DHT22)': 
                try: current_value = float(self.sensor_temp_c.get().split('°')[0]); 
                except: continue
            elif rule['sensor'] == 'Humidity (DHT22)': 
                try: current_value = float(self.sensor_humidity.get().split('%')[0]); 
                except: continue
            elif rule['sensor'] == 'Temp (DHT11)': 
                try: current_value = float(self.sensor_temp_c_dht11.get().split('°')[0]); 
                except: continue
            elif rule['sensor'] == 'Humidity (DHT11)': 
                try: current_value = float(self.sensor_humidity_dht11.get().split('%')[0]); 
                except: continue
            if current_value is None: continue

            try:
                rule_val = float(rule['value']) if rule['sensor'] != 'Soil Moisture' else rule['value']
                if rule['condition'] == 'is' and current_value == rule_val: triggered = True
                elif rule['condition'] == '>' and current_value > rule_val: triggered = True
                elif rule['condition'] == '<' and current_value < rule_val: triggered = True
                elif rule['condition'] == '==' and current_value == rule_val: triggered = True
            except (ValueError, TypeError): continue

            if triggered:
                self.log(f"Automation rule triggered: {AutomationWindow.format_rule_for_display(rule)}")
                self.automation_rules[i]['last_triggered'] = now
                target_type, target_name = rule['target'].split(': ')
                item_list = self.valves if target_type == 'Valve' else self.aux_controls
                for idx, item in enumerate(item_list):
                    if item['name'] == target_name:
                        action_on = rule['action'] == 'Turn ON'
                        if item.get("status") != action_on:
                            self.toggle_item(idx, target_type.lower(), is_on=action_on, duration_min=rule.get('duration_min'))
                        break
        if hasattr(self, 'root') and self.root.winfo_exists(): self.root.after(10000, self.check_automation_rules)

    def set_location(self):
        new_loc = simpledialog.askstring("Set Location", "Enter location (e.g., 'City,CountryCode'):", initialvalue=self.location, parent=self.root)
        if new_loc and new_loc.strip() != self.location:
            self.location = new_loc.strip()
            self.settings.set("location", self.location)
            self.log(f"Location set to {self.location}. Fetching new data.")
            self.update_location_data()

    def update_system_clock(self):
        """
        This method runs every second to update the main clock and now also
        handles the live update for all active valve timers.
        """
        # Update the main system clock display
        self.system_time_var.set(f"Time: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        # --- NEW TIMER LOGIC ---
        # Loop through all valves and update their timers if they are ON
        for valve in self.valves:
            if valve.get("status") and valve.get("current_on_start_time"):
                elapsed = time.time() - valve["current_on_start_time"]
                valve["timer_var"].set(f"ON for: {utils.format_duration(elapsed)}")
            elif not valve.get("status") and valve["timer_var"].get() != "":
                # If the valve is off, ensure its timer text is cleared
                valve["timer_var"].set("")
        # --- END OF NEW TIMER LOGIC ---

        # Publish the latest state to the web UI
        if self.mqtt_manager:
            self.mqtt_manager.publish_state()

        # Schedule this method to run again in 1 second
        if hasattr(self, 'root') and self.root.winfo_exists():
            self.root.after(1000, self.update_system_clock)

    def update_location_data(self):
        if self.api_key == "d7b8a4a58f2d8f3f8b9e8a7b9c8d7e6f": 
            self.live_weather_var.set("Weather: API Key Needed")
            if hasattr(self, 'root') and self.root.winfo_exists(): self.root.after(600000, self.update_location_data)
            return
        try:
            url = f"https://api.openweathermap.org/data/2.5/weather?q={self.location}&appid={self.api_key}&units=metric"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            weather_main, weather_desc = data['weather'][0]['main'], data['weather'][0]['description'].title()
            weather_icon = constants.WEATHER_ICONS.get(weather_main, "❔")
            temp = data['main']['temp']
            self.live_weather_var.set(f"Weather: {weather_icon} {weather_desc}, {temp:.1f}°C")
            self.location_var.set(f"Location: {data['name']}, {data['sys']['country']}")

            local_sunrise = datetime.datetime.fromtimestamp(data['sys']['sunrise'] + data.get('timezone', 0), tz=datetime.timezone.utc)
            local_sunset = datetime.datetime.fromtimestamp(data['sys']['sunset'] + data.get('timezone', 0), tz=datetime.timezone.utc)
            self.settings.set("virtual_sunrise_time", local_sunrise.strftime('%H:%M'))
            self.settings.set("virtual_sunset_time", local_sunset.strftime('%H:%M'))
            self.log(f"Live data updated for {self.location}.")
        except requests.exceptions.RequestException: self.live_weather_var.set("Weather: Network Error")
        except (KeyError, IndexError): self.live_weather_var.set("Weather: Invalid Location")
        if hasattr(self, 'root') and self.root.winfo_exists(): self.root.after(600000, self.update_location_data)

    def show_about(self):
        messagebox.showinfo(f"About {constants.APP_NAME}", f"{constants.APP_NAME} - v{constants.APP_VERSION}\n\nAdvanced Irrigation & Auxiliary Control.\n\nBuilt with Python & Tkinter.\n© 2024-2025 SmartFarm Solutions Inc.", parent=self.root)

    def find_schedule_by_id(self, schedule_id):
        for item in self.valves + self.aux_controls:
            for schedule in item.get("schedules", []):
                if schedule['id'] == schedule_id: return schedule, item
        return None, None
    
    def _setup_map_view(self):
        """Creates the UI for the Map View feature with scrollbars and edit controls."""
        # preserve scale when reopening after UI refresh
        self.map_scale = getattr(self, 'map_scale', 1.0)

        # Initialize instance variables for drawing/editing state
        self.is_in_draw_mode = False
        self.is_in_edit_mode = False
        self.current_polygon_points = []
        self.temp_draw_items = []

        # This frame will hold the map canvas and buttons
        self.map_view_frame = ttk.Frame(self.notebook, style="TFrame")
        # Configure grid layout for canvas and scrollbars
        self.map_view_frame.rowconfigure(1, weight=1)
        self.map_view_frame.columnconfigure(0, weight=1)
        
        # --- Map Control Buttons ---
        map_controls = ttk.Frame(self.map_view_frame, style="TFrame", padding=5)
        map_controls.grid(row=0, column=0, columnspan=2, sticky="ew")

        upload_btn = ttk.Button(map_controls, text="📂 Upload Map Image", command=self._upload_map_image)
        upload_btn.pack(side=tk.LEFT, padx=5)
        
        draw_btn = ttk.Button(map_controls, text="✏️ Draw New Zone", command=self._enter_draw_mode)
        draw_btn.pack(side=tk.LEFT, padx=5)

        edit_btn = ttk.Button(map_controls, text="🔧 Edit Zones", command=self._enter_edit_mode)
        edit_btn.pack(side=tk.LEFT, padx=5)

        zoom_in_btn = ttk.Button(map_controls, text="➕ Zoom In", command=self._zoom_in)
        zoom_in_btn.pack(side=tk.LEFT, padx=5)

        zoom_out_btn = ttk.Button(map_controls, text="➖ Zoom Out", command=self._zoom_out)
        zoom_out_btn.pack(side=tk.LEFT, padx=5)

        reset_zoom_btn = ttk.Button(map_controls, text="🔄 Reset Zoom", command=self._reset_zoom)
        reset_zoom_btn.pack(side=tk.LEFT, padx=5)

        # --- The Canvas and Scrollbars ---
        self.map_canvas = tk.Canvas(self.map_view_frame, bg=self.style.lookup("TEntry", "fieldbackground"), highlightthickness=0)
        # section double-click events are bound directly when sections are drawn with tags
        # self.map_canvas.bind("<Double-Button-1>", self._on_section_double_click)  # not used
        self.map_v_scroll = ttk.Scrollbar(self.map_view_frame, orient="vertical", command=self.map_canvas.yview)
        self.map_h_scroll = ttk.Scrollbar(self.map_view_frame, orient="horizontal", command=self.map_canvas.xview)
        self.map_canvas.configure(yscrollcommand=self.map_v_scroll.set, xscrollcommand=self.map_h_scroll.set)

        # Place widgets on the grid
        self.map_canvas.grid(row=1, column=0, sticky="nsew")
        self.map_v_scroll.grid(row=1, column=1, sticky="ns")
        self.map_h_scroll.grid(row=2, column=0, sticky="ew")

        # --- Load existing data ---
        self.map_view_data = self.settings.get("map_view_data", {"image_path": None, "sections": []})
        self.map_image = None
        self.map_image_original = None
        self.map_image_item = None
        self.map_scale = 1.0

        if self.map_view_data.get("image_path") and os.path.exists(self.map_view_data["image_path"]):
            self._load_map_image(self.map_view_data["image_path"])
            # preserve zoom when returning to map view
            self._render_map_image()
        
        self.root.after(100, self._draw_map_sections)
        return self.map_view_frame

    def _load_map_image(self, path):
        """Loads and stores original map image, then renders it at current zoom."""
        try:
            img = Image.open(path)
            self.map_image_original = img.convert("RGBA")
            # don't force reset on re-open. only reset on explicit reset action.
            self.map_view_data["image_path"] = path
            self.settings.set("map_view_data", self.map_view_data)
            self._render_map_image()
            self.log(f"Map image loaded from {path}")
        except Exception as e:
            self.log(f"Error loading map image: {e}")
            messagebox.showerror("Error", f"Could not load map image from {path}.\n\n{e}", parent=self.root)

    def _render_map_image(self):
        if not self.map_image_original:
            return

        width, height = self.map_image_original.size
        scaled_w = max(1, int(width * self.map_scale))
        scaled_h = max(1, int(height * self.map_scale))

        resized = self.map_image_original.resize((scaled_w, scaled_h), Image.LANCZOS)
        self.map_image = ImageTk.PhotoImage(resized)

        if self.map_image_item:
            self.map_canvas.delete(self.map_image_item)

        self.map_image_item = self.map_canvas.create_image(0, 0, anchor="nw", image=self.map_image)
        self.map_canvas.tag_lower(self.map_image_item)

        self.map_canvas.config(scrollregion=(0, 0, scaled_w, scaled_h))
        self._draw_map_sections()

    def _set_map_scale(self, scale):
        old_scale = self.map_scale
        self.map_scale = max(0.2, min(4.0, scale))
        if abs(self.map_scale - old_scale) < 1e-6:
            return

        self._render_map_image()
        self.map_canvas.config(scrollregion=self.map_canvas.bbox("all") or (0,0,0,0))

    def _zoom_in(self):
        self._set_map_scale(self.map_scale * 1.2)

    def _zoom_out(self):
        self._set_map_scale(self.map_scale / 1.2)

    def _reset_zoom(self):
        self._set_map_scale(1.0)

    def _upload_map_image(self):
        """Opens a file dialog to let the user select a new map image."""
        path = filedialog.askopenfilename(title="Select Map Image", filetypes=[("Image Files", "*.png *.jpg *.jpeg *.bmp *.gif")])
        if not path: return
        self.map_view_data["image_path"] = path
        self.settings.set("map_view_data", self.map_view_data)
        self._load_map_image(path)

    def _enter_draw_mode(self):
        """Prepares the canvas for drawing a new polygon zone."""
        self.is_in_draw_mode = True
        self.current_polygon_points = []
        self.map_canvas.config(cursor="crosshair")
        self.map_canvas.bind("<Button-1>", self._on_map_left_click)
        self.map_canvas.bind("<Double-Button-1>", self._on_map_double_click)
        self.map_canvas.bind("<Button-3>", self._on_map_right_click)
        self.map_canvas.bind("<Motion>", self._on_map_mouse_move)
        self.root.bind("<Escape>", self._cancel_draw)
        self.notify("Draw Mode: Left-click to add points, double-click or Right-click to finish.", 4000)

    def _exit_draw_mode(self):
        """Cleans up after drawing is complete or cancelled."""
        self.is_in_draw_mode = False
        self.current_polygon_points = []
        self.map_canvas.config(cursor="")
        self.map_canvas.unbind("<Button-1>")
        self.map_canvas.unbind("<Button-3>")
        self.map_canvas.unbind("<Motion>")
        self.root.unbind("<Escape>")
        for item in self.temp_draw_items: self.map_canvas.delete(item)
        self.temp_draw_items = []

    def _cancel_draw(self, event=None):
        if self.is_in_draw_mode:
            self.log("Drawing cancelled by user.")
            self._exit_draw_mode()

    def _on_map_left_click(self, event):
        canvas_x, canvas_y = self.map_canvas.canvasx(event.x), self.map_canvas.canvasy(event.y)
        orig_x, orig_y = canvas_x / self.map_scale, canvas_y / self.map_scale
        self.current_polygon_points.extend([orig_x, orig_y])

        dot = self.map_canvas.create_oval(canvas_x-3, canvas_y-3, canvas_x+3, canvas_y+3,
                                          fill=self.style.lookup("Accent.TButton", "background"), outline="")
        self.temp_draw_items.append(dot)

        if len(self.current_polygon_points) > 2:
            scaled_points = [p * self.map_scale for p in self.current_polygon_points]
            line = self.map_canvas.create_line(scaled_points, fill="white", width=max(1,int(2*self.map_scale)))
            self.temp_draw_items.append(line)

        # auto-close by proximity to start (optional refinement)
        if len(self.current_polygon_points) >= 8:
            first_canvas_x = self.current_polygon_points[0] * self.map_scale
            first_canvas_y = self.current_polygon_points[1] * self.map_scale
            dist_to_start = math.hypot(canvas_x - first_canvas_x, canvas_y - first_canvas_y)
            if dist_to_start <= 12:
                self.log("Auto-completing and assigning zone: last point close to first point.")
                self._complete_draw_section()

    def _on_map_mouse_move(self, event):
        if not self.is_in_draw_mode or not self.current_polygon_points: return
        if self.temp_draw_items and "rubber_band" in self.map_canvas.gettags(self.temp_draw_items[-1]):
            self.map_canvas.delete(self.temp_draw_items.pop())

        last_x, last_y = self.current_polygon_points[-2] * self.map_scale, self.current_polygon_points[-1] * self.map_scale
        cursor_canvas_x, cursor_canvas_y = self.map_canvas.canvasx(event.x), self.map_canvas.canvasy(event.y)

        line = self.map_canvas.create_line(last_x, last_y, cursor_canvas_x, cursor_canvas_y,
                                           fill="white", dash=(4, 4), tags="rubber_band")
        self.temp_draw_items.append(line)

    def _on_map_right_click(self, event):
        self._complete_draw_section()

    def _on_map_double_click(self, event):
        if self.is_in_draw_mode:
            self._complete_draw_section()
        else:
            return

    def _complete_draw_section(self):
        if len(self.current_polygon_points) < 6:
            self.notify("A shape needs at least 3 points.", 3000)
            return

        coords = self.current_polygon_points
        assigned_pins = {s['valve_pin'] for s in self.map_view_data.get('sections', [])}
        available_valves = {f"{v['name']} (Pin {v['pin']})": i for i, v in enumerate(self.valves) if v['pin'] not in assigned_pins}

        if not available_valves:
            messagebox.showwarning("No Valves", "There are no available valves to assign.", parent=self.root)
            self._exit_draw_mode()
            return

        dialog = AssignValveDialog(self.root, available_valves)
        if dialog.result:
            result = dialog.result
            valve_index = result['valve_index']
            new_name = result['name']
            valve_to_rename = self.valves[valve_index]
            self.log(f"Renaming valve '{valve_to_rename['name']}' to '{new_name}' via Map View.")
            valve_to_rename['name'] = new_name
            for plant, emoji in constants.PLANT_EMOJIS.items():
                if plant in new_name.lower():
                    valve_to_rename["icon"] = emoji
                    break
            new_section = {"coords": coords, "valve_pin": valve_to_rename['pin']}
            self.map_view_data.setdefault('sections', []).append(new_section)
            self.settings.set("map_view_data", self.map_view_data)
            self.save_state()
            self._draw_map_sections()
            self.filter_valves()
            self.notify(f"Zone '{new_name}' created and assigned to Pin {valve_to_rename['pin']}.")

        self._exit_draw_mode()
    
    def _enter_edit_mode(self):
        """Prepares the canvas for editing or deleting zones."""
        self.is_in_edit_mode = True
        self.map_canvas.config(cursor="hand2")
        self.map_canvas.bind("<Button-1>", self._on_section_click)
        self.root.bind("<Escape>", self._exit_edit_mode)
        self.notify("Edit Mode: Click a zone to modify. Press ESC to exit.", 4000)

    def _exit_edit_mode(self, event=None):
        """Cleans up after editing is complete."""
        self.is_in_edit_mode = False
        self.map_canvas.config(cursor="")
        self.map_canvas.unbind("<Button-1>")
        self.root.unbind("<Escape>")
        self.notify("Exited Edit Mode.", 2000)

    def _on_section_click(self, event):
        """Handles a click on a section when in edit mode."""
        canvas_x, canvas_y = self.map_canvas.canvasx(event.x), self.map_canvas.canvasy(event.y)
        
        # Find the item (polygon) that was clicked on
        clicked_items = self.map_canvas.find_closest(canvas_x, canvas_y)
        if not clicked_items: return
        
        tags = self.map_canvas.gettags(clicked_items[0])
        section_pin = None
        for tag in tags:
            if tag.startswith("section_pin_"):
                section_pin = int(tag.split("_")[-1])
                break
        
        if section_pin is None: return

        # --- Create a pop-up menu for editing ---
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="Rename Zone...", command=lambda: self._rename_section(section_pin))
        menu.add_command(label="Delete Zone", command=lambda: self._delete_section(section_pin))
        # We can add "Re-assign Valve" here in the future

        # Display the menu at the cursor's position
        menu.tk_popup(event.x_root, event.y_root)
    
    def _on_section_double_click(self, event, valve_pin):
        """Toggles the valve for a specific pin, called directly by a shape's event binding."""
        # This interaction should only work when not in Draw or Edit mode
        if self.is_in_draw_mode or self.is_in_edit_mode:
            return

        # Find the index of the valve that has this pin
        valve_index = -1
        for i, valve in enumerate(self.valves):
            if valve['pin'] == valve_pin:
                valve_index = i
                break
        
        # If we found the valve, toggle it
        if valve_index != -1:
            self.log(f"Toggling valve '{self.valves[valve_index]['name']}' via map double-click.")
            self.toggle_valve(valve_index)

    def _rename_section(self, valve_pin):
        """Renames a zone and its associated valve."""
        valve = self.find_item_by_pin(valve_pin)
        if not valve: return

        new_name = simpledialog.askstring("Rename Zone", f"Enter new name for '{valve['name']}':", parent=self.root)
        if not new_name or not new_name.strip(): return

        self.log(f"Renaming valve '{valve['name']}' to '{new_name}' via Map Edit.")
        valve['name'] = new_name.strip()
        self.save_state()
        self._draw_map_sections() # Redraw with new name
        self.filter_valves()     # Update the Card View
        self.notify(f"Zone renamed to '{new_name}'.")

    def _delete_section(self, valve_pin):
        """Deletes a zone from the map."""
        valve = self.find_item_by_pin(valve_pin)
        if not valve: return
        
        if not messagebox.askyesno("Confirm Delete", f"Are you sure you want to delete the zone '{valve['name']}' from the map?\n\n(The valve itself will not be deleted.)", parent=self.root):
            return

        # Find and remove the section from the settings data
        sections = self.map_view_data.get('sections', [])
        self.map_view_data['sections'] = [s for s in sections if s['valve_pin'] != valve_pin]
        
        self.settings.set("map_view_data", self.map_view_data)
        self.log(f"Map zone for Pin {valve_pin} ('{valve['name']}') deleted.")
        self._draw_map_sections() # Redraw the map without the deleted section
        self.notify(f"Zone '{valve['name']}' deleted.")


    def _draw_map_sections(self):
        """Clears and redraws all saved polygons and binds double-click events directly to them."""
        self.map_canvas.delete("map_section") 

        for section in self.map_view_data.get('sections', []):
            valve_pin = section['valve_pin']
            valve = self.find_item_by_pin(valve_pin)
            if not valve or not section.get('coords'): continue

            coords = section['coords']
            scaled_coords = [c * self.map_scale for c in coords]
            fill_color = "#81C784" if valve.get('status') else "#546E7A"
            unique_tag = f"section_pin_{valve_pin}"
            
            # Draw the polygon and text with the unique tag
            self.map_canvas.create_polygon(
                scaled_coords, outline=fill_color, fill=fill_color, stipple="gray50",
                width=max(1, int(2 * self.map_scale)), tags=("map_section", unique_tag)
            )
            
            avg_x = sum(scaled_coords[i] for i in range(0, len(scaled_coords), 2)) / (len(scaled_coords) / 2)
            avg_y = sum(scaled_coords[i] for i in range(1, len(scaled_coords), 2)) / (len(scaled_coords) / 2)
            
            self.map_canvas.create_text(
                avg_x, avg_y, text=valve['name'], fill="white",
                font=('Segoe UI', max(8, int(10 * self.map_scale)), 'bold'), tags=("map_section", unique_tag)
            )

            # --- THIS IS THE NEW, DIRECT BINDING ---
            # This binds the event to all items with this unique tag (the polygon and its text).
            # The lambda function ensures the correct valve_pin is passed when the event fires.
            self.map_canvas.tag_bind(
                unique_tag, 
                "<Double-Button-1>", 
                lambda event, pin=valve_pin: self._on_section_double_click(event, pin)
            )

    def find_item_by_pin(self, pin):
        for item in self.valves + self.aux_controls:
            if item['pin'] == pin: return item
        return None

    def format_schedule_for_display(self, schedule_obj):
        s_type = schedule_obj.get('type', 'Fixed Time')
        if s_type == 'Cycle':
            count = schedule_obj.get('count', '∞') or '∞'
            details = f"CYCLE: ON {schedule_obj['on_m']}m, OFF {schedule_obj['off_m']}m, x{count} at {schedule_obj['time']}"
        else:
            details = f"{schedule_obj['action']} at {schedule_obj['time']}"
        if schedule_obj.get('skip_rainy'): details += " (☔ Skip if Rainy)"
        return details
    # In main_window.py

    