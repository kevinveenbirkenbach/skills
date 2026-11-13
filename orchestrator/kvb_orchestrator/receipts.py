from __future__ import annotations

import functools
import inspect
import json
import math
import os
import sys
import threading
import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

from .council import NEWS, RECEIPT
from .names import PSEUDO, SESSION_ID, Directory, Names
from .presence import fresh_snapshot, read_snapshot
from .records import epoch, read_json, read_jsonl, read_regular, write_atomic
from .skill_scripts import RADIO, script_module

SEEN = "radio-seen"
PROMPT = "news-seen"
NAMES = "receipt-names.json"
READS = "receipt-reads.json"
READ_ENTRIES = 32768
LOG_CHARS = 300
SNAPSHOT_SOURCE = "session"
PROMPT_BYTES = 64
STATE_BYTES = 4096
CACHED = 4096
SIGHTING = 15.0
LOOKED_AGE = 2 * SIGHTING
KEPT = 7 * 86400
ENTRIES = 4096
STEP = 3600.0
NAME_CHARS = 200
SEEN_PARAMETERS = ("row", "name", "sid", "prompt", "state", "since")

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


def fits(sid: str, name: object) -> bool:
    return bool(SESSION_ID.fullmatch(sid)) and isinstance(name, str) and 0 < len(name) <= NAME_CHARS


class ReceiptNames(Names):
    def __init__(self, file: Path) -> None:
        """Args:
            file: the hub's receipt name store; beside the Names history it
                keeps each session's last sighting under sighted. An entry or
                observed name whose session id is not of SESSION_ID or whose
                name is not 1 to NAME_CHARS characters, and a malformed
                sighting are left out.
        """
        super().__init__(file)
        self.entries = [entry for entry in self.entries if fits(entry["session"], entry["name"])]
        self.observed = {key: name for key, name in self.observed.items() if fits(key.partition("\x00")[0], name)}
        sighted = self.data.get("sighted")
        self.sighted: dict[str, float] = {sid: when for sid, value in sighted.items() if SESSION_ID.fullmatch(sid) and (when := epoch(value)) is not None} if isinstance(sighted, dict) else {}

    def payload(self) -> dict:
        return {**super().payload(), "sighted": self.sighted}

    def keep(self, live: list[str], now: float) -> None:
        """Args:
            live: the sessions of the snapshot, sighted at now; a sighting is
                stored at most every STEP seconds, and a session without one
                counts as sighted now.
            now: the moment of the sighting; a sighting after it counts as at
                it, a session not sighted for KEPT seconds loses its entries,
                and past ENTRIES entries the sessions sighted longest ago lose
                theirs first.
        """
        seen = set(live)
        with self.lock:
            future = {sid for sid, last in self.sighted.items() if last > now}
            changed = bool(future)
            self.sighted.update(dict.fromkeys(future, now))
            sessions = {entry["session"] for entry in self.entries}
            for sid in sorted(sessions | seen):
                last = self.sighted.get(sid)
                if last is None or (sid in seen and now - last >= STEP):
                    self.sighted[sid] = now
                    changed = True
            gone = {sid for sid, last in self.sighted.items() if now - last > KEPT or sid not in sessions}
            counts = Counter(entry["session"] for entry in self.entries if entry["session"] not in gone)
            total = sum(counts.values())
            for sid in sorted(counts, key=lambda sid: (self.sighted[sid], sid)):
                if total <= ENTRIES:
                    break
                gone.add(sid)
                total -= counts[sid]
            if gone:
                self.entries = [entry for entry in self.entries if entry["session"] not in gone]
                self.observed = {key: name for key, name in self.observed.items() if key.partition("\x00")[0] not in gone}
                self.sighted = {sid: last for sid, last in self.sighted.items() if sid not in gone}
                changed = True
            if changed:
                self.save()


def sightings(sessions: dict[str, dict]) -> list[tuple[str, str, None, str]]:
    return [(sid, record["name"], None, SNAPSHOT_SOURCE) for sid, record in sessions.items() if fits(sid, record.get("name"))]


def stored_read(entry: object) -> tuple[tuple[str, float], float | None] | None:
    if not isinstance(entry, list) or len(entry) != 3 or not isinstance(entry[0], str) or not SESSION_ID.fullmatch(entry[0]):
        return None
    ts, when = epoch(entry[1]), epoch(entry[2])
    if ts is None or (when is None and entry[2] is not None) or (when is not None and when < ts):
        return None
    return (entry[0], ts), when


