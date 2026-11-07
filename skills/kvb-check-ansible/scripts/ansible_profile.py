"""Merge the main and worker cProfile files of an ansible-playbook run.

Args:
    directory: profile directory; the default of profile/sitecustomize.py when None.
    top: functions per ranking.

Output:
    A (report, lines) pair: per role (main, worker) the profile count, own seconds and the
    top functions by cumulative and by own time. Unmeasurable when the directory holds no
    profile or an unreadable one.
"""

from __future__ import annotations

import importlib.util
import pstats
from pathlib import Path

import ansible_log

PROFILER = Path(__file__).resolve().parent / "profile" / "sitecustomize.py"
ROLES = ("main", "worker")
TOTAL_TIME = 2
CUMULATIVE_TIME = 3


def default_dir() -> Path:
    spec = importlib.util.spec_from_file_location("ansible_profile_site", PROFILER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return Path(module.profile_dir())


def hottest(stats: pstats.Stats, field: int, top: int) -> list[dict]:
    rows = sorted(stats.stats.items(), key=lambda item: -item[1][field])[:top]
    return [
        {"function": pstats.func_std_string(func), "calls": calls, "tottime": round(own, 6), "cumtime": round(cumulative, 6)}
        for func, (_, calls, own, cumulative, _) in rows
    ]


def merged(directory: Path, top: int) -> dict[str, dict]:
    roles: dict[str, dict] = {}
    for role in ROLES:
        files = sorted(directory.glob(f"{role}-*.prof"))
        if not files:
            continue
        try:
            stats = pstats.Stats(*(str(file) for file in files))
        except (EOFError, TypeError, ValueError) as error:
            raise ansible_log.Unmeasurable(f"unreadable profile in {directory}: {error}") from None
        roles[role] = {
            "profiles": len(files),
            "seconds": round(stats.total_tt, 3),
            "cumulative": hottest(stats, CUMULATIVE_TIME, top),
            "tottime": hottest(stats, TOTAL_TIME, top),
        }
    if not roles:
        raise ansible_log.Unmeasurable(f"no main-*.prof or worker-*.prof in {directory}")
    return roles


def report(directory: Path | None, top: int) -> tuple[dict, list[str]]:
    chosen = default_dir() if directory is None else directory
    roles = merged(chosen, top)
    lines: list[str] = []
    for role, found in roles.items():
        lines.append(f"== {role}: {found['profiles']} profiles, {found['seconds']:.3f} s ==")
        for order in ("cumulative", "tottime"):
            lines.append(f"-- {order}: cumtime, tottime, calls, function --")
            lines += [
                f"{row['cumtime']:.3f}\t{row['tottime']:.3f}\t{row['calls']}\t{row['function']}" for row in found[order]
            ]
    return {"dir": str(chosen), **roles}, lines
