"""Local TTS playback via gTTS (Google Text-to-Speech)."""

from __future__ import annotations

import logging
import os
import tempfile
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TTSConfig:
    rate: int = 170
    voice: str = "ko"
    lang: str = "ko"  # gTTS language code


class LocalTTS:
    """
    Speaks text locally using gTTS (Google Text-to-Speech).

    Generates MP3 audio file and plays it using pygame or system player.
    """

    def __init__(self, config: TTSConfig | None = None) -> None:
        self._cfg = config or TTSConfig()
        
        try:
            from gtts import gTTS  # type: ignore[import-untyped]
            self._gtts_available = True
            log.info("TTS engine: gTTS (Google Text-to-Speech)")
        except ImportError:
            self._gtts_available = False
            log.warning("gTTS not available. Install with: pip install gTTS")
        
        # Try to initialize pygame for audio playback
        self._pygame_available = False
        try:
            import pygame  # type: ignore[import-untyped]
            pygame.mixer.init()
            self._pygame_available = True
            log.info("Audio player: pygame")
        except Exception as exc:
            log.warning("pygame not available, will try mpg123 (%s)", exc)

    def speak(self, text: str) -> bool:
        """
        Speak *text* synchronously using gTTS.

        Returns ``True`` on success, ``False`` on failure.
        """
        msg = (text or "").strip()
        if not msg:
            return True

        if not self._gtts_available:
            log.info("[TTS fallback] %s", msg)
            return False

        try:
            from gtts import gTTS
            
            # Create TTS audio
            tts = gTTS(text=msg, lang=self._cfg.lang, slow=False)
            
            # Save to temporary file
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as fp:
                temp_file = fp.name
                tts.save(temp_file)
            
            # Play the audio file
            log.info("TTS speak: %s", msg)
            success = self._play_audio(temp_file)
            
            # Clean up temporary file
            try:
                os.unlink(temp_file)
            except Exception:
                pass
            
            return success
            
        except Exception as exc:
            log.warning("gTTS failed: %s", exc)
            log.info("[TTS fallback] %s", msg)
            return False

    def _play_audio(self, audio_file: str) -> bool:
        """
        Play audio file using pygame or mpg123 fallback.
        """
        # Try pygame first
        if self._pygame_available:
            try:
                import pygame
                pygame.mixer.music.load(audio_file)
                pygame.mixer.music.play()
                while pygame.mixer.music.get_busy():
                    pygame.time.Clock().tick(10)
                return True
            except Exception as exc:
                log.warning("pygame playback failed: %s", exc)
        
        # Try mpg123 as fallback
        try:
            import subprocess
            subprocess.run(
                ["mpg123", "-q", audio_file],
                check=True,
                capture_output=True,
            )
            return True
        except Exception as exc:
            log.warning("mpg123 playback failed: %s", exc)
        
        return False
