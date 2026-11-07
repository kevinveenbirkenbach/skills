from __future__ import annotations

import secrets
import time

from .asking import ask_state
from .cleanup import cleanup_request
from .denying import DENIABLE, DENY_KEYS, denial_note, request_status, request_words
from .errors import Conflict, Missing, ToolError
from .fields import decode, expect, field
from .offices import office_request
from .records import digest, shown
from .register import REGISTER, operator_rows, read_register, runnable
from .rules import rule_matches, subject_of
from .signed import (
    ask_signed,
    operator_signed,
    request_signed,
    review_signed,
    signing,
    verifier,
)

BATCH_LIMIT = 100
INBOX_KINDS = ("review", "ask", "decision", "operator", "rule")
VERBS = ("approve", "reject")
ITEM_KEYS = ("kind", "id", "verb", "label", "sha256")


def inbox_item(raw: dict, label: str, title: str, gate: str, subject: dict | None) -> dict:
    """Args:
        raw: the page's entry, already checked for its keys and types.
        label: the chosen option of a decision, else empty.
        title: what the stream logs for the item.
        gate: the review gate, else empty.
        subject: what an approval signs; None for a decision.

    Returns:
        The batch item. A denial of a deniable kind signs its own item and
        carries the note that tells the requesting agent.
    """
    note = denial_note(raw) if raw["verb"] == "reject" and raw["kind"] in DENIABLE else None
    signed = subject if raw["verb"] == "approve" else None if note is None else signing.denial_item(subject, note["channel"], note["reason"])
    sha256 = raw["sha256"] if raw["kind"] == "operator" else ""
    return {"kind": raw["kind"], "id": raw["id"], "verb": raw["verb"], "label": label, "sha256": sha256, "title": shown(title)[:200], "gate": gate, "signed": signed, "note": note}


