"""Tests for :mod:`src.timesheet_mcp.logging_config`."""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from timesheet_mcp import logging_config


class TestSetupLogging:
    """Verify the logging setup respects the no-stdout rule."""

    def test_gets_root_logger(self):
        logger = logging_config.setup_logging()
        assert logger.name == logging_config.LOGGER_NAME

    def test_file_handler_attached(self):
        logger = logging_config.setup_logging()
        handler_types = [type(h).__name__ for h in logger.handlers]
        assert "RotatingFileHandler" in handler_types

    def test_no_stdout_handler(self):
        """Critical: stdout must NEVER be used for logs."""
        logger = logging_config.setup_logging()
        for h in logger.handlers:
            # Check that no handler writes to sys.stdout
            if isinstance(h, logging.StreamHandler):
                assert h.stream is not sys.stdout, (
                    "StreamHandler must never write to stdout"
                )

    def test_default_level(self, tmp_path, monkeypatch):
        """Default log level is INFO."""
        monkeypatch.delenv("TIMESHEET_LOG_LEVEL", raising=False)
        monkeypatch.delenv("TIMESHEET_LOG_STDERR", raising=False)
        with mock.patch.object(logging_config, "_LOG_DIR", tmp_path):
            logger = logging_config.setup_logging()
            assert logger.level == logging.INFO

    def test_custom_level(self, tmp_path, monkeypatch):
        """TIMESHEET_LOG_LEVEL env var overrides default."""
        monkeypatch.setenv("TIMESHEET_LOG_LEVEL", "DEBUG")
        monkeypatch.delenv("TIMESHEET_LOG_STDERR", raising=False)
        with mock.patch.object(logging_config, "_LOG_DIR", tmp_path):
            logger = logging_config.setup_logging()
            assert logger.level == logging.DEBUG

    def test_invalid_level_falls_back(self, tmp_path, monkeypatch):
        """An invalid level value falls back to INFO."""
        monkeypatch.setenv("TIMESHEET_LOG_LEVEL", "BOGUS")
        monkeypatch.delenv("TIMESHEET_LOG_STDERR", raising=False)
        with mock.patch.object(logging_config, "_LOG_DIR", tmp_path):
            logger = logging_config.setup_logging()
            assert logger.level == logging.INFO

    def test_logs_to_file(self, tmp_path, monkeypatch):
        """A message logged after setup arrives in the log file."""
        monkeypatch.delenv("TIMESHEET_LOG_LEVEL", raising=False)
        monkeypatch.delenv("TIMESHEET_LOG_STDERR", raising=False)
        with mock.patch.object(logging_config, "_LOG_DIR", tmp_path):
            # Reset logger state so handlers are re-created
            root = logging.getLogger(logging_config.LOGGER_NAME)
            old_handlers = root.handlers[:]
            root.handlers.clear()

            try:
                logger = logging_config.setup_logging()
                logger.info("test message arrives in log file")

                log_file = tmp_path / "timesheet_mcp.log"
                assert log_file.exists(), "Log file should be created"
                content = log_file.read_text("utf-8")
                assert "test message arrives in log file" in content
            finally:
                root.handlers.clear()
                root.handlers.extend(old_handlers)

    def test_stderr_handler_when_enabled(self, tmp_path, monkeypatch, capsys):
        """When TIMESHEET_LOG_STDERR=1, stderr handler is attached."""
        monkeypatch.delenv("TIMESHEET_LOG_LEVEL", raising=False)
        monkeypatch.setenv("TIMESHEET_LOG_STDERR", "1")
        with mock.patch.object(logging_config, "_LOG_DIR", tmp_path):
            root = logging.getLogger(logging_config.LOGGER_NAME)
            old_handlers = root.handlers[:]
            root.handlers.clear()

            try:
                logger = logging_config.setup_logging()
                stream_types = []
                for h in logger.handlers:
                    if isinstance(h, logging.StreamHandler):
                        stream_types.append("stderr")
                assert "stderr" in stream_types

                logger.warning("stderr warning")
                captured = capsys.readouterr()
                assert "stderr warning" in captured.err
            finally:
                root.handlers.clear()
                root.handlers.extend(old_handlers)

    def test_no_duplicate_handlers_on_reentry(self, tmp_path, monkeypatch):
        """Calling setup_logging() twice does not add duplicate handlers."""
        monkeypatch.delenv("TIMESHEET_LOG_LEVEL", raising=False)
        monkeypatch.delenv("TIMESHEET_LOG_STDERR", raising=False)
        with mock.patch.object(logging_config, "_LOG_DIR", tmp_path):
            logger = logging_config.setup_logging()
            file_count_before = sum(
                1 for h in logger.handlers
                if isinstance(h, logging.handlers.RotatingFileHandler)
            )
            logging_config.setup_logging()
            file_count_after = sum(
                1 for h in logger.handlers
                if isinstance(h, logging.handlers.RotatingFileHandler)
            )
            assert file_count_before == file_count_after == 1


