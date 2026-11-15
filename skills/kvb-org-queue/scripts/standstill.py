"""Tell a held command that stands still from one that works, from /proc alone.

queue.py's supervise() asks a Clock at every poll; once the process tree of
the command (tree()) stood still for HUNG_SECONDS, hold signals every member
(members(), signal_all(), settle()) and exits HUNG_EXIT, and list marks an
active job that runs SUSPECT_FACTOR times its longest learned run, at least
SUSPECT_FLOOR_SECONDS, as suspect hung.
"""

from __future__ import annotations

import contextlib
import os
import sys
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import NamedTuple

PROC = Path("/proc")
HUNG_SECONDS = 3600
KILL_GRACE_SECONDS = 30
SETTLE_SECONDS = 0.2
HUNG_EXIT = 124
SUSPECT_FACTOR = 3
SUSPECT_FLOOR_SECONDS = 1800
TRACE_LIMIT = 20
STATE, PARENT, SESSION, START = 0, 1, 3, 19
TIMES = slice(11, 15)
IO_KEYS = (b"rchar", b"wchar", b"read_bytes", b"write_bytes")
PAUSED = frozenset({b"T", b"t"})
GONE = frozenset({b"Z", b"X"})
ELSEWHERE = frozenset({b"docker", b"docker-compose", b"docker-buildx", b"podman", b"podman-compose", b"ssh"})
TICKS = os.sysconf("SC_CLK_TCK")


class Process(NamedTuple):
    pid: int
    comm: bytes
    state: bytes
    parent: int
    session: int
    ticks: int
    start: int


class Sample(NamedTuple):
    members: frozenset[tuple[int, int]]
    ticks: int
    io: tuple[int, ...]
    elsewhere: tuple[bytes, ...]
    paused: bool

    @property
    def held(self) -> bool:
        return bool(self.elsewhere) or self.paused


def parse_stat(data: bytes) -> Process:
    """Args:
        data: the bytes of /proc/<pid>/stat; field 2, the command name in
            parentheses, may hold spaces and parentheses itself, so the
            fields are split after the last `)`.

    Returns:
        The process: pid (field 1), comm (2), state (3), parent (4), session
        (6), utime + stime + cutime + cstime (14 to 17, in clock ticks) and
        start time (22, in clock ticks after boot).
    """
    head, tail = data.rsplit(b")", 1)
    pid, comm = head.split(b"(", 1)
    fields = tail.split()
    return Process(int(pid), comm, fields[STATE], int(fields[PARENT]), int(fields[SESSION]),
                   sum(int(ticks) for ticks in fields[TIMES]), int(fields[START]))


def read(name: str) -> Process | None:
    try:
        return parse_stat((PROC / name / "stat").read_bytes())
    except (OSError, ValueError, IndexError):
        return None


def table() -> dict[int, Process] | None:
    """Returns:
        Every process /proc lists, by pid, skipping one that vanished
        between the listing and the read; None when /proc cannot be listed.
    """
    try:
        names = [name for name in os.listdir(PROC) if name.isdigit()]
    except OSError:
        return None
    return {found.pid: found for found in map(read, names) if found is not None}


def family(processes: dict[int, Process], roots: Iterable[int]) -> set[int]:
    """Returns:
        The roots processes shows and all their descendants, whatever
        session or process group each one moved to.
    """
    children: dict[int, list[int]] = {}
    for process in processes.values():
        children.setdefault(process.parent, []).append(process.pid)
    found: set[int] = set()
    todo = [pid for pid in roots if pid in processes]
    while todo:
        pid = todo.pop()
        if pid not in found:
            found.add(pid)
            todo.extend(children.get(pid, ()))
    return found


def tree(processes: dict[int, Process], root: int) -> list[Process]:
    """Returns:
        root, its descendants (family()) and every process still in the
        session root leads, as an orphan handed to init keeps it.
    """
    session = {process.pid for process in processes.values() if process.session == root}
    return [processes[pid] for pid in family(processes, [root]) | session]


