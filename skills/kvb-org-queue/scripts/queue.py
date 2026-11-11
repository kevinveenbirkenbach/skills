#!/usr/bin/env python3
"""Queue the heavy jobs of parallel agents and grant them in a fixed order, without messages.

Usage:
    queue.py hold --kind KIND --task TASK [--need-gb N] [--hotfix SLUG] [--session ID] -- CMD...
    queue.py list
    queue.py history
    queue.py cancel ID [--session ID]
    queue.py block     hook (PreToolUse on Bash)

Environment:
    AGENTS_COUNCIL_ROOT: shared state directory; /tmp/agents-council unless set,
        because every agent on the host must agree on it. The queue is
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
        the lock until this entry is granted; measure disk, RAM and CPU, run
        CMD in the current directory with inherited stdio in a session of its
        own, forward SIGINT and SIGTERM to its process group, measure every
        POLL_SECONDS and at its end, record its history row and leave the
        queue. The entry carries its code (a hash of this file and the
        SIBLINGS); a poll that finds other code installed in
        ~/.agents/skills leaves the queue ungranted and restarts the same hold
        with the installed queue.py.
        --kind: a key of slot_need_gb in the config.
        --task: an open task of the kvb-org-rasci register; its rank orders
            the queue, and the operator's agent order (`rasci.py agents
            order`) of the holding session breaks ties.
        --need-gb: disk the job takes, in GB; when omitted the need learned
            for the command's signature, else slot_need_gb[kind].
        --hotfix: the slug of the register row hotfix/<slug> the job proves;
            hotfix jobs go first.
        --session: the caller's session for runtimes other than Claude Code.
    list: a header, then one line per entry: position (run for active jobs),
        id, status, kind, task, need GB, minutes waited, ETA minutes (until a
        running job ends or a waiting one starts, from learned medians; - while
        one is unknown), workdir, blocking reason (the one the holder saw at
        its last poll, host load included; prefixed when the entry runs other
        code than the installed one). Entries of dead holders are dropped
        first.
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
above (history.slot_limits); queue_enforce (bool), optional, read by block
only. The watch.py keys disk, thresholds_gb (stop is the floor every grant
leaves free), slot_need_gb (the disk seed per kind), load_limits (every grant
also needs CPU busy below cpu_percent and RAM used plus the job's learned RAM
share below mem_percent; both bound the learned slot limits), memory_limits (no
grant at memory stage stop), heavy_commands and never_block are used as
watch.py documents them. A signature is `<repository>: <command signature>`
(qualified()).

Exit codes:
    hold: the command's exit code unchanged, 128+N when signal N ended it;
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
import shlex
import signal
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import NoReturn

SKILLS = Path(__file__).resolve().parents[2]
SIBLINGS = {
    "watch": SKILLS / "kvb-org-organize" / "scripts" / "watch.py",
    "council": SKILLS / "kvb-org-organize" / "scripts" / "council.py",
    "rasci": SKILLS / "kvb-org-rasci" / "scripts" / "rasci.py",
    "history": Path(__file__).resolve().parent / "history.py",
    "nofollow": SKILLS / "kvb-org-organize" / "scripts" / "nofollow.py",
}
HOST_SKILLS = Path.home() / ".agents" / "skills"
EXE = os.path.realpath(sys.executable)
CODE_FILES = tuple(path.relative_to(SKILLS) for path in (Path(__file__).resolve(), *SIBLINGS.values()))
POLL_SECONDS = 20
CLAIM_SECONDS = 3 * POLL_SECONDS
TICK_SECONDS = 0.2
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
MANAGED = Path("/etc/claude-code")
BUDGET_KEYS = ("budget_percent.ram", "budget_percent.cpu")
HOTFIX = "hotfix/"


@functools.cache
def sibling(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"kvb_queue_{name}", SIBLINGS[name])
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


watch = sibling("watch")
history = sibling("history")
nofollow = sibling("nofollow")
STORE = watch.ROOT / "queue.json"
LOCK = watch.ROOT / "queue.lock"
HOLDS = watch.ROOT / "holds"
TAG = re.compile(r"\d+-\d+")
SILENCE = watch.ROOT / "radio-silence.json"
HISTORIES = (watch.HISTORY, watch.KEPT_HISTORY)


def code_of(root: Path) -> str | None:
    try:
        return hashlib.sha256(b"".join((root / name).read_bytes() for name in CODE_FILES)).hexdigest()[:12]
    except OSError:
        return None


CODE = code_of(SKILLS)


class Stale(Exception):
    pass


def fail(message: str) -> NoReturn:
    print(f"queue: {message}", file=sys.stderr)
    sys.exit(2)


def config() -> dict:
    cfg = watch.load_config()
    if cfg is None:
        fail(f"no config at {watch.CONFIG}; the queue reads the kvb-org-organize watch config")
    problem = watch.missing(cfg, (*BUDGET_KEYS, *watch.MEMORY_KEYS))
    if problem is not None:
        fail(problem)
    return cfg


def caps(cfg: dict) -> dict[str, int]:
    return cfg.get("slot_limits", {})


def learned(cfg: dict, now: float) -> tuple[dict[str, dict], dict[str, dict]]:
    return history.learn(history.read(HISTORIES), now, cfg)


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


def qualified(workdir: str, argv: list[str]) -> str:
    """Returns:
        `<repository>: <history.signature of command_words>`: the directory
        holding the main checkout's .git, so every worktree of one repository
        shares it, else the workdir's name; one make test of two repositories
        stays apart.
    """
    return f"{repository(workdir)}: {history.signature(command_words(argv))}"


def signature_of(entry: dict) -> str:
    return qualified(entry["workdir"], shlex.split(entry["cmd"]))


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


def ordered(waiting: list[dict], ranks: dict[str, int], agents: dict[str, int], now: float) -> list[dict]:
    def key(entry: dict) -> tuple:
        hours = int((now - entry["enqueued"]) // HOUR)
        rank = ranks[entry["task"]] if entry["task"] in ranks else len(ranks)
        agent = agents[entry["name"]] if entry["name"] in agents else len(agents)
        return (not entry["hotfix"], rank - hours, agent, entry["seq"])

    return sorted(waiting, key=key)


def over_budget(used: dict[str, float], share: dict[str, float], budget: dict[str, float]) -> str | None:
    over = [resource for resource in budget if used[resource] + share[resource] > budget[resource]]
    if not over:
        return None
    return ", ".join(
        f"{resource.upper()} {used[resource]:.0f} % in use or reserved + {share[resource]:.0f} % > budget {budget[resource]:g} %"
        for resource in over
    ) + "; reserved"


def evaluate(entries: list[dict], free_gb: float, floor: float, stage: str, memory: str, silenced: bool,
             slot_limits: dict[str, int], footprints: dict[str, dict[str, float]], budget: dict[str, float],
             ranks: dict[str, int], agents: dict[str, int], loaded: dict[str, str],
             now: float) -> dict[str, str | None]:
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
        (history.footprint), in percentage points.
      budget: {ram, cpu}: the sum of the footprints of active and granted
        entries may not pass it; a job alone always fits.
      ranks: {task: index in the register's ranking}; a task missing there
        ranks after all of them.
      agents: {agent name: index in the operator's agent order}; it breaks
        ties of equal rank only, an entry whose holder is missing there after
        all of them.
      loaded: {entry id: why live CPU or RAM holds it back (load_reason())}
        for the waiting entries the host load keeps out.
      now: epoch seconds; each whole hour waited moves an entry one rank up.

    Returns:
      {entry id: None when granted, else the blocking reason}, in grant order.
      An unblocked entry counts as granted for the entries after it, whoever
      holds it, so a lower entry never takes a higher entry's slot; one
      blocked by disk or budget reserves its need against the entries after it.
      A hotfix entry that passes every check but the host load holds back
      every entry after it, so lighter jobs cannot keep the load up. A waiting
      entry whose holder has not polled for CLAIM_SECONDS reserves nothing and
      comes last.
    """
    active = [e for e in entries if e["status"] == "active"]
    available = free_gb - sum(e["need_gb"] for e in active)
    used = {resource: sum(footprints[e["id"]][resource] for e in active) for resource in budget}
    taken = len(active)
    counts = Counter(e["kind"] for e in active)
    busy = {e["workdir"] for e in active}
    verdicts: dict[str, str | None] = {}
    waiting = [e for e in entries if e["status"] == "waiting"]
    held = None
    for entry in ordered([e for e in waiting if not silent(e, now)], ranks, agents, now):
        if held is not None:
            verdicts[entry["id"]] = f"waits behind hotfix {held}, which the host load holds back"
            continue
        kind, need, workdir, share = entry["kind"], entry["need_gb"], entry["workdir"], footprints[entry["id"]]
        reason = host_reason(stage, memory, silenced, need) or slot_reason(kind, workdir, slot_limits, counts, busy)
        if reason is None:
            reason, used, available = resources(need, share, used, available, floor, budget, taken)
            if reason is None and entry["hotfix"] and entry["id"] in loaded:
                reason, held = loaded[entry["id"]], entry["id"]
            elif reason is None:
                taken += 1
                counts[kind] += 1
                busy.add(workdir)
        verdicts[entry["id"]] = reason
    for entry in waiting:
        if silent(entry, now):
            verdicts[entry["id"]] = f"no poll for {now - entry['polled']:.0f} s; reserves nothing until it polls again"
    return verdicts


