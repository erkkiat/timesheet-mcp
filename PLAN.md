# timesheet-mcp — Design Plan

Status: **draft v1** — ready for implementation by the local Qwen coder/tester pipeline (solidcoder).
Do not implement ahead of this doc; update this doc first if the design changes.

## 1. Goal

A local, MCP-only timesheet application. There is no UI of its own — Claude (or any other
MCP client) is the interface. Users ask their AI assistant to log hours, correct entries,
run monthly reports, and pull the numbers needed to invoice customers. The server's job is
correct data storage, filtering/aggregation, and Finnish-holiday-aware working-time math —
not natural-language parsing (the AI client is responsible for turning "log 3h on Tempo
yesterday" into a structured tool call).

Out of scope for v1: authentication/auth, invoice document/PDF generation, currency or
billable-rate tracking, a web/GUI frontend, multi-tenant deployment. Keep the domain model
generic — no funder- or project-specific concepts baked into the schema (see §4, tags).

## 2. Tech stack

- Python 3.11+
- `mcp` (official Python MCP SDK, FastMCP-style server) — already available in the dev
  environment (`pip show mcp`); add to `pyproject.toml` as a dependency.
- `sqlite3` (stdlib) for storage — single file DB, no server process.
- `holidays` (PyPI package) for Finnish public holidays: `holidays.country_holidays("FI", years=...)`.
  Not currently installed — add as a dependency.
- stdlib `logging` for debug logging (see §7).
- `uv` for dependency/venv management (already installed on this machine); `pyproject.toml`
  is the source of truth for dependencies.
- `pytest` for tests.

## 3. Project layout

```
timesheet-mcp/
  pyproject.toml
  README.md
  PLAN.md                       (this file)
  .gitignore                    (data/, logs/, .venv/, __pycache__/)
  src/timesheet_mcp/
    __init__.py
    server.py                   # FastMCP app, tool registrations (thin — delegates to repository/reports)
    db.py                       # sqlite connection + schema creation/migration
    models.py                   # dataclasses: Customer, Project, Person, TimeEntry
    repository.py               # CRUD data-access layer, no MCP/logging concerns
    reports.py                  # aggregation/grouping logic, working-day math
    holidays_fi.py              # thin wrapper around `holidays` lib (year-cached)
    config.py                   # settings table access (default_daily_hours etc.)
    logging_config.py           # logging setup (file handler, level from env)
  tests/
    test_db.py
    test_repository.py
    test_reports.py
    test_holidays_fi.py
    test_server_tools.py        # call the tool functions directly (not over stdio)
  data/                          # sqlite db file lives here, gitignored
  logs/                          # log files live here, gitignored
```

## 4. Data model (SQLite schema)

```sql
CREATE TABLE customers (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    notes       TEXT,
    archived    INTEGER NOT NULL DEFAULT 0,   -- 0/1
    created_at  TEXT NOT NULL                  -- ISO 8601 UTC
);

CREATE TABLE projects (
    id          INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    name        TEXT NOT NULL,
    active      INTEGER NOT NULL DEFAULT 1,   -- 0/1
    notes       TEXT,
    created_at  TEXT NOT NULL,
    UNIQUE(customer_id, name)
);

CREATE TABLE project_tags (
    project_id  INTEGER NOT NULL REFERENCES projects(id),
    tag         TEXT NOT NULL,                -- free-form, e.g. "business-finland", "tempo"
    PRIMARY KEY (project_id, tag)
);

CREATE TABLE people (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL
);

CREATE TABLE time_entries (
    id           INTEGER PRIMARY KEY,
    person_id    INTEGER NOT NULL REFERENCES people(id),
    project_id   INTEGER NOT NULL REFERENCES projects(id),
    entry_date   TEXT NOT NULL,                -- ISO date, "YYYY-MM-DD"
    hours        REAL NOT NULL,                -- > 0, allow fractional (e.g. 0.5)
    description  TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE TABLE settings (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);
-- seeded row: ('default_daily_hours', '7.5')

CREATE INDEX idx_time_entries_date ON time_entries(entry_date);
CREATE INDEX idx_time_entries_person ON time_entries(person_id);
CREATE INDEX idx_time_entries_project ON time_entries(project_id);
```

Tags are free-form strings on projects (not a fixed enum, not a funder-specific field) —
e.g. a project can carry `["business-finland", "tempo"]`. Reports can filter/group by tag
so "give me all Business Finland hours this month" is just `tag="business-finland"`, with
no funder-specific code anywhere in the schema or server.

`people` exists because this is multi-user: every time entry belongs to a person, and
reports can filter/group by person as well as by project/customer/tag.

Validation rules (enforced in `repository.py`, not just relied on from SQLite):
- `hours` must be `> 0` and `<= 24`.
- `entry_date` must parse as a valid ISO date.
- Deleting/archiving a customer or project does not delete existing time entries (soft
  delete only — `archived`/`active` flags, never `DELETE FROM customers/projects`).

## 5. Working-time math (Finnish holidays)

- `default_daily_hours` lives in `settings` (seeded to `7.5`), read via `config.py`.
  A single global default for v1 — no per-person override (can be added later if needed).
- `holidays_fi.py` wraps `holidays.country_holidays("FI", years=[...])`, caching by year
  (the underlying library recomputes moveable feasts like Easter per year, so cache per
  year not globally). pip install holidays
- "Working day" = Monday–Friday and not in the Finnish holiday set for that year.
- `expected_hours(year, month)` = `working_days_in_month(year, month) * default_daily_hours`.
- Weekends and holidays are never counted as working days; there is no concept of
  vacation/sick-leave entries in v1 — if someone is out, they simply log fewer hours than
  expected and the balance reflects that. Warn if entering working hours for a holiday or weekend.

## 6. MCP tools

All tools are plain functions registered on a `FastMCP` app in `server.py`; they call into
`repository.py` / `reports.py` and return JSON-serializable dicts/lists. Errors raise; let
the MCP framework surface them as tool errors (don't swallow and return ambiguous `None`).

**Customers**
- `create_customer(name, notes=None) -> customer`
- `update_customer(customer_id, name=None, notes=None, archived=None) -> customer`
- `list_customers(include_archived=False) -> [customer]`
- `get_customer(customer_id) -> customer`

**Projects**
- `create_project(name, customer_id, tags=[], notes=None) -> project`
- `update_project(project_id, name=None, active=None, notes=None) -> project`
- `set_project_tags(project_id, tags) -> project`  (replaces the full tag set)
- `list_projects(customer_id=None, tag=None, active_only=True) -> [project]`
- `get_project(project_id) -> project`

**People**
- `create_person(name) -> person`
- `update_person(person_id, name=None, active=None) -> person`
- `list_people(active_only=True) -> [person]`

**Time entries**
- `log_time(person_id, project_id, entry_date, hours, description=None) -> time_entry`
- `update_time_entry(entry_id, entry_date=None, hours=None, description=None) -> time_entry`
- `delete_time_entry(entry_id) -> {deleted: true, id}`
- `list_time_entries(person_id=None, project_id=None, customer_id=None, tag=None, date_from=None, date_to=None) -> [time_entry]`

**Reports / reference data**
- `get_finnish_holidays(year) -> [{date, name}]`
- `get_working_days(year, month) -> {working_days, expected_hours}`
- `get_monthly_report(year, month, group_by="project", project_id=None, customer_id=None, tag=None, person_id=None) -> report`
  - `group_by` is one of `"project" | "customer" | "tag" | "person" | "day"`.
  - Filters narrow the entries considered; `group_by` controls how the totals are bucketed.
  - Response shape:
    ```
    {
      "year": 2026, "month": 8,
      "working_days": 21, "expected_hours": 157.5,
      "grand_total_hours": 142.0,
      "groups": [
        {"key": "Tempo (Business Finland)", "total_hours": 60.0, "entries": [...]},
        ...
      ]
    }
    ```
  - `expected_hours` / a `balance` field (`total_hours - expected_hours`) is only
    meaningful per-person: when `group_by="person"`, each group row additionally includes
    `expected_hours` and `balance` for that person. For every other `group_by`, groups
    carry `total_hours` only (no balance — expected hours isn't a property of a project,
    customer, or tag).

## 7. Logging

- stdlib `logging`, configured once in `logging_config.py`, called from `server.py` at
  startup — **never log to stdout**: the MCP stdio transport uses stdout for the JSON-RPC
  channel, so any stray print/log-to-stdout corrupts the protocol stream. Log to a file
  (and optionally stderr) only.
- `RotatingFileHandler` writing to `logs/timesheet_mcp.log` (maxBytes ~5MB, backupCount 3).
- Level from `TIMESHEET_LOG_LEVEL` env var, default `INFO`.
- Each MCP tool call logs at `DEBUG` on entry (tool name + args) and on exit
  (result summary or exception with stack trace at `ERROR`). This is the primary debugging
  aid since there's no UI to inspect state visually — logs are how you or Claude diagnose
  "why did this report come back wrong."

## 8. MCP server registration

stdio transport (this is a local single-machine tool driven by a local AI client). Module
entry point: `python -m timesheet_mcp.server`. Example client config:

```json
{
  "mcpServers": {
    "timesheet": {
      "command": "uv",
      "args": ["run", "--directory", "/Users/eki1/Documents/Work/Src/timesheet-mcp",
                "python", "-m", "timesheet_mcp.server"]
    }
  }
}
```

DB path defaults to `data/timesheet.db` (relative to the project root), overridable via
`TIMESHEET_DB_PATH` env var.

## 9. Testing

- `pytest`, tests run against a temp SQLite file (or `:memory:` where the connection can
  be shared) — never against `data/timesheet.db`.
- `test_repository.py`: CRUD + validation rules (rejects `hours <= 0`, rejects bad dates,
  soft-delete behavior, unique constraints).
- `test_reports.py`: working-day math against known Finnish holidays (e.g. Juhannus/
  Midsummer, Independence Day) for a couple of different years/months; each `group_by`
  mode; balance only appears for `group_by="person"`.
- `test_holidays_fi.py`: sanity-check a handful of known fixed and moveable Finnish
  holidays for at least two different years.
- `test_server_tools.py`: call the registered tool functions directly (import from
  `server.py`) with a temp DB, covering the create → log → report round trip end to end.

## 10. Open items for a future iteration (explicitly not in v1)

- Billable rates / currency and invoice document generation.
- Per-person expected daily hours (part-time people).
- Vacation/sick/absence entry types.
- Multi-tenant / auth.

## 11. Setup checklist for whoever implements this

1. `uv init` / hand-write `pyproject.toml` with deps: `mcp`, `holidays`, `pytest` (dev).
2. `git init` this directory (it does not have a repo yet).
3. Implement in the order: `db.py` (schema) → `models.py` → `repository.py` → `holidays_fi.py`
   → `config.py` → `reports.py` → `logging_config.py` → `server.py` (tool registrations) →
   tests alongside each module.
4. Run `pytest` before considering any module done.
