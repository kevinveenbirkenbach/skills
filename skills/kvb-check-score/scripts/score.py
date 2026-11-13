#!/usr/bin/env python3
"""Fold fix confidence, break risk, tokens, velocity and security into one score and one gate verdict.

Args:
    --fix: fix confidence in percent, 0 to 100.
    --break: break risk in percent, 0 to 100.
    --efficiency: tokens in percent above 0, from kvb-check-efficiency; `-` when not
        measured or not relevant, `new` when the change has no base. Both count as 100
        in the score.
    --speed: velocity in percent above 0, from kvb-check-speed; `-` or `new` as for
        --efficiency.
    --security: security in percent, 0 to 100, from security.py of kvb-check-security;
        `~<n>` for a value from a review by hand.
    --critical: count of critical security findings.
    --table: print one markdown table instead of the two lines.
    --commit-table <repo>: the same table, led by the branch and staged diff stat of
        that repository, then a blank line, `📁 Worktree:` and the top level path
        alone in a ```text block, so it copies in one go.
    --commit <sha>: with --commit-table, the diff stat of that commit instead of
        the staged one, plus a commit column.
    --message-block: print the commit message block instead of the two lines, one
        value per line: `🎯 Fix: <f> %`, `💥 Break: <b> %`, `💸 Tokens: <c>`,
        `⏱️ Velocity: <t>`, `🛡️ Security: <n> %`, `💰 Value: <n:n>` with --value only,
        `🏆 Score: <n>`, `🚦 Gate: <verdict>`; values and markers as in line 1. Each
        render appends one row to the score journal of journal.py; a failed append
        prints one stderr line and keeps the exit code.
    --value <n:n|?>: with --table, --commit-table or --message-block, a value after
        the tokens one (--message-block: after security): the cost:value quotient of
        tokens.py of kvb-check-efficiency, `?` when unknown. It changes neither score nor gate.

Labels and emojis come from ../labels.json.

Output:
    Line 1: `🎯 fix <f> % · 💥 break <b> % · 💸 tokens <c> % · ⏱️ velocity <t> % ·
        🛡️ security <n> % · 🏆 score <n>`, `–` in place of `<x> %` for `-`, `new` for `new`.
        Score is fix * (100 - break) / 100 * 100 / tokens * 100 / velocity * security / 100,
        capped to 0..100, rounded half up.
    Line 2: the gate verdict, `✅ gate: ...`, `⛔ gate: ...` or `⚠️ gate: ...`.

Exit codes:
    0 gate passed, 1 fix under 90 or break over 5, 2 usage error, a malformed
    labels.json or a --commit-table repository git cannot read, one stderr line
    and nothing on stdout (4 still wins with a critical finding), 3 tokens or
    velocity over 100 or new, or security under 100: ask the operator before the
    commit, 4 a critical security finding: do not commit.
"""

from __future__ import annotations

import argparse
import math
import re
import sys
import time
from pathlib import Path

from journal import (
    LABELS,
    append,
    entry,
    git,
    git_read,
    journal_path,
    load_labels,
    origin,
)

FIX_MIN = 90
BREAK_MAX = 5
COST_MAX = 100
SAFE = 100
DASH = "-"
NEW = "new"
ESTIMATE = "~"
COMMIT_HEADER = ("🌿 Branch", "📊 Diff stat")
WORKTREE = "📁 Worktree:"
UNKNOWN = "?"
LABEL_ERRORS = (OSError, ValueError, LookupError, TypeError, AttributeError)
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


def labels(keys: set[str]) -> tuple[dict, dict]:
    """Args:
        keys: the metric keys score.py measures.

    Returns:
        (metrics, extras) of labels.json; ValueError when it lacks one of the
        keys, holds another or an entry has no string emoji and label.
    """
    found = load_labels(LABELS)
    metrics, extras = found["metrics"], found["extras"]
    named = [*metrics.values(), extras["value"], extras["gate"]]
    if set(metrics) != keys or not all(isinstance(item["emoji"], str) and isinstance(item["label"], str) for item in named):
        raise ValueError(f"needs a string emoji and label for {', '.join(sorted(keys))}, value and gate")
    return metrics, extras


