from __future__ import annotations

import json
import logging
import sys
from typing import Any

from shared.security import utc_now


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": utc_now().isoformat(),
            "service": getattr(record, "triage_service", record.name),
            "level": record.levelname.lower(),
            "event": getattr(record, "triage_event", record.getMessage()),
        }
        extra_payload = getattr(record, "triage_payload", {})
        if isinstance(extra_payload, dict):
            payload.update(extra_payload)
        if record.exc_info and "error" not in payload:
            payload["error"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def _get_json_logger(service: str) -> logging.Logger:
    logger = logging.getLogger(f"triage.{service}")
    if getattr(logger, "_triage_json_configured", False):
        return logger

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonLogFormatter())
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger._triage_json_configured = True
    return logger


def log_event(service: str, event: str, *, level: str = "info", **payload: Any) -> None:
    logger = _get_json_logger(service)
    logger.log(
        getattr(logging, level.upper(), logging.INFO),
        event,
        extra={
            "triage_service": service,
            "triage_event": event,
            "triage_payload": payload,
        },
    )


def log_web_event(event: str, *, level: str = "info", **payload: Any) -> None:
    log_event("web", event, level=level, **payload)


def log_worker_event(event: str, *, level: str = "info", **payload: Any) -> None:
    log_event("worker", event, level=level, **payload)
