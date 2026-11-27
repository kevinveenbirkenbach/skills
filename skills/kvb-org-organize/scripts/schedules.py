#!/usr/bin/env python3
"""Usage:
    schedules.py check ROW
    schedules.py set ROW [--on | --off] [--every HOURS] [--at HH:MM ...]
    schedules.py view [--timers FILE] [--units DIR] [--repos DIR]
    schedules.py apply [--units DIR]
    schedules.py run [--units DIR] [--repos DIR]
    schedules.py timer UNIT (--on | --off | --reset | --calendar EXPR | --at HH:MM ...) [--units DIR] [--repos DIR]
    schedules.py cron FILE ID (--cron EXPR | --remove) [--units DIR] [--repos DIR]

Args:
    check: exit 0 while ROW is on, printing its hours for a reminder hook;
        OFF (3) while it is off. A missing, linked or malformed schedules.json
        or row gives the row's default.
    set: change ROW in schedules.json, keep every other row, print ROW.
    view: print one JSON row per schedule of the host: every user timer
        (source skills for the units of ROWS, hub for kvb-orchestrator-*
        units, system for the rest) and every Claude task of a
        .claude/scheduled_tasks.json under the repositories (source
        claude), each with name, source, kind, unit, file, task, schedule,
        next and last run in epoch seconds, on, dropin (a schedule.conf
        exists), error and command (a task's prompt, cut).
    apply: switch the units of ROWS and the hub timers of the units section
        of schedules.json to their rows: the drop-in
        DIR/<timer>.d/schedule.conf for a retime, its removal for a hub
        timer without one, then enable --now or disable --now where the
        unit's state differs. A calendar that systemd-analyze refuses keeps
        the old schedule and becomes the row's error. A System timer is
        never named.
    run: apply, then view into schedules-view.json with apply's errors;
        kvb-schedules.path and kvb-schedules.timer start it.
    timer: one signed change of a System timer, run by the hub runner: on
        or off (enable --now or disable --now), reset (remove its drop-in)
        or a retime (its drop-in), then a view refresh; exit 2 when UNIT is
        unknown, first-party or the calendar is refused.
    cron: one signed change of a Claude task, run by the hub runner: its
        cron replaced, every other byte of FILE kept, or the task removed,
        then a view refresh; exit 2 unless FILE is a task file view lists
        and holds the task ID.
    ROW: one of ROWS.
    --timers: a systemctl --user list-timers --all --output=json answer;
        systemctl is asked when left out.
    --units: the systemd user unit directory, ~/.config/systemd/user unless
        given.
    --repos: the directory holding the repositories, ~/Repositories unless
        given; its task files sit one to three levels below it.

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
UNITS_KEY = "units"
HUB_PREFIX = "kvb-orchestrator-"
HUB_UNIT = re.compile(r"kvb-orchestrator-[a-z0-9-]{1,64}\.timer")
HOURS = (1, 24)
TIMES_LIMIT = 6
CLOCK = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]")
CALENDAR = re.compile(r"(?![ -])[A-Za-z0-9*:,./~_+ -]{1,128}(?<! )")
CRON = re.compile(r"[0-9*,/-]{1,64}(?: [0-9*,/-]{1,64}){4}")
TIMER_KEYS = ("OnCalendar", "OnActiveSec", "OnBootSec", "OnStartupSec", "OnUnitActiveSec", "OnUnitInactiveSec")
SEARCHED = (Path("/etc/systemd/user"), Path("/usr/lib/systemd/user"))
DROP_IN = "schedule.conf"
SWITCHED = ("enabled", "disabled")
OFF_STATES = ("disabled", "masked", "masked-runtime")
SYSTEMCTL = ("systemctl", "--user")
ANALYZE = ("systemd-analyze", "calendar", "--")
TASK_FILE = Path(".claude") / "scheduled_tasks.json"
REPO_DEPTHS = ("*", "*/*", "*/*/*")
LAYOUTS = ({"indent": 2}, {"separators": (",", ":")}, {}, {"indent": 4}, {"indent": "\t"})
PROMPT_SHOWN = 200
RUN_TIMEOUT = 60
MICRO = 1_000_000
MILLI = 1000
FILE_MODE = 0o600
OFF = 3

Runner = Callable[[list[str]], tuple[int, str]]


def sibling(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"kvb_schedules_{name}", Path(__file__).resolve().parent / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def timing(name: str, value: dict) -> dict:
    """Args:
        name: the row or unit, for the errors.
        value: a timer row with at (1 to TIMES_LIMIT distinct HH:MM) or
            calendar (an OnCalendar expression CALENDAR matches), not both.

    Returns:
        {at} with the times sorted, or {calendar}; ValueError when malformed.
    """
    if "at" in value and "calendar" in value:
        raise ValueError(f"{name} takes at or calendar, not both")
    if "calendar" in value:
        if not isinstance(value["calendar"], str) or not CALENDAR.fullmatch(value["calendar"]):
            raise ValueError(f"{name}.calendar must be an OnCalendar expression of letters, digits, spaces and * : , . / ~ _ + -")
        return {"calendar": value["calendar"]}
    times = value["at"]
    if not isinstance(times, list) or not 1 <= len(times) <= TIMES_LIMIT or not all(isinstance(item, str) and CLOCK.fullmatch(item) for item in times):
        raise ValueError(f"{name}.at must hold 1 to {TIMES_LIMIT} times like 17:00")
    if len(set(times)) != len(times):
        raise ValueError(f"{name}.at names a time twice")
    return {"at": sorted(times)}


def valid_row(name: str, value: object) -> dict:
    """Args:
        name: one of ROWS.
        value: the row, with exactly the keys of its ROWS default; a timer
            row may hold calendar in place of at.

    Returns:
        The row, times sorted; ValueError when malformed.
    """
    default = ROWS[name]
    keys = set(default)
    if "at" in default and isinstance(value, dict) and "calendar" in value:
        keys = {"on", "calendar"}
    if not isinstance(value, dict) or set(value) != keys or not isinstance(value["on"], bool):
        raise ValueError(f"{name} must hold exactly {', '.join(sorted(keys))}")
    found = {"on": value["on"]}
    if "every" in default:
        every = value["every"]
        if isinstance(every, bool) or not isinstance(every, int) or not HOURS[0] <= every <= HOURS[1]:
            raise ValueError(f"{name}.every must be a whole number of hours from {HOURS[0]} to {HOURS[1]}")
        found["every"] = every
    if "at" in default:
        found.update(timing(name, value))
    return found


def valid_unit(unit: object, value: object) -> dict:
    """Args:
        unit: a hub timer HUB_UNIT matches.
        value: on, plus at or calendar for a retime.

    Returns:
        The override, times sorted; ValueError when malformed.
    """
    if not isinstance(unit, str) or not HUB_UNIT.fullmatch(unit):
        raise ValueError(f"{unit} is no kvb-orchestrator- timer")
    if not isinstance(value, dict) or not isinstance(value.get("on"), bool) or not set(value) - {"on"} <= {"at", "calendar"}:
        raise ValueError(f"{unit} must hold on and at most at or calendar")
    return {"on": value["on"], **(timing(unit, value) if len(value) > 1 else {})}


def loaded(root: Path) -> object:
    try:
        return json.loads(sibling("nofollow").read_text(root, root / SCHEDULES))
    except (OSError, ValueError):
        return {}


def stored(root: Path) -> dict:
    data = loaded(root)
    rows = {}
    for name, default in ROWS.items():
        try:
            rows[name] = valid_row(name, data[name])
        except (ValueError, KeyError, TypeError):
            rows[name] = default
    return rows


def stored_units(root: Path) -> dict:
    """Returns:
        The hub timer overrides of schedules.json; a malformed one is left
        out and its unit left alone.
    """
    data = loaded(root)
    units = data.get(UNITS_KEY) if isinstance(data, dict) else None
    kept = {}
    for unit, value in units.items() if isinstance(units, dict) else ():
        try:
            kept[unit] = valid_unit(unit, value)
        except ValueError:
            continue
    return kept


def write(root: Path, name: str, data: object) -> None:
    sibling("nofollow").replace(root, root / name, json.dumps(data, sort_keys=True), FILE_MODE)


def changed(row: dict, default: dict, on: bool | None, every: int | None, at: list[str] | None) -> dict:
    found = dict(row)
    for key, value in (("on", on), ("every", every), ("at", at)):
        if value is not None:
            if key not in default:
                raise ValueError(f"this row takes no --{key}")
            found.pop("calendar", None)
            found[key] = value
    return found


def unit_file(units: Path, unit: str) -> Path | None:
    return next((folder / unit for folder in (units, *SEARCHED) if (folder / unit).is_file()), None)


def schedule_of(path: Path | None, units: Path) -> str:
    """Returns:
        The timer settings of the unit file, its drop-ins beside it and its
        drop-ins in the user unit directory, in order; an empty assignment
        resets the ones before it, as systemd reads them.
    """
    if path is None:
        return ""
    found: list[str] = []
    folders = {path.with_name(f"{path.name}.d"), units / f"{path.name}.d"}
    drop_ins = sorted((file for folder in folders for file in folder.glob("*.conf")), key=lambda file: file.name)
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


def epoch(value: object, scale: int) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        return None
    return value / scale


def source_of(unit: str) -> str:
    if unit in UNITS.values():
        return "skills"
    return "hub" if unit.startswith(HUB_PREFIX) else "system"


def enabled_states(names: list[str], run: Runner) -> dict[str, str]:
    """Returns:
        Per unit its `systemctl --user is-enabled` answer, one call for all;
        "" for a unit the answer leaves out.
    """
    if not names:
        return {}
    lines = run([*SYSTEMCTL, "is-enabled", *names])[1].splitlines()
    return {name: lines[index].strip() if index < len(lines) else "" for index, name in enumerate(names)}


def timer_rows(timers: object, units: Path, run: Runner, errors: dict[str, str]) -> list[dict]:
    entries = [entry for entry in timers if isinstance(entry, dict) and isinstance(entry.get("unit"), str) and entry["unit"]] if isinstance(timers, list) else []
    states = enabled_states([entry["unit"] for entry in entries], run)
    rows = []
    for entry in entries:
        unit = entry["unit"]
        path = unit_file(units, unit)
        rows.append({
            "name": unit, "source": source_of(unit), "kind": "timer", "unit": unit, "file": str(path or ""), "task": "", "schedule": schedule_of(path, units),
            "next": epoch(entry.get("next"), MICRO), "last": epoch(entry.get("last"), MICRO), "on": states[unit] not in OFF_STATES,
            "dropin": (units / f"{unit}.d" / DROP_IN).is_file(), "error": errors.get(unit, ""), "command": "",
        })
    return rows


def task_files(repos: Path) -> list[Path]:
    return sorted({path for depth in REPO_DEPTHS for path in repos.glob(f"{depth}/{TASK_FILE}") if path.is_file() and not path.is_symlink()})


def read_tasks(repos: Path, path: Path) -> tuple[str, object, list] | None:
    """Returns:
        (text, data, tasks) of a task file read below repos without
        following a link: tasks the list under "tasks", or data itself when
        it is a list; None when unreadable or of another shape.
    """
    try:
        text = sibling("nofollow").read_text(repos, path)
        data = json.loads(text)
    except (OSError, ValueError):
        return None
    tasks = data.get("tasks") if isinstance(data, dict) else data
    return (text, data, tasks) if isinstance(tasks, list) else None


def task_rows(repos: Path, errors: dict[str, str]) -> list[dict]:
    rows = []
    for path in task_files(repos):
        found = read_tasks(repos, path)
        for task in found[2] if found else []:
            if not isinstance(task, dict) or not isinstance(task.get("id"), str) or not isinstance(task.get("cron"), str):
                continue
            prompt = task.get("prompt") if isinstance(task.get("prompt"), str) else ""
            key = f"{path}#{task['id']}"
            rows.append({
                "name": f"{path.parents[1].name} {task['id']}", "source": "claude", "kind": "cron", "unit": "", "file": str(path), "task": task["id"],
                "schedule": task["cron"], "next": None, "last": epoch(task.get("lastFiredAt"), MILLI), "on": True, "dropin": False,
                "error": errors.get(key, ""), "command": prompt[:PROMPT_SHOWN],
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


def view(timers: object, units: Path, repos: Path, run: Runner, errors: dict[str, str]) -> list[dict]:
    """Args:
        errors: per unit, or per `<file>#<task id>` for a Claude task, the
            error of its last change, shown on its row.
    """
    return timer_rows(timers, units, run, errors) + task_rows(repos, errors)


def drop_in_text(schedule: dict) -> str:
    lines = [f"OnCalendar={schedule['calendar']}"] if "calendar" in schedule else [f"OnCalendar=*-*-* {item}:00" for item in schedule["at"]]
    return "[Timer]\nOnCalendar=\n" + "".join(f"{line}\n" for line in lines)


def drop_in(units: Path, unit: str, schedule: dict) -> bool:
    """Returns:
        True when DIR/<unit>.d/schedule.conf changed: OnCalendar reset, then
        one daily OnCalendar per time or the calendar.
    """
    path = units / f"{unit}.d" / DROP_IN
    text = drop_in_text(schedule)
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


def remove_drop_in(units: Path, unit: str) -> bool:
    path = units / f"{unit}.d" / DROP_IN
    if not path.is_file():
        return False
    path.unlink()
    return True


def calendar_error(schedule: dict, run: Runner) -> str:
    """Returns:
        Why systemd-analyze refuses the calendar of schedule, "" for a
        valid one or daily times.
    """
    if "calendar" not in schedule:
        return ""
    code, _ = run([*ANALYZE, schedule["calendar"]])
    return "" if code == 0 else f"systemd-analyze refuses OnCalendar={schedule['calendar']}; the old schedule stays"


def retimed(units: Path, unit: str, schedule: dict, run: Runner, errors: dict[str, str]) -> bool:
    """Args:
        schedule: {at} or {calendar} to write, or {} to remove the drop-in.

    Returns:
        Whether the drop-in changed; a refused calendar leaves it and goes
        into errors.
    """
    if not schedule:
        return remove_drop_in(units, unit)
    error = calendar_error(schedule, run)
    if error:
        errors[unit] = error
        return False
    return drop_in(units, unit, schedule)


def reload(retimed_units: list[str], run: Runner) -> list[list[str]]:
    calls = [[*SYSTEMCTL, "daemon-reload"], *([*SYSTEMCTL, "try-restart", unit] for unit in retimed_units)] if retimed_units else []
    for call in calls:
        run(call)
    return calls


def switched(wanted: dict[str, bool], run: Runner) -> list[list[str]]:
    """Returns:
        The enable --now or disable --now calls made for each unit whose
        enabled or disabled state differs from wanted; a masked, static or
        missing unit is never switched.
    """
    states = enabled_states(list(wanted), run)
    calls = [[*SYSTEMCTL, "enable" if on else "disable", "--now", unit] for unit, on in wanted.items() if states[unit] in SWITCHED and on != (states[unit] == "enabled")]
    for call in calls:
        run(call)
    return calls


def schedule_part(row: dict) -> dict:
    return {key: row[key] for key in ("at", "calendar") if key in row}


def apply(rows: dict, overrides: dict, run: Runner, units: Path) -> tuple[list[str], dict[str, str]]:
    """Args:
        rows: the rows of ROWS.
        overrides: the hub timer overrides (stored_units()).

    Returns:
        The systemctl calls made, without the state queries, and per unit
        the error of a refused calendar.
    """
    wanted = {unit: (rows[name], bool(schedule_part(rows[name]))) for name, unit in UNITS.items()}
    wanted |= {unit: (row, True) for unit, row in overrides.items()}
    present = {unit: value for unit, value in wanted.items() if unit_file(units, unit)}
    errors: dict[str, str] = {}
    changed_units = [unit for unit, (row, timed) in present.items() if timed and retimed(units, unit, schedule_part(row), run, errors)]
    calls = reload(changed_units, run) + switched({unit: row["on"] for unit, (row, _) in present.items()}, run)
    return [" ".join(call[2:]) for call in calls], errors


def refresh(root: Path, units: Path, repos: Path, run: Runner, errors: dict[str, str]) -> None:
    write(root, SCHEDULES_VIEW, {"at": time.time(), "rows": view(listed_timers(run), units, repos, run, errors)})


def timer_change(unit: str, args: argparse.Namespace, run: Runner, units: Path) -> tuple[list[str], str]:
    """Returns:
        The calls made for one System timer change and its error, "" when
        none; a first-party or unknown unit is refused untouched.
    """
    if unit.startswith(HUB_PREFIX) or unit in UNITS.values() or not unit.endswith(".timer"):
        return [], f"{unit} is first-party or no timer; the Schedules tab switches it through schedules.json"
    if unit_file(units, unit) is None:
        return [], f"{unit} has no unit file under {units} or {', '.join(map(str, SEARCHED))}"
    if args.on is not None:
        return [" ".join(call[2:]) for call in switched({unit: args.on}, run)], ""
    errors: dict[str, str] = {}
    try:
        schedule = {} if args.reset else timing(unit, {"calendar": args.calendar} if args.calendar else {"at": args.at})
    except ValueError as error:
        return [], str(error)
    calls = reload([unit], run) if retimed(units, unit, schedule, run, errors) else []
    return [" ".join(call[2:]) for call in calls], errors.get(unit, "")


def layout_of(text: str, data: object) -> tuple[dict, str] | None:
    """Returns:
        The json.dumps options and trailing text that give back text from
        data exactly, None when no LAYOUTS entry does.
    """
    for layout in LAYOUTS:
        dumped = json.dumps(data, ensure_ascii=False, **layout)
        for tail in ("", "\n"):
            if dumped + tail == text:
                return layout, tail
    return None


def cron_change(path: Path, task_id: str, cron: str | None, repos: Path) -> str:
    """Args:
        cron: the new cron, or None to remove the task.

    Returns:
        Why the change was refused, "" once the file holds it with every
        other byte kept.
    """
    if path not in task_files(repos):
        return f"{path} is no task file below {repos}"
    found = read_tasks(repos, path)
    layout = layout_of(found[0], found[1]) if found else None
    index = next((place for place, task in enumerate(found[2]) if isinstance(task, dict) and task.get("id") == task_id), None) if found else None
    if layout is None or index is None:
        return f"{path} holds no task {task_id} in a layout this script keeps byte for byte"
    tasks = found[2]
    if cron is None:
        del tasks[index]
    else:
        tasks[index]["cron"] = cron
    sibling("nofollow").rewrite(repos, path, json.dumps(found[1], ensure_ascii=False, **layout[0]) + layout[1], path.stat().st_mode & 0o777)
    return ""


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
    hosts = {name: commands.add_parser(name) for name in ("view", "apply", "run", "timer", "cron")}
    hosts["view"].add_argument("--timers", type=Path)
    for name, host in hosts.items():
        host.add_argument("--units", type=Path, default=Path.home() / ".config" / "systemd" / "user")
        if name != "apply":
            host.add_argument("--repos", type=Path, default=Path.home() / "Repositories")
    hosts["timer"].add_argument("unit")
    change = hosts["timer"].add_mutually_exclusive_group(required=True)
    change.add_argument("--on", dest="on", action="store_const", const=True)
    change.add_argument("--off", dest="on", action="store_const", const=False)
    change.add_argument("--reset", action="store_true")
    change.add_argument("--calendar")
    change.add_argument("--at", nargs="+")
    hosts["cron"].add_argument("file", type=Path)
    hosts["cron"].add_argument("id")
    task = hosts["cron"].add_mutually_exclusive_group(required=True)
    task.add_argument("--cron", type=cron_arg)
    task.add_argument("--remove", action="store_true")
    return parser.parse_args(argv)


def cron_arg(value: str) -> str:
    if not CRON.fullmatch(value):
        raise argparse.ArgumentTypeError(f"no 5-field cron: {value}")
    return value


def set_row(root: Path, args: argparse.Namespace) -> int:
    rows = stored(root)
    try:
        rows[args.row] = valid_row(args.row, changed(rows[args.row], ROWS[args.row], args.on, args.every, args.at))
    except ValueError as error:
        print(f"schedules.py: {error}", file=sys.stderr)
        return 2
    write(root, SCHEDULES, {**rows, UNITS_KEY: stored_units(root)})
    print(json.dumps(rows[args.row], sort_keys=True))
    return 0


def host_change(root: Path, args: argparse.Namespace) -> int:
    """Returns:
        The exit code of a timer or cron change: 0 once applied, 2 when
        refused; the view is refreshed either way, with the error on the
        row.
    """
    if args.command == "timer":
        calls, error = timer_change(args.unit, args, run_command, args.units)
        key = args.unit
    else:
        calls, error = [], cron_change(args.file, args.id, args.cron, args.repos)
        key = f"{args.file}#{args.id}"
    refresh(root, args.units, args.repos, run_command, {key: error} if error else {})
    for call in calls:
        print(call)
    if error:
        print(f"schedules.py: {error}", file=sys.stderr)
        return 2
    return 0


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
        return set_row(root, args)
    if args.command in ("timer", "cron"):
        return host_change(root, args)
    if args.command == "view":
        timers = json.loads(args.timers.read_text(encoding="utf-8")) if args.timers else listed_timers(run_command)
        print(json.dumps(view(timers, args.units, args.repos, run_command, {}), indent=2))
        return 0
    calls, errors = apply(stored(root), stored_units(root), run_command, args.units)
    if args.command == "run":
        refresh(root, args.units, args.repos, run_command, errors)
    for call in calls:
        print(call)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
