#!/usr/bin/env python3
"""Keep the commands only the operator can run in the kvb-org-rasci register, each with a done test.

Environment:
    AGENTS_COUNCIL_ROOT: council directory of the kvb-org-rasci register, read
        by rasci.py; the rows are its tasks operator/<slug>.
    CLAUDE_CODE_SESSION_ID: the adding session, recorded as A; other runtimes
        pass --session.
    PATH: searched by the binary check.

Args:
    add <slug> --dir <abs dir> --command "<cmd>" --reason "<why>"
        --check <kind>[:<arg>] [--session <id>]: record a command, or update
        the row of that slug, as queued with Operator R and the adder A.
        Kinds, never a shell command:
            pushed:<repo dir>  `git rev-list --count @{u}..HEAD` is 0 there;
                no upstream counts as open.
            installed:<source dir>=<installed dir>  both trees hold the same
                files with the same bytes, __pycache__ ignored.
            binary:<name>  the name is on PATH.
            absent:<path>  the path does not exist.
            manual  only `done` closes it.
        Paths are absolute; no argument holds a shell metacharacter.
    list [--json]: run the check of every queued or blocked operator row and
        set the passing ones done.
    done <slug>: mark a row done, whatever its check.

Output:
    list: the open rows as `| # | Directory | Command | Why | Check |`, rows
        naming `commit` first, then by kind in the order above, insertion
        order inside a kind; then one bash block with `cd <dir>` and the
        command per row. `operator: nothing open` when none is. --json prints
        the same rows as a JSON list.

Exit codes:
    0 done, 2 usage error.
"""

from __future__ import annotations

import os
import sys

# Trip-wire: this file shadows the stdlib operator module; without this, argparse's
# import of collections, which imports operator, loads this script when site has not.
sys.path.sort(key=lambda entry: os.path.realpath(entry) == os.path.dirname(os.path.realpath(__file__)))

import argparse
import hashlib
import importlib.util
import json
import re
import shlex
import shutil
import subprocess
from pathlib import Path
from types import ModuleType

RASCI = Path(__file__).resolve().parents[2] / "kvb-org-rasci" / "scripts" / "rasci.py"
PREFIX = "operator/"
KINDS = ("pushed", "installed", "binary", "absent", "manual")
OPEN = ("queued", "blocked")
META = re.compile(r"[\s|&;()<>$`\\\"'*?\[\]{}~!#]")
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")
COMMIT = re.compile(r"\bcommit\b")
HEADER = "| # | Directory | Command | Why | Check |"


def fail(message: str) -> None:
    print(f"operator: {message}", file=sys.stderr)
    sys.exit(2)


def module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def task_of(rasci: ModuleType, slug: str) -> str:
    if not rasci.TASK.match(slug):
        fail(f"invalid slug {slug!r}; use lowercase letters, digits, '.', '_', '-' and '/'")
    return PREFIX + slug


def path_problem(path: str, what: str) -> str | None:
    if META.search(path):
        return f"{what} {path!r} holds a shell metacharacter"
    if not os.path.isabs(path):
        return f"{what} {path!r} is not an absolute path"
    return None


def problem(check: str) -> str | None:
    kind, sep, arg = check.partition(":")
    if kind not in KINDS:
        return f"unknown check kind {kind!r}; use one of {', '.join(KINDS)}"
    if kind == "manual":
        return "manual takes no argument" if sep else None
    if not arg:
        return f"{kind} needs an argument"
    if META.search(arg):
        return f"check argument {arg!r} holds a shell metacharacter"
    if kind == "binary":
        return None if NAME.match(arg) else f"binary takes a name, not {arg!r}"
    if kind == "installed":
        source, sep, target = arg.partition("=")
        if not sep or "=" in target:
            return "installed takes <source dir>=<installed dir>"
        return path_problem(source, "source") or path_problem(target, "installed dir")
    return path_problem(arg, kind)


def ahead(repo: str) -> int | None:
    try:
        result = subprocess.run(
            ["git", "rev-list", "--count", "@{u}..HEAD"],
            cwd=repo, capture_output=True, text=True, check=False,
        )
    except OSError:
        return None
    return int(result.stdout) if result.returncode == 0 else None


def digests(root: str) -> dict[str, bytes] | None:
    if not os.path.isdir(root):
        return None
    found = {}
    try:
        for top, dirs, names in os.walk(root):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for name in names:
                path = os.path.join(top, name)
                with open(path, "rb") as handle:
                    found[os.path.relpath(path, root)] = hashlib.file_digest(handle, "sha256").digest()
    except OSError:
        return None
    return found


