#!/usr/bin/env python3
"""Scan the files a change touches with MEDUSA and fold the findings into one security percentage.

Args:
    --repo: git repository whose working tree holds the change.
    --base: git ref the change starts from.
    --json: print the figures as JSON instead of the line.

    accept --repo <root> --rule <rule_id> [--rule ...] --path <repo path> --sha1 <40 hex> [--line <n>] --reason <one line>:
        record reviewed false positives of one line instead, a row per rule; --json
        of a scan prints rule, path, line and sha1 of every finding. --line binds
        the row to that line's neighbourhood and is required when the line's text
        occurs more than once in the file.

Scan:
    The regular files `git diff <ref>` names plus untracked ones, symlinks left
    out, copied to a temporary tree and scanned once with
    `medusa scan <tree> --format json -o <dir> --no-cache --workers <w>`, w the
    files scanned but at most WORKERS, HOME pointing into the temporary
    directory because medusa creates ~/.medusa on start, read from
    `<dir>/medusa-scan-*.json`: a `findings` list whose entries carry
    `severity` (critical, high, medium, low or info), `rule_id`, `file` and `line`.
    medusa skips the SKIPPED suffixes (.mjs, .cjs, any case), so such a file is
    copied under its name with ALIAS (.js) appended, again while a path or
    folder of the change holds that name, or under the sha1 of its path with
    ALIAS when that file name would pass NAME_MAX bytes; its findings are
    fingerprinted from that copy and reported and accepted at its repository
    path. Rules, coverage and not covered judge the tree path medusa scans and
    name the repository path.
    Rules: medusa's own RULES, read without running medusa from the medusa
    package that the interpreter of medusa's shebang (an `env` program looked
    up on PATH) imports with medusa's environment: from core/parallel.py the
    extensions of FILE_SCANNERS, the exact names, the name prefixes and
    suffix, the top-level folders whose markdown it takes up and
    MAX_SCAN_FILE_SIZE; from scanners/base.py MAX_RULE_SCAN_LINES; from
    config.py the default exclude_paths and exclude_files. Without all of
    them no file can be proven covered and a diff with files gets no score.
    Not covered: a copied file of a type medusa never scans, or one its
    exclusions drop (a path part equal to or matching a path pattern, a path
    pattern anywhere inside the path, a file pattern), is named as such and
    left out of the score and its proof; a diff of such files only gets no
    score.
    Coverage, checked before medusa runs: no scanned file over medusa's
    MAX_SCAN_FILE_SIZE bytes (skipped) or MAX_RULE_SCAN_LINES lines, with CR,
    CRLF and LF as breaks as its scanners read text (regex scan cut). Such a
    file is never covered, on any run, so the scan stops there. After the run
    its report must prove it: its `scan_summary` counts every scanned file in
    `files_scanned` and, as medusa counts each file's LF bytes plus one and a
    skipped file as 0, their sum in `lines_scanned`. The run is complete only when medusa also exits 0 and its
    output names no FAULT (a scanner error or a timeout: a scanner over its
    per-file timeout, as under a fully loaded CPU, adds nothing to the report;
    a directory left unread, both printed by medusa's main process) and no
    SKIP. A SKIP line is a second signal only: medusa runs with `python -E`,
    so its pool workers print it into a buffer that dies with them.

Cache:
    The findings of a complete scan, keyed by the sha256 of this script, the
    resolved medusa binary with its mtime and size, PATH, the files not covered,
    every MEDUSA_* variable and the tree path, repository path, mode and
    content sha256 of every copied file, in
    <council root>/security-cache/<key>.json for CACHE_SECONDS. A later scan
    with the same key reads them instead of running medusa; any edit of a
    scanned file, of medusa or of this script misses. The folder is used only
    when it is a directory of the current user that neither group nor others
    may write, an entry only when it is a regular file of the current user.

Accepted:
    One JSON row per reviewed false positive (id, rule, path, sha1 of the stripped
    source line, or of the whole file for a finding without a line, context: the
    sha1 of the stripped lines up to REACH above and below it when accept got
    --line, reason, repo, date), appended by accept to
    <council root>/security-accepted.jsonl of the kvb-org-organize watch.py, whose
    hook keeps the rows in ~/.local/state/agents-council/security-accepted.jsonl;
    a scan reads both. A finding with that rule, path, text and context is
    accepted and leaves the score; a row without context accepts it only while no
    other finding of the scan shares its rule, path and text, so one acceptance
    never hides an identical line elsewhere. An edit of the line, its
    neighbourhood or the file brings it back. A row without rule, path and sha1
    is a usage error.

Output:
    `🛡️ security <n> % (medusa: <k> findings, <a> accepted in <m> files: <severity> <path>:<line>, ...; not covered: <path>, ...)`,
    `, <a> accepted` only when a is above 0, m the files scanned, the first 5
    locations by severity and `+<rest> more`, the first 5 files not covered
    and `+<rest> more` only when there are any.
    n = 100 - 50 * critical - 25 * high - 10 * medium - 2 * low, at least 0. Matched
    values are never printed. --json adds the counts per severity, every location
    with its rule and sha1, the accepted ones and every file not covered.

Exit codes:
    0 security 100, 1 a critical finding, 2 usage error, 3 under 100 without a
    critical finding, 4 medusa missing, its report or RULES unreadable, its
    run incomplete (rerun once the host is idle), a scanned file it never
    covers or a diff of files not covered only: review the diff by hand.
"""

