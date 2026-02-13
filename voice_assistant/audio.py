"""Audio capture with WebRTC VAD-based speech segmentation."""

from __future__ import annotations

import io
import logging
import queue
import wave
from collections import deque
from dataclasses import dataclass
from array import array

import sounddevice as sd
import webrtcvad

from .exceptions import AudioError

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Settings value object
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AudioSettings:
    sample_rate: int = 16000
    frame_duration_ms: int = 30        # 10 | 20 | 30
    vad_aggressiveness: int = 2        # 0‒3  (higher = more aggressive)
    silence_ms: int = 700              # trailing silence to stop
    max_record_seconds: float = 12.0
    min_speech_ms: int = 300           # minimum speech to accept


# ---------------------------------------------------------------------------
# Utility: raw PCM → WAV bytes
# ---------------------------------------------------------------------------

def pcm16_to_wav(pcm: bytes, sample_rate: int, channels: int = 1) -> bytes:
    """Wrap raw 16-bit PCM in a RIFF/WAV container (in-memory)."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# VAD recorder
# ---------------------------------------------------------------------------

class VADRecorder:
    """Records from the default mic and returns a WAV when the user stops speaking."""

    def __init__(self, settings: AudioSettings) -> None:
        if settings.frame_duration_ms not in (10, 20, 30):
            raise AudioError("frame_duration_ms must be 10, 20, or 30")

        self._s = settings
        self._vad = webrtcvad.Vad(settings.vad_aggressiveness)
        self._samples_per_frame = int(settings.sample_rate * settings.frame_duration_ms / 1000)
        self._bytes_per_frame = self._samples_per_frame * 2          # 16-bit
        self._silence_limit = max(1, settings.silence_ms // settings.frame_duration_ms)
        self._min_speech = max(1, settings.min_speech_ms // settings.frame_duration_ms)
        self._max_frames = int(settings.max_record_seconds * 1000 / settings.frame_duration_ms)
        # Fallback thresholds for environments where VAD misses real speech.
        self._start_level_threshold = 220
        self._accept_level_threshold = 120

    # ---- internal frame generator -------------------------------------------

    def _frames(self):
        """Yields fixed-size PCM16 frames from the microphone."""
        q: queue.Queue[bytes] = queue.Queue()

        def _cb(indata, _frames, _time, status):
            if status:
                log.warning("mic stream status: %s", status)
            q.put(bytes(indata))

        try:
            with sd.RawInputStream(
                samplerate=self._s.sample_rate,
                blocksize=self._samples_per_frame,
                channels=1,
                dtype="int16",
                callback=_cb,
            ):
                while True:
                    chunk = q.get()
                    if len(chunk) < self._bytes_per_frame:
                        continue
                    yield chunk[: self._bytes_per_frame]
        except Exception as exc:
            raise AudioError(f"microphone stream error: {exc}") from exc

    # ---- public API ---------------------------------------------------------

    def record_until_silence(self) -> bytes | None:
        """
        Block until the user speaks then stops (trailing silence).

        Returns WAV bytes, or ``None`` when no speech was detected
        within the maximum recording window.
        """
        pre_roll: deque[bytes] = deque(maxlen=10)
        recorded: list[bytes] = []
        started = False
        speech_count = 0
        silence_run = 0

        for idx, frame in enumerate(self._frames()):
            is_speech = self._vad.is_speech(frame, self._s.sample_rate)
            level = self._frame_level(frame)
            pre_roll.append(frame)

            if not started:
                if is_speech or level >= self._start_level_threshold:
                    if not is_speech:
                        log.info("VAD missed start. starting by energy level=%d", level)
                    started = True
                    recorded.extend(pre_roll)
                    speech_count += 1
                elif idx >= self._max_frames:
                    break
                continue

            recorded.append(frame)
            if is_speech:
                speech_count += 1
                silence_run = 0
            else:
                silence_run += 1
                if silence_run >= self._silence_limit:
                    break

            if len(recorded) >= self._max_frames:
                break

        if speech_count < self._min_speech:
            avg_level = self._avg_level(recorded)
            if recorded and avg_level >= self._accept_level_threshold:
                log.info(
                    "low VAD confidence (speech_frames=%d) but accepting by energy avg=%d",
                    speech_count,
                    avg_level,
                )
            else:
                log.info("speech too short (%d frames), discarding", speech_count)
                return None

        pcm = b"".join(recorded)
        log.info("recorded %d frames (~%.1fs)", len(recorded),
                 len(recorded) * self._s.frame_duration_ms / 1000)
        return pcm16_to_wav(pcm, self._s.sample_rate)

    @staticmethod
    def _frame_level(frame: bytes) -> int:
        samples = array("h")
        samples.frombytes(frame)
        if not samples:
            return 0
        return int(sum(abs(v) for v in samples) / len(samples))

    def _avg_level(self, frames: list[bytes]) -> int:
        if not frames:
            return 0
        levels = [self._frame_level(f) for f in frames]
        return int(sum(levels) / len(levels))
