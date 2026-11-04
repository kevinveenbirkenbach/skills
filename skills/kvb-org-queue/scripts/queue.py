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
        Every finished job appends a row (history.py) to
        <root>/queue-history.jsonl; the watch hook of watch.py keeps a copy in
        ~/.local/state/agents-council/queue-history.jsonl, and reading merges
        both by row id.
    AGENTS_COUNCIL_CONFIG: the config of the kvb-org-organize watch.py;
        ~/.config/agents-council/config.json unless set.
    CLAUDE_CODE_SESSION_ID: the caller's session, taken over --session; other
        runtimes pass --session.

Args:
    hold: enqueue CMD, then every POLL_SECONDS evaluate the whole queue under
        the lock until this entry is granted; measure disk, RAM and CPU, run
        CMD in the current directory with inherited stdio in a session of its
        own, forward SIGINT and SIGTERM to its process group, measure every
        POLL_SECONDS and at its end, record its history row and leave the
        queue.
        --kind: a key of slot_need_gb in the config.
        --task: an open task of the kvb-org-rasci register; its rank orders
            the queue.
        --need-gb: disk the job takes, in GB; when omitted the need learned
            for the command's signature, else slot_need_gb[kind].
        --hotfix: the slug of the register row hotfix/<slug> the job proves;
            hotfix jobs go first.
        --session: the caller's session for runtimes other than Claude Code.
    list: a header, then one line per entry: position (run for active jobs),
        id, status, kind, task, need GB, minutes waited, ETA minutes (until a
        running job ends or a waiting one starts, from learned medians; - while
        one is unknown), workdir, blocking reason. Entries of dead holders are
        dropped first.
    history: a markdown table per command signature and one per kind of what
        the last 30 days of history teach, with each slot limit's source.
    cancel ID: remove the caller's waiting entry ID; its hold exits 3.
    block: read the hook payload on stdin; with queue_enforce true in the
        config, refuse a command matching heavy_commands or `gate.py run|hold`
        unless it matches never_block or runs `queue.py hold`.

Config keys: slot_limits {kind: N}, optional, caps the learned slot limit of a
kind from above (history.slot_limits); queue_enforce (bool), optional, read by
block only. The watch.py keys disk, thresholds_gb (stop is the floor every
grant leaves free), slot_need_gb (the disk seed per kind), load_limits (kinds
in its kinds also need CPU and RAM below the limits; mem_percent and
cpu_percent bound the learned slot limits), heavy_commands and never_block are
used as watch.py documents them.

Exit codes:
    hold: the command's exit code unchanged, 128+N when signal N ended it;
        before the command started 2 on a usage or config error or when it
        cannot start, 3 when cancel removed the entry, 128+N when signal N
        reached hold.
    list, history: 0 done, 2 config error.
    cancel: 0 removed, 2 no waiting entry of the caller with that id.
    block: 0 allow, 2 refuse the tool call; every error allows.
