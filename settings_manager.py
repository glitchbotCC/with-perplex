# smart_farm/settings_manager.py

import json
import os
from . import utils
from . import constants

class PersistentSettings:
    """ Handles loading and saving of application settings to a JSON file. """
    def __init__(self, filename=constants.SETTINGS_FILE):
        self.filename = utils.resource_path(filename)
        self.data = {}
        self.load()

    def _get_default_settings(self):
        """ Returns a dictionary containing all default application settings. """
        return {
            "theme": "dark",
            "location": "London,UK",
            "valves": [],
            "aux_controls": [],
            "automation_rules": [],
            "schedule_history": [],
            "logs": [],
            "virtual_sunrise_time": "06:00",
            "virtual_sunset_time": "18:30",
            "enable_rain_skip": True,
        }

    def load(self):
        """
        Loads settings from the JSON file.
        If the file doesn't exist, is corrupt, or a key is missing,
        it falls back to default values for the missing parts or the entire settings.
        """
        default_settings = self._get_default_settings()
        if os.path.exists(self.filename):
            try:
                with open(self.filename, "r", encoding='utf-8') as f:
                    loaded_data = json.load(f)
                    self.data = default_settings.copy()
                    self.data.update(loaded_data)
            except json.JSONDecodeError:
                print(f"Error: Corrupt JSON data in {self.filename}. Using default settings.")
                self.data = default_settings
            except FileNotFoundError:
                print(f"Error: Settings file {self.filename} not found. Using default settings.")
                self.data = default_settings
            except Exception as e:
                print(f"An unexpected error occurred while loading settings from {self.filename}: {e}. Using defaults.")
                self.data = default_settings
        else:
            print(f"Settings file {self.filename} does not exist. Using default settings.")
            self.data = default_settings

        # Ensure all default keys exist in the loaded data
        for key, value in default_settings.items():
            self.data.setdefault(key, value)

    def save(self):
        """ Saves the current settings dictionary (self.data) to the JSON file. """
        try:
            with open(self.filename, "w", encoding='utf-8') as f:
                json.dump(self.data, f, indent=4)
        except Exception as e:
            print(f"Error saving settings to {self.filename}: {e}")

    def get(self, key, default_override=None):
        """
        Retrieves a setting value by its key.
        - If 'default_override' is provided, it's used if the key is not found in self.data.
        - Otherwise, the default value for that key from `_get_default_settings` is used.
        """
        default_value_from_schema = self._get_default_settings().get(key)
        if default_override is not None:
            return self.data.get(key, default_override)
        return self.data.get(key, default_value_from_schema)

    def set(self, key, value):
        """ Sets a setting value for a given key and immediately saves all settings. """
        self.data[key] = value
        self.save()