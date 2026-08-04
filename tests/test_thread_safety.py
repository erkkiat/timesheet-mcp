"""Regression test: SQLite thread-affinity error must not break operations.

This test exercises the default-connection path across multiple OS threads,
matching how server.py dispatches tool calls through a thread pool.

Before the fix, this test fails with:

    SQLite objects created in a thread can only be used in that same thread.
    The object was created in thread id X and this is thread id Y.
"""

from __future__ import annotations

import os
import tempfile
import threading
from pathlib import Path

import pytest

from timesheet_mcp import repository
from timesheet_mcp.db import get_connection, get_db_path, init_db


# ── temp DB fixture ────────────────────────────────────────────────────────


@pytest.fixture()
def temp_db_path(tmp_path: Path) -> Path:
    """Return a path to a temporary DB file and seed it.

    Also set TIMESHEET_DB_PATH so all workers use this as the default
    database file (matching production).
    """
    db_path = tmp_path / "timesheet.db"
    conn = get_connection(db_path)
    init_db(conn)
    conn.close()

    _clear_caches()
    _orig = os.environ.get("TIMESHEET_DB_PATH")
    os.environ["TIMESHEET_DB_PATH"] = str(db_path)
    yield db_path
    if _orig is None:
        os.environ.pop("TIMESHEET_DB_PATH", None)
    else:
        os.environ["TIMESHEET_DB_PATH"] = _orig
    _clear_caches()


def _clear_caches() -> None:
    """Clear the thread-local connection caches in all affected modules."""
    import timesheet_mcp.db as db_mod

    db_mod._thread_local.conn = None


# ── workers (use default-connection path, NOT explicit conn) ───────────────


def _worker_create_person(thread_idx: int, exception_holder: list) -> None:
    """Worker: create_person without passing conn=."""
    try:
        repository.create_person(f"TS-Person-{thread_idx}")
    except Exception as exc:
        exception_holder.append(exc)


def _worker_create_customer(thread_idx: int, exception_holder: list) -> None:
    """Worker: create_customer without passing conn=."""
    try:
        repository.create_customer(f"TS-Customer-{thread_idx}")
    except Exception as exc:
        exception_holder.append(exc)


# ── tests ──────────────────────────────────────────────────────────────────


class TestThreadPoolSafety:
    """Thread-safety regression using the default-connection path."""

    def test_concurrent_create_person(self, temp_db_path: Path) -> None:
        """10 threads, each create_person via default-connection path."""
        NUM = 10
        exceptions: list[Exception] = []
        threads = [
            threading.Thread(target=_worker_create_person, args=(i, exceptions))
            for i in range(NUM)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Join any remaining WAL frames so reads pick up committed writes
        conn = get_connection(temp_db_path)
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.close()

        assert exceptions == [], f"Thread exceptions: {exceptions}"

        # Verify rows landed
        conn = get_connection(temp_db_path)
        row = conn.execute("SELECT COUNT(*) AS c FROM people").fetchone()
        conn.close()
        assert row["c"] == NUM

    def test_concurrent_create_customer(self, temp_db_path: Path) -> None:
        """10 threads, each create_customer via default-connection path."""
        NUM = 10
        exceptions: list[Exception] = []
        threads = [
            threading.Thread(
                target=_worker_create_customer, args=(i, exceptions)
            )
            for i in range(NUM)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        conn = get_connection(temp_db_path)
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.close()

        assert exceptions == [], f"Thread exceptions: {exceptions}"

        conn = get_connection(temp_db_path)
        row = conn.execute("SELECT COUNT(*) AS c FROM customers").fetchone()
        conn.close()
        assert row["c"] == NUM

    def test_concurrent_mixed_operations(
        self, temp_db_path: Path
    ) -> None:
        """People and customers written from separate threads."""
        NUM = 5
        exceptions: list[Exception] = []
        threads: list[threading.Thread] = []

        person_threads = [
            threading.Thread(target=_worker_create_person, args=(i, exceptions))
            for i in range(NUM)
        ]
        threads.extend(person_threads)

        customer_threads = [
            threading.Thread(
                target=_worker_create_customer, args=(i, exceptions)
            )
            for i in range(NUM)
        ]
        threads.extend(customer_threads)

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        conn = get_connection(temp_db_path)
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.close()

        assert exceptions == [], f"Thread exceptions: {exceptions}"

        import timesheet_mcp.db as db_mod
        db_mod._thread_local.conn = None

        conn = get_connection(temp_db_path)
        people_count = conn.execute("SELECT COUNT(*) AS c FROM people").fetchone()[
            "c"
        ]
        customer_count = conn.execute(
            "SELECT COUNT(*) AS c FROM customers"
        ).fetchone()["c"]
        conn.close()
        assert people_count == NUM
        assert customer_count == NUM

    def test_concurrent_read_reports(self, temp_db_path: Path) -> None:
        """Cross-thread read access via default-connection path."""
        path = temp_db_path

        # Create baseline data via explicit connection
        conn = get_connection(path)
        repository.create_customer(
            "Acme", conn=conn
        )
        repository.create_person("Alice", conn=conn)
        repository.create_person("Bob", conn=conn)
        repository.create_project("P", 1, conn=conn)
        repository.log_time(1, 1, "2026-07-01", 7.5, conn=conn)
        conn.close()
        conn = get_connection(path)
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.close()

        # Clear caches so workers create their own thread-local connections
        _clear_caches()

        exceptions: list[Exception] = []
        from timesheet_mcp import reports

        def _worker_report(worker_idx: int, exc_holder: list) -> None:
            try:
                reports.get_monthly_report(2026, 7, "person")
                from timesheet_mcp.config import get_default_daily_hours

                get_default_daily_hours()
            except Exception as exc:
                exc_holder.append(exc)

        NUM = 8
        threads = [
            threading.Thread(target=_worker_report, args=(i, exceptions))
            for i in range(NUM)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert exceptions == [], f"Thread exceptions: {exceptions}"
