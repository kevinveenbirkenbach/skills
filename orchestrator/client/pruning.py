from __future__ import annotations

import datetime
import re

import signing

ANNOUNCE = "announce"
APPLY = "prune"
TASKS_LIMIT = 50
WINDOW_MIN = 60
SKEW = 300
SENDER = "Operator"
RECORDS = ("operator/", "hotfix/")
DAYS = re.compile(r"[1-9][0-9]{0,2}")
EPOCH = re.compile(r"[1-9][0-9]{9}")


def whole(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def checked_tasks(tasks: list[str]) -> list[str]:
    """Returns:
        tasks: 1 to TASKS_LIMIT distinct register slugs signing.TASK matches,
        none an operator/ or hotfix/ record.

    Raises:
        signing.Refused for any other list.
    """
    if not 1 <= len(tasks) <= TASKS_LIMIT or len(set(tasks)) != len(tasks):
        raise signing.Refused(f"a prune names 1 to {TASKS_LIMIT} distinct tasks")
    if not all(signing.TASK.fullmatch(task) and not task.startswith(RECORDS) for task in tasks):
        raise signing.Refused("a pruned task is no register task slug outside operator/ and hotfix/")
    return tasks


def announced(argv: list[str]) -> bool:
    return len(argv) >= 6 and argv[0] == ANNOUNCE and argv[1] == "--days" and argv[3] == "--deadline" and bool(DAYS.fullmatch(argv[2]) and EPOCH.fullmatch(argv[4]))


def applied(argv: list[str], not_before: object) -> bool:
    if len(argv) < 4 or argv[:2] != [APPLY, "--since"] or not EPOCH.fullmatch(argv[2]) or not whole(not_before):
        return False
    return WINDOW_MIN <= not_before - int(argv[2]) <= signing.PRUNE_WINDOW


def prune_argv(argv: object, not_before: object) -> list[str]:
    """Args:
        argv: the announce job's `announce --days <N> --deadline <epoch>
            <task>...` (N 1 to 999 DAYS, an EPOCH) with not_before None, or
            the apply job's rasci.py arguments `prune --since <epoch>
            <task>...` with not_before the deadline, WINDOW_MIN to
            signing.PRUNE_WINDOW seconds after since; the tasks as
            checked_tasks() takes them.
        not_before: the epoch the runner holds the job back until, signed
            with it.

    Returns:
        argv, the hub and the runner check it the same way.

    Raises:
        signing.Refused for every other argv or not_before.
    """
    if not isinstance(argv, list) or not all(isinstance(part, str) for part in argv):
        raise signing.Refused("the argv is no list of texts")
    if not_before is None and announced(argv):
        checked_tasks(argv[5:])
        return argv
    if applied(argv, not_before):
        checked_tasks(argv[3:])
        return argv
    raise signing.Refused(f"the argv is no prune announce with --days and --deadline, nor rasci.py prune --since with a deadline {WINDOW_MIN} to {signing.PRUNE_WINDOW} s later")


def prune_item(argv: list[str], not_before: int | None) -> dict:
    item = {"kind": signing.PRUNE_KIND, "argv": argv}
    return item if not_before is None else {**item, "not_before": not_before}


def tasks_of(argv: list[str]) -> list[str]:
    return argv[5:] if argv[0] == ANNOUNCE else argv[3:]


def deadline_of(argv: list[str]) -> int:
    return int(argv[4])


def timely(argv: list[str], not_before: int | None, now: float) -> None:
    """Raises:
        signing.Refused for an announce whose deadline passed or lies over
        signing.PRUNE_WINDOW + SKEW seconds ahead, and for an apply job
        before its not_before.
    """
    if not_before is not None and not_before > now:
        raise signing.Refused(f"the prune is not due before {stamp(not_before)}")
    if not_before is None and not now < deadline_of(argv) <= now + signing.PRUNE_WINDOW + SKEW:
        raise signing.Refused(f"the prune deadline {stamp(deadline_of(argv))} passed or lies over {signing.PRUNE_WINDOW} s ahead")


def stamp(epoch: int) -> str:
    return datetime.datetime.fromtimestamp(epoch).astimezone().isoformat(timespec="seconds")


def announcement(argv: list[str]) -> str:
    """Returns:
        The Securite text of an announce argv: every task, the deadline in
        local HH:MM and ISO 8601, and how an agent keeps a task.
    """
    deadline = datetime.datetime.fromtimestamp(deadline_of(argv)).astimezone()
    names = ", ".join(tasks_of(argv))
    return (
        f"Stale task prune at {deadline:%H:%M} ({deadline.isoformat(timespec='seconds')}): {names}. "
        f"Each had no register change for {argv[2]} days; at the deadline the hub runner sets every one still unchanged to stopped. "
        "Keep a task with rasci.py keep <task>; any register change of it keeps it too."
    )


def radio_argv(argv: list[str]) -> list[str]:
    return ["send", "security", announcement(argv), "--session", SENDER]
