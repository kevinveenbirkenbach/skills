from __future__ import annotations

import hashlib
import os
import re
import shlex
import stat

from .signed import client_module, signing

sandbox_paths = client_module("sandbox_paths", {})

PAYLOAD_LIMIT = 64 << 10
PAYLOAD_FILES = 8
PAYLOAD_ROOT = "/tmp"
BINARY_PROBE = 8000
EXTENSION = re.compile(r"[^/]+\.[A-Za-z0-9]{1,8}")
URL = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://")


def words_of(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()


def named_paths(command: str, directory: str) -> list[str]:
    """Returns:
        Every word of the command, or value of a --name=value option, that
        names a path: one holding a / or ending in a file extension, no
        URL; relative ones joined to directory, each once, in order.
    """
    found: list[str] = []
    for word in words_of(command):
        value = word.split("=", 1)[1] if word.startswith("-") and "=" in word else word
        if not value or value.startswith("-") or URL.match(value) or not ("/" in value or EXTENSION.fullmatch(value)):
            continue
        path = os.path.normpath(os.path.join(directory, os.path.expanduser(value)))
        if path not in found:
            found.append(path)
    return found


def refused(path: str, reason: str, size: int) -> dict:
    return {"path": path, "state": "refused", "reason": reason, "sha256": "", "size": size, "content": ""}


def read_payload(path: str, roots: list[str] | None) -> dict | None:
    """Args:
        path: an absolute, normalized path a command names.
        roots: the sandbox denyRead roots, None when the hub knows none yet.

    Returns:
        The file as shown on a card: read with its content and sha256, or
        refused with the reason and no content; None when nothing lies at
        the path or it is no file.
    """
    try:
        info = os.lstat(path)
    except OSError:
        return None
    if stat.S_ISLNK(info.st_mode):
        return refused(path, "a symlink, never followed", 0)
    if not stat.S_ISREG(info.st_mode):
        return None
    if not path.startswith(f"{PAYLOAD_ROOT}/") or os.path.realpath(path) != path:
        return refused(path, f"outside {PAYLOAD_ROOT} or behind a symlinked folder", info.st_size)
    if roots is None:
        return refused(path, "no sandbox view yet, so no file is read", info.st_size)
    if sandbox_paths.denied(path, roots):
        return refused(path, "the sandbox denies reading it", info.st_size)
    if info.st_size > PAYLOAD_LIMIT:
        return refused(path, f"{info.st_size} bytes, over the {PAYLOAD_LIMIT} bytes a card shows", info.st_size)
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as error:
        return refused(path, f"unreadable: {error.strerror}", info.st_size)
    with os.fdopen(descriptor, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            return refused(path, "no regular file", info.st_size)
        data = handle.read(PAYLOAD_LIMIT + 1)
    if len(data) > PAYLOAD_LIMIT:
        return refused(path, f"over the {PAYLOAD_LIMIT} bytes a card shows", len(data))
    if b"\0" in data[:BINARY_PROBE]:
        return refused(path, "a binary file", len(data))
    return {"path": path, "state": "read", "reason": "", "sha256": hashlib.sha256(data).hexdigest(), "size": len(data), "content": data.decode("utf-8", "replace")}


def payload_files(command: str, directory: str, roots: list[str] | None) -> list[dict]:
    found = (read_payload(path, roots) for path in named_paths(command, directory) if directory.startswith("/"))
    return [entry for entry in found if entry is not None][:PAYLOAD_FILES]


def payload_hash(command: str, directory: str, files: list[dict]) -> str:
    """Returns:
        The sha256 a command card is bound to: its command, directory and
        each named file's path, state, reason and content digest.
    """
    listed = [[entry["path"], entry["state"], entry["reason"], entry["sha256"]] for entry in files]
    return signing.item_hash({"kind": "payload", "command": command, "directory": directory, "files": listed})


def denied_roots(settings_files: list[dict]) -> list[str] | None:
    """Args:
        settings_files: the settings files of the hub's sandbox view, each
            with its permissions and sandbox sections.

    Returns:
        Every absolute sandbox.filesystem.denyRead entry of them, None when
        the view lists no file.
    """
    if not settings_files:
        return None
    roots: list[str] = []
    for entry in settings_files:
        sandbox = entry["settings"].get("sandbox")
        filesystem = sandbox.get("filesystem") if isinstance(sandbox, dict) else None
        listed = filesystem.get("denyRead") if isinstance(filesystem, dict) else None
        roots += [path.rstrip("/") or "/" for path in listed or [] if isinstance(path, str) and path.startswith("/")]
    return roots
