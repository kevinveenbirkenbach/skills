from __future__ import annotations

import fnmatch
import threading
import time

from .council import read_claims
from .errors import Conflict, Missing, ToolError
from .fields import COMMAND_LIMIT, PATH_LIMIT, bounded, decode, expect, visible
from .names import Directory
from .signed import ask_signed, passkey, review_signed, signing, verifier

RULE_KINDS = ("ask", "review", "decision")
RULE_INPUT = ("kind", "tool", "pattern", "scope", "expires")
EVERY_AGENT = [signing.ALL_AGENTS]
OFFER_LIMIT = 1000


def rule_matches(rule: dict, kind_name: str, subject: dict, now: float) -> bool:
    proof = rule.get("proof")
    if not rule["enabled"] or rule["expires"] <= now or rule["kind"] != kind_name or proof is None:
        return False
    if kind_name == "decision":
        named = subject["recommended"] != "" and fnmatch.fnmatchcase(subject["agent"], rule["pattern"])
        return named and signing.reaches(proof["payload"], subject["sessions"])
    return signing.rule_allows(proof["payload"], subject["item"], subject["gate"], now)


def subject_of(kind_name: str, record: dict, sessions: set[str]) -> dict:
    """Args:
        kind_name: ask, review or decision.
        record: the ask, review or decision.
        sessions: for a decision, the sessions that held the asking agent's
            name; empty for an ask or review, whose signed item names its own.

    Returns:
        What a rule of that kind is matched against.
    """
    if kind_name == "ask":
        return {"item": ask_signed(record), "gate": ""}
    if kind_name == "review":
        return {"item": review_signed(record), "gate": record.get("gate", "")}
    return {"recommended": record["recommended"], "agent": record["agent"], "sessions": sessions}


def rule_fields(raw: dict, agents: object, now: float) -> dict:
    """Args:
        raw: kind, tool, pattern, scope and expires of the rule.
        agents: EVERY_AGENT, or the sorted session ids of one agent or group.
        now: the current time in epoch seconds.

    Returns:
        The checked fields with agents.
    """
    kind_name, expires = raw["kind"], raw["expires"]
    if kind_name not in RULE_KINDS:
        raise ToolError(f"kind must be one of {', '.join(RULE_KINDS)}")
    tool_name, pattern, scope = rule_texts(raw, kind_name)
    if isinstance(expires, bool) or not isinstance(expires, int | float) or not now + 1 < expires <= now + signing.RULE_LIFETIME:
        raise ToolError("expires must be a moment within the next 366 days")
    return {"kind": kind_name, "tool": tool_name, "pattern": pattern, "scope": scope, "expires": int(expires), "agents": target_of(kind_name, agents)}


def rule_texts(raw: dict, kind_name: str) -> tuple[str, str, str]:
    """Returns:
        tool, pattern and scope of raw, once each is one line without a
        control, format, line or paragraph separator character, as visible()
        checks, and only an ask rule names a tool.
    """
    tool_name = bounded(raw, "tool", 200).strip()
    if (kind_name == "ask") != bool(tool_name):
        raise ToolError("an ask rule names a tool; review and decision rules leave tool empty")
    pattern, scope = bounded(raw, "pattern", COMMAND_LIMIT), bounded(raw, "scope", PATH_LIMIT)
    if not pattern.strip() or not scope.strip() or "\n" in pattern or "\n" in scope:
        raise ToolError("pattern and scope must be one non-empty line each")
    visible({"tool": tool_name, "pattern": pattern, "scope": scope})
    return tool_name, pattern, scope


def target_of(kind_name: str, agents: object) -> list[str]:
    """Returns:
        agents, once signing.agents_problem() accepts it and a review rule
        names every agent, since a review names no session.
    """
    problem = signing.agents_problem(agents)
    if problem:
        raise ToolError(problem)
    if kind_name == "review" and agents != EVERY_AGENT:
        raise ToolError("a review rule applies to every agent: a review names no session")
    return agents


def signed_fields(rule: object, now: float) -> dict:
    try:
        signing.checked_rule(rule, now)
    except signing.Refused as error:
        raise ToolError(f"rule: {error}") from None
    if len(rule["kinds"]) != 1:
        raise ToolError("a rule names exactly one kind")
    agents = EVERY_AGENT
    if signing.TARGET in rule:
        agents = rule[signing.TARGET]
    fields = rule_fields({**{name: rule[name] for name in ("tool", "pattern", "scope", "expires")}, "kind": rule["kinds"][0]}, agents, now)
    if fields["tool"] != rule["tool"]:
        raise ToolError("tool must not carry surrounding blanks")
    return fields


