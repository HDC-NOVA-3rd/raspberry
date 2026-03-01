# mymqtt.py
import json
import paho.mqtt.client as mqtt

from config import (
    BROKER_HOST, BROKER_PORT,
    SPRING_CMD_SUBSCRIBE, SPRING_RES_TOPIC_FMT,
    LED_PIN
)
from led import LED


class MqttWorker:
    def __init__(self):
        self.client = mqtt.Client()
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

        self.led = LED(LED_PIN)

    def on_connect(self, client, userdata, flags, rc):
        print("connect rc =", rc)
        if rc == 0:
            client.subscribe(SPRING_CMD_SUBSCRIBE)
            print("subscribed:", SPRING_CMD_SUBSCRIBE)
        else:
            print("연결 실패 rc=", rc)

    def _publish_result(self, ho_id: str, trace_id: str, status: str, message: str = ""):
        """
        Spring으로 실행 결과 보내기 (권장)
        payload 예:
        {"traceId":"...","status":"SUCCESS","message":"LED ON"}
        """
        topic = SPRING_RES_TOPIC_FMT.format(hoId=ho_id)
        payload = {
            "traceId": trace_id,
            "status": status,   # SUCCESS / FAIL
            "message": message
        }
        self.client.publish(topic, json.dumps(payload))
        print("RES publish:", topic, payload)

    def _handle_spring_command(self, topic: str, payload_str: str):
        """
        topic: hdc/{hoId}/assistant/execute/req
        payload: {"traceId":"...","command":"LIGHT_ON"} 등
        """
        parts = topic.split("/")
        ho_id = parts[1] if len(parts) >= 2 else "unknown"

        try:
            data = json.loads(payload_str)
        except Exception as e:
            print("JSON parse error:", e, "raw=", payload_str)
            self._publish_result(ho_id, "", "FAIL", "Invalid JSON")
            return

        command = (data.get("command") or "").strip()
        trace_id = (data.get("traceId") or "").strip()

        print("[SPRING CMD]", "hoId=", ho_id, "traceId=", trace_id, "command=", command)

        try:
            if command == "LIGHT_ON":
                self.led.on()
                self._publish_result(ho_id, trace_id, "SUCCESS", "LED ON")
            elif command == "LIGHT_OFF":
                self.led.off()
                self._publish_result(ho_id, trace_id, "SUCCESS", "LED OFF")
            else:
                self._publish_result(ho_id, trace_id, "FAIL", f"Unknown command: {command}")
        except Exception as e:
            print("execute error:", e)
            self._publish_result(ho_id, trace_id, "FAIL", f"Execute error: {e}")

    def on_message(self, client, userdata, message):
        topic = message.topic
        payload_str = message.payload.decode("utf-8", errors="ignore").strip()

        print("MQTT 수신:", topic, payload_str)

        # Spring 챗봇 명령 처리
        if topic.startswith("hdc/") and topic.endswith("/assistant/execute/req"):
            self._handle_spring_command(topic, payload_str)

    def run(self):
        try:
            print("브로커 연결 시작:", BROKER_HOST, BROKER_PORT)
            self.client.connect(BROKER_HOST, BROKER_PORT, 60)
            self.client.loop_forever()
        except KeyboardInterrupt:
            pass
        finally:
            try:
                self.client.disconnect()
            except:
                pass
            try:
                self.led.cleanup()
            except:
                pass
            print("종료")
