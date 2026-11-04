#!/usr/bin/env python3
"""Compare the estimated tokens of changed skill text files, and the listing words, with a base ref, and weigh their daily cost against their value.

Args:
    --repo: skills repository root; its scripts/budget.py counts the listing.
    --base: git ref the change starts from; the working tree is the after side.
    --transcripts: Claude Code transcripts root, e.g. ~/.claude/projects; every */*.jsonl of the
        last 7 days gives the requests (unique assistant message ids) and the invocations per skill
        (unique Skill tool_use ids, a `<scope>:` prefix stripped). Read only; no text is printed.
    --value: tokens per day the change saves; needs --evidence.
    --evidence: one line that derives --value.
    --json: print the figures as JSON instead of the lines.

    value --repo <root> --since <commit> --transcripts <root> [--json]: measure the value of a
        shipped change instead.

Output:
    Line 1: `🌱 efficiency <p> % (skills <b>→<a> tokens; listing <b>→<a> words)`, p = after / before * 100,
    or `🌱 efficiency new (+<a> tokens; listing <b>→<a> words)` when the changed files hold no
    base tokens. Changed files are the *.md under skills/ that `git diff <ref>` names plus untracked
    ones; a file missing on a side counts 0. Tokens are an estimate: characters / 4. The listing
    is the sum of every skills/*/SKILL.md description word.
    Line 2: `💰 value 1:<n> (cost <c>/day, value <v>/day; <evidence>)` when the value is at least
    the cost, `<n>:1` below it, `0:1` without a cost, `1:0` without a value; without --value
    `💰 value ?:? (cost <c>/day; pass --value with evidence)`. Cost per day = listing words delta
    * 1.33 tokens * requests per day * 0.1 (cached) + per changed SKILL.md its tokens delta * the
    skill's invocations per day. A skill without a base SKILL.md takes the median invocations of
    its category's base skills (the name up to its second dash; all base skills when it has
    none), and the line names it.
    --json prints efficiency (null when new), the skills and listing totals, the tokens per skill
    and the value figures.
    value: `💰 measured value <v>/day (median daily context <b>→<a> tokens over <n> active days
    before and <m> after <sha> of <day>)`: the context tokens per UTC day as context.py of
    kvb-skill-silence sums them, days without a turn left out, over the 7 days before the
    commit's day and the up to 7 full days after it; v = b - a.

Exit codes:
    0 efficiency at most 100, 2 usage error, 3 over 100 or new; the value line never changes it.
    value: 0 measured, 2 usage error or no active day on a side.
"""

from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import math
import statistics
import subprocess
import sys
from pathlib import Path, PurePosixPath
from types import ModuleType

CHARS_PER_TOKEN = 4
LIMIT = 100
SKILLS = "skills"
TOKENS_PER_WORD = 1.33
CACHE_FACTOR = 0.1
DAYS = 7
ROUND_ABOVE = 10
ALL_SKILLS = "all skills"
CONTEXT = Path(__file__).resolve().parents[2] / "kvb-skill-silence" / "scripts" / "context.py"


def fail(message: str) -> None:
    print(f"tokens: {message}", file=sys.stderr)
    sys.exit(2)


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, check=False)


def paths(repo: Path, *args: str) -> list[str]:
    result = git(repo, *args)
    if result.returncode != 0:
        fail(result.stderr.decode(errors="replace").strip())
    return [p for p in result.stdout.decode().split("\0") if p]


def load(path: Path, name: str, role: str) -> ModuleType:
    if not path.is_file():
        fail(f"{path} is missing; it {role}")
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def at_base(repo: Path, ref: str, path: str) -> str:
    result = git(repo, "show", f"{ref}:{path}")
    return result.stdout.decode(errors="replace") if result.returncode == 0 else ""


def in_tree(repo: Path, path: str) -> str:
    file = repo / path
    return file.read_text(encoding="utf-8", errors="replace") if file.is_file() else ""


def tokens(chars: int) -> int:
    return round(chars / CHARS_PER_TOKEN)


def is_skill_md(path: str) -> bool:
    parts = PurePosixPath(path).parts
    return len(parts) == 3 and parts[0] == SKILLS and parts[2] == "SKILL.md"


def category(skill: str) -> str:
    return "-".join(skill.split("-")[:2])


def figure(amount: float) -> str:
    if abs(amount) >= ROUND_ABOVE:
        return str(round(amount))
    return f"{round(amount, 1) + 0.0:g}"


def quotient(cost: float, value: float) -> str:
    if cost <= 0:
        return "0:1" if value > 0 else "0:0"
    if value <= 0:
        return "1:0"
    if value >= cost:
        return f"1:{figure(value / cost)}"
    return f"{figure(cost / value)}:1"


