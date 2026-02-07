# config.py
BROKER_HOST = "192.168.14.83"
BROKER_PORT = 1883

# Spring 챗봇 명령 토픽(수신): hdc/{hoId}/assistant/execute/req
SPRING_CMD_SUBSCRIBE = "hdc/+/assistant/execute/req"

# (선택) 결과/ACK 송신 토픽: hdc/{hoId}/assistant/execute/res
# ※ Spring에서 수신 핸들러가 parse하는 토픽이 /res 라면 여기에 맞추는 게 좋음
SPRING_RES_TOPIC_FMT = "hdc/{hoId}/assistant/execute/res"

# LED GPIO 핀 (BCM)
LED_PIN = 13