def io_of(pid: int) -> tuple[int, ...]:
    """Returns:
        The IO_KEYS counters of /proc/<pid>/io; zeros when that file cannot
        be read (a setuid member's, or one that vanished after its stat),
        which leaves its CPU time counted.
    """
    try:
        pairs = dict(line.split(b":", 1) for line in (PROC / str(pid) / "io").read_bytes().splitlines())
        return tuple(int(pairs[key]) for key in IO_KEYS)
    except (OSError, ValueError, KeyError):
        return (0,) * len(IO_KEYS)


def wchan_of(pid: int) -> str:
    """Returns:
        The kernel function /proc/<pid>/wchan names as the one the process
        sleeps in; empty while it runs and when that file cannot be read.
    """
    try:
        name = (PROC / str(pid) / "wchan").read_text(encoding="ascii", errors="replace")
    except OSError:
        return ""
    return "" if name == "0" else name


def trace(root: int) -> list[str]:
    """Returns:
        `<pid> <comm> <state> [<wchan>]` of the tree() members of root, the
        ones without a child in the tree first (the stuck one, not the
        ancestors waiting on it), then by pid, at most TRACE_LIMIT; comm with
        control bytes escaped, as a process sets its own. Never a command
        line, which can carry credentials. Empty when /proc cannot be listed
        or does not show root.
    """
    processes = table()
    if processes is None or root not in processes:
        return []
    in_tree = tree(processes, root)
    parents = {process.parent for process in in_tree}
    return [" ".join(filter(None, (str(process.pid), process.comm.decode(errors="replace").encode("unicode_escape").decode(),
                                   process.state.decode(), wchan_of(process.pid))))
            for process in sorted(in_tree, key=lambda process: (process.pid in parents, process.pid))[:TRACE_LIMIT]]


def probe(root: int) -> Sample | None:
    """Args:
        root: the pid of the held command.

    Returns:
        The tree() of root: its members as (pid, start time), their CPU
        ticks and io_of() counters summed, the ELSEWHERE commands among them
        and whether one is stopped or traced; None when /proc cannot be
        listed or does not show root, as a /proc of another PID namespace
        does not.
    """
    processes = table()
    if processes is None or root not in processes:
        return None
    in_tree = tree(processes, root)
    return Sample(
        frozenset((process.pid, process.start) for process in in_tree),
        sum(process.ticks for process in in_tree),
        tuple(map(sum, zip(*(io_of(process.pid) for process in in_tree)))),
        tuple(sorted({process.comm for process in in_tree} & ELSEWHERE)),
        any(process.state in PAUSED for process in in_tree),
    )


def say(text: str) -> None:
    print(f"queue: {text}", file=sys.stderr, flush=True)


class Clock:
    """Clock how long the process tree of a held command stood still.

    Args:
        root: the command's pid.
    """

    def __init__(self, root: int) -> None:
        self.root = root
        self.seen: Sample | None = None
        self.since = time.monotonic()
        self.blind = False
        self.away = False

    def hung(self) -> bool:
        """Returns:
            Whether probe() of the tree gave the same sample for
            HUNG_SECONDS. A probe that sees nothing, a tree running an
            ELSEWHERE client, whose work runs outside the tree, and a tree
            with a stopped or traced member restart the clock and never fire.
        """
        now = time.monotonic()
        seen = probe(self.root)
        self.warn(seen)
        if seen is None or seen.held or seen != self.seen:
            self.since = now
        self.seen = seen
        return seen is not None and not seen.held and now - self.since >= HUNG_SECONDS

    def warn(self, seen: Sample | None) -> None:
        """Args:
            seen: the probe() of this poll; the first None of the run says
                on stderr that the guard is off, the first naming an
                ELSEWHERE client that it holds off.
        """
        if seen is None and not self.blind:
            say(f"/proc does not show process {self.root}; the hung-job guard is off for it")
            self.blind = True
        if seen is not None and seen.elsewhere and not self.away:
            names = ", ".join(name.decode(errors="replace") for name in seen.elsewhere)
            say(f"the command runs {names}, whose work /proc does not show; the hung-job guard holds off while one runs")
            self.away = True

    def report(self) -> dict[str, float | int | list[str]]:
        """Returns:
            The sample of the last hung() that saw the tree, for the history
            row: cpu_s (CPU seconds), read_bytes and written_bytes (rchar and
            wchar), still_min (minutes without a change), members (the
            number of processes) and tree (their trace(), taken now, before
            any signal).
        """
        rchar, wchar = self.seen.io[:2]
        return {"cpu_s": round(self.seen.ticks / TICKS, 2), "read_bytes": rchar, "written_bytes": wchar,
                "still_min": round((time.monotonic() - self.since) / 60, 1), "members": len(self.seen.members),
                "tree": trace(self.root)}