def amount(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a number") from None
    if not math.isfinite(value):
        raise argparse.ArgumentTypeError(f"{text!r} is not finite")
    return value


def directory(text: str) -> Path:
    root = Path(text).expanduser()
    if not root.is_dir():
        fail(f"{root} is not a directory")
    return root


def skill_uses(message: dict) -> list[tuple[str, str]]:
    content = message.get("content")
    found = []
    for block in content if isinstance(content, list) else []:
        if not isinstance(block, dict) or block.get("type") != "tool_use" or block.get("name") != "Skill":
            continue
        given = block.get("input")
        skill = given.get("skill") if isinstance(given, dict) else None
        if isinstance(skill, str) and block.get("id"):
            found.append((skill.rpartition(":")[2], str(block["id"])))
    return found


def usage(root: Path, since: float) -> tuple[int, dict[str, int]]:
    requests: set[str] = set()
    invocations: dict[str, set[str]] = {}
    for path in root.glob("*/*.jsonl"):
        if path.stat().st_mtime < since:
            continue
        with path.open(encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                if '"assistant"' not in line:
                    continue
                try:
                    entry = json.loads(line)
                    stamp = datetime.datetime.fromisoformat(entry["timestamp"]).timestamp()
                except (ValueError, KeyError, TypeError):
                    continue
                message = entry.get("message")
                if entry.get("type") != "assistant" or stamp < since or not isinstance(message, dict):
                    continue
                if message.get("id"):
                    requests.add(str(message["id"]))
                for skill, use in skill_uses(message):
                    invocations.setdefault(skill, set()).add(use)
    return len(requests), {skill: len(uses) for skill, uses in invocations.items()}


def weigh(root: Path, listing_delta: int, body: dict[str, int], new: set[str], base_skills: list[str]) -> dict:
    requests, invocations = usage(root, datetime.datetime.now(datetime.UTC).timestamp() - DAYS * 86400)
    per_day = {skill: count / DAYS for skill, count in invocations.items()}
    rates, assumed = {}, {}
    for skill in body:
        if skill in new:
            peers = [peer for peer in base_skills if category(peer) == category(skill)]
            assumed[skill] = category(skill) if peers else ALL_SKILLS
            pool = [per_day.get(peer, 0.0) for peer in peers or base_skills]
            rates[skill] = statistics.median(pool) if pool else 0.0
        else:
            rates[skill] = per_day.get(skill, 0.0)
    listing = listing_delta * TOKENS_PER_WORD * (requests / DAYS) * CACHE_FACTOR
    return {
        "cost": listing + sum(delta * rates[skill] for skill, delta in body.items()),
        "requests_per_day": requests / DAYS,
        "invocations_per_day": rates,
        "median_for_new": assumed,
    }


def value_line(weighed: dict, value: float | None, evidence: str | None) -> tuple[str, str]:
    notes = [
        f"{skill} new: {group} median {figure(weighed['invocations_per_day'][skill])} invocations/day"
        for skill, group in sorted(weighed["median_for_new"].items())
    ]
    cost = weighed["cost"]
    if value is None:
        return "?:?", f"💰 value ?:? ({'; '.join([f'cost {figure(cost)}/day', 'pass --value with evidence', *notes])})"
    ratio = quotient(cost, value)
    parts = [f"cost {figure(cost)}/day, value {figure(value)}/day", evidence, *notes]
    return ratio, f"💰 value {ratio} ({'; '.join(parts)})"


def parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--transcripts", required=True)
    parser.add_argument("--value", type=amount)
    parser.add_argument("--evidence")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if (args.value is None) != (args.evidence is None):
        parser.error("--value and --evidence go together")
    if args.evidence is not None and (not args.evidence.strip() or "\n" in args.evidence):
        parser.error("--evidence must be one non-empty line")
    return args


def measure(
    repo: Path, base: str, base_files: set[str], changed: list[str]
) -> tuple[dict[str, list[int]], dict[str, int], set[str]]:
    chars: dict[str, list[int]] = {}
    body: dict[str, int] = {}
    new: set[str] = set()
    for path in sorted({p for p in changed if p.endswith(".md")}):
        skill = PurePosixPath(path).parts[1]
        old = at_base(repo, base, path) if path in base_files else ""
        current = in_tree(repo, path)
        side = chars.setdefault(skill, [0, 0])
        side[0] += len(old)
        side[1] += len(current)
        if is_skill_md(path):
            body[skill] = tokens(len(current)) - tokens(len(old))
            if path not in base_files:
                new.add(skill)
    return chars, body, new


def check(argv: list[str]) -> int:
    args = parse(argv)
    repo = Path(args.repo).resolve()
    if not (repo / SKILLS).is_dir():
        fail(f"{repo} has no {SKILLS}/ directory")
    if git(repo, "rev-parse", "--verify", "--quiet", f"{args.base}^{{commit}}").returncode != 0:
        fail(f"unknown ref {args.base!r}")
    root = directory(args.transcripts)
    budget = load(repo / "scripts" / "budget.py", "budget", "counts the listing")
    base_files = set(paths(repo, "ls-tree", "-r", "-z", "--name-only", args.base, "--", SKILLS))
    # Trip-wire: with rename detection a moved file lists only its new path and drops the old one's tokens.
    changed = paths(repo, "diff", "--no-renames", "-z", "--name-only", args.base, "--", SKILLS)
    changed += paths(repo, "ls-files", "-z", "--others", "--exclude-standard", "--", SKILLS)

    chars, body, new = measure(repo, args.base, base_files, changed)
    before = tokens(sum(c[0] for c in chars.values()))
    after = tokens(sum(c[1] for c in chars.values()))
    base_skills = sorted(PurePosixPath(p).parts[1] for p in base_files if is_skill_md(p))
    listing_before = sum(budget.words(at_base(repo, args.base, f"{SKILLS}/{s}/SKILL.md")) for s in base_skills)
    listing_after = sum(budget.counts(repo, index=False).values())
    weighed = weigh(root, listing_after - listing_before, body, new, base_skills)
    ratio, money = value_line(weighed, args.value, args.evidence)

    if before:
        efficiency = round(after / before * 100)
    else:
        efficiency = None if after else LIMIT
    if args.json:
        print(json.dumps({
            "efficiency": efficiency,
            "skills": {"before": before, "after": after},
            "listing": {"before": listing_before, "after": listing_after},
            "per_skill": {name: {"before": tokens(b), "after": tokens(a)} for name, (b, a) in chars.items()},
            "value": {
                "quotient": ratio,
                "cost": round(weighed["cost"], 2),
                "value": args.value,
                "evidence": args.evidence,
                "requests_per_day": round(weighed["requests_per_day"], 2),
                "invocations_per_day": {s: round(r, 2) for s, r in weighed["invocations_per_day"].items()},
                "median_for_new": weighed["median_for_new"],
            },
        }))
    else:
        listing = f"listing {listing_before}→{listing_after} words"
        if efficiency is None:
            print(f"🌱 efficiency new (+{after} tokens; {listing})")
        else:
            print(f"🌱 efficiency {efficiency} % (skills {before}→{after} tokens; {listing})")
        print(money)
    return 3 if efficiency is None or efficiency > LIMIT else 0


def measured(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="tokens.py value", description="Measure the value of a shipped change from the daily context tokens."
    )
    parser.add_argument("--repo", required=True)
    parser.add_argument("--since", required=True)
    parser.add_argument("--transcripts", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    repo = Path(args.repo).resolve()
    if not repo.is_dir():
        fail(f"{repo} is not a directory")
    result = git(repo, "show", "-s", "--format=%ct %h", f"{args.since}^{{commit}}")
    if result.returncode != 0:
        fail(f"unknown commit {args.since!r}")
    stamp, sha = result.stdout.decode().split()
    root = directory(args.transcripts)
    context = load(CONTEXT, "context", "sums the daily context tokens")

    day = datetime.datetime.fromtimestamp(int(stamp), datetime.UTC).date()
    today = datetime.datetime.now(datetime.UTC).date()
    windows = (
        [day - datetime.timedelta(days=n) for n in range(DAYS, 0, -1)],
        [d for d in (day + datetime.timedelta(days=n) for n in range(1, DAYS + 1)) if d < today],
    )
    start = datetime.datetime.combine(windows[0][0], datetime.time.min, tzinfo=datetime.UTC).timestamp()
    turns, _ = context.scan(root, start)
    totals: dict[str, int] = {}
    for turn_day, size in turns.values():
        totals[turn_day] = totals.get(turn_day, 0) + size
    sides = [[totals[d.isoformat()] for d in window if totals.get(d.isoformat())] for window in windows]
    for name, side in zip(("before", "after"), sides, strict=True):
        if not side:
            fail(f"no active day in the {DAYS} days {name} {sha} of {day}")
    median_before, median_after = (statistics.median(side) for side in sides)
    value = median_before - median_after

    if args.json:
        print(json.dumps({
            "since": sha,
            "day": day.isoformat(),
            "before": {"days": len(sides[0]), "median": median_before},
            "after": {"days": len(sides[1]), "median": median_after},
            "value": value,
        }))
    else:
        print(
            f"💰 measured value {figure(value)}/day (median daily context {figure(median_before)}→"
            f"{figure(median_after)} tokens over {len(sides[0])} active days before and {len(sides[1])} after "
            f"{sha} of {day})"
        )
    return 0


def main(argv: list[str]) -> int:
    if argv[:1] == ["value"]:
        return measured(argv[1:])
    return check(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
