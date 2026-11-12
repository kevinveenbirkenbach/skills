"""Args:
    top: the working tree; its .claude folder and that of $CLAUDE_PROJECT_DIR join the merge.

Returns:
    denied_roots: FLOOR with every sandbox.filesystem.denyRead path and every
        permissions.deny Read(...) rule of the settings Claude Code merges
        (managed, user, project), as absolute paths or globs (a **/ also
        matching no folder), also resolved
        through symlinks; a relative one lies under its scope (managed: its
        folder, user: the config dir, project: the project root).
    denied: whether a path is, matches or lies under one of those.

Raises:
    Unreadable: when a settings file or managed-settings.d exists but cannot be read or parsed.
"""

from __future__ import annotations

import fnmatch
import itertools
import json
import os
import re
import stat
from pathlib import Path

MANAGED = Path("/etc/claude-code")
SETTINGS = ("settings.json", "settings.local.json")
SETTINGS_LIMIT = 1 << 20
GLOB = re.compile(r"[*?\[]")
FLOOR = ("~/.ssh", "~/.gnupg", "~/.aws", "~/.kube", "~/.netrc", "~/.git-credentials", "~/.config/gcloud", "~/.docker/config.json", "~/.claude")
READ_RULE = re.compile(r"\s*Read(?:\((.*)\))?\s*")


class Unreadable(Exception):
    pass


def project_roots(top: Path) -> list[Path]:
    session = os.environ.get("CLAUDE_PROJECT_DIR")
    return [top, *([Path(session)] if session else [])]


def settings_files(top: Path) -> list[tuple[Path, Path]]:
    """Returns:
        Every settings file Claude Code merges, with the folder its relative
        paths start from.
    """
    user = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    scoped = [(MANAGED / "managed-settings.json", MANAGED), *((file, MANAGED) for file in managed_parts())]
    scoped += [(user / name, user) for name in SETTINGS]
    return scoped + [(root / ".claude" / name, root) for root in project_roots(top) for name in SETTINGS]


def managed_parts() -> list[Path]:
    folder = MANAGED / "managed-settings.d"
    try:
        names = sorted(os.listdir(folder))
    except FileNotFoundError:
        return []
    except OSError as error:
        raise Unreadable(f"settings folder {folder} unreadable: {type(error).__name__}") from error
    return [folder / name for name in names if name.endswith(".json")]


def settings_text(file: Path) -> str | None:
    """Returns:
        The text of a settings file, None when it does not exist.

    Raises:
        Unreadable: when it is no regular file of at most SETTINGS_LIMIT bytes.
        OSError, ValueError: when it cannot be opened or is no UTF-8.
    """
    try:
        fd = os.open(file, os.O_RDONLY | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > SETTINGS_LIMIT:
            raise Unreadable(f"settings {file} is no regular file of at most {SETTINGS_LIMIT} bytes")
        with open(fd, "rb", closefd=False) as handle:
            return handle.read(SETTINGS_LIMIT + 1).decode("utf-8")
    finally:
        os.close(fd)


def settings_data(file: Path) -> object:
    try:
        text = settings_text(file)
        return json.loads(text) if text and text.strip() else {}
    except (OSError, ValueError) as error:
        raise Unreadable(f"settings {file} unreadable: {type(error).__name__}") from error


def strings_at(data: object, keys: tuple[str, ...]) -> list[str]:
    for key in keys:
        data = data.get(key) if isinstance(data, dict) else None
    if data is None:
        return []
    if not (isinstance(data, list) and all(isinstance(entry, str) for entry in data)):
        raise Unreadable(f"{'.'.join(keys)} is no list of strings")
    return data


def rule_paths(rules: list[str], scope: Path, folders: list[Path]) -> list[str]:
    """Returns:
        The paths the permissions.deny Read rules name, read as Claude Code
        reads them: //x absolute, ~/x under home, /x under scope, any other
        under scope and every one of folders, a name without / at any depth;
        a bare Read denies /.
    """
    found = []
    for entry in rules:
        match = READ_RULE.fullmatch(entry)
        if match:
            found += rule_path(match.group(1) or "//", scope, folders)
    return found


def rule_path(spec: str, scope: Path, folders: list[Path]) -> list[str]:
    if spec.startswith("//"):
        return ["/" + spec.lstrip("/")]
    if spec == "~" or spec.startswith("~/"):
        return [os.path.expanduser(spec)]
    if spec.startswith("/"):
        return [f"{scope}{spec}"]
    name = spec.removeprefix("./")
    bases = [scope, *folders]
    if "/" in name.rstrip("/"):
        return [f"{base}/{name}" for base in bases]
    return [entry for base in bases for entry in (f"{base}/{name}", f"{base}/*/{name}")]


def denied_roots(top: Path) -> list[str]:
    folders = project_roots(top)
    entries = [(entry, Path.home()) for entry in FLOOR]
    for file, scope in settings_files(top):
        data = settings_data(file)
        entries += [(entry, scope) for entry in strings_at(data, ("sandbox", "filesystem", "denyRead"))]
        entries += [(entry, scope) for entry in rule_paths(strings_at(data, ("permissions", "deny")), scope, folders)]
    return [root for entry, scope in entries for root in resolved(entry, scope)]


def resolved(entry: str, base: Path) -> set[str]:
    found = set()
    for path in zero_folders("/" + os.path.normpath(os.path.join(base, os.path.expanduser(entry))).lstrip("/")):
        cut = GLOB.search(path)
        head = os.path.dirname(path[: cut.start()]) if cut else path
        found |= {path, os.path.realpath(head) + path[len(head) :]}
    return found


def zero_folders(path: str) -> set[str]:
    """Returns:
        path and every spelling of it with some of its **/ dropped, as a
        gitignore ** also matches no folder at all.
    """
    parts = path.split("**/")
    return {"".join(part + cut for part, cut in zip(parts, cuts, strict=False)) + parts[-1] for cuts in itertools.product(("**/", ""), repeat=len(parts) - 1)}


def denied(path: str, roots: list[str]) -> bool:
    if any(path == root or path.startswith(f"{root.rstrip('/')}/") for root in roots if not GLOB.search(root)):
        return True
    chain = [path, *map(str, Path(path).parents)]
    return any(fnmatch.fnmatchcase(link, root) for root in roots if GLOB.search(root) for link in chain)
