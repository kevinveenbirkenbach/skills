from __future__ import annotations

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
FINEST = {"tasks": 0, "commits": 0, "krs": 0, "tokens": HOUR}
INTERVAL = 60
DONE = "done"
DIGITS = 4

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


def counted(pieces: list[Piece], window: tuple[float, float], first: float | None, finest: float) -> dict[str, dict]:
    """Args:
        pieces: (start, end, amount) per event of one kind; start None for
            one without a time, end equal to start for an instant.
        window: (begin, end) the rates cover, in epoch seconds.
        first: the first time the records of the kind hold, None without any.
        finest: the shortest span the kind's pieces resolve.

    Returns:
        Per period {value, approx, covered}: covered the seconds of the
        window from first on; total the amount inside the window, every
        other period that amount per its seconds of covered; value None
        where no record covers the window; approx where the window is
        shorter than finest, and for every period but total where it starts
        before first.
    """
    begin, end = window
    covered = end - max(begin, first) if first is not None else 0.0
    if covered <= 0:
        return {name: {"value": None, "approx": False, "covered": None} for name in PERIOD_NAMES}
    amount = sum(share(piece, begin, end) for piece in pieces)
    short, early = end - begin < finest, begin < first
    return {
        name: {"value": precise(amount if seconds is None else amount * seconds / covered), "approx": short or (early and seconds is not None), "covered": covered}
        for name, seconds in PERIODS
    }


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


def tally(items: list[Placed], window: tuple[float, float]) -> dict:
    """Returns:
        The add() of every placed() row inside the window, a row whose
        bucket straddles either end by its share inside.
    """
    found = blank()
    for t, width, row in items:
        part = share((t, t + width, 1.0), *window)
        if part:
            add(found, row, part)
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
    return {key: {**entry, "approx": False} for key, entry in found.items()}


def rated(council: Path, kept: Path, now: float, window: tuple[float, float]) -> dict:
    """Args:
        council: the council directory holding the register and the score
            journal, read through scores.journal().
        kept: the directory holding the host sampler's resources folder.
        now: the present in epoch seconds; the current token hour ends here.
        window: (begin, end) the rates cover, end at most now.

    Returns:
        {"now", "since", "from", "to", "periods", "rates"}: since the first
        time any record holds; periods [{name, seconds}], total without
        seconds; rates per period per metric: counted() of the done tasks,
        the commits, the key results met and the tokens, each kind covered
        from since on, tokens from their first row, and the gauges() of the
        samples inside the window, the same in every period.
    """
    tasks = read_register(council / REGISTER)
    folder = kept / RESOURCES
    items = list(filter(None, map(placed, rows_between(folder / SAMPLES, 0, now, 0))))
    pieces = {
        "tasks": points(task_times(tasks)),
        "commits": points(commit_times(journal(council))),
        "krs": points(kr_times(tasks)),
        "tokens": token_pieces(rows_between(folder / TOKENS, 0, now, HOUR), now),
    }
    starts = {kind: [piece[0] for piece in found if piece[0] is not None] for kind, found in pieces.items()}
    since = min([*(t for found in starts.values() for t in found), *(item[0] for item in items)], default=None)
    firsts = {**dict.fromkeys(COUNTS, since), "tokens": min(starts["tokens"], default=None)}
    counts = {kind: counted(found, window, firsts[kind], FINEST[kind]) for kind, found in pieces.items()}
    measured = gauges(tally(items, window))
    shown = {name: {**{kind: counts[kind][name] for kind in COUNTS}, **measured} for name in PERIOD_NAMES}
    return {"now": now, "since": since, "from": window[0], "to": window[1], "periods": [{"name": name, "seconds": seconds} for name, seconds in PERIODS], "rates": shown}