from __future__ import annotations

import argparse
import ast
import datetime
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from collections import Counter
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath
from typing import NamedTuple

WEIGHTS = {"critical": 50, "high": 25, "medium": 10, "low": 2, "info": 0}
SAFE = 100
SHOWN = 5
REACH = 2
WORKERS = 4
SKIPPED = (".mjs", ".cjs")
ALIAS = ".js"
NAME_MAX = 255
CACHE = "security-cache"
CACHE_SECONDS = 24 * 3600
NOTHING = type(None)
SHAPE = {
    "severity": (str,), "rule": (str, NOTHING), "path": (str,), "line": (int, NOTHING),
    "sha1": (str, NOTHING), "context": (str, NOTHING),
}
SHA1 = re.compile(r"[0-9a-f]{40}")
FAULT = re.compile(r"scanner error\(s\)/timeout\(s\) during scan|could not be read and were skipped")
SKIP = re.compile(r"Skipped .+ exceeds .+ limit")
RULES = {
    "core/parallel.py": {
        "FILE_SCANNERS": dict, "special_exact_names": set, "special_prefixes": tuple, "env_suffix": str,
        "ai_context_dir_names": set, "MAX_SCAN_FILE_SIZE": int,
    },
    "scanners/base.py": {"MAX_RULE_SCAN_LINES": int},
    "config.py": {"exclude_paths": list, "exclude_files": list},
}
WILD = re.compile(r"[*?\[]")
LOCATE = (
    "import importlib.util\n"
    "spec = importlib.util.find_spec('medusa')\n"
    "print(*(spec.submodule_search_locations or []) if spec else [], sep='\\n')\n"
)
WATCH = Path(__file__).resolve().parents[2] / "kvb-org-organize" / "scripts" / "watch.py"
HAND = (
    "review trust boundaries, secrets and injection in the diff by hand, "
    "then pass --security '~<n>' to kvb-check-score"
)


class Unreadable(Exception):
    pass


class Incomplete(Exception):
    pass


class Uncovered(Exception):
    pass


class Rules(NamedTuple):
    extensions: frozenset
    names: frozenset
    prefixes: tuple
    suffix: str
    folders: frozenset
    file_limit: int
    line_limit: int
    paths: tuple
    files: tuple


def fail(message: str) -> None:
    print(f"security: {message}", file=sys.stderr)
    sys.exit(2)


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, check=False)
    if result.returncode != 0:
        fail(result.stderr.decode(errors="replace").strip() or f"git {args[0]} failed in {repo}")
    return result.stdout.decode(errors="replace")


