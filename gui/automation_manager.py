# smart_farm/gui/automation_manager.py

import time
from .automation_window import AutomationWindow


class AutomationManagerMixin:
    """Encapsulates automation rule evaluation logic."""

    def check_automation_rules(self):
        now = time.time()
        for i, rule in enumerate(self.automation_rules):
            if rule.get('last_triggered') and (now - rule['last_triggered'] < 300):
                continue

            current_value = None
            triggered = False

            if rule['sensor'] == 'Soil Moisture':
                current_value = self.sensor_moisture.get().split(' ')[-1]
            elif rule['sensor'] == 'Temp (DHT22)':
                try:
                    current_value = float(self.sensor_temp_c.get().split('°')[0])
                except Exception:
                    continue
            elif rule['sensor'] == 'Humidity (DHT22)':
                try:
                    current_value = float(self.sensor_humidity.get().split('%')[0])
                except Exception:
                    continue
            elif rule['sensor'] == 'Temp (DHT11)':
                try:
                    current_value = float(self.sensor_temp_c_dht11.get().split('°')[0])
                except Exception:
                    continue
            elif rule['sensor'] == 'Humidity (DHT11)':
                try:
                    current_value = float(self.sensor_humidity_dht11.get().split('%')[0])
                except Exception:
                    continue

            if current_value is None:
                continue

            try:
                rule_val = float(rule['value']) if rule['sensor'] != 'Soil Moisture' else rule['value']
                if rule['condition'] == 'is' and current_value == rule_val:
                    triggered = True
                elif rule['condition'] == '>' and current_value > rule_val:
                    triggered = True
                elif rule['condition'] == '<' and current_value < rule_val:
                    triggered = True
                elif rule['condition'] == '==' and current_value == rule_val:
                    triggered = True
            except (ValueError, TypeError):
                continue

            if triggered:
                self.log(f"Automation rule triggered: {AutomationWindow.format_rule_for_display(rule)}")
                self.automation_rules[i]['last_triggered'] = now
                target_type, target_name = rule['target'].split(': ')
                item_list = self.valves if target_type == 'Valve' else self.aux_controls
                for idx, item in enumerate(item_list):
                    if item['name'] == target_name:
                        action_on = rule['action'] == 'Turn ON'
                        if item.get('status') != action_on:
                            self.toggle_item(idx, target_type.lower(), is_on=action_on, duration_min=rule.get('duration_min'))
                        break

        if hasattr(self, 'root') and self.root.winfo_exists():
            self.root.after(10000, self.check_automation_rules)
