# smart_farm/gui/automation_window.py

import tkinter as tk
from tkinter import ttk, messagebox

class AutomationWindow(tk.Toplevel):
    """A Toplevel window for creating and managing sensor-based automation rules."""
    def __init__(self, master_app):
        super().__init__(master_app.root)
        self.master_app = master_app
        self.transient(master_app.root)
        self.title("🤖 Automation Rules")
        self.geometry("900x600")
        self.resizable(True, True)
        self.grab_set()

        self.sensor_var = tk.StringVar()
        self.condition_var = tk.StringVar()
        self.value_var = tk.StringVar()
        self.action_var = tk.StringVar()
        self.target_var = tk.StringVar()
        self.duration_var = tk.StringVar(value="10")

        self.configure(bg=self.master_app.style.lookup(".", "background"))
        self._setup_ui()
        self._populate_rules_treeview()

    @staticmethod
    def format_rule_for_display(rule):
        """Creates a human-readable string from a rule dictionary."""
        if rule['sensor'] == "Soil Moisture":
            condition_str = f"Soil Moisture is {rule['value']}"
        else:
            unit = "°C" if "Temp" in rule['sensor'] else "%"
            condition_str = f"{rule['sensor']} {rule['condition']} {rule['value']}{unit}"

        action_str = f"{rule['action']} {rule['target']}"
        if rule['action'] == 'Turn ON':
            action_str += f" for {rule['duration_min']} min"

        return f"IF {condition_str} THEN {action_str}"


    def _setup_ui(self):
        main_frame = ttk.Frame(self, padding=15, style="TFrame")
        main_frame.pack(fill=tk.BOTH, expand=True)
        main_frame.columnconfigure(1, weight=1)

        # --- Rule Creation Frame ---
        create_frame = ttk.Labelframe(main_frame, text="Create New Rule", style="Card.TFrame", padding=15)
        create_frame.pack(fill=tk.X, pady=(0, 15))
        create_frame.columnconfigure(1, weight=1)

        # --- IF (Trigger) ---
        if_frame = ttk.Frame(create_frame, style="Card.TFrame")
        if_frame.grid(row=0, column=0, columnspan=3, padx=5, pady=10, sticky='nsew')
        if_frame.columnconfigure(1, weight=1)
        ttk.Label(if_frame, text="IF (Trigger)", font=('Segoe UI', 12, 'bold')).grid(row=0, column=0, columnspan=2, sticky='w', padx=5, pady=5)

        ttk.Label(if_frame, text="Sensor:").grid(row=1, column=0, padx=5, pady=5, sticky='w')
        self.sensor_cb = ttk.Combobox(if_frame, textvariable=self.sensor_var, state="readonly",
                                      values=["Soil Moisture", "Temp (DHT22)", "Humidity (DHT22)", "Temp (DHT11)", "Humidity (DHT11)"])
        self.sensor_cb.grid(row=1, column=1, padx=5, pady=5, sticky='ew')
        self.sensor_cb.bind("<<ComboboxSelected>>", self._update_condition_ui)
        self.sensor_cb.current(0)

        self.condition_frame = ttk.Frame(if_frame, style="Card.TFrame")
        self.condition_frame.grid(row=2, column=0, columnspan=2, padx=5, pady=5, sticky='ew')
        self.condition_frame.columnconfigure(1, weight=1)

        # --- THEN (Action) ---
        then_frame = ttk.Frame(create_frame, style="Card.TFrame")
        then_frame.grid(row=1, column=0, columnspan=3, padx=5, pady=10, sticky='nsew')
        then_frame.columnconfigure(1, weight=1)
        ttk.Label(then_frame, text="THEN (Action)", font=('Segoe UI', 12, 'bold')).grid(row=0, column=0, columnspan=2, sticky='w', padx=5, pady=5)

        ttk.Label(then_frame, text="Action:").grid(row=1, column=0, padx=5, pady=5, sticky='w')
        self.action_cb = ttk.Combobox(then_frame, textvariable=self.action_var, state="readonly", values=["Turn ON", "Turn OFF"])
        self.action_cb.grid(row=1, column=1, padx=5, pady=5, sticky='ew')
        self.action_cb.bind("<<ComboboxSelected>>", self._toggle_duration_entry)
        self.action_cb.current(0)

        ttk.Label(then_frame, text="Target:").grid(row=2, column=0, padx=5, pady=5, sticky='w')
        self.target_cb = ttk.Combobox(then_frame, textvariable=self.target_var, state="readonly")
        self.target_cb.grid(row=2, column=1, padx=5, pady=5, sticky='ew')
        self._populate_target_devices()

        self.duration_frame = ttk.Frame(then_frame, style="Card.TFrame")
        self.duration_frame.grid(row=3, column=1, padx=5, pady=5, sticky='w')
        ttk.Label(self.duration_frame, text="for").pack(side=tk.LEFT)
        self.duration_entry = ttk.Entry(self.duration_frame, textvariable=self.duration_var, width=5)
        self.duration_entry.pack(side=tk.LEFT, padx=3)
        ttk.Label(self.duration_frame, text="minutes").pack(side=tk.LEFT)

        # --- Buttons ---
        action_button_frame = ttk.Frame(create_frame, style="Card.TFrame")
        action_button_frame.grid(row=2, column=0, columnspan=3, pady=10, sticky='ew')
        action_button_frame.columnconfigure(0, weight=1)
        action_button_frame.columnconfigure(1, weight=1)

        add_btn = ttk.Button(action_button_frame, text="💾 Add Rule", command=self._add_rule, style="Accent.TButton")
        add_btn.grid(row=0, column=0, padx=(0, 5), sticky='ew')

        remove_btn = ttk.Button(action_button_frame, text="🗑️ Remove Selected Rule", command=self._remove_rule, style="TButton")
        remove_btn.grid(row=0, column=1, padx=(5, 0), sticky='ew')

        # --- Active Rules List ---
        list_frame = ttk.Labelframe(main_frame, text="Active Rules", style="Card.TFrame", padding=10)
        list_frame.pack(fill=tk.BOTH, expand=True)

        self.rules_tree = ttk.Treeview(list_frame, columns=("rule",), show="headings", style="Treeview")
        self.rules_tree.heading("rule", text="Rule Description")
        self.rules_tree.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)

        tree_scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.rules_tree.yview)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.rules_tree.configure(yscrollcommand=tree_scroll.set)

        self._update_condition_ui()
        self._toggle_duration_entry()

    def _update_condition_ui(self, event=None):
        """Dynamically create the UI for the condition based on the selected sensor."""
        for widget in self.condition_frame.winfo_children():
            widget.destroy()

        sensor = self.sensor_var.get()

        ttk.Label(self.condition_frame, text="Condition:").grid(row=0, column=0, padx=5, pady=5, sticky='w')

        if sensor == "Soil Moisture":
            self.condition_var.set("is")
            value_cb = ttk.Combobox(self.condition_frame, textvariable=self.value_var, state="readonly", values=["Wet", "Dry"])
            value_cb.grid(row=0, column=1, padx=5, pady=5, sticky='ew')
            value_cb.set("Dry")
        else:
            condition_cb = ttk.Combobox(self.condition_frame, textvariable=self.condition_var, state="readonly", values=[">", "<", "=="], width=4)
            condition_cb.grid(row=0, column=1, padx=5, pady=5, sticky='w')
            condition_cb.set(">")

            value_entry = ttk.Entry(self.condition_frame, textvariable=self.value_var, width=8)
            value_entry.grid(row=0, column=2, padx=5, pady=5, sticky='w')

            unit = "°C" if "Temp" in sensor else "%"
            ttk.Label(self.condition_frame, text=unit).grid(row=0, column=3, padx=5, pady=5, sticky='w')

    def _toggle_duration_entry(self, event=None):
        """Show or hide the duration entry based on the selected action."""
        if self.action_var.get() == "Turn ON":
            self.duration_frame.grid()
        else:
            self.duration_frame.grid_remove()

    def _populate_target_devices(self):
        """Populate the target device combobox."""
        targets = [f"Valve: {v['name']}" for v in self.master_app.valves] + \
                  [f"Aux: {a['name']}" for a in self.master_app.aux_controls]
        self.target_cb['values'] = targets
        if targets:
            self.target_cb.current(0)

    def _add_rule(self):
        """Validates and adds a new automation rule."""
        sensor = self.sensor_var.get()
        condition = self.condition_var.get()
        value = self.value_var.get()
        action = self.action_var.get()
        target_str = self.target_var.get()
        duration = self.duration_var.get()

        if not all([sensor, condition, value, action, target_str]):
            messagebox.showerror("Error", "All fields must be filled out.", parent=self)
            return

        if sensor != "Soil Moisture":
            try:
                float(value)
            except ValueError:
                messagebox.showerror("Error", "Value must be a number for this sensor type.", parent=self)
                return

        if action == "Turn ON":
            try:
                if int(duration) <= 0: raise ValueError
            except ValueError:
                messagebox.showerror("Error", "Duration must be a positive number of minutes.", parent=self)
                return

        rule = {
            "sensor": sensor,
            "condition": condition,
            "value": value,
            "action": action,
            "target": target_str,
            "duration_min": int(duration) if action == "Turn ON" else None,
            "last_triggered": None # Timestamp to prevent rapid re-triggering
        }

        self.master_app.automation_rules.append(rule)
        self.master_app.save_state()
        self.master_app.log(f"Automation rule added: {self.format_rule_for_display(rule)}")
        self.notify("Automation rule added.", 3000)
        self._populate_rules_treeview()

    def _remove_rule(self, event=None):
        """Removes the selected rule from the list."""
        selected_item = self.rules_tree.selection()
        if not selected_item:
            messagebox.showwarning("No Selection", "Please select a rule from the list to remove.", parent=self)
            return

        selected_iid = selected_item[0]
        rule_index = self.rules_tree.index(selected_iid)

        if messagebox.askyesno("Confirm", "Are you sure you want to remove the selected rule?", parent=self):
            removed_rule = self.master_app.automation_rules.pop(rule_index)
            self.master_app.save_state()
            self.master_app.log(f"Automation rule removed: {self.format_rule_for_display(removed_rule)}")
            self.notify("Automation rule removed.", 3000)
            self._populate_rules_treeview()

    def _populate_rules_treeview(self):
        """Fills the treeview with the current automation rules."""
        for i in self.rules_tree.get_children():
            self.rules_tree.delete(i)

        for rule in self.master_app.automation_rules:
            self.rules_tree.insert("", "end", values=(self.format_rule_for_display(rule),))

    def notify(self, msg, duration=3500):
        """ Displays a temporary message in the window title. """
        self.title(f"🤖 Automation Rules - {msg}")
        self.after(duration, lambda: self.title("🤖 Automation Rules"))