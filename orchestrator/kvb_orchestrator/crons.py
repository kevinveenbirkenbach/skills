from __future__ import annotations

import os
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .council import agent
from .events import event
from .names import Directory
from .records import epoch, read_json, shown
from .signed import client_module

queue_live = client_module("queue_live", {})

CRON_ACTIVE = 900
TIMER_KEYS = ("OnCalendar", "OnActiveSec", "OnBootSec", "OnStartupSec", "OnUnitActiveSec", "OnUnitInactiveSec")
CRON_LABELS = {"cron": "Cron", "wakeup": "Wakeup", "background": "Background", "timer": "Timer", "queue": "Queue"}
OUTCOME = "hub_outcome"


def cron_state(cron: dict, beats: dict[str, float], now: float) -> dict:
    beat = beats.get(cron["session"])
    alive = cron["deleted"] is None and (cron["until"] is None or cron["until"] > now)
    return {**cron, "active": alive and beat is not None and now - beat < CRON_ACTIVE}


def timer_rows(folder: Path) -> list[dict]:
    try:
        paths = sorted(folder.glob("*.timer"))
    except OSError:
        return []
    rows = []
    for path in paths:
        try:
            lines = [line.strip() for line in path.read_text(encoding="utf-8", errors="replace").splitlines()]
            created = path.stat().st_mtime
        except OSError:
            continue
        pairs = [line.partition("=") for line in lines]
        schedule = [value.strip() for key, _, value in pairs if key.strip() in TIMER_KEYS]
        description = next((value.strip() for key, _, value in pairs if key.strip() == "Description"), "")
        enabled = (folder / "timers.target.wants" / path.name).exists()
        rows.append({
            "key": f"timer:{path.name}", "type": "timer", "session": "", "sub": "", "created": created, "deleted": None, "until": None,
            "job": "", "expression": ", ".join(schedule) or "-", "prompt": description, "reason": path.name, "active": enabled,
        })
    return rows


@dataclass
class History:
    path: Path
    lock: threading.Lock = field(default_factory=threading.Lock)
    cached: list[dict] = field(default_factory=list)
    stamp: tuple[int, int, int] | None = None

    def rows(self) -> list[dict]:
        """Returns:
            queue_live.read_history() of the whole file, parsed again only
            when its inode, size or mtime changed; after a failed read the
            rows read before, and the next call reads again. The list is
            shared, read only.
        """
        with self.lock:
            try:
                info = os.lstat(self.path)
            except FileNotFoundError:
                self.cached, self.stamp = [], None
                return self.cached
            except OSError:
                self.stamp = None
                return self.cached
            stamp = (info.st_ino, info.st_size, info.st_mtime_ns)
            if stamp != self.stamp:
                found = queue_live.read_history(self.path)
                if found is None:
                    self.stamp = None
                else:
                    self.cached, self.stamp = found, stamp
            return self.cached


def outcome_of(entry: dict) -> dict | None:
    found = entry.get(OUTCOME)
    return found if isinstance(found, dict) else None


def queue_entries(council: Path, history: Callable[[], list[dict]]) -> list[tuple[dict, float]]:
    """Args:
        council: the council directory.
        history: returns the queue-history.jsonl rows, History.rows.

    Returns:
        Each entry of queue.json with an enqueue time that queue_live.settled()
        keeps, with that time, as a copy whose OUTCOME is its outcome.
    """
    data = read_json(council / "queue.json")
    entries = data.get("entries") if isinstance(data, dict) else None
    found = []
    for entry in entries if isinstance(entries, list) else []:
        created = epoch(entry.get("enqueued")) if isinstance(entry, dict) else None
        if created is not None:
            found.append((entry, created))
    return [({**entry, OUTCOME: result}, created) for entry, created, result in queue_live.settled(council, found, history)]


def queue_state(entry: dict) -> str:
    found = outcome_of(entry)
    if found is None:
        return "running" if entry.get("status") == "active" else "waiting"
    if found.get("state") == "gone":
        return "holder gone without an exit code"
    code = found.get("exit")
    return "ended" if code is None else f"exit {code}"


def queue_rows(council: Path, history: Callable[[], list[dict]]) -> list[dict]:
    rows = []
    for entry, created in queue_entries(council, history):
        rows.append({
            "key": f"queue:{shown(entry.get('id'))}", "type": "queue", "session": shown(entry.get("session")), "sub": "", "created": created,
            "deleted": None, "until": None, "job": shown(entry.get("id")), "expression": f"{shown(entry.get('kind'))} · {queue_state(entry)}",
            "prompt": shown(entry.get("cmd")), "reason": shown(entry.get("task")), "active": outcome_of(entry) is None, "agent": agent(entry.get("name")),
        })
    return rows


def cron_event(cron: dict, directory: Directory) -> dict:
    text = "\n".join(part for part in (cron["prompt"], cron["reason"]) if part and part != "-")
    return event({
        "id": f"cron:{cron['key']}", "ts": cron["created"], "kind": "cron", "agent": directory.at(cron["session"], cron["created"]) or cron.get("agent", ""),
        "now": directory.now(cron["session"]), "session": cron["session"], "sub": cron["sub"], "title": f"{CRON_LABELS[cron['type']]}: {cron['expression']}", "text": text,
        "ref": {key: cron[key] for key in ("type", "expression", "created", "deleted", "until", "active", "job")},
    })
