from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path

from .council import agent
from .records import iso_epoch
from .register import ENDED, status_of

LABEL_PARTS = 3
# renaming it silently stops the tree timer: kvb-orchestrator-tree.service tests this file's age
TREE_HEARTBEAT = "tree-heartbeat"


def worktree(item: dict) -> dict:
    state = item["worktree_state"]
    unread = state == "changed" and item["staged"] is None
    return {
        "path": item["worktree"],
        "head": item["head"] or "",
        "branch": item["branch"] or "",
        "prunable": state == "missing",
        "dirty": None if state == "missing" or unread else state == "changed",
        "state": state,
        "staged": item["staged"],
        "unstaged": item["unstaged"],
        "untracked": item["untracked"],
        "locked": item["locked"],
    }


def branch(item: dict) -> dict:
    remote = next(iter(item["remotes"].values()), "")
    return {
        "name": item["branch"],
        "head": item["local_sha"] or item["head"] or remote,
        "upstream": item["upstream"] or "",
        "ahead": item["ahead"] or 0,
        "behind": item["behind"] or 0,
        "gone": item["gone"],
        "state": item["state"],
        "merged_by": item["merged_by"],
        "skip": item["skip"],
        "reason": item["reason"],
        "worktrees": [worktree(item)] if item["worktree"] else [],
    }


def repo(entry: dict) -> dict:
    items = entry["items"]
    return {
        **{key: value for key, value in entry.items() if key != "items"},
        "name": "/".join(Path(entry["path"]).parts[-LABEL_PARTS:]),
        "branches": [branch(item) for item in items if item["branch"]],
        "detached": [worktree(item) for item in items if item["detached"]],
    }


def read_tree(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {
            "repos": sorted((repo(entry) for entry in data["repos"]), key=lambda entry: entry["name"]),
            "scanned": iso_epoch(data["generated_at"]),
            "delete_ready": data["delete_ready"],
            "delete_reason": data["delete_reason"],
        }
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        return {"repos": [], "scanned": None, "error": f"pkgmgr tree file {path} unreadable: {error}"}


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
        for item in entry["branches"]:
            trees = []
            for tree in item["worktrees"]:
                workers = set()
                for task, row in current.items():
                    workdir, name = row.get("workdir"), row.get("branch")
                    by_dir = isinstance(workdir, str) and workdir.startswith("/") and inside(workdir, tree["path"])
                    by_branch = not isinstance(workdir, str) and name == item["name"]
                    if by_dir or by_branch:
                        workers |= holders[task]
                trees.append({**tree, "workers": sorted(workers, key=str.lower), "review": latest.get(tree["path"])})
            branches.append({**item, "worktrees": trees})
        repos.append({**entry, "branches": branches, "detached": [{**tree, "workers": [], "review": latest.get(tree["path"])} for tree in entry["detached"]]})
    return {**scan, "repos": repos}


@dataclass
class Tree:
    file: Path
    heartbeat: Path
    lock: threading.Lock
    cached: dict | None
    stamp: tuple[int, int] | None

    def beat(self) -> None:
        self.heartbeat.touch()

    def get(self) -> dict:
        with self.lock:
            try:
                info = self.file.stat()
            except OSError as error:
                return {"repos": [], "scanned": None, "error": f"no pkgmgr tree file at {self.file}: {error.strerror}"}
            stamp = (info.st_mtime_ns, info.st_size)
            if self.cached is None or stamp != self.stamp:
                self.cached, self.stamp = read_tree(self.file), stamp
            return self.cached