def silent(entry: dict, now: float) -> bool:
    return entry["status"] == "waiting" and now - entry.get("polled", now) > CLAIM_SECONDS


def rejoin(data: dict, entry: dict, now: float) -> None:
    if silent(entry, now):
        data["seq"] += 1
        entry.update(seq=data["seq"], enqueued=now)
    entry["polled"] = now


def plus(used: dict[str, float], share: dict[str, float]) -> dict[str, float]:
    return {resource: used[resource] + share[resource] for resource in used}


def resources(need: float, share: dict[str, float], used: dict[str, float], available: float, floor: float,
              budget: dict[str, float], taken: int) -> tuple[str | None, dict[str, float], float]:
    """Returns:
        (reason or None, RAM and CPU used or reserved, disk available) after
        the job: one passing the budget beside other jobs reserves its share,
        one cutting into the floor its disk, a granted one takes both.
    """
    if taken and (reason := over_budget(used, share, budget)) is not None:
        return reason, plus(used, share), available
    if available - need < floor:
        return f"{need:g} GB would cut into the {floor:g} GB floor; reserved", used, available - need
    return None, plus(used, share), available - need


def host_reason(stage: str, memory: str, silenced: bool, need: float) -> str | None:
    if stage in ("stop", "critical"):
        return f"disk stage {stage}"
    if stage == "warn" and need > 0:
        return "disk stage warn admits only jobs that need no disk"
    if memory == "stop":
        return "memory stage stop"
    if silenced:
        return "radio silence"
    return None


