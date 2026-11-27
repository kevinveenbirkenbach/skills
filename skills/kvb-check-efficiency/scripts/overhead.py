#!/usr/bin/env python3
"""Measure what the skills cost every agent per call: hook latency and output size.

Args:
    --skills: the skills root whose scripts are measured (an installed
        ~/.claude/skills or a repository's skills/).
    --runs: runs per case; the median is printed.
    --case: one case name, repeatable; all cases when left out.
    --flags: the interpreter flags of every case, as the hooks run them.

Returns:
    One line per case: name, median ms, min ms, max ms, median CPU ms of
    the child (steady under load), output bytes, exit code, tab-separated.
    Exit 0; exit 2 on a usage error.
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PYTHON = "/usr/bin/python3"
SESSION = "00000000-0000-0000-0000-0000overhead"
TIMEOUT = 120


def event(name: str, tool: str, command: str) -> bytes:
    data = {"session_id": SESSION, "transcript_path": os.devnull, "cwd": tempfile.gettempdir(), "hook_event_name": name, "tool_name": tool, "tool_input": {"command": command}}
    return json.dumps(data).encode()


def cases(skills: Path, flags: list[str]) -> dict[str, tuple[list[str], bytes]]:
    """Args:
        skills: the skills root.
        flags: the interpreter flags.

    Returns:
        Per case name the argv and the stdin it gets.
    """
    pre = event("PreToolUse", "Bash", "git status")
    post = event("PostToolUse", "Bash", "git status")
    prompt = event("UserPromptSubmit", "", "")

    def script(path: str, *args: str) -> list[str]:
        return [PYTHON, *flags, str(skills / path), *args]

    return {
        "python-empty": ([PYTHON, *flags, "-c", "pass"], b""),
        "pre-bash": (script("kvb-org-organize/scripts/hooks.py", "pre-bash"), pre),
        "post-bash": (script("kvb-org-organize/scripts/hooks.py", "post-bash"), post),
        "radio-tool": (script("kvb-org-radio/scripts/radio.py", "tool"), post),
        "radio-prompt": (script("kvb-org-radio/scripts/radio.py", "hook"), prompt),
        "watch-prompt": (script("kvb-org-organize/scripts/watch.py", "watch"), prompt),
        "radio-show-1d": (script("kvb-org-radio/scripts/radio.py", "show", "--all", "--since", "1d"), b""),
        "rasci-show": (script("kvb-org-rasci/scripts/rasci.py", "show"), b""),
        "council-list": (script("kvb-org-organize/scripts/council.py", "list"), b""),
    }


def cpu() -> float:
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return (usage.ru_utime + usage.ru_stime) * 1000


def measure(argv: list[str], stdin: bytes, runs: int) -> tuple[list[float], list[float], int, int]:
    """Returns:
        (wall milliseconds per run, CPU milliseconds per run, output bytes of
        stdout plus stderr of the last run, its exit code).
    """
    times, spent = [], []
    done = None
    for _ in range(runs):
        start, used = time.perf_counter(), cpu()
        done = subprocess.run(argv, input=stdin, capture_output=True, timeout=TIMEOUT, check=False)
        times.append((time.perf_counter() - start) * 1000)
        spent.append(cpu() - used)
    return times, spent, len(done.stdout) + len(done.stderr), done.returncode


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--skills", type=Path, required=True)
    parser.add_argument("--runs", type=int, required=True)
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--flags", default="-I")
    args = parser.parse_args(argv)
    known = cases(args.skills, args.flags.split())
    unknown = [name for name in args.case if name not in known]
    if unknown or args.runs < 1:
        print(f"overhead: unknown case {', '.join(unknown)} or --runs below 1; cases: {', '.join(known)}", file=sys.stderr)
        return 2
    for name in args.case or list(known):
        times, spent, size, code = measure(*known[name], args.runs)
        print(f"{name}\t{statistics.median(times):.0f}ms\t{min(times):.0f}\t{max(times):.0f}\tcpu={statistics.median(spent):.0f}ms\t{size}B\trc={code}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
