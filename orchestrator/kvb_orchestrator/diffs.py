from __future__ import annotations

import json
import re
from pathlib import Path

from .errors import Missing, ToolError
from .records import read_json, write_atomic
from .signed import limits

DIFF_LIMIT = limits.DIFF_LIMIT
DIFF_BODY_LIMIT = limits.DIFF_BODY_LIMIT
SEALED_LIMIT = limits.SEALED_LIMIT
FILE_CAP = limits.FILE_CAP
PATH_LIMIT = limits.PATH_LIMIT
STATUSES = ("A", "M", "D", "R", "B")
DIFF_KEYS = ("path", "status", "mode", "additions", "deletions", "patch", "note")
HIDDEN = (limits.WITHHELD, limits.MASKED)
NOTES = ("", *HIDDEN)
MODE = re.compile(r"[0-7]{6}(?: => [0-7]{6})?")
DIFF_SUFFIX = {"review": ".review-diff.json", "ask": ".ask-diff.json"}
SEALED_SUFFIX = {"review": ".review-sealed.json", "ask": ".ask-sealed.json"}


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
    if entry["note"] not in NOTES or (entry["note"] == limits.WITHHELD and patch):
        raise ToolError(f"note must be empty, {limits.MASKED!r} or {limits.WITHHELD!r}, the latter with an empty patch")
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


def valid_sealed(value: object, diff: list[dict] | None) -> dict[str, str]:
    """Returns:
        The clear patches a request seals apart from its diff, checked: an
        object from the path of a masked or withheld file of diff to its
        patch text, at most SEALED_LIMIT bytes of JSON-encoded text in all;
        none without a diff.
    """
    hidden = {entry["path"] for entry in diff or [] if entry["note"] in HIDDEN}
    if not isinstance(value, dict) or not all(isinstance(patch, str) for patch in value.values()) or not set(value) <= hidden:
        raise ToolError("sealed must map the path of a masked or withheld file of the diff to its patch text")
    if sum(len(json.dumps(patch, ensure_ascii=False).encode("utf-8")) for patch in value.values()) > SEALED_LIMIT:
        raise ToolError(f"the sealed patches must stay within {SEALED_LIMIT} bytes")
    return dict(value)


def diff_bytes(diff: list[dict]) -> bytes:
    return json.dumps({"diff": diff}, ensure_ascii=False).encode("utf-8")


def sealed_bytes(sealed: dict[str, str]) -> bytes:
    return json.dumps({"sealed": sealed}, ensure_ascii=False).encode("utf-8")


def sealed_file(folder: Path, kind_name: str, item_id: str) -> Path:
    return folder / f"{item_id}{SEALED_SUFFIX[kind_name]}"


def store_sealed(folder: Path, kind_name: str, item_id: str, sealed: dict[str, str]) -> None:
    write_atomic(sealed_file(folder, kind_name, item_id), sealed_bytes(sealed))


def stored_sealed(folder: Path, kind_name: str, item_id: str) -> dict[str, str]:
    data = read_json(sealed_file(folder, kind_name, item_id))
    if not isinstance(data, dict) or not isinstance(data.get("sealed"), dict):
        raise Missing(item_id)
    return data["sealed"]


def store_diff(folder: Path, kind_name: str, item_id: str, diff: list[dict]) -> None:
    write_atomic(folder / f"{item_id}{DIFF_SUFFIX[kind_name]}", diff_bytes(diff))


def stored_diff(folder: Path, kind_name: str, item_id: str) -> dict:
    data = read_json(folder / f"{item_id}{DIFF_SUFFIX[kind_name]}") if kind_name in DIFF_SUFFIX else None
    if not isinstance(data, dict) or not isinstance(data.get("diff"), list):
        raise Missing(item_id)
    return {"kind": kind_name, "id": item_id, "diff": data["diff"]}
