# HDC Voice Assistant

Raspberry Pi 음성 비서 런타임.  
로컬 WakeWord + VAD 녹음 → **MQTT로 오디오 전송** → 백엔드(STT/의도/응답) → 로컬 TTS 재생.  
MQTT를 통한 디바이스 제어 명령 수신/실행도 지원합니다.

---

## 아키텍처

```
┌──────────────────────────────────────────────────────────────────┐
│  Raspberry Pi (voice_assistant)                                  │
│                                                                  │
│  ┌──────────┐   ┌───────────┐   ┌────────────────┐   ┌───────┐ │
│  │ WakeWord │──▶│ VAD Record│──▶│  MQTT Handler  │──▶│  TTS  │ │
│  │ Detector │   │  (audio)  │   │  (voice turn)  │   │(local)│ │
│  └──────────┘   └───────────┘   └────────────────┘   └───────┘ │
│                                                                  │
│  MQTT Topics:                                                    │
│  PUB: hdc/{hoId}/assistant/voice/req     (base64 WAV 전송)      │
│  SUB: hdc/{hoId}/assistant/voice/res     (STT+의도+응답 수신)    │
│  SUB: hdc/{hoId}/assistant/execute/req   (디바이스 제어 수신)    │
│  PUB: hdc/{hoId}/assistant/execute/res   (디바이스 결과 발행)    │
└──────────────────────────────────────────────────────────────────┘
                       │
                       ▼
              ┌──────────────────┐
              │   MQTT Broker    │
              │   (Mosquitto)    │
              └────────┬─────────┘
                       │
                       ▼
              ┌──────────────────┐
              │  Spring Backend  │
              │  (STT + LLM)    │
              └──────────────────┘
```

## 모듈 구조

```
voice_assistant/
├── __init__.py          # 패키지 메타
├── __main__.py          # python -m voice_assistant 진입점
├── config.py            # .env 기반 설정 로드
├── models.py            # 데이터 클래스 (VoiceTurnResult, MqttCommand 등)
├── exceptions.py        # 커스텀 예외 계층
├── audio.py             # VAD 기반 마이크 녹음 → WAV 변환
├── wakeword.py          # WakeWord 감지 (manual / porcupine)
├── tts.py               # 로컬 TTS (espeak-ng / pyttsx3)
├── mqtt_handler.py      # MQTT 클라이언트 (음성 턴 + 디바이스 제어)
├── pipeline.py          # 메인 오케스트레이터 (전체 턴 루프)
├── requirements.txt     # Python 의존성
└── .env.example         # 환경변수 템플릿
```

## 턴 처리 흐름

1. **WakeWord 감지** — Enter 키(manual) 또는 Porcupine 핫워드
2. **인사 프롬프트** — "네, 말씀하세요."
3. **VAD 녹음** — WebRTC VAD로 발화 시작/종료 판정 → 16kHz mono WAV
4. **MQTT 전송** — `hdc/{hoId}/assistant/voice/req` (base64 WAV + sessionId)
5. **백엔드 처리** — STT(Whisper) → 의도 분석 → LLM 응답 생성
6. **응답 수신** — `hdc/{hoId}/assistant/voice/res` (JSON)
7. **TTS 재생** — 응답 텍스트를 espeak-ng/pyttsx3로 로컬 재생
8. **반복**

## 설치

```bash
cd voice_assistant
python3 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# .env 설정
cp .env.example .env
# 편집: MQTT_BROKER_HOST, HO_ID 등
```

### 선택 의존성

```bash
# Porcupine 핫워드 엔진 (WAKEWORD_MODE=porcupine)
pip install pvporcupine
```

## 실행

```bash
python -m voice_assistant
```

### 환경변수 주요 항목

| 변수                 | 기본값        | 설명                          |
| -------------------- | ------------- | ----------------------------- |
| `HO_ID`              | `1`           | 세대 ID (backend 식별자)      |
| `MQTT_BROKER_HOST`   | `127.0.0.1`   | MQTT 브로커 주소              |
| `MQTT_BROKER_PORT`   | `1883`        | MQTT 브로커 포트              |
| `MQTT_CLIENT_ID`     | `pi-voice-01` | MQTT 클라이언트 ID            |
| `MQTT_VOICE_TIMEOUT` | `15`          | 음성 응답 대기 시간 (초)      |
| `WAKEWORD_MODE`      | `manual`      | `manual` / `porcupine`        |
| `PORCUPINE_KEYWORD`  | `porcupine`   | Porcupine 기본 키워드         |
| `PORCUPINE_SENSITIVITY` | `0.65`     | 웨이크워드 감도 (`0.0~1.0`)   |
| `WAKEWORD_INPUT_DEVICE` | (비움)     | 마이크 입력 장치 인덱스 고정  |
| `SAMPLE_RATE`        | `16000`       | 오디오 샘플레이트 (Hz)        |
| `SILENCE_MS`         | `700`         | 발화 종료 판정 무음 구간 (ms) |
| `MAX_RECORD_SECONDS` | `12`          | 최대 녹음 길이 (초)           |

## MQTT 프로토콜

### 음성 요청 (Pi → Server)

**Topic:** `hdc/{hoId}/assistant/voice/req`

```json
{
  "audio": "<base64-encoded WAV>",
  "sessionId": "abc123"
}
```

### 음성 응답 (Server → Pi)

**Topic:** `hdc/{hoId}/assistant/voice/res`

```json
{
  "sessionId": "abc123",
  "requestId": "uuid",
  "recognizedText": "거실 불 켜줘",
  "answer": "거실 불을 켰습니다.",
  "ttsText": "거실 불을 켰습니다.",
  "intent": "DEVICE_CONTROL",
  "actions": [{ "type": "MQTT", "target": "living-room-light", "command": "ON" }],
  "endSession": false
}
```

### 디바이스 제어 (Server → Pi)

**Topic:** `hdc/{hoId}/assistant/execute/req`

```json
{
  "traceId": "uuid",
  "command": "ON living-room-light"
}
```

### 디바이스 결과 (Pi → Server)

**Topic:** `hdc/{hoId}/assistant/execute/res`

```json
{
  "traceId": "uuid",
  "status": "SUCCESS",
  "detail": "executed: ON living-room-light",
  "ts": "2026-02-12T10:00:00Z"
}
```

## 개발 모드

초기 연동 테스트에는 `WAKEWORD_MODE=manual` 권장:

- Enter 키로 wakeword를 시뮬레이션
- 마이크 입력 → 녹음 → MQTT 전송 → 응답 수신 → TTS 재생 확인
