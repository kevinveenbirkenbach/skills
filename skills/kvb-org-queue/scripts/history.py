"""Record the jobs of the kvb-org-queue and learn disk need per command and slot limits per kind.

Pure functions over rows and paths: queue.py passes the council history file
and the copy the kvb-org-organize watch hook keeps in ~/.local/state.

A row: id, kind, signature, workdir, start, end (epoch seconds), minutes, exit,
free_before_gb, min_free_gb, disk_gb (free_before_gb - min_free_gb, at least
0), mem_before, mem_max, cpu_before, cpu_max (percent), concurrent (other
active jobs at the grant), PREDICTED ({ram, cpu}, the footprint the grant
booked) only on a run granted on a learned footprint, and HUNG ({cpu_s,
read_bytes, written_bytes, still_min, members, tree}, the report of
standstill.py) only on a run hold ended for standing still, whose exit is
124, and override (true) only on a run `queue.py override` started past the
budget; learn() counts it like every other run.
"""

from __future__ import annotations

import json
import math
import operator
import os
import re
from collections.abc import Callable, Hashable, Iterable, Iterator
from pathlib import Path

MIN_RUNS = 5
WINDOW_SECONDS = 30 * 86400
DISK_MARGIN_GB = 1
MIN_SHARE_PERCENT = 1
SEED_LIMIT = 1
INTERPRETERS = re.compile(r"python[\d.]*|bash|sh|zsh|node|perl|ruby")
MAKE_VALUE_OPTIONS = frozenset({"-C", "-f", "-I", "-o", "-W"})
RESOURCES = ("ram", "cpu")
SIGNATURE_KEY = operator.itemgetter("kind", "signature")
NAME_KEY = operator.itemgetter("signature")
KIND_KEY = operator.itemgetter("kind")
ANY_KIND = "*"
RAM_CAP = "ram_cap_percent"
HUNG = "hung"
PREDICTED = "predicted"
MARGIN = (1.0, 2.0)
MARGIN_SHRINK = 0.05
SHARE_SOURCES = {"ram": "mem", "cpu": "cpu"}
SIGNATURE_HEADER = ("Signature", "Kind", "Runs", "Median min", "p90 disk GB", "p95 RAM %", "Margin", "Need GB")
KIND_HEADER = ("Kind", "Runs", "p90 RAM share %", "Median CPU share %", "Slot limit", "Source")

def first_operand(tokens: Iterable[str]) -> list[str]:
    operand = next((token for token in tokens if not token.startswith("-")), None)
    return [] if operand is None or os.sep in operand else [operand]


def make_target(tokens: Iterator[str]) -> list[str]:
    for token in tokens:
        if token in MAKE_VALUE_OPTIONS:
            next(tokens, None)
        # A bare number is the count of a preceding -j or -l, not a target.
        elif not (token.startswith("-") or "=" in token or token.isdigit()):
            return [token]
    return []


def signature(argv: list[str]) -> str:
    """Name a command apart from its paths, options and variables.

    Args:
      argv: the command as run.

    Returns:
      `make <first target>` for make, skipping -C, -f, -I, -o and -W with their
      values, other options, job counts and VAR=value; `<script basename>
      <first operand>` for an interpreter running a script (python, bash, ...)
      and `<interpreter> -c` for inline code; else `<argv[0] basename> <first
      operand>`. An operand is an argument not starting with `-`; a missing
      target or operand is left out, and so is an operand holding a path
      separator.
    """
    name = os.path.basename(argv[0])
    tokens = iter(argv[1:])
    if name == "make":
        return " ".join([name, *make_target(tokens)])
    if INTERPRETERS.fullmatch(name):
        for token in tokens:
            if token == "-c":
                return f"{name} -c"
            if not token.startswith("-"):
                name = os.path.basename(token)
                break
    return " ".join([name, *first_operand(tokens)])


