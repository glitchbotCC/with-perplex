# smart_farm/gui/mqtt_manager.py

import paho.mqtt.client as mqtt
import json
import random
import threading
import certifi # <-- 1. IMPORT THE NEW LIBRARY

class MqttManager:
    """
    Handles all MQTT communication for the Smart Farm application.
    It connects to the broker, publishes state changes, and listens for commands
    from the web interface.
    """
    def __init__(self, main_app):
        """
        Initializes the MQTT Manager. The connection logic is run in a separate
        thread to prevent blocking the main GUI thread.

        Args:
            main_app: A reference to the main MainWindow instance.
        """
        self.main_app = main_app
        self.client = None
        
        mqtt_thread = threading.Thread(target=self._setup_mqtt, daemon=True)
        mqtt_thread.start()

    def _setup_mqtt(self):
        """
        Initializes the Paho MQTT client, sets credentials, defines callbacks,
        and connects to the broker. This method runs in its own thread.
        """
        try:
            client_id = f"smartfarm-pi-app-{random.randint(1000, 9999)}"
            self.client = mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv311)

            self.client.on_connect = self._on_connect
            self.client.on_message = self._on_message
            self.client.on_disconnect = self._on_disconnect
            
            self.client.username_pw_set("glitchbothive", "hive1Aaa")
            
            broker_address = "10c4099f97f641fbab2858a037337cbd.s1.eu.hivemq.cloud"
            port = 8883
            
            # --- 2. THIS IS THE CRITICAL CHANGE ---
            # Explicitly tell the client to use the certificates from the certifi library.
            self.client.tls_set(certifi.where())

            self.main_app.log("Attempting to connect to MQTT broker...")
            self.main_app.set_mqtt_status("Connecting...", "orange")
            
            self.client.connect(broker_address, port, 60)
            self.client.loop_forever()
            
        except Exception as e:
            self.main_app.log(f"MQTT setup failed: {e}")
            self.main_app.set_mqtt_status("Setup Failed", "red")

    def _on_connect(self, client, userdata, flags, rc):
        """
        Callback executed when the client connects to the MQTT broker.
        """
        if rc == 0:
            self.main_app.log("MQTT successfully connected to HiveMQ broker.")
            client.subscribe("smartfarm/web/command", qos=1)
            client.subscribe("smartfarm/system/sync", qos=1)
            self.publish_state()
            self.main_app.set_mqtt_status("Connected", "green")
        else:
            self.main_app.log(f"MQTT connection failed with code {rc}")
            self.main_app.set_mqtt_status(f"Failed (Code: {rc})", "red")

    def _on_disconnect(self, client, userdata, rc):
        """Callback for when the client disconnects from the broker."""
        self.main_app.log("MQTT client disconnected.")
        self.main_app.set_mqtt_status("Disconnected", "red")

    def _on_message(self, client, userdata, msg):
        """
        Callback executed when a message is received from a subscribed topic.
        """
        try:
            payload = json.loads(msg.payload.decode())
            
            if msg.topic == "smartfarm/system/sync" and payload.get("action") == "request_sync":
                self.main_app.log(f"Sync request received from {payload.get('from')}. Publishing full state.")
                self.publish_state()
                return

            if msg.topic == "smartfarm/web/command":
                command = payload.get("command")
                data = payload.get("data", {})
                self.main_app.log(f"Received MQTT command: {command}")
                self.main_app.root.after(0, self.main_app._process_mqtt_command, command, data)
            
        except Exception as e:
            self.main_app.log(f"Error processing MQTT message: {e}")

    def publish_state(self):
        """
        Publishes the entire application state to the MQTT broker.
        """
        if self.client and self.client.is_connected():
            try:
                state_dict = self.main_app._get_current_state_as_dict()
                payload = json.dumps(state_dict, indent=4)
                self.client.publish("smartfarm/pi/state", payload, qos=1, retain=True)
            except Exception as e:
                self.main_app.log(f"MQTT Publish Error: {e}")

    def disconnect(self):
        """
        Cleanly disconnects the MQTT client.
        """
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()
            self.main_app.log("MQTT client disconnected.")
