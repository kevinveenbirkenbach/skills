from __future__ import annotations

from pathlib import Path

from .records import epoch, parse_line, read_regular

RESOURCES = "resources"
SAMPLES = "samples.jsonl"
TOKENS = "tokens.jsonl"
HOUR = 3600
FILE_LIMIT = 64 << 20


def rows_between(path: Path, begin: float, end: float, width: float) -> list[dict]:
    try:
        lines = read_regular(path, FILE_LIMIT).splitlines()
    except (OSError, ValueError):
        return []
    found = []
    for row in map(parse_line, lines):
        t = None if row is None else epoch(row.get("t"))
        if t is not None and begin <= t + width and t <= end:
            found.append(row)
    return found


def sampled(folder: Path, span: tuple[float, float]) -> dict:
    """Args:
        folder: the host sampler's directory, mounted read-only.
        span: (begin, end) of the page's time window in epoch seconds.

    Returns:
        {"since", "until", "samples", "tokens"}: the rows of samples.jsonl
        within the span and those of tokens.jsonl whose hour overlaps it, as
        the host unit wrote them; the hub reads nothing of the host itself.
    """
    begin, end = span
    return {"since": begin, "until": end, "samples": rows_between(folder / SAMPLES, begin, end, 0), "tokens": rows_between(folder / TOKENS, begin, end, HOUR)}
