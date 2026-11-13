from __future__ import annotations

import os
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .errors import Held
from .phrasing import PROCEDURE_LINES
from .records import READ_FLAGS, epoch, parse_line

FRESH = 120
TAIL = 1 << 16


def tail_lines(path: Path, size: int) -> list[str]:
    """Args:
        path: a file the host sampler appends to; a link, FIFO or other
            non-regular file reads as empty without blocking.
        size: the most bytes to read from its end.

    Returns:
        The complete lines within the last size bytes, oldest first; [] when
        the file cannot be read.
    """
    try:
        with open(os.open(path, READ_FLAGS), "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode):
                return []
            start = max(info.st_size - size, 0)
            handle.seek(start)
            data = handle.read(size)
    except OSError:
        return []
    lines = data.decode("utf-8", errors="replace").splitlines()
    return lines[1:] if start else lines


def latest_cpu(path: Path, now: float) -> float | None:
    """Args:
        path: samples.jsonl of the W4 resource feed.
        now: the current time in epoch seconds.

    Returns:
        The cpu percent of the newest timed row, when that row lies at most
        FRESH seconds from now and carries a number from 0 to 100; else None.
    """
    for row in map(parse_line, reversed(tail_lines(path, TAIL))):
        t = None if row is None else epoch(row.get("t"))
        if t is None:
            continue
        cpu = row.get("cpu")
        fresh = abs(now - t) <= FRESH
        return float(cpu) if fresh and not isinstance(cpu, bool) and isinstance(cpu, int | float) and 0 <= cpu <= 100 else None
    return None


@dataclass(frozen=True)
class CpuGate:
    samples: Path
    threshold: Callable[[], int]
    clock: Callable[[], float]

    def state(self) -> dict:
        """Returns:
            {"threshold", "cpu", "open"}: open only while the latest fresh
            sample lies below the threshold; cpu None without one.
        """
        cpu = latest_cpu(self.samples, self.clock())
        limit = self.threshold()
        return {"threshold": limit, "cpu": cpu, "open": cpu is not None and cpu < limit}

    def admit(self, line: str) -> None:
        """Args:
            line: the uncached line about to be rendered in a voice the hub
                hands out; a procedure word line always renders, it is the
                same few lines per voice and outlives the cache trim.

        Returns:
            None when the line may render; otherwise it raises Held busy
            while the latest fresh sample is at or above the threshold and
            Held unknown without a fresh sample.
        """
        if line in PROCEDURE_LINES:
            return
        gate = self.state()
        if gate["cpu"] is None:
            raise Held("unknown")
        if not gate["open"]:
            raise Held("busy")