def row(job: dict, start: float, end: float, code: int, samples: list[dict[str, float]], concurrent: int) -> dict:
    """Build the history row of a finished job.

    Args:
      job: its id, kind, signature and workdir, with HUNG and override when
        set.
      start: epoch seconds the command started.
      end: epoch seconds it ended.
      code: its exit code.
      samples: {free_gb, mem, cpu} measurements, the first taken at the grant.
      concurrent: other active jobs at the grant.
    """
    before = samples[0]
    min_free = min(s["free_gb"] for s in samples)
    return {
        **job,
        "start": start,
        "end": end,
        "minutes": round((end - start) / 60, 2),
        "exit": code,
        "free_before_gb": round(before["free_gb"], 2),
        "min_free_gb": round(min_free, 2),
        "disk_gb": round(max(0.0, before["free_gb"] - min_free), 2),
        "mem_before": round(before["mem"], 1),
        "mem_max": round(max(s["mem"] for s in samples), 1),
        "cpu_before": round(before["cpu"], 1),
        "cpu_max": round(max(s["cpu"] for s in samples), 1),
        "concurrent": concurrent,
    }


def line(entry: dict) -> str:
    return json.dumps(entry, sort_keys=True) + "\n"


def read(paths: Iterable[Path]) -> list[dict]:
    """Merge the rows of every history file.

    Args:
      paths: JSON-lines files; a missing file holds no rows and a line that is
        no JSON object with an id is skipped.

    Returns:
      The rows, the first one of each id winning.
    """
    rows: dict[str, dict] = {}
    for path in paths:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            continue
        for line in lines:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if isinstance(entry, dict) and "id" in entry:
                rows.setdefault(entry["id"], entry)
    return list(rows.values())


def p90(values: list[float]) -> float:
    import statistics

    return statistics.quantiles(values, n=10, method="inclusive")[-1]


def p95(values: list[float]) -> float:
    import statistics

    return statistics.quantiles(values, n=20, method="inclusive")[-1]


def median(values: Iterable[float]) -> float:
    import statistics

    return statistics.median(values)


def shares(rows: list[dict], resource: str) -> list[float]:
    return [r[f"{resource}_max"] - r[f"{resource}_before"] for r in rows]


def grouped(rows: list[dict], key: Callable[[dict], Hashable]) -> dict[Hashable, list[dict]]:
    groups: dict[Hashable, list[dict]] = {}
    for entry in rows:
        groups.setdefault(key(entry), []).append(entry)
    return groups


def command_stats(rows: list[dict]) -> dict:
    stats = {"runs": len(rows), "minutes": None, "longest": None, "disk_gb": None, "ram_share": None, "cpu_share": None,
             "need_gb": None, "margin": margin(rows)}
    if len(rows) >= MIN_RUNS:
        disk = p90([r["disk_gb"] for r in rows])
        stats.update(
            minutes=median(r["minutes"] for r in rows), longest=max(r["minutes"] for r in rows), disk_gb=disk,
            ram_share=p95(shares(rows, "mem")), cpu_share=median(shares(rows, "cpu")),
            need_gb=math.ceil(disk + DISK_MARGIN_GB),
        )
    return stats


def margin(rows: list[dict]) -> float:
    """Returns:
        The factor a command's learned shares are booked with, replayed
        over its rows by end: from MARGIN[0], a row whose share (max minus
        before) passed what its grant booked (PREDICTED) on a resource
        multiplies it by the largest such ratio, any other row with
        PREDICTED lowers it by MARGIN_SHRINK; always within MARGIN. Rows
        without PREDICTED leave it as it is.
    """
    value = MARGIN[0]
    for row in sorted(rows, key=lambda r: r["end"]):
        booked = row.get(PREDICTED)
        if not isinstance(booked, dict):
            continue
        ratios = [
            (row[f"{source}_max"] - row[f"{source}_before"]) / booked[resource]
            for resource, source in SHARE_SOURCES.items()
            if isinstance(booked.get(resource), (int, float)) and not isinstance(booked[resource], bool) and booked[resource] > 0
        ]
        if ratios:
            worst = max(ratios)
            value = min(MARGIN[1], max(MARGIN[0], value * worst if worst > 1 else value - MARGIN_SHRINK))
    return value