"""

from __future__ import annotations

# Trip-wire: run as a script, this file shadows the stdlib queue module, so nothing here
# may import a module that imports queue (logging.handlers, concurrent.futures, multiprocessing).
import argparse
import contextlib
import fcntl
import functools
import importlib.util
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import tempfile
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
}
POLL_SECONDS = 20
TICK_SECONDS = 0.2
HOUR = 3600
CANCELLED = 3
FORWARDED = (signal.SIGINT, signal.SIGTERM)
GATE = re.compile(r"\bgate\.py\s+(run|hold)\b")
THROUGH_QUEUE = re.compile(r"\bqueue\.py\s+hold\b")
HOTFIX = "hotfix/"


@functools.cache
def sibling(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"kvb_queue_{name}", SIBLINGS[name])
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


watch = sibling("watch")
history = sibling("history")
STORE = watch.ROOT / "queue.json"
LOCK = watch.ROOT / "queue.lock"
SILENCE = watch.ROOT / "radio-silence.json"
HISTORIES = (watch.HISTORY, watch.KEPT_HISTORY)


def fail(message: str) -> NoReturn:
    print(f"queue: {message}", file=sys.stderr)
    sys.exit(2)


def config() -> dict:
    cfg = watch.load_config()
    if cfg is None:
        fail(f"no config at {watch.CONFIG}; the queue reads the kvb-org-organize watch config")
    return cfg


def caps(cfg: dict) -> dict[str, int]:
    return cfg.get("slot_limits", {})


def learned(cfg: dict, now: float) -> tuple[dict[str, dict], dict[str, dict]]:
    return history.learn(history.read(HISTORIES), now, cfg)


def limits(cfg: dict, kinds: dict[str, dict], entries: list[dict]) -> dict[str, tuple[int, str]]:
    return history.slot_limits(kinds, caps(cfg), {*cfg["slot_need_gb"], *(e["kind"] for e in entries)})


def signature_of(entry: dict) -> str:
    return history.signature(shlex.split(entry["cmd"]))


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


def prune(entries: list[dict]) -> list[dict]:
    return [
        e for e in entries
        if alive(e["pid"], e["pid_start"]) or (e["status"] == "active" and alive(e["child"], e["child_start"]))
    ]


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
    with LOCK.open("a", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = read_store()
        yield data
        with tempfile.NamedTemporaryFile(
            "w", dir=watch.ROOT, prefix=".queue-", delete=False, encoding="utf-8"
        ) as tmp:
            json.dump(data, tmp, indent=1, sort_keys=True)
        os.replace(tmp.name, STORE)


def ordered(waiting: list[dict], ranks: dict[str, int], now: float) -> list[dict]:
    def key(entry: dict) -> tuple:
        hours = int((now - entry["enqueued"]) // HOUR)
        rank = ranks[entry["task"]] if entry["task"] in ranks else len(ranks)
        return (not entry["hotfix"], rank - hours, entry["seq"])

    return sorted(waiting, key=key)


def evaluate(entries: list[dict], free_gb: float, floor: float, stage: str, silenced: bool,
             slot_limits: dict[str, int], ranks: dict[str, int], now: float) -> dict[str, str | None]:
    """Decide every waiting entry in grant order, without disk or processes.

    Args:
      entries: the queue's entries, active and waiting.
      free_gb: free disk in GB.
      floor: GB every grant must leave free (thresholds_gb.stop).
      stage: the watch stage: ok, warn, stop or critical.
      silenced: whether a radio-silence mayday holds.
      slot_limits: {kind: max concurrent jobs}.
      ranks: {task: index in the register's ranking}; a task missing there
        ranks after all of them.
      now: epoch seconds; each whole hour waited moves an entry one rank up.

    Returns:
      {entry id: None when granted, else the blocking reason}, in grant order.
      An unblocked entry counts as granted for the entries after it, whoever
      holds it, so a lower entry never takes a higher entry's slot.
    """
    active = [e for e in entries if e["status"] == "active"]
    available = free_gb - sum(e["need_gb"] for e in active)
    counts = Counter(e["kind"] for e in active)
    busy = {e["workdir"] for e in active}
    verdicts: dict[str, str | None] = {}
    for entry in ordered([e for e in entries if e["status"] == "waiting"], ranks, now):
        kind, need, workdir = entry["kind"], entry["need_gb"], entry["workdir"]
        reason = None
        if stage in ("stop", "critical"):
            reason = f"disk stage {stage}"
        elif stage == "warn" and need > 0:
            reason = "disk stage warn admits only jobs that need no disk"
        elif silenced:
            reason = "radio silence"
        elif kind not in slot_limits:
            reason = f"slot_limits has no {kind}"
        elif counts[kind] >= slot_limits[kind]:
            reason = f"all {slot_limits[kind]} {kind} slots taken"
        elif workdir in busy:
            reason = f"{workdir} runs another job"
        elif available - need < floor:
            reason = f"{need:g} GB would cut into the {floor:g} GB floor; reserved"
            available -= need
        else:
            counts[kind] += 1
            busy.add(workdir)
            available -= need
        verdicts[entry["id"]] = reason
    return verdicts


def register_ranks() -> dict[str, int]:
    rasci = sibling("rasci")
    return {task: index for index, task in enumerate(rasci.ranked(rasci.merged(False)))}


def stage(cfg: dict, free_gb: float, now: float) -> str:
    state = watch.read_json(watch.STATE)
    return state["stage"] if "stage" in state else watch.stage_for(free_gb, [], cfg, now)


def silenced(now: float) -> bool:
    state = watch.read_json(SILENCE)
    return "until" in state and state["until"] > now


def decide(cfg: dict, entries: list[dict], free_gb: float, now: float, kinds: dict[str, dict]) -> dict[str, str | None]:
    slots = {kind: limit for kind, (limit, _) in limits(cfg, kinds, entries).items()}
    return evaluate(
        entries, free_gb, cfg["thresholds_gb"]["stop"], stage(cfg, free_gb, now), silenced(now),
        slots, register_ranks(), now,
    )


def load_reason(cfg: dict, kind: str) -> str | None:
    limits = cfg["load_limits"]
    if kind not in limits["kinds"]:
        return None
    cpu, mem = watch.load(cfg)
    if cpu < limits["cpu_percent"] and mem < limits["mem_percent"]:
        return None
    return f"cpu or ram at the limit ({limits['cpu_percent']} %, {limits['mem_percent']} %)"


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


def wait(cfg: dict, entry_id: str, kind: str, caught: list[int]) -> tuple[int | None, int]:
    """Poll until the grant.

    Args:
      cfg: the config.
      entry_id: this hold's entry.
      kind: its kind, for the load sample.
      caught: signals the caller caught; the first ends the wait.

    Returns:
      (None, other active jobs at the grant) once granted, else (the exit
      code, 0).
    """
    shown = None
    while not caught:
        busy_load = load_reason(cfg, kind)
        free, _ = watch.disk(cfg)
        now = time.time()
        _, kinds = learned(cfg, now)
        with store() as data:
            data["entries"] = prune(data["entries"])
            mine = [e for e in data["entries"] if e["id"] == entry_id]
            if not mine:
                print(f"queue: {entry_id} was cancelled", file=sys.stderr)
                return CANCELLED, 0
            verdicts = decide(cfg, data["entries"], free, now, kinds)
            reason = verdicts[entry_id] or busy_load
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
        history.record(watch.HISTORY, row)
    except OSError as error:
        # A full disk refuses the row; the job's exit code must still come through.
        print(f"queue: no history row for {row['id']}: {error.strerror}", file=sys.stderr)


def cmd_hold(args: argparse.Namespace) -> int:
    cfg = config()
    if args.kind not in cfg["slot_need_gb"]:
        fail(f"kind {args.kind!r} is not in slot_need_gb of {watch.CONFIG}")
    rasci = sibling("rasci")
    if args.task not in rasci.merged(False):
        fail(f"{args.task} is no open task of the kvb-org-rasci register")
    if args.hotfix is not None and HOTFIX + args.hotfix not in rasci.load():
        fail(f"the register has no row {HOTFIX}{args.hotfix}")
    signature = history.signature(args.command)
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
    entry = enqueue({
        "kind": args.kind, "task": args.task, "need_gb": need, "hotfix": args.hotfix,
        "workdir": workdir(), "session": session, "name": council.live_sessions().get(session) or session,
        "pid": os.getpid(), "pid_start": identity(os.getpid()), "child": None, "child_start": None,
        "status": "waiting", "enqueued": time.time(), "granted": None, "cmd": shlex.join(args.command),
    })
    try:
        code, concurrent = wait(cfg, entry["id"], args.kind, caught)
        if code is not None:
            return code
        if caught:
            return 128 + caught[0]
        samples = [measure(cfg)]
        start = time.time()
        try:
            child = subprocess.Popen(args.command, start_new_session=True)
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
        keep(history.row(job, start, time.time(), code, samples, concurrent))
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
        verdicts = decide(cfg, entries, free, now, kinds)
    by_id = {e["id"]: e for e in entries}
    running = [(signature_of(e), e["granted"]) for e in entries if e["status"] == "active"]
    rows = [
        ("run", e, history.eta(signatures, [(signature_of(e), e["granted"])], [], now), "-")
        for e in entries if e["status"] == "active"
    ]
    ahead: list[str] = []
    for n, (entry_id, reason) in enumerate(verdicts.items(), 1):
        e = by_id[entry_id]
        rows.append((str(n), e, history.eta(signatures, running, ahead, now), reason or "granted on its next poll"))
        ahead.append(signature_of(e))
    print("position\tid\tstatus\tkind\ttask\tneed_gb\twaited_min\teta_min\tworkdir\treason")
    for position, e, eta, reason in rows:
        waited = ((e["granted"] or now) - e["enqueued"]) / 60
        print("\t".join(
            [position, e["id"], e["status"], e["kind"], e["task"], f"{e['need_gb']:g}", f"{waited:.0f}",
             "-" if eta is None else f"{eta:.0f}", e["workdir"], reason]
        ))
    return 0


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


def cmd_block() -> int:
    payload = json.load(sys.stdin)
    cfg = watch.load_config()
    if cfg is None or cfg.get("queue_enforce") is not True:
        return 0
    command = watch.executable_text((payload.get("tool_input") or {}).get("command") or "")
    if THROUGH_QUEUE.search(command) or any(re.search(p, command) for p in cfg["never_block"]):
        return 0
    if GATE.search(command) or any(re.search(p, command) for p in cfg["heavy_commands"]):
        print(
            f"kvb-org-queue: heavy jobs run through the queue: start `python3 {Path(__file__).resolve()} hold "
            "--kind <kind> --task <register task> -- <command>` in the background; it runs the command on its grant.",
            file=sys.stderr,
        )
        return 2
    return 0


def main() -> int:
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
    args = parser.parse_args()
    if args.cmd == "block":
        try:
            return cmd_block()
        except (OSError, ValueError, KeyError, TypeError, AttributeError, re.error):
            return 0
    commands = {"hold": cmd_hold, "list": cmd_list, "history": cmd_history, "cancel": cmd_cancel}
    return commands[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
