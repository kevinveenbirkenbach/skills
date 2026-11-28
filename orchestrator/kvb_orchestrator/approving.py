from __future__ import annotations

import secrets
import time

from .asking import ask_state
from .choosing import (
    PICKED,
    answer_signed,
    answered,
    decision_status,
    picks,
    row_answer_signed,
)
from .cleanup import cleanup_request
from .denying import (
    DENIABLE,
    DENY_KEYS,
    LAPSING,
    NOTED,
    denial_note,
    request_status,
    request_words,
)
from .errors import Conflict, Missing, ToolError
from .fields import decode, expect, field, visible
from .firewall import settings_request
from .gating import gate_request
from .offices import office_request
from .prunes import prune_request
from .queueing import queue_request
from .records import digest, shown
from .register import REGISTER, adder, operator_rows, read_register, runnable
from .rules import enable_request, rule_matches, subject_of
from .scheduling import schedule_request
from .signed import (
    ask_signed,
    operator_signed,
    passkey,
    request_signed,
    review_signed,
    signing,
    verifier,
)
from .tasking import task_request
from .triage import DISMISS_VERB, dismiss_entry, dismiss_request

BATCH_LIMIT = 100
INBOX_KINDS = ("review", "ask", "decision", "operator", "rule")
VERBS = ("approve", "reject")
ITEM_KEYS = ("kind", "id", "verb", "label", "sha256")


def inbox_item(raw: dict, label: str, title: str, gate: str, subject: dict | None, requester: str) -> dict:
    """Args:
        raw: the page's entry, already checked for its keys and types.
        label: the chosen option of a decision, else empty.
        title: what the stream logs for the item.
        gate: the review gate, else empty.
        subject: what an approval signs; for a decision the answer post to
            the asking agent.
        requester: the requesting agent's name for a denial, else empty.

    Returns:
        The batch item. A denial of a deniable kind signs its own item and
        carries the note that tells the requesting agent.
    """
    note = denial_note(raw, requester) if raw["verb"] == "reject" and "channel" in raw else None
    signed = subject if raw["verb"] == "approve" else None if note is None else signing.denial_item(subject, note["channel"], note["reason"], note["to"])
    sha256 = raw["sha256"] if raw["kind"] == "operator" else ""
    return {"kind": raw["kind"], "id": raw["id"], "verb": raw["verb"], "label": label, "sha256": sha256, "title": shown(title)[:200], "gate": gate, "signed": signed, "note": note}


def signed_of(items: list[dict]) -> list[dict]:
    """Returns:
        Every item the approval of items must list: each item's own signed
        item and the payload bindings of operator commands.
    """
    return [entry for item in items for entry in ([item["signed"]] if item["signed"] is not None else []) + item.get("bound", [])]


