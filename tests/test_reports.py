"""Tests for src/timesheet_mcp/reports — working-day math and monthly reports."""

from __future__ import annotations

import datetime
import sqlite3

import pytest

from timesheet_mcp.db import init_db
from timesheet_mcp.repository import (
    create_customer,
    create_project,
    create_person,
    log_time,
    set_project_tags,
)
from timesheet_mcp.reports import (
    get_finnish_holidays,
    get_monthly_report,
    get_working_days,
)


# ── fixture ────────────────────────────────────────────────────────────────


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    init_db(c)
    yield c
    c.close()


@pytest.fixture()
def seeded_conn(conn):
    """Create a customer, project, person and return the connection."""
    create_customer("Acme Oy", conn=conn)
    create_project("Tempo", 1, tags=["tempo"], conn=conn)
    create_person("TestUser", conn=conn)
    return conn


# ── Working-day math ──────────────────────────────────────────────────────


class TestWorkingDays2026January:
    """January 2026: 23 weekdays minus Jan 1 (New Year) and Jan 6 (Epiphany) = 20."""

    def test_working_days(self, conn):
        result = get_working_days(2026, 1, conn=conn)
        assert result["working_days"] == 20

    def test_expected_hours(self, conn):
        result = get_working_days(2026, 1, conn=conn)
        assert result["expected_hours"] == pytest.approx(20 * 7.5)


class TestWorkingDays2025June:
    """June 2025: 21 weekdays minus Jun 20 (Midsummer Eve, Friday) = 20."""

    def test_working_days(self, conn):
        result = get_working_days(2025, 6, conn=conn)
        assert result["working_days"] == 20

    def test_expected_hours(self, conn):
        result = get_working_days(2025, 6, conn=conn)
        assert result["expected_hours"] == pytest.approx(20 * 7.5)


class TestWorkingDays2025April:
    """April 2025: 22 weekdays minus Good Friday (Apr 18) and Easter Monday (Apr 21) = 20."""

    def test_working_days(self, conn):
        result = get_working_days(2025, 4, conn=conn)
        assert result["working_days"] == 20


class TestWorkingDays2025December:
    """December 2025: Christmas Eve (Dec 24), Christmas (Dec 25), St Stephen (Dec 26).

    23 weekdays minus 3 weekday holidays = 20 working days."""

    def test_working_days(self, conn):
        result = get_working_days(2025, 12, conn=conn)
        assert result["working_days"] == 20


# ── get_finnish_holidays ──────────────────────────────────────────────────


class TestGetFinnishHolidays:
    def test_dec6_independence_day(self):
        """Independence Day is on Dec 6 (using date, not English name)."""
        holidays = get_finnish_holidays(2025)
        by_date = {h["date"]: h["name"] for h in holidays}
        assert "2025-12-06" in by_date

    def test_midsummer_included(self):
        holidays = get_finnish_holidays(2025)
        dates = {h["date"] for h in holidays}
        assert "2025-06-20" in dates  # Midsummer Eve
        assert "2025-06-21" in dates  # Midsummer Day

    def test_yearly_cache_independent(self):
        h1 = get_finnish_holidays(2025)
        h2 = get_finnish_holidays(2026)
        dates_2025 = {h["date"] for h in h1}
        dates_2026 = {h["date"] for h in h2}
        # Easter dates differ (moveable feast)
        assert dates_2025 != dates_2026


# ── Monthly report - empty month ─────────────────────────────────────────


class TestMonthlyReportEmpty:
    """Report with no entries should still compute working days / expected hours."""

    def test_report_structure(self, conn):
        report = get_monthly_report(
            2026, 1, "project", conn=conn
        )
        assert report["year"] == 2026
        assert report["month"] == 1
        assert report["working_days"] == 20
        assert report["groups"] == []
        assert report["grand_total_hours"] == 0.0

    def test_expected_hours_field_present(self, conn):
        report = get_monthly_report(
            2026, 1, "project", conn=conn
        )
        assert "expected_hours" in report