def fit(ceiling: float, rows: list[dict], resource: str, share: float) -> int:
    before = median(r[f"{resource}_before"] for r in rows)
    return math.floor((ceiling - before) / max(share, MIN_SHARE_PERCENT))


def kind_stats(rows: list[dict], limits: dict) -> dict:
    stats = {"runs": len(rows), "ram_share": None, "cpu_share": None, "limit": None}
    if len(rows) >= MIN_RUNS:
        ram, cpu = p90(shares(rows, "mem")), median(shares(rows, "cpu"))
        stats.update(ram_share=ram, cpu_share=cpu, limit=max(1, min(
            fit(limits["mem_percent"], rows, "mem", ram), fit(limits["cpu_percent"], rows, "cpu", cpu),
        )))
    return stats


def learn(rows: list[dict], now: float, cfg: dict) -> tuple[dict[tuple[str, str], dict], dict[str, dict]]:
    """Derive disk need per command and slot limit per kind from recent rows.

    Args:
      rows: history rows, as read() returns them; HUNG rows are ignored, as
        their standstill would stretch the minutes and the shares.
      now: epoch seconds; rows that ended more than WINDOW_SECONDS earlier are
        ignored.
      cfg: the config; load_limits.mem_percent and cpu_percent bound a limit,
        light_kinds marks a kind light, RAM_CAP {kind: percent} sets its
        ram_cap.

    Returns:
      (signatures, kinds). signatures: {(kind, signature): {runs, minutes,
      longest, disk_gb, ram_share, cpu_share, need_gb, margin}}, and {(ANY_KIND, signature):
      ...} over the rows of every kind with that signature, which is what a
      queue before the per-kind learning booked; kinds: {kind: {runs,
      ram_share, cpu_share, limit, light, ram_cap}}, ram_cap None without a
      cap. With fewer than MIN_RUNS rows every value but runs, margin, light
      and ram_cap is None.
      minutes is the median and longest the largest minutes, disk_gb the
      p90 of the disk taken; a signature's ram_share and cpu_share are the
      p95 of max minus before in percentage points, its margin margin();
      a kind's ram_share is the p90 and its cpu_share the median of max
      minus before; need_gb is ceil(disk_gb + DISK_MARGIN_GB); limit is
      max(1, min over RAM and CPU of floor((load limit - median before) /
      max(share, MIN_SHARE_PERCENT))).
    """
    recent = [r for r in rows if now - r["end"] <= WINDOW_SECONDS and HUNG not in r]
    light = set(cfg.get("light_kinds", []))
    caps = cfg.get(RAM_CAP, {})
    signatures = {(ANY_KIND, name): command_stats(group) for name, group in grouped(recent, NAME_KEY).items()}
    signatures.update((key, command_stats(group)) for key, group in grouped(recent, SIGNATURE_KEY).items())
    kinds = {
        name: {**kind_stats(group, cfg["load_limits"]), "light": name in light, "ram_cap": caps.get(name)}
        for name, group in grouped(recent, KIND_KEY).items()
    }
    return signatures, kinds


def own(signatures: dict[tuple[str, str], dict], kind: str, name: str) -> dict | None:
    stats = signatures.get((kind, name))
    return stats if stats is not None and stats["runs"] >= MIN_RUNS else None


def wider(signatures: dict[tuple[str, str], dict], aliases: tuple[str, ...]) -> list[dict]:
    found = [signatures.get((ANY_KIND, name)) for name in aliases]
    return [stats for stats in found if stats is not None and stats["runs"] >= MIN_RUNS]