def slot_reason(kind: str, workdir: str, slot_limits: dict[str, int], counts: Counter, busy: set[str]) -> str | None:
    if kind not in slot_limits:
        return f"slot_limits has no {kind}"
    if counts[kind] >= slot_limits[kind]:
        return f"all {slot_limits[kind]} {kind} slots taken"
    if workdir in busy:
        return f"{workdir} runs another job"
    return None


def register_ranks() -> dict[str, int]:
    rasci = sibling("rasci")
    return {task: index for index, task in enumerate(rasci.ranked(rasci.merged(False)))}


def agent_ranks() -> dict[str, int]:
    return {name: index for index, name in enumerate(sibling("rasci").agent_order())}


def stage(cfg: dict, free_gb: float, now: float) -> str:
    state = watch.read_json(watch.STATE)
    return state["stage"] if "stage" in state else watch.stage_for(free_gb, [], cfg, now)


def silenced(now: float) -> bool:
    state = watch.read_json(SILENCE)
    return "until" in state and state["until"] > now


def footprint(entry: dict, signatures: dict[str, dict], kinds: dict[str, dict]) -> dict[str, float] | None:
    return history.footprint(entry["kind"], signature_of(entry), signatures, kinds)


def held_back(cfg: dict, entries: list[dict], now: float, signatures: dict[str, dict], kinds: dict[str, dict],
              cpu: float, mem: float) -> dict[str, str]:
    loaded = {}
    for entry in entries:
        if entry["status"] == "waiting":
            pending = pending_ram(entries, entry["id"], now, signatures, kinds)
            if (reason := load_reason(cfg["load_limits"], cpu, mem, pending)) is not None:
                loaded[entry["id"]] = reason
    return loaded


def decide(cfg: dict, entries: list[dict], free_gb: float, now: float, signatures: dict[str, dict],
           kinds: dict[str, dict], loaded: dict[str, str]) -> dict[str, str | None]:
    slots = {kind: limit for kind, (limit, _) in limits(cfg, kinds, entries).items()}
    budget = cfg["budget_percent"]
    footprints = {}
    for entry in entries:
        share = footprint(entry, signatures, kinds)
        footprints[entry["id"]] = dict(budget) if share is None else share
    return evaluate(
        entries, free_gb, cfg["thresholds_gb"]["stop"], stage(cfg, free_gb, now),
        watch.memory_stage(watch.memory(), cfg), silenced(now), slots, footprints, budget,
        register_ranks(), agent_ranks(), loaded, now,
    )


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


