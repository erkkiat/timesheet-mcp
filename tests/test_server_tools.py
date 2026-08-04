"""End-to-end tests for server.py tool functions.

Calls the registered tool functions directly (not over stdio) with a temp
in-memory SQLite database, covering the create -> log -> report round trip.
"""

from __future__ import annotations

import sqlite3

import pytest

from timesheet_mcp.db import init_db
from timesheet_mcp import repository
from timesheet_mcp import config as config_mod
from timesheet_mcp import reports as reports_mod

# ---------------------------------------------------------------------------
# Fixture — in-memory DB wired into the thread-local storage
# ---------------------------------------------------------------------------


@pytest.fixture()
def server_conn():
    """Create an in-memory SQLite DB and wire it into the thread-local storage.

    All modules (repository, config, reports) now delegate to
    ``db.get_default_connection()`` when no explicit *conn* is passed.
    We set the thread-local ``conn`` attribute so the in-memory DB is
    returned for the current test thread.
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)

    import timesheet_mcp.db as db_mod
    _orig = getattr(db_mod._thread_local, "conn", None)
    db_mod._thread_local.conn = conn
    try:
        yield conn
    finally:
        if _orig is None:
            del db_mod._thread_local.conn
        else:
            db_mod._thread_local.conn = _orig
        conn.close()


# ---------------------------------------------------------------------------
# Helper — import the server tool functions
# ---------------------------------------------------------------------------

from timesheet_mcp.server import (
    # Customers
    create_customer,
    update_customer,
    list_customers,
    get_customer,
    # Projects
    create_project,
    update_project,
    set_project_tags,
    list_projects,
    get_project,
    # People
    create_person,
    update_person,
    list_people,
    # Time entries
    log_time,
    update_time_entry,
    delete_time_entry,
    list_time_entries,
    # Reports / reference
    get_finnish_holidays,
    get_working_days,
    get_monthly_report,
)


# ---------------------------------------------------------------------------
# End-to-end round trip
# ---------------------------------------------------------------------------


class TestRoundTrip:
    """Create → log → report end-to-end."""

    def test_full_round_trip(self, server_conn):
        """Create entities, log a time entry, and generate a report."""
        # 1. Create customer and project
        cust = create_customer("Acme Oy", "Main client")
        assert isinstance(cust, dict)
        assert cust["name"] == "Acme Oy"
        assert cust["archived"] == 0

        proj = create_project("Tempo", cust["id"], tags=["tempo"], notes="Project")
        assert isinstance(proj, dict)
        assert proj["name"] == "Tempo"
        assert proj["customer_id"] == cust["id"]
        assert "tempo" in proj["tags"]

        # 2. Create person
        person = create_person("Erkki Tapola")
        assert isinstance(person, dict)
        assert person["name"] == "Erkki Tapola"
        assert person["active"] == 1

        # 3. Log time
        entry = log_time(
            person_id=person["id"],
            project_id=proj["id"],
            entry_date="2026-07-01",
            hours=7.5,
            description="Backend work",
        )
        assert isinstance(entry, dict)
        assert entry["person_id"] == person["id"]
        assert entry["project_id"] == proj["id"]
        assert entry["hours"] == 7.5
        assert entry["entry_date"] == "2026-07-01"

        # 4. Get monthly report
        report = get_monthly_report(2026, 7, "project")
        assert report["year"] == 2026
        assert report["month"] == 7
        assert report["working_days"] == 23  # July 2026 has 23 working days
        assert report["grand_total_hours"] == 7.5
        assert len(report["groups"]) == 1
        assert report["groups"][0]["key"] == "Tempo"
        assert report["groups"][0]["total_hours"] == 7.5
        # Project groups must NOT have expected_hours or balance
        assert "expected_hours" not in report["groups"][0]
        assert "balance" not in report["groups"][0]

    def test_person_group_includes_balance(self, server_conn):
        """When group_by='person', each group row must have expected_hours and balance."""
        create_customer("Acme Oy")
        create_project("Tempo", 1)
        create_person("Erkki Tapola")
        log_time(1, 1, "2026-07-01", 7.5)

        report = get_monthly_report(2026, 7, "person")
        assert len(report["groups"]) == 1
        g = report["groups"][0]
        assert g["key"] == "Erkki Tapola"
        assert "expected_hours" in g
        assert "balance" in g
        assert g["total_hours"] == 7.5

    def test_customer_filter(self, server_conn):
        """Time entries can be filtered by customer_id."""
        create_customer("Acme")
        create_customer("Beta")
        create_project("A", 1)
        create_project("B", 2)
        create_person("P")
        log_time(1, 1, "2026-07-01", 5.0)
        log_time(1, 2, "2026-07-01", 3.0)

        entries = list_time_entries(customer_id=1)
        assert len(entries) == 1
        assert entries[0]["project_id"] == 1


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------


class TestCustomers:
    def test_create_customer(self, server_conn):
        c = create_customer("Acme Oy")
        assert isinstance(c, dict)
        assert c["name"] == "Acme Oy"
        assert c["archived"] == 0
        assert "created_at" in c
        assert "id" in c

    def test_list_customers(self, server_conn):
        create_customer("A")
        create_customer("B")
        items = list_customers()
        assert len(items) == 2
        names = {i["name"] for i in items}
        assert names == {"A", "B"}

    def test_get_customer(self, server_conn):
        create_customer("Acme")
        c = get_customer(1)
        assert c["id"] == 1
        assert c["name"] == "Acme"

    def test_update_customer(self, server_conn):
        create_customer("Old")
        c = update_customer(1, name="New")
        assert c["name"] == "New"

    def test_archive_customer(self, server_conn):
        create_customer("Acme")
        c = update_customer(1, archived=1)
        assert c["archived"] == 1
        # Inactive customers excluded by default
        assert len(list_customers()) == 0

    def test_include_archived(self, server_conn):
        create_customer("Archived")
        update_customer(1, archived=1)
        assert len(list_customers(include_archived=True)) == 1


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------


class TestProjects:
    def test_create_project(self, server_conn):
        create_customer("Acme")
        p = create_project("Tempo", 1, tags=["tag-a"])
        assert isinstance(p, dict)
        assert p["name"] == "Tempo"
        assert "tag-a" in p["tags"]

    def test_list_projects(self, server_conn):
        create_customer("Acme")
        create_project("A", 1)
        create_project("B", 1)
        items = list_projects()
        assert len(items) == 2

    def test_get_project(self, server_conn):
        create_customer("Acme")
        create_project("Tempo", 1)
        p = get_project(1)
        assert p["id"] == 1

    def test_update_project(self, server_conn):
        create_customer("Acme")
        create_project("Tempo", 1)
        p = update_project(1, name="Renamed")
        assert p["name"] == "Renamed"

    def test_set_project_tags(self, server_conn):
        create_customer("Acme")
        create_project("Tempo", 1, tags=["old"])
        p = set_project_tags(1, ["new1", "new2"])
        assert p["tags"] == ["new1", "new2"]

    def test_list_projects_filter_by_tag(self, server_conn):
        create_customer("Acme")
        create_project("A", 1, tags=["infra"])
        create_project("B", 1, tags=["web"])
        items = list_projects(tag="infra")
        assert len(items) == 1
        assert items[0]["name"] == "A"


# ---------------------------------------------------------------------------
# People
# ---------------------------------------------------------------------------


class TestPeople:
    def test_create_person(self, server_conn):
        p = create_person("Erkki")
        assert isinstance(p, dict)
        assert p["name"] == "Erkki"
        assert p["active"] == 1

    def test_list_people(self, server_conn):
        create_person("A")
        create_person("B")
        assert len(list_people()) == 2

    def test_update_person(self, server_conn):
        create_person("Old")
        p = update_person(1, name="New")
        assert p["name"] == "New"

    def test_deactivate_person(self, server_conn):
        create_person("A")
        update_person(1, active=0)
        assert len(list_people()) == 0
        assert len(list_people(active_only=False)) == 1


# ---------------------------------------------------------------------------
# Time entries
# ---------------------------------------------------------------------------


class TestTimeEntries:
    def test_log_time(self, server_conn):
        create_person("P")
        create_customer("C")
        create_project("P", 1)
        te = log_time(1, 1, "2026-07-01", 7.5, "Work")
        assert isinstance(te, dict)
        assert te["hours"] == 7.5
        assert te["entry_date"] == "2026-07-01"

    def test_update_time_entry(self, server_conn):
        create_person("P")
        create_customer("C")
        create_project("P", 1)
        log_time(1, 1, "2026-07-01", 5.0)
        te = update_time_entry(1, hours=7.5)
        assert te["hours"] == 7.5

    def test_delete_time_entry(self, server_conn):
        create_person("P")
        create_customer("C")
        create_project("P", 1)
        log_time(1, 1, "2026-07-01", 5.0)
        result = delete_time_entry(1)
        assert result == {"deleted": True, "id": 1}
        assert len(list_time_entries()) == 0

    def test_list_time_entries(self, server_conn):
        create_person("P")
        create_customer("C")
        create_project("P", 1)
        log_time(1, 1, "2026-07-01", 5.0)
        log_time(1, 1, "2026-07-02", 3.0)
        items = list_time_entries()
        assert len(items) == 2

    def test_validation_hours_too_small(self, server_conn):
        create_person("P")
        create_customer("C")
        create_project("P", 1)
        with pytest.raises(ValueError, match="hours"):
            log_time(1, 1, "2026-07-01", 0)

    def test_validation_hours_too_large(self, server_conn):
        create_person("P")
        create_customer("C")
        create_project("P", 1)
        with pytest.raises(ValueError, match="hours"):
            log_time(1, 1, "2026-07-01", 25)

    def test_validation_bad_date(self, server_conn):
        create_person("P")
        create_customer("C")
        create_project("P", 1)
        with pytest.raises(ValueError, match="entry_date"):
            log_time(1, 1, "not-a-date", 5.0)

    def test_list_by_person(self, server_conn):
        create_person("A")
        create_person("B")
        create_customer("C")
        create_project("P", 1)
        log_time(1, 1, "2026-07-01", 5.0)
        log_time(2, 1, "2026-07-01", 3.0)
        items = list_time_entries(person_id=1)
        assert len(items) == 1

    def test_list_by_date_range(self, server_conn):
        create_person("P")
        create_customer("C")
        create_project("P", 1)
        log_time(1, 1, "2026-07-01", 5.0)
        log_time(1, 1, "2026-07-15", 3.0)
        items = list_time_entries(date_from="2026-07-10", date_to="2026-07-20")
        assert len(items) == 1


# ---------------------------------------------------------------------------
# Reports / reference
# ---------------------------------------------------------------------------


class TestReports:
    def test_finnish_holidays(self):
        holidays = get_finnish_holidays(2025)
        assert isinstance(holidays, list)
        dates = {h["date"] for h in holidays}
        assert "2025-12-06" in dates  # Independence Day

    def test_working_days(self, server_conn):
        wd = get_working_days(2026, 1)
        assert wd["working_days"] == 20
        assert "expected_hours" in wd
        assert wd["expected_hours"] == pytest.approx(20 * 7.5)

    def test_monthly_report_empty(self, server_conn):
        report = get_monthly_report(2026, 1, "project")
        assert report["year"] == 2026
        assert report["working_days"] == 20
        assert report["grand_total_hours"] == 0.0
        assert report["groups"] == []

    def test_monthly_report_project_group(self, server_conn):
        create_customer("C")
        create_project("P", 1)
        create_person("P")
        log_time(1, 1, "2026-07-01", 7.5)
        report = get_monthly_report(2026, 7, "project")
        assert len(report["groups"]) == 1
        assert report["groups"][0]["key"] == "P"
        assert report["groups"][0]["total_hours"] == 7.5
        assert "expected_hours" not in report["groups"][0]
        assert "balance" not in report["groups"][0]

    def test_monthly_report_person_group_has_balance(self, server_conn):
        create_customer("C")
        create_project("P", 1)
        create_person("User")
        log_time(1, 1, "2026-07-01", 7.5)
        report = get_monthly_report(2026, 7, "person")
        assert len(report["groups"]) == 1
        g = report["groups"][0]
        assert "expected_hours" in g
        assert "balance" in g

    def test_monthly_report_invalid_group_by(self, server_conn):
        with pytest.raises(ValueError, match="group_by"):
            get_monthly_report(2026, 7, "invalid")


# ---------------------------------------------------------------------------
# Tool-call logging (verifies the wrapper is wired into registered tools)
# ---------------------------------------------------------------------------


def test_tool_call_logs_debug_record(caplog, server_conn):
    """Calling a tool function emits a DEBUG log record via the wrapper.

    This test would have caught the regression in which tool functions were
    registered without ``log_tool_call_context``, producing zero log entries
    in a running server.
    """
    import logging

    from timesheet_mcp import logging_config as lc
    from timesheet_mcp.logging_config import LOGGER_NAME
    from timesheet_mcp.server import _with_logging

    # Ensure the named logger is at DEBUG and propagates to caplog's handler.
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.DEBUG)

    wrapped = _with_logging(create_customer)
    result = wrapped("Log-Test Corp", "notes for logging")
    assert result["name"] == "Log-Test Corp"

    # Check caplog captures the log record.
    assert len(caplog.record_tuples) > 0, (
        "Expected at least one log record — the _with_logging wrapper "
        "may not be applied or log_tool_call_context may not emit DEBUG"
    )
    debug_records = [r for r in caplog.record_tuples if "Tool call" in str(r[2])]
    assert debug_records, (
        "Expected a DEBUG record with 'Tool call' — the wrapper may not "
        "log via log_tool_call_context"
    )
    assert "create_customer" in debug_records[0][2]
    assert "Log-Test Corp" in debug_records[0][2]


def test_registered_tools_are_wrapped():
    """Verify every tool registered on the MCPServer passed through _with_logging.

    The existing test pattern imports raw functions, so a tool called through
    the server goes through `_with_logging`.  This test inspects the server's
    internal ``_tool_manager`` to confirm each registered tool's ``fn`` is a
    wrapped callable (has ``__wrapped__`` from ``functools.wraps``).
    """
    from mcp.server.mcpserver import MCPServer
    from timesheet_mcp.server import app

    tools = app._tool_manager.list_tools()
    assert len(tools) == 19, f"Expected 19 tools, got {len(tools)}"
    for info in tools:
        fn = info.fn
        assert hasattr(fn, "__wrapped__"), (
            f"Tool {info.name!r}: registered fn has no __wrapped__ attr — "
            "the _with_logging decorator may not have been applied"
        )
