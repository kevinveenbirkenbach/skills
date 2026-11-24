from __future__ import annotations

import time

from .council import agent
from .errors import ToolError
from .fields import decode, expect, field
from .messaging import DIRECT, EVERYONE, TO_ALL
from .records import digest
from .register import REGISTER, adder, operator_rows, read_register
from .signed import signing

CHOICE_REQUEST = "send me your open decisions as choices"
CHANNELS = {**DIRECT, **TO_ALL}
CHOICE_KEYS = ("class", "to")
RECIPIENT_LIMIT = 40
ANSWER_CLASS = signing.CHOICE_CLASS
PICKED = signing.PICKED
OTHER_LIMIT = 1000


def picks(decision: dict, label: str) -> bool:
    """Args:
        decision: a decision or a decision row, with its options.
        label: the answer to it: one option label, or for a multi decision
            one or more labels in option order, joined by PICKED, which no
            label holds; or one line of free text up to OTHER_LIMIT
            characters, trimmed and no option label.

    Returns:
        Whether label is a valid answer to the decision.
    """
    labels = [option["label"] for option in decision["options"]]
    if PICKED not in label and label not in labels:
        return 0 < len(label) <= OTHER_LIMIT and label == label.strip()
    if not decision.get("multi"):
        return label in labels
    parts = label.split(PICKED)
    return [found for found in labels if found in parts] == parts


def decision_status(decision: dict, now: float) -> str:
    """Returns:
        The decision's status, expired for a pending one the permission hook
        asked whose wait ran out.
    """
    return "expired" if decision["status"] == "pending" and decision.get("expires", now + 1) <= now else decision["status"]


def answer_text(decision: dict, label: str) -> str:
    return signing.choice_text(decision["id"], decision["question"], label)


def answer_signed(decision: dict, label: str) -> dict:
    """Returns:
        The post to the asking agent that a click on the option label
        signs: the operator's answer operator_message proves, or for a
        decision the permission hook asked, the one it verifies itself.
    """
    if EVERYONE in decision["agent"]:
        raise ToolError(f"a choice answer goes to the asking agent, never to a name with {EVERYONE}")
    return signing.choice_item(agent(decision["agent"]), decision["id"], decision["question"], label)


def row_answer_signed(row: dict, to: str, label: str) -> dict:
    """Args:
        row: an open decision row of the register.
        to: the row's adding agent.
        label: the answer picks() accepts for the row.

    Returns:
        The post to that agent that a Match pick signs, in the words the
        inbox's own answer sends.
    """
    if not to or EVERYONE in to:
        raise ToolError(f"a decision row is answered only when an agent other than {EVERYONE} holds role A on it")
    return signing.message_item(agent(to), ANSWER_CLASS, f"Decision {row['task']}\nAnswer: {label}", "", "", "")


def answered(record: dict | None, row: dict) -> bool:
    return record is not None and record["sha256"] == digest(row["command"])


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
        status = decision_status(record, time.time())
        if status != "pending":
            return f"already {status}"
        self.operator_proven(proof, item["signed"])
        if record.get("hooked"):
            decided, changed = self.decisions.decide(item["id"], {"status": "decided", "choice": item["label"], "proof": proof})
            return "decided · answered through the permission hook" if changed else f"already {decided['status']}"
        message = self.stored_message(item["signed"], proof, None)
        decided, changed = self.decisions.decide(item["id"], {"status": "decided", "choice": item["label"], "message": message["id"]})
        if not changed:
            self.messages.remove(message["id"])
            return f"already {decided['status']}"
        run = self.radioed(message, CHANNELS[ANSWER_CLASS])
        where = f"{ANSWER_CLASS} to {message['address']}"
        return f"decided · {where}" if run["code"] == 0 else f"decided · {where} failed ({run['code']})"

    def answer_row(self, item: dict, proof: dict) -> str:
        """Args:
            item: a checked operator item of a decision row whose label is
                the picked option and whose signed is row_answer_signed().
            proof: the relayed signature, verified here once, as the hub
                sends the answer itself.

        Returns:
            The outcome words for the stream; the row stays open until its
            agent closes it, while answers keeps it off the Match stack.
        """
        tasks = read_register(self.council / REGISTER)
        row = next((row for row in operator_rows(tasks) if row["task"] == item["id"]), None)
        if row is None or not picks(row, item["label"]) or row_answer_signed(row, adder(tasks[item["id"]]), item["label"]) != item["signed"]:
            return "refused: the row changed since the release"
        self.operator_proven(proof, item["signed"])
        with self.answers.changed:
            if answered(self.answers.get(item["id"]), row):
                return "already answered"
            message = self.stored_message(item["signed"], proof, None)
            self.answers.insert(item["id"], {"sha256": digest(row["command"]), "label": item["label"], "message": message["id"]})
        run = self.radioed(message, CHANNELS[ANSWER_CLASS])
        where = f"{ANSWER_CLASS} to {message['address']}"
        return f"answered · {where}" if run["code"] == 0 else f"answered · {where} failed ({run['code']})"
