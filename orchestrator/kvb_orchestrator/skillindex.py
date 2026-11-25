from __future__ import annotations

import re
from pathlib import Path

from .records import read_json

SKILLS_INDEX = "skills-index.json"
NAME = re.compile(r"[A-Za-z0-9:_.-]{1,100}")
TEXT_CHARS = 300
SOURCE_CHARS = 1000
SKILLS_LIMIT = 2000


def entry(raw: object) -> dict | None:
    """Returns:
        {name, description, source} of an index row whose name matches NAME
        and whose description and source are strings within their limits;
        None for any other row.
    """
    if not isinstance(raw, dict):
        return None
    name, description, source = raw.get("name"), raw.get("description"), raw.get("source")
    if not isinstance(name, str) or not NAME.fullmatch(name) or not isinstance(description, str) or not isinstance(source, str) or not source or len(source) > SOURCE_CHARS:
        return None
    return {"name": name, "description": description[:TEXT_CHARS], "source": source}


def served(file: Path) -> dict:
    """Args:
        file: the index client/skills_index.py writes next to the branch tree.

    Returns:
        {"skills"}: its valid rows, at most SKILLS_LIMIT, sorted by name and
        source; none while the file is missing or unreadable.
    """
    data = read_json(file)
    rows = data.get("skills") if isinstance(data, dict) else None
    found = [shown for raw in rows[:SKILLS_LIMIT] if (shown := entry(raw)) is not None] if isinstance(rows, list) else []
    return {"skills": sorted(found, key=lambda row: (row["name"], row["source"]))}
