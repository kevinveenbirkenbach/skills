#!/usr/bin/env python3
"""Report how ready a repository is for agents: instructions, runtime-specific files, code index.

Args:
    --repo: path of the repository.

Environment:
    CBM_CACHE_DIR: graph cache of codebase-memory-mcp holding _config.db;
        default ~/.cache/codebase-memory-mcp. Opened read-only, so the check
        works inside an agent sandbox that cannot write there.

Output:
    one tab-separated line per check: check, state, detail. States are ok,
    missing, drift, or for the snapshot tracked, ignored or untracked.

Exit codes:
    0 report printed, 2 usage error.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from contextlib import closing
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


def auto_index() -> tuple[str, str]:
    """Returns:
        State and detail of the auto_index setting in _config.db, read through
        a read-only SQLite URI: ok when false or unset (upstream default
        false), so only the graph.py hook indexes, through its size and memory
        gates; drift when anything else; missing when the file is absent or
        unreadable.
    """
    cache = Path(os.environ.get("CBM_CACHE_DIR") or Path.home() / ".cache" / "codebase-memory-mcp")
    config = cache / "_config.db"
    if not config.is_file():
        return "missing", f"{config} not found"
    try:
        with closing(sqlite3.connect(f"{config.resolve().as_uri()}?mode=ro", uri=True)) as db:
            row = db.execute("SELECT value FROM config WHERE key = 'auto_index'").fetchone()
    except sqlite3.Error as error:
        return "missing", f"{config} unreadable: {error}"
    if row is None or row[0] == "false":
        return "ok", f"auto_index = {row[0] if row else 'unset'} (the graph.py hook indexes through the gates)"
    return "drift", f"auto_index = {row[0]}: the daemon indexes session roots and bypasses the queue and memory gates"


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
    rows.append(("auto-index", *auto_index()))
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
