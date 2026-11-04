#!/usr/bin/env python3
"""Report how ready a repository is for agents: instructions, runtime-specific files, code index.

Args:
    --repo: path of the repository.

Output:
    one tab-separated line per check: check, state, detail. States are ok,
    missing, drift, or for the snapshot tracked, ignored or untracked.

Exit codes:
    0 report printed, 2 usage error.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

RUNTIME_FILES = ("CLAUDE.md", ".claude/CLAUDE.md", "CLAUDE.local.md", "GEMINI.md")
INDEX = "codebase-memory-mcp"
SNAPSHOT = ".codebase-memory/graph.db.zst"
LINK = re.compile(r"\]\(([^)\s#]+)")


def fail(message: str) -> None:
    print(f"agents: {message}", file=sys.stderr)
    sys.exit(2)


def git_ok(repo: Path, *args: str) -> bool:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, check=False).returncode == 0


def snapshot_state(repo: Path) -> str:
    if not (repo / SNAPSHOT).exists():
        return "missing"
    if git_ok(repo, "ls-files", "--error-unmatch", SNAPSHOT):
        return "tracked"
    if git_ok(repo, "check-ignore", "-q", SNAPSHOT):
        return "ignored"
    return "untracked"


def checks(repo: Path) -> list[tuple[str, str, str]]:
    agents = repo / "AGENTS.md"
    text = agents.read_text(encoding="utf-8") if agents.is_file() else ""
    rows = [("AGENTS.md", "ok" if text else "missing", "single source of the agent instructions")]
    rows.extend(
        (name, "drift", "runtime-specific; fold into AGENTS.md and remove")
        for name in RUNTIME_FILES
        if (repo / name).is_file()
    )
    dead = sorted(
        {
            target
            for target in LINK.findall(text)
            if ":" not in target and not (repo / target).exists()
        }
    )
    rows.append(("links", "drift" if dead else "ok", ", ".join(dead) or "every relative link resolves"))
    rows.append(("index-pointer", "ok" if INDEX in text else "missing", f"AGENTS.md names {INDEX}"))
    rows.append(("index-binary", "ok" if shutil.which(INDEX) else "missing", f"{INDEX} on PATH"))
    rows.append(("snapshot", snapshot_state(repo), SNAPSHOT))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", required=True)
    args = parser.parse_args()
    repo = Path(args.repo)
    if not repo.is_dir():
        fail(f"{repo} is not a directory")
    for row in checks(repo):
        print("\t".join(row))
    return 0


if __name__ == "__main__":
    sys.exit(main())
