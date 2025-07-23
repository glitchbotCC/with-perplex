# smart_farm/mqtt_manager.py

import paho.mqtt.client as mqtt
import json
import random
import threading

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
        
        # Run the MQTT client in a daemon thread. This means the thread will
        # exit automatically when the main application exits.
        mqtt_thread = threading.Thread(target=self._setup_mqtt, daemon=True)
        mqtt_thread.start()

    def _setup_mqtt(self):
        """
        Initializes the Paho MQTT client, sets credentials, defines callbacks,
        and connects to the broker. This method runs in its own thread.
        """
        try:
            # Create a unique client ID to avoid conflicts
            client_id = f"smartfarm-pi-app-{random.randint(1000, 9999)}"
            self.client = mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv311)

            # Assign callback functions
            self.client.on_connect = self._on_connect
            self.client.on_message = self._on_message
            self.client.on_disconnect = self._on_disconnect
            # --- IMPORTANT: These credentials must match your web app ---
            self.client.username_pw_set("glitchbothive", "hive1Aaa")
            
            # Connection details for HiveMQ Cloud
            broker_address = "10c4099f97f641fbab2858a037337cbd.s1.eu.hivemq.cloud"
            port = 8883  # Port 8883 is standard for MQTT over TLS
            self.client.tls_set() # Enable TLS encryption

            self.main_app.log("Attempting to connect to MQTT broker...")
            self.main_app.root.after(0, self.main_app.set_mqtt_status, "Connecting...", "orange")
            self.client.connect(broker_address, port, 60)
            
            # loop_forever() is a blocking call that processes network traffic,
            # dispatches callbacks, and handles reconnecting automatically.
            # Since it's in a separate thread, it won't block the GUI.
            self.client.loop_forever()
        except Exception as e:
            self.main_app.log(f"MQTT setup failed: {e}")

    def _on_connect(self, client, userdata, flags, rc):
        """
        Callback executed when the client connects to the MQTT broker.
        A result code of 0 means a successful connection.
        """
        if rc == 0:
            self.main_app.log("MQTT successfully connected to HiveMQ broker.")
            # Subscribe to the topic where the web UI will send commands
            client.subscribe("smartfarm/web/command", qos=1)
            # Subscribe to the sync topic to handle new web clients
            client.subscribe("smartfarm/system/sync", qos=1)
            # Publish the initial, full state of the application upon connection
            self.publish_state()
            self.main_app.root.after(0, self.main_app.set_mqtt_status, "Connected", "green")
        else:
            self.main_app.log(f"MQTT connection failed with code {rc}")
            self.main_app.root.after(0, self.main_app.set_mqtt_status, f"Failed (Code: {rc})", "red")

    def _on_message(self, client, userdata, msg):
        """
        Callback executed when a message is received from a subscribed topic.
        """
        try:
            payload = json.loads(msg.payload.decode())
            
            # Handle sync requests directly
            if msg.topic == "smartfarm/system/sync" and payload.get("action") == "request_sync":
                self.main_app.log(f"Sync request received from {payload.get('from')}. Publishing full state.")
                self.publish_state()
                return

            # Process other commands from the web UI
            if msg.topic == "smartfarm/web/command":
                command = payload.get("command")
                data = payload.get("data", {})
                self.main_app.log(f"Received MQTT command: {command}")

                # Safely delegate command processing to the main GUI thread
                # to prevent threading issues with Tkinter.
                self.main_app.root.after(0, self.main_app._process_mqtt_command, command, data)
            
        except json.JSONDecodeError:
            self.main_app.log(f"MQTT received malformed JSON on topic {msg.topic}")
        except Exception as e:
            self.main_app.log(f"Error processing MQTT message: {e}")

    def publish_state(self):
        """
        Gathers the current state from the main application, formats it as JSON,
        and publishes it to the state topic for the web UI to consume.
        """
        if self.client and self.client.is_connected():
            try:
                state_dict = self.main_app._get_current_state_as_dict()
                payload = json.dumps(state_dict, indent=4)
                
                # Publish to the state topic with QoS 1 and the Retain flag set to True.
                # Retain=True ensures that any new client subscribing to this topic
                # will immediately receive the last known state.
                self.client.publish("smartfarm/pi/state", payload, qos=1, retain=True)
            except TypeError as e:
                self.main_app.log(f"MQTT Publish Error: Could not serialize state - {e}")
            except Exception as e:
                self.main_app.log(f"MQTT Publish Error: {e}")

    def disconnect(self):
        """
        Cleanly disconnects the MQTT client. This should be called when the
        application is closing.
        """
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()
            self.main_app.log("MQTT client disconnected.")
    
    def _on_disconnect(self, client, userdata, rc):
        """Callback for when the client disconnects from the broker."""
        self.main_app.log("MQTT client disconnected.")
        # Update UI status to "Disconnected" with a red color
        self.main_app.root.after(0, self.main_app.set_mqtt_status, "Disconnected", "red")
