from __future__ import annotations

import time

from .asking import ASK_LIFETIME, ask_state
from .council import HUMAN, read_claims
from .errors import ToolError
from .messaging import DIRECT, TO_ALL
from .register import REGISTER, adder, operator_rows, read_register
from .signed import operator_signed, signing
from .skill_scripts import RADIO, RASCI

DENIABLE = ("ask", "operator", "rule")
DENY_KEYS = ("channel", "reason")
DENY_CHANNELS = {**DIRECT, **{name: words for name, words in TO_ALL.items() if name != "mayday"}}
REASON_LIMIT = 2000


def denial_note(raw: dict) -> dict:
    channel, reason = raw["channel"], raw["reason"]
    if not isinstance(channel, str) or channel not in DENY_CHANNELS:
        raise ToolError(f"channel must be one of {', '.join(DENY_CHANNELS)}")
    if not isinstance(reason, str) or len(reason) > REASON_LIMIT:
        raise ToolError(f"reason must be text of at most {REASON_LIMIT} characters")
    return {"channel": channel, "reason": " ".join(reason.split())}


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
            if row is None or signing.denial_item(operator_signed(row), note["channel"], note["reason"]) != item["signed"]:
                return "verweigert: die Zeile hat sich seit der Ablehnung geändert"
            if item["id"] in self.open_jobs():
                return "läuft schon"
            run = self.scripts.run(RASCI, ["set", item["id"], "--status", "stopped"])
            if run["code"] != 0:
                return f"fehlgeschlagen: {run['command']} → {run['code']}"
            command, directory = row["command"][:200], row["directory"]
            return f"gestoppt · {self.tell(note, proof, adder(tasks[item['id']]), f'operator command {command} in {directory}')}"
        ledger = self.asks if item["kind"] == "ask" else self.rule_requests
        record = ledger.get(item["id"])
        if record is None:
            return "unbekannt"
        now = time.time()
        if (ask_state(record, now)["status"] if item["kind"] == "ask" else request_status(record, now)) == "expired":
            return "abgelaufen"
        record, changed = ledger.decide(item["id"], {"status": "denied", "proof": proof, **note})
        if not changed:
            return f"schon {record['status']}"
        if item["kind"] == "ask":
            tool, command = record["tool"], record["command"][:200]
            return f"abgelehnt · {self.tell(note, proof, record['session'], f'ask {tool}: {command}')}"
        return f"abgelehnt · {self.tell(note, proof, record['agent'], f'rule request {request_words(record)}')}"

    def tell(self, note: dict, proof: dict | None, who: str, what: str) -> str:
        """Args:
            note: the chosen channel and the reason.
            proof: the operator's signature over the denial, kept with the
                message operator_message proves.
            who: the requesting agent's name or session; empty when unknown.
            what: what was denied, in the agent's words.

        Returns:
            The class and addressee for the outcome line.
        """
        claim = next((claim for claim in read_claims(self.council) if who and claim["address"] and who in (claim["agent"], claim["session"])), None)
        name, address = (claim["agent"], claim["address"]) if claim else (who, who)
        channel = note["channel"]
        direct = channel in DIRECT
        if direct and not address:
            return f"kein Empfänger für {channel}"
        text = denial_text(what, name, note["reason"])
        to, where = (address, f"{channel} an {address}") if direct else ("*", f"{channel} an alle")
        record = self.messages.add({"to": name if direct else "*", "address": to, "text": text, "upload": None, "class": channel, "proof": proof, "created_ts": time.time()})
        targets = ["--to", address] if direct else []
        run = self.scripts.run(RADIO, [*DENY_CHANNELS[channel], *targets, "--session", HUMAN, f"[kvb-orchestrator msg {record['id']}] {' '.join(text.split())}"])
        return where if run["code"] == 0 else f"{where} fehlgeschlagen ({run['code']})"
