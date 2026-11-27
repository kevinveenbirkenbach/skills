from __future__ import annotations

from .jobs import QUEUE_JOB, argv_items
from .signed import signing

QUEUE_TASK = "queue"


def queue_request(raw: object) -> bool:
    return isinstance(raw, list) and bool(raw) and all(isinstance(entry, dict) and entry.get("kind") == QUEUE_JOB for entry in raw)


def shown_command(argv: list[str]) -> str:
    return " ".join(["queue.py", *argv])


class Queueing:
    def queue_view(self) -> dict:
        return self.queue_order.learned()

    def queue_changes(self, raw: object) -> list[dict]:
        """Args:
            raw: the page's items, each {"kind": "queue", "argv"} with the
                queue.py arguments of one Start now (`override <id>`) or one
                staged setting (`config set <key> <value>`); a batch goes
                under one passkey assertion.

        Returns:
            The signed items, each with an argv signing.queue_argv() accepts.
        """
        return argv_items(raw, lambda argv: signing.queue_item(signing.queue_argv(argv)), "queue change")

    def change_queue(self, body: bytes) -> dict:
        return self.signed_jobs(body, self.queue_changes, QUEUE_JOB, QUEUE_TASK, shown_command)
