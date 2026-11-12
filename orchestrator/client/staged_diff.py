"""Args:
    cwd: the working directory whose repository the diff is taken of.
    everything: False for the staged tree against HEAD (git diff --cached),
        True for what git commit -a records (every index path as it lies in
        the working tree) against HEAD.
    tree: for tree_diff, the tree object (git write-tree) diffed against
        HEAD instead of the live index.
    rules: the MEDUSA rules directory, None when MEDUSA is not installed.
    pinned: for bound_diff, what binding returned for the same cwd and everything.

Returns:
    review_diff, tree_diff, bound_diff: the review diff of requirement 003,
        one {path, status, mode, additions, deletions, patch, note} per
        changed path, sorted by path, status A, M, D or B (binary); path is
        the file name with bytes that are no UTF-8 written as backslash
        escapes; mode the git file mode, "old => new" when it changed (with
        everything, the executable bit on disk). patch holds the unified
        hunks; it is empty for a binary file, a gitlink, a side over
        BLOB_LIMIT bytes (counted 0/0), a path sandbox_paths denies (its
        FLOOR and the settings' deny lists) and every file past DIFF_LIMIT
        bytes of JSON-encoded patch text. A file whose old or new content
        holds an ARMOUR line or matches a MEDUSA secret rule for its name,
        and every file when no secret rule pattern loads, ships no patch,
        only its counts and the note WITHHELD. With everything, a working
        tree file over BLOB_LIMIT or under a denied path is not read and so
        always counts as changed. The diff fails when more than FILE_CAP
        paths changed or one is longer than PATH_LIMIT, a settings file
        sandbox_paths reads is unreadable, the working tree lies under a
        denied path, HEAD exists but its tree cannot be listed, HEAD is
        neither a commit nor unborn, or for bound_diff, the working tree
        changed while it was read.
    binding: what a commit records, for the permission hook to bind an
        allow to: the tree git write-tree prints; with everything, joined by
        the digest of every index path's mode and content id as it lies in
        the working tree, a file not read by its size, inode and times.
    commit_of: the directory and -a mode of a single git commit whose
        preview matches what it records, None for any other command.

Only git plumbing runs (rev-parse, symbolic-ref, ls-tree, ls-files, cat-file,
write-tree) with core.fsmonitor and lazy fetching off, and the diff itself is computed here:
the permission hook calls this outside the sandbox in a directory the agent
chose, where a planted repository config, filter, diff driver or promisor
remote must start no program, and a working tree path must not lead the read
through a symlinked directory, out of the working tree or into a path the
sandbox denies reading.
"""

from __future__ import annotations

import difflib
import fnmatch
import hashlib
import json
import os
import re
import shlex
import stat
import subprocess
from pathlib import Path

import hub_limits
import sandbox_paths

