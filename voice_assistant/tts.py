"""Local TTS playback via espeak-ng or pyttsx3 fallback."""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TTSConfig:
    rate: int = 170
    voice: str = "ko"


class LocalTTS:
    """
    Speaks text locally.

    Priority order:
    1. espeak-ng  (subprocess, preferred on Pi)
    2. pyttsx3    (cross-platform fallback)
    3. log only   (no audio, last resort)
    """

    def __init__(self, config: TTSConfig | None = None) -> None:
        self._cfg = config or TTSConfig()
        self._espeak = shutil.which("espeak-ng") or shutil.which("espeak")
        self._pyttsx3 = None

        if self._espeak:
            log.info("TTS engine: espeak (%s)", self._espeak)
            return

        try:
            import pyttsx3  # type: ignore[import-untyped]
            self._pyttsx3 = pyttsx3
            probe = self._create_pyttsx3_engine()
            probe.stop()
            log.info("TTS engine: pyttsx3")
        except Exception as exc:
            log.warning("TTS unavailable. text-only fallback enabled (%s)", exc)

    def _select_pyttsx3_voice(self, engine, preferred_voice: str) -> None:
        token = (preferred_voice or "").strip().lower()
        if not token:
            return

        try:
            voices = engine.getProperty("voices")
            for voice in voices:
                voice_id = str(getattr(voice, "id", "")).lower()
                voice_name = str(getattr(voice, "name", "")).lower()
                languages = " ".join(str(x).lower() for x in getattr(voice, "languages", []))
                if token in voice_id or token in voice_name or token in languages:
                    engine.setProperty("voice", voice.id)
                    log.info("pyttsx3 voice selected: %s", voice.id)
                    return
        except Exception as exc:
            log.warning("pyttsx3 voice selection failed: %s", exc)

    def _create_pyttsx3_engine(self):
        if self._pyttsx3 is None:
            return None
        engine = self._pyttsx3.init()
        engine.setProperty("rate", self._cfg.rate)
        self._select_pyttsx3_voice(engine, self._cfg.voice)
        return engine

    def speak(self, text: str) -> bool:
        """
        Speak *text* synchronously.

        Returns ``True`` on success, ``False`` on failure.
        """
        msg = (text or "").strip()
        if not msg:
            return True

        if self._espeak:
            try:
                subprocess.run(
                    [
                        self._espeak,
                        "-s",
                        str(self._cfg.rate),
                        "-v",
                        self._cfg.voice,
                        msg,
                    ],
                    check=True,
                    capture_output=True,
                )
                return True
            except Exception as exc:
                log.warning("espeak execution failed: %s", exc)

        if self._pyttsx3 is not None:
            try:
                log.info("TTS speak: %s", msg)
                engine = self._create_pyttsx3_engine()
                if engine is None:
                    raise RuntimeError("pyttsx3 engine init failed")
                engine.say(msg)
                engine.runAndWait()
                engine.stop()
                return True
            except Exception as exc:
                log.warning("pyttsx3 failed: %s", exc)

        log.info("[TTS fallback] %s", msg)
        return False