def footprint(kind: str, aliases: tuple[str, ...], signatures: dict[tuple[str, str], dict],
              kinds: dict[str, dict]) -> dict[str, float] | None:
    """Predict the RAM and CPU share a job takes, in percentage points.

    Args:
      kind: the job's kind.
      aliases: its signature, then the signature rows before the runner
        naming carry for the same command.
      signatures: the signature map of learn().
      kinds: the kind map of learn().

    Returns:
      {ram, cpu}: the signature's share under kind once MIN_RUNS rows exist
      there, each share times its margin (largest()), for a kind not light
      at least booked_before(); else the
      largest of the kind's share and each alias's share over every kind,
      so a shape without runs of its own never books less than its kind or
      the runs it was learned from; at least MIN_SHARE_PERCENT; RAM at most
      the kind's ram_cap (capped()). None while the kind is not learned yet.
    """
    if kind not in kinds or kinds[kind]["ram_share"] is None:
        return None
    mine = own(signatures, kind, aliases[0])
    if mine is None:
        sources = [kinds[kind], *wider(signatures, aliases)]
    else:
        sources = [mine] if kinds[kind]["light"] else [mine, booked_before(kind, aliases, signatures, kinds)]
    return capped(kinds[kind], largest(sources))


def booked_before(kind: str, aliases: tuple[str, ...], signatures: dict[tuple[str, str], dict],
                  kinds: dict[str, dict]) -> dict:
    """Returns:
        The stats a queue before the per-kind learning booked the job on:
        its last alias over every kind once learned, else its kind's.
    """
    pooled = wider(signatures, aliases[-1:])
    return pooled[0] if pooled else kinds[kind]


def ceiling(kind: str, aliases: tuple[str, ...], signatures: dict[tuple[str, str], dict],
            kinds: dict[str, dict]) -> dict[str, float] | None:
    """Returns:
        The largest of every share footprint() can pick for the job: its
        signature under kind once learned, its kind's and each alias's over
        every kind, which holds booked_before(); RAM at most the kind's
        ram_cap (capped()); None while the kind is not learned yet.
    """
    if kind not in kinds or kinds[kind]["ram_share"] is None:
        return None
    mine = own(signatures, kind, aliases[0])
    return capped(kinds[kind], largest([kinds[kind], *wider(signatures, aliases), *([mine] if mine is not None else [])]))


def largest(sources: list[dict]) -> dict[str, float]:
    """Returns:
        {ram, cpu}: the largest share of sources, each times its margin
        (1.0 for a kind's stats), at least MIN_SHARE_PERCENT.
    """
    return {
        resource: max(MIN_SHARE_PERCENT, *(s[f"{resource}_share"] * s.get("margin", MARGIN[0]) for s in sources))
        for resource in RESOURCES
    }


def capped(stats: dict, shares: dict[str, float]) -> dict[str, float]:
    """Returns:
        shares with RAM lowered to the ram_cap of the kind stats, learn()'s
        RAM_CAP value; unchanged without one.
    """
    cap = stats.get("ram_cap")
    return shares if cap is None else {**shares, "ram": min(shares["ram"], cap)}


def learned_value(signatures: dict[tuple[str, str], dict], kind: str, aliases: tuple[str, ...],
                  field: str) -> float | None:
    """Returns:
        field of the signature under kind once MIN_RUNS rows exist there,
        else the largest field of the aliases over every kind, else None.
    """
    mine = own(signatures, kind, aliases[0])
    return mine[field] if mine is not None else max((s[field] for s in wider(signatures, aliases)), default=None)


def seed_ram(kinds: dict[str, dict]) -> float:
    """Returns:
        The RAM share assumed for a kind not learned yet: the largest of the
        learned kinds' p90 RAM shares, 0 while none is learned.
    """
    return max((stats["ram_share"] for stats in kinds.values() if stats["ram_share"] is not None), default=0.0)


def need_gb(signatures: dict[tuple[str, str], dict], kinds: dict[str, dict], kind: str,
            aliases: tuple[str, ...]) -> int | None:
    """Returns:
        The disk need learned_value() finds, None while nothing is learned
        (slot_need_gb); for a kind not light at least that of the last alias
        over every kind, as a queue before the per-kind learning booked.
    """
    learned = learned_value(signatures, kind, aliases, "need_gb")
    pooled = [] if kind in kinds and kinds[kind]["light"] else wider(signatures, aliases[-1:])
    return max(learned, pooled[0]["need_gb"]) if pooled else learned


