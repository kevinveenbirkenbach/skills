"""Parse Ansible output into timed task occurrences.

Args:
    path: the Ansible output to read.
    first, last: first and last line to read, 1-based and inclusive; None reads to that end.
    source: wall (ISO timestamps) or profile (profile_tasks); None picks wall when a header
        in range carries a timestamp, else profile.

Output:
    A task lasts from its TASK or RUNNING HANDLER header to the next header or PLAY RECAP;
    profile_tasks prints that duration under the next header. Its kind is ran on an ok,
    changed, failed or fatal result line, else skipped on a skipping line, else included
    on an included line, else other. A stamp without zone counts as UTC. Unmeasurable
    names what the range lacks.
"""

from __future__ import annotations

import calendar
import re
from collections.abc import Iterator
from pathlib import Path

HEADER = re.compile(r"(?:TASK|RUNNING HANDLER) \[(?P<name>.*)\][\s*]*$")
RECAP = re.compile(r"PLAY RECAP \*")
STAMP = re.compile(
    r"^(?P<day>\d{4}-\d{2}-\d{2})[T ](?P<hour>\d{2}):(?P<minute>\d{2}):(?P<second>\d{2})"
    r"(?:[.,](?P<fraction>\d+))?(?P<zone>Z|[+-]\d{2}:?\d{2})? ?"
)
ELAPSED = re.compile(r"\((?P<hours>\d+):(?P<minutes>\d+):(?P<seconds>\d+(?:\.\d+)?)\)")
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
RESULTS = (
    ("ran", re.compile(r"^\s*(?:ok|changed|failed|fatal): \[")),
    ("skipped", re.compile(r"^\s*skipping: \[")),
    ("included", re.compile(r"^\s*included: ")),
)
OTHER = "other"
KINDS = (*(kind for kind, _ in RESULTS), OTHER)
SOURCES = ("wall", "profile")

Rows = Iterator[tuple[int, float | None, str]]


class Unmeasurable(Exception):
    pass


class NoStamps(Unmeasurable):
    pass


class Task:
    def __init__(self, name: str, line: int, start: float | None) -> None:
        self.name = name
        self.line = line
        self.start = start
        self.seconds = 0.0
        self.seen: set[str] = set()

    def note(self, content: str) -> None:
        self.seen.update(kind for kind, pattern in RESULTS if pattern.search(content))

    @property
    def kind(self) -> str:
        return next((kind for kind, _ in RESULTS if kind in self.seen), OTHER)


def offset(zone: str | None) -> int:
    if zone is None or zone == "Z":
        return 0
    digits = zone[1:].replace(":", "")
    seconds = int(digits[:2]) * 3600 + int(digits[2:]) * 60
    return -seconds if zone.startswith("-") else seconds


def epoch(match: re.Match[str]) -> float:
    year, month, day = (int(part) for part in match["day"].split("-"))
    whole = calendar.timegm((year, month, day, int(match["hour"]), int(match["minute"]), int(match["second"])))
    fraction = float(f"0.{match['fraction']}") if match["fraction"] else 0.0
    return whole + fraction - offset(match["zone"])


def split_stamp(text: str) -> tuple[float | None, str]:
    match = STAMP.match(text)
    if match is None:
        return None, text
    return epoch(match), text[match.end():]


def read(path: Path, first: int | None, last: int | None) -> Rows:
    with path.open(encoding="utf-8-sig", errors="replace") as handle:
        for number, raw in enumerate(handle, 1):
            if first is not None and number < first:
                continue
            if last is not None and number > last:
                return
            stamp, content = split_stamp(ANSI.sub("", raw.rstrip("\r\n")))
            yield number, stamp, content


def boundary(content: str) -> tuple[bool, str | None]:
    header = HEADER.search(content)
    if header is not None:
        return True, header["name"]
    return RECAP.search(content) is not None, None


def wall(rows: Rows) -> list[Task]:
    done: list[Task] = []
    current: Task | None = None
    stamped = False
    for number, stamp, content in rows:
        found, name = boundary(content)
        if not found:
            if current is not None:
                current.note(content)
            continue
        if stamp is None:
            continue
        stamped = True
        if current is not None:
            current.seconds = stamp - current.start
            done.append(current)
        current = None if name is None else Task(name, number, stamp)
    if not stamped:
        raise NoStamps("no TASK, RUNNING HANDLER or PLAY RECAP header with an ISO timestamp in range")
    if not done:
        raise Unmeasurable("no task closed by a later timestamped header in range")
    return done


def elapsed(match: re.Match[str]) -> float:
    return int(match["hours"]) * 3600 + int(match["minutes"]) * 60 + float(match["seconds"])


def profile(rows: Rows) -> list[Task]:
    done: list[Task] = []
    current: Task | None = None
    waiting: Task | None = None
    for number, _, content in rows:
        found, name = boundary(content)
        if found:
            if current is not None:
                waiting = current
            current = None if name is None else Task(name, number, None)
            continue
        duration = ELAPSED.search(content)
        if duration is not None and waiting is not None:
            waiting.seconds = elapsed(duration)
            done.append(waiting)
            waiting = None
        elif current is not None:
            current.note(content)
    if not done:
        raise Unmeasurable(
            "no profile_tasks (h:mm:ss.sss) duration under a header in range; "
            "enable the ansible.posix.profile_tasks callback, or use gaps on a timestamped log"
        )
    return done


def tasks(path: Path, first: int | None, last: int | None, source: str | None) -> tuple[str, list[Task]]:
    if source == "profile":
        return source, profile(read(path, first, last))
    if source == "wall":
        return source, wall(read(path, first, last))
    try:
        return "wall", wall(read(path, first, last))
    except NoStamps:
        return "profile", profile(read(path, first, last))