class Approving:
    def keys(self) -> list[dict]:
        try:
            entries = signing.load_pinned(self.approvers)
        except signing.Refused:
            return []
        return [{"id": entry["id"], "alg": signing.ALGORITHMS[entry["alg"]]} for entry in entries]

    def challenge_for(self, items: list[dict]) -> dict:
        """Returns:
            The approval payload over the items, its WebAuthn challenge and the
            pinned credential ids; payload and challenge are None for no item.

        Raises:
            ToolError from visible() for an item holding a text no prompt
            shows as signed, whatever source missed it.
        """
        visible(items)
        credentials = [key["id"] for key in self.keys()]
        if not items:
            return {"payload": None, "challenge": None, "credentials": credentials}
        request = signing.approval_payload([signing.item_hash(item) for item in items], secrets.token_hex(16), int(time.time()) + signing.lifetime(items))
        return {"payload": request, "challenge": signing.challenge(request), "credentials": credentials}

    def operator_proven(self, proof: object, item: dict) -> dict:
        """Args:
            proof: {"payload", "assertion"} the page sends for an act the hub
                runs itself as the operator.
            item: the hub's own item for that act.

        Returns:
            The proof, once a pinned key signed an unexpired approval listing
            the item, used here for the first time.
        """
        trust = verifier.Trust(approvers=self.approvers, replay=self.replay, origin=signing.origin_of(self.public_port))
        try:
            verifier.check(proof, item, "", trust, time.time())
        except signing.Refused as error:
            raise ToolError(f"not signed: {error}") from None
        return proof

    def still_signed(self, proof: dict, item: dict) -> None:
        """Raises:
            ToolError unless a pinned key signed the stored proof and it lists
            the item; expiry and replay held when the hub stored it.
        """
        try:
            if signing.item_hash(item) not in proof["payload"]["items"]:
                raise signing.Refused("the signature does not list this item")
            passkey.verify_assertion(proof["assertion"], proof["payload"], verifier.pinned(self.approvers), signing.origin_of(self.public_port))
        except signing.Refused as error:
            raise ToolError(f"not signed: {error}") from None

    def covered(self, proof: object, signed: list[dict], now: float) -> dict | None:
        """Args:
            proof: {"payload", "assertion"} from the page, or None.
            signed: the executor items the approval must list.
            now: the current time in epoch seconds.

        Returns:
            The proof to relay, None when nothing needs a signature. The hub
            verifies the signature of a denial itself, since it acts on it;
            of an approval it checks the shape, and the executors verify,
            the hub itself for a choice answer when it sends it.
        """
        if not signed:
            if proof is not None:
                raise ToolError("proof must be null when no item needs a signature")
            return None
        if not isinstance(proof, dict):
            raise ToolError("not signed: an approval of an ask, review, choice or operator command needs the passkey signature")
        expect(proof, ("payload", "assertion"))
        try:
            payload = signing.checked_approval(proof["payload"], now, signing.lifetime(signed))
        except signing.Refused as error:
            raise ToolError(f"proof: {error}") from None
        if not isinstance(proof["assertion"], dict) or any(signing.item_hash(item) not in payload["items"] for item in signed):
            raise ToolError("proof must carry the assertion and list every approved item")
        for item in signed:
            if item["kind"] == "deny":
                self.operator_proven(proof, item)
        return {"payload": payload, "assertion": proof["assertion"]}

    def automate(self, kind_name: str, record: dict) -> None:
        now = time.time()
        subject = subject_of(kind_name, record, self.deciders(kind_name, record))
        rule = next((rule for rule in self.rules.listed() if rule_matches(rule, kind_name, subject, now)), None)
        if rule is None:
            return
        title = {"review": record.get("title"), "ask": f"{record.get('tool')} {record.get('command')}", "decision": record.get("question")}[kind_name]
        signed = None if kind_name == "decision" else subject["item"]
        item = {"kind": kind_name, "id": record["id"], "verb": "approve", "label": record.get("recommended", ""), "sha256": "", "title": shown(title)[:200], "gate": record.get("gate", ""), "signed": signed, "note": None}
        batch = self.batches.add([item], f"rule:{rule['id']}", rule.get("proof"), self.apply)
        words = f"{rule['kind']} {rule['tool']} {rule['pattern']}".replace("  ", " ")
        self.log.add({"kind": "rule", "title": f"Rule grants: {item['title']}", "text": words, "ref": {"rule": rule["id"], "batch": batch["id"], "item": item["id"]}})

    def apply(self, batch: dict) -> None:
        """Args:
            batch: its dismissals of a Match release first, through
                apply_dismissals(), then the rest settled item by item;
                operator rows after every other item, so a commit row's job
                never starts before the reviews its verify steps check are
                decided.
        """
        dismissed = [item for item in batch["items"] if item["verb"] == DISMISS_VERB]
        if dismissed:
            self.apply_dismissals({**batch, "items": dismissed})
        for item in sorted((item for item in batch["items"] if item["verb"] != DISMISS_VERB), key=lambda item: item["kind"] == "operator"):
            try:
                outcome = self.settle_item(item, batch["proof"] if item["signed"] is not None else None)
            except (OSError, ToolError) as error:
                outcome = f"failed: {error}"
            verb = "Grant" if item["verb"] == "approve" else "Denial"
            label = f" → {item['label']}" if item["label"] else ""
            ref = {"kind": item["kind"], "id": item["id"], "verb": item["verb"], "source": batch["source"], "outcome": outcome}
            self.log.add({"kind": "approval", "title": f"{verb} {item['kind']}: {item['title']}{label}", "text": f"{outcome} ({batch['source']})", "ref": ref})

    def settle_item(self, item: dict, proof: dict | None) -> str:
        approve = item["verb"] == "approve"
        if item["note"] is not None:
            return self.deny(item, proof)
        if item["kind"] == "operator":
            if item["label"]:
                return self.answer_row(item, proof)
            if not all(self.payload_holds(bound) for bound in item.get("bound", [])):
                return "refused: a payload file changed since the release"
            return self.queue_job(item, proof)
        if item["kind"] == "ask":
            record = self.asks.get(item["id"])
            if record is None or ask_state(record, time.time())["status"] == "expired":
                return "expired"
            record, changed = self.asks.decide(item["id"], {"status": "allowed" if approve else "denied", "proof": proof})
        elif item["kind"] == "review":
            record, changed = self.reviews.decide(item["id"], {"status": "approved" if approve else "rejected", "proof": proof})
        elif item["signed"] is not None:
            return self.answer_choice(item, proof)
        else:
            record, changed = self.decisions.decide(item["id"], {"status": "decided", "choice": item["label"]})
        if record is None:
            return "unknown"
        return record["status"] if changed else f"already {record['status']}"

    def requester(self, raw: dict, who: str) -> str:
        """Returns:
            The agent a denial addresses: the requester the inbox showed, or
            for a direct channel the claimed agent the operator picked
            instead; empty for every other item.

        Raises:
            Conflict when raw["to"] is neither, the requester sent back as
            raw["to"].
        """
        if raw["verb"] != "reject" or "channel" not in raw:
            return ""
        name = self.addressee(who)[0]
        if raw["to"] != name and not self.pickable(raw["channel"], raw["to"]):
            raise Conflict({"id": raw["id"], "status": "recipient changed", "to": name})
        return raw["to"]

    def operator_entry(self, raw: dict, tasks: dict[str, dict]) -> dict:
        """Args:
            raw: a checked inbox entry of kind operator.
            tasks: the register.

        Returns:
            The signed item of the operator row raw names, once its task,
            command and directory pass visible().
        """
        row = next((row for row in operator_rows(tasks) if row["task"] == raw["id"]), None)
        if row is None:
            raise Missing(str(raw["id"]))
        visible({name: row[name] for name in ("task", "command", "directory")})
        if row["check"] == "decision" and raw["verb"] == "approve":
            return self.row_answer_entry(raw, row, tasks)
        if raw["verb"] == "approve" and not runnable(row):
            raise ToolError("an operator row is approved only when it holds a directory and a command")
        if digest(row["command"]) != raw["sha256"]:
            raise Conflict({"id": row["task"], "status": "changed"})
        if row["task"] in self.open_jobs():
            raise Conflict({"id": row["task"], "status": "queued"})
        bound = self.payload_bound(row, raw["payload"]) if "payload" in raw else []
        return {**inbox_item(raw, "", row["command"], "", operator_signed(row), self.requester(raw, adder(tasks[row["task"]]))), "bound": bound}

    def row_answer_entry(self, raw: dict, row: dict, tasks: dict[str, dict]) -> dict:
        """Returns:
            The signed item of a decision row answered with one of its option
            labels or one line of other text: the post row_answer_signed()
            builds to the row's agent.
        """
        if not picks(row, raw["label"]) or "payload" in raw:
            raise ToolError("a decision row is approved with one of its option labels or one line of other text, and no payload")
        visible({"label": raw["label"]})
        if digest(row["command"]) != raw["sha256"]:
            raise Conflict({"id": row["task"], "status": "changed"})
        if answered(self.answers.get(row["task"]), row):
            raise Conflict({"id": row["task"], "status": "answered"})
        return inbox_item(raw, raw["label"], row["command"], "", row_answer_signed(row, adder(tasks[row["task"]]), raw["label"]), "")

    def item_of(self, raw: object, tasks: dict[str, dict]) -> dict:
        if not isinstance(raw, dict):
            raise ToolError("every item must be an object with kind, id, verb, label and sha256, and a denial also channel, reason and to")
        kind_name, verb = raw.get("kind"), raw.get("verb")
        noted = verb == "reject" and (kind_name in DENIABLE or kind_name in (*NOTED, *LAPSING) and "channel" in raw)
        shown = ("payload",) if kind_name == "operator" and verb == "approve" and "payload" in raw else ()
        expect(raw, (*ITEM_KEYS, *DENY_KEYS) if noted else (*ITEM_KEYS, *shown))
        if kind_name not in INBOX_KINDS or verb not in VERBS or not isinstance(raw["label"], str) or not isinstance(raw["sha256"], str):
            raise ToolError(f"kind must be one of {', '.join(INBOX_KINDS)}, verb approve or reject, label and sha256 text")
        if kind_name == "operator":
            return self.operator_entry(raw, tasks)
        if kind_name == "rule" and verb == "approve":
            raise ToolError("a rule request is accepted in its row, with the passkey signature over the rule itself")
        item_id = field(raw, "id")
        record = {"review": self.reviews, "ask": self.asks, "decision": self.decisions, "rule": self.rule_requests}[kind_name].get(item_id)
        if record is None:
            raise Missing(item_id)
        status = ask_state(record, time.time())["status"] if kind_name == "ask" else request_status(record, time.time()) if kind_name == "rule" else decision_status(record, time.time()) if kind_name == "decision" else record["status"]
        lapsed = status == "expired" and noted and kind_name in LAPSING
        if status != "pending" and not lapsed:
            raise Conflict({"id": item_id, "status": status})
        label = ""
        if kind_name == "decision" and not lapsed:
            if verb != "approve" or not picks(record, raw["label"]):
                raise ToolError("a decision is approved with one of its option labels, a multi decision with one or more of them in option order, or with one line of other text")
            visible([{"label": part} for part in raw["label"].split(PICKED)])
            label = raw["label"]
        if kind_name == "rule":
            return inbox_item(raw, "", f"Rule {request_words(record)}", "", request_signed(record), self.requester(raw, record["agent"]))
        title = {"review": record.get("title"), "ask": f"{record.get('tool')} {record.get('command')}", "decision": record.get("question")}[kind_name]
        subject = {"review": review_signed, "ask": ask_signed}[kind_name](record) if kind_name != "decision" else answer_signed(record, label)
        return inbox_item(raw, label, title, record.get("gate", ""), subject, self.requester(raw, record["session"] if kind_name == "ask" else record.get("agent", "")))

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

    def released(self, raw: object) -> list[dict]:
        """Args:
            raw: the page's entries: inbox entries (checked()) and the dismiss
                entries (dismissable()) of a Match release, which one
                signature covers together.

        Returns:
            The batch items of the inbox entries, then of the dismissals.

        Raises:
            ToolError as checked() for no inbox entry and no dismissal, and
            for two items of one request.
        """
        dropped = [entry for entry in raw if dismiss_entry(entry)] if isinstance(raw, list) else []
        if not dropped:
            return self.checked(raw)
        kept = [entry for entry in raw if not dismiss_entry(entry)]
        items = (self.checked(kept) if kept else []) + self.dismissable(dropped)
        keys = [(item["kind"], item["id"]) for item in items]
        if len(set(keys)) != len(keys):
            raise ToolError("items must be distinct")
        return items

    def sign(self, body: bytes) -> dict:
        payload = decode(body)
        expect(payload, ("items",))
        raw = payload["items"]
        if cleanup_request(raw):
            signed = self.deletable(raw)
        elif office_request(raw):
            signed = self.appointable(raw)
        elif task_request(raw):
            signed = self.task_changes(raw)
        elif gate_request(raw):
            signed = self.gate_changes(raw)
        elif queue_request(raw):
            signed = self.queue_changes(raw)
        elif schedule_request(raw):
            signed = self.schedule_changes(raw)
        elif prune_request(raw):
            signed = self.prune_changes(raw)
        elif settings_request(raw):
            signed = self.settings_changes(raw)
        elif dismiss_request(raw):
            signed = [item["signed"] for item in self.dismissable(raw)]
        elif enable_request(raw):
            signed = self.enable_items(raw)
            return {**self.challenge_for(signed), "enables": signed[0]["rule"]}
        else:
            signed = signed_of(self.released(raw))
        return self.challenge_for(signed)

    def approve(self, body: bytes) -> dict:
        """Args:
            body: {"items", "proof"}: the entries released() takes and the
                one passkey assertion over their signed items; the hub
                verifies a dismissal's signature itself, since it acts on it.
        """
        payload = decode(body)
        expect(payload, ("items", "proof"))
        items = self.released(payload["items"])
        proof = self.covered(payload["proof"], signed_of(items), time.time())
        for item in items:
            if item["verb"] == DISMISS_VERB:
                self.operator_proven(proof, item["signed"])
        return self.batches.add(items, "operator", proof, self.apply)

    def undo(self, batch_id: str) -> dict:
        batch = self.batches.undo(batch_id)
        titles = ", ".join(item["title"][:80] for item in batch["items"])
        self.log.add({"kind": "approval", "title": f"Undone: {titles}", "text": batch["source"], "ref": {"batch": batch_id}})
        return {"id": batch_id, "status": "undone"}
