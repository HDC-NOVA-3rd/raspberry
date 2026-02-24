"""Wake-word detection: manual (Enter key) or Porcupine hot-word engine."""

from __future__ import annotations

import abc
import logging
import queue
import threading
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

    def stop(self) -> None:
        """Request wait loop to stop ASAP. Override if needed."""

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

    def __init__(
        self,
        access_key: str,
        keyword: str,
        sensitivity: float = 0.65,
        input_device: int | None = None,
    ) -> None:
        try:
            import pvporcupine  # type: ignore[import-untyped]
        except ImportError as exc:
            raise WakeWordError(
                "pvporcupine 패키지가 필요합니다. `pip install pvporcupine`"
            ) from exc

        if not access_key.strip():
            raise WakeWordError("PORCUPINE_ACCESS_KEY 필수")

        sens = max(0.0, min(1.0, float(sensitivity)))
        kw = keyword.strip()

        if kw.endswith(".ppn"):
            # Detect language from filename (e.g. "_ko_" → porcupine_params_ko.pv)
            import os, re
            _lib_common = os.path.join(
                os.path.dirname(pvporcupine.__file__), "lib", "common"
            )
            _lang_match = re.search(r"_([a-z]{2})_", os.path.basename(kw))
            _model_path: str | None = None
            if _lang_match:
                _lang = _lang_match.group(1)
                _candidate = os.path.join(_lib_common, f"porcupine_params_{_lang}.pv")
                if os.path.isfile(_candidate):
                    _model_path = _candidate
                    log.info("porcupine: using language model %s", _candidate)
                else:
                    log.warning(
                        "porcupine: model file not found for language '%s' (%s); "
                        "falling back to default English model",
                        _lang, _candidate,
                    )
            create_kwargs: dict = dict(
                access_key=access_key.strip(),
                keyword_paths=[kw],
                sensitivities=[sens],
            )
            if _model_path:
                create_kwargs["model_path"] = _model_path
            self._porcupine = pvporcupine.create(**create_kwargs)
        else:
            self._porcupine = pvporcupine.create(
                access_key=access_key.strip(),
                keywords=[kw or "porcupine"],
                sensitivities=[sens],
            )
        self._input_device = input_device
        self._stop_requested = threading.Event()
        log.info(
            "porcupine initialised (keyword=%s, sensitivity=%.2f, input_device=%s)",
            keyword,
            sens,
            input_device if input_device is not None else "default",
        )

    def wait(self) -> None:
        self._stop_requested.clear()
        fl = self._porcupine.frame_length
        q: queue.Queue[bytes] = queue.Queue()

        def _cb(indata, _frames, _time, status):
            if status:
                log.warning("wakeword mic status: %s", status)
            q.put(bytes(indata))

        def _listen(device_index: int | None) -> None:
            with sd.RawInputStream(
                samplerate=self._porcupine.sample_rate,
                blocksize=fl,
                channels=1,
                dtype="int16",
                device=device_index,
                callback=_cb,
            ):
                while not self._stop_requested.is_set():
                    try:
                        raw = q.get(timeout=0.2)
                    except queue.Empty:
                        continue
                    if len(raw) != fl * 2:
                        continue
                    if self._porcupine.process(array("h", raw)) >= 0:
                        log.info("wake-word detected!")
                        return

        try:
            _listen(self._input_device)
        except Exception as exc:
            if self._input_device is not None:
                log.warning(
                    "wakeword input_device=%s open failed (%s). retrying default input device",
                    self._input_device,
                    exc,
                )
                _listen(None)
                return
            raise

    def stop(self) -> None:
        self._stop_requested.set()

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
    porcupine_sensitivity: float = 0.65,
    wakeword_input_device: int | None = None,
) -> WakeWordDetector:
    """Return the appropriate detector for *mode* ('manual' | 'porcupine')."""
    mode = (mode or "manual").strip().lower()
    if mode == "manual":
        return ManualWakeWordDetector()
    if mode == "porcupine":
        return PorcupineWakeWordDetector(
            porcupine_access_key,
            porcupine_keyword,
            porcupine_sensitivity,
            wakeword_input_device,
        )
    raise WakeWordError(f"지원하지 않는 WAKEWORD_MODE: {mode!r}")
