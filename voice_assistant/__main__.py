"""``python -m voice_assistant`` entry point."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    # Support direct script execution:
    # python voice_assistant/__main__.py
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from voice_assistant.config import AssistantConfig
    from voice_assistant.pipeline import VoiceAssistantPipeline
else:
    from .config import AssistantConfig
    from .pipeline import VoiceAssistantPipeline


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    log = logging.getLogger("voice_assistant")

    try:
        config = AssistantConfig.from_env()
    except Exception as exc:
        log.critical("설정 로드 실패: %s", exc, exc_info=True)
        sys.exit(1)

    log.info("config loaded  ho_id=%d  wakeword=%s  mqtt=%s:%d",
             config.ho_id, config.wakeword_mode,
             config.mqtt_broker_host, config.mqtt_broker_port)

    pipeline = VoiceAssistantPipeline(config)
    pipeline.run_forever()


if __name__ == "__main__":
    main()
