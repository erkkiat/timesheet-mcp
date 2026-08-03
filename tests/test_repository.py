"""Tests for src/timesheet_mcp/repository — CRUD + validation + soft-delete."""

from __future__ import annotations

import sqlite3

import pytest

from timesheet_mcp.db import get_connection, init_db
from timesheet_mcp.models import Customer, Person, Project, TimeEntry
from timesheet_mcp.repository import (
    create_customer,
    update_customer,
    list_customers,
    get_customer,
    create_project,
    update_project,
    set_project_tags,
    list_projects,
    get_project,
    create_person,
    update_person,
    list_people,
    log_time,
    update_time_entry,
    delete_time_entry,
    list_time_entries,
)


# ── fixture ────────────────────────────────────────────────────────────────


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    init_db(c)
    yield c
    c.close()


# ── Customers ──────────────────────────────────────────────────────────────


class TestCreateCustomer:
    def test_returns_customer_with_id(self, conn):
        c = create_customer("Acme Oy", "Key client", conn=conn)
        assert isinstance(c, Customer)
        assert c.id == 1
        assert c.name == "Acme Oy"
        assert c.notes == "Key client"
        assert c.archived == 0
        assert c.created_at

    def test_default_notes_is_none(self, conn):
        c = create_customer("Beta", conn=conn)
        assert c.notes is None
        assert c.archived == 0

    def test_empty_name_raises(self, conn):
        with pytest.raises(ValueError, match="name.*empty"):
            create_customer("", conn=conn)


class TestGetCustomer:
    def test_found(self, conn):
        create_customer("Acme", conn=conn)
        c = get_customer(1, conn=conn)
        assert c.id == 1
        assert c.name == "Acme"

    def test_missing_raises(self, conn):
        with pytest.raises(ValueError, match="not found"):
            get_customer(999, conn=conn)


class TestListCustomers:
    def test_lists_active_only_by_default(self, conn):
        create_customer("Alpha", conn=conn)
        create_customer("Beta", conn=conn)
        results = list_customers(conn=conn)
        assert len(results) == 2

    def test_archived_excluded_by_default(self, conn):
        create_customer("Alpha", conn=conn)
        update_customer(1, archived=1, conn=conn)
        results = list_customers(conn=conn)
        assert len(results) == 0

    def test_include_archived_shows_all(self, conn):
        create_customer("Alpha", conn=conn)
        create_customer("Beta", conn=conn)
        update_customer(1, archived=1, conn=conn)
        results = list_customers(include_archived=True, conn=conn)
        assert len(results) == 2


class TestUpdateCustomer:
    def test_updates_name(self, conn):
        create_customer("Old Name", conn=conn)
        c = update_customer(1, name="New Name", conn=conn)
        assert c.name == "New Name"

    def test_updates_notes(self, conn):
        create_customer("Acme", notes="v1", conn=conn)
        c = update_customer(1, notes="v2", conn=conn)
        assert c.notes == "v2"

    def test_archives_customer(self, conn):
        create_customer("Acme", conn=conn)
        c = update_customer(1, archived=1, conn=conn)
        assert c.archived == 1

    def test_invalid_archived_raises(self, conn):
        create_customer("Acme", conn=conn)
        with pytest.raises(ValueError, match="archived"):
            update_customer(1, archived=2, conn=conn)

    def test_soft_delete_not_physical(self, conn):
        create_customer("Acme", conn=conn)
        update_customer(1, archived=1, conn=conn)
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM customers WHERE id = 1"
        ).fetchone()["c"]
        assert row == 1  # still exists, just archived

    def test_updates_partial_fields(self, conn):
        create_customer("Old", notes="v1", conn=conn)
        c = update_customer(1, name="New", conn=conn)
        assert c.name == "New"
        assert c.notes == "v1"  # unchanged


# ── Projects ───────────────────────────────────────────────────────────────


class TestCreateProject:
    def test_returns_project(self, conn):
        create_customer("Acme", conn=conn)
        p = create_project("Tempo", 1, conn=conn)
        assert isinstance(p, Project)
        assert p.id == 1
        assert p.name == "Tempo"
        assert p.customer_id == 1
        assert p.active == 1

    def test_stores_tags(self, conn):
        create_customer("Acme", conn=conn)
        p = create_project("Tempo", 1, tags=["tempo", "infra"], conn=conn)
        assert "tempo" in p._tags
        assert "infra" in p._tags

    def test_no_tags_by_default(self, conn):
        create_customer("Acme", conn=conn)
        p = create_project("Tempo", 1, conn=conn)
        assert p._tags == []

    def test_customer_not_found(self, conn):
        with pytest.raises(ValueError, match="Customer.*not found"):
            create_project("X", 999, conn=conn)

    def test_archived_customer_rejected(self, conn):
        create_customer("Acme", conn=conn)
        update_customer(1, archived=1, conn=conn)
        with pytest.raises(ValueError, match="archived"):
            create_project("X", 1, conn=conn)

    def test_empty_name_raises(self, conn):
        create_customer("Acme", conn=conn)
        with pytest.raises(ValueError, match="name.*empty"):
            create_project("", 1, conn=conn)


