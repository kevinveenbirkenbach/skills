#!/usr/bin/env python3
"""Delete the kvb-org-queue jobs whose hold lock no living process holds, announced by a pan-pan and a security.

Usage:
    cleanup.py run --window SECONDS
    cleanup.py status
    cleanup.py request

Environment:
    AGENTS_COUNCIL_ROOT: shared state directory; /tmp/agents-council unless
        set. Agents append their requests to <root>/queue-cleanup.request,
        which kvb-org-queue-cleanup.path watches below /tmp/agents-council
        only. The round lives in ~/.local/state/agents-council, which only
        the host can write, in queue-cleanup.json under queue-cleanup.lock,
        written by run alone.
    CLAUDE_CODE_SESSION_ID: run refuses to start while it is set.

Args:
    run: one round, accountable to the live holder of the council office
        chair; without one it deletes nothing. --window: seconds of each
        window, at least WINDOW_FLOOR (the service passes 900). It refuses
        unless it can write the host state. A job is a waiting or active
        entry with a string id, status, kind and lock; every other entry
        stays and counts as malformed. A job is dead when no line of
        /proc/locks, whatever its type, pid or blocked state, names the
        device and inode of <root>/holds/<lock>.lock and a flock on it
        would not block, or when that file is gone. Nothing is dead while
        /proc/locks cannot be read, holds a line without exactly one device
        and inode, or misses the shared flock the round holds on
        <root>/holds while it reads them; nor is a job whose lock file
        cannot be opened, is no regular file with one link, or changed more
        than CREATED_SECONDS away from the time in its tag.
        Without a dead job it sends nothing. Else a pan-pan names the dead
        jobs and counts the others; the window starts once it is sent and
        ends once both the wall clock and the monotonic clock have run
        --window seconds. A security then names the round's jobs still dead
        and every job held by a living process, and a second window starts
        once it is sent. Each job of the round still queued under the same
        id and lock tag and still dead at the end, judged under the queue
        lock, leaves the queue; nothing is signalled and no stop is written.
        Radio silence on any poll, a gap above DEAD_SECONDS between the
        round's own last beat and the end of a poll's sleep or the moment
        the delete holds the queue lock, a newer round in the host state, or
        radio silence or a vacant or stale chair before the delete ends the
        round at once without deleting; it is recorded stopped. Any other
        error after the claim, a queue store gone invalid included, records
        phase stopped, deletes nothing more, posts one line to the chair and
        exits FAILED. The result goes by post to the chair and into task
        queue-cleanup of the kvb-org-rasci register. Every row it sends
        comes from the station queue-cleanup.
    status: the open round's phase and deadline, then one line per job it
        judged: id, status, kind and delete for a dead one, id and held or
        unclear for the others; without an open round the last result.
    request: append a line to the request file in place, so
        kvb-org-queue-cleanup.path starts a round outside the sandbox;
        refused while a round runs and for SPACING_SECONDS after one ended.

Exit codes:
    0 done, 1 run failed after its claim, 2 usage error, run inside an agent
    session, with a window below WINDOW_FLOOR or without write access to the
    host state, request without the installed path unit, during a round or
    within SPACING_SECONDS after one, a council root that watch.py refuses;
    run: 3 while another round runs.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime
import fcntl
import importlib.util
import json
import os
import re
import sys
import time
from pathlib import Path
from types import ModuleType
from typing import NoReturn, Protocol

SKILLS = Path(__file__).resolve().parents[2]
SELF = Path(__file__).resolve()
STATION = "queue-cleanup"
TASK = "queue-cleanup"
WORKER = "systemd kvb-org-queue-cleanup"
OBJECTIVE = "Delete the queue jobs no living process holds"
WINDOW_FLOOR = 900
POLL_SECONDS = 5
DEAD_SECONDS = 180
SPACING_SECONDS = 1800
CREATED_SECONDS = 10
NAMES_SHOWN = 6
NAME_WIDTH = 32
OPEN = ("need", "warn")
ENDED = ("done", "stopped")
STATUSES = ("waiting", "active")
DEAD, HELD, UNCLEAR = "dead", "held", "unclear"
GONE = "gone"
RUNNING = 3
FAILED = 1
PROC = Path("/proc")
DEVICE = re.compile(r"(?<!\S)([0-9a-f]+):([0-9a-f]+):(\d+)(?!\S)")
UNIT = Path.home() / ".config" / "systemd" / "user" / "kvb-org-queue-cleanup.path"


class Clock(Protocol):
    def time(self) -> float: ...

    def monotonic(self) -> float: ...

    def sleep(self, seconds: float) -> None: ...


class Superseded(Exception):
    pass


def script(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"kvb_queue_cleanup_{name}", path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


queue = script("queue", SKILLS / "kvb-org-queue" / "scripts" / "queue.py")
radio = script("radio", SKILLS / "kvb-org-radio" / "scripts" / "radio.py")
rasci = script("rasci", SKILLS / "kvb-org-rasci" / "scripts" / "rasci.py")
watch, nofollow = queue.watch, queue.nofollow
REQUEST = watch.ROOT / "queue-cleanup.request"
STATE = watch.KEPT / "queue-cleanup.json"
STATE_LOCK = watch.KEPT / "queue-cleanup.lock"


def fail(message: str) -> NoReturn:
    print(f"queue-cleanup: {message}", file=sys.stderr)
    sys.exit(2)


def council() -> ModuleType:
    return radio.council()


def host_state() -> dict:
    try:
        data = json.loads(nofollow.read_text(watch.KEPT, STATE))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save(state: dict) -> None:
    nofollow.replace(watch.KEPT, STATE, json.dumps(state, indent=1), 0o600)


def publish(state: dict) -> None:
    with nofollow.locked(watch.KEPT, STATE_LOCK, 0o600, None):
        if host_state().get("start") != state["start"]:
            raise Superseded
        save(state)


def alive(state: dict, now: float) -> bool:
    return state.get("phase") in OPEN and now - state["beat"] <= DEAD_SECONDS


def busy(state: dict, now: float) -> bool:
    return "beat" in state and state["phase"] not in ENDED and now - state["beat"] <= DEAD_SECONDS


def stalled(state: dict, now: float) -> str | None:
    gap = now - state["beat"]
    return f"the round stalled for {gap:.0f} s" if gap > DEAD_SECONDS else None


def top_chair() -> tuple[str | None, str]:
    """Returns:
        (session, name) of the live holder of the council office chair, else
        (None, why no one is accountable).
    """
    claim = council().read_claim(council().ROOT / "chair")
    if claim is None:
        return None, "the council office chair is vacant"
    if council().is_stale(claim, council().live_sessions()):
        return None, f"the chair {radio.clip(claim.get('name') or claim['session'])} is stale"
    return claim["session"], radio.name_of(claim["session"])


def hushed() -> str | None:
    active = radio.silence()
    return None if active is None else f"radio silence by {radio.clip(active.get('by'))} holds"


def tagged(tag: object) -> bool:
    return isinstance(tag, str) and bool(queue.TAG.fullmatch(tag))


def key(info: os.stat_result) -> tuple[int, int, int]:
    return os.major(info.st_dev), os.minor(info.st_dev), info.st_ino


def lock_lines(root: Path) -> set[tuple[int, int, int]] | None:
    """Returns:
        The (device major, minor, inode) of every line of locks below root,
        a /proc; None where it cannot be read or a line names not exactly one.
    """
    try:
        lines = (root / "locks").read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError):
        return None
    found = [DEVICE.findall(line) for line in lines]
    if any(len(names) != 1 for names in found):
        return None
    return {(int(major, 16), int(minor, 16), int(inode)) for [(major, minor, inode)] in found}


def holders() -> set[tuple[int, int, int]] | None:
    """Returns:
        lock_lines of PROC, read under a shared flock of this process on
        <root>/holds; None unless they show that flock.
    """
    try:
        fd = nofollow.directory(watch.ROOT, nofollow.parts_below(watch.ROOT, queue.HOLDS), False)
    except OSError:
        return None
    try:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        found = lock_lines(PROC)
        return found if found is not None and key(os.fstat(fd)) in found else None
    except OSError:
        return None
    finally:
        os.close(fd)


def lock_file(tag: object) -> tuple[int, int, int] | str | None:
    """Returns:
        HELD where a flock on the lock file of tag would block, GONE where it
        is missing, else its key; None for no lock tag or a file that cannot
        be opened, is no regular file with one link or changed more than
        CREATED_SECONDS away from its tag's time.
    """
    if not tagged(tag):
        return None
    try:
        fd = nofollow.open_below(watch.ROOT, queue.HOLDS / f"{tag}.lock", os.O_RDONLY, 0)
    except FileNotFoundError:
        return GONE
    except OSError:
        return None
    try:
        info = os.fstat(fd)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return HELD
    except OSError:
        return None
    finally:
        os.close(fd)
    made = abs(info.st_ctime_ns - int(tag.split("-")[1])) <= CREATED_SECONDS * 1_000_000_000
    return key(info) if made else None


def judge(jobs: list[dict]) -> dict[str, list[dict]]:
    """Returns:
        The jobs by verdict: DEAD, HELD or UNCLEAR.
    """
    files = {job["lock"]: lock_file(job["lock"]) for job in jobs}
    found = holders()
    groups: dict[str, list[dict]] = {DEAD: [], HELD: [], UNCLEAR: []}
    for job in jobs:
        name = files[job["lock"]]
        if name == HELD or (found is not None and name in found):
            groups[HELD].append(job)
        else:
            groups[UNCLEAR if found is None or name is None else DEAD].append(job)
    return groups


def sound(entry: object) -> bool:
    return (isinstance(entry, dict) and all(isinstance(entry.get(field), str) for field in ("id", "status", "kind", "lock"))
            and entry["status"] in STATUSES)


def snapshot() -> tuple[dict[str, list[dict]], int]:
    """Returns:
        (the jobs of the queue by verdict, the number of malformed entries).
    """
    with queue.store() as data:
        jobs = [entry for entry in data["entries"] if sound(entry)]
        groups = judge(jobs)
    return groups, len(data["entries"]) - len(jobs)


def idents(entries: list[dict]) -> list[str]:
    return [entry["id"] for entry in entries]


def standing(state: dict) -> list[dict]:
    """Returns:
        The round's jobs still queued under their lock tag and dead; state
        takes the ids of the queue's held and unclear jobs.
    """
    groups, _ = snapshot()
    state.update(held=idents(groups[HELD]), unclear=idents(groups[UNCLEAR]))
    dead = pairs(groups[DEAD])
    return [job for job in state["jobs"] if (job["id"], job["lock"]) in dead]


def host_writable() -> bool:
    try:
        watch.KEPT.mkdir(mode=0o700, parents=True, exist_ok=True)
        with nofollow.locked(watch.KEPT, STATE_LOCK, 0o600, None):
            return True
    except OSError:
        return False


def pairs(jobs: list[dict]) -> set[tuple[str, str]]:
    return {(job["id"], job["lock"]) for job in jobs}


def cancel(state: dict, doomed: list[dict], clock: Clock) -> dict[str, list[str]] | str:
    """Returns:
        The stall found once the queue lock is held, and nothing deleted;
        else the ids of the round's jobs still queued under the same lock tag
        by outcome: deleted (dead and among doomed, out of the queue), else
        left alone.
    """
    named, chosen = pairs(state["jobs"]), pairs(doomed)
    with queue.store() as data:
        problem = stalled(state, clock.time())
        if problem is not None:
            return problem
        publish(state)
        mine = [entry for entry in data["entries"] if sound(entry) and (entry["id"], entry["lock"]) in named]
        groups = judge(mine)
        gone = [entry for entry in groups[DEAD] if (entry["id"], entry["lock"]) in chosen]
        data["entries"] = [entry for entry in data["entries"] if entry not in gone]
    return outcome(groups, gone)


def outcome(groups: dict[str, list[dict]], gone: list[dict]) -> dict[str, list[str]]:
    found = {"deleted": idents(gone), "held by a living process, not deleted": idents(groups[HELD]),
             "unclear, not deleted": idents(groups[UNCLEAR]),
             "not deleted, alive at the security": [entry["id"] for entry in groups[DEAD] if entry not in gone]}
    return {word: ids for word, ids in found.items() if ids or word == "deleted"}


def send(cls: str, to: list[str], text: str) -> None:
    radio.transmit(cls, to, text, STATION, [])


def capped(ids: list[str]) -> str:
    hidden = len(ids) - NAMES_SHOWN
    shown = ", ".join(council().short(radio.clip(i), NAME_WIDTH) for i in ids[:NAMES_SHOWN])
    return (shown or "none") + (f", +{hidden} more" if hidden > 0 else "")


def head(state: dict) -> str:
    return f"queue cleanup {state['round']}, chair {council().short(radio.clip(state['chair']), NAME_WIDTH)}"


def unclear(state: dict) -> str:
    return f"; unclear, not deleted: {capped(state['unclear'])}" if state["unclear"] else ""


def ask(state: dict) -> str:
    odd = f", {state['malformed']} malformed entries" if state["malformed"] else ""
    return (
        f"{head(state)}: no living process holds the lock of {len(state['jobs'])} queue jobs: {capped(idents(state['jobs']))}. "
        f"A security at {radio.clock(state['deadline'])} names those still dead, deleted {state['window'] / 60:g} min after it; "
        f"nothing is signalled. {len(state['held'])} held and {len(state['unclear'])} unclear jobs{odd} stay; "
        f"python3 {SELF} status lists them."
    )


def warn(state: dict) -> str:
    return (
        f"{head(state)}: still no living lock holder, deleted at {radio.clock(state['deadline'])}: {capped(state['delete'])}; "
        f"held by a living process, not deleted: {capped(state['held'])}{unclear(state)}."
    )


ALARMS = {"need": ("pan-pan", ask), "warn": ("security", warn)}


def alarm(state: dict, phase: str, clock: Clock) -> str | None:
    """Args:
        state: the round; its deadline moves to the window's end.
        phase: need (pan-pan) or warn (security).
        clock: time, monotonic and sleep.

    Returns:
        Why the round must stop (radio silence or a stall on a poll), else
        None once the window has run on both clocks.
    """
    cls, text = ALARMS[phase]
    window = state["window"]
    state.update(phase=phase, deadline=clock.time() + window, beat=clock.time())
    publish(state)
    send(cls, [], text(state))
    wall, mono = clock.time(), clock.monotonic()
    state.update(deadline=wall + window, beat=wall)
    publish(state)
    while True:
        problem = hushed()
        left = max(wall + window - clock.time(), mono + window - clock.monotonic())
        if problem is not None or left <= 0:
            return problem
        clock.sleep(min(POLL_SECONDS, left))
        problem = stalled(state, clock.time())
        if problem is not None:
            return problem
        state["beat"] = clock.time()
        publish(state)


def stamp(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts, datetime.UTC).isoformat(timespec="seconds")


def register(state: dict, status: str) -> None:
    try:
        with rasci.database() as tasks:
            entry = tasks.setdefault(TASK, {"roles": {}})
            entry.update(
                objective=OBJECTIVE, description=state["result"], worker=WORKER, status=status,
                roles={state["chair"]: "A", WORKER: "R"}, start=stamp(state["start"]), end=stamp(state["end"]),
            )
    except (OSError, SystemExit) as error:
        print(f"queue-cleanup: the round is missing from the rasci register ({error})", file=sys.stderr)


def listed(ids: list[str]) -> str:
    return ", ".join(ids) if ids else "none"


def finish(state: dict, named: dict[str, list[str]], status: str) -> int:
    handled = {job_id for ids in named.values() for job_id in ids}
    outcome = {**named, "left the queue": [job["id"] for job in state["jobs"] if job["id"] not in handled]}
    result = f"queue cleanup {state['round']}: " + "; ".join(f"{word} {listed(ids)}" for word, ids in outcome.items())
    state.update(phase="done", result=result, end=time.time())
    publish(state)
    counts = "; ".join(f"{word} {len(ids)}" for word, ids in outcome.items())
    send("post", [state["chair"]], f"queue cleanup {state['round']}: {counts}; python3 {SELF} status lists the ids")
    register(state, status)
    print(result)
    return 0


def halt(state: dict, problem: str) -> int:
    return finish(state, {f"not deleted, {problem}": idents(state["jobs"])}, "stopped")


def abort(state: dict, error: BaseException) -> int:
    why = f"queue cleanup {state['round']}: the round failed ({type(error).__name__}); nothing more is deleted"
    state.update(phase="stopped", result=why, end=time.time())
    with contextlib.suppress(Exception):
        publish(state)
    with contextlib.suppress(Exception):
        send("post", [state["chair"]], why)
    with contextlib.suppress(Exception):
        register(state, "stopped")
    print(f"queue-cleanup: {why}: {error!r}", file=sys.stderr)
    return FAILED


def claim(state: dict) -> bool:
    with nofollow.locked(watch.KEPT, STATE_LOCK, 0o600, None):
        if busy(host_state(), state["start"]):
            return False
        save(state)
    return True


def run_round(window: float, clock: Clock) -> int:
    """Args:
        window: seconds each of the two windows lasts.
        clock: time, monotonic and sleep; the time module outside tests.

    Returns:
        The exit code.
    """
    session, chair = top_chair()
    if session is None:
        print(f"queue-cleanup: {chair}; no one is accountable, nothing is deleted")
        return 0
    groups, malformed = snapshot()
    if not groups[DEAD]:
        print(f"queue-cleanup: no queue job without a living lock holder ({len(groups[HELD])} held, "
              f"{len(groups[UNCLEAR])} unclear, {malformed} malformed); nothing sent")
        return 0
    now = clock.time()
    state = {
        "round": radio.clock(now), "start": now, "beat": now, "phase": "need", "deadline": now + window,
        "window": window, "chair": chair, "malformed": malformed, "held": idents(groups[HELD]),
        "unclear": idents(groups[UNCLEAR]),
        "jobs": [{field: job[field] for field in ("id", "lock", "status", "kind")} for job in groups[DEAD]],
    }
    if not claim(state):
        print("queue-cleanup: another round runs; status shows it", file=sys.stderr)
        return RUNNING
    try:
        return proceed(state, clock)
    except Superseded:
        print("queue-cleanup: a newer round took over this one; nothing more is deleted", file=sys.stderr)
        return 0
    except (Exception, SystemExit) as error:  # noqa: BLE001
        return abort(state, error)


def proceed(state: dict, clock: Clock) -> int:
    problem = hushed()
    if problem is None:
        problem = alarm(state, "need", clock)
    if problem is not None:
        return halt(state, problem)
    state.update(phase="warn", beat=clock.time())
    publish(state)
    doomed = standing(state)
    if not doomed:
        return close(state, doomed, clock)
    state["delete"] = idents(doomed)
    problem = alarm(state, "warn", clock)
    if problem is not None:
        return halt(state, problem)
    state.update(phase="closing", beat=clock.time())
    publish(state)
    return close(state, doomed, clock)


def close(state: dict, doomed: list[dict], clock: Clock) -> int:
    session, chair = top_chair()
    if session is not None:
        state["chair"] = chair
    problem = chair if session is None else hushed() or stalled(state, clock.time())
    if problem is not None and doomed:
        return halt(state, problem)
    found = cancel(state, doomed, clock)
    return halt(state, found) if isinstance(found, str) else finish(state, found, "done")


def cmd_status(_: argparse.Namespace) -> int:
    state = host_state()
    if not alive(state, time.time()):
        print(f"no open round; last: {state['result']}" if "result" in state else "no open round")
        return 0
    print(f"round {state['round']} {state['phase']} until {radio.clock(state['deadline'])}")
    for job in state["jobs"]:
        print(f"{job['id']} {job['status']} {job['kind']} delete")
    for verdict in (HELD, UNCLEAR):
        for job_id in state[verdict]:
            print(f"{job_id} {verdict}")
    return 0


def cmd_request(_: argparse.Namespace) -> int:
    if not UNIT.is_file():
        fail(f"{UNIT} is missing, so no round would start; make install enables it")
    state, now = host_state(), time.time()
    if busy(state, now):
        fail(f"round {state['round']} runs; status shows it")
    if "end" in state and now - state["end"] < SPACING_SECONDS:
        fail(f"the last round ended at {radio.clock(state['end'])}; request again from {radio.clock(state['end'] + SPACING_SECONDS)}")
    nofollow.append(watch.ROOT, REQUEST, f"{now}\n", 0o600)
    print(f"requested a queue-cleanup round through {REQUEST}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    if os.environ.get("CLAUDE_CODE_SESSION_ID"):
        fail("run starts from kvb-org-queue-cleanup.service, never in an agent session; agents use request")
    if args.window < WINDOW_FLOOR:
        fail(f"--window must be at least {WINDOW_FLOOR} seconds")
    if not host_writable():
        fail(f"cannot write {watch.KEPT}; run starts outside the sandbox only")
    return run_round(args.window, time)


def cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run")
    run.add_argument("--window", type=float, required=True)
    sub.add_parser("status")
    sub.add_parser("request")
    return parser


def main(argv: list[str]) -> int:
    args = cli().parse_args(argv)
    refused = watch.guard_root(hook=False)
    if refused is not None:
        return refused
    return {"run": cmd_run, "status": cmd_status, "request": cmd_request}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
