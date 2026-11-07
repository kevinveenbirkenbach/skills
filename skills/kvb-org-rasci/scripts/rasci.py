#!/usr/bin/env python3
"""Keep the RASCI register of the organisation's tasks in a local JSON file.

Environment:
    AGENTS_COUNCIL_ROOT: council directory shared by every agent on the host;
        the register is <root>/rasci.json, and `show` also lists every work/
        and cluster/ claim of the council there. /tmp/agents-council unless set.

Exit codes:
    0 done, 2 usage error.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime
import importlib.util
import json
import os
import re
import statistics
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

ROOT = Path(os.environ.get("AGENTS_COUNCIL_ROOT", "/tmp/agents-council"))
DB = ROOT / "rasci.json"
LOCK = ROOT / "rasci.lock"
FILE_MODE = 0o600
ORGANIZE = Path(__file__).resolve().parents[2] / "kvb-org-organize" / "scripts"
COUNCIL = ORGANIZE / "council.py"
TASK = re.compile(r"^[a-z0-9][a-z0-9._-]*(/[a-z0-9][a-z0-9._-]*)*$")
LETTERS = re.compile(r"^(?!.*(.).*\1)[RASCI]+$")
ORDER = "RASCI"
WIDE = ("Prio", "WSJF", "Task", "OKR", "Status", "Worker", "Artifacts", "Start", "End", *ORDER)
COMPACT = ("Prio", "WSJF", "Task", "Status", "Worker", "A")
STATUSES = ("queued", "running", "blocked", "done", "stopped")
ENDED = ("done", "stopped")
FIELDS = (
    "title", "objective", "description", "prio", "status", "worker", "start", "end", "workdir",
    "branch", "base",
)
TEXT_FIELDS = ("title", "objective", "description", "worker", "workdir", "branch", "base")
LIST_FIELDS = {"tools": "tool"}
ARTIFACT = re.compile(r"^[a-z]+:\S")
FIBONACCI = (1, 2, 3, 5, 8, 13, 21, 34, 55, 89)
OPERATOR = "Operator"
RECORDS = ("hotfix/", "operator/")


def fail(message: str) -> None:
    print(f"rasci: {message}", file=sys.stderr)
    sys.exit(2)


def check_task(task: str) -> None:
    if not TASK.match(task):
        fail(f"invalid task {task!r}; use a slug like work/<slug>")


def stamp(value: str = "now") -> str:
    if value == "now":
        return datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")
    try:
        parsed = datetime.datetime.fromisoformat(value)
    except ValueError:
        fail(f"invalid time {value!r}; use ISO 8601 or now")
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed.astimezone(datetime.UTC).isoformat(timespec="seconds")


def letters_of(*parts: str) -> str:
    return "".join(letter for letter in ORDER if any(letter in part for part in parts))


def script(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


nofollow = script("kvb_rasci_nofollow", ORGANIZE / "nofollow.py")


def load() -> dict[str, dict]:
    try:
        tasks = json.loads(nofollow.read_text(ROOT, DB))
    except FileNotFoundError:
        return {}
    except (ValueError, RecursionError):
        fail(f"{DB} is not valid JSON")
    except OSError as error:
        fail(f"{DB} is no regular file below {ROOT}: {error.strerror}")
    if not isinstance(tasks, dict) or not all(isinstance(entry, dict) for entry in tasks.values()):
        fail(f"{DB} is not an object of task objects")
    return tasks


@contextlib.contextmanager
def database() -> Iterator[dict[str, dict]]:
    with contextlib.ExitStack() as held:
        try:
            ROOT.mkdir(parents=True, exist_ok=True)
            held.enter_context(nofollow.locked(ROOT, LOCK, FILE_MODE, None))
        except OSError as error:
            fail(f"cannot lock {LOCK}: {error.strerror}")
        tasks = load()
        yield tasks
        nofollow.replace(ROOT, DB, json.dumps(tasks, indent=1, sort_keys=True), FILE_MODE)


def open_results(entry: dict) -> int:
    return sum(not kr["met"] for kr in entry.get("key_results", []))


def apply_status(entry: dict, status: str) -> None:
    if status not in ENDED:
        entry.pop("end", None)
    entry["status"] = status
    if status == "running":
        entry.setdefault("start", stamp())
    if status in ENDED:
        entry.setdefault("end", stamp())


def track(task: str, holder: str, status: str, *, description: str | None = None,
          previous: str | None = None, workdir: str | None = None,
          branch: str | None = None) -> None:
    """Write a council claim (status running) or release (status done) through.

    Args:
      task: the claimed office, e.g. work/<slug>.
      holder: the session holding the claim.
      status: running on claim and takeover, done on release; a release with
        open key results ends as stopped.
      description: the claim's --work line, kept unless one is recorded.
      previous: the stale holder a takeover replaces; loses its R and A.
      workdir: the claiming process's directory, kept unless one is recorded.
      branch: the checked-out branch there, kept unless one is recorded.
    """
    with database() as tasks:
        entry = tasks.setdefault(task, {"roles": {}})
        roles = entry.setdefault("roles", {})
        if previous and previous != holder:
            left = roles.pop(previous, "").replace("R", "").replace("A", "")
            if left:
                roles[previous] = left
            if entry.get("worker") == previous:
                entry["worker"] = holder
        entry.setdefault("worker", holder)
        for field, value in (("description", description), ("workdir", workdir), ("branch", branch)):
            if value:
                entry.setdefault(field, value)
        if status == "done" and open_results(entry):
            status = "stopped"
        if status in ENDED or entry.get("status") in (None, "queued", *ENDED):
            apply_status(entry, status)
        if status not in ENDED:
            accountable = any("A" in v for p, v in roles.items() if p != holder)
            roles[holder] = letters_of(roles.get(holder, ""), "R" if accountable else "RA")


def claimed() -> dict[str, dict]:
    if not COUNCIL.is_file():
        return {}
    council = script("council", COUNCIL)
    live = council.live_sessions()
    rows = {}
    for office, claim in council.claims():
        if not office.startswith(("work/", "cluster/")):
            continue
        holder = claim["name"] or claim["session"]
        rows[office] = {
            "description": claim["work"],
            "status": "claimed",
            "worker": holder,
            "start": claim["since"],
            "roles": {holder: "RA"},
            "stale": council.is_stale(claim, live),
        }
    return rows


def merged(include_done: bool) -> dict[str, dict]:
    rows = claimed()
    for task, entry in load().items():
        base = rows.get(task, {"status": "queued", "roles": {}})
        fields = {k: v for k, v in entry.items() if k != "roles"}
        rows[task] = {**base, **fields, "roles": {**base["roles"], **entry.get("roles", {})}}
    for row in rows.values():
        if row.get("stale"):
            row["status"] = "stale"
    return {
        task: row for task, row in rows.items() if include_done or row["status"] not in ENDED
    }


def cell(text: object, width: int) -> str:
    text = " ".join(str(text).split()).replace("|", "\\|")
    return text if len(text) <= width else text[: width - 1] + "…"


def when(value: str | None) -> str:
    if not value:
        return "-"
    return datetime.datetime.fromisoformat(value).astimezone().strftime("%m-%d %H:%M")


def wsjf(row: dict) -> tuple[float, float, float] | None:
    estimates = list(row.get("estimates", {}).values())
    if not estimates:
        return None
    value = statistics.median(e["value"] for e in estimates)
    complexity = statistics.median(e["complexity"] for e in estimates)
    return value, complexity, round(value / complexity, 2)


def ranked(rows: dict[str, dict]) -> list[str]:
    def key(task: str) -> tuple:
        row = rows[task]
        score = wsjf(row)
        pinned = row.get("prio")
        return (pinned is None, pinned or 0, score is None, -(score[2] if score else 0), task)

    return sorted(rows, key=key)


def by_agent(rows: dict[str, dict]) -> dict[str, list[str]]:
    agents: dict[str, list[str]] = {}
    for task in ranked(rows):
        agents.setdefault(rows[task].get("worker") or "-", []).append(task)
    return agents


def cmd_agents(_: argparse.Namespace) -> int:
    for rank, (agent, tasks) in enumerate(by_agent(merged(include_done=False)).items(), 1):
        print(f"{rank}\t{agent}\t{len(tasks)}\t{', '.join(tasks)}")
    return 0


def cmd_order(args: argparse.Namespace) -> int:
    names = [name.strip() for name in args.agents.split(",") if name.strip()]
    agents = by_agent(merged(include_done=False))
    unknown = [name for name in names if name not in agents]
    if not names or unknown or len(set(names)) != len(names):
        fail(f"order needs distinct agents from `agents`; unknown: {', '.join(unknown) or '-'}")
    with database() as tasks:
        prio = 0
        for name in names:
            for task in agents[name]:
                prio += 1
                tasks.setdefault(task, {})["prio"] = prio
        for name in agents.keys() - set(names):
            for task in agents[name]:
                tasks.get(task, {}).pop("prio", None)
    print(f"pinned {prio} tasks of {len(names)} agents; the others rank by WSJF after them")
    return 0


def okr(row: dict) -> str:
    results = row.get("key_results", [])
    text = cell(row.get("objective") or "-", 40)
    if results:
        text += f" ({sum(kr['met'] for kr in results)}/{len(results)} KR)"
    return text


def gaps(task: str, row: dict) -> list[str]:
    if task.startswith(RECORDS):
        return []
    found = []
    roles = row["roles"]
    accountable = sum("A" in letters for letters in roles.values())
    if accountable != 1:
        found.append(f"{task} has {accountable} A")
    if not any("R" in letters for letters in roles.values()):
        found.append(f"{task} has no R")
    if not row.get("key_results") and row["status"] not in ENDED:
        found.append(f"{task} has no key result")
    return found


def cmd_set(args: argparse.Namespace) -> int:
    check_task(args.task)
    if args.prio is not None and args.prio < 1:
        fail("--prio must be 1 or higher")
    times = {f: stamp(getattr(args, f)) for f in ("start", "end") if getattr(args, f)}
    for ref in args.artifact:
        if not ARTIFACT.match(ref):
            fail(f"invalid artifact {ref!r}; use <kind>:<ref>, e.g. image:<name>:<tag>")
    with database() as tasks:
        entry = tasks.setdefault(args.task, {"roles": {}})
        if args.status == "done" and open_results(entry):
            fail(f"{args.task}: {open_results(entry)} key result(s) open; mark them met or set stopped")
        for field in (*TEXT_FIELDS, "prio"):
            value = getattr(args, field)
            if value is not None:
                entry[field] = value
        if args.status:
            apply_status(entry, args.status)
        entry.update(times)
        for field, flag in LIST_FIELDS.items():
            drop = getattr(args, f"drop_{flag}")
            items = [i for i in entry.get(field, []) if i not in drop]
            items += [i for i in dict.fromkeys(getattr(args, flag)) if i not in items]
            if items:
                entry[field] = items
            else:
                entry.pop(field, None)
        kept = [a for a in entry.get("artifacts", []) if a["ref"] not in args.drop_artifact]
        known = {a["ref"] for a in kept}
        kept += [{"ref": r, "added": stamp()} for r in dict.fromkeys(args.artifact) if r not in known]
        if kept:
            entry["artifacts"] = kept
        else:
            entry.pop("artifacts", None)
    print(f"set {args.task}")
    return 0


def cmd_role(args: argparse.Namespace) -> int:
    check_task(args.task)
    letters = args.letters.upper()
    if letters != "-" and not LETTERS.match(letters):
        fail("letters must be distinct ones of R, A, S, C, I, or - to clear")
    with database() as tasks:
        roles = tasks.setdefault(args.task, {"roles": {}}).setdefault("roles", {})
        if letters == "-":
            roles.pop(args.party, None)
        else:
            roles[args.party] = letters_of(letters)
    print(f"{args.task}: {args.party} {letters}")
    return 0


def cmd_kr(args: argparse.Namespace) -> int:
    check_task(args.task)
    with database() as tasks:
        entry = tasks.setdefault(args.task, {"roles": {}})
        results = entry.setdefault("key_results", [])
        if args.action == "add":
            if all(kr["text"] != args.value for kr in results):
                results.append({"text": args.value, "met": False})
        else:
            if not args.value.isdigit() or not 1 <= int(args.value) <= len(results):
                fail(f"{args.task}: no key result {args.value!r}; `get` lists them by number")
            index = int(args.value) - 1
            if args.action == "rm":
                results.pop(index)
            else:
                results[index]["met"] = args.action == "met"
        if not results:
            entry.pop("key_results")
    print(f"{args.task}: key result {args.action} {args.value}")
    return 0


def cmd_get(args: argparse.Namespace) -> int:
    row = merged(True).get(args.task)
    if row is None:
        fail(f"{args.task}: not in the register")
    print(f"task: {args.task}")
    for field in FIELDS:
        if row.get(field) not in (None, ""):
            print(f"{field}: {row[field]}")
    for number, kr in enumerate(row.get("key_results", []), 1):
        print(f"key result {number} [{'x' if kr['met'] else ' '}]: {kr['text']}")
    for artifact in row.get("artifacts", []):
        print(f"artifact: {artifact['ref']} (since {when(artifact['added'])})")
    for field, flag in LIST_FIELDS.items():
        for item in row.get(field, []):
            print(f"{flag}: {item}")
    roles = ", ".join(f"{p}={v}" for p, v in sorted(row["roles"].items()))
    print(f"roles: {roles or '-'}")
    for party, estimate in sorted(row.get("estimates", {}).items()):
        print(f"estimate {party}: business value {estimate['value']}, complexity {estimate['complexity']}")
    score = wsjf(row)
    if score:
        print(f"wsjf: {score[2]:g}")
    return 0


def cmd_estimate(args: argparse.Namespace) -> int:
    check_task(args.task)
    if not args.drop:
        for name in ("value", "complexity"):
            if getattr(args, name) not in FIBONACCI:
                fail(f"--{name} must be one of {', '.join(map(str, FIBONACCI))}")
    with database() as tasks:
        entry = tasks.setdefault(args.task, {"roles": {}})
        estimates = entry.setdefault("estimates", {})
        if args.drop:
            estimates.pop(args.party, None)
        else:
            estimates[args.party] = {"value": args.value, "complexity": args.complexity, "at": stamp()}
        if not estimates:
            entry.pop("estimates")
    print(f"{args.task}: estimate {'dropped' if args.drop else 'recorded'} for {args.party}")
    return 0


def cmd_wsjf(args: argparse.Namespace) -> int:
    rows = {task: row for task, row in merged(args.all).items() if not task.startswith(RECORDS)}
    if not rows:
        print("no tasks")
        return 0
    header = ["Rank", "Task", "OKR", "Business value", "Complexity", "WSJF", "Estimators", "Status"]
    print("| " + " | ".join(header) + " |")
    print("|" + "---|" * len(header))
    unestimated = []
    for rank, task in enumerate(ranked(rows), 1):
        row = rows[task]
        score = wsjf(row)
        if score is None:
            unestimated.append(task)
        figures = [f"{n:g}" for n in score] if score else ["-", "-", "-"]
        estimators = ", ".join(sorted(row.get("estimates", {}), key=str.lower)) or "-"
        values = [rank, task, okr(row), *figures, cell(estimators, 40), row["status"]]
        print("| " + " | ".join(str(v) for v in values) + " |")
    if unestimated:
        print("unestimated: " + ", ".join(unestimated))
    return 0


def cmd_artifacts(args: argparse.Namespace) -> int:
    rows = merged(True)
    for task in sorted(rows):
        row = rows[task]
        if task.startswith(RECORDS) or (args.task and task != args.task):
            continue
        if args.ended and row["status"] not in (*ENDED, "stale"):
            continue
        places = [(f"{f}:{row[f]}", None) for f in ("workdir", "branch") if row.get(f)]
        recorded = [(a["ref"], a["added"]) for a in row.get("artifacts", [])]
        for ref, added in (*places, *recorded):
            print(f"{row['status']}\t{task}\t{row.get('worker') or '-'}\t{ref}\t{when(added)}")
    return 0


def cmd_tools(_: argparse.Namespace) -> int:
    used: dict[str, list[str]] = {}
    for task, row in merged(True).items():
        for tool in row.get("tools", []):
            used.setdefault(tool, []).append(task)
    for tool, tasks in sorted(used.items(), key=lambda item: (-len(item[1]), item[0])):
        print(f"{len(tasks)}\t{tool}\t{' '.join(sorted(tasks))}")
    return 0


def cmd_rm(args: argparse.Namespace) -> int:
    check_task(args.task)
    with database() as tasks:
        removed = tasks.pop(args.task, None)
    print(f"removed {args.task}" if removed is not None else f"{args.task}: not in the register")
    return 0


def holders(row: dict, letter: str, width: int) -> str:
    parties = sorted(row["roles"], key=lambda p: (p != OPERATOR, p.lower()))
    return cell(", ".join(p for p in parties if letter in row["roles"][p]), width)


def wide(task: str, row: dict) -> list[object]:
    title = f"{task}: {row['title']}" if row.get("title") else task
    return [
        cell(title, 50),
        okr(row),
        row["status"],
        cell(row.get("worker") or "-", 30),
        len(row.get("artifacts", [])) or "-",
        when(row.get("start")),
        when(row.get("end")),
        *(holders(row, letter, 30) for letter in ORDER),
    ]


def compact(task: str, row: dict) -> list[object]:
    title = cell(f"{task}: {row['title']}", max(40, len(task) + 1)) if row.get("title") else task
    return [title, row["status"], cell(row.get("worker") or "-", 24), holders(row, "A", 24)]


def cmd_show(args: argparse.Namespace) -> int:
    rows = merged(args.all)
    if not rows:
        print("no tasks")
        return 0
    header, columns = (WIDE, wide) if args.wide else (COMPACT, compact)
    print("| " + " | ".join(header) + " |")
    print("|" + "---|" * len(header))
    problems = []
    for rank, task in enumerate(ranked(rows), 1):
        row = rows[task]
        score = wsjf(row)
        values = [rank, f"{score[2]:g}" if score else "-", *columns(task, row)]
        print("| " + " | ".join(str(v) for v in values) + " |")
        problems += gaps(task, row)
    if problems:
        print("gaps: " + "; ".join(problems))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("set")
    p.add_argument("task")
    for field in (*TEXT_FIELDS, "start", "end"):
        p.add_argument(f"--{field}")
    p.add_argument("--prio", type=int)
    for flag in (*LIST_FIELDS.values(), "artifact"):
        p.add_argument(f"--{flag}", action="append", default=[])
        p.add_argument(f"--drop-{flag}", action="append", default=[])
    p.add_argument("--status", choices=STATUSES)
    p.set_defaults(func=cmd_set)
    p = sub.add_parser("estimate")
    p.add_argument("task")
    p.add_argument("party")
    p.add_argument("--value", type=int)
    p.add_argument("--complexity", type=int)
    p.add_argument("--drop", action="store_true")
    p.set_defaults(func=cmd_estimate)
    p = sub.add_parser("wsjf")
    p.add_argument("--all", action="store_true")
    p.set_defaults(func=cmd_wsjf)
    p = sub.add_parser("kr")
    p.add_argument("task")
    p.add_argument("action", choices=("add", "met", "open", "rm"))
    p.add_argument("value")
    p.set_defaults(func=cmd_kr)
    p = sub.add_parser("role")
    p.add_argument("task")
    p.add_argument("party")
    p.add_argument("letters")
    p.set_defaults(func=cmd_role)
    for name, func in (("get", cmd_get), ("rm", cmd_rm)):
        p = sub.add_parser(name)
        p.add_argument("task")
        p.set_defaults(func=func)
    p = sub.add_parser("show")
    p.add_argument("--all", action="store_true")
    p.add_argument("--wide", action="store_true")
    p.set_defaults(func=cmd_show)
    p = sub.add_parser("artifacts")
    p.add_argument("--ended", action="store_true")
    p.add_argument("--task")
    p.set_defaults(func=cmd_artifacts)
    sub.add_parser("tools").set_defaults(func=cmd_tools)
    sub.add_parser("agents").set_defaults(func=cmd_agents)
    p = sub.add_parser("order")
    p.add_argument("agents")
    p.set_defaults(func=cmd_order)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