class TestGetProject:
    def test_found_with_tags(self, conn):
        create_customer("Acme", conn=conn)
        create_project("Tempo", 1, tags=["infra"], conn=conn)
        p = get_project(1, conn=conn)
        assert p.name == "Tempo"
        assert p._tags == ["infra"]

    def test_missing_raises(self, conn):
        with pytest.raises(ValueError, match="not found"):
            get_project(999, conn=conn)


class TestUpdateProject:
    def test_updates_name(self, conn):
        create_customer("Acme", conn=conn)
        create_project("Tempo", 1, conn=conn)
        p = update_project(1, name="Rebranded", conn=conn)
        assert p.name == "Rebranded"

    def test_deactivates(self, conn):
        create_customer("Acme", conn=conn)
        create_project("Tempo", 1, conn=conn)
        p = update_project(1, active=0, conn=conn)
        assert p.active == 0

    def test_invalid_active_raises(self, conn):
        create_customer("Acme", conn=conn)
        create_project("Tempo", 1, conn=conn)
        with pytest.raises(ValueError, match="active"):
            update_project(1, active=2, conn=conn)


class TestSetProjectTags:
    def test_replaces_tags(self, conn):
        create_customer("Acme", conn=conn)
        create_project("Tempo", 1, tags=["infra"], conn=conn)
        p = set_project_tags(1, ["new-tag"], conn=conn)
        assert p._tags == ["new-tag"]

    def test_clears_tags(self, conn):
        create_customer("Acme", conn=conn)
        create_project("Tempo", 1, tags=["infra"], conn=conn)
        p = set_project_tags(1, [], conn=conn)
        assert p._tags == []

    def test_missing_project_raises(self, conn):
        create_customer("Acme", conn=conn)
        with pytest.raises(ValueError, match="not found"):
            set_project_tags(999, ["x"], conn=conn)


class TestListProjects:
    def test_list_all(self, conn):
        create_customer("Acme", conn=conn)
        create_project("A", 1, conn=conn)
        create_project("B", 1, conn=conn)
        result = list_projects(conn=conn)
        assert len(result) == 2

    def test_filter_by_customer(self, conn):
        create_customer("Acme", conn=conn)
        create_customer("Beta", conn=conn)
        create_project("A", 1, conn=conn)
        create_project("B", 2, conn=conn)
        result = list_projects(customer_id=1, conn=conn)
        assert len(result) == 1
        assert result[0].name == "A"

    def test_filter_by_tag(self, conn):
        create_customer("Acme", conn=conn)
        create_project("A", 1, tags=["infra"], conn=conn)
        create_project("B", 1, tags=["web"], conn=conn)
        result = list_projects(tag="infra", conn=conn)
        assert len(result) == 1
        assert result[0].name == "A"

    def test_active_only_excludes_inactive(self, conn):
        create_customer("Acme", conn=conn)
        create_project("Active", 1, conn=conn)
        create_project("Inactive", 1, conn=conn)
        update_project(2, active=0, conn=conn)
        result = list_projects(conn=conn)
        assert len(result) == 1
        assert result[0].name == "Active"


# ── People ─────────────────────────────────────────────────────────────────


class TestCreatePerson:
    def test_returns_person(self, conn):
        p = create_person("Erkki Tapola", conn=conn)
        assert isinstance(p, Person)
        assert p.id == 1
        assert p.name == "Erkki Tapola"
        assert p.active == 1

    def test_empty_name_raises(self, conn):
        with pytest.raises(ValueError, match="name.*empty"):
            create_person("", conn=conn)


class TestUpdatePerson:
    def test_updates_name(self, conn):
        create_person("Old", conn=conn)
        p = update_person(1, name="New", conn=conn)
        assert p.name == "New"

    def test_deactivates(self, conn):
        create_person("Erkki", conn=conn)
        p = update_person(1, active=0, conn=conn)
        assert p.active == 0

    def test_invalid_active_raises(self, conn):
        create_person("Erkki", conn=conn)
        with pytest.raises(ValueError, match="active"):
            update_person(1, active=5, conn=conn)


