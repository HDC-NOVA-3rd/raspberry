"""Centralised configuration loaded from environment / .env file."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _env(name: str, default: str) -> str:
    return os.getenv(name, default)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return default if raw is None or raw.strip() == "" else int(raw)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return default if raw is None or raw.strip() == "" else float(raw)


def _env_optional_int(name: str) -> int | None:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return None
    return int(raw)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes")


# ---------------------------------------------------------------------------
# Config dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AssistantConfig:
    """Immutable snapshot of all runtime settings."""

    # ── MQTT (mandatory) ────────────────────────────────────────────────
    ho_id: int
    mqtt_broker_host: str
    mqtt_broker_port: int
    mqtt_username: str
    mqtt_password: str
    mqtt_client_id: str
    mqtt_voice_timeout: float          # seconds to wait for voice response

    # ── Wake-word ───────────────────────────────────────────────────────
    wakeword_mode: str                 # "manual" | "porcupine"
    porcupine_access_key: str
    porcupine_keyword: str
    porcupine_sensitivity: float       # 0.0-1.0
    wakeword_input_device: int | None  # sounddevice input device index

    # ── Audio / VAD ─────────────────────────────────────────────────────
    sample_rate: int
    vad_aggressiveness: int            # 0-3
    frame_duration_ms: int             # 10 | 20 | 30
    silence_ms: int                    # trailing silence to end recording
    max_record_seconds: float
    min_speech_ms: int
    stt_input_device: int | None       # sounddevice index for STT recording (None = default)
    stt_start_level: int               # energy level to trigger speech start
    stt_end_level: int                 # energy level for silence detection
    # ── TTS ─────────────────────────────────────────────────────────────
    tts_rate: int
    tts_voice: str

    # ── UX fallback texts ───────────────────────────────────────────────
    greeting_text: str
    no_speech_text: str
    backend_error_text: str

    # ── Derived helpers (not env-based) ─────────────────────────────────
    @property
    def mqtt_topic_execute_req(self) -> str:
        return f"hdc/{self.ho_id}/assistant/execute/req"

    @property
    def mqtt_topic_execute_res(self) -> str:
        return f"hdc/{self.ho_id}/assistant/execute/res"

    # ── Factory ─────────────────────────────────────────────────────────
    @classmethod
    def from_env(cls) -> AssistantConfig:
        return cls(
            # MQTT (mandatory)
            ho_id=_env_int("HO_ID", 1),
            mqtt_broker_host=_env("MQTT_BROKER_HOST", "127.0.0.1"),
            mqtt_broker_port=_env_int("MQTT_BROKER_PORT", 1883),
            mqtt_username=_env("MQTT_USERNAME", ""),
            mqtt_password=_env("MQTT_PASSWORD", ""),
            mqtt_client_id=_env("MQTT_CLIENT_ID", "pi-voice-01"),
            mqtt_voice_timeout=_env_float("MQTT_VOICE_TIMEOUT", 15.0),
            # Wake-word
            wakeword_mode=_env("WAKEWORD_MODE", "manual").lower(),
            porcupine_access_key=_env("PORCUPINE_ACCESS_KEY", ""),
            porcupine_keyword=_env("PORCUPINE_KEYWORD", "porcupine"),
            porcupine_sensitivity=_env_float("PORCUPINE_SENSITIVITY", 0.65),
            wakeword_input_device=_env_optional_int("WAKEWORD_INPUT_DEVICE"),
            # Audio / VAD
            sample_rate=_env_int("SAMPLE_RATE", 16000),
            vad_aggressiveness=_env_int("VAD_AGGRESSIVENESS", 2),
            frame_duration_ms=_env_int("FRAME_DURATION_MS", 30),
            silence_ms=_env_int("SILENCE_MS", 700),
            max_record_seconds=_env_float("MAX_RECORD_SECONDS", 12.0),
            min_speech_ms=_env_int("MIN_SPEECH_MS", 300),
            stt_input_device=_env_optional_int("STT_INPUT_DEVICE"),
            stt_start_level=_env_int("STT_START_LEVEL", 800),
            stt_end_level=_env_int("STT_END_LEVEL", 400),
            # TTS
            tts_rate=_env_int("TTS_RATE", 170),
            tts_voice=_env("TTS_VOICE", "ko"),
            # Fallback texts
            greeting_text=_env(
                "GREETING_TEXT",
                "네, 말씀하세요.",
            ),
            no_speech_text=_env(
                "NO_SPEECH_TEXT",
                "말씀을 듣지 못했어요. 다시 말씀해 주세요.",
            ),
            backend_error_text=_env(
                "BACKEND_ERROR_TEXT",
                "서버 연결이 불안정합니다. 잠시 후 다시 시도해 주세요.",
            ),
        )
