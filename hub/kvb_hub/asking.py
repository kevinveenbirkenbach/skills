from __future__ import annotations

import time

from .errors import Conflict, Missing, ToolError
from .fields import (
    COMMAND_LIMIT,
    PATH_LIMIT,
    WAIT_CAP,
    bounded,
    decode,
    expect,
    field,
    instant,
    message_text,
    seconds,
)
from .signed import ask_signed

ASK_LIFETIME = 3600
DESCRIPTION_LIMIT = 1000
OPTION_LIMIT = 12
ASK_TEXTS = {"command": COMMAND_LIMIT, "cwd": PATH_LIMIT, "session": 200, "agent": 200}
ANSWERS = {"allow": "allowed", "deny": "denied"}


def ask_state(ask: dict, now: float) -> dict:
    status = "expired" if ask["status"] == "pending" and ask["expires"] <= now else ask["status"]
    return {"id": ask["id"], "status": status, "decided": ask["decided"], "proof": ask.get("proof")}


def ask_row(ask: dict, names: dict[str, str]) -> dict:
    keys = ("id", "tool", "command", "cwd", "session", "created_ts", "expires")
    return {**{key: ask[key] for key in keys}, "agent": names.get(ask["session"], ""), "subagent": ask["agent"]}


def decision_state(decision: dict) -> dict:
    return {key: decision[key] for key in ("id", "status", "choice", "decided")}


def decision_row(decision: dict) -> dict:
    return {key: decision[key] for key in ("id", "question", "options", "agent", "created_ts")}


def option_of(option: object) -> dict:
    if not isinstance(option, dict):
        raise ToolError("every option must be an object with label and description")
    expect(option, ("label", "description"))
    label = field(option, "label").strip()
    return {"label": label, "description": bounded(option, "description", DESCRIPTION_LIMIT).strip()}


class Asking:
    def ask(self, body: bytes) -> dict:
        payload = decode(body)
        expect(payload, ("tool", *ASK_TEXTS, "timeout"))
        values = {name: bounded(payload, name, limit) for name, limit in ASK_TEXTS.items()}
        lifetime = seconds(payload, "timeout", ASK_LIFETIME)
        created = time.time()
        fields = {**values, "tool": field(payload, "tool").strip(), "status": "pending", "decided": None, "proof": None}
        record = self.asks.add({**fields, "created_ts": created, "expires": created + lifetime})
        self.automate("ask", record, {"item": ask_signed(record), "gate": ""})
        return {"id": record["id"], "status": record["status"]}

    def ask_wait(self, ask_id: str, query: dict[str, list[str]]) -> dict:
        wait = instant(query, "wait")
        record = self.asks.get(ask_id)
        if record is None:
            raise Missing(ask_id)
        left = max(record["expires"] - time.time(), 0.0)
        record = self.asks.wait(ask_id, min(wait or 0.0, WAIT_CAP, left))
        return ask_state(record, time.time())

    def settle(self, kind_name: str, item_id: str, verb: str, body: bytes) -> dict:
        if kind_name == "asks" and verb in ANSWERS:
            record = self.asks.get(item_id)
            if record is None:
                raise Missing(item_id)
            if ask_state(record, time.time())["status"] == "expired":
                raise Conflict(ask_state(record, time.time()))
            proof = None
            if verb == "allow":
                payload = decode(body)
                expect(payload, ("proof",))
                proof = self.covered(payload["proof"], [ask_signed(record)], time.time())
            decided, changed = self.asks.decide(item_id, {"status": ANSWERS[verb], "proof": proof})
            if not changed:
                raise Conflict(ask_state(decided, time.time()))
            return ask_state(decided, time.time())
        if kind_name != "decisions" or verb != "choose":
            raise Missing(verb)
        payload = decode(body)
        expect(payload, ("label",))
        label = field(payload, "label")
        record = self.decisions.get(item_id)
        if record is None:
            raise Missing(item_id)
        if label not in [option["label"] for option in record["options"]]:
            raise ToolError(f"label must be one of the options of decision {item_id}")
        decided, changed = self.decisions.decide(item_id, {"status": "decided", "choice": label})
        if not changed:
            raise Conflict(decision_state(decided))
        return decision_state(decided)

    def decision_request(self, arguments: dict) -> dict:
        expect(arguments, ("question", "options", "agent", "recommended"))
        question = message_text(arguments, "question")
        options = arguments["options"]
        if not isinstance(options, list) or not 1 <= len(options) <= OPTION_LIMIT:
            raise ToolError(f"options must be a list of 1 to {OPTION_LIMIT} objects")
        parsed = [option_of(option) for option in options]
        if len({option["label"] for option in parsed}) != len(parsed):
            raise ToolError("option labels must be distinct")
        recommended = arguments["recommended"]
        if not isinstance(recommended, str) or recommended.strip() not in ["", *(option["label"] for option in parsed)]:
            raise ToolError("recommended must be one of the option labels or an empty string")
        fields = {"question": question, "options": parsed, "agent": field(arguments, "agent").strip(), "recommended": recommended.strip()}
        record = self.decisions.add({**fields, "status": "pending", "choice": None, "decided": None, "created_ts": time.time()})
        self.automate("decision", record, {"recommended": record["recommended"], "agent": record["agent"]})
        return {"id": record["id"], "status": record["status"], "url": self.url()}

    def decision_wait(self, arguments: dict) -> dict:
        expect(arguments, ("id", "timeout_seconds"))
        decision_id = field(arguments, "id")
        record = self.decisions.wait(decision_id, seconds(arguments, "timeout_seconds", WAIT_CAP))
        if record is None:
            raise ToolError(f"no decision {decision_id}")
        return decision_state(record)
