from __future__ import annotations

import datetime
import hashlib
import json
import os
import tempfile
from pathlib import Path


def stamp() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")


def write_atomic(path: Path, data: bytes) -> None:
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}-", delete=False) as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(handle.name, path)


def read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return None


def parse_line(line: str) -> dict | None:
    try:
        row = json.loads(line)
    except (ValueError, RecursionError):
        return None
    return row if isinstance(row, dict) else None


def read_jsonl(path: Path) -> list[dict]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError):
        return []
    return [row for row in map(parse_line, lines) if row is not None]


def epoch(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float) or not 0 <= value < 1e11:
        return None
    return float(value)


def iso_epoch(value: object) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.UTC)
    return parsed.timestamp()


def shown(value: object) -> str:
    if value is None or value == "":
        return "-"
    return str(value)


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
