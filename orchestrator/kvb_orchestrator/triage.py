from __future__ import annotations

import json
import time

from .council import NEWS, read_claims
from .errors import Conflict, Missing, ToolError
from .fields import decode, expect
from .jobs import console_of
from .previewing import card_id, merge_hash, review_card
from .records import digest, read_jsonl, shown
from .register import REGISTER, read_register
from .signed import signing

REQUEST_KINDS = ("open", "expired", "stale", "failed")
ALL = "all"
SCOPES = (*REQUEST_KINDS, ALL)
FAILED_JOBS = ("failed", "refused")
DISMISS_VERB = "dismiss"
DISMISS_KEYS = ("kind", "target", "id", "scope")
DISMISS_LIMIT = 100
REF_LIMIT = 200
TITLE_LIMIT = 200
TITLE_SHOWN = 80


def request_kind(item: dict) -> str:
    """Args:
        item: an inbox item, or one of lapsed_items(), the only items that
            carry expires.

    Returns:
        Its one request kind: expired for a lapsed ask or decision, open for
        a lapsed bound one (claude), whose dialog is still open in Claude;
        failed for an operator row whose last hub job failed or the runner
        refused; stale for a review or row whose tree or merge preview moved
        since it was added; open for every other request.
    """
    if "expires" in item:
        return "open" if item["claude"] else "expired"
    job = item["job"]
    if item["kind"] == "operator" and job is not None and job["status"] in FAILED_JOBS:
        return "failed"
    return "stale" if item["stale"] else "open"


def request_mark(command: str, job: dict | None) -> str:
    """Args:
        command: the command the request shows, "" for one without.
        job: the hub job console it shows, None for none.

    Returns:
        What a dismissal binds besides kind and id, so a row whose command
        changed or that ran again shows again.
    """
    return digest(json.dumps([command, "" if job is None else job["id"]]))


def dismiss_entry(entry: object) -> bool:
    return isinstance(entry, dict) and entry.get("kind") == signing.DISMISS_KIND


def dismiss_request(raw: object) -> bool:
    return isinstance(raw, list) and bool(raw) and all(dismiss_entry(entry) for entry in raw)


def hides(hidden: tuple[dict[str, str], set[str]], key: str, mark: str) -> bool:
    """Args:
        hidden: Triage.hidden_refs().
        key: <kind>:<id> of a request.
        mark: its request_mark().
    """
    dismissed, pending = hidden
    return key in pending or dismissed.get(key) == mark


