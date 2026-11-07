from __future__ import annotations

import time

from .approving import INBOX_KINDS
from .errors import ToolError
from .fields import decode, expect
from .jobs import console_of
from .names import Directory
from .records import digest, iso_epoch
from .register import adder, operator_rows, runnable
from .signed import signing

SNOOZE_LIMIT = 8 * 86400


class Inbox:
    def inbox(self, now: float, tasks: dict[str, dict], directory: Directory) -> list[dict]:
        base = {"agent": "", "detail": "", "green": False, "gate": "", "score": "", "warnings": [], "options": [], "recommended": "", "command": "", "directory": "", "sha256": "", "runnable": False, "deniable": False, "job": None, "rule": None, "dry_run": None}
        items = []
        for review in self.reviews.pending():
            created = iso_epoch(review["created"]) or now
            gate = review.get("gate", "")
            fields = {"title": review["title"], "detail": review["branch"], "green": gate == "pass", "gate": gate, "score": review.get("score", ""), "directory": review["worktree"]}
            items.append({**base, "kind": "review", "id": review["id"], "ts": created, **fields})
        for ask in (ask for ask in self.asks.pending() if ask["expires"] > now):
            warnings = signing.warnings(ask["command"])
            fields = {"title": f"{ask['tool']}: {ask['command'][:200]}", "agent": directory.now(ask["session"]), "green": not warnings, "warnings": warnings, "deniable": True}
            items.append({**base, "kind": "ask", "id": ask["id"], "ts": ask["created_ts"], **fields, "command": ask["command"], "directory": ask["cwd"]})
        for decision in self.decisions.pending():
            recommended = decision.get("recommended", "")
            fields = {"title": decision["question"][:300], "agent": decision["agent"], "green": recommended != "", "options": decision["options"], "recommended": recommended}
            items.append({**base, "kind": "decision", "id": decision["id"], "ts": decision["created_ts"], **fields})
        held = self.open_jobs()
        consoles = self.consoles()
        rows = operator_rows(tasks)
        for row in rows:
            busy = row["task"] in held
            fields = {"title": row["command"], "detail": row["why"], "agent": adder(tasks[row["task"]]), "command": row["command"], "directory": row["directory"], "sha256": digest(row["command"])}
            state = {"runnable": runnable(row) and not busy, "deniable": not busy, "job": console_of(consoles.get(row["task"]))}
            items.append({**base, "kind": "operator", "id": row["task"], "ts": self.watch.first(row["task"], now), **fields, **state})
        listed = {row["task"] for row in rows}
        for task, job in consoles.items():
            if task not in listed:
                fields = {"title": job["command"], "command": job["command"], "directory": job["directory"], "job": console_of(job)}
                items.append({**base, "kind": "operator", "id": task, "ts": job["created_ts"], **fields})
        items += self.request_items(base, now)
        for item in items:
            mark = self.marks.get(f"{item['kind']}:{item['id']}")
            item.update(pinned=mark["pinned"], until=mark["until"] if mark["until"] > now else 0.0, held=self.batches.holds(item["kind"], item["id"]))
        return sorted(items, key=lambda item: (not item["pinned"], -item["ts"], item["id"]))

    def mark(self, body: bytes) -> dict:
        payload = decode(body)
        expect(payload, ("kind", "id", "until", "pinned"))
        kind_name, until, pinned = payload["kind"], payload["until"], payload["pinned"]
        if kind_name not in INBOX_KINDS or not isinstance(payload["id"], str) or not 0 < len(payload["id"]) <= 200:
            raise ToolError(f"kind must be one of {', '.join(INBOX_KINDS)} and id an item id")
        now = time.time()
        if isinstance(until, bool) or not isinstance(until, int | float) or not (until == 0 or now < until <= now + SNOOZE_LIMIT):
            raise ToolError("until must be 0 or a moment within the next 8 days")
        if not isinstance(pinned, bool):
            raise ToolError("pinned must be true or false")
        mark = {"until": float(until), "pinned": pinned}
        self.marks.put(f"{kind_name}:{payload['id']}", mark)
        return {"kind": kind_name, "id": payload["id"], **mark}
