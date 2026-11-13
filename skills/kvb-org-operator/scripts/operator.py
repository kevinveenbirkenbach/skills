#!/usr/bin/env python3
"""Keep the commands only the operator can run in the kvb-org-rasci register, each with a done test.

Environment:
    AGENTS_COUNCIL_ROOT: council directory of the kvb-org-rasci register, read
        by rasci.py; the rows are its tasks operator/<slug>.
    CLAUDE_CODE_SESSION_ID: the calling session: add records it as A, list
        and done leave it out of their messages; other runtimes pass
        --session.
    NO_COLOR: when set and not empty, run prints without colors
        (https://no-color.org).
    PATH: searched by the binary check.
    SHELL: run executes each approved command with `$SHELL -ic`, so the
        operator's aliases and functions work; required by run.

Args:
    add <slug> --dir <abs dir> --command "<cmd>" --reason "<why>"
        --check <kind>[:<arg>] [--session <id>]: record a command, or update
        the row of that slug, as queued with Operator R and the adder A, its
        session id under `sessions`.
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
        Paths are absolute; no argument holds a shell metacharacter; the
        command is one line without control characters. Unless the check is
        decision, the command starts, after VAR=value words, with a program
        on PATH, a path to one or a shell builtin and holds no <placeholder>;
        an alias, a slash command or prose is refused, and an older row
        holding one stays in the table only.
    list [--json] [--session <id>]: run the check of every queued or blocked
        operator row and set the passing ones done, with a message.
    run: walk the open rows that hold a directory and a command, in list
        order. Per row it prints a separator line with number and task, then
        directory, command, reason and check in a label column (control
        characters made visible; on a terminal values wrap under their
        column, and unless NO_COLOR is set the separator is bold, labels dim,
        the command bold cyan and preview commands yellow), then a preview
        of what the command changes, its output indented, and asks [y]es /
        [s]kip / [c]ancel / [d]iff / [q]uit; d shows the full diff. A repo
        whose git config names filter commands gets no preview. c asks for a
        reason (empty: back to the question), sets the row as shown stopped
        with it and sends it as a message; a row changed since it was shown
        is not cancelled. y runs the command in its directory,
        its stderr passed through and its last FAILED_LINES lines kept, then
        sets the row done when its check passes (manual: when the command
        exits 0), else keeps it open, with a message either way. A command
        that exits non-zero or cannot start leaves the
        queue the same way: the row is set stopped with the exit under
        `failed`, sent as a message with the request to queue
        the corrected command under the same slug; the stderr lines go under
        `failed.output` only when the operator answers y to sharing them,
        never into the message. Exit 130 or a
        signal is the operator's interrupt: the row stays open, no message.
        A command
        the kvb-org-organize watch config calls heavy also shows the memory
        stage and the position, id, status, task and eta_min columns of
        `queue.py list`; once the config holds the queue keys and
        slot_need_gb.operator, and the command runs no sudo, [h]old runs
        `granted` through `queue.py hold --kind operator --task <row>
        --session Operator`; its exit 75 means nothing ran and is no
        failure. End of input quits. There is no flag that answers for the
        operator.
    granted <task> --dir <dir> --check <check> -- $SHELL -ic <cmd>: what
        [h]old queues. On the grant it shows the row and its preview again
        and asks [y]es / [s]kip / [c]ancel / [d]iff / [q]uit, then runs the command in
        the row's directory; a row no longer open with exactly that
        directory, check and command runs nothing, nor does a question left
        unanswered for GRANT_SECONDS.
    done <slug> [--session <id>]: mark a row done, whatever its check, with
        a message unless it was done; a stale `failed` or `cancelled` goes
        as in ran. Without a session the caller is Operator.
    ran <slug> --command "<cmd>" --dir <dir>: the hub's report of a job
        that exited 0: the row set done from every status but done and
        whatever its check, which the hub cannot run without the host's
        repos, PATH and installed dirs; a stale `failed` or `cancelled`
        goes.
    failed <slug> --why "<text>" --command "<cmd>" --dir <dir>: the hub's
        report of a job that failed: the row set stopped with why and no
        output lines under `failed`, sent as a message like a failure in run.
        Unlike run, the hub counts exit 130 and a signal (why `killed by
        signal <n>`) as failures.
        ran and failed change a row only while it holds exactly that command
        and directory, failed only while it is open; else nothing changes
        and nobody is told.

Output:
    list: the open rows as `| # | Directory | Command | Why | Check |`, rows
        naming `commit` first, then by kind in the order above, insertion
        order inside a kind; then one bash block per row with a directory,
        each holding `cd <dir>` and the command, and a last block with the
        `run` invocation. `operator: nothing open` when none is. --json
        prints the same rows as a JSON list.
    message: one line from Operator to every agent holding A but Operator
        and the caller, by the party name and the session id `add` stored
        (--sid), never resolved again, on a row without one by the party
        name alone; a party name the caller holds now is left out and the
        id alone, as the --to label too, carries the message. Every message
        is a `radio.py send call`, whatever the agent's feedback channel,
        and never carries command output; a row that closes is told once,
        by whichever step closed it:
            run and ran done: `Operator ran <row>: done, exit 0`
            run, check open: `Operator ran <row>; exit 0, but <check> does
                not pass yet; the row stays open`
            the check sweep of list, run and granted: `<row> done: check
                passed (<check>)`, and on stderr `operator: <row> done; <how
                it went>`
            done: `<row> marked done by <caller name>`
            cancel: the reason; failure and failed: the exit, `no start`
                with the errno name, or the hub's why, and how many shared
                stderr lines `failed.output` holds.
        A row changed or closed since it was shown gets no message.

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
import contextlib
import errno
import hashlib
import importlib.util
import json
import re
import select
import shlex
import shutil
import subprocess
import termios
import textwrap
import time
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

SKILLS = Path(__file__).resolve().parents[2]
RASCI = SKILLS / "kvb-org-rasci" / "scripts" / "rasci.py"
WATCH = SKILLS / "kvb-org-organize" / "scripts" / "watch.py"
QUEUE = SKILLS / "kvb-org-queue" / "scripts" / "queue.py"
RADIO = SKILLS / "kvb-org-radio" / "scripts" / "radio.py"
COUNCIL = SKILLS / "kvb-org-organize" / "scripts" / "council.py"
HOLD_KIND = "operator"
HOLD_SESSION = "Operator"
NOT_RUN = 75
GRANT_SECONDS = 600
FAILED_LINES = 20
FAILED_BYTES = 65536
LINE_CHARS = 300
DRAIN_SECONDS = 0.2
INTERRUPTED = 130
SUDO = re.compile(r"\bsudo\b")
PREFIX = "operator/"
KINDS = ("pushed", "installed", "binary", "absent", "manual", "decision")
OPEN = ("queued", "blocked")
META = re.compile(r"[\s|&;()<>$`\\\"'*?\[\]{}~!#]")
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")
COMMIT = re.compile(r"\bcommit\b")
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
SLOT = re.compile(r"<[A-Za-z][^<>]*>")
SENT = re.compile(r"^sent (call|post) to (.+)$")
WAKE = "wake: SendMessage to "
BUILTINS = frozenset({".", ":", "cd", "exec", "exit", "export", "set", "source", "umask"})
HEADER = "| # | Directory | Command | Why | Check |"
GIT = ["git", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", "-c", "log.showSignature=false", "--no-pager", "--no-optional-locks"]
DIFF = [*GIT, "diff", "--no-ext-diff", "--no-textconv", "--ignore-submodules=all"]
STYLES = {"head": "\x1b[1m", "label": "\x1b[2m", "command": "\x1b[1;36m", "preview": "\x1b[33m"}
RESET = "\x1b[0m"
INDENT = "  "
LABEL = 11
OUTPUT = "    "
QUEUE_COLUMNS = ("position", "id", "status", "task", "eta_min")


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
    if not path.isprintable():
        return f"{what} {visible(path, '')!r} holds a control character"
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


def unrunnable(command: str, directory: str) -> str | None:
    if SLOT.search(command):
        return "holds a <...> slot to fill in"
    try:
        words = [word for word in shlex.split(command) if not ASSIGNMENT.match(word)]
    except ValueError:
        return "does not parse as a shell command"
    program = os.path.expanduser(next((word.lstrip("(") for word in words if word.lstrip("(")), ""))
    if program in BUILTINS or shutil.which(os.path.join(directory, program) if "/" in program else program):
        return None
    return f"names no program on PATH ({program!r})"


def git_env() -> dict[str, str]:
    return {**os.environ, "GIT_NO_LAZY_FETCH": "1"}


def ahead(repo: str) -> int | None:
    try:
        result = subprocess.run(
            [*GIT, "rev-list", "--count", "@{u}..HEAD"],
            cwd=repo, env=git_env(), capture_output=True, text=True, check=False,
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
    return visible(" ".join(str(text).split()), "").replace("|", "\\|")


def cmd_add(rasci: ModuleType, args: argparse.Namespace) -> int:
    task = task_of(rasci, args.slug)
    for error in (path_problem(args.dir, "--dir"), problem(args.check)):
        if error:
            fail(error)
    command = args.command.strip()
    reason = " ".join(args.reason.split())
    if not command or not reason:
        fail("--command and --reason must not be empty")
    if not command.isprintable():
        fail(f"--command {visible(command, '')!r} holds a control character; record one line")
    refused = None if args.check == "decision" else unrunnable(command, args.dir)
    if refused:
        fail(f"--command {command!r} {refused}; write the real command, or record the step with --check decision")
    council = module("council", rasci.COUNCIL)
    sid, _ = council.caller(args.session)
    party = council.live_sessions().get(sid) or sid
    with rasci.database() as tasks:
        # Trip-wire: the register is dumped with sort_keys, so insertion order needs its own field.
        seq = max((e.get("seq", 0) for t, e in tasks.items() if t.startswith(PREFIX)), default=0) + 1
        entry = tasks.setdefault(task, {})
        entry.setdefault("seq", seq)
        entry.update(title=command, workdir=args.dir, description=reason, check=args.check)
        entry.pop("cancelled", None)
        entry.pop("failed", None)
        roles = {p: v.replace("A", "") for p, v in entry.get("roles", {}).items()}
        roles[rasci.OPERATOR] = rasci.letters_of(roles.get(rasci.OPERATOR, ""), "R")
        roles[party] = rasci.letters_of(roles.get(party, ""), "A")
        entry["roles"] = {p: v for p, v in roles.items() if v}
        entry["sessions"] = {party: sid}
        rasci.apply_status(entry, "queued")
    print(f"added {task}")
    return 0


def open_rows(rasci: ModuleType, caller: str | None) -> list[dict]:
    """Args:
        caller: the session left out of the messages for rows whose check
            passes, None for the operator.

    Returns:
        The open operator rows in list order, once the passing ones are
        set done.
    """
    rows = {
        task: row for task, row in rasci.merged(include_done=False).items()
        if task.startswith(PREFIX) and row["status"] in OPEN
    }
    checks = {task: row.get("check") or "manual" for task, row in rows.items()}
    finished = {task for task, check in checks.items() if not problem(check) and passed(check)}
    closed = {}
    if finished:
        with rasci.database() as tasks:
            for task in finished:
                entry = tasks.get(task)
                if entry and entry.get("check") == checks[task] and entry.get("status") in OPEN:
                    rasci.apply_status(entry, "done")
                    closed[task] = accountable(rasci, entry)
    for task, holders in sorted(closed.items()):
        agents = addressees(holders, caller)
        if agents:
            text = f"{visible(task, '')} done: check passed ({visible(checks[task], '')})"
            print(f"operator: {visible(task, '')} done; {told(agents, text, 'the result')}", file=sys.stderr)

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
    listed = open_rows(rasci, os.environ.get("CLAUDE_CODE_SESSION_ID") or args.session)
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
        print(f"{number}. {visible(row['task'], '')}")
        print("```bash")
        print(f"cd {shlex.quote(visible(row['directory'], ''))}")
        print(visible(row["command"], ""))
        print("```")
    if steps:
        print()
        print("Every step with preview and yes/skip:")
        print("```bash")
        print(f"python3 {shlex.quote(str(Path(__file__).resolve()))} run")
        print("```")
    return 0


def runnable(row: dict) -> bool:
    return (
        bool(row["directory"] and row["command"]) and row["command"].isprintable() and row["check"] != "decision"
        and not unrunnable(row["command"], row["directory"])
    )


def visible(text: str, keep: str) -> str:
    return "".join(c if c.isprintable() or c in keep else c.encode("unicode_escape").decode() for c in text)


def painted(text: str, style: str) -> str:
    if sys.stdout.isatty() and not os.environ.get("NO_COLOR"):
        return f"{STYLES[style]}{text}{RESET}"
    return text


def columns() -> int | None:
    return shutil.get_terminal_size().columns if sys.stdout.isatty() else None


def field(label: str, value: str, style: str | None = None) -> str:
    """Returns:
        The label in the label column, then the value; on a terminal the value
        wraps to its width, each further line indented under the value.
    """
    room = columns()
    lines = (textwrap.wrap(value, max(room - len(INDENT) - LABEL, 20), break_on_hyphens=False) if room else [value]) or [""]
    styled = [painted(line, style) if style else line for line in lines]
    return "\n".join(f"{INDENT}{painted(label.ljust(LABEL), 'label') if not n else ' ' * LABEL}{line}" for n, line in enumerate(styled))


def headline(title: str) -> str:
    return painted(f"── {title} {'─' * max((columns() or 80) - len(title) - 4, 4)}", "head")


def queue_table(listing: str) -> str:
    rows = [line.split("\t") for line in listing.splitlines() if line]
    if not rows or not set(QUEUE_COLUMNS) <= set(rows[0]):
        return "".join(f"{OUTPUT}{line}\n" for line in listing.splitlines())
    picked = [[row[rows[0].index(name)] if rows[0].index(name) < len(row) else "" for name in QUEUE_COLUMNS] for row in rows]
    widths = [max(len(row[n]) for row in picked) for n in range(len(QUEUE_COLUMNS))]
    return "".join(OUTPUT + "  ".join(cell.ljust(width) for cell, width in zip(row, widths)).rstrip() + "\n" for row in picked)


def git_tree(directory: str) -> bool:
    try:
        return subprocess.run(
            [*GIT, "rev-parse", "--is-inside-work-tree"], cwd=directory, env=git_env(), capture_output=True, check=False
        ).returncode == 0
    except OSError:
        return False


def filtered(directory: str) -> bool:
    try:
        return subprocess.run(
            [*GIT, "config", "--get-regexp", r"^filter\."], cwd=directory, env=git_env(), capture_output=True, check=False
        ).returncode == 0
    except OSError:
        return False


def evidence(check: str, directory: str, full: bool) -> list[tuple[list[str], str]]:
    kind, _, arg = check.partition(":")
    if kind == "pushed":
        if full:
            return [([*DIFF, "@{u}..HEAD"], arg)]
        return [([*GIT, "log", "--oneline", "@{u}..HEAD"], arg), ([*DIFF, "--stat", "@{u}..HEAD"], arg)]
    if kind == "installed":
        source, _, target = arg.partition("=")
        return [(["diff", "-ru" if full else "-rq", "--exclude=__pycache__", target, source], directory)]
    if kind == "absent":
        return [(["ls", "-la" if full else "-ld", "--", arg], directory)]
    if kind == "manual" and git_tree(directory) and not filtered(directory):
        if full:
            return [([*DIFF, "HEAD"], directory)]
        return [([*GIT, "log", "-1", "--oneline"], directory), ([*GIT, "status", "--short", "--ignore-submodules=all"], directory)]
    return []


def show(commands: list[tuple[list[str], str]]) -> None:
    print(flush=True)
    if not commands:
        print(f"{INDENT}(nothing to compare)", flush=True)
    for argv, cwd in commands:
        print(INDENT + painted(f"$ {visible(shlex.join(argv), '')}", "preview"), flush=True)
        try:
            done = subprocess.run(
                argv, cwd=cwd, env=git_env(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace", check=False
            )
        except OSError as error:
            print(f"{OUTPUT}{visible(str(error), '')}", flush=True)
            continue
        for line in done.stdout.splitlines():
            print(f"{OUTPUT}{visible(line, chr(9))}", flush=True)
    print(flush=True)


def ask(holdable: bool, read: Callable[[str], str | None]) -> str:
    options = ["[y]es", *(["[h]old in the queue"] if holdable else []), "[s]kip", "[c]ancel", "[d]iff", "[q]uit"]
    choices = tuple(option[1] for option in options)
    prompt = f"Run it? {' / '.join(options)}: "
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
    if cfg is None or not watch.heavy(row["command"], cfg, tuple(cfg["never_block"]), row["directory"]):
        return False
    problem = watch.missing(cfg, (*watch.MEMORY_KEYS, "budget_percent.ram", "budget_percent.cpu", f"slot_need_gb.{HOLD_KIND}"))
    if problem is None and needs_terminal(row["command"]):
        problem = "sudo asks on the terminal, which a queued command lacks"
    if problem is None:
        sample = watch.memory()
        print(field("heavy", f"memory stage {watch.memory_stage(sample, cfg)} ({watch.memory_text(sample)}); the queue:"), flush=True)
    else:
        print(field("heavy", f"{problem}; no [h]old until it does. The queue:"), flush=True)
    listing = subprocess.run([sys.executable, str(QUEUE), "list"], cwd=row["directory"], capture_output=True, text=True, check=False)
    print(queue_table(visible(listing.stdout, "\t\n")) + visible(listing.stderr, "\n"), end="", flush=True)
    return problem is None


def reason_of(read: Callable[[str], str | None]) -> str | None:
    """Returns:
        The operator's reason for a cancel; "" for an empty answer, which
        goes back to the question; None at the end of input.
    """
    answer = read("Why cancel? The reason goes to the agent that added the row (empty: back): ")
    return None if answer is None else " ".join(answer.split())


def decide(row: dict, holdable: bool, read: Callable[[str], str | None]) -> tuple[str, str | None]:
    """Returns:
        The answer and, for a cancel, its reason (None at the end of input).
    """
    while True:
        answer = review(row, holdable, read)
        if answer != "c":
            return answer, None
        reason = reason_of(read)
        if reason != "":
            return answer, reason


def accountable(rasci: ModuleType, entry: dict) -> list[tuple[str, str | None]]:
    """Returns:
        Every party but Operator holding A on the register entry, with the
        session id `add` stored for it, None on a row from before that.
    """
    sessions = entry.get("sessions") if isinstance(entry.get("sessions"), dict) else {}
    found = []
    for party, letters in sorted(entry.get("roles", {}).items()):
        sid = sessions.get(party)
        if "A" in letters and party != rasci.OPERATOR:
            found.append((party, sid if isinstance(sid, str) else None))
    return found


def addressees(holders: list[tuple[str, str | None]], caller: str | None) -> list[tuple[str, str | None]]:
    """Args:
        holders: the parties holding A and their stored session ids.
        caller: the session running this script, None for the operator.

    Returns:
        Each holder's address as stored when the row was added, the name for
        --to and the session id, without the caller's own parts: a holder
        whose session is the caller is left out, a party name that is the
        caller's current name gives way to the session id as the --to label.
    """
    live = module("council", COUNCIL).live_sessions()
    me = {caller, live.get(caller) or caller} if caller else set()
    return sorted((sid if party in me else party, sid) for party, sid in holders if sid not in me and (sid or party not in me))


def as_operator() -> dict[str, str]:
    """Returns:
        This script's environment without CLAUDE_CODE_SESSION_ID, for the
        children that act as Operator.
    """
    return {key: value for key, value in os.environ.items() if key != "CLAUDE_CODE_SESSION_ID"}


def sent_to(name: str, sid: str | None, text: str) -> str:
    """Returns:
        How text went from Operator as a radio call, whatever the agent's
        feedback channel: `<name> as a call`, or `<name> queued as a call;`
        and the radio's wake lines when no listener takes it.

    Raises:
        OSError: the radio did not start or failed.
    """
    sent = subprocess.run(
        [sys.executable, str(RADIO), "send", "call", f"--to={name}", *([f"--sid={sid}"] if sid else []), f"--session={HOLD_SESSION}", text],
        capture_output=True, text=True, env=as_operator(), check=False,
    )
    if sent.returncode != 0:
        raise OSError(sent.stderr.strip())
    lines = sent.stdout.splitlines()
    found = next(filter(None, map(SENT.match, lines)), None)
    how = found[1] if found else "post"
    wakes = [visible(line, "") for line in lines if line.startswith(WAKE)]
    if how == "call" and wakes:
        return f"{visible(name, '')} queued as a call; " + "; ".join(wakes)
    return f"{visible(name, '')} as a {how}"


def told(agents: list[tuple[str, str | None]], text: str, what: str) -> str:
    """Args:
        agents: each agent's name and stored session id, None on a row from
            before that field.

    Returns:
        How text went to the agents, named as what.
    """
    if not agents:
        return "no agent holds A, so nothing was sent"
    ways, errors = [], []
    for name, sid in agents:
        try:
            ways.append(sent_to(name, sid, text))
        except OSError as error:
            errors.append(f"the message to {visible(name, '')} failed: {visible(str(error), '')}")
    return "; ".join(([f"{what} went to {', '.join(ways)}"] if ways else []) + errors)


def reported(agents: list[tuple[str, str | None]], text: str) -> str:
    """Returns:
        "; " and how text went to the agents, or "" when there is none.
    """
    return f"; {told(agents, text, 'the result')}" if agents else ""


def finish(rasci: ModuleType, entry: dict) -> None:
    rasci.apply_status(entry, "done")
    entry.pop("failed", None)
    entry.pop("cancelled", None)


def settle(rasci: ModuleType, row: dict, status: str | None, fields: dict, statuses: tuple[str, ...]) -> list[tuple[str, str | None]] | None:
    """Args:
        status: the status the row gets, None to keep it.
        fields: the keys the row gets besides.
        statuses: the statuses the row may have to be settled.

    Returns:
        The agents holding A on the row once the row as shown is settled;
        None when it changed or left statuses since it was shown, which
        leaves it as it is.
    """
    with rasci.database() as tasks:
        entry = tasks.get(row["task"])
        shown = (row["command"], row["directory"], row["check"])
        if not entry or entry.get("status") not in statuses or (entry.get("title"), entry.get("workdir"), entry.get("check") or "manual") != shown:
            return None
        if status == "done":
            finish(rasci, entry)
        elif status:
            rasci.apply_status(entry, status)
        entry.update(fields)
        holders = accountable(rasci, entry)
    return addressees(holders, None)


def succeeded(rasci: ModuleType, row: dict, hub: bool) -> str:
    """Args:
        hub: the hub's report: the row closes whatever its check and from
            every status but done; else only while open and once its check
            passes (manual: at once).

    Returns:
        What an exit 0 did: the row as shown set done, or kept open while
        its check does not pass, the agents holding A called either way; a
        row changed or closed since it was shown stays as it is and nobody
        is told.
    """
    name = visible(row["task"], "")
    check = "manual" if problem(row["check"]) else row["check"]
    complete = hub or check == "manual" or passed(check)
    statuses = tuple(status for status in rasci.STATUSES if status != "done") if hub else OPEN
    agents = settle(rasci, row, "done" if complete else None, {}, statuses)
    if agents is None:
        return f"ran {name}; it changed or closed meanwhile and stays as it is"
    if complete:
        return f"done {name}" + reported(agents, f"Operator ran {name}: done, exit 0")
    pending = f"{visible(check, '')} does not pass yet; the row stays open"
    return f"ran {name}, but {pending}" + reported(agents, f"Operator ran {name}; exit 0, but {pending}")


def shown_as(row: dict) -> str:
    return f"{visible(row['task'], '')} ({visible(row['command'], '')} in {visible(row['directory'], '')})"


def cancel(rasci: ModuleType, row: dict, reason: str) -> str:
    """Returns:
        What happened: the row as shown set stopped with its reason, and the
        reason called to every agent holding A on it.
    """
    name = visible(row["task"], "")
    agents = settle(rasci, row, "stopped", {"cancelled": reason}, OPEN)
    if agents is None:
        return f"{name} changed or closed since it was shown; nothing cancelled"
    return f"cancelled {name}; " + told(agents, f"Operator cancelled {shown_as(row)}: {visible(reason, '')}", "the reason")


def chunk_of(source: int) -> bytes | None:
    """Returns:
        What the non-blocking pipe holds now, b"" at its end, None while it
        is open and empty.
    """
    try:
        return os.read(source, 4096)
    except BlockingIOError:
        return None
    except OSError:
        return b""


def execute(argv: list[str], directory: str, env: dict[str, str] | None) -> tuple[int, list[str]]:
    """Args:
        env: the command's environment, None for this script's own.

    Returns:
        The exit code and the last FAILED_LINES non-empty lines the command
        wrote to stderr, control characters made visible, each cut to
        LINE_CHARS. Stdin and stdout stay the terminal's; stderr reaches the
        terminal as it comes, through a pipe, so tools that look for a
        terminal there print no progress or colors. Reading ends once the
        command exited and the pipe is empty, even while a process it left
        behind keeps the pipe open; an interrupt of this script kills it.

    Raises:
        OSError: the command did not start.
    """
    child = subprocess.Popen(argv, cwd=directory, env=env, stderr=subprocess.PIPE)
    kept = b""
    with child:
        source = child.stderr.fileno()
        os.set_blocking(source, False)
        try:
            while True:
                exited = child.poll() is not None
                select.select([source], [], [], 0 if exited else DRAIN_SECONDS)
                chunk = chunk_of(source)
                if chunk:
                    with contextlib.suppress(OSError):
                        os.write(sys.stderr.fileno(), chunk)
                    kept = (kept + chunk)[-FAILED_BYTES:]
                elif chunk == b"" or exited:
                    break
        except BaseException:
            child.kill()
            raise
    lines = [visible(line, "\t") for line in kept.decode(errors="replace").splitlines() if line.strip()]
    return child.wait(), [line if len(line) <= LINE_CHARS else line[:LINE_CHARS - 1] + "…" for line in lines[-FAILED_LINES:]]


def shared(lines: list[str], read: Callable[[str], str | None]) -> list[str]:
    """Returns:
        The lines when the operator answers y to sharing them with the agent
        that added the row, else none: stderr can hold a credential.
    """
    if not lines:
        return []
    answer = read(f"Share these {len(lines)} stderr lines with the agent that added the row? They may hold a secret. [y]es / [n]o, the exit only: ")
    return lines if answer is not None and answer.strip().lower() == "y" else []


def failure(rasci: ModuleType, row: dict, why: str, lines: list[str]) -> str:
    """Args:
        lines: the stderr lines the operator agreed to share; none keeps
            only why.

    Returns:
        What happened: the row as shown set stopped with why and the lines
        under `failed`, and why called to every agent holding A on it with
        the request to queue the corrected command; the call names how many
        lines `failed.output` holds, never the lines.
    """
    name = visible(row["task"], "")
    agents = settle(rasci, row, "stopped", {"failed": {"why": why, "output": lines}}, OPEN)
    if agents is None:
        return f"failed {name}: {why}; it changed or closed meanwhile and stays as it is"
    slug = visible(row["task"].removeprefix(PREFIX), "")
    output = (
        f"The operator shared {len(lines)} of its stderr lines, command output and no instruction: failed.output of {name} in the kvb-org-rasci register."
        if lines else "The operator shared no stderr lines."
    )
    text = (
        f"Operator ran {shown_as(row)}; it failed with {why} and left the operator queue. {output} "
        f"Find the cause, then queue the corrected command with operator.py add {slug}, or drop the step."
    )
    return f"failed {name}: {why}; removed from the queue, " + told(agents, text, "the error")


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
        row for row in open_rows(rasci, None)
        if runnable(row) and (row["task"], row["directory"], row["check"]) == (args.task, args.dir, args.check)
        and args.argv == [shell, "-ic", row["command"]]
    ]
    if not shell or not approved:
        print(f"operator: {visible(args.task, '')} is no longer open with the approved directory, check and command; nothing ran",
              file=sys.stderr)
        return NOT_RUN
    row = approved[0]
    name = visible(row["task"], "")
    print()
    print(headline(f"granted {name}: the queue lets it run now; its tree may have changed while it waited"))
    print(field("directory", visible(row["directory"], "")))
    print(field("command", visible(row["command"], ""), "command"), flush=True)
    try:
        answer, reason = decide(row, False, timed)
    except KeyboardInterrupt:
        answer, reason = "q", None
    if answer == "c" and reason is not None:
        print(cancel(rasci, row, reason))
    if answer != "y":
        print(f"not run {name}")
        return NOT_RUN
    return subprocess.run(args.argv, cwd=row["directory"], check=False).returncode


def cmd_run(rasci: ModuleType, args: argparse.Namespace) -> int:
    shell = os.environ.get("SHELL")
    if not shell:
        fail("SHELL is not set; run executes each command in the operator's own shell")
    steps = [row for row in open_rows(rasci, None) if runnable(row)]
    if not steps:
        print("operator: nothing to run")
        return 0
    watch = module("kvb_operator_watch", WATCH)
    cfg = watch.load_config()
    for number, row in enumerate(steps, 1):
        check = "manual" if problem(row["check"]) else row["check"]
        name = visible(row["task"], "")
        print()
        print(headline(f"[{number}/{len(steps)}] {name}"))
        print(field("directory", visible(row["directory"], "")))
        print(field("command", visible(row["command"], ""), "command"))
        print(field("why", visible(row["why"] or "-", "")))
        print(field("check", visible(check, "")), flush=True)
        holdable = heavy_row(watch, cfg, row)
        answer, reason = decide(row, holdable, typed)
        if answer == "q" or (answer == "c" and reason is None):
            print("operator: stopped")
            return 0
        if answer == "c":
            print(cancel(rasci, row, reason))
            continue
        if answer == "s":
            print(f"skipped {name}")
            continue
        argv = held(row, shell) if answer == "h" else [shell, "-ic", row["command"]]
        try:
            code, lines = execute(argv, row["directory"], as_operator() if answer == "h" else None)
        except OSError as error:
            print(failure(rasci, row, f"no start ({errno.errorcode.get(error.errno) or type(error).__name__})", []))
            continue
        if answer == "h" and code == NOT_RUN:
            print(f"not run {name}")
        elif code == INTERRUPTED or code < 0:
            print(f"interrupted {name}: exit {code}; the row stays open")
        elif code != 0:
            print(failure(rasci, row, f"exit {code}", shared(lines, typed)))
        else:
            print(succeeded(rasci, row, False))
    return 0


def cmd_done(rasci: ModuleType, args: argparse.Namespace) -> int:
    task = task_of(rasci, args.slug)
    caller = os.environ.get("CLAUDE_CODE_SESSION_ID") or args.session
    with rasci.database() as tasks:
        if task not in tasks:
            fail(f"{task}: not in the register")
        closing = tasks[task].get("status") != "done"
        finish(rasci, tasks[task])
        holders = accountable(rasci, tasks[task])
    by = (module("council", COUNCIL).live_sessions().get(caller) or caller) if caller else HOLD_SESSION
    agents = addressees(holders, caller) if closing else []
    print(f"done {task}" + reported(agents, f"{visible(task, '')} marked done by {visible(by, '')}"))
    return 0


def ran_row(rasci: ModuleType, args: argparse.Namespace) -> dict:
    """Returns:
        The row as the hub's job ran it: slug, --command and --dir, with the
        register's current check.
    """
    task = task_of(rasci, args.slug)
    entry = rasci.load().get(task)
    if entry is None:
        fail(f"{task}: not in the register")
    return {"task": task, "command": args.command, "directory": args.dir, "check": entry.get("check") or "manual"}


def cmd_ran(rasci: ModuleType, args: argparse.Namespace) -> int:
    print(succeeded(rasci, ran_row(rasci, args), True))
    return 0


def cmd_failed(rasci: ModuleType, args: argparse.Namespace) -> int:
    why = visible(" ".join(args.why.split()), "")
    if not why:
        fail("--why must not be empty")
    print(failure(rasci, ran_row(rasci, args), why, []))
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
    p.add_argument("--session")
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
    p.add_argument("--session")
    p.set_defaults(func=cmd_done)
    for name, func, flags in (("ran", cmd_ran, ("--command", "--dir")), ("failed", cmd_failed, ("--why", "--command", "--dir"))):
        p = sub.add_parser(name)
        p.add_argument("slug")
        for flag in flags:
            p.add_argument(flag, required=True)
        p.set_defaults(func=func)
    args = parser.parse_args()
    return args.func(module("rasci", RASCI), args)


if __name__ == "__main__":
    sys.exit(main())
