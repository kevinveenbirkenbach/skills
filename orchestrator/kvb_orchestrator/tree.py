from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from pathlib import Path

from .council import agent
from .records import iso_epoch
from .register import ENDED, status_of
from .signed import signing

LABEL_PARTS = 3
FLOW_LIMIT = 16
FLOW_REF = re.compile(r"[^\x00-\x20\x7f]{1,255}")
FLOW_SOURCE = re.compile(r"[a-z][a-z0-9-]{0,31}")
INVALID = "invalid"
# renaming it silently stops the tree timer: kvb-orchestrator-tree.service tests this file's age
TREE_HEARTBEAT = "tree-heartbeat"
GC_SKILL = "kvb-git-gc"
GC_COMPOSE_DOWN = ("docker", "compose", "-p", "{project}", "down", "-v", "--remove-orphans")
LOCAL_PLAN = "local-plan.json"


def flow(item: dict) -> dict | None:
    """Returns:
        The worktree's pkgmgr merge flow: pull, the sources merged into the
        branch before a gate, and push, the targets the finished branch
        merges into, each capped at FLOW_LIMIT; None when the item names no
        flow, source invalid with empty lists when pkgmgr found the flow
        file broken or the field has the wrong shape.
    """
    raw = item.get("flow")
    if raw is None:
        return None
    broken = {"pull": [], "push": [], "source": INVALID}
    if not isinstance(raw, dict) or not isinstance(raw.get("source"), str) or not FLOW_SOURCE.fullmatch(raw["source"]) or raw["source"] == INVALID:
        return broken
    lists = [raw.get(side)[:FLOW_LIMIT] if isinstance(raw.get(side), list) else None for side in ("pull", "push")]
    if not all(names is not None and all(isinstance(name, str) and FLOW_REF.fullmatch(name) for name in names) for names in lists):
        return broken
    return {"pull": lists[0], "push": lists[1], "source": raw["source"]}


def work(item: dict, dirty: bool | None) -> list[str]:
    ahead = item["ahead"]
    found = (("dirty", dirty is True), ("unpushed", isinstance(ahead, int) and ahead > 0), ("unmerged", item["state"] == "unmerged"))
    return [reason for reason, hit in found if hit]


def worktree(item: dict) -> dict:
    state = item["worktree_state"]
    unread = state == "changed" and item["staged"] is None
    dirty = None if state == "missing" or unread else state == "changed"
    return {
        "path": item["worktree"],
        "head": item["head"] or "",
        "branch": item["branch"] or "",
        "prunable": state == "missing",
        "dirty": dirty,
        "state": state,
        "staged": item["staged"],
        "unstaged": item["unstaged"],
        "untracked": item["untracked"],
        "locked": item["locked"],
        "flow": flow(item),
        "open_work": work(item, dirty),
    }


def held_by(worktree: str) -> str:
    return f"held by worktree {worktree}: pkgmgr branch cleanup skips it, use branch gc ({GC_SKILL}, pkgmgr gc)"


def kept_by(planned: dict | None, tip: str, upstream_of: str, stale: str) -> str:
    """Args:
        planned: this branch's item of the `pkgmgr branch cleanup --local`
            dry run beside the tree file, None when it has none.
        tip: the branch's local tip in the tree file.
        upstream_of: a branch of the same dry run whose local upstream this
            branch is, "" for none; pkgmgr's _config_keeps keeps it when the
            host's `--branch` dry run chooses it alone.
        stale: why the repository's dry run is stale, "" when it is fresh.

    Returns:
        Why the hub offers no delete: a stale dry run, or from that dry run
        what keeps the branch (signing.local_keeps, the predicate the host
        runner refuses by, then the local upstream), or that it has not
        planned this tip yet; "" when it deletes exactly the local branch at
        this tip.
    """
    if stale:
        return f"pkgmgr branch cleanup --local plan stale: {stale}; use branch gc ({GC_SKILL}, pkgmgr gc)"
    if planned is None or planned.get("local_sha") != tip:
        return f"no pkgmgr branch cleanup --local dry run of {tip[:12]} yet: the tree timer writes {LOCAL_PLAN} within a minute"
    keeps = signing.local_keeps(planned) or (f"kept: local upstream of {upstream_of}" if upstream_of else "")
    return f"pkgmgr branch cleanup --local keeps it: {keeps}; use branch gc ({GC_SKILL}, pkgmgr gc)" if keeps else ""


