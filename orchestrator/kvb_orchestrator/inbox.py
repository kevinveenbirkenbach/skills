from __future__ import annotations

import time

from .approving import INBOX_KINDS
from .choosing import answered, decision_status
from .council import read_claims
from .denying import requester_of
from .errors import ToolError
from .fields import decode, expect
from .jobs import console_of, row_blocked
from .names import Directory
from .records import digest, iso_epoch
from .register import adder, operator_rows, runnable
from .signed import signing
from .skill_scripts import task_pattern

SNOOZE_LIMIT = 8 * 86400
LAPSE_WINDOW = 86400


def item_base() -> dict:
    return {"agent": "", "to": "", "detail": "", "green": False, "gate": "", "score": "", "warnings": [], "options": [], "recommended": "", "multi": False, "check": "", "command": "", "directory": "", "sha256": "", "runnable": False, "deniable": False, "job": None, "rule": None, "dry_run": None, "diff": None, "settled": False, "answered": "", "reviews": [], "blocked": ""}


def lapsed_of(records: list[dict], now: float, called: bool) -> list[dict]:
    """Args:
        records: asks or decisions; a decision without expires never lapses.
        now: the current time in epoch seconds.
        called: True for asks, which count only with the call_key of their
            call: an ask of an older hook has none, and one whose call ran is
            no longer pending (ask_ran()).

    Returns:
        The records still pending whose expires passed at most LAPSE_WINDOW
        ago: what expired before the operator decided it. A decided record
        is never among them.
    """
    return [record for record in records if record.get("status") == "pending" and now - LAPSE_WINDOW <= record.get("expires", now + 1) <= now and (record.get("call_key") or not called)]


def decision_item(base: dict, decision: dict) -> dict:
    recommended = decision.get("recommended", "")
    fields = {"title": decision["question"][:300], "agent": decision["agent"], "green": recommended != "", "options": decision["options"], "recommended": recommended, "multi": bool(decision.get("multi"))}
    return {**base, "kind": "decision", "id": decision["id"], "ts": decision["created_ts"], **fields}


class Inbox:
    def inbox(self, now: float, tasks: dict[str, dict], directory: Directory) -> list[dict]:
        claims = read_claims(self.council)
        base = item_base()
        items = []
        for review in self.reviews.pending():
            created = iso_epoch(review["created"]) or now
            gate = review.get("gate", "")
            agent = review.get("agent", "")
            fields = {"title": review["title"], "detail": review["branch"], "green": gate == "pass", "gate": gate, "score": review.get("score", ""), "directory": review["worktree"], "agent": agent, "to": requester_of(claims, agent)[0], "diff": review.get("diff_files")}
            items.append({**base, "kind": "review", "id": review["id"], "ts": created, **fields})
        items += [self.inbox_ask(base, ask, claims, directory) for ask in self.asks.pending() if ask["expires"] > now]
        items += [decision_item(base, decision) for decision in self.decisions.pending() if decision_status(decision, now) == "pending"]
        held = self.open_jobs()
        reasons = self.blocked_rows(now)
        consoles = self.consoles()
        pattern = task_pattern(self.scripts.skills)
        rows = [row for row in operator_rows(tasks) if pattern is not None and pattern.fullmatch(row["task"])]
        for row in rows:
            busy = row["task"] in held
            answer = self.answers.get(row["task"])
            fields = {"answered": answer["label"] if answered(answer, row) else "", "title": row["command"], "detail": row["why"], "agent": adder(tasks[row["task"]]), "to": requester_of(claims, adder(tasks[row["task"]]))[0], "command": row["command"], "directory": row["directory"], "sha256": digest(row["command"]), "check": row["check"], "options": row["options"], "recommended": row["recommended"]}
            state = {"runnable": runnable(row) and not busy, "deniable": not busy, "job": console_of(consoles.get(row["task"])), "reviews": self.linked(row["command"]), "blocked": row_blocked(row, reasons)}
            items.append({**base, "kind": "operator", "id": row["task"], "ts": self.watch.first(row["task"], now), **fields, **state})
        listed = {row["task"] for row in rows}
        for task, job in consoles.items():
            if task not in listed:
                fields = {"title": job["command"], "command": job["command"], "directory": job["directory"], "job": console_of(job), "settled": True}
                items.append({**base, "kind": "operator", "id": task, "ts": job["created_ts"], **fields})
        items += self.request_items(base, now, claims)
        return self.marked_items(items, now)

    def marked_items(self, items: list[dict], now: float) -> list[dict]:
        for item in items:
            mark = self.marks.get(f"{item['kind']}:{item['id']}")
            item.update(pinned=mark["pinned"], until=mark["until"] if mark["until"] > now else 0.0, held=self.batches.holds(item["kind"], item["id"]))
        return sorted(items, key=lambda item: (not item["pinned"], -item["ts"], item["id"]))

    def inbox_ask(self, base: dict, ask: dict, claims: list[dict], directory: Directory) -> dict:
        warnings = signing.warnings(ask["command"])
        fields = {"title": f"{ask['tool']}: {ask['command'][:200]}", "agent": directory.now(ask["session"]), "to": requester_of(claims, ask["session"])[0], "green": not warnings, "warnings": warnings, "deniable": True, "diff": ask.get("diff_files")}
        return {**base, "kind": "ask", "id": ask["id"], "ts": ask["created_ts"], **fields, "command": ask["command"], "directory": ask["cwd"]}

    def lapsed_items(self, now: float, directory: Directory) -> list[dict]:
        """Returns:
            An item as inbox() builds it, with its expires, of every ask and
            decision lapsed_of() keeps; the Inbox lists none of them, Match
            keeps each greyed until the operator denies it.
        """
        claims = read_claims(self.council)
        base = item_base()
        asks = [{**self.inbox_ask(base, ask, claims, directory), "expires": ask["expires"]} for ask in lapsed_of(self.asks.pending(), now, True)]
        decisions = [{**decision_item(base, decision), "to": requester_of(claims, decision["agent"])[0], "expires": decision["expires"]} for decision in lapsed_of(self.decisions.pending(), now, False)]
        return self.marked_items(asks + decisions, now)

    def linked(self, command: str) -> list[dict]:
        """Returns:
            {"id", "status", "gate"} of each review the approval.py verify
            steps of command check; status unknown for one the hub lacks.
        """
        records = {review_id: self.reviews.get(review_id) for review_id in signing.verified_reviews(command)}
        return [{"id": review_id, "status": record["status"] if record else "unknown", "gate": record.get("gate", "") if record else ""} for review_id, record in records.items()]

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
