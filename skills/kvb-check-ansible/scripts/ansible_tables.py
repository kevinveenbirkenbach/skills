"""Rank timed task occurrences into the reports of durations, gaps, kinds, kind and task.

Args:
    source: the source the occurrences came from, echoed in the JSON report.
    found: the task occurrences of ansible_log.
    top: rows per table; every row when None.
    kind: ran, skipped, included or other.
    needle: substring of the task name.

Output:
    A (report, lines) pair: the JSON-ready report and its tab-separated text, biggest
    first. Name tables end in a TOTAL row over all their tasks; kind tables bucket each
    occurrence into <0.25, <0.5, <1, <2 or >=2 s.
"""

from __future__ import annotations

from collections.abc import Iterable

import ansible_log

BUCKETS = ((0.25, "<0.25"), (0.5, "<0.5"), (1.0, "<1"), (2.0, "<2"))
LAST_BUCKET = ">=2"
LABELS = (*(label for _, label in BUCKETS), LAST_BUCKET)

Found = list[ansible_log.Task]


def bucket(seconds: float) -> str:
    return next((label for limit, label in BUCKETS if seconds < limit), LAST_BUCKET)


def ranked(rows: Iterable[dict]) -> list[dict]:
    return sorted(rows, key=lambda row: -row["sum"])


def of_kind(found: Found, kind: str) -> Found:
    return [item for item in found if item.kind == kind]


def names(source: str, found: Found, top: int | None) -> tuple[dict, list[str]]:
    table: dict[str, dict] = {}
    for item in found:
        row = table.setdefault(item.name, {"name": item.name, "sum": 0.0, "count": 0})
        row["sum"] += item.seconds
        row["count"] += 1
    rows = ranked(table.values())[:top]
    total = sum(item.seconds for item in found)
    report = {
        "source": source,
        "rows": [{**row, "sum": round(row["sum"], 3)} for row in rows],
        "total": {"sum": round(total, 3), "count": len(found)},
    }
    lines = [f"{row['sum']:.1f}\t{row['count']}\t{row['name']}" for row in rows]
    return report, [*lines, f"{total:.1f}\t{len(found)}\tTOTAL"]


def kind_table(source: str, found: Found, top: int | None) -> tuple[dict, list[str]]:
    table: dict[str, dict] = {}
    for item in found:
        row = table.setdefault(
            item.kind, {"kind": item.kind, "count": 0, "sum": 0.0, "buckets": dict.fromkeys(LABELS, 0)}
        )
        row["count"] += 1
        row["sum"] += item.seconds
        row["buckets"][bucket(item.seconds)] += 1
    rows = ranked(table.values())[:top]
    report = {
        "source": source,
        "kinds": [
            {**row, "sum": round(row["sum"], 3), "mean": round(row["sum"] / row["count"], 4)} for row in rows
        ],
    }
    lines = ["\t".join(("kind", "count", "sum", "mean", *LABELS))]
    lines += [
        "\t".join(
            (
                row["kind"],
                str(row["count"]),
                f"{row['sum']:.1f}",
                f"{row['sum'] / row['count']:.4f}",
                *(str(row["buckets"][label]) for label in LABELS),
            )
        )
        for row in rows
    ]
    return report, lines


def occurrences(source: str, found: Found, needle: str, top: int | None) -> tuple[dict, list[str]]:
    hits = sorted((item for item in found if needle in item.name), key=lambda item: -item.seconds)
    shown = hits[:top]
    report = {
        "source": source,
        "needle": needle,
        "count": len(hits),
        "sum": round(sum(item.seconds for item in hits), 3),
        "occurrences": [
            {"line": item.line, "seconds": round(item.seconds, 3), "kind": item.kind, "name": item.name}
            for item in shown
        ],
    }
    return report, [f"{item.line}\t{item.seconds:.3f}\t{item.kind}\t{item.name}" for item in shown]
