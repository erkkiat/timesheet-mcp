"""Tests for src/timesheet_mcp/db — schema creation, tables, indexes, seeds."""

import sqlite3
from pathlib import Path

import pytest

from timesheet_mcp.db import get_connection, get_db_path, init_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def in_memory_db():
    """Return an in-memory sqlite3.Connection and run init_db on it."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# Table existence
# ---------------------------------------------------------------------------

TABLES = ["customers", "projects", "project_tags", "people", "time_entries", "settings"]


class TestTablesExist:
    def test_all_tables_exist(self, in_memory_db):
        cursor = in_memory_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        names = {row["name"] for row in cursor}
        for t in TABLES:
            assert t in names, f"Table '{t}' not found in sqlite_master"

    def test_no_extra_user_tables(self, in_memory_db):
        cursor = in_memory_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        names = {row["name"] for row in cursor}
        assert names == set(TABLES)


# ---------------------------------------------------------------------------
# Index existence
# ---------------------------------------------------------------------------

INDEXES = [
    "idx_time_entries_date",
    "idx_time_entries_person",
    "idx_time_entries_project",
]


class TestIndexesExist:
    def test_all_indexes_exist(self, in_memory_db):
        cursor = in_memory_db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%' ORDER BY name"
        )
        names = {row["name"] for row in cursor}
        for idx in INDEXES:
            assert idx in names, f"Index '{idx}' not found"

    def test_all_indexes_exist_no_extra(self, in_memory_db):
        cursor = in_memory_db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%' ORDER BY name"
        )
        names = {row["name"] for row in cursor}
        assert names == set(INDEXES)


# ---------------------------------------------------------------------------
# Seed row
# ---------------------------------------------------------------------------

class TestSeedRow:
    def test_default_daily_hours_present(self, in_memory_db):
        row = in_memory_db.execute(
            "SELECT value FROM settings WHERE key = 'default_daily_hours'"
        ).fetchone()
        assert row is not None
        assert row["value"] == "7.5"

    def test_only_one_seed_row(self, in_memory_db):
        count = in_memory_db.execute(
            "SELECT COUNT(*) AS c FROM settings WHERE key = 'default_daily_hours'"
        ).fetchone()["c"]
        assert count == 1


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

class TestIdempotency:
    def test_init_db_twice_succeeds(self, in_memory_db):
        # Second call should not raise
        init_db(in_memory_db)

    def test_seed_row_not_duplicated_after_reread(self, in_memory_db):
        init_db(in_memory_db)
        count = in_memory_db.execute(
            "SELECT COUNT(*) AS c FROM settings WHERE key = 'default_daily_hours'"
        ).fetchone()["c"]
        assert count == 1


# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------

class TestConnection:
    def test_row_factory(self, in_memory_db):
        """Verify that init_db preserves the sqlite3.Row row_factory."""
        assert in_memory_db.row_factory is sqlite3.Row

    def test_get_db_path_defaults_to_project_data(self):
        """Default path is data/timesheet.db relative to project root."""
        path = get_db_path()
        assert path.name == "timesheet.db"
        assert path.parent.name == "data"
