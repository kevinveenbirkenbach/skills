#!/usr/bin/env python3
"""Args:
    --port: port of the Agent Orchestrator; the signature's origin is
        http://localhost:<port>.
    --jobs: the directory the hub writes signed office orders into, e.g.
        ~/.local/state/kvb-orchestrator/offices/jobs.
    --results: the directory each job's result goes to as <id>.json.
    --approvers: the pinned passkeys, e.g. ~/.config/kvb-orchestrator/approvers.json.
    --replay: this runner's replay store, outside the hub's reach, e.g.
        ~/.local/state/kvb-orchestrator-approvals/offices.json.
    --council: the council directory every agent shares, e.g.
        /tmp/agents-council.
    --script: the installed council.py of the kvb-org-organize skill.

Returns:
    Runs once over every job in --jobs, as the operator on the host: per item
    it verifies the operator's passkey signature over action, office, holder,
    session and work, refuses a council directory others can write and an
    office path holding a link, and checks that the office still has the
    signed holder. A takeover or recall then moves the office aside, reads its
    claim there and removes it only while that claim names the signed holder,
    else it puts the office back; an appoint or takeover ends in a plain
    council.py claim for the successor, run as an argument list, never through
    a shell: a live Claude Code successor goes in as CLAUDE_CODE_SESSION_ID,
    any other as --session. Writes each item's result and removes the job.
    The exit code is 0.
"""

from __future__ import annotations

import argparse
import errno
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

import signing
import verifier

JOB = re.compile(r"[0-9a-f]{16}\.json")
SAFE_PATH = "/usr/local/bin:/usr/bin:/bin"
CLAIM = "claim.json"
CLAIM_SHAPE = (("session", str), ("runtime", str), ("beat", (int, float)))
DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
FILE = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
READ_LIMIT = 1 << 20
OUTPUT_LIMIT = 4000
TIMEOUT = 120


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


def claim_in(office_fd: int) -> dict | None:
    """Returns:
        The claim of the open office directory in the shape council.py
        reads, or None.
    """
    try:
        claim = json.loads(read_regular(CLAIM, office_fd))
    except (OSError, ValueError, RecursionError):
        return None
    shaped = isinstance(claim, dict) and all(isinstance(claim.get(key), kind) for key, kind in CLAIM_SHAPE)
    return claim if shaped else None


def parent_of(council: Path, office: str) -> tuple[int, str]:
    """Returns:
        The open directory holding the office, without following a link on
        the way, and the office's last name; the caller closes it.
    """
    *dirs, name = office.split("/")
    fd = os.open(council, DIRECTORY)
    try:
        for part in dirs:
            child = os.open(part, DIRECTORY, dir_fd=fd)
            os.close(fd)
            fd = child
    except BaseException:
        os.close(fd)
        raise
    return fd, name


def unsafe(council: Path, office: str) -> str | None:
    """Returns:
        Why the council directory or the office's path below it must not be
        used, or None.
    """
    try:
        root = council.lstat()
    except OSError as error:
        return f"the council directory is unreadable: {error.strerror}"
    if not stat.S_ISDIR(root.st_mode) or root.st_uid != os.getuid() or root.st_mode & 0o022:
        return f"{council} is no directory of uid {os.getuid()}, or others can write it"
    path = council
    for part in office.split("/"):
        path = path / part
        try:
            found = path.lstat()
        except FileNotFoundError:
            return None
        if not stat.S_ISDIR(found.st_mode):
            return f"{path} is a link or no directory"
    try:
        found = (path / CLAIM).lstat()
    except FileNotFoundError:
        return None
    return None if stat.S_ISREG(found.st_mode) else f"{path / CLAIM} is a link or no file"


def holder_of(council: Path, office: str) -> str | None:
    """Returns:
        The session holding the office, empty while it is vacant, None while
        its claim is missing, unreadable or not in the shape council.py reads.
    """
    try:
        parent, name = parent_of(council, office)
    except FileNotFoundError:
        return ""
    except OSError:
        return None
    try:
        fd = os.open(name, DIRECTORY, dir_fd=parent)
    except FileNotFoundError:
        return ""
    except OSError:
        return None
    finally:
        os.close(parent)
    try:
        claim = claim_in(fd)
    finally:
        os.close(fd)
    return claim["session"] if claim else None


def vacate(council: Path, office: str, holder: str) -> str | None:
    """Args:
        council: the council directory.
        office: the office to empty.
        holder: the session the operator signed as its holder.

    Returns:
        None once the office is gone, else why nothing changed.
    """
    parent, name = parent_of(council, office)
    try:
        tomb = f"{name}.recalled-{os.getpid()}-{time.time_ns()}"
        try:
            os.rename(name, tomb, src_dir_fd=parent, dst_dir_fd=parent)
        except FileNotFoundError:
            return f"the holder changed since the signature: signed {holder}, now vacant; nothing changed"
        try:
            fd = os.open(tomb, DIRECTORY, dir_fd=parent)
        except OSError:
            claim = None
        else:
            try:
                claim = claim_in(fd)
            finally:
                os.close(fd)
        if claim is not None and claim["session"] == holder:
            shutil.rmtree(tomb, dir_fd=parent)
            return None
        now_held = "unreadable" if claim is None else claim["session"]
        try:
            os.lstat(name, dir_fd=parent)
        except FileNotFoundError:
            # Python has no RENAME_NOREPLACE: rename(2) replaces an empty office a claimant made after the lstat.
            os.rename(tomb, name, src_dir_fd=parent, dst_dir_fd=parent)
            return f"the holder changed since the signature: signed {holder}, now {now_held}; nothing changed"
        kept = council.joinpath(*office.split("/")[:-1], tomb)
        return f"the holder changed since the signature: signed {holder}, now {now_held}; a new claim arrived meanwhile, the old office waits at {kept}"
    finally:
        os.close(parent)


