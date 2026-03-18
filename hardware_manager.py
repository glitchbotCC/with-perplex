# smart_farm/hardware_manager.py

import random
from . import constants

# --- Raspberry Pi GPIO and Sensor Integration ---
IS_RASPBERRY_PI = False
try:
    import board
    import adafruit_dht
    import RPi.GPIO as GPIO
    IS_RASPBERRY_PI = True
    print("Success: RPi.GPIO and Adafruit CircuitPython libraries found. Running in Raspberry Pi mode.")
except (ImportError, RuntimeError, NotImplementedError):
    print("Warning: Hardware libraries not found. Running in simulation mode.")

class HardwareManager:
    """ Manages all hardware interactions (GPIO, sensors) for the application. """

    def __init__(self):
        self.is_pi = IS_RASPBERRY_PI
        self.dht22_sensor = None
        self.dht11_sensor = None

        if self.is_pi:
            self._initialize_gpio()
            self._initialize_sensors()
        else:
            self.simulated_moisture = "Dry"

    def _initialize_gpio(self):
        """ Sets up all GPIO pins as outputs and initializes them to LOW. """
        try:
            GPIO.setwarnings(False)
            GPIO.setmode(GPIO.BCM)
            output_pins = constants.GPIO_PINS + constants.EXTRA_GPIO_PINS
            for pin in output_pins:
                GPIO.setup(pin, GPIO.OUT)
                GPIO.output(pin, GPIO.LOW)
            # Setup moisture sensor pin as input
            GPIO.setup(constants.MOISTURE_SENSOR_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            print("GPIO setup complete.")
        except Exception as e:
            print(f"FATAL: An error occurred during GPIO setup: {e}")
            self.is_pi = False # Fallback to simulation mode on error

    def _initialize_sensors(self):
        """ Initializes DHT sensor objects. """
        try:
            # use_pulseio=False is important for compatibility with other libraries
            self.dht22_sensor = adafruit_dht.DHT22(getattr(board, f"D{constants.TEMP_HUMIDITY_SENSOR_PIN}"), use_pulseio=False)
            print(f"DHT22 sensor object created for GPIO {constants.TEMP_HUMIDITY_SENSOR_PIN}.")
        except Exception as e:
            print(f"Warning: Could not initialize DHT22 sensor: {e}")

        try:
            self.dht11_sensor = adafruit_dht.DHT11(getattr(board, f"D{constants.TEMP_HUMIDITY_SENSOR_PIN_DHT11}"), use_pulseio=False)
            print(f"DHT11 sensor object created for GPIO {constants.TEMP_HUMIDITY_SENSOR_PIN_DHT11}.")
        except Exception as e:
            print(f"Warning: Could not initialize DHT11 sensor: {e}")

    def set_pin_state(self, pin, is_on):
        """ Sets the physical state of a single GPIO pin. """
        state_str = "ON" if is_on else "OFF"
        if self.is_pi:
            try:
                state = GPIO.HIGH if is_on else GPIO.LOW
                GPIO.output(pin, state)
            except Exception as e:
                print(f"ERROR: Failed to set pin {pin} state: {e}")
        else:
            # In simulation mode, we just print the action
            print(f"SIMULATE: Set pin {pin} to {state_str}")

    def read_dht22(self):
        """ Reads temperature and humidity from the DHT22 sensor. """
        if self.is_pi and self.dht22_sensor:
            try:
                self.dht22_sensor.measure()
                return self.dht22_sensor.temperature, self.dht22_sensor.humidity
            except (RuntimeError, OSError): # Add OSError for robustness
                return "Failed", "Failed" # Often occurs on read failures
        # Simulation data
        return 24.5 + random.uniform(-0.5, 0.5), 55.2 + random.uniform(-1, 1)

    def read_dht11(self):
        """ Reads temperature and humidity from the DHT11 sensor. """
        if self.is_pi and self.dht11_sensor:
            try:
                self.dht11_sensor.measure()
                return self.dht11_sensor.temperature, self.dht11_sensor.humidity
            except (RuntimeError, OSError):
                return "Failed", "Failed"
        # Simulation data
        return 25.0 + random.uniform(-0.5, 0.5), 60.0 + random.uniform(-1, 1)

    def read_moisture(self):
        """ Reads the state from the digital soil moisture sensor. """
        if self.is_pi:
            try:
                return "Wet" if GPIO.input(constants.MOISTURE_SENSOR_PIN) == GPIO.LOW else "Dry"
            except Exception:
                return "Not Connected"
        # Simulation data
        if random.random() < 0.1: # Occasionally flip the state
            self.simulated_moisture = "Wet" if self.simulated_moisture == "Dry" else "Dry"
        return self.simulated_moisture

    def cleanup(self):
        """ Cleans up GPIO resources on application exit. """
        if self.is_pi:
            try:
                print("Cleaning up GPIO resources...")
                GPIO.cleanup()
                print("GPIO cleanup successful.")
            except Exception as e:
                print(f"Error during GPIO cleanup: {e}")