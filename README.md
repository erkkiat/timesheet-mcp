# timesheet-mcp

A local, MCP-only timesheet application. There is no UI of its own — Claude (or any
other MCP client) is the interface. Users ask their AI assistant to log hours, correct
entries, run monthly reports, and pull the numbers needed to invoice customers. The
server's job is correct data storage, filtering/aggregation, and Finnish-holiday-aware
working-time math — not natural-language parsing (the AI client is responsible for
turning "log 3h on Tempo yesterday" into a structured tool call).

## Tech stack

- Python 3.11+
- `mcp` (official Python MCP SDK, FastMCP-style server)
- `holidays` for Finnish public holidays
- SQLite (stdlib) for storage
- `uv` for dependency/venv management
- `pytest` for tests

## Setup

```bash
uv sync
```

## Testing

Verify the project scaffolds correctly (no tests yet, but confirms the package is
importable and dependencies resolve):

```bash
pytest --collect-only
```

Run all tests against a temp SQLite database:

```bash
pytest
```

Run specific test modules:

```bash
pytest tests/test_models.py
```

## Docker

Build the image:

```bash
docker build -t timesheet-mcp .
```

Run the MCP server (stdio transport — requires `-i` for stdin):

```bash
docker run -i --rm \
  -v ./data:/app/data \
  -v ./logs:/app/logs \
  timesheet-mcp
```

Mount `./data` and `./logs` from the host so the SQLite database and log
file persist across container restarts and rebuilds.

Environment variables can be passed with `-e` (defaults are sane):
`TIMESHEET_DB_PATH`, `TIMESHEET_LOG_LEVEL`, `TIMESHEET_LOG_STDERR`.

## Project status

This project is under active development. The core data model, repository layer,
Finnish-holiday-aware reporting, and MCP server tool registrations are planned —
see PLAN.md for the full design spec and implementation order.
