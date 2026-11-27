from __future__ import annotations

import bisect
import itertools
import json
import math
import re
import threading
from pathlib import Path

from .council import HUMAN, agent
from .events import event
from .records import read_json, write_atomic
from .transcripts import STREAM_AGE

PSEUDO = "name:"
TITLE_SCAN = 10.0
SESSION_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")


class Directory:
    def __init__(self, entries: list[dict]) -> None:
        self.by_session: dict[str, list[dict]] = {}
        self.by_name: dict[str, list[str]] = {}
        for entry in entries:
            self.by_session.setdefault(entry["session"], []).append(entry)
            holders = self.by_name.setdefault(entry["name"], [])
            if entry["session"] in holders:
                holders.remove(entry["session"])
            holders.append(entry["session"])
        self.times = {session: [entry["first_seen"] for entry in own] for session, own in self.by_session.items()}

    def at(self, session: str, ts: float) -> str:
        own = self.by_session.get(session)
        if not own:
            return ""
        index = bisect.bisect_right(self.times[session], ts)
        return own[index - 1 if index else 0]["name"]

    def now(self, session: str) -> str:
        own = self.by_session.get(session)
        return own[-1]["name"] if own else ""

    def find(self, name: str, ts: float) -> str:
        holders = self.by_name.get(name, [])
        real = [session for session in holders if not session.startswith(PSEUDO)]
        valid = [session for session in real if self.at(session, ts) == name]
        chosen = valid or real or holders
        return chosen[-1] if chosen else ""

    def key(self, name: str, ts: float) -> str:
        if not name or name == HUMAN:
            return name
        return self.find(name, ts) or f"{PSEUDO}{name}"

    def label(self, key: str, ts: float) -> str:
        return self.at(key, ts) or key.removeprefix(PSEUDO)

    def names(self, key: str) -> list[str]:
        return list(dict.fromkeys(entry["name"] for entry in self.by_session.get(key, [])))

    def timeline(self, key: str, begin: float | None = None) -> list[dict]:
        """Args:
            key: the session.
            begin: when given, the names between the first one and the last
                one seen at or before begin are left out; the first stays as
                the session's birth.
        """
        own = self.by_session.get(key, [])
        if begin is not None and own:
            start = bisect.bisect_right(self.times[key], begin) - 1
            own = own[:1] + own[max(start, 1):]
        return [{"name": entry["name"], "since": entry["first_seen"]} for entry in own]

    def aliases(self, name: str) -> set[str]:
        return set(self.by_name.get(name, []))

    def renames(self, begin: float, end: float) -> list[dict]:
        found = []
        shown = set()
        for session, own in self.by_session.items():
            for before, after in itertools.pairwise(own):
                pair = (session, before["name"], after["name"])
                if before["name"] == after["name"] or pair in shown:
                    continue
                shown.add(pair)
                if begin <= after["first_seen"] <= end:
                    found.append(event({
                        "id": f"rename:{session}:{after['first_seen']}", "ts": after["first_seen"], "kind": "rename", "agent": after["name"],
                        "now": self.now(session), "session": session, "title": f"{before['name']} is now called {after['name']}",
                        "text": f"Source: {after['source']}", "ref": {"before": before["name"], "after": after["name"], "source": after["source"]},
                    }))
        return found


def kept(entries: list[dict], indexes: list[int]) -> list[int]:
    """Args:
        entries: every entry.
        indexes: the positions of one session's entries, in order.

    Returns:
        The positions of the first and the last entry of each name, of the
        first entry of each rename with the entry before it, and of every
        predecessor needed until two kept neighbours that were apart form a
        rename the session showed before; so the kept entries show the same
        renames at the same moments.
    """
    names = [entries[index]["name"] for index in indexes]
    first: dict[tuple[str, str], int] = {}
    seen: dict[str, int] = {}
    last: dict[str, int] = {}
    for position, name in enumerate(names):
        seen.setdefault(name, position)
        last[name] = position
        if position:
            first.setdefault((names[position - 1], name), position)
    keep = {*seen.values(), *last.values()}
    keep |= {near for position in first.values() for near in (position - 1, position)}
    while apart := unshown(names, first, keep):
        keep.update(later - 1 for later in apart)
    return [indexes[position] for position in sorted(keep)]


def unshown(names: list[str], first: dict[tuple[str, str], int], keep: set[int]) -> list[int]:
    """Returns:
        Each kept position whose kept neighbour before it was not its
        predecessor and forms a rename the session first showed later or
        never.
    """
    return [later for earlier, later in itertools.pairwise(sorted(keep))
            if later - earlier > 1 and names[earlier] != names[later] and first.get((names[earlier], names[later]), later + 1) > later]


