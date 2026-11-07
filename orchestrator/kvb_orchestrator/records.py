from __future__ import annotations

import datetime
import errno
import hashlib
import json
import os
import stat
import tempfile
from pathlib import Path

READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
JSON_LIMIT = 1 << 24


def stamp() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")


def write_atomic(path: Path, data: bytes) -> None:
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}-", delete=False) as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(handle.name, path)


def read_regular(path: Path, limit: int | None) -> str:
    """Args:
        path: the file; a link, FIFO or other non-regular file raises OSError
            without blocking.
        limit: the most bytes to accept, more raise OSError; None for any size.

    Returns:
        The file's text, UTF-8 decoded.
    """
    with open(os.open(path, READ_FLAGS), "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise OSError(errno.EINVAL, "not a regular file", str(path))
        data = handle.read() if limit is None else handle.read(limit + 1)
    if limit is not None and len(data) > limit:
        raise OSError(errno.EFBIG, f"larger than {limit} bytes", str(path))
    return data.decode("utf-8")


def read_json(path: Path) -> object:
    try:
        return json.loads(read_regular(path, JSON_LIMIT))
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
        lines = read_regular(path, None).splitlines()
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
