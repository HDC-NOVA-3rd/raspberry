# ~/work/control/fan.py
import RPi.GPIO as GPIO

# 한 프로세스에서 공통 GPIO 초기화는 1번만
_GPIO_READY = False

def _ensure_gpio():
    global _GPIO_READY
    if not _GPIO_READY:
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        _GPIO_READY = True


class Fan:
    """
    기본: GPIO.HIGH = ON, GPIO.LOW = OFF
    만약 릴레이 보드가 'LOW가 ON'인 타입이면 active_high=False로 생성
    예) Fan(23, active_high=False)
    """
    def __init__(self, pin: int, active_high: bool = True):
        _ensure_gpio()
        self.pin = pin
        self.active_high = active_high

        GPIO.setup(self.pin, GPIO.OUT)

        # 아무 출력도 건드리지 않는다
        # → 마지막 GPIO 상태 그대로 유지
    def on(self):
        GPIO.output(self.pin, GPIO.HIGH if self.active_high else GPIO.LOW)

    def off(self):
        GPIO.output(self.pin, GPIO.LOW if self.active_high else GPIO.HIGH)

    def cleanup(self):
        # 이 핀만 정리 (다른 디바이스 영향 최소화)
        try:
            GPIO.output(self.pin, GPIO.LOW if self.active_high else GPIO.HIGH)
        except:
            pass
        GPIO.cleanup(self.pin)
