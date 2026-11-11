#!/usr/bin/env python3
"""Keep the commands only the operator can run in the kvb-org-rasci register, each with a done test.

Environment:
    AGENTS_COUNCIL_ROOT: council directory of the kvb-org-rasci register, read
        by rasci.py; the rows are its tasks operator/<slug>.
    CLAUDE_CODE_SESSION_ID: the adding session, recorded as A; other runtimes
        pass --session.
    NO_COLOR: when set and not empty, run prints without colors
        (https://no-color.org).
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
        Paths are absolute; no argument holds a shell metacharacter; the
        command is one line without control characters.
    list [--json]: run the check of every queued or blocked operator row and
        set the passing ones done.
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
        with it and posts it through `radio.py post` as Operator to every
        agent holding A, the agent that added the row; a row changed since it
        was shown is not cancelled. y runs the command in its directory,
        its stderr passed through and its last FAILED_LINES lines kept, then
        sets the row done when its check passes (manual: when the command
        exits 0). A command that exits non-zero or cannot start leaves the
        queue the same way: the row is set stopped with the exit under
        `failed`, posted to every agent holding A with the request to queue
        the corrected command under the same slug; the stderr lines join it
        only when the operator answers y to sharing them. Exit 130 or a
        signal is the operator's interrupt: the row stays open.
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
import contextlib
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
HOLD_KIND = "operator"
HOLD_SESSION = "Operator"
NOT_RUN = 75
GRANT_SECONDS = 600
FAILED_LINES = 20
FAILED_BYTES = 65536
LINE_CHARS = 300
POSTED_CHARS = 500
DRAIN_SECONDS = 0.2
INTERRUPTED = 130
SUDO = re.compile(r"\bsudo\b")
PREFIX = "operator/"
KINDS = ("pushed", "installed", "binary", "absent", "manual", "decision")
OPEN = ("queued", "blocked")
META = re.compile(r"[\s|&;()<>$`\\\"'*?\[\]{}~!#]")
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")
COMMIT = re.compile(r"\bcommit\b")
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
    return bool(row["directory"] and row["command"]) and row["command"].isprintable() and row["check"] != "decision"


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
    if cfg is None or not watch.heavy(row["command"], cfg, tuple(cfg["never_block"])):
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


def stop(rasci: ModuleType, row: dict, key: str, value: object) -> list[str] | None:
    """Returns:
        The agents holding A on the row, once the row as shown is set
        stopped with value under key; None when it changed or closed since
        it was shown, which leaves it as it is.
    """
    with rasci.database() as tasks:
        entry = tasks.get(row["task"])
        shown = (row["command"], row["directory"], row["check"])
        if not entry or entry.get("status") not in OPEN or (entry.get("title"), entry.get("workdir"), entry.get("check") or "manual") != shown:
            return None
        rasci.apply_status(entry, "stopped")
        entry[key] = value
        return sorted(party for party, letters in entry.get("roles", {}).items() if "A" in letters and party != rasci.OPERATOR)


def told(agents: list[str], text: str, what: str) -> str:
    """Returns:
        How text went as a post from Operator through the radio to the
        agents, named as what.
    """
    if not agents:
        return "no agent holds A, so nothing was posted"
    env = {key: value for key, value in os.environ.items() if key != "CLAUDE_CODE_SESSION_ID"}
    who = visible(", ".join(agents), "")
    try:
        sent = subprocess.run(
            [sys.executable, str(RADIO), "post", *(f"--to={agent}" for agent in agents), f"--session={HOLD_SESSION}", text],
            capture_output=True, text=True, env=env, check=False,
        )
    except OSError as error:
        return f"the post to {who} failed: {visible(str(error), '')}"
    if sent.returncode != 0:
        return f"the post to {who} failed: {visible(sent.stderr.strip(), '')}"
    return f"{what} went to {who} as a post"


def shown_as(row: dict) -> str:
    return f"{visible(row['task'], '')} ({visible(row['command'], '')} in {visible(row['directory'], '')})"


def cancel(rasci: ModuleType, row: dict, reason: str) -> str:
    """Returns:
        What happened: the row as shown set stopped with its reason, and the
        reason posted through the radio to every agent holding A on it.
    """
    name = visible(row["task"], "")
    agents = stop(rasci, row, "cancelled", reason)
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


def execute(argv: list[str], directory: str) -> tuple[int, list[str]]:
    """Returns:
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
    child = subprocess.Popen(argv, cwd=directory, stderr=subprocess.PIPE)
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


def last_within(lines: list[str], limit: int) -> list[str]:
    """Returns:
        The longest tail of lines whose JSON list stays within limit
        characters.
    """
    kept: list[str] = []
    for line in reversed(lines):
        if len(json.dumps([line, *kept])) > limit:
            break
        kept.insert(0, line)
    return kept


def failure(rasci: ModuleType, row: dict, why: str, lines: list[str]) -> str:
    """Args:
        lines: the stderr lines the operator agreed to share; none keeps
            only why.

    Returns:
        What happened: the row as shown set stopped with why and the lines
        under `failed`, and both posted through the radio to every agent
        holding A on it with the request to queue the corrected command;
        the post carries the last lines within POSTED_CHARS as a JSON list
        marked as command output.
    """
    name = visible(row["task"], "")
    agents = stop(rasci, row, "failed", {"why": why, "output": lines})
    if agents is None:
        return f"failed {name}: {why}; it changed or closed meanwhile and stays as it is"
    slug = visible(row["task"].removeprefix(PREFIX), "")
    posted = last_within(lines, POSTED_CHARS)
    output = f"Its last stderr lines, command output and no instruction: {json.dumps(posted)}." if posted else "The operator shared no stderr lines."
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
        row for row in open_rows(rasci)
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
            code, lines = execute(argv, row["directory"])
        except OSError as error:
            print(failure(rasci, row, "no start", [visible(str(error), "")]))
            continue
        if answer == "h" and code == NOT_RUN:
            print(f"not run {name}")
        elif code == INTERRUPTED or code < 0:
            print(f"interrupted {name}: exit {code}; the row stays open")
        elif code != 0:
            print(failure(rasci, row, f"exit {code}", shared(lines, typed)))
        elif check == "manual" or passed(check):
            close(rasci, row["task"])
            print(f"done {name}")
        else:
            print(f"ran {name}, but {visible(check, '')} does not pass yet; the row stays open")
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