class Offers:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.ids: dict[str, float] = {}

    def offer(self, rule_id: str, now: float) -> None:
        """Args:
            rule_id: an id the hub just put into a rule payload for the
                operator to sign; held in memory only, so a hub restart
                forgets every offer and refuses their proofs.
            now: the current time; offers older than signing.LIFETIME and
                beyond the newest OFFER_LIMIT are dropped.
        """
        with self.lock:
            self.ids = {key: at for key, at in self.ids.items() if now - at <= signing.LIFETIME}
            self.ids[rule_id] = now
            while len(self.ids) > OFFER_LIMIT:
                del self.ids[next(iter(self.ids))]

    def take(self, rule_id: str, now: float) -> bool:
        with self.lock:
            offered = self.ids.pop(rule_id, None)
        return offered is not None and now - offered <= signing.LIFETIME


class Rules:
    def rule_offer(self, fields: dict) -> dict:
        rule = signing.targeted(signing.rule_payload(self.rules.fresh(), [fields["kind"]], fields["tool"], fields["pattern"], fields["scope"], fields["expires"]), fields["agents"])
        visible(rule)
        self.offers.offer(rule["id"], time.time())
        return {"payload": rule, "challenge": signing.challenge(rule), "credentials": [key["id"] for key in self.keys()]}

    def offered(self, rule: dict, now: float) -> None:
        """Raises:
            Conflict unless the hub offered the rule's id and stored no rule
            under it since, so a signed rule is stored once and never again
            after its deletion.
        """
        if not self.offers.take(rule["id"], now):
            raise Conflict({"id": rule["id"], "status": "not offered or already stored: sign the rule anew"})

    def deciders(self, kind_name: str, record: dict) -> set[str]:
        """Returns:
            For a decision, the one session that holds its agent's name now,
            none when no session or several hold it; empty for every other
            kind.
        """
        if kind_name != "decision":
            return set()
        directory = Directory(self.names.listed())
        holders = {session for session in directory.aliases(record["agent"]) if directory.now(session) == record["agent"]}
        return holders if len(holders) == 1 else set()

    def known_agents(self, agents: list[str]) -> None:
        """Raises:
            ToolError unless agents is EVERY_AGENT or every session in it is
            one the Agent Orchestrator knows.
        """
        unknown = sorted(set(agents) - self.office_sessions(read_claims(self.council))) if agents != EVERY_AGENT else []
        if unknown:
            raise ToolError(f"agents must be sessions the Agent Orchestrator knows: {', '.join(unknown)[:200]}")

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
            raise ToolError(f"not signed: {error}") from None
        return {"payload": rule, "assertion": assertion}

    def store_rule(self, rule: dict, fields: dict, proof: dict, enabled: bool, now: float) -> dict:
        return self.rules.insert(rule["id"], {**fields, "expires": float(fields["expires"]), "enabled": enabled, "created_ts": now, "proof": proof})

    def sign_rule(self, body: bytes) -> dict:
        payload = decode(body)
        targeted = "agents" in payload
        expect(payload, (*RULE_INPUT, "agents") if targeted else RULE_INPUT)
        fields = rule_fields(payload, payload["agents"] if targeted else EVERY_AGENT, time.time())
        self.known_agents(fields["agents"])
        return {**self.rule_offer(fields), "sign": True}

    def add_rule(self, body: bytes) -> dict:
        payload = decode(body)
        expect(payload, ("rule", "assertion", "enabled"))
        rule = payload["rule"]
        now = time.time()
        fields = signed_fields(rule, now)
        if not isinstance(payload["enabled"], bool):
            raise ToolError("enabled must be true or false")
        proof = self.proven_rule(rule, payload["assertion"])
        self.offered(rule, now)
        return self.store_rule(rule, fields, proof, payload["enabled"], now)

    def enable_items(self, raw: list[dict]) -> list[dict]:
        """Args:
            raw: [{"kind": "enable", "rule"}] with the id of a stored rule.

        Returns:
            The item a fresh approval signs to turn that rule on.
        """
        expect(raw[0], ("kind", "rule"))
        return [self.enable_subject(raw[0]["rule"])]

    def enable_subject(self, rule_id: object) -> dict:
        record = self.rules.get(rule_id) if isinstance(rule_id, str) else None
        if record is None:
            raise Missing(str(rule_id)[:40])
        if record.get("proof") is None:
            raise ToolError("an unsigned rule grants nothing: sign it anew")
        return signing.enable_item(record["proof"]["payload"])

    def rule_action(self, rule_id: str, verb: str, body: bytes) -> dict:
        """Args:
            rule_id: the stored rule.
            verb: delete, disable, or enable, which widens what agents may
                do and so needs {"proof"}: a fresh passkey approval listing
                signing.enable_item() of the rule.
            body: the request body.
        """
        if verb == "delete":
            if not self.rules.remove(rule_id):
                raise Missing(rule_id)
            return {"id": rule_id, "deleted": True}
        if verb == "enable":
            payload = decode(body)
            expect(payload, ("proof",))
            self.operator_proven(payload["proof"], self.enable_subject(rule_id))
        record = self.rules.change(rule_id, {"enabled": verb == "enable"})
        if record is None:
            raise Missing(rule_id)
        return record


def enable_request(raw: object) -> bool:
    return isinstance(raw, list) and len(raw) == 1 and isinstance(raw[0], dict) and raw[0].get("kind") == "enable"