def live(home: Path, session: str) -> bool:
    for path in (home / ".claude" / "sessions").glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("sessionId") == session:
            return True
    return False


class Offices:
    def __init__(self, trust: verifier.Trust, council: Path, script: Path, home: Path) -> None:
        self.trust = trust
        self.council = council
        self.script = script
        self.home = home

    def command(self, item: dict) -> tuple[list[str], dict[str, str]]:
        argv = [sys.executable, "-I", "-B", str(self.script), "claim", item["office"], f"--work={item['work']}"]
        env = {"PATH": SAFE_PATH, "HOME": str(self.home), "AGENTS_COUNCIL_ROOT": str(self.council)}
        if live(self.home, item["session"]):
            return argv, {**env, "CLAUDE_CODE_SESSION_ID": item["session"]}
        return [*argv, f"--session={item['session']}"], env

    def item(self, item: dict, proof: object, now: float) -> dict:
        """Args:
            item: one well-formed office order.
            proof: the job's {"payload", "assertion"}.
            now: the current time in epoch seconds.

        Returns:
            The order with status done, failed or refused, the reason, the
            exit code and the output of council.py; a refused order changed
            nothing.
        """
        def ended(status: str, reason: str, code: int | None, output: str) -> dict:
            return {**item, "status": status, "reason": reason, "code": code, "output": output}

        try:
            verifier.check(proof, signing.office_item(**item), "", self.trust, now)
        except (signing.Refused, OSError) as error:
            return ended("refused", f"no valid operator signature: {error}", None, "")
        reason = unsafe(self.council, item["office"])
        if reason:
            return ended("refused", reason, None, "")
        current = holder_of(self.council, item["office"])
        if current != item["holder"]:
            now_held = "unreadable" if current is None else current or "vacant"
            return ended("refused", f"the holder changed since the signature: signed {item['holder'] or 'vacant'}, now {now_held}", None, "")
        if item["action"] != "appoint":
            try:
                reason = vacate(self.council, item["office"], item["holder"])
            except OSError as error:
                return ended("failed", f"the office could not be emptied: {error.strerror or error}; nothing changed", None, "")
            if reason:
                return ended("refused", reason, None, "")
            if item["action"] == "recall":
                return ended("done", "", None, f"recalled {item['office']} from {item['holder']}")
        argv, env = self.command(item)
        try:
            done = subprocess.run(argv, cwd="/", env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, errors="replace", timeout=TIMEOUT, check=False)
        except (OSError, subprocess.TimeoutExpired) as error:
            return ended("failed", f"{error}; the office is vacant now", 127, "")
        output = (done.stdout + done.stderr)[-OUTPUT_LIMIT:]
        if done.returncode == 0:
            return ended("done", "", 0, output)
        vacant = "; the office is vacant now" if item["action"] == "takeover" else ""
        return ended("failed", f"{output.strip()[-500:]}{vacant}", done.returncode, output)

    def job(self, path: Path, now: float) -> dict:
        try:
            job = json.loads(read_regular(path, None))
        except (OSError, ValueError, RecursionError) as error:
            return {"id": path.stem, "finished": now, "items": [], "error": f"unreadable job: {error}"}
        items = job.get("items") if isinstance(job, dict) else None
        if not isinstance(items, list) or not items or any(signing.office_problem(item) for item in items) or job.get("id") != path.stem:
            return {"id": path.stem, "finished": now, "items": [], "error": "malformed job: refused, nothing changed"}
        results = [self.item(item, job.get("proof"), now) for item in items]
        return {"id": path.stem, "finished": time.time(), "items": results}


def cycle(jobs: Path, results: Path, offices: Offices) -> int:
    handled = 0
    for path in sorted(jobs.iterdir()):
        if JOB.fullmatch(path.name):
            verifier.write_private(results / path.name, offices.job(path, time.time()))
            handled += 1
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)
    return handled


def main() -> int:
    parser = argparse.ArgumentParser(prog="offices")
    parser.add_argument("--port", type=int, required=True)
    for name in ("--jobs", "--results", "--approvers", "--replay", "--council", "--script"):
        parser.add_argument(name, type=Path, required=True)
    args = parser.parse_args()
    trust = verifier.Trust(approvers=args.approvers, replay=args.replay, origin=signing.origin_of(args.port))
    args.results.mkdir(mode=0o700, parents=True, exist_ok=True)
    cycle(args.jobs, args.results, Offices(trust, args.council, args.script, Path.home()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
