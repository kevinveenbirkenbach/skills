from __future__ import annotations

from pathlib import Path

from .council import HUMAN, MODES, agent
from .records import epoch, read_json

STATES = ("sleeping", "suspending", "alive", "working", "dead", "unreachable")
STALE = 15 * 60
UNANSWERED = 10 * 60
SNAPSHOT = "agent-sessions.json"
SNAPSHOT_STALE = 5 * 60


def read_snapshot(path: Path, now: float) -> dict[str, dict]:
    """Args:
        path: the snapshot client/sessions.py writes on the host.
        now: the moment to judge at.

    Returns:
        Its session records by session id; empty when it is missing,
        malformed, written more than SNAPSHOT_STALE ago or dated in the
        future.
    """
    data = read_json(path)
    if not isinstance(data, dict) or not isinstance(data.get("sessions"), dict):
        return {}
    written = data.get("written")
    if isinstance(written, bool) or not isinstance(written, int | float) or not 0 <= now - written <= SNAPSHOT_STALE:
        return {}
    return {sid: record for sid, record in data["sessions"].items() if isinstance(record, dict)}


def unanswered(news: list[dict], now: float) -> list[tuple[str, float]]:
    """Returns:
        (callee name, call time) of every call older than UNANSWERED that its
        callee never receipted.
    """
    receipts = {(agent(row.get("from")), round(epoch(row.get("call")) or 0, 3)) for row in news if row.get("class") == "receipt"}
    late = []
    for row in news:
        ts = epoch(row.get("ts"))
        if row.get("class") != "call" or ts is None or now - ts < UNANSWERED or not isinstance(row.get("to"), list):
            continue
        late += [(name, ts) for name in map(agent, row["to"]) if name and (name, round(ts, 3)) not in receipts]
    return late


def presence(sessions: dict[str, dict], parts: dict[str, str], mode: str, claims: list[dict], news: list[dict], now: float) -> dict[str, str]:
    """Args:
        sessions: the session records of read_snapshot; running says
            whether a record's process still runs.
        parts: night_parts, a session's own part over the mode.
        mode: night_mode, drain, suspend or day.
        claims: the council claims; a session without a record shows alive
            or dead by its freshest beat.
        news: the radio rows, for calls without a receipt.
        now: the moment to judge at.

    Returns:
        One of STATES per session id (decision 61).
    """
    late = unanswered(news, now)
    beats: dict[str, list[float]] = {}
    names: dict[str, set[str]] = {}
    for claim in claims:
        if claim["session"] != "-" and claim["agent"] != HUMAN:
            beats.setdefault(claim["session"], []).append(claim["beat"] or 0)
            names.setdefault(claim["session"], set()).add(claim["agent"])
    states = {sid: "alive" if now - max(beat) < STALE else "dead" for sid, beat in beats.items() if sid not in sessions}
    for sid, record in sessions.items():
        if record.get("running") is not True:
            states[sid] = "dead"
            continue
        busy = record.get("status") == "busy"
        stamp = record.get("statusUpdatedAt")
        updated = (epoch(stamp / 1000) if isinstance(stamp, int | float) and not isinstance(stamp, bool) else None) or 0
        called = names.get(sid, set()) | {agent(record.get("name"))}
        if (busy and now - updated > STALE) or any(name in called and ts > updated for name, ts in late):
            states[sid] = "unreachable"
            continue
        part = parts.get(sid, mode)
        if part in MODES:
            states[sid] = "suspending" if busy else "sleeping"
        else:
            states[sid] = "working" if busy else "alive"
    return states
