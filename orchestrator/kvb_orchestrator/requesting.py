from __future__ import annotations

import time

from .denying import request_status, request_words
from .errors import Conflict, Missing, ToolError
from .fields import WAIT_CAP, bounded, decode, expect, field, seconds
from .records import iso_epoch
from .rules import rule_fields, rule_matches, signed_fields, subject_of
from .signed import signing

# Trip-wire: MCP carries no caller identity, so an agent may name itself anew for each request; AGENT_CAP only spreads the queue, TOTAL_CAP is the bound.
AGENT_CAP = 3
TOTAL_CAP = 20
WHY_LIMIT = 1000
RECENT_DAYS = 7
RULE_FIELDS = ("kind", "tool", "pattern", "scope", "expires")
REQUEST_STATE = ("id", "status", "rule", "reason", "decided")


def request_state(record: dict, now: float) -> dict:
    return {**{key: record[key] for key in REQUEST_STATE}, "status": request_status(record, now)}


def created_of(record: dict) -> float:
    return record["created_ts"] if "created_ts" in record else iso_epoch(record["created"]) or 0.0


class Requesting:
    def open_requests(self, now: float) -> list[dict]:
        return [record for record in self.rule_requests.pending() if request_status(record, now) == "pending"]

    def rule_request(self, arguments: dict) -> dict:
        expect(arguments, (*RULE_FIELDS, "agent", "why"))
        now = time.time()
        fields = rule_fields(arguments, now)
        if fields["kind"] == "decision" and fields["scope"] != "*":
            raise ToolError("a decision rule takes scope *, as the rules form does")
        name = field(arguments, "agent").strip()
        why = bounded(arguments, "why", WHY_LIMIT).strip()
        if not why:
            raise ToolError("why must name the purpose of the requested rule")

        def capped(records: list[dict]) -> None:
            pending = [record for record in records if request_status(record, now) == "pending"]
            if len(pending) >= TOTAL_CAP:
                raise ToolError(f"{TOTAL_CAP} rule requests wait for the operator; ask again once some are answered")
            if sum(1 for record in pending if record["agent"] == name) >= AGENT_CAP:
                raise ToolError(f"{name} already has {AGENT_CAP} pending rule requests; wait for their answer with rule_request_wait")

        record = self.rule_requests.add_checked({**fields, "agent": name, "why": why, "status": "pending", "rule": None, "reason": "", "channel": "", "proof": None, "decided": None, "created_ts": now}, capped)
        self.log.add({"kind": "rule", "title": f"Regelwunsch von {name}: {request_words(record)}", "text": why, "ref": {"request": record["id"]}})
        return {"id": record["id"], "status": record["status"], "url": self.url()}

    def rule_request_wait(self, arguments: dict) -> dict:
        expect(arguments, ("id", "timeout_seconds"))
        request_id = field(arguments, "id")
        record = self.rule_requests.wait(request_id, seconds(arguments, "timeout_seconds", WAIT_CAP))
        if record is None:
            raise ToolError(f"no rule request {request_id}")
        return request_state(record, time.time())

    def dry_run(self, record: dict, now: float) -> dict:
        """Returns:
            How many of the asks, reviews or decisions of the last
            RECENT_DAYS the requested rule would have approved, matched by
            the same code that applies a stored rule.
        """
        kind_name = record["kind"]
        payload = signing.rule_payload(record["id"], [kind_name], record["tool"], record["pattern"], record["scope"], int(record["expires"]))
        rule = {**{key: record[key] for key in RULE_FIELDS}, "enabled": True, "proof": {"payload": payload, "assertion": None}}
        ledger = {"ask": self.asks, "review": self.reviews, "decision": self.decisions}[kind_name]
        since = now - RECENT_DAYS * 86400
        subjects = [subject_of(kind_name, entry) for entry in ledger.listed() if created_of(entry) >= since]
        return {"matched": sum(rule_matches(rule, kind_name, subject, now) for subject in subjects), "total": len(subjects), "days": RECENT_DAYS}

    def request_items(self, base: dict, now: float) -> list[dict]:
        items = []
        for record in self.open_requests(now):
            rule = {key: record[key] for key in RULE_FIELDS}
            fields = {"title": f"Regel: {request_words(record)}", "agent": record["agent"], "detail": record["why"], "rule": rule, "dry_run": self.dry_run(record, now), "deniable": True}
            items.append({**base, "kind": "rule", "id": record["id"], "ts": record["created_ts"], **fields})
        return items

    def pending_request(self, request_id: str) -> dict:
        record = self.rule_requests.get(request_id)
        if record is None:
            raise Missing(request_id)
        state = request_state(record, time.time())
        if state["status"] != "pending":
            raise Conflict(state)
        if self.batches.holds("rule", request_id):
            raise Conflict({"id": request_id, "status": "held"})
        return record

    def sign_request(self, request_id: str) -> dict:
        record = self.pending_request(request_id)
        return {**self.rule_offer(rule_fields(record, time.time())), "sign": True}

    def accept_request(self, request_id: str, body: bytes) -> dict:
        payload = decode(body)
        expect(payload, ("rule", "assertion"))
        record = self.pending_request(request_id)
        now = time.time()
        rule = payload["rule"]
        fields = signed_fields(rule, now)
        if [fields[key] for key in RULE_FIELDS] != [record[key] for key in RULE_FIELDS]:
            raise ToolError("the signed rule must be exactly the requested one")
        if self.rules.get(rule["id"]) is not None:
            raise Conflict({"id": rule["id"], "status": "exists"})
        proof = self.proven_rule(rule, payload["assertion"])
        decided, changed = self.rule_requests.decide(request_id, {"status": "accepted", "rule": rule["id"]})
        if not changed:
            raise Conflict(request_state(decided, now))
        self.store_rule(rule, fields, proof, True, now)
        self.log.add({"kind": "rule", "title": f"Regelwunsch angenommen: {request_words(record)}", "text": f"von {record['agent']}", "ref": {"request": request_id, "rule": rule["id"]}})
        return request_state(decided, now)