def slot_limits(kinds: dict[str, dict], caps: dict[str, int], names: Iterable[str]) -> dict[str, tuple[int, str]]:
    """Report the slot limit history fits for every kind; queue.py admits by
    its utilization band, and only the config caps bind there.

    Args:
      kinds: the kind map of learn().
      caps: the config's optional slot_limits {kind: N}; a cap only lowers.
      names: kinds to decide besides those of kinds and caps.

    Returns:
      {kind: (limit, source)}, sorted by kind: the learned limit (source
      `learned`), else SEED_LIMIT (`seed`), lowered to a smaller cap
      (`capped by config`).
    """
    limits = {}
    for kind in sorted({*names, *kinds, *caps}):
        limit, source = SEED_LIMIT, "seed"
        if kind in kinds and kinds[kind]["limit"] is not None:
            limit, source = kinds[kind]["limit"], "learned"
        if kind in caps and caps[kind] < limit:
            limit, source = caps[kind], "capped by config"
        limits[kind] = (limit, source)
    return limits


def eta(signatures: dict[tuple[str, str], dict], running: list[tuple[tuple[str, tuple[str, ...]], float]],
        ahead: list[tuple[str, tuple[str, ...]]], now: float) -> float | None:
    """Estimate the minutes until a waiting job starts, or until a running one ends.

    Args:
      signatures: the signature map of learn(); its median minutes
        (learned_value()) drive the estimate.
      running: ((kind, aliases), grant epoch seconds) of the running jobs
        counted.
      ahead: (kind, aliases) of the waiting jobs before it.
      now: epoch seconds.

    Returns:
      The remaining median minutes of running plus the median minutes of
      ahead, as if run one after another; None when one has no median yet.
    """
    def median(key: tuple[str, tuple[str, ...]]) -> float | None:
        return learned_value(signatures, key[0], key[1], "minutes")

    parts = [(median(name), (now - granted) / 60) for name, granted in running]
    parts += [(median(name), 0.0) for name in ahead]
    if any(minutes is None for minutes, _ in parts):
        return None
    return sum(max(0.0, minutes - elapsed) for minutes, elapsed in parts)


def cell(value: float | None) -> str:
    return "-" if value is None else f"{value:.1f}"


def table(header: tuple[str, ...], rows: list[list[str]]) -> str:
    lines = [header, ["---"] * len(header), *rows]
    return "".join(f"| {' | '.join(line)} |\n" for line in lines)


def report(signatures: dict[tuple[str, str], dict], kinds: dict[str, dict], limits: dict[str, tuple[int, str]]) -> str:
    """Render the learned values as two markdown tables.

    Args:
      signatures: the signature map of learn().
      kinds: the kind map of learn().
      limits: slot_limits() for every kind to list.

    Returns:
      A table per signature and kind, sorted by signature, a blank line, a
      table per kind.
    """
    commands = [
        [name, kind, str(s["runs"]), cell(s["minutes"]), cell(s["disk_gb"]),
         cell(s["ram_share"]), f"{s.get('margin', MARGIN[0]):.2f}", "-" if s["need_gb"] is None else str(s["need_gb"])]
        for (kind, name), s in sorted(signatures.items(), key=lambda item: item[0][::-1]) if kind != ANY_KIND
    ]
    per_kind = []
    for kind, (limit, source) in limits.items():
        runs, ram, cpu = 0, None, None
        if kind in kinds:
            runs, ram, cpu = (kinds[kind][key] for key in ("runs", "ram_share", "cpu_share"))
        per_kind.append([kind, str(runs), cell(ram), cell(cpu), str(limit), source])
    return table(SIGNATURE_HEADER, commands) + "\n" + table(KIND_HEADER, per_kind)
