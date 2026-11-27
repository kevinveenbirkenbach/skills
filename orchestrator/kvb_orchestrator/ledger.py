from __future__ import annotations

import json
import secrets
import threading
from collections.abc import Callable
from pathlib import Path

from .diffs import SEALED_SUFFIX
from .records import read_json, stamp, write_atomic


def unused(items: dict[str, dict]) -> str:
    item_id = secrets.token_hex(8)
    while item_id in items:
        item_id = secrets.token_hex(8)
    return item_id


class Ledger:
    def __init__(self, file: Path) -> None:
        self.file = file
        self.changed = threading.Condition()
        self.items: dict[str, dict] = {}
        if file.is_file():
            self.items = json.loads(file.read_text(encoding="utf-8"))

    def fresh(self) -> str:
        with self.changed:
            return unused(self.items)

    def batch(self, check: Callable[[list[dict]], None], changes: dict[str, dict], added: list[dict]) -> None:
        """Args:
            check: raises to refuse the whole batch; it sees every record
                under the lock the write holds.
            changes: fields merged into the record of each id, which keeps
                its id and created stamp.
            added: new records, each under a fresh id.
        """
        with self.changed:
            check(self.listed())
            items = {**self.items, **{item_id: {**self.items[item_id], **fields} for item_id, fields in changes.items()}}
            created = stamp()
            for fields in added:
                item_id = unused(items)
                items[item_id] = {**fields, "id": item_id, "created": created}
            self.write(items)

    def write(self, items: dict[str, dict]) -> None:
        write_atomic(self.file, json.dumps(items, indent=1, sort_keys=True).encode("utf-8"))
        self.items = items

    def insert(self, item_id: str, fields: dict) -> dict:
        with self.changed:
            record = {**fields, "id": item_id, "created": stamp()}
            self.write({**self.items, item_id: record})
            return dict(record)

    def add(self, fields: dict) -> dict:
        with self.changed:
            return self.insert(self.fresh(), fields)

    def add_checked(self, fields: dict, check: Callable[[list[dict]], None]) -> dict:
        """Args:
            fields: the record to add.
            check: raises to refuse the record; it sees every record under
                the lock the add holds, so parallel callers cannot pass a
                cap together.
        """
        with self.changed:
            check(self.listed())
            return self.add(fields)

    def get(self, item_id: str) -> dict | None:
        with self.changed:
            record = self.items.get(item_id)
            return None if record is None else dict(record)

    def listed(self) -> list[dict]:
        with self.changed:
            records = [dict(record) for record in self.items.values()]
        return sorted(records, key=lambda record: (record["created"], record["id"]))

    def pending(self) -> list[dict]:
        return [record for record in self.listed() if record.get("status") == "pending"]

    def transition(self, item_id: str, before: str, changes: dict) -> tuple[dict | None, bool]:
        with self.changed:
            record = self.items.get(item_id)
            if record is None:
                return None, False
            if record.get("status") != before:
                return dict(record), False
            updated = {**record, **changes}
            self.write({**self.items, item_id: updated})
            self.changed.notify_all()
            return dict(updated), True

    def decide(self, item_id: str, changes: dict) -> tuple[dict | None, bool]:
        return self.transition(item_id, "pending", {**changes, "decided": stamp()})

    def change(self, item_id: str, changes: dict) -> dict | None:
        with self.changed:
            record = self.items.get(item_id)
            if record is None:
                return None
            updated = {**record, **changes}
            self.write({**self.items, item_id: updated})
            return dict(updated)

    def note(self, item_id: str, changes: dict) -> dict | None:
        """Returns:
            The record with changes applied in memory only; the next write of
            any record stores them, a restart before it loses them.
        """
        with self.changed:
            record = self.items.get(item_id)
            if record is None:
                return None
            self.items = {**self.items, item_id: {**record, **changes}}
            return dict(self.items[item_id])

    def keep(self, wanted: Callable[[dict], bool]) -> None:
        with self.changed:
            kept = {key: record for key, record in self.items.items() if wanted(record)}
            if len(kept) != len(self.items):
                self.write(kept)

    def remove(self, item_id: str) -> bool:
        with self.changed:
            if item_id not in self.items:
                return False
            self.write({key: value for key, value in self.items.items() if key != item_id})
            return True

    def wait(self, item_id: str, timeout: float) -> dict | None:
        with self.changed:
            if item_id not in self.items:
                return None
            self.changed.wait_for(lambda: self.items[item_id].get("status") != "pending", timeout)
            return dict(self.items[item_id])


class Sealed(Ledger):
    def __init__(self, file: Path, pages: Path, suffix: str) -> None:
        """Args:
            pages: the folder holding each item's sealed clear patches.
            suffix: the name suffix of an item's sealed file there; it is
                deleted once the item leaves pending.
        """
        super().__init__(file)
        self.pages = pages
        self.sealed_suffix = suffix

    def transition(self, item_id: str, before: str, changes: dict) -> tuple[dict | None, bool]:
        record, changed = super().transition(item_id, before, changes)
        if changed and record is not None and record.get("status") != "pending":
            (self.pages / f"{item_id}{self.sealed_suffix}").unlink(missing_ok=True)
        return record, changed


class Reviews(Sealed):
    def __init__(self, state: Path) -> None:
        (state / "pages").mkdir(exist_ok=True)
        super().__init__(state / "reviews.json", state / "pages", SEALED_SUFFIX["review"])
        for newest in {(review["worktree"], review["branch"]): review for review in self.pending()}.values():
            self.supersede(newest)

    def stored(self, review_id: str, suffix: str) -> Path:
        return self.pages / f"{review_id}{suffix}"

    def supersede(self, newest: dict) -> None:
        """Args:
            newest: the review that replaces every other pending review of
                its worktree and branch; each is set superseded, with
                superseded_by naming it.
        """
        for review in self.pending():
            if review["id"] != newest["id"] and (review["worktree"], review["branch"]) == (newest["worktree"], newest["branch"]):
                self.decide(review["id"], {"status": "superseded", "superseded_by": newest["id"]})

    def submit(self, fields: dict[str, str], page: bytes, files: list[dict], attached: dict[str, bytes]) -> dict:
        """Args:
            attached: further files written before the review shows, by
                suffix.
        """
        with self.changed:
            review_id = self.fresh()
            write_atomic(self.stored(review_id, ".html"), page)
            write_atomic(self.stored(review_id, ".json"), json.dumps({"files": files}).encode("utf-8"))
            for suffix, data in attached.items():
                write_atomic(self.stored(review_id, suffix), data)
            review = self.insert(review_id, {**fields, "files": len(files), "status": "pending", "decided": None})
            self.supersede(review)
            return review


class Marks:
    def __init__(self, file: Path) -> None:
        self.file = file
        self.lock = threading.Lock()
        data = read_json(file)
        self.items: dict[str, dict] = data if isinstance(data, dict) else {}

    def put(self, key: str, mark: dict) -> None:
        with self.lock:
            self.items = {**self.items, key: mark}
            write_atomic(self.file, json.dumps(self.items, sort_keys=True).encode("utf-8"))

    def get(self, key: str) -> dict:
        with self.lock:
            return dict(self.items.get(key, {"until": 0.0, "pinned": False}))
