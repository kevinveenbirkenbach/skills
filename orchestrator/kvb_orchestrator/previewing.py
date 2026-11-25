from __future__ import annotations

import json
import re
import time

from .diffs import stored_diff, valid_diff
from .errors import Conflict, Missing, ToolError
from .fields import bounded, decode, expect, field
from .records import digest
from .register import OPERATOR, REGISTER, operator_rows, read_register
from .signed import signing

OBJECT_ID = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
ERROR_LIMIT = 500
SHOWN = ("task", "command", "head", "base", "target", "diff")
FAILED = ("task", "command", "head", "error")
REVIEW_SHOWN = ("id", "head", "diff")
REVIEW_FAILED = ("id", "head", "error")


def card_id(task: str) -> str:
    return f"operator:{task}"


def review_card(review_id: str) -> str:
    return f"review:{review_id}"


def object_id(payload: dict, name: str, empty: bool) -> str:
    value = payload[name]
    if not isinstance(value, str) or not (OBJECT_ID.fullmatch(value) or (empty and value == "")):
        raise ToolError(f"{name} must be a full git object id")
    return value


def merge_hash(row: dict, preview: dict) -> str:
    """Returns:
        The sha256 a merge card is bound to: its command, directory, the
        HEAD, merge base and target the runner previewed and the digest of
        the diff or the error it sent.
    """
    shown = {key: preview.get(key, "") for key in ("head", "base", "target", "error")}
    return signing.item_hash({"kind": "merge", "command": row["command"], "directory": row["directory"], **shown, "diff": digest(json.dumps(preview.get("diff", []), sort_keys=True))})


class Previewing:
    def open_rows(self) -> list[dict]:
        held = self.open_jobs()
        return [row for row in operator_rows(read_register(self.council / REGISTER)) if row["check"] != "decision" and row["task"] not in held]

    def preview_of(self, row: dict) -> dict | None:
        """Returns:
            The runner's merge preview of the row's command, None when it
            sent none for this command.
        """
        found = self.merge_previews.get(card_id(row["task"]))
        return found if found is not None and found["command"] == row["command"] else None

    def shipped(self, review_id: str) -> bool:
        try:
            return bool(stored_diff(self.reviews.pages, "review", review_id)["diff"])
        except Missing:
            return False

    def review_preview(self, review_id: str) -> dict | None:
        """Returns:
            The runner's diff of a review that shipped none, its staged tree
            against its worktree's HEAD: {head, diff} or {head, error}, with
            moved, the HEAD it saw later, once HEAD moved; None before any.
        """
        return None if self.shipped(review_id) else self.merge_previews.get(review_card(review_id))

    def preview_rows(self) -> dict:
        """Returns:
            {"rows", "reviews"}: every open operator row in an absolute
            directory with the HEAD of the preview the hub holds, None for
            none, for the runner to preview the git merges among them; and
            every pending review in an absolute worktree that shipped no
            diff, with its tree and the HEAD the hub last saw, for the
            runner to diff the tree against HEAD.
        """
        rows = [row for row in self.open_rows() if row["directory"].startswith("/")]
        reviews = [review for review in self.reviews.pending() if review["worktree"].startswith("/") and not self.shipped(review["id"])]
        seen = {review["id"]: self.merge_previews.get(review_card(review["id"])) or {} for review in reviews}
        return {
            "rows": [{"task": row["task"], "command": row["command"], "directory": row["directory"], "head": (self.preview_of(row) or {}).get("head")} for row in rows],
            "reviews": [{"id": review["id"], "worktree": review["worktree"], "tree": review["tree"], "head": seen[review["id"]].get("moved") or seen[review["id"]].get("head")} for review in reviews],
        }

    def record_review_preview(self, payload: dict) -> dict:
        expect(payload, REVIEW_FAILED if "error" in payload else REVIEW_SHOWN)
        review_id = field(payload, "id")
        review = self.reviews.get(review_id)
        if review is None or review["status"] != "pending":
            raise Missing(review_id)
        head = object_id(payload, "head", "error" in payload)
        key = review_card(review_id)
        found = self.merge_previews.get(key)
        if found is not None and "diff" in found and found["head"] != head:
            self.merge_previews.change(key, {"moved": head})
            return {"id": key, "head": head}
        record = {"head": head, "taken": time.time()}
        if "error" in payload:
            record["error"] = bounded(payload, "error", ERROR_LIMIT)
        else:
            record["diff"] = valid_diff(payload["diff"])
        self.merge_previews.remove(key)
        self.merge_previews.insert(key, record)
        return {"id": key, "head": head}

    def record_preview(self, body: bytes) -> dict:
        """Args:
            body: from the runner, {task, command, head, base, target, diff}
                for a git merge row, or {task, command, head, error} when it
                could not preview it; {id, head, diff} or {id, head, error}
                for a review that shipped no diff; head is empty when HEAD is
                unreadable.
        """
        payload = decode(body)
        if "id" in payload:
            return self.record_review_preview(payload)
        expect(payload, FAILED if "error" in payload else SHOWN)
        task = payload["task"]
        if not isinstance(task, str) or not task.startswith(OPERATOR) or not signing.TASK.fullmatch(task):
            raise ToolError("task must be an operator row")
        row = next((row for row in self.open_rows() if row["task"] == task), None)
        if row is None:
            raise Missing(task)
        if payload["command"] != row["command"]:
            raise Conflict({"id": task, "status": "changed"})
        record = {"command": row["command"], "head": object_id(payload, "head", "error" in payload), "taken": time.time()}
        if "error" in payload:
            record["error"] = bounded(payload, "error", ERROR_LIMIT)
        else:
            record.update(base=object_id(payload, "base", False), target=object_id(payload, "target", False), diff=valid_diff(payload["diff"]))
        self.merge_previews.remove(card_id(task))
        self.merge_previews.insert(card_id(task), record)
        return {"id": card_id(task), "head": record["head"]}

    def previewed_head(self, task: str, command: str) -> str:
        found = self.merge_previews.get(card_id(task))
        return found["head"] if found is not None and found["command"] == command and "diff" in found else ""
