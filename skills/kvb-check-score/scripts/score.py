#!/usr/bin/env python3
"""Fold fix confidence, break risk, efficiency, speed and security into one score and one gate verdict.

Args:
    --fix: fix confidence in percent, 0 to 100.
    --break: break risk in percent, 0 to 100.
    --efficiency: efficiency in percent above 0; `-` when not measured or not
        relevant, `new` when the change has no base. Both count as 100 in the score.
    --speed: speed in percent above 0, `-` or `new` as for --efficiency.
    --security: security in percent, 0 to 100, from security.py of kvb-check-security;
        `~<n>` for a value from a review by hand.
    --critical: count of critical security findings.
    --table: print one markdown table instead of the two lines.
    --commit-table <repo>: the same table, led by the worktree, branch and staged
        diff stat of that repository.
    --commit <sha>: with --commit-table, the diff stat of that commit instead of
        the staged one, plus a commit column.
    --message-block: print the commit message block instead of the two lines, one
        value per line: `🎯 Fix: <f> %`, `💥 Break: <b> %`, `🌱 Efficiency: <e>`,
        `⚡ Speed: <s>`, `🛡️ Security: <n> %`, `💰 Value: <n:n>` with --value only,
        `🏆 Score: <n>`, `🚦 Gate: <verdict>`; values and markers as in line 1.
    --value <n:n|?>: with --table, --commit-table or --message-block, a value after
        the efficiency one (--message-block: after security): the cost:value quotient of
        tokens.py of kvb-check-efficiency, `?` when unknown. It changes neither score nor gate.

Output:
    Line 1: `🎯 fix <f> % · 💥 break <b> % · 🌱 efficiency <e> % · ⚡ speed <s> % ·
        🛡️ security <n> % · 🏆 score <n>`, `–` in place of `<x> %` for `-`, `new` for `new`.
        Score is fix * (100 - break) / 100 * 100 / efficiency * 100 / speed * security / 100,
        capped to 0..100, rounded half up.
    Line 2: the gate verdict, `✅ gate: ...`, `⛔ gate: ...` or `⚠️ gate: ...`.

Exit codes:
    0 gate passed, 1 fix under 90 or break over 5, 2 usage error,
    3 efficiency or speed over 100 or new, or security under 100: ask the operator
    before the commit, 4 a critical security finding: do not commit.
"""

from __future__ import annotations

import argparse
import math
import re
import subprocess
import sys

FIX_MIN = 90
BREAK_MAX = 5
COST_MAX = 100
SAFE = 100
DASH = "-"
NEW = "new"
ESTIMATE = "~"
SCORE_HEADER = ("🎯 Fix", "💥 Break", "🌱 Efficiency", "⚡ Speed", "🛡️ Security", "🏆 Score", "Gate")
COMMIT_HEADER = ("📁 Worktree", "🌿 Branch", "📊 Diff stat")
VALUE_HEADER = "💰 Value"
VALUE_AT = SCORE_HEADER.index("🌱 Efficiency") + 1
UNKNOWN = "?"
QUOTIENT = re.compile(r"\d+(?:\.\d+)?:\d+(?:\.\d+)?")
SHORTSTAT = re.compile(
    r"(\d+) files? changed(?:, (\d+) insertions?\(\+\))?(?:, (\d+) deletions?\(-\))?"
)


