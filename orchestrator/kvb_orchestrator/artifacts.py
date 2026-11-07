from __future__ import annotations

import itertools
import re
import threading
from collections.abc import Callable
from pathlib import Path

from .records import epoch, iso_epoch, read_json, shown
from .register import ENDED, status_of
from .tree import inside, owns

PUSH = re.compile(r"\b(?:push|gipsn|git-sign-push)\b")
GATES = ("gate", "test")
LANE_LIMIT = 200
SHARED_SHOWN = 20
TITLE_LIMIT = 160


def artefacts_of(task: str, row: dict) -> list[dict]:
    listed = row.get("artifacts")
    found = []
    for entry in listed if isinstance(listed, list) else []:
        ref = entry.get("ref") if isinstance(entry, dict) else None
        if isinstance(ref, str) and ":" in ref.strip(":"):
            kind, _, name = ref.partition(":")
            found.append({"task": task, "ref": ref, "kind": kind, "name": name, "added": shown(entry.get("added")), "ended": status_of(row) in ENDED})
    return found


def lane(paths: list[str], reviews: list[dict], history: list[dict], jobs: list[dict]) -> list[dict]:
    """Args:
        paths: the worktree paths of one branch.
        reviews: the hub's reviews; an approved one stands for the commit
            the agent makes right after the approval.
        history: queue-history.jsonl rows; test and gate kinds count as gates.
        jobs: the runner jobs; a push command counts as a push.

    Returns:
        The branch's swimlane events, oldest first, each with ts, kind
        (commit, review, gate or push), title and ok (true, false or None).
    """
    def mine(path: object) -> bool:
        return isinstance(path, str) and any(inside(path, folder) for folder in paths)

    events = []
    for review in (review for review in reviews if mine(review.get("worktree"))):
        created, title = iso_epoch(review.get("created")), shown(review.get("title"))[:TITLE_LIMIT]
        events.append({"ts": created, "kind": "review", "title": title, "ok": None})
        if review.get("gate") in ("pass", "fail"):
            events.append({"ts": created, "kind": "gate", "title": f"Gate {review['gate']}: {title}", "ok": review["gate"] == "pass"})
        if review.get("status") == "approved":
            events.append({"ts": iso_epoch(review.get("decided")), "kind": "commit", "title": title, "ok": True})
    for row in (row for row in history if mine(row.get("workdir")) and str(row.get("kind", "")).startswith(GATES)):
        events.append({"ts": epoch(row.get("end")) or epoch(row.get("start")), "kind": "gate", "title": shown(row.get("kind")), "ok": row.get("exit") == 0})
    for job in (job for job in jobs if mine(job.get("directory")) and PUSH.search(str(job.get("command", "")))):
        finished = job.get("status") in ("done", "failed", "refused")
        when = epoch(job.get("finished")) or epoch(job.get("started")) or epoch(job.get("created_ts"))
        events.append({"ts": when, "kind": "push", "title": shown(job.get("command"))[:TITLE_LIMIT], "ok": job.get("status") == "done" if finished else None})
    return sorted((event for event in events if event["ts"] is not None), key=lambda event: event["ts"])[-LANE_LIMIT:]


class Touched:
    def __init__(self, stored: Callable[[str, str], Path]) -> None:
        """Args:
            stored: maps a review id and suffix to its stored file; the
                .json lists the files the review touched and never changes,
                so each is read once.
        """
        self.stored = stored
        self.lock = threading.Lock()
        self.known: dict[str, frozenset[str]] = {}

    def of(self, review_id: str) -> frozenset[str]:
        with self.lock:
            if review_id not in self.known:
                data = read_json(self.stored(review_id, ".json"))
                files = data.get("files") if isinstance(data, dict) else None
                self.known[review_id] = frozenset(entry["path"] for entry in files or [] if isinstance(entry, dict) and isinstance(entry.get("path"), str) and entry["path"])
            return self.known[review_id]


def enrich(scan: dict, tasks: dict[str, dict], reviews: list[dict], touched: Touched, history: list[dict], jobs: list[dict]) -> dict:
    """Returns:
        The scan with each worktree's register artefacts, the tasks whose
        artefacts belong to no worktree, each branch's touched files and
        swimlane events, and per repository the file overlaps between
        branches and the merges the gc classification names.
    """
    placed: set[str] = set()
    repos = []
    for entry in scan["repos"]:
        branches, files = [], {}
        for item in entry["branches"]:
            trees = []
            for tree in item["worktrees"]:
                held = [(task, row) for task, row in sorted(tasks.items()) if owns(row, tree["path"], item["name"])]
                placed.update(task for task, _ in held)
                trees.append({**tree, "artefacts": [found for task, row in held for found in artefacts_of(task, row)]})
            paths = [tree["path"] for tree in trees]
            files[item["name"]] = frozenset().union(*(touched.of(review["id"]) for review in reviews if isinstance(review.get("worktree"), str) and any(inside(review["worktree"], path) for path in paths)))
            branches.append({**item, "worktrees": trees, "files": len(files[item["name"]]), "events": lane(paths, reviews, history, jobs)})
        overlaps = []
        for a, b in itertools.combinations(sorted(files), 2):
            shared = sorted(files[a] & files[b])
            if shared:
                overlaps.append({"a": a, "b": b, "count": len(shared), "files": shared[:SHARED_SHOWN]})
        merges = [{"from": item["name"], "into": item["merged_into"] or entry.get("default") or "", "by": item["merged_by"]} for item in entry["branches"] if item["merged_by"]]
        repos.append({**entry, "branches": branches, "overlaps": overlaps, "merges": merges})
    loose = [{"task": task, "title": shown(row.get("title")), "status": status_of(row), "artefacts": artefacts_of(task, row)} for task, row in sorted(tasks.items()) if task not in placed and artefacts_of(task, row)]
    return {**scan, "repos": repos, "tasks": loose}
