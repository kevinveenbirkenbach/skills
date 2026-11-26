from __future__ import annotations

import json
from pathlib import Path

from .errors import ToolError
from .fields import decode
from .records import read_json, write_atomic
from .settings import CLOCK, flag, section

SCHEDULES = "schedules.json"
SCHEDULES_VIEW = "schedules-view.json"
ROWS = {
    "coach": {"on": False, "every": 1},
    "dream": {"on": False, "every": 12},
    "dream-popup": {"on": False, "at": ["17:00"]},
    "queue-cleanup": {"on": True, "at": ["00:00", "12:00"]},
    "code-graph": {"on": True},
}
HOURS = (1, 24)
TIMES_LIMIT = 6
VIEW_LIMIT = 200
VIEW_TEXT = 2000
VIEW_KEYS = ("name", "kind", "owner", "unit", "file", "schedule", "next", "last", "event", "command", "off")


def valid_row(name: object, value: object) -> dict:
    """Args:
        name: one of ROWS.
        value: the row: on, plus every (hours from 1 to 24) for a reminder
            hook or at (1 to TIMES_LIMIT distinct HH:MM) for a timer.

    Returns:
        The row, times sorted.
    """
    if not isinstance(name, str) or name not in ROWS:
        raise ToolError(f"no such schedule: {name}")
    row = section(value, str(name), tuple(ROWS[name]))
    found = {"on": flag(row["on"], f"{name}.on")}
    if "every" in row:
        every = row["every"]
        if isinstance(every, bool) or not isinstance(every, int) or not HOURS[0] <= every <= HOURS[1]:
            raise ToolError(f"{name}.every must be a whole number of hours from {HOURS[0]} to {HOURS[1]}")
        found["every"] = every
    if "at" in row:
        times = row["at"]
        if not isinstance(times, list) or not 1 <= len(times) <= TIMES_LIMIT or not all(isinstance(time, str) and CLOCK.fullmatch(time) for time in times):
            raise ToolError(f"{name}.at must hold 1 to {TIMES_LIMIT} times like 17:00")
        if len(set(times)) != len(times):
            raise ToolError(f"{name}.at names a time twice")
        found["at"] = sorted(times)
    return found


def stored_rows(council: Path) -> dict:
    """Returns:
        Every row of ROWS from schedules.json; a missing, linked or malformed
        file, or a malformed row, gives that row's default.
    """
    data = read_json(council / SCHEDULES)
    rows = {}
    for name, default in ROWS.items():
        try:
            rows[name] = valid_row(name, data[name])
        except (ToolError, KeyError, TypeError):
            rows[name] = default
    return rows


def view_rows(council: Path) -> dict:
    """Returns:
        {at, rows}: what the host reconciler last saw, each row with the
        VIEW_KEYS as strings or numbers; {at: None, rows: []} before its first
        run or for a malformed file.
    """
    data = read_json(council / SCHEDULES_VIEW)
    rows = data.get("rows") if isinstance(data, dict) else None
    at = data.get("at") if isinstance(data, dict) else None
    if not isinstance(rows, list) or isinstance(at, bool) or not isinstance(at, int | float):
        return {"at": None, "rows": []}
    kept = []
    for row in rows[:VIEW_LIMIT]:
        if isinstance(row, dict) and isinstance(row.get("name"), str):
            kept.append({key: shown(row.get(key)) for key in VIEW_KEYS})
    return {"at": at, "rows": kept}


def shown(value: object) -> str | float | None:
    if isinstance(value, str):
        return value[:VIEW_TEXT]
    if isinstance(value, int | float) and not isinstance(value, bool):
        return value
    return None


class Schedules:
    def __init__(self, council: Path) -> None:
        self.council = council

    def view(self) -> dict:
        return {"rows": stored_rows(self.council), "host": view_rows(self.council)}

    def save(self, body: bytes) -> dict:
        """Args:
            body: {row, value}: one row of ROWS and its new value; every
                other row keeps its stored value.
        """
        data = section(decode(body), "body", ("row", "value"))
        rows = {**stored_rows(self.council), data["row"]: valid_row(data["row"], data["value"])}
        self.council.mkdir(parents=True, exist_ok=True)
        write_atomic(self.council / SCHEDULES, json.dumps(rows, sort_keys=True).encode())
        return self.view()
