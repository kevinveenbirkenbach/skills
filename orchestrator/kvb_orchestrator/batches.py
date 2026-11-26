from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Callable

from .errors import Conflict, Missing

UNDO = 3


class Pending:
    def __init__(self, window: Callable[[], float]) -> None:
        """Args:
            window: returns the undo window in seconds the operator set, read
                anew for every batch; a running batch keeps its due time.
        """
        self.window = window
        self.lock = threading.Lock()
        self.batches: dict[str, dict] = {}
        self.applied: set[str] = set()

    def add(self, items: list[dict], source: str, proof: dict | None, apply: Callable[[dict], None]) -> dict:
        """Args:
            items: the checked inbox items.
            source: operator, or rule:<id> for an automatic approval.
            proof: the signature relayed to the executors once the undo
                window passed; None when no item needs one.
            apply: settles the batch after the undo window.

        Returns:
            The batch without its proof and timer.
        """
        batch_id = secrets.token_hex(8)
        window = self.window()
        timer = threading.Timer(window, self.fire, args=(batch_id, apply))
        timer.daemon = True
        batch = {"id": batch_id, "items": items, "source": source, "due": time.time() + window}
        with self.lock:
            self.batches[batch_id] = {**batch, "proof": proof, "timer": timer}
        timer.start()
        return dict(batch)

    def fire(self, batch_id: str, apply: Callable[[dict], None]) -> None:
        with self.lock:
            batch = self.batches.get(batch_id)
            if batch is None:
                return
            self.applied.add(batch_id)
        try:
            apply(batch)
        finally:
            with self.lock:
                self.batches.pop(batch_id, None)

    def undo(self, batch_id: str) -> dict:
        with self.lock:
            if batch_id in self.applied:
                raise Conflict({"id": batch_id, "status": "applied"})
            batch = self.batches.pop(batch_id, None)
        if batch is None:
            raise Missing(batch_id)
        batch["timer"].cancel()
        return batch

    def holds(self, kind_name: str, item_id: str) -> bool:
        with self.lock:
            return any(item["kind"] == kind_name and item["id"] == item_id for batch in self.batches.values() for item in batch["items"])

    def listed(self) -> list[dict]:
        """Returns:
            The batches still in their undo window, without proof and timer.
        """
        with self.lock:
            return [{key: batch[key] for key in ("id", "items", "source", "due")} for batch in self.batches.values() if batch["id"] not in self.applied]
