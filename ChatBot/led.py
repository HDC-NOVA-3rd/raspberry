# led.py
import RPi.GPIO as GPIO

class LED:
    def __init__(self, led_pin: int):
        self.led_pin = led_pin
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.led_pin, GPIO.OUT)
        GPIO.output(self.led_pin, GPIO.LOW)  # 초기 OFF

    def on(self):
        GPIO.output(self.led_pin, GPIO.HIGH)

    def off(self):
        GPIO.output(self.led_pin, GPIO.LOW)

    def cleanup(self):
        GPIO.cleanup(self.led_pin)
