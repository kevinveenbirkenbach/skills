#!/usr/bin/env python3
"""Args:
    --sessions: Claude Code's sessions directory, one <pid>.json per session,
        e.g. ~/.claude/sessions.
    --output: the snapshot the Agent Orchestrator reads, e.g.
        ~/.local/state/kvb-orchestrator/agent-sessions.json.

Returns:
    Runs on the host, because the hub's container sees neither these files
    nor the host's processes: replaces --output with {"written": <epoch>,
    "sessions": {<session id>: {"name", "status", "statusUpdatedAt",
    "running"}}}, running being whether the record's pid still runs the
    process it started. The exit code is 0.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import tempfile
import time
from pathlib import Path

PROC = Path("/proc")
KEPT = ("name", "status", "statusUpdatedAt")
RECORD_BYTES = 65536
VALUE_CHARS = 200


def read_record(path: Path) -> object:
    """Returns:
        The parsed JSON of path, read without following a symlink and only
        when it is a regular file of at most RECORD_BYTES.

    Raises:
        OSError: path is missing, a symlink, no regular file or too big.
        ValueError, RecursionError: its content is no JSON or nested too deep.
    """
    handle = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(handle, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > RECORD_BYTES:
            raise OSError(f"{path}: no regular file of at most {RECORD_BYTES} bytes")
        return json.loads(stream.read(RECORD_BYTES + 1).decode("utf-8"))


def kept(record: dict) -> dict:
    return {
        key: record[key]
        for key in KEPT
        if isinstance(record.get(key), str | int | float) and not isinstance(record[key], bool) and len(str(record[key])) <= VALUE_CHARS
    }


def read_sessions(folder: Path) -> dict[str, dict]:
    """Returns:
        The session records under folder by session id; unreadable files and
        records without a session id are left out.
    """
    found = {}
    for path in sorted(folder.glob("*.json")):
        try:
            data = read_record(path)
        except (OSError, ValueError, RecursionError):
            continue
        if isinstance(data, dict) and isinstance(data.get("sessionId"), str):
            found[data["sessionId"]] = data
    return found


def running(record: dict, proc: Path) -> bool:
    """Returns:
        Whether the record's pid still runs the process it started: the
        start tick in /proc/<pid>/stat (field 22) equals procStart, so a
        reused pid counts as gone.
    """
    pid, start = record.get("pid"), record.get("procStart")
    if isinstance(pid, bool) or not isinstance(pid, int) or not isinstance(start, str):
        return False
    try:
        fields = (proc / str(pid) / "stat").read_text(encoding="utf-8").rpartition(")")[2].split()
    except OSError:
        return False
    return len(fields) > 19 and fields[19] == start


def snapshot(folder: Path, proc: Path, now: float) -> dict:
    return {
        "written": now,
        "sessions": {
            sid: {**kept(record), "running": running(record, proc)}
            for sid, record in read_sessions(folder).items()
        },
    }


def write(output: Path, data: dict) -> None:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=output.parent, prefix=f".{output.name}.", delete=False) as handle:
        try:
            json.dump(data, handle)
        except BaseException:
            os.unlink(handle.name)
            raise
    os.replace(handle.name, output)


def main() -> int:
    parser = argparse.ArgumentParser(description="Snapshot Claude Code's sessions for the Agent Orchestrator.")
    parser.add_argument("--sessions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    write(args.output, snapshot(args.sessions, PROC, time.time()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