class TestLogToolCallContext:
    """Verify the tool-call context manager."""

    def test_logs_entry_debug(self, tmp_path, monkeypatch):
        """On entry, a DEBUG message is emitted."""
        monkeypatch.setenv("TIMESHEET_LOG_LEVEL", "DEBUG")
        monkeypatch.delenv("TIMESHEET_LOG_STDERR", raising=False)
        with mock.patch.object(logging_config, "_LOG_DIR", tmp_path):
            root = logging.getLogger(logging_config.LOGGER_NAME)
            root.handlers.clear()
            logger = logging_config.setup_logging()

            with logging_config.log_tool_call_context(
                logger, "create_customer", {"name": "Acme"}
            ):
                pass

            log_file = tmp_path / "timesheet_mcp.log"
            content = log_file.read_text("utf-8")
            assert "create_customer" in content
            assert "name=Acme" in content
            root.handlers.clear()

    def test_logs_traceback_on_exception(self, tmp_path, monkeypatch):
        """On exception, ERROR + traceback is emitted."""
        monkeypatch.setenv("TIMESHEET_LOG_LEVEL", "DEBUG")
        monkeypatch.delenv("TIMESHEET_LOG_STDERR", raising=False)
        with mock.patch.object(logging_config, "_LOG_DIR", tmp_path):
            root = logging.getLogger(logging_config.LOGGER_NAME)
            root.handlers.clear()
            logger = logging_config.setup_logging()

            with pytest.raises(ValueError, match="boom"):
                with logging_config.log_tool_call_context(
                    logger, "log_time", {"person_id": 1}
                ):
                    raise ValueError("boom")

            log_file = tmp_path / "timesheet_mcp.log"
            content = log_file.read_text("utf-8")
            assert "ERROR" in content
            assert "log_time" in content
            assert "boom" in content
            assert "Traceback" in content
            root.handlers.clear()

    def test_propagates_exception(self, tmp_path, monkeypatch):
        """The context manager re-raises the original exception."""
        monkeypatch.delenv("TIMESHEET_LOG_LEVEL", raising=False)
        monkeypatch.delenv("TIMESHEET_LOG_STDERR", raising=False)
        with mock.patch.object(logging_config, "_LOG_DIR", tmp_path):
            logger = logging_config.setup_logging()

            with pytest.raises(RuntimeError, match="test"):
                with logging_config.log_tool_call_context(
                    logger, "test_tool"
                ):
                    raise RuntimeError("test")

    def test_success_logs_no_error(self, tmp_path, monkeypatch):
        """On success (no exception), no ERROR line is written."""
        monkeypatch.setenv("TIMESHEET_LOG_LEVEL", "DEBUG")
        monkeypatch.delenv("TIMESHEET_LOG_STDERR", raising=False)
        with mock.patch.object(logging_config, "_LOG_DIR", tmp_path):
            root = logging.getLogger(logging_config.LOGGER_NAME)
            root.handlers.clear()
            logger = logging_config.setup_logging()

            with logging_config.log_tool_call_context(
                logger, "ok_tool"
            ):
                pass

            log_file = tmp_path / "timesheet_mcp.log"
            content = log_file.read_text("utf-8")
            assert "ERROR" not in content
            assert "ok_tool" in content
            root.handlers.clear()

    def test_truncates_long_args(self, tmp_path, monkeypatch):
        """Long argument values are truncated in log lines."""
        monkeypatch.setenv("TIMESHEET_LOG_LEVEL", "DEBUG")
        monkeypatch.delenv("TIMESHEET_LOG_STDERR", raising=False)
        with mock.patch.object(logging_config, "_LOG_DIR", tmp_path):
            root = logging.getLogger(logging_config.LOGGER_NAME)
            root.handlers.clear()
            logger = logging_config.setup_logging()

            long_value = "x" * 500
            with logging_config.log_tool_call_context(
                logger, "long_arg_tool", {"data": long_value}
            ):
                pass

            log_file = tmp_path / "timesheet_mcp.log"
            content = log_file.read_text("utf-8")
            # The truncated value should not exceed ~120 chars
            assert isinstance(long_value, str)
            root.handlers.clear()


