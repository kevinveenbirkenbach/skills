#!/usr/bin/env python3
"""Count every first-party skill description against the listing budget.

Args:
    --repo: skills repository root.
    --index: count the staged versions in the git index instead of the files.
    --top: how many of the longest descriptions to list.

Exit codes:
    0 within budget, 1 over budget, 2 usage error.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

LISTING_WORDS = 1500
DESCRIPTION_WORDS = 40


def words(skill_md: str) -> int:
    frontmatter = skill_md.split("---", 2)[1]
    return len(frontmatter.split("description:", 1)[1].split()) - 1


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        print(f"budget: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(2)
    return result.stdout


def counts(repo: Path, index: bool) -> dict[str, int]:
    if index:
        paths = git(repo, "ls-files", "skills/*/SKILL.md").split()
        return {Path(p).parent.name: words(git(repo, "show", f":{p}")) for p in paths}
    return {
        p.parent.name: words(p.read_text(encoding="utf-8"))
        for p in sorted((repo / "skills").glob("*/SKILL.md"))
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", required=True)
    parser.add_argument("--index", action="store_true")
    parser.add_argument("--top", type=int, required=True)
    args = parser.parse_args()

    repo = Path(args.repo)
    if not (repo / "skills").is_dir():
        print(f"budget: {repo} has no skills/ directory", file=sys.stderr)
        return 2
    found = counts(repo, args.index)
    total = sum(found.values())
    over = sorted(name for name, n in found.items() if n > DESCRIPTION_WORDS)
    print(f"total {total}/{LISTING_WORDS} words in {len(found)} skills")
    for name, n in sorted(found.items(), key=lambda item: -item[1])[: args.top]:
        print(f"{n}\t{name}")
    for name in over:
        print(f"over {DESCRIPTION_WORDS}: {name}")
    return 1 if total > LISTING_WORDS or over else 0


if __name__ == "__main__":
    sys.exit(main())
