# ~/work/control/rn_mqtt_worker.py
import os
import json
import time
import threading
from datetime import datetime

import requests
import paho.mqtt.client as mqtt
import board
import adafruit_dht
from dotenv import load_dotenv

from led import LED
from fan import Fan

# .env 로드 (이 파일과 같은 디렉토리 기준)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

def env(name: str, default: str | None = None) -> str:
    v = os.getenv(name, default)
    if v is None:
        raise RuntimeError(f"Missing env: {name}")
    return v

def env_int(name: str, default: int | None = None) -> int:
    v = os.getenv(name)
    if v is None:
        if default is None:
            raise RuntimeError(f"Missing env: {name}")
        return default
    return int(v)

# ===== API =====
API_BASE = env("API_BASE").rstrip("/")

# ===== MQTT 공통 =====
BROKER_IP = env("MQTT_BROKER_HOST")
BROKER_PORT = env_int("MQTT_BROKER_PORT", 1883)

MQTT_USERNAME = os.getenv("MQTT_USERNAME")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD")

HO_ID = env("HO_ID", "1")
MQTT_CLIENT_ID = env("MQTT_CLIENT_ID", f"rn_pi_{int(time.time())}")

ROOM_IDS_RAW = os.getenv("ROOM_IDS", "1,2,3")
ROOM_IDS = [int(x.strip()) for x in ROOM_IDS_RAW.split(",") if x.strip().isdigit()]

TOPIC_DEVICE_REQ = f"hdc/{HO_ID}/room/+/device/execute/req"
TOPIC_RES_TEMPLATE = f"hdc/{HO_ID}/room/{{roomId}}/device/execute/res"
TOPIC_ENV_TEMPLATE = f"hdc/{HO_ID}/room/{{roomId}}/env/data"

# ===== GPIO =====
LED_PINS = {1: 13, 2: 20, 3: 26}
FAN_PINS = {
    (1, 1): 23, (1, 2): 24,
    (2, 1): 17, (2, 2): 27,
    (3, 1): 22, (3, 2): 5,
}
DHT_PINS = {1: board.D25, 2: board.D12, 3: board.D16}

# 난방/냉방 표시등(빨강/파랑) GPIO(BCM) 핀 매핑
STATUS_LED_PINS = {
    (1, "RED"): 6,
    (1, "BLUE"): 21,

    (2, "RED"): 18,
    (2, "BLUE"): 19,

    (3, "RED"): 14, 
    (3, "BLUE"): 15,
}

