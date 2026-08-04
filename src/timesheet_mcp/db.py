"""SQLite database connection, schema creation, and migration for timesheet-mcp."""

import os
import sqlite3
import threading
from pathlib import Path

# Project root is the directory containing pyproject.toml (one level above src/)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent

_DB_PATH_ENV = "TIMESHEET_DB_PATH"


def get_db_path() -> Path:
    """Return the path to the SQLite database file.

    Resolved from the ``TIMESHEET_DB_PATH`` environment variable if set,
    otherwise defaults to ``data/timesheet.db`` relative to the project root.
    """
    env_path = os.environ.get(_DB_PATH_ENV)
    if env_path:
        return Path(env_path)
    return _PROJECT_ROOT / "data" / "timesheet.db"


def get_connection(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Open a connection to the SQLite database.

    Parameters
    ----------
    db_path : str | Path | None
        Explicit path to the database.  If *None*, :func:`get_db_path` is
        used to resolve the path automatically.

    Returns
    -------
    sqlite3.Connection
        Connection with :py:data:`sqlite3.Row` as the row factory so results
        are accessible by column name as well as index.
    """
    if db_path is None:
        db_path = get_db_path()

    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


# ── Schema DDL (verbatim from PLAN.md §4) ──────────────────────────────────

_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS customers (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    notes       TEXT,
    archived    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    id          INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    name        TEXT NOT NULL,
    active      INTEGER NOT NULL DEFAULT 1,
    notes       TEXT,
    created_at  TEXT NOT NULL,
    UNIQUE(customer_id, name)
);

CREATE TABLE IF NOT EXISTS project_tags (
    project_id  INTEGER NOT NULL REFERENCES projects(id),
    tag         TEXT NOT NULL,
    PRIMARY KEY (project_id, tag)
);

CREATE TABLE IF NOT EXISTS people (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS time_entries (
    id           INTEGER PRIMARY KEY,
    person_id    INTEGER NOT NULL REFERENCES people(id),
    project_id   INTEGER NOT NULL REFERENCES projects(id),
    entry_date   TEXT NOT NULL,
    hours        REAL NOT NULL,
    description  TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_time_entries_date
    ON time_entries(entry_date);

CREATE INDEX IF NOT EXISTS idx_time_entries_person
    ON time_entries(person_id);

CREATE INDEX IF NOT EXISTS idx_time_entries_project
    ON time_entries(project_id);
"""

_SEED_SQL = "INSERT OR IGNORE INTO settings (key, value) VALUES ('default_daily_hours', '7.5')"


def init_db(conn: sqlite3.Connection | None = None) -> sqlite3.Connection:
    """Create all tables and indexes, seed defaults, and return the connection.

    This function is idempotent — running it multiple times on the same
    connection is safe and will not raise errors or produce duplicates.
    """
    if conn is None:
        conn = get_connection()

    conn.executescript(_SCHEMA_SQL)
    conn.execute(_SEED_SQL)
    conn.commit()
    return conn


# ── Thread-local default connection ────────────────────────────────────────

_thread_local = threading.local()


def get_default_connection() -> sqlite3.Connection:
    """Return a connection to the default DB path, cached per-thread.

    Each OS thread gets its own sqlite3.Connection (created + schema-initialized
    lazily on first use in that thread) rather than sharing one connection
    across threads, which sqlite3 does not support.
    """
    conn = getattr(_thread_local, "conn", None)
    if conn is None:
        conn = get_connection()
        init_db(conn)
        _thread_local.conn = conn
    return conn