DIFF_LIMIT = hub_limits.DIFF_LIMIT
FILE_CAP = hub_limits.FILE_CAP
PATH_LIMIT = hub_limits.PATH_LIMIT
WITHHELD = hub_limits.WITHHELD
BLOB_LIMIT = 2 << 20
BINARY_PROBE = 8000
CONTEXT = 3
GIT_TIMEOUT = 30
GITLINK = "160000"
SYMLINK = "120000"
REGULAR = "100644"
EXECUTABLE = "100755"
SECRET_CWE = re.compile(r"CWE-(?:259|321|540|798)\b")
RULES_HOME = Path.home() / ".local" / "pipx" / "venvs" / "medusa-security" / "lib"
RULES_TAIL = "python3*/site-packages/medusa/rules"
CACHE = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "kvb-orchestrator" / "secret-rules.json"
UNREAD = "unread"
SAFE = ("git", "--no-pager", "--no-lazy-fetch", "-c", "core.fsmonitor=false")
COMMIT_LONGS = {
    "quiet", "verbose", "file", "author", "date", "message", "reedit-message", "reuse-message", "fixup", "squash", "reset-author", "trailer", "signoff",
    "template", "edit", "cleanup", "status", "gpg-sign", "all", "include", "interactive", "patch", "unified", "inter-hunk-context", "only", "no-verify",
    "dry-run", "short", "branch", "ahead-behind", "porcelain", "long", "null", "amend", "no-post-rewrite", "untracked-files", "pathspec-from-file",
    "pathspec-file-nul", "allow-empty", "allow-empty-message", "verify", "post-rewrite", "no-quiet", "no-verbose", "no-file", "no-author", "no-date",
    "no-message", "no-reedit-message", "no-reuse-message", "no-fixup", "no-squash", "no-reset-author", "no-trailer", "no-signoff", "no-template", "no-edit",
    "no-cleanup", "no-status", "no-gpg-sign", "no-all", "no-include", "no-interactive", "no-patch", "no-only", "no-dry-run", "no-short", "no-branch",
    "no-ahead-behind", "no-porcelain", "no-long", "no-null", "no-amend", "no-untracked-files", "no-pathspec-from-file", "no-pathspec-file-nul", "no-allow-empty",
    "no-allow-empty-message",
}
LONG_ARGS = {"message", "file", "reuse-message", "reedit-message", "template", "author", "date", "cleanup", "fixup", "squash", "trailer", "unified", "inter-hunk-context"}
NARROWING = {"only", "include", "interactive", "patch", "pathspec-from-file", "no-all"}
SHORT_ARGS = set("mFcCtuSU")
KEPT_VARS = {"GIT_EDITOR", "GIT_SEQUENCE_EDITOR", "GIT_PAGER", "GIT_TERMINAL_PROMPT", "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_AUTHOR_DATE", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "GIT_COMMITTER_DATE"}
ASSIGNMENT = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=.*")
ARMOUR = re.compile(r"-----BEGIN [A-Z0-9 ]+-----")
Patterns = list[re.Pattern]
Rules = list[tuple[tuple[str, ...], Patterns]]


class DiffError(Exception):
    pass


def git(cwd: Path, args: list[str], data: bytes | None) -> bytes:
    try:
        done = subprocess.run([*SAFE, *args], cwd=cwd, input=data, capture_output=True, timeout=GIT_TIMEOUT, check=False, env={**os.environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_NO_LAZY_FETCH": "1"})
    except (OSError, subprocess.TimeoutExpired) as error:
        raise DiffError(f"git {args[0]} failed to start: {error}") from error
    if done.returncode != 0:
        raise DiffError(f"git {' '.join(args)} failed: {done.stderr.decode('utf-8', 'replace').strip()}")
    return done.stdout


def listed(raw: bytes, object_field: int) -> dict[str, tuple[str, str]]:
    found = {}
    for record in raw.split(b"\0"):
        head, _, path = record.partition(b"\t")
        if path:
            fields = head.decode("ascii").split()
            found[path.decode("utf-8", "surrogateescape")] = (fields[0], fields[object_field])
    return found


def blob_sizes(cwd: Path, oids: set[str]) -> dict[str, int]:
    order = sorted(oids)
    lines = git(cwd, ["cat-file", "--batch-check"], "".join(f"{oid}\n" for oid in order).encode()).decode("ascii").splitlines() if order else []
    fields = {oid: line.split() for oid, line in zip(order, lines, strict=True)}
    missing = sorted(oid for oid, found in fields.items() if len(found) != 3)
    if missing:
        raise DiffError(f"objects missing from the repository: {' '.join(missing)}")
    return {oid: int(found[2]) for oid, found in fields.items()}


def blobs(cwd: Path, oids: set[str]) -> dict[str, bytes]:
    order = sorted(oids)
    if not order:
        return {}
    out = git(cwd, ["cat-file", "--batch"], "".join(f"{oid}\n" for oid in order).encode())
    found, at = {}, 0
    for oid in order:
        end = out.index(b"\n", at)
        size = int(out[at:end].split()[2])
        found[oid] = out[end + 1 : end + 1 + size]
        at = end + 2 + size
    return found


def worktree(top: Path, path: str, mode: str, algorithm: str, roots: list[str]) -> tuple[str, str, bytes | None] | None:
    """Args:
        top: the working tree, resolved through symlinks.
        roots: the paths the sandbox denies reading (sandbox_paths.denied_roots).

    Returns:
        The mode (for a regular file its executable bit on disk), blob id and
        content of an index path as it lies in the working tree; for a file
        over BLOB_LIMIT or under one of roots, which is not read, content
        None and in place of the blob id UNREAD with its size, inode and
        times; None when it is gone, lies behind a symlinked directory or is
        neither a regular file nor a symlink.

    Raises:
        DiffError: for a path with an empty, . or .. component.
    """
    parts = path.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise DiffError(f"index path {path!r} leaves the working tree")
    try:
        if sandbox_paths.denied(os.path.join(top, *parts), roots):
            return mode, unread(os.lstat(os.path.join(top, *parts))), None
        found = on_disk(top, parts)
    except OSError:
        return None
    if found is None:
        return None
    mode, data, info = found
    if data is None:
        return mode, unread(info), None
    return mode, hashlib.new(algorithm, b"blob %d\0" % len(data) + data).hexdigest(), data


def unread(info: os.stat_result) -> str:
    return f"{UNREAD}:{info.st_size}:{info.st_ino}:{info.st_mtime_ns}:{info.st_ctime_ns}"


def on_disk(top: Path, parts: list[str]) -> tuple[str, bytes | None, os.stat_result] | None:
    """Returns:
        The mode, content (None past BLOB_LIMIT) and status of top/parts,
        every folder from / on opened without following a symlink, None for
        an entry that is neither a regular file nor a symlink.
    """
    folder = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in [*top.parts[1:], *parts[:-1]]:
            inner = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=folder)
            os.close(folder)
            folder = inner
        return leaf(folder, parts[-1])
    finally:
        os.close(folder)


def leaf(folder: int, name: str) -> tuple[str, bytes | None, os.stat_result] | None:
    info = os.stat(name, dir_fd=folder, follow_symlinks=False)
    if stat.S_ISLNK(info.st_mode):
        return SYMLINK, os.readlink(name, dir_fd=folder).encode("utf-8", "surrogateescape"), info
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=folder)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            return None
        mode = EXECUTABLE if info.st_mode & stat.S_IXUSR else REGULAR
        if info.st_size > BLOB_LIMIT:
            return mode, None, info
        with open(fd, "rb", closefd=False) as handle:
            data = handle.read(BLOB_LIMIT + 1)
        return mode, data if len(data) <= BLOB_LIMIT else None, info
    finally:
        os.close(fd)