def compacted(entries: list[dict]) -> list[dict]:
    """Returns:
        The entries in order without the repeats of a name flip-flop, by
        kept() per session.
    """
    by_session: dict[str, list[int]] = {}
    for index, entry in enumerate(entries):
        by_session.setdefault(entry["session"], []).append(index)
    keep = {index for indexes in by_session.values() for index in kept(entries, indexes)}
    return [entries[index] for index in sorted(keep)]


def valid_entry(entry: object) -> bool:
    if not isinstance(entry, dict) or set(entry) != {"session", "name", "first_seen", "source"}:
        return False
    texts = all(isinstance(entry[key], str) and entry[key] for key in ("session", "name", "source"))
    moment = entry["first_seen"]
    return texts and isinstance(moment, int | float) and not isinstance(moment, bool) and math.isfinite(moment)


class Names:
    def __init__(self, file: Path) -> None:
        """Args:
            file: the store; an entry or an observed name of the wrong shape
                or type is left out.
        """
        self.file = file
        self.lock = threading.Lock()
        self.titled = -math.inf
        data = read_json(file)
        self.data = data if isinstance(data, dict) else {}
        entries, observed = self.data.get("entries"), self.data.get("observed")
        valid = [entry for entry in entries if valid_entry(entry)] if isinstance(entries, list) else []
        self.entries = compacted(valid)
        self.observed: dict[str, str] = {key: name for key, name in observed.items() if isinstance(name, str)} if isinstance(observed, dict) else {}
        self.version = 0
        self.cached: tuple[int, Directory] | None = None
        if len(self.entries) < len(valid):
            self.save()

    def payload(self) -> dict:
        return {"entries": self.entries, "observed": self.observed}

    def save(self) -> None:
        write_atomic(self.file, json.dumps(self.payload(), sort_keys=True).encode("utf-8"))

    def observe(self, sightings: list[tuple[str, str, float | None, str]], now: float) -> None:
        """Args:
            sightings: (session, name, seen, source); of several sightings of
                one session from one source only the newest counts, so two
                claims under different names cannot flip the name back and
                forth on every state build.
        """
        newest: dict[tuple[str, str], tuple[str, str, float | None, str]] = {}
        for sighting in sightings:
            key = (sighting[0], sighting[3])
            if key not in newest or (sighting[2] or -math.inf) >= (newest[key][2] or -math.inf):
                newest[key] = sighting
        with self.lock:
            changed = False
            for session, name, seen, source in newest.values():
                key = f"{session}\x00{source}"
                if not session or not name or self.observed.get(key) == name:
                    continue
                self.observed[key] = name
                changed = True
                history = [entry for entry in self.entries if entry["session"] == session]
                if history and history[-1]["name"] == name:
                    continue
                floor = history[-1]["first_seen"] if history else -math.inf
                first = seen if seen is not None and seen > floor else max(now, floor)
                self.entries.append({"session": session, "name": name, "first_seen": first, "source": source})
                self.version += 1
            if changed:
                self.entries = compacted(self.entries)
                self.save()

    def listed(self) -> list[dict]:
        with self.lock:
            return [dict(entry) for entry in self.entries]

    def directory(self) -> Directory:
        """Returns:
            The Directory of the current entries, rebuilt only after observe()
            added one; it shares the entry dicts, which nothing mutates.
        """
        with self.lock:
            if self.cached is None or self.cached[0] != self.version:
                self.cached = (self.version, Directory(list(self.entries)))
            return self.cached[1]

    def due(self, now: float) -> bool:
        with self.lock:
            if now - self.titled < TITLE_SCAN:
                return False
            self.titled = now
            return True


def title_sightings(root: Path, claimed: set[str], now: float) -> list[tuple[str, str, float | None, str]]:
    try:
        paths = sorted(root.glob("*/*/custom-title.json"))
    except OSError:
        return []
    found = []
    for path in paths:
        session = path.parent.name
        try:
            changed = path.stat().st_mtime
        except OSError:
            continue
        if not SESSION_ID.fullmatch(session) or (session not in claimed and changed < now - STREAM_AGE):
            continue
        data = read_json(path)
        name = agent(data.get("customTitle") if isinstance(data, dict) else None)
        if name:
            found.append((session, name, changed, "title"))
    return found
