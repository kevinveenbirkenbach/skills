#!/usr/bin/env python3
"""Keep the commands only the operator can run in the kvb-org-rasci register, each with a done test.

Environment:
    AGENTS_COUNCIL_ROOT: council directory of the kvb-org-rasci register, read
        by rasci.py; the rows are its tasks operator/<slug>.
    CLAUDE_CODE_SESSION_ID: the adding session, recorded as A; other runtimes
        pass --session.
    PATH: searched by the binary check.
    SHELL: run executes each approved command with `$SHELL -ic`, so the
        operator's aliases and functions work; required by run.

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
            manual  only `done` closes it, or `run` once the command exits 0.
            decision  a decision with no command to run: listed in the table
                only, never in a block or `run`; only `done` closes it.
        Paths are absolute; no argument holds a shell metacharacter.
    list [--json]: run the check of every queued or blocked operator row and
        set the passing ones done.
    run: walk the open rows that hold a directory and a command, in list
        order. Per row it prints directory, command (control characters made
        visible), reason and check, then a preview of what the command
        changes, and asks [y]es / [s]kip / [d]iff / [q]uit; d shows the full
        diff. y runs the command in its directory, then sets the row done
        when its check passes (manual: when the command exits 0). A command
        the kvb-org-organize watch config calls heavy also shows the memory
        stage and `queue.py list`; once the config holds the queue keys and
        slot_need_gb.operator, and the command runs no sudo, [h]old runs
        `granted` through `queue.py hold --kind operator --task <row>
        --session Operator`. End of input quits. There is no flag that
        answers for the operator.
    granted <task> --dir <dir> --check <check> -- $SHELL -ic <cmd>: what
        [h]old queues. On the grant it shows the row and its preview again
        and asks [y]es / [s]kip / [d]iff / [q]uit, then runs the command in
        the row's directory; a row no longer open with exactly that
        directory, check and command runs nothing, nor does a question left
        unanswered for GRANT_SECONDS.
    done <slug>: mark a row done, whatever its check.

Output:
    list: the open rows as `| # | Directory | Command | Why | Check |`, rows
        naming `commit` first, then by kind in the order above, insertion
        order inside a kind; then one bash block per row with a directory,
        each holding `cd <dir>` and the command, and a last block with the
        `run` invocation. `operator: nothing open` when none is. --json
        prints the same rows as a JSON list.

Exit codes:
    0 done, 2 usage error. granted: the command's exit code, or 75
    (EX_TEMPFAIL, which queue.py hold does not learn from) when nothing ran.
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
import select
import shlex
import shutil
import subprocess
import termios
import time
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

SKILLS = Path(__file__).resolve().parents[2]
RASCI = SKILLS / "kvb-org-rasci" / "scripts" / "rasci.py"
WATCH = SKILLS / "kvb-org-organize" / "scripts" / "watch.py"
QUEUE = SKILLS / "kvb-org-queue" / "scripts" / "queue.py"
HOLD_KIND = "operator"
HOLD_SESSION = "Operator"
NOT_RUN = 75
GRANT_SECONDS = 600
SUDO = re.compile(r"\bsudo\b")
PREFIX = "operator/"
KINDS = ("pushed", "installed", "binary", "absent", "manual", "decision")
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
    if kind in ("manual", "decision"):
        return f"{kind} takes no argument" if sep else None
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


def open_rows(rasci: ModuleType) -> list[dict]:
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
    return [
        {
            "task": task,
            "directory": rows[task].get("workdir"),
            "command": rows[task].get("title"),
            "why": rows[task].get("description"),
            "check": checks[task],
        }
        for task in order
    ]


def cmd_list(rasci: ModuleType, args: argparse.Namespace) -> int:
    listed = open_rows(rasci)
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
    steps = [(number, row) for number, row in enumerate(listed, 1) if runnable(row)]
    for number, row in steps:
        print()
        print(f"{number}. {row['task']}")
        print("```bash")
        print(f"cd {shlex.quote(row['directory'])}")
        print(row["command"])
        print("```")
    if steps:
        print()
        print("Every step with preview and yes/skip:")
        print("```bash")
        print(f"python3 {shlex.quote(str(Path(__file__).resolve()))} run")
        print("```")
    return 0


def runnable(row: dict) -> bool:
    # Trip-wire: legacy rows carry a prose title and no directory; only rows recorded by `add` are commands.
    return bool(row["directory"] and row["command"]) and row["check"] != "decision"


def visible(text: str, keep: str) -> str:
    return "".join(c if c.isprintable() or c in keep else c.encode("unicode_escape").decode() for c in text)


def git_tree(directory: str) -> bool:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"], cwd=directory, capture_output=True, check=False
        ).returncode == 0
    except OSError:
        return False


def evidence(check: str, directory: str, full: bool) -> list[tuple[list[str], str]]:
    kind, _, arg = check.partition(":")
    if kind == "pushed":
        if full:
            return [(["git", "diff", "@{u}..HEAD"], arg)]
        return [
            (["git", "--no-pager", "log", "--oneline", "@{u}..HEAD"], arg),
            (["git", "--no-pager", "diff", "--stat", "@{u}..HEAD"], arg),
        ]
    if kind == "installed":
        source, _, target = arg.partition("=")
        return [(["diff", "-ru" if full else "-rq", "--exclude=__pycache__", target, source], directory)]
    if kind == "absent":
        return [(["ls", "-la" if full else "-ld", "--", arg], directory)]
    if kind == "manual" and git_tree(directory):
        if full:
            return [(["git", "diff", "HEAD"], directory)]
        return [
            (["git", "--no-pager", "log", "-1", "--oneline"], directory),
            (["git", "--no-pager", "status", "--short"], directory),
        ]
    return []


def show(commands: list[tuple[list[str], str]]) -> None:
    if not commands:
        print("  (nothing to compare)", flush=True)
    for argv, cwd in commands:
        print(f"$ {shlex.join(argv)}", flush=True)
        try:
            subprocess.run(argv, cwd=cwd, check=False)
        except OSError as error:
            print(f"  {error}", flush=True)


def ask(holdable: bool, read: Callable[[str], str | None]) -> str:
    choices = ("y", "h", "s", "d", "q") if holdable else ("y", "s", "d", "q")
    prompt = "Run it? [y]es / [h]old in the queue / [s]kip / [d]iff / [q]uit: " if holdable else "Run it? [y]es / [s]kip / [d]iff / [q]uit: "
    while True:
        answer = read(prompt)
        if answer is None:
            return "q"
        if answer.strip().lower() in choices:
            return answer.strip().lower()


def typed(prompt: str) -> str | None:
    try:
        return input(prompt)
    except EOFError:
        return None


def timed(prompt: str) -> str | None:
    """Returns:
        One line read unbuffered from stdin, None at its end or when no line
        came within GRANT_SECONDS, so an unanswered grant frees its slot;
        what was typed while the job waited is dropped first.
    """
    if sys.stdin.isatty():
        termios.tcflush(sys.stdin.fileno(), termios.TCIFLUSH)
    print(prompt, end="", flush=True)
    deadline = time.monotonic() + GRANT_SECONDS
    line = b""
    while not line.endswith(b"\n"):
        ready, _, _ = select.select([sys.stdin.fileno()], [], [], max(0.0, deadline - time.monotonic()))
        byte = os.read(sys.stdin.fileno(), 1) if ready else b""
        if not byte:
            print(flush=True)
            return None
        line += byte
    return line.decode(errors="replace")


def needs_terminal(command: str) -> bool:
    return SUDO.search(command) is not None


def heavy_row(watch: ModuleType, cfg: dict | None, row: dict) -> bool:
    """Returns:
        Whether [h]old can queue the row's command: a heavy job by the
        kvb-org-organize watch config, which holds every queue key and the
        kind operator, and no sudo, whose prompt needs the terminal a queued
        command lacks; prints the memory stage and `queue.py list` for a
        heavy one, its output control characters made visible.
    """
    if cfg is None or not watch.heavy(row["command"], cfg, tuple(cfg["never_block"])):
        return False
    problem = watch.missing(cfg, (*watch.MEMORY_KEYS, "budget_percent.ram", "budget_percent.cpu", f"slot_need_gb.{HOLD_KIND}"))
    if problem is None and needs_terminal(row["command"]):
        problem = "sudo asks on the terminal, which a queued command lacks"
    if problem is None:
        sample = watch.memory()
        print(f"  heavy:     memory stage {watch.memory_stage(sample, cfg)} ({watch.memory_text(sample)}); the queue:", flush=True)
    else:
        print(f"  heavy:     {problem}; no [h]old until it does. The queue:", flush=True)
    listing = subprocess.run([sys.executable, str(QUEUE), "list"], cwd=row["directory"], capture_output=True, text=True, check=False)
    print(visible(listing.stdout + listing.stderr, "\t\n"), end="", flush=True)
    return problem is None


def held(row: dict, shell: str) -> list[str]:
    return [
        sys.executable, str(QUEUE), "hold", "--kind", HOLD_KIND, "--task", row["task"], "--session", HOLD_SESSION,
        "--", sys.executable, str(Path(__file__).resolve()), "granted", row["task"], "--dir", row["directory"],
        "--check", row["check"], "--", shell, "-ic", row["command"],
    ]


def review(row: dict, holdable: bool, read: Callable[[str], str | None]) -> str:
    check = "manual" if problem(row["check"]) else row["check"]
    show(evidence(check, row["directory"], full=False))
    answer = ask(holdable, read)
    while answer == "d":
        show(evidence(check, row["directory"], full=True))
        answer = ask(holdable, read)
    return answer


def cmd_granted(rasci: ModuleType, args: argparse.Namespace) -> int:
    shell = os.environ.get("SHELL")
    approved = [
        row for row in open_rows(rasci)
        if runnable(row) and (row["task"], row["directory"], row["check"]) == (args.task, args.dir, args.check)
        and args.argv == [shell, "-ic", row["command"]]
    ]
    if not shell or not approved:
        print(f"operator: {args.task} is no longer open with the approved directory, check and command; nothing ran",
              file=sys.stderr)
        return NOT_RUN
    row = approved[0]
    print(f"\ngranted {row['task']}: the queue lets it run now; its tree may have changed while it waited")
    print(f"  directory: {visible(row['directory'], '')}")
    print(f"  command:   {visible(row['command'], '')}", flush=True)
    try:
        answer = review(row, False, timed)
    except KeyboardInterrupt:
        answer = "q"
    if answer != "y":
        print(f"not run {row['task']}")
        return NOT_RUN
    return subprocess.run(args.argv, cwd=row["directory"], check=False).returncode


def close(rasci: ModuleType, task: str) -> None:
    with rasci.database() as tasks:
        entry = tasks.get(task)
        if entry and entry.get("status") in OPEN:
            rasci.apply_status(entry, "done")


def cmd_run(rasci: ModuleType, args: argparse.Namespace) -> int:
    shell = os.environ.get("SHELL")
    if not shell:
        fail("SHELL is not set; run executes each command in the operator's own shell")
    steps = [row for row in open_rows(rasci) if runnable(row)]
    if not steps:
        print("operator: nothing to run")
        return 0
    watch = module("kvb_operator_watch", WATCH)
    cfg = watch.load_config()
    for number, row in enumerate(steps, 1):
        check = "manual" if problem(row["check"]) else row["check"]
        print(f"\n[{number}/{len(steps)}] {row['task']}")
        print(f"  directory: {visible(row['directory'], '')}")
        print(f"  command:   {visible(row['command'], '')}")
        print(f"  why:       {visible(row['why'] or '-', '')}")
        print(f"  check:     {check}", flush=True)
        holdable = heavy_row(watch, cfg, row)
        answer = review(row, holdable, typed)
        if answer == "q":
            print("operator: stopped")
            return 0
        if answer == "s":
            print(f"skipped {row['task']}")
            continue
        argv = held(row, shell) if answer == "h" else [shell, "-ic", row["command"]]
        try:
            code = subprocess.run(argv, cwd=row["directory"], check=False).returncode
        except OSError as error:
            print(f"failed {row['task']}: {error}")
            continue
        if code != 0:
            print(f"failed {row['task']}: exit {code}; the row stays open")
        elif check == "manual" or passed(check):
            close(rasci, row["task"])
            print(f"done {row['task']}")
        else:
            print(f"ran {row['task']}, but {check} does not pass yet; the row stays open")
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
    p = sub.add_parser("run")
    p.set_defaults(func=cmd_run)
    p = sub.add_parser("granted")
    p.add_argument("task")
    p.add_argument("--dir", required=True)
    p.add_argument("--check", required=True)
    p.add_argument("argv", nargs="+")
    p.set_defaults(func=cmd_granted)
    p = sub.add_parser("done")
    p.add_argument("slug")
    p.set_defaults(func=cmd_done)
    args = parser.parse_args()
    return args.func(module("rasci", RASCI), args)


if __name__ == "__main__":
    sys.exit(main())