def pending_ram(entries: list[dict], entry_id: str, now: float, signatures: dict[str, dict],
                kinds: dict[str, dict]) -> float:
    """Returns:
        The RAM share of entry_id plus the whole share of every active job
        granted less than RAMP_SECONDS ago (or without a grant time): what
        may still come once they ramp up. An older job counts as ramped, its
        RAM inside the RAM used; one that peaks later is bounded by the
        memory stage only.
    """
    mine = [e for e in entries if e["id"] == entry_id]
    young = [e for e in entries if e["status"] == "active" and now - e.get("granted", now) < RAMP_SECONDS]
    return ram_share(mine[0], signatures, kinds) + sum(ram_share(e, signatures, kinds) for e in young)


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
    with store() as data:
        data["seq"] += 1
        entry = {"id": f"{fields['kind']}-{data['seq']}", "seq": data["seq"], **fields}
        data["entries"].append(entry)
    return entry


def update(entry_id: str, **fields: object) -> None:
    with store() as data:
        for entry in data["entries"]:
            if entry["id"] == entry_id:
                entry.update(fields)


def leave(entry_id: str) -> None:
    with store() as data:
        data["entries"] = [e for e in data["entries"] if e["id"] != entry_id]


def pause(caught: list[int]) -> None:
    deadline = time.monotonic() + POLL_SECONDS
    while not caught and time.monotonic() < deadline:
        time.sleep(TICK_SECONDS)


def wait(cfg: dict, entry_id: str, caught: list[int]) -> tuple[int | None, int]:
    """Poll until the grant.

    Args:
      cfg: the config.
      entry_id: this hold's entry.
      caught: signals the caller caught; the first ends the wait.

    Returns:
      (None, other active jobs at the grant) once granted, else (the exit
      code, 0).
    """
    shown = None
    while not caught:
        host = code_of(HOST_SKILLS)
        if host not in (None, CODE):
            raise Stale(host, caught)
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
            loaded = held_back(cfg, data["entries"], now, signatures, kinds, cpu, mem)
            verdicts = decide(cfg, data["entries"], free, now, signatures, kinds, loaded)
            reason = verdicts[entry_id] or loaded.get(entry_id)
            mine[0]["reason"] = reason
            if reason is None:
                concurrent = sum(e["status"] == "active" for e in data["entries"])
                mine[0].update(status="active", granted=now)
                return None, concurrent
        position = list(verdicts).index(entry_id) + 1
        if (position, reason) != shown:
            print(f"queue: {entry_id} waits at position {position}: {reason}", file=sys.stderr, flush=True)
            shown = (position, reason)
        pause(caught)
    return 128 + caught[0], 0


def send(child: subprocess.Popen, signum: int) -> None:
    if child.returncode is None:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(child.pid, signum)


def measure(cfg: dict) -> dict[str, float]:
    free, _ = watch.disk(cfg)
    cpu, mem = watch.load(cfg)
    return {"free_gb": free, "mem": mem, "cpu": cpu}


def supervise(cfg: dict, child: subprocess.Popen, samples: list[dict[str, float]]) -> int:
    """Wait for the child, measuring every POLL_SECONDS and once at its end.

    Args:
      cfg: the config.
      child: the running command.
      samples: the measurements so far; each new one is appended.

    Returns:
      The child's return code.
    """
    code = None
    while code is None:
        with contextlib.suppress(subprocess.TimeoutExpired):
            code = child.wait(timeout=POLL_SECONDS)
        samples.append(measure(cfg))
    return code


def keep(row: dict) -> None:
    try:
        nofollow.append(watch.ROOT, watch.HISTORY, history.line(row), 0o600)
    except OSError as error:
        # A full disk refuses the row; the job's exit code must still come through.
        print(f"queue: no history row for {row['id']}: {error.strerror}", file=sys.stderr)


def record(job: dict, start: float, code: int, samples: list[dict[str, float]], concurrent: int) -> None:
    if code != NOT_RUN:
        keep(history.row(job, start, time.time(), code, samples, concurrent))


