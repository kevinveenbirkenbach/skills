from __future__ import annotations

import json
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

EVENT_KINDS = ("radio", "review", "ask", "decision", "operator", "register", "rename", "cron", "rule", "approval", "run", "transcript")
VIEWS = {
    "fuer-dich": {"label": "Für dich", "kinds": list(EVENT_KINDS[:-1]), "waiting": True},
    "reviews": {"label": "Reviews", "kinds": ["review"], "waiting": False},
    "asks": {"label": "Asks", "kinds": ["ask"], "waiting": False},
    "entscheidungen": {"label": "Entscheidungen", "kinds": ["decision"], "waiting": False},
    "operator": {"label": "Operator", "kinds": ["operator", "run"], "waiting": False},
    "register": {"label": "Register", "kinds": ["register", "rename"], "waiting": False},
    "radio": {"label": "Radio", "kinds": ["radio"], "waiting": False},
    "crons": {"label": "Crons", "kinds": ["cron"], "waiting": False},
}


def event(fields: dict) -> dict:
    return {"part": "", "agent": "", "now": "", "session": "", "sub": "", "text": "", "waiting": False, "ref": {}, **fields}


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
    return {"kinds": kinds, "waiting": waiting, "parts": chosen, "q": (single(query, "q") or "").lower(), "aliases": set(), **texts}


def wanted(entry: dict, filters: dict) -> bool:
    return all(
        (
            entry["kind"] in filters["kinds"],
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
            change = f"neu: {shown(row.get('title'))}" if old is None else "entfernt"
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
