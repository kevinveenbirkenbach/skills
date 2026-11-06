from __future__ import annotations

import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .council import agent
from .register import ENDED, status_of
from .skill_scripts import SAFE_PATH

TREE_TTL = 60.0
TREE_DEPTH = 6
GIT_TIMEOUT = 10


def git(cwd: Path, args: list[str], home: Path) -> str | None:
    env = {"PATH": SAFE_PATH, "HOME": str(home), "GIT_CONFIG_NOSYSTEM": "1", "GIT_NO_LAZY_FETCH": "1", "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}
    try:
        done = subprocess.run(
            ["git", "-c", "safe.directory=*", "-c", "core.fsmonitor=false", "-C", str(cwd), *args],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=GIT_TIMEOUT,
            env=env,
            stdin=subprocess.DEVNULL,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout if done.returncode == 0 else None


def parse_worktrees(text: str) -> list[dict]:
    found = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.partition(" ")[::2] for line in block.splitlines() if line)
        if "worktree" not in lines or "bare" in lines:
            continue
        found.append({
            "path": lines["worktree"], "head": lines.get("HEAD", ""), "branch": lines.get("branch", "").removeprefix("refs/heads/"),
            "prunable": "prunable" in lines,
        })
    return found


def tracking(text: str) -> tuple[int, int, bool]:
    counts = {name: int(number) for name, number in re.findall(r"(ahead|behind) ([0-9]+)", text)}
    return counts.get("ahead", 0), counts.get("behind", 0), text.strip() == "gone"


def parse_refs(text: str) -> list[dict]:
    found = []
    for line in text.splitlines():
        parts = line.split("\x00")
        if len(parts) != 4:
            continue
        ahead, behind, gone = tracking(parts[3])
        found.append({"name": parts[0], "head": parts[1], "upstream": parts[2], "ahead": ahead, "behind": behind, "gone": gone})
    return found


def linked(root: Path) -> list[Path]:
    found = []
    for top, dirs, names in os.walk(root):
        here = Path(top)
        if ".git" in names or ".git" in dirs:
            found.append(here)
            dirs[:] = []
        elif len(here.relative_to(root).parts) >= TREE_DEPTH:
            dirs[:] = []
        else:
            dirs.sort()
    return found


def dirty(path: Path, home: Path) -> bool | None:
    # agents write these repos, and status runs every filter.*.clean command the config names
    if git(path, ["config", "--get-regexp", r"^filter\."], home) is not None:
        return None
    status = git(path, ["status", "--porcelain=v1", "--untracked-files=normal", "--ignore-submodules=all"], home)
    return None if status is None else bool(status.strip())


def repo_entry(path: Path, label: str, home: Path) -> dict:
    trees = parse_worktrees(git(path, ["worktree", "list", "--porcelain"], home) or "")
    refs = git(path, ["for-each-ref", "--format=%(refname:short)%00%(objectname)%00%(upstream:short)%00%(upstream:track,nobracket)", "refs/heads"], home)
    branches = parse_refs(refs or "")
    for tree in trees:
        tree["dirty"] = None if tree["prunable"] else dirty(Path(tree["path"]), home)
    known = {branch["name"] for branch in branches}
    branches += [{"name": tree["branch"], "head": tree["head"], "upstream": "", "ahead": 0, "behind": 0, "gone": False} for tree in trees if tree["branch"] and tree["branch"] not in known]
    for branch in branches:
        branch["worktrees"] = [tree for tree in trees if tree["branch"] == branch["name"]]
    return {"path": str(path), "name": label, "branches": branches, "detached": [tree for tree in trees if not tree["branch"]]}


def scan_tree(repos: Path, worktrees: Path, home: Path) -> dict:
    root = repos.resolve()
    try:
        mains = sorted(path.resolve() for path in root.glob("*/*/*") if (path / ".git").is_dir())
    except OSError:
        mains = []
    entries = {str(path): repo_entry(path, str(path.relative_to(root)), home) for path in mains if path.is_relative_to(root)}
    seen = {tree["path"] for entry in entries.values() for branch in entry["branches"] for tree in branch["worktrees"]}
    seen |= {tree["path"] for entry in entries.values() for tree in entry["detached"]}
    for path in linked(worktrees.resolve()):
        if str(path) in seen:
            continue
        common = git(path, ["rev-parse", "--path-format=absolute", "--git-common-dir"], home)
        main = Path(common.strip()).parent if common else None
        if main is not None and str(main) not in entries and (main / ".git").is_dir():
            entries[str(main)] = repo_entry(main, str(main), home)
    return {"repos": sorted(entries.values(), key=lambda entry: entry["name"]), "scanned": time.time()}


def inside(path: str, folder: str) -> bool:
    return path == folder or path.startswith(f"{folder.rstrip('/')}/")


def assign(scan: dict, tasks: dict[str, dict], claims: list[dict], reviews: list[dict]) -> dict:
    current = {task: row for task, row in tasks.items() if status_of(row) not in ENDED}
    holders: dict[str, set[str]] = {}
    for task, row in current.items():
        names = {agent(row.get("worker"))} | {claim["agent"] for claim in claims if claim["office"] == task}
        holders[task] = {name for name in names if name}
    latest: dict[str, dict] = {}
    for review in reviews:
        latest[review["worktree"]] = {"status": review["status"], "gate": review.get("gate", ""), "title": review["title"]}
    repos = []
    for entry in scan["repos"]:
        branches = []
        for branch in entry["branches"]:
            trees = []
            for tree in branch["worktrees"]:
                workers = set()
                for task, row in current.items():
                    workdir, name = row.get("workdir"), row.get("branch")
                    by_dir = isinstance(workdir, str) and workdir.startswith("/") and inside(workdir, tree["path"])
                    by_branch = not isinstance(workdir, str) and name == branch["name"]
                    if by_dir or by_branch:
                        workers |= holders[task]
                trees.append({**tree, "workers": sorted(workers, key=str.lower), "review": latest.get(tree["path"])})
            branches.append({**branch, "worktrees": trees})
        repos.append({**entry, "branches": branches})
    return {"repos": repos, "scanned": scan["scanned"]}


@dataclass
class Tree:
    repos: Path
    worktrees: Path
    home: Path
    lock: threading.Lock
    cached: dict | None
    scanned: float

    def get(self) -> dict:
        with self.lock:
            if self.cached is None or time.monotonic() - self.scanned >= TREE_TTL:
                self.cached = scan_tree(self.repos, self.worktrees, self.home)
                self.scanned = time.monotonic()
            return self.cached
