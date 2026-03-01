"""
MQTT client for voice turn communication and device-control commands.

Topics:
  PUB  hdc/{hoId}/assistant/voice/req   — audio upload (base64 WAV + sessionId)
  SUB  hdc/{hoId}/assistant/voice/res   — backend response (STT/intent/reply)
  SUB  hdc/{hoId}/assistant/execute/req — device-control command from server
  PUB  hdc/{hoId}/assistant/execute/res — device-control result to server
"""

from __future__ import annotations

import base64
import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any, Callable

from .exceptions import MqttError
from .models import MqttCommand, MqttCommandResult, VoiceTurnResult

log = logging.getLogger(__name__)

# Callback types
CommandHandler = Callable[[MqttCommand], tuple[str, str]]


class MqttHandler:
    """
    Unified MQTT client handling:
      1. Voice turn: Pi sends audio → backend returns STT/intent/reply
      2. Device-control: backend sends command → Pi executes → reports result
    """

    def __init__(
        self,
        broker_host: str,
        broker_port: int,
        client_id: str,
        ho_id: int,
        username: str = "",
        password: str = "",
        on_command: CommandHandler | None = None,
    ) -> None:
        try:
            import paho.mqtt.client as mqtt  # type: ignore[import-untyped]
        except ImportError as exc:
            raise MqttError(
                "paho-mqtt 패키지가 필요합니다. `pip install paho-mqtt`"
            ) from exc

        self._mqtt = mqtt
        self._ho_id = ho_id

        # Voice turn topics
        self._topic_voice_req = f"hdc/{ho_id}/assistant/voice/req"
        self._topic_voice_res = f"hdc/{ho_id}/assistant/voice/res"

        # Device-control topics
        self._topic_exec_req = f"hdc/{ho_id}/assistant/execute/req"
        self._topic_exec_res = f"hdc/{ho_id}/assistant/execute/res"

        self._on_command = on_command

        # Voice response synchronisation
        self._voice_response: VoiceTurnResult | None = None
        self._voice_event = threading.Event()

        self._client = mqtt.Client(
            client_id=client_id,
            protocol=mqtt.MQTTv311,
        )
        if username:
            self._client.username_pw_set(username, password)

        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.on_disconnect = self._on_disconnect

        self._broker_host = broker_host
        self._broker_port = broker_port

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Connect and start the network loop in a daemon thread."""
        log.info("MQTT connecting to %s:%d …", self._broker_host, self._broker_port)
        try:
            self._client.reconnect_delay_set(min_delay=2, max_delay=30)
            self._client.connect(self._broker_host, self._broker_port, keepalive=60)
        except Exception as exc:
            raise MqttError(f"MQTT 연결 실패: {exc}") from exc

        self._client.loop_start()
        log.info("MQTT loop started")

    def stop(self) -> None:
        """Disconnect gracefully."""
        self._client.loop_stop()
        self._client.disconnect()
        log.info("MQTT disconnected")

    # ------------------------------------------------------------------
    # Voice turn: send audio, wait for response
    # ------------------------------------------------------------------

    def send_audio(
        self,
        wav_bytes: bytes,
        session_id: str = "",
        timeout: float = 15.0,
    ) -> VoiceTurnResult | None:
        """
        Publish audio to the voice request topic and block until the
        backend responds on the voice response topic (or timeout).

        Returns ``VoiceTurnResult`` on success, ``None`` on timeout.
        """
        self._voice_response = None
        self._voice_event.clear()

        audio_b64 = base64.b64encode(wav_bytes).decode("ascii")
        payload: dict[str, Any] = {"audio": audio_b64}
        if session_id:
            payload["sessionId"] = session_id

        msg = json.dumps(payload, ensure_ascii=False)
        info = self._client.publish(self._topic_voice_req, msg, qos=1)
        log.info("audio published to %s (%d bytes, rc=%s)",
                 self._topic_voice_req, len(wav_bytes), info.rc)

        # Block until voice/res arrives
        if self._voice_event.wait(timeout=timeout):
            return self._voice_response

        log.warning("voice response timeout (%.1fs)", timeout)
        return None

    # ------------------------------------------------------------------
    # Device-control: publish result
    # ------------------------------------------------------------------

    def publish_exec_result(self, result: MqttCommandResult) -> None:
        """Publish device-control execution result."""
        payload = json.dumps(result.to_dict(), ensure_ascii=False)
        self._client.publish(self._topic_exec_res, payload, qos=0)
        log.debug("exec result published on %s", self._topic_exec_res)

    # ------------------------------------------------------------------
    # MQTT callbacks
    # ------------------------------------------------------------------

    def _on_connect(self, client, userdata, flags, rc):
        if rc != 0:
            log.error("MQTT connect failed (rc=%d)", rc)
            return

        log.info("MQTT connected — subscribing to topics")
        client.subscribe(self._topic_voice_res, qos=1)
        client.subscribe(self._topic_exec_req, qos=0)

    def _on_disconnect(self, client, userdata, rc):
        if rc != 0:
            log.warning("MQTT disconnected (rc=%d) — will auto-reconnect (2~30s)", rc)

    def _on_message(self, client, userdata, msg):
        topic = msg.topic
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except Exception as exc:
            log.error("MQTT payload decode failed: topic=%s err=%s", topic, exc)
            return

        if topic == self._topic_voice_res:
            self._handle_voice_response(payload)
        elif topic == self._topic_exec_req:
            self._handle_exec_command(payload)
        else:
            log.debug("MQTT unknown topic: %s", topic)

    # ------------------------------------------------------------------
    # Internal handlers
    # ------------------------------------------------------------------

    def _handle_voice_response(self, payload: dict[str, Any]) -> None:
        """Parse backend voice response and unblock the waiting thread."""
        tts_text = str(payload.get("ttsText", "") or "")
        answer = str(payload.get("answer", payload.get("replyText", "")) or "")
        log.info(
            "voice response received: intent=%s tts_len=%d answer_len=%d",
            payload.get("intent"),
            len(tts_text.strip()),
            len(answer.strip()),
        )
        try:
            self._voice_response = VoiceTurnResult.from_json(payload)
        except Exception as exc:
            log.error("voice response parse failed: %s", exc)
            self._voice_response = None
        self._voice_event.set()

    def _handle_exec_command(self, payload: dict[str, Any]) -> None:
        """Handle device-control command from the server."""
        log.info("exec command received: %s", payload)
        cmd = MqttCommand.from_payload(payload, ho_id=self._ho_id)

        if self._on_command is not None:
            status, detail = self._on_command(cmd)
        else:
            status, detail = "FAIL", "no handler registered"

        result = MqttCommandResult(
            trace_id=cmd.trace_id,
            status=status,
            detail=detail,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        self.publish_exec_result(result)
