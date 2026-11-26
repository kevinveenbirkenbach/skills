#!/usr/bin/env python3
"""Queue the heavy jobs of parallel agents and grant them in a fixed order, without messages.

Usage:
    queue.py hold --kind KIND --task TASK [--need-gb N] [--hotfix SLUG] [--session ID]
        [--receipt LEVEL --log PATH] -- CMD...
    queue.py list [--json]
    queue.py history
    queue.py cancel ID [--session ID]
    queue.py block     hook (PreToolUse on Bash through hooks.py pre-bash)

Environment:
    AGENTS_COUNCIL_ROOT, XDG_STATE_HOME, HOME: the shared state directory the
        kvb-org-organize councilroot.py resolves, on which every agent on the
        host agrees. The queue is
        <root>/queue.json, every read-modify-write holds <root>/queue.lock.
        Each hold keeps an exclusive flock on <root>/holds/<tag>.lock, shared
        with its command, from before its entry exists until it leaves; an
        entry whose lock nobody holds is dead. Pids cannot tell, because every
        sandboxed tool call has its own PID namespace.
        Every finished job appends a row (history.py) to
        <root>/queue-history.jsonl; the watch hook of watch.py keeps a copy in
        ~/.local/state/agents-council/queue-history.jsonl, and reading merges
        both by row id.
    AGENTS_COUNCIL_CONFIG: the config of the kvb-org-organize watch.py;
        ~/.claude/agents-council/config.json unless set.
    CLAUDE_CODE_SESSION_ID: the caller's session, taken over --session; other
        runtimes pass --session.
    CLAUDE_PROJECT_DIR: block reads the project's .claude/settings.json and
        settings.local.json there, next to the managed and user settings.

Args:
    hold: enqueue CMD, then every POLL_SECONDS evaluate the whole queue under
        the lock until this entry is granted; while the head waits blocked,
        that poll escalates over kvb-org-radio by ESCALATION, starts the
        watch.py low-risk cleanup once per head when disk alone (its stage
        or the floor) blocks it and nothing waiting fits, logs its report
        once and posts to Main once when disk still blocks the head
        (stalled()); its mayday sets no radio silence, and any silence
        stops grants; a drain starts only after DEBOUNCE_SECONDS of polls
        proposing it (latched()); measure disk, RAM and CPU, run
        CMD in the current directory with inherited stdio in a session of its
        own, forward SIGINT and SIGTERM to its process group, measure every
        POLL_SECONDS and at its end, end its process tree once the tree stood
        still for standstill.HUNG_SECONDS (supervise()), record its history
        row and leave the queue. The entry carries its code (a hash of this
        file and the SIBLINGS); a poll that finds other code installed in
        ~/.agents/skills leaves the queue ungranted and restarts the same hold
        with the installed queue.py, which keeps its entry id, place and
        enqueue time (hand_over()).
        --kind: a key of slot_need_gb in the config; a light one
            (light_kinds or watch.LIGHT_KIND) refuses a command watch.light()
            does not recognise, naming watch.queue_hold().
        --task: an open task of the kvb-org-rasci register; its rank orders
            the queue, and the operator's agent order (`rasci.py agents
            order`) of the holding session breaks ties. While one of its
            `after` tasks in the register is neither done nor stopped, the
            entry waits with `waits for <task>` (the reason names the
            `rasci.py set --drop-after` that lifts it), after every other
            entry, and reserves nothing.
        --need-gb: disk the job takes, in GB; when omitted the need learned
            for the command's signature, else slot_need_gb[kind].
        --hotfix: the slug of the register row hotfix/<slug> the job proves;
            hotfix jobs go first.
        --session: the caller's session for runtimes other than Claude Code.
        --receipt: a gate level of kvb-check-gate's gates.py above none; the
            command's stdout and stderr go to --log instead, and when it
            exits 0 on the tree it started on (gates.py tree of the workdir
            before and after) hold records a receipt for that tree, level
            and log, with INFINITO_TEST_GPU of its environment.
    list: a header, then one line per entry: position (run for active jobs),
        id, status, kind, task, need GB, minutes waited, ETA minutes (until a
        running job ends or a waiting one starts, from learned medians; - while
        one is unknown), workdir, reason (the one the holder saw at its last
        poll, host load included, such as `waits in line behind <id>` or
        `drained for <id>`, the head's after `escalated <step>: ` once the
        stall reached it; `backfilled` for a job started past a blocked one;
        led by `suspect hung (<runtime> min)` for an active job past
        standstill.suspect_seconds() (suspected()); prefixed when the entry
        runs other code than the installed one).
        Entries of dead holders are dropped first.
        --json: print the same rows as a JSON list (listed()), each with
            the trace of the evaluate() pass that set its reason.
    history: a markdown table per command signature and one per kind of what
        the last 30 days of history teach, with each slot limit's source.
    cancel ID: remove the caller's waiting entry ID; its hold exits 3.
    block: read the hook payload on stdin. The permission matcher sees only
        `queue.py hold`, so every hold in the command is parsed like hold
        itself, and a held command any of whose word-started tails meets a
        Bash deny rule of the settings is refused, one meeting an ask rule
        asks the operator, with or without queue_enforce; a hold that cannot
        be parsed or checked is refused. With queue_enforce true in the config,
        refuse a command that watch.heavy() calls heavy or that runs
        `gate.py run|hold`, unless it matches never_block or runs `queue.py
        hold`.

Config keys: budget_percent {ram, cpu}, required: the active and granted jobs'
learned footprints (history.footprint, the whole budget for a kind not learned
yet) may sum to at most these percentage points, a job alone always fits;
slot_limits {kind: N}, optional, caps the learned slot limit of a kind from
above (history.slot_limits); ram_cap_percent {kind: percent above 0 up to
100}, optional, caps the RAM share history.footprint and history.ceiling
book for a job of that kind, the learned shares stay raw; exclusive_kinds [kind] and light_kinds [kind],
optional: a job of an exclusive kind runs only beside jobs of light kinds, and
no job of another kind starts beside it; queue_enforce (bool), optional, read by block only. The watch.py keys
disk, thresholds_gb (stop is the floor every grant leaves free), slot_need_gb (the disk seed per kind), load_limits (every grant
also needs CPU busy below cpu_percent and RAM used plus the job's learned RAM
share, the live admit records (admit()) and the young jobs' ramp
(ramping_ram()) below mem_percent; both bound the learned slot limits), memory_limits (no
grant at memory stage stop), heavy_commands and never_block are used as
watch.py documents them. A signature is `<repository>: <command signature>`
(aliases()).

Exit codes:
    hold: the command's exit code unchanged, 128+N when signal N ended it,
        standstill.HUNG_EXIT (124) when hold ended it for standing still;
        a command exiting 75 (EX_TEMPFAIL: it did no work, such as a declined
        `operator.py granted`) leaves no history row;
        before the command started 2 on a usage or config error or when it
        cannot start or cannot restart with the installed code, 3 when cancel
        removed the entry, 128+N when signal N reached hold; after a restart,
        the installed hold's exit code.
    list, history: 0 done, 2 config error.
    cancel: 0 removed, 2 no waiting entry of the caller with that id.
    block: 0 allow, or ask when it prints an ask decision, or a council root
        that watch.py refuses; 2 refuse the tool call; every other error allows.
    list, history, cancel, hold: 2 on a council root that watch.py refuses.
"""

from __future__ import annotations

# Trip-wire: run as a script, this file shadows the stdlib queue module, so nothing here
# may import a module that imports queue (logging.handlers, concurrent.futures, multiprocessing).
import argparse
import contextlib
import fcntl
import functools
import hashlib
import importlib.util
import json
import os
import re
import select
import shlex
import signal
import stat
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Callable, Iterator
from pathlib import Path
from types import ModuleType
from typing import NoReturn

SKILLS = Path(__file__).resolve().parents[2]
SIBLINGS = {
    "watch": SKILLS / "kvb-org-organize" / "scripts" / "watch.py",
    "council": SKILLS / "kvb-org-organize" / "scripts" / "council.py",
    "rasci": SKILLS / "kvb-org-rasci" / "scripts" / "rasci.py",
    "history": Path(__file__).resolve().parent / "history.py",
    "standstill": Path(__file__).resolve().parent / "standstill.py",
    "nofollow": SKILLS / "kvb-org-organize" / "scripts" / "nofollow.py",
    "councilroot": SKILLS / "kvb-org-organize" / "scripts" / "councilroot.py",
}
TOOLS = {"gates": SKILLS / "kvb-check-gate" / "scripts" / "gates.py"}
HOST_SKILLS = Path.home() / ".agents" / "skills"
EXE = os.path.realpath(sys.executable)
CODE_FILES = tuple(path.relative_to(SKILLS) for path in (Path(__file__).resolve(), *SIBLINGS.values()))
POLL_SECONDS = 20
CLAIM_SECONDS = 3 * POLL_SECONDS
HOUR = 3600
CANCELLED = 3
NOT_RUN = 75
RAMP_SECONDS = 900
SETUP =frozenset({"cd", "pushd", "set", "source", ".", "export", "umask", "shopt", "trap"})
FORWARDED =(signal.SIGINT, signal.SIGTERM)
GATE = re.compile(r"\bgate\.py\s+(run|hold)\b")
THROUGH_QUEUE = re.compile(r"\bqueue\.py\s+hold\b")
BASH_RULE = re.compile(r"Bash(?:\((.*)\))?", re.DOTALL)
RULE_PART = re.compile(r"( \*|\*)")
BUDGET_KEYS = ("budget_percent.ram", "budget_percent.cpu")
HOTFIX = "hotfix/"
PYTEST = frozenset({"pytest", "py.test"})
XDIST = frozenset({"-n", "--numprocesses"})
XDIST_LONG = "--numprocesses="
ADDOPTS = "PYTEST_ADDOPTS="
FROZEN = "footprint"
ALIASES = "aliases"
ADMIT = "admit"
ADMITS = "admits"
ADMIT_SECONDS = 120
GRANTED_MEM = "granted_mem"
CLAIMS = "claims"
DRAIN = "drain"
GRANTED = "granted_at"
STALL = "stall"
CLEANUP = "cleanup"
HANDOVER = "handover"
STACK = "stack:"
COMPOSE_FILES = ("compose.yaml", "compose.yml", "docker-compose.yaml", "docker-compose.yml")
PROJECT_ENV = re.compile(r"^COMPOSE_PROJECT_NAME=(.*)$", re.MULTILINE)
COMPOSE_NAME = re.compile(r"^name:[ \t]*([^#\n]*)", re.MULTILINE)
PROJECT_CHARS = re.compile(r"[a-z0-9_-]")
SLOT = "slot:"
SLOT_ENV = re.compile(r"^INFINITO_INSTANCE=(.*)$", re.MULTILINE)
SLOT_FILES = ("custom.env", ".env", "default.env")
BLOCKED = "blocked_since"
DEBOUNCE_SECONDS = 3 * POLL_SECONDS
DRAIN_AFTER_SECONDS = HOUR
IDLE_SECONDS = 30 * 60
RADIO = SKILLS / "kvb-org-radio" / "scripts" / "radio.py"
RADIO_SECONDS = 30
PREFIX = "kvb-org-queue: "
TEXT = "<text>"
ESCALATION = (
    (30, "post", ("post", TEXT, "--to", "Main")),
    (60, "call", ("send", "call", TEXT, "--to", "Main")),
    (120, "security", ("send", "security", TEXT)),
    (240, "pan-pan", ("send", "pan-pan", TEXT)),
    (24 * 60, "mayday", ("send", "mayday", TEXT, "--no-silence")),
)
STEPS = {step: (minutes, argv) for minutes, step, argv in ESCALATION}


