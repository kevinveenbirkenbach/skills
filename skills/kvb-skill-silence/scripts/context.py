#!/usr/bin/env python3
"""Report how much context agent sessions re-read per turn, from Claude Code's session transcripts.

Args:
    --root: transcripts root, e.g. ~/.claude/projects (every */*.jsonl below).
    --days: how many days back, one row per day, newest last.
    --threshold: a context size in tokens; per threshold the report adds the
        share of turns above it and the share of context tokens above it.
        Repeatable.
    --json: print the rows as JSON instead of tab-separated lines.

Output:
    per day: date, turns, context tokens, median and p90 context per turn,
    compactions, then per threshold `>N: turns% tokens%`. A turn is one model
    message, counted once although the transcript repeats its usage per
    content block.

Exit codes:
    0 done, 2 usage error.
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
import time
from pathlib import Path


def fail(message: str) -> None:
    print(f"context: {message}", file=sys.stderr)
    sys.exit(2)


def scan(root: Path, since: float) -> tuple[dict[str, tuple[str, int]], dict[str, int]]:
    turns: dict[str, tuple[str, int]] = {}
    compactions: dict[str, int] = {}
    for path in root.glob("*/*.jsonl"):
        if path.stat().st_mtime < since:
            continue
        with path.open(encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                if '"usage"' not in line and "compact_boundary" not in line:
                    continue
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                day = str(entry.get("timestamp", ""))[:10]
                if not day:
                    continue
                if entry.get("subtype") == "compact_boundary":
                    compactions[day] = compactions.get(day, 0) + 1
                message = entry.get("message")
                usage = message.get("usage") if isinstance(message, dict) else None
                if usage and message.get("id"):
                    size = sum(usage.get(k) or 0 for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
                    turns[message["id"]] = (day, size)
    return turns, compactions


def rows(root: Path, days: int, thresholds: list[int], now: float) -> list[dict]:
    first = datetime.datetime.fromtimestamp(now, datetime.UTC).date() - datetime.timedelta(days=days - 1)
    start = datetime.datetime.combine(first, datetime.time.min, tzinfo=datetime.UTC).timestamp()
    turns, compactions = scan(root, start)
    by_day: dict[str, list[int]] = {}
    for day, size in turns.values():
        if day >= first.isoformat():
            by_day.setdefault(day, []).append(size)
    out = []
    for offset in range(days):
        day = (first + datetime.timedelta(days=offset)).isoformat()
        sizes = sorted(by_day.get(day, []))
        total = sum(sizes)
        row = {
            "day": day,
            "turns": len(sizes),
            "tokens": total,
            "median": sizes[len(sizes) // 2] if sizes else 0,
            "p90": sizes[int(len(sizes) * 0.9)] if sizes else 0,
            "compactions": compactions.get(day, 0),
            "over": {},
        }
        for limit in thresholds:
            above = [s for s in sizes if s > limit]
            row["over"][str(limit)] = {
                "turns": round(100 * len(above) / len(sizes)) if sizes else 0,
                "tokens": round(100 * sum(s - limit for s in above) / total) if total else 0,
            }
        out.append(row)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", required=True)
    parser.add_argument("--days", type=int, required=True)
    parser.add_argument("--threshold", type=int, action="append", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    root = Path(args.root).expanduser()
    if not root.is_dir() or args.days < 1:
        fail("--root must be a directory and --days at least 1")
    report = rows(root, args.days, sorted(args.threshold), time.time())
    if args.json:
        print(json.dumps(report, indent=1))
        return 0
    for row in report:
        over = " ".join(f">{k}: {v['turns']}% {v['tokens']}%" for k, v in row["over"].items())
        print(f"{row['day']}\t{row['turns']}\t{row['tokens']}\t{row['median']}\t{row['p90']}\t{row['compactions']}\t{over}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
