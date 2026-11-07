from __future__ import annotations

import datetime
import os
import stat
import time
from pathlib import Path

from .errors import Conflict, Missing, ToolError
from .fields import WAIT_CAP, bounded, decode, expect, field, seconds
from .review_page import review_files
from .signed import review_signed

PAGE_LIMIT = 32 << 20
NOTES_LIMIT = 100_000
SCORE_LIMIT = 500
GATES = ("pass", "fail")
REQUEST = ("repo", "worktree", "branch", "tree", "title", "page", "notes", "gate", "score")
LISTED = ("id", "created", "worktree", "branch", "tree", "title")
STATE = ("id", "status", "tree", "decided")


def found(review: dict | None, review_id: str) -> dict:
    if review is None:
        raise ToolError(f"no review {review_id}")
    return review


def state_of(review: dict) -> dict:
    return {key: review[key] for key in STATE}


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
        expect(arguments, REQUEST)
        fields = {name: field(arguments, name) for name in ("repo", "worktree", "branch", "tree", "title")}
        notes = arguments["notes"]
        if not isinstance(notes, str) or len(notes) > NOTES_LIMIT:
            raise ToolError(f"notes must be text of at most {NOTES_LIMIT} characters")
        if arguments["gate"] not in GATES:
            raise ToolError("gate must be pass or fail")
        score = " ".join(bounded(arguments, "score", SCORE_LIMIT).split())
        page = self.read_page(field(arguments, "page"))
        extra = {"notes": notes, "gate": arguments["gate"], "score": score}
        review = self.reviews.submit({**fields, "title": fields["title"].strip(), **extra}, page, review_files(page))
        self.automate("review", review)
        return {"id": review["id"], "status": review["status"], "url": self.url()}

    def review_proof(self, review_id: str) -> dict:
        review = self.reviews.get(review_id)
        if review is None:
            raise Missing(review_id)
        return {**state_of(review), "proof": review.get("proof")}

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
        return state_of(found(self.reviews.get(review_id), review_id))

    def wait(self, arguments: dict) -> dict:
        expect(arguments, ("id", "timeout_seconds"))
        review_id = field(arguments, "id")
        timeout = seconds(arguments, "timeout_seconds", WAIT_CAP)
        return state_of(found(self.reviews.wait(review_id, timeout), review_id))

    def pending(self, arguments: dict) -> dict:
        expect(arguments, ())
        return {"reviews": [{key: review[key] for key in LISTED} for review in self.reviews.pending()]}
