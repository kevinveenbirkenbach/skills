#!/usr/bin/env python3
"""Compare the estimated tokens of changed skill text files, and the listing words, with a base ref.

Args:
    --repo: skills repository root; its scripts/budget.py counts the listing.
    --base: git ref the change starts from; the working tree is the after side.
    --json: print the figures as JSON instead of the line.

Output:
    `🌱 efficiency <p> % (skills <b>→<a> tokens; listing <b>→<a> words)`, p = after / before * 100,
    or `🌱 efficiency new (+<a> tokens; listing <b>→<a> words)` when the changed files hold no
    base tokens. Changed files are the *.md under skills/ that `git diff <ref>` names plus untracked
    ones; a file missing on a side counts 0. Tokens are an estimate: characters / 4. The listing
    is the sum of every skills/*/SKILL.md description word. --json prints efficiency (null when
    new), the skills and listing totals and the tokens per skill.

Exit codes:
    0 efficiency at most 100, 2 usage error, 3 over 100 or new.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path, PurePosixPath
from types import ModuleType

CHARS_PER_TOKEN = 4
LIMIT = 100
SKILLS = "skills"


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


def load_budget(repo: Path) -> ModuleType:
    path = repo / "scripts" / "budget.py"
    if not path.is_file():
        fail(f"{path} is missing; it counts the listing")
    spec = importlib.util.spec_from_file_location("budget", path)
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    if not (repo / SKILLS).is_dir():
        fail(f"{repo} has no {SKILLS}/ directory")
    if git(repo, "rev-parse", "--verify", "--quiet", f"{args.base}^{{commit}}").returncode != 0:
        fail(f"unknown ref {args.base!r}")
    budget = load_budget(repo)
    base_files = set(paths(repo, "ls-tree", "-r", "-z", "--name-only", args.base, "--", SKILLS))
    # Trip-wire: with rename detection a moved file lists only its new path and drops the old one's tokens.
    changed = paths(repo, "diff", "--no-renames", "-z", "--name-only", args.base, "--", SKILLS)
    changed += paths(repo, "ls-files", "-z", "--others", "--exclude-standard", "--", SKILLS)

    chars: dict[str, list[int]] = {}
    for path in sorted({p for p in changed if p.endswith(".md")}):
        before = at_base(repo, args.base, path) if path in base_files else ""
        side = chars.setdefault(PurePosixPath(path).parts[1], [0, 0])
        side[0] += len(before)
        side[1] += len(in_tree(repo, path))
    before = tokens(sum(c[0] for c in chars.values()))
    after = tokens(sum(c[1] for c in chars.values()))
    listing_before = sum(budget.words(at_base(repo, args.base, p)) for p in sorted(base_files) if is_skill_md(p))
    listing_after = sum(budget.counts(repo, index=False).values())

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
        }))
    else:
        listing = f"listing {listing_before}→{listing_after} words"
        if efficiency is None:
            print(f"🌱 efficiency new (+{after} tokens; {listing})")
        else:
            print(f"🌱 efficiency {efficiency} % (skills {before}→{after} tokens; {listing})")
    return 3 if efficiency is None or efficiency > LIMIT else 0


if __name__ == "__main__":
    sys.exit(main())