def local_upstreams(items: list[dict]) -> dict[str, str]:
    """Args:
        items: one repository's items of the `--local` dry run, each with
            its `%(upstream:short)` as upstream.

    Returns:
        Each branch that is the local upstream of another branch there, with
        the first such branch by name, as pkgmgr's _config_keeps names it.
    """
    names = {item["branch"] for item in items}
    found: dict[str, str] = {}
    for item in sorted(items, key=lambda entry: entry["branch"]):
        upstream = str(item.get("upstream") or "")
        parent = upstream if upstream in names else upstream.removeprefix("heads/")
        if parent in names and parent != item["branch"]:
            found.setdefault(parent, item["branch"])
    return found


def dry_run(item: dict, kept: str) -> list[str]:
    """Args:
        item: one tree item.
        kept: kept_by() for it, "" when the hub offers its delete.

    Returns:
        What the runner's `pkgmgr branch cleanup` does for one tree item,
        read from the gc plan the tree file carries: it deletes the local
        branch and never touches a worktree, Compose stack or volume; a
        remote branch stays, the runner refuses a plan that deletes one. A
        branch held by a worktree it skips, and one the `--local` dry run
        keeps or has not planned it does not delete; their lines name what
        branch gc would do instead, its `docker compose down -v` deleting
        the stack's volumes.
    """
    tip = (item["local_sha"] or item["head"] or "")[:12]
    merged = f", merged by {item['merged_by']}" if item["merged_by"] else ""
    lines = [f"{item['branch']} @ {tip}: {item['state']}{merged}"]
    if item["worktree"]:
        lines.append(held_by(item["worktree"]))
        lines.append(f"branch gc would remove the worktree {item['worktree']} and the local branch {item['branch']}")
        lines += [f"branch gc would run {' '.join(GC_COMPOSE_DOWN).format(project=name)}, which deletes the volumes of {name}" for name in item["compose_projects"]]
        lines += [f"branch gc would remove the image {name}" for name in item["images"]]
        return lines
    if kept:
        lines.append(kept)
        lines += [f"branch gc would delete the local branch {item['branch']}" if action == "local-branch" else f"branch gc would delete {action}" for action in item["actions"]]
        return lines
    for action in item["actions"]:
        if action == "local-branch":
            lines.append(f"deletes the local branch {item['branch']}")
        elif action.startswith("remote"):
            lines.append(f"stays: {action} (local only; the host refuses a plan that deletes it)")
        else:
            lines.append(action)
    return lines


def branch(item: dict, path: str, default: object, planned: dict | None, upstream_of: str, stale: str) -> dict:
    """Args:
        item: one tree item with a branch.
        path: its repository's path.
        default: the repository's default branch.
        planned: the branch's item of the `--local` dry run, None without.
        upstream_of: as kept_by() takes it.
        stale: as kept_by() takes it.
    """
    remote = next(iter(item["remotes"].values()), "")
    head = item["local_sha"] or item["head"] or remote
    held = held_by(item["worktree"]) if item["worktree"] and item["state"] == "merged-clean" else ""
    candidate = item["state"] == "merged-clean" and bool(item["local_sha"]) and not item["worktree"]
    kept = kept_by(planned, item["local_sha"], upstream_of, stale) if candidate else ""
    open_to_delete = candidate and not item["skip"] and not kept
    return {
        "held": held,
        "kept": kept,
        "token_free": signing.token_free(planned, default) if candidate and planned is not None else False,
        "name": item["branch"],
        "head": head,
        "upstream": item["upstream"] or "",
        "ahead": item["ahead"] or 0,
        "behind": item["behind"] or 0,
        "gone": item["gone"],
        "state": item["state"],
        "merged_by": item["merged_by"],
        "merged_into": item["merged_into"],
        "skip": item["skip"],
        "reason": item["reason"],
        "plan": dry_run(item, kept),
        "cleanup": signing.cleanup_item(path, item["branch"], item["worktree"] or "", item["local_sha"]) if open_to_delete else None,
        "worktrees": [worktree(item)] if item["worktree"] else [],
    }


