"""Main voice-assistant pipeline: wake -> record -> MQTT -> TTS loop."""

from __future__ import annotations

import logging
import signal
import time

from .audio import AudioSettings, VADRecorder
from .config import AssistantConfig
from .exceptions import MqttError, VoiceAssistantError
from .models import MqttCommand
from .mqtt_handler import MqttHandler
from .tts import LocalTTS, TTSConfig
from .wakeword import build_wakeword_detector

log = logging.getLogger(__name__)


class VoiceAssistantPipeline:
    """
    Orchestrates the full voice-assistant loop:

    1. Wait for wake-word
    2. Record speech (VAD)
    3. Send WAV audio via MQTT to backend
    4. Receive (STT + intent + reply) via MQTT
    5. TTS playback of the reply
    6. Repeat
    """

    def __init__(self, config: AssistantConfig) -> None:
        self._cfg = config
        self._running = False
        self._session_id = ""

        self._wakeword = build_wakeword_detector(
            mode=config.wakeword_mode,
            porcupine_access_key=config.porcupine_access_key,
            porcupine_keyword=config.porcupine_keyword,
            porcupine_sensitivity=config.porcupine_sensitivity,
            wakeword_input_device=config.wakeword_input_device,
        )

        self._recorder = VADRecorder(
            AudioSettings(
                sample_rate=config.sample_rate,
                frame_duration_ms=config.frame_duration_ms,
                vad_aggressiveness=config.vad_aggressiveness,
                silence_ms=config.silence_ms,
                max_record_seconds=config.max_record_seconds,
                min_speech_ms=config.min_speech_ms,
                input_device=config.stt_input_device,
                start_level_threshold=config.stt_start_level,
                end_level_threshold=config.stt_end_level,
            )
        )

        self._tts = LocalTTS(
            TTSConfig(
                rate=config.tts_rate,
                voice=config.tts_voice,
            )
        )

        self._mqtt = MqttHandler(
            broker_host=config.mqtt_broker_host,
            broker_port=config.mqtt_broker_port,
            client_id=config.mqtt_client_id,
            ho_id=config.ho_id,
            username=config.mqtt_username,
            password=config.mqtt_password,
            on_command=self._handle_device_command,
        )

    def run_forever(self) -> None:
        """Start the pipeline and loop until interrupted."""
        self._running = True
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        try:
            self._mqtt.start()
        except MqttError:
            log.critical("MQTT connection failed. shutting down")
            raise

        log.info(
            "voice assistant started (ho_id=%d, wakeword=%s)",
            self._cfg.ho_id,
            self._cfg.wakeword_mode,
        )

        try:
            while self._running:
                self._single_turn()
        except KeyboardInterrupt:
            pass
        finally:
            self._shutdown()

    def _single_turn(self) -> None:
        """Execute one wake -> record -> send -> tts cycle."""

        try:
            log.info("wake-word waiting")
            self._wakeword.wait()
            if not self._running:
                return
        except VoiceAssistantError:
            raise
        except Exception as exc:
            log.error("wake-word error: %s", exc)
            return

        self._tts.speak(self._cfg.greeting_text)
        # 캐시된 노이즈 플로어가 있으면 짧게 대기 (잔향 제거 최소화)
        # 첫 턴은 1.5s (캘리브레이션 전 잔향 방지), 이후 턴은 0.3s
        post_tts_sleep = 0.3 if self._recorder.has_noise_cache else 1.5
        time.sleep(post_tts_sleep)

        try:
            wav = self._recorder.record_until_silence()
        except Exception as exc:
            log.error("recording error: %s", exc)
            return

        if wav is None:
            self._tts.speak(self._cfg.no_speech_text)
            return

        result = self._mqtt.send_audio(
            wav_bytes=wav,
            session_id=self._session_id,
            timeout=self._cfg.mqtt_voice_timeout,
        )

        if result is None:
            log.warning("MQTT voice response timeout")
            self._tts.speak(self._cfg.backend_error_text)
            return

        tts_text = (result.tts_text or "").strip()
        answer_text = (result.answer or "").strip()
        reply = tts_text if tts_text else answer_text
        if reply:
            ok = self._tts.speak(reply)
            if not ok:
                log.warning("reply TTS playback failed: %s", reply)
        else:
            log.warning("empty reply payload: intent=%s", result.intent)
            self._tts.speak("응답이 비어 있어요. 다시 말씀해 주세요.")

        if result.session_id:
            self._session_id = result.session_id

        log.info(
            "turn complete — intent=%s | recognized: %s",
            result.intent or "(none)",
            (result.recognized_text or "")[:60] or "(empty)",
        )

    @staticmethod
    def _handle_device_command(cmd: MqttCommand) -> tuple[str, str]:
        """
        Handle device-control commands from the server.
        Returns (status, detail) tuple.
        """
        log.info("device command received: %s", cmd.command)
        # TODO: implement actual device control (GPIO, IR, etc.)
        return "SUCCESS", f"executed: {cmd.command}"

    def _signal_handler(self, signum, frame) -> None:
        log.info("signal %d received, shutting down", signum)
        self._running = False
        self._wakeword.stop()

    def _shutdown(self) -> None:
        log.info("shutting down")
        self._mqtt.stop()
        self._wakeword.cleanup()
        log.info("voice assistant stopped")