def changed(root: Path, base: str) -> list[str]:
    # Trip-wire: with rename detection a moved file lists only its new path.
    listed = git(root, "diff", "--no-renames", "-z", "--name-only", base, "--")
    listed += git(root, "ls-files", "-z", "--others", "--exclude-standard")
    return sorted({p for p in listed.split("\0") if p})


def alias(name: str, taken: set[str]) -> str:
    """Returns:
        the tree path of name, whose suffix medusa skips: its file name with
        ALIAS appended, again while taken holds that path, or the sha1 of name
        treated the same way when that file name would pass NAME_MAX bytes.
    """
    folder = Path(name).parent
    for stem in (Path(name).name, digest(name)):
        scratch = stem + ALIAS
        while (folder / scratch).as_posix() in taken:
            scratch += ALIAS
        if len(os.fsencode(scratch)) <= NAME_MAX:
            break
    return (folder / scratch).as_posix()


def copy(root: Path, paths: list[str], tree: Path) -> dict[str, str]:
    """Returns:
        the tree path of every copied file mapped to its repository path.
    """
    names = {}
    taken = set(paths) | {parent.as_posix() for name in paths for parent in Path(name).parents}
    for name in paths:
        source = root / name
        # Trip-wire: a symlink's target may lie outside the repository; even a copied link lets the scan read it.
        if source.is_symlink() or not source.is_file():
            continue
        scratch = name
        if Path(name).suffix.lower() in SKIPPED:
            scratch = alias(name, taken)
            taken.add(scratch)
        target = tree / scratch
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        names[scratch] = name
    return names


def located(name: str, tree: Path) -> str:
    path = Path(name)
    if not path.is_absolute():
        path = tree / path if (tree / path).exists() else tree.parent / path
    try:
        return path.resolve().relative_to(tree.resolve()).as_posix()
    except ValueError:
        return name


