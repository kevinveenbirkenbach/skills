from __future__ import annotations

import math
from collections.abc import Iterable
from pathlib import Path

from .records import epoch, iso_epoch
from .register import OPERATOR, REGISTER, read_register, status_of
from .resources import HOUR, RESOURCES, SAMPLES, TOKENS, rows_between
from .scores import journal

DAY = 86400
PERIODS = (("minute", 60), ("hour", HOUR), ("day", DAY), ("week", 7 * DAY), ("month", 30 * DAY), ("year", 365 * DAY), ("total", None))
PERIOD_NAMES = tuple(name for name, _ in PERIODS)
COUNTS = ("tasks", "commits", "krs", "tokens")
GAUGES = ("cpu", "ram", "vram", "swap", "disk")
METRICS = (*COUNTS, *GAUGES)
HOST = ("cpu", "ram", "swap")
TOKEN_FIELDS = ("input", "output", "cache_read", "cache_write")
FINEST = {"tokens": HOUR}
INTERVAL = 60
DONE = "done"
DIGITS = 4
TOTAL = "total"

NUMBERS = (int, float)
LIMIT = 1e18

Piece = tuple[float | None, float | None, float]
Placed = tuple[float, float, dict]


def rounded(value: float | None, digits: int) -> float | int | None:
    if value is None:
        return None
    return round(value) if digits == 0 else round(value, digits)


def points(times: Iterable[float | None]) -> list[Piece]:
    return [(t, t, 1.0) for t in times]


def task_times(tasks: dict[str, dict]) -> list[float | None]:
    """Returns:
        The end of every done register task but the operator's commands,
        None for one without a readable end.
    """
    return [iso_epoch(row.get("end")) for task, row in tasks.items() if not task.startswith(OPERATOR) and status_of(row) == DONE]


def kr_times(tasks: dict[str, dict]) -> list[float | None]:
    """Returns:
        The met_at of every met key result, None for one met before
        rasci.py recorded that time.
    """
    results = [kr for row in tasks.values() if isinstance(row.get("key_results"), list) for kr in row["key_results"]]
    return [iso_epoch(kr.get("met_at")) for kr in results if isinstance(kr, dict) and kr.get("met") is True]


def commit_times(rows: list[dict]) -> list[float | None]:
    """Returns:
        The time of every commit the score journal holds a row with a sha
        for, once per remote and sha.
    """
    found: dict[tuple[str | None, str], float | None] = {}
    for row in rows:
        sha, remote = row.get("sha"), row.get("remote")
        if isinstance(sha, str) and sha:
            found.setdefault((remote if isinstance(remote, str) else None, sha), epoch(row.get("time")))
    return list(found.values())


def token_pieces(rows: list[dict], now: float) -> list[Piece]:
    """Returns:
        Per token row its hour, or its day for a row with width, cut at now,
        and its tokens of every kind.
    """
    found = []
    for row in rows:
        t = epoch(row.get("t"))
        width = row["width"] if sane(row.get("width")) and row["width"] > 0 else HOUR
        amount = sum(value for name in TOKEN_FIELDS if isinstance(value := row.get(name), int) and not isinstance(value, bool) and value > 0)
        if t is not None and amount:
            found.append((t, max(t, min(t + width, now)), float(amount)))
    return found


def share(piece: Piece, begin: float, now: float) -> float:
    """Returns:
        The part of the piece's amount inside [begin, now]: an instant
        counts whole or not at all, a span by the share of it inside.
    """
    start, end, amount = piece
    if start is None or end is None:
        return 0.0
    if end <= start:
        return amount if begin <= start <= now else 0.0
    inside = min(end, now) - max(start, begin)
    return amount * inside / (end - start) if inside > 0 else 0.0


def sums(pieces: list[Piece], now: float, finest: float) -> dict[str, float | None]:
    """Args:
        pieces: (start, end, amount) per event; start None for one without
            a time, end equal to start for an instant.
        now: the end of every window.
        finest: the shortest window the pieces resolve; a shorter one holds
            no event of its own.

    Returns:
        Per period the amount inside its window, None below finest; total
        holds every piece.
    """
    found: dict[str, float | None] = {}
    for name, seconds in PERIODS:
        if seconds is None:
            found[name] = sum(piece[2] for piece in pieces)
        else:
            found[name] = None if seconds < finest else sum(share(piece, now - seconds, now) for piece in pieces)
    return found


def lengths(now: float, since: float | None) -> dict[str, float | None]:
    total = now - since if since is not None and now > since else None
    return {name: total if seconds is None else float(seconds) for name, seconds in PERIODS}


