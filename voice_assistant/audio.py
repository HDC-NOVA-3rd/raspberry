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
        self._start_level_threshold = 180
        self._accept_level_threshold = 90
        self._end_level_threshold = 70

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
        pre_levels: list[int] = []
        recorded: list[bytes] = []
        started = False
        speech_count = 0
        silence_run = 0

        # Calibrate noise floor from first 30 frames (~0.9s) before speech starts
        _calibrated = False
        start_level_threshold = self._start_level_threshold
        end_level_threshold = self._end_level_threshold

        for idx, frame in enumerate(self._frames()):
            is_speech = self._vad.is_speech(frame, self._s.sample_rate)
            level = self._frame_level(frame)
            pre_roll.append(frame)

            if not started:
                if not _calibrated:
                    pre_levels.append(level)
                    if len(pre_levels) >= 30:
                        pre_levels.sort()
                        noise_floor = pre_levels[len(pre_levels) // 2]
                        # 노이즈 최댓값도 고려 (중앙값 대신 상위 80% 사용)
                        noise_p80 = pre_levels[int(len(pre_levels) * 0.8)]
                        # start: 음성이 노이즈보다 확실히 커야 트리거
                        start_level_threshold = max(
                            self._start_level_threshold,
                            int(noise_p80 * 2.5),
                        )
                        # end: 묵음 판정 기준 (노이즈 p80 * 1.6)
                        end_level_threshold = max(
                            self._end_level_threshold,
                            int(noise_p80 * 1.6),
                        )
                        _calibrated = True
                        log.debug(
                            "noise floor calibrated: median=%d p80=%d start_thr=%d end_thr=%d",
                            noise_floor, noise_p80, start_level_threshold, end_level_threshold,
                        )
                    else:
                        # 캘리브레이션 미완료 — 트리거 검사 건너뜀
                        continue

                # 시작 조건: 에너지 레벨 기반 (VAD는 노이즈에 취약하므로 보조 수단)
                energy_trigger = level >= start_level_threshold
                if energy_trigger:
                    log.debug("recording started: level=%d vad=%s start_thr=%d end_thr=%d",
                              level, is_speech, start_level_threshold, end_level_threshold)
                    started = True
                    recorded.extend(pre_roll)
                    speech_count += 1
                elif idx >= self._max_frames:
                    break
                continue

            recorded.append(frame)
            # 묵음 판정은 순수 레벨 기반 (VAD가 노이즈에 항상 True 반환하는 환경 대응)
            is_active_speech = level >= end_level_threshold
            if is_active_speech:
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
                log.debug(
                    "low VAD confidence (speech_frames=%d) accepted by energy avg=%d",
                    speech_count, avg_level,
                )
            else:
                log.debug("speech too short (%d frames), discarding", speech_count)
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
