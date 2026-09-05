"""Structured logging tests (TV2-037, blueprint §36)."""

import json
from io import StringIO

from backend.core.config import settings as global_settings
from backend.core.logging import setup_logging


def _last_record(io: StringIO) -> dict:
    lines = [line for line in io.getvalue().splitlines() if line.strip()]
    assert lines, "no log output captured"
    return json.loads(lines[-1])


def test_json_format_emits_structured_fields(monkeypatch):
    monkeypatch.setattr(global_settings, "LOG_FORMAT", "json")
    io = StringIO()
    setup_logging(sink=io)

    from loguru import logger

    logger.bind(
        operation="identify",
        job_id=42,
        file_id=812,
        provider="acoustid",
        status="matched",
        score=98.4,
        duration_ms=421,
    ).info("identify decision")

    payload = _last_record(io)
    # loguru JSON envelope: formatted "text" + "record" (raw message + extra).
    record = payload["record"]
    assert record["message"] == "identify decision"
    extra = record["extra"]
    assert extra["operation"] == "identify"
    assert extra["job_id"] == 42
    assert extra["file_id"] == 812
    assert extra["provider"] == "acoustid"
    assert extra["status"] == "matched"
    assert extra["duration_ms"] == 421


def test_pretty_format_for_local_dev(monkeypatch):
    monkeypatch.setattr(global_settings, "LOG_FORMAT", "pretty")
    io = StringIO()
    setup_logging(sink=io)

    from loguru import logger

    logger.info("hello tunevault")
    out = io.getvalue()
    assert "hello tunevault" in out
    assert not out.lstrip().startswith("{")  # human-readable, not JSON


def test_setup_logging_is_idempotent(monkeypatch):
    """Calling setup twice replaces the sink instead of duplicating lines."""
    monkeypatch.setattr(global_settings, "LOG_FORMAT", "json")
    io = StringIO()

    from loguru import logger

    setup_logging(sink=io)
    setup_logging(sink=io)
    logger.info("only once")

    lines = [line for line in io.getvalue().splitlines() if line.strip()]
    assert len(lines) == 1


def test_log_level_respected(monkeypatch):
    monkeypatch.setattr(global_settings, "LOG_LEVEL", "WARNING")
    monkeypatch.setattr(global_settings, "LOG_FORMAT", "json")
    io = StringIO()
    setup_logging(sink=io)

    from loguru import logger

    logger.info("dropped")
    logger.warning("kept")
    assert "dropped" not in io.getvalue()
    assert "kept" in io.getvalue()