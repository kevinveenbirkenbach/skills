#!/usr/bin/env python3
"""Args:
    --home: the home whose ~/.claude/skills and ~/.agents/skills are read.
    --tree: the branch-tree.json pkgmgr branch tree writes; each of its
        repositories' .claude/skills and .agents/skills are read.
    --output: the index the Agent Orchestrator serves at /api/skills, e.g.
        ~/.local/state/pkgmgr/tree/skills-index.json.

Returns:
    Runs on the host, because the hub's container sees no repository:
    replaces --output with {"written": <epoch>, "skills": [{"name",
    "description", "source"}]}, one entry per skill folder holding a
    SKILL.md, sorted by name and source; source is ~/.claude/skills,
    ~/.agents/skills or the repository's path. The exit code is 0.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import tempfile
import time
from pathlib import Path

HOME_SOURCES = (".claude/skills", ".agents/skills")
SKILL_FILE = "SKILL.md"
HEAD_BYTES = 16384
TREE_BYTES = 8 << 20
NAME = re.compile(r"[A-Za-z0-9:_.-]{1,100}")
DESCRIPTION_CHARS = 300
FIELD = re.compile(r"^(name|description):[ \t]*(.*)$")
BLOCKS = (">", "|", ">-", "|-", ">+", "|+")


def read_head(path: Path, limit: int) -> str:
    """Returns:
        The first limit bytes of path as text, read without following a
        symlink and only from a regular file.

    Raises:
        OSError: path is missing, a symlink or no regular file.
    """
    handle = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(handle, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise OSError(f"{path}: no regular file")
        return stream.read(limit).decode("utf-8", "replace")


def front_matter(text: str) -> dict[str, str]:
    """Returns:
        name and description from the YAML front matter that opens text,
        each one line with its quotes stripped, a folded or literal block
        joined into it; none without a closed front matter.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    found, folding = {}, None
    for line in lines[1:]:
        if line.strip() == "---":
            return {key: " ".join(value.split()) for key, value in found.items()}
        match = FIELD.match(line)
        if match:
            value = match.group(2).strip()
            folding = match.group(1) if value in BLOCKS else None
            found[match.group(1)] = "" if folding else value.strip("\"'")
        elif folding and line[:1] in (" ", "\t"):
            found[folding] += f" {line.strip()}"
        else:
            folding = None
    return {}


def skill_of(folder: Path, source: str) -> dict | None:
    """Returns:
        {name, description, source} of a skill folder: the front matter's
        name, else the folder's; None without a readable SKILL.md or with a
        name outside NAME.
    """
    try:
        fields = front_matter(read_head(folder / SKILL_FILE, HEAD_BYTES))
    except OSError:
        return None
    name = fields.get("name") or folder.name
    if not NAME.fullmatch(name):
        return None
    return {"name": name, "description": fields.get("description", "")[:DESCRIPTION_CHARS], "source": source}


def skills_in(root: Path, source: str) -> list[dict]:
    try:
        folders = sorted(path for path in root.iterdir() if path.is_dir())
    except OSError:
        return []
    return [found for folder in folders if (found := skill_of(folder, source)) is not None]


def repositories(tree: Path) -> list[str]:
    """Returns:
        The absolute repository paths of the branch tree; none when it is
        unreadable.
    """
    try:
        scan = json.loads(read_head(tree, TREE_BYTES))
    except (OSError, ValueError, RecursionError):
        return []
    repos = scan.get("repos") if isinstance(scan, dict) else None
    return sorted({repo["path"] for repo in repos if isinstance(repo, dict) and isinstance(repo.get("path"), str) and repo["path"].startswith("/")}) if isinstance(repos, list) else []


def index(home: Path, tree: Path) -> list[dict]:
    found = [skill for part in HOME_SOURCES for skill in skills_in(home / part, f"~/{part}")]
    found += [skill for repo in repositories(tree) for part in HOME_SOURCES for skill in skills_in(Path(repo) / part, repo)]
    unique = {(skill["name"], skill["source"]): skill for skill in found}
    return [unique[key] for key in sorted(unique)]


def write(output: Path, data: dict) -> None:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=output.parent, prefix=f".{output.name}.", delete=False) as handle:
        try:
            json.dump(data, handle)
        except BaseException:
            os.unlink(handle.name)
            raise
    os.replace(handle.name, output)


def main() -> int:
    parser = argparse.ArgumentParser(description="Index the skills an agent message may name for the Agent Orchestrator.")
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--tree", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    write(args.output, {"written": time.time(), "skills": index(args.home, args.tree)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
