# ~/work/control/rn_mqtt_worker.py
import requests
import json
import time
import threading
import paho.mqtt.client as mqtt
import board
import adafruit_dht

from led import LED
from fan import Fan
from datetime import datetime

API_BASE = "http://192.168.14.90:8080/api"
# ===== MQTT 공통 =====
BROKER_IP = "192.168.14.90"
BROKER_PORT = 1883

# 이 라즈베리파이가 설치된 세대(동-호) : 데모는 고정값
HO_ID = "1"

# 제어 명령(서버/RN → 라즈베리파이)
TOPIC_CMD = f"hdc/{HO_ID}/assistant/execute/req"

# 실행 결과(라즈베리파이 → 서버)
TOPIC_RES = f"hdc/{HO_ID}/assistant/execute/res"

# 센서 값 전송(라즈베리파이 → 서버) : 유지
TOPIC_ENV = "hdc/device/dht11-1/env/data"
ROOM_ID = 1

# ===== GPIO =====
FAN_PIN = 23


class RNMqttWorker:
    def __init__(self):
        self.client = mqtt.Client(client_id=f"rn_pi_{int(time.time())}")
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

        # DHT11 센서 (데이터 핀: GPIO25면 D25)
        self.dht = adafruit_dht.DHT11(board.D25)

        self.led = LED(13)
        self.fan = Fan(FAN_PIN)

        self.state = {
            "led_on": False,
            "brightness": 100,
            "target_temp": 24,
            "ac_on": False
        }

    def on_connect(self, client, userdata, flags, rc):
        print("[RN] connected:", rc)
        client.subscribe(TOPIC_CMD)
        print("[MQTT] subscribed:", TOPIC_CMD)

    def on_message(self, client, userdata, msg):
        topic = msg.topic
        raw = msg.payload.decode(errors="ignore").strip()
        print("[MQTT] recv:", topic, raw)

        if topic != TOPIC_CMD:
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
            self.publish_result(trace_id, "FAIL", "missing deviceCode/command")
            return

        try:
            # LED POWER
            if device_code in ["light-1", "led-1"] and command == "POWER":
                on = (value is True) or (str(value).upper() == "ON") or (str(value) == "1")
                if on:
                    self.led.led_on()
                else:
                    self.led.led_off()
                self.publish_result(trace_id, "SUCCESS", f"{device_code} power={on}")

            # LED BRIGHTNESS
            elif device_code in ["light-1", "led-1"] and command == "BRIGHTNESS":
                b = max(0, min(100, int(value)))
                if hasattr(self.led, "set_brightness"):
                    self.led.set_brightness(b)
                self.publish_result(trace_id, "SUCCESS", f"{device_code} brightness={b}")

            # FAN POWER
            elif device_code in ["fan-1", "aircon-1"] and command == "POWER":
                on = (value is True) or (str(value).upper() == "ON") or (str(value) == "1")
                if on:
                    self.fan.on()
                else:
                    self.fan.off()
                self.publish_result(trace_id, "SUCCESS", f"{device_code} power={on}")

            # TARGET TEMP
            elif device_code in ["fan-1", "aircon-1"] and command in ["TARGET_TEMP", "SET_TEMP"]:
                t = int(value)
                self.state["target_temp"] = t
                self.publish_result(trace_id, "SUCCESS", f"{device_code} target_temp={t}")

            else:
                self.publish_result(trace_id, "FAIL", f"unsupported: {device_code}/{command}")

        except Exception as e:
            print("[MQTT] execute error:", e)
            self.publish_result(trace_id, "FAIL", str(e))

    def apply_snapshot(self):
        try:
            url1 = f"{API_BASE}/room/{ROOM_ID}/snapshot"
            url2 = f"{API_BASE}/rooms/{ROOM_ID}/snapshot"

            for url in [url1, url2]:
                print("[SNAPSHOT] try:", url)
                res = requests.get(url, timeout=5)
                print("[SNAPSHOT] status:", res.status_code)
                print("[SNAPSHOT] body:", res.text[:300])

                if res.status_code == 200:
                    data = res.json()
                    devices = data.get("device", []) or []

                    led = next((d for d in devices if d.get("deviceCode") in ["light-1", "led-1"]), None)
                    if led:
                        power = bool(led.get("power"))
                        brightness = led.get("brightness")
                        print("[SNAPSHOT] led:", power, brightness)

                        if power:
                            self.led.led_on()
                            if brightness is not None and hasattr(self.led, "set_brightness"):
                                self.led.set_brightness(int(brightness))
                        else:
                            self.led.led_off()

                    fan = next((d for d in devices if d.get("deviceCode") in ["fan-1", "aircon-1"]), None)
                    if fan:
                        power = bool(fan.get("power"))
                        print("[SNAPSHOT] fan:", power)
                        if power:
                            self.fan.on()
                        else:
                            self.fan.off()

                    print("[SNAPSHOT] applied OK")
                    return

            print("[SNAPSHOT] no valid endpoint (not 200)")

        except Exception as e:
            print("[SNAPSHOT] apply failed:", repr(e))


    def dht_publish_loop(self):
        while True:
            try:
                temp = self.dht.temperature
                humi = self.dht.humidity

                # 센서가 None 줄 때 방어
                if temp is None or humi is None:
                    time.sleep(2)
                    continue

                ts = datetime.now().replace(microsecond=0).isoformat()

                # ✅ TEMP publish
                payload_temp = json.dumps({
                    "roomId": ROOM_ID,
                    "sensorType": "TEMP",
                    "value": int(temp),
                    "unit": "C",
                    "ts": ts
                })
                self.client.publish(TOPIC_ENV, payload_temp)
                print("[DHT] publish TEMP:", payload_temp)

                # ✅ HUMIDITY publish
                payload_humi = json.dumps({
                    "roomId": ROOM_ID,
                    "sensorType": "HUMIDITY",
                    "value": int(humi),
                    "unit": "%",
                    "ts": ts
                })
                self.client.publish(TOPIC_ENV, payload_humi)
                print("[DHT] publish HUMI:", payload_humi)

                time.sleep(30)

            except RuntimeError as e:
                print("[DHT] read error:", e)
                time.sleep(2)
            except Exception as e:
                print("[DHT] unknown error:", e)
                time.sleep(2)


    def start(self):
        try:
            print("[RN] broker connecting...")
            self.client.connect(BROKER_IP, BROKER_PORT, 60)
            # 서버 스냅샷으로 상태 복구 (Pi 재시작해도 LED/FAN 맞추기)
            self.apply_snapshot()


            # loop_forever 전에 쓰레드 시작해야 함
            threading.Thread(target=self.dht_publish_loop, daemon=True).start()

            self.client.loop_forever()

        finally:
            try:
                self.fan.cleanup()
            except:
                pass
    def publish_result(self, trace_id, result, detail):
        payload = json.dumps({
            "traceId": trace_id,
            "result": result,
            "detail": detail,
            "ts": datetime.now().replace(microsecond=0).isoformat()
        })
        self.client.publish(TOPIC_RES, payload)
        print("[MQTT] res:", TOPIC_RES, payload)

if __name__ == "__main__":
    RNMqttWorker().start()
