"""Structured (JSON) logging that automatically includes the active trace/span ids."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

from agentcore.obs.tracing import current_span

_RESERVED = set(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {"message", "asctime"}


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        span = current_span()
        if span is not None:
            payload["trace_id"] = span.trace_id
            payload["span_id"] = span.span_id
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(
    level: str | int = "INFO", json_format: bool = True, stream: Any = None
) -> None:
    """Configure the ``agentcore`` logger hierarchy."""
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(
        JSONFormatter()
        if json_format
        else logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    logger = logging.getLogger("agentcore")
    logger.handlers[:] = [handler]
    logger.setLevel(level if isinstance(level, int) else level.upper())
    logger.propagate = False


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name if name.startswith("agentcore") else f"agentcore.{name}")
