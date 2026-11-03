#!/usr/bin/env python3
"""Stage only the changed lines of one file that match a pattern.

Args:
    --repo: path of the git worktree.
    --file: the file, relative to the worktree root.
    --match: regular expression; a hunk of only added lines keeps the added
        lines it matches, any other hunk is staged whole when one of its
        changed lines matches.
    --dry-run: print the patch instead of applying it to the index.

Exit codes:
    0 staged or printed, 1 nothing matched, 2 usage error.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@(.*)$")


def renumber(hunks: list[list[str]]) -> list[list[str]]:
    offset = 0
    out = []
    for hunk in hunks:
        match = HEADER.match(hunk[0])
        start, count = int(match.group(1)), int(match.group(2) or 1)
        added = sum(line.startswith("+") for line in hunk[1:])
        removed = sum(line.startswith("-") for line in hunk[1:])
        new_start = start + offset + (1 if count == 0 else 0) - (1 if added == 0 else 0)
        out.append([f"@@ -{start},{count} +{new_start},{added} @@{match.group(3)}", *hunk[1:]])
        offset += added - removed
    return out


def fail(message: str) -> None:
    print(f"stage_hunks: {message}", file=sys.stderr)
    sys.exit(2)


def git(repo: Path, *args: str, stdin: str | None = None) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, input=stdin, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        fail(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout


def split(diff: str) -> tuple[list[str], list[list[str]]]:
    header: list[str] = []
    hunks: list[list[str]] = []
    for line in diff.splitlines():
        if line.startswith("@@"):
            hunks.append([line])
        elif hunks:
            hunks[-1].append(line)
        else:
            header.append(line)
    return header, hunks


def select(hunks: list[list[str]], pattern: re.Pattern) -> list[list[str]]:
    kept = []
    for hunk in hunks:
        changes = [line for line in hunk[1:] if line[:1] in "+-"]
        if all(line.startswith("+") for line in changes):
            lines = [line for line in changes if pattern.search(line[1:])]
            if lines:
                kept.append([hunk[0], *lines])
        elif any(pattern.search(line[1:]) for line in changes):
            kept.append(hunk)
    return kept


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", required=True)
    parser.add_argument("--file", required=True)
    parser.add_argument("--match", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    repo = Path(args.repo)
    if not repo.is_dir():
        fail(f"{repo} is not a directory")
    try:
        pattern = re.compile(args.match)
    except re.error as error:
        fail(f"--match: {error}")
    header, hunks = split(git(repo, "diff", "--no-color", "-U0", "--", args.file))
    kept = renumber(select(hunks, pattern))
    if not kept:
        print(f"stage_hunks: no change in {args.file} matches {args.match!r}", file=sys.stderr)
        return 1
    patch = "\n".join([*header, *(line for hunk in kept for line in hunk)]) + "\n"
    if args.dry_run:
        print(patch, end="")
        return 0
    git(repo, "apply", "--cached", "--unidiff-zero", "--recount", "-", stdin=patch)
    print(f"staged {sum(len(h) - 1 for h in kept)} lines of {args.file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
