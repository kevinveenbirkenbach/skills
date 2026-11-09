from __future__ import annotations

from .council import agent
from .errors import ToolError
from .fields import decode, expect, field
from .messaging import DIRECT, EVERYONE, TO_ALL
from .signed import signing

CHOICE_REQUEST = "send me your open decisions as choices"
CHANNELS = {**DIRECT, **TO_ALL}
CHOICE_KEYS = ("class", "to")
RECIPIENT_LIMIT = 40
ANSWER_CLASS = "post"
QUESTION_SHOWN = 200


def answer_text(decision: dict, label: str) -> str:
    question = " ".join(decision["question"].split())[:QUESTION_SHOWN]
    return f"Choice for decision {decision['id']} ({question}): {label}"


def answer_signed(decision: dict, label: str) -> dict:
    """Returns:
        The post to the asking agent that a click on the option label
        signs: the operator's answer operator_message proves.
    """
    if EVERYONE in decision["agent"]:
        raise ToolError(f"a choice answer goes to the asking agent, never to a name with {EVERYONE}")
    return signing.message_item(agent(decision["agent"]), ANSWER_CLASS, answer_text(decision, label), "", "", "")


def recipients(payload: dict) -> list[str]:
    """Args:
        payload: the page's class and to: 1 to RECIPIENT_LIMIT distinct
            agent names for post and call, [EVERYONE] for a class to all.
    """
    cls, names = payload["class"], payload["to"]
    if not isinstance(cls, str) or cls not in CHANNELS:
        raise ToolError(f"class must be one of {', '.join(CHANNELS)}")
    if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
        raise ToolError("to must be a list of agent names")
    if cls in TO_ALL:
        if names != [EVERYONE]:
            raise ToolError(f"a choice request to all names to [{EVERYONE}]")
        return names
    targets = [field({"to": name}, "to").strip() for name in names]
    if not 1 <= len(targets) <= RECIPIENT_LIMIT or any(EVERYONE in target for target in targets):
        raise ToolError(f"a post or a call names 1 to {RECIPIENT_LIMIT} agents, never a name with {EVERYONE}")
    if len({agent(target) for target in targets}) != len(targets):
        raise ToolError("to must name distinct agents")
    return targets


class Choosing:
    def choice_items(self, payload: dict) -> list[dict]:
        return [signing.message_item(target, payload["class"], CHOICE_REQUEST, "", "", "") for target in recipients(payload)]

    def sign_choices(self, body: bytes) -> dict:
        payload = decode(body)
        expect(payload, CHOICE_KEYS)
        return self.challenge_for(self.choice_items(payload))

    def request_choices(self, body: bytes) -> dict:
        """Returns:
            The ids of the stored requests, one per recipient, once one
            passkey assertion signed each of them; nothing is stored or sent
            before every item verified.
        """
        payload = decode(body)
        expect(payload, (*CHOICE_KEYS, "proof"))
        items = self.choice_items(payload)
        for item in items:
            self.operator_proven(payload["proof"], item)
        records = [self.stored_message(item, payload["proof"], None) for item in items]
        runs = [self.radioed(record, CHANNELS[payload["class"]]) for record in records]
        return {"ids": [record["id"] for record in records], "ok": all(run["code"] == 0 for run in runs), "runs": runs}

    def answer_choice(self, item: dict, proof: dict) -> str:
        """Args:
            item: a checked decision item whose signed is answer_signed().
            proof: the relayed signature; the hub sends the answer itself,
                so it verifies the signature here, once.

        Returns:
            The outcome words for the stream.
        """
        record = self.decisions.get(item["id"])
        if record is None:
            return "unknown"
        if record["status"] != "pending":
            return f"already {record['status']}"
        self.operator_proven(proof, item["signed"])
        message = self.stored_message(item["signed"], proof, None)
        decided, changed = self.decisions.decide(item["id"], {"status": "decided", "choice": item["label"], "message": message["id"]})
        if not changed:
            self.messages.remove(message["id"])
            return f"already {decided['status']}"
        run = self.radioed(message, CHANNELS[ANSWER_CLASS])
        where = f"{ANSWER_CLASS} to {message['address']}"
        return f"decided · {where}" if run["code"] == 0 else f"decided · {where} failed ({run['code']})"