def clamped(times: dict[tuple[str, float], float | None], now: float) -> dict[tuple[str, float], float | None]:
    return {key: when if when is None or when <= now else now for key, when in times.items()}


class ReceiptReads:
    def __init__(self, file: Path) -> None:
        """Args:
            file: the hub's read time store, {"reads": [[session id, row ts,
                first sighting or null]]}; an entry of another shape, a
                session id not of SESSION_ID, a time that is no epoch or a
                sighting before its row is left out.
        """
        self.file = file
        self.lock = threading.Lock()
        self.looked: float | None = None
        self.floor = -math.inf
        data = read_json(file)
        reads = data.get("reads") if isinstance(data, dict) else None
        self.times: dict[tuple[str, float], float | None] = dict(found for entry in reads if (found := stored_read(entry))) if isinstance(reads, list) else {}

    def listed(self, now: float) -> dict[tuple[str, float], float | None]:
        """Returns:
            Per (session id, row ts) its first sighting, one after now as
            now.
        """
        with self.lock:
            return clamped(self.times, now)

    def blind(self) -> None:
        with self.lock:
            self.looked = None

    def see(self, covered: set[tuple[str, float]], now: float, begin: float, fresh: bool) -> None:
        """Args:
            covered: (session id, row ts) of each row a mark of the session
                covers now.
            now: the moment of the sighting pass; a pair not stored yet is
                stored with it, with None unless the previous pass of this
                process read a fresh snapshot at most LOOKED_AGE seconds
                before, since it was read at an unknown time before the hub
                looked, as across a frozen hub; a stored sighting after it is
                stored as it.
            begin: the start of the radio window; pairs of older rows go, and
                past READ_ENTRIES those of the oldest rows, which then never
                come back with a later time.
            fresh: whether this pass read a fresh session snapshot.
        """
        with self.lock:
            when = now if self.looked is not None and 0 <= now - self.looked <= LOOKED_AGE else None
            self.floor = max(self.floor, begin)
            times = {key: value for key, value in clamped(self.times, now).items() if key[1] >= self.floor}
            times.update({key: when for key in covered if key[1] >= self.floor and key not in times})
            if len(times) > READ_ENTRIES:
                self.floor = math.nextafter(sorted(key[1] for key in times)[-READ_ENTRIES - 1], math.inf)
                times = {key: value for key, value in times.items() if key[1] >= self.floor}
            self.looked = now if fresh else None
            if times != self.times:
                self.times = times
                write_atomic(self.file, json.dumps({"reads": [[sid, ts, read] for (sid, ts), read in sorted(times.items())]}).encode("utf-8"))


def session_directory(store: ReceiptNames, sessions: dict[str, dict], now: float) -> Directory:
    """Args:
        store: the hub's own name file for receipts, apart from the claim and
            title history, which any agent can feed through a claim file.
        sessions: read_snapshot(), written on the host from Claude Code's
            sessions; each record's name is the one radio.py's name_of()
            reads, kept as is, so rows and receipts match it unnormalized; a
            record without a session id of SESSION_ID or a name of 1 to
            NAME_CHARS characters is left out.
        now: the moment of the sighting.

    Returns:
        The store's history from snapshot sightings alone, the names of
        ended sessions included until ReceiptNames.keep() drops them.
    """
    found = sightings(sessions)
    store.observe(found, now)
    store.keep([sid for sid, *_ in found], now)
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


def reader(radio: ModuleType, row: dict, sid: str, name: str, marks: Marks, acked: dict[str, float], sighted: dict[tuple[str, float], float | None]) -> dict | None:
    prompt, state = marks
    if not radio.seen(row, name, sid, radio.NEVER if prompt is None else prompt, state, radio.NEVER):
        return None
    if sid in acked:
        return {"session": sid, "name": name, "read": acked[sid], "approximate": False}
    when = sighted.get((sid, epoch(row["ts"])))
    return {"session": sid, "name": name, "read": when, "approximate": when is not None}


def order(entry: dict) -> tuple:
    return entry["read"] is None, entry["read"] or 0.0, entry["name"], entry["session"]