class TestListPeople:
    def test_active_only(self, conn):
        create_person("Active", conn=conn)
        create_person("Inactive", conn=conn)
        update_person(2, active=0, conn=conn)
        result = list_people(conn=conn)
        assert len(result) == 1
        assert result[0].name == "Active"

    def test_all_when_requested(self, conn):
        create_person("A", conn=conn)
        create_person("B", conn=conn)
        update_person(2, active=0, conn=conn)
        result = list_people(active_only=False, conn=conn)
        assert len(result) == 2


# ── Time Entries ───────────────────────────────────────────────────────────


class TestLogTime:
    def test_creates_entry(self, conn):
        create_person("Erkki", conn=conn)
        create_customer("Acme", conn=conn)
        create_project("Tempo", 1, conn=conn)
        te = log_time(1, 1, "2026-07-01", 7.5, "Dev work", conn=conn)
        assert isinstance(te, TimeEntry)
        assert te.entry_date == "2026-07-01"
        assert te.hours == 7.5
        assert te.description == "Dev work"

    def test_hours_validation_too_small(self, conn):
        create_person("Erkki", conn=conn)
        create_customer("Acme", conn=conn)
        create_project("Tempo", 1, conn=conn)
        with pytest.raises(ValueError, match="hours"):
            log_time(1, 1, "2026-07-01", 0, conn=conn)

    def test_hours_validation_too_large(self, conn):
        create_person("Erkki", conn=conn)
        create_customer("Acme", conn=conn)
        create_project("Tempo", 1, conn=conn)
        with pytest.raises(ValueError, match="hours"):
            log_time(1, 1, "2026-07-01", 25, conn=conn)

    def test_date_validation_bad(self, conn):
        create_person("Erkki", conn=conn)
        create_customer("Acme", conn=conn)
        create_project("Tempo", 1, conn=conn)
        with pytest.raises(ValueError, match="entry_date"):
            log_time(1, 1, "not-a-date", 5.0, conn=conn)

    def test_person_not_found(self, conn):
        create_customer("Acme", conn=conn)
        create_project("Tempo", 1, conn=conn)
        with pytest.raises(ValueError, match="Person.*not found"):
            log_time(999, 1, "2026-07-01", 5.0, conn=conn)

    def test_project_not_found(self, conn):
        create_person("Erkki", conn=conn)
        create_customer("Acme", conn=conn)
        with pytest.raises(ValueError, match="Project.*not found"):
            log_time(1, 999, "2026-07-01", 5.0, conn=conn)

    def test_boundary_hours_24_accepted(self, conn):
        create_person("Erkki", conn=conn)
        create_customer("Acme", conn=conn)
        create_project("Tempo", 1, conn=conn)
        te = log_time(1, 1, "2026-07-01", 24, conn=conn)
        assert te.hours == 24.0

    def test_fractional_hours_accepted(self, conn):
        create_person("Erkki", conn=conn)
        create_customer("Acme", conn=conn)
        create_project("Tempo", 1, conn=conn)
        te = log_time(1, 1, "2026-07-01", 0.5, conn=conn)
        assert te.hours == 0.5


class TestUpdateTimeEntry:
    def test_updates_hours(self, conn):
        create_person("Erkki", conn=conn)
        create_customer("Acme", conn=conn)
        create_project("Tempo", 1, conn=conn)
        log_time(1, 1, "2026-07-01", 5.0, conn=conn)
        te = update_time_entry(1, hours=7.5, conn=conn)
        assert te.hours == 7.5

    def test_updates_date(self, conn):
        create_person("Erkki", conn=conn)
        create_customer("Acme", conn=conn)
        create_project("Tempo", 1, conn=conn)
        log_time(1, 1, "2026-07-01", 5.0, conn=conn)
        te = update_time_entry(1, entry_date="2026-07-05", conn=conn)
        assert te.entry_date == "2026-07-05"

    def test_updates_description(self, conn):
        create_person("Erkki", conn=conn)
        create_customer("Acme", conn=conn)
        create_project("Tempo", 1, conn=conn)
        log_time(1, 1, "2026-07-01", 5.0, "old", conn=conn)
        te = update_time_entry(1, description="new", conn=conn)
        assert te.description == "new"

    def test_invalid_hours_rejected(self, conn):
        create_person("Erkki", conn=conn)
        create_customer("Acme", conn=conn)
        create_project("Tempo", 1, conn=conn)
        log_time(1, 1, "2026-07-01", 5.0, conn=conn)
        with pytest.raises(ValueError, match="hours"):
            update_time_entry(1, hours=-1, conn=conn)

    def test_missing_entry_raises(self, conn):
        with pytest.raises(ValueError, match="not found"):
            update_time_entry(999, hours=5.0, conn=conn)


