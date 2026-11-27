from __future__ import annotations

from .errors import ToolError, Unsigned
from .fields import decode, expect
from .jobs import SCHEDULE_JOB, argv_items
from .schedules import valid_cron
from .signed import signing

SCHEDULE_TASK = "schedules"


def schedule_request(raw: object) -> bool:
    return isinstance(raw, list) and bool(raw) and all(isinstance(entry, dict) and entry.get("kind") == SCHEDULE_JOB for entry in raw)


def shown_command(argv: list[str]) -> str:
    return " ".join(["schedules.py", *argv])


def schedule_item(argv: object) -> dict:
    """Returns:
        The signed item of one foreign row change, its argv as
        signing.schedule_argv() accepts it; a cron out of range is refused
        first, naming its field (valid_cron()).
    """
    if isinstance(argv, list) and len(argv) == 5 and argv[0] == "cron" and argv[3] == "--cron":
        valid_cron(argv[4])
    return signing.schedule_item(signing.schedule_argv(argv))


class Scheduling:
    def schedule_changes(self, raw: object) -> list[dict]:
        """Args:
            raw: the page's items, each {"kind": "schedule", "argv"} with the
                schedules.py arguments of one System timer or Claude task
                change; a batch goes under one passkey assertion.

        Returns:
            The signed items (schedule_item()).
        """
        return argv_items(raw, schedule_item, "schedule change")

    def save_schedule(self, body: bytes) -> dict:
        """Args:
            body: {row, value} or {unit, value} for a Skills or Hub row,
                which schedules.json takes without a proof
                (Schedules.save()), or {items, proof} for System timers and
                Claude tasks, one runner job per item once a pinned key
                signed them all.

        Returns:
            The Schedules view, or {"jobs", "status"} for signed changes;
            Unsigned (403) for a foreign change without a valid proof,
            which stores nothing.
        """
        payload = decode(body)
        if not isinstance(payload, dict) or "items" not in payload:
            return self.schedule_settings.save(payload)
        expect(payload, ("items", "proof"))
        items = self.schedule_changes(payload["items"])
        try:
            proof = self.proven(payload["proof"], items)
        except ToolError as error:
            raise Unsigned(str(error)) from None
        return self.queued_changes(items, proof, SCHEDULE_JOB, SCHEDULE_TASK, shown_command)
