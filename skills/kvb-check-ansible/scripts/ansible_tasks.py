#!/usr/bin/env python3
"""Measure where an Ansible run spends its time: from its log, its controller profiles or a bench.

Subcommands:
    durations: per task name sum and count of the profile_tasks `(h:mm:ss.sss)` durations.
    gaps: per task name sum and count of the wall time between the headers of a log
        whose lines start with an ISO timestamp.
    kinds: per kind (ran, skipped, included, other) count, sum, mean and the buckets
        <0.25, <0.5, <1, <2 and >=2 s.
    kind: per task name sum and count of one --kind.
    task: every occurrence of the task names holding --needle: start line, seconds, kind.
    profile-report: the main and worker profiles of --dir merged, by cumulative and own time.
    bench-carrier: a synthetic JSON fact of exactly --kb KiB written to --out.

Args:
    --log: the Ansible output to read.
    --from, --to: first and last line to read, 1-based and inclusive; the whole log when omitted.
    --top: rows per table; every row when omitted for a log, required for profile-report.
    --json: JSON instead of tab-separated text.
    --source: wall (ISO timestamps) or profile (profile_tasks) for kinds, kind and task;
        wall when a header in range carries a timestamp, else profile, when omitted.
    --kind: ran, skipped, included or other.
    --needle: substring of the task name.
    --dir: profile directory; $ANSIBLE_PROFILE_DIR, else <TMPDIR>/ansible-profile, when omitted.
    --kb: size of the synthetic fact in KiB.
    --out: file the synthetic fact goes to.

Exit codes:
    0 success, 2 usage error or nothing measurable in the range.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path

# Trip-wire: python3 -I keeps the script directory off sys.path, and the subcommands live there.
sys.path.append(str(Path(__file__).resolve().parent))

import ansible_bench
import ansible_log
import ansible_profile
import ansible_tables

Report = tuple[dict, list[str]]


def parsed(args: argparse.Namespace, source: str | None) -> tuple[str, ansible_tables.Found]:
    return ansible_log.tasks(args.log, args.first, args.last, source)


def durations(args: argparse.Namespace) -> Report:
    return ansible_tables.names(*parsed(args, "profile"), args.top)


def gaps(args: argparse.Namespace) -> Report:
    return ansible_tables.names(*parsed(args, "wall"), args.top)


def kinds(args: argparse.Namespace) -> Report:
    return ansible_tables.kind_table(*parsed(args, args.source), args.top)


def kind(args: argparse.Namespace) -> Report:
    source, found = parsed(args, args.source)
    return ansible_tables.names(source, ansible_tables.of_kind(found, args.kind), args.top)


def task(args: argparse.Namespace) -> Report:
    return ansible_tables.occurrences(*parsed(args, args.source), args.needle, args.top)


def profile_report(args: argparse.Namespace) -> Report:
    return ansible_profile.report(args.dir, args.top)


def bench_carrier(args: argparse.Namespace) -> Report:
    return ansible_bench.write(args.kb, args.out)


COMMANDS: dict[str, Callable[[argparse.Namespace], Report]] = {
    "durations": durations,
    "gaps": gaps,
    "kinds": kinds,
    "kind": kind,
    "task": task,
    "profile-report": profile_report,
    "bench-carrier": bench_carrier,
}


def positive(text: str) -> int:
    try:
        number = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r}: expected a whole number") from None
    if number < 1:
        raise argparse.ArgumentTypeError(f"{text!r} is below 1")
    return number


def parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    output = argparse.ArgumentParser(add_help=False)
    output.add_argument("--json", action="store_true")
    log = argparse.ArgumentParser(add_help=False, parents=[output])
    log.add_argument("--log", required=True, type=Path)
    log.add_argument("--from", dest="first", type=positive)
    log.add_argument("--to", dest="last", type=positive)
    log.add_argument("--top", type=positive)
    detect = argparse.ArgumentParser(add_help=False, parents=[log])
    detect.add_argument("--source", choices=ansible_log.SOURCES)
    commands.add_parser("durations", parents=[log])
    commands.add_parser("gaps", parents=[log])
    commands.add_parser("kinds", parents=[detect])
    commands.add_parser("kind", parents=[detect]).add_argument("--kind", required=True, choices=ansible_log.KINDS)
    commands.add_parser("task", parents=[detect]).add_argument("--needle", required=True)
    report = commands.add_parser("profile-report", parents=[output])
    report.add_argument("--dir", type=Path)
    report.add_argument("--top", required=True, type=positive)
    bench = commands.add_parser("bench-carrier", parents=[output])
    bench.add_argument("--kb", required=True, type=positive)
    bench.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    first, last = getattr(args, "first", None), getattr(args, "last", None)
    if first is not None and last is not None and first > last:
        parser.error(f"--from {first} is after --to {last}")
    return args


def main(argv: list[str]) -> int:
    args = parse(argv)
    try:
        report, lines = COMMANDS[args.command](args)
    except (ansible_log.Unmeasurable, OSError) as error:
        print(f"ansible_tasks: {error}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2) if args.json else "\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
