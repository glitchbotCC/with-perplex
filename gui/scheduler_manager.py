# smart_farm/gui/scheduler_manager.py

import datetime
import time
import random
import tkinter as tk
from .. import constants, utils


class SchedulerManagerMixin:
    """Encapsulates schedule management and schedule engine."""

    def _setup_schedule_logic(self, item_obj, schedule_obj):
        job_id = schedule_obj['id']
        if job_id in self.scheduled_jobs:
            try:
                self.root.after_cancel(self.scheduled_jobs[job_id])
            except (tk.TclError, KeyError):
                pass

        is_cycle = schedule_obj['type'] == 'Cycle'
        turn_on = schedule_obj.get('action') == 'ON' if not is_cycle else True
        h, m = map(int, schedule_obj['time'].split(':'))
        schedule_skip_rainy = schedule_obj['skip_rainy']

        def runner():
            current_item_obj = self.find_item_by_pin(item_obj['pin'])
            if not current_item_obj:
                self.log(f"Scheduled task for pin {item_obj['pin']} skipped: item no longer exists.")
                if job_id in self.scheduled_jobs:
                    del self.scheduled_jobs[job_id]
                return

            now = datetime.datetime.now()
            is_rainy = "rain" in self.live_weather_var.get().lower()
            if (turn_on or is_cycle) and schedule_skip_rainy and self.settings.get("enable_rain_skip") and is_rainy:
                self.log(f"Schedule for {current_item_obj['name']} skipped due to Rainy weather.")
            elif now.hour == h and now.minute == m:
                if not current_item_obj.get('locked'):
                    if is_cycle:
                        self.log(f"Cycle for '{current_item_obj['name']}' started.")
                        item_idx = self.valves.index(current_item_obj) if 'flow_rate_lpm' in current_item_obj else self.aux_controls.index(current_item_obj)
                        self.toggle_item(item_idx, 'valve' if 'flow_rate_lpm' in current_item_obj else 'aux', is_on=True)
                    elif current_item_obj['status'] != turn_on:
                        item_idx = self.valves.index(current_item_obj) if 'flow_rate_lpm' in current_item_obj else self.aux_controls.index(current_item_obj)
                        self.toggle_item(item_idx, 'valve' if 'flow_rate_lpm' in current_item_obj else 'aux', is_on=turn_on)

                self.log(f"Fixed time event for '{current_item_obj['name']}' fired. Removing schedule.")
                self.clear_schedule_by_id(job_id, reason='executed')
                return

            self.scheduled_jobs[job_id] = self.root.after(constants.SCHEDULER_CHECK_INTERVAL_S * 1000, runner)

        self.scheduled_jobs[job_id] = self.root.after(1000, runner)
        self.log(f"Schedule armed for '{item_obj['name']}': {self.format_schedule_for_display(schedule_obj)}")

    def _activate_all_schedules(self):
        self.log("Startup: Activating stored schedules...")
        self.scheduled_jobs = {}
        count = 0
        for item in self.valves + self.aux_controls:
            for schedule in item.get('schedules', []):
                try:
                    self._setup_schedule_logic(item, schedule)
                    count += 1
                except Exception as e:
                    self.log(f"Error re-activating schedule {schedule.get('id')} for '{item.get('name')}': {e}")
        self.log(f"Re-activated {count} schedule(s).")

    def set_schedule_for_item(self, item_type, item_idx, schedule_id, details):
        target_list = self.valves if item_type == 'valve' else self.aux_controls
        item_obj = target_list[item_idx]

        try:
            if details['type'] == 'Fixed Time':
                time_str = details['time_str']
                if details['time_preset'] != 'Custom':
                    time_str = self.settings.get(f"virtual_{details['time_preset'].lower()}_time")
                h, m = map(int, time_str.split(':'))
                if not (0 <= h <= 23 and 0 <= m <= 59):
                    raise ValueError('Invalid time')
                new_schedule = {'type': 'Fixed Time', 'action': details['action'], 'time': f"{h:02d}:{m:02d}", 'skip_rainy': details['skip_rainy']}
            elif details['type'] == 'Cycle':
                start_time = details['cycle_start_time']
                if details['cycle_start_preset'] != 'Custom':
                    start_time = self.settings.get(f"virtual_{details['cycle_start_preset'].lower()}_time")
                h, m = map(int, start_time.split(':'))
                on_m = int(details['cycle_on_min'])
                off_m = int(details['cycle_off_min'])
                count = int(details['cycle_count'])
                if not (0 <= h <= 23 and 0 <= m <= 59 and on_m > 0 and off_m > 0 and count >= 0):
                    raise ValueError('Invalid cycle params')
                new_schedule = {'type': 'Cycle', 'time': f"{h:02d}:{m:02d}", 'on_m': on_m, 'off_m': off_m, 'count': count, 'skip_rainy': details['cycle_skip_rainy']}
            else:
                return False

        except (ValueError, TypeError):
            return False

        if schedule_id:
            for i, sched in enumerate(item_obj['schedules']):
                if sched['id'] == schedule_id:
                    new_schedule['id'] = schedule_id
                    item_obj['schedules'][i] = new_schedule
                    break
        else:
            new_schedule['id'] = f"sched_{int(time.time() * 1000)}_{random.randint(100, 999)}"
            item_obj.setdefault('schedules', []).append(new_schedule)

        self._setup_schedule_logic(item_obj, new_schedule)
        self.save_state()
        if item_type == 'valve':
            self.filter_valves()
        else:
            self.update_aux_controls_ui()
        if self.scheduler_window and self.scheduler_window.winfo_exists():
            self.scheduler_window._populate_all_schedule_views()

        return True

    def clear_schedule_by_id(self, schedule_id, reason='manual'):
        schedule_obj, item_obj = self.find_schedule_by_id(schedule_id)
        if schedule_obj and item_obj:
            if reason == 'executed':
                history_entry = {
                    'name': item_obj['name'],
                    'details': self.format_schedule_for_display(schedule_obj),
                    'time': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                self.schedule_history.insert(0, history_entry)
                if len(self.schedule_history) > 200:
                    self.schedule_history = self.schedule_history[:200]

            if schedule_id in self.scheduled_jobs:
                try:
                    self.root.after_cancel(self.scheduled_jobs.pop(schedule_id))
                except (tk.TclError, KeyError):
                    pass

            item_obj['schedules'] = [s for s in item_obj.get('schedules', []) if s['id'] != schedule_id]
            self.log(f"Schedule '{schedule_id}' for '{item_obj['name']}' cleared.")
            self.save_state()
            self.filter_valves()
            self.update_aux_controls_ui()
            return True
        return False

    def clear_all_schedules_for_item(self, item_type, item_idx):
        target_list = self.valves if item_type == 'valve' else self.aux_controls
        item_obj = target_list[item_idx]
        for schedule in list(item_obj.get('schedules', [])):
            self.clear_schedule_by_id(schedule['id'])

    def clear_all_pending_schedules(self):
        for item in self.valves + self.aux_controls:
            for schedule in list(item.get('schedules', [])):
                self.clear_schedule_by_id(schedule['id'])
        self.log("Cleared all pending schedules from all devices.")

    def find_schedule_by_id(self, schedule_id):
        for item in self.valves + self.aux_controls:
            for schedule in item.get('schedules', []):
                if schedule['id'] == schedule_id:
                    return schedule, item
        return None, None
