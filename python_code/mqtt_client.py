# mqtt_client.py
import threading
import base64
import json
import cv2
import numpy as np
import paho.mqtt.client as mqtt

# =====================================================
# MQTT CONFIG
# =====================================================
BROKER_IP = "192.168.1.10"

VIDEO_TOPIC  = "pi/video/frame"
GYRO_TOPIC   = "pi/gyro/data"
RS485_TOPIC  = "pi/rs485/radar"

# =====================================================
# THREAD-SAFE SHARED DATA
# =====================================================
latest_data = {
    "frame": None,
    "gyro": {},
    "rs485": {}
}

lock = threading.Lock()

# =====================================================
# CALLBACK
# =====================================================
def on_message(client, userdata, msg):
    global latest_data

    with lock:
        if msg.topic == VIDEO_TOPIC:
            jpg = base64.b64decode(msg.payload)
            arr = np.frombuffer(jpg, np.uint8)
            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if frame is not None:
                latest_data["frame"] = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        elif msg.topic == GYRO_TOPIC:
            latest_data["gyro"] = json.loads(msg.payload.decode())

        elif msg.topic == RS485_TOPIC:
            latest_data["rs485"] = json.loads(msg.payload.decode())

# =====================================================
# MQTT LOOP
# =====================================================
def _mqtt_loop():
    client = mqtt.Client()
    client.on_message = on_message
    client.connect(BROKER_IP, 1883, 60)
    client.subscribe([
        (VIDEO_TOPIC, 0),
        (GYRO_TOPIC, 0),
        (RS485_TOPIC, 0)
    ])
    client.loop_forever()

# =====================================================
# START ONCE
# =====================================================
def start_mqtt():
    t = threading.Thread(target=_mqtt_loop, daemon=True)
    t.start()
