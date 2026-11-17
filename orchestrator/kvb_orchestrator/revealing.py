from __future__ import annotations

import time

from .asking import ask_state
from .diffs import SEALED_SUFFIX, sealed_file, stored_sealed
from .errors import Conflict, Missing, ToolError
from .fields import decode, expect
from .records import shown

TITLE_LIMIT = 200
PATHS_SHOWN = 2000


def reveal_item(kind_name: str, item_id: str, paths: list[str]) -> dict:
    """Returns:
        The item a reveal signs: the sorted paths of one review or ask; its
        hash equals no item an executor approves.
    """
    return {"kind": "reveal", "target": kind_name, "id": item_id, "paths": paths}


class Revealing:
    def sealed_status(self, kind_name: str, item_id: str, now: float) -> tuple[dict | None, str | None]:
        record = self.reviews.get(item_id) if kind_name == "review" else self.asks.get(item_id)
        if record is None:
            return None, None
        return record, record["status"] if kind_name == "review" else ask_state(record, now)["status"]

    def open_record(self, kind_name: str, item_id: str) -> dict:
        """Returns:
            The pending review or ask whose sealed patches a reveal reads.

        Raises:
            Missing for an unknown item; Conflict once it is decided or
            expired, after its sealed file is deleted.
        """
        record, status = self.sealed_status(kind_name, item_id, time.time())
        if record is None:
            raise Missing(item_id)
        if status != "pending":
            sealed_file(self.reviews.pages, kind_name, item_id).unlink(missing_ok=True)
            raise Conflict({"kind": kind_name, "id": item_id, "status": status})
        return record

    def requested(self, kind_name: str, item_id: str, paths: object) -> tuple[dict, list[str], dict[str, str]]:
        record = self.open_record(kind_name, item_id)
        if not isinstance(paths, list) or not paths or not all(isinstance(path, str) for path in paths) or len(set(paths)) != len(paths):
            raise ToolError("paths must name one or more distinct files")
        sealed = stored_sealed(self.reviews.pages, kind_name, item_id)
        unsealed = [path for path in paths if path not in sealed]
        if unsealed:
            raise ToolError(f"nothing sealed to reveal for {shown(unsealed[0])[:TITLE_LIMIT]}")
        return record, sorted(paths), sealed

    def sign_reveal(self, kind_name: str, item_id: str, body: bytes) -> dict:
        payload = decode(body)
        expect(payload, ("paths",))
        _, paths, _ = self.requested(kind_name, item_id, payload["paths"])
        return self.challenge_for([reveal_item(kind_name, item_id, paths)])

    def reveal(self, kind_name: str, item_id: str, body: bytes) -> dict:
        """Returns:
            The clear patches of exactly the requested paths, once a pinned
            passkey signed their reveal_item unexpired and for the first
            time; the approval stream records kind, id and paths, never a
            patch.
        """
        payload = decode(body)
        expect(payload, ("paths", "proof"))
        record, paths, sealed = self.requested(kind_name, item_id, payload["paths"])
        self.operator_proven(payload["proof"], reveal_item(kind_name, item_id, paths))
        title = record["title"] if kind_name == "review" else f"{record['tool']}: {record['command']}"
        self.log.add({"kind": "approval", "title": f"Reveal {kind_name}: {shown(title)[:TITLE_LIMIT]}", "text": shown(", ".join(paths))[:PATHS_SHOWN], "ref": {"kind": kind_name, "id": item_id, "verb": "reveal", "paths": paths}})
        return {"kind": kind_name, "id": item_id, "patches": {path: sealed[path] for path in paths}}

    def sweep_sealed(self) -> None:
        now = time.time()
        for kind_name, suffix in SEALED_SUFFIX.items():
            for file in self.reviews.pages.glob(f"*{suffix}"):
                if self.sealed_status(kind_name, file.name.removesuffix(suffix), now)[1] != "pending":
                    file.unlink(missing_ok=True)
