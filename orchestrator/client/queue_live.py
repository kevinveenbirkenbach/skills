from __future__ import annotations

import errno
import fcntl
import json
import os
import re
import stat
from collections.abc import Callable
from pathlib import Path

HISTORY = "queue-history.jsonl"
HOLDS = "holds"
HOLD_TAG = re.compile(r"\d+-\d+")
JOB_SUFFIX = re.compile(r"\d+")
READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
REFUSED = frozenset({errno.ELOOP, errno.ENOTDIR})
NO_HISTORY = frozenset({errno.ENOENT, errno.ELOOP, errno.ENOTDIR})


def moment(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float) or not 0 <= value < 1e11:
        return None
    return float(value)


def opened(council: Path, tag: str) -> tuple[int | None, bool]:
    """Returns:
        (descriptor, gone): the descriptor of holds/<tag>.lock, opened as
        queue.py's open_below walks to it, and False; else None and True
        where queue.py's held() finds no lock (a missing directory or file)
        or open_below refuses one (a link or a non-directory on the way),
        None and False where the open fails otherwise.
    """
    try:
        folder = os.open(council / HOLDS, DIRECTORY)
    except FileNotFoundError:
        return None, True
    except OSError as error:
        return None, error.errno in REFUSED
    try:
        return os.open(f"{tag}.lock", READ_FLAGS, dir_fd=folder), False
    except FileNotFoundError:
        return None, True
    except OSError as error:
        return None, error.errno in REFUSED
    finally:
        os.close(folder)


def holder_gone(council: Path, tag: object) -> bool:
    """Args:
        council: the council directory.
        tag: the lock tag of an entry that has one; queue.py's living()
            decides by held(tag) alone then.

    Returns:
        not held(tag) for every lock queue.py's held() decides: True for a
        tag queue.py would not write, a missing lock and a lock a
        non-blocking shared flock gets, False for a held one. A hard-linked
        lock gets the same probe. A link or a non-regular file, which no
        hold can create, is True; a lock that cannot be opened or flocked
        otherwise (EACCES) is False.
    """
    if not isinstance(tag, str) or not HOLD_TAG.fullmatch(tag):
        return True
    fd, gone = opened(council, tag)
    if fd is None:
        return gone
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return True
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
    except OSError:
        return False
    finally:
        os.close(fd)
    return True


def read_history(path: Path) -> list[dict] | None:
    """Args:
        path: a queue-history.jsonl; a missing file, a link or another
            non-regular file reads as no rows.

    Returns:
        The JSON object rows of the whole file, in file order; an undecodable
        byte or a bad line costs that line only. None when the read fails
        otherwise (EACCES, EIO, EMFILE).
    """
    try:
        fd = os.open(path, READ_FLAGS)
    except OSError as error:
        return [] if error.errno in NO_HISTORY else None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return []
        with open(fd, "rb", closefd=False) as handle:
            data = handle.read()
    except OSError:
        return None
    finally:
        os.close(fd)
    rows = []
    for line in data.decode("utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except (ValueError, RecursionError):
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def history_jobs(rows: list[dict]) -> dict[str, list[dict]]:
    """Returns:
        The history rows with a start by entry id, the row id without its
        last dash and digits.
    """
    jobs: dict[str, list[dict]] = {}
    for row in rows:
        entry_id, _, suffix = str(row.get("id", "")).rpartition("-")
        if entry_id and JOB_SUFFIX.fullmatch(suffix) and moment(row.get("start")) is not None:
            jobs.setdefault(entry_id, []).append(row)
    return jobs


def exit_of(row: dict) -> int | None:
    code = row.get("exit")
    return code if isinstance(code, int) and not isinstance(code, bool) else None


def outcome(entry: dict, created: float, gone: bool, jobs: dict[str, list[dict]]) -> tuple[bool, dict | None]:
    """Args:
        entry: a queue.json entry.
        created: its enqueue time.
        gone: holder_gone() of its lock, False without a lock key.
        jobs: history_jobs().

    Returns:
        (kept, outcome): an active entry whose job has a history row started
        after the enqueue is kept with {"state": "ended", "exit", "end"} of
        the newest such row by end; else an active one whose holder is gone
        is kept with {"state": "gone", "exit": None, "end": None}; else any
        other entry whose holder is gone is not kept; else the entry is kept
        live with outcome None.
    """
    active = entry.get("status") == "active"
    ident = entry.get("id")
    rows = [row for row in jobs.get(ident, []) if (moment(row.get("start")) or 0.0) >= created] if active and isinstance(ident, str) else []
    if rows:
        row = max(rows, key=lambda found: moment(found.get("end")) or 0.0)
        return True, {"state": "ended", "exit": exit_of(row), "end": moment(row.get("end"))}
    if gone:
        return active, {"state": "gone", "exit": None, "end": None} if active else None
    return True, None


def settled(council: Path, found: list[tuple[dict, float]], history: Callable[[], list[dict]]) -> list[tuple[dict, float, dict | None]]:
    """Args:
        council: the council directory.
        found: the queue.json entries with their enqueue time.
        history: returns the queue-history.jsonl rows, None for an
            unreadable file; called once, after every hold lock is probed,
            and only while an entry is active.

    Returns:
        Each kept entry with its enqueue time and outcome, as outcome()
        reads it, in the order of found; an entry without a lock key, which
        queue.py's living() judges by pids of other PID namespaces, is never
        gone and ends only by its history row.
    """
    gone = ["lock" in entry and holder_gone(council, entry["lock"]) for entry, _ in found]
    jobs = history_jobs(history() or []) if any(entry.get("status") == "active" for entry, _ in found) else {}
    kept = []
    for (entry, created), dead in zip(found, gone, strict=True):
        keep, result = outcome(entry, created, dead, jobs)
        if keep:
            kept.append((entry, created, result))
    return kept
