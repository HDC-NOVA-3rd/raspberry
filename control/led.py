# ~/work/control/led.py
import RPi.GPIO as GPIO

_GPIO_READY = False

def _ensure_gpio():
    global _GPIO_READY
    if not _GPIO_READY:
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        _GPIO_READY = True


class LED:
    def __init__(self, led_pin: int, pwm_hz: int = 1000, default_brightness: int = 100):
        _ensure_gpio()
        self.led_pin = led_pin
        self.pwm_hz = pwm_hz

        GPIO.setup(self.led_pin, GPIO.OUT)

        self.pwm = GPIO.PWM(self.led_pin, self.pwm_hz)

        # 상태값
        self.is_on = False
        self.brightness = max(0, min(100, int(default_brightness)))

        # 시작은 무조건 OFF (0%)로 시작
        self.pwm.start(0)

    def led_on(self):
        self.is_on = True
        # brightness가 0이면 "켜졌는데 안보임" 상태라서 기본값으로 올려줌
        if self.brightness <= 0:
            self.brightness = 100
        self.pwm.ChangeDutyCycle(self.brightness)

    def led_off(self):
        self.is_on = False
        self.pwm.ChangeDutyCycle(0)

    def set_brightness(self, value_0_100: int):
        v = max(0, min(100, int(value_0_100)))
        self.brightness = v
        if self.is_on:
            self.pwm.ChangeDutyCycle(v)

    def cleanup(self):
        # 이 핀만 정리
        try:
            self.pwm.ChangeDutyCycle(0)
        except:
            pass
        try:
            self.pwm.stop()
        except:
            pass
        GPIO.cleanup(self.led_pin)
