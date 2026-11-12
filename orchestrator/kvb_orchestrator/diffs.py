from __future__ import annotations

import json
import re
from pathlib import Path

from .errors import Missing, ToolError
from .records import read_json, write_atomic
from .signed import limits

DIFF_LIMIT = limits.DIFF_LIMIT
DIFF_BODY_LIMIT = limits.DIFF_BODY_LIMIT
FILE_CAP = limits.FILE_CAP
PATH_LIMIT = limits.PATH_LIMIT
STATUSES = ("A", "M", "D", "R", "B")
DIFF_KEYS = ("path", "status", "mode", "additions", "deletions", "patch", "note")
NOTES = ("", limits.WITHHELD)
MODE = re.compile(r"[0-7]{6}(?: => [0-7]{6})?")
DIFF_SUFFIX = {"review": ".review-diff.json", "ask": ".ask-diff.json"}


def counted(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def diff_entry(entry: object) -> dict:
    if not isinstance(entry, dict) or set(entry) != set(DIFF_KEYS):
        raise ToolError(f"every diff entry must be an object with exactly {', '.join(DIFF_KEYS)}")
    path, patch, mode = entry["path"], entry["patch"], entry["mode"]
    if not isinstance(path, str) or not 0 < len(path) <= PATH_LIMIT or entry["status"] not in STATUSES:
        raise ToolError(f"a diff path must be 1 to {PATH_LIMIT} characters and its status one of {', '.join(STATUSES)}")
    if not isinstance(mode, str) or not MODE.fullmatch(mode):
        raise ToolError("mode must be a git file mode, or old => new for a changed one")
    if not counted(entry["additions"]) or not counted(entry["deletions"]) or not isinstance(patch, str) or (entry["status"] == "B" and patch):
        raise ToolError("additions and deletions must be counts, patch text, empty for a binary file")
    if entry["note"] not in NOTES or (entry["note"] and patch):
        raise ToolError(f"note must be empty or {limits.WITHHELD!r}, the latter with an empty patch")
    return {key: entry[key] for key in DIFF_KEYS}


def valid_diff(value: object) -> list[dict]:
    """Returns:
        The review diff of requirement 003, checked: at most FILE_CAP
        entries, and at most DIFF_LIMIT bytes of JSON-encoded patch text in
        all, the bound the requesting script keeps.
    """
    if not isinstance(value, list) or len(value) > FILE_CAP:
        raise ToolError(f"diff must be a list of at most {FILE_CAP} files")
    entries = [diff_entry(entry) for entry in value]
    if sum(len(json.dumps(entry["patch"], ensure_ascii=False).encode("utf-8")) for entry in entries) > DIFF_LIMIT:
        raise ToolError(f"the patches of a diff must stay within {DIFF_LIMIT} bytes")
    return entries


def diff_bytes(diff: list[dict]) -> bytes:
    return json.dumps({"diff": diff}, ensure_ascii=False).encode("utf-8")


def store_diff(folder: Path, kind_name: str, item_id: str, diff: list[dict]) -> None:
    write_atomic(folder / f"{item_id}{DIFF_SUFFIX[kind_name]}", diff_bytes(diff))


def stored_diff(folder: Path, kind_name: str, item_id: str) -> dict:
    data = read_json(folder / f"{item_id}{DIFF_SUFFIX[kind_name]}") if kind_name in DIFF_SUFFIX else None
    if not isinstance(data, dict) or not isinstance(data.get("diff"), list):
        raise Missing(item_id)
    return {"kind": kind_name, "id": item_id, "diff": data["diff"]}
