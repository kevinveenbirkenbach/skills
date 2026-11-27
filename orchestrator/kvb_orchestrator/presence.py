from __future__ import annotations

from pathlib import Path

from .council import HUMAN, MODES, agent
from .records import epoch, read_json

STATES = ("sleeping", "suspending", "alive", "working", "dead", "unreachable")
STALE = 15 * 60
UNANSWERED = 10 * 60
SNAPSHOT = "agent-sessions.json"
SNAPSHOT_STALE = 5 * 60
BUSY = "busy"


def fresh_snapshot(path: Path, now: float) -> dict[str, dict] | None:
    """Args:
        path: the snapshot client/sessions.py writes on the host.
        now: the moment to judge at.

    Returns:
        Its session records by session id; None when it is missing,
        malformed, written more than SNAPSHOT_STALE ago or dated in the
        future.
    """
    data = read_json(path)
    if not isinstance(data, dict) or not isinstance(data.get("sessions"), dict):
        return None
    written = data.get("written")
    if isinstance(written, bool) or not isinstance(written, int | float) or not 0 <= now - written <= SNAPSHOT_STALE:
        return None
    return {sid: record for sid, record in data["sessions"].items() if isinstance(record, dict)}


def read_snapshot(path: Path, now: float) -> dict[str, dict]:
    """Returns:
        fresh_snapshot(), empty in place of None.
    """
    return fresh_snapshot(path, now) or {}


def status_time(record: dict) -> float | None:
    """Returns:
        The record's statusUpdatedAt, which the host stores in
        milliseconds, in epoch seconds; None when it is no valid time.
    """
    stamp = record.get("statusUpdatedAt")
    return epoch(stamp / 1000) if isinstance(stamp, int | float) and not isinstance(stamp, bool) else None


def beats(sessions: dict[str, dict], claims: list[dict]) -> dict[str, float]:
    """Args:
        sessions: the session records of read_snapshot.
        claims: the council claims.

    Returns:
        The latest heartbeat per agent name as agent() reads it, in epoch
        seconds: the status_time of each running busy session record and
        the beat of each claim an agent other than the Operator holds.
        Kanban.marks judges how fresh a beat must be.
    """
    stamps = [(agent(record.get("name")), status_time(record)) for record in sessions.values() if record.get("running") is True and record.get("status") == BUSY]
    stamps += [(claim["agent"], claim["beat"]) for claim in claims if claim["agent"] != HUMAN]
    found: dict[str, float] = {}
    for name, beat in stamps:
        if name and beat is not None:
            found[name] = max(beat, found.get(name, beat))
    return found


def unanswered(news: list[dict], now: float) -> list[tuple[str, float]]:
    """Returns:
        (callee, call time) of every call older than UNANSWERED without a
        receipt: one per session id in `to_sessions`, answered by any
        receipt of that call; else one per name in `to`.
    """
    receipts = {(agent(row.get("from")), round(epoch(row.get("call")) or 0, 3)) for row in news if row.get("class") == "receipt"}
    answered = {call for _, call in receipts}
    late = []
    for row in news:
        ts = epoch(row.get("ts"))
        if row.get("class") != "call" or ts is None or now - ts < UNANSWERED or not isinstance(row.get("to"), list):
            continue
        sessions = [sid for sid in row["to_sessions"] if isinstance(sid, str)] if isinstance(row.get("to_sessions"), list) else []
        if sessions:
            late += [(sid, ts) for sid in sessions if round(ts, 3) not in answered]
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
        busy = record.get("status") == BUSY
        updated = status_time(record) or 0
        called = names.get(sid, set()) | {agent(record.get("name")), sid}
        if (busy and now - updated > STALE) or any(name in called and ts > updated for name, ts in late):
            states[sid] = "unreachable"
            continue
        part = parts.get(sid, mode)
        if part in MODES:
            states[sid] = "suspending" if busy else "sleeping"
        else:
            states[sid] = "working" if busy else "alive"
    return states
