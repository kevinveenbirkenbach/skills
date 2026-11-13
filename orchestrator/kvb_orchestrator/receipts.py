from __future__ import annotations

import functools
import inspect
import json
import os
from pathlib import Path
from types import ModuleType

from .council import RECEIPT
from .names import PSEUDO, Directory, Names
from .records import epoch, read_regular
from .skill_scripts import RADIO, script_module

SEEN = "radio-seen"
PROMPT = "news-seen"
SNAPSHOT_SOURCE = "session"
PROMPT_BYTES = 64
STATE_BYTES = 4096
CACHED = 4096
SEEN_PARAMETERS = ("row", "name", "prompt", "state", "since")

Marks = tuple[float | None, dict[str, float]]
Stamp = tuple[int, int, int]


def radio_module(skills: Path) -> ModuleType | None:
    """Args:
        skills: the installed skills directory, the hub's --skills mount.

    Returns:
        Its kvb-org-radio radio.py as a module, the same file the hooks run;
        None when it is missing, does not load or its seen() does not take
        SEEN_PARAMETERS, as after an install of other skills than the hub's.
    """
    module = script_module(skills / RADIO)
    seen = getattr(module, "seen", None)
    try:
        parameters = tuple(inspect.signature(seen).parameters) if callable(seen) else ()
    except (TypeError, ValueError):
        return None
    return module if parameters == SEEN_PARAMETERS else None


def moment(value: object, now: float) -> float | None:
    found = epoch(value)
    return found if found is not None and found <= now else None


def stamp(path: Path) -> Stamp | None:
    try:
        found = os.lstat(path)
    except OSError:
        return None
    return found.st_ino, found.st_mtime_ns, found.st_size


@functools.lru_cache(maxsize=CACHED)
def parsed_prompt(path: Path, version: Stamp) -> float | None:
    try:
        return float(read_regular(path, PROMPT_BYTES))
    except (OSError, ValueError):
        return None


@functools.lru_cache(maxsize=CACHED)
def parsed_state(path: Path, version: Stamp) -> object:
    try:
        return json.loads(read_regular(path, STATE_BYTES))
    except (OSError, ValueError, RecursionError):
        return None


def prompt_of(path: Path, now: float) -> float | None:
    version = stamp(path)
    return None if version is None else moment(parsed_prompt(path, version), now)


def state_of(path: Path, now: float) -> dict[str, float]:
    version = stamp(path)
    data = None if version is None else parsed_state(path, version)
    if not isinstance(data, dict):
        return {}
    return {key: found for key, value in data.items() if (found := moment(value, now)) is not None}


def read_marks(council: Path, now: float) -> dict[str, Marks]:
    """Args:
        council: the council directory with radio-seen/<sid>.json and the
            older news-seen/<sid>.
        now: the moment to judge at.

    Returns:
        Per session id with a mark file its prompt mark and its radio-seen
        marks; a missing, malformed, unreadable, non-regular, oversized or
        future-dated mark is left out, a prompt mark then None. A file is
        parsed again only after its inode, mtime or size changed.
    """
    sids = {path.stem for path in (council / SEEN).glob("*.json")} | {path.name for path in (council / PROMPT).glob("*")}
    return {sid: (prompt_of(council / PROMPT / sid, now), state_of(council / SEEN / f"{sid}.json", now)) for sid in sorted(sids)}


def session_directory(store: Names, sessions: dict[str, dict], now: float) -> Directory:
    """Args:
        store: the hub's own name file for receipts, apart from the claim and
            title history, which any agent can feed through a claim file.
        sessions: read_snapshot(), written on the host from Claude Code's
            sessions; each record's name is the one radio.py's name_of()
            reads, kept as is, so rows and receipts match it unnormalized.
        now: the moment of the sighting.

    Returns:
        The store's history from snapshot sightings alone, the names of
        ended sessions included.
    """
    store.observe([(sid, record["name"], None, SNAPSHOT_SOURCE) for sid, record in sessions.items() if isinstance(record.get("name"), str) and record["name"]], now)
    return Directory([entry for entry in store.listed() if entry["source"] == SNAPSHOT_SOURCE])


def first_known(directory: Directory, sid: str, first: dict[str, float]) -> float:
    if sid not in first:
        first[sid] = directory.timeline(sid)[0]["since"]
    return first[sid]


def owners(directory: Directory, sender: str, ts: float, sessions: set[str], first: dict[str, float]) -> list[str]:
    held = [sid for sid in sorted(directory.aliases(sender)) if not sid.startswith(PSEUDO) and directory.at(sid, ts) == sender]
    strict = [sid for sid in held if first_known(directory, sid, first) <= ts]
    return strict or held or ([sender] if sender in sessions else [])


def acknowledged(radio: ModuleType, rows: list[dict], sessions: set[str], directory: Directory) -> dict[float, dict[str, float]]:
    found: dict[float, dict[str, float]] = {}
    first: dict[str, float] = {}
    for row in rows:
        call, sender, ts = epoch(row.get("call")), row.get("from"), epoch(row["ts"])
        if radio.kind(row) != RECEIPT or call is None or not isinstance(sender, str):
            continue
        for owner in owners(directory, sender, ts, sessions, first):
            found.setdefault(call, {}).setdefault(owner, ts)
    return found


def reader(radio: ModuleType, row: dict, sid: str, name: str, marks: Marks, acked: dict[str, float]) -> dict | None:
    prompt, state = marks
    if not radio.seen(row, name, radio.NEVER if prompt is None else prompt, state, radio.NEVER):
        return None
    return {"session": sid, "name": name, "read": acked.get(sid)}


def order(entry: dict) -> tuple:
    return entry["read"] is None, entry["read"] or 0.0, entry["name"], entry["session"]


def readers_and_acks(radio: ModuleType, news: list[dict], window: tuple[float, float], marks: dict[str, Marks], directory: Directory) -> dict[float, dict]:
    """Args:
        radio: radio_module(); its seen() decides whether a session read a
            row, with the marks alone and no delivery window.
        news: every news.jsonl row; a receipt counts for its call even when
            it lies outside the window.
        window: (begin, end); each row inside it but a receipt gets an entry.
        marks: read_marks() of the sessions.
        directory: session_directory(); a session goes by the name it held
            at the row's time, after it ended too, and by its id without one,
            as radio.py's name_of(); a receipt belongs to the
            sessions known to hold its sender's name by its time, else to
            those whose first known name it is.

    Returns:
        Per row ts {"readers": [{"session", "name", "read"}], "acks": [session
        ids]}: acks the sessions with a receipt whose call is that ts; read
        the first such receipt's ts, None for a reader without one, as the
        seen marks keep no delivery time.
    """
    begin, end = window
    rows = [row for row in news if epoch(row.get("ts")) is not None]
    acks = acknowledged(radio, rows, set(marks), directory)
    reach = {sid: max(radio.NEVER if prompt is None else prompt, radio.NEVER, *state.values()) for sid, (prompt, state) in marks.items()}
    found = {}
    for row in rows:
        ts = epoch(row["ts"])
        if radio.kind(row) == RECEIPT or not begin <= ts <= end:
            continue
        acked = acks.get(ts, {})
        readers = [entry for sid, held in marks.items() if ts <= reach[sid] and (entry := reader(radio, row, sid, directory.at(sid, ts) or sid, held, acked))]
        found[ts] = {"readers": sorted(readers, key=order), "acks": sorted(acked)}
    return found
