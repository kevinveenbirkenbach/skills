from __future__ import annotations

import json
import re
import time

from .diffs import valid_diff
from .errors import Conflict, Missing, ToolError
from .fields import bounded, decode, expect
from .records import digest
from .register import OPERATOR, REGISTER, operator_rows, read_register
from .signed import signing

OBJECT_ID = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
ERROR_LIMIT = 500
SHOWN = ("task", "command", "head", "base", "target", "diff")
FAILED = ("task", "command", "head", "error")


def card_id(task: str) -> str:
    return f"operator:{task}"


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

    def preview_rows(self) -> dict:
        """Returns:
            {"rows"}: every open operator row in an absolute directory with
            the HEAD of the preview the hub holds, None for none, for the
            runner to preview the git merges among them.
        """
        rows = [row for row in self.open_rows() if row["directory"].startswith("/")]
        return {"rows": [{"task": row["task"], "command": row["command"], "directory": row["directory"], "head": (self.preview_of(row) or {}).get("head")} for row in rows]}

    def record_preview(self, body: bytes) -> dict:
        """Args:
            body: from the runner, {task, command, head, base, target, diff}
                for a git merge row, or {task, command, head, error} when it
                could not preview it; head is empty when HEAD is unreadable.
        """
        payload = decode(body)
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