class RNMqttWorker:
    def __init__(self):
        self.client = mqtt.Client(client_id=MQTT_CLIENT_ID)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

        # 인증 (옵션)
        if MQTT_USERNAME and MQTT_PASSWORD:
            self.client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

        # 방별 센서/디바이스
        self.dht_map = {rid: adafruit_dht.DHT11(pin) for rid, pin in DHT_PINS.items()}
        self.led_map = {rid: LED(pin) for rid, pin in LED_PINS.items()}
        self.fan_map = {(rid, idx): Fan(pin) for (rid, idx), pin in FAN_PINS.items()}

        # 난방/냉방 표시등(빨강/파랑)
        self.status_led_map = {(rid, color): LED(pin) for (rid, color), pin in STATUS_LED_PINS.items()}

    def parse_device_code(self, device_code: str):
        if device_code.startswith("light-"):
            room_id = int(device_code.split("-")[1])
            return ("LED", room_id, None)

        if device_code.startswith("fan-"):
            parts = device_code.split("-")
            room_id = int(parts[1])
            fan_idx = int(parts[2]) if len(parts) >= 3 else None
            return ("FAN", room_id, fan_idx)

        if device_code.startswith("aircon-"):
            room_id = int(device_code.split("-")[1])
            return ("AIRCON", room_id, None)

        # RN 표시등: red-led-{roomId}, blue-led-{roomId}
        if device_code.startswith("red-led-"):
            return ("STATUS_LED", None, "RED")

        if device_code.startswith("blue-led-"):
            return ("STATUS_LED", None, "BLUE")

        return (None, None, None)

    def on_connect(self, client, userdata, flags, rc):
        print("[RN] connected:", rc)
        client.subscribe(TOPIC_DEVICE_REQ)
        print("[MQTT] subscribed:", TOPIC_DEVICE_REQ)

    def on_message(self, client, userdata, msg):
        topic = msg.topic
        raw = msg.payload.decode(errors="ignore").strip()
        print("[MQTT] recv:", topic, raw)

        try:
            parts = topic.split("/")
            if len(parts) < 7:
                return
            if parts[0] != "hdc":
                return
            if parts[1] != str(HO_ID):
                return
            if parts[2] != "room":
                return
            room_id = int(parts[3])
            if parts[4] != "device" or parts[5] != "execute" or parts[6] != "req":
                return
        except Exception:
            print("[MQTT] roomId/topic parse error")
            return

        try:
            data = json.loads(raw)
        except Exception as e:
            print("[MQTT] json parse error:", e)
            return

        trace_id = data.get("traceId") or "no-trace"
        device_code = data.get("deviceCode")
        command = data.get("command")
        value = data.get("value")

        if not device_code or not command:
            self.publish_result(room_id, trace_id, "FAIL", "missing deviceCode/command")
            return

        def parse_on(v):
            return (v is True) or (str(v).upper() == "ON") or (str(v) == "1") or (str(v).upper() == "TRUE")

        try:
            dtype, rid, extra = self.parse_device_code(device_code)
            if not dtype:
                self.publish_result(room_id, trace_id, "FAIL", f"unknown deviceCode={device_code}")
                return

            # STATUS_LED는 deviceCode 숫자 대신 토픽 room_id 기준으로 동작
            if dtype == "STATUS_LED":
                rid = room_id

            if dtype != "STATUS_LED" and rid != room_id:
                self.publish_result(room_id, trace_id, "FAIL", f"room mismatch topic={room_id} code={rid}")
                return

            if dtype == "LED" and command == "POWER":
                led = self.led_map.get(rid)
                if not led:
                    self.publish_result(room_id, trace_id, "FAIL", f"no LED for room {rid}")
                    return
                on = parse_on(value)
                led.led_on() if on else led.led_off()
                self.publish_result(room_id, trace_id, "SUCCESS", f"{device_code} power={on}")

            elif dtype == "LED" and command == "BRIGHTNESS":
                led = self.led_map.get(rid)
                if not led:
                    self.publish_result(room_id, trace_id, "FAIL", f"no LED for room {rid}")
                    return
                b = max(0, min(100, int(value)))
                if b > 0:
                    led.led_on()
                else:
                    led.led_off()
                led.set_brightness(b)
                self.publish_result(room_id, trace_id, "SUCCESS", f"{device_code} brightness={b}")

            elif dtype == "FAN" and command == "POWER":
                on = parse_on(value)

                fan_idx = extra
                if fan_idx is None:
                    f1 = self.fan_map.get((rid, 1))
                    f2 = self.fan_map.get((rid, 2))
                    if not f1 or not f2:
                        self.publish_result(room_id, trace_id, "FAIL", f"missing fans for room {rid}")
                        return
                    f1.on() if on else f1.off()
                    f2.on() if on else f2.off()
                    self.publish_result(room_id, trace_id, "SUCCESS", f"fan-{rid} power={on} -> FAN1,FAN2 synced")
                    return

                fan = self.fan_map.get((rid, fan_idx))
                if not fan:
                    self.publish_result(room_id, trace_id, "FAIL", f"no FAN{fan_idx} for room {rid}")
                    return
                fan.on() if on else fan.off()
                self.publish_result(room_id, trace_id, "SUCCESS", f"{device_code} power={on}")

            elif dtype == "AIRCON" and command == "POWER":
                on = parse_on(value)
                f1 = self.fan_map.get((rid, 1))
                f2 = self.fan_map.get((rid, 2))
                if not f1 or not f2:
                    self.publish_result(room_id, trace_id, "FAIL", f"missing fans for room {rid}")
                    return
                if on:
                    f1.on(); f2.on()
                else:
                    f1.off(); f2.off()
                self.publish_result(room_id, trace_id, "SUCCESS", f"{device_code} power={on} -> FAN1,FAN2 synced")

            elif dtype == "STATUS_LED" and command == "POWER":
                color = extra  # "RED" or "BLUE"
                led = self.status_led_map.get((rid, color))
                if not led:
                    self.publish_result(room_id, trace_id, "FAIL", f"no STATUS_LED {color} for room {rid}")
                    return
                on = parse_on(value)
                led.led_on() if on else led.led_off()
                self.publish_result(room_id, trace_id, "SUCCESS", f"{device_code} power={on}")

            else:
                self.publish_result(room_id, trace_id, "FAIL", f"unsupported: {device_code}/{command}")

        except Exception as e:
            print("[MQTT] execute error:", e)
            self.publish_result(room_id, trace_id, "FAIL", str(e))

    def apply_snapshot(self):
        for room_id in ROOM_IDS:
            try:
                url = f"{API_BASE}/room/{room_id}/snapshot"
                print("[SNAPSHOT] try:", url)
                res = requests.get(url, timeout=5)
                print("[SNAPSHOT] status:", res.status_code)
                if res.status_code != 200:
                    continue

                data = res.json()
                devices = data.get("device", []) or []

                led = next((d for d in devices if d.get("type") == "LED"), None)
                if led:
                    power = bool(led.get("power"))
                    brightness = led.get("brightness") or 0
                    led_hw = self.led_map.get(room_id)
                    if led_hw:
                        if power:
                            if brightness > 0:
                                led_hw.set_brightness(int(brightness))
                            led_hw.led_on()
                        else:
                            led_hw.led_off()

                fan_devices = [d for d in devices if d.get("type") == "FAN"]
                for fd in fan_devices:
                    code = fd.get("deviceCode") or ""
                    power = bool(fd.get("power"))
                    try:
                        _, rid, idx = self.parse_device_code(code)
                        if rid != room_id:
                            continue
                        fan_hw = self.fan_map.get((rid, idx))
                        if fan_hw:
                            fan_hw.on() if power else fan_hw.off()
                    except Exception:
                        continue

                print(f"[SNAPSHOT] room={room_id} applied OK")

            except Exception as e:
                print("[SNAPSHOT] apply failed:", repr(e))

    def dht_publish_loop(self):
        while True:
            for rid, dht in self.dht_map.items():
                try:
                    temp = dht.temperature
                    humi = dht.humidity
                    if temp is None or humi is None:
                        continue

                    ts = datetime.now().replace(microsecond=0).isoformat()
                    topic = TOPIC_ENV_TEMPLATE.format(roomId=rid)

                    payload_temp = json.dumps({
                        "roomId": rid,
                        "sensorType": "TEMP",
                        "value": float(temp),
                        "unit": "C",
                        "ts": ts
                    })
                    self.client.publish(topic, payload_temp)
                    print("[DHT] publish TEMP:", topic, payload_temp)

                    payload_humi = json.dumps({
                        "roomId": rid,
                        "sensorType": "HUMIDITY",
                        "value": float(humi),
                        "unit": "%",
                        "ts": ts
                    })
                    self.client.publish(topic, payload_humi)
                    print("[DHT] publish HUMI:", topic, payload_humi)

                except RuntimeError as e:
                    print(f"[DHT] room={rid} read error:", e)
                except Exception as e:
                    print(f"[DHT] room={rid} unknown error:", e)

            time.sleep(30)

    def publish_result(self, room_id, trace_id, result, detail):
        payload = json.dumps({
            "traceId": trace_id,
            "result": result,
            "detail": detail,
            "ts": datetime.now().replace(microsecond=0).isoformat()
        })
        topic = TOPIC_RES_TEMPLATE.format(roomId=room_id)
        self.client.publish(topic, payload)
        print("[MQTT] res:", topic, payload)

    def start(self):
        try:
            print("[RN] broker connecting...", BROKER_IP, BROKER_PORT)
            self.client.connect(BROKER_IP, BROKER_PORT, 60)

            self.apply_snapshot()

            threading.Thread(target=self.dht_publish_loop, daemon=True).start()
            self.client.loop_forever()

        finally:
            try:
                for f in self.fan_map.values():
                    f.cleanup()
                for l in self.led_map.values():
                    l.cleanup()
                for l in self.status_led_map.values():
                    l.cleanup()
            except:
                pass

if __name__ == "__main__":
    RNMqttWorker().start()
