from __future__ import annotations

import functools
import json
import os
import stat
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO

from .errors import ToolError
from .fields import instant, single
from .records import epoch, parse_line
from .resources import HOUR, rows_between

CONTEXT = "context.jsonl"
USAGE = "usage.jsonl"
LINE_LIMIT = 1 << 16
DAY = 86400
COUNTS = ("input", "output", "cache_read", "cache_write")
FILTERS = ("skill", "tool", "subagent", "repo", "model", "agent", "account")
GROUPS = (*FILTERS, "hour", "day")
PARAMS = ("group", "since", "until", *FILTERS)
BUCKETS = {"hour": HOUR, "day": DAY}
PRICES = Path(__file__).with_name("prices.json")
MILLION = 1_000_000
KILO = 1000
VALUE_TEXT = 254
QUANTILES = (("median", 1, 2), ("p90", 9, 10))


@functools.cache
def prices() -> dict:
    """Returns:
        prices.json: {date, source, unit, families: {family: {model, input,
        output, cache_read, cache_write}}}, USD per million tokens.
    """
    return json.loads(PRICES.read_text(encoding="utf-8"))


def family(model: str, families: dict) -> dict | None:
    """Returns:
        The prices of the first family whose name the model id holds, None
        for an unknown model.
    """
    lowered = model.lower()
    return next((found for name, found in families.items() if name in lowered), None)


def cost(row: dict, families: dict) -> float | None:
    found = family(row["model"], families)
    return None if found is None else sum(row[name] * found[name] for name in COUNTS) / MILLION


