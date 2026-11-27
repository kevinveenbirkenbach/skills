from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

CACHE = "kvb-review-cache.json"
STAMPS = "kvb-review.json"
SECTIONS = ("files", "diffs", "verdicts")
FILE_MODE = 0o600


def digest(*parts: str) -> str:
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()


def file_key(lens: str, version: str, path: str, blob: str, context: str) -> str:
    """Args:
        context: the digest of the standards the lens judged against, ""
            for a lens that reads none.
    """
    return digest("file", lens, version, path, blob, context)


def diff_key(lens: str, version: str, patch: str, context: str) -> str:
    return digest("diff", lens, version, patch, context)


def finding_key(finding: dict, blob: str, flagged: str) -> str:
    """Args:
        finding: lens, rule and path of the finding.
        blob: the blob of its path after the change.
        flagged: the text of its flagged line, "" without a line.
    """
    return digest("finding", finding["lens"], str(finding.get("rule") or ""), finding["path"], blob, flagged)


def read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except ValueError as error:
        raise ValueError(f"{path} is not JSON: {error}") from error
    if not isinstance(data, dict):
        raise TypeError(f"{path} holds no JSON object")
    return data


def write(path: Path, data: dict) -> None:
    handle, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=1, sort_keys=True)
        os.chmod(name, FILE_MODE)
        os.replace(name, path)
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise


@contextlib.contextmanager
def held(path: Path) -> Iterator[dict]:
    """Args:
        path: the JSON file, read and written back under an exclusive lock on
            its .lock sibling.
    """
    lock = path.with_name(f"{path.name}.lock")
    with open(os.open(lock, os.O_RDWR | os.O_CREAT, FILE_MODE), "r+", encoding="utf-8") as guard:
        fcntl.flock(guard, fcntl.LOCK_EX)
        data = read(path)
        yield data
        write(path, data)


def cache(common: Path) -> contextlib.AbstractContextManager[dict]:
    return held(common / CACHE)


def sections(data: dict) -> dict:
    for name in SECTIONS:
        data.setdefault(name, {})
    return data
