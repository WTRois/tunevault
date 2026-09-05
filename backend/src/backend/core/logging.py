"""Structured logging setup (blueprint §36, TV2-037).

The codebase logs through loguru everywhere, so this module configures a
single app-wide sink: one JSON object per line (``LOG_FORMAT=json``) with
the §36 minimum fields carried via ``logger.bind(...)``::

    logger.bind(
        operation="identify", file_id=812, provider="acoustid",
        status="matched", score=98.4, duration_ms=421,
    ).info("identify decision")

No new dependency — loguru is already installed and used by every module.

No PII: ``diagnose=False`` keeps local variables out of tracebacks, and
call sites only ever bind ids/paths, never tag contents.
"""

import sys
from typing import TextIO

from loguru import logger

from backend.core.config import settings


def setup_logging(sink: TextIO | None = None) -> None:
    """(Re)configure the single loguru sink for structured output (§36).

    Idempotent: removes all existing sinks first. ``sink`` defaults to
    stderr so tests can capture the stream.
    """
    logger.remove()
    logger.add(
        sink or sys.stderr,
        level=settings.LOG_LEVEL,
        serialize=settings.LOG_FORMAT == "json",
        backtrace=False,
        diagnose=False,
    )