def held(now: float, since: float | None, begins: float | None) -> dict[str, float | None]:
    """Args:
        now: the end of every window.
        since: the first time any record holds.
        begins: the first time the records of one kind hold, None when they
            reach back as far as any record.

    Returns:
        Per period the seconds now - begins where other records reach
        further back into its window than this kind's, else None.
    """
    if since is None or begins is None:
        return dict.fromkeys(PERIOD_NAMES)
    return {name: now - begins if begins > (since if seconds is None else max(now - seconds, since)) else None for name, seconds in PERIODS}


def estimate(own: dict[str, float | None], length: dict[str, float | None], partial: dict[str, float | None], index: int) -> tuple[float, str | None]:
    """Returns:
        (value, source) of the period at index in PERIODS: its own amount
        when partial holds no seconds for it and it holds any or is total;
        its own amount scaled from the partial seconds to the part of its
        window any record covers when it holds any, source total; else the
        shortest longer window that holds any, scaled to the period's length
        (at most its whole amount), source that window, or total when
        partial holds seconds for that window and those scale it; 0 without
        any.
    """
    name, seconds = PERIODS[index]
    value = own[name]
    if partial[name] is None and (value or seconds is None):
        return value or 0.0, None
    if value and partial[name]:
        return value * min(length[name], length[TOTAL]) / partial[name], TOTAL
    for other, _ in PERIODS[index + 1:]:
        if own[other] and length[other]:
            covered = partial[other] or length[other]
            return own[other] * min(1.0, (seconds or covered) / covered), TOTAL if partial[other] else other
    return 0.0, None


def extrapolated(own: dict[str, float | None], length: dict[str, float | None], partial: dict[str, float | None]) -> dict[str, dict]:
    """Args:
        own: sums() of one kind.
        length: lengths() of the windows.
        partial: held() of the kind.

    Returns:
        Per period {value, approx, source} of estimate(); approx whenever it
        names a source.
    """
    found = {}
    for index, name in enumerate(PERIOD_NAMES):
        value, source = estimate(own, length, partial, index)
        found[name] = {"value": precise(value), "approx": source is not None, "source": source}
    return found


def precise(value: float) -> float:
    return round(value, DIGITS - 1) if value >= 1 else float(f"{value:.{DIGITS}g}")


def sane(value: object) -> bool:
    return type(value) in NUMBERS and -LIMIT < value < LIMIT


def placed(row: dict) -> Placed | None:
    """Returns:
        (t, width, row) of a sample row: width the seconds of the bucket a
        folded row stands for (its span when it names no width, 0 for a raw
        row, an instant); None without a time.
    """
    t = epoch(row.get("t"))
    if t is None:
        return None
    width, span = row.get("width"), row.get("span")
    return t, float(width if sane(width) and width > 0 else span if sane(span) and span > 0 else 0), row


def blank() -> dict:
    return {**{key: [0.0, 0.0] for key in HOST}, "vram": [0.0, 0.0, 0.0], "disks": {}}


def copied(tally: dict) -> dict:
    return {**{key: list(tally[key]) for key in (*HOST, "vram")}, "disks": {mount: list(cell) for mount, cell in tally["disks"].items()}}


def add_vram(cell: list[float], gpus: object, weight: float) -> None:
    used = total = 0.0
    for gpu in gpus if type(gpus) is list else ():
        if type(gpu) is dict and gpu.get("asleep") is not True:
            part, whole = gpu.get("vram_used"), gpu.get("vram_total")
            if sane(part) and sane(whole) and whole > 0:
                used, total = used + part, total + whole
    if total:
        cell[0] += weight
        cell[1] += weight * 100 * used / total
        cell[2] += weight * used


def add_disks(cells: dict[str, list[float]], disks: object, weight: float) -> None:
    for disk in disks if type(disks) is list else ():
        if type(disk) is dict:
            mount, used, total = disk.get("mount"), disk.get("used"), disk.get("total")
            if type(mount) is str and sane(used) and sane(total) and total > 0:
                cell = cells.get(mount) or cells.setdefault(mount, [0.0, 0.0, 0.0, 0.0])
                cell[0] += weight
                cell[1] += weight * 100 * used / total
                cell[2] += weight * used
                cell[3] += weight * total


