# smart_farm/constants.py

# --- Global Application Constants ---
APP_NAME = "Smart Farm Valve Control (Pi Edition)"
APP_VERSION = "4.3.0-queuing"
# CHANGE THIS LINE BACK TO THE DEFAULT
SETTINGS_FILE = "valve_app_settings.json"
MAX_VALVES = 5
SCHEDULER_CHECK_INTERVAL_S = 5
# IMPORTANT: Replace with your own key from https://openweathermap.org/
API_KEY = "d7b8a4a58f2d8f3f8b9e8a7b9c8d7e6f"

# --- GPIO Pin Constants ---
# Pins for the primary irrigation valves (BCM numbering)
GPIO_PINS = [17, 18, 27, 22, 23, 24, 25, 5, 6, 12]
# Pins for auxiliary controls (pumps, lights, etc.)
EXTRA_GPIO_PINS = [13, 19, 21, 16]

# --- Sensor Pin Constants ---
# Note: These are BCM pin numbers
TEMP_HUMIDITY_SENSOR_PIN = 4      # For DHT22
TEMP_HUMIDITY_SENSOR_PIN_DHT11 = 26 # For DHT11
MOISTURE_SENSOR_PIN = 20          # For Capacitive Soil Moisture Sensor

# --- UI Dictionaries ---
# Dictionary mapping plant name keywords to their corresponding emojis
PLANT_EMOJIS = {
    "tomato": "🍅", "pepper": "🌶️", "corn": "🌽", "lettuce": "🥬",
    "carrot": "🥕", "broccoli": "🥦", "flower": "🌸", "rose": "🌹",
    "sunflower": "🌻", "tree": "🌳", "herb": "🌿", "melon": "🍉",
    "pump": "🎃", "plant": "🌱", "garden": "🪴", "Grape": "🍇", "berry": "🍓", "Groubd nut":"🥜"
}

# Dictionary for weather condition icons
WEATHER_ICONS = {
    "Clear": "☀️", "Clouds": "☁️", "Drizzle": "💧", "Rain": "🌧️",
    "Thunderstorm": "⛈️", "Snow": "❄️", "Mist": "🌫️", "Smoke": "💨",
    "Haze": "🌫️", "Dust": "💨", "Fog": "🌫️", "Sand": "💨",
    "Ash": "💨", "Squall": "💨", "Tornado": "🌪️"
}
