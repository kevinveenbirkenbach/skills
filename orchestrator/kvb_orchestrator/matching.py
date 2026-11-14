from __future__ import annotations

import time

from .council import read_claims
from .diffs import stored_diff
from .errors import Missing, ToolError
from .fields import decode, expect, field
from .payloads import denied_roots, payload_files, payload_hash
from .records import digest, iso_epoch
from .register import REGISTER, adder, operator_rows, read_register
from .signed import signing
from .tree import inside

OPERATOR = "operator/"


def repository_of(common_dir: str) -> str:
    return common_dir.removesuffix("/.git") if common_dir.endswith("/.git") else common_dir


def born_of(agent: str, names: list[dict], claims: list[dict]) -> float | None:
    """Returns:
        When the agent was first seen: its earliest name sighting, else its
        earliest claim; None when neither knows it.
    """
    seen = [entry["first_seen"] for entry in names if entry["name"] == agent and isinstance(entry.get("first_seen"), int | float)]
    claimed = [iso_epoch(claim["since"]) for claim in claims if agent and agent in (claim["agent"], claim["session"])]
    found = seen or [moment for moment in claimed if moment is not None]
    return min(found) if found else None


def place_of(directory: str, scan: dict) -> tuple[str, str, str]:
    """Returns:
        The repository, branch and worktree of the deepest worktree of the
        branch tree that holds directory; empty texts outside every one.
    """
    found = [(repo["path"], branch["name"], tree["path"]) for repo in scan.get("repos", []) for branch in repo["branches"] for tree in branch["worktrees"] if tree["path"] and inside(directory, tree["path"])]
    return max(found, key=lambda place: len(place[2])) if found else ("", "", directory)


class Matching:
    def match_cards(self) -> dict:
        now = time.time()
        claims = read_claims(self.council)
        names = self.names.listed()
        reviews = self.reviews.pending()
        cards = [self.commit_card(review, reviews, born_of(review.get("agent", ""), names, claims)) for review in reviews]
        tasks = read_register(self.council / REGISTER)
        held = self.open_jobs()
        rows = [row for row in operator_rows(tasks) if row["check"] != "decision" and row["task"] not in held]
        roots = denied_roots(self.settings_files()[0])
        scan = self.tree.get()
        for row in rows:
            agent = adder(tasks[row["task"]])
            cards.append(self.command_card(row, agent, born_of(agent, names, claims), roots, scan))
        listed = {card["id"] for card in cards}
        for snapshot in self.match_snapshots.listed():
            if snapshot["id"] not in listed:
                self.match_snapshots.remove(snapshot["id"])
        return {"now": now, "cards": cards}

    def commit_card(self, review: dict, reviews: list[dict], born: float | None) -> dict:
        newer = [other["id"] for other in reviews if other["created"] > review["created"] and (other["worktree"], other["branch"]) == (review["worktree"], review["branch"])]
        live = review.get("live_tree")
        reason = f"added again as review:{newer[-1]}" if newer else "the staged tree changed since it was added" if live not in (None, review["tree"]) else ""
        try:
            files = stored_diff(self.reviews.pages, "review", review["id"])["diff"]
        except Missing:
            files = None
        place = {"repo": repository_of(review.get("repo", "")), "branch": review["branch"], "worktree": review["worktree"]}
        return {
            "id": f"review:{review['id']}", "kind": "commit", "ref": review["id"], "agent": review.get("agent", ""), "born": born, "created_ts": iso_epoch(review["created"]),
            **place, "title": review["title"], "score": review.get("score", ""), "gate": review.get("gate", ""), "hash": review["tree"], "live_hash": live or review["tree"],
            "stale": bool(reason), "stale_reason": reason, "files": files, "command": "", "directory": review["worktree"], "reason": "",
        }

    def command_card(self, row: dict, agent: str, born: float | None, roots: list[str] | None, scan: dict) -> dict:
        card_id = f"operator:{row['task']}"
        files = payload_files(row["command"], row["directory"], roots)
        live = payload_hash(row["command"], row["directory"], files)
        snapshot = self.match_snapshots.get(card_id)
        if snapshot is None or snapshot["command_sha256"] != digest(row["command"]):
            self.match_snapshots.remove(card_id)
            snapshot = self.match_snapshots.insert(card_id, {"command_sha256": digest(row["command"]), "hash": live, "files": files, "taken": time.time()})
        stale = snapshot["hash"] != live
        repo, branch, worktree = place_of(row["directory"], scan)
        return {
            "id": card_id, "kind": "command", "ref": row["task"], "agent": agent, "born": born, "created_ts": snapshot["taken"], "repo": repo, "branch": branch, "worktree": worktree,
            "title": row["command"], "score": "", "gate": "", "hash": snapshot["hash"], "live_hash": live, "stale": stale,
            "stale_reason": "a payload file changed since it was added" if stale else "", "files": snapshot["files"], "command": row["command"], "directory": row["directory"],
            "reason": row["why"], "sha256": digest(row["command"]),
        }

    def match_stale(self, body: bytes) -> dict:
        """Args:
            body: {"id", "tree"}: a pending review and the tree git
                write-tree prints in its worktree now; a tree other than the
                review's marks its card stale.
        """
        payload = decode(body)
        expect(payload, ("id", "tree"))
        review_id, tree = field(payload, "id"), field(payload, "tree")
        review = self.reviews.get(review_id)
        if review is None or review["status"] != "pending":
            raise Missing(review_id)
        self.reviews.change(review_id, {"live_tree": tree})
        return {"id": review_id, "stale": tree != review["tree"]}

    def match_snapshot(self, body: bytes) -> dict:
        """Args:
            body: {"task"}: an open operator row whose card takes its payload
                files as they are now.
        """
        payload = decode(body)
        expect(payload, ("task",))
        task = payload["task"]
        if not isinstance(task, str) or not task.startswith(OPERATOR) or not signing.TASK.fullmatch(task):
            raise ToolError("task must be an operator row")
        self.match_snapshots.remove(f"operator:{task}")
        card = next((card for card in self.match_cards()["cards"] if card["id"] == f"operator:{task}"), None)
        if card is None:
            raise Missing(task)
        return {"id": card["id"], "hash": card["hash"], "stale": card["stale"]}
