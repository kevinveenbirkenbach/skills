from __future__ import annotations

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

    def at(self, session: str, ts: float) -> str:
        own = self.by_session.get(session)
        if not own:
            return ""
        valid = [entry for entry in own if entry["first_seen"] <= ts]
        return (valid[-1] if valid else own[0])["name"]

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

    def timeline(self, key: str) -> list[dict]:
        return [{"name": entry["name"], "since": entry["first_seen"]} for entry in self.by_session.get(key, [])]

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


class Names:
    def __init__(self, file: Path) -> None:
        self.file = file
        self.lock = threading.Lock()
        self.titled = -math.inf
        data = read_json(file)
        data = data if isinstance(data, dict) else {}
        entries, observed = data.get("entries"), data.get("observed")
        keys = {"session", "name", "first_seen", "source"}
        self.entries = [entry for entry in entries if isinstance(entry, dict) and set(entry) == keys] if isinstance(entries, list) else []
        self.observed: dict[str, str] = observed if isinstance(observed, dict) else {}

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
            if changed:
                write_atomic(self.file, json.dumps({"entries": self.entries, "observed": self.observed}, sort_keys=True).encode("utf-8"))

    def listed(self) -> list[dict]:
        with self.lock:
            return [dict(entry) for entry in self.entries]

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