def told(report: dict) -> str:
    return (f"the command's process tree stood still for {report['still_min']:g} min (CPU {report['cpu_s']:g} s, "
            f"{report['read_bytes']} bytes read, {report['written_bytes']} written, all unchanged); "
            f"tree of {report['members']}: {', '.join(report['tree'])}")


def members(root: int) -> dict[int, int]:
    """Returns:
        The tree() of root as {pid: start time}; empty when /proc cannot be
        listed or does not show root.
    """
    processes = table()
    if processes is None or root not in processes:
        return {}
    return {process.pid: process.start for process in tree(processes, root)}


def alive(targets: dict[int, int]) -> dict[int, int]:
    """Args:
        targets: {pid: start time} as members() recorded them, the command
            among them (a zombie still shows in /proc).

    Returns:
        The targets still running with their recorded start time, so a
        reused pid never counts, the members of every session such a target
        or a target gone from /proc leads, as a process a member starts
        during the grace keeps its session when its parent exits (Linux
        keeps a session id allocated while a member lives, so no reused pid
        matches it), and the descendants all of them have now, as
        {pid: start time}; zombies are left out, and nothing when /proc
        cannot be listed.
    """
    processes = table() or {}
    kept = [pid for pid, start in targets.items() if pid in processes and processes[pid].start == start]
    leaders = {pid for pid, start in targets.items() if pid not in processes or processes[pid].start == start}
    kept += [process.pid for process in processes.values() if process.session in leaders]
    return {pid: processes[pid].start for pid in family(processes, kept) if processes[pid].state not in GONE}


def signal_all(targets: dict[int, int], signum: int) -> dict[int, int]:
    """Send signum to every process alive() finds of targets.

    Returns:
        Those processes as {pid: start time}.
    """
    living = alive(targets)
    for pid in living:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.kill(pid, signum)
    return living


def settle(targets: dict[int, int], reap: Callable[[], int | None], signum: int | None) -> dict[int, int]:
    """Wait up to KILL_GRACE_SECONDS until the command is reaped and alive()
    finds none of targets, recording every process it finds on the way, so
    one a member starts in a session of its own during the grace stays a
    target after its parent exits; one started and orphaned between two
    passes, SETTLE_SECONDS and a /proc scan apart, is not seen.

    Args:
        targets: {pid: start time} of the tree.
        reap: Popen.poll of the command, None while it runs.
        signum: sent to everything each pass finds (signal_all()), so a
            process forked while the last pass signalled gets it too; None
            only waits, letting a member's cleanup run out the grace.

    Returns:
        targets and every process found, as {pid: start time}.
    """
    seen = dict(targets)
    deadline = time.monotonic() + KILL_GRACE_SECONDS
    while time.monotonic() < deadline:
        living = alive(seen) if signum is None else signal_all(seen, signum)
        seen |= living
        if reap() is not None and not living:
            break
        time.sleep(SETTLE_SECONDS)
    return seen


def suspect_seconds(longest: float | None) -> float:
    """Args:
        longest: the longest learned run of a job's signature in minutes,
            None while nothing is learned.

    Returns:
        The runtime past which list marks the job suspect hung:
        SUSPECT_FACTOR times longest, at least SUSPECT_FLOOR_SECONDS.
    """
    if longest is None:
        return SUSPECT_FLOOR_SECONDS
    return max(SUSPECT_FLOOR_SECONDS, SUSPECT_FACTOR * longest * 60)
