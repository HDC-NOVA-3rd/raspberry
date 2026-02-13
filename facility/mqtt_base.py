# mqtt_base.py
import json
import time
import paho.mqtt.client as mqtt
from abc import ABC, abstractmethod

class BaseMqttNode(ABC):
    def __init__(self, broker_ip, port, client_id_prefix, username=None, password=None):
        self.client_id = f"{client_id_prefix}_{int(time.time())}"
        self.client = mqtt.Client(client_id=self.client_id)
        self.broker_ip = broker_ip
        self.port = port
        
        # 인증 정보 설정
        if username and password:
            self.client.username_pw_set(username, password)
            print(f"[{self.client_id}] 인증 정보 설정 완료 ({username})")
        
        # 콜백 설정
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

    def connect(self):
        try:
            print(f"[{self.client_id}] 브로커 연결 시도: {self.broker_ip}")
            self.client.connect(self.broker_ip, self.port, 60)
            self.client.loop_start() # 별도 스레드로 루프 실행
        except Exception as e:
            print(f"연결 실패: {e}")

    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            print("MQTT 연결 성공")
            self.subscribe_topics() # 자식 클래스에서 구현할 메서드 호출
        else:
            print(f"MQTT 연결 실패 코드: {rc}")

    def on_message(self, client, userdata, msg):
        try:
            topic = msg.topic
            payload = msg.payload.decode("utf-8")
            self.handle_message(topic, payload) # 자식 클래스에 위임
        except Exception as e:
            print(f"메시지 처리 에러: {e}")

    def send_json(self, topic, data):
        """JSON 데이터 전송 헬퍼"""
        try:
            payload = json.dumps(data, ensure_ascii=False)
            self.client.publish(topic, payload)
            print(f"[SEND] {topic} >> {payload}")
        except Exception as e:
            print(f"전송 실패: {e}")

    @abstractmethod
    def subscribe_topics(self):
        """자식 클래스에서 구독할 토픽 정의"""
        pass

    @abstractmethod
    def handle_message(self, topic, payload):
        """자식 클래스에서 메시지 처리 로직 구현"""
        pass

    def stop(self):
        self.client.loop_stop()
        self.client.disconnect()