# ── group_by = "project" ─────────────────────────────────────────────────


class TestReportGroupByProject:
    def test_single_project(self, seeded_conn):
        log_time(1, 1, "2026-07-01", 7.5, "Dev", conn=seeded_conn)
        log_time(1, 1, "2026-07-02", 5.0, "Bugfix", conn=seeded_conn)

        report = get_monthly_report(
            2026, 7, "project", conn=seeded_conn
        )
        assert len(report["groups"]) == 1
        assert report["groups"][0]["key"] == "Tempo"
        assert report["groups"][0]["total_hours"] == 12.5
        assert report["grand_total_hours"] == 12.5
        # No balance for project group
        assert "balance" not in report["groups"][0]
        assert "expected_hours" not in report["groups"][0]

    def test_two_projects(self, seeded_conn):
        create_customer("Beta Oy", conn=seeded_conn)
        create_project("Alpha", 2, conn=seeded_conn)
        log_time(1, 1, "2026-07-01", 7.0, conn=seeded_conn)
        log_time(1, 2, "2026-07-01", 3.0, conn=seeded_conn)

        report = get_monthly_report(
            2026, 7, "project", conn=seeded_conn
        )
        assert len(report["groups"]) == 2
        keys = {g["key"] for g in report["groups"]}
        assert "Tempo" in keys
        assert "Alpha" in keys
        assert report["grand_total_hours"] == 10.0


# ── group_by = "customer" ────────────────────────────────────────────────


class TestReportGroupByCustomer:
    def test_group_key_is_customer_name(self, seeded_conn):
        create_customer("Beta Oy", conn=seeded_conn)
        create_project("Other", 2, conn=seeded_conn)
        log_time(1, 1, "2026-07-01", 7.0, conn=seeded_conn)
        log_time(1, 2, "2026-07-01", 3.0, conn=seeded_conn)

        report = get_monthly_report(
            2026, 7, "customer", conn=seeded_conn
        )
        assert len(report["groups"]) == 2
        assert report["grand_total_hours"] == 10.0
        for g in report["groups"]:
            assert "balance" not in g
            assert "expected_hours" not in g


# ── group_by = "tag" ─────────────────────────────────────────────────────


class TestReportGroupByTag:
    def test_projects_with_multiple_tags(self, seeded_conn):
        set_project_tags(1, ["tempo", "infra"], conn=seeded_conn)
        log_time(1, 1, "2026-07-01", 7.0, conn=seeded_conn)

        report = get_monthly_report(
            2026, 7, "tag", conn=seeded_conn
        )
        # The project appears under each of its tags.
        assert len(report["groups"]) == 2
        tags = {g["key"] for g in report["groups"]}
        assert "tempo" in tags
        assert "infra" in tags

    def test_tag_filtering_via_tag_parameter(self, seeded_conn):
        set_project_tags(1, ["tempo", "infra"], conn=seeded_conn)
        log_time(1, 1, "2026-07-01", 7.0, conn=seeded_conn)

        # Filtering by tag="infra" but grouping by "project" should
        # only return entries belonging to projects that have that tag.
        report = get_monthly_report(
            2026, 7, "project", tag="infra", conn=seeded_conn
        )
        assert len(report["groups"]) == 1
        assert report["groups"][0]["key"] == "Tempo"


# ── group_by = "person" ──────────────────────────────────────────────────