@functools.cache
def sibling(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"kvb_queue_{name}", {**SIBLINGS, **TOOLS}[name])
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


watch = sibling("watch")
history = sibling("history")
standstill = sibling("standstill")
nofollow = sibling("nofollow")
STORE = watch.ROOT / "queue.json"
LOCK = watch.ROOT / "queue.lock"
HOLDS = watch.ROOT / "holds"
TAG = re.compile(r"\d+-\d+")
SILENCE = watch.ROOT / "radio-silence.json"
HISTORIES = (watch.HISTORY, watch.KEPT_HISTORY)
LEARNED: dict[str, tuple[dict, dict]] = {}


def code_of(root: Path) -> str | None:
    try:
        return hashlib.sha256(b"".join((root / name).read_bytes() for name in CODE_FILES)).hexdigest()[:12]
    except OSError:
        return None


CODE = code_of(SKILLS)


class Stale(Exception):
    pass


class Disk(str):
    pass


class Outside(str):
    pass


def fail(message: str) -> NoReturn:
    print(f"queue: {message}", file=sys.stderr)
    sys.exit(2)


def config() -> dict:
    cfg, _ = watch.announced_config()
    if cfg is None:
        fail(f"no config at {watch.CONFIG}; the queue reads the kvb-org-organize watch config")
    problem = watch.missing(cfg, (*BUDGET_KEYS, *watch.MEMORY_KEYS)) or cap_problem(cfg)
    if problem is not None:
        fail(problem)
    return cfg


def cap_problem(cfg: dict) -> str | None:
    """Returns:
        Why history.RAM_CAP is no {kind: percent above 0 up to 100} map, None
        when it is one or unset.
    """
    caps = cfg.get(history.RAM_CAP, {})
    if isinstance(caps, dict) and all(
        isinstance(cap, (int, float)) and not isinstance(cap, bool) and 0 < cap <= 100 for cap in caps.values()
    ):
        return None
    return f"{history.RAM_CAP} is no {{kind: percent above 0 up to 100}} map"


def fresh(cfg: dict) -> dict:
    """Returns:
        The config as it stands now, else cfg while the file is missing,
        unusable (watch.checked_config()) or incomplete, so a half-saved
        edit never ends a wait.
    """
    try:
        now = watch.checked_config(watch.load_config())
    except watch.UNUSABLE:
        return cfg
    if (watch.missing(now, (*BUDGET_KEYS, *watch.MEMORY_KEYS)) or cap_problem(now)) is not None:
        return cfg
    return now


def caps(cfg: dict) -> dict[str, int]:
    return cfg.get("slot_limits", {})


def marks(paths: tuple[Path, ...]) -> tuple[tuple[int, int, int] | None, ...]:
    found = []
    for path in paths:
        try:
            info = path.stat()
        except OSError:
            found.append(None)
        else:
            found.append((info.st_ino, info.st_mtime_ns, info.st_size))
    return tuple(found)


def learned(cfg: dict, now: float) -> tuple[dict[str, dict], dict[str, dict]]:
    """Returns:
        history.learn over HISTORIES, computed once per process while both
        files keep their inode, mtime and size and cfg its learning keys; a
        row that leaves the window meanwhile counts until the next change.
    """
    key = json.dumps([marks(HISTORIES), cfg.get("light_kinds"), cfg.get(history.RAM_CAP), cfg.get("load_limits")], sort_keys=True)
    if key not in LEARNED:
        LEARNED.clear()
        LEARNED[key] = history.learn(history.read(HISTORIES), now, cfg)
    return LEARNED[key]


def limits(cfg: dict, kinds: dict[str, dict], entries: list[dict]) -> dict[str, tuple[int, str]]:
    return history.slot_limits(kinds, caps(cfg), {*cfg["slot_need_gb"], *(e["kind"] for e in entries)})


@functools.cache
def repository(path: str) -> str:
    try:
        common = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=path, capture_output=True, text=True, check=False,
        )
    except OSError:
        return os.path.basename(path)
    if common.returncode != 0:
        return os.path.basename(path)
    return os.path.basename(os.path.dirname(common.stdout.strip()))


def command_words(argv: list[str]) -> list[str]:
    """Returns:
        The command a wrapper runs: watch.program() unwrapped, the first simple
        command of `sh -c` code that is no setup such as cd, set or source,
        the tail after `--` of a Python script such as gate.py hold or
        operator.py granted.
    """
    run = watch.program(argv) or argv
    code = watch.inline_code(run)
    inner = first_command(code) if code is not None else script_tail(run)
    return run if inner is None else command_words(inner)


def first_command(code: str) -> list[str] | None:
    try:
        parts = [part for part in map(watch.program, watch.segments(code)) if part and os.path.basename(part[0]) not in SETUP]
    except ValueError:
        return None
    return parts[0] if parts else None


def script_tail(run: list[str]) -> list[str] | None:
    if len(run) > 2 and watch.PYTHON.fullmatch(os.path.basename(run[0])) and run[1].endswith(".py") and "--" in run[2:-1]:
        return run[run.index("--", 2) + 1 :]
    return None


def aliases(workdir: str, argv: list[str], cwd: str | None) -> tuple[str, ...]:
    """Args:
        workdir: the hold's workdir, which names the repository.
        argv: the command as held.
        cwd: the directory the hold runs it in, None when unknown
            (runner_signature()).

    Returns:
        `<repository>: <runner_signature or else history.signature of
        command_words>`, then `<repository>: <history.signature>`, the
        signature history rows before the runner naming carry, when it
        differs. The repository is the directory holding the main checkout's
        .git, so every worktree of one repository shares it, else the
        workdir's name; one make test of two repositories stays apart.
    """
    words = command_words(argv)
    repo = repository(workdir)
    plain = f"{repo}: {history.signature(words)}"
    runner = runner_signature(words, argv, cwd)
    return (plain,) if runner is None else tuple(dict.fromkeys((f"{repo}: {runner}", plain)))


def runner_signature(words: list[str], argv: list[str], cwd: str | None) -> str | None:
    """Args:
        words: the command, command_words() of argv.
        argv: the command as held; a PYTEST_ADDOPTS= word in it adds its
            options before the command's own.
        cwd: the directory the hold runs it in, None when unknown; a
            discover run then counts by its pattern alone
            (watch.one_discovered()).

    Returns:
        `<runner> files=N` when each of the N tests a pytest or unittest run
        names is one file or module, a discover pattern only when exactly
        one file below its start directory matches it, else `<runner>
        paths=N` (0 for the whole suite), then ` workers=W` for the last
        pytest-xdist count; None for other commands. One test file and a
        suite never share what they learn.
    """
    name, args = watch.tool(words)
    named = tests_named(name, args)
    if named is None:
        return None
    if name == "unittest" and args[:1] == ["discover"]:
        prefix = argv[: argv.index(words[0])] if words[0] in argv else []
        files = watch.one_discovered(args[1:], watch.started_in(prefix, cwd))
    else:
        files = bool(named) and all(name == "unittest" or watch.TEST_FILE.fullmatch(test) for test in named)
    shape = f"{'unittest' if name == 'unittest' else 'pytest'} {'files' if files else 'paths'}={len(named)}"
    count = workers([*addopts(argv), *args]) if name in PYTEST else None
    return shape if count is None else f"{shape} workers={count}"


def addopts(argv: list[str]) -> list[str]:
    found = [word[len(ADDOPTS):] for word in argv if word.startswith(ADDOPTS)]
    return found[-1].split() if found else []


def tests_named(name: str, args: list[str]) -> list[str] | None:
    if name in PYTEST:
        return watch.operands(args, watch.PYTEST_VALUE_OPTIONS)
    if name != "unittest":
        return None
    if args[:1] == ["discover"]:
        return watch.discover_patterns(args[1:])
    return watch.operands(args, watch.UNITTEST_VALUE_OPTIONS)


def workers(args: list[str]) -> str | None:
    found = None
    for at, word in enumerate(args):
        if word in XDIST and at + 1 < len(args):
            found = args[at + 1]
        elif word.startswith(XDIST_LONG):
            found = word[len(XDIST_LONG):]
        elif word.startswith("-n") and not word.startswith("--") and len(word) > 2:
            found = word[2:].removeprefix("=")
    return found


def aliases_of(entry: dict) -> tuple[str, ...]:
    """Returns:
        The aliases the holder stored at enqueue, in the directory the
        command starts in, else (an entry of older code, whose directory is
        unknown) those derived here.
    """
    if ALIASES in entry:
        return tuple(entry[ALIASES])
    return aliases(entry["workdir"], shlex.split(entry["cmd"]), None)


def key_of(entry: dict) -> tuple[str, tuple[str, ...]]:
    return entry["kind"], aliases_of(entry)


def claims_of(path: str) -> list[str]:
    """Returns:
        What a job whose workdir is path holds alone: path, then
        `stack:<project>` when path holds a compose file, the project being
        COMPOSE_PROJECT_NAME of path/.env, else the top-level `name:` of the
        first of COMPOSE_FILES there, else the name of path normalized as
        docker compose normalizes it, then `slot:<n>` for the
        INFINITO_INSTANCE of the first of SLOT_FILES below path that pins
        one, so custom.env wins and an unpinned core checkout holds the slot
        of its default.env.
    """
    slots = slot_of(path)
    files = tuple(name for name in COMPOSE_FILES if os.path.isfile(os.path.join(path, name)))
    if not files:
        return [path, *slots]
    named = [value for value in pinned(path, PROJECT_ENV, (".env",)) if value][-1:]
    named = named or [value for value in pinned(path, COMPOSE_NAME, files[:1]) if value][:1]
    project = named[-1] if named else "".join(PROJECT_CHARS.findall(os.path.basename(path).lower()))
    return [path, f"{STACK}{project.lstrip('_-')}", *slots]


