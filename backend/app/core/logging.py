"""Logging setup for the whole app. Called once from the lifespan hook.

Everything is emitted as one JSON object per line on stdout, so a log
aggregator can parse it without regex. Application modules just use
``logging.getLogger(__name__)``; this module owns the root handler and format,
and folds uvicorn's own loggers into it so access/error lines share the shape.
"""

import json
import logging
import sys
from datetime import UTC, datetime

from app.core.config import settings

# uvicorn ships its own handlers + formatters on these loggers; we clear them and
# let the records propagate to root so every line is JSON, not just app logs.
_UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")

# Record attributes that are always present; anything else a caller passes via
# ``logger.info(..., extra={...})`` is merged into the JSON payload.
_STANDARD_ATTRS = frozenset(
    logging.LogRecord("", 0, "", 0, "", None, None).__dict__
) | {"message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    """Render a log record as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Structured context passed via `extra=` (e.g. request ids later).
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)
        return json.dumps(payload, default=str)


def setup_logging() -> None:
    """Install a single JSON stdout handler on the root logger.

    Idempotent: it clears existing handlers before adding its own, so repeated
    calls (or a call after uvicorn configured its defaults) always leave exactly
    one handler and a consistent format.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.log_level.upper())

    for name in _UVICORN_LOGGERS:
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
