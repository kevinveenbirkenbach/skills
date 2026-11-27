from __future__ import annotations

import json
import re
from pathlib import Path

from .errors import ToolError, Unsigned
from .records import read_json, write_atomic
from .settings import CLOCK, flag, section
from .signed import signing

SCHEDULES = "schedules.json"
SCHEDULES_VIEW = "schedules-view.json"
ROWS = {
    "coach": {"on": False, "every": 1},
    "dream": {"on": False, "every": 12},
    "dream-popup": {"on": False, "at": ["17:00"]},
    "queue-cleanup": {"on": True, "at": ["00:00", "12:00"]},
    "code-graph": {"on": True},
}
UNITS_KEY = "units"
HUB_UNIT = re.compile(r"kvb-orchestrator-[a-z0-9-]{1,64}\.timer")
HOURS = (1, 24)
TIMES_LIMIT = 6
VIEW_LIMIT = 500
VIEW_TEXT = 2000
VIEW_KEYS = ("name", "source", "kind", "unit", "file", "task", "schedule", "next", "last", "on", "dropin", "error", "command")
CRON_FIELDS = (("minute", 0, 59), ("hour", 0, 23), ("day of month", 1, 31), ("month", 1, 12), ("day of week", 0, 6))
CRON_PART = re.compile(r"(?:\*|([0-9]{1,2})(?:-([0-9]{1,2}))?)(?:/([0-9]{1,2}))?")


def timing(name: str, row: dict) -> dict:
    """Args:
        name: the row or unit, for the errors.
        row: a timer row with at (1 to TIMES_LIMIT distinct HH:MM) or
            calendar (an OnCalendar expression signing.SCHEDULE_CALENDAR
            matches), not both.

    Returns:
        {at} with the times sorted, or {calendar}.
    """
    if "at" in row and "calendar" in row:
        raise ToolError(f"{name} takes at or calendar, not both")
    if "calendar" in row:
        calendar = row["calendar"]
        if not isinstance(calendar, str) or not signing.SCHEDULE_CALENDAR.fullmatch(calendar):
            raise ToolError(f"{name}.calendar must be an OnCalendar expression of letters, digits, spaces and * : , . / ~ _ + -")
        return {"calendar": calendar}
    times = row["at"]
    if not isinstance(times, list) or not 1 <= len(times) <= TIMES_LIMIT or not all(isinstance(time, str) and CLOCK.fullmatch(time) for time in times):
        raise ToolError(f"{name}.at must hold 1 to {TIMES_LIMIT} times like 17:00")
    if len(set(times)) != len(times):
        raise ToolError(f"{name}.at names a time twice")
    return {"at": sorted(times)}


def valid_row(name: object, value: object) -> dict:
    """Args:
        name: one of ROWS.
        value: the row: on, plus every (hours from 1 to 24) for a reminder
            hook, or at or calendar (timing()) for a timer.

    Returns:
        The row, times sorted.
    """
    if not isinstance(name, str) or name not in ROWS:
        raise ToolError(f"no such schedule: {name}")
    default = ROWS[name]
    calendar = "at" in default and isinstance(value, dict) and "calendar" in value
    row = section(value, name, ("on", "calendar") if calendar else tuple(default))
    found = {"on": flag(row["on"], f"{name}.on")}
    if "every" in row:
        every = row["every"]
        if isinstance(every, bool) or not isinstance(every, int) or not HOURS[0] <= every <= HOURS[1]:
            raise ToolError(f"{name}.every must be a whole number of hours from {HOURS[0]} to {HOURS[1]}")
        found["every"] = every
    if "at" in default:
        found.update(timing(name, row))
    return found


def valid_unit(unit: object, value: object) -> dict:
    """Args:
        unit: a hub timer HUB_UNIT matches; any other text is a System timer
            or a Claude task, which takes the signed route.
        value: on, plus at or calendar (timing()) for a retime; without
            them the reconciler removes the unit's drop-in.

    Returns:
        The override, times sorted.
    """
    if not isinstance(unit, str):
        raise ToolError("unit must be a text")
    if not HUB_UNIT.fullmatch(unit):
        raise Unsigned(f"{unit} is no kvb-orchestrator- timer: a System timer or a Claude task needs the passkey")
    keys = ("on", *(key for key in ("at", "calendar") if isinstance(value, dict) and key in value))
    row = section(value, unit, keys)
    found = {"on": flag(row["on"], f"{unit}.on")}
    return {**found, **timing(unit, row)} if len(keys) > 1 else found


def cron_part(part: str, low: int, high: int) -> bool:
    found = CRON_PART.fullmatch(part)
    if found is None:
        return False
    start, end, step = (None if group is None else int(group) for group in found.groups())
    first = low if start is None else start
    last = high if start is None or (end is None and step is not None) else start if end is None else end
    return low <= first <= last <= high and step != 0


def valid_cron(cron: object) -> str:
    """Returns:
        cron, five fields of `*`, numbers, ranges, lists and steps within
        CRON_FIELDS; ToolError naming the first field out of range.
    """
    if not isinstance(cron, str) or not signing.CRON.fullmatch(cron):
        raise ToolError("cron must be 5 fields of digits and * , / -, like 0 9 * * 1-5")
    for text, (field, low, high) in zip(cron.split(" "), CRON_FIELDS, strict=True):
        if not all(cron_part(part, low, high) for part in text.split(",")):
            raise ToolError(f"cron {field} field {text} must stay within {low} to {high}")
    return cron


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


def stored_units(council: Path) -> dict:
    """Returns:
        The hub timer overrides of schedules.json; a malformed one is left
        out, as the reconciler leaves it alone.
    """
    data = read_json(council / SCHEDULES)
    units = data.get(UNITS_KEY) if isinstance(data, dict) else None
    kept = {}
    for unit, value in units.items() if isinstance(units, dict) else ():
        try:
            kept[unit] = valid_unit(unit, value)
        except (ToolError, Unsigned):
            continue
    return kept


def view_rows(council: Path) -> dict:
    """Returns:
        {at, rows}: what the host reconciler last saw, each row with the
        VIEW_KEYS as texts, numbers or true/false; {at: None, rows: []}
        before its first run or for a malformed file.
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


def shown(value: object) -> str | float | bool | None:
    if isinstance(value, str):
        return value[:VIEW_TEXT]
    if isinstance(value, bool | int | float):
        return value
    return None


class Schedules:
    def __init__(self, council: Path) -> None:
        self.council = council

    def view(self) -> dict:
        return {"rows": stored_rows(self.council), "units": stored_units(self.council), "host": view_rows(self.council)}

    def save(self, payload: object) -> dict:
        """Args:
            payload: {row, value}: one row of ROWS and its new value, or
                {unit, value}: one hub timer and its override (valid_unit());
                every other row and override keeps its stored value.
        """
        if isinstance(payload, dict) and "unit" in payload:
            data = section(payload, "body", ("unit", "value"))
            changed = {UNITS_KEY: {**stored_units(self.council), data["unit"]: valid_unit(data["unit"], data["value"])}}
        else:
            data = section(payload, "body", ("row", "value"))
            changed = {data["row"]: valid_row(data["row"], data["value"])}
        stored = {**stored_rows(self.council), UNITS_KEY: stored_units(self.council), **changed}
        self.council.mkdir(parents=True, exist_ok=True)
        write_atomic(self.council / SCHEDULES, json.dumps(stored, sort_keys=True).encode())
        return self.view()