def slot_of(path: str) -> list[str]:
    for name in SLOT_FILES:
        found = [value for value in pinned(path, SLOT_ENV, (name,)) if value]
        if found:
            return [f"{SLOT}{found[-1]}"]
    return []


def pinned(path: str, key: re.Pattern, names: tuple[str, ...]) -> list[str]:
    """Returns:
        The values the env files names below path give the key, unquoted,
        in file order; an unreadable file gives none.
    """
    found: list[str] = []
    for name in names:
        try:
            found += [value.strip().strip("\"'") for value in key.findall(Path(path, name).read_text(encoding="utf-8"))]
        except (OSError, UnicodeDecodeError):
            continue
    return found


def claims(entry: dict) -> list[str]:
    """Returns:
        The claims stored at enqueue (claims_of(); the workdir alone for an
        entry an older queue stored without them).
    """
    return entry[CLAIMS] if CLAIMS in entry else [entry["workdir"]]


def identity(pid: int) -> str | None:
    """Name a live process by its start time, so a reused pid does not match.

    Args:
      pid: the process id.

    Returns:
      The start time from /proc, `running` where /proc is unreadable, None for
      a gone or zombie process.
    """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return None
    except PermissionError:
        pass
    try:
        fields = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").rsplit(")", 1)[1].split()
    except OSError:
        return "running"
    return None if fields[0] == "Z" else fields[19]


def alive(pid: int | None, start: str | None) -> bool:
    return pid is not None and start is not None and identity(pid) == start


def held(tag: object) -> bool:
    if not isinstance(tag, str) or not TAG.fullmatch(tag):
        return False
    path = HOLDS / f"{tag}.lock"
    try:
        fd = nofollow.open_below(watch.ROOT, path, os.O_RDONLY, 0)
    except FileNotFoundError:
        return False
    with open(fd, encoding="utf-8") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
    with contextlib.suppress(FileNotFoundError):
        nofollow.unlink(watch.ROOT, path)
    return False


@contextlib.contextmanager
def holding() -> Iterator[tuple[str, int]]:
    tag = f"{os.getpid()}-{time.time_ns()}"
    path = HOLDS / f"{tag}.lock"
    with nofollow.locked(watch.ROOT, path, 0o600, None) as handle:
        try:
            yield tag, handle.fileno()
        finally:
            with contextlib.suppress(OSError):
                nofollow.unlink(watch.ROOT, path)


def living(entry: dict) -> bool:
    if "lock" in entry:
        return held(entry["lock"])
    return alive(entry["pid"], entry["pid_start"]) or (
        entry["status"] == "active" and alive(entry["child"], entry["child_start"])
    )


def prune(entries: list[dict]) -> list[dict]:
    return [e for e in entries if living(e)]


def read_store() -> dict:
    try:
        return json.loads(STORE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"seq": 0, "entries": []}
    except ValueError:
        fail(f"{STORE} is not valid JSON; move it aside to start over")


@contextlib.contextmanager
def store() -> Iterator[dict]:
    watch.ROOT.mkdir(parents=True, exist_ok=True)
    with nofollow.locked(watch.ROOT, LOCK, 0o600, None):
        data = read_store()
        yield data
        nofollow.replace(watch.ROOT, STORE, json.dumps(data, indent=1, sort_keys=True), 0o600)


