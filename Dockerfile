# syntax=docker/dockerfile:1

# Dockerfile for timesheet-mcp — MCP server running over stdio transport.
#
# Build:  docker build -t timesheet-mcp .
# Run:    docker run -i --rm -v ./data:/app/data -v ./logs:/app/logs timesheet-mcp
#
# Important: the server communicates over stdin/stdout (MCP stdio transport),
# so the container MUST be run with -i (interactive) so that the MCP client's
# JSON-RPC messages arrive on stdin and the server's responses go to stdout.
# Example session:
#
#   echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"0.1.0"}}}' \
#   | docker run -i --rm -v $(pwd)/data:/app/data -v $(pwd)/logs:/app/logs timesheet-mcp
#
# Environment variables (passed through, not hardcoded):
#   TIMESHEET_DB_PATH   — absolute path to SQLite DB  (default: /app/data/timesheet.db)
#   TIMESHEET_LOG_LEVEL — log level string             (default: INFO)
#   TIMESHEET_LOG_STDERR— enable stderr handler        ("1"/"true"/"yes")
#
# Volume mount points (for persistence across restarts/rebuilds):
#   /app/data  — where TIMESHEET_DB_PATH defaults to (SQLite + WAL files)
#   /app/logs  — where RotatingFileHandler writes (timesheet_mcp.log)
#
# Path layout inside the image:
#   /app/pyproject.toml       (project root = WORKDIR)
#   /app/timesheet_mcp/      (package files)
#
#   db.py   and  logging_config.py  both resolve _PROJECT_ROOT as
#   Path(__file__).resolve().parent.parent — i.e. two levels above
#   timesheet_mcp, which gives /app.  This matches the layout and
#   means data/ and logs/ naturally live at /app/data and /app/logs.
#
# Build-time layout note:
#   The repo uses a src/ layout (src/timesheet_mcp/). Hatch needs this
#   during the editable install step, so we copy src/ in, run uv sync
#   (which installs deps + editable project), then copy the package
#   flat to /app/timesheet_mcp/ and remove src/ so that
#   Path(__file__).parent.parent == /app at runtime.

FROM python:3.13-slim

# Install uv for dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy lock file + project metadata.
# Copy src/ — hatch needs src/timesheet_mcp/ to build the editable package.
COPY uv.lock pyproject.toml README.md ./
COPY src/ src/

# Install deps + project (editable, from src/ layout).
RUN uv sync --frozen

# Reposition: copy package flat to /app/ so Path(__file__).parent.parent == /app
# (src/timesheet_mcp/ parent.parent == /app/src, but /app/timesheet_mcp/ parent.parent == /app)
RUN cp -r /app/src/timesheet_mcp /app/timesheet_mcp/

# Remove old src/ layout and editable-install .pth artifacts
RUN rm -rf /app/src
RUN find /app/.venv -name '*.pth' -delete

# Environment variables for runtime configuration
ENV TIMESHEET_DB_PATH=/app/data/timesheet.db
ENV TIMESHEET_LOG_LEVEL=INFO
ENV TIMESHEET_LOG_STDERR=0

# Ensure /app is importable so python -m timesheet_mcp.server works
# (the package is at /app/timesheet_mcp/)
ENV PYTHONPATH=/app

# Ensure .venv/bin is first in PATH so `python` resolves to the venv Python
ENV PATH="/app/.venv/bin:${PATH}"

# Default to running the MCP server over stdio
CMD ["python", "-m", "timesheet_mcp.server"]
