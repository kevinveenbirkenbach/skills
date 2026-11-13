from __future__ import annotations

import contextlib
import datetime
import errno
import fcntl
import json
import os
import secrets
import shutil
import stat
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import NamedTuple

from passkey import verify_assertion
from signing import (
    Refused,
    checked_approval,
    checked_rule,
    item_hash,
    load_pinned,
    rule_allows,
)

FOLDER = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
FILE = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
READ_LIMIT = 1 << 20


class Trust(NamedTuple):
    approvers: Path
    replay: Path
    origin: str


def pinned(path: Path) -> list[dict]:
    entries = load_pinned(path)
    if not entries:
        raise Refused("no key is pinned")
    return entries


def write_at(folder: int, name: str, data: dict) -> None:
    """Args:
        folder: the open directory the file goes into.
        name: the file's name there; a link of that name is replaced, never
            followed.
        data: written as JSON with mode 0600, by rename.
    """
    temp = f".{name}-{secrets.token_hex(8)}"
    descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=folder)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=1, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, name, src_dir_fd=folder, dst_dir_fd=folder)
    except OSError:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temp, dir_fd=folder)
        raise


def write_private(path: Path, data: dict) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    folder = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        write_at(folder, path.name, data)
    finally:
        os.close(folder)


def read_regular(name: str | Path, dir_fd: int | None) -> bytes:
    """Args:
        name: the file, relative to dir_fd or a path; a link, FIFO or other
            non-regular file raises OSError, so does one over READ_LIMIT bytes.
        dir_fd: the open directory name is relative to, or None.

    Returns:
        The file's bytes.
    """
    fd = os.open(name, FILE, dir_fd=dir_fd)
    with open(fd, "rb") as handle:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError(errno.EINVAL, "not a regular file", str(name))
        data = handle.read(READ_LIMIT + 1)
    if len(data) > READ_LIMIT:
        raise OSError(errno.EFBIG, f"larger than {READ_LIMIT} bytes", str(name))
    return data


def descend(folder: int, part: str, create: bool, follow: bool) -> int:
    """Args:
        folder: an open directory, closed once part is open.
        part: one name in it.
        create: make a missing part with mode 0700.
        follow: follow part when it is a link.

    Returns:
        The open directory part.
    """
    try:
        child = os.open(part, FOLDER, dir_fd=folder)
    except FileNotFoundError:
        if not create:
            raise
        with contextlib.suppress(FileExistsError):
            os.mkdir(part, 0o700, dir_fd=folder)
        child = os.open(part, FOLDER, dir_fd=folder)
    except OSError as error:
        if error.errno not in (errno.ELOOP, errno.ENOTDIR) or not follow:
            raise
        child = os.open(part, FOLDER & ~os.O_NOFOLLOW, dir_fd=folder)
    os.close(folder)
    return child


@contextlib.contextmanager
def private_dir(path: Path, create: bool) -> Iterator[int]:
    """Args:
        path: the directory, opened from / one name at a time by descend();
            a link is followed only by a process other than root, and only
            while every directory entered so far is root's and no one else
            can write it.
        create: make missing directories with mode 0700.

    Returns:
        The open directory, closed on exit.

    Raises:
        Refused unless it is a directory of this effective uid that no one
        else can write, reached without a link descend() did not follow.
    """
    folder = os.open("/", FOLDER)
    rooted = os.geteuid() != 0
    try:
        for part in path.absolute().parts[1:]:
            held = os.fstat(folder)
            rooted = rooted and held.st_uid == 0 and not held.st_mode & 0o022
            folder = descend(folder, part, create, rooted)
        found = os.fstat(folder)
    except OSError as error:
        os.close(folder)
        raise Refused(f"{path}: {error.filename}: {error.strerror or error}") from error
    if found.st_uid != os.geteuid() or found.st_mode & 0o022:
        os.close(folder)
        raise Refused(f"{path} is no directory of uid {os.geteuid()}, or others can write it")
    try:
        yield folder
    finally:
        os.close(folder)


def remove_at(folder: int, name: str) -> None:
    """Args:
        folder: the open directory.
        name: the entry to remove: a real directory with all below it through
            shutil.rmtree, which refuses a link swapped in; anything else as
            the name itself, never what a link names.
    """
    try:
        if stat.S_ISDIR(os.lstat(name, dir_fd=folder).st_mode):
            shutil.rmtree(name, dir_fd=folder)
        else:
            os.unlink(name, dir_fd=folder)
    except FileNotFoundError:
        return


def unreported(folder: int, out: int, name: str, result: dict, error: OSError) -> None:
    """Args:
        folder: the open jobs directory.
        out: the open results directory.
        name: the job whose result could not be written; it moves to
            .<id>.unreported in out, or is removed where that move fails, so
            it never runs again.
        result: its result, printed on stderr as one line.
        error: why the result could not be written.
    """
    kept = f".{Path(name).stem}.unreported"
    print(f"no result for {name}: {error}; the job is kept as {kept} beside the results: {json.dumps(result, sort_keys=True)}", file=sys.stderr)
    try:
        os.rename(name, kept, src_dir_fd=folder, dst_dir_fd=out)
    except OSError:
        try:
            remove_at(folder, name)
        except OSError as stuck:
            print(f"kept {name}: {stuck}", file=sys.stderr)


