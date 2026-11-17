from __future__ import annotations

import re
from pathlib import Path

from .records import epoch, parse_line, read_json, read_regular

SCORES = "scores.jsonl"
LABELS = "kvb-check-score/labels.json"
FILE_LIMIT = 64 << 20
VARIATION = "️"
VALUE = r"([0-9]+(?:\.[0-9]+)?(?:\s*%)?|–|-|new)(?![0-9.])"


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


def journal(council: Path) -> list[dict]:
    """Args:
        council: the council directory holding scores.jsonl.

    Returns:
        The journal rows with a values object, in file order; none when the
        journal is missing or unreadable.
    """
    try:
        lines = read_regular(council / SCORES, FILE_LIMIT).splitlines()
    except (OSError, ValueError):
        lines = []
    return [row for row in map(parse_line, lines) if row is not None and isinstance(row.get("values"), dict)]


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
    inside = [row for row in journal(council) if (moment := epoch(row.get("time"))) is not None and begin <= moment <= end]
    return {"since": begin, "until": end, "labels": score_labels(skills), "rows": sorted(inside, key=lambda row: row["time"])}


def score_labels(skills: Path) -> dict | None:
    return checked(read_json(skills / LABELS))


def metric_chips(score: str, labels: dict | None) -> list[dict]:
    """Args:
        score: an agent's free score line, such as line 1 or the message
            block of score.py.
        labels: the label file as checked() returns it, or None.

    Returns:
        In label order, per metric whose emoji (with or without its
        variation selector) or label or former label stands right before a
        value in score, the first such value: {"id", "emoji", "label",
        "value"}; none without labels.
    """
    found = []
    for key, metric in (labels or {}).get("metrics", {}).items():
        emoji = re.escape(metric["emoji"].removesuffix(VARIATION)) + f"{VARIATION}?"
        names = "|".join(re.escape(name) for name in (metric["label"], *metric.get("former", [])))
        match = re.search(rf"(?:{emoji}\s*(?:(?:{names})\s*:?\s*)?|\b(?:{names})\s*:?\s*){VALUE}", score, re.IGNORECASE)
        if match:
            found.append({"id": key, "emoji": metric["emoji"], "label": metric["label"], "value": " ".join(match.group(1).split())})
    return found
