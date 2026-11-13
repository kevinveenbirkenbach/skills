#!/usr/bin/env python3
"""Args:
    --port: port of the Agent Orchestrator; the signature's origin is
        http://localhost:<port>.
    --jobs: the directory the hub writes signed settings changes into, e.g.
        ~/.local/state/kvb-orchestrator/firewall/jobs.
    --results: the directory each job's result goes to as <id>.json.
    --view: the file the Firewall reads, e.g.
        ~/.local/state/kvb-orchestrator/firewall/view.json: per listed file
        its path, sha256 and only its permissions and sandbox sections.
    --approvers: the pinned passkeys, e.g. ~/.config/kvb-orchestrator/approvers.json.
    --replay: this writer's replay store, outside the hub's reach, e.g.
        ~/.local/state/kvb-orchestrator-approvals/firewall.json.
    --tree: the tree file `pkgmgr branch tree` writes; the repositories it
        knows name the project settings files.

Returns:
    Exit code 2 without touching anything when CLAUDECODE or
    SANDBOX_RUNTIME is set: it runs only from its unit, never inside an
    agent or its sandbox. Else, as the operator on the host, per item of
    every job in --jobs: verifies the operator's passkey signature over
    file, base and changes with the replay store; refuses a file outside the
    fixed list (~/.claude/settings.json and <repository>/.claude/settings.json
    of every repository the tree file knows), a link or non-directory on its
    path, a file of another uid, a non-regular file and a file whose sha256
    is no longer the signed base; then applies exactly the signed changes to
    the parsed file, keeps every other key, copies the old bytes to
    <file>.before-firewall-<job id> beside it and replaces the file
    atomically, both with the file's mode (0600 for a new file). A refused
    item changes nothing; a failed one keeps the file's content. Writes each
    job's result, removes the job and rewrites --view, all through
    verifier.drain() and verifier.private_dir(): relative to open directory
    descriptors, never through a link, a linked or foreign jobs, results or
    view directory refused with one line on stderr. The exit code is 0.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import secrets
import stat
import sys
import time
from pathlib import Path

import signing
import verifier
from cleanup import tree_facts
from offices import cycle

AGENT_MARKERS = ("CLAUDECODE", "SANDBOX_RUNTIME")
DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
FILE = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
CREATE = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
READ_LIMIT = 1 << 20
NEW_MODE = 0o600
BACKUP = "before-firewall"
OUTSIDE = "an agent or its sandbox runs this: the settings writer runs only from the kvb-orchestrator-firewall unit"
MISSING_DIRECTORY = "no directory: create it first"


def listed(home: Path, tree: Path) -> list[str]:
    """Returns:
        The fixed list of settings files: the operator's own and those of
        every repository the tree file knows.
    """
    own = str(home / ".claude" / "settings.json")
    projects = sorted(f"{repository.rstrip('/')}{signing.SETTINGS_FILE}" for repository in tree_facts(tree)[0])
    return [own, *(path for path in projects if path != own)]


def parent_of(path: str) -> int:
    """Returns:
        The open directory holding path, reached from / without following a
        link on the way; the caller closes it.
    """
    fd = os.open("/", DIRECTORY)
    try:
        for part in Path(path).parent.parts[1:]:
            child = os.open(part, DIRECTORY, dir_fd=fd)
            os.close(fd)
            fd = child
    except BaseException:
        os.close(fd)
        raise
    return fd


def read_settings(parent: int, name: str) -> tuple[bytes | None, os.stat_result | None]:
    """Returns:
        The file's bytes and status, None and None while it is missing.

    Raises:
        signing.Refused for a link, a non-regular file or one over
        READ_LIMIT bytes.
    """
    try:
        fd = os.open(name, FILE, dir_fd=parent)
    except FileNotFoundError:
        return None, None
    except OSError as error:
        raise signing.Refused(f"the file opens only through a link or not at all: {error.strerror}") from None
    with open(fd, "rb") as handle:
        found = os.fstat(fd)
        if not stat.S_ISREG(found.st_mode):
            raise signing.Refused("the file is no regular file")
        data = handle.read(READ_LIMIT + 1)
    if len(data) > READ_LIMIT:
        raise signing.Refused(f"the file is larger than {READ_LIMIT} bytes")
    return data, found


def write_beside(parent: int, name: str, data: bytes, mode: int) -> str:
    """Args:
        parent: the open directory.
        name: the file to replace or create in it.
        data: its new bytes.
        mode: its permission bits.

    Returns:
        "" once the directory is synced, else why its sync failed after the
        file was already replaced.
    """
    temporary = f".{name}.{secrets.token_hex(8)}"
    fd = os.open(temporary, CREATE, mode, dir_fd=parent)
    try:
        with open(fd, "wb") as handle:
            os.fchmod(fd, mode)
            handle.write(data)
            handle.flush()
            os.fsync(fd)
        os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
    except BaseException:
        os.unlink(temporary, dir_fd=parent)
        raise
    try:
        os.fsync(parent)
    except OSError as error:
        return error.strerror or type(error).__name__
    return ""


class Unsafe(ValueError):
    pass


def no_constant(name: str) -> float:
    raise Unsafe(f"the file holds {name}, which JSON readers reject")


def finite(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise Unsafe("the file holds a number beyond the double range, which JSON readers reject")
    return value


def unique(pairs: list[tuple[str, object]]) -> dict:
    found = dict(pairs)
    if len(found) != len(pairs):
        raise Unsafe("the file repeats a key in one object")
    return found


def parsed(data: bytes | None) -> dict:
    """Returns:
        The settings object, {} while the file is missing.

    Raises:
        Unsafe for anything but strict JSON every reader parses alike: no
        NaN, Infinity or overflowing number, no repeated key, no lone
        surrogate, at most signing.DEPTH_LIMIT levels, an object at the top.
        The reason never quotes the file.
    """
    if data is None:
        return {}
    try:
        settings = json.loads(data.decode("utf-8"), parse_constant=no_constant, parse_float=finite, object_pairs_hook=unique)
    except Unsafe:
        raise
    except (ValueError, RecursionError) as error:
        raise Unsafe(f"the file holds no strict JSON: {type(error).__name__}") from None
    problem = signing.plain_problem(settings, 0) if isinstance(settings, dict) else "the file holds no JSON object"
    if problem:
        raise Unsafe(problem)
    return settings


def digest(data: bytes | None) -> str:
    return "" if data is None else hashlib.sha256(data).hexdigest()


def view_of(path: str) -> dict:
    """Returns:
        {"path", "exists", "sha256", "error", "settings"}: settings only the
        permissions and sandbox sections; error why the file was unreadable,
        for anything unforeseen only the exception's class, so one bad path
        never keeps the others or the view from being written.
    """
    entry = {"path": path, "exists": False, "sha256": "", "error": "", "settings": {}}
    try:
        return read_view(path, entry)
    except Exception as error:  # noqa: BLE001
        return {**entry, "error": f"unreadable: {type(error).__name__}"}


def read_view(path: str, entry: dict) -> dict:
    try:
        parent = parent_of(path)
    except FileNotFoundError:
        return {**entry, "error": MISSING_DIRECTORY}
    except OSError as error:
        return {**entry, "error": f"a link or no directory on the path: {error.strerror}"}
    try:
        data, _ = read_settings(parent, Path(path).name)
        return {**entry, "exists": data is not None, "sha256": digest(data), "settings": signing.settings_view(parsed(data))}
    except (OSError, Unsafe, signing.Refused) as error:
        return {**entry, "error": str(error)[:300]}
    finally:
        os.close(parent)


class Writer:
    def __init__(self, trust: verifier.Trust, home: Path, tree: Path) -> None:
        self.trust = trust
        self.home = home
        self.tree = tree

    def view(self) -> dict:
        return {"written": time.time(), "files": [view_of(path) for path in listed(self.home, self.tree)]}

    def apply(self, item: dict, job_id: str) -> dict:
        """Args:
            item: one signed, well-formed settings change.
            job_id: the job's id, part of the backup's name.

        Returns:
            {"backup", "sha256", "unsynced"}: the backup beside the file, ""
            for a file that was missing, the new content's sha256, and why
            the directory sync failed after a replace, "" when it did not.

        Raises:
            signing.Refused or OSError when nothing was written.
        """
        name = Path(item["file"]).name
        try:
            parent = parent_of(item["file"])
        except OSError as error:
            raise signing.Refused(f"a link or no directory on the path: {error.strerror}") from None
        try:
            data, found = read_settings(parent, name)
            if found is not None and found.st_uid != os.getuid():
                raise signing.Refused(f"the file belongs to uid {found.st_uid}, not {os.getuid()}")
            if digest(data) != item["base"]:
                raise signing.Refused("the file changed since the signature")
            text = (json.dumps(signing.apply_changes(parsed(data), item["changes"]), indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
            mode = NEW_MODE if found is None else stat.S_IMODE(found.st_mode)
            backup = unsynced = ""
            if data is not None:
                backup = f"{name}.{BACKUP}-{job_id}"
                unsynced = write_beside(parent, backup, data, mode)
            unsynced = write_beside(parent, name, text, mode) or unsynced
        finally:
            os.close(parent)
        return {"backup": str(Path(item["file"]).with_name(backup)) if backup else "", "sha256": digest(text), "unsynced": unsynced}

    def item(self, item: dict, proof: object, job_id: str, now: float) -> dict:
        """Args:
            item: one well-formed settings change.
            proof: the job's {"payload", "assertion"}.
            job_id: the job's id.
            now: the current time in epoch seconds.

        Returns:
            The item with status done, refused or failed and the reason; a
            refused or failed item wrote nothing, and a failure's reason names
            only its kind, never the file's content.
        """
        try:
            status, reason, written = self.outcome(item, proof, job_id, now)
        except OSError as error:
            status, reason, written = "failed", f"{error.strerror or error}; the file kept its content", {}
        except Exception as error:  # noqa: BLE001
            status, reason, written = "failed", f"{error if isinstance(error, Unsafe) else type(error).__name__}; the file kept its content", {}
        return {**item, "status": status, "reason": reason, **written}

    def outcome(self, item: dict, proof: object, job_id: str, now: float) -> tuple[str, str, dict]:
        try:
            verifier.check(proof, signing.settings_item(item["file"], item["base"], item["changes"]), "", self.trust, now)
        except (signing.Refused, OSError) as error:
            return "refused", f"no valid operator signature: {error}", {}
        if item["file"] not in listed(self.home, self.tree):
            return "refused", "unlisted file: only ~/.claude/settings.json and the .claude/settings.json of a repository pkgmgr knows", {}
        try:
            written = self.apply(item, job_id)
        except signing.Refused as error:
            return "refused", str(error)[:500], {}
        unsynced = written.pop("unsynced")
        return "done", f"written, but its directory sync failed: {unsynced}; the change may not survive a crash" if unsynced else "", written

    def job(self, folder: int, path: Path, now: float) -> dict:
        """Args:
            folder: the open jobs directory, as verifier.drain() passes it.
            path: the job's name in it.
            now: the current time in epoch seconds.

        Returns:
            The job's result; whatever goes wrong in one job fails only that
            job, so the next job and the view still run.
        """
        try:
            return self.checked_job(folder, path, now)
        except Exception as error:  # noqa: BLE001
            return {"id": path.stem, "finished": now, "items": [], "error": f"failed: {type(error).__name__}; nothing changed"}

    def checked_job(self, folder: int, path: Path, now: float) -> dict:
        try:
            job = json.loads(verifier.read_regular(path, folder))
        except (OSError, ValueError, RecursionError) as error:
            return {"id": path.stem, "finished": now, "items": [], "error": f"unreadable job: {error}"}
        items = job.get("items") if isinstance(job, dict) else None
        if not isinstance(items, list) or not items or any(signing.settings_problem(item) for item in items) or job.get("id") != path.stem:
            return {"id": path.stem, "finished": now, "items": [], "error": "malformed job: refused, nothing changed"}
        return {"id": path.stem, "finished": time.time(), "items": [self.item(item, job.get("proof"), path.stem, now) for item in items]}


def main() -> int:
    if any(marker in os.environ for marker in AGENT_MARKERS):
        print(f"settings_writer: refused: {OUTSIDE}", file=sys.stderr)
        return 2
    parser = argparse.ArgumentParser(prog="settings_writer")
    parser.add_argument("--port", type=int, required=True)
    for name in ("--jobs", "--results", "--view", "--approvers", "--replay", "--tree"):
        parser.add_argument(name, type=Path, required=True)
    args = parser.parse_args()
    trust = verifier.Trust(approvers=args.approvers, replay=args.replay, origin=signing.origin_of(args.port))
    writer = Writer(trust, Path.home(), args.tree)
    try:
        cycle(args.jobs, args.results, writer)
    finally:
        write_view(args.view, writer.view())
    return 0


def write_view(path: Path, view: dict) -> None:
    """Args:
        path: the view file, written relative to its directory opened by
            verifier.private_dir(); a linked or foreign spool, or a write
            that fails, prints one line and raises nothing, so an error of
            the cycle before it still surfaces.
        view: Writer.view().
    """
    try:
        with verifier.private_dir(path.parent, True) as folder:
            verifier.write_at(folder, path.name, view)
    except (signing.Refused, OSError) as error:
        print(f"view not written: {error}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