def drain(jobs: Path, results: Path, run: Callable[[int, str], dict | None]) -> int:
    """Args:
        jobs: the directory the hub writes jobs into.
        results: the directory each result goes to under its job's name;
            made when missing.
        run: called with the open jobs directory and each entry's name, in
            sorted order; returns the entry's result, or None for no job.

    Returns:
        The number of results written. Every entry is removed after its
        result, each write and removal relative to the open directories; a
        result that cannot be written goes to unreported(), a removal that
        fails prints one line on stderr, and the cycle goes on; a refused
        directory changes nothing and prints one line.
    """
    with contextlib.ExitStack() as stack:
        try:
            folder = stack.enter_context(private_dir(jobs, False))
            out = stack.enter_context(private_dir(results, True))
        except Refused as error:
            print(f"refused, nothing done: {error}", file=sys.stderr)
            return 0
        with os.scandir(folder) as entries:
            names = sorted(entry.name for entry in entries)
        handled = 0
        for name in names:
            result = run(folder, name)
            if result is not None:
                try:
                    write_at(out, name, result)
                    handled += 1
                except OSError as error:
                    unreported(folder, out, name, result, error)
                    continue
            try:
                remove_at(folder, name)
            except OSError as error:
                print(f"kept {name}: {error}", file=sys.stderr)
        return handled


def pin(path: Path, entry: dict, now: float) -> list[dict]:
    stamp = datetime.datetime.fromtimestamp(now, datetime.UTC).isoformat(timespec="seconds")
    entries = [old for old in load_pinned(path) if old["id"] != entry["id"]] + [{**entry, "pinned": stamp}]
    write_private(path, {"credentials": entries})
    return entries


def read_store(store: Path) -> dict:
    try:
        data = json.loads(store.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"used": {}, "counts": {}}
    except (OSError, ValueError, RecursionError) as error:
        raise Refused(f"the replay store {store} is unreadable") from error
    counts = data.get("counts") if isinstance(data, dict) else None
    shaped = isinstance(counts, dict) and all(isinstance(last, dict) and isinstance(last.get("count"), int) and isinstance(last.get("nonce"), str) for last in counts.values())
    if not shaped or not isinstance(data.get("used"), dict):
        raise Refused(f"the replay store {store} is malformed")
    return data


def consume(store: Path, key: str, expires: int, credential: str, count: int, nonce: str, now: float) -> None:
    """Args:
        store: the executor's own replay store, outside the hub's reach.
        key: the one-time id, nonce and item hash.
        expires: until when the id must stay known.
        credential: the id of the key that signed.
        count: its signature counter; 0 when the authenticator keeps none.
        nonce: the payload nonce; one bulk signature carries one counter.
        now: the current time in epoch seconds.
    """
    store.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(store.with_name(f"{store.name}.lock"), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        state = read_store(store)
        used = {name: until for name, until in state["used"].items() if isinstance(until, int | float) and until > now}
        if key in used:
            raise Refused("this signature was already used for this item")
        last = state["counts"].get(credential)
        if last is not None and not (count > last["count"] or (count == last["count"] and (count == 0 or nonce == last["nonce"]))):
            raise Refused("the signature counter did not grow: a cloned authenticator or a replay")
        write_private(store, {"used": {**used, key: expires}, "counts": {**state["counts"], credential: {"count": count, "nonce": nonce}}})
    finally:
        os.close(descriptor)


def check(proof: object, item: dict, gate: str, trust: Trust, now: float) -> None:
    """Args:
        proof: {"payload", "assertion"} the Agent Orchestrator relayed for the item.
        item: the executor's own item, built from what it is about to do.
        gate: pass or fail as the executor itself saw it; a rule approves a
            review on pass only.
        trust: the pinned keys, the executor's replay store and the origin.
        now: the current time in epoch seconds.

    Raises:
        Refused with the reason, unless a pinned key signed an unexpired
        approval that lists the item and is used here for the first time, or
        an unexpired rule whose pattern the item matches.
    """
    if not isinstance(proof, dict) or set(proof) != {"payload", "assertion"}:
        raise Refused("no signature")
    payload = proof["payload"]
    if isinstance(payload, dict) and payload.get("kind") == "rule":
        checked_rule(payload, now)
        verify_assertion(proof["assertion"], payload, pinned(trust.approvers), trust.origin)
        if not rule_allows(payload, item, gate, now):
            raise Refused("the signed rule does not match this item")
        return
    checked_approval(payload, now)
    count = verify_assertion(proof["assertion"], payload, pinned(trust.approvers), trust.origin)
    digest = item_hash(item)
    if digest not in payload["items"]:
        raise Refused("the signature does not list this item")
    consume(trust.replay, f"{payload['nonce']}:{digest}", payload["expires"], proof["assertion"]["id"], count, payload["nonce"], now)
