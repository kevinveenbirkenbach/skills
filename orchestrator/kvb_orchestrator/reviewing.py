from __future__ import annotations

import datetime
import os
import stat
import time
from pathlib import Path

from .diffs import (
    DIFF_SUFFIX,
    SEALED_SUFFIX,
    diff_bytes,
    sealed_bytes,
    stored_diff,
    valid_diff,
    valid_sealed,
)
from .errors import Conflict, Missing, ToolError
from .fields import WAIT_CAP, bounded, decode, expect, field, seconds
from .review_page import review_files
from .signed import limits, review_signed

PAGE_LIMIT = 32 << 20
NOTES_LIMIT = limits.NOTES_LIMIT
SCORE_LIMIT = 500
GATES = ("pass", "fail")
REQUEST = ("repo", "worktree", "branch", "tree", "title", "page", "notes", "gate", "score")
OPTIONAL = ("agent", "diff", "sealed")
LISTED = ("id", "created", "worktree", "branch", "tree", "title")
STATE = ("id", "status", "tree", "decided")
DENIAL = ("channel", "reason", "to")


def found(review: dict | None, review_id: str) -> dict:
    if review is None:
        raise ToolError(f"no review {review_id}")
    return review


def state_of(review: dict) -> dict:
    """Returns:
        The review's id, status, tree and decision time, superseded_by
        once a newer review of its worktree and branch replaced it, and
        channel, reason and to of a denial with a note.
    """
    replaced = {"superseded_by": review["superseded_by"]} if "superseded_by" in review else {}
    return {**{key: review[key] for key in STATE}, **replaced, **{key: review[key] for key in DENIAL if key in review}}


def proven(review: dict) -> dict:
    return {**state_of(review), "proof": review.get("proof")}


def review_row(review: dict) -> dict:
    created = datetime.datetime.fromisoformat(review["created"]).timestamp()
    return {**{key: review[key] for key in LISTED}, "notes": review["notes"], "created_ts": created, "files": review.get("files")}


class Reviewing:
    def read_page(self, page: str) -> bytes:
        path = Path(page)
        resolved = path.resolve()
        inside = ".." not in path.parts and path.is_relative_to(self.pages) and resolved.is_relative_to(self.pages.resolve())
        if not inside or path.suffix != ".html" or resolved.suffix != ".html":
            raise ToolError(f"page must be an .html file under {self.pages}")
        try:
            descriptor = os.open(resolved, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except OSError as error:
            raise ToolError(f"page {page}: {error.strerror}") from error
        with os.fdopen(descriptor, "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise ToolError(f"page {page} is not a regular file")
            data = handle.read(PAGE_LIMIT + 1)
        if len(data) > PAGE_LIMIT:
            raise ToolError(f"page {page} exceeds {PAGE_LIMIT} bytes")
        return data

    def request(self, arguments: dict) -> dict:
        expect(arguments, (*REQUEST, *(name for name in OPTIONAL if name in arguments)))
        fields = {name: field(arguments, name) for name in ("repo", "worktree", "branch", "tree", "title")}
        notes = arguments["notes"]
        if not isinstance(notes, str) or len(notes) > NOTES_LIMIT:
            raise ToolError(f"notes must be text of at most {NOTES_LIMIT} characters")
        if arguments["gate"] not in GATES:
            raise ToolError("gate must be pass or fail")
        score = " ".join(bounded(arguments, "score", SCORE_LIMIT).split())
        agent = field(arguments, "agent").strip() if "agent" in arguments else ""
        diff = valid_diff(arguments["diff"]) if "diff" in arguments else None
        sealed = valid_sealed(arguments["sealed"], diff) if "sealed" in arguments else {}
        page = self.read_page(field(arguments, "page"))
        extra = {"notes": notes, "gate": arguments["gate"], "score": score, "agent": agent, "diff_files": None if diff is None else len(diff)}
        attached = {} if diff is None else {DIFF_SUFFIX["review"]: diff_bytes(diff)}
        if sealed:
            attached[SEALED_SUFFIX["review"]] = sealed_bytes(sealed)
        review = self.reviews.submit({**fields, "title": fields["title"].strip(), **extra}, page, review_files(page), attached)
        self.automate("review", review)
        return {"id": review["id"], "status": review["status"], "url": self.url()}

    def diff_of(self, kind_name: str, item_id: str) -> dict:
        return stored_diff(self.reviews.pages, kind_name, item_id)

    def review_proof(self, review_id: str) -> dict:
        review = self.reviews.get(review_id)
        if review is None:
            raise Missing(review_id)
        return proven(review)

    def verdict(self, review_id: str, status: str, body: bytes) -> dict:
        review = self.reviews.get(review_id)
        if review is None:
            raise Missing(review_id)
        proof = None
        if status == "approved":
            payload = decode(body)
            expect(payload, ("proof",))
            proof = self.covered(payload["proof"], [review_signed(review)], time.time())
        decided, changed = self.reviews.decide(review_id, {"status": status, "proof": proof})
        if not changed:
            raise Conflict(state_of(decided))
        return state_of(decided)

    def status(self, arguments: dict) -> dict:
        expect(arguments, ("id",))
        review_id = field(arguments, "id")
        return proven(found(self.reviews.get(review_id), review_id))

    def wait(self, arguments: dict) -> dict:
        expect(arguments, ("id", "timeout_seconds"))
        review_id = field(arguments, "id")
        timeout = seconds(arguments, "timeout_seconds", WAIT_CAP)
        return proven(found(self.reviews.wait(review_id, timeout), review_id))

    def pending(self, arguments: dict) -> dict:
        expect(arguments, ())
        return {"reviews": [{key: review[key] for key in LISTED} for review in self.reviews.pending()]}