def cmd_hold(args: argparse.Namespace) -> int:
    cfg = config()
    if args.kind not in cfg["slot_need_gb"]:
        fail(f"kind {args.kind!r} is not in slot_need_gb of {watch.CONFIG}")
    rasci = sibling("rasci")
    if args.task not in rasci.merged(False):
        fail(f"{args.task} is no open task of the kvb-org-rasci register")
    if args.hotfix is not None and HOTFIX + args.hotfix not in rasci.load():
        fail(f"the register has no row {HOTFIX}{args.hotfix}")
    here = workdir()
    signature = qualified(here, args.command)
    signatures, _ = learned(cfg, time.time())
    need = args.need_gb
    if need is None:
        need = history.need_gb(signatures, signature)
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

    for signum in FORWARDED:
        signal.signal(signum, forward)
    with holding() as (tag, lock_fd):
        entry = enqueue({
            "kind": args.kind, "task": args.task, "need_gb": need, "hotfix": args.hotfix,
            "workdir": here, "session": session, "name": council.live_sessions().get(session) or session,
            "lock": tag, "code": CODE, "pid": os.getpid(), "pid_start": identity(os.getpid()), "child": None,
            "child_start": None, "status": "waiting", "enqueued": time.time(), "granted": None,
            "cmd": shlex.join(args.command),
        })
        try:
            code, concurrent = wait(cfg, entry["id"], caught)
            if code is not None:
                return code
            if caught:
                return 128 + caught[0]
            samples = [measure(cfg)]
            start = time.time()
            try:
                child = subprocess.Popen(args.command, start_new_session=True, pass_fds=(lock_fd,))
            except OSError as error:
                print(f"queue: cannot start {args.command[0]}: {error.strerror}", file=sys.stderr)
                return 2
            for signum in caught:
                send(child, signum)
            update(entry["id"], child=child.pid, child_start=identity(child.pid))
            code = supervise(cfg, child, samples)
            code = code if code >= 0 else 128 - code
            job = {"id": f"{entry['id']}-{time.time_ns()}", "kind": args.kind, "signature": signature,
                   "workdir": entry["workdir"]}
            record(job, start, code, samples, concurrent)
            return code
        finally:
            leave(entry["id"])


def cmd_list(_: argparse.Namespace) -> int:
    cfg = config()
    free, _ = watch.disk(cfg)
    now = time.time()
    signatures, kinds = learned(cfg, now)
    with store() as data:
        data["entries"] = prune(data["entries"])
        entries = list(data["entries"])
        verdicts = decide(cfg, entries, free, now, signatures, kinds, {})
    by_id = {e["id"]: e for e in entries}
    running = [(signature_of(e), e["granted"]) for e in entries if e["status"] == "active"]
    rows = [
        ("run", e, history.eta(signatures, [(signature_of(e), e["granted"])], [], now), "-")
        for e in entries if e["status"] == "active"
    ]
    ahead: list[str] = []
    for n, (entry_id, reason) in enumerate(verdicts.items(), 1):
        e = by_id[entry_id]
        polled = reason if silent(e, now) else e.get("reason") or reason
        rows.append((str(n), e, history.eta(signatures, running, ahead, now), polled or "granted on its next poll"))
        ahead.append(signature_of(e))
    host = code_of(HOST_SKILLS) or CODE
    print("position\tid\tstatus\tkind\ttask\tneed_gb\twaited_min\teta_min\tworkdir\treason")
    for position, e, eta, reason in rows:
        if e.get("code") != host:
            reason = f"queue code {e.get('code') or 'without a stamp'}, the host runs {host}: {reason}"
        waited = ((e["granted"] or now) - e["enqueued"]) / 60
        print(tab_line(
            [position, e["id"], e["status"], e["kind"], e["task"], f"{e['need_gb']:g}", f"{waited:.0f}",
             "-" if eta is None else f"{eta:.0f}", e["workdir"], reason]
        ))
    return 0


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
    user = Path.home() / ".claude"
    return [
        MANAGED / "managed-settings.json",
        *sorted((MANAGED / "managed-settings.d").glob("*.json")),
        user / "settings.json",
        user / "settings.local.json",
        project / ".claude" / "settings.json",
        project / ".claude" / "settings.local.json",
    ]


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
            settings.append(json.loads(path.read_text(encoding="utf-8")).get("permissions") or {})
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
    cfg = watch.load_config()
    if cfg is None or cfg.get("queue_enforce") is not True:
        return 0
    gated = {**cfg, "heavy_commands": [*cfg["heavy_commands"], GATE.pattern]}
    if watch.heavy(raw, gated, (THROUGH_QUEUE.pattern, *cfg["never_block"])):
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
    hold.add_argument("command", nargs="+")
    sub.add_parser("list")
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
        except (OSError, ValueError, KeyError, TypeError, AttributeError, re.error):
            return 0
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