def priority(entry: dict, ranks: dict[str, int], agents: dict[str, int], now: float) -> tuple[tuple, list[str]]:
    """Returns:
        The sort key of entry in ordered() (hotfix first, register rank less
        the whole hours waited, agent order, arrival) and the trace steps
        that name it.
    """
    hours = int((now - entry["enqueued"]) // HOUR)
    rank = ranks[entry["task"]] if entry["task"] in ranks else len(ranks)
    agent = agents[entry["name"]] if entry["name"] in agents else len(agents)
    steps = [
        *(["hotfix first"] if entry["hotfix"] else []),
        (f"rank {rank}" if entry["task"] in ranks else "unranked") + (f", {hours} h waited: {rank - hours}" if hours else ""),
        *([f"agent order {agent}"] if entry["name"] in agents else []),
        f"arrival {entry['seq']}",
    ]
    return (not entry["hotfix"], rank - hours, agent, entry["seq"]), steps


def ordered(waiting: list[dict], ranks: dict[str, int], agents: dict[str, int], now: float) -> list[dict]:
    return sorted(waiting, key=lambda entry: priority(entry, ranks, agents, now)[0])


def in_lines(order: list[dict]) -> list[dict]:
    """Returns:
        order with every entry moved behind each entry of order enqueued
        before it that shares one of its claims (claims()), so a line runs
        by enqueue time alone, whatever the rank; a hotfix moves behind
        older hotfixes only.
    """
    held = {e["id"]: set(claims(e)) for e in order}
    placed: dict[str, dict] = {}

    def place(entry: dict) -> None:
        if entry["id"] in placed:
            return
        for older in order:
            earlier = (older["enqueued"], older["seq"]) < (entry["enqueued"], entry["seq"])
            if earlier and held[older["id"]] & held[entry["id"]] and (older["hotfix"] or not entry["hotfix"]):
                place(older)
        placed[entry["id"]] = entry

    for entry in order:
        place(entry)
    return list(placed.values())


def over_budget(used: dict[str, float], share: dict[str, float], budget: dict[str, float]) -> str | None:
    over = [resource for resource in budget if used[resource] + share[resource] > budget[resource]]
    if not over:
        return None
    return ", ".join(
        f"{resource.upper()} {used[resource]:.0f} % in use or reserved + {share[resource]:.0f} % > budget {budget[resource]:g} %"
        for resource in over
    )


def evaluate(entries: list[dict], free_gb: float, floor: float, stage: str, memory: str, silenced: bool,
             slot_limits: dict[str, int], footprints: dict[str, dict[str, float]], budget: dict[str, float],
             ranks: dict[str, int], agents: dict[str, int], loaded: dict[str, str],
             exclusive: set[str], light: set[str], drain: str | None,
             now: float, *, trace: dict[str, list[str]] | None = None) -> tuple[dict[str, str | None], str | None, list[dict]]:
    """Decide every waiting entry in grant order, without disk or processes.

    Args:
      entries: the queue's entries, active and waiting.
      free_gb: free disk in GB.
      floor: GB every grant must leave free (thresholds_gb.stop).
      stage: the watch disk stage: ok, warn, stop or critical.
      memory: the watch memory stage: ok, warn or stop.
      silenced: whether a radio-silence mayday holds.
      slot_limits: {kind: max concurrent jobs}, an upper cap beside the budget.
      footprints: {entry id: {ram, cpu}}, the learned share of every entry
        (footprint(), an active one's as granted), in percentage points.
      budget: {ram, cpu}: the sum of the footprints of active and granted
        entries may not pass it; a job alone always fits.
      ranks: {task: index in the register's ranking}; a task missing there
        ranks after all of them.
      agents: {agent name: index in the operator's agent order}; it breaks
        ties of equal rank only, an entry whose holder is missing there after
        all of them.
      loaded: {entry id: why live CPU or RAM holds it back (load_reason())}
        for the waiting entries the host load keeps out.
      exclusive: kinds that run only beside light kinds (exclusive_kinds,
        alone_reason()); they wait in grant order, in no line of their own.
      light: kinds allowed beside an exclusive one (light_kinds).
      drain: the entry the previous pass drained for (DRAIN), else None.
      now: epoch seconds; each whole hour waited moves an entry one rank up.
      trace: when given, filled with {waiting entry id: the steps that
        decided it, in order}: its priority() steps, `drain head`,
        `passes <id>: it waits for the machine` (or `<id> can never start,
        <why>`) per entry it passes, then the
        rule that blocked it, or `takes nothing <head> lacks`, the fit and
        `backfilled past <id>` for a granted one.

    Returns:
      ({entry id: None when granted, else the blocking reason, a Disk when
      the disk stage or the floor alone blocks it} in grant order, the entry
      the next pass drains for (drained()), the polling waiting entries in
      grant order). A granted entry counts against the disk, budget and
      slots of the entries after it, whoever holds it. A blocked entry
      reserves nothing, so a later entry that fits starts past it
      (backfill), except the head: drain, or before it a blocked hotfix
      that is the first blocked entry not unstartable() or an exclusive entry that only
      running jobs of other kinds keep out (alone_reason()). Behind the
      head every later entry, light ones too, starts only when it takes
      nothing the head still lacks, the last slot of its kind included
      (takes(); beside a head that is
      exclusive or waits for an exclusive job only light jobs count); every
      later one but light ones waits behind a
      hotfix head, and behind any head whose kind is exclusive or that live
      load holds while queue jobs run; light ones wait too while load the
      queue causes holds a hotfix head. Behind an exclusive entry that only
      load the queue causes holds, head or not, no later entry but a light
      one starts (loaded_exclusive()): it would keep that entry out once the
      load drops. An entry never passes an active,
      granted or waiting entry enqueued before it that shares one of its
      claims (claims(): worktree, compose stack, slot): those form its
      line, which runs by enqueue time alone (in_lines()), never by rank,
      except that a hotfix waits behind no older entry but a hotfix or an
      active one, and a light entry passes a waiting one that is no hotfix
      and waits only for the machine (its slot, alone_reason() or a hold
      behind an entry of other claims), which then waits for that light run;
      a head keeps its slot, so that delays it by one light run at most. A
      granted entry holds its claims for the rest of the pass. A waiting
      entry of the session Main that could start, whose line only runs,
      waits for the machine or is the head, reserves like a head against the
      later entries of other claims: its slot, its exclusive room and its
      budget (held_for()).
      An entry that could not start with no queue job running (its disk
      need cuts into floor, its kind has no slot, or load holds it that no
      queue job causes: an Outside reason, or no queue job active) is no
      head; one with an Outside reason holds no line either. A waiting
      entry whose holder has not polled for CLAIM_SECONDS reserves nothing
      and comes last. An entry passes a waiting entry of its line that never
      could start (unstartable()) and takes its place in that line.
    """
    active = [e for e in entries if e["status"] == "active"]
    used = {resource: sum(footprints[e["id"]][resource] for e in active) for resource in budget}
    available = free_gb - sum(e["need_gb"] for e in active)
    lit = [e for e in active if e["kind"] in light]
    beside = {resource: sum(footprints[e["id"]][resource] for e in lit) for resource in budget}
    room = free_gb - sum(e["need_gb"] for e in lit)
    counts = Counter(e["kind"] for e in active)
    lines = {claim: e["id"] for e in active for claim in claims(e)}
    polling = [e for e in entries if e["status"] == "waiting" and not silent(e, now)]
    order = in_lines(ordered(polling, ranks, agents, now))
    never = {e["id"]: unstartable(e, free_gb, floor, slot_limits) for e in order}
    could = {
        e["id"] for e in order if not never[e["id"]]
        and not (e["id"] in loaded and (not active or isinstance(loaded[e["id"]], Outside)))
    }
    drain = drain if drain in could else None
    steps = {} if trace is None else trace
    verdicts: dict[str, str | None] = {}
    blocked: list[dict] = []
    able: list[dict] = []
    reserve: tuple[dict[str, float], float, bool, str, str, str] | None = None
    machine: set[str] = set()
    holds: list[tuple[dict[str, float], float, str, str, set[str]]] = []
    running = {e["id"] for e in active}
    for entry in order:
        kind, need, share, mine = entry["kind"], entry["need_gb"], footprints[entry["id"]], claims(entry)
        taken = sum(counts.values())
        lifted = [c for c in mine if never.get(lines.get(c))]
        passed = list(dict.fromkeys(lines[c] for c in mine if c in lifted or kind in light and lines.get(c) in machine))
        kept = [c for c in mine if lines.get(c) not in passed]
        owners = {lines[c] for c in kept if c in lines}
        lined = bool(owners)
        lead = behind(entry, kept, lines, able, reserve[4] if reserve else drain, exclusive, light, loaded)
        alone, slot = alone_reason(kind, counts, exclusive, light), slot_reason(kind, slot_limits, counts)
        reason = blocking(
            lead and lead[0], disk_reason(stage, need),
            host_reason(memory, silenced) or slot or alone or (over_budget(used, share, budget) if taken else None),
            None if available - need >= floor else floor_reason(need, floor), loaded.get(entry["id"]),
        )
        step = lead[1] if lead else reason
        if reason is None and reserve is not None:
            slotted = reserve[5] if kind == reserve[5] and counts[kind] + 1 >= slot_limits.get(kind, 0) else None
            short = takes(need, share, *((beside, room) if reserve[2] else (used, available)), floor, budget, reserve[:2], slotted)
            reason = reserve[3] if short else None
            step = f"{reserve[3]}: takes {short}" if short else f"takes nothing {reserve[4]} lacks"
        pools = used, available, beside, room
        why = None if reason is not None else next(((h[2], s) for h in holds if not h[4] & set(mine) and (
            s := held_for(kind, need, share, h, counts, slot_limits, exclusive, light, pools, floor, budget))), None)
        if why:
            reason, step = f"reserved for {why[0]}", f"reserved for {why[0]}: {why[1]}"
        gate = None if reason is not None or kind in light else loaded_exclusive(able, verdicts, loaded, exclusive)
        if gate:
            reason, step = f"waits behind exclusive {gate}", f"exclusive {gate} blocked ahead: load holds it, {kind} beside it would keep it out"
        for claim in () if isinstance(loaded.get(entry["id"]), Outside) else mine:
            if reason is None or claim in lifted:
                lines[claim] = entry["id"]
            else:
                lines.setdefault(claim, entry["id"])
        mark = [
            *priority(entry, ranks, agents, now)[1], *(["drain head"] if entry["id"] == drain else []),
            *(f"passes {o}: {o} can never start, {never[o]}" if never.get(o) else f"passes {o}: it waits for the machine" for o in passed),
        ]
        if reason is None:
            steps[entry["id"]] = [*mark, *fitted(step, used, share, need, available, blocked)]
            used, available = plus(used, share), available - need
            if kind in light:
                beside, room = plus(beside, share), room - need
            counts[kind] += 1
        else:
            steps[entry["id"]] = [*mark, str(step)]
            blocked.append(entry)
            able += [] if never[entry["id"]] else [entry]
            first = entry["hotfix"] and able == [entry] or kind in exclusive and reason == alone
            if reserve is None and (entry["id"] == drain or entry["id"] in could and first):
                held = f"waits behind hotfix {entry['id']}" if entry["hotfix"] else f"drained for {entry['id']}"
                reserve = share, need, kind in exclusive or reason == alone, held, entry["id"], kind
            if not entry["hotfix"] and not lined and (lead or reason in (alone, slot)):
                machine.add(entry["id"])
            settled = running | machine | {i for i, v in verdicts.items() if v is None} | {reserve[4] if reserve else None}
            if lined and entry["name"] == "Main" and entry["id"] in could and entry["id"] != (reserve and reserve[4]) and owners <= settled:
                holds.append((share, need, entry["id"], kind, set(mine)))
        verdicts[entry["id"]] = reason
    for entry in entries:
        if entry["status"] == "waiting" and silent(entry, now):
            verdicts[entry["id"]] = f"no poll for {now - entry['polled']:.0f} s; reserves nothing until it polls again"
            steps[entry["id"]] = [verdicts[entry["id"]]]
    return verdicts, drained(order, verdicts, drain, could, now), order


def fitted(step: str | None, used: dict[str, float], share: dict[str, float], need: float, available: float,
           blocked: list[dict]) -> list[str]:
    """Returns:
        The trace steps of a granted entry: step when a head reserves, its
        fit beside used and available, and the blocked entry it passes.
    """
    fit = ", ".join(f"{r.upper()} {used[r]:.0f} % + {share[r]:.0f} %" for r in used) + f", {need:g} GB of {available:.0f} GB fits"
    return [*([step] if step else []), fit, *([f"backfilled past {blocked[0]['id']}"] if blocked else [])]


def blocking(lead: str | None, staged: str | None, rest: str | None, floored: str | None,
             late: str | None) -> str | None:
    """Returns:
        The first reason of lead, staged, rest, floored and late, a Disk
        when only staged or floored, the disk checks, hold the entry back.
    """
    reason = lead or staged or rest or floored or late
    return Disk(reason) if reason is not None and lead is None and rest is None and late is None else reason


def behind(entry: dict, mine: list[str], lines: dict[str, str], blocked: list[dict], drain: str | None,
           exclusive: set[str], light: set[str], loaded: dict[str, str]) -> tuple[str, str] | None:
    """Returns:
        (why an entry before it holds entry back, its trace step), else None:
        the first of blocked (the blocked entries not unstartable()) is a
        hotfix and entry is not light, or load
        the queue causes holds that hotfix (loaded, no Outside reason); an
        entry enqueued before it shares one of its claims mine (lines maps a
        claim to the first entry holding it); or drain, the entry that
        reserves (evaluate()), is blocked before it, entry is not light, and
        live load holds drain or its kind is exclusive.
    """
    first = blocked[0] if blocked else None
    if first and first["hotfix"]:
        pressed = first["id"] in loaded and not isinstance(loaded[first["id"]], Outside)
        if entry["kind"] not in light or pressed:
            return f"waits behind hotfix {first['id']}", f"hotfix {first['id']} blocked ahead" + (": load holds it" if pressed else "")
    ahead = [(claim, lines[claim]) for claim in mine if claim in lines]
    if ahead:
        return f"waits in line behind {ahead[0][1]}", f"line {ahead[0][0]} behind {ahead[0][1]}"
    for e in blocked:
        if entry["kind"] not in light and e["id"] == drain and (drain in loaded or e["kind"] in exclusive):
            return f"drained for {drain}", f"drained for {drain}: " + ("load holds it" if drain in loaded else f"{e['kind']} is exclusive")
    return None


def loaded_exclusive(able: list[dict], verdicts: dict[str, str | None], loaded: dict[str, str],
                     exclusive: set[str]) -> str | None:
    """Returns:
        The id of the first entry of able (blocked, not unstartable()) whose
        kind is exclusive and that only live load holds back (its verdict is
        its loaded reason), the queue's own jobs causing that load; a job of
        a kind that is not light, started now, would keep it out once they
        end (alone_reason()). None when there is none. An Outside reason
        never counts: the entry stays out with the queue empty, so holding
        others back would only starve them while that load lasts, and once
        it drops, the jobs then running turn the reason into the queue's.
    """
    return next((e["id"] for e in able if e["kind"] in exclusive and e["id"] in loaded and not isinstance(loaded[e["id"]], Outside)
                 and verdicts[e["id"]] == loaded[e["id"]]), None)


def drained(order: list[dict], verdicts: dict[str, str | None], drain: str | None, could: set[str],
            now: float) -> str | None:
    """Returns:
        The entry the next pass drains for, among could, the entries of order
        that could start with no queue job running: drain while it still
        waits, else the first blocked one that waited DRAIN_AFTER_SECONDS,
        else the first of order once none of order fits; None when there is
        none.
    """
    blocked = [e["id"] for e in order if verdicts[e["id"]] is not None]
    aged = [e["id"] for e in order if e["id"] in blocked and now - e["enqueued"] >= DRAIN_AFTER_SECONDS]
    stuck = [order[0]["id"]] if order and len(blocked) == len(order) else []
    return next((e for e in [drain, *aged, *stuck] if e in could), None)


def silent(entry: dict, now: float) -> bool:
    return entry["status"] == "waiting" and now - entry.get("polled", now) > CLAIM_SECONDS


def rejoin(data: dict, entry: dict, now: float) -> None:
    if silent(entry, now):
        data["seq"] += 1
        entry.update(seq=data["seq"], enqueued=now)
    entry["polled"] = now


def plus(used: dict[str, float], share: dict[str, float]) -> dict[str, float]:
    return {resource: used[resource] + share[resource] for resource in used}


def takes(need: float, share: dict[str, float], used: dict[str, float], available: float, floor: float,
          budget: dict[str, float], reserve: tuple[dict[str, float], float], slotted: str | None) -> str | None:
    """Returns:
        What a job of disk need and footprint share, beside jobs that use
        used and leave available GB, takes that the head's reserve
        (footprint, disk need) leaves too short: `its <kind> slot` when
        slotted names the head's kind whose last free slot it takes, the
        budget resources it pushes past, or disk; None when it takes none of
        a short resource.
    """
    held, held_need = reserve
    over = plus(plus(used, held), share)
    short = [r.upper() for r in budget if share[r] > 0 and over[r] > budget[r]]
    if slotted:
        return f"its {slotted} slot"
    if short:
        return " and ".join(short)
    return "disk" if need > 0 and available - held_need - need < floor else None


def held_for(kind: str, need: float, share: dict[str, float], hold: tuple[dict[str, float], float, str, str, set[str]],
             counts: Counter, slot_limits: dict[str, int], exclusive: set[str], light: set[str],
             pools: tuple[dict[str, float], float, dict[str, float], float], floor: float, budget: dict[str, float]) -> str | None:
    """Returns:
        Why a job of kind, disk need and footprint share takes what hold
        (footprint, disk need, id, kind, claims), a job whose line only runs
        or waits for the machine, lacks: `<kind> is exclusive` when one of
        the two is exclusive and the other not light, else `takes` what
        takes() finds beside pools (used, available, then the light jobs'
        beside and room, which count when hold's kind is exclusive), its last
        free slot of hold's kind included; None when it takes nothing.
    """
    held = hold[3]
    if held in exclusive and kind not in light or kind in exclusive and held not in light:
        return f"{held if held in exclusive else kind} is exclusive"
    used, available, beside, room = pools
    slotted = held if kind == held and counts[kind] + 1 >= slot_limits.get(kind, 0) else None
    short = takes(need, share, *((beside, room) if held in exclusive else (used, available)), floor, budget, hold[:2], slotted)
    return f"takes {short}" if short else None


def unstartable(entry: dict, free_gb: float, floor: float, slot_limits: dict[str, int]) -> str | None:
    """Returns:
        Why entry could not start even with no queue job running: `<cap>
        <kind> slots` when its kind's cap is 0 or missing, floor_reason()
        when its disk need cuts into floor of free_gb; else None.
    """
    cap = slot_limits.get(entry["kind"], 0)
    if cap <= 0:
        return f"{cap} {entry['kind']} slots"
    return floor_reason(entry["need_gb"], floor) if free_gb - entry["need_gb"] < floor else None


def floor_reason(need: float, floor: float) -> str:
    return f"{need:g} GB would cut into the {floor:g} GB floor"


def disk_reason(stage: str, need: float) -> str | None:
    if stage in ("stop", "critical"):
        return f"disk stage {stage}"
    if stage == "warn" and need > 0:
        return "disk stage warn admits only jobs that need no disk"
    return None


def host_reason(memory: str, silenced: bool) -> str | None:
    if memory == "stop":
        return "memory stage stop"
    if silenced:
        return "radio silence"
    return None


def slot_reason(kind: str, slot_limits: dict[str, int], counts: Counter) -> str | None:
    if kind not in slot_limits:
        return f"slot_limits has no {kind}"
    if counts[kind] >= slot_limits[kind]:
        return f"all {slot_limits[kind]} {kind} slots taken"
    return None


def alone_reason(kind: str, counts: Counter, exclusive: set[str], light: set[str]) -> str | None:
    if kind in light:
        return None
    running = sorted(k for k, n in counts.items() if n and k not in light)
    if kind in exclusive and running:
        return f"{kind} runs only beside {', '.join(sorted(light)) or 'nothing'}, but {', '.join(running)} runs"
    blocking = [k for k in running if k in exclusive]
    if blocking:
        return f"{', '.join(blocking)} runs only beside {', '.join(sorted(light)) or 'nothing'}"
    return None


def register_ranks() -> dict[str, int]:
    rasci = sibling("rasci")
    return {task: index for index, task in enumerate(rasci.ranked(rasci.merged(False)))}


def agent_ranks() -> dict[str, int]:
    return {name: index for index, name in enumerate(sibling("rasci").agent_order())}


def after_waits(entries: list[dict]) -> dict[str, str]:
    rasci = sibling("rasci")
    register = rasci.load()
    waits = {}
    for entry in entries:
        task = entry["task"]
        ahead = [
            other for other in register.get(task, {}).get("after", [])
            if other in register and register[other].get("status") not in rasci.ENDED
        ]
        if entry["status"] == "waiting" and ahead:
            lift = shlex.join(["rasci.py", "set", task, "--drop-after", ahead[0]])
            waits[entry["id"]] = f"waits for {ahead[0]}, an after task of {task} not yet done or stopped; {lift} lifts it"
    return waits


def stage(cfg: dict, free_gb: float, now: float) -> str:
    state = watch.read_json(watch.STATE)
    return state["stage"] if "stage" in state else watch.stage_for(free_gb, [], cfg, now)


def silenced(now: float) -> bool:
    state = watch.read_json(SILENCE)
    return "until" in state and state["until"] > now


def footprint(entry: dict, signatures: dict[tuple[str, str], dict], kinds: dict[str, dict]) -> dict[str, float] | None:
    """Returns:
        The footprint an active entry was granted on (its footprint field,
        so what history learns later never moves a running job's
        reservation); history.ceiling of an active entry an older queue
        granted without one, so it never books less than that queue did;
        else history.footprint of its aliases.
    """
    if entry["status"] == "active":
        if FROZEN in entry:
            return entry[FROZEN]
        return history.ceiling(entry["kind"], aliases_of(entry), signatures, kinds)
    return history.footprint(entry["kind"], aliases_of(entry), signatures, kinds)


def held_back(cfg: dict, entries: list[dict], now: float, signatures: dict[str, dict], kinds: dict[str, dict],
              cpu: float, mem: float, admitted: float) -> dict[str, str]:
    """Returns:
        {waiting entry id: load_reason()} for the waiting entries the host
        load keeps out, an Outside reason when the load would keep the entry
        out alone with every queue job gone: CPU less the active jobs' CPU
        shares, RAM less the ramped ones' RAM shares.
    """
    active = [e for e in entries if e["status"] == "active"]
    ramped = sum(ram_share(e, signatures, kinds) for e in active if now - e.get("granted", now) >= RAMP_SECONDS)
    busy = sum((footprint(e, signatures, kinds) or {"cpu": 0})["cpu"] for e in active)
    loaded = {}
    for entry in entries:
        if entry["status"] == "waiting":
            pending = pending_ram(entries, entry["id"], now, signatures, kinds, mem, admitted)
            if (reason := load_reason(cfg["load_limits"], cpu, mem, pending)) is not None:
                alone = load_reason(cfg["load_limits"], cpu - busy, mem - ramped, ram_share(entry, signatures, kinds))
                loaded[entry["id"]] = reason if alone is None else Outside(reason)
    return loaded


def decide(cfg: dict, entries: list[dict], free_gb: float, now: float, signatures: dict[str, dict],
           kinds: dict[str, dict], loaded: dict[str, str], drain: str | None, *,
           trace: dict[str, list[str]] | None = None) -> tuple[dict[str, str | None], str | None, list[dict]]:
    slots = {kind: limit for kind, (limit, _) in limits(cfg, kinds, entries).items()}
    budget = cfg["budget_percent"]
    footprints = {}
    for entry in entries:
        share = footprint(entry, signatures, kinds)
        footprints[entry["id"]] = dict(budget) if share is None else share
    waits = after_waits(entries)
    steps = {} if trace is None else trace
    verdicts, drain, order = evaluate(
        [e for e in entries if e["id"] not in waits], free_gb, cfg["thresholds_gb"]["stop"], stage(cfg, free_gb, now),
        watch.memory_stage(watch.memory(), cfg), silenced(now), slots, footprints, budget,
        register_ranks(), agent_ranks(), loaded,
        set(cfg.get("exclusive_kinds", [])), set(cfg.get("light_kinds", [])), drain, now, trace=steps,
    )
    steps.update({entry_id: [reason] for entry_id, reason in waits.items()})
    return verdicts | waits, drain, order


def latched(data: dict, drain: str | None, now: float) -> str | None:
    """Returns:
        drain when the store data drains for it already, or once a new drain
        was proposed at every poll for DEBOUNCE_SECONDS (BLOCKED keeps since
        when), else None; a pass proposing none clears BLOCKED.
    """
    if drain is None or drain == data.get(DRAIN):
        data.pop(BLOCKED, None)
        return drain
    data.setdefault(BLOCKED, now)
    return drain if now - data[BLOCKED] >= DEBOUNCE_SECONDS else None


def labelled(verdicts: dict[str, str | None], fired: list[str]) -> dict[str, str | None]:
    """Returns:
        verdicts with `backfilled` for a granted entry after a blocked one,
        and `escalated <step>: ` before the first entry's reason for the last
        step fired in the stall.
    """
    shown: dict[str, str | None] = {}
    for entry_id, reason in verdicts.items():
        if reason is None:
            shown[entry_id] = "backfilled" if any(shown.values()) else None
        else:
            shown[entry_id] = f"escalated {fired[-1]}: {reason}" if fired and not shown else reason
    return shown


def escalate(stall: dict, grant: float | None, since: float, hotfix: bool,
             now: float) -> tuple[dict, str | None]:
    """Args:
        stall: the stored STALL, {} for none; one stored for another grant,
            or last advanced more than IDLE_SECONDS before since, counts as
            none, so a grant or an idle queue resets it, and nothing else: a
            restart, rejoin, cancel or new hold keeps its clock.
        grant: epoch seconds of the last grant on the host, None for none.
        since: epoch seconds the oldest polling waiting entry was enqueued;
            a new stall's clock starts at the later of grant and since.
        hotfix: whether a hotfix job runs ahead of the head; the clock
            stands still while one does.
        now: epoch seconds.

    Returns:
        (the stall to store, the ESCALATION step to fire now or None). Each
        step fires once per stall; steps the clock passed unseen are marked
        fired with the last of them, which alone fires.
    """
    fresh = {"grant": grant, "since": since if grant is None else max(grant, since), "seen": now, "fired": []}
    if stall.get("grant") != grant or not fresh.keys() <= stall.keys() or since - stall["seen"] > IDLE_SECONDS:
        stall = fresh
    start = now if hotfix else stall["since"]
    due = [step for minutes, step, _ in ESCALATION if now - start >= minutes * 60 and step not in stall["fired"]]
    return {**stall, "since": start, "seen": now, "fired": [*stall["fired"], *due]}, due[-1] if due else None


def cleanup_due(state: dict, head: str, disk: bool, now: float) -> tuple[dict, bool]:
    """Returns:
        (the CLEANUP to store: the stored one while head stays the head,
        whatever grants pass beside it, else a new one for head; whether to
        start the low-risk cleanup now, once per head, when disk alone
        blocks it).
    """
    if state.get("head") != head:
        state = {"head": head, "cleaned": False, "cleaned_at": None, "settled": False, "noticed": False}
    if disk and not state["cleaned"]:
        return {**state, "cleaned": True, "cleaned_at": now}, True
    return state, False


def settle(stall: dict, outcome: Callable[[], tuple[bool, list[tuple[float, str]]]],
           short: bool) -> tuple[dict, str | None, bool]:
    """Args:
        stall: the CLEANUP cleanup_due() returned.
        outcome: () -> (whether a cleanup holds the watch.py cleanup lock,
            the cleanup alerts as (epoch seconds, text)); called only while
            the head's cleanup has started and not yet settled.
        short: whether disk alone still blocks the head.

    Returns:
        (the CLEANUP to store, the line to log once the cleanup has ended
        (its newest report since it started, or that it left none), whether
        to send the notice now); both come once per head.
    """
    log = None
    if stall["cleaned"] and not stall["settled"]:
        cleaning, reports = outcome()
        if cleaning:
            return stall, None, False
        texts = [text for at, text in reports if at >= stall["cleaned_at"]]
        log = f"low-risk cleanup: {texts[-1]}" if texts else "low-risk cleanup ended without a report"
        stall = {**stall, "settled": True}
    notice = stall["settled"] and short and not stall["noticed"]
    return {**stall, "noticed": stall["noticed"] or notice}, log, notice


def cleanup_outcome(now: float) -> tuple[bool, list[tuple[float, str]]]:
    """Returns:
        (whether a watch.py cleanup holds its lock, younger than LOCK_TTL,
        at now; the cleanup alerts of watch.py as (epoch seconds, text),
        none while it does or when the file is unreadable).
    """
    try:
        held = os.lstat(watch.ROOT / watch.CLEANUP_LOCK)
    except OSError:
        held = None
    if held is not None and stat.S_ISDIR(held.st_mode) and now - held.st_mtime <= watch.LOCK_TTL:
        return True, []
    try:
        rows = [json.loads(line) for _, line in watch.history_rows(nofollow.read_text(watch.ROOT, watch.ALERTS))]
    except OSError:
        return False, []
    return False, [
        (row["id"] / 1e9, row["text"]) for row in rows
        if row.get("stage") == "cleanup" and isinstance(row["id"], int) and isinstance(row.get("text"), str)
    ]


def stalled(data: dict, order: list[dict], verdicts: dict[str, str | None], floor: float, free_gb: float,
            outcome: Callable[[], tuple[bool, list[tuple[float, str]]]],
            now: float) -> tuple[list[tuple[str, list[str]]], bool, str | None]:
    """Returns:
        ([(label, radio.py argv)] to send: the ESCALATION step due, then
        the notice that the head cannot fit after the cleanup; whether to
        start the cleanup; the line to log about the cleanup, else None).
    """
    fits = None in verdicts.values()
    head = next((e for e in order if isinstance(verdicts[e["id"]], Disk)), None) if fits else next(iter(order), None)
    if head is None:
        return [], False, None
    reason = verdicts[head["id"]]
    active = [e for e in data["entries"] if e["status"] == "active"]
    grants = [*([data[GRANTED]] if GRANTED in data else []), *(e["granted"] for e in active)]
    disk = isinstance(reason, Disk)
    sends = []
    if not fits:
        data[STALL], step = escalate(
            data.get(STALL) or {}, max(grants) if grants else None, min(e["enqueued"] for e in order),
            any(e["hotfix"] for e in active), now,
        )
        sends = [] if step is None else [(f"escalated {step}", radio_words(step, (
            f"{PREFIX}no grant for {STEPS[step][0]} min; head {head['id']} ({head['kind']}, {head['task']}) waits: {reason}"
        )))]
    state, clean = cleanup_due(data.get(CLEANUP) or {}, head["id"], disk, now)
    log = None
    if not clean:
        state, log, notice = settle(state, outcome, disk)
        reach = max(free_gb - floor, 0) if reason == floor_reason(head["need_gb"], floor) else 0
        if notice:
            sends.append(("noticed that the head cannot fit", radio_words("post", (
                f"{PREFIX}head {head['id']} needs {head['need_gb']:g} GB, max reachable {reach:.0f} GB "
                f"after cleanup ({reason}); operator cleanup needed"
            ))))
    data[CLEANUP] = state
    return sends, clean, log


def radio_words(step: str, text: str) -> list[str]:
    return [text if word == TEXT else word for word in STEPS[step][1]]


def cleaned(state: dict) -> tuple[dict, str]:
    """Returns:
        (the CLEANUP state, settled when the cleanup did not start, so no
        report is awaited; the line to log).
    """
    try:
        watch.spawn_cleanup("--full")
    except OSError as error:
        return {**state, "settled": True}, f"low-risk cleanup did not start: {error}"
    return state, "disk alone blocks the head; low-risk cleanup started"


def act(sends: list[tuple[str, list[str]]], logs: list[str], session: str) -> None:
    """Args:
        sends: [(label, radio.py argv)] to send over kvb-org-radio, each
            reported once by its label.
        logs: lines to log.
        session: the session that sends the radio rows.
    """
    for log in logs:
        print(f"queue: {log}", file=sys.stderr, flush=True)
    for label, words in sends:
        try:
            sent = subprocess.run(
                [EXE, str(RADIO), *words, "--session", session], stdin=subprocess.DEVNULL, capture_output=True,
                timeout=RADIO_SECONDS, check=False,
            ).returncode
        except (OSError, subprocess.TimeoutExpired) as error:
            sent = error
        print(f"queue: {label}" if sent == 0 else f"queue: {label} failed: {sent}", file=sys.stderr, flush=True)


def load_reason(limits: dict, cpu: float, mem: float, ram_share: float) -> str | None:
    """Args:
        limits: load_limits of the config.
        cpu: CPU busy now, in percent.
        mem: RAM used now, in percent; stacks and jobs outside the queue
            included.
        ram_share: what the job and the active ones may still take, in
            percentage points (pending_ram()).

    Returns:
        None when CPU stays below cpu_percent and RAM used plus the share
        below mem_percent, else why not.
    """
    if cpu >= limits["cpu_percent"]:
        return f"CPU {cpu:.0f} % busy reaches the limit {limits['cpu_percent']} %"
    if mem + ram_share >= limits["mem_percent"]:
        return f"RAM {mem:.0f} % used + {ram_share:.0f} % still to come reach the limit {limits['mem_percent']} %"
    return None


def ram_share(entry: dict, signatures: dict[str, dict], kinds: dict[str, dict]) -> float:
    share = footprint(entry, signatures, kinds)
    return history.seed_ram(kinds) if share is None else share["ram"]


def ramping_ram(entries: list[dict], now: float, signatures: dict[str, dict], kinds: dict[str, dict],
                mem: float) -> float:
    """Returns:
        What the active jobs granted less than RAMP_SECONDS ago (or without a
        grant time) may still add: the shares of those whose grant recorded
        the RAM used (GRANTED_MEM) minus what RAM used gained since the
        earliest of these grants, between 0 and those shares (a RAM used
        that fell since counts as no gain), plus the whole share of the
        others. An older job counts as ramped, its RAM inside the RAM used;
        one that peaks later is bounded by the memory stage only.
    """
    young = [e for e in entries if e["status"] == "active" and now - e.get("granted", now) < RAMP_SECONDS]
    dated = [e for e in young if GRANTED_MEM in e]
    gained = max(0.0, mem - min((e[GRANTED_MEM] for e in dated), default=mem))
    ramp = max(0.0, sum(ram_share(e, signatures, kinds) for e in dated) - gained)
    return ramp + sum(ram_share(e, signatures, kinds) for e in young if GRANTED_MEM not in e)


def pending_ram(entries: list[dict], entry_id: str, now: float, signatures: dict[str, dict],
                kinds: dict[str, dict], mem: float, admitted: float) -> float:
    """Returns:
        The RAM share of entry_id plus admitted (admitted_ram()) plus
        ramping_ram() at RAM used mem.
    """
    mine = [e for e in entries if e["id"] == entry_id]
    return ram_share(mine[0], signatures, kinds) + admitted + ramping_ram(entries, now, signatures, kinds, mem)


def admitted_ram(data: dict, now: float) -> float:
    return sum(record["ram"] for record in data.get(ADMITS, []) if record["expires"] > now)


def workdir() -> str:
    try:
        top = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=False
        )
    except OSError:
        return os.path.realpath(os.getcwd())
    path = top.stdout.strip() if top.returncode == 0 else ""
    return os.path.realpath(path or os.getcwd())


