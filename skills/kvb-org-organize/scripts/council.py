#!/usr/bin/env python3
"""Claim, release and list kvb-org-organize offices in the shared council directory.

Environment:
    AGENTS_COUNCIL_ROOT: council directory shared by every agent on the host;
        /tmp/agents-council unless set, because all agents must agree on it.
    CLAUDE_CODE_SESSION_ID: the caller's session, taken over --session; other
        runtimes pass --session.
    PATH: filtered to the directories hookpath.py trusts before git runs.

Exit codes:
    0 done, 2 usage error, 3 office held by a live session,
    4 office held by a dead session (take it over with `takeover`),
    gate: 2 blocks the tool call: an edit without a claim of this session
        below a directory whose .git is a directory holding HEAD or a file
        starting with gitdir:.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime
import errno
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType


def sibling(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"kvb_council_{name}", Path(__file__).resolve().parent / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


nofollow = sibling("nofollow")

ROOT = Path(os.environ.get("AGENTS_COUNCIL_ROOT", "/tmp/agents-council"))
HEARTBEAT_LIMIT = 3600
OFFICE = re.compile(r"^[a-z0-9][a-z0-9._-]*(/[a-z0-9][a-z0-9._-]*)*$")
CLAIM = "claim.json"
CLAIM_MODE = 0o644
WORK_WIDTH = 40
RASCI = Path(__file__).resolve().parents[2] / "kvb-org-rasci" / "scripts" / "rasci.py"


def live_sessions() -> dict[str, str | None]:
    found: dict[str, str | None] = {}
    for path in (Path.home() / ".claude" / "sessions").glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if data.get("sessionId"):
            found[data["sessionId"]] = data.get("name")
    return found


def caller(session: str | None) -> tuple[str, str]:
    env = os.environ.get("CLAUDE_CODE_SESSION_ID")
    if env:
        return env, "claude-code"
    if session:
        return session, "other"
    print("council: no session id; pass --session", file=sys.stderr)
    sys.exit(2)


def office_dir(office: str) -> Path:
    if not OFFICE.match(office):
        print(f"council: invalid office {office!r}", file=sys.stderr)
        sys.exit(2)
    return ROOT / office


def read_claim(path: Path) -> dict | None:
    try:
        claim = json.loads(nofollow.read_text(ROOT, path / CLAIM))
    except (OSError, ValueError, RecursionError):
        return None
    shaped = isinstance(claim, dict) and all(
        isinstance(claim.get(key), kind) for key, kind in (("session", str), ("runtime", str), ("beat", (int, float)))
    )
    return claim if shaped else None


def is_stale(claim: dict | None, live: dict[str, str | None]) -> bool:
    if claim is None:
        return False
    if claim["runtime"] == "claude-code":
        return claim["session"] not in live
    return time.time() - claim["beat"] > HEARTBEAT_LIMIT


def claims() -> list[tuple[str, dict]]:
    found = []
    for path in sorted(ROOT.glob(f"**/{CLAIM}")):
        claim = read_claim(path.parent)
        if claim is not None:
            found.append((path.parent.relative_to(ROOT).as_posix(), claim))
    return found


def write_claim(path: Path, office: str, sid: str, runtime: str, work: str) -> dict:
    claim = {
        "office": office,
        "session": sid,
        "runtime": runtime,
        "name": live_sessions().get(sid),
        "since": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        "beat": time.time(),
        "work": work,
    }
    nofollow.replace(ROOT, path / CLAIM, json.dumps(claim), CLAIM_MODE)
    return claim


def make_office(path: Path) -> bool:
    *dirs, name = nofollow.parts_below(ROOT, path)
    ROOT.mkdir(parents=True, exist_ok=True)
    fd = nofollow.directory(ROOT, tuple(dirs), True)
    try:
        os.mkdir(name, nofollow.DIRECTORY_MODE, dir_fd=fd)
    except FileExistsError:
        return False
    finally:
        os.close(fd)
    return True


def remove_office(path: Path) -> None:
    *dirs, name = nofollow.parts_below(ROOT, path)
    try:
        fd = nofollow.directory(ROOT, tuple(dirs), False)
    except FileNotFoundError:
        return
    try:
        try:
            found = os.lstat(name, dir_fd=fd)
        except FileNotFoundError:
            return
        if not stat.S_ISDIR(found.st_mode):
            raise OSError(errno.ENOTDIR, "the office is no directory", str(path))
        tomb = f"{name}.stale-{os.getpid()}-{time.time_ns()}"
        try:
            os.rename(name, tomb, src_dir_fd=fd, dst_dir_fd=fd)
        except FileNotFoundError:
            return
        shutil.rmtree(tomb, dir_fd=fd)
    finally:
        os.close(fd)


def here() -> dict[str, str | None]:
    # The Agent Orchestrator's office runner claims from / for the successor: / is no task's workdir.
    if os.getcwd() == os.sep:
        return {}
    try:
        head = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True, check=False
        )
    except OSError:
        head = None
    branch = head.stdout.strip() if head and head.returncode == 0 else ""
    return {"workdir": os.getcwd(), "branch": branch if branch not in ("", "HEAD") else None}


def register(office: str, holder: str, status: str, **extra: str | None) -> None:
    if not office.startswith(("work/", "cluster/")):
        return
    try:
        spec = importlib.util.spec_from_file_location("rasci", RASCI)
        rasci = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(rasci)
        rasci.track(office, holder, status, **extra)
    except (OSError, SystemExit) as exc:
        print(f"council: {office} is missing from the rasci register ({exc})", file=sys.stderr)


def cmd_claim(args: argparse.Namespace) -> int:
    sid, runtime = caller(args.session)
    path = office_dir(args.office)
    try:
        created = make_office(path)
    except OSError as error:
        print(f"council: cannot open {args.office}: {error.strerror}", file=sys.stderr)
        return 2
    if not created:
        claim = read_claim(path)
        if claim is not None and claim["session"] == sid:
            claim = write_claim(path, args.office, sid, runtime, args.work)
            register(args.office, claim["name"] or sid, "running", description=args.work, **here())
            print(f"held {args.office}")
            return 0
        print(json.dumps(claim) if claim else f"{args.office}: claim in progress")
        return 4 if is_stale(claim, live_sessions()) else 3
    claim = write_claim(path, args.office, sid, runtime, args.work)
    register(
        args.office,
        claim["name"] or sid,
        "running",
        description=args.work,
        previous=getattr(args, "previous", None),
        **here(),
    )
    print(f"elected {args.office}")
    return 0


def cmd_takeover(args: argparse.Namespace) -> int:
    path = office_dir(args.office)
    claim = read_claim(path)
    if path.exists() and not is_stale(claim, live_sessions()):
        print(json.dumps(claim) if claim else f"{args.office}: claim in progress")
        return 3
    if claim is not None:
        args.previous = claim["name"] or claim["session"]
    # Two successors racing between this check and the rename can both win;
    # kvb-org-organize names exactly one successor per office to keep that window closed.
    try:
        remove_office(path)
    except OSError as error:
        print(f"council: cannot take over {args.office}: {error.strerror}", file=sys.stderr)
        return 2
    return cmd_claim(args)


def cmd_release(args: argparse.Namespace) -> int:
    sid, _ = caller(args.session)
    path = office_dir(args.office)
    claim = read_claim(path)
    if claim is None:
        print(f"{args.office}: not claimed")
        return 0
    if claim["session"] != sid and not is_stale(claim, live_sessions()):
        print(json.dumps(claim))
        return 3
    try:
        remove_office(path)
    except OSError as error:
        print(f"council: cannot release {args.office}: {error.strerror}", file=sys.stderr)
        return 2
    register(args.office, claim["name"] or claim["session"], "done")
    print(f"released {args.office}")
    return 0


def cmd_beat(args: argparse.Namespace) -> int:
    sid, _ = caller(args.session)
    for office, claim in claims():
        if claim["session"] == sid:
            claim["beat"] = time.time()
            with contextlib.suppress(FileNotFoundError):
                nofollow.rewrite(ROOT, ROOT / office / CLAIM, json.dumps(claim), CLAIM_MODE)
    return 0


def short(text: str, width: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= width else text[: width - 1] + "…"


def cmd_list(args: argparse.Namespace) -> int:
    live = live_sessions()
    sid = None
    if args.mine:
        sid, _ = caller(args.session)
    for office, claim in claims():
        if sid is not None and claim["session"] != sid:
            continue
        state = "stale" if is_stale(claim, live) else "live"
        holder = claim["name"] or claim["session"]
        if args.long:
            print(f"{office}\t{holder}\t{claim['since']}\t{state}\t{claim['work']}")
        else:
            print(f"{office}\t{holder}\t{state}\t{short(claim['work'], WORK_WIDTH)}")
    return 0


def is_git_marker(marker: Path) -> bool:
    if marker.is_dir():
        return (marker / "HEAD").is_file()
    # is_file() first: opening a planted FIFO named .git would hang this hook.
    if not marker.is_file():
        return False
    try:
        with marker.open("rb") as handle:
            return handle.read(7) == b"gitdir:"
    except OSError:
        return False


def in_git_worktree(target: Path) -> bool:
    return any(is_git_marker(path / ".git") for path in (target, *target.parents))


def cmd_gate(_: argparse.Namespace) -> int:
    payload = json.load(sys.stdin)
    tool_input = payload.get("tool_input") or {}
    target = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not target or not in_git_worktree(Path(target).resolve()):
        return 0
    if any(claim["session"] == payload.get("session_id") for _, claim in claims()):
        return 0
    script = Path(__file__).resolve()
    print(
        "kvb-org-organize: this session holds no claim, so it may not edit files in a git "
        f"worktree. Claim the work first: python3 {script} claim work/<slug> "
        "--work '<one line>'. Exit 3 or 4 means another agent holds it; read the "
        "kvb-org-organize skill.",
        file=sys.stderr,
    )
    return 2


def main() -> int:
    parser = argparse.ArgumentParser(prog="council")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name, func in (("claim", cmd_claim), ("takeover", cmd_takeover)):
        cmd = sub.add_parser(name)
        cmd.add_argument("office")
        cmd.add_argument("--work", required=True)
        cmd.add_argument("--session")
        cmd.set_defaults(func=func)
    release = sub.add_parser("release")
    release.add_argument("office")
    release.add_argument("--session")
    release.set_defaults(func=cmd_release)
    beat = sub.add_parser("beat")
    beat.add_argument("--session")
    beat.set_defaults(func=cmd_beat)
    listing = sub.add_parser("list")
    listing.add_argument("--mine", action="store_true")
    listing.add_argument("--long", action="store_true")
    listing.add_argument("--session")
    listing.set_defaults(func=cmd_list)
    sub.add_parser("gate").set_defaults(func=cmd_gate)
    args = parser.parse_args()
    os.environ["PATH"] = sibling("hookpath").trusted(os.environ.get("PATH", ""))
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
