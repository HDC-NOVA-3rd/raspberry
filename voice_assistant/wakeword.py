"""Wake-word detection: manual (Enter key) or Porcupine hot-word engine."""

from __future__ import annotations

import abc
import logging
import queue
from array import array

import sounddevice as sd

from .exceptions import WakeWordError

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class WakeWordDetector(abc.ABC):
    """Blocks until the wake-word is detected, then returns."""

    @abc.abstractmethod
    def wait(self) -> None: ...

    def cleanup(self) -> None:
        """Release resources.  Override if needed."""


# ---------------------------------------------------------------------------
# Manual: press Enter
# ---------------------------------------------------------------------------

class ManualWakeWordDetector(WakeWordDetector):
    """Dev/test mode — user presses Enter to simulate wake-word."""

    def wait(self) -> None:
        input("\n[MANUAL] Enter 키를 눌러 wakeword 시뮬레이션 ▶  ")


# ---------------------------------------------------------------------------
# Porcupine
# ---------------------------------------------------------------------------

class PorcupineWakeWordDetector(WakeWordDetector):
    """Production mode — Picovoice Porcupine on-device hot-word."""

    def __init__(self, access_key: str, keyword: str) -> None:
        try:
            import pvporcupine  # type: ignore[import-untyped]
        except ImportError as exc:
            raise WakeWordError(
                "pvporcupine 패키지가 필요합니다. `pip install pvporcupine`"
            ) from exc

        if not access_key.strip():
            raise WakeWordError("PORCUPINE_ACCESS_KEY 필수")

        self._porcupine = pvporcupine.create(
            access_key=access_key.strip(),
            keywords=[keyword.strip() or "porcupine"],
        )
        log.info("porcupine initialised (keyword=%s)", keyword)

    def wait(self) -> None:
        fl = self._porcupine.frame_length
        q: queue.Queue[bytes] = queue.Queue()

        def _cb(indata, _frames, _time, status):
            if status:
                log.warning("wakeword mic status: %s", status)
            q.put(bytes(indata))

        with sd.RawInputStream(
            samplerate=self._porcupine.sample_rate,
            blocksize=fl,
            channels=1,
            dtype="int16",
            callback=_cb,
        ):
            while True:
                raw = q.get()
                if len(raw) != fl * 2:
                    continue
                if self._porcupine.process(array("h", raw)) >= 0:
                    log.info("wake-word detected!")
                    return

    def cleanup(self) -> None:
        if self._porcupine is not None:
            self._porcupine.delete()
            self._porcupine = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def build_wakeword_detector(
    mode: str,
    porcupine_access_key: str = "",
    porcupine_keyword: str = "porcupine",
) -> WakeWordDetector:
    """Return the appropriate detector for *mode* ('manual' | 'porcupine')."""
    mode = (mode or "manual").strip().lower()
    if mode == "manual":
        return ManualWakeWordDetector()
    if mode == "porcupine":
        return PorcupineWakeWordDetector(porcupine_access_key, porcupine_keyword)
    raise WakeWordError(f"지원하지 않는 WAKEWORD_MODE: {mode!r}")
