from __future__ import annotations

import fnmatch
import time

from .errors import Conflict, Missing, ToolError
from .fields import COMMAND_LIMIT, PATH_LIMIT, bounded, decode, expect
from .signed import ask_signed, passkey, review_signed, signing, verifier

RULE_KINDS = ("ask", "review", "decision")


def rule_matches(rule: dict, kind_name: str, subject: dict, now: float) -> bool:
    proof = rule.get("proof")
    if not rule["enabled"] or rule["expires"] <= now or rule["kind"] != kind_name or proof is None:
        return False
    if kind_name == "decision":
        return subject["recommended"] != "" and fnmatch.fnmatchcase(subject["agent"], rule["pattern"])
    return signing.rule_allows(proof["payload"], subject["item"], subject["gate"], now)


def subject_of(kind_name: str, record: dict) -> dict:
    if kind_name == "ask":
        return {"item": ask_signed(record), "gate": ""}
    if kind_name == "review":
        return {"item": review_signed(record), "gate": record.get("gate", "")}
    return {"recommended": record["recommended"], "agent": record["agent"]}


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


def signed_fields(rule: object, now: float) -> dict:
    try:
        signing.checked_rule(rule, now)
    except signing.Refused as error:
        raise ToolError(f"rule: {error}") from None
    if len(rule["kinds"]) != 1:
        raise ToolError("a rule names exactly one kind")
    fields = rule_fields({**{name: rule[name] for name in ("tool", "pattern", "scope", "expires")}, "kind": rule["kinds"][0]}, now)
    if fields["tool"] != rule["tool"]:
        raise ToolError("tool must not carry surrounding blanks")
    return fields


class Rules:
    def rule_offer(self, fields: dict) -> dict:
        rule = signing.rule_payload(self.rules.fresh(), [fields["kind"]], fields["tool"], fields["pattern"], fields["scope"], fields["expires"])
        return {"payload": rule, "challenge": signing.challenge(rule), "credentials": [key["id"] for key in self.keys()]}

    def proven_rule(self, rule: dict, assertion: object) -> dict:
        """Args:
            rule: the rule payload, already checked by signed_fields.
            assertion: the passkey assertion over its challenge.

        Returns:
            The proof to store. The hub verifies it itself, since it settles
            matching items by the rule.
        """
        try:
            passkey.verify_assertion(assertion, rule, verifier.pinned(self.approvers), signing.origin_of(self.public_port))
        except signing.Refused as error:
            raise ToolError(f"nicht signiert: {error}") from None
        return {"payload": rule, "assertion": assertion}

    def store_rule(self, rule: dict, fields: dict, proof: dict, enabled: bool, now: float) -> dict:
        return self.rules.insert(rule["id"], {**fields, "expires": float(fields["expires"]), "enabled": enabled, "created_ts": now, "proof": proof})

    def sign_rule(self, body: bytes) -> dict:
        payload = decode(body)
        expect(payload, ("kind", "tool", "pattern", "scope", "expires"))
        return {**self.rule_offer(rule_fields(payload, time.time())), "sign": True}

    def add_rule(self, body: bytes) -> dict:
        payload = decode(body)
        expect(payload, ("rule", "assertion", "enabled"))
        rule = payload["rule"]
        now = time.time()
        fields = signed_fields(rule, now)
        if not isinstance(payload["enabled"], bool):
            raise ToolError("enabled must be true or false")
        if self.rules.get(rule["id"]) is not None:
            raise Conflict({"id": rule["id"], "status": "exists"})
        return self.store_rule(rule, fields, self.proven_rule(rule, payload["assertion"]), payload["enabled"], now)

    def rule_action(self, rule_id: str, verb: str) -> dict:
        if verb == "delete":
            if not self.rules.remove(rule_id):
                raise Missing(rule_id)
            return {"id": rule_id, "deleted": True}
        record = self.rules.change(rule_id, {"enabled": verb == "enable"})
        if record is None:
            raise Missing(rule_id)
        return record
