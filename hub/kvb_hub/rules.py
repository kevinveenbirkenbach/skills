from __future__ import annotations

import fnmatch
import time

from .errors import Conflict, Missing, ToolError
from .fields import COMMAND_LIMIT, PATH_LIMIT, bounded, decode, expect
from .signed import signing

RULE_KINDS = ("ask", "review", "decision")


def rule_matches(rule: dict, kind_name: str, subject: dict, now: float) -> bool:
    if not rule["enabled"] or rule["expires"] <= now or rule["kind"] != kind_name:
        return False
    if kind_name == "decision":
        return subject["recommended"] != "" and fnmatch.fnmatchcase(subject["agent"], rule["pattern"])
    proof = rule.get("proof")
    return proof is not None and signing.rule_allows(proof["payload"], subject["item"], subject["gate"], now)


def rule_fields(raw: dict, now: float) -> dict:
    kind_name, expires = raw["kind"], raw["expires"]
    if kind_name not in RULE_KINDS:
        raise ToolError(f"kind must be one of {', '.join(RULE_KINDS)}")
    tool_name = bounded(raw, "tool", 200).strip()
    if (kind_name == "ask") != bool(tool_name):
        raise ToolError("an ask rule names a tool; review and decision rules leave tool empty")
    pattern, scope = bounded(raw, "pattern", COMMAND_LIMIT), bounded(raw, "scope", PATH_LIMIT)
    if not pattern.strip() or not scope.strip() or "\n" in pattern or "\n" in scope:
        raise ToolError("pattern and scope must be one non-empty line each")
    if isinstance(expires, bool) or not isinstance(expires, int | float) or not now + 1 < expires <= now + signing.RULE_LIFETIME:
        raise ToolError("expires must be a moment within the next 366 days")
    return {"kind": kind_name, "tool": tool_name, "pattern": pattern, "scope": scope, "expires": int(expires)}


class Rules:
    def sign_rule(self, body: bytes) -> dict:
        payload = decode(body)
        expect(payload, ("kind", "tool", "pattern", "scope", "expires"))
        fields = rule_fields(payload, time.time())
        rule = signing.rule_payload(self.rules.fresh(), [fields["kind"]], fields["tool"], fields["pattern"], fields["scope"], fields["expires"])
        credentials = [key["id"] for key in self.keys()]
        return {"payload": rule, "challenge": signing.challenge(rule), "sign": fields["kind"] != "decision", "credentials": credentials}

    def add_rule(self, body: bytes) -> dict:
        payload = decode(body)
        expect(payload, ("rule", "assertion", "enabled"))
        rule, assertion = payload["rule"], payload["assertion"]
        now = time.time()
        try:
            signing.checked_rule(rule, now)
        except signing.Refused as error:
            raise ToolError(f"rule: {error}") from None
        if len(rule["kinds"]) != 1:
            raise ToolError("a rule names exactly one kind")
        fields = rule_fields({**{name: rule[name] for name in ("tool", "pattern", "scope", "expires")}, "kind": rule["kinds"][0]}, now)
        if fields["tool"] != rule["tool"]:
            raise ToolError("tool must not carry surrounding blanks")
        signed = fields["kind"] != "decision"
        if not (isinstance(assertion, dict) if signed else assertion is None):
            raise ToolError("an ask or review rule carries the passkey assertion; a decision rule carries null")
        if not isinstance(payload["enabled"], bool):
            raise ToolError("enabled must be true or false")
        if self.rules.get(rule["id"]) is not None:
            raise Conflict({"id": rule["id"], "status": "exists"})
        proof = {"payload": rule, "assertion": assertion} if signed else None
        return self.rules.insert(rule["id"], {**fields, "expires": float(fields["expires"]), "enabled": payload["enabled"], "created_ts": now, "proof": proof})

    def rule_action(self, rule_id: str, verb: str) -> dict:
        if verb == "delete":
            if not self.rules.remove(rule_id):
                raise Missing(rule_id)
            return {"id": rule_id, "deleted": True}
        record = self.rules.change(rule_id, {"enabled": verb == "enable"})
        if record is None:
            raise Missing(rule_id)
        return record
