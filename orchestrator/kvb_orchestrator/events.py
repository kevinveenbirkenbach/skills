from __future__ import annotations

import datetime
import json
import re
import secrets
import threading
import time
from collections import deque
from pathlib import Path

from .council import agent
from .errors import ToolError
from .fields import single
from .records import read_jsonl, shown
from .register import status_of
from .transcripts import LOG_KEEP, STREAM_CUT, STREAM_KINDS

KINDS = (
    ("radio", "Radio"), ("review", "Reviews"), ("ask", "Asks"), ("decision", "Decisions"), ("operator", "Operator"), ("register", "Register"),
    ("rename", "Names"), ("cron", "Crons"), ("rule", "Firewall"), ("approval", "Grants"), ("run", "Runner"), ("transcript", "Transcripts"),
)
EVENT_KINDS = tuple(name for name, _ in KINDS)
WORK = [name for name in EVENT_KINDS if name not in ("radio", "transcript")]
VIEWS = {
    "fuer-dich": {"label": "For you", "kinds": ["radio", *WORK], "waiting": True},
    "funk": {"label": "Radio", "kinds": ["radio"], "waiting": False},
    "arbeit": {"label": "Work", "kinds": WORK, "waiting": False},
    "transkripte": {"label": "Transcripts", "kinds": ["transcript"], "waiting": False},
}
KIND_WORDS = {word: name for name, label in KINDS for word in (name, label.lower())}
SPAN = re.compile(r"(\d{1,4})([mhd])")
UNITS = {"m": 60, "h": 3600, "d": 86400}


def event(fields: dict) -> dict:
    return {"part": "", "agent": "", "now": "", "session": "", "sub": "", "text": "", "waiting": False, "ref": {}, **fields}


def since_of(word: str, now: float) -> float:
    span = SPAN.fullmatch(word)
    if span:
        return now - int(span.group(1)) * UNITS[span.group(2)]
    try:
        return datetime.datetime.fromisoformat(word).timestamp()
    except ValueError:
        raise ToolError("since: takes 30m, 2h, 3d or a date like 2026-11-06 or 2026-11-06T08:30") from None


def search(text: str, now: float) -> dict:
    """Args:
        text: the search line: words, `agent:<name>`, `kind:<kind or label>`
            and `since:<span or date>`.
        now: the clock `since:` spans count back from.

    Returns:
        The plain words as `q`, plus `agent`, `kinds` and `since` for each
        token the line holds.
    """
    found: dict = {"q": []}
    for word in text.split():
        key, colon, value = word.partition(":")
        if not colon or key not in ("agent", "kind", "since"):
            found["q"].append(word)
        elif not value:
            raise ToolError(f"{key}: needs a value")
        elif key == "agent":
            found["agent"] = value
        elif key == "kind":
            if value.lower() not in KIND_WORDS:
                raise ToolError(f"kind: takes one of {', '.join(EVENT_KINDS)}")
            found.setdefault("kinds", set()).add(KIND_WORDS[value.lower()])
        else:
            found["since"] = since_of(value, now)
    found["q"] = " ".join(found["q"]).lower()
    return found


def event_filters(query: dict[str, list[str]]) -> dict:
    view = single(query, "view") or ""
    if view:
        if view not in VIEWS:
            raise ToolError(f"view must be one of {', '.join(VIEWS)}")
        kinds, waiting = set(VIEWS[view]["kinds"]), VIEWS[view]["waiting"]
    else:
        listed = single(query, "kinds")
        kinds = set(EVENT_KINDS) if not listed else set(listed.split(","))
        if not kinds <= set(EVENT_KINDS):
            raise ToolError(f"kinds must be a comma list of {', '.join(EVENT_KINDS)}")
        waiting = single(query, "waiting") == "1"
    parts = single(query, "parts")
    chosen = set(STREAM_KINDS) if not parts else set(parts.split(","))
    if not chosen <= set(STREAM_KINDS):
        raise ToolError(f"parts must be a comma list of {', '.join(STREAM_KINDS)}")
    texts = {name: single(query, name) or "" for name in ("agent", "session", "sub")}
    line = search(single(query, "q") or "", time.time())
    texts["agent"] = line.get("agent", texts["agent"])
    kinds &= line.get("kinds", kinds)
    return {"kinds": kinds, "waiting": waiting, "parts": chosen, "q": line["q"], "since": line.get("since"), "aliases": set(), **texts}


def wanted(entry: dict, filters: dict) -> bool:
    return all(
        (
            entry["kind"] in filters["kinds"],
            filters["since"] is None or entry["ts"] >= filters["since"],
            not filters["waiting"] or entry["waiting"],
            not filters["agent"] or entry["agent"] == filters["agent"] or entry["session"] in filters["aliases"],
            not filters["session"] or entry["session"] == filters["session"],
            not filters["sub"] or entry["sub"] == filters["sub"],
            entry["kind"] != "transcript" or entry["part"] in filters["parts"],
            not filters["q"] or filters["q"] in f"{entry['title']}\n{entry['text']}".lower(),
        )
    )


def described(value: object) -> str:
    if value is None or isinstance(value, str | int | float | bool):
        return shown(value)
    return "…"


def register_changes(before: dict[str, dict], after: dict[str, dict], now: float) -> list[dict]:
    found = []
    for task in sorted(set(before) | set(after)):
        old, new = before.get(task), after.get(task)
        if old == new:
            continue
        if old is None or new is None:
            row = new if old is None else old
            change = f"new: {shown(row.get('title'))}" if old is None else "removed"
        else:
            keys = sorted(key for key in set(old) | set(new) if old.get(key) != new.get(key))
            change = "; ".join(f"{key}: {described(old.get(key))} → {described(new.get(key))}" for key in keys)
        row = new if new is not None else old
        found.append(event({
            "id": f"register:{task}:{now}", "ts": now, "kind": "register", "agent": agent(row.get("worker")),
            "title": task, "text": change[:STREAM_CUT], "ref": {"task": task, "status": status_of(row)},
        }))
    return found


class Watch:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.last: dict[str, dict] | None = None
        self.seen: dict[str, float] = {}
        self.changes: deque[dict] = deque(maxlen=LOG_KEEP)

    def see(self, tasks: dict[str, dict], now: float) -> None:
        with self.lock:
            for task in tasks:
                self.seen.setdefault(task, now)
            if self.last is not None and self.last != tasks:
                self.changes.extend(register_changes(self.last, tasks, now))
            self.last = json.loads(json.dumps(tasks))

    def first(self, task: str, now: float) -> float:
        with self.lock:
            return self.seen.get(task, now)

    def listed(self) -> list[dict]:
        with self.lock:
            return list(self.changes)


class Log:
    def __init__(self, file: Path) -> None:
        self.file = file
        self.lock = threading.Lock()
        self.rows: deque[dict] = deque(read_jsonl(file)[-LOG_KEEP:], maxlen=LOG_KEEP)

    def add(self, row: dict) -> dict:
        entry = event({**row, "id": f"{row['kind']}:{secrets.token_hex(8)}", "ts": time.time()})
        with self.lock:
            self.rows.append(entry)
            with self.file.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry) + "\n")
        return entry

    def listed(self) -> list[dict]:
        with self.lock:
            return list(self.rows)