def digest(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()


def fingerprint(tree: Path, path: str, line: int | None) -> tuple[str | None, str | None]:
    """Returns:
        (sha1 of the stripped line or of the whole file without a line, sha1 of
        the stripped lines up to REACH around the line or None), (None, None) for
        an unreadable file or a line outside it.
    """
    try:
        text = (tree / path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None, None
    if line is None:
        return digest(text), None
    rows = text.splitlines()
    if not 1 <= line <= len(rows):
        return None, None
    around = rows[max(0, line - 1 - REACH):line + REACH]
    return digest(rows[line - 1].strip()), digest("\n".join(row.strip() for row in around))


def watch():
    if not WATCH.is_file():
        fail(f"{WATCH} is missing; its council paths hold the accepted findings")
    spec = importlib.util.spec_from_file_location("kvb_security_watch", WATCH)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def accepted(listings: tuple[Path, ...]) -> set[tuple[str, str, str, str | None]]:
    entries = set()
    for listing in listings:
        if not listing.is_file():
            continue
        for number, line in enumerate(listing.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                entries.add((row["rule"], row["path"], row["sha1"], row.get("context")))
            except (ValueError, KeyError, TypeError, AttributeError):
                fail(f"{listing}:{number}: want a JSON row with rule, path and sha1")
    return entries


def covered(finding: dict, reviewed: set[tuple[str, str, str, str | None]], shared: Counter) -> bool:
    key = (finding["rule"], finding["path"], finding["sha1"])
    return (*key, finding["context"]) in reviewed or (shared[key] == 1 and (*key, None) in reviewed)


def accept(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="security.py accept", description="Record a reviewed false positive.")
    for flag in ("--repo", "--path", "--sha1", "--reason"):
        parser.add_argument(flag, required=True)
    parser.add_argument("--rule", action="append", required=True)
    parser.add_argument("--line", type=int)
    args = parser.parse_args(argv)
    if not SHA1.fullmatch(args.sha1):
        parser.error("--sha1 must be 40 lowercase hex digits")
    if not args.reason.strip() or "\n" in args.reason:
        parser.error("--reason must be one non-empty line")
    root = git(Path(args.repo), "rev-parse", "--show-toplevel").strip()
    context = None
    if args.line is not None:
        sha1, context = fingerprint(Path(root), args.path, args.line)
        if sha1 != args.sha1:
            parser.error(f"--sha1 is not the sha1 of line {args.line} of {args.path}")
    else:
        try:
            rows = (Path(root) / args.path).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            rows = []
        twins = sum(digest(row.strip()) == args.sha1 for row in rows)
        if twins > 1:
            parser.error(f"the line occurs {twins} times in {args.path}; name the reviewed one with --line")
    date = datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")
    rows = [
        {
            "id": digest("\t".join([rule, args.path, args.sha1, *([context] if context else [])])), "rule": rule,
            "path": args.path, "sha1": args.sha1, **({"context": context} if context else {}),
            "reason": args.reason, "repo": root, "date": date,
        }
        for rule in args.rule
    ]
    target = watch().ACCEPTED
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as listing:
        fcntl.flock(listing, fcntl.LOCK_EX)
        listing.write("".join(json.dumps(row) + "\n" for row in rows))
    print(f"accepted {', '.join(args.rule)} {args.path} ({args.sha1[:12]}) in {target}")
    return 0


def findings(reports: Path, tree: Path, names: dict[str, str]) -> tuple[list[dict], dict]:
    """Returns:
        the findings of medusa's report at their repository paths and its `scan_summary`.
    """
    files = sorted(reports.glob("medusa-scan-*.json")) if reports.is_dir() else []
    if not files:
        raise Unreadable(f"no medusa-scan-*.json in {reports}")
    try:
        report = json.loads(files[-1].read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise Unreadable(f"{files[-1].name}: {error}") from None
    entries = report.get("findings") if isinstance(report, dict) else None
    if not isinstance(entries, list):
        raise Unreadable(f"{files[-1].name} holds no findings list")
    summary = report.get("scan_summary")
    if not isinstance(summary, dict) or any(type(summary.get(k)) is not int for k in ("files_scanned", "lines_scanned")):
        raise Unreadable(f"{files[-1].name} holds no files_scanned and lines_scanned counts")
    found = []
    for entry in entries:
        severity = str(entry.get("severity", "")).lower() if isinstance(entry, dict) else ""
        if severity not in WEIGHTS:
            raise Unreadable(f"{files[-1].name}: a finding without a known severity")
        line = entry.get("line") if isinstance(entry.get("line"), int) else None
        scratch = located(str(entry.get("file") or "?"), tree)
        sha1, context = fingerprint(tree, scratch, line)
        found.append({
            "severity": severity,
            "rule": entry.get("rule_id") if isinstance(entry.get("rule_id"), str) else None,
            "path": names.get(scratch, scratch),
            "line": line,
            "sha1": sha1,
            "context": context,
        })
    rank = list(WEIGHTS)
    return sorted(found, key=lambda f: (rank.index(f["severity"]), f["path"], f["line"] or 0)), summary


def interpreter(medusa: str) -> list[str] | None:
    """Returns:
        the interpreter command of the medusa script's shebang, its `env`
        program looked up on PATH, else None.
    """
    try:
        head = Path(medusa).resolve().read_bytes().split(b"\n", 1)[0].decode()
    except (OSError, UnicodeDecodeError):
        return None
    words = head[2:].split() if head.startswith("#!") else []
    if words and Path(words[0]).name == "env":
        named = [word for word in words[1:] if not word.startswith("-") and "=" not in word]
        program = shutil.which(named[0]) if named else None
        words = [program, *words[words.index(named[0]) + 1:]] if program else []
    return words or None


def package(medusa: str, work: Path, env: dict[str, str]) -> Path | None:
    """Returns:
        the folder of the medusa package that medusa's own interpreter imports
        with medusa's environment, else None.
    """
    command = interpreter(medusa)
    if command is None:
        return None
    try:
        result = subprocess.run(
            [*command, "-c", LOCATE], cwd=work, stdin=subprocess.DEVNULL, capture_output=True, check=False,
            env=env, timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    folders = result.stdout.decode(errors="replace").splitlines() if result.returncode == 0 else []
    return Path(folders[0]) if folders and folders[0] else None


def literal(node: ast.expr | None) -> object:
    """Returns:
        the value of a literal, of an integer product, sum or difference, or of
        a field's default_factory lambda; raises ValueError for anything else.
    """
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Mult, ast.Add, ast.Sub)):
        left, right = literal(node.left), literal(node.right)
        if type(left) is not int or type(right) is not int:
            raise ValueError("not an integer")
        return left * right if isinstance(node.op, ast.Mult) else left + right if isinstance(node.op, ast.Add) else left - right
    factory = [k.value for k in node.keywords if k.arg == "default_factory"] if isinstance(node, ast.Call) else []
    if factory and isinstance(factory[0], ast.Lambda):
        return literal(factory[0].body)
    if node is None:
        raise ValueError("assigned more than once or not at all")
    return ast.literal_eval(node)


def assigned(path: Path, names: dict[str, type]) -> dict[str, object]:
    """Returns:
        the value of each name assigned exactly once in the module at path,
        checked against its type; raises ValueError for any other.
    """
    found = {}
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        target = node.targets[0] if isinstance(node, ast.Assign) and len(node.targets) == 1 else None
        target = node.target if isinstance(node, ast.AnnAssign) and node.value else target
        if isinstance(target, ast.Name) and target.id in names:
            found[target.id] = None if target.id in found else node.value
    values = {name: literal(found.get(name)) for name in names}
    if any(type(values[name]) is not kind or kind in (str, int) and not values[name] for name, kind in names.items()):
        raise ValueError("a rule of an unexpected shape")
    return values


def rules(folder: Path | None) -> Rules | None:
    """Returns:
        medusa's RULES from its package folder, else None when one is missing.
    """
    try:
        values = {name: value for file, names in RULES.items() for name, value in assigned(folder / file, names).items()}
    except (OSError, SyntaxError, ValueError, TypeError):
        return None
    strings = (*values["FILE_SCANNERS"], *values["special_exact_names"], *values["special_prefixes"],
               *values["ai_context_dir_names"], *values["exclude_paths"], *values["exclude_files"])
    if not all(isinstance(item, str) and item for item in strings):
        return None
    return Rules(
        frozenset(values["FILE_SCANNERS"]), frozenset(values["special_exact_names"]), values["special_prefixes"],
        values["env_suffix"], frozenset(values["ai_context_dir_names"]), values["MAX_SCAN_FILE_SIZE"],
        values["MAX_RULE_SCAN_LINES"], tuple(path.rstrip("/") for path in values["exclude_paths"]),
        tuple(values["exclude_files"]),
    )


def taken(name: str, found: Rules) -> bool:
    """Returns:
        whether medusa's find_scannable_files takes up a file of this tree path:
        a type it scans, and no exclusion that drops it.
    """
    path = PurePosixPath(name)
    extension = os.path.splitext(path.name)[1].lower()
    typed = (
        extension in found.extensions or path.name in found.names or path.name.startswith(found.prefixes)
        or path.name.endswith(found.suffix)
        or (len(path.parts) == 2 and path.parts[0] in found.folders and extension == ".md")
    )
    dropped = (
        any(part == pattern or WILD.search(pattern) and fnmatchcase(part, pattern)
            for part in path.parts for pattern in found.paths)
        or any(pattern in name or WILD.search(pattern) and fnmatchcase(name, f"*{pattern}*") for pattern in found.paths)
        or any(fnmatchcase(path.name, pattern) for pattern in found.files)
    )
    return typed and not dropped


def sized(tree: Path) -> dict[str, tuple[int, int, int]]:
    """Returns:
        of every file in the tree by its tree path: its bytes, its LF bytes
        plus one as medusa's `lines_scanned` counts them, and its lines with
        CR, CRLF and LF as breaks, as medusa's scanners read them in text mode.
    """
    sizes = {}
    for path in sorted(p for p in tree.rglob("*") if p.is_file()):
        data = path.read_bytes()
        breaks = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n").count(b"\n")
        sizes[path.relative_to(tree).as_posix()] = (len(data), data.count(b"\n") + 1, breaks + 1)
    return sizes


def oversized(sizes: dict[str, tuple[int, int, int]], found: Rules) -> str | None:
    """Returns:
        the first file over medusa's file or line limit with the limit it breaks, else None.
    """
    for name, (size, _, lines) in sizes.items():
        if size > found.file_limit:
            return f"{name} has {size} bytes, over medusa's {found.file_limit} byte file limit"
        if lines > found.line_limit:
            return f"{name} has {lines} lines, over medusa's {found.line_limit} line regex limit"
    return None


def uncovered(said: list[str], summary: dict, sizes: dict[str, tuple[int, int, int]]) -> str | None:
    """Returns:
        why medusa never covers the scanned files: its SKIP line, or the count
        it took up when it is not every scanned one, else None.
    """
    for line in said:
        if SKIP.search(line):
            return line
    if summary["files_scanned"] != len(sizes):
        return f"medusa took up {summary['files_scanned']} of {plural(len(sizes), 'file')} its rules take up"
    return None


def cut(code: int, said: list[str], summary: dict, sizes: dict[str, tuple[int, int, int]]) -> str | None:
    """Returns:
        why this run fell short: a non-zero exit, its FAULT line or fewer
        `lines_scanned` than the scanned files hold, else None.
    """
    if code:
        return f"medusa exit {code}"
    for line in said:
        if FAULT.search(line):
            return line
    expected = sum(counted for _, counted, _ in sizes.values())
    if summary["lines_scanned"] != expected:
        return f"medusa counted {summary['lines_scanned']} of {expected} lines"
    return None


def keyed(medusa: str, tree: Path, names: dict[str, str], missed: list[str]) -> str:
    binary = Path(medusa).resolve()
    info = binary.stat()
    key = hashlib.sha256(Path(__file__).read_bytes())
    key.update(f"\0{binary}\0{info.st_mtime_ns}\0{info.st_size}\0{os.environ.get('PATH', '')}\0".encode())
    key.update("".join(f"{name}\0" for name in missed).encode() + b"\0")
    key.update("".join(f"{k}={v}\0" for k, v in sorted(os.environ.items()) if k.startswith("MEDUSA_")).encode())
    for scratch, name in sorted(names.items()):
        path = tree / scratch
        key.update(f"{scratch}\0{name}\0{path.stat().st_mode & 0o777:o}\0".encode())
        key.update(hashlib.sha256(path.read_bytes()).digest())
    return key.hexdigest()


def shelf(root: Path) -> Path | None:
    folder = root / CACHE
    try:
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = folder.lstat()
    except OSError:
        return None
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
        return None
    return folder


def recalled(folder: Path, key: str) -> list[dict] | None:
    entry = folder / f"{key}.json"
    try:
        info = entry.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or time.time() - info.st_mtime > CACHE_SECONDS:
            return None
        found = json.loads(entry.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(found, list) or not all(
        isinstance(f, dict) and f.keys() == SHAPE.keys() and all(isinstance(f[k], t) for k, t in SHAPE.items())
        and f["severity"] in WEIGHTS
        for f in found
    ):
        return None
    return found


def remember(folder: Path, key: str, found: list[dict]) -> None:
    now = time.time()
    for old in folder.glob("*.json"):
        try:
            if now - old.lstat().st_mtime > CACHE_SECONDS:
                old.unlink()
        except OSError:
            continue
    try:
        descriptor, name = tempfile.mkstemp(dir=folder, prefix=".", suffix=".tmp")
    except OSError:
        return
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(found, handle)
        os.replace(name, folder / f"{key}.json")
    except OSError:
        Path(name).unlink(missing_ok=True)


def scan(medusa: str, root: Path, base: str, cache: Path | None) -> tuple[int, list[dict], list[str]]:
    """Returns:
        the count of scanned files, their findings and the repository paths
        of the copied files medusa never takes up.
    """
    with tempfile.TemporaryDirectory(prefix="kvb-security-") as scratch:
        work = Path(scratch)
        tree, reports, home = work / "tree", work / "reports", work / "home"
        tree.mkdir()
        home.mkdir()
        names = copy(root, changed(root, base), tree)
        if not names:
            return 0, [], []
        env = {**os.environ, "HOME": str(home)}
        known = rules(package(medusa, work, env))
        if known is None:
            raise Uncovered("medusa's own types, exclusions and limits are unreadable from its source")
        sizes = {names[scratch]: size for scratch, size in sized(tree).items() if taken(scratch, known)}
        missed = sorted(set(names.values()) - sizes.keys())
        scanned = len(sizes)
        if not scanned:
            raise Uncovered(f"medusa scans none of its files, not covered: {shown(missed)}")
        over = oversized(sizes, known)
        if over:
            raise Uncovered(over)
        key = keyed(medusa, tree, names, missed)
        hit = recalled(cache, key) if cache else None
        if hit is not None:
            return scanned, hit, missed
        result = subprocess.run(
            [medusa, "scan", str(tree), "--format", "json", "-o", str(reports), "--no-cache",
             "--workers", str(min(scanned, WORKERS))],
            cwd=work, stdin=subprocess.DEVNULL, capture_output=True, check=False, env=env,
        )
        try:
            found, summary = findings(reports, tree, names)
        except Unreadable as error:
            raise Unreadable(f"{error} (medusa exit {result.returncode})") from None
        said = [line.replace(f"{tree}/", "").strip(" \t!⚠️") for line in result.stdout.decode(errors="replace").splitlines()]
        never = uncovered(said, summary, sizes)
        if never:
            raise Uncovered(never)
        short = cut(result.returncode, said, summary, sizes)
        if short:
            raise Incomplete(short)
        if cache:
            remember(cache, key, found)
        return scanned, found, missed


def plural(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"


def shown(items: list[str]) -> str:
    return ", ".join(items[:SHOWN]) + (f", +{len(items) - SHOWN} more" if len(items) > SHOWN else "")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    repo = Path(args.repo)
    if not repo.is_dir():
        fail(f"{repo} is not a directory")
    root = Path(git(repo, "rev-parse", "--show-toplevel").strip())
    if subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"{args.base}^{{commit}}"], cwd=root, capture_output=True, check=False
    ).returncode != 0:
        fail(f"unknown ref {args.base!r}")

    council = watch()
    reviewed = accepted((council.ACCEPTED, council.KEPT_ACCEPTED))
    medusa = shutil.which("medusa")
    problem = None if medusa else "medusa missing"
    if medusa:
        try:
            scanned, every, missed = scan(medusa, root, args.base, shelf(council.ROOT))
        except Unreadable as error:
            problem = f"medusa report unreadable: {error}"
        except Incomplete as error:
            problem = f"medusa run incomplete, nothing cached, rerun once the host is idle: {error}"
        except Uncovered as error:
            problem = f"medusa never covers this diff, nothing cached: {error}"
    if problem:
        if args.json:
            print(json.dumps({"security": None, "problem": problem}))
        else:
            print(f"🛡️ security – ({problem}: {HAND})")
        return 4

    shared = Counter((f["rule"], f["path"], f["sha1"]) for f in every)
    passed = [f for f in every if covered(f, reviewed, shared)]
    found = [f for f in every if f not in passed]
    counts = {severity: sum(f["severity"] == severity for f in found) for severity in WEIGHTS}
    value = max(0, SAFE - sum(WEIGHTS[s] * n for s, n in counts.items()))
    if args.json:
        print(json.dumps({
            "security": value, "files": scanned, **counts, "findings": found, "accepted": passed, "not_covered": missed,
        }))
    else:
        places = [f"{f['severity']} {f['path']}:{f['line'] if f['line'] is not None else '?'}" for f in found]
        detail = f": {shown(places)}" if places else ""
        waived = f", {len(passed)} accepted" if passed else ""
        rest = f"; not covered: {shown(missed)}" if missed else ""
        print(
            f"🛡️ security {value} % (medusa: {plural(len(found), 'finding')}{waived} "
            f"in {plural(scanned, 'file')}{detail}{rest})"
        )
    if counts["critical"]:
        return 1
    return 3 if value < SAFE else 0


if __name__ == "__main__":
    sys.exit(accept(sys.argv[2:]) if sys.argv[1:2] == ["accept"] else main())