class TestReportGroupByPerson:
    def test_balance_field_present(self, seeded_conn):
        log_time(1, 1, "2026-07-01", 7.5, conn=seeded_conn)

        report = get_monthly_report(
            2026, 7, "person", conn=seeded_conn
        )
        assert len(report["groups"]) == 1
        g = report["groups"][0]
        assert "expected_hours" in g
        assert "balance" in g
        assert g["key"] == "1"  # person_id as string
        assert g["total_hours"] == 7.5
        # expected_hours ≈ 21 working days * 7.5 daily = 157.5 (July 2026)

    def test_two_people(self, seeded_conn):
        create_person("Anna", conn=seeded_conn)
        log_time(1, 1, "2026-07-01", 7.5, conn=seeded_conn)
        log_time(2, 1, "2026-07-01", 5.0, conn=seeded_conn)

        report = get_monthly_report(
            2026, 7, "person", conn=seeded_conn
        )
        assert len(report["groups"]) == 2
        for g in report["groups"]:
            assert "expected_hours" in g
            assert "balance" in g

    def test_no_balance_for_other_group_by(self, seeded_conn):
        """Balance must NOT appear for non-person group_by values."""
        log_time(1, 1, "2026-07-01", 7.5, conn=seeded_conn)

        for gb in ("project", "customer", "tag", "day"):
            report = get_monthly_report(
                2026, 7, gb, conn=seeded_conn
            )
            for g in report["groups"]:
                assert "balance" not in g, (
                    f"group_by={gb!r} group must not have 'balance'"
                )
                assert "expected_hours" not in g, (
                    f"group_by={gb!r} group must not have 'expected_hours'"
                )


# ── group_by = "day" ─────────────────────────────────────────────────────


class TestReportGroupByDay:
    def test_groups_by_date(self, seeded_conn):
        log_time(1, 1, "2026-07-01", 7.5, conn=seeded_conn)
        log_time(1, 1, "2026-07-01", 3.0, "extra", conn=seeded_conn)
        log_time(1, 1, "2026-07-02", 5.0, conn=seeded_conn)

        report = get_monthly_report(
            2026, 7, "day", conn=seeded_conn
        )
        assert len(report["groups"]) == 2
        day_hours = {g["key"]: g["total_hours"] for g in report["groups"]}
        assert day_hours["2026-07-01"] == 10.5
        assert day_hours["2026-07-02"] == 5.0


# ── Filters ──────────────────────────────────────────────────────────────


class TestFilters:
    def test_filter_by_project_id(self, seeded_conn):
        create_customer("Beta Oy", conn=seeded_conn)
        create_project("Alpha", 2, conn=seeded_conn)
        log_time(1, 1, "2026-07-01", 7.0, conn=seeded_conn)
        log_time(1, 2, "2026-07-01", 3.0, conn=seeded_conn)

        report = get_monthly_report(
            2026, 7, "project", project_id=1, conn=seeded_conn
        )
        assert report["grand_total_hours"] == 7.0
        assert len(report["groups"]) == 1
        assert report["groups"][0]["key"] == "Tempo"

    def test_filter_by_person_id(self, seeded_conn):
        create_person("Anna", conn=seeded_conn)
        log_time(1, 1, "2026-07-01", 7.0, conn=seeded_conn)
        log_time(2, 1, "2026-07-01", 3.0, conn=seeded_conn)

        report = get_monthly_report(
            2026, 7, "person", person_id=1, conn=seeded_conn
        )
        assert report["grand_total_hours"] == 7.0

    def test_filter_by_customer_id(self, seeded_conn):
        create_customer("Beta Oy", conn=seeded_conn)
        create_project("Other", 2, conn=seeded_conn)
        log_time(1, 1, "2026-07-01", 7.0, conn=seeded_conn)
        log_time(1, 2, "2026-07-01", 3.0, conn=seeded_conn)

        report = get_monthly_report(
            2026, 7, "project", customer_id=2, conn=seeded_conn
        )
        assert report["grand_total_hours"] == 3.0

    def test_filter_by_tag(self, seeded_conn):
        set_project_tags(1, ["tempo", "infra"], conn=seeded_conn)
        log_time(1, 1, "2026-07-01", 7.0, conn=seeded_conn)


# ── Invalid group_by ─────────────────────────────────────────────────────


class TestInvalidGroupBy:
    def test_raises_on_unknown_group_by(self, conn):
        with pytest.raises(ValueError, match="group_by"):
            get_monthly_report(2026, 7, "invalid", conn=conn)
