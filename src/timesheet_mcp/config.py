"""Settings table access for the timesheet application.

All functions accept an optional ``conn`` parameter for testability.
When ``conn`` is omitted the module-level default connection (``data/
timesheet.db``) is used.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from .db import get_default_connection

# ── connection management ──────────────────────────────────────────────────


def _get_conn(
    conn: sqlite3.Connection | None,
) -> sqlite3.Connection:
    """Return a database connection, using the default when *conn* is omitted."""
    if conn is not None:
        return conn
    return get_default_connection()


# ── core settings functions ────────────────────────────────────────────────


def get_setting(
    key: str,
    *,
    conn: sqlite3.Connection | None = None,
) -> str:
    """Retrieve a setting value by key.

    Parameters
    ----------
    key : str
        The setting key to look up.

    Returns
    -------
    str
        The text value associated with *key*.

    Raises
    ------
    ValueError
        If *key* does not exist in the settings table.
    """
    __conn = _get_conn(conn)
    try:
        row = __conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Setting '{key}' not found")
        return row["value"]
    finally:
        pass


def set_setting(
    key: str,
    value: Any,
    *,
    conn: sqlite3.Connection | None = None,
) -> str:
    """Store or update a setting value.

    Parameters
    ----------
    key : str
        The setting key.
    value : Any
        The value to store (converted to str).

    Returns
    -------
    str
        The value that was stored (as text).
    """
    __conn = _get_conn(conn)
    try:
        text_value = str(value)
        __conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, text_value),
        )
        __conn.commit()
        return text_value
    finally:
        pass


def ensure_settings(
    conn: sqlite3.Connection | None = None,
) -> None:
    """Ensure the settings table is seeded with defaults.

    This function runs the seed for 'default_daily_hours' using
    INSERT OR IGNORE so it is idempotent.  It is safe to call
    multiple times.
    """
    if conn is None:
        __conn = _get_conn(None)
        try:
            __conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) "
                "VALUES ('default_daily_hours', '7.5')"
            )
            __conn.commit()
        finally:
            pass
    else:
        conn.execute(
            "INSERT OR IGNORE INTO settings (key, value) "
            "VALUES ('default_daily_hours', '7.5')"
        )
        conn.commit()


# ── convenience accessors ──────────────────────────────────────────────────


def get_default_daily_hours(
    *,
    conn: sqlite3.Connection | None = None,
) -> float:
    """Return the configured default daily hours as a float.

    Reads the ``default_daily_hours`` setting and converts it to
    ``float``.
    """
    return float(get_setting("default_daily_hours", conn=conn))
