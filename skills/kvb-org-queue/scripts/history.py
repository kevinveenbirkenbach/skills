"""Record the jobs of the kvb-org-queue and learn disk need per command and slot limits per kind.

Pure functions over rows and paths: queue.py passes the council history file
and the copy the kvb-org-organize watch hook keeps in ~/.local/state.

A row: id, kind, signature, workdir, start, end (epoch seconds), minutes, exit,
free_before_gb, min_free_gb, disk_gb (free_before_gb - min_free_gb, at least
0), mem_before, mem_max, cpu_before, cpu_max (percent), concurrent (other
active jobs at the grant).
"""

from __future__ import annotations

import json
import math
import os
import re
import statistics
from collections.abc import Iterable, Iterator
from pathlib import Path

MIN_RUNS = 5
WINDOW_SECONDS = 30 * 86400
DISK_MARGIN_GB = 1
MIN_SHARE_PERCENT = 1
SEED_LIMIT = 1
INTERPRETERS = re.compile(r"python[\d.]*|bash|sh|zsh|node|perl|ruby")
MAKE_VALUE_OPTIONS = frozenset({"-C", "-f", "-I", "-o", "-W"})
SIGNATURE_HEADER = ("Signature", "Kind", "Runs", "Median min", "p90 disk GB", "p90 RAM %", "Need GB")
KIND_HEADER = ("Kind", "Runs", "p90 RAM share %", "p90 CPU share %", "Slot limit", "Source")

def first_operand(tokens: Iterable[str]) -> list[str]:
    return [token for token in tokens if not token.startswith("-")][:1]


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
      target or operand is left out.
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
      job: its id, kind, signature and workdir.
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


def record(path: Path, entry: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")


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
    return statistics.quantiles(values, n=10, method="inclusive")[-1]


def shares(rows: list[dict], resource: str) -> list[float]:
    return [r[f"{resource}_max"] - r[f"{resource}_before"] for r in rows]


def grouped(rows: list[dict], key: str) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for entry in rows:
        groups.setdefault(entry[key], []).append(entry)
    return groups


def command_stats(rows: list[dict]) -> dict:
    stats = {
        "kinds": sorted({r["kind"] for r in rows}), "runs": len(rows),
        "minutes": None, "disk_gb": None, "ram_share": None, "need_gb": None,
    }
    if len(rows) >= MIN_RUNS:
        disk = p90([r["disk_gb"] for r in rows])
        stats.update(
            minutes=statistics.median(r["minutes"] for r in rows), disk_gb=disk,
            ram_share=p90(shares(rows, "mem")), need_gb=math.ceil(disk + DISK_MARGIN_GB),
        )
    return stats


def fit(ceiling: float, rows: list[dict], resource: str, share: float) -> int:
    before = statistics.median(r[f"{resource}_before"] for r in rows)
    return math.floor((ceiling - before) / max(share, MIN_SHARE_PERCENT))


def kind_stats(rows: list[dict], limits: dict) -> dict:
    stats = {"runs": len(rows), "ram_share": None, "cpu_share": None, "limit": None}
    if len(rows) >= MIN_RUNS:
        ram, cpu = p90(shares(rows, "mem")), p90(shares(rows, "cpu"))
        stats.update(ram_share=ram, cpu_share=cpu, limit=max(1, min(
            fit(limits["mem_percent"], rows, "mem", ram), fit(limits["cpu_percent"], rows, "cpu", cpu),
        )))
    return stats


def learn(rows: list[dict], now: float, cfg: dict) -> tuple[dict[str, dict], dict[str, dict]]:
    """Derive disk need per command and slot limit per kind from recent rows.

    Args:
      rows: history rows, as read() returns them.
      now: epoch seconds; rows that ended more than WINDOW_SECONDS earlier are
        ignored.
      cfg: the config; load_limits.mem_percent and cpu_percent bound a limit.

    Returns:
      (signatures, kinds). signatures: {signature: {kinds, runs, minutes,
      disk_gb, ram_share, need_gb}}; kinds: {kind: {runs, ram_share,
      cpu_share, limit}}. With fewer than MIN_RUNS rows every value but kinds
      and runs is None. minutes is the median, disk_gb, ram_share and
      cpu_share the p90 of the disk taken and of max minus before in
      percentage points; need_gb is ceil(disk_gb + DISK_MARGIN_GB); limit is
      max(1, min over RAM and CPU of floor((load limit - median before) /
      max(share, MIN_SHARE_PERCENT))).
    """
    recent = [r for r in rows if now - r["end"] <= WINDOW_SECONDS]
    signatures = {name: command_stats(group) for name, group in grouped(recent, "signature").items()}
    kinds = {name: kind_stats(group, cfg["load_limits"]) for name, group in grouped(recent, "kind").items()}
    return signatures, kinds


def need_gb(signatures: dict[str, dict], name: str) -> int | None:
    return signatures[name]["need_gb"] if name in signatures else None


def slot_limits(kinds: dict[str, dict], caps: dict[str, int], names: Iterable[str]) -> dict[str, tuple[int, str]]:
    """Decide the slot limit of every kind.

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


def eta(signatures: dict[str, dict], running: list[tuple[str, float]], ahead: list[str], now: float) -> float | None:
    """Estimate the minutes until a waiting job starts, or until a running one ends.

    Args:
      signatures: the signature map of learn(); its median minutes drive the
        estimate.
      running: (signature, grant epoch seconds) of the running jobs counted.
      ahead: signatures of the waiting jobs before it.
      now: epoch seconds.

    Returns:
      The remaining median minutes of running plus the median minutes of
      ahead, as if run one after another; None when one has no median yet.
    """
    def median(name: str) -> float | None:
        return signatures[name]["minutes"] if name in signatures else None

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


def report(signatures: dict[str, dict], kinds: dict[str, dict], limits: dict[str, tuple[int, str]]) -> str:
    """Render the learned values as two markdown tables.

    Args:
      signatures: the signature map of learn().
      kinds: the kind map of learn().
      limits: slot_limits() for every kind to list.

    Returns:
      A table per signature, a blank line, a table per kind.
    """
    commands = [
        [name, ", ".join(s["kinds"]), str(s["runs"]), cell(s["minutes"]), cell(s["disk_gb"]),
         cell(s["ram_share"]), "-" if s["need_gb"] is None else str(s["need_gb"])]
        for name, s in sorted(signatures.items())
    ]
    per_kind = []
    for kind, (limit, source) in limits.items():
        runs, ram, cpu = 0, None, None
        if kind in kinds:
            runs, ram, cpu = (kinds[kind][key] for key in ("runs", "ram_share", "cpu_share"))
        per_kind.append([kind, str(runs), cell(ram), cell(cpu), str(limit), source])
    return table(SIGNATURE_HEADER, commands) + "\n" + table(KIND_HEADER, per_kind)
