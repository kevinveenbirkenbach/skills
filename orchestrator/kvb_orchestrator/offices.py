from __future__ import annotations

import secrets
import time

from .council import HUMAN, office_kind, read_claims
from .errors import Conflict, Missing, ToolError
from .fields import decode, expect
from .records import read_json, stamp
from .signed import signing

ITEM_LIMIT = 20
JOB_VERSION = 1
LABELS = {"appoint": "appointed", "takeover": "handed over", "recall": "recalled"}


def office_request(raw: object) -> bool:
    return isinstance(raw, list) and bool(raw) and all(isinstance(entry, dict) and entry.get("kind") == "office" for entry in raw)


class Offices:
    def office_sessions(self, claims: list[dict]) -> set[str]:
        named = {entry["session"] for entry in self.names.listed()} | {claim["session"] for claim in claims}
        return {session for session in named if signing.SESSION.fullmatch(session) and session != HUMAN}

    def appointable(self, raw: object) -> list[dict]:
        """Args:
            raw: the orders the page chose, each {"kind": "office", "action",
                "office", "holder", "session", "work"}.

        Returns:
            The signed items: each order well formed, its holder the office's
            current one, its successor a known session that represents no
            other line of the same dimension.
        """
        if not isinstance(raw, list) or not 1 <= len(raw) <= ITEM_LIMIT:
            raise ToolError(f"items must be a list of 1 to {ITEM_LIMIT} objects")
        claims = read_claims(self.council)
        holders = {claim["office"]: claim["session"] for claim in claims}
        sessions = self.office_sessions(claims)
        chosen = []
        for entry in raw:
            if not isinstance(entry, dict):
                raise ToolError("every item must be an object with kind, action, office, holder, session and work")
            expect(entry, ("kind", *signing.OFFICE_KEYS))
            if entry["kind"] != "office":
                raise ToolError("kind must be office")
            order = {name: entry[name] for name in signing.OFFICE_KEYS}
            problem = signing.office_problem(order)
            if problem:
                raise ToolError(problem)
            if order["holder"] != holders.get(order["office"], ""):
                raise Conflict({"office": order["office"], "holder": holders.get(order["office"], "")})
            if order["action"] != "recall":
                self.successor(order, sessions, claims)
            item = signing.office_item(**order)
            if item in chosen:
                raise ToolError("items must be distinct")
            chosen.append(item)
        return chosen

    def successor(self, order: dict, sessions: set[str], claims: list[dict]) -> None:
        if order["session"] not in sessions:
            raise ToolError("session must be a session the Agent Orchestrator knows")
        kind, dimension, _ = office_kind(order["office"])
        others = [claim["office"] for claim in claims if claim["session"] == order["session"] and claim["dimension"] == dimension and claim["office"] != order["office"]]
        if kind == "line" and others:
            raise ToolError(f"{order['session']} represents {others[0]} already: one line per dimension")

    def appoint(self, body: bytes) -> dict:
        payload = decode(body)
        expect(payload, ("items", "proof"))
        items = self.appointable(payload["items"])
        proof = self.covered(payload["proof"], items, time.time())
        job_id = secrets.token_hex(8)
        job = {"v": JOB_VERSION, "id": job_id, "created": stamp(), "items": [{name: item[name] for name in signing.OFFICE_KEYS} for item in items], "proof": proof}
        self.office_spool.put(job_id, job)
        names = ", ".join(f"{item['office']} {LABELS[item['action']]}" for item in items)
        lines = "\n".join(f"{item['action']} {item['office']}: {item['holder'] or '-'} -> {item['session'] or '-'}" for item in items)
        self.log.add({"kind": "run", "title": f"Office signed: {names}"[:200], "text": lines, "ref": {"offices": job_id, "status": "queued"}})
        return {"id": job_id, "status": "queued", "items": job["items"]}

    def office_state(self, job_id: str) -> dict:
        result = read_json(self.office_spool.results / f"{job_id}.json")
        if isinstance(result, dict) and isinstance(result.get("items"), list):
            return {**result, "id": job_id, "status": "done"}
        if (self.office_spool.jobs / f"{job_id}.json").is_file():
            return {"id": job_id, "status": "queued", "items": []}
        raise Missing(job_id)
