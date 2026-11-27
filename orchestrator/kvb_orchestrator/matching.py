from __future__ import annotations

import json
import time

from .council import NEWS, read_claims
from .denying import LAPSED, requester_of
from .diffs import stored_diff
from .errors import Conflict, Missing, ToolError
from .fields import decode, expect, field
from .jobs import blocked_kinds, row_blocked, row_blocked_kind
from .payloads import denied_roots, payload_files, payload_hash
from .previewing import TREE, merge_hash, preview_line
from .records import digest, iso_epoch, read_jsonl
from .register import REGISTER, adder, operator_rows, read_register
from .scores import metric_chips, score_labels
from .signed import signing
from .tree import inside

OPERATOR = "operator/"
WAITING = ("ask", "decision", "rule")
EXPIRED = "expired"
EXPIRED_REASONS = {
    "ask": f"{LAPSED.capitalize()}: its tool call went back to the terminal, only Reject is left",
    "decision": f"{LAPSED.capitalize()}: its agent stopped waiting for the answer, only Reject is left",
}


def expired_card(card: dict, expires: float) -> dict:
    """Args:
        card: the waiting_card() of an ask or decision lapsed_of() keeps.
        expires: when it expired, in epoch seconds.

    Returns:
        The card greyed with blocked_kind EXPIRED, the EXPIRED_REASONS line of
        its kind and its expires time.
    """
    return {**card, "blocked": EXPIRED_REASONS[card["kind"]], "blocked_kind": EXPIRED, "expires": expires}


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
        """Returns:
            {"now", "cards"}: every card waiting on the operator, none held
            by a release in its undo window or while it applies; a held
            command card keeps its snapshot, so an undo shows it unchanged;
            an expired ask or decision stays, greyed by expired_card(),
            until the operator denies it.
        """
        now = time.time()
        claims = read_claims(self.council)
        names = self.names.listed()
        reviews = self.reviews.pending()
        labels = score_labels(self.scripts.skills)
        senders = {review["id"]: review.get("agent", "") for review in reviews}
        cards = [{**self.commit_card(review, born_of(senders[review["id"]], names, claims), labels), "to": requester_of(claims, senders[review["id"]])[0]} for review in reviews if not self.batches.holds("review", review["id"])]
        tasks = read_register(self.council / REGISTER)
        blocked = self.blocked_rows(now)
        kinds = blocked_kinds(self.jobs.listed())
        rows = [row for row in operator_rows(tasks) if row["check"] != "decision"]
        releasing = {f"operator:{row['task']}" for row in rows if self.batches.holds("operator", row["task"])}
        roots = denied_roots(self.settings_files()[0])
        scan = self.tree.get()
        for row in rows:
            if f"operator:{row['task']}" in releasing:
                continue
            owner = adder(tasks[row["task"]])
            cards.append({**self.command_card(row, owner, born_of(owner, names, claims), roots, scan, labels), "to": requester_of(claims, owner)[0], "blocked": row_blocked(row, blocked), "blocked_kind": row_blocked_kind(row, kinds)})
        directory = self.directory(claims, read_jsonl(self.council / NEWS), now)
        items = self.inbox(now, tasks, directory)
        cards += [self.waiting_card(item, born_of(item["agent"], names, claims), scan, labels) for item in items if self.waits(item)]
        cards += [expired_card(self.waiting_card(item, born_of(item["agent"], names, claims), scan, labels), item["expires"]) for item in self.lapsed_items(now, directory) if self.waits(item)]
        asked = {row["task"] for row in operator_rows(tasks) if row["check"] == "decision"}
        for answer in self.answers.listed():
            if answer["id"] not in asked:
                self.answers.remove(answer["id"])
        listed = {card["id"] for card in cards} | releasing
        for store in (self.match_snapshots, self.merge_previews):
            for snapshot in store.listed():
                if snapshot["id"] not in listed:
                    store.remove(snapshot["id"])
        return {"now": now, "cards": cards}

    def match_open(self, inbox: list[dict]) -> int:
        """Returns:
            How many cards match_cards() lists that can be decided, by its
            filters without building them: pending reviews, open command rows
            not held by a release and without a row_blocked() reason, and the
            inbox items waits() keeps.
        """
        reviews = sum(1 for review in self.reviews.pending() if not self.batches.holds("review", review["id"]))
        rows = sum(1 for row in self.open_rows() if not self.batches.holds("operator", row["task"]) and not row_blocked(row, {}))
        return reviews + rows + sum(1 for item in inbox if self.waits(item))

    def commit_card(self, review: dict, born: float | None, labels: dict | None) -> dict:
        live = review.get("live_tree")
        reason = "the staged tree changed since it was added" if live not in (None, review["tree"]) else ""
        try:
            files = stored_diff(self.reviews.pages, "review", review["id"])["diff"]
        except Missing:
            files = None
        preview = self.review_preview(review["id"])
        if preview is not None:
            files = preview.get("diff")
            reason = reason or ("HEAD moved since it was added" if preview.get("moved") else "")
        place = {"repo": repository_of(review.get("repo", "")), "branch": review["branch"], "worktree": review["worktree"]}
        return {
            "id": f"review:{review['id']}", "kind": "commit", "ref": review["id"], "agent": review.get("agent", ""), "born": born, "created_ts": iso_epoch(review["created"]),
            **place, "title": review["title"], "score": review.get("score", ""), "metrics": metric_chips(review.get("score", ""), labels, True), "gate": review.get("gate", ""),
            "hash": review["tree"], "live_hash": live or review["tree"],
            "stale": bool(reason), "stale_reason": reason, "files": files, "command": "", "directory": review["worktree"], "reason": "",
            "diff_error": None if preview is None else preview.get("error"),
        }

    def card_payload(self, row: dict, roots: list[str] | None) -> tuple[list[dict], str, dict | None]:
        """Returns:
            What a command card shows and is bound to: the runner's merge
            preview diff and merge_hash() for a git merge or commit-tree it previewed, else
            the named payload files and payload_hash(); and the preview.
        """
        preview = self.preview_of(row)
        if preview is not None:
            return preview.get("diff", []), merge_hash(row, preview), preview
        files = payload_files(row["command"], row["directory"], roots)
        return files, payload_hash(row["command"], row["directory"], files), None

    def waits(self, item: dict) -> bool:
        """Returns:
            Whether an inbox item is a Match card of its own: an ask, a
            choice, a rule request, or a decision row not yet answered with
            its current question, none held by a release in its undo window
            nor snoozed in Waits on Operator; commits and commands have their
            own cards.
        """
        if item["held"] or item["until"]:
            return False
        if item["kind"] == "operator":
            return item["check"] == "decision" and not item["settled"] and item["job"] is None and not item["answered"]
        return item["kind"] in WAITING

    def waiting_card(self, item: dict, born: float | None, scan: dict, labels: dict | None) -> dict:
        """Args:
            item: an inbox item waits() keeps.
            born: when its agent was first seen.
            scan: the branch tree.
            labels: the score labels.

        Returns:
            Its card: kind ask, decision (a choice or a decision row) or rule;
            entry names the inbox kind a release signs, metrics the scores
            its question, command or reason carries.
        """
        files = []
        if item["kind"] == "ask" and item["diff"]:
            try:
                files = stored_diff(self.reviews.pages, "ask", item["id"])["diff"]
            except Missing:
                files = None
        preview = self.ask_preview(item["id"]) if item["kind"] == "ask" and item["diff"] is None else None
        if preview is not None:
            files = preview.get("diff", [])
        repo, branch, worktree = place_of(item["directory"], scan) if item["directory"] else ("", "", "")
        shown = digest(json.dumps([item["title"], item["command"], item["detail"], item["options"], item["rule"]], sort_keys=True))
        return {
            "id": f"{item['kind']}:{item['id']}", "kind": "decision" if item["kind"] == "operator" else item["kind"], "entry": item["kind"], "ref": item["id"], "agent": item["agent"], "to": item["to"],
            "born": born, "created_ts": item["ts"], "repo": repo, "branch": branch, "worktree": worktree, "title": item["title"], "score": "",
            "metrics": metric_chips("\n".join((item["title"], item["command"], item["detail"])), labels, False), "gate": "", "hash": shown, "live_hash": shown, "stale": False, "stale_reason": "",
            "files": files, "command": item["command"], "directory": item["directory"], "reason": item["detail"], "sha256": item["sha256"], "options": item["options"],
            "recommended": item["recommended"], "multi": item["multi"], "warnings": item["warnings"], "rule": item["rule"], "dry_run": item["dry_run"], "merge": preview_line(preview),
        }

    def command_card(self, row: dict, agent: str, born: float | None, roots: list[str] | None, scan: dict, labels: dict | None) -> dict:
        card_id = f"operator:{row['task']}"
        files, live, preview = self.card_payload(row, roots)
        snapshot = self.match_snapshots.get(card_id)
        if snapshot is None or snapshot["command_sha256"] != digest(row["command"]) or (preview is not None and not snapshot.get("previewed")):
            self.match_snapshots.remove(card_id)
            snapshot = self.match_snapshots.insert(card_id, {"command_sha256": digest(row["command"]), "hash": live, "files": files, "previewed": preview is not None, "taken": time.time()})
        stale = snapshot["hash"] != live
        merge = preview_line(preview)
        moved = "a payload file changed since it was added" if merge is None else "its diff changed since it was added" if merge["kind"] == TREE else "HEAD or the merge base moved since it was added"
        repo, branch, worktree = place_of(row["directory"], scan)
        return {
            "id": card_id, "kind": "command", "ref": row["task"], "agent": agent, "born": born, "created_ts": snapshot["taken"], "repo": repo, "branch": branch, "worktree": worktree,
            "title": row["command"], "score": "", "metrics": metric_chips(f"{row['command']}\n{row['why']}", labels, False), "gate": "", "hash": snapshot["hash"], "live_hash": live, "stale": stale,
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
