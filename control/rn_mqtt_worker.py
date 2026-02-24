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
ROOM_ID = 1

# 모드, 디바이스 토픽
TOPIC_DEVICE_REQ = f"hdc/{HO_ID}/room/+/device/execute/req"

# 실행 결과 토픽 - 일단 형태 정상으로
TOPIC_RES = f"hdc/{HO_ID}/device/execute/res"

# roomId 포함 응답 토픽 추천 (방 분리)
TOPIC_RES_TEMPLATE = f"hdc/{HO_ID}/room/{{roomId}}/device/execute/res"

# 센서 값 전송(라즈베리파이 → 서버) : 유지
TOPIC_ENV_TEMPLATE = f"hdc/{HO_ID}/room/{{roomId}}/env/data"
        
# ===== GPIO =====
# 방별 LED 1개
LED_PINS = {
    1: 13,
    2: 20,
    3: 26,
}

# 방별 FAN 2개 (tuple key)
FAN_PINS = {
    (1, 1): 23,
    (1, 2): 24,
    (2, 1): 17,
    (2, 2): 27,
    (3, 1): 22,
    (3, 2): 5,
}

# 방별 DHT 1개
DHT_PINS = {
    1: board.D25,
    2: board.D12,
    3: board.D16,
}

# (선택) 에어컨 릴레이/IR 등 제어 핀이 있으면 추가
AIRCON_PINS = {
    1: 18,
    2: 19,
    3: 16,
}
class RNMqttWorker: 
    def __init__(self):
        self.client = mqtt.Client(client_id=f"rn_pi_{int(time.time())}")
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

        #  방별 DHT 생성
        self.dht_map = {rid: adafruit_dht.DHT11(pin) for rid, pin in DHT_PINS.items()}

        self.led_map = {rid: LED(pin) for rid, pin in LED_PINS.items()}
        self.fan_map = {(rid, idx): Fan(pin) for (rid, idx), pin in FAN_PINS.items()}

        self.state = {
            "led_on": False,
            "brightness": 100,
            "target_temp": 24,
            "ac_on": False
        }
    def parse_device_code(self, device_code: str):
        # light-1
        if device_code.startswith("light-"):
            room_id = int(device_code.split("-")[1])
            return ("LED", room_id, None)

        # fan-1-2 (room=1, idx=2)  / fan-1 (room=1, idx=None -> group)
        if device_code.startswith("fan-"):
            parts = device_code.split("-")
            room_id = int(parts[1])
            fan_idx = int(parts[2]) if len(parts) >= 3 else None
            return ("FAN", room_id, fan_idx)

        # aircon-1
        if device_code.startswith("aircon-"):
            room_id = int(device_code.split("-")[1])
            return ("AIRCON", room_id, None)

        return (None, None, None)
    
    def on_connect(self, client, userdata, flags, rc):
        print("[RN] connected:", rc)
        client.subscribe(TOPIC_DEVICE_REQ)
        print("[MQTT] subscribed:", TOPIC_DEVICE_REQ)

    def on_message(self, client, userdata, msg):
        topic = msg.topic
        raw = msg.payload.decode(errors="ignore").strip()
        print("[MQTT] recv:", topic, raw)

        # 토픽 형식 검증 + roomId 파싱
        # 기대: hdc/{HO_ID}/room/{roomId}/device/execute/req
        try:
            parts = topic.split("/")
            # ["hdc", "{hoId}", "room", "{roomId}", "device", "execute", "req"]
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

        # JSON 파싱 (빠져있던 부분)
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

        try:
            dtype, rid, fan_idx = self.parse_device_code(device_code)
            if not dtype:
                self.publish_result(room_id, trace_id, "FAIL", f"unknown deviceCode={device_code}")
                return

            # 토픽 room_id 와 deviceCode의 rid가 다르면 방어 (원하면 제거 가능)
            if rid != room_id:
                self.publish_result(room_id, trace_id, "FAIL", f"room mismatch topic={room_id} code={rid}")
                return

            def parse_on(v):
                return (v is True) or (str(v).upper() == "ON") or (str(v) == "1") or (str(v).upper() == "TRUE")

            # LED POWER
            if dtype == "LED" and command == "POWER":
                led = self.led_map.get(rid)
                if not led:
                    self.publish_result(room_id, trace_id, "FAIL", f"no LED for room {rid}")
                    return
                on = parse_on(value)
                led.led_on() if on else led.led_off()
                self.publish_result(room_id, trace_id, "SUCCESS", f"{device_code} power={on}")

            #  LED BRIGHTNESS
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

            #  FAN POWER (fan-<room>-<1|2>)
            elif dtype == "FAN" and command == "POWER":
                on = parse_on(value)

                # fan-<room> 이면 팬 2개 같이
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

                # fan-<room>-<idx> 이면 단일 팬
                fan = self.fan_map.get((rid, fan_idx))
                if not fan:
                    self.publish_result(room_id, trace_id, "FAIL", f"no FAN{fan_idx} for room {rid}")
                    return
                fan.on() if on else fan.off()
                self.publish_result(room_id, trace_id, "SUCCESS", f"{device_code} power={on}")

            #  AIRCON POWER => 팬 2개 같이 ON/OFF
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

            else:
                self.publish_result(room_id, trace_id, "FAIL", f"unsupported: {device_code}/{command}")

        except Exception as e:
            print("[MQTT] execute error:", e)
            self.publish_result(room_id, trace_id, "FAIL", str(e))

    def apply_snapshot(self):
        try:
            # 방별 스냅샷 적용 (1~3 고정)
            for room_id in [1, 2, 3]:
                url = f"{API_BASE}/rooms/{room_id}/snapshot"
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

                # FAN: 방에 팬이 2개면 둘 다 찾아서 적용
                fan_devices = [d for d in devices if d.get("type") == "FAN"]
                for fd in fan_devices:
                    code = fd.get("deviceCode") or ""
                    power = bool(fd.get("power"))

                    # 기대: fan-<room>-<1|2>
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

                    # 센서가 None 줄 때 방어
                    if temp is None or humi is None:
                        continue

                    ts = datetime.now().replace(microsecond=0).isoformat()
                    topic = TOPIC_ENV_TEMPLATE.format(roomId=rid)

                    #  TEMP 1번 publish
                    payload_temp = json.dumps({
                        "roomId": rid,
                        "sensorType": "TEMP",
                        "value": float(temp),
                        "unit": "C",
                        "ts": ts
                    })
                    self.client.publish(topic, payload_temp)
                    print("[DHT] publish TEMP:", topic, payload_temp)

                    #  HUMIDITY 1번 publish
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


if __name__ == "__main__":
    RNMqttWorker().start()
