"""Read and check the resource limits file of the agents council (requirement 083).

<root>/limits.json (root: councilroot.py) is the one source of the load limits
queue.py and watch.py apply over their config, and of the lines the hub draws
(requirement 084). One JSON object holding every metric with its four levels:

    {"cpu":  {"lower": 70, "upper": 90, "stop": 95, "mayday": 99},
     "ram":  {"lower": 70, "upper": 85, "stop": 92, "mayday": 97},
     "swap": {"lower": 20, "upper": 60, "stop": 90, "mayday": 97},
     "disk": {"lower": 70, "upper": 85, "stop": 95, "mayday": 98},
     "psi":  {"lower": 1, "upper": 10, "stop": 30, "mayday": 60}}

Every value is a percent from 0 to 100: cpu is CPU busy, ram RAM used (100
less MemAvailable), swap swap used, disk the used share of the watch disk,
psi the memory PSI some avg10; per metric lower < upper < stop < mayday.
applied() maps them onto the config keys their readers use: the queue band
from cpu and ram lower and upper, its AIMD target between them with psi
lower as its calm bound, the live guard load_limits cpu_percent and
mem_percent from cpu and ram stop; the watch memory stage warn from ram,
swap and psi upper, stop from their stop; the disk stages warn, stop and
critical (thresholds_gb, whose stop is the queue's floor) from disk upper,
stop and mayday. A valid file is kept as <root>/limits.last.json; a file
that breaks the checks is refused and that copy stays in force; without
the file the config applies.
"""

from __future__ import annotations

import contextlib
import importlib.util
import itertools
import json
import math
import os
from pathlib import Path

METRICS = ("cpu", "ram", "swap", "disk", "psi")
LEVELS = ("lower", "upper", "stop", "mayday")
NAME = "limits.json"
LAST = "limits.last.json"
KEY = "limits"
MEMORY_STAGES = {"warn": "upper", "stop": "stop"}
DISK_STAGES = {"warn": "upper", "stop": "stop", "critical": "mayday"}
UNREADABLE = (OSError, ValueError, RecursionError)


def _nofollow():
    spec = importlib.util.spec_from_file_location("kvb_limits_nofollow", Path(__file__).resolve().parent / "nofollow.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


nofollow = _nofollow()


def percent(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and 0 <= value <= 100


def problem(data: object) -> str | None:
    """Returns:
        Why data is no limits object (exactly METRICS, each with exactly
        LEVELS, every value a percent from 0 to 100, lower < upper < stop <
        mayday), None when it is one.
    """
    if not isinstance(data, dict) or set(data) != set(METRICS):
        return f"the limits are no object of exactly {', '.join(METRICS)}"
    for metric in METRICS:
        levels = data[metric]
        if not isinstance(levels, dict) or set(levels) != set(LEVELS):
            return f"{metric} holds not exactly {', '.join(LEVELS)}"
        values = [levels[level] for level in LEVELS]
        if not all(percent(value) for value in values):
            return f"{metric} holds a value that is no percent from 0 to 100"
        if not all(low < high for low, high in itertools.pairwise(values)):
            return f"{metric} breaks lower < upper < stop < mayday"
    return None


def parsed(root: Path, path: Path) -> object:
    return json.loads(nofollow.read_text(root, path))


def keep(root: Path, last: Path, data: dict) -> None:
    with contextlib.suppress(*UNREADABLE):
        if parsed(root, last) == data:
            return
    with contextlib.suppress(OSError):
        nofollow.replace(root, last, json.dumps(data, indent=1, sort_keys=True) + "\n", 0o600)


def read(root: Path) -> tuple[dict | None, str | None]:
    """Args:
        root: the council directory.

    Returns:
        (the limits in force, None while the config applies; why NAME was
        refused, None when it was not): NAME when it passes problem(), kept
        as LAST; else LAST while that passes, else None. Without NAME the
        config applies and LAST stays as it is.
    """
    path, last = root / NAME, root / LAST
    if not os.path.lexists(path):
        return None, None
    try:
        data = parsed(root, path)
    except UNREADABLE as error:
        why = f"{path} is unreadable ({error})"
    else:
        why = problem(data)
        if why is None:
            keep(root, last, data)
            return data, None
        why = f"{path} is refused: {why}"
    try:
        kept = parsed(root, last)
    except UNREADABLE:
        kept = None
    if problem(kept) is None:
        return kept, f"{why}; the last valid copy {last} stays in force"
    return None, f"{why}; no valid copy is kept, so the config applies"


def memory_bounds(held: dict, level: str) -> dict[str, float]:
    return {"available": 100 - held["ram"][level], "swap_free": 100 - held["swap"][level], "psi_some": held["psi"][level]}


def applied(cfg: dict, held: dict | None, total_gb: float | None) -> dict:
    """Args:
        cfg: the config.
        held: the limits in force (read()), None for none.
        total_gb: the size of cfg's disk in GB, None when unknown; the disk
            stages then stay the config's.

    Returns:
        cfg itself without limits, else a copy holding them under KEY with
        load_limits cpu_percent and mem_percent, memory_limits warn and stop
        (available, swap_free, psi_some) and thresholds_gb (GB left free at
        each disk level) taken from them; a section cfg lacks or holds as no
        object stays as it is, so the config check still names it.
    """
    if held is None:
        return cfg
    out = {**cfg, KEY: held}
    if isinstance(cfg.get("load_limits"), dict):
        out["load_limits"] = {**cfg["load_limits"], "cpu_percent": held["cpu"]["stop"], "mem_percent": held["ram"]["stop"]}
    memory = cfg.get("memory_limits")
    if isinstance(memory, dict) and all(isinstance(memory.get(stage), dict) for stage in MEMORY_STAGES):
        out["memory_limits"] = {
            **memory, **{stage: {**memory[stage], **memory_bounds(held, level)} for stage, level in MEMORY_STAGES.items()},
        }
    if total_gb is not None and isinstance(cfg.get("thresholds_gb"), dict):
        out["thresholds_gb"] = {
            **cfg["thresholds_gb"],
            **{stage: round(total_gb * (100 - held["disk"][level]) / 100, 1) for stage, level in DISK_STAGES.items()},
        }
    return out