def percent(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a number") from None
    if not 0 <= value <= 100:
        raise argparse.ArgumentTypeError(f"{text!r} is outside 0..100")
    return value


def cost(text: str) -> float | str:
    if text in (DASH, NEW):
        return text
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is neither a number, {DASH!r} nor {NEW!r}") from None
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError(f"{text!r} must be a positive number")
    return value


def security(text: str) -> tuple[float, str]:
    mark = ESTIMATE if text.startswith(ESTIMATE) else ""
    return percent(text.removeprefix(ESTIMATE)), mark


def worth(text: str) -> str:
    if text == UNKNOWN or QUOTIENT.fullmatch(text):
        return text
    raise argparse.ArgumentTypeError(f"{text!r} is neither n:n nor {UNKNOWN!r}")


def count(text: str) -> int:
    if not text.isdigit():
        raise argparse.ArgumentTypeError(f"{text!r} is not a count")
    return int(text)


def number(value: float) -> str:
    return f"{value:g}"


def shown(value: float | str) -> str:
    if value == DASH:
        return "–"
    if value == NEW:
        return NEW
    return f"{number(value)} %"


def factor(value: float | str) -> float:
    return 100 / value if isinstance(value, float) else 1.0


def score(args: argparse.Namespace) -> int:
    raw = (
        args.fix * (100 - args.risk) / 100 * factor(args.efficiency) * factor(args.speed)
        * args.security[0] / 100
    )
    return math.floor(min(max(raw, 0.0), 100.0) + 0.5)


def over(name: str, value: float | str) -> str | None:
    if value == NEW:
        return f"{name} {NEW}"
    if isinstance(value, float) and value > COST_MAX:
        return f"{name} {number(value)} % > {COST_MAX}"
    return None


def gate(args: argparse.Namespace) -> tuple[str, str, int]:
    if args.critical > 0:
        return "⛔", "critical security finding: do not commit", 4
    failed = []
    if args.fix < FIX_MIN:
        failed.append(f"fix {number(args.fix)} % < {FIX_MIN}")
    if args.risk > BREAK_MAX:
        failed.append(f"break {number(args.risk)} % > {BREAK_MAX}")
    value, mark = args.security
    unsafe = f"security {mark}{number(value)} % < {SAFE}" if value < SAFE else None
    asks = [text for text in (over("efficiency", args.efficiency), over("speed", args.speed), unsafe) if text]
    ask = f"{', '.join(asks)}: ask the operator before the commit" if asks else ""
    if failed:
        return "⛔", "; ".join(part for part in (", ".join(failed), ask) if part), 1
    if asks:
        return "⚠️", ask, 3
    return "✅", f"{FIX_MIN}/{BREAK_MAX}, efficiency and speed <= {COST_MAX}, security {SAFE} %", 0


def git(repo: str, *args: str) -> str:
    try:
        result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=False)
    except OSError as error:
        print(f"score: git {args[0]} in {repo}: {error}", file=sys.stderr)
        sys.exit(2)
    if result.returncode != 0:
        print(f"score: git {args[0]} in {repo}: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(2)
    return result.stdout.strip()


def diffstat(shortstat: str) -> str:
    match = SHORTSTAT.search(shortstat)
    files, added, removed = (int(g or 0) for g in match.groups()) if match else (0, 0, 0)
    return f"{files} file{'' if files == 1 else 's'} +{added}/-{removed}"


def commit_cells(repo: str, commit: str | None) -> tuple[list[str], list[str]]:
    branch = git(repo, "branch", "--show-current") or f"detached at {git(repo, 'rev-parse', '--short', 'HEAD')}"
    if commit is None:
        stat = git(repo, "diff", "--cached", "--shortstat")
        return list(COMMIT_HEADER), [git(repo, "rev-parse", "--show-toplevel"), branch, diffstat(stat)]
    stat = git(repo, "show", "--shortstat", "--format=", commit)
    return (
        [*COMMIT_HEADER, "🔖 Commit"],
        [git(repo, "rev-parse", "--show-toplevel"), branch, diffstat(stat), git(repo, "rev-parse", "--short", commit)],
    )


def cell(text: str) -> str:
    return text.replace("|", "\\|")


def table(header: list[str], row: list[str]) -> str:
    return "\n".join(
        (
            "| " + " | ".join(header) + " |",
            "|" + " --- |" * len(header),
            "| " + " | ".join(cell(value) for value in row) + " |",
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fix", type=percent, required=True)
    parser.add_argument("--break", dest="risk", type=percent, required=True)
    parser.add_argument("--efficiency", type=cost, required=True)
    parser.add_argument("--speed", type=cost, required=True)
    parser.add_argument("--security", type=security, required=True)
    parser.add_argument("--critical", type=count, required=True)
    layout = parser.add_mutually_exclusive_group()
    layout.add_argument("--table", action="store_true")
    layout.add_argument("--commit-table", metavar="REPO")
    layout.add_argument("--message-block", action="store_true")
    parser.add_argument("--commit", metavar="SHA")
    parser.add_argument("--value", type=worth)
    args = parser.parse_args()
    if args.commit and not args.commit_table:
        parser.error("--commit needs --commit-table")
    if args.value and not (args.table or args.commit_table or args.message_block):
        parser.error("--value needs --table, --commit-table or --message-block")

    total = score(args)
    emoji, verdict, code = gate(args)
    value, mark = args.security
    values = [
        f"{number(args.fix)} %", f"{number(args.risk)} %", shown(args.efficiency), shown(args.speed),
        f"{mark}{number(value)} %", str(total), f"{emoji} {verdict}",
    ]
    header, row = list(SCORE_HEADER), list(values)
    if args.value:
        header.insert(VALUE_AT, VALUE_HEADER)
        row.insert(VALUE_AT, args.value)
    if args.commit_table:
        lead, cells = commit_cells(args.commit_table, args.commit)
        print(table([*lead, *header], [*cells, *row]))
    elif args.table:
        print(table(header, row))
    elif args.message_block:
        worth_line = [f"💰 Value: {args.value}"] if args.value else []
        print("\n".join((
            f"🎯 Fix: {values[0]}", f"💥 Break: {values[1]}", f"🌱 Efficiency: {values[2]}",
            f"⚡ Speed: {values[3]}", f"🛡️ Security: {values[4]}", *worth_line,
            f"🏆 Score: {total}", f"🚦 Gate: {values[6]}",
        )))
    else:
        print(
            f"🎯 fix {values[0]} · 💥 break {values[1]} · 🌱 efficiency {values[2]} · "
            f"⚡ speed {values[3]} · 🛡️ security {values[4]} · 🏆 score {total}"
        )
        print(f"{emoji} gate: {verdict}")
    return code


if __name__ == "__main__":
    sys.exit(main())
