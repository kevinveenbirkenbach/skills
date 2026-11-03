#!/usr/bin/env python3
"""List, run and check a project's `make test*` targets against the current HEAD.

Args:
    list --repo <dir> [--json]: the Makefile targets named `test` or `test-*`,
        parsed statically from the Makefile make reads in <dir> and every file
        it includes; make is never run.
    status --repo <dir> [--json]: per listed target green, red or missing for
        HEAD, from `kvb-gate.json` in the git common dir.
    run --repo <dir> --target <t> [--target ...] --log-dir <dir>
        [--fail-regex <re> ...]: run each target as `make -C <dir> <t>` with
        stdout and stderr in <log-dir>/gate-<t>-<sha8>.log and record the
        result for HEAD. A target is red on a non-zero exit, a `make: ***`
        line, a matching --fail-regex, or tracked files it modified.

Output:
    list: one `<target>\t<file>:<line>` per target.
    status: one `<status>\t<target>\t<log>\t<finished>\t<reason>` per target,
        then `gate: green`, or `gate: open (...)` naming what is missing.
    run: one `<status>\t<target>\t<log>\t<reason>` per target.
    --json prints the same data as JSON.

Exit codes:
    list: 0 done, 2 usage error.
    status: 0 gate green, 1 gate open, 2 usage error.
    run: 0 every target green, 1 a target red, 2 usage error, dirty tracked
        files or HEAD moved during a run.
"""

from __future__ import annotations

import argparse
import fcntl
import glob
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn

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


def fail(message: str) -> NoReturn:
    print(f"gate: {message}", file=sys.stderr)
    sys.exit(2)


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


def repository(value: str) -> Path:
    repo = Path(value).resolve()
    if not repo.is_dir():
        fail(f"{value} is no directory")
    return repo


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
    rows = []
    for target in found:
        entry = state[sha].get(target) if sha in state else None
        rows.append({"target": target, "status": "missing"} if entry is None else {"target": target, **entry})
    missing = [r["target"] for r in rows if r["status"] == "missing"]
    red = [r["target"] for r in rows if r["status"] == "red"]
    reasons = []
    if not found:
        reasons.append("no make test* target found")
    if missing:
        reasons.append(f"missing: {', '.join(missing)}")
    if red:
        reasons.append(f"red: {', '.join(red)}")
    if dirty:
        reasons.append(f"dirty: {len(dirty)} tracked file(s)")
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
        print("gate: green" if gate == "green" else f"gate: open ({'; '.join(reasons)})")
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
    for target in dict.fromkeys(args.target):
        log = log_dir / f"gate-{UNSAFE.sub('_', target)}-{sha[:8]}.log"
        with open(log, "w", encoding="utf-8") as out:
            code = subprocess.run(
                ["make", "-C", str(repo), target],
                stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, check=False,
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("list", "status"):
        command = sub.add_parser(name)
        command.add_argument("--repo", required=True)
        command.add_argument("--json", action="store_true")
    run = sub.add_parser("run")
    run.add_argument("--repo", required=True)
    run.add_argument("--target", action="append", required=True)
    run.add_argument("--log-dir", required=True)
    run.add_argument("--fail-regex", action="append")
    args = parser.parse_args()
    return {"list": cmd_list, "status": cmd_status, "run": cmd_run}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