def toplevel(cwd: Path) -> Path:
    return Path(os.path.realpath(git(cwd, ["rev-parse", "--show-toplevel"], None).decode("utf-8", "surrogateescape").strip()))


def binding(cwd: Path, everything: bool) -> str:
    top = toplevel(cwd)
    tree = git(top, ["write-tree"], None).decode("ascii").strip()
    if not everything:
        return tree
    new, _ = working_side(top, denied_roots(top))
    return f"{tree} {hashlib.sha256(json.dumps(sorted(new.items())).encode('utf-8', 'surrogateescape')).hexdigest()}"


def bound_diff(cwd: Path, everything: bool, pinned: str, rules: Path | None) -> list[dict]:
    if not everything:
        return tree_diff(cwd, pinned, rules)
    diff = review_diff(cwd, True, rules)
    if binding(cwd, True) != pinned:
        raise DiffError("the working tree changed while its preview was read")
    return diff


def sides(cwd: Path, everything: bool, tree: str | None) -> tuple[dict, dict, dict[str, bytes | None]]:
    top = toplevel(cwd)
    roots = denied_roots(top)
    old = head_tree(top)
    if tree is not None:
        new, contents = listed(git(top, ["ls-tree", "-r", "-z", "--full-tree", tree], None), 2), {}
    elif everything:
        new, contents = working_side(top, roots)
    else:
        new, contents = listed(git(top, ["ls-files", "-s", "-z"], None), 1), {}
    contents.update(dict.fromkeys(side[path][1] for side in (old, new) for path in side if sandbox_paths.denied(os.path.join(top, path), roots)))
    return old, new, contents


def denied_roots(top: Path) -> list[str]:
    try:
        roots = sandbox_paths.denied_roots(top)
    except sandbox_paths.Unreadable as error:
        raise DiffError(str(error)) from error
    if sandbox_paths.denied(str(top), roots):
        raise DiffError(f"the working tree {top} lies under a path the sandbox denies reading")
    return roots


