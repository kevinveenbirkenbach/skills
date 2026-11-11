#!/usr/bin/env python3
"""List, run and check a project's `make test*` targets against the current HEAD.

Args:
    list --repo <dir> [--json]: the Makefile targets named `test` or `test-*`,
        parsed statically from the Makefile make reads in <dir> and every file
        it includes; make is never run.
    status --repo <dir> [--json]: per listed target green, red or missing for
        HEAD, from `kvb-gate.json` in the git common dir, or excluded when the
        list gate_excluded_targets in CONFIG names it; an excluded target never
        keeps the gate open, excluding every target does. CONFIG is
        .claude/agents-council/config.json in the passwd home of the account
        running gate.py, never $HOME. `hotfix.py pending --target <t> ...`
        of the kvb-git-hotfix skill, given the other listed targets, keeps the
        gate open while a merged hotfix that turns one of them green is
        missing from HEAD.
    run --repo <dir> --target <t> [--target ...] --log-dir <dir>
        [--fail-regex <re> ...]: under the worktree lock, run each target as
        `make -C <dir> <t>` with stdout and stderr in
        <log-dir>/gate-<t>-<sha8>.log and record the result for HEAD. A
        target is red on a non-zero exit, a `make: ***` line, a matching
        --fail-regex, or tracked files it modified. Before each target,
        `hotfix.py void` decides over it and every target after it whether a
        merged hotfix missing from HEAD voids the run.
    hold --repo <dir> -- <command...>: under the worktree lock, run the
        command in <dir> in a session of its own, without a controlling
        terminal; SIGINT, SIGTERM and SIGHUP reaching hold go to the
        command's process group while hold keeps waiting for it. For deploys
        and every other heavy command that is no `make test*` target.

    The worktree lock is `kvb-gate-run.lock` in the worktree's git dir,
    taken without waiting and passed to make or the command, so it stays
    held while they or a process they left running on this host live; a
    process inside a container (`docker compose exec`) runs on there after
    they die, and the lock no longer covers it. run and hold write their PID
    and command into it, and a busy message names them. `hotfix.py sync`
    takes `kvb-gate-sync.lock` exclusively, recording its PID and command
    there, then the worktree lock, and releases them in reverse order; run
    and hold take the worktree lock while holding `kvb-gate-sync.lock`
    shared, so they wait for a running sync, naming it, for at most
    SYNC_WAIT_SECONDS, and a busy worktree lock then means another run or
    hold.

    Without hotfix.py next to this skill, or when it exits non-zero without
    a verdict line, gate.py warns on stderr and goes on without the hotfix
    check.

Output:
    list: one `<target>\t<file>:<line>` per target.
    status: one `<status>\t<target>\t<log>\t<finished>\t<reason>` per target,
        then `gate: green`, `gate: green (excluded: <target>, ... by
        <CONFIG>)`, or `gate: open (...)` naming what is missing,
        `missing hotfix: <slug>, ...` included.
    run: one `<status>\t<target>\t<log>\t<reason>` per target; on a void
        `void: merge main for hotfix <slug>, then rerun`.
    hold: the command's own output.
    --json prints the same data as JSON.

Exit codes:
    list: 0 done, 2 usage error.
    status: 0 gate green, 1 gate open, 2 usage error.
    run: 0 every target green, 1 a target red, 2 usage error, an excluded
        target, dirty tracked files or HEAD moved during a run, 3 void: the remaining targets are
        neither run nor recorded, 75 (EX_TEMPFAIL) busy: another run or hold
        holds the worktree, or a sync still holds it after SYNC_WAIT_SECONDS.
    hold: the command's exit code unchanged, 128+N when signal N ended it;
        before the command started 2 on a usage error, 75 busy as for run,
        128+N when signal N reached hold.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import glob
import json
import os
import pwd
import re
import shlex
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn, TextIO

MAKEFILES = ("GNUmakefile", "makefile", "Makefile")
INCLUDE = re.compile(r"^\s*(?P<kind>-include|sinclude|include)\s+(?P<paths>.+)$")
DEFINE = re.compile(r"^\s*(?:(?:export|override|private)\s+)*define\b")
ENDEF = re.compile(r"^\s*endef\b")
CONDITIONAL = re.compile(r"^\s*(?:ifeq|ifneq|ifdef|ifndef|else|endif)\b")
ASSIGNMENT = re.compile(
    r"^\s*(?:(?:export|override|private|unexport)\s+)*[^\s:#=]+\s*(?::{1,3}=|[?+!]?=)"
)
COMMENT = re.compile(r"(?<!\\)#.*$")
MAKE_ERROR = re.compile(r"\bmake(?:\[\d+\])?: \*\*\*")
UNSAFE = re.compile(r"[^\w.-]")
LINE_CHARS = 300
STATE = "kvb-gate.json"
RUN_LOCK = "kvb-gate-run.lock"
SYNC_LOCK = "kvb-gate-sync.lock"
SYNC_WAIT_SECONDS = 300
POLL_SECONDS = 0.1
BUSY = os.EX_TEMPFAIL
FORWARDED = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
HOTFIX = Path(__file__).resolve().parents[2] / "kvb-git-hotfix" / "scripts" / "hotfix.py"
CONFIG = Path(pwd.getpwuid(os.getuid()).pw_dir) / ".claude" / "agents-council" / "config.json"
EXCLUDED = "gate_excluded_targets"


def fail(message: str) -> NoReturn:
    print(f"gate: {message}", file=sys.stderr)
    sys.exit(2)


def busy(message: str) -> NoReturn:
    print(f"gate: {message}", file=sys.stderr)
    sys.exit(BUSY)


def logical_lines(path: Path) -> list[tuple[int, str]]:
    lines: list[tuple[int, str]] = []
    start, buffer = 0, ""
    for number, raw in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if not buffer:
            start = number
        if (len(raw) - len(raw.rstrip("\\"))) % 2:
            buffer += raw[:-1] + " "
            continue
        lines.append((start, buffer + raw))
        buffer = ""
    if buffer:
        lines.append((start, buffer))
    return lines


def rule_head(line: str) -> tuple[str, str] | None:
    depth = 0
    for index, char in enumerate(line):
        if char in "({":
            depth += 1
        elif char in ")}":
            depth = max(depth - 1, 0)
        elif depth == 0 and char == "=":
            return None
        elif depth == 0 and char == ":":
            rest = line[index:]
            if re.match(r":{1,3}=", rest):
                return None
            width = 2 if rest.startswith("::") else 1
            return line[:index].rstrip("&"), line[index + width:]
    return None


def is_test(name: str) -> bool:
    return name == "test" or (name.startswith("test-") and "%" not in name)


def parse(path: Path, repo: Path, found: dict, seen: set) -> None:
    resolved = path.resolve()
    if resolved in seen:
        return
    seen.add(resolved)
    shown = os.path.relpath(resolved, repo)
    define_depth = 0
    for number, line in logical_lines(path):
        if define_depth:
            if DEFINE.match(line):
                define_depth += 1
            elif ENDEF.match(line):
                define_depth -= 1
            continue
        if line.startswith("\t"):
            continue
        if DEFINE.match(line):
            define_depth = 1
            continue
        line = COMMENT.sub("", line)
        if not line.strip() or CONDITIONAL.match(line):
            continue
        include = INCLUDE.match(line)
        if include:
            for word in include.group("paths").split():
                if "$" in word:
                    print(f"gate: {shown}:{number}: include {word} not resolved", file=sys.stderr)
                    continue
                matches = sorted(glob.glob(str(repo / os.path.expanduser(word))))
                if not matches and include.group("kind") == "include":
                    print(f"gate: {shown}:{number}: include {word} not found", file=sys.stderr)
                for match in matches:
                    parse(Path(match), repo, found, seen)
            continue
        if ASSIGNMENT.match(line):
            continue
        head = rule_head(line)
        if head is None or ASSIGNMENT.match(head[1]):
            continue
        for name in head[0].split():
            if "$" in name:
                print(f"gate: {shown}:{number}: target {name} not resolved", file=sys.stderr)
            elif is_test(name) and name not in found:
                found[name] = f"{shown}:{number}"


def targets(repo: Path) -> dict[str, str]:
    makefile = next((repo / n for n in MAKEFILES if (repo / n).is_file()), None)
    if makefile is None:
        fail(f"{repo} has no {', '.join(MAKEFILES)}")
    found: dict[str, str] = {}
    parse(makefile, repo, found, set())
    return dict(sorted(found.items()))


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        fail(f"git {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout


def head(repo: Path) -> str:
    return git(repo, "rev-parse", "--verify", "HEAD^{commit}").strip()


def tree(repo: Path) -> tuple[list[str], list[str]]:
    dirty, untracked = [], []
    for line in git(repo, "status", "--porcelain=v1", "--untracked-files=all").splitlines():
        (untracked if line.startswith("??") else dirty).append(line[3:])
    return dirty, untracked


def state_path(repo: Path) -> Path:
    return Path(git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()) / STATE


def load(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        fail(f"{path} is not valid JSON; move it aside to start over")
    if not isinstance(data, dict):
        fail(f"{path} holds no object; move it aside to start over")
    return data


def record(path: Path, sha: str, target: str, entry: dict) -> None:
    # Linked worktrees share the git common dir, so parallel runs write this file.
    with open(path.with_name(f"{STATE}.lock"), "w", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = load(path)
        data.setdefault(sha, {})[target] = entry
        handle, temp = tempfile.mkstemp(dir=path.parent, prefix=f".{STATE}.")
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            json.dump(data, out, indent=1, sort_keys=True)
            out.write("\n")
        os.replace(temp, path)


def first_failure(log: Path, checks: list[re.Pattern]) -> str | None:
    with open(log, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if MAKE_ERROR.search(line) or any(check.search(line) for check in checks):
                return line.strip()[:LINE_CHARS]
    return None


def hotfix_checks() -> bool:
    if HOTFIX.is_file():
        return True
    print(f"gate: {HOTFIX} is missing; merged hotfixes are not checked", file=sys.stderr)
    return False


def hotfix(repo: Path, command: str, args: list[str], verdict: str) -> list[str]:
    result = subprocess.run(
        [sys.executable, str(HOTFIX), command, *args, "--repo", str(repo)],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False,
    )
    sys.stderr.write(result.stderr)
    slugs = [
        line.split("\t")[1].removeprefix("hotfix/")
        for line in result.stdout.splitlines() if line.startswith(f"{verdict}\t")
    ]
    if result.returncode and not slugs:
        print(f"gate: hotfix.py {command} exited {result.returncode}; going on without its check", file=sys.stderr)
    return slugs


def target_flags(targets: list[str]) -> list[str]:
    return [part for target in targets for part in ("--target", target)]


def voiding_hotfixes(repo: Path, targets: list[str]) -> list[str]:
    return hotfix(repo, "void", target_flags(targets), "void")


def missing_hotfixes(repo: Path, targets: list[str]) -> list[str]:
    return hotfix(repo, "pending", target_flags(targets), "missing (merge main)")


def claim(lock: TextIO, command: list[str]) -> None:
    """Record the holder in a lock file it holds exclusively.

    Args:
      lock: the open, exclusively held lock file.
      command: the holder's command line.
    """
    lock.truncate(0)
    lock.write(f"{os.getpid()}\t{shlex.join(command)}\n")
    lock.flush()


def holder(path: Path) -> str:
    """Name the holder that `claim` recorded in a lock file.

    Args:
      path: the lock file.
    """
    try:
        pid, _, command = path.read_text(encoding="utf-8").strip().partition("\t")
    except OSError:
        pid, command = "", ""
    return f"pid {pid}: {command}" if pid and command else "holder not recorded"


def shared(sync: TextIO, repo: Path, caught: list[int]) -> None:
    """Take SYNC_LOCK shared, waiting at most SYNC_WAIT_SECONDS for a running sync.

    Args:
      sync: the open SYNC_LOCK file.
      repo: the worktree, named in messages.
      caught: signals the caller caught; the first ends the wait with 128+N.
    """
    deadline = time.monotonic() + SYNC_WAIT_SECONDS
    waiting = False
    while True:
        try:
            fcntl.flock(sync, fcntl.LOCK_SH | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            pass
        if caught:
            sys.exit(128 + caught[0])
        if time.monotonic() >= deadline:
            busy(f"a hotfix.py sync still holds {repo} after {SYNC_WAIT_SECONDS} s ({holder(Path(sync.name))}); "
                 "retry once it ends")
        if not waiting:
            print(f"gate: a hotfix.py sync merges in {repo} ({holder(Path(sync.name))}); waiting for it at most "
                  f"{SYNC_WAIT_SECONDS} s", file=sys.stderr, flush=True)
            waiting = True
        time.sleep(POLL_SECONDS)


@contextlib.contextmanager
def worktree_lock(repo: Path, command: list[str], caught: list[int]) -> Iterator[int]:
    """Hold the worktree lock; yields its file descriptor for pass_fds.

    Args:
      repo: the worktree whose git dir holds RUN_LOCK and SYNC_LOCK.
      command: the holder's command line, recorded in RUN_LOCK.
      caught: signals the caller caught; the first ends a wait for a sync with 128+N.
    """
    git_dir = Path(git(repo, "rev-parse", "--absolute-git-dir").strip())
    with open(git_dir / RUN_LOCK, "a", encoding="utf-8") as lock:
        with open(git_dir / SYNC_LOCK, "a", encoding="utf-8") as sync:
            shared(sync, repo, caught)
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                busy(f"another gate.py run or hold holds {repo} ({holder(git_dir / RUN_LOCK)})")
            claim(lock, command)
        yield lock.fileno()


def repository(value: str) -> Path:
    repo = Path(value).resolve()
    if not repo.is_dir():
        fail(f"{value} is no directory")
    return repo


def excluded() -> set[str]:
    if not CONFIG.is_file():
        return set()
    try:
        listed = json.loads(CONFIG.read_text(encoding="utf-8")).get(EXCLUDED, [])
    except (OSError, ValueError, AttributeError) as error:
        fail(f"cannot read {EXCLUDED} from {CONFIG}: {error}")
    if not isinstance(listed, list) or not all(isinstance(target, str) for target in listed):
        fail(f"{EXCLUDED} in {CONFIG} must be a list of target names")
    return set(listed)


def cmd_list(args: argparse.Namespace) -> int:
    found = targets(repository(args.repo))
    if args.json:
        print(json.dumps([{"target": t, "defined": d} for t, d in found.items()], indent=1))
        return 0
    for target, defined in found.items():
        print(f"{target}\t{defined}")
    return 0


def cell(value: str | None) -> str:
    return "-" if value is None else value


def cmd_status(args: argparse.Namespace) -> int:
    repo = repository(args.repo)
    found = targets(repo)
    sha = head(repo)
    state = load(state_path(repo))
    dirty, untracked = tree(repo)
    skip = excluded()
    required = [target for target in found if target not in skip]
    skipped = [target for target in found if target in skip]
    rows = []
    for target in found:
        entry = state[sha].get(target) if sha in state else None
        if target in skip:
            rows.append({"target": target, "status": "excluded", "reason": f"{EXCLUDED} in {CONFIG}"})
        else:
            rows.append({"target": target, "status": "missing"} if entry is None else {"target": target, **entry})
    missing = [r["target"] for r in rows if r["status"] == "missing"]
    red = [r["target"] for r in rows if r["status"] == "red"]
    reasons = []
    if not found:
        reasons.append("no make test* target found")
    elif not required:
        reasons.append("every make test* target is excluded")
    if missing:
        reasons.append(f"missing: {', '.join(missing)}")
    if red:
        reasons.append(f"red: {', '.join(red)}")
    if dirty:
        reasons.append(f"dirty: {len(dirty)} tracked file(s)")
    hotfixes = missing_hotfixes(repo, required) if required and hotfix_checks() else []
    if hotfixes:
        reasons.append(f"missing hotfix: {', '.join(hotfixes)}")
    gate = "open" if reasons else "green"
    if args.json:
        print(json.dumps(
            {"sha": sha, "gate": gate, "open": reasons, "targets": rows,
             "dirty": dirty, "untracked": untracked},
            indent=1,
        ))
    else:
        print(f"head\t{sha}")
        for r in rows:
            print("\t".join([r["status"], r["target"], *(cell(r.get(k)) for k in ("log", "finished", "reason"))]))
        if untracked:
            print(f"untracked\t{len(untracked)} file(s), not part of the gate")
        if reasons:
            print(f"gate: open ({'; '.join(reasons)})")
        elif skipped:
            print(f"gate: green (excluded: {', '.join(skipped)} by {CONFIG})")
        else:
            print("gate: green")
    return 0 if gate == "green" else 1


def cmd_run(args: argparse.Namespace) -> int:
    repo = repository(args.repo)
    checks = []
    if args.fail_regex is not None:
        try:
            checks = [re.compile(pattern) for pattern in args.fail_regex]
        except re.error as error:
            fail(f"--fail-regex: {error}")
    found = targets(repo)
    unknown = [t for t in args.target if t not in found]
    if unknown:
        fail(f"not a make test* target of {repo}: {', '.join(unknown)}")
    barred = sorted(set(args.target) & excluded())
    if barred:
        fail(f"excluded from every gate by {EXCLUDED} in {CONFIG}: {', '.join(barred)}")
    with worktree_lock(repo, ["gate.py", "run", "--repo", str(repo), *target_flags(args.target)], []) as lock:
        sha = head(repo)
        dirty, untracked = tree(repo)
        if dirty:
            fail(f"tracked files are dirty, commit or drop them first: {', '.join(dirty)}")
        if untracked:
            print(f"untracked\t{len(untracked)} file(s), not part of the gate")
        log_dir = Path(args.log_dir).resolve()
        log_dir.mkdir(parents=True, exist_ok=True)
        state = state_path(repo)
        red = False
        order = list(dict.fromkeys(args.target))
        checking = hotfix_checks()
        for index, target in enumerate(order):
            slugs = voiding_hotfixes(repo, order[index:]) if checking else []
            if slugs:
                print(f"void: merge main for hotfix {', '.join(slugs)}, then rerun")
                return 3
            log = log_dir / f"gate-{UNSAFE.sub('_', target)}-{sha[:8]}.log"
            with open(log, "w", encoding="utf-8") as out:
                code = subprocess.run(
                    ["make", "-C", str(repo), target],
                    stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, pass_fds=(lock,), check=False,
                ).returncode
            if head(repo) != sha:
                fail(f"HEAD moved during {target}; nothing recorded for it")
            changed, _ = tree(repo)
            reasons = []
            if code:
                reasons.append(f"exit {code}")
            line = first_failure(log, checks)
            if line is not None:
                reasons.append(line)
            if changed:
                reasons.append(f"modified tracked files: {', '.join(changed)}")
            status = "red" if reasons else "green"
            red = red or status == "red"
            entry = {"status": status, "log": str(log),
                     "finished": datetime.now(UTC).isoformat(timespec="seconds"),
                     "fail_regex": [c.pattern for c in checks]}
            if reasons:
                entry["reason"] = "; ".join(reasons)
            record(state, sha, target, entry)
            print("\t".join([status, target, str(log), cell(entry.get("reason"))]))
            if changed:
                fail(f"{target} left tracked files dirty; remaining targets not run")
    return 1 if red else 0


def send(child: subprocess.Popen, signum: int) -> None:
    if child.returncode is None:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(child.pid, signum)


def cmd_hold(args: argparse.Namespace) -> int:
    repo = repository(args.repo)
    caught: list[int] = []
    child: subprocess.Popen | None = None

    def forward(signum: int, _frame: object) -> None:
        if child is None:
            caught.append(signum)
        else:
            send(child, signum)

    for signum in FORWARDED:
        signal.signal(signum, forward)
    with worktree_lock(repo, ["gate.py", "hold", "--repo", str(repo), "--", *args.command], caught) as lock:
        if caught:
            return 128 + caught[0]
        try:
            child = subprocess.Popen(args.command, cwd=repo, pass_fds=(lock,), start_new_session=True)
        except OSError as error:
            fail(f"cannot start {args.command[0]}: {error.strerror}")
        for signum in caught:
            send(child, signum)
        code = child.wait()
    return code if code >= 0 else 128 - code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="subcommand", required=True)
    for name in ("list", "status"):
        command = sub.add_parser(name)
        command.add_argument("--repo", required=True)
        command.add_argument("--json", action="store_true")
    run = sub.add_parser("run")
    run.add_argument("--repo", required=True)
    run.add_argument("--target", action="append", required=True)
    run.add_argument("--log-dir", required=True)
    run.add_argument("--fail-regex", action="append")
    hold = sub.add_parser("hold")
    hold.add_argument("--repo", required=True)
    hold.add_argument("command", nargs="+")
    args = parser.parse_args()
    commands = {"list": cmd_list, "status": cmd_status, "run": cmd_run, "hold": cmd_hold}
    return commands[args.subcommand](args)


if __name__ == "__main__":
    sys.exit(main())
