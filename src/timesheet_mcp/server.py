"""MCP tool registrations for the timesheet application.

All tools are plain functions registered on an ``MCPServer`` instance.
They delegate to ``repository.py`` / ``reports.py`` / ``config.py`` /
``holidays_fi.py`` and return JSON-serializable dicts or lists.

Module entry point:  python -m timesheet_mcp.server
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from . import logging_config
from . import reports
from . import repository


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_dicts(items: list) -> list[dict[str, Any]]:
    """Convert a list of objects with ``to_row()`` to plain dicts."""
    return [item.to_row() for item in items]


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------


def create_customer(
    name: str,
    notes: str | None = None,
) -> dict[str, Any]:
    """Create a new customer."""
    return repository.create_customer(name, notes).to_row()


def update_customer(
    customer_id: int,
    name: str | None = None,
    notes: str | None = None,
    archived: int | None = None,
) -> dict[str, Any]:
    """Update an existing customer."""
    return repository.update_customer(
        customer_id, name=name, notes=notes, archived=archived,
    ).to_row()


def list_customers(
    include_archived: bool = False,
) -> list[dict[str, Any]]:
    """List all customers (active by default)."""
    return _to_dicts(repository.list_customers(include_archived))


def get_customer(
    customer_id: int,
) -> dict[str, Any]:
    """Get a single customer by ID."""
    return repository.get_customer(customer_id).to_row()


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------


def _project_to_row(project: Any) -> dict[str, Any]:
    """Convert a Project (possibly ProjectWithTags) to a JSON-serialisable dict."""
    d = project.to_row()
    tags = getattr(project, "_tags", None)
    if tags is not None:
        d["tags"] = tags
    return d


def create_project(
    name: str,
    customer_id: int,
    tags: list[str] | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Create a new project."""
    return _project_to_row(repository.create_project(
        name, customer_id, tags=tags, notes=notes,
    ))


def update_project(
    project_id: int,
    name: str | None = None,
    active: int | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Update an existing project."""
    return _project_to_row(repository.update_project(
        project_id, name=name, active=active, notes=notes,
    ))


def set_project_tags(
    project_id: int,
    tags: list[str],
) -> dict[str, Any]:
    """Replace the full set of tags for a project."""
    return _project_to_row(repository.set_project_tags(project_id, tags))


def list_projects(
    customer_id: int | None = None,
    tag: str | None = None,
    active_only: bool = True,
) -> list[dict[str, Any]]:
    """List projects with optional filters."""
    projects = repository.list_projects(
        customer_id=customer_id,
        tag=tag,
        active_only=active_only,
    )
    return [_project_to_row(p) for p in projects]


def get_project(
    project_id: int,
) -> dict[str, Any]:
    """Get a single project by ID."""
    return _project_to_row(repository.get_project(project_id))


# ---------------------------------------------------------------------------
# People
# ---------------------------------------------------------------------------


def create_person(
    name: str,
) -> dict[str, Any]:
    """Create a new person."""
    return repository.create_person(name).to_row()


def update_person(
    person_id: int,
    name: str | None = None,
    active: int | None = None,
) -> dict[str, Any]:
    """Update an existing person."""
    return repository.update_person(
        person_id, name=name, active=active,
    ).to_row()


def list_people(
    active_only: bool = True,
) -> list[dict[str, Any]]:
    """List all people (active by default)."""
    return _to_dicts(repository.list_people(active_only))


# ---------------------------------------------------------------------------
# Time entries
# ---------------------------------------------------------------------------


def log_time(
    person_id: int,
    project_id: int,
    entry_date: str,
    hours: float,
    description: str | None = None,
) -> dict[str, Any]:
    """Log a new time entry."""
    return repository.log_time(
        person_id, project_id, entry_date, hours,
        description=description,
    ).to_row()


def update_time_entry(
    entry_id: int,
    entry_date: str | None = None,
    hours: float | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    """Update an existing time entry."""
    return repository.update_time_entry(
        entry_id, entry_date=entry_date, hours=hours,
        description=description,
    ).to_row()


def delete_time_entry(
    entry_id: int,
) -> dict[str, Any]:
    """Delete a time entry."""
    return repository.delete_time_entry(entry_id)


def list_time_entries(
    person_id: int | None = None,
    project_id: int | None = None,
    customer_id: int | None = None,
    tag: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict[str, Any]]:
    """List time entries with optional filters."""
    return _to_dicts(repository.list_time_entries(
        person_id=person_id,
        project_id=project_id,
        customer_id=customer_id,
        tag=tag,
        date_from=date_from,
        date_to=date_to,
    ))


# ---------------------------------------------------------------------------
# Reports / reference data
# ---------------------------------------------------------------------------


def get_finnish_holidays(year: int) -> list[dict[str, str]]:
    """Return Finnish holidays for *year*.

    Format: ``[{"date": "YYYY-MM-DD", "name": "..."}, ...]``
    """
    return reports.get_finnish_holidays(year)


def get_working_days(
    year: int,
    month: int,
) -> dict[str, Any]:
    """Return working-day count and expected hours for *year*-``month``."""
    return reports.get_working_days(year, month)


def get_monthly_report(
    year: int,
    month: int,
    group_by: str,
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
    project_id, customer_id, tag, person_id : int | None
        Filters applied before grouping.
    """
    return reports.get_monthly_report(
        year, month, group_by,
        project_id=project_id,
        customer_id=customer_id,
        tag=tag,
        person_id=person_id,
    )


# ---------------------------------------------------------------------------
# MCP Server setup
# ---------------------------------------------------------------------------

app = MCPServer(
    "timesheet-mcp",
    version="0.1.0",
)


def _setup_logging() -> None:
    """Configure logging (idempotent - called only once)."""
    logging_config.setup_logging()


# Register all tools on the MCP server
for _tool_func in [
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
]:
    app.tool()(_tool_func)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Start the MCP server using stdio transport."""
    _setup_logging()
    app.run(transport="stdio")


if __name__ == "__main__":
    main()