def head_tree(top: Path) -> dict[str, tuple[str, str]]:
    """Returns:
        The paths of HEAD's tree; none for an unborn HEAD, a symbolic ref
        to a branch that does not exist yet.

    Raises:
        DiffError: when HEAD resolves but its tree cannot be listed, or
            neither resolves nor is a symbolic ref.
    """
    try:
        git(top, ["rev-parse", "-q", "--verify", "HEAD"], None)
    except DiffError:
        git(top, ["symbolic-ref", "-q", "HEAD"], None)
        return {}
    return listed(git(top, ["ls-tree", "-r", "-z", "--full-tree", "HEAD"], None), 2)


def working_side(top: Path, roots: list[str]) -> tuple[dict, dict[str, bytes | None]]:
    algorithm = git(top, ["rev-parse", "--show-object-format"], None).decode("ascii").strip()
    new, contents = {}, {}
    for path, (mode, oid) in listed(git(top, ["ls-files", "-s", "-z"], None), 1).items():
        found = (mode, oid, None) if mode == GITLINK else worktree(top, path, mode, algorithm, roots)
        if found is not None:
            new[path] = found[:2]
            contents[found[1]] = found[2]
    return new, contents


def text_lines(text: str) -> list[str]:
    lines = text.split("\n")
    return lines[:-1] if lines[-1] == "" else lines


def secret_rules(root: Path | None) -> Rules | None:
    """Returns:
        Per MEDUSA rule whose cwe names hard-coded credentials, its file
        globs and compiled patterns (flags as MEDUSA compiles them); cached
        in CACHE until a rule file changes. None without rules or PyYAML,
        or when a rule file cannot be read or parsed.
    """
    if root is None or not root.is_dir():
        return None
    files = sorted(root.rglob("*.yaml"))
    signature = hashlib.sha256(json.dumps([[str(file.relative_to(root)), file.stat().st_size, file.stat().st_mtime_ns] for file in files]).encode()).hexdigest()
    try:
        cached = json.loads(CACHE.read_text(encoding="utf-8"))
        if cached.get("signature") == signature:
            return loaded(cached["rules"])
    except (OSError, ValueError, AttributeError, KeyError, TypeError):
        pass
    raw = parsed_rules(files)
    if raw is None:
        return None
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps({"signature": signature, "rules": raw}), encoding="utf-8")
    except OSError:
        pass
    return loaded(raw)


def loaded(raw: list) -> Rules:
    return [(tuple(map(str, globs)), compiled(list(map(str, patterns)))) for globs, patterns in raw]


def parsed_rules(files: list[Path]) -> list[list] | None:
    try:
        import yaml
    except ImportError:
        return None
    found = []
    for file in files:
        try:
            text = file.read_text(encoding="utf-8", errors="replace")
            data = (yaml.safe_load(text) or {}) if SECRET_CWE.search(text) else {}
        except (OSError, RecursionError, yaml.YAMLError):
            return None
        if not isinstance(data, list | dict):
            return None
        for rule in data if isinstance(data, list) else data.get("rules") or []:
            if isinstance(rule, dict) and SECRET_CWE.match(str(rule.get("cwe") or "")) and rule.get("patterns"):
                types = rule.get("file_types") or ["*"]
                globs = [str(kind) if "*" in str(kind) else f"*.{str(kind).lstrip('.')}" for kind in types]
                found.append([globs, [str(pattern) for pattern in rule["patterns"]]])
    return found


def compiled(patterns: list[str]) -> Patterns:
    found = []
    for pattern in patterns:
        try:
            found.append(re.compile(pattern, re.IGNORECASE | re.MULTILINE))
        except re.error:
            continue
    return found


def rules_root() -> Path | None:
    found = sorted(RULES_HOME.glob(RULES_TAIL))
    return found[-1] if found else None


def rule_patterns(path: str, rules: Rules) -> Patterns:
    name = Path(path).name.lower()
    return [pattern for globs, found in rules if any(fnmatch.fnmatchcase(name, glob.lower()) for glob in globs) for pattern in found]


