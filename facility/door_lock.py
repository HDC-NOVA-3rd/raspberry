import RPi.GPIO as GPIO
import time

class DoorLock:
    def __init__(self, pin=18):
        """
        pin: 서보모터 신호선(Orange/Yellow)이 연결된 BCM GPIO 번호 (기본값 18)
        """
        self.pin = pin
        
        # GPIO 설정
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.pin, GPIO.OUT)
        
        # PWM 설정 (50Hz)
        self.pwm = GPIO.PWM(self.pin, 50)
        self.pwm.start(0) # 초기 듀티비 0 (정지)

    def _set_angle(self, angle):
        """
        각도를 받아 듀티비로 변환하여 모터를 움직임
        0도 ~ 180도
        """
        # 듀티비 계산 공식 (서보모터마다 약간 다를 수 있음, 보통 2.5 ~ 12.5 사이)
        duty = 2.5 + (12.0 * angle / 180)
        
        self.pwm.ChangeDutyCycle(duty)
        time.sleep(0.5) # 모터가 움직일 시간을 줌
        
        # 떨림 방지를 위해 신호를 0으로 설정 (모터 힘 풀림 방지)
        self.pwm.ChangeDutyCycle(0)

    def unlock(self):
        """문 열기 (예: 90도)"""
        print(f"[DoorLock] Unlocking... (Pin {self.pin})")
        self._set_angle(90) 

    def lock(self):
        """문 닫기 (예: 0도)"""
        print(f"[DoorLock] Locking... (Pin {self.pin})")
        self._set_angle(0)

    def cleanup(self):
        """종료 시 리소스 해제"""
        self.pwm.stop()
        GPIO.cleanup()