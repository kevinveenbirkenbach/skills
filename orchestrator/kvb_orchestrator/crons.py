from __future__ import annotations

from pathlib import Path

from .council import agent
from .events import event
from .names import Directory
from .records import epoch, read_json, shown

CRON_ACTIVE = 900
TIMER_KEYS = ("OnCalendar", "OnActiveSec", "OnBootSec", "OnStartupSec", "OnUnitActiveSec", "OnUnitInactiveSec")
CRON_LABELS = {"cron": "Cron", "wakeup": "Wakeup", "background": "Hintergrund", "timer": "Timer", "queue": "Queue"}


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


def queue_entries(council: Path) -> list[tuple[dict, float]]:
    """Returns:
        Each kvb-org-queue entry of queue.json with its enqueue time; an
        entry without one is no entry.
    """
    data = read_json(council / "queue.json")
    entries = data.get("entries") if isinstance(data, dict) else None
    found = []
    for entry in entries if isinstance(entries, list) else []:
        created = epoch(entry.get("enqueued")) if isinstance(entry, dict) else None
        if created is not None:
            found.append((entry, created))
    return found


def queue_rows(council: Path) -> list[dict]:
    rows = []
    for entry, created in queue_entries(council):
        running = "läuft" if entry.get("status") == "active" else "wartet"
        rows.append({
            "key": f"queue:{shown(entry.get('id'))}", "type": "queue", "session": shown(entry.get("session")), "sub": "", "created": created,
            "deleted": None, "until": None, "job": shown(entry.get("id")), "expression": f"{shown(entry.get('kind'))} · {running}",
            "prompt": shown(entry.get("cmd")), "reason": shown(entry.get("task")), "active": True, "agent": agent(entry.get("name")),
        })
    return rows


def cron_event(cron: dict, directory: Directory) -> dict:
    text = "\n".join(part for part in (cron["prompt"], cron["reason"]) if part and part != "-")
    return event({
        "id": f"cron:{cron['key']}", "ts": cron["created"], "kind": "cron", "agent": directory.at(cron["session"], cron["created"]) or cron.get("agent", ""),
        "now": directory.now(cron["session"]), "session": cron["session"], "sub": cron["sub"], "title": f"{CRON_LABELS[cron['type']]}: {cron['expression']}", "text": text,
        "ref": {key: cron[key] for key in ("type", "expression", "created", "deleted", "until", "active", "job")},
    })
