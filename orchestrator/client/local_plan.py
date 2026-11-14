#!/usr/bin/env python3
"""Args:
    --tree: the tree file `pkgmgr branch tree` writes; the plan goes beside
        it as local-plan.json, in the directory the orchestrator mounts
        read-only.
    --pkgmgr: the pkgmgr executable built from a signed tag.
    --budget: seconds one repository's dry run may take, well below the
        tree unit's TimeoutStartSec.

Returns:
    Keeps local-plan.json beside the tree file: the dry run of `pkgmgr
    branch cleanup --local --json` of every repository the tree file says
    pkgmgr knows, run in it as the cleanup runner runs its dry run
    (cleanup.run: no repository hook or fsmonitor), named by its real path.
    A repository whose refs, HEAD, config, reftable and worktree heads
    (fingerprint) are unchanged since its last attempt is not planned
    again. Before each dry run the file is rewritten atomically with that
    repository marked stale ("replan started <time> has not finished") at
    the attempted fingerprint, and again after it, so a kill keeps every
    plan written before; a dry run that fails or outlasts --budget keeps
    the repository's old items, marked stale with the reason and time, and
    is retried only once its fingerprint changes. The hub offers nothing
    from a stale repository. Deleting local-plan.json plans every
    repository again. The exit code is 0 when every dry run of this run
    printed a plan, else 1.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

import cleanup

LOCAL_PLAN = "local-plan.json"
PLAN_ARGV = ["branch", "cleanup", "--local", "--json"]
GIT_FILES = ("HEAD", "config", "packed-refs", "reftable/tables.list")
WORKTREE_FILES = ("HEAD", "gitdir", "locked", "config.worktree")


def git_dir(repo: Path) -> Path:
    dot = repo / ".git"
    if dot.is_file():
        return (repo / dot.read_text(encoding="utf-8").strip().removeprefix("gitdir: ")).resolve()
    return dot


def fingerprint(repo: str) -> str | None:
    """Returns:
        sha256 over name, mtime and size of every file the `--local` plan
        reads from the repository's git dir: HEAD, config, packed-refs, the
        reftable table list, every ref, and each worktree's HEAD, gitdir,
        lock and config; None when the git dir cannot be read.
    """
    try:
        root = git_dir(Path(repo))
        paths = [root / name for name in GIT_FILES]
        for folder, _, files in os.walk(root / "refs"):
            paths += [Path(folder, name) for name in files]
        worktrees = root / "worktrees"
        if worktrees.is_dir():
            paths += [entry / name for entry in worktrees.iterdir() for name in WORKTREE_FILES]
        digest = hashlib.sha256()
        for path in sorted(paths):
            try:
                info = path.stat()
            except FileNotFoundError:
                continue
            digest.update(f"{path.relative_to(root)}\0{info.st_mtime_ns}\0{info.st_size}\n".encode())
        return digest.hexdigest()
    except OSError:
        return None


def known_repos(tree: Path) -> list[str]:
    data = json.loads(tree.read_text(encoding="utf-8"))
    return [entry["path"] for entry in data["repos"] if entry.get("known") is True and entry.get("missing") is not True and isinstance(entry.get("path"), str)]


def old_plans(target: Path) -> dict[str, dict]:
    try:
        return {entry["repo"]: entry for entry in json.loads(target.read_text(encoding="utf-8"))["repos"] if isinstance(entry, dict) and isinstance(entry.get("repo"), str)}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {}


def plan(pkgmgr: Path, repo: str, budget: int) -> tuple[dict | None, str]:
    """Returns:
        The repository's {"repo", "default", "merged_into", "warnings",
        "items"} as pkgmgr prints it, named by its real path, and ""; or
        None and "timed out" or "failed" when pkgmgr printed no plan of
        exactly one repository within the budget.
    """
    code, stdout, stderr = cleanup.run(pkgmgr, PLAN_ARGV, repo, budget)
    if cleanup.plan_items(stdout) is None:
        return None, "timed out" if code == 127 and "timed out" in stderr else "failed"
    repos = json.loads(stdout)["repos"]
    if len(repos) != 1 or not isinstance(repos[0].get("repo"), str):
        return None, "failed"
    return {**repos[0], "repo": os.path.realpath(repos[0]["repo"])}, ""


def write(target: Path, data: dict) -> None:
    with tempfile.NamedTemporaryFile("w", dir=target.parent, prefix=f".{target.name}-", delete=False, encoding="utf-8") as handle:
        json.dump(data, handle)
    os.replace(handle.name, target)


def now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")


def main() -> int:
    parser = argparse.ArgumentParser(prog="local_plan")
    parser.add_argument("--tree", type=Path, required=True)
    parser.add_argument("--pkgmgr", type=Path, required=True)
    parser.add_argument("--budget", type=int, required=True)
    args = parser.parse_args()
    target = args.tree.with_name(LOCAL_PLAN)
    try:
        known = [os.path.realpath(repo) for repo in known_repos(args.tree)]
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        print(f"local_plan: tree file {args.tree} unreadable ({error}), the old plan stays", file=sys.stderr)
        return 1
    plans = {repo: entry for repo, entry in old_plans(target).items() if repo in known}

    def save() -> None:
        write(target, {"repos": [plans[repo] for repo in known if repo in plans]})

    failed = []
    for repo in known:
        current = fingerprint(repo)
        if current is not None and plans.get(repo, {}).get("fingerprint") == current:
            continue
        previous = plans.get(repo, {"repo": repo, "default": None, "merged_into": [], "warnings": [], "items": []})
        plans[repo] = {**previous, "fingerprint": current, "stale": f"replan started {now()} has not finished"}
        save()
        planned, reason = plan(args.pkgmgr, repo, args.budget)
        if planned is None:
            plans[repo] = {**previous, "fingerprint": current, "stale": f"replan {reason} at {now()}"}
            failed.append(f"{repo}: {reason}")
        else:
            plans[repo] = {**planned, "fingerprint": current}
        save()
    if not known:
        save()
    for line in failed:
        print(f"local_plan: no --local plan for {line}, the hub offers no delete there until its refs change", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
