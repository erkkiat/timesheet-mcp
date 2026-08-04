"""Aggregation / grouping logic and working-day math for the timesheet application.

All database-consuming functions accept an optional ``conn`` parameter for
testability.  When *conn* is omitted the module-level default connection is used.
"""

from __future__ import annotations

import calendar
import datetime
import sqlite3
from collections import defaultdict
from typing import Any

from . import config
from . import holidays_fi
from .db import get_default_connection

# ---------------------------------------------------------------------------
# Connection management
# ---------------------------------------------------------------------------


def _get_conn(
    conn: sqlite3.Connection | None,
) -> sqlite3.Connection:
    """Return a database connection, using the default when *conn* is omitted."""
    if conn is not None:
        return conn
    return get_default_connection()


# ---------------------------------------------------------------------------
# Refused-day helpers
# ---------------------------------------------------------------------------


def _is_refused_day(d: datetime.date) -> bool:
    """Return *True* if *d* is a weekend or a Finnish holiday."""
    if d.weekday() >= 5:
        return True
    return holidays_fi.is_working_day(d) is False


def _working_days_in_month(year: int, month: int) -> int:
    """Count working (Mon-Fri, non-holiday) days in *year*-*month*."""
    _, last_day = calendar.monthrange(year, month)
    count = 0
    for day in range(1, last_day + 1):
        d = datetime.date(year, month, day)
        if not _is_refused_day(d):
            count += 1
    return count


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_finnish_holidays(year: int) -> list[dict[str, str]]:
    """Return Finnish holidays for *year*.

    Format: ``[{"date": "YYYY-MM-DD", "name": "..."}, ...]``
    """
    return holidays_fi.get_finnish_holidays(year)


def get_working_days(
    year: int,
    month: int,
    *,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Return working-day count and expected hours for *year*-*month*.

    Returns
    -------
    dict
        ``{"working_days": int, "expected_hours": float}``
    """
    days = _working_days_in_month(year, month)
    conn = _get_conn(conn)
    daily_hours = config.get_default_daily_hours(conn=conn)
    return {
        "working_days": days,
        "expected_hours": round(days * daily_hours, 10),
    }


def get_monthly_report(
    year: int,
    month: int,
    group_by: str,
    *,
    conn: sqlite3.Connection | None = None,
    project_id: int | None = None,
    customer_id: int | None = None,
    tag: str | None = None,
    person_id: int | None = None,
) -> dict[str, Any]:
    """Return a monthly timesheet report grouped by *group_by*.

    Parameters
    ----------
    year, month : int
        Month to report on.
    group_by : str
        One of ``"project"``, ``"customer"``, ``"tag"``, ``"person"``, ``"day"``.
    project_id, customer_id, tag, person_id : int | str | None
        Filters applied before grouping.
    conn : sqlite3.Connection | None
        Database connection.

    Returns
    -------
    dict
        ``{"year", "month", "working_days", "expected_hours",
          "grand_total_hours", "groups"}``

    When *group_by* is ``"person"``, each group row also includes
    ``"expected_hours"`` and ``"balance"`` (total_hours − expected_hours).
    All other group_by modes carry only ``"total_hours"``.
    """
    conn = _get_conn(conn)

    valid_group_by = {"project", "customer", "tag", "person", "day"}
    if group_by not in valid_group_by:
        raise ValueError(
            f"group_by must be one of {sorted(valid_group_by)}, got '{group_by}'"
        )

    days = _working_days_in_month(year, month)
    daily_hours = config.get_default_daily_hours(conn=conn)
    expected = days * daily_hours

    # Determine the date range for the given year/month.
    first_day = datetime.date(year, month, 1)
    _, last_day = calendar.monthrange(year, month)
    last_date = datetime.date(year, month, last_day)

    # ── build query filters ──────────────────────────────────────────
    conditions: list[str] = []
    params: list[Any] = []

    conditions.append("te.entry_date >= ?")
    params.append(first_day.isoformat())
    conditions.append("te.entry_date <= ?")
    params.append(last_date.isoformat())

    if person_id is not None:
        conditions.append("te.person_id = ?")
        params.append(person_id)
    if project_id is not None:
        conditions.append("te.project_id = ?")
        params.append(project_id)

    # customer filter joins through projects
    if customer_id is not None:
        conditions.append("p.customer_id = ?")
        params.append(customer_id)

    # date_from / date_to are also supported per issue spec
    # These are implicitly handled by the range above

    where_clause = " WHERE " + " AND ".join(conditions)

    # ── fetch entries with enrichment data ───────────────────────────
    sql = (
        "SELECT te.id, te.person_id, te.project_id, te.entry_date, "
        "te.hours, te.description, te.created_at, te.updated_at, "
        "p.name AS project_name, c.name AS customer_name, "
        "pe.name AS person_name "
        "FROM time_entries te "
        "JOIN projects p ON te.project_id = p.id "
        "JOIN customers c ON p.customer_id = c.id "
        "JOIN people pe ON te.person_id = pe.id "
        + where_clause
        + " ORDER BY te.entry_date"
    )
    curs = conn.execute(sql, params).fetchall()
    entries = [dict(r) for r in curs]

    # ── tag post-filter ──────────────────────────────────────────────
    if tag is not None:
        tagged_ids = {
            r["project_id"]
            for r in conn.execute(
                "SELECT project_id FROM project_tags WHERE tag = ?",
                (tag,),
            ).fetchall()
        }
        entries = [e for e in entries if e["project_id"] in tagged_ids]

    # ── group ────────────────────────────────────────────────────────
    groups_map: dict[str, list[dict[str, Any]]] = defaultdict(list)
    grand_total = 0.0

    for entry in entries:
        grand_total += entry["hours"]
        hours = entry["hours"]
        key: str

        if group_by == "project":
            key = entry["project_name"]
        elif group_by == "customer":
            key = entry["customer_name"]
        elif group_by == "day":
            key = entry["entry_date"]
        elif group_by == "person":
            key = entry["person_name"]
        elif group_by == "tag":
            # One project can have many tags — emit one group per tag.
            tag_rows = conn.execute(
                "SELECT tag FROM project_tags WHERE project_id = ?",
                (entry["project_id"],),
            ).fetchall()
            for tr in tag_rows:
                tg = tr["tag"]
                groups_map[tg].append(entry)
            continue
        else:
            raise ValueError(
                f"group_by must be one of "
                f"{{'project','customer','tag','person','day'}}, got '{group_by}'"
            )

        groups_map[key].append(entry)

    # ── build group list ─────────────────────────────────────────────
    is_person = group_by == "person"
    group_list: list[dict[str, Any]] = []

    for key in sorted(groups_map.keys()):
        elist = groups_map[key]
        total_hr = sum(e["hours"] for e in elist)
        group_row: dict[str, Any] = {
            "key": key,
            "total_hours": round(total_hr, 10),
            "entries": elist,
        }
        if is_person:
            group_row["expected_hours"] = round(expected, 10)
            group_row["balance"] = round(total_hr - expected, 10)
        group_list.append(group_row)

    return {
        "year": year,
        "month": month,
        "working_days": days,
        "expected_hours": round(expected, 10),
        "grand_total_hours": round(grand_total, 10),
        "groups": group_list,
    }