class Approving:
    def keys(self) -> list[dict]:
        try:
            entries = signing.load_pinned(self.approvers)
        except signing.Refused:
            return []
        return [{"id": entry["id"], "alg": signing.ALGORITHMS[entry["alg"]]} for entry in entries]

    def covered(self, proof: object, signed: list[dict], now: float) -> dict | None:
        """Args:
            proof: {"payload", "assertion"} from the page, or None.
            signed: the executor items the approval must list.
            now: the current time in epoch seconds.

        Returns:
            The proof to relay, None when nothing needs a signature. The hub
            verifies the signature of a denial itself, since it acts on it;
            of an approval it checks the shape, and the executors verify.
        """
        if not signed:
            if proof is not None:
                raise ToolError("proof must be null when no item needs a signature")
            return None
        if not isinstance(proof, dict):
            raise ToolError("nicht signiert: an approval of an ask, review or operator command needs the passkey signature")
        expect(proof, ("payload", "assertion"))
        try:
            payload = signing.checked_approval(proof["payload"], now)
        except signing.Refused as error:
            raise ToolError(f"proof: {error}") from None
        if not isinstance(proof["assertion"], dict) or any(signing.item_hash(item) not in payload["items"] for item in signed):
            raise ToolError("proof must carry the assertion and list every approved item")
        for item in signed:
            if item["kind"] == "deny":
                self.proven(proof, item)
        return {"payload": payload, "assertion": proof["assertion"]}

    def proven(self, proof: object, item: dict) -> dict:
        trust = verifier.Trust(approvers=self.approvers, replay=self.replay, origin=signing.origin_of(self.public_port))
        try:
            verifier.check(proof, item, "", trust, time.time())
        except signing.Refused as error:
            raise ToolError(f"nicht signiert: {error}") from None
        return proof

    def automate(self, kind_name: str, record: dict) -> None:
        now = time.time()
        subject = subject_of(kind_name, record)
        rule = next((rule for rule in self.rules.listed() if rule_matches(rule, kind_name, subject, now)), None)
        if rule is None:
            return
        title = {"review": record.get("title"), "ask": f"{record.get('tool')} {record.get('command')}", "decision": record.get("question")}[kind_name]
        signed = None if kind_name == "decision" else subject["item"]
        item = {"kind": kind_name, "id": record["id"], "verb": "approve", "label": record.get("recommended", ""), "sha256": "", "title": shown(title)[:200], "gate": record.get("gate", ""), "signed": signed, "note": None}
        batch = self.batches.add([item], f"rule:{rule['id']}", rule.get("proof"), self.apply)
        words = f"{rule['kind']} {rule['tool']} {rule['pattern']}".replace("  ", " ")
        self.log.add({"kind": "rule", "title": f"Regel gibt frei: {item['title']}", "text": words, "ref": {"rule": rule["id"], "batch": batch["id"], "item": item["id"]}})

    def apply(self, batch: dict) -> None:
        for item in batch["items"]:
            try:
                outcome = self.settle_item(item, batch["proof"] if item["signed"] is not None else None)
            except (OSError, ToolError) as error:
                outcome = f"fehlgeschlagen: {error}"
            verb = "Freigabe" if item["verb"] == "approve" else "Ablehnung"
            label = f" → {item['label']}" if item["label"] else ""
            ref = {"kind": item["kind"], "id": item["id"], "verb": item["verb"], "source": batch["source"], "outcome": outcome}
            self.log.add({"kind": "approval", "title": f"{verb} {item['kind']}: {item['title']}{label}", "text": f"{outcome} ({batch['source']})", "ref": ref})

    def settle_item(self, item: dict, proof: dict | None) -> str:
        approve = item["verb"] == "approve"
        if item["note"] is not None:
            return self.deny(item, proof)
        if item["kind"] == "operator":
            return self.queue_job(item, proof)
        if item["kind"] == "ask":
            record = self.asks.get(item["id"])
            if record is None or ask_state(record, time.time())["status"] == "expired":
                return "abgelaufen"
            record, changed = self.asks.decide(item["id"], {"status": "allowed" if approve else "denied", "proof": proof})
        elif item["kind"] == "review":
            record, changed = self.reviews.decide(item["id"], {"status": "approved" if approve else "rejected", "proof": proof})
        else:
            record, changed = self.decisions.decide(item["id"], {"status": "decided", "choice": item["label"]})
        if record is None:
            return "unbekannt"
        return record["status"] if changed else f"schon {record['status']}"

    def item_of(self, raw: object, tasks: dict[str, dict]) -> dict:
        if not isinstance(raw, dict):
            raise ToolError("every item must be an object with kind, id, verb, label and sha256, and a denial also channel and reason")
        kind_name, verb = raw.get("kind"), raw.get("verb")
        expect(raw, (*ITEM_KEYS, *DENY_KEYS) if verb == "reject" and kind_name in DENIABLE else ITEM_KEYS)
        if kind_name not in INBOX_KINDS or verb not in VERBS or not isinstance(raw["label"], str) or not isinstance(raw["sha256"], str):
            raise ToolError(f"kind must be one of {', '.join(INBOX_KINDS)}, verb approve or reject, label and sha256 text")
        if kind_name == "operator":
            row = next((row for row in operator_rows(tasks) if row["task"] == raw["id"]), None)
            if row is None:
                raise Missing(str(raw["id"]))
            if verb == "approve" and not runnable(row):
                raise ToolError("an operator row is approved only when it holds a directory and a command")
            if digest(row["command"]) != raw["sha256"]:
                raise Conflict({"id": row["task"], "status": "changed"})
            if row["task"] in self.open_jobs():
                raise Conflict({"id": row["task"], "status": "queued"})
            return inbox_item(raw, "", row["command"], "", operator_signed(row))
        if kind_name == "rule" and verb == "approve":
            raise ToolError("a rule request is accepted in its row, with the passkey signature over the rule itself")
        item_id = field(raw, "id")
        record = {"review": self.reviews, "ask": self.asks, "decision": self.decisions, "rule": self.rule_requests}[kind_name].get(item_id)
        if record is None:
            raise Missing(item_id)
        status = ask_state(record, time.time())["status"] if kind_name == "ask" else request_status(record, time.time()) if kind_name == "rule" else record["status"]
        if status != "pending":
            raise Conflict({"id": item_id, "status": status})
        label = ""
        if kind_name == "decision":
            if verb != "approve" or raw["label"] not in [option["label"] for option in record["options"]]:
                raise ToolError("a decision is approved with one of its option labels")
            label = raw["label"]
        if kind_name == "rule":
            return inbox_item(raw, "", f"Regel {request_words(record)}", "", request_signed(record))
        title = {"review": record.get("title"), "ask": f"{record.get('tool')} {record.get('command')}", "decision": record.get("question")}[kind_name]
        subject = {"review": review_signed, "ask": ask_signed}[kind_name](record) if kind_name != "decision" else None
        return inbox_item(raw, label, title, record.get("gate", ""), subject)

    def checked(self, raw: object) -> list[dict]:
        if not isinstance(raw, list) or not 1 <= len(raw) <= BATCH_LIMIT:
            raise ToolError(f"items must be a list of 1 to {BATCH_LIMIT} objects")
        tasks = read_register(self.council / REGISTER)
        items = [self.item_of(entry, tasks) for entry in raw]
        keys = [(item["kind"], item["id"]) for item in items]
        if len(set(keys)) != len(keys):
            raise ToolError("items must be distinct")
        if len(items) > 1 and any(item["kind"] == "review" and item["verb"] == "approve" and item["gate"] != "pass" for item in items):
            raise ToolError("a review whose gate is not green is approved only on its own")
        if any(self.batches.holds(kind_name, item_id) for kind_name, item_id in keys):
            raise Conflict({"status": "held"})
        return items

    def sign(self, body: bytes) -> dict:
        payload = decode(body)
        expect(payload, ("items",))
        raw = payload["items"]
        if cleanup_request(raw):
            signed = self.deletable(raw)
        elif office_request(raw):
            signed = self.appointable(raw)
        else:
            signed = [item["signed"] for item in self.checked(raw) if item["signed"] is not None]
        hashes = [signing.item_hash(item) for item in signed]
        credentials = [key["id"] for key in self.keys()]
        if not hashes:
            return {"payload": None, "challenge": None, "credentials": credentials}
        request = signing.approval_payload(hashes, secrets.token_hex(16), int(time.time()) + signing.LIFETIME)
        return {"payload": request, "challenge": signing.challenge(request), "credentials": credentials}

    def approve(self, body: bytes) -> dict:
        payload = decode(body)
        expect(payload, ("items", "proof"))
        items = self.checked(payload["items"])
        proof = self.covered(payload["proof"], [item["signed"] for item in items if item["signed"] is not None], time.time())
        return self.batches.add(items, "operator", proof, self.apply)

    def undo(self, batch_id: str) -> dict:
        batch = self.batches.undo(batch_id)
        titles = ", ".join(item["title"][:80] for item in batch["items"])
        self.log.add({"kind": "approval", "title": f"Rückgängig: {titles}", "text": batch["source"], "ref": {"batch": batch_id}})
        return {"id": batch_id, "status": "undone"}