def repo(entry: dict, local: dict[tuple[str, str], tuple[dict, str]], stale: dict[str, str]) -> dict:
    items = entry["items"]
    return {
        **{key: value for key, value in entry.items() if key != "items"},
        "name": "/".join(Path(entry["path"]).parts[-LABEL_PARTS:]),
        "branches": [branch(item, entry["path"], entry.get("default"), *local.get((entry["path"], item["branch"]), (None, "")), stale.get(entry["path"], "")) for item in items if item["branch"]],
        "detached": [worktree(item) for item in items if item["detached"]],
    }


def local_plan(path: Path) -> tuple[dict[tuple[str, str], tuple[dict, str]], dict[str, str]]:
    """Returns:
        Every item of the `pkgmgr branch cleanup --local` dry run that
        client/local_plan.py writes at path, keyed by repository path and
        branch, with the branch whose local upstream it is (local_upstreams,
        "" for none); and each repository whose dry run is stale, with why.
        Both are empty when the file is missing or unreadable, so the hub
        offers no delete.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        found, stale = {}, {}
        for repository in data["repos"]:
            items = [item for item in repository["items"] if isinstance(item, dict) and isinstance(item.get("branch"), str)]
            upstreams = local_upstreams(items)
            found.update({(repository["repo"], item["branch"]): (item, upstreams.get(item["branch"], "")) for item in items})
            if repository.get("stale"):
                stale[repository["repo"]] = str(repository["stale"])[:200]
        return found, stale
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {}, {}


def offered(scan: dict, ready: bool) -> list[dict]:
    """Args:
        scan: the tree.
        ready: whether pkgmgr holds the GitHub token.

    Returns:
        The cleanup items deletable now: every one with the token, without
        it only those of token-free branches.
    """
    return [entry["cleanup"] for repository in scan["repos"] for entry in repository["branches"] if entry["cleanup"] is not None and (ready or entry["token_free"])]


def read_tree(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        local, stale = local_plan(path.with_name(LOCAL_PLAN))
        return {
            "repos": sorted((repo(entry, local, stale) for entry in data["repos"]), key=lambda entry: entry["name"]),
            "scanned": iso_epoch(data["generated_at"]),
            "delete_ready": data["delete_ready"],
            "delete_reason": data["delete_reason"],
        }
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        return {"repos": [], "scanned": None, "error": f"pkgmgr tree file {path} unreadable: {error}"}


def inside(path: str, folder: str) -> bool:
    return path == folder or path.startswith(f"{folder.rstrip('/')}/")


def owns(row: dict, path: str, name: str) -> bool:
    workdir = row.get("workdir")
    if isinstance(workdir, str):
        return workdir.startswith("/") and inside(workdir, path)
    return row.get("branch") == name


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
                held = sorted(task for task, row in current.items() if owns(row, tree["path"], item["name"]))
                for task in held:
                    workers |= holders[task]
                open_work = [*tree["open_work"], "task"] if held else tree["open_work"]
                trees.append({**tree, "workers": sorted(workers, key=str.lower), "review": latest.get(tree["path"]), "tasks": held, "open_work": open_work})
            branches.append({**item, "worktrees": trees})
        repos.append({**entry, "branches": branches, "detached": [{**tree, "workers": [], "review": latest.get(tree["path"]), "tasks": []} for tree in entry["detached"]]})
    return {**scan, "repos": repos}


@dataclass
class Tree:
    file: Path
    heartbeat: Path
    lock: threading.Lock
    cached: dict | None
    stamp: tuple[tuple[int, int], tuple[int, int] | None] | None

    def beat(self) -> None:
        self.heartbeat.touch()

    def get(self) -> dict:
        with self.lock:
            try:
                info = self.file.stat()
            except OSError as error:
                return {"repos": [], "scanned": None, "error": (
                    f"no pkgmgr tree file at {self.file}: {error.strerror}. The tree timer runs `pkgmgr branch tree`, which the installed pkgmgr "
                    "lacks until a release ships it: release pkgmgr and install it, then the timer writes the file within a minute."
                )}
            try:
                planned = self.file.with_name(LOCAL_PLAN).stat()
                plan_stamp = (planned.st_mtime_ns, planned.st_size)
            except OSError:
                plan_stamp = None
            stamp = ((info.st_mtime_ns, info.st_size), plan_stamp)
            if self.cached is None or stamp != self.stamp:
                self.cached, self.stamp = read_tree(self.file), stamp
            return self.cached