def add(tally: dict, row: dict, part: float) -> None:
    """Args:
        tally: blank() summed so far: per host key [weight, weighted value],
            vram [weight, weighted percent, weighted bytes] of every GPU
            awake with a reading together, per mount [weight, weighted
            percent, weighted used, weighted total].
        row: one sample row, weighted by the seconds it sampled: its span,
            INTERVAL for a raw row.
        part: the share of the row inside the window.
    """
    span = row.get("span")
    weight = (span if sane(span) and span > 0 else INTERVAL) * part
    for key in HOST:
        value = row.get(key)
        if sane(value):
            cell = tally[key]
            cell[0] += weight
            cell[1] += weight * value
    add_vram(tally["vram"], row.get("gpus"), weight)
    add_disks(tally["disks"], row.get("disks"), weight)


def tallies(items: list[Placed], begins: list[float]) -> list[dict]:
    """Args:
        items: placed() of every sample row, newest first.
        begins: the start of every window, latest first; every window ends
            at the newest row or later.

    Returns:
        Per window the add() of every row inside it, a row whose bucket
        straddles its start by the share inside, in one pass over items.
    """
    widest = max((item[1] for item in items), default=0.0)
    running, index, found = blank(), 0, []
    for begin in begins:
        while index < len(items) and items[index][0] >= begin:
            add(running, items[index][2], 1.0)
            index += 1
        tally = copied(running)
        cursor = index
        while cursor < len(items) and items[cursor][0] > begin - widest:
            t, width, row = items[cursor]
            if t + width > begin:
                add(tally, row, (t + width - begin) / width)
            cursor += 1
        found.append(tally)
    return found


def mean(cell: list[float], at: int) -> float | None:
    return cell[at] / cell[0] if cell[0] else None


def fullest(mounts: dict[str, list[float]]) -> dict:
    """Returns:
        {value, mount, used, total} of the mount fullest on average, all
        None without a disk.
    """
    top = max(mounts, key=lambda mount: (mean(mounts[mount], 1), mount), default=None)
    if top is None:
        return {"value": None, "mount": None, "used": None, "total": None}
    cell = mounts[top]
    return {"value": rounded(mean(cell, 1), 1), "mount": top, "used": rounded(mean(cell, 2), 0), "total": rounded(mean(cell, 3), 0)}


def gauges(tally: dict) -> dict[str, dict]:
    """Returns:
        Per gauge its mean over the rows the tally holds, each row weighted
        by its seconds inside the window: value the percent, None without a
        reading; vram adds used, the bytes, and disk names the mount fullest
        on average.
    """
    found = {key: {"value": rounded(mean(tally[key], 1), 1)} for key in HOST}
    found["vram"] = {"value": rounded(mean(tally["vram"], 1), 1), "used": rounded(mean(tally["vram"], 2), 0)}
    found["disk"] = fullest(tally["disks"])
    return {key: {**entry, "approx": False, "source": None} for key, entry in found.items()}


def rated(council: Path, kept: Path, now: float) -> dict:
    """Args:
        council: the council directory holding the register and the score
            journal, read through scores.journal().
        kept: the directory holding the host sampler's resources folder.
        now: the end of every window in epoch seconds.

    Returns:
        {"now", "since", "periods", "rates"}: since the first time any record
        holds; periods [{name, seconds}], total without seconds; rates per
        period per metric {value, approx, source}: the done tasks, the
        commits, the key results met and the tokens inside the window ending
        now, extrapolated() where it holds none or, for tokens, where it
        reaches back before the first token row, and the gauges() of the
        samples inside it; total spans every record.
    """
    tasks = read_register(council / REGISTER)
    folder = kept / RESOURCES
    items = sorted(filter(None, map(placed, rows_between(folder / SAMPLES, 0, now, 0))), key=lambda item: item[0], reverse=True)
    counted = {
        "tasks": points(task_times(tasks)),
        "commits": points(commit_times(journal(council))),
        "krs": points(kr_times(tasks)),
        "tokens": token_pieces(rows_between(folder / TOKENS, 0, now, HOUR), now),
    }
    starts = {kind: [piece[0] for piece in pieces if piece[0] is not None] for kind, pieces in counted.items()}
    times = [*(t for found in starts.values() for t in found), *(item[0] for item in items)]
    since = min(times) if times else None
    length = lengths(now, since)
    begins = {"tokens": min(starts["tokens"], default=None)}
    counts = {kind: extrapolated(sums(pieces, now, FINEST.get(kind, 0)), length, held(now, since, begins.get(kind))) for kind, pieces in counted.items()}
    measured = tallies(items, [-math.inf if seconds is None else now - seconds for _, seconds in PERIODS])
    shown = {name: {**{kind: counts[kind][name] for kind in COUNTS}, **gauges(tally)} for name, tally in zip(PERIOD_NAMES, measured, strict=True)}
    return {"now": now, "since": since, "periods": [{"name": name, "seconds": seconds} for name, seconds in PERIODS], "rates": shown}
