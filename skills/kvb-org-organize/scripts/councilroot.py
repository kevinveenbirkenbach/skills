#!/usr/bin/env python3
"""Usage:
    councilroot.py root
    councilroot.py durable
    councilroot.py dir PART [PART ...]
    councilroot.py release VERSION
    councilroot.py migrate [--legacy DIR] [--catch-up]
    councilroot.py preflight [--legacy DIR] [--settings FILE] [--managed DIR]
    councilroot.py retire [--days N]

Environment:
    AGENTS_COUNCIL_ROOT: the council root when it is an absolute path.
    XDG_STATE_HOME: else both roots lie below it, when it is an absolute path.
    HOME: else both lie below ~/.local/state.
    AGENTS_COUNCIL_LEGACY: the default DIR of migrate and preflight, LEGACY
        unless set.

Args:
    root: print the council root.
    durable: print the host-only root; AGENTS_COUNCIL_ROOT never moves it.
    dir: create <root>/PART/... with mode 700 where missing, refusing a
        level that is a link, not the current user's or writable by group or
        others, and print it:
        pages holds the kvb-git-diff review pages the hub reads, approvals
        the replay stores of approval.py verify, gates the gate logs.
    release: create agents-release/VERSION beside the roots with mode 700
        and print it: the kvb-release drafts, which the release skills write
        with the Edit and Write tools.
    migrate: move every regular file below DIR, LEGACY unless given, to the
        same place below the root and remove the emptied directories, through
        nofollow.py, so no link on either side is followed; each copy is
        written to a temp file and linked into place, so it never replaces a
        file. Refuses, moving nothing, while a *.lock below DIR is held or
        its queue.json holds a job, and, under those locks and unless
        --catch-up is given, while a regular file cannot be opened or its
        place below the root is reached through a link (`unmoved <path>:
        <reason>`) or a whole file the root holds differs (`conflict <file>
        differs from <legacy file>`). A file the root already holds is never
        overwritten: an identical one leaves only the root's copy; a .jsonl
        journal gets the legacy rows it lacks, by id when every row on both
        sides carries one, else each exact line as often as the legacy side
        holds it more often, appended or, when every row carries a ts, in ts
        order; with --catch-up a differing whole file is copied beside its
        namesake as <name>.legacy-<12 hex digits of its sha256> (`kept
        <legacy file> beside <file> as <copy>`). Each file is first renamed
        to <name>.<16 hex digits>.migrating and copied from there, so a
        writer that opens the old name meanwhile makes a new file for the
        catch-up; a later run moves a staged file to its old name. A link or
        another non-regular entry stays (`skipped <path>: <reason>`); a file
        that fails after the check stays (`unmoved <path>: <reason>`).
        <durable>/migrate.started exists from the first move to the end of
        the run, so after a crash it tells the install the move stopped
        halfway; a completed run removes it. A second run moves nothing new
        and duplicates no journal row. Run it while no agent, unit or queue
        job writes either root; the install runs it again with --catch-up
        after the copy for what the old skills wrote meanwhile.
    preflight: print to stderr every reason migrate would refuse, and every
        missing or wrong sandbox.filesystem.allowWrite entry, all files only
        read: the root and agents-release must be in the user file
        (--settings, ~/.claude/settings.json unless given); no entry of it,
        of the managed and user files settings_files() lists (--managed DIR,
        /etc/claude-code unless given, with its managed-settings.d drop-ins;
        the queue's permission check reads the same list), of a
        .claude/settings.json or .claude/settings.local.json up to 8 levels
        below the pkgmgr repositories and worktrees directories, directory
        links followed, or in the start directory of a session listed in
        ~/.claude/projects may be the host-only root, inside it or above it.
        It warns, without failing, while the agents are not suspended. The
        global install runs it before it copies anything.
    retire: move every regular file below <root>/gates and <root>/pages
        changed more than N days ago (30 unless given) to the same place
        below <root>/archive/<date>, which no reader opens, never following
        a link, and print the count.

Exit codes:
    0 done, 2 usage error, a refused preflight, a busy legacy root, a root
    that cannot be created, or a legacy or council root that is a link, not
    a directory of the current user, writable by group or others, or inside
    the other, 3 a whole file migrate kept in both roots or beside its
    namesake, 4 nothing moved for the unmoved and conflict lines printed, 5
    a partial move: a file that failed after the check stays in DIR; any
    other code is a crash.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import shutil
import stat
import sys
import time
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

NAME = "agents-council"
SHARED = "agents-shared"
RELEASES = "agents-release"
QUEUE = "queue.json"
LOCK_SUFFIX = ".lock"
ARCHIVE = "archive"
RETIRED = ("gates", "pages")
RETIRE_DAYS = 30
DAY_SECONDS = 86400
LEGACY = Path("/tmp/agents-council")
DIRECTORY_MODE = 0o700
PART = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]*")
JOURNAL_SUFFIX = ".jsonl"
FILE_BITS = 0o755
MANAGED = Path("/etc/claude-code")
MARKER = "migrate.started"
STAGED = re.compile(r"\.[0-9a-f]{16}\.migrating\Z")
PROJECT_FILES = ("settings.json", "settings.local.json")
PROJECT_DEPTH = 8
PRUNED = frozenset({".git", "node_modules", ".venv", "venv", "__pycache__", ".tox", ".cache", ".mypy_cache", ".pytest_cache", ".ruff_cache", "site-packages"})
PKGMGR_DIRECTORIES = {"repositories": "~/Repositories/", "worktrees": "~/.local/share/worktrees/"}
NIGHT = "night.json"
SUSPENDED = ("suspend", "sunset")
LOCK_WAIT = 30
ENCODED = re.compile(r"[^A-Za-z0-9]")


def state_home() -> Path:
    state = os.environ.get("XDG_STATE_HOME", "")
    return Path(state) if os.path.isabs(state) else Path.home() / ".local" / "state"


def durable() -> Path:
    return state_home() / NAME


def root() -> Path:
    explicit = os.environ.get("AGENTS_COUNCIL_ROOT", "")
    return Path(explicit) if os.path.isabs(explicit) else state_home() / SHARED


def guard(base: Path, hook: bool) -> int | None:
    """Args:
        base: the council root.
        hook: True for a hook, which must never block on a broken root.

    Returns:
        None once the root exists as a directory of the current user that
        group and others cannot write; otherwise the exit code after the
        reason was printed: 0 for a hook (to stdout), 2 otherwise (to stderr).
    """
    stream, code = (sys.stdout, 0) if hook else (sys.stderr, 2)
    try:
        base.mkdir(mode=0o700, parents=True, exist_ok=True)
    except FileExistsError:
        pass
    except OSError as error:
        print(
            f"agents council: cannot create {base} ({error.strerror or error}); a sandbox needs it in allowWrite; "
            "the council hooks stay off until it exists",
            file=stream,
        )
        return code
    st = base.lstat()
    if stat.S_ISDIR(st.st_mode) and st.st_uid == os.getuid() and not st.st_mode & 0o022:
        return None
    print(
        f"agents council: {base} must be a directory of uid {os.getuid()} that group and others cannot write; "
        "the council hooks stay off until it is",
        file=stream,
    )
    return code


def directory(base: Path, *parts: str) -> Path:
    """Args:
        base: the directory the parts lie below; its missing parents are
            created with the default mode.
        parts: path segments, each matching PART.

    Returns:
        base/parts, each level from base down created with mode 700 where
        missing; ValueError for a part that does not match PART or a level
        that refusal() names: a link, not a directory of the current user,
        or writable by group or others.
    """
    bad = [part for part in parts if not PART.fullmatch(part)]
    if bad:
        raise ValueError(f"not a directory name: {bad[0]!r}")
    base.parent.mkdir(parents=True, exist_ok=True)
    levels = [base]
    for part in parts:
        levels.append(levels[-1] / part)
    for level in levels:
        with contextlib.suppress(FileExistsError):
            level.mkdir(mode=DIRECTORY_MODE)
        problem = refusal(level)
        if problem is not None:
            raise ValueError(problem)
    return levels[-1]


def nofollow() -> ModuleType:
    spec = importlib.util.spec_from_file_location("kvb_councilroot_nofollow", Path(__file__).resolve().parent / "nofollow.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def refusal(path: Path) -> str | None:
    info = path.lstat()
    if stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() and not info.st_mode & 0o022:
        return None
    return f"{path} must be a directory of uid {os.getuid()} that group and others cannot write"


def row_ids(text: str) -> list[tuple[str, str]] | None:
    """Returns:
        (id key, line) per non-empty line, the id serialised as JSON; None
        when a line is no JSON object with an id.
    """
    rows = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except (ValueError, RecursionError):
            return None
        if not isinstance(row, dict) or "id" not in row:
            return None
        rows.append((json.dumps(row["id"], sort_keys=True), line))
    return rows


def copied(helper: ModuleType, legacy: Path, source: Path, target_root: Path, target: Path) -> bool:
    """Returns:
        True once source is copied, with its mode and times, to a temp file
        that is then linked to the name target; False when target exists,
        which stays untouched.
    """
    *dirs, name = helper.parts_below(target_root, target)
    with open(helper.open_below(legacy, source, os.O_RDONLY, 0), "rb") as handle:
        info = os.fstat(handle.fileno())
        folder = helper.directory(target_root, tuple(dirs), True)
        temp = f".{name}.{os.urandom(8).hex()}"
        try:
            with open(os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=folder), "wb") as out:
                shutil.copyfileobj(handle, out)
                out.flush()
                os.fchmod(out.fileno(), info.st_mode & FILE_BITS)
                os.utime(out.fileno(), ns=(info.st_atime_ns, info.st_mtime_ns))
                os.fsync(out.fileno())
            try:
                os.link(temp, name, src_dir_fd=folder, dst_dir_fd=folder, follow_symlinks=False)
            except FileExistsError:
                return False
            return True
        finally:
            with contextlib.suppress(OSError):
                os.unlink(temp, dir_fd=folder)
            os.close(folder)


def content(helper: ModuleType, base: Path, path: Path) -> bytes:
    with open(helper.open_below(base, path, os.O_RDONLY, 0), "rb") as handle:
        return handle.read()


def novel(text: str, legacy_text: str) -> tuple[list[str], bool]:
    """Returns:
        The legacy lines text lacks and True when both are id journals: each
        id once; else each exact line as often as legacy_text holds it more
        often than text, and False.
    """
    ours, theirs = row_ids(text), row_ids(legacy_text)
    if ours is not None and theirs is not None:
        known, fresh = {key for key, _ in ours}, []
        for key, line in theirs:
            if key not in known:
                known.add(key)
                fresh.append(line)
        return fresh, True
    have, fresh = Counter(text.splitlines()), []
    for line in legacy_text.splitlines():
        if not line.strip():
            continue
        if have[line]:
            have[line] -= 1
        else:
            fresh.append(line)
    return fresh, False


def in_ts_order(lines: list[str]) -> list[str] | None:
    """Returns:
        lines stably sorted by their numeric ts; None when a line is no JSON
        object with one.
    """
    stamps = []
    for line in lines:
        try:
            row = json.loads(line)
        except (ValueError, RecursionError):
            return None
        stamp = row.get("ts") if isinstance(row, dict) else None
        if isinstance(stamp, bool) or not isinstance(stamp, int | float):
            return None
        stamps.append(stamp)
    return [line for _, line in sorted(zip(stamps, lines, strict=True), key=lambda pair: pair[0])]


def merged(helper: ModuleType, legacy: Path, source: Path, target_root: Path, target: Path) -> int:
    """Returns:
        The number of novel() legacy rows target gained, under the flock of
        target and of its <stem>.lock when one exists (the radio's lock):
        appended, or for a journal compared by line whose rows all carry a
        ts and would fall out of order, the whole file replaced in ts order.
    """
    legacy_text = helper.read_text(legacy, source)
    lock = target.with_suffix(LOCK_SUFFIX)
    with contextlib.ExitStack() as stack:
        if lock.is_file() and not lock.is_symlink():
            stack.enter_context(helper.locked(target_root, lock, 0o600, LOCK_WAIT))
        handle = stack.enter_context(open(helper.open_below(target_root, target, os.O_RDWR | os.O_APPEND, 0), "a+", encoding="utf-8", errors="replace"))
        handle.seek(0)
        fcntl.flock(handle, fcntl.LOCK_EX)
        text = handle.read()
        fresh, by_id = novel(text, legacy_text)
        lines = [line for line in text.splitlines() if line.strip()] + fresh
        order = None if by_id or not fresh else in_ts_order(lines)
        if order is None or order == lines:
            handle.write(("" if not fresh or not text or text.endswith("\n") else "\n") + "".join(f"{line}\n" for line in fresh))
        else:
            helper.replace(target_root, target, "".join(f"{line}\n" for line in order), os.fstat(handle.fileno()).st_mode & FILE_BITS)
    return len(fresh)


def beside(helper: ModuleType, legacy: Path, source: Path, target_root: Path, target: Path) -> Path:
    """Returns:
        target.legacy-<first 12 hex digits of the sha256 of source>, a copy
        of source beside target unless that name already holds it.
    """
    kept = target.with_name(f"{target.name}.legacy-{hashlib.sha256(content(helper, legacy, source)).hexdigest()[:12]}")
    copied(helper, legacy, source, target_root, kept)
    return kept


def destination(legacy: Path, source: Path, target_root: Path) -> Path:
    """Returns:
        The place of source below target_root, a staged() suffix dropped.
    """
    relative = source.relative_to(legacy)
    return target_root / relative.with_name(STAGED.sub("", relative.name))


def staged(helper: ModuleType, legacy: Path, source: Path) -> Path:
    """Returns:
        source renamed in its directory to <name>.<16 hex digits>.migrating,
        so a writer that opens the old name afterwards creates a new file the
        catch-up moves; source itself when it already carries such a name.
    """
    if STAGED.search(source.name):
        return source
    *dirs, name = helper.parts_below(legacy, source)
    stage = f"{name}.{os.urandom(8).hex()}.migrating"
    fd = helper.directory(legacy, tuple(dirs), False)
    try:
        os.rename(name, stage, src_dir_fd=fd, dst_dir_fd=fd)
    finally:
        os.close(fd)
    return source.with_name(stage)


def settle(helper: ModuleType, legacy: Path, source: Path, target_root: Path, catch_up: bool) -> tuple[str, str | None]:
    """Args:
        helper: nofollow.py.
        legacy: the earlier council root.
        source: a regular file below it.
        target_root: the council root.
        catch_up: keep a differing whole file beside its namesake instead of
            leaving it in legacy.

    Returns:
        (moved, merged, kept, conflict or unmoved, report line), the line
        None for a plain move or an identical copy; every copy is made from
        the staged() file, which a line naming a file left in legacy names.
    """
    target, stage = destination(legacy, source, target_root), source
    try:
        stage = staged(helper, legacy, source)
        if copied(helper, legacy, stage, target_root, target) or content(helper, legacy, stage) == content(helper, target_root, target):
            helper.unlink(legacy, stage)
            return "moved", None
        if target.suffix == JOURNAL_SUFFIX:
            count = merged(helper, legacy, stage, target_root, target)
            helper.unlink(legacy, stage)
            return "merged", f"merged {count} rows of {source} into {target}"
        if catch_up:
            kept = beside(helper, legacy, stage, target_root, target)
            helper.unlink(legacy, stage)
            return "kept", f"kept {source} beside {target} as {kept}"
        return "conflict", f"conflict {target} differs from {stage}; both kept"
    except OSError as error:
        return "unmoved", f"unmoved {stage}: {error.strerror or error}"


def held(helper: ModuleType, legacy: Path, stack: contextlib.ExitStack) -> list[str]:
    """Args:
        helper: nofollow.py.
        legacy: the earlier council root.
        stack: keeps every lock this takes until the move ends.

    Returns:
        Why the move must wait: each *.lock below legacy another process
        holds, and a queue.json with jobs or that cannot be read.
    """
    problems = []
    for folder, _, files in os.walk(legacy):
        for name in files:
            path = Path(folder) / name
            if not name.endswith(LOCK_SUFFIX) or not stat.S_ISREG(path.lstat().st_mode):
                continue
            try:
                lock = helper.open_below(legacy, path, os.O_RDONLY, 0)
                stack.callback(os.close, lock)
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                problems.append(f"{path} is held")
            except OSError as error:
                problems.append(f"{path} cannot be locked: {error.strerror or error}")
    queue = legacy / QUEUE
    if queue.exists() or queue.is_symlink():
        try:
            entries = json.loads(helper.read_text(legacy, queue)).get("entries")
        except (OSError, ValueError, AttributeError):
            entries = None
        if not isinstance(entries, list):
            problems.append(f"{queue} is unreadable")
        elif entries:
            problems.append(f"{queue} holds {len(entries)} queue jobs")
    return problems


def prune(helper: ModuleType, legacy: Path) -> None:
    for folder, _, _ in os.walk(legacy, topdown=False):
        here = Path(folder)
        if here == legacy:
            continue
        *dirs, name = helper.parts_below(legacy, here)
        with contextlib.suppress(OSError):
            fd = helper.directory(legacy, tuple(dirs), False)
            try:
                os.rmdir(name, dir_fd=fd)
            finally:
                os.close(fd)
    with contextlib.suppress(OSError):
        os.rmdir(legacy)


class Blocked(Exception):
    """Args:
        lines: the conflicts() lines that kept migrate from moving anything.
    """

    def __init__(self, lines: list[str]) -> None:
        super().__init__("; ".join(lines))
        self.lines = lines


def migrate(legacy: Path, target: Path, catch_up: bool = False) -> list[str]:
    """Args:
        legacy: the earlier council root.
        target: the council root.
        catch_up: move what conflicts() names too, keeping a differing whole
            file beside its namesake, instead of refusing.

    Returns:
        The report lines, the moved count first, the rest sorted; ValueError
        naming the refused root when either is a link, not a directory of the
        current user, writable by group or others, or lies inside the other,
        and naming every reason held() finds, moving nothing; without
        catch_up, Blocked naming every conflicts() line found under the
        held locks, moving nothing.
    """
    helper = nofollow()
    if not legacy.exists() and not legacy.is_symlink():
        unmark(helper)
        return []
    problem = refusal(legacy)
    if problem is not None:
        raise ValueError(problem)
    if legacy.resolve() == target.resolve():
        return []
    with contextlib.ExitStack() as stack:
        problems = held(helper, legacy, stack)
        if problems:
            raise ValueError("; ".join(problems) + "; nothing moved")
        blocked = [] if catch_up else conflicts(helper, legacy, target)
        if blocked:
            raise Blocked(blocked)
        return move(legacy, target, catch_up)


def move(legacy: Path, target: Path, catch_up: bool) -> list[str]:
    target.mkdir(mode=DIRECTORY_MODE, parents=True, exist_ok=True)
    problem = refusal(target)
    if problem is not None:
        raise ValueError(problem)
    old, new = legacy.resolve(), target.resolve()
    if old.is_relative_to(new) or new.is_relative_to(old):
        raise ValueError(f"{legacy} and {target} must not lie inside each other")
    helper = nofollow()
    host = directory(durable())
    helper.replace(host, host / MARKER, f"{legacy} -> {target}\n", 0o600)
    moved, lines = 0, []
    for folder, folders, files in os.walk(legacy):
        here = Path(folder)
        lines += [f"skipped {here / name}: a link" for name in folders if (here / name).is_symlink()]
        for name in sorted(files):
            source = here / name
            try:
                regular = stat.S_ISREG(source.lstat().st_mode)
            except OSError:
                continue
            if not regular:
                lines.append(f"skipped {source}: not a regular file")
                continue
            outcome, line = settle(helper, legacy, source, target, catch_up)
            moved += outcome == "moved"
            if line is not None:
                lines.append(line)
    prune(helper, legacy)
    unmark(helper)
    head = [f"moved {moved} files from {legacy} to {target}"] if moved else []
    return head + sorted(lines)


def unmark(helper: ModuleType) -> None:
    with contextlib.suppress(FileNotFoundError):
        helper.unlink(durable(), durable() / MARKER)


def unmovable(helper: ModuleType, legacy: Path, source: Path, target: Path, twin: Path) -> str | None:
    """Returns:
        The `unmoved` line migrate would print because source cannot be
        opened as it opens it, or a directory on the way to twin is a link
        or no directory; None when nothing stops the copy.
    """
    try:
        os.close(helper.open_below(legacy, source, os.O_RDONLY, 0))
        *dirs, _ = helper.parts_below(target, twin)
        with contextlib.suppress(FileNotFoundError):
            os.close(helper.directory(target, tuple(dirs), False))
    except OSError as error:
        return f"unmoved {source}: {error.strerror or error}"
    return None


def conflicts(helper: ModuleType, legacy: Path, target: Path) -> list[str]:
    """Returns:
        A line per regular file below legacy that migrate could not move, or
        that is no .jsonl journal and whose namesake below target differs.
    """
    lines = []
    for folder, _, files in os.walk(legacy):
        for name in files:
            source = Path(folder) / name
            twin = destination(legacy, source, target)
            if not stat.S_ISREG(source.lstat().st_mode):
                continue
            stuck = unmovable(helper, legacy, source, target, twin)
            if stuck is not None:
                lines.append(stuck)
                continue
            if not (twin.exists() or twin.is_symlink()):
                continue
            try:
                ours, theirs = content(helper, legacy, source), content(helper, target, twin)
            except OSError as error:
                lines.append(f"unmoved {source}: {error.strerror or error}")
                continue
            if ours != theirs and source.suffix != JOURNAL_SUFFIX:
                lines.append(f"conflict {twin} differs from {source}")
    return lines


def written(entry: object, base: Path) -> Path | None:
    """Args:
        entry: one allowWrite entry.
        base: the directory a relative entry lies below.

    Returns:
        The normalised path the entry names, a trailing /** dropped; None for
        anything but a string.
    """
    if not isinstance(entry, str):
        return None
    text = entry.removesuffix("/**").rstrip("/") or "/"
    path = Path(os.path.expanduser(text[1:] if text.startswith("//") else text))
    return Path(os.path.normpath(base / path))


def allowed(settings: Path, base: Path) -> list[tuple[str, Path]] | None:
    """Returns:
        (entry, path) per sandbox.filesystem.allowWrite entry of settings,
        relative ones below base; None when it holds no such list.
    """
    try:
        entries = json.loads(settings.read_text(encoding="utf-8"))["sandbox"]["filesystem"]["allowWrite"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not isinstance(entries, list):
        return None
    return [(entry, path) for entry in entries if (path := written(entry, base)) is not None]


def pkgmgr_roots() -> list[Path]:
    """Returns:
        The repositories and worktrees directories of the directories block
        of ~/.config/pkgmgr/config.yaml, pkgmgr's defaults where it names
        none.
    """
    found = dict(PKGMGR_DIRECTORIES)
    inside = False
    with contextlib.suppress(OSError):
        for line in (Path.home() / ".config" / "pkgmgr" / "config.yaml").read_text(encoding="utf-8").splitlines():
            text = line.split("#", 1)[0]
            if text[:1].strip():
                inside = text.strip() == "directories:"
                continue
            key, _, value = text.strip().partition(":")
            if inside and key in found and value.strip():
                found[key] = value.strip().strip("'\"")
    return [Path(os.path.expanduser(value)) for value in found.values()]


def settings_files(project: Path | None, managed: Path | None = None) -> list[Path]:
    """Args:
        project: the start directory of a session; None for only the managed
            and user files.
        managed: the managed settings directory, MANAGED unless given.

    Returns:
        Every Claude Code settings file that can apply there:
        managed-settings.json and managed-settings.d/*.json in name order,
        ~/.claude/settings.json and settings.local.json, then the project's
        .claude/settings.json and settings.local.json.
    """
    managed = managed or MANAGED
    files = [managed / "managed-settings.json", *sorted((managed / "managed-settings.d").glob("*.json"))]
    files += [Path.home() / ".claude" / name for name in PROJECT_FILES]
    return files + ([] if project is None else [project / ".claude" / name for name in PROJECT_FILES])


def settings_in(folder: Path) -> list[Path]:
    """Returns:
        folder/.claude/settings.json and settings.local.json where they are
        files, read through a link like Claude Code does.
    """
    return [path for name in PROJECT_FILES if (path := folder / ".claude" / name).is_file()]


def project_settings(top: Path) -> list[Path]:
    """Returns:
        The settings_in() of every directory at most PROJECT_DEPTH levels
        below top, in walk order, following directory links but entering each
        real directory once and never one of PRUNED.
    """
    found, seen = [], set()
    for folder, folders, _ in os.walk(top, followlinks=True):
        here = Path(folder)
        real = os.path.realpath(here)
        if real in seen:
            folders[:] = []
            continue
        seen.add(real)
        depth = len(here.relative_to(top).parts)
        folders[:] = sorted(name for name in folders if name not in PRUNED) if depth < PROJECT_DEPTH else []
        found += settings_in(here)
    return found


def decoded(folder: Path, rest: str) -> list[Path]:
    """Returns:
        Every directory below folder whose path after folder encodes to rest
        the way Claude Code names a project: each character but an ASCII
        letter or digit turned into '-'.
    """
    if not rest:
        return [folder]
    try:
        with os.scandir(folder) as entries:
            children = sorted((entry.name, entry.path) for entry in entries)
    except OSError:
        return []
    found = []
    for name, path in children:
        mark = "-" + ENCODED.sub("-", name)
        if rest.startswith(mark) and rest[len(mark):][:1] in ("", "-") and os.path.isdir(path):
            found += decoded(Path(path), rest[len(mark):])
    return found


def started(projects: Path) -> list[Path]:
    """Returns:
        The decoded() start directory of every Claude Code session folder
        below projects that still exists.
    """
    try:
        with os.scandir(projects) as entries:
            names = sorted(entry.name for entry in entries if entry.is_dir(follow_symlinks=False))
    except OSError:
        return []
    return [folder for name in names for folder in decoded(Path("/"), name)]


def sandbox_problems(settings: Path, managed: Path) -> list[str]:
    """Args:
        settings: the user settings file.
        managed: the managed settings directory.

    Returns:
        An add line per agent path the user file's allowWrite lacks, and a
        drop line per allowWrite entry that is the host-only root, inside it
        or above it, of settings, of a settings_files() file, of a
        project_settings() file below pkgmgr_roots(), or of a settings_in()
        file of a started() session directory; each real file once.
    """
    release, host = state_home() / RELEASES, durable()
    user = allowed(settings, settings.parent)
    if user is None:
        problems = [f"{settings} holds no sandbox.filesystem.allowWrite list; the operator adds {root()} and {release} there"]
    else:
        paths = {path for _, path in user}
        problems = [f"add {path} to sandbox.filesystem.allowWrite in {settings} (operator step)" for path in (root(), release) if path not in paths]
    files = [(path, path.parent) for path in (*settings_files(None, managed), settings)]
    files += [(path, path.parent.parent) for top in pkgmgr_roots() for path in project_settings(top)]
    files += [(path, path.parent.parent) for folder in started(Path.home() / ".claude" / "projects") for path in settings_in(folder)]
    unique: dict[tuple[str, Path], tuple[Path, Path]] = {}
    for file, base in files:
        unique.setdefault((os.path.realpath(file), base.resolve()), (file, base))
    for file, base in unique.values():
        problems += [
            f"{file}: drop allowWrite entry {entry!r} ({path}): the sandbox must never write the host-only {host}"
            for entry, path in allowed(file, base) or [] if path == host or path in host.parents or host in path.parents
        ]
    return problems


def suspended(legacy: Path) -> bool:
    """Returns:
        True when night.json exists in legacy or the council root and every
        one there is in a suspend mode.
    """
    helper, modes = nofollow(), []
    for base in (legacy, root()):
        with contextlib.suppress(OSError, ValueError, AttributeError):
            modes.append(json.loads(helper.read_text(base, base / NIGHT)).get("mode"))
    return bool(modes) and all(mode in SUSPENDED for mode in modes)


def preflight(settings: Path, managed: Path, legacy: Path) -> list[str]:
    """Args:
        settings: the user settings file, only read.
        managed: the managed settings directory, only read.
        legacy: the earlier council root.

    Returns:
        Every reason the install must stop before it copies anything: the
        sandbox_problems(), a refused council root, and for an existing
        legacy root its refusal, held() and conflicts().
    """
    problems = sandbox_problems(settings, managed)
    target = root()
    if target.exists() or target.is_symlink():
        problems += [problem for problem in (refusal(target),) if problem is not None]
    if not legacy.exists() and not legacy.is_symlink():
        return problems
    problem = refusal(legacy)
    if problem is not None:
        return [*problems, problem]
    helper = nofollow()
    with contextlib.ExitStack() as stack:
        problems += held(helper, legacy, stack)
    return problems + conflicts(helper, legacy, target)


def retire(base: Path, days: int, now: float) -> tuple[Path, int]:
    """Args:
        base: the council root.
        days: files changed longer ago than this move.
        now: the current epoch time.

    Returns:
        The dated archive directory and the number of files moved there.
    """
    helper = nofollow()
    archive = base / ARCHIVE / time.strftime("%Y-%m-%d", time.localtime(now))
    cutoff, count = now - days * DAY_SECONDS, 0
    for part in RETIRED:
        top = base / part
        if top.is_symlink() or not top.is_dir():
            continue
        for folder, _, files in os.walk(top):
            for name in files:
                path = Path(folder) / name
                info = path.lstat()
                if not stat.S_ISREG(info.st_mode) or info.st_mtime > cutoff:
                    continue
                *dirs, _ = helper.parts_below(base, path)
                source = helper.directory(base, tuple(dirs), False)
                try:
                    target = helper.directory(base, (*helper.parts_below(base, archive), *dirs), True)
                    try:
                        os.rename(name, name, src_dir_fd=source, dst_dir_fd=target)
                    finally:
                        os.close(target)
                finally:
                    os.close(source)
                count += 1
    return archive, count


def legacy_default() -> Path:
    return Path(os.environ.get("AGENTS_COUNCIL_LEGACY") or LEGACY)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="councilroot.py", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("root")
    commands.add_parser("durable")
    commands.add_parser("dir").add_argument("parts", nargs="+")
    commands.add_parser("release").add_argument("version")
    moving = commands.add_parser("migrate")
    moving.add_argument("--legacy", type=Path, default=legacy_default())
    moving.add_argument("--catch-up", action="store_true")
    check = commands.add_parser("preflight")
    check.add_argument("--legacy", type=Path, default=legacy_default())
    check.add_argument("--settings", type=Path, default=Path.home() / ".claude" / "settings.json")
    check.add_argument("--managed", type=Path, default=MANAGED)
    commands.add_parser("retire").add_argument("--days", type=int, default=RETIRE_DAYS)
    args = parser.parse_args(argv)
    try:
        if args.command == "root":
            print(root())
        elif args.command == "durable":
            print(durable())
        elif args.command == "dir":
            print(directory(root(), *args.parts))
        elif args.command == "release":
            print(directory(state_home() / RELEASES, args.version))
        elif args.command == "preflight":
            problems = preflight(args.settings, args.managed, args.legacy)
            for problem in problems:
                print(f"councilroot: preflight: {problem}", file=sys.stderr)
            if not suspended(args.legacy):
                print("councilroot: preflight: warning: the agents are not suspended (kvb-org-suspend); the install moves what they write meanwhile in a second migrate after the copy", file=sys.stderr)
            return 2 if problems else 0
        elif args.command == "retire":
            archive, count = retire(root(), args.days, time.time())
            print(f"archived {count} files into {archive}")
        else:
            try:
                report = migrate(args.legacy, root(), args.catch_up)
            except Blocked as blocked:
                print("\n".join([*blocked.lines, f"nothing moved from {args.legacy}"]))
                return 4
            print("\n".join(report) or f"nothing to move from {args.legacy}")
            for code, kinds in ((5, ("unmoved ",)), (3, ("conflict ", "kept "))):
                if any(line.startswith(kinds) for line in report):
                    return code
    except (OSError, ValueError) as error:
        print(f"councilroot: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
