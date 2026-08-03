"""Dataclasses matching the SQLite schema defined in PLAN.md §4."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True, frozen=True)
class Customer:
    """Row for the ``customers`` table."""
    id: int
    name: str
    notes: str | None
    archived: int
    created_at: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Customer:
        """Build a *Customer* from a dict / *sqlite3.Row*.

        Accepted keys: *id*, *name*, *notes*, *archived*, *created_at*.
        Extra keys are silently ignored.
        """
        return cls(
            id=int(row["id"]),
            name=str(row["name"]),
            notes=row.get("notes"),
            archived=int(row["archived"]),
            created_at=str(row["created_at"]),
        )

    def to_row(self) -> dict[str, Any]:
        """Return this *Customer* as a row dict (inverse of :py:meth:`from_row`)."""
        return {
            "id": self.id,
            "name": self.name,
            "notes": self.notes,
            "archived": self.archived,
            "created_at": self.created_at,
        }


@dataclass(slots=True, frozen=True)
class Project:
    """Row for the ``projects`` table."""
    id: int
    customer_id: int
    name: str
    active: int
    notes: str | None
    created_at: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Project:
        """Build a *Project* from a dict / *sqlite3.Row*."""
        return cls(
            id=int(row["id"]),
            customer_id=int(row["customer_id"]),
            name=str(row["name"]),
            active=int(row["active"]),
            notes=row.get("notes"),
            created_at=str(row["created_at"]),
        )

    def to_row(self) -> dict[str, Any]:
        """Return this *Project* as a row dict."""
        return {
            "id": self.id,
            "customer_id": self.customer_id,
            "name": self.name,
            "active": self.active,
            "notes": self.notes,
            "created_at": self.created_at,
        }


@dataclass(slots=True, frozen=True)
class Person:
    """Row for the ``people`` table."""
    id: int
    name: str
    active: int
    created_at: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Person:
        """Build a *Person* from a dict / *sqlite3.Row*."""
        return cls(
            id=int(row["id"]),
            name=str(row["name"]),
            active=int(row["active"]),
            created_at=str(row["created_at"]),
        )

    def to_row(self) -> dict[str, Any]:
        """Return this *Person* as a row dict."""
        return {
            "id": self.id,
            "name": self.name,
            "active": self.active,
            "created_at": self.created_at,
        }


@dataclass(slots=True, frozen=True)
class TimeEntry:
    """Row for the ``time_entries`` table."""
    id: int
    person_id: int
    project_id: int
    entry_date: str
    hours: float
    description: str | None
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> TimeEntry:
        """Build a *TimeEntry* from a dict / *sqlite3.Row*."""
        return cls(
            id=int(row["id"]),
            person_id=int(row["person_id"]),
            project_id=int(row["project_id"]),
            entry_date=str(row["entry_date"]),
            hours=float(row["hours"]),
            description=row.get("description"),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def to_row(self) -> dict[str, Any]:
        """Return this *TimeEntry* as a row dict."""
        return {
            "id": self.id,
            "person_id": self.person_id,
            "project_id": self.project_id,
            "entry_date": self.entry_date,
            "hours": self.hours,
            "description": self.description,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