def gate(args: argparse.Namespace, metrics: dict) -> tuple[str, str, int]:
    def word(key: str) -> str:
        return metrics[key]["label"].lower()

    if args.critical > 0:
        return "⛔", f"critical {word('security')} finding: do not commit", 4
    failed = []
    if args.fix < FIX_MIN:
        failed.append(f"{word('fix')} {number(args.fix)} % < {FIX_MIN}")
    if args.risk > BREAK_MAX:
        failed.append(f"{word('break')} {number(args.risk)} % > {BREAK_MAX}")
    value, mark = args.security
    unsafe = f"{word('security')} {mark}{number(value)} % < {SAFE}" if value < SAFE else None
    asks = [text for text in (over(word("tokens"), args.efficiency), over(word("velocity"), args.speed), unsafe) if text]
    ask = f"{', '.join(asks)}: ask the operator before the commit" if asks else ""
    if failed:
        return "⛔", "; ".join(part for part in (", ".join(failed), ask) if part), 1
    if asks:
        return "⚠️", ask, 3
    return "✅", f"{FIX_MIN}/{BREAK_MAX}, {word('tokens')} and {word('velocity')} <= {COST_MAX}, {word('security')} {SAFE} %", 0


def diffstat(shortstat: str) -> str:
    match = SHORTSTAT.search(shortstat)
    files, added, removed = (int(g or 0) for g in match.groups()) if match else (0, 0, 0)
    return f"{files} file{'' if files == 1 else 's'} +{added}/-{removed}"


def commit_cells(repo: str, commit: str | None) -> tuple[list[str], list[str]]:
    branch = git(repo, "branch", "--show-current") or f"detached at {git(repo, 'rev-parse', '--short', 'HEAD')}"
    if commit is None:
        return list(COMMIT_HEADER), [branch, diffstat(git(repo, "diff", "--cached", "--shortstat"))]
    stat = git(repo, "show", "--shortstat", "--format=", commit)
    return [*COMMIT_HEADER, "🔖 Commit"], [branch, diffstat(stat), git(repo, "rev-parse", "--short", commit)]


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
    value, mark = args.security
    measured = {
        "fix": f"{number(args.fix)} %", "break": f"{number(args.risk)} %", "tokens": shown(args.efficiency),
        "velocity": shown(args.speed), "security": f"{mark}{number(value)} %", "score": str(total),
    }
    try:
        metrics, extras = labels(set(measured))
    except LABEL_ERRORS as error:
        print(f"score: labels {LABELS}: {error!r}", file=sys.stderr)
        return 4 if args.critical > 0 else 2
    emoji, verdict, code = gate(args, metrics)
    verdict_cell = f"{emoji} {verdict}"
    value_header = f"{extras['value']['emoji']} {extras['value']['label']}"
    header = [*(f"{metric['emoji']} {metric['label']}" for metric in metrics.values()), extras["gate"]["label"]]
    row = [*(measured[key] for key in metrics), verdict_cell]
    if args.value:
        header.insert(list(metrics).index("tokens") + 1, value_header)
        row.insert(list(metrics).index("tokens") + 1, args.value)
    if args.commit_table:
        try:
            lead, cells = commit_cells(args.commit_table, args.commit)
            top = git(args.commit_table, "rev-parse", "--show-toplevel")
        except LookupError as error:
            print(f"score: {error}", file=sys.stderr)
            return 4 if code == 4 else 2
        print(table([*lead, *header], [*cells, *row]))
        print(f"\n{WORKTREE}\n\n```text\n{top}\n```")
    elif args.table:
        print(table(header, row))
    elif args.message_block:
        lines = [f"{metric['emoji']} {metric['label']}: {measured[key]}" for key, metric in metrics.items()]
        if args.value:
            lines.insert(list(metrics).index("score"), f"{value_header}: {args.value}")
        gate_label = extras["gate"]
        block = "\n".join((*lines, f"{gate_label['emoji']} {gate_label['label']}: {verdict_cell}"))
        print(block, flush=True)
        journal(args, total, block)
    else:
        print(" · ".join(f"{metric['emoji']} {metric['label'].lower()} {measured[key]}" for key, metric in metrics.items()))
        print(f"{emoji} gate: {verdict}")
    return code


def plain(value: float | str) -> float | int | None:
    if not isinstance(value, float):
        return None
    return int(value) if value.is_integer() else value


def journal(args: argparse.Namespace, total: int, block: str) -> None:
    values = {
        "fix": plain(args.fix), "break": plain(args.risk), "tokens": plain(args.efficiency),
        "velocity": plain(args.speed), "security": plain(args.security[0]), "score": total,
    }
    path = journal_path()
    try:
        here = Path.cwd()
        append(path, [entry(int(time.time()), origin(here), git_read(here, "branch", "--show-current") or None, None, values, block)])
    except (OSError, ValueError) as error:
        print(f"score: journal {path}: {getattr(error, 'strerror', None) or error}", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
