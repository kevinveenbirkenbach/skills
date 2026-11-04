#!/usr/bin/env python3
"""Find merged and abandoned branches and worktrees of a repository and propose a step for each.

Reads only: no fetch, delete or edit; the caller fetches first. Every git call
runs with GIT_OPTIONAL_LOCKS=0, because a plain `git status` refreshes the
index and so moves the index mtime this script reads as activity.

Args:
    --repo: any worktree of the repository.
    --default: the default branch; merged means merged into origin/<default>.
    --stale-days: an unmerged row idle for longer may be stale-open.
    --top: rows per class the summary shows, 0 for the counts only.
    --full: file that receives the complete table of every row but the active
        ones; the summary names it.
    --sizes: measure the worktree of every row but the active ones (bytes of
        its regular files, .git skipped, no symlink followed), show it and
        order by it, largest first; slow, as it walks every file.
    --json: print every row, active ones included, as JSON instead of the
        summary; --top does not shorten it.

Environment:
    AGENTS_COUNCIL_ROOT: council directory of the kvb-org-organize skill, read
        through its council.py for claims.
    AGENTS_COUNCIL_CONFIG: config of its watch.py, whose busy_processes name
        the busy processes; without the file busy is unknown (null).

Rows, one per local branch with the worktree holding it, and one per worktree
with a detached HEAD:
    merged: `ancestor` when the tip is an ancestor of origin/<default>,
        `patch` when `git cherry` finds a patch-equivalent there for every
        commit outside it. That catches squash and rebase merges only partly:
        a squash of several commits, a rebase that changed a patch or a merge
        commit outside origin/<default> stays unmerged.
    dirty: changed and untracked files of the worktree.
    unpushed: commits outside origin/<default> without a patch-equivalent
        there that the upstream lacks; without an upstream on a remote, those
        no remote-tracking ref holds. Always 0 when merged.
    upstream: the remote-tracking upstream, null when none resolves; null
        counts as unpushed for an unmerged row.
    last activity: newest of the tip's commit date, the worktree's index mtime
        and the mtimes of its changed files.
    claims: council claims whose work names the worktree path or the branch;
        only a live one protects.
    busy: a busy_processes process works inside the worktree; processes of
        another PID namespace stay unseen.
    size: bytes with --sizes, else null; null for active rows and rows
        without a worktree.

Classes, first match wins:
    active: the main worktree, the default branch and archive/ branches.
    merged-clean: merged, nothing dirty; proposal kvb-git-branch-gc.
    merged-dirty: merged with dirty files; proposal ask.
    stale-open: unmerged, dirty or unpushed, last activity older than
        --stale-days, no live claim, not busy; proposal ask.
    active: anything else; proposal keep.
    A merged row with a live claim or a busy process proposes keep (claimed)
    or keep (busy) instead.

Output:
    A summary: one line per class with its count and proposal, the --full
    file, claims or busy that could not be checked; then the table `| Class |
    Branch | Worktree | Dirty | Unpushed | Last activity | Claim | Proposal |`
    of the top rows per class but active, oldest last activity first, with
    --sizes largest first and a Size column after Worktree. The --full file
    holds the same table with every row but the active ones.

Exit codes:
    0 done, 2 usage error, a failed git call or origin/<default> missing.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import NoReturn

ORGANIZE = Path(__file__).resolve().parents[2] / "kvb-org-organize" / "scripts"
DAY = 86400
ORDER = ("merged-clean", "merged-dirty", "stale-open", "active")
HEADER = ("Class", "Branch", "Worktree", "Dirty", "Unpushed", "Last activity", "Claim", "Proposal")
GC = "kvb-git-branch-gc"
PROPOSALS = {"merged-clean": GC, "merged-dirty": "ask", "stale-open": "ask", "active": "keep, listed by --json"}
UNITS = ("KiB", "MiB", "GiB", "TiB")
DETACHED = "(detached)"
ARCHIVE = "refs/heads/archive/"


@dataclasses.dataclass(frozen=True)
class Scan:
    repo: str
    base: str
    default: str
    claims: list[dict]
    busy: Callable[[str], bool] | None
    now: float
    limit: float


def fail(message: str) -> NoReturn:
    print(f"orphans: {message}", file=sys.stderr)
    sys.exit(2)


def module(name: str) -> ModuleType | None:
    path = ORGANIZE / f"{name}.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def git(where: str, *args: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["git", *args], cwd=where, stdin=subprocess.DEVNULL, capture_output=True, text=True,
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"}, check=False,
        )
    except OSError as error:
        return subprocess.CompletedProcess(["git", *args], 128, "", str(error))


def git_out(where: str, *args: str) -> str:
    result = git(where, *args)
    if result.returncode:
        fail(f"git {' '.join(args)} in {where}: {(result.stderr or result.stdout).strip()}")
    return result.stdout


def resolves(where: str, ref: str) -> bool:
    return git(where, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").returncode == 0


def worktrees(repo: str) -> list[dict]:
    trees: list[dict] = []
    for line in git_out(repo, "worktree", "list", "--porcelain").splitlines():
        key, _, value = line.partition(" ")
        if key == "worktree":
            trees.append({"path": value, "head": None, "branch": None, "main": not trees, "bare": False})
        elif trees and key == "HEAD":
            trees[-1]["head"] = value
        elif trees and key == "branch":
            trees[-1]["branch"] = value
        elif trees and key == "bare":
            trees[-1]["bare"] = True
    return trees


def branches(repo: str) -> list[list[str]]:
    out = git_out(repo, "branch", "--list", "--format=%(refname)\t%(upstream)\t%(committerdate:unix)")
    return [line.split("\t") for line in out.splitlines() if line]


def committed(repo: str, rev: str) -> int:
    return int(git_out(repo, "log", "-1", "--format=%ct", rev).strip())


def measure(scan: Scan, ref: str, upstream: str) -> tuple[str | None, int, str | None]:
    tracked = upstream if upstream.startswith("refs/remotes/") and resolves(scan.repo, upstream) else None
    outside = set(git_out(scan.repo, "rev-list", ref, f"^{scan.base}").split())
    if not outside:
        return "ancestor", 0, tracked
    cherry = git_out(scan.repo, "cherry", scan.base, ref).splitlines()
    equivalent = {line[2:] for line in cherry if line.startswith("- ")}
    if equivalent == outside:
        return "patch", 0, tracked
    held = [f"^{tracked}"] if tracked else ["--not", "--remotes"]
    local = set(git_out(scan.repo, "rev-list", ref, *held).split())
    return None, len(local & (outside - equivalent)), tracked


def index_mtime(tree: str) -> float:
    path = git_out(tree, "rev-parse", "--path-format=absolute", "--git-path", "index").strip()
    try:
        return os.stat(path).st_mtime
    except OSError:
        return 0.0


def changes(tree: str) -> tuple[int, float]:
    fields = git_out(tree, "status", "--porcelain=v1", "-z", "--untracked-files=all").split("\0")
    count, newest, at = 0, 0.0, 0
    while at < len(fields):
        entry = fields[at]
        at += 2 if "R" in entry[:2] or "C" in entry[:2] else 1
        if not entry:
            continue
        count += 1
        with contextlib.suppress(OSError):
            newest = max(newest, os.lstat(os.path.join(tree, entry[3:])).st_mtime)
    return count, newest


def mentions(text: str, name: str) -> bool:
    return re.search(rf"(?<![\w./-]){re.escape(name)}(?![\w-]|\.\w)", text) is not None


def classify(item: dict, scan: Scan, ref: str) -> str:
    if item["main"] or item["default"] or ref.startswith(ARCHIVE):
        return "active"
    if item["merged"]:
        return "merged-dirty" if item["dirty"] else "merged-clean"
    pending = bool(item["dirty"] or item["unpushed"] or not item["upstream"])
    idle = scan.now - item["last_activity"] > scan.limit
    guarded = any(claim["live"] for claim in item["claims"]) or item["busy"]
    return "stale-open" if pending and idle and not guarded else "active"


def proposal(item: dict) -> str:
    if item["class"] == "active":
        return "keep"
    if any(claim["live"] for claim in item["claims"]):
        return "keep (claimed)"
    if item["busy"]:
        return "keep (busy)"
    return GC if item["class"] == "merged-clean" else "ask"


def inspect(scan: Scan, ref: str, upstream: str, date: int, tree: dict | None) -> dict:
    name = ref.removeprefix("refs/heads/") if ref.startswith("refs/heads/") else DETACHED
    merged, unpushed, tracked = measure(scan, ref, upstream)
    path = tree["path"] if tree else None
    present = path is not None and os.path.isdir(path)
    activity, dirty, busy = float(date), None, False
    if present:
        activity = max(activity, index_mtime(path))
        dirty, changed = changes(path)
        activity = max(activity, changed)
        busy = scan.busy(path) if scan.busy else None
    names = {path, os.path.realpath(path)} if path else set()
    if ref.startswith("refs/heads/"):
        names.add(name)
    item = {
        "branch": name,
        "worktree": path,
        "missing": path is not None and not present,
        "main": bool(tree and tree["main"]),
        "default": ref == f"refs/heads/{scan.default}",
        "merged": merged,
        "dirty": dirty,
        "unpushed": unpushed,
        "upstream": tracked,
        "last_activity": int(activity),
        "claims": [
            {key: claim[key] for key in ("office", "holder", "live")}
            for claim in scan.claims
            if any(mentions(claim["work"], each) for each in names)
        ],
        "busy": busy,
    }
    item["class"] = classify(item, scan, ref)
    item["proposal"] = proposal(item)
    return item


def tree_size(top: str) -> int:
    total = 0
    for base, dirs, files in os.walk(top):
        dirs[:] = [name for name in dirs if name != ".git"]
        for name in files:
            if name == ".git":
                continue
            with contextlib.suppress(OSError):
                found = os.lstat(os.path.join(base, name))
                if stat.S_ISREG(found.st_mode):
                    total += found.st_size
    return total


def human(size: int | None) -> str:
    if size is None:
        return "-"
    if size < 1024:
        return f"{size} B"
    value = float(size)
    for unit in UNITS:
        value /= 1024
        if value < 1024 or unit == UNITS[-1]:
            break
    return f"{value:.1f} {unit}"


def cells(item: dict, now: float, sizes: bool) -> list[str]:
    worktree = (item["worktree"] or "-") + (" (missing)" if item["missing"] else "")
    unpushed = str(item["unpushed"]) + (" (no upstream)" if not item["upstream"] and not item["merged"] else "")
    day = time.strftime("%Y-%m-%d", time.localtime(item["last_activity"]))
    age = int((now - item["last_activity"]) // DAY)
    claims = [f"{c['office']} ({c['holder']}{'' if c['live'] else ', ended'})" for c in item["claims"]]
    if item["busy"]:
        claims.append("busy")
    values = [
        item["class"], item["branch"], worktree, *([human(item["size"])] if sizes else []),
        "-" if item["dirty"] is None else str(item["dirty"]), unpushed, f"{day} ({age} d)",
        ", ".join(claims) or "-", item["proposal"],
    ]
    return [value.replace("|", "\\|") for value in values]


def table(items: list[dict], now: float, sizes: bool) -> list[str]:
    header = [*HEADER[:3], *(["Size"] if sizes else []), *HEADER[3:]]
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    return lines + ["| " + " | ".join(cells(item, now, sizes)) + " |" for item in items]


def rank(item: dict, sizes: bool) -> tuple:
    largest = -(item["size"] or 0) if sizes else 0
    return ORDER.index(item["class"]), largest, item["last_activity"], item["branch"], item["worktree"] or ""


def parse() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", required=True)
    parser.add_argument("--default", required=True)
    parser.add_argument("--stale-days", type=int, required=True)
    parser.add_argument("--top", type=int, required=True)
    parser.add_argument("--full")
    parser.add_argument("--sizes", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.stale_days < 0:
        fail("--stale-days must be 0 or more")
    if args.top < 0:
        fail("--top must be 0 or more")
    return args


def target(args: argparse.Namespace) -> tuple[str, str]:
    repo = os.path.realpath(args.repo)
    if not os.path.isdir(repo):
        fail(f"--repo {args.repo} is no directory")
    if args.default.startswith("-") or git(repo, "check-ref-format", f"refs/heads/{args.default}").returncode:
        fail(f"--default {args.default!r} is no valid branch name")
    base = f"refs/remotes/origin/{args.default}"
    if not resolves(repo, base):
        fail(f"origin/{args.default} does not resolve in {repo}; fetch first")
    return repo, base


def council_claims(council: ModuleType | None) -> list[dict]:
    if council is None:
        return []
    live = council.live_sessions()
    return [
        {
            "office": office,
            "holder": claim.get("name") or claim.get("session"),
            "live": not council.is_stale(claim, live),
            "work": str(claim.get("work", "")),
        }
        for office, claim in council.claims()
    ]


def rows(scan: Scan, sizes: bool) -> list[dict]:
    trees = worktrees(scan.repo)
    held = {tree["branch"]: tree for tree in trees if tree["branch"]}
    items = [inspect(scan, ref, upstream, int(date), held.get(ref)) for ref, upstream, date in branches(scan.repo)]
    items += [
        inspect(scan, tree["head"], "", committed(scan.repo, tree["head"]), tree)
        for tree in trees
        if not tree["bare"] and tree["branch"] is None and tree["head"]
    ]
    for item in items:
        measured = sizes and item["class"] != "active" and item["worktree"] and not item["missing"]
        item["size"] = tree_size(item["worktree"]) if measured else None
    items.sort(key=lambda item: rank(item, sizes))
    return items


def main() -> int:
    args = parse()
    repo, base = target(args)
    council, watch = module("council"), module("watch")
    config = watch.load_config() if watch else None
    names = config["busy_processes"] if config else None
    scan = Scan(
        repo=repo, base=base, default=args.default, claims=council_claims(council),
        busy=(lambda tree: watch.busy(tree, names)) if names is not None else None,
        now=time.time(), limit=args.stale_days * DAY,
    )
    items = rows(scan, args.sizes)
    orphans = [item for item in items if item["class"] != "active"]
    full = os.path.abspath(args.full) if args.full is not None else None
    if full is not None:
        try:
            Path(full).write_text("\n".join(table(orphans, scan.now, args.sizes)) + "\n", encoding="utf-8")
        except OSError as error:
            fail(f"--full {args.full}: {error.strerror or error}")
    if args.json:
        print(json.dumps({
            "repo": repo, "default": args.default, "stale_days": args.stale_days,
            "claims_checked": council is not None, "busy_checked": names is not None, "rows": items,
        }, indent=1))
        return 0
    print(f"orphans in {repo}, merged into origin/{args.default}, stale after {args.stale_days} days:")
    for name in ORDER:
        print(f"- {name}: {sum(item['class'] == name for item in items)} ({PROPOSALS[name]})")
    if full is not None:
        print(f"- full table: {full}")
    if council is None:
        print("- claims unknown: council.py of kvb-org-organize is missing")
    if names is None:
        print("- busy unknown: no agents-council config")
    top = [item for name in ORDER[:-1] for item in [o for o in orphans if o["class"] == name][: args.top]]
    if top:
        print(f"\nTop {args.top} per class, {'largest' if args.sizes else 'oldest'} first:\n")
        print("\n".join(table(top, scan.now, args.sizes)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
