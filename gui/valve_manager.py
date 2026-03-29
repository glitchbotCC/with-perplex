# smart_farm/gui/valve_manager.py

import json
import datetime
import time
import tkinter as tk
from tkinter import simpledialog, messagebox
try:
    from .. import constants, utils
except ImportError:
    import constants, utils


class ValveManagerMixin:
    """Encapsulates valve and aux control operations."""

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
                if plant in valve["name"].lower():
                    valve["icon"] = emoji
                    break
            else:
                valve["icon"] = '💧'
            self.save_state()
            self.filter_valves()
            self.notify(f"Valve '{old_name}' renamed.")

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

    def toggle_aux_control(self, idx):
        self.toggle_item(idx, "aux")

    def toggle_item(self, idx, item_type, is_on=None, duration_min=None):
        item_list = self.valves if item_type == "valve" else self.aux_controls
        item = item_list[idx]

        if item.get("locked"):
            self.notify(f"'{item['name']}' is locked.")
            return

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
            else:
                self._update_valve_on_time_end(idx)

            ts = datetime.datetime.now().isoformat(sep=' ', timespec='seconds')
            item.setdefault("history", []).append((ts, log_msg))

        self.log(f"{item_type.title()} '{item['name']}' (Pin {item['pin']}) toggled {action_str}.")
        self.save_state()

        if item_type == "valve":
            self.filter_valves()
        else:
            self.update_aux_controls_ui()

        self.update_dashboard()

        if hasattr(self, 'map_canvas') and self.map_canvas.winfo_exists():
            self._draw_map_sections()

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
        if not messagebox.askyesno("Remove", f"Remove '{valve['name']}' & all its schedules?", icon='warning'):
            return

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

        if not self.undo_stack:
            self.notify("Nothing to undo.")
            return

        if len(self.valves) >= constants.MAX_VALVES:
            self.notify(f"Max valves reached. Cannot restore.")
            return

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
            self.notify("Copy failed.")
            self.log(f"Error copying valve config: {e}")

    def show_valve_history(self, idx):
        valve = self.valves[idx]
        hist = valve.get("history", [])
        msg = f"History for {valve['name']} (Pin {valve['pin']}):\n{'-'*50}\n\n"
        if not hist:
            msg += "No history entries."
        else:
            msg += "\n".join([f"• {ts}: {ev}" for ts, ev in reversed(hist[-25:])])
        if len(hist) > 25:
            msg += f"\n\n(...and {len(hist)-25} older entries not shown)"
        messagebox.showinfo(f"History: {valve['name']}", msg, parent=self.root)
