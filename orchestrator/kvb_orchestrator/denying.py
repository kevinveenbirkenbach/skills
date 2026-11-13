from __future__ import annotations

import time

from .asking import ASK_LIFETIME, ask_state
from .council import read_claims
from .errors import ToolError
from .messaging import DIRECT, EVERYONE, TO_ALL
from .register import REGISTER, adder, operator_rows, read_register
from .signed import operator_signed, signing
from .skill_scripts import RASCI

DENIABLE = ("ask", "operator", "rule")
DENY_KEYS = ("channel", "reason", "to")
DENY_CHANNELS = {**DIRECT, **{name: words for name, words in TO_ALL.items() if name != "mayday"}}
REASON_LIMIT = 2000


def denial_note(raw: dict, requester: str) -> dict:
    """Args:
        raw: the page's denial entry with channel and reason.
        requester: the requesting agent's name as the operator saw it when
            signing; the signature binds it as the addressee.
    """
    channel, reason = raw["channel"], raw["reason"]
    if not isinstance(channel, str) or channel not in DENY_CHANNELS:
        raise ToolError(f"channel must be one of {', '.join(DENY_CHANNELS)}")
    if not isinstance(reason, str) or len(reason) > REASON_LIMIT:
        raise ToolError(f"reason must be text of at most {REASON_LIMIT} characters")
    return {"channel": channel, "reason": " ".join(reason.split()), "to": requester if channel in DIRECT else EVERYONE}


def requester_of(claims: list[dict], who: str) -> tuple[str, str]:
    """Args:
        claims: the council's claims.
        who: an agent name or session; empty when unknown.

    Returns:
        The agent name and radio address of the claims whose agent or
        session is who, else who for both. Empty for an empty who and when
        those claims name more than one agent, so a planted claim makes a
        denial reach nobody rather than the planter.
    """
    found = [claim for claim in claims if claim["address"] and who in (claim["agent"], claim["session"])] if who else []
    if len({claim["agent"] for claim in found}) > 1:
        return ("", "")
    return (found[0]["agent"], found[0]["address"]) if found else (who, who)


def denial_text(what: str, requester: str, reason: str) -> str:
    words = f"Denied by the operator: {what} (from {requester or 'an agent'})."
    return f"{words} Reason: {reason}" if reason else words


def request_words(record: dict) -> str:
    return " ".join(part for part in (record["kind"], record["tool"], record["pattern"]) if part) + f" in {record['scope']}"


def request_status(record: dict, now: float) -> str:
    lapsed = record["created_ts"] + ASK_LIFETIME <= now or record["expires"] <= now
    return "expired" if record["status"] == "pending" and lapsed else record["status"]


class Denying:
    def deny(self, item: dict, proof: dict | None) -> str:
        """Args:
            item: a checked inbox item with verb reject and its note.
            proof: the relayed signature over the denial item.

        Returns:
            The outcome words for the stream: what changed and whom the
            radio told.
        """
        note = item["note"]
        if item["kind"] == "operator":
            tasks = read_register(self.council / REGISTER)
            row = next((row for row in operator_rows(tasks) if row["task"] == item["id"]), None)
            if row is None or signing.denial_item(operator_signed(row), note["channel"], note["reason"], note["to"]) != item["signed"]:
                return "refused: the row changed since the denial"
            if item["id"] in self.open_jobs():
                return "already running"
            run = self.scripts.run(RASCI, ["set", item["id"], "--status", "stopped"])
            if run["code"] != 0:
                return f"failed: {run['command']} → {run['code']}"
            command, directory = row["command"][:200], row["directory"]
            return f"stopped · {self.tell(item, proof, adder(tasks[item['id']]), f'operator command {command} in {directory}')}"
        ledger = self.asks if item["kind"] == "ask" else self.rule_requests
        record = ledger.get(item["id"])
        if record is None:
            return "unknown"
        now = time.time()
        if (ask_state(record, now)["status"] if item["kind"] == "ask" else request_status(record, now)) == "expired":
            return "expired"
        record, changed = ledger.decide(item["id"], {"status": "denied", "proof": proof, **note})
        if not changed:
            return f"already {record['status']}"
        if item["kind"] == "ask":
            tool, command = record["tool"], record["command"][:200]
            return f"denied · {self.tell(item, proof, record['session'], f'ask {tool}: {command}')}"
        return f"denied · {self.tell(item, proof, record['agent'], f'rule request {request_words(record)}')}"

    def addressee(self, who: str) -> tuple[str, str]:
        return requester_of(read_claims(self.council), who)

    def tell(self, item: dict, proof: dict | None, who: str, what: str) -> str:
        """Args:
            item: the denied inbox item: its note holds the chosen channel,
                the reason and the signed addressee, its signed the denial
                item the proof lists.
            proof: the operator's signature over the denial, kept with the
                message operator_message proves.
            who: the requesting agent's name or session; empty when unknown.
            what: what was denied, in the agent's words.

        Returns:
            The class and addressee for the outcome line.
        """
        note = item["note"]
        channel = note["channel"]
        direct = channel in DIRECT
        address = self.addressee(note["to"])[1] if direct else EVERYONE
        if direct and not address:
            return f"no recipient for {channel}"
        text = denial_text(what, self.addressee(who)[0], note["reason"])
        where = f"{channel} to {address}" if direct else f"{channel} to all"
        fields = {"to": note["to"], "address": address, "text": text, "upload": None, "voice": None, "voice_sha256": "", "class": channel}
        record = self.messages.add({**fields, "denial": item["signed"], "proof": proof, "created_ts": time.time()})
        run = self.radioed(record, DENY_CHANNELS[channel])
        return where if run["code"] == 0 else f"{where} failed ({run['code']})"
