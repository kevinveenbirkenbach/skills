from __future__ import annotations

import re
from pathlib import Path

from .records import epoch, parse_line, read_json, read_regular

SCORES = "scores.jsonl"
LABELS = "kvb-check-score/labels.json"
FILE_LIMIT = 64 << 20
VARIATION = "️"
VALUE = r"([0-9]+(?:\.[0-9]+)?(?:\s*%|:[0-9]+(?:\.[0-9]+)?)?|–|-|new)(?![0-9.])"
CHIP_EXTRAS = ("legal", "architecture", "value")


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


def metric_chips(score: str, labels: dict | None, bare: bool) -> list[dict]:
    """Args:
        score: an agent's free score line, such as line 1 or the message
            block of score.py, or a free text that may carry one.
        labels: the label file as checked() returns it, or None.
        bare: whether a label without its emoji counts; False for a free
            text, where "fix 2 tests" is no score.

    Returns:
        In label order, each CHIP_EXTRAS entry right before the metric its
        "before" names, else after all, per metric whose emoji (with or
        without its variation selector) or label or former label stands
        right before a value in score (the label alone only when bare), the
        first such value: {"id", "emoji", "label", "value"}; none without
        labels.
    """
    found = []
    extras = (labels or {}).get("extras")
    ordered = list((labels or {}).get("metrics", {}).items())
    for key in CHIP_EXTRAS:
        if isinstance(extras, dict) and checked({"metrics": {key: extras.get(key)}}):
            keys = [name for name, _ in ordered]
            ordered.insert(keys.index(extras[key]["before"]) if extras[key].get("before") in keys else len(ordered), (key, extras[key]))
    for key, metric in ordered:
        emoji = re.escape(metric["emoji"].removesuffix(VARIATION)) + f"{VARIATION}?"
        names = "|".join(re.escape(name) for name in (metric["label"], *metric.get("former", [])))
        alone = rf"|\b(?:{names})\s*:?\s*" if bare else ""
        match = re.search(rf"(?:{emoji}\s*(?:(?:{names})\s*:?\s*)?{alone}){VALUE}", score, re.IGNORECASE)
        if match:
            found.append({"id": key, "emoji": metric["emoji"], "label": metric["label"], "value": " ".join(match.group(1).split())})
    return found
