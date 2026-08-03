"""CRUD data-access layer over the timesheet schema.

All functions accept an optional ``conn`` parameter for testability.
When ``conn`` is omitted the module-level default connection (``data/
timesheet.db``) is used.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from typing import Any

from .models import Customer, Person, Project, TimeEntry


def _now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── helpers ────────────────────────────────────────────────────────────────


def _validate_hours(hours: Any) -> float:
    """Validate hours and return a float value."""
    try:
        h = float(hours)
    except (TypeError, ValueError):
        raise ValueError(f"hours must be a number, got {type(hours).__name__}")
    if h <= 0 or h > 24:
        raise ValueError(f"hours must be > 0 and <= 24, got {h}")
    return h


def _validate_date(entry_date: Any) -> str:
    """Validate entry_date and return 'YYYY-MM-DD' string."""
    if isinstance(entry_date, date):
        return entry_date.isoformat()
    if isinstance(entry_date, str):
        try:
            parsed = date.fromisoformat(entry_date)
        except (ValueError, TypeError):
            raise ValueError(
                f"entry_date must be a valid ISO date (YYYY-MM-DD), got {entry_date!r}"
            )
        return parsed.isoformat()
    raise ValueError(
        f"entry_date must be a string or datetime.date, got {type(entry_date).__name__}"
    )


def _ensure_row(result: Any, entity: str, id_value: Any) -> dict[str, Any]:
    """Raise ValueError when an ORM-like entity is not found."""
    if result is None:
        raise ValueError(f"{entity} with id={id_value} not found")
    if isinstance(result, dict):
        return result
    return dict(result)


def _to_dict(row: Any) -> dict[str, Any]:
    """Convert a sqlite3.Row (or already-a-dict) to a plain dict."""
    if isinstance(row, dict):
        return row
    if row is None:
        return None
    return dict(row)


def _validate_non_empty(value: Any, field_name: str) -> None:
    if not value or not str(value).strip():
        raise ValueError(f"{field_name} must not be empty")


# ── connection management ─────────────────────────────────────────────────

_default_conn: sqlite3.Connection | None = None


def _acquire(
    conn: sqlite3.Connection | None,
) -> tuple[sqlite3.Connection, bool]:
    """Return (conn, owned).  owned=True means the caller must not close *conn*."""
    if conn is not None:
        return conn, False
    global _default_conn
    if _default_conn is None:
        from .db import get_connection, init_db

        _default_conn = get_connection()
        init_db(_default_conn)
    return _default_conn, True


# ── Customers ──────────────────────────────────────────────────────────────


def create_customer(
    name: str,
    notes: str | None = None,
    *,
    conn: sqlite3.Connection | None = None,
) -> Customer:
    __conn, _ = _acquire(conn)
    try:
        _validate_non_empty(name, "name")
        now = _now_ts()
        cur = __conn.execute(
            "INSERT INTO customers (name, notes, archived, created_at) VALUES (?, ?, 0, ?)",
            (name, notes, now),
        )
        __conn.commit()
        return Customer(
            id=cur.lastrowid,
            name=name,
            notes=notes,
            archived=0,
            created_at=now,
        )
    finally:
        pass


def update_customer(
    customer_id: int,
    name: str | None = None,
    notes: str | None = None,
    archived: int | None = None,
    *,
    conn: sqlite3.Connection | None = None,
) -> Customer:
    __conn, _ = _acquire(conn)
    try:
        row = _ensure_row(
            __conn.execute(
                "SELECT id, name, notes, archived, created_at "
                "FROM customers WHERE id = ?",
                (customer_id,),
            ).fetchone(),
            "Customer",
            customer_id,
        )
        parts: list[str] = []
        vals: list[Any] = []
        if name is not None:
            _validate_non_empty(name, "name")
            parts.append("name = ?")
            vals.append(name)
        if notes is not None:
            parts.append("notes = ?")
            vals.append(notes)
        if archived is not None:
            if archived not in (0, 1):
                raise ValueError(f"archived must be 0 or 1, got {archived}")
            parts.append("archived = ?")
            vals.append(archived)

        if parts:
            vals.append(customer_id)
            __conn.execute(
                f"UPDATE customers SET {', '.join(parts)} WHERE id = ?",
                vals,
            )
            __conn.commit()

        row = _ensure_row(
            __conn.execute(
                "SELECT id, name, notes, archived, created_at "
                "FROM customers WHERE id = ?",
                (customer_id,),
            ).fetchone(),
            "Customer",
            customer_id,
        )
        return Customer.from_row(row)
    finally:
        pass


def list_customers(
    include_archived: bool = False,
    *,
    conn: sqlite3.Connection | None = None,
) -> list[Customer]:
    __conn, _ = _acquire(conn)
    try:
        if include_archived:
            cursor = __conn.execute(
                "SELECT id, name, notes, archived, created_at "
                "FROM customers ORDER BY name"
            )
        else:
            cursor = __conn.execute(
                "SELECT id, name, notes, archived, created_at "
                "FROM customers WHERE archived = 0 ORDER BY name"
            )
        return [Customer.from_row(dict(r)) for r in cursor.fetchall()]
    finally:
        pass


def get_customer(
    customer_id: int,
    *,
    conn: sqlite3.Connection | None = None,
) -> Customer:
    __conn, _ = _acquire(conn)
    try:
        return Customer.from_row(
            _ensure_row(
                __conn.execute(
                    "SELECT id, name, notes, archived, created_at "
                    "FROM customers WHERE id = ?",
                    (customer_id,),
                ).fetchone(),
                "Customer",
                customer_id,
            )
        )
    finally:
        pass


# ── Projects ───────────────────────────────────────────────────────────────


def _collect_tags(
    conn: sqlite3.Connection, project_id: int
) -> list[str]:
    rows = conn.execute(
        "SELECT tag FROM project_tags WHERE project_id = ? ORDER BY tag",
        (project_id,),
    ).fetchall()
    return [r["tag"] for r in rows]


class ProjectWithTags(Project):
    """A mutable Project subclass that carries a ``tags`` attribute."""

    __slots__ = ("_tags",)
    _tags: list[str]

    def __init__(self, __obj: Project) -> None:
        # Re-create the frozen dataclass fields
        super().__init__(
            id=__obj.id,
            customer_id=__obj.customer_id,
            name=__obj.name,
            active=__obj.active,
            notes=__obj.notes,
            created_at=__obj.created_at,
        )


def _build_project_row(
    conn: sqlite3.Connection,
    row: dict[str, Any],
) -> dict[str, Any]:
    """Build a Project model and attach a ``tags`` field to the row dict."""
    p = Project.from_row(row)
    tags = _collect_tags(conn, p.id)
    return {
        "id": p.id,
        "customer_id": p.customer_id,
        "name": p.name,
        "active": p.active,
        "notes": p.notes,
        "created_at": p.created_at,
        "tags": tags,
    }


def create_project(
    name: str,
    customer_id: int,
    tags: list[str] | None = None,
    notes: str | None = None,
    *,
    conn: sqlite3.Connection | None = None,
) -> ProjectWithTags:
    __conn, _ = _acquire(conn)
    try:
        _validate_non_empty(name, "name")
        cust = __conn.execute(
            "SELECT id FROM customers WHERE id = ? AND archived = 0",
            (customer_id,),
        ).fetchone()
        if not cust:
            raise ValueError(f"Customer with id={customer_id} not found or archived")

        now = _now_ts()
        __conn.execute(
            "INSERT INTO projects (customer_id, name, active, notes, created_at) "
            "VALUES (?, ?, 1, ?, ?)",
            (customer_id, name, notes, now),
        )
        project_id = __conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        if tags:
            __conn.executemany(
                "INSERT INTO project_tags (project_id, tag) VALUES (?, ?)",
                [(project_id, t) for t in tags],
            )
        __conn.commit()
        return _fetch_project(__conn, project_id)
    finally:
        pass


def _fetch_project(
    conn: sqlite3.Connection,
    project_id: int,
) -> ProjectWithTags:
    """Fetch a project row and return it as a *ProjectWithTags*."""
    row = _ensure_row(
        conn.execute(
            "SELECT p.id, p.customer_id, p.name, p.active, p.notes, p.created_at "
            "FROM projects p JOIN customers c ON p.customer_id = c.id "
            "WHERE p.id = ?",
            (project_id,),
        ).fetchone(),
        "Project",
        project_id,
    )
    enriched = _build_project_row(conn, row)
    p = Project.from_row(enriched)
    obj = object.__new__(ProjectWithTags)
    Project.__init__(
        obj,
        id=enriched["id"],
        customer_id=enriched["customer_id"],
        name=enriched["name"],
        active=enriched["active"],
        notes=enriched["notes"],
        created_at=enriched["created_at"],
    )
    object.__setattr__(obj, "_tags", enriched["tags"])
    return obj


def update_project(
    project_id: int,
    name: str | None = None,
    active: int | None = None,
    notes: str | None = None,
    *,
    conn: sqlite3.Connection | None = None,
) -> ProjectWithTags:
    __conn, _ = _acquire(conn)
    try:
        row = _ensure_row(
            __conn.execute(
                "SELECT p.id, p.customer_id, p.name, p.active, p.notes, p.created_at "
                "FROM projects p JOIN customers c ON p.customer_id = c.id "
                "WHERE p.id = ?",
                (project_id,),
            ).fetchone(),
            "Project",
            project_id,
        )
        parts: list[str] = []
        vals: list[Any] = []
        if name is not None:
            _validate_non_empty(name, "name")
            parts.append("name = ?")
            vals.append(name)
        if active is not None:
            if active not in (0, 1):
                raise ValueError(f"active must be 0 or 1, got {active}")
            parts.append("active = ?")
            vals.append(active)
        if notes is not None:
            parts.append("notes = ?")
            vals.append(notes)

        if parts:
            vals.append(project_id)
            __conn.execute(
                f"UPDATE projects SET {', '.join(parts)} WHERE id = ?",
                vals,
            )
            __conn.commit()
        return _fetch_project(__conn, project_id)
    finally:
        pass


def set_project_tags(
    project_id: int,
    tags: list[str],
    *,
    conn: sqlite3.Connection | None = None,
) -> ProjectWithTags:
    __conn, _ = _acquire(conn)
    try:
        _ensure_row(
            __conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone(),
            "Project",
            project_id,
        )
        __conn.execute(
            "DELETE FROM project_tags WHERE project_id = ?", (project_id,)
        )
        if tags:
            __conn.executemany(
                "INSERT INTO project_tags (project_id, tag) VALUES (?, ?)",
                [(project_id, t) for t in tags],
            )
        __conn.commit()
        return _fetch_project(__conn, project_id)
    finally:
        pass


def list_projects(
    customer_id: int | None = None,
    tag: str | None = None,
    active_only: bool = True,
    *,
    conn: sqlite3.Connection | None = None,
) -> list[ProjectWithTags]:
    __conn, _ = _acquire(conn)
    try:
        sql = (
            "SELECT p.id, p.customer_id, p.name, p.active, p.notes, p.created_at "
            "FROM projects p JOIN customers c ON p.customer_id = c.id"
        )
        conditions: list[str] = ["c.archived = 0"]
        params: list[Any] = []

        if customer_id is not None:
            conditions.append("p.customer_id = ?")
            params.append(customer_id)
        if active_only:
            conditions.append("p.active = 1")

        rows = __conn.execute(sql + " WHERE " + " AND ".join(conditions), params).fetchall()
        projects = []
        for r in rows:
            projects.append(_fetch_project(__conn, dict(r)["id"]))

        if tag is not None:
            projects = [
                p
                for p in projects
                if tag in getattr(p, "_tags", [])
            ]

        return projects
    finally:
        pass


def get_project(
    project_id: int,
    *,
    conn: sqlite3.Connection | None = None,
) -> ProjectWithTags:
    __conn, _ = _acquire(conn)
    try:
        return _fetch_project(__conn, project_id)
    finally:
        pass


# ── People ─────────────────────────────────────────────────────────────────


def create_person(
    name: str,
    *,
    conn: sqlite3.Connection | None = None,
) -> Person:
    __conn, _ = _acquire(conn)
    try:
        _validate_non_empty(name, "name")
        now = _now_ts()
        __conn.execute(
            "INSERT INTO people (name, active, created_at) VALUES (?, 1, ?)",
            (name, now),
        )
        __conn.commit()
        return Person(
            id=__conn.execute("SELECT last_insert_rowid()").fetchone()[0],
            name=name,
            active=1,
            created_at=now,
        )
    finally:
        pass


def update_person(
    person_id: int,
    name: str | None = None,
    active: int | None = None,
    *,
    conn: sqlite3.Connection | None = None,
) -> Person:
    __conn, _ = _acquire(conn)
    try:
        row = _ensure_row(
            __conn.execute(
                "SELECT id, name, active, created_at FROM people WHERE id = ?",
                (person_id,),
            ).fetchone(),
            "Person",
            person_id,
        )
        parts: list[str] = []
        vals: list[Any] = []
        if name is not None:
            _validate_non_empty(name, "name")
            parts.append("name = ?")
            vals.append(name)
        if active is not None:
            if active not in (0, 1):
                raise ValueError(f"active must be 0 or 1, got {active}")
            parts.append("active = ?")
            vals.append(active)

        if parts:
            vals.append(person_id)
            __conn.execute(
                f"UPDATE people SET {', '.join(parts)} WHERE id = ?",
                vals,
            )
            __conn.commit()

        row = _ensure_row(
            __conn.execute(
                "SELECT id, name, active, created_at FROM people WHERE id = ?",
                (person_id,),
            ).fetchone(),
            "Person",
            person_id,
        )
        return Person.from_row(row)
    finally:
        pass


def list_people(
    active_only: bool = True,
    *,
    conn: sqlite3.Connection | None = None,
) -> list[Person]:
    __conn, _ = _acquire(conn)
    try:
        if active_only:
            rows = __conn.execute(
                "SELECT id, name, active, created_at FROM people "
                "WHERE active = 1 ORDER BY name"
            ).fetchall()
        else:
            rows = __conn.execute(
                "SELECT id, name, active, created_at FROM people ORDER BY name"
            ).fetchall()
        return [Person.from_row(dict(r)) for r in rows]
    finally:
        pass


# ── Time Entries ───────────────────────────────────────────────────────────


def log_time(
    person_id: int,
    project_id: int,
    entry_date: str,
    hours: float,
    description: str | None = None,
    *,
    conn: sqlite3.Connection | None = None,
) -> TimeEntry:
    __conn, _ = _acquire(conn)
    try:
        validated_date = _validate_date(entry_date)
        validated_hours = _validate_hours(hours)

        person = __conn.execute(
            "SELECT id FROM people WHERE id = ?", (person_id,)
        ).fetchone()
        if not person:
            raise ValueError(f"Person with id={person_id} not found")

        proj = __conn.execute(
            "SELECT id FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if not proj:
            raise ValueError(f"Project with id={project_id} not found")

        now = _now_ts()
        cur = __conn.execute(
            "INSERT INTO time_entries "
            "(person_id, project_id, entry_date, hours, description, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (person_id, project_id, validated_date, validated_hours, description, now, now),
        )
        __conn.commit()
        return TimeEntry(
            id=cur.lastrowid,
            person_id=person_id,
            project_id=project_id,
            entry_date=validated_date,
            hours=validated_hours,
            description=description,
            created_at=now,
            updated_at=now,
        )
    finally:
        pass


def update_time_entry(
    entry_id: int,
    entry_date: str | None = None,
    hours: float | None = None,
    description: str | None = None,
    *,
    conn: sqlite3.Connection | None = None,
) -> TimeEntry:
    __conn, _ = _acquire(conn)
    try:
        row = _ensure_row(
            __conn.execute(
                "SELECT id, person_id, project_id, entry_date, hours, "
                "description, created_at, updated_at "
                "FROM time_entries WHERE id = ?",
                (entry_id,),
            ).fetchone(),
            "TimeEntry",
            entry_id,
        )
        parts: list[str] = []
        vals: list[Any] = []
        if entry_date is not None:
            parts.append("entry_date = ?")
            vals.append(_validate_date(entry_date))
        if hours is not None:
            parts.append("hours = ?")
            vals.append(_validate_hours(hours))
        if description is not None:
            parts.append("description = ?")
            vals.append(description)
        if parts:
            parts.append("updated_at = ?")
            vals.append(_now_ts())
            vals.append(entry_id)
            __conn.execute(
                f"UPDATE time_entries SET {', '.join(parts)} WHERE id = ?",
                vals,
            )
            __conn.commit()

        row = _ensure_row(
            __conn.execute(
                "SELECT id, person_id, project_id, entry_date, hours, "
                "description, created_at, updated_at "
                "FROM time_entries WHERE id = ?",
                (entry_id,),
            ).fetchone(),
            "TimeEntry",
            entry_id,
        )
        return TimeEntry.from_row(row)
    finally:
        pass


def delete_time_entry(
    entry_id: int,
    *,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    __conn, _ = _acquire(conn)
    try:
        _ensure_row(
            __conn.execute(
                "SELECT id FROM time_entries WHERE id = ?", (entry_id,)
            ).fetchone(),
            "TimeEntry",
            entry_id,
        )
        __conn.execute("DELETE FROM time_entries WHERE id = ?", (entry_id,))
        __conn.commit()
        return {"deleted": True, "id": entry_id}
    finally:
        pass


def list_time_entries(
    person_id: int | None = None,
    project_id: int | None = None,
    customer_id: int | None = None,
    tag: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    *,
    conn: sqlite3.Connection | None = None,
) -> list[TimeEntry]:
    __conn, _ = _acquire(conn)
    try:
        sql = (
            "SELECT te.id, te.person_id, te.project_id, te.entry_date, "
            "te.hours, te.description, te.created_at, te.updated_at "
            "FROM time_entries te "
            "JOIN projects p ON te.project_id = p.id "
            "JOIN customers c ON p.customer_id = c.id"
        )
        conditions: list[str] = [
            "c.archived = 0",
            "p.active = 1",
        ]
        params: list[Any] = []

        if person_id is not None:
            conditions.append("te.person_id = ?")
            params.append(person_id)
        if project_id is not None:
            conditions.append("te.project_id = ?")
            params.append(project_id)
        if customer_id is not None:
            conditions.append("c.id = ?")
            params.append(customer_id)
        if date_from is not None:
            conditions.append("te.entry_date >= ?")
            params.append(_validate_date(date_from))
        if date_to is not None:
            conditions.append("te.entry_date <= ?")
            params.append(_validate_date(date_to))

        where = " WHERE " + " AND ".join(conditions)
        sql += where
        sql += " ORDER BY te.entry_date DESC, te.id DESC"
        rows = __conn.execute(sql, params).fetchall()
        results = [TimeEntry.from_row(dict(r)) for r in rows]

        if tag is not None:
            tag_project_ids: set[int] = {
                r["project_id"]
                for r in __conn.execute(
                    "SELECT project_id FROM project_tags WHERE tag = ?",
                    (tag,),
                ).fetchall()
            }
            results = [e for e in results if e.project_id in tag_project_ids]

        return results
    finally:
        pass