def readers_and_acks(radio: ModuleType, news: list[dict], window: tuple[float, float], marks: dict[str, Marks], directory: Directory, sighted: dict[tuple[str, float], float | None]) -> dict[float, dict]:
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
        sighted: ReceiptReads.listed(), per (session id, row ts) the first
            sighting pass that found a mark covering the row.

    Returns:
        Per row ts {"readers": [{"session", "name", "read", "approximate"}],
        "acks": [session ids]}: acks the sessions with a receipt whose call is
        that ts; read the first such receipt's ts, else its sighting with
        approximate true, else None, never a mark, which holds a send time.
        A ts more than one row carries gets no entry: radio.py never stores
        two rows at one ts, so a row appended with a genuine ts can neither
        replace nor lend its readers and acks.
    """
    begin, end = window
    rows = [row for row in news if epoch(row.get("ts")) is not None]
    shared = {ts for ts, count in Counter(epoch(row["ts"]) for row in rows).items() if count > 1}
    acks = acknowledged(radio, rows, set(marks), directory)
    reach = {sid: max(radio.NEVER if prompt is None else prompt, radio.NEVER, *state.values()) for sid, (prompt, state) in marks.items()}
    found = {}
    for row in rows:
        ts = epoch(row["ts"])
        if radio.kind(row) == RECEIPT or not begin <= ts <= end or ts in shared:
            continue
        acked = acks.get(ts, {})
        readers = [entry for sid, held in marks.items() if ts <= reach[sid] and (entry := reader(radio, row, sid, directory.at(sid, ts) or sid, held, acked, sighted))]
        found[ts] = {"readers": sorted(readers, key=order), "acks": sorted(acked)}
    return found


def inline(skills: Path, council: Path, store: ReceiptNames, reads: ReceiptReads, snapshot: Path, news: list[dict], window: tuple[float, float], now: float) -> dict[float, dict]:
    """Args:
        skills: the installed skills directory, for radio_module().
        council: the council directory holding the seen marks.
        store: the hub's receipt name store, NAMES in its state directory.
        reads: the hub's read time store, READS in its state directory.
        snapshot: agent-sessions.json, the host's session snapshot.
        news: every news.jsonl row.
        window: (begin, end) of the rows the hub serves.
        now: the moment to judge at.

    Returns:
        readers_and_acks() of the rows; empty while radio.py is missing or
        its seen() does not take SEEN_PARAMETERS.
    """
    radio = radio_module(skills)
    if radio is None:
        return {}
    directory = session_directory(store, read_snapshot(snapshot, now), now)
    return readers_and_acks(radio, news, window, read_marks(council, now), directory, reads.listed(now))


def read_of(inlined: dict[float, dict], ts: float | None) -> dict:
    return inlined.get(ts, {"readers": [], "acks": []})


def sighting_pass(skills: Path, council: Path, store: ReceiptNames, reads: ReceiptReads, snapshot: Path, window: float, now: float) -> None:
    """Args:
        skills: the installed skills directory, for radio_module().
        council: the council directory with news.jsonl and the seen marks.
        store: the hub's receipt name store; the pass records the snapshot's
            names in it, so a session that left before the next state build
            keeps its name.
        reads: the hub's read time store; the pass records each row of the
            last window seconds a mark newly covers.
        snapshot: agent-sessions.json, which the host rewrites every 15
            seconds; a pass without a fresh one or without radio_module()
            counts as one that did not look.
        window: seconds of rows the pass looks at, the hub's radio window.
        now: the moment of the pass.
    """
    sessions = fresh_snapshot(snapshot, now)
    directory = session_directory(store, sessions or {}, now)
    radio = radio_module(skills)
    if radio is None:
        reads.see(set(), now, now - window, False)
        return
    found = readers_and_acks(radio, read_jsonl(council / NEWS), (now - window, now), read_marks(council, now), directory, {})
    reads.see({(entry["session"], ts) for ts, row in found.items() for entry in row["readers"]}, now, now - window, sessions is not None)


def sight(step: Callable[[float], None], reads: ReceiptReads, stop: threading.Event, every: float) -> None:
    """Args:
        step: one sighting pass, called with its moment; a pass that fails
            for any reason but SystemExit or KeyboardInterrupt logs one line
            to stderr and the next one runs.
        reads: the read time store the passes feed; a failed pass counts as
            one that did not look.
        stop: ends the loop once set.
        every: seconds between two passes.
    """
    while True:
        try:
            step(time.time())
        except Exception as error:  # noqa: BLE001
            reads.blind()
            print(f"receipts: sighting pass failed: {error!r}"[:LOG_CHARS], file=sys.stderr, flush=True)
        if stop.wait(every):
            return