def enqueue(fields: dict) -> dict:
    """Returns:
        The entry of fields; a hold that hand_over() left for the installed
        code at most CLAIM_SECONDS before, of the same pid, session and
        command, keeps its id, seq and enqueue time.
    """
    with store() as data:
        kept = {pid: h for pid, h in data.get(HANDOVER, {}).items() if fields["enqueued"] - h["at"] <= CLAIM_SECONDS}
        mine = kept.pop(str(fields["pid"]), None)
        if mine is not None and (mine["session"], mine["cmd"]) == (fields["session"], fields["cmd"]):
            entry = {**fields, "id": mine["id"], "seq": mine["seq"], "enqueued": mine["enqueued"]}
        else:
            data["seq"] += 1
            entry = {"id": f"{fields['kind']}-{data['seq']}", "seq": data["seq"], **fields}
        data[HANDOVER] = kept
        data["entries"].append(entry)
    return entry


def hand_over(entry_id: str) -> None:
    with store() as data:
        for entry in [e for e in data["entries"] if e["id"] == entry_id]:
            data["entries"].remove(entry)
            data.setdefault(HANDOVER, {})[str(entry["pid"])] = {
                **{key: entry[key] for key in ("id", "seq", "enqueued", "session", "cmd")}, "at": time.time(),
            }


