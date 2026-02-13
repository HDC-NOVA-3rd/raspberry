"""Custom exception hierarchy for the voice assistant."""

from __future__ import annotations


class VoiceAssistantError(Exception):
    """Base class for all voice-assistant errors."""


class AudioError(VoiceAssistantError):
    """Raised when audio capture or processing fails."""


class MqttError(VoiceAssistantError):
    """Raised when an MQTT operation fails."""


class WakeWordError(VoiceAssistantError):
    """Raised when the wake-word engine fails to initialize."""
