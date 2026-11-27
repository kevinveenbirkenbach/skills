from __future__ import annotations

import time

from .errors import ToolError
from .fields import expect
from .jobs import PRUNE_JOB
from .register import ENDED, REGISTER, read_register, status_of
from .signed import pruning, signing

PRUNE_TASK = "prune"
ANNOUNCE_KEYS = ("kind", "argv")
APPLY_KEYS = ("kind", "argv", "not_before")


def prune_request(raw: object) -> bool:
    return isinstance(raw, list) and bool(raw) and all(isinstance(entry, dict) and entry.get("kind") == PRUNE_JOB for entry in raw)


def shown_command(argv: list[str]) -> str:
    if argv[0] == pruning.ANNOUNCE:
        return f"radio.py send security {pruning.announcement(argv)}"
    return " ".join(["rasci.py", *argv])


def prune_items(raw: object, now: float, open_tasks: set[str]) -> list[dict]:
    """Args:
        raw: the page's two items under one passkey assertion: first
            {"kind": "prune", "argv"} with the announce argv, then
            {"kind": "prune", "argv", "not_before"} with the rasci.py prune
            argv and the deadline (pruning.prune_argv()).
        now: the current time in epoch seconds.
        open_tasks: the register tasks neither done nor stopped.

    Returns:
        The two signed items, once both name the same tasks, all open in
        the register, the apply job's not_before is the announced deadline,
        that deadline lies ahead (pruning.timely()) and --since is no older
        than one signature lifetime and at most pruning.SKEW ahead.
    """
    if not isinstance(raw, list) or len(raw) != 2 or not all(isinstance(entry, dict) for entry in raw):
        raise ToolError("a prune is two items: the announce, then the apply job")
    announce, apply = raw
    expect(announce, ANNOUNCE_KEYS)
    expect(apply, APPLY_KEYS)
    try:
        first = pruning.prune_argv(announce["argv"], None)
        second = pruning.prune_argv(apply["argv"], apply["not_before"])
        pruning.timely(first, None, now)
    except signing.Refused as error:
        raise ToolError(f"prune: {error}") from None
    if pruning.tasks_of(first) != pruning.tasks_of(second) or pruning.deadline_of(first) != apply["not_before"]:
        raise ToolError("the announce and the apply job must name the same tasks and the same deadline")
    if not now - signing.LIFETIME <= int(second[2]) <= now + pruning.SKEW:
        raise ToolError("--since must be the epoch the page listed the stale tasks at")
    closed = [task for task in pruning.tasks_of(first) if task not in open_tasks]
    if closed:
        raise ToolError(f"not open in the register: {', '.join(closed)[:300]}")
    return [pruning.prune_item(first, None), pruning.prune_item(second, apply["not_before"])]


class Prunes:
    def prune_changes(self, raw: object) -> list[dict]:
        tasks = read_register(self.council / REGISTER)
        return prune_items(raw, time.time(), {task for task, row in tasks.items() if status_of(row) not in ENDED})

    def prune(self, body: bytes) -> dict:
        """Args:
            body: {"items", "proof"}: the two prune items (prune_items())
                and the one passkey assertion over both.

        Returns:
            {"jobs": ids, "status": "queued"}: the announce job, which the
            runner runs at once, and the apply job it holds until the
            deadline.
        """
        return self.signed_jobs(body, self.prune_changes, PRUNE_JOB, PRUNE_TASK, shown_command)