def update(entry_id: str, **fields: object) -> None:
    with store() as data:
        for entry in data["entries"]:
            if entry["id"] == entry_id:
                entry.update(fields)


def leave(entry_id: str) -> None:
    with store() as data:
        data["entries"] = [e for e in data["entries"] if e["id"] != entry_id]


def pause(wake: int) -> None:
    select.select([wake], [], [], POLL_SECONDS)


def wait(cfg: dict, entry_id: str, caught: list[int], wake: int) -> tuple[int | None, int]:
    """Poll until the grant.

    Args:
      cfg: the config at the hold's start; every poll reads it anew.
      entry_id: this hold's entry.
      caught: signals the caller caught; the first ends the wait.
      wake: the read end of the signal wakeup pipe; a caught signal makes it
        readable, so a pause between polls ends at once.

    Returns:
      (None, other active jobs at the grant) once granted, else (the exit
      code, 0).
    """
    shown = None
    while not caught:
        host = code_of(HOST_SKILLS)
        if host not in (None, CODE):
            raise Stale(host, caught)
        cfg = fresh(cfg)
        cpu, mem = watch.load(cfg)
        free, _ = watch.disk(cfg)
        now = time.time()
        signatures, kinds = learned(cfg, now)
        with store() as data:
            data["entries"] = prune(data["entries"])
            mine = [e for e in data["entries"] if e["id"] == entry_id]
            if not mine:
                print(f"queue: {entry_id} was cancelled", file=sys.stderr)
                return CANCELLED, 0
            rejoin(data, mine[0], now)
            loaded = held_back(cfg, data["entries"], now, signatures, kinds, cpu, mem, admitted_ram(data, now))
            steps: dict[str, list[str]] = {}
            verdicts, drain, order = decide(cfg, data["entries"], free, now, signatures, kinds, loaded, data.get(DRAIN), trace=steps)
            data[DRAIN] = latched(data, drain, now)
            mine[0]["trace"] = steps[entry_id]
            if verdicts[entry_id] is None:
                concurrent = sum(e["status"] == "active" for e in data["entries"])
                mine[0].update(status="active", granted=now, reason=labelled(verdicts, [])[entry_id],
                               **{GRANTED_MEM: mem, FROZEN: footprint(mine[0], signatures, kinds)})
                data[GRANTED] = now
                data.pop(STALL, None)
                if shown is not None:
                    print(f"queue: {entry_id} granted after waiting; running {mine[0]['cmd']}", file=sys.stderr, flush=True)
                return None, concurrent
            sends, clean, log = stalled(data, order, verdicts, cfg["thresholds_gb"]["stop"], free,
                                        functools.partial(cleanup_outcome, now), now)
            logs = [] if log is None else [log]
            if clean:
                data[CLEANUP], started = cleaned(data[CLEANUP])
                logs.append(started)
            reason = labelled(verdicts, data[STALL]["fired"] if STALL in data else [])[entry_id]
            mine[0]["reason"] = reason
        act(sends, logs, mine[0]["session"])
        position = list(verdicts).index(entry_id) + 1
        if (position, reason) != shown:
            print(f"queue: {entry_id} waits at position {position}: {reason}", file=sys.stderr, flush=True)
            shown = (position, reason)
        pause(wake)
    return 128 + caught[0], 0