def passed(check: str) -> bool:
    kind, _, arg = check.partition(":")
    if kind == "pushed":
        return ahead(arg) == 0
    if kind == "installed":
        source, _, target = arg.partition("=")
        tree = digests(source)
        return tree is not None and tree == digests(target)
    if kind == "binary":
        return shutil.which(arg) is not None
    if kind == "absent":
        return not os.path.lexists(arg)
    return False


def cell(text: object) -> str:
    return " ".join(str(text).split()).replace("|", "\\|")


def cmd_add(rasci: ModuleType, args: argparse.Namespace) -> int:
    task = task_of(rasci, args.slug)
    for error in (path_problem(args.dir, "--dir"), problem(args.check)):
        if error:
            fail(error)
    command = args.command.strip()
    reason = " ".join(args.reason.split())
    if not command or not reason:
        fail("--command and --reason must not be empty")
    council = module("council", rasci.COUNCIL)
    sid, _ = council.caller(args.session)
    party = council.live_sessions().get(sid) or sid
    with rasci.database() as tasks:
        # Trip-wire: the register is dumped with sort_keys, so insertion order needs its own field.
        seq = max((e.get("seq", 0) for t, e in tasks.items() if t.startswith(PREFIX)), default=0) + 1
        entry = tasks.setdefault(task, {})
        entry.setdefault("seq", seq)
        entry.update(title=command, workdir=args.dir, description=reason, check=args.check)
        roles = {p: v.replace("A", "") for p, v in entry.get("roles", {}).items()}
        roles[rasci.OPERATOR] = rasci.letters_of(roles.get(rasci.OPERATOR, ""), "R")
        roles[party] = rasci.letters_of(roles.get(party, ""), "A")
        entry["roles"] = {p: v for p, v in roles.items() if v}
        rasci.apply_status(entry, "queued")
    print(f"added {task}")
    return 0


def cmd_list(rasci: ModuleType, args: argparse.Namespace) -> int:
    rows = {
        task: row for task, row in rasci.merged(include_done=False).items()
        if task.startswith(PREFIX) and row["status"] in OPEN
    }
    checks = {task: row.get("check") or "manual" for task, row in rows.items()}
    finished = {task for task, check in checks.items() if not problem(check) and passed(check)}
    if finished:
        with rasci.database() as tasks:
            for task in finished:
                entry = tasks.get(task)
                if entry and entry.get("check") == checks[task] and entry.get("status") in OPEN:
                    rasci.apply_status(entry, "done")

    def rank(task: str) -> tuple:
        kind = "manual" if problem(checks[task]) else checks[task].partition(":")[0]
        first = COMMIT.search(rows[task].get("title") or "")
        return (0 if first else 1 + KINDS.index(kind), rows[task].get("seq", 0), task)

    order = sorted(rows.keys() - finished, key=rank)
    listed = [
        {
            "task": task,
            "directory": rows[task].get("workdir"),
            "command": rows[task].get("title"),
            "why": rows[task].get("description"),
            "check": checks[task],
        }
        for task in order
    ]
    if args.json:
        print(json.dumps(listed, indent=1))
        return 0
    if not listed:
        print("operator: nothing open")
        return 0
    print(HEADER)
    print("|---|---|---|---|---|")
    for number, row in enumerate(listed, 1):
        values = (number, row["directory"] or "-", row["command"] or "-", row["why"] or "-", row["check"])
        print("| " + " | ".join(cell(v) for v in values) + " |")
    # Trip-wire: legacy rows carry a prose title and no directory; only rows recorded by `add` are commands.
    runnable = [row for row in listed if row["directory"] and row["command"]]
    if runnable:
        print()
        print("```bash")
        for row in runnable:
            print(f"cd {shlex.quote(row['directory'])}")
            print(row["command"])
        print("```")
    return 0


def cmd_done(rasci: ModuleType, args: argparse.Namespace) -> int:
    task = task_of(rasci, args.slug)
    with rasci.database() as tasks:
        if task not in tasks:
            fail(f"{task}: not in the register")
        rasci.apply_status(tasks[task], "done")
    print(f"done {task}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("add")
    p.add_argument("slug")
    for flag in ("--dir", "--command", "--reason", "--check"):
        p.add_argument(flag, required=True)
    p.add_argument("--session")
    p.set_defaults(func=cmd_add)
    p = sub.add_parser("list")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_list)
    p = sub.add_parser("done")
    p.add_argument("slug")
    p.set_defaults(func=cmd_done)
    args = parser.parse_args()
    return args.func(module("rasci", RASCI), args)


if __name__ == "__main__":
    sys.exit(main())
