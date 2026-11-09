from __future__ import annotations

import time

from .errors import Conflict, Missing, ToolError
from .fields import decode, expect
from .jobs import TASK_JOB
from .register import REGISTER, read_register, status_of
from .signed import signing
from .tasks import editable

CHANGE_LIMIT = 100
CHANGE_KEYS = ("kind", "id", "argv")


def task_request(raw: object) -> bool:
    return isinstance(raw, list) and bool(raw) and all(isinstance(entry, dict) and entry.get("kind") == TASK_JOB for entry in raw)


def shown_command(argv: list[str]) -> str:
    return " ".join(["rasci.py", *argv])


class Tasking:
    def task_changes(self, raw: object) -> list[dict]:
        """Args:
            raw: the page's items, each {"kind": "task", "id", "argv"} with
                the rasci.py arguments of one priority pin, WSJF estimate or
                operator business value; a bulk change over a selection is
                one item per task under one passkey assertion.

        Returns:
            The signed items, each for an open register task outside
            operator/ and hotfix/ whose argv signing.task_argv() accepts.
        """
        if not isinstance(raw, list) or not 1 <= len(raw) <= CHANGE_LIMIT:
            raise ToolError(f"items must be a list of 1 to {CHANGE_LIMIT} task changes")
        tasks = read_register(self.council / REGISTER)
        signed: list[dict] = []
        for entry in raw:
            if not isinstance(entry, dict):
                raise ToolError("every item must be an object with kind, id and argv")
            expect(entry, CHANGE_KEYS)
            try:
                argv = signing.task_argv(entry["id"], entry["argv"])
            except signing.Refused as error:
                raise ToolError(f"{entry['id']!s:.200}: {error}") from None
            row = tasks.get(entry["id"])
            if row is None:
                raise Missing(entry["id"])
            if not editable(entry["id"], row):
                raise Conflict({"id": entry["id"], "status": status_of(row)})
            item = signing.task_item(entry["id"], argv)
            if item in signed:
                raise ToolError("items must be distinct")
            signed.append(item)
        return signed

    def change_tasks(self, body: bytes) -> dict:
        payload = decode(body)
        expect(payload, ("items", "proof"))
        items = self.task_changes(payload["items"])
        proof = self.covered(payload["proof"], items, time.time())
        for item in items:
            self.operator_proven(proof, item)
        ids = []
        for item in items:
            fields = {"kind": TASK_JOB, "task": item["id"], "argv": item["argv"], "command": shown_command(item["argv"]), "directory": "", "sha256": "", "status": "queued", "proof": proof}
            ids.append(self.jobs.add({**fields, "code": None, "output": "", "created_ts": time.time(), "started": None, "finished": None})["id"])
        commands = [shown_command(item["argv"]) for item in items]
        self.log.add({"kind": "run", "title": f"Task change signed: {', '.join(item['id'] for item in items)}"[:200], "text": "\n".join(commands), "ref": {"jobs": ids, "status": "queued"}})
        return {"jobs": ids, "status": "queued"}