class Triage:
    def hidden_refs(self) -> tuple[dict[str, str], set[str]]:
        """Returns:
            The request_mark() of every dismissed request by <kind>:<id>, and
            the keys a dismissal holds in its undo window; hides() keeps both
            out of the snapshot, Match and the badge for every browser.
        """
        dismissed = {key: mark for record in self.dismissals.listed() for key, mark in record["refs"].items()}
        pending = {f"{item['kind']}:{item['id']}" for batch in self.batches.listed() for item in batch["items"] if item["verb"] == DISMISS_VERB}
        return dismissed, pending

    def triaged(self, items: list[dict]) -> list[dict]:
        """Returns:
            The items hides() keeps, each with its request_kind() as request.
        """
        hidden = self.hidden_refs()
        return [{**item, "request": request_kind(item)} for item in items if not hides(hidden, f"{item['kind']}:{item['id']}", request_mark(item["command"], item["job"]))]

    def review_hidden(self, hidden: tuple[dict[str, str], set[str]], review_id: str) -> bool:
        return hides(hidden, review_card(review_id), request_mark("", None))

    def row_hidden(self, hidden: tuple[dict[str, str], set[str]], row: dict, consoles: dict[str, dict]) -> bool:
        return hides(hidden, card_id(row["task"]), request_mark(row["command"], console_of(consoles.get(row["task"]))))

    def review_moved(self, review: dict) -> bool:
        """Returns:
            Whether the commit card of a pending review is stale, read from
            the ledgers alone: its staged tree changed, or the runner saw its
            worktree's HEAD move.
        """
        preview = self.merge_previews.get(review_card(review["id"])) or {}
        return review.get("live_tree") not in (None, review["tree"]) or bool(preview.get("moved"))

    def row_moved(self, row: dict) -> bool:
        """Returns:
            Whether the command card of an open row is stale by its merge
            preview: the snapshot Match took is bound to another HEAD, merge
            base or diff than the preview the runner sent last. A changed
            payload file marks only the card, which reads the files.
        """
        snapshot = self.match_snapshots.get(card_id(row["task"]))
        preview = self.preview_of(row)
        if row["check"] == "decision" or snapshot is None or preview is None or not snapshot.get("previewed"):
            return False
        return snapshot["command_sha256"] == digest(row["command"]) and snapshot["hash"] != merge_hash(row, preview)

    def listed_requests(self) -> dict[str, dict]:
        """Returns:
            Every request the snapshot lists, the inbox and the lapsed asks
            and decisions, by <kind>:<id>.
        """
        now = time.time()
        claims = read_claims(self.council)
        directory = self.directory(claims, read_jsonl(self.council / NEWS), now)
        items = self.inbox(now, read_register(self.council / REGISTER), directory) + self.lapsed_items(now, directory)
        return {f"{item['kind']}:{item['id']}": item for item in items}

    def dismissable(self, raw: object) -> list[dict]:
        """Args:
            raw: the page's entries, each {"kind": "dismiss", "target", "id",
                "scope"}: the inbox kind and id of a request the snapshot
                lists, and the chip it is deleted from, one of SCOPES.

        Returns:
            One batch item per entry, its signed the dismiss_item() the
            passkey signs: a listed request no batch holds whose request
            kind is the scope, any kind under the scope all.

        Raises:
            ToolError for a malformed entry, Missing for a request the
            snapshot no longer lists, Conflict for a held one or one of
            another kind than its scope.
        """
        if not isinstance(raw, list) or not 1 <= len(raw) <= DISMISS_LIMIT:
            raise ToolError(f"items must be a list of 1 to {DISMISS_LIMIT} requests")
        listed = self.listed_requests()
        chosen: list[dict] = []
        for entry in raw:
            if not isinstance(entry, dict):
                raise ToolError("every item must be an object with kind, target, id and scope")
            expect(entry, DISMISS_KEYS)
            target, item_id, scope = entry["target"], entry["id"], entry["scope"]
            if not all(isinstance(value, str) and 0 < len(value) <= REF_LIMIT for value in (target, item_id)) or not isinstance(scope, str) or scope not in SCOPES:
                raise ToolError(f"target and id must name a listed request and scope be one of {', '.join(SCOPES)}")
            item = listed.get(f"{target}:{item_id}")
            if item is None:
                raise Missing(shown(item_id)[:REF_LIMIT])
            if item["held"]:
                raise Conflict({"id": item_id, "status": "held"})
            if scope not in (ALL, item["request"]):
                raise Conflict({"id": item_id, "status": item["request"]})
            signed = signing.dismiss_item(target, item_id, item["request"], request_mark(item["command"], item["job"]))
            if any(other["signed"] == signed for other in chosen):
                raise ToolError("items must be distinct")
            chosen.append({"kind": target, "id": item_id, "verb": DISMISS_VERB, "label": "", "sha256": "", "title": shown(item["title"])[:TITLE_LIMIT], "gate": "", "request": item["request"], "signed": signed, "note": None})
        return chosen

    def dismiss_requests(self, body: bytes) -> dict:
        """Args:
            body: {"items", "proof"}: the page's entries (dismissable()) and
                the one passkey assertion over their dismiss items.

        Returns:
            The batch in its undo window, without proof and timer; the
            requests leave the snapshot at once, /api/inbox/undo brings them
            back until apply_dismissals() settles the batch.
        """
        payload = decode(body)
        expect(payload, ("items", "proof"))
        items = self.dismissable(payload["items"])
        self.proven(payload["proof"], [item["signed"] for item in items])
        return self.batches.add(items, "operator", None, self.apply_dismissals)

    def apply_dismissals(self, batch: dict) -> None:
        """Args:
            batch: dismissed requests past their undo window. Each stays out
                of the hub while its request_mark() holds; an open ask whose
                hook still waits is also denied without a reason, so its hook
                stops waiting for a card nobody sees, while one open in
                Claude stays pending for its dialog. No agent gets a radio
                message.
        """
        now = time.time()
        refs = {f"{item['kind']}:{item['id']}": item["signed"]["mark"] for item in batch["items"]}
        self.dismissals.add({"refs": refs, "ts": now})
        waiting = [item["id"] for item in batch["items"] if item["kind"] == "ask" and item["request"] == "open" and (self.asks.get(item["id"]) or {"expires": now})["expires"] > now]
        denied = [ask_id for ask_id in waiting if self.asks.decide(ask_id, {"status": "denied", "proof": None})[1]]
        titles = ", ".join(item["title"][:TITLE_SHOWN] for item in batch["items"])
        self.log.add({"kind": "approval", "title": f"Deleted {len(refs)} requests: {titles}"[:TITLE_LIMIT], "text": f"{len(denied)} open asks denied ({batch['source']})", "ref": {"verb": DISMISS_VERB, "items": sorted(refs), "denied": denied, "source": batch["source"]}})
