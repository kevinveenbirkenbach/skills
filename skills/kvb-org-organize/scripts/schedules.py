#!/usr/bin/env python3
"""Usage:
    schedules.py check ROW
    schedules.py set ROW [--on | --off] [--every HOURS] [--at HH:MM ...]
    schedules.py view [--timers FILE] [--settings FILE] [--units DIR]
    schedules.py apply [--units DIR]
    schedules.py run

Args:
    check: exit 0 while ROW is on, printing its hours for a reminder hook;
        OFF (3) while it is off. A missing, linked or malformed schedules.json
        or row gives the row's default.
    set: change ROW in schedules.json, keep every other row, print ROW.
    view: print every user timer and every hook command of the settings file
        as JSON rows: name, kind, owner (skills for the rows of ROWS, hub for
        kvb-orchestrator-* units, other), unit, file, schedule, next and last
        run in epoch seconds, event, command and off, the command that
        switches a foreign row off.
    apply: switch the units of ROWS to their rows: the drop-in
        DIR/<timer>.d/schedule.conf for a retime, then enable --now or
        disable --now where the unit's state differs. A foreign or hub unit
        is never named.
    run: view into schedules-view.json, then apply; kvb-schedules.path and
        kvb-schedules.timer start it.
    ROW: one of ROWS.
    --timers: a systemctl --user list-timers --all --output=json answer;
        systemctl is asked when left out.
    --settings: the Claude Code settings file, ~/.claude/settings.json unless
        given.
    --units: the systemd user unit directory, ~/.config/systemd/user unless
        given.

Environment:
    AGENTS_COUNCIL_ROOT, XDG_STATE_HOME, HOME: the council directory
        councilroot.py resolves; the hub's Schedules tab writes
        schedules.json into it.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

SCHEDULES = "schedules.json"
SCHEDULES_VIEW = "schedules-view.json"
ROWS = {
    "coach": {"on": False, "every": 1},
    "dream": {"on": False, "every": 12},
    "dream-popup": {"on": False, "at": ["17:00"]},
    "queue-cleanup": {"on": True, "at": ["00:00", "12:00"]},
    "code-graph": {"on": True},
}
UNITS = {"dream-popup": "kvb-dream-notify.timer", "queue-cleanup": "kvb-org-queue-cleanup.timer", "code-graph": "kvb-code-graph.service"}
HOOKS = {"coach": "/kvb-coach/hooks/reminder.sh", "dream": "/kvb-dream/hooks/reminder.sh"}
HUB_PREFIX = "kvb-orchestrator-"
HOURS = (1, 24)
TIMES_LIMIT = 6
CLOCK = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]")
TIMER_KEYS = ("OnCalendar", "OnActiveSec", "OnBootSec", "OnStartupSec", "OnUnitActiveSec", "OnUnitInactiveSec")
SEARCHED = (Path("/etc/systemd/user"), Path("/usr/lib/systemd/user"))
DROP_IN = "schedule.conf"
SWITCHED = ("enabled", "disabled")
SYSTEMCTL = ("systemctl", "--user")
RUN_TIMEOUT = 60
MICRO = 1_000_000
FILE_MODE = 0o600
OFF = 3

Runner = Callable[[list[str]], tuple[int, str]]


def sibling(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"kvb_schedules_{name}", Path(__file__).resolve().parent / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def valid_row(name: str, value: object) -> dict:
    """Args:
        name: one of ROWS.
        value: the row, with exactly the keys of its ROWS default.

    Returns:
        The row, times sorted; ValueError when malformed.
    """
    default = ROWS[name]
    if not isinstance(value, dict) or set(value) != set(default) or not isinstance(value["on"], bool):
        raise ValueError(f"{name} must hold exactly {', '.join(sorted(default))}")
    found = {"on": value["on"]}
    if "every" in default:
        every = value["every"]
        if isinstance(every, bool) or not isinstance(every, int) or not HOURS[0] <= every <= HOURS[1]:
            raise ValueError(f"{name}.every must be a whole number of hours from {HOURS[0]} to {HOURS[1]}")
        found["every"] = every
    if "at" in default:
        times = value["at"]
        if not isinstance(times, list) or not 1 <= len(times) <= TIMES_LIMIT or not all(isinstance(item, str) and CLOCK.fullmatch(item) for item in times):
            raise ValueError(f"{name}.at must hold 1 to {TIMES_LIMIT} times like 17:00")
        if len(set(times)) != len(times):
            raise ValueError(f"{name}.at names a time twice")
        found["at"] = sorted(times)
    return found


def stored(root: Path) -> dict:
    try:
        data = json.loads(sibling("nofollow").read_text(root, root / SCHEDULES))
    except (OSError, ValueError):
        data = {}
    rows = {}
    for name, default in ROWS.items():
        try:
            rows[name] = valid_row(name, data[name])
        except (ValueError, KeyError, TypeError):
            rows[name] = default
    return rows


def write(root: Path, name: str, data: object) -> None:
    sibling("nofollow").replace(root, root / name, json.dumps(data, sort_keys=True), FILE_MODE)


def changed(row: dict, on: bool | None, every: int | None, at: list[str] | None) -> dict:
    found = dict(row)
    for key, value in (("on", on), ("every", every), ("at", at)):
        if value is not None:
            if key not in found:
                raise ValueError(f"this row takes no --{key}")
            found[key] = value
    return found


def unit_file(units: Path, unit: str) -> Path | None:
    return next((folder / unit for folder in (units, *SEARCHED) if (folder / unit).is_file()), None)


def schedule_of(path: Path | None) -> str:
    """Returns:
        The timer settings of the unit file and its drop-ins in order; an
        empty assignment resets the ones before it, as systemd reads them.
    """
    if path is None:
        return ""
    found: list[str] = []
    drop_ins = sorted(path.with_name(f"{path.name}.d").glob("*.conf"))
    for file in (path, *drop_ins):
        try:
            lines = file.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            key, sign, value = line.strip().partition("=")
            if sign and key.strip() in TIMER_KEYS:
                value = value.strip()
                found = [item for item in found if not item.startswith(f"{key.strip()}=")] if not value else [*found, f"{key.strip()}={value}"]
    return "; ".join(found)


def epoch(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        return None
    return value / MICRO


def owner_of(unit: str) -> str:
    if unit in UNITS.values():
        return "skills"
    return "hub" if unit.startswith(HUB_PREFIX) else "other"


def timer_rows(timers: object, units: Path) -> list[dict]:
    rows = []
    for entry in timers if isinstance(timers, list) else []:
        unit = entry.get("unit") if isinstance(entry, dict) else None
        if not isinstance(unit, str) or not unit:
            continue
        path = unit_file(units, unit)
        owner = owner_of(unit)
        rows.append({
            "name": unit, "kind": "timer", "owner": owner, "unit": unit, "file": str(path or ""), "schedule": schedule_of(path),
            "next": epoch(entry.get("next")), "last": epoch(entry.get("last")), "event": "", "command": "",
            "off": f"systemctl --user disable --now {unit}" if owner == "other" else "",
        })
    return rows


def hook_rows(settings: Path) -> list[dict]:
    try:
        hooks = json.loads(settings.read_text(encoding="utf-8")).get("hooks")
    except (OSError, ValueError, AttributeError):
        return []
    rows = []
    for event, groups in hooks.items() if isinstance(hooks, dict) else []:
        for group in groups if isinstance(groups, list) else []:
            for hook in group.get("hooks", []) if isinstance(group, dict) else []:
                command = hook.get("command") if isinstance(hook, dict) else None
                if not isinstance(command, str):
                    continue
                mine = next((name for name, script in HOOKS.items() if script in command), None)
                rows.append({
                    "name": mine or f"{event} hook", "kind": "hook", "owner": "skills" if mine else "other", "unit": "", "file": str(settings),
                    "schedule": event, "next": None, "last": None, "event": event, "command": command,
                    "off": "" if mine else f"remove it from hooks.{event} in {settings}",
                })
    return rows


def run_command(argv: list[str]) -> tuple[int, str]:
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=RUN_TIMEOUT, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""
    return done.returncode, done.stdout


def listed_timers(run: Runner) -> object:
    code, out = run([*SYSTEMCTL, "list-timers", "--all", "--output=json"])
    try:
        return json.loads(out) if code == 0 else []
    except ValueError:
        return []


def view(timers: object, settings: Path, units: Path) -> list[dict]:
    return timer_rows(timers, units) + hook_rows(settings)


def drop_in(units: Path, unit: str, times: list[str]) -> bool:
    """Returns:
        True when DIR/<unit>.d/schedule.conf changed: OnCalendar reset, then
        one daily OnCalendar per time.
    """
    path = units / f"{unit}.d" / DROP_IN
    text = "[Timer]\nOnCalendar=\n" + "".join(f"OnCalendar=*-*-* {item}:00\n" for item in times)
    try:
        if path.read_text(encoding="utf-8") == text:
            return False
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{DROP_IN}.{os.getpid()}")
    temp.write_text(text, encoding="utf-8")
    temp.replace(path)
    return True


def apply(rows: dict, run: Runner, units: Path) -> list[str]:
    """Returns:
        The systemctl calls made, without the state queries.
    """
    calls = []
    retimed = [unit for name, unit in UNITS.items() if "at" in rows[name] and unit_file(units, unit) and drop_in(units, unit, rows[name]["at"])]
    if retimed:
        calls.append([*SYSTEMCTL, "daemon-reload"])
        calls += [[*SYSTEMCTL, "try-restart", unit] for unit in retimed]
    for call in calls:
        run(call)
    for name, unit in UNITS.items():
        state = run([*SYSTEMCTL, "is-enabled", unit])[1].strip()
        if state in SWITCHED and rows[name]["on"] != (state == "enabled"):
            call = [*SYSTEMCTL, "enable" if rows[name]["on"] else "disable", "--now", unit]
            run(call)
            calls.append(call)
    return [" ".join(call[2:]) for call in calls]


def parsed(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="schedules.py", add_help=False)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check").add_argument("row", choices=ROWS)
    setter = commands.add_parser("set")
    setter.add_argument("row", choices=ROWS)
    switch = setter.add_mutually_exclusive_group()
    switch.add_argument("--on", dest="on", action="store_const", const=True)
    switch.add_argument("--off", dest="on", action="store_const", const=False)
    setter.add_argument("--every", type=int)
    setter.add_argument("--at", nargs="+")
    viewer = commands.add_parser("view")
    viewer.add_argument("--timers", type=Path)
    viewer.add_argument("--settings", type=Path, default=Path.home() / ".claude" / "settings.json")
    viewer.add_argument("--units", type=Path, default=Path.home() / ".config" / "systemd" / "user")
    commands.add_parser("apply").add_argument("--units", type=Path, default=Path.home() / ".config" / "systemd" / "user")
    commands.add_parser("run")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    try:
        args = parsed(argv)
    except SystemExit:
        print(__doc__, file=sys.stderr)
        return 2
    root = sibling("councilroot").root()
    if args.command == "check":
        row = stored(root)[args.row]
        if not row["on"]:
            return OFF
        if "every" in row:
            print(row["every"])
        return 0
    if args.command == "set":
        rows = stored(root)
        try:
            rows[args.row] = valid_row(args.row, changed(rows[args.row], args.on, args.every, args.at))
        except ValueError as error:
            print(f"schedules.py: {error}", file=sys.stderr)
            return 2
        write(root, SCHEDULES, rows)
        print(json.dumps(rows[args.row], sort_keys=True))
        return 0
    settings = Path.home() / ".claude" / "settings.json"
    units = getattr(args, "units", Path.home() / ".config" / "systemd" / "user")
    if args.command == "view":
        timers = json.loads(args.timers.read_text(encoding="utf-8")) if args.timers else listed_timers(run_command)
        print(json.dumps(view(timers, args.settings, units), indent=2))
        return 0
    if args.command == "run":
        write(root, SCHEDULES_VIEW, {"at": time.time(), "rows": view(listed_timers(run_command), settings, units)})
    for call in apply(stored(root), run_command, units):
        print(call)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
