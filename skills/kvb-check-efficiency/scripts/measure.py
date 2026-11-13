#!/usr/bin/env python3
"""Measure a command's CPU seconds, peak RAM and wall time on a base ref and on the working tree.

Args:
    --base: git ref to compare with; checked out as a detached worktree under /tmp
        and removed again, whatever happens.
    --json: print the figures as JSON instead of the line.
    -- <command...>: the command, run without a shell from the same directory
        relative to each tree's root; its output is discarded.

Runs:
    One run per tree, base first. When tokens and velocity are both at most 100 that
    is the result; otherwise 4 more runs per tree, alternating, and the arithmetic mean
    of all 5 per tree counts.

Other load:
    A 1 s /proc/stat sample of system CPU busy before and after the runs, and per run
    the busy jiffies minus the command's own CPU time, as a share of all jiffies. When
    any share exceeds 30 % or cannot be read, the result is an estimate: velocity comes
    from the CPU-time ratio instead of wall time.

Output:
    `💸 tokens <p> % (cpu <b>→<a> s, ram <b>→<a> MB) · ⏱️ velocity <p> % (wall <b>→<a> s)`,
    then ` · mean of 5` after the extra runs. An estimate marks both values with `~`,
    shows `(cpu <b>→<a> s)` for velocity and ends in `(estimated: other load <x> %)`, or
    `unknown` for <x>. Tokens is the mean of the CPU ratio (user plus system seconds
    of the command and its waited-for children) and the peak RSS ratio; each ratio is
    working tree over base, times 100.

Exit codes:
    0 tokens and velocity at most 100, 2 usage error or a failing command
    (its tree, exit code and last stderr line on stderr), 3 either over 100.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

WORKTREE_PARENT = "/tmp"
LIMIT = 100
LOAD_LIMIT = 30
SAMPLE_SECONDS = 1
MORE_RUNS = 4
RESOLUTION = 0.001
PROC_STAT = Path("/proc/stat")
CLOCK_TICKS = os.sysconf("SC_CLK_TCK")
# Trip-wire: ru_maxrss counts kilobytes on Linux but bytes on macOS.
RSS_UNIT = 1 if sys.platform == "darwin" else 1024
USAGE = "usage: measure.py --base <ref> [--json] -- <command...>"
LABELS = Path(__file__).resolve().parents[2] / "kvb-check-score" / "labels.json"
LABEL_ERRORS = (OSError, ValueError, LookupError, TypeError)


def labelled(keys: tuple[str, ...]) -> dict[str, str]:
    """Args:
        keys: metric keys of kvb-check-score's labels.json.

    Returns:
        Per key `<emoji> <label>`, the label in lower case; one of LABEL_ERRORS
        for a missing or malformed file.
    """
    metrics = json.loads(LABELS.read_text(encoding="utf-8"))["metrics"]
    found = {key: (metrics[key]["emoji"], metrics[key]["label"]) for key in keys}
    if not all(isinstance(part, str) for pair in found.values() for part in pair):
        raise ValueError(f"needs a string emoji and label for {', '.join(keys)}")
    return {key: f"{emoji} {label.lower()}" for key, (emoji, label) in found.items()}


def fail(message: str) -> None:
    print(f"measure: {message}", file=sys.stderr)
    sys.exit(2)


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        fail(result.stderr.strip() or f"git {args[0]} failed in {cwd}")
    return result.stdout.strip()


def cpu_ticks() -> tuple[int, int] | None:
    try:
        fields = [int(v) for v in PROC_STAT.read_text(encoding="ascii").split("\n", 1)[0].split()[1:9]]
    except (OSError, ValueError):
        return None
    if len(fields) < 8:
        return None
    return sum(fields) - fields[3] - fields[4], sum(fields)


def share(before: tuple[int, int] | None, after: tuple[int, int] | None, own: float) -> float | None:
    if before is None or after is None:
        return None
    total = after[1] - before[1]
    return max(0.0, (after[0] - before[0] - own) / total * 100) if total > 0 else 0.0


def idle_load() -> float | None:
    before = cpu_ticks()
    time.sleep(SAMPLE_SECONDS)
    return share(before, cpu_ticks(), 0.0)


def sample(command: list[str], cwd: Path, tree: str) -> dict[str, float | None]:
    with tempfile.TemporaryFile() as err:
        ticks = cpu_ticks()
        started = time.perf_counter()
        try:
            child = subprocess.Popen(
                command, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=err
            )
        except OSError as error:
            fail(f"{tree} tree {cwd}: {error}")
        # Trip-wire: Popen.wait() discards the child's rusage, so wait4 reaps it and returncode is set by hand.
        _, status, usage = os.wait4(child.pid, 0)
        wall = time.perf_counter() - started
        cpu = usage.ru_utime + usage.ru_stime
        load = share(ticks, cpu_ticks(), cpu * CLOCK_TICKS)
        child.returncode = os.waitstatus_to_exitcode(status)
        if child.returncode != 0:
            err.seek(0)
            lines = err.read().decode(errors="replace").strip().splitlines()
            fail(f"command exited {child.returncode} in the {tree} tree {cwd}: {lines[-1] if lines else ''}")
    return {"cpu": cpu, "ram": usage.ru_maxrss * RSS_UNIT / 2**20, "wall": wall, "load": load}


def ratio(after: float, before: float) -> float:
    return max(after, RESOLUTION) / max(before, RESOLUTION)


def figures(runs: dict[str, list[dict]], loads: list[float | None]) -> dict:
    before, after = (
        {key: statistics.fmean(s[key] for s in runs[tree]) for key in ("cpu", "ram", "wall")}
        for tree in ("base", "head")
    )
    unknown = None in loads
    estimated = unknown or max(loads) > LOAD_LIMIT
    basis = "cpu" if estimated else "wall"
    return {
        "efficiency": round((ratio(after["cpu"], before["cpu"]) + ratio(after["ram"], before["ram"])) / 2 * 100),
        "speed": round(ratio(after[basis], before[basis]) * 100),
        "runs": len(runs["head"]),
        "estimated": estimated,
        "other_load": None if unknown else round(max(loads)),
        "base": before,
        "head": after,
    }


def line(found: dict, names: dict[str, str]) -> str:
    mark = "~" if found["estimated"] else ""
    basis = "cpu" if found["estimated"] else "wall"
    before, after = found["base"], found["head"]
    text = (
        f"{names['tokens']} {mark}{found['efficiency']} % (cpu {before['cpu']:.2f}→{after['cpu']:.2f} s, "
        f"ram {before['ram']:.1f}→{after['ram']:.1f} MB) · "
        f"{names['velocity']} {mark}{found['speed']} % ({basis} {before[basis]:.2f}→{after[basis]:.2f} s)"
    )
    if found["runs"] > 1:
        text += f" · mean of {found['runs']}"
    if found["estimated"]:
        other = "unknown" if found["other_load"] is None else f"{found['other_load']} %"
        text += f" (estimated: other load {other})"
    return text


def run_loads(runs: dict[str, list[dict]]) -> list[float | None]:
    return [s["load"] for s in runs["base"] + runs["head"]]


def costly(found: dict) -> bool:
    return found["efficiency"] > LIMIT or found["speed"] > LIMIT


def main(argv: list[str]) -> int:
    if "--" not in argv:
        fail(USAGE)
    split = argv.index("--")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0], usage=USAGE)
    parser.add_argument("--base", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv[:split])
    command = argv[split + 1:]
    if not command:
        fail("no command after --")
    try:
        names = {} if args.json else labelled(("tokens", "velocity"))
    except LABEL_ERRORS as error:
        fail(f"labels {LABELS}: {error!r}")

    here = Path.cwd().resolve()
    root = Path(git(here, "rev-parse", "--show-toplevel")).resolve()
    relative = here.relative_to(root)
    resolved = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"{args.base}^{{commit}}"],
        cwd=root, capture_output=True, text=True, check=False,
    )
    if resolved.returncode != 0:
        fail(f"unknown ref {args.base!r}")

    parent = Path(tempfile.mkdtemp(prefix="kvb-measure-", dir=WORKTREE_PARENT))
    tree = parent / "base"
    runs: dict[str, list[dict]] = {"base": [], "head": []}
    try:
        git(root, "worktree", "add", "--detach", str(tree), resolved.stdout.strip())
        base_cwd = tree / relative
        if not base_cwd.is_dir():
            fail(f"{relative} does not exist at {args.base}")
        loads = [idle_load()]
        for count in range(1 + MORE_RUNS):
            runs["base"].append(sample(command, base_cwd, "base"))
            runs["head"].append(sample(command, here, "head"))
            if count == 0 and not costly(figures(runs, loads + run_loads(runs))):
                break
        loads.append(idle_load())
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(tree)], cwd=root, capture_output=True, check=False)
        shutil.rmtree(parent, ignore_errors=True)

    found = figures(runs, loads + run_loads(runs))
    print(json.dumps(found) if args.json else line(found, names))
    return 3 if costly(found) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