class TestDeleteTimeEntry:
    def test_deletes(self, conn):
        create_person("Erkki", conn=conn)
        create_customer("Acme", conn=conn)
        create_project("Tempo", 1, conn=conn)
        log_time(1, 1, "2026-07-01", 5.0, conn=conn)
        result = delete_time_entry(1, conn=conn)
        assert result == {"deleted": True, "id": 1}

    def test_nothing_stored(self, conn):
        create_person("Erkki", conn=conn)
        create_customer("Acme", conn=conn)
        create_project("Tempo", 1, conn=conn)
        log_time(1, 1, "2026-07-01", 5.0, conn=conn)
        delete_time_entry(1, conn=conn)
        rows = conn.execute("SELECT COUNT(*) AS c FROM time_entries").fetchone()["c"]
        assert rows == 0

    def test_missing_raises(self, conn):
        with pytest.raises(ValueError, match="not found"):
            delete_time_entry(999, conn=conn)


class TestListTimeEntries:
    def test_empty_when_no_data(self, conn):
        assert list_time_entries(conn=conn) == []

    def test_lists_all(self, conn):
        create_person("Erkki", conn=conn)
        create_customer("Acme", conn=conn)
        create_project("Tempo", 1, conn=conn)
        log_time(1, 1, "2026-07-01", 5.0, conn=conn)
        log_time(1, 1, "2026-07-02", 3.0, conn=conn)
        entries = list_time_entries(conn=conn)
        assert len(entries) == 2

    def test_filter_by_person(self, conn):
        create_person("A", conn=conn)
        create_person("B", conn=conn)
        create_customer("Acme", conn=conn)
        create_project("P", 1, conn=conn)
        log_time(1, 1, "2026-07-01", 5.0, conn=conn)
        log_time(2, 1, "2026-07-01", 3.0, conn=conn)
        results = list_time_entries(person_id=1, conn=conn)
        assert len(results) == 1

    def test_filter_by_project(self, conn):
        create_person("Erkki", conn=conn)
        create_customer("Acme", conn=conn)
        create_project("A", 1, conn=conn)
        create_project("B", 1, conn=conn)
        log_time(1, 1, "2026-07-01", 5.0, conn=conn)
        log_time(1, 2, "2026-07-01", 3.0, conn=conn)
        results = list_time_entries(project_id=1, conn=conn)
        assert len(results) == 1

    def test_filter_by_customer_via_project(self, conn):
        create_person("Erkki", conn=conn)
        create_customer("Acme", conn=conn)
        create_customer("Beta", conn=conn)
        create_project("A", 1, conn=conn)
        create_project("B", 2, conn=conn)
        log_time(1, 1, "2026-07-01", 5.0, conn=conn)
        log_time(1, 2, "2026-07-01", 3.0, conn=conn)
        results = list_time_entries(customer_id=1, conn=conn)
        assert len(results) == 1

    def test_filter_by_tag(self, conn):
        create_person("Erkki", conn=conn)
        create_customer("Acme", conn=conn)
        create_project("Frontend", 1, tags=["infra"], conn=conn)
        create_project("Backend", 1, tags=["api"], conn=conn)
        log_time(1, 1, "2026-07-01", 5.0, conn=conn)
        log_time(1, 2, "2026-07-01", 3.0, conn=conn)
        results = list_time_entries(tag="infra", conn=conn)
        assert len(results) == 1
        assert results[0].project_id == 1

    def test_filter_by_date_range(self, conn):
        create_person("Erkki", conn=conn)
        create_customer("Acme", conn=conn)
        create_project("Tempo", 1, conn=conn)
        log_time(1, 1, "2026-07-01", 5.0, conn=conn)
        log_time(1, 1, "2026-07-15", 3.0, conn=conn)
        log_time(1, 1, "2026-07-31", 2.0, conn=conn)
        results = list_time_entries(
            date_from="2026-07-10", date_to="2026-07-20", conn=conn
        )
        assert len(results) == 1
        assert results[0].entry_date == "2026-07-15"

    def test_excludes_archived_customers(self, conn):
        create_person("Erkki", conn=conn)
        create_customer("Acme", conn=conn)
        create_project("Tempo", 1, conn=conn)
        log_time(1, 1, "2026-07-01", 5.0, conn=conn)
        update_customer(1, archived=1, conn=conn)
        results = list_time_entries(conn=conn)
        assert len(results) == 0

    def test_excludes_inactive_projects(self, conn):
        create_person("Erkki", conn=conn)
        create_customer("Acme", conn=conn)
        create_project("Tempo", 1, conn=conn)
        log_time(1, 1, "2026-07-01", 5.0, conn=conn)
        update_project(1, active=0, conn=conn)
        results = list_time_entries(conn=conn)
        assert len(results) == 0
