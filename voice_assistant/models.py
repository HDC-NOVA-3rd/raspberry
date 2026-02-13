"""Data models shared across modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Voice turn (HTTP response from POST /api/voice/turn)
# ---------------------------------------------------------------------------

@dataclass
class VoiceAction:
    """A single action the backend wants the edge device to execute."""
    type: str          # e.g. "MQTT", "IOT"
    target: str        # e.g. "living-room-light"
    command: str       # e.g. "ON"
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> VoiceAction:
        return cls(
            type=str(d.get("type", "")),
            target=str(d.get("target", "")),
            command=str(d.get("command", "")),
            metadata=d.get("metadata") or {},
        )


@dataclass
class VoiceTurnResult:
    """Parsed backend response for one voice turn."""
    session_id: str
    request_id: str
    recognized_text: str
    answer: str
    tts_text: str
    intent: str
    data: Any
    actions: list[VoiceAction] = field(default_factory=list)
    end_session: bool = False

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> VoiceTurnResult:
        raw_actions = payload.get("actions") or []
        return cls(
            session_id=str(payload.get("sessionId", "") or ""),
            request_id=str(payload.get("requestId", "") or ""),
            recognized_text=str(payload.get("recognizedText", "") or ""),
            answer=str(payload.get("answer", payload.get("replyText", "")) or ""),
            tts_text=str(payload.get("ttsText", "") or ""),
            intent=str(payload.get("intent", "") or ""),
            data=payload.get("data"),
            actions=[VoiceAction.from_dict(a) for a in raw_actions],
            end_session=bool(payload.get("endSession", False)),
        )



# ---------------------------------------------------------------------------
# MQTT command execution
# ---------------------------------------------------------------------------

@dataclass
class MqttCommand:
    """Inbound MQTT command from server → edge."""
    trace_id: str
    command: str
    ho_id: int

    @classmethod
    def from_payload(cls, payload: dict[str, Any], ho_id: int) -> MqttCommand:
        return cls(
            trace_id=str(payload.get("traceId", "")),
            command=str(payload.get("command", "")),
            ho_id=ho_id,
        )


@dataclass
class MqttCommandResult:
    """Outbound MQTT result from edge → server."""
    trace_id: str
    status: str   # SUCCESS | FAIL
    detail: str
    timestamp: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "traceId": self.trace_id,
            "status": self.status,
            "detail": self.detail,
            "ts": self.timestamp,
        }
