"""Tests for src/timesheet_mcp/models — field coverage, round-trip conversion."""

import pytest

from timesheet_mcp.models import Customer, Person, Project, TimeEntry


# ---------------------------------------------------------------------------
# Customer
# ---------------------------------------------------------------------------

class TestCustomer:
    @pytest.fixture
    def row(self):
        return {
            "id": 1,
            "name": "Acme Oy",
            "notes": "Key customer",
            "archived": 0,
            "created_at": "2026-01-01T00:00:00Z",
        }

    @pytest.fixture
    def customer(self, row):
        return Customer(
            id=row["id"],
            name=row["name"],
            notes=row["notes"],
            archived=row["archived"],
            created_at=row["created_at"],
        )

    def test_fields_match_schema(self):
        """Customer must have exactly the columns defined in PLAN.md §4."""
        assert Customer.__dataclass_fields__.keys() == {
            "id", "name", "notes", "archived", "created_at",
        }

    def test_round_trip(self, customer, row):
        result = Customer.from_row(customer.to_row())
        assert result == customer
        assert result.to_row() == row

    def test_from_row_dict(self, row):
        c = Customer.from_row(row)
        assert c.id == 1
        assert c.name == "Acme Oy"
        assert c.notes == "Key customer"
        assert c.archived == 0
        assert c.created_at == "2026-01-01T00:00:00Z"

    def test_from_row_null_notes(self):
        c = Customer.from_row({
            "id": 2, "name": "Beta", "notes": None,
            "archived": 1, "created_at": "2026-06-15T12:00:00Z",
        })
        assert c.notes is None
        assert c.archived == 1

    def test_from_row_extra_keys_ignored(self):
        c = Customer.from_row({
            "id": 1, "name": "Acme", "notes": None, "archived": 0,
            "created_at": "2026-01-01T00:00:00Z", "unknown_col": "x",
        })
        assert c.id == 1


# ---------------------------------------------------------------------------
# Project
# ---------------------------------------------------------------------------

class TestProject:
    @pytest.fixture
    def row(self):
        return {
            "id": 1,
            "customer_id": 1,
            "name": "Tempo",
            "active": 1,
            "notes": "Active project",
            "created_at": "2026-01-15T10:00:00Z",
        }

    @pytest.fixture
    def project(self, row):
        return Project(
            id=row["id"],
            customer_id=row["customer_id"],
            name=row["name"],
            active=row["active"],
            notes=row["notes"],
            created_at=row["created_at"],
        )

    def test_fields_match_schema(self):
        assert Project.__dataclass_fields__.keys() == {
            "id", "customer_id", "name", "active", "notes", "created_at",
        }

    def test_round_trip(self, project, row):
        result = Project.from_row(project.to_row())
        assert result == project
        assert result.to_row() == row

    def test_from_row(self, row):
        p = Project.from_row(row)
        assert p.customer_id == 1
        assert p.active == 1
        assert p.name == "Tempo"


# ---------------------------------------------------------------------------
# Person
# ---------------------------------------------------------------------------

class TestPerson:
    @pytest.fixture
    def row(self):
        return {
            "id": 1,
            "name": "Erkki Tapola",
            "active": 1,
            "created_at": "2026-02-01T08:00:00Z",
        }

    @pytest.fixture
    def person(self, row):
        return Person(
            id=row["id"],
            name=row["name"],
            active=row["active"],
            created_at=row["created_at"],
        )

    def test_fields_match_schema(self):
        assert Person.__dataclass_fields__.keys() == {
            "id", "name", "active", "created_at",
        }

    def test_round_trip(self, person, row):
        result = Person.from_row(person.to_row())
        assert result == person
        assert result.to_row() == row


# ---------------------------------------------------------------------------
# TimeEntry
# ---------------------------------------------------------------------------

class TestTimeEntry:
    @pytest.fixture
    def row(self):
        return {
            "id": 1,
            "person_id": 1,
            "project_id": 1,
            "entry_date": "2026-07-01",
            "hours": 7.5,
            "description": "Implemented feature X",
            "created_at": "2026-07-01T09:00:00Z",
            "updated_at": "2026-07-01T17:00:00Z",
        }

    @pytest.fixture
    def entry(self, row):
        return TimeEntry(
            id=row["id"],
            person_id=row["person_id"],
            project_id=row["project_id"],
            entry_date=row["entry_date"],
            hours=row["hours"],
            description=row["description"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def test_fields_match_schema(self):
        assert TimeEntry.__dataclass_fields__.keys() == {
            "id", "person_id", "project_id", "entry_date",
            "hours", "description", "created_at", "updated_at",
        }

    def test_round_trip(self, entry, row):
        result = TimeEntry.from_row(entry.to_row())
        assert result == entry
        assert result.to_row() == row

    def test_from_row_hour_types(self):
        """hours may come in as int or float from SQLite."""
        t = TimeEntry.from_row({
            "id": 1, "person_id": 1, "project_id": 1,
            "entry_date": "2026-07-01", "hours": 8,
            "description": None,
            "created_at": "2026-07-01T09:00:00Z",
            "updated_at": "2026-07-01T17:00:00Z",
        })
        assert isinstance(t.hours, float)
        assert t.hours == 8.0

    def test_from_row_null_description(self):
        t = TimeEntry.from_row({
            "id": 1, "person_id": 1, "project_id": 1,
            "entry_date": "2026-07-01", "hours": 1.0,
            "description": None,
            "created_at": "2026-07-01T09:00:00Z",
            "updated_at": "2026-07-01T17:00:00Z",
        })
        assert t.description is None
