# smart_farm/gui/scheduler_window.py

import tkinter as tk
from tkinter import ttk, messagebox
import datetime
import time
import random
try:
    from .. import utils
except ImportError:
    import utils

class SchedulerWindow(tk.Toplevel):
    """
    A Toplevel window for managing complex schedules for valves and auxiliary controls,
    including fixed time events and cycle-based irrigation.
    """
    def __init__(self, master_app):
        super().__init__(master_app.root)
        self.master_app = master_app
        self.transient(master_app.root)
        self.title("📅 Master Scheduler")
        self.geometry("950x700")
        self.resizable(True, True)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.selected_item_display_name = tk.StringVar()
        self.schedule_type_var = tk.StringVar(value="Fixed Time")
        self.editing_schedule_id = None

        # Fixed Time Vars
        self.schedule_action_var = tk.StringVar(value="ON")
        self.schedule_time_var = tk.StringVar(value=datetime.datetime.now().strftime("%H:%M"))
        self.time_preset_var = tk.StringVar(value="Custom")
        self.skip_if_rainy_var = tk.BooleanVar(value=False)

        # Cycle Vars
        self.cycle_on_duration_var = tk.StringVar(value="5")
        self.cycle_off_duration_var = tk.StringVar(value="10")
        self.cycle_count_var = tk.StringVar(value="3")
        self.cycle_start_time_var = tk.StringVar(value=datetime.datetime.now().strftime("%H:%M"))
        self.cycle_time_preset_var = tk.StringVar(value="Custom")
        self.cycle_skip_if_rainy_var = tk.BooleanVar(value=False)

        self.items_for_scheduling_map = {}

        self.configure(bg=self.master_app.style.lookup(".", "background"))
        self._setup_scheduler_ui()
        self._populate_items_for_scheduling()
        self._populate_all_schedule_views()
        self._toggle_schedule_mode_ui()

        self.item_combobox.focus_set()

    @staticmethod
    def _parse_schedule_string(schedule_str):
        """Helper to parse old schedule string format."""
        try:
            parts = schedule_str.split(' at ')
            if len(parts) == 2:
                return parts[0].strip(), parts[1].strip()
        except Exception:
            return None, None
        return None, None

    def _on_close(self):
        """Handle the window closing event by hiding it instead of destroying."""
        self.withdraw()

    def _setup_scheduler_ui(self):
        """Sets up all UI components for the SchedulerWindow."""
        main_frame = ttk.Frame(self, padding=(18, 16))
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="Master Scheduler", font=('Segoe UI Semibold', 13)).pack(anchor="w", pady=(0, 4))
        ttk.Separator(main_frame, orient="horizontal").pack(fill=tk.X, pady=(0, 12))

        # --- Item Selection ---
        item_frame = ttk.Frame(main_frame, padding=(0, 0, 0, 10))
        item_frame.pack(fill=tk.X)
        ttk.Label(item_frame, text="Item to Schedule:").pack(side=tk.LEFT, padx=(0, 8))
        self.item_combobox = ttk.Combobox(item_frame, textvariable=self.selected_item_display_name,
                                          width=45, state="readonly")
        self.item_combobox.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.item_combobox.bind("<<ComboboxSelected>>", self._on_item_selected_from_combobox)

        # --- Schedule Type Radio Buttons ---
        type_frame = ttk.Frame(main_frame, padding=(0, 0, 0, 10))
        type_frame.pack(fill=tk.X)
        ttk.Label(type_frame, text="Schedule Type:").pack(side=tk.LEFT, padx=(0, 12))
        ttk.Radiobutton(type_frame, text="Fixed Time Event",
                        variable=self.schedule_type_var, value="Fixed Time",
                        command=self._toggle_schedule_mode_ui).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Radiobutton(type_frame, text="Cycle / Interval",
                        variable=self.schedule_type_var, value="Cycle",
                        command=self._toggle_schedule_mode_ui).pack(side=tk.LEFT)

        # --- Fixed Time Frame ---
        self.fixed_time_frame = ttk.Labelframe(main_frame, text="  Fixed Time Event  ", padding=12)
        ttk.Label(self.fixed_time_frame, text="Action:").grid(row=0, column=0, padx=(0, 8), pady=8, sticky="w")
        ttk.Radiobutton(self.fixed_time_frame, text="Turn ON",  variable=self.schedule_action_var, value="ON").grid(row=0, column=1, padx=5, pady=8, sticky="w")
        ttk.Radiobutton(self.fixed_time_frame, text="Turn OFF", variable=self.schedule_action_var, value="OFF").grid(row=0, column=2, padx=5, pady=8, sticky="w")
        ttk.Label(self.fixed_time_frame, text="Time:").grid(row=1, column=0, padx=(0, 8), pady=8, sticky="w")
        self.time_entry = ttk.Entry(self.fixed_time_frame, textvariable=self.schedule_time_var, width=8)
        self.time_entry.grid(row=1, column=1, padx=5, pady=8, sticky="w")
        self.time_preset_combobox = ttk.Combobox(self.fixed_time_frame, textvariable=self.time_preset_var,
                                                  values=["Custom", "Sunrise", "Sunset"], width=10, state="readonly")
        self.time_preset_combobox.grid(row=1, column=2, padx=5, pady=8, sticky="w")
        self.time_preset_combobox.bind("<<ComboboxSelected>>", self._update_time_from_preset)
        self.fixed_time_skip_rain_check = ttk.Checkbutton(self.fixed_time_frame, text="Skip if Rainy",
                                                           variable=self.skip_if_rainy_var)
        self.fixed_time_skip_rain_check.grid(row=0, column=3, padx=(16, 0), pady=8, sticky="w")
        utils.tooltip(self.fixed_time_skip_rain_check, "If checked, this ON schedule will be skipped if live weather is 'Rainy' and global rain skip is enabled.")

        # --- Cycle Frame ---
        self.cycle_frame = ttk.Labelframe(main_frame, text="  Cycle / Interval Details  ", padding=12)
        ttk.Label(self.cycle_frame, text="ON Duration (mins):").grid(row=0, column=0, padx=(0, 8), pady=5, sticky="w")
        self.cycle_on_entry = ttk.Entry(self.cycle_frame, textvariable=self.cycle_on_duration_var, width=5)
        self.cycle_on_entry.grid(row=0, column=1, padx=5, pady=5, sticky="w")
        ttk.Label(self.cycle_frame, text="OFF Duration (mins):").grid(row=1, column=0, padx=(0, 8), pady=5, sticky="w")
        self.cycle_off_entry = ttk.Entry(self.cycle_frame, textvariable=self.cycle_off_duration_var, width=5)
        self.cycle_off_entry.grid(row=1, column=1, padx=5, pady=5, sticky="w")
        ttk.Label(self.cycle_frame, text="Number of Cycles:").grid(row=2, column=0, padx=(0, 8), pady=5, sticky="w")
        self.cycle_count_entry = ttk.Entry(self.cycle_frame, textvariable=self.cycle_count_var, width=5)
        self.cycle_count_entry.grid(row=2, column=1, padx=5, pady=5, sticky="w")
        utils.tooltip(self.cycle_count_entry, "Enter a number (e.g., 3), or 0 for indefinite cycles.")
        ttk.Label(self.cycle_frame, text="Cycle Start Time:").grid(row=3, column=0, padx=(0, 8), pady=8, sticky="w")
        self.cycle_start_time_entry = ttk.Entry(self.cycle_frame, textvariable=self.cycle_start_time_var, width=8)
        self.cycle_start_time_entry.grid(row=3, column=1, padx=5, pady=8, sticky="w")
        self.cycle_time_preset_combobox = ttk.Combobox(self.cycle_frame, textvariable=self.cycle_time_preset_var,
                                                        values=["Custom", "Sunrise", "Sunset"], width=10, state="readonly")
        self.cycle_time_preset_combobox.grid(row=3, column=2, padx=5, pady=8, sticky="w")
        self.cycle_time_preset_combobox.bind("<<ComboboxSelected>>", self._update_time_from_preset)
        self.cycle_skip_rain_check = ttk.Checkbutton(self.cycle_frame, text="Skip if Rainy",
                                                      variable=self.cycle_skip_if_rainy_var)
        self.cycle_skip_rain_check.grid(row=0, column=2, rowspan=2, padx=(16, 0), pady=5, sticky="w")
        utils.tooltip(self.cycle_skip_rain_check, "If checked, this cycle schedule will be skipped if live weather is 'Rainy' and global rain skip is enabled.")

        # --- Action Buttons ---
        action_button_frame = ttk.Frame(main_frame, padding=(0, 10, 0, 0))
        action_button_frame.pack(fill=tk.X)
        self.add_update_btn = ttk.Button(action_button_frame, text="💾  Add Schedule",
                                         command=self._set_or_update_schedule, style="Accent.TButton")
        self.add_update_btn.pack(side=tk.LEFT, padx=(0, 4), fill=tk.X, expand=True)
        new_btn = ttk.Button(action_button_frame, text="➕  New",
                             command=self._reset_fields_for_new_schedule, style="TButton")
        new_btn.pack(side=tk.LEFT, padx=4, fill=tk.X, expand=True)
        utils.tooltip(new_btn, "Clear fields to create a new schedule.")
        clear_all_btn = ttk.Button(action_button_frame, text="🗑️  Clear All for Item",
                                   command=self._clear_all_schedules_for_selected_item, style="TButton")
        clear_all_btn.pack(side=tk.LEFT, padx=4, fill=tk.X, expand=True)
        utils.tooltip(clear_all_btn, "Clears all schedules for the item selected in the dropdown.")

        # --- Paned Window for Lists ---
        schedule_panes = ttk.PanedWindow(main_frame, orient=tk.HORIZONTAL)
        schedule_panes.pack(fill=tk.BOTH, expand=True, pady=(14, 0))

        # --- Current Schedules List ---
        current_frame = ttk.Labelframe(schedule_panes, text="  Current Schedules  ", padding=10)
        schedule_panes.add(current_frame, weight=1)
        current_frame.rowconfigure(0, weight=1)
        current_frame.columnconfigure(0, weight=1)
        self.current_schedules_tree = ttk.Treeview(current_frame,
                                                    columns=("item", "type", "details"),
                                                    show="headings")
        self.current_schedules_tree.heading("item",    text="Item Name")
        self.current_schedules_tree.heading("type",    text="Type")
        self.current_schedules_tree.heading("details", text="Schedule Details")
        self.current_schedules_tree.column("item",    width=150, anchor="w")
        self.current_schedules_tree.column("type",    width=80,  anchor="center")
        self.current_schedules_tree.column("details", width=250, anchor="w")
        current_ysb = ttk.Scrollbar(current_frame, orient="vertical",   command=self.current_schedules_tree.yview)
        current_xsb = ttk.Scrollbar(current_frame, orient="horizontal", command=self.current_schedules_tree.xview)
        self.current_schedules_tree.configure(yscrollcommand=current_ysb.set, xscrollcommand=current_xsb.set)
        self.current_schedules_tree.grid(row=0, column=0, sticky="nsew")
        current_ysb.grid(row=0, column=1, sticky="ns")
        current_xsb.grid(row=1, column=0, sticky="ew")
        self.current_schedules_tree.bind("<Delete>", self._clear_schedule_from_treeview_selection)
        self.current_schedules_tree.bind("<<TreeviewSelect>>", self._load_schedule_for_editing)

        # --- History List ---
        history_frame = ttk.Labelframe(schedule_panes, text="  Execution History  ", padding=10)
        schedule_panes.add(history_frame, weight=1)
        history_frame.rowconfigure(0, weight=1)
        history_frame.columnconfigure(0, weight=1)
        self.history_schedules_tree = ttk.Treeview(history_frame,
                                                    columns=("time", "item", "details"),
                                                    show="headings")
        self.history_schedules_tree.heading("time",    text="Executed At")
        self.history_schedules_tree.heading("item",    text="Item Name")
        self.history_schedules_tree.heading("details", text="Executed Schedule")
        self.history_schedules_tree.column("time",    width=120, anchor="w")
        self.history_schedules_tree.column("item",    width=120, anchor="w")
        self.history_schedules_tree.column("details", width=200, anchor="w")
        history_ysb = ttk.Scrollbar(history_frame, orient="vertical",   command=self.history_schedules_tree.yview)
        history_xsb = ttk.Scrollbar(history_frame, orient="horizontal", command=self.history_schedules_tree.xview)
        self.history_schedules_tree.configure(yscrollcommand=history_ysb.set, xscrollcommand=history_xsb.set)
        self.history_schedules_tree.grid(row=0, column=0, sticky="nsew")
        history_ysb.grid(row=0, column=1, sticky="ns")
        history_xsb.grid(row=1, column=0, sticky="ew")
        clear_history_btn = ttk.Button(history_frame, text="🗑️  Clear History",
                                       command=self._clear_all_history_schedules, style="TButton")
        clear_history_btn.grid(row=2, column=0, columnspan=2, pady=(10, 0), sticky="ew")
        utils.tooltip(clear_history_btn, "Clears all executed schedules from the history list above.")

    def _toggle_schedule_mode_ui(self):
        """Shows or hides the UI sections for Fixed Time or Cycle scheduling based on selection."""
        mode = self.schedule_type_var.get()
        if mode == "Fixed Time":
            self.cycle_frame.pack_forget()
            self.fixed_time_frame.pack(fill=tk.X, pady=(0, 10), before=self.add_update_btn.master)
        else: # mode == "Cycle"
            self.fixed_time_frame.pack_forget()
            self.cycle_frame.pack(fill=tk.X, pady=(0, 10), before=self.add_update_btn.master)

    def _update_time_from_preset(self, event=None):
        """Updates the time entry field when a preset (Sunrise/Sunset) is selected."""
        mode = self.schedule_type_var.get()
        if mode == "Fixed Time":
            preset = self.time_preset_var.get()
            if preset == "Sunrise":
                self.schedule_time_var.set(self.master_app.settings.get("virtual_sunrise_time"))
            elif preset == "Sunset":
                self.schedule_time_var.set(self.master_app.settings.get("virtual_sunset_time"))
        elif mode == "Cycle":
            preset = self.cycle_time_preset_var.get()
            if preset == "Sunrise":
                self.cycle_start_time_var.set(self.master_app.settings.get("virtual_sunrise_time"))
            elif preset == "Sunset":
                self.cycle_start_time_var.set(self.master_app.settings.get("virtual_sunset_time"))

    def _on_item_selected_from_combobox(self, event=None):
        """When an item is selected, clear the fields and repopulate the schedule list."""
        self._reset_fields_for_new_schedule()
        # Repopulating is handled by the main app, this just resets the entry form
        self.current_schedules_tree.selection_set([])


    def _populate_items_for_scheduling(self):
        """Populates the item selection combobox with available valves and auxiliary controls."""
        current_selection = self.selected_item_display_name.get()
        self.items_for_scheduling_map.clear()
        display_names = []
        for i, valve in enumerate(self.master_app.valves):
            name = f"Valve: {valve['name']} (Pin {valve['pin']})"
            self.items_for_scheduling_map[name] = {"type": "valve", "id": i, "original_name": valve['name'], "pin": valve['pin']}
            display_names.append(name)
        for i, aux in enumerate(self.master_app.aux_controls):
            name = f"Aux: {aux['name']} (Pin {aux['pin']})"
            self.items_for_scheduling_map[name] = {"type": "aux", "id": i, "original_name": aux['name'], "pin": aux['pin']}
            display_names.append(name)

        self.item_combobox['values'] = display_names

        if current_selection in display_names:
            self.item_combobox.set(current_selection)
        elif display_names:
            self.item_combobox.current(0)
        self._on_item_selected_from_combobox()

    def _populate_all_schedule_views(self):
        """Populates both the current and history treeviews."""
        self._populate_current_schedules_treeview()
        self._populate_history_schedules_treeview()

    def _populate_current_schedules_treeview(self):
        """Populates the Treeview list with all currently active schedules."""
        for i in self.current_schedules_tree.get_children():
            self.current_schedules_tree.delete(i)

        all_items = self.master_app.valves + self.master_app.aux_controls

        for item_obj in all_items:
            # item_type is 'Valve' if it has a flow rate, otherwise 'Aux'
            item_type = "Valve" if "flow_rate_lpm" in item_obj else "Aux"
            for schedule in item_obj.get("schedules", []):
                details_display = self.master_app.format_schedule_for_display(schedule)
                self.current_schedules_tree.insert("", "end", iid=schedule['id'], values=(item_obj["name"], item_type, details_display))

    def _populate_history_schedules_treeview(self):
        """Populates the Treeview with executed schedule history."""
        for i in self.history_schedules_tree.get_children():
            self.history_schedules_tree.delete(i)

        # Sort history by time descending before inserting
        sorted_history = sorted(self.master_app.schedule_history, key=lambda x: x['time'], reverse=True)
        for entry in sorted_history:
            self.history_schedules_tree.insert("", "end", values=(entry["time"], entry["name"], entry["details"]))

    def _set_or_update_schedule(self):
        """Gathers UI data and passes it to the main app to add or update a schedule."""
        item_data = self.items_for_scheduling_map.get(self.selected_item_display_name.get())
        if not item_data:
            messagebox.showerror("Error", "Please select an item to schedule.", parent=self)
            return

        schedule_details = {
            "type": self.schedule_type_var.get(),
            # Fixed time details
            "action": self.schedule_action_var.get(),
            "time_str": self.schedule_time_var.get(),
            "time_preset": self.time_preset_var.get(),
            "skip_rainy": self.skip_if_rainy_var.get(),
            # Cycle details
            "cycle_on_min": self.cycle_on_duration_var.get(),
            "cycle_off_min": self.cycle_off_duration_var.get(),
            "cycle_count": self.cycle_count_var.get(),
            "cycle_start_time": self.cycle_start_time_var.get(),
            "cycle_start_preset": self.cycle_time_preset_var.get(),
            "cycle_skip_rainy": self.cycle_skip_if_rainy_var.get()
        }

        success = self.master_app.set_schedule_for_item(
            item_type=item_data["type"],
            item_idx=item_data["id"],
            schedule_id=self.editing_schedule_id,
            details=schedule_details
        )

        if success:
            self._populate_all_schedule_views()
            self._reset_fields_for_new_schedule()
            self.master_app.notify(f"Schedule for '{item_data['original_name']}' has been set.")
        else:
            messagebox.showerror("Error", "Failed to set schedule. Please check parameters and try again.", parent=self)

    def _reset_fields_for_new_schedule(self):
        """Resets the input fields to their default state for creating a new schedule."""
        self.editing_schedule_id = None
        self.add_update_btn.config(text="💾 Add Schedule")

        self.schedule_action_var.set("ON")
        self.schedule_time_var.set(datetime.datetime.now().strftime("%H:%M"))
        self.time_preset_var.set("Custom")
        self.skip_if_rainy_var.set(False)

        self.cycle_on_duration_var.set("5")
        self.cycle_off_duration_var.set("10")
        self.cycle_count_var.set("3")
        self.cycle_start_time_var.set(datetime.datetime.now().strftime("%H:%M"))
        self.cycle_time_preset_var.set("Custom")
        self.cycle_skip_if_rainy_var.set(False)

        self.current_schedules_tree.selection_set([])

    def _load_schedule_for_editing(self, event=None):
        """Loads the data from a selected schedule in the treeview into the input fields for editing."""
        selected_iids = self.current_schedules_tree.selection()
        if not selected_iids:
            return

        schedule_id = selected_iids[0]
        schedule_obj, item_obj = self.master_app.find_schedule_by_id(schedule_id)

        if not schedule_obj:
            self._reset_fields_for_new_schedule()
            return

        self.editing_schedule_id = schedule_id
        self.add_update_btn.config(text="💾 Update Schedule")

        # Set the item in the combobox
        item_type = "Valve" if "flow_rate_lpm" in item_obj else "Aux"
        display_name = f"{item_type}: {item_obj['name']} (Pin {item_obj['pin']})"
        self.item_combobox.set(display_name)

        schedule_type = schedule_obj.get('type', 'Fixed Time')
        self.schedule_type_var.set(schedule_type)

        if schedule_type == 'Cycle':
            self.cycle_on_duration_var.set(str(schedule_obj.get('on_m', '5')))
            self.cycle_off_duration_var.set(str(schedule_obj.get('off_m', '10')))
            self.cycle_count_var.set(str(schedule_obj.get('count', '3')))
            self.cycle_start_time_var.set(schedule_obj.get('time', datetime.datetime.now().strftime("%H:%M")))
            self.cycle_skip_if_rainy_var.set(schedule_obj.get('skip_rainy', False))
            self.cycle_time_preset_var.set("Custom") # Reset preset on load
        else: # Fixed Time
            self.schedule_action_var.set(schedule_obj.get('action', 'ON'))
            self.schedule_time_var.set(schedule_obj.get('time', datetime.datetime.now().strftime("%H:%M")))
            self.skip_if_rainy_var.set(schedule_obj.get('skip_rainy', False))
            self.time_preset_var.set("Custom") # Reset preset on load

        self._toggle_schedule_mode_ui()


    def _clear_schedule_from_treeview_selection(self, event=None):
        """Clears schedule(s) for item(s) selected in the CURRENT schedules Treeview list."""
        selected_iids = self.current_schedules_tree.selection()
        if not selected_iids:
            messagebox.showwarning("No Selection", "Please select one or more schedules from the list to clear.", parent=self)
            return

        if not messagebox.askyesno("Confirm Clear", f"Are you sure you want to clear the selected {len(selected_iids)} schedule(s)?", parent=self):
            return

        for schedule_id in selected_iids:
            self.master_app.clear_schedule_by_id(schedule_id)

        self._populate_all_schedule_views()
        self._reset_fields_for_new_schedule()

    def _clear_all_schedules_for_selected_item(self):
        """Clears all schedules for the item currently selected in the combobox."""
        item_data = self.items_for_scheduling_map.get(self.selected_item_display_name.get())
        if not item_data:
            messagebox.showerror("Error", "Please select an item from the dropdown first.", parent=self)
            return

        if not messagebox.askyesno("Confirm Clear All", f"Are you sure you want to remove ALL schedules for '{item_data['original_name']}'?", parent=self):
            return

        self.master_app.clear_all_schedules_for_item(item_data["type"], item_data["id"])
        self.update_idletasks()
        self._populate_all_schedule_views()
        self._reset_fields_for_new_schedule()

    def _clear_all_history_schedules(self):
        """Command for the 'Clear History List' button."""
        if not self.master_app.schedule_history:
            messagebox.showinfo("History Empty", "The schedule history is already empty.", parent=self)
            return
        if not messagebox.askyesno("Confirm Clear History", "Are you sure you want to permanently delete ALL schedule execution history?", icon='warning', parent=self):
            return
        self.master_app.schedule_history.clear()
        self.master_app.save_state()
        self.master_app.log("Schedule history cleared by user.")
        self.master_app.notify("Schedule history has been cleared.", 3000)
        self._populate_all_schedule_views()