def withheld(path: str, texts: tuple[str, str], rules: Rules | None) -> bool:
    if not rules or not any(patterns for _, patterns in rules):
        return True
    patterns = [ARMOUR, *rule_patterns(path, rules)]
    return any(pattern.search(text) for text in texts for pattern in patterns)


def entry(head: dict, before: bytes | None, after: bytes | None, rules: Rules | None) -> tuple[dict, list[str]]:
    """Args:
        head: the entry's path, status and mode.

    Returns:
        The diff entry without its patch, and the patch lines; no lines for
        a binary side, one over BLOB_LIMIT or content withheld.
    """
    found = {**head, "additions": 0, "deletions": 0, "note": ""}
    if before is None or after is None:
        return found, []
    if b"\0" in before[:BINARY_PROBE] or b"\0" in after[:BINARY_PROBE]:
        return {**found, "status": "B"}, []
    texts = (before.decode("utf-8", "replace"), after.decode("utf-8", "replace"))
    lines = list(difflib.unified_diff(*map(text_lines, texts), lineterm="", n=CONTEXT))[2:]
    found.update(additions=sum(1 for line in lines if line.startswith("+")), deletions=sum(1 for line in lines if line.startswith("-")))
    if withheld(head["path"], texts, rules):
        return {**found, "note": WITHHELD}, []
    return found, lines


def content_of(side: tuple[str, str] | None, gitlink: bool, contents: dict[str, bytes | None]) -> bytes | None:
    if side is None:
        return b""
    return None if gitlink else contents.get(side[1])


def review_diff(cwd: Path, everything: bool, rules: Path | None) -> list[dict]:
    return built(cwd, sides(cwd, everything, None), rules)


def tree_diff(cwd: Path, tree: str, rules: Path | None) -> list[dict]:
    return built(cwd, sides(cwd, False, tree), rules)


def fetched(cwd: Path, old: dict, new: dict, changed: list[str], contents: dict[str, bytes | None]) -> None:
    needed = {side[path][1] for side in (old, new) for path in changed if path in side and side[path][0] != GITLINK and side[path][1] not in contents}
    sizes = blob_sizes(cwd, needed)
    contents.update(blobs(cwd, {oid for oid in needed if sizes[oid] <= BLOB_LIMIT}))


def shown_path(path: str) -> str:
    shown = path.encode("utf-8", "surrogateescape").decode("utf-8", "backslashreplace")
    if len(shown) > PATH_LIMIT:
        raise DiffError(f"a changed path runs past {PATH_LIMIT} characters, the most a preview takes")
    return shown


def path_entry(path: str, before: tuple[str, str] | None, after: tuple[str, str] | None, contents: dict[str, bytes | None], rules: Rules | None) -> tuple[dict, list[str]]:
    status = "A" if before is None else "D" if after is None else "M"
    gitlink = any(side is not None and side[0] == GITLINK for side in (before, after))
    modes = list(dict.fromkeys(side[0] for side in (before, after) if side is not None))
    head = {"path": shown_path(path), "status": status, "mode": " => ".join(modes)}
    return entry(head, content_of(before, gitlink, contents), content_of(after, gitlink, contents), rules)


def built(cwd: Path, found_sides: tuple[dict, dict, dict[str, bytes | None]], rules: Path | None) -> list[dict]:
    old, new, contents = found_sides
    changed = sorted(path for path in {*old, *new} if old.get(path) != new.get(path))
    if len(changed) > FILE_CAP:
        raise DiffError(f"{len(changed)} paths changed, a preview lists at most {FILE_CAP}")
    for path in changed:
        shown_path(path)
    fetched(cwd, old, new, changed, contents)
    secrets = secret_rules(rules)
    diff, spent, full = [], 0, False
    for path in changed:
        found, lines = path_entry(path, old.get(path), new.get(path), contents, secrets)
        patch = "\n".join(lines)
        size = len(json.dumps(patch, ensure_ascii=False).encode("utf-8"))
        full = full or spent + size > DIFF_LIMIT
        if full:
            patch = ""
        else:
            spent += size
        diff.append({**found, "patch": patch})
    return diff


