# entrance_worker.py
import time
import json
import threading
import os  # 환경변수 접근용
import sys  # 경로 조정용
from dotenv import load_dotenv  # .env 로드용

# 상위 폴더(루트)를 경로에 추가하여 control 패키지를 찾을 수 있게 함
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

from mqtt_base import BaseMqttNode
from qr_cam import QRCam
from door_lock import DoorLock
from control.led import LED

# 1. .env 파일 로드
load_dotenv()

# 2. 환경변수에서 값 가져오기 (없으면 기본값 사용)
BROKER_IP = os.getenv("BROKER_IP", "localhost")
BROKER_PORT = int(os.getenv("BROKER_PORT", 1883))
MQTT_USER = os.getenv("MQTT_USER", "")
MQTT_PASS = os.getenv("MQTT_PASS", "")

SPACE_ID = os.getenv("SPACE_ID", "1")
SERVO_PIN = int(os.getenv("SERVO_PIN", 18))

RED_PIN = int(os.getenv("RED_PIN", 24))
YELLOW_PIN = int(os.getenv("YELLOW_PIN", 23))
GREEN_PIN = int(os.getenv("GREEN_PIN", 17))

# 토픽 정의
TOPIC_SCAN_START = f"hdc/entrance/scan/{SPACE_ID}"   # 앱 -> Pi: 스캔해라
TOPIC_VERIFY_QR = f"hdc/entrance/verify" # Pi -> Server: 이 QR 확인좀
TOPIC_CMD_DOOR   = f"hdc/entrance/command/{SPACE_ID}"    # Server -> Pi: 문 열어라

class EntranceWorker(BaseMqttNode):
    def __init__(self):
        super().__init__(
            BROKER_IP, 
            BROKER_PORT, 
            f"entrance_{SPACE_ID}", 
            username=MQTT_USER, 
            password=MQTT_PASS
        )
        
        self.cam = QRCam()
        self.door_lock = DoorLock(pin=SERVO_PIN) 
        self.is_scanning = False
        
        # LED 객체 생성
        self.red_led = LED(RED_PIN)
        self.yellow_led = LED(YELLOW_PIN)
        self.green_led = LED(GREEN_PIN)
        # 초기 대기 상태 설정 (노란색 on)
        self.set_idle_state()
        
    def set_idle_state(self):
        """대기 상태: 노란색 점등, 나머지 소등"""
        self.red_led.led_off()
        self.green_led.led_off()
        self.yellow_led.led_on()
    
    def show_error_state(self):
        """에러/실패 상태: 빨간색 3초 점등 후 대기 상태 복귀"""
        self.yellow_led.led_off()
        self.green_led.led_off()
        self.red_led.led_on()
        time.sleep(3)
        self.set_idle_state()

    def subscribe_topics(self):
        self.client.subscribe(TOPIC_SCAN_START)
        self.client.subscribe(TOPIC_CMD_DOOR)
        print(f"[SUB] {TOPIC_SCAN_START}, {TOPIC_CMD_DOOR}")

    def handle_message(self, topic, payload):
        print(f"[RECV] {topic} : {payload}")
        
        # 1. 앱이나 버튼에서 스캔 요청이 왔을 때
        if topic == TOPIC_SCAN_START:
            if not self.is_scanning:
                # 스캔은 시간이 걸리므로 별도 스레드에서 실행 (MQTT 루프 차단 방지)
                threading.Thread(target=self.run_scan_process).start()
            else:
                print("이미 스캔 중입니다.")

        # 2. 서버에서 인증 성공 후 '문 열어' 명령이 왔을 때
        # topic: hdc/entrance/command , msg: {spaceId: }
        elif topic == TOPIC_CMD_DOOR:
            try:
                data = json.loads(payload)
                command = data.get("command") # 변수명 통일 (dataSpace -> command)
                
                if command == "OPEN_DOOR":
                    # 문 여는 동작 수행 (별도 스레드로 하면 MQTT 수신이 안 막힘)
                    threading.Thread(target=self.open_door).start()
                elif command == "FAIL_DOOR":
                    # 인증 실패: 서버에서 실패 커맨드를 보냈을 때 (예: FAIL_DOOR)
                    print("=== [AUTH FAIL] 서버 인증 실패 ===")
                    threading.Thread(target=self.show_error_state).start()
            except Exception as e:
                print(f"[ERROR] JSON 파싱 실패: {e}")
    
    def _blink_yellow(self):
        """스캔 중 노란색 LED 깜빡임 로직"""
        while self.is_scanning:
            self.yellow_led.led_on()
            time.sleep(0.3)
            if not self.is_scanning: break # 스캔이 끝나면 바로 빠져나옴
            self.yellow_led.led_off()
            time.sleep(0.3)

    def run_scan_process(self):
        """카메라를 켜고 QR을 스캔하는 로직"""
        self.is_scanning = True
        
        # 스캔 중 깜빡임 스레드 실행
        threading.Thread(target=self._blink_yellow).start()
        try:
            # 10초간 스캔 시도
            qr_code = self.cam.scan_once(timeout=10)
        finally:
            self.is_scanning = False # 스캔 종료 시 깜빡임 중단 신호

        if qr_code:
            # QR을 찾았으면 서버로 검증 요청
            req_data = {
                "spaceId": SPACE_ID,
                "qrToken": qr_code,
                "timestamp": time.time()
            }
            self.send_json(TOPIC_VERIFY_QR, req_data)
        else:
            print("QR 인식 실패 또는 시간 초과")
            self.show_error_state() # 실패 시 빨간불 점등

    def open_door(self):
        print("=== [DOOR OPEN] 문이 열립니다! ===")
        # 성공 시 노란불 끄고 초록불 점등
        self.yellow_led.led_off()
        self.green_led.led_on()
        
        # 1. 문 열기 (90도)
        self.door_lock.unlock()
        
        # 2. 3초 대기 (사람이 들어갈 시간)
        time.sleep(3)
        
        # 3. 문 닫기 (0도)
        self.door_lock.lock()
        print("=== [DOOR CLOSE] 문이 닫혔습니다. ===")
        
        # 문이 닫히면 초록불 끄고 대기 상태(노란불)로 복귀
        self.set_idle_state()

    def stop(self):
        """종료 시 호출"""
        super().stop()
        if self.door_lock:
            self.door_lock.cleanup()
        # LED 핀 정리
        self.red_led.cleanup()
        self.yellow_led.cleanup()
        self.green_led.cleanup()
            
    def run_forever(self):
        try:
            self.connect()
            while True:
                # 여기에 물리 버튼 입력 감지 로직을 추가할 수도 있음
                # if GPIO.input(BUTTON_PIN) == GPIO.HIGH:
                #     self.handle_message(TOPIC_SCAN_START, "{}")
                time.sleep(0.1)
        except KeyboardInterrupt:
            self.stop()
            self.cam.stop()

if __name__ == "__main__":
    worker = EntranceWorker()
    worker.run_forever()