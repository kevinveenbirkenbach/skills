#!/usr/bin/env python3
"""Count every first-party skill description against the listing budget, and each SKILL.md against its cap.

Args:
    --repo: skills repository root.
    --index: count the staged versions in the git index instead of the files.
    --top: how many of the longest descriptions to list.
    --memory: a MEMORY.md index to hold to MEMORY_WORDS; repeatable, a
        missing file counts as empty.

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
SKILL_WORDS = 600
MEMORY_WORDS = 400


def skill_sizes(repo: Path) -> dict[str, int]:
    return {
        p.parent.name: len(p.read_text(encoding="utf-8").split())
        for p in sorted((repo / "skills").glob("*/SKILL.md"))
    }


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
    parser.add_argument("--memory", action="append", default=[])
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
    long = sorted(name for name, n in skill_sizes(repo).items() if n > SKILL_WORDS)
    for name in long:
        print(f"SKILL.md over {SKILL_WORDS}: {name}")
    memory_over = report_memories(args.memory)
    return 1 if total > LISTING_WORDS or over or long or memory_over else 0


def report_memories(paths: list[str]) -> bool:
    """Args:
        paths: MEMORY.md indexes; a missing file counts as empty.

    Returns:
        Whether any index holds more than MEMORY_WORDS words.
    """
    over = False
    for path in paths:
        try:
            n = len(Path(path).read_text(encoding="utf-8").split())
        except FileNotFoundError:
            n = 0
        over = over or n > MEMORY_WORDS
        print(f"{n}/{MEMORY_WORDS} words in {path}" if n <= MEMORY_WORDS else f"MEMORY.md over {MEMORY_WORDS}: {path} ({n})")
    return over


if __name__ == "__main__":
    sys.exit(main())