def send(child: subprocess.Popen, signum: int) -> None:
    if child.returncode is None:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(child.pid, signum)


def measure(cfg: dict) -> dict[str, float]:
    free, _ = watch.disk(cfg)
    cpu, mem = watch.load(cfg)
    return {"free_gb": free, "mem": mem, "cpu": cpu}


def supervise(cfg: dict, child: subprocess.Popen, samples: list[dict[str, float]]) -> tuple[int, dict | None]:
    """Wait for the child, measuring every POLL_SECONDS and once at its end.

    Args:
      cfg: the config.
      child: the running command, leading a session of its own.
      samples: the measurements so far; each new one is appended.

    Returns:
      (the child's return code, None); (standstill.HUNG_EXIT, the probe of
      standstill.Clock.report()) once its process tree stood still for
      standstill.HUNG_SECONDS and stop() ended it.
    """
    clock = standstill.Clock(child.pid)
    code = None
    while code is None:
        with contextlib.suppress(subprocess.TimeoutExpired):
            code = child.wait(timeout=POLL_SECONDS)
        samples.append(measure(cfg))
        if code is None and clock.hung() and child.poll() is None:
            probe = clock.report()
            print(f"queue: {standstill.told(probe)}; ending the tree", file=sys.stderr, flush=True)
            return stop(child), probe
    return code, None


def stop(child: subprocess.Popen) -> int:
    """SIGTERM every process of the child's tree (standstill.members()), of
    the sessions its members lead and the descendants those have now,
    SIGKILL the ones still there after standstill.KILL_GRACE_SECONDS and
    those standstill.settle() found during it, again at each pass of the
    SIGKILL grace, a recorded member only while its start time matches; the
    child's process group (send()) when /proc does not show the child. A
    process that leaves the tree and every recorded session between two
    passes (setsid, then its parent dies) escapes; only a subreaper or a
    cgroup per job would hold it.

    Returns:
        standstill.HUNG_EXIT, also when a process outlives SIGKILL by another
        grace (uninterruptible sleep), so hold never waits on it.
    """
    targets = standstill.members(child.pid)
    for signum, repeat in ((signal.SIGTERM, None), (signal.SIGKILL, signal.SIGKILL)):
        living = standstill.signal_all(targets, signum)
        if child.pid not in living:
            send(child, signum)
        targets = standstill.settle(targets | living, child.poll, repeat)
    return standstill.HUNG_EXIT


def keep(row: dict) -> None:
    try:
        nofollow.append(watch.ROOT, watch.HISTORY, history.line(row), 0o600)
    except OSError as error:
        # A full disk refuses the row; the job's exit code must still come through.
        print(f"queue: no history row for {row['id']}: {error.strerror}", file=sys.stderr)


def record(job: dict, start: float, code: int, samples: list[dict[str, float]], concurrent: int) -> None:
    if code != NOT_RUN:
        keep(history.row(job, start, time.time(), code, samples, concurrent))