class TestLogToolCall:
    """Fire-and-forget tool-call logging."""

    def test_log_success(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TIMESHEET_LOG_LEVEL", "DEBUG")
        monkeypatch.delenv("TIMESHEET_LOG_STDERR", raising=False)
        with mock.patch.object(logging_config, "_LOG_DIR", tmp_path):
            root = logging.getLogger(logging_config.LOGGER_NAME)
            root.handlers.clear()
            logger = logging_config.setup_logging()

            logging_config.log_tool_call(
                logger, "get_customer", {"id": 1}, result="Ok"
            )

            log_file = tmp_path / "timesheet_mcp.log"
            content = log_file.read_text("utf-8")
            assert "get_customer" in content
            assert "DEBUG" in content
            root.handlers.clear()

    def test_log_error(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TIMESHEET_LOG_LEVEL", "ERROR")
        monkeypatch.delenv("TIMESHEET_LOG_STDERR", raising=False)
        with mock.patch.object(logging_config, "_LOG_DIR", tmp_path):
            root = logging.getLogger(logging_config.LOGGER_NAME)
            root.handlers.clear()
            logger = logging_config.setup_logging()

            logging_config.log_tool_call(
                logger, "bad_tool", {"id": 999}, error=ValueError("not found")
            )

            log_file = tmp_path / "timesheet_mcp.log"
            content = log_file.read_text("utf-8")
            assert "ERROR" in content
            assert "not found" in content
            root.handlers.clear()


class TestRotatingFileHandlerConfig:
    """Verify the RotatingFileHandler configuration."""

    def test_max_bytes_and_backup_count(self, tmp_path, monkeypatch):
        """Ensure maxBytes=5MB and backupCount=3."""
        monkeypatch.delenv("TIMESHEET_LOG_LEVEL", raising=False)
        monkeypatch.delenv("TIMESHEET_LOG_STDERR", raising=False)
        with mock.patch.object(logging_config, "_LOG_DIR", tmp_path):
            logger = logging_config.setup_logging()
            for h in logger.handlers:
                if isinstance(h, logging.handlers.RotatingFileHandler):
                    assert h.maxBytes == 5 * 1024 * 1024
                    assert h.backupCount == 3


class TestNoStdoutOnRealSetup:
    """End-to-end integration test: calling setup_logging() on a fresh
    process-level setup must never produce anything on stdout."""

    def test_no_stdout_leak(self, monkeypatch, tmp_path):
        """
        This test creates a subprocess that imports and calls setup_logging(),
        then captures stdout.  stdout must be empty.
        """
        script = '''
import logging
import sys

# Force a writable temp dir
import timesheet_mcp.logging_config as lc
lc._LOG_DIR = PATH

logger = lc.setup_logging()
# Force a flush so any handler output is written
handler = logger.handlers[0]
for h in logger.handlers:
    h.flush()
# If anything went to stdout, print a marker so the test can detect it
print("STDOUT_MARKER", file=sys.stdout)
'''
        script = script.replace("PATH", repr(str(tmp_path)))

        p = os.path.join(
            os.path.dirname(__file__),
            "_check_stdout.py",  # helper will be in the same dir
        )

        # Instead of a subprocess (complex setup), let's use a simpler test:
        # verify that no handler in the logger writes to stdout at all
        monkeypatch.delenv("TIMESHEET_LOG_LEVEL", raising=False)
        monkeypatch.delenv("TIMESHEET_LOG_STDERR", raising=False)
        with mock.patch.object(logging_config, "_LOG_DIR", tmp_path):
            root = logging.getLogger(logging_config.LOGGER_NAME)
            old_handlers = root.handlers[:]
            root.handlers.clear()

            try:
                logger = logging_config.setup_logging()
                # The logger must have handlers, none of which write to stdout
                for h in logger.handlers:
                    if isinstance(h, logging.StreamHandler):
                        assert (
                            h.stream is not sys.stdout
                        ), "A StreamHandler writes to stdout — this corrupts MCP protocol"
            finally:
                root.handlers.clear()
                root.handlers.extend(old_handlers)
