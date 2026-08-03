"""Logging setup for timesheet-mcp.

Configures a ``RotatingFileHandler`` writing to ``logs/timesheet_mcp.log``
(maxBytes=5 MB, backupCount=3).  Log level defaults to ``INFO`` but can
be overridden via the ``TIMESHEET_LOG_LEVEL`` environment variable.

.. important::

    *Never* attach a ``StreamHandler`` to ``sys.stdout`` — the MCP stdio
    transport uses stdout for the JSON‑RPC channel, so any stray log line
    to stdout corrupts the protocol stream.  Log to file (and optionally
    stderr) only.

Tool-call logging helpers
-------------------------

``log_tool_call(logger, name, ...)`` / ``log_tool_call_context``
    Emit ``DEBUG`` on entry and ``ERROR`` (with traceback) on exit.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
import traceback
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

# Project root is the directory containing pyproject.toml (one level above src/)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_LOG_DIR = _PROJECT_ROOT / "logs"

# Root logger name used for all timesheet modules
LOGGER_NAME = "timesheet_mcp"

_DEFAULT_LEVEL = "INFO"


# ── setup ──────────────────────────────────────────────────────────────────


def setup_logging() -> logging.Logger:
    """Configure the root *timesheet_mcp* logger and return it.

    Called once at application startup (from ``server.py``).
    """
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(_resolve_level())

    # If logger already has handlers (e.g. re-entry), do not duplicate.
    if logger.handlers:
        return logger

    handler = _make_file_handler()
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-5s %(name)s -- %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(fmt)
    logger.addHandler(handler)

    # Optionally attach stderr handler so errors are visible on the terminal
    # without touching stdout.
    if os.environ.get("TIMESHEET_LOG_STDERR", "").lower() in ("1", "true", "yes"):
        stderr_handler = logging.StreamHandler(sys.stderr)
        stderr_handler.setFormatter(fmt)
        logger.addHandler(stderr_handler)

    return logger


def _resolve_level() -> int:
    """Convert the value of ``TIMESHEET_LOG_LEVEL`` to an integer level."""
    raw = os.environ.get("TIMESHEET_LOG_LEVEL", _DEFAULT_LEVEL).strip().upper()
    level = getattr(logging, raw, None)
    if not isinstance(level, int):
        level = getattr(logging, _DEFAULT_LEVEL)
    return level


def _make_file_handler() -> logging.handlers.RotatingFileHandler:
    """Create a :class:`RotatingFileHandler` for the log file."""
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = _LOG_DIR / "timesheet_mcp.log"
    return logging.handlers.RotatingFileHandler(
        str(log_file),
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=3,
        encoding="utf-8",
    )


# ── Tool-call logging helpers ──────────────────────────────────────────────


@contextmanager
def log_tool_call_context(
    logger: logging.Logger,
    tool_name: str,
    args: dict[str, Any] | None = None,
) -> Generator[None, None, None]:
    """Context manager that logs tool entry on ``DEBUG`` and exit on ``ERROR``.

    Usage::

        with log_tool_call_context(logger, "create_customer", {"name": "Acme"}):
            result = do_create_customer(...)

    On successful return nothing is logged (tool entry was already recorded).
    On any raised exception the traceback is logged at ``ERROR``.
    """
    logger.debug("Tool call: %s(%s)", tool_name, _fmt_args(args or {}))
    try:
        yield
    except Exception:
        logger.error(
            "Tool call %s failed:\n%s",
            tool_name,
            traceback.format_exc(),
            exc_info=True,
        )
        raise


def log_tool_call(
    logger: logging.Logger,
    tool_name: str,
    args: dict[str, Any] | None = None,
    result: str | None = None,
    error: Exception | None = None,
) -> None:
    """Fire-and-forget tool-call logging (non-context-manager form).

    Useful when the function is synchronous and doesn't fit naturally
    into a ``with`` block.
    """
    if result is not None:
        logger.debug("Tool call: %s(%s) -> OK", tool_name, _fmt_args(args))
    if error is not None:
        logger.error(
            "Tool call %s(%s) failed: %s",
            tool_name,
            _fmt_args(args),
            error,
            exc_info=True,
        )


def _fmt_args(args: dict[str, Any]) -> str:
    """Truncate long values so logs stay readable."""
    parts: list[str] = []
    for k, v in args.items():
        s = str(v)
        if len(s) > 120:
            s = s[:117] + "..."
        parts.append(f"{k}={s}")
    return ", ".join(parts)