def gated(args: argparse.Namespace, here: str) -> tuple[ModuleType | None, int | None]:
    if args.receipt is None:
        if args.log is not None:
            fail("--log goes with --receipt")
        return None, None
    gates = sibling("gates")
    if args.receipt not in gates.LEVELS[1:] or args.log is None:
        fail(f"--receipt takes one of {', '.join(gates.LEVELS[1:])} and needs --log")
    gates.root(here)
    try:
        return gates, os.open(args.log, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    except OSError as error:
        fail(f"cannot write the log {args.log}: {error.strerror}")


def start_tree(gates: ModuleType | None, here: str) -> str | None:
    return None if gates is None else gates.worktree_tree(here)


def keep_receipt(gates: ModuleType | None, args: argparse.Namespace, here: str, before: str | None, code: int) -> None:
    if gates is None or code != 0:
        return
    after = gates.worktree_tree(here)
    if after != before:
        print(f"queue: the command changed the tree from {before} to {after}; no receipt", file=sys.stderr)
        return
    gates.add_receipt(gates.root(here), before, args.receipt, os.path.abspath(args.log))
    print(f"queue: receipt {args.receipt} for tree {before}", file=sys.stderr)


def check_hold(args: argparse.Namespace, cfg: dict) -> None:
    """Args:
        args: the hold arguments; fail() exits on an unknown kind, a command
            that is no light run under a light kind, a task outside the
            register or a missing hotfix row.
        cfg: the watch config.
    """
    if args.kind not in cfg["slot_need_gb"]:
        fail(f"kind {args.kind!r} is not in slot_need_gb of {watch.CONFIG}")
    shown = shlex.join(args.command)
    if args.kind in {watch.LIGHT_KIND, *cfg.get("light_kinds", [])} and not watch.light(shown, os.getcwd()):
        fail(f"{shown} is no light run and the light kind {args.kind} skips every reservation; run `{watch.queue_hold(shown)}`")
    rasci = sibling("rasci")
    if args.task not in rasci.merged(False):
        fail(f"{args.task} is no open task of the kvb-org-rasci register")
    if args.hotfix is not None and HOTFIX + args.hotfix not in rasci.load():
        fail(f"the register has no row {HOTFIX}{args.hotfix}")

def cmd_hold(args: argparse.Namespace) -> int:
    cfg = config()
    check_hold(args, cfg)
    here = workdir()
    gates, out = gated(args, here)
    names = aliases(here, args.command, os.getcwd())
    signatures, kinds = learned(cfg, time.time())
    need = args.need_gb
    if need is None:
        need = history.need_gb(signatures, kinds, args.kind, names)
    if need is None:
        need = cfg["slot_need_gb"][args.kind]
    if need < 0:
        fail("--need-gb must be 0 or more")
    council = sibling("council")
    session, _ = council.caller(args.session)
    caught: list[int] = []
    child: subprocess.Popen | None = None

    def forward(signum: int, _frame: object) -> None:
        if child is None:
            caught.append(signum)
        else:
            send(child, signum)

    wake, alarm = os.pipe()
    os.set_blocking(alarm, False)
    signal.set_wakeup_fd(alarm, warn_on_full_buffer=False)
    for signum in FORWARDED:
        signal.signal(signum, forward)
    with holding() as (tag, lock_fd):
        entry = enqueue({
            "kind": args.kind, "task": args.task, "need_gb": need, "hotfix": args.hotfix,
            "workdir": here, "session": session, "name": council.live_sessions().get(session) or session,
            "lock": tag, "code": CODE, "pid": os.getpid(), "pid_start": identity(os.getpid()), "child": None,
            "child_start": None, "status": "waiting", "enqueued": time.time(), "granted": None,
            "cmd": shlex.join(args.command), ALIASES: list(names), CLAIMS: claims_of(here),
        })
        try:
            try:
                code, concurrent = wait(cfg, entry["id"], caught, wake)
            except Stale:
                hand_over(entry["id"])
                raise
            if code is not None:
                return code
            if caught:
                return 128 + caught[0]
            samples = [measure(cfg)]
            before = start_tree(gates, here)
            start = time.time()
            try:
                child = subprocess.Popen(
                    args.command, start_new_session=True, pass_fds=(lock_fd,), stdout=out, stderr=out
                )
            except OSError as error:
                print(f"queue: cannot start {args.command[0]}: {error.strerror}", file=sys.stderr)
                return 2
            for signum in caught:
                send(child, signum)
            update(entry["id"], child=child.pid, child_start=identity(child.pid))
            code, hung = supervise(cfg, child, samples)
            code = code if code >= 0 else 128 - code
            job = {"id": f"{entry['id']}-{time.time_ns()}", "kind": args.kind, "signature": names[0],
                   "workdir": entry["workdir"], **({} if hung is None else {history.HUNG: hung})}
            record(job, start, code, samples, concurrent)
            keep_receipt(gates, args, here, before, code)
            return code
        finally:
            leave(entry["id"])


def cmd_list(args: argparse.Namespace) -> int:
    cfg = config()
    free, _ = watch.disk(cfg)
    now = time.time()
    signatures, kinds = learned(cfg, now)
    steps: dict[str, list[str]] = {}
    with store() as data:
        data["entries"] = prune(data["entries"])
        entries = list(data["entries"])
        verdicts, _, _ = decide(cfg, entries, free, now, signatures, kinds, {}, data.get(DRAIN), trace=steps)
        verdicts = labelled(verdicts, (data.get(STALL) or {}).get("fired", []))
    by_id = {e["id"]: e for e in entries}
    running = [(key_of(e), e["granted"]) for e in entries if e["status"] == "active"]
    rows = [
        (None, e, history.eta(signatures, [(key_of(e), e["granted"])], [], now), suspected(e, e.get("reason"), signatures, now) or "-",
         e.get("trace", []))
        for e in entries if e["status"] == "active"
    ]
    ahead: list[tuple[str, str]] = []
    for n, (entry_id, reason) in enumerate(verdicts.items(), 1):
        e = by_id[entry_id]
        own = not silent(e, now) and bool(e.get("reason"))
        rows.append((n, e, history.eta(signatures, running, ahead, now), (e["reason"] if own else reason) or "granted on its next poll",
                     e.get("trace", steps[entry_id]) if own else steps[entry_id]))
        ahead.append(key_of(e))
    host = code_of(HOST_SKILLS) or CODE
    rows = [(position, e, eta, stamped(e, reason, host), trace) for position, e, eta, reason, trace in rows]
    if args.json:
        rasci = sibling("rasci")
        print(json.dumps(listed(rows, rasci.merged(False), rasci.wsjf, now), indent=1))
        return 0
    print("position\tid\tstatus\tkind\ttask\tneed_gb\twaited_min\teta_min\tworkdir\treason")
    for position, e, eta, reason, _ in rows:
        waited = ((e["granted"] or now) - e["enqueued"]) / 60
        print(tab_line(
            ["run" if position is None else position, e["id"], e["status"], e["kind"], e["task"], f"{e['need_gb']:g}", f"{waited:.0f}",
             "-" if eta is None else f"{eta:.0f}", e["workdir"], reason]
        ))
    return 0


def suspected(entry: dict, reason: str | None, signatures: dict[tuple[str, str], dict], now: float) -> str | None:
    """Returns:
        reason led by `suspect hung (<runtime> min)` once the active entry
        runs past standstill.suspect_seconds() of the longest run its
        signature learned (history.learned_value()), else reason.
    """
    longest = history.learned_value(signatures, entry["kind"], aliases_of(entry), "longest")
    runtime = now - entry["granted"]
    if runtime < standstill.suspect_seconds(longest):
        return reason
    mark = f"suspect hung ({runtime / 60:.0f} min)"
    return mark if reason is None else f"{mark}; {reason}"


def stamped(entry: dict, reason: str, host: str) -> str:
    if entry.get("code") == host:
        return reason
    return f"queue code {entry.get('code') or 'without a stamp'}, the host runs {host}: {reason}"


def job_class(entry: dict, pin: int | None) -> str:
    """Returns:
        hotfix for a --hotfix job or a task pinned in the hotfix band (prio
        1), main for a job of the session named Main, fix for the fix band
        (prio 2), else feature.
    """
    if entry["hotfix"] or pin == 1:
        return "hotfix"
    if entry["name"] == "Main":
        return "main"
    return "fix" if pin == 2 else "feature"


def listed(rows: list[tuple], register: dict[str, dict], score: Callable[[dict], tuple | None],
           now: float) -> list[dict]:
    """Args:
        rows: (position, None while active, entry, ETA minutes or None, the
            reason list shows, the trace steps) in list order.
        register: the merged kvb-org-rasci rows by task.
        score: rasci.wsjf, (value, complexity, WSJF) of a row or None.
        now: epoch seconds.

    Returns:
        One object per row: position, id, status, kind, task, session,
        agent, class (job_class()), prio (the task's pin or None), wsjf (or
        None), waited_s, eta_s (or None), reason and trace, the steps of
        evaluate() that decided the entry at the poll that set its reason.
    """
    shown = []
    for position, e, eta, reason, trace in rows:
        row = register.get(e["task"], {})
        wsjf = score(row)
        shown.append({
            "position": position, "id": e["id"], "status": e["status"], "kind": e["kind"], "task": e["task"],
            "session": e.get("session"), "agent": e["name"], "class": job_class(e, row.get("prio")), "prio": row.get("prio"),
            "wsjf": None if wsjf is None else wsjf[2], "waited_s": round((e["granted"] or now) - e["enqueued"]),
            "eta_s": None if eta is None else round(eta * 60), "reason": reason, "trace": trace,
        })
    return shown


def tab_line(fields: list[object]) -> str:
    return "\t".join("".join(c if c.isprintable() else c.encode("unicode_escape").decode() for c in str(f)) for f in fields)


def cmd_history(_: argparse.Namespace) -> int:
    cfg = config()
    signatures, kinds = learned(cfg, time.time())
    print(history.report(signatures, kinds, limits(cfg, kinds, [])), end="")
    return 0


def cmd_cancel(args: argparse.Namespace) -> int:
    session, _ = sibling("council").caller(args.session)
    with store() as data:
        mine = [
            e for e in data["entries"]
            if e["id"] == args.id and e["status"] == "waiting" and e["session"] == session
        ]
        if not mine:
            fail(f"no waiting entry {args.id} of this session; `queue.py list` shows the ids")
        data["entries"].remove(mine[0])
    print(f"cancelled {args.id}")
    return 0


def settings_files(project: Path) -> list[Path]:
    return sibling("councilroot").settings_files(project)


def bash_rule(rule: str) -> re.Pattern | None:
    match = BASH_RULE.fullmatch(rule)
    if match is None:
        return None
    body = match.group(1) or "*"
    if body.endswith(":*"):
        body = body[:-2] + " *"
    return re.compile(
        "".join(
            r"(?:\s.*)?" if part == " *" else ".*" if part == "*" else re.escape(part)
            for part in RULE_PART.split(body)
        ),
        re.DOTALL,
    )


def permission(commands: list[str], project: Path) -> str | None:
    settings = []
    for path in settings_files(project):
        with contextlib.suppress(FileNotFoundError):
            text = path.read_text(encoding="utf-8")
            settings.append((json.loads(text).get("permissions") or {}) if text.strip() else {})
    for decision in ("deny", "ask"):
        rules = [bash_rule(rule) for permissions in settings for rule in permissions.get(decision) or []]
        if any(rule and rule.fullmatch(command) for rule in rules for command in commands):
            return decision
    return None


def held_commands(command: str) -> list[list[str]]:
    return [
        cli().parse_args(part[at + 1 :]).command
        for part in watch.segments(command)
        for at, token in enumerate(part)
        if token.endswith("queue.py") and part[at + 1 : at + 2] == ["hold"]
    ]


def enforced(cfg: dict) -> dict:
    return {**cfg, "heavy_commands": [*cfg["heavy_commands"], GATE.pattern]}


def admit(cfg: dict, kind: str, argv: list[str], cpu: float, mem: float, calm: bool) -> str | None:
    """Args:
        cfg: the config.
        kind: the kind of the light job that asks to start outside the queue.
        argv: its command, run in the current directory.
        cpu: CPU busy now, in percent.
        mem: RAM used now, in percent.
        calm: whether the memory stage is ok; the live active jobs' ramp
            (ramping_ram()) counts only when it is not.

    Returns:
        cap_problem() of cfg first; else load_reason() over the job's RAM
        share plus the live admit records (admitted_ram()) and the ramp;
        under the store lock, a grant records the share for ADMIT_SECONDS
        and expired records leave.
    """
    if (problem := cap_problem(cfg)) is not None:
        return problem
    now = time.time()
    signatures, kinds = learned(cfg, now)
    mine = {"id": ADMIT, "status": "waiting", "kind": kind, ALIASES: list(aliases(workdir(), argv, os.getcwd()))}
    share = ram_share(mine, signatures, kinds)
    with store() as data:
        active = [e for e in data["entries"] if e["status"] == "active" and living(e)]
        ramp = 0.0 if calm else ramping_ram(active, now, signatures, kinds, mem)
        reason = load_reason(cfg["load_limits"], cpu, mem, share + admitted_ram(data, now) + ramp)
        granted = [{"ram": share, "expires": now + ADMIT_SECONDS}] if reason is None else []
        data[ADMITS] = [record for record in data.get(ADMITS, []) if record["expires"] > now] + granted
    return reason


def tails(argv: list[str]) -> list[str]:
    return [shlex.join(argv[at:]) for at, word in enumerate(argv) if not word.startswith("-")]


def cmd_block() -> int:
    payload = json.load(sys.stdin)
    raw = (payload.get("tool_input") or {}).get("command") or ""
    try:
        holds = held_commands(raw)
        commands = [t for argv in holds for t in tails(argv)]
        decision = permission(commands, Path(os.environ["CLAUDE_PROJECT_DIR"])) if commands else None
    except (ValueError, KeyError, OSError, SystemExit) as error:
        if "queue" in raw:
            print(
                f"kvb-org-queue: cannot check the held command against the settings ({error!r}); "
                "fix the settings or run the command outside queue.py hold.",
                file=sys.stderr,
            )
            return 2
        holds, decision = [], None
    shown = " ; ".join(shlex.join(argv) for argv in holds)
    if decision == "deny":
        print(f"kvb-org-queue: the held command `{shown}` meets a deny rule of the settings.", file=sys.stderr)
        return 2
    if decision == "ask":
        reason = f"kvb-org-queue: the held command `{shown}` meets an ask rule of the settings"
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "ask", "permissionDecisionReason": reason,
        }}))
        return 0
    cfg, _ = watch.announced_config()
    if cfg is None or cfg.get("queue_enforce") is not True:
        return 0
    if watch.heavy(raw, enforced(cfg), (THROUGH_QUEUE.pattern, *cfg["never_block"]), watch.payload_cwd(payload)):
        print(
            f"kvb-org-queue: heavy jobs run through the queue: start `python3 {Path(__file__).resolve()} hold "
            "--kind <kind> --task <register task> -- <command>` in the background; it runs the command on its grant.",
            file=sys.stderr,
        )
        return 2
    return 0


def cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    hold = sub.add_parser("hold")
    hold.add_argument("--kind", required=True)
    hold.add_argument("--task", required=True)
    hold.add_argument("--need-gb", type=float)
    hold.add_argument("--hotfix")
    hold.add_argument("--session")
    hold.add_argument("--receipt")
    hold.add_argument("--log")
    hold.add_argument("command", nargs="+")
    sub.add_parser("list").add_argument("--json", action="store_true")
    sub.add_parser("history")
    cancel = sub.add_parser("cancel")
    cancel.add_argument("id")
    cancel.add_argument("--session")
    sub.add_parser("block")
    return parser


def main() -> int:
    args = cli().parse_args()
    refused = watch.guard_root(hook=args.cmd == "block")
    if refused is not None:
        return refused
    if args.cmd == "block":
        try:
            return cmd_block()
        except Exception as error:  # noqa: BLE001
            print(f"kvb-org-queue: the block hook failed ({error!r}), so the command counts as heavy and is refused.",
                  file=sys.stderr)
            return 2
    commands = {"hold": cmd_hold, "list": cmd_list, "history": cmd_history, "cancel": cmd_cancel}
    try:
        return commands[args.cmd](args)
    except Stale as stale:
        host, caught = stale.args
        for signum in FORWARDED:
            signal.signal(signum, signal.SIG_DFL)
        if caught:
            return 128 + caught[0]
        script = HOST_SKILLS / CODE_FILES[0]
        print(
            f"queue: this hold ran queue code {CODE} from {SKILLS}, but the queue code installed on this host is "
            f"{host} in {HOST_SKILLS}. Holders on different code each apply their own rules to the shared queue "
            f"and together overrun the RAM and CPU budget, so this hold grants nothing on its own code. "
            f"Restarting this hold with {script}; run every queue.py command from that path.",
            file=sys.stderr, flush=True,
        )
        try:
            os.execv(EXE, [EXE, str(script), *sys.argv[1:]])
        except OSError as error:
            fail(f"cannot restart with {script}: {error.strerror}; run the same hold with {script}")


if __name__ == "__main__":
    sys.exit(main())
