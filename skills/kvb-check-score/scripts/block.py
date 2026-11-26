#!/usr/bin/env python3
"""Measure a staged bundle with every scoring script and print its commit table and message block.

Args:
    --repo: the worktree of the commit.
    --base: git ref the change starts from, HEAD for staged work.
    --fix: fix confidence in percent, from kvb-check-confidence.
    --break: break risk in percent, from kvb-check-break-risk.
    --transcripts: transcripts root for tokens.py of kvb-check-efficiency, given
        when skill text changed: it adds 💸 tokens and 💰 value.
    --saves: tokens per day the change saves, tokens.py's --value; needs
        --evidence and --transcripts.
    --evidence: the line that derives --saves.
    -- <command...>: the targeted tests or a CLI call of the changed code for
        measure.py of kvb-check-efficiency, run from the current directory: it
        adds 💸 tokens and ⏱️ velocity. With --transcripts too, the higher
        tokens figure counts.

Runs:
    tokens.py and measure.py as given, security.py --repo --base of
    kvb-check-security and gate.py status --repo of kvb-check-gate, then
    score.py of this skill with --commit-table and with --message-block.
    Without --transcripts and a command, tokens and velocity are `-`.

Output:
    score.py's commit table, the verdict line of gate.py status and score.py's
    message block, each after a blank line, then `after the commit:` with the
    score.py call that prints the table of the commit, `<hash>` to fill in.

Exit codes:
    score.py's: 0 pass, 1 below 90/5, 3 ask the operator again, 4 a critical
    finding. 2 usage error, or a script that failed or printed no figure,
    named on stderr with its exit code and last output line.
"""

from __future__ import annotations

import argparse
import re
import shlex
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from score import DASH, NEW, UNKNOWN, percent

SKILLS = HERE.parents[1]
SCORE = HERE / "score.py"
TOKENS = SKILLS / "kvb-check-efficiency" / "scripts" / "tokens.py"
MEASURE = SKILLS / "kvb-check-efficiency" / "scripts" / "measure.py"
SECURITY = SKILLS / "kvb-check-security" / "scripts" / "security.py"
GATE = SKILLS / "kvb-check-gate" / "scripts" / "gate.py"
FIGURE = re.compile(r"\b(new)\b|~?(\d+(?:\.\d+)?) %")
PERCENT = re.compile(r"~?(\d+(?:\.\d+)?) %")
VALUE = re.compile(r"value (\d+(?:\.\d+)?:\d+(?:\.\d+)?|\?:\?)")
SAFETY = re.compile(r"(\d+(?:\.\d+)?) % critical (\d+)")
VERDICT = "gate: "
UNPRICED = "?:?"


def last_line(*texts: str) -> str:
    for text in texts:
        lines = text.strip().splitlines()
        if lines:
            return lines[-1]
    return "no output"


def run(script: Path, args: list[str], accepted: set[int]) -> str:
    """Args:
        script: the scoring script.
        args: its arguments.
        accepted: the exit codes that carry a result.

    Returns:
        Its stdout; LookupError naming the script, its exit code and last
        output line on any other exit code.
    """
    done = subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True, check=False)
    if done.returncode not in accepted:
        raise LookupError(f"{script.name} exited {done.returncode}: {last_line(done.stderr, done.stdout)}")
    return done.stdout


def match(pattern: re.Pattern, text: str, script: Path) -> re.Match:
    found = pattern.search(text)
    if not found:
        raise LookupError(f"{script.name} printed no figure: {last_line(text)}")
    return found


def tokens(args: argparse.Namespace) -> tuple[str, str]:
    command = ["--repo", args.repo, "--base", args.base, "--transcripts", args.transcripts]
    if args.saves:
        command += ["--value", args.saves, "--evidence", args.evidence]
    out = run(TOKENS, command, {0, 3})
    figure = match(FIGURE, out, TOKENS)
    quotient = match(VALUE, out, TOKENS).group(1)
    return figure.group(2) or NEW, UNKNOWN if quotient == UNPRICED else quotient


def measured(command: list[str], base: str) -> tuple[str, str]:
    out = run(MEASURE, ["--base", base, "--", *command], {0, 3})
    figures = PERCENT.findall(out)
    if len(figures) < 2:
        raise LookupError(f"{MEASURE.name} printed no figure: {last_line(out)}")
    return figures[0], figures[1]


def worse(first: str, second: str) -> str:
    if NEW in (first, second):
        return NEW
    if DASH in (first, second):
        return second if first == DASH else first
    return max(first, second, key=float)


def figures(args: argparse.Namespace) -> list[str]:
    """Args:
        args: the parsed arguments and the measure.py command.

    Returns:
        The score.py arguments from --fix through --critical, and --value
        when tokens.py ran.
    """
    efficiency, speed, value = DASH, DASH, None
    if args.transcripts:
        efficiency, value = tokens(args)
    if args.command:
        cost, speed = measured(args.command, args.base)
        efficiency = worse(efficiency, cost)
    safety = match(SAFETY, run(SECURITY, ["--repo", args.repo, "--base", args.base], {0, 1, 3}), SECURITY)
    values = [
        "--fix", f"{args.fix:g}", "--break", f"{args.risk:g}", "--efficiency", efficiency, "--speed", speed,
        "--security", safety.group(1), "--critical", safety.group(2),
    ]
    return values + (["--value", value] if value else [])


def verdict(repo: str) -> str:
    lines = [line for line in run(GATE, ["status", "--repo", repo], {0, 1}).splitlines() if line.startswith(VERDICT)]
    if not lines:
        raise LookupError(f"{GATE.name} printed no verdict")
    return lines[-1]


def score(values: list[str], *layout: str) -> int:
    return subprocess.run([sys.executable, str(SCORE), *values, *layout], check=False).returncode


def parse(argv: list[str]) -> argparse.Namespace:
    split = argv.index("--") if "--" in argv else len(argv)
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--fix", type=percent, required=True)
    parser.add_argument("--break", dest="risk", type=percent, required=True)
    parser.add_argument("--transcripts")
    parser.add_argument("--saves")
    parser.add_argument("--evidence")
    args = parser.parse_args(argv[:split])
    args.command = argv[split + 1:]
    if bool(args.saves) != bool(args.evidence) or (args.saves and not args.transcripts):
        parser.error("--saves needs --evidence and --transcripts")
    return args


def main() -> int:
    args = parse(sys.argv[1:])
    try:
        values = figures(args)
        gate = verdict(args.repo)
    except LookupError as error:
        print(f"block: {error}", file=sys.stderr)
        return 2
    if score(values, "--commit-table", args.repo) == 2:
        return 2
    print(f"\n{gate}\n", flush=True)
    code = score(values, "--message-block")
    print(f"\nafter the commit: {shlex.join(['python3', str(SCORE), *values, '--commit-table', args.repo])} --commit <hash>")
    return code


if __name__ == "__main__":
    sys.exit(main())