# smart_farm/gui/mqtt_manager.py

import paho.mqtt.client as mqtt
import json
import random
import threading
import certifi # <-- 1. IMPORT THE NEW LIBRARY

class MqttManager:
    """
    Handles all MQTT communication for the Smart Farm application.
    It connects to the broker, publishes state changes, and listens for commands
    from the web interface.
    """
    def __init__(self, main_app):
        """
        Initializes the MQTT Manager. The connection logic is run in a separate
        thread to prevent blocking the main GUI thread.

        Args:
            main_app: A reference to the main MainWindow instance.
        """
        self.main_app = main_app
        self.client = None
        
        mqtt_thread = threading.Thread(target=self._setup_mqtt, daemon=True)
        mqtt_thread.start()

    def _setup_mqtt(self):
        """
        Initializes the Paho MQTT client, sets credentials, defines callbacks,
        and connects to the broker. This method runs in its own thread.
        """
        try:
            client_id = f"smartfarm-pi-app-{random.randint(1000, 9999)}"
            self.client = mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv311)

            self.client.on_connect = self._on_connect
            self.client.on_message = self._on_message
            self.client.on_disconnect = self._on_disconnect
            
            self.client.username_pw_set("glitchbothive", "hive1Aaa")
            
            broker_address = "10c4099f97f641fbab2858a037337cbd.s1.eu.hivemq.cloud"
            port = 8883
            
            # --- 2. THIS IS THE CRITICAL CHANGE ---
            # Explicitly tell the client to use the certificates from the certifi library.
            self.client.tls_set(certifi.where())

            self.main_app.log("Attempting to connect to MQTT broker...")
            self.main_app.set_mqtt_status("Connecting...", "orange")
            
            self.client.connect(broker_address, port, 60)
            self.client.loop_forever()
            
        except Exception as e:
            self.main_app.log(f"MQTT setup failed: {e}")
            self.main_app.set_mqtt_status("Setup Failed", "red")

    def _on_connect(self, client, userdata, flags, rc):
        """
        Callback executed when the client connects to the MQTT broker.
        """
        if rc == 0:
            self.main_app.log("MQTT successfully connected to HiveMQ broker.")
            client.subscribe("smartfarm/web/command", qos=1)
            client.subscribe("smartfarm/system/sync", qos=1)
            self.publish_state()
            self.main_app.set_mqtt_status("Connected", "green")
        else:
            self.main_app.log(f"MQTT connection failed with code {rc}")
            self.main_app.set_mqtt_status(f"Failed (Code: {rc})", "red")

    def _on_disconnect(self, client, userdata, rc):
        """Callback for when the client disconnects from the broker."""
        self.main_app.log("MQTT client disconnected.")
        self.main_app.set_mqtt_status("Disconnected", "red")

    def _on_message(self, client, userdata, msg):
        """
        Callback executed when a message is received from a subscribed topic.
        """
        try:
            payload = json.loads(msg.payload.decode())
            
            if msg.topic == "smartfarm/system/sync" and payload.get("action") == "request_sync":
                self.main_app.log(f"Sync request received from {payload.get('from')}. Publishing full state.")
                self.publish_state()
                return

            if msg.topic == "smartfarm/web/command":
                command = payload.get("command")
                data = payload.get("data", {})
                self.main_app.log(f"Received MQTT command: {command}")
                self.main_app.root.after(0, self.main_app._process_mqtt_command, command, data)
            
        except Exception as e:
            self.main_app.log(f"Error processing MQTT message: {e}")

    def publish_state(self):
        """
        Publishes the entire application state to the MQTT broker.
        """
        if self.client and self.client.is_connected():
            try:
                state_dict = self.main_app._get_current_state_as_dict()
                payload = json.dumps(state_dict, indent=4)
                self.client.publish("smartfarm/pi/state", payload, qos=1, retain=True)
            except Exception as e:
                self.main_app.log(f"MQTT Publish Error: {e}")

    def disconnect(self):
        """
        Cleanly disconnects the MQTT client.
        """
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()
            self.main_app.log("MQTT client disconnected.")
