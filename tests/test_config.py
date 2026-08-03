"""Tests for src/timesheet_mcp/config — get/set round-trip, seeding."""

from __future__ import annotations

import sqlite3

import pytest

from timesheet_mcp.db import init_db
from timesheet_mcp.config import (
    ensure_settings,
    get_default_daily_hours,
    get_setting,
    set_setting,
)


# ── fixture ────────────────────────────────────────────────────────────────


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    init_db(c)
    yield c
    c.close()


# ── seeding ────────────────────────────────────────────────────────────────


class TestEnsureSettings:
    def test_seeds_default_daily_hours(self, conn):
        """ensure_settings adds the seed row if it does not exist."""
        ensure_settings(conn)
        value = get_setting("default_daily_hours", conn=conn)
        assert value == "7.5"

    def test_idempotent(self, conn):
        """Running ensure_settings twice does not duplicate the seed."""
        ensure_settings(conn)
        ensure_settings(conn)
        count = conn.execute(
            "SELECT COUNT(*) AS c FROM settings WHERE key = 'default_daily_hours'"
        ).fetchone()["c"]
        assert count == 1

    def test_skips_existing_seed(self, conn):
        """If the row is already present, ensure_settings leaves it alone."""
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('default_daily_hours', '8.0')"
        )
        ensure_settings(conn)
        value = get_setting("default_daily_hours", conn=conn)
        assert value == "8.0"


# ── get_setting ────────────────────────────────────────────────────────────


class TestGetSetting:
    def test_returns_value(self, conn):
        conn.execute(
            "INSERT INTO settings (key, value) VALUES ('foo', 'bar')"
        )
        assert get_setting("foo", conn=conn) == "bar"

    def test_not_found_raises(self, conn):
        with pytest.raises(ValueError, match="not found"):
            get_setting("missing", conn=conn)

    def test_seed_value(self, conn):
        """Initial seed gives '7.5'."""
        ensure_settings(conn)
        assert get_setting("default_daily_hours", conn=conn) == "7.5"


# ── set_setting ────────────────────────────────────────────────────────────


class TestSetSetting:
    def test_sets_new_key(self, conn):
        result = set_setting("max_entry_hours", "24", conn=conn)
        assert result == "24"
        assert get_setting("max_entry_hours", conn=conn) == "24"

    def test_updates_existing_key(self, conn):
        ensure_settings(conn)
        set_setting("default_daily_hours", "8.0", conn=conn)
        assert get_setting("default_daily_hours", conn=conn) == "8.0"

    def test_converts_value_to_string(self, conn):
        set_setting("num_key", 42, conn=conn)
        assert get_setting("num_key", conn=conn) == "42"

    def test_round_trip(self, conn):
        original = "hello world"
        set_setting("test_key", original, conn=conn)
        assert get_setting("test_key", conn=conn) == original


# ── default_daily_hours convenience accessor ──────────────────────────────


class TestGetDefaultDailyHours:
    def test_returns_7_5_as_float(self, conn):
        ensure_settings(conn)
        assert get_default_daily_hours(conn=conn) == 7.5

    def test_reflects_updated_value(self, conn):
        ensure_settings(conn)
        set_setting("default_daily_hours", "8.0", conn=conn)
        assert get_default_daily_hours(conn=conn) == 8.0

    def test_raises_when_missing(self, conn):
        """When default_daily_hours is missing, it raises."""
        conn.execute("DELETE FROM settings WHERE key = 'default_daily_hours'")
        with pytest.raises(ValueError, match="not found"):
            get_default_daily_hours(conn=conn)