def whole(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def entry(row: dict) -> dict | None:
    """Returns:
        A token row with every dimension of FILTERS, "" where an older row
        lacks it, and its counts as whole tokens; None without a number t.
    """
    t = row.get("t")
    if not isinstance(t, int | float) or isinstance(t, bool):
        return None
    return {"t": t, **{name: row[name] if isinstance(row.get(name), str) else "" for name in FILTERS}, **{name: whole(row.get(name)) for name in COUNTS}}


def parsed(query: dict[str, list[str]], now: float) -> tuple[str, float, float, dict[str, str]]:
    """Args:
        query: group (one of GROUPS), since and until in epoch seconds,
            until at most now and now when left out, and a value per
            dimension of FILTERS to keep; any other key raises ToolError.

    Returns:
        (group, since, until, filters).
    """
    unknown = sorted(set(query) - set(PARAMS))
    if unknown:
        raise ToolError(f"unknown parameter {unknown[0]}: use {', '.join(PARAMS)}")
    group = single(query, "group")
    if group not in GROUPS:
        raise ToolError(f"group must be one of {', '.join(GROUPS)}")
    since, until = instant(query, "since"), instant(query, "until")
    if since is None:
        raise ToolError("since must be given in seconds since the epoch")
    until = now if until is None else min(until, now)
    if since > until:
        raise ToolError("since must not lie after until")
    filters = {name: single(query, name) or "" for name in FILTERS if name in query}
    if any(len(value) > VALUE_TEXT for value in filters.values()):
        raise ToolError(f"a filter value must hold at most {VALUE_TEXT} characters")
    return group, since, until, filters


def matches(row: dict, filters: dict[str, str]) -> bool:
    return all(value in row["tool"].split(",") if name == "tool" else row[name] == value for name, value in filters.items())


def keys_of(row: dict, group: str) -> list:
    """Returns:
        The group keys a row counts under: each tool name of its tool set
        for tool, the start of its hour or day (UTC) for hour and day, else
        its value of the dimension.
    """
    if group == "tool":
        return row["tool"].split(",")
    if group in BUCKETS:
        return [int(row["t"] // BUCKETS[group] * BUCKETS[group])]
    return [row[group]]


def blank() -> dict:
    return {**dict.fromkeys(COUNTS, 0), "cost": 0.0}


def added(total: dict, row: dict, families: dict) -> None:
    for name in COUNTS:
        total[name] += row[name]
    found = cost(row, families)
    total["cost"] = None if found is None or total["cost"] is None else total["cost"] + found


def finished(key: object, total: dict, grand: int) -> dict:
    """Returns:
        The eight columns of one row: input, output, cache_read,
        cache_write, total, share of grand in percent, cost in USD (None
        when a row of an unknown model counts in it) and hit_rate, cache read
        over input plus cache read (None without either).
    """
    tokens = sum(total[name] for name in COUNTS)
    read = total["input"] + total["cache_read"]
    return {
        "key": key, **{name: total[name] for name in COUNTS}, "total": tokens, "share": round(100 * tokens / grand, 1) if grand else None,
        "cost": None if total["cost"] is None else round(total["cost"], 6), "hit_rate": round(total["cache_read"] / read, 4) if read else None,
    }


def quantile(turns: dict[int, int], numerator: int, denominator: int) -> int | None:
    """Returns:
        The nearest-rank quantile numerator / denominator of the histogram
        turns (per kilo, the turns of that context) in tokens, to the KILO
        below; None without a turn.
    """
    rank, seen = -(-sum(turns.values()) * numerator // denominator), 0
    for kilo in sorted(turns):
        seen += turns[kilo]
        if seen >= max(rank, 1):
            return kilo * KILO
    return None


def context_of(folder: Path, since: float, until: float, agent: str | None) -> list[dict]:
    """Returns:
        Per day and agent of context.jsonl within the span (one agent only
        when given) {day, agent, turns, median, p90, compactions}, the newest
        day first.
    """
    merged: dict[tuple, list] = {}
    for row in rows_between(folder / CONTEXT, since, until, DAY):
        turns = row.get("turns")
        if not isinstance(row.get("agent"), str) or not isinstance(turns, dict) or (agent is not None and row["agent"] != agent):
            continue
        found = merged.setdefault((int(row["t"]), row["agent"]), [{}, 0])
        for kilo, number in turns.items():
            if kilo.isdigit() and whole(number):
                found[0][int(kilo)] = found[0].get(int(kilo), 0) + number
        found[1] += whole(row.get("compactions"))
    return [
        {"day": day, "agent": name, "turns": sum(sizes.values()), **{label: quantile(sizes, top, bottom) for label, top, bottom in QUANTILES}, "compactions": compactions}
        for (day, name), (sizes, compactions) in sorted(merged.items(), key=lambda item: (-item[0][0], item[0][1]))
    ]


def lines_of(handle: BinaryIO) -> Iterator[bytes]:
    """Returns:
        The complete lines of handle of at most LINE_LIMIT bytes, read in
        chunks of that size; a longer line and an unterminated last line are
        skipped.
    """
    skipping = False
    while chunk := handle.readline(LINE_LIMIT):
        ended = chunk.endswith(b"\n")
        if ended and not skipping:
            yield chunk
        skipping = not ended


def streamed(path: Path, since: float, until: float) -> Iterator[dict]:
    """Returns:
        The rows of path that reach into since to until, an hourly row by its
        hour and a row with a width by that width, read line by line without
        following a link, so the file's size meets no read limit; a malformed
        line yields nothing, and so does a path that is missing or no
        regular file.
    """
    try:
        handle = os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC), "rb")
    except OSError:
        return
    with handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            return
        for raw in lines_of(handle):
            row = parse_line(raw.decode("utf-8", "replace"))
            t = None if row is None else epoch(row.get("t"))
            if t is not None and t <= until and since <= t + max(HOUR, epoch(row.get("width")) or 0):
                yield row


def usage_view(folder: Path, query: dict[str, list[str]], now: float) -> dict:
    """Args:
        folder: the host sampler's directory, mounted read-only.
        query: as parsed() reads it.
        now: epoch seconds.

    Returns:
        {group, since, until, filters, split, rows, total, prices, context}:
        rows one finished() row per group key, the most tokens first, total
        the finished() sum of every matching usage.jsonl row, each counted
        once, streamed() line by line;
        split true for group tool, where a row of several tools counts under
        each of them, so the shares may sum above 100; prices {date, source}
        of prices.json; context as context_of() gives it.
    """
    group, since, until, filters = parsed(query, now)
    table = prices()
    groups: dict[object, dict] = {}
    grand = blank()
    for row in map(entry, streamed(folder / USAGE, since, until)):
        if row is None or not matches(row, filters):
            continue
        added(grand, row, table["families"])
        for key in keys_of(row, group):
            added(groups.setdefault(key, blank()), row, table["families"])
    tokens = sum(grand[name] for name in COUNTS)
    listed = sorted((finished(key, total, tokens) for key, total in groups.items()), key=lambda found: (-found["total"], str(found["key"])))
    return {
        "group": group, "since": since, "until": until, "filters": filters, "split": group == "tool", "rows": listed, "total": finished(None, grand, tokens),
        "prices": {"date": table["date"], "source": table["source"]}, "context": context_of(folder, since, until, filters.get("agent")),
    }
