from __future__ import annotations

import time

from .council import read_claims
from .denying import requester_of
from .diffs import stored_diff
from .errors import Conflict, Missing, ToolError
from .fields import decode, expect, field
from .payloads import denied_roots, payload_files, payload_hash
from .previewing import merge_hash
from .records import digest, iso_epoch
from .register import REGISTER, adder, operator_rows, read_register
from .scores import metric_chips, score_labels
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
        labels = score_labels(self.scripts.skills)
        cards = [{**self.commit_card(review, reviews, born_of(review.get("agent", ""), names, claims), labels), "to": requester_of(claims, review.get("agent", ""))[0]} for review in reviews]
        tasks = read_register(self.council / REGISTER)
        held = self.open_jobs()
        rows = [row for row in operator_rows(tasks) if row["check"] != "decision" and row["task"] not in held]
        roots = denied_roots(self.settings_files()[0])
        scan = self.tree.get()
        for row in rows:
            agent = adder(tasks[row["task"]])
            cards.append({**self.command_card(row, agent, born_of(agent, names, claims), roots, scan), "to": requester_of(claims, agent)[0]})
        listed = {card["id"] for card in cards}
        for store in (self.match_snapshots, self.merge_previews):
            for snapshot in store.listed():
                if snapshot["id"] not in listed:
                    store.remove(snapshot["id"])
        return {"now": now, "cards": cards}

    def commit_card(self, review: dict, reviews: list[dict], born: float | None, labels: dict | None) -> dict:
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
            **place, "title": review["title"], "score": review.get("score", ""), "metrics": metric_chips(review.get("score", ""), labels), "gate": review.get("gate", ""),
            "hash": review["tree"], "live_hash": live or review["tree"],
            "stale": bool(reason), "stale_reason": reason, "files": files, "command": "", "directory": review["worktree"], "reason": "",
        }

    def card_payload(self, row: dict, roots: list[str] | None) -> tuple[list[dict], str, dict | None]:
        """Returns:
            What a command card shows and is bound to: the runner's merge
            preview diff and merge_hash() for a git merge it previewed, else
            the named payload files and payload_hash(); and the preview.
        """
        preview = self.preview_of(row)
        if preview is not None:
            return preview.get("diff", []), merge_hash(row, preview), preview
        files = payload_files(row["command"], row["directory"], roots)
        return files, payload_hash(row["command"], row["directory"], files), None

    def command_card(self, row: dict, agent: str, born: float | None, roots: list[str] | None, scan: dict) -> dict:
        card_id = f"operator:{row['task']}"
        files, live, preview = self.card_payload(row, roots)
        snapshot = self.match_snapshots.get(card_id)
        if snapshot is None or snapshot["command_sha256"] != digest(row["command"]) or (preview is not None and not snapshot.get("previewed")):
            self.match_snapshots.remove(card_id)
            snapshot = self.match_snapshots.insert(card_id, {"command_sha256": digest(row["command"]), "hash": live, "files": files, "previewed": preview is not None, "taken": time.time()})
        stale = snapshot["hash"] != live
        moved = "HEAD or the merge base moved since it was added" if preview is not None else "a payload file changed since it was added"
        merge = None if preview is None else {key: preview.get(key, "") for key in ("head", "base", "target", "error")}
        repo, branch, worktree = place_of(row["directory"], scan)
        return {
            "id": card_id, "kind": "command", "ref": row["task"], "agent": agent, "born": born, "created_ts": snapshot["taken"], "repo": repo, "branch": branch, "worktree": worktree,
            "title": row["command"], "score": "", "metrics": [], "gate": "", "hash": snapshot["hash"], "live_hash": live, "stale": stale,
            "stale_reason": moved if stale else "", "files": snapshot["files"], "command": row["command"], "directory": row["directory"],
            "reason": row["why"], "sha256": digest(row["command"]), "merge": merge,
        }

    def live_payload(self, row: dict) -> str:
        return self.card_payload(row, denied_roots(self.settings_files()[0]))[1]

    def payload_bound(self, row: dict, shown: object) -> list[dict]:
        """Args:
            row: the open operator row a Match release approves.
            shown: the payload hash its card showed the operator.

        Returns:
            The match item binding the approval to that hash.

        Raises:
            ToolError for a hash that is no hex digest; Conflict when the
            card's snapshot is gone or retaken, or a payload file changed
            since the card showed it.
        """
        if not isinstance(shown, str) or not signing.HASH.fullmatch(shown):
            raise ToolError("payload must be the hash the card showed")
        snapshot = self.match_snapshots.get(f"operator:{row['task']}")
        if snapshot is None or snapshot["command_sha256"] != digest(row["command"]) or snapshot["hash"] != shown or self.live_payload(row) != shown:
            raise Conflict({"id": row["task"], "status": "stale"})
        return [signing.match_item(f"operator:{row['task']}", shown)]

    def payload_holds(self, bound: dict) -> bool:
        task = bound["id"].removeprefix("operator:")
        row = next((row for row in operator_rows(read_register(self.council / REGISTER)) if row["task"] == task), None)
        return row is not None and self.live_payload(row) == bound["hash"]

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
