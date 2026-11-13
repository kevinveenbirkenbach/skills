from __future__ import annotations

from pathlib import Path

from .records import epoch, parse_line, read_json, read_regular

SCORES = "scores.jsonl"
LABELS = "kvb-check-score/labels.json"
FILE_LIMIT = 64 << 20


def checked(labels: object) -> dict | None:
    """Args:
        labels: the parsed label file, or None.

    Returns:
        labels when its "metrics" is a non-empty object of entries with a string
        emoji and label, else None.
    """
    metrics = labels.get("metrics") if isinstance(labels, dict) else None
    valid = isinstance(metrics, dict) and metrics and all(isinstance(metric, dict) and isinstance(metric.get("emoji"), str) and isinstance(metric.get("label"), str) for metric in metrics.values())
    return labels if valid else None


def scored(council: Path, skills: Path, span: tuple[float, float]) -> dict:
    """Args:
        council: the council directory holding scores.jsonl, which score.py
            and backfill.py of kvb-check-score append to.
        skills: the skills directory holding kvb-check-score/labels.json.
        span: (begin, end) of the burndown's time range in epoch seconds.

    Returns:
        {"since", "until", "labels", "rows"}: the label file, None when
        unreadable or not as checked() wants it, and the journal rows whose time lies within the span, in
        time order.
    """
    begin, end = span
    try:
        lines = read_regular(council / SCORES, FILE_LIMIT).splitlines()
    except (OSError, ValueError):
        lines = []
    rows = [row for row in map(parse_line, lines) if row is not None and isinstance(row.get("values"), dict)]
    inside = [row for row in rows if (moment := epoch(row.get("time"))) is not None and begin <= moment <= end]
    return {"since": begin, "until": end, "labels": checked(read_json(skills / LABELS)), "rows": sorted(inside, key=lambda row: row["time"])}
