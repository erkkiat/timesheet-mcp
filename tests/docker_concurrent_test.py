#!/usr/bin/env python3
"""Concurrent verification: asyncio-based tool-call concurrency through MCP server.

Starts the MCP server as a subprocess, performs the initialize handshake, then
fires off multiple tools/call requests using asyncio tasks.  Each task sends its
request, then reads its response from a shared response queue (ensuring correct
request-response pairing despite concurrent sends).
"""

import asyncio
import json
import sys
import os

# Use the installed package (matches Docker image layout)


def server_cmd():
    import importlib.util
    if importlib.util.find_spec("timesheet_mcp.server") is not None:
        return [sys.executable, "-m", "timesheet_mcp.server"]
    return ["docker", "run", "-i", "--rm", "-v", "./data:/app/data", "-v", "./logs:/app/logs", "timesheet-mcp:threadfix"]


async def send_msg(stream, method, params=None, request_id=None):
    """Send a JSON-RPC message to the server."""
    msg = {"jsonrpc": "2.0"}
    if request_id is not None:
        msg["id"] = request_id
    msg["method"] = method
    if params is not None:
        msg["params"] = params
    raw = json.dumps(msg) + "\n"
    stream.write(raw.encode())
    await stream.drain()


async def reader_loop(reader, response_queue):
    """Continuously read responses from the server and push to queue."""
    try:
        while True:
            line = await reader.readline()
            if not line:
                break
            data = json.loads(line)
            rid = data.get("id")
            await response_queue.put((rid, data))
    except asyncio.CancelledError:
        pass


async def main():
    print("=" * 60)
    print("Concurrent verification test")
    print("=" * 60)
    print()

    # Decide: use subprocess or Docker
    use_docker = not __import__("importlib.util").util.find_spec("timesheet_mcp.server")
    if use_docker:
        print("Using: docker run timesheet-mcp:threadfix")
        proc_args = [
            "docker", "run", "-i",
            "--rm",
            "-v", "./data:/app/data",
            "-v", "./logs:/app/logs",
            "timesheet-mcp:threadfix",
        ]
    else:
        print(f"Using: {sys.executable} -m timesheet_mcp.server")
        proc_args = [sys.executable, "-m", "timesheet_mcp.server"]

    env = os.environ.copy()
    env["TIMESHEET_DB_PATH"] = "/tmp/timesheet_test_db.db"

    proc = await asyncio.create_subprocess_exec(
        *proc_args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )

    reader = proc.stdout
    writer = proc.stdin

    # Start response reader
    response_queue = asyncio.Queue()
    reader_task = asyncio.create_task(reader_loop(reader, response_queue))

    # Initialize handshake
    await send_msg(writer, "initialize", {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "concurrent-test", "version": "1.0.0"},
    }, 0)
    resp = await response_queue.get()
    print(f"  [initialize] {resp[1].get('result', 'error')}")

    # Initialized notification (no response expected)
    await send_msg(writer, "notifications/initialized", None, None)

    # Flush any stray responses from init
    while not response_queue.empty():
        await response_queue.get()

    print()

    # Build tool call tasks
    calls = []
    rid = 0
    for i in range(10):
        calls.append((rid, rid + 1, "create_person", {"name": f"ConnPerson-{i}"}))
        rid += 2
    calls.append((rid, rid + 1, "create_customer", {"name": "ConnCust-A"}))
    rid += 2
    calls.append((rid, rid + 1, "create_customer", {"name": "ConnCust-B"}))
    rid += 2
    calls.append((rid, rid + 1, "list_people", {}))
    rid += 2
    calls.append((rid, rid + 1, "list_customers", {}))
    rid += 2
    calls.append((rid, rid + 1, "get_finnish_holidays", {"year": 2026}))

    # Send all requests concurrently
    send_tasks = []
    for rid_sent, rid_exp, method, args in calls:
        send_tasks.append(send_msg(writer, "tools/call", {"name": method, "arguments": args}, rid_exp))

    send_done = await asyncio.gather(*send_tasks)
    del send_done

    # Also send the get_working_days request
    rid += 2
    await send_msg(writer, "tools/call", {
        "name": "get_working_days",
        "arguments": {"year": 2026, "month": 7},
    }, rid)

    # Read all responses
    results = {}
    expected_rids = set(rid_exp for _, rid_exp, _, _ in calls) | {rid}

    for i in range(len(calls) + 1):  # +1 for get_working_days
        try:
            rid, data = await asyncio.wait_for(response_queue.get(), timeout=5)
            results[rid] = data
        except asyncio.TimeoutError:
            print(f"  TIMEOUT reading response for rid=None")
            results[None] = {"error": "timeout"}

    # Print results
    ok = 0
    failed = []

    for _, rid_exp, method, _ in calls:
        resp = results.get(rid_exp)
        if resp is None:
            failed.append(f"MISSING: {method} (id={rid_exp})")
            continue
        if "result" in resp:
            content = resp["result"].get("content", [])
            if content and isinstance(content, list) and content[0]:
                item = content[0]
                if isinstance(item, dict) and item.get("isError"):
                    failed.append(f"SERVER-ERR: {method} (id={rid_exp}) -> {item.get('text', str(item))}")
                else:
                    pid = item.get("id", "N/A")
                    print(f"  OK:   {method} (id={rid_exp}) -> id={pid}")
                    ok += 1
            elif content and isinstance(content, list) and not content:
                print(f"  OK:   {method} (id={rid_exp}) -> []")
                ok += 1
            else:
                print(f"  OK:   {method} (id={rid_exp})")
                ok += 1
        elif "error" in resp:
            failed.append(f"CLIENT-ERR: {method} (id={rid_exp}) -> {resp['error']}")
        else:
            failed.append(f"UNEXPECTED: {method} (id={rid_exp}) -> {resp}")

    # Check get_working_days
    wid = rid
    resp = results.get(wid)
    if resp and "result" in resp:
        print(f"  OK:   get_working_days (id={wid})")
        ok += 1
    elif resp and "error" in resp:
        failed.append(f"CLIENT-ERR: get_working_days (id={wid}) -> {resp['error']}")
    else:
        failed.append(f"MISSING: get_working_days (id={wid})")

    # Cleanup
    reader_task.cancel()
    try:
        await reader_task
    except asyncio.CancelledError:
        pass
    proc.terminate()
    try:
        await asyncio.wait_for(proc.wait(), timeout=5)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()

    # Cleanup test DB files
    db_path = "/tmp/timesheet_test_db.db"
    for suffix in [".db", ".db-wal", ".db-shm"]:
        try:
            os.remove(db_path + suffix)
        except OSError:
            pass

    print()
    print(f"Results: {ok} ok, {len(failed)} failed")

    if failed:
        print()
        print("FAILED:")
        for f in failed:
            print(f"  {f}")
        sys.exit(1)
    else:
        print()
        print("SUCCESS: All requests completed without errors.")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
