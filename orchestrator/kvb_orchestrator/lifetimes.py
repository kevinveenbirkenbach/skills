from __future__ import annotations

import datetime
from pathlib import Path

from .records import iso_epoch, parse_line, read_json, shown

EDGE_READ = 256 << 10
GONE = 86400


def lifetime_stamp(ts: float | None) -> str:
    if ts is None:
        return ""
    return datetime.datetime.fromtimestamp(ts, datetime.UTC).strftime("%Y-%m-%dT%H:%MZ")


def line_ts(raw: bytes) -> float | None:
    row = parse_line(raw.decode("utf-8", errors="replace"))
    return None if row is None else iso_epoch(row.get("timestamp"))


def edge_times(path: Path) -> tuple[float | None, float | None, float | None]:
    try:
        info = path.stat()
        with path.open("rb") as handle:
            head = handle.read(EDGE_READ)
            handle.seek(max(info.st_size - EDGE_READ, 0))
            tail = handle.read(EDGE_READ)
    except OSError:
        return None, None, None
    first = next((ts for ts in map(line_ts, head.splitlines()) if ts is not None), None)
    last = next((ts for ts in map(line_ts, reversed(tail.splitlines())) if ts is not None), None)
    return first, last, info.st_mtime


def lifetime(times: tuple[float | None, float | None, float | None], gone: bool) -> dict:
    """Args:
        times: first entry, last entry and modification time of a transcript.
        gone: whether the agent is known to have ended.

    Returns:
        born and died as YYYY-MM-DDTHH:MMZ in UTC, empty when unknown; died
        stays empty unless gone. since and until hold the same moments in
        epoch seconds, None when unknown or not gone.
    """
    first, last, _ = times
    ended = last if gone else None
    return {"born": lifetime_stamp(first), "died": lifetime_stamp(ended), "since": first, "until": ended}


def session_gone(beat: float | None, changed: float | None, now: float) -> bool:
    return (beat is None or now - beat > GONE) and changed is not None and now - changed > GONE


def subagent_rows(root: Path, session: str) -> list[dict]:
    try:
        paths = sorted(root.glob(f"*/{session}/subagents/agent-*.meta.json"))
    except OSError:
        return []
    rows = []
    for path in paths:
        data = read_json(path)
        if not isinstance(data, dict):
            continue
        ident = path.name.removeprefix("agent-").removesuffix(".meta.json")
        depth = data.get("spawnDepth")
        try:
            started = path.stat().st_mtime
        except OSError:
            continue
        finished = bool(data.get("finished"))
        rows.append({
            "id": ident, "type": shown(data.get("agentType")), "description": shown(data.get("description")),
            "depth": depth if isinstance(depth, int) and not isinstance(depth, bool) and depth > 0 else 1,
            "finished": finished, "tool_use": shown(data.get("toolUseId")), "started": started,
            **lifetime(edge_times(path.with_name(f"agent-{ident}.jsonl")), finished),
        })
    return sorted(rows, key=lambda row: (row["started"], row["id"]))
