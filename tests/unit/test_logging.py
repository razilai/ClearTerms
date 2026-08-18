"""Unit tests: JSON log formatter and setup_logging."""


import json
import logging
import sys
from collections.abc import Iterator

import pytest

from app.core.config import settings
from app.core.logging import JsonFormatter, setup_logging

# --- logging ---


def _record(msg: str, *args: object, level: int = logging.INFO) -> logging.LogRecord:
    return logging.LogRecord(
        name="test.logger",
        level=level,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=args,
        exc_info=None,
    )


def test_json_formatter_emits_valid_json_with_core_fields() -> None:
    out = json.loads(JsonFormatter().format(_record("hello %s", "world")))
    assert out["message"] == "hello world"
    assert out["level"] == "INFO"
    assert out["logger"] == "test.logger"
    assert "timestamp" in out


def test_json_formatter_merges_extra_fields() -> None:
    record = _record("with context")
    record.user_id = 7  # what logging does for logger.info(..., extra={"user_id": 7})
    out = json.loads(JsonFormatter().format(record))
    assert out["user_id"] == 7


def test_json_formatter_includes_exception_traceback() -> None:
    record = _record("boom", level=logging.ERROR)
    try:
        raise ValueError("kaboom")
    except ValueError:
        record.exc_info = sys.exc_info()
    out = json.loads(JsonFormatter().format(record))
    assert "ValueError: kaboom" in out["exception"]


@pytest.fixture
def _restore_root_logging() -> Iterator[None]:
    """Snapshot and restore global logging state around a setup_logging() test."""
    names = ("uvicorn", "uvicorn.error", "uvicorn.access")
    root = logging.getLogger()
    saved_root = (root.handlers[:], root.level)
    saved = {
        n: (logging.getLogger(n).handlers[:], logging.getLogger(n).propagate)
        for n in names
    }
    try:
        yield
    finally:
        root.handlers[:] = saved_root[0]
        root.setLevel(saved_root[1])
        for n, (handlers, propagate) in saved.items():
            lg = logging.getLogger(n)
            lg.handlers[:] = handlers
            lg.propagate = propagate


@pytest.mark.usefixtures("_restore_root_logging")
def test_setup_logging_installs_single_json_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "log_level", "WARNING")
    setup_logging()
    setup_logging()  # idempotent: a second call must not stack handlers.

    root = logging.getLogger()
    assert len(root.handlers) == 1
    assert isinstance(root.handlers[0].formatter, JsonFormatter)
    assert root.level == logging.WARNING


@pytest.mark.usefixtures("_restore_root_logging")
def test_setup_logging_folds_uvicorn_loggers_into_root() -> None:
    setup_logging()
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        assert lg.handlers == []
        assert lg.propagate is True