def commit_of(command: str, cwd: str) -> tuple[Path, bool] | None:
    """Returns:
        The directory git commit runs in and whether it records every
        tracked change (-a or --all), for a command that is one git commit,
        optionally behind variable assignments, env -C and git -C; None for
        any other command and for one whose commit the preview would not
        match (a pathspec, -o, -i, -p, --no-all, an unknown or ambiguous long
        option, git -c, or a GIT_ variable outside KEPT_VARS).
    """
    try:
        words = shlex.split(command)
    except ValueError:
        return None
    if any(word in {";", "&&", "||", "|", "&"} for word in words):
        return None
    place, words = launched(Path(cwd), words)
    if not words or Path(words[0]).name != "git":
        return None
    place, rest = past_git_options(place, words[1:])
    mode = commit_mode(rest[1:]) if rest else None
    return None if mode is None else (place, mode)


def launched(place: Path, words: list[str]) -> tuple[Path, list[str]]:
    """Returns:
        The directory and the words of the program a command starts, past
        variable assignments and env with -C or --chdir; no words when an
        assignment names a GIT_ variable outside KEPT_VARS or env takes
        another option.
    """
    words = past_assignments(words)
    if words and Path(words[0]).name == "env":
        place, words = past_env_options(place, words[1:])
        words = past_assignments(words)
    return place, words


def past_assignments(words: list[str]) -> list[str]:
    while words and (assigned := ASSIGNMENT.fullmatch(words[0])):
        if assigned.group(1).startswith("GIT_") and assigned.group(1) not in KEPT_VARS:
            return []
        words = words[1:]
    return words


def past_env_options(place: Path, words: list[str]) -> tuple[Path, list[str]]:
    while words and words[0].startswith("-"):
        if words[0] in ("-C", "--chdir") and len(words) > 1:
            place, words = place / words[1], words[2:]
        elif words[0].startswith("--chdir="):
            place, words = place / words[0].partition("=")[2], words[1:]
        else:
            return place, []
    return place, words


def past_git_options(place: Path, rest: list[str]) -> tuple[Path, list[str]]:
    while rest and rest[0] != "commit":
        if rest[0] == "-C" and len(rest) > 1:
            place, rest = place / rest[1], rest[2:]
        elif rest[0] in ("--no-pager", "-P", "--no-optional-locks"):
            rest = rest[1:]
        else:
            return place, []
    return place, rest


def commit_mode(words: list[str]) -> bool | None:
    """Returns:
        True for -a or --all, False for the staged tree, None when the
        commit records something else (NARROWING, -o, -i, -p or a pathspec).
    """
    skip, everything = False, False
    for at, word in enumerate(words):
        if skip:
            skip = False
            continue
        if word == "--":
            return None if words[at + 1 :] else everything
        found = option(word)
        if found is None:
            return None
        everything, skip = everything or found[0], found[1]
    return everything


def option(word: str) -> tuple[bool, bool] | None:
    """Returns:
        Whether a git commit option word is -a or --all and whether the next
        word is its argument, a long option named in full or by a prefix of
        exactly one of COMMIT_LONGS (what git 2.56 lists for git commit
        --git-completion-helper-all); None for NARROWING, -o, -i, -p, a
        pathspec and a long option it names no single one of.
    """
    if word.startswith("--"):
        name = long_option(word[2:].partition("=")[0])
        return None if name is None or name in NARROWING else (name == "all", name in LONG_ARGS and "=" not in word)
    if word.startswith("-") and word != "-":
        return cluster(word[1:])
    return None


def long_option(name: str) -> str | None:
    if name in COMMIT_LONGS:
        return name
    found = [known for known in COMMIT_LONGS if known.startswith(name)]
    return found[0] if len(found) == 1 else None


def cluster(letters: str) -> tuple[bool, bool] | None:
    """Returns:
        Whether a short option cluster holds -a and whether the next word is
        its argument; None when it holds -o, -i or -p.
    """
    everything = False
    for at, letter in enumerate(letters):
        if letter in "oip":
            return None
        everything = everything or letter == "a"
        if letter in SHORT_ARGS:
            return everything, at == len(letters) - 1 and letter in "mFcCtU"
    return everything, False
