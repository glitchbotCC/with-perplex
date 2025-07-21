# smart_farm/gui/main_window.py

# Standard library imports
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
import json
import datetime
import os
import sys
import time
import re
import random
import requests

# Local application imports
from .. import constants, utils
from ..settings_manager import PersistentSettings
from ..hardware_manager import HardwareManager

# GUI window imports
from .settings_windows import AppSettingsWindow, ValveSettingsWindow
from .scheduler_window import SchedulerWindow
from .automation_window import AutomationWindow
from .log_window import LogWindow


class MainWindow:
    """Main application class for Smart Farm Valve Control."""
    def __init__(self, root):
        self.log_window = None
        self.root = root
        self.settings = PersistentSettings()
        self.hardware = HardwareManager()

        # --- Load settings and initialize state ---
        # The 'logs' list MUST be created first, as other functions like _migrate_schedule_data call self.log()
        self.logs = self.settings.get("logs", [])
        
        self.theme = self.settings.get("theme", "dark")
        self.location = self.settings.get("location", "London,UK")
        self.api_key = constants.API_KEY

         # This section now safely loads data from your settings file
        self.valves = self.settings.get("valves", [])
        self.aux_controls = self.settings.get("aux_controls", [])
        self.automation_rules = self.settings.get("automation_rules", [])
        self.schedule_history = self.settings.get("schedule_history", [])

        # Now that self.logs exists, it's safe to run the migration
        self._migrate_schedule_data()

        # CRITICAL: Initialize dynamic valve data that isn't saved in the file
        for v in self.valves:
            self._initialize_valve_data(v)

        # Initialize Aux controls if they are invalid or missing
        default_aux_controls = [{"id": f"aux_{i}", "name": f"AUX {i+1}", "pin": pin, "status": False, "schedules": []} for i, pin in enumerate(constants.EXTRA_GPIO_PINS)]
        loaded_aux = self.settings.get("aux_controls")

        # More robust check: verify that the actual pin numbers match the constants
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

        self.undo_stack = []
        self.style = ttk.Style()
        self.scheduled_jobs = {}
        self.filtered_valves = []
        self.log_window = None
        self.scheduler_window = None

        # --- Tkinter Variables ---
        self.search_var = tk.StringVar()
        self.valve_count_var = tk.StringVar(value="1")
        self.location_var = tk.StringVar(value=f"Location: {self.location}")
        self.system_time_var = tk.StringVar(value="Time: --:--:--")
        self.live_weather_var = tk.StringVar(value="Weather: Fetching...")
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
                    # Try parsing cycle format first
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
                    else: # Try parsing fixed time format
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
        # This check ensures the loop stops if the UI is destroyed
        if not hasattr(self, 'root') or not self.root.winfo_exists():
            return

        for i, valve_data in enumerate(self.valves):
            # Check if the valve card and its label still exist
            if i < len(self.valve_status_labels) and self.valve_status_labels[i].winfo_exists():
                label = self.valve_status_labels[i]
                if valve_data.get("status"):
                    current_fg = str(label.cget("foreground"))
                    pulse_color_1 = "#a3be8c" # Nord green
                    pulse_color_2 = "#8fbcbb" # Nord teal
                    try:
                        label.config(foreground=pulse_color_2 if current_fg == pulse_color_1 else pulse_color_1)
                    except tk.TclError:
                        # This can happen on theme change, just reset the color
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
        self.theme = "dark" if self.theme == "light" else "light"
        self.settings.set("theme", self.theme)
        # Re-initialize the entire UI to apply the theme
        self.apply_theme()
        self.setup_ui()
        self.filter_valves() # This calls render_valves_grid
        self.update_aux_controls_ui()
        self.update_dashboard()

    def apply_theme(self):
        self.style.theme_use("clam")
        # Theme colors
        dark_bg, dark_fg = "#2e3440", "#d8dee9"
        dark_frame_bg, dark_border = "#3b4252", "#4c566a"
        dark_accent, dark_accent_fg = "#88c0d0", "#2e3440"
        dark_emergency, dark_emergency_fg = "#bf616a", "#eceff4"
        dark_locked = "#434c5e"
        light_bg, light_fg = "#f5f7fa", "#2d3748"
        light_frame_bg, light_border = "#ffffff", "#e2e8f0"
        light_accent, light_accent_fg = "#4299e1", "#ffffff"
        light_emergency, light_emergency_fg = "#e53e3e", "#ffffff"
        light_locked = "#edf2f7"

        # Set colors based on current theme
        if self.theme == "dark":
            bg, fg, frame_bg, border = dark_bg, dark_fg, dark_frame_bg, dark_border
            accent, accent_fg = dark_accent, dark_accent_fg
            emergency, emergency_fg = dark_emergency, dark_emergency_fg
            locked_bg = dark_locked
            entry_bg, entry_fg, entry_insert = dark_frame_bg, dark_fg, dark_accent
            tree_bg, tree_fg, tree_sel_bg = dark_frame_bg, dark_fg, "#5e81ac"
            btn_bg, btn_fg, btn_active_bg = "#434c5e", "#eceff4", "#4c566a"
        else: # light theme
            bg, fg, frame_bg, border = light_bg, light_fg, light_frame_bg, light_border
            accent, accent_fg = light_accent, light_accent_fg
            emergency, emergency_fg = light_emergency, light_emergency_fg
            locked_bg = light_locked
            entry_bg, entry_fg, entry_insert = light_frame_bg, light_fg, light_accent
            tree_bg, tree_fg, tree_sel_bg = light_frame_bg, light_fg, "#bee3f8"
            btn_bg, btn_fg, btn_active_bg = "#e2e8f0", "#2d3748", "#cbd5e0"

        # Apply styles
        self.style.configure(".", background=bg, foreground=fg, bordercolor=border, font=('Segoe UI', 10))
        self.style.configure("TFrame", background=bg)
        self.style.configure("TLabel", background=bg, foreground=fg)
        self.style.configure("Header.TLabel", font=("Segoe UI Variable Display", 28, "bold"), background=bg, foreground=fg)
        self.style.configure("Subheader.TLabel", font=("Segoe UI Variable Text", 14), background=bg, foreground=fg)
        self.style.configure("TButton", background=btn_bg, foreground=btn_fg, borderwidth=1, relief="raised", font=('Segoe UI', 10), padding=(8, 5))
        self.style.map("TButton", background=[('active', btn_active_bg), ('pressed', accent)])
        self.style.configure("Accent.TButton", background=accent, foreground=accent_fg, font=('Segoe UI', 10, 'bold'))
        self.style.map("Accent.TButton", background=[('active', btn_active_bg)])
        self.style.configure("Emergency.TButton", background=emergency, foreground=emergency_fg, font=('Segoe UI', 10, 'bold'))
        self.style.map("Emergency.TButton", background=[('active', '#d08770' if self.theme == 'dark' else '#f56565')])
        self.style.configure("Card.TFrame", background=frame_bg, borderwidth=1, relief="solid", bordercolor=border)
        self.style.configure("Card.TFrame.Label", background=frame_bg, foreground=fg, font=('Segoe UI', 11, 'bold'))
        self.style.configure("TEntry", fieldbackground=entry_bg, foreground=entry_fg, insertcolor=entry_insert, bordercolor=border, lightcolor=border, darkcolor=border)
        self.style.configure("TScrollbar", troughcolor=bg, background=btn_bg, arrowcolor=fg)
        self.style.configure("TRadiobutton", background=frame_bg, foreground=fg)
        self.style.map("TRadiobutton", indicatorcolor=[('selected', accent), ('!selected', border)], background=[('active', bg)])
        self.style.configure("TCheckbutton", background=frame_bg, foreground=fg)
        self.style.map("TCheckbutton", indicatorcolor=[('selected', accent), ('!selected', border)], background=[('active', bg)])
        self.style.configure("Treeview", background=tree_bg, foreground=tree_fg, fieldbackground=tree_bg, font=('Segoe UI', 10), rowheight=28)
        self.style.map("Treeview", background=[('selected', tree_sel_bg)], foreground=[('selected', fg)])
        self.style.configure("Treeview.Heading", background=btn_bg, foreground=btn_fg, relief="raised", font=('Segoe UI', 10, 'bold'))
        self.style.map("Treeview.Heading", relief=[('active', 'groove'), ('pressed', 'sunken')])
        self.style.configure("TCombobox", fieldbackground=entry_bg, background=btn_bg, foreground=entry_fg, arrowcolor=fg, insertcolor=entry_insert, lightcolor=border, darkcolor=border, bordercolor=border)
        self.style.map('TCombobox', selectbackground=[('readonly', tree_sel_bg)], selectforeground=[('readonly', fg)])
        self.style.configure("Valve.Card.TFrame", background=frame_bg, borderwidth=1, relief="solid")
        self.style.map("Valve.Card.TFrame", bordercolor=[('!focus', border), ('focus', accent)])
        self.style.configure("Locked.Valve.Card.TFrame", background=locked_bg, bordercolor=dark_emergency if self.theme == 'dark' else light_emergency)

        if hasattr(self, 'root'):
            self.root.configure(bg=bg)

    def setup_ui(self):
        """Sets up the main UI using a PanedWindow for a robust, user-resizable layout."""
        # Clear existing widgets before rebuilding
        for widget in self.root.winfo_children():
            widget.destroy()
        self.root.configure(bg=self.style.lookup(".", "background"))

        self.setup_menu()

        # --- Top Section (Header, Dashboard, Controls) ---
        top_frame = ttk.Frame(self.root, style="TFrame", padding=(30, 15, 30, 10))
        top_frame.pack(fill=tk.X, side=tk.TOP)

        # Header
        header = ttk.Frame(top_frame, style="TFrame")
        header.pack(fill=tk.X, pady=(5, 2))
        ttk.Label(header, text="👨‍🌾", font=("Segoe UI Emoji", 36), style="TLabel").pack(side=tk.LEFT, padx=(0, 15), pady=10)
        title_frame = ttk.Frame(header, style="TFrame")
        title_frame.pack(side=tk.LEFT, pady=10, anchor="w")
        ttk.Label(title_frame, text=constants.APP_NAME, style="Header.TLabel").pack(anchor="w")
        ttk.Label(title_frame, text="Automate and Monitor Your Irrigation System", style="Subheader.TLabel").pack(anchor="w")

        # Dashboard
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
        ttk.Label(dash_right_frame, textvariable=self.location_var, font=dash_font).pack(anchor='e')
        ttk.Label(dash_right_frame, textvariable=self.live_weather_var, font=dash_font).pack(anchor='e')
        ttk.Label(dash_right_frame, textvariable=self.system_time_var, font=dash_font).pack(anchor='e')

        # Controls & Search
        top_controls_card = ttk.Labelframe(top_frame, text="System Controls & Search", style="Card.TFrame", padding=(15, 10))
        top_controls_card.pack(pady=10, fill=tk.X)
        add_search_frame = ttk.Frame(top_controls_card)
        add_search_frame.pack(pady=8, padx=8, fill=tk.X)
        add_frame = ttk.Frame(add_search_frame)
        add_frame.pack(side=tk.LEFT, padx=(0, 20))
        ttk.Label(add_frame, text=f"Valves to add (1-{constants.MAX_VALVES}):").pack(side=tk.LEFT, pady=(0, 3))
        self.valve_entry = ttk.Entry(add_frame, textvariable=self.valve_count_var, width=5, style="TEntry", font=('Segoe UI', 10))
        self.valve_entry.pack(side=tk.LEFT, padx=7)
        add_btn = ttk.Button(add_frame, text="Add", command=self.add_valves, style="Accent.TButton")
        add_btn.pack(side=tk.LEFT)
        utils.tooltip(add_btn, "Add new valves (Ctrl+N)")
        search_frame = ttk.Frame(add_search_frame)
        search_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(search_frame, text="🔍 Search:", font=("Segoe UI Emoji", 12)).pack(side=tk.LEFT)
        self.search_entry = ttk.Entry(search_frame, textvariable=self.search_var, width=35, style="TEntry", font=('Segoe UI', 10))
        self.search_entry.pack(side=tk.LEFT, padx=6, fill=tk.X, expand=True)
        utils.tooltip(self.search_entry, "Search by name, note, 'on', 'off', or 'pin:X' (Ctrl+F)")
        self.search_entry.bind("<KeyRelease>", lambda _: self.filter_valves())
        btn_group_frame = ttk.Frame(top_controls_card)
        btn_group_frame.pack(pady=(8, 8), padx=8, fill=tk.X, expand=True)
        main_actions = [
            ("Scheduler 📅", self.open_scheduler_window, "Ctrl+Alt+S"),
            ("Reset All ♻️", self.reset_valves, "Ctrl+R"),
            ("🚨 Turn All Systems OFF", self.turn_all_systems_off, "Immediately turns OFF all valves and aux controls.")
        ]
        for txt, cmd, tip in main_actions:
            style = "Emergency.TButton" if "OFF" in txt else "TButton"
            b = ttk.Button(btn_group_frame, text=txt, command=cmd, style=style)
            b.pack(side=tk.LEFT, padx=5, pady=3, fill=tk.X, expand=True)
            utils.tooltip(b, tip)

        # --- Main Paned Window Layout ---
        self.main_pane = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL, style="TPanedwindow")
        self.main_pane.pack(fill=tk.BOTH, expand=True, padx=30, pady=(0, 10))

        # Left Pane: Valve Cards
        valves_lf = ttk.Labelframe(self.main_pane, text="Configured Irrigation Valves", style="Card.TFrame", padding=10)
        self.main_pane.add(valves_lf, weight=1)
        valves_lf.rowconfigure(0, weight=1)
        valves_lf.columnconfigure(0, weight=1)
        self.valve_canvas = tk.Canvas(valves_lf, bg=self.style.lookup("Card.TFrame", "background"), highlightthickness=0)
        self.valve_vbar = ttk.Scrollbar(valves_lf, orient="vertical", command=self.valve_canvas.yview)
        self.valve_canvas.configure(yscrollcommand=self.valve_vbar.set)
        self.valve_card_frame = ttk.Frame(self.valve_canvas, style="TFrame")
        self.canvas_frame_id = self.valve_canvas.create_window((0, 0), window=self.valve_card_frame, anchor="nw")
        self.valve_vbar.grid(row=0, column=1, sticky="ns")
        self.valve_canvas.grid(row=0, column=0, sticky="nsew")
        self.valve_canvas.bind("<Configure>", self.on_valve_canvas_configure)
        self.valve_card_frame.bind("<Configure>", self.on_valve_frame_configure)
        self.valve_canvas.bind_all("<MouseWheel>", lambda e: self.valve_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))
        self.valve_canvas.bind_all("<Button-4>", lambda e: self.valve_canvas.yview_scroll(-1, "units"))
        self.valve_canvas.bind_all("<Button-5>", lambda e: self.valve_canvas.yview_scroll(1, "units"))
        self.valve_status_labels = []

        # Right Pane: Aux Controls & Sensors
        right_column_frame = ttk.Frame(self.main_pane, style="TFrame")
        self.main_pane.add(right_column_frame, weight=0)
        right_column_frame.pack_propagate(False)
        right_column_frame.rowconfigure(0, weight=1)
        right_column_frame.columnconfigure(0, weight=1)
        right_column_frame.columnconfigure(1, weight=1)
        # Aux Controls
        aux_lf = ttk.Labelframe(right_column_frame, text="Auxiliary Controls", style="Card.TFrame", padding=10)
        aux_lf.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        self.aux_buttons_ui_elements = []
        for i, aux_data in enumerate(self.aux_controls):
            btn = ttk.Button(aux_lf, text="", command=lambda idx=i: self.toggle_aux_control(idx), compound=tk.LEFT)
            btn.pack(pady=5, padx=5, fill=tk.X, ipady=3)
            btn.bind("<Button-3>", lambda e, idx=i: self.rename_aux_control(idx))
            utils.tooltip(btn, f"Controls {aux_data['name']}. Right-click to rename. Schedule via Master Scheduler.")
            self.aux_buttons_ui_elements.append(btn)
        # Sensor Data
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

        # --- Footer ---
        self.footer = ttk.Frame(self.root, style="TFrame", padding=(30, 5))
        self.footer.pack(fill=tk.X, side=tk.BOTTOM, pady=(5, 10))
        self.footer.columnconfigure(0, weight=1)
        self.footer_label = ttk.Label(self.footer, text="System Ready.", anchor="w", font=('Segoe UI', 10))
        self.footer_label.pack(side=tk.LEFT)
        theme_btn_footer = ttk.Button(self.footer, text="🌗 Theme", command=self.toggle_theme, style="TButton", compound=tk.LEFT)
        theme_btn_footer.pack(side=tk.RIGHT, padx=5)
        utils.tooltip(theme_btn_footer, "Toggle Dark/Light Theme (Ctrl+T)")

        self.root.after(100, self._set_initial_sash)

    def _set_initial_sash(self):
        """Sets the initial 70/30 sash position for the main pane."""
        try:
            initial_pos = int(self.main_pane.winfo_width() * 0.7)
            self.main_pane.sashpos(0, initial_pos)
        except (tk.TclError, AttributeError):
            if hasattr(self, 'root') and self.root.winfo_exists():
                self.root.after(200, self._set_initial_sash)

    def setup_menu(self):
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        # File Menu
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Import Config", command=self.import_config, accelerator="Ctrl+I")
        file_menu.add_command(label="Export Config", command=self.export_config, accelerator="Ctrl+E")
        file_menu.add_command(label="Save Log", command=self.save_log_manually, accelerator="Ctrl+Shift+S")
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.on_close)
        # System Menu
        system_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="System", menu=system_menu)
        system_menu.add_command(label="Automation Rules", command=self.open_automation_window)
        system_menu.add_separator()
        system_menu.add_command(label="Application Settings", command=self.open_app_settings_window, accelerator="Ctrl+Shift+C")
        system_menu.add_command(label="System Logs", command=self.open_log_window)
        system_menu.add_separator()
        system_menu.add_command(label="Undo Remove", command=self.undo_remove, accelerator="Ctrl+Z")
        # Location Menu
        location_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Location", menu=location_menu)
        location_menu.add_command(label="Set Location...", command=self.set_location)
        # Help Menu
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="Sensor Connection Guide", command=self.show_sensor_connection_info)
        help_menu.add_command(label="About", command=self.show_about)

    def update_sensor_readings(self):
        """Fetches and updates sensor readings from the hardware manager."""
        # DHT22
        temp_c, humidity = self.hardware.read_dht22()
        if isinstance(temp_c, (float, int)):
            self.sensor_temp_c.set(f"{temp_c:.1f}°C")
            self.sensor_humidity.set(f"{humidity:.1f}%")
        else:
            self.sensor_temp_c.set(str(temp_c))
            self.sensor_humidity.set(str(humidity))
        # DHT11
        temp_c_dht11, humidity_dht11 = self.hardware.read_dht11()
        if isinstance(temp_c_dht11, (float, int)):
            self.sensor_temp_c_dht11.set(f"{temp_c_dht11:.1f}°C")
            self.sensor_humidity_dht11.set(f"{humidity_dht11:.1f}%")
        else:
            self.sensor_temp_c_dht11.set(str(temp_c_dht11))
            self.sensor_humidity_dht11.set(str(humidity_dht11))
        # Moisture
        moisture_status = self.hardware.read_moisture()
        if moisture_status == "Wet": self.sensor_moisture.set(f"💧 Wet")
        elif moisture_status == "Dry": self.sensor_moisture.set(f"🔥 Dry")
        else: self.sensor_moisture.set(moisture_status)

        if hasattr(self, 'root') and self.root.winfo_exists():
            self.root.after(5000, self.update_sensor_readings)

    def show_sensor_connection_info(self):
        """Displays a messagebox with sensor connection details."""
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

        # Define tags for styling
        text_widget.tag_configure("h1", font=("Segoe UI", 14, "bold"), spacing3=10)
        text_widget.tag_configure("h2", font=("Segoe UI", 11, "bold"), spacing1=15, spacing3=5)
        text_widget.tag_configure("code", font=("Consolas", 9), background=self.style.lookup("TEntry", "fieldbackground"))
        text_widget.tag_configure("pin", font=("Consolas", 9, "bold"), foreground=self.style.lookup("Accent.TButton", "background"))
        text_widget.tag_configure("lib", font=("Consolas", 9, "italic"))
        text_widget.tag_configure("sep", overstrike=True)

        # Insert content
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
        """Renders the valve cards in a responsive grid."""
        self.valve_status_labels.clear()
        for widget in self.valve_card_frame.winfo_children():
            widget.destroy()

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
                card = ttk.Frame(self.valve_card_frame, style=card_style, padding=12)
                card.grid(row=row, column=col, padx=10, pady=10, sticky="nsew")
                self.valve_card_frame.columnconfigure(col, weight=1)

                is_on = valve_data.get("status")
                icon = valve_data.get("icon", "💧")
                status_txt = "🟢" if is_on else ("🔴" if valve_data.get("locked") and is_on else "⚪")
                status_color = "#a3be8c" if is_on else ("#bf616a" if valve_data.get("locked") else self.style.lookup("TLabel", "foreground"))

                header_frame = ttk.Frame(card, style=card_style.replace("Valve.Card", "T"))
                header_frame.pack(fill=tk.X, pady=(0, 8))
                status_lbl = ttk.Label(header_frame, text=status_txt, style="TLabel", foreground=status_color, font=("Segoe UI Emoji", 16))
                status_lbl.pack(side=tk.LEFT, padx=(0, 8))
                utils.tooltip(status_lbl, f"Valve ON" if is_on else f"Valve OFF { '(Locked)' if valve_data.get('locked') else ''}")
                self.valve_status_labels.append(status_lbl)
                ttk.Label(header_frame, text=f"{icon} {valve_data['name']}", font=('Segoe UI', 12, 'bold')).pack(side=tk.LEFT, anchor="w")

                ttk.Button(card, text="Toggle Status", command=lambda i=orig_idx: self.toggle_valve(i), style="TButton").pack(fill=tk.X, pady=(0, 10))
                ttk.Label(card, textvariable=valve_data["timer_var"], font=('Segoe UI', 9, 'italic'), foreground=self.style.lookup("Accent.TButton", "background")).pack(anchor="w")

                info_frame = ttk.Frame(card, style=card_style.replace("Valve.Card", "T"))
                info_frame.pack(fill=tk.X, pady=(5, 10))
                ttk.Label(info_frame, text=f"Pin: {valve_data['pin']}", font=('Segoe UI', 9)).pack(anchor="w")
                num_schedules = len(valve_data.get('schedules', []))
                sched_txt = f"⏰ {num_schedules} schedule(s) set" if num_schedules > 0 else "⏰ Not Scheduled"
                sl = ttk.Label(info_frame, text=sched_txt, font=('Segoe UI', 9, "italic"), anchor="w", wraplength=180)
                sl.pack(anchor="w", fill=tk.X)
                utils.tooltip(sl, "Open Master Scheduler to view/edit schedules")
                note = valve_data.get('note', '')
                if note:
                    nl = ttk.Label(info_frame, text=f"📝 {note[:25]}{'...' if len(note)>25 else ''}", font=('Segoe UI', 9, "italic"), foreground="#b48ead" if self.theme == "dark" else "#718096", anchor="w")
                    nl.pack(anchor="w", fill=tk.X)
                    utils.tooltip(nl, f"Note: {note}")

                btns_frame = ttk.Frame(card, style=card_style.replace("Valve.Card", "T"))
                btns_frame.pack(fill=tk.X, pady=(5, 0))
                btns = [("✏️", lambda i=orig_idx: self.rename_valve(i), "Rename"), ("🗑️", lambda i=orig_idx: self.remove_valve(i), "Remove"),
                        ("🔒" if not valve_data.get("locked") else "🔓", lambda i=orig_idx: self.toggle_lock(i), "Lock/Unlock"),
                        ("📝", lambda i=orig_idx: self.edit_note(i), "Note"), ("📋", lambda i=orig_idx: self.copy_valve(i), "Copy Cfg"),
                        ("📈", lambda i=orig_idx: self.show_valve_history(i), "History"), ("⚙️", lambda i=orig_idx: self.open_valve_settings_window(i), "Settings"),
                        ("📊", lambda i=orig_idx: self.show_valve_stats(i), "Stats")]
                for txt, cmd, tip in btns:
                    b = ttk.Button(btns_frame, text=txt, command=cmd, width=4, style="TButton")
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
                        # Basic cycle logic here, more complex state needed for full implementation
                        self.log(f"Cycle for '{current_item_obj['name']}' started.")
                        item_idx = self.valves.index(current_item_obj) if "flow_rate_lpm" in current_item_obj else self.aux_controls.index(current_item_obj)
                        self.toggle_item(item_idx, "valve" if "flow_rate_lpm" in current_item_obj else "aux", is_on=True)

                    elif current_item_obj["status"] != turn_on:
                        item_idx = self.valves.index(current_item_obj) if "flow_rate_lpm" in current_item_obj else self.aux_controls.index(current_item_obj)
                        self.toggle_item(item_idx, "valve" if "flow_rate_lpm" in current_item_obj else "aux", is_on=turn_on)

                self.log(f"Fixed time event for '{current_item_obj['name']}' fired. Removing schedule.")
                self.clear_schedule_by_id(job_id, reason="executed")
                return # Stop rescheduling this job
            # Reschedule the check
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
        """Adds or updates a schedule for an item."""
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

        if schedule_id: # Update existing
            for i, sched in enumerate(item_obj["schedules"]):
                if sched['id'] == schedule_id: new_schedule['id'] = schedule_id; item_obj["schedules"][i] = new_schedule; break
        else: # Add new
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
        """Generic toggle function for valves or aux controls."""
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
        valves_to_save = [v.copy() for v in self.valves]
        for v in valves_to_save: v.pop("timer_var", None)
        self.settings.set("valves", valves_to_save)
        self.settings.set("aux_controls", self.aux_controls)
        self.settings.set("automation_rules", self.automation_rules)
        self.settings.set("schedule_history", self.schedule_history)
        self.settings.set("logs", self.logs)

    def on_close(self):
        self.log("Application closing. Saving state.")
        self.save_state()
        self.hardware.cleanup()
        # Cancel all pending .after jobs to prevent errors on close
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
        if not self.undo_stack: self.notify("Nothing to undo."); return
        if len(self.valves) >= constants.MAX_VALVES: self.notify(f"Max valves reached. Cannot restore."); return
        valve_to_restore = self.undo_stack.pop()
        current_pins = {v['pin'] for v in self.valves}
        if valve_to_restore['pin'] in current_pins:
            available_pins = [p for p in constants.GPIO_PINS if p not in current_pins]
            if not available_pins:
                self.notify(f"Cannot restore '{valve_to_restore['name']}': Pin taken and no free pins.", duration=4000)
                self.undo_stack.append(valve_to_restore) # Put it back
                return
            valve_to_restore['pin'] = available_pins[0]
        self.valves.append(valve_to_restore)
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

    def log(self, msg):
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = f"[{ts}] {msg}"
        self.logs.append(entry)
        if len(self.logs) > 500: self.logs = self.logs[-300:]
        if self.log_window and self.log_window.winfo_exists(): self.log_window.add_log_entry(entry)
        if hasattr(self, 'dash_logs') and self.dash_logs.winfo_exists(): self.update_dashboard()

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
            if rule.get("last_triggered") and (now - rule["last_triggered"] < 300): continue # 5 min cooldown
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
        self.system_time_var.set(f"Time: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        if hasattr(self, 'root') and self.root.winfo_exists(): self.root.after(1000, self.update_system_clock)

    def update_location_data(self):
        if self.api_key == "d7b8a4a58f2d8f3f8b9e8a7b9c8d7e6f": # Default key
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

            # Update sunrise/sunset times
            local_sunrise = datetime.datetime.fromtimestamp(data['sys']['sunrise'] + data.get('timezone', 0), tz=datetime.timezone.utc)
            local_sunset = datetime.datetime.fromtimestamp(data['sys']['sunset'] + data.get('timezone', 0), tz=datetime.timezone.utc)
            self.settings.set("virtual_sunrise_time", local_sunrise.strftime('%H:%M'))
            self.settings.set("virtual_sunset_time", local_sunset.strftime('%H:%M'))
            self.log(f"Live data updated for {self.location}.")
        except requests.exceptions.RequestException: self.live_weather_var.set("Weather: Network Error")
        except (KeyError, IndexError): self.live_weather_var.set("Weather: Invalid Location")
        if hasattr(self, 'root') and self.root.winfo_exists(): self.root.after(600000, self.update_location_data) # Update every 10 mins

    def show_about(self):
        messagebox.showinfo(f"About {constants.APP_NAME}", f"{constants.APP_NAME} - v{constants.APP_VERSION}\n\nAdvanced Irrigation & Auxiliary Control.\n\nBuilt with Python & Tkinter.\n© 2024-2025 SmartFarm Solutions Inc.", parent=self.root)

    def find_schedule_by_id(self, schedule_id):
        for item in self.valves + self.aux_controls:
            for schedule in item.get("schedules", []):
                if schedule['id'] == schedule_id: return schedule, item
        return None, None

    def find_item_by_pin(self, pin):
        for item in self.valves + self.aux_controls:
            if item['pin'] == pin: return item
        return None

    def format_schedule_for_display(self, schedule_obj):
        """Creates a human-readable string from a schedule dictionary."""
        s_type = schedule_obj.get('type', 'Fixed Time')
        if s_type == 'Cycle':
            count = schedule_obj.get('count', '∞') or '∞'
            details = f"CYCLE: ON {schedule_obj['on_m']}m, OFF {schedule_obj['off_m']}m, x{count} at {schedule_obj['time']}"
        else:
            details = f"{schedule_obj['action']} at {schedule_obj['time']}"
        if schedule_obj.get('skip_rainy'): details += " (☔ Skip if Rainy)"
        return details