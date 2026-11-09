#!/usr/bin/env python3
"""Classify installed skills as current, project, legacy, removed or unknown.

Args:
    --skills-repo: checkout of the skills repository, read with its git history;
        a SKILL.md that keeps SIMILARITY of its text across a move counts as
        renamed, since a renamed skill rewrites its own name throughout.
    --root: a skills directory to classify, repeatable.
    --json: print the rows as JSON instead of tab-separated lines.

Exit codes:
    0 done, 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

SIMILARITY = "40%"


def fail(message: str) -> None:
    print(f"legacy: {message}", file=sys.stderr)
    sys.exit(2)


def git(cwd: Path, *args: str) -> str | None:
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=False
    )
    return result.stdout if result.returncode == 0 else None


def current_names(skills_repo: Path) -> set[str]:
    names = {p.name for p in (skills_repo / "skills").iterdir() if (p / "SKILL.md").is_file()}
    lock = json.loads((skills_repo / "skills-lock.json").read_text(encoding="utf-8"))
    return names | set(lock.get("skills", {}))


def moves(skills_repo: Path) -> dict[str, str | None]:
    out = git(
        skills_repo,
        "log", f"-M{SIMILARITY}", "--diff-filter=RD", "--name-status", "--format=", "--", "skills/*/SKILL.md",
    )
    if out is None:
        fail(f"{skills_repo} is not a git repository")
    found: dict[str, str | None] = {}
    for line in out.splitlines():
        parts = line.split("\t")
        if parts[0].startswith("R") and len(parts) == 3:
            found.setdefault(Path(parts[1]).parent.name, Path(parts[2]).parent.name)
        elif parts[0] == "D" and len(parts) == 2:
            found.setdefault(Path(parts[1]).parent.name, None)
    return found


def successor(name: str, history: dict[str, str | None], current: set[str]) -> str | None:
    seen = set()
    while name not in current:
        if name in seen or history.get(name) is None:
            return None
        seen.add(name)
        name = history[name]
    return name


def project_names(root: Path) -> set[str]:
    top = git(root, "rev-parse", "--show-toplevel")
    if top is None:
        return set()
    tracked = git(Path(top.strip()), "ls-files", "*SKILL.md") or ""
    return {Path(line).parent.name for line in tracked.splitlines()}


def classify(root: Path, current: set[str], history: dict[str, str | None]) -> list[dict]:
    project = project_names(root)
    rows = []
    for entry in sorted(p for p in root.iterdir() if (p / "SKILL.md").is_file()):
        name, succ = entry.name, None
        if name in current:
            verdict = "current"
        elif name in project:
            verdict = "project"
        elif name in history:
            succ = successor(name, history, current)
            verdict = "legacy" if succ else "removed"
        else:
            verdict = "unknown"
        rows.append({"verdict": verdict, "successor": succ, "path": str(entry)})
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--skills-repo", required=True)
    parser.add_argument("--root", action="append", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    repo = Path(args.skills_repo)
    if not (repo / "skills").is_dir() or not (repo / "skills-lock.json").is_file():
        fail(f"{repo} is not a skills repository")
    roots = [Path(r) for r in args.root]
    for root in roots:
        if not root.is_dir():
            fail(f"{root} is not a directory")
    current, history = current_names(repo), moves(repo)
    rows = [row for root in roots for row in classify(root, current, history)]
    if args.json:
        print(json.dumps(rows, indent=1))
    else:
        for row in rows:
            print(f"{row['verdict']}\t{row['successor'] or '-'}\t{row['path']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
