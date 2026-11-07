from __future__ import annotations

import json
import secrets
import threading
from collections.abc import Callable
from pathlib import Path

from .records import read_json, stamp, write_atomic


class Ledger:
    def __init__(self, file: Path) -> None:
        self.file = file
        self.changed = threading.Condition()
        self.items: dict[str, dict] = {}
        if file.is_file():
            self.items = json.loads(file.read_text(encoding="utf-8"))

    def fresh(self) -> str:
        with self.changed:
            item_id = secrets.token_hex(8)
            while item_id in self.items:
                item_id = secrets.token_hex(8)
            return item_id

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


class Reviews(Ledger):
    def __init__(self, state: Path) -> None:
        super().__init__(state / "reviews.json")
        self.pages = state / "pages"
        self.pages.mkdir(exist_ok=True)

    def stored(self, review_id: str, suffix: str) -> Path:
        return self.pages / f"{review_id}{suffix}"

    def submit(self, fields: dict[str, str], page: bytes, files: list[dict]) -> dict:
        with self.changed:
            review_id = self.fresh()
            write_atomic(self.stored(review_id, ".html"), page)
            write_atomic(self.stored(review_id, ".json"), json.dumps({"files": files}).encode("utf-8"))
            return self.insert(review_id, {**fields, "files": len(files), "status": "pending", "decided": None})


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
