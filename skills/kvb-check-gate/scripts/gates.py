#!/usr/bin/env python3
"""Gate rules, branch parents and gate receipts of every repository on this host.

Args:
    --db: the SQLite database of rules and parents, default
        ~/.local/state/agents-council/gates.db (GATES_DB overrides it); it
        survives reboots, the council root under /tmp does not. Only rule and
        parents add|drop|derive write it; every other command opens it
        read-only and an absent one as empty.

    rule set --repo R --branch B --action A --level L: the branch's own level
        for one action. rule drop --repo R --branch B --action A removes it.
    parents add|drop --repo R --branch B --parent P [--source S]: one parent
        edge; S is recorded, derived or operator (default operator). drop
        keeps the edge as dropped, so a recorded row of the journal stays out.
    parents derive --repo R: gives every local branch without a parent, except
        the default branch, the nearest local branches whose tip is its
        ancestor, as derived parents.
    parents record --worktree W: when W's branch has a single reflog entry, so
        it was just created, every other branch whose local or remote-tracking
        tip (origin/main counts as main) is its start commit becomes a
        recorded parent, else the default branch; prints them.
    resolve --repo R --branch B --action A: prints `<level>\t<source>`, the
        branch's own level, else the strictest resolved level of all its
        parents, else `none\t-`.
    tree --worktree W: prints the tree sha of everything W holds, tracked,
        staged, unstaged and untracked, ignored files left out.
    quick --worktree W: the quick checks of the staged files, every file of
        W's index: Python syntax, JSON, `bash -n` for .sh, then `git diff
        --cached --check`; nothing else runs. Green records a quick receipt
        for the index tree.
    receipt add --repo R --tree T --level L --log P: records a green gate.
    receipt check --repo R --tree T --level L: exit 0 when a receipt for T
        meets L, else 1.
    hooks install --repo R: writes pre-commit, commit-msg, pre-merge-commit,
        pre-push and post-checkout into R's hooks directory, each running
        `gates.py hook <name>`, and changes no git config; refuses before
        writing any while one of them exists that gates.py did not write.
    hook NAME [ARG...]: what the installed hook NAME runs, in the directory
        git runs it in. pre-commit: quick. commit-msg and pre-merge-commit:
        the index tree on the current branch, action commit (plus merge while
        MERGE_HEAD or SQUASH_MSG exists, so neither a refused merge nor a
        squash lands by a commit unwarned) and merge; on a detached HEAD the
        branch a rebase works on, else the default branch. pre-push: the
        tree of every pushed commit (stdin), action push on its local and its
        remote branch and action merge on the remote branch, so a
        fast-forward or squash merge, which no merge hook sees, meets the
        branch's merge level before it leaves. Each passes when a receipt for the tree meets the resolved
        level, else prints the command that produces it and exits 1:
        `gates.py quick` for quick; above it `queue.py hold --receipt <level>`
        of `make <level>` with INFINITO_TEST_GPU=false, held as kind
        quality-high for e2e, else as the level, with the open register task
        whose branch is B. post-checkout: parents record on a branch
        checkout; it exits 0 even when recording fails.
    show --json [--repo R]: {repo: {branch: {parents: [{parent, source}],
        rules: {action: level}, resolved: {action: {level, source}}}}} for the
        local branches of R, or of every repository the database or the
        parents journal knows.

    R is any path inside the repository; it is stored as the absolute path of
    the main checkout, so linked worktrees share it.

Journals:
    Receipts {id, repo, tree, level, gpu, log, at} and recorded parents {id,
    repo, branch, parent} are rows of gate-receipts.jsonl and
    gate-parents.jsonl in the council root (AGENTS_COUNCIL_ROOT, else
    /tmp/agents-council), which sandboxed agents can write; the watch hook of
    kvb-org-organize copies them to ~/.local/state/agents-council, and reading
    merges both by id; a row whose id is no string is skipped. A receipt
    carries INFINITO_TEST_GPU of the environment that wrote it as gpu; it
    meets its own level and every lower one, above quick only with gpu
    `false`, and only for 30 days (RECEIPT_SECONDS): every receipt written prunes the
    older ones from both files where they are writable. A row of the
    database for an edge wins over a recorded one.

Exit codes:
    0 done, 1 a receipt check, quick check or hook that fails, 2 usage error.
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import importlib.util
import json
import os
import re
import shlex
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import ModuleType

LEVELS = ("none", "quick", "test", "quality-high", "e2e")
ACTIONS = ("commit", "merge", "push", "pr")
SOURCES = ("recorded", "derived", "operator")
DROPPED = "dropped"
DEFAULT_DB = Path.home() / ".local" / "state" / "agents-council" / "gates.db"
SKILLS = Path(__file__).resolve().parents[2]
QUEUE = SKILLS / "kvb-org-queue" / "scripts" / "queue.py"
RASCI = SKILLS / "kvb-org-rasci" / "scripts" / "rasci.py"
HOOKS = ("pre-commit", "commit-msg", "pre-merge-commit", "pre-push", "post-checkout")
HOOK = '#!/bin/sh\nexec python3 {script} hook {name} "$@"\n'
OURS = re.compile(r"^exec python3 \S*gates\.py'? hook ", re.MULTILINE)
KINDS = {"test": "test", "quality-high": "quality-high", "e2e": "quality-high"}
ZERO = re.compile(r"0+")
GPU_OFF = "false"
RECEIPT_SECONDS = 30 * 24 * 3600
MERGE_STATES = ("MERGE_HEAD", "SQUASH_MSG")
REBASE_HEADS = ("rebase-merge/head-name", "rebase-apply/head-name")
FILE_MODE = 0o600
SCHEMA = """
CREATE TABLE IF NOT EXISTS rules (repo TEXT, branch TEXT, action TEXT, level TEXT, set_at REAL,
    PRIMARY KEY (repo, branch, action));
CREATE TABLE IF NOT EXISTS parents (repo TEXT, branch TEXT, parent TEXT, source TEXT,
    PRIMARY KEY (repo, branch, parent));
"""
PARENTS = """
SELECT parent, source FROM parents WHERE repo = ? AND branch = ? AND source != ?
UNION
SELECT parent, 'recorded' FROM recorded AS r WHERE repo = ? AND branch = ? AND NOT EXISTS
    (SELECT 1 FROM parents AS p WHERE p.repo = r.repo AND p.branch = r.branch AND p.parent = r.parent)
ORDER BY parent
"""
KNOWN = "SELECT repo FROM rules UNION SELECT repo FROM parents UNION SELECT repo FROM recorded ORDER BY repo"


def module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


watch = module("kvb_gates_watch", SKILLS / "kvb-org-organize" / "scripts" / "watch.py")


def fail(message: str) -> None:
    print(f"gates: {message}", file=sys.stderr)
    sys.exit(2)


def git(cwd: str | Path, *args: str, env: dict | None = None) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False, env=env)
    if result.returncode != 0:
        fail(result.stderr.strip() or f"git {args[0]} failed in {cwd}")
    return result.stdout.strip()


def ancestor(repo: str, older: str, newer: str) -> bool:
    return subprocess.run(
        ["git", "merge-base", "--is-ancestor", older, newer], cwd=repo, capture_output=True, check=False
    ).returncode == 0


def root(path: str) -> str:
    common = Path(git(path, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    return str(common.parent if common.name == ".git" else common)


def current_branch(worktree: str) -> str | None:
    named = subprocess.run(
        ["git", "symbolic-ref", "--short", "-q", "HEAD"], cwd=worktree, capture_output=True, text=True, check=False
    )
    return named.stdout.strip() if named.returncode == 0 else None


def journal(origin: Path, kept_dir: Path, kept: Path) -> list[dict]:
    merged: dict[str, dict] = {}
    for base, path in ((kept_dir, kept), (watch.ROOT, origin)):
        if base == watch.ROOT and watch.guard_root(hook=True) is not None:
            continue
        try:
            text = watch.nofollow.read_text(base, path)
        except OSError:
            continue
        for row_id, line in watch.history_rows(text):
            if isinstance(row_id, str):
                merged.setdefault(row_id, json.loads(line))
    return list(merged.values())


def journal_lock(path: Path) -> contextlib.AbstractContextManager:
    return watch.nofollow.locked(watch.ROOT, path.with_suffix(".lock"), FILE_MODE, None)


def append(path: Path, row: dict) -> None:
    refused = watch.guard_root(hook=False)
    if refused is not None:
        sys.exit(refused)
    line = json.dumps({"id": f"{time.time_ns()}-{os.getpid()}", **row}, sort_keys=True)
    with journal_lock(path):
        watch.nofollow.append(watch.ROOT, path, line + "\n", FILE_MODE)


def fresh(row: dict, cutoff: float) -> bool:
    return isinstance(row.get("at"), (int, float)) and row["at"] >= cutoff


def prune(base: Path, path: Path, cutoff: float) -> None:
    text = watch.nofollow.read_text(base, path)
    kept = [line for _, line in watch.history_rows(text) if fresh(json.loads(line), cutoff)]
    if len(kept) != len(text.splitlines()):
        watch.nofollow.replace(base, path, "".join(f"{line}\n" for line in kept), FILE_MODE)


def prune_receipts(cutoff: float) -> None:
    with contextlib.suppress(OSError), journal_lock(watch.RECEIPTS):
        prune(watch.ROOT, watch.RECEIPTS, cutoff)
    with contextlib.suppress(OSError):
        prune(watch.KEPT, watch.KEPT_RECEIPTS, cutoff)


def add_receipt(repo: str, tree: str, level: str, log: str | None) -> None:
    append(watch.RECEIPTS, {
        "repo": repo, "tree": tree, "level": level, "gpu": os.environ.get("INFINITO_TEST_GPU"), "log": log,
        "at": time.time(),
    })
    prune_receipts(time.time() - RECEIPT_SECONDS)


def meets(row: dict, level: str) -> bool:
    if row.get("level") not in LEVELS or LEVELS.index(row["level"]) < LEVELS.index(level):
        return False
    return LEVELS.index(level) <= LEVELS.index("quick") or row.get("gpu") == GPU_OFF


def receipted(repo: str, tree: str, level: str) -> bool:
    cutoff = time.time() - RECEIPT_SECONDS
    return any(
        row.get("repo") == repo and row.get("tree") == tree and fresh(row, cutoff) and meets(row, level)
        for row in journal(watch.RECEIPTS, watch.KEPT, watch.KEPT_RECEIPTS)
    )


def opened(path: Path, write: bool, kept_dir: Path) -> sqlite3.Connection:
    """Args:
        path: gates.db; read-only unless write, in memory when it is missing.
        write: open it for rule and parent changes.
        kept_dir: the directory holding the kept gate-parents.jsonl: watch.KEPT
            on the host, the read-only mount of it in the hub.

    Returns:
        The connection with the TEMP table recorded filled from the parent
        journals, which parents_of(), resolve() and show() read.
    """
    if write:
        path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(path)
    elif path.exists():
        db = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    else:
        db = sqlite3.connect(":memory:")
    try:
        if write or not path.exists():
            db.executescript(SCHEMA)
        db.execute("CREATE TEMP TABLE recorded (repo TEXT, branch TEXT, parent TEXT)")
        db.executemany("INSERT INTO recorded VALUES (?, ?, ?)", [
            (row["repo"], row["branch"], row["parent"])
            for row in journal(watch.PARENTS, kept_dir, kept_dir / watch.KEPT_PARENTS.name)
            if all(isinstance(row.get(key), str) for key in ("repo", "branch", "parent")) and row["branch"] != row["parent"]
        ])
    except BaseException:
        db.close()
        raise
    return db


def branches(repo: str) -> dict[str, str]:
    listed = git(repo, "for-each-ref", "refs/heads", "--format=%(refname:short) %(objectname)")
    return dict(line.split(" ", 1) for line in listed.splitlines() if line)


def remote_tips(repo: str) -> list[tuple[str, str]]:
    listed = git(repo, "for-each-ref", "refs/remotes", "--format=%(refname:lstrip=3) %(objectname)")
    return [tuple(line.split(" ", 1)) for line in listed.splitlines() if line and not line.startswith("HEAD ")]


def default_branch(repo: str, local: dict[str, str]) -> str | None:
    remote = subprocess.run(
        ["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"], cwd=repo, capture_output=True, text=True,
        check=False,
    ).stdout.strip()
    named = remote.removeprefix("origin/") if remote else None
    return next((name for name in (named, "main", "master") if name in local), None)


def parents_of(db: sqlite3.Connection, repo: str, branch: str) -> list[tuple[str, str]]:
    return db.execute(PARENTS, (repo, branch, DROPPED, repo, branch)).fetchall()


def resolve(db: sqlite3.Connection, repo: str, branch: str, action: str, seen: frozenset = frozenset()) -> tuple[str, str | None]:
    own = db.execute(
        "SELECT level FROM rules WHERE repo = ? AND branch = ? AND action = ?", (repo, branch, action)
    ).fetchone()
    if own:
        return own[0], branch
    best: tuple[str, str | None] = ("none", None)
    for parent, _ in parents_of(db, repo, branch):
        if parent in seen or parent == branch:
            continue
        level, source = resolve(db, repo, parent, action, seen | {branch})
        if LEVELS.index(level) > LEVELS.index(best[0]):
            best = (level, source)
    return best


def derive(db: sqlite3.Connection, repo: str) -> list[tuple[str, str]]:
    local = branches(repo)
    default = default_branch(repo, local)
    added = []
    for branch, tip in sorted(local.items()):
        if branch == default or parents_of(db, repo, branch):
            continue
        candidates = [
            other for other, other_tip in local.items()
            if other != branch and (other_tip != tip or other == default) and ancestor(repo, other_tip, tip)
        ]
        nearest = [
            other for other in candidates
            if not any(more != other and local[more] != local[other] and ancestor(repo, local[other], local[more]) for more in candidates)
        ]
        for parent in sorted(nearest):
            db.execute("INSERT OR IGNORE INTO parents VALUES (?, ?, ?, 'derived')", (repo, branch, parent))
            added.append((branch, parent))
    db.commit()
    return added


def record(worktree: str) -> list[str]:
    branch = current_branch(worktree)
    if branch is None:
        return []
    created = subprocess.run(
        ["git", "reflog", "show", "--format=%H", f"refs/heads/{branch}", "--"], cwd=worktree, capture_output=True,
        text=True, check=False,
    ).stdout.split()
    if len(created) != 1:
        return []
    local = branches(worktree)
    tips = [*local.items(), *remote_tips(worktree)]
    found = sorted({other for other, tip in tips if other != branch and tip == created[0]})
    default = default_branch(worktree, local)
    if not found and default not in (None, branch):
        found = [default]
    repo = root(worktree)
    for parent in found:
        append(watch.PARENTS, {"repo": repo, "branch": branch, "parent": parent})
    return found


def worktree_tree(worktree: str) -> str:
    with tempfile.TemporaryDirectory(prefix="kvb-gates-") as scratch:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(scratch) / "index")}
        git(worktree, "read-tree", "HEAD", env=env)
        git(worktree, "add", "-A", ".", env=env)
        return git(worktree, "write-tree", env=env)


def python_error(path: str, content: bytes) -> str | None:
    try:
        ast.parse(content, path)
    except (SyntaxError, ValueError) as error:
        return f"{path}: {error}"
    return None


def json_error(path: str, content: bytes) -> str | None:
    try:
        json.loads(content.decode("utf-8"))
    except ValueError as error:
        return f"{path}: {error}"
    return None


def shell_error(path: str, content: bytes) -> str | None:
    checked = subprocess.run(["bash", "-n"], input=content, capture_output=True, check=False)
    return None if checked.returncode == 0 else f"{path}: {checked.stderr.decode('utf-8', 'replace').strip()}"


CHECKS = {".py": python_error, ".json": json_error, ".sh": shell_error}


def blobs(worktree: str, shas: list[str]) -> list[bytes]:
    out = subprocess.run(
        ["git", "cat-file", "--batch"], cwd=worktree, input="".join(f"{sha}\n" for sha in shas).encode(),
        capture_output=True, check=True,
    ).stdout
    contents, at = [], 0
    for _ in shas:
        end = out.index(b"\n", at)
        size = int(out[at:end].split()[2])
        contents.append(out[end + 1 : end + 1 + size])
        at = end + 2 + size
    return contents


def checked_files(worktree: str) -> list[tuple[str, str]]:
    listed = [entry.split("\t", 1) for entry in git(worktree, "ls-files", "-s", "-z").split("\0") if entry]
    return [
        (path, info.split()[1]) for info, path in listed
        if info.split()[0] in ("100644", "100755") and Path(path).suffix in CHECKS
    ]


def staged_problems(worktree: str) -> list[str]:
    files = checked_files(worktree)
    problems = [
        problem for (path, _), content in zip(files, blobs(worktree, [sha for _, sha in files]))
        if (problem := CHECKS[Path(path).suffix](path, content)) is not None
    ]
    spaced = subprocess.run(["git", "diff", "--cached", "--check"], cwd=worktree, capture_output=True, text=True, check=False)
    if spaced.returncode != 0:
        problems.extend((spaced.stdout or spaced.stderr).splitlines())
    return problems


def quick(worktree: str) -> int:
    problems = staged_problems(worktree)
    for problem in problems:
        print(f"gates: {problem}", file=sys.stderr)
    if problems:
        return 1
    add_receipt(root(worktree), git(worktree, "write-tree"), "quick", None)
    return 0


def install(path: str) -> list[Path]:
    hooks = Path(git(path, "rev-parse", "--path-format=absolute", "--git-path", "hooks"))
    foreign = [
        name for name in HOOKS
        if (hooks / name).is_symlink() or ((hooks / name).exists() and not OURS.search((hooks / name).read_text(errors="replace")))
    ]
    if foreign:
        fail(f"{hooks} holds hooks gates.py did not write: {', '.join(foreign)}; move them aside first")
    hooks.mkdir(parents=True, exist_ok=True)
    script = shlex.quote(str(Path(__file__).resolve()))
    for name in HOOKS:
        (hooks / name).write_text(HOOK.format(script=script, name=name), encoding="utf-8")
        (hooks / name).chmod(0o755)
    return [hooks / name for name in HOOKS]


def task_of(branch: str) -> str:
    rasci = module("kvb_gates_rasci", RASCI)
    tasks = sorted(
        task for task, row in rasci.load().items() if row.get("branch") == branch and row.get("status") not in rasci.ENDED
    )
    return tasks[0] if tasks else "<register task>"


def producer(worktree: str, branch: str, level: str, tree: str) -> str:
    if level == "quick":
        return shlex.join(["python3", str(Path(__file__).resolve()), "quick", "--worktree", worktree])
    log = Path(tempfile.gettempdir()) / f"gate-{tree[:12]}-{level}.log"
    return shlex.join([
        "env", "-C", worktree, f"INFINITO_TEST_GPU={GPU_OFF}", "python3", str(QUEUE), "hold", "--kind", KINDS[level],
        "--task", task_of(branch), "--receipt", level, "--log", str(log), "--", "make", level,
    ])


def refusal(db: sqlite3.Connection, worktree: str, branch: str, tree: str, action: str) -> str | None:
    repo = root(worktree)
    level, source = resolve(db, repo, branch, action)
    if level == "none" or receipted(repo, tree, level):
        return None
    return (
        f"gates: {action} on {branch} needs {level} (rule of {source}); no receipt for tree {tree} meets it. "
        f"Produce it with:\n  {producer(worktree, branch, level, tree)}"
    )


def pushed(worktree: str, lines: str) -> list[tuple[str, str, str]]:
    targets = []
    for line in lines.splitlines():
        local_ref, local_sha, remote_ref, _ = line.split()
        if ZERO.fullmatch(local_sha):
            continue
        tree = git(worktree, "rev-parse", f"{local_sha}^{{tree}}")
        checks = {(ref.removeprefix("refs/heads/"), "push") for ref in (local_ref, remote_ref) if ref.startswith("refs/heads/")}
        if remote_ref.startswith("refs/heads/"):
            checks.add((remote_ref.removeprefix("refs/heads/"), "merge"))
        targets.extend((name, tree, action) for name, action in sorted(checks))
    return targets


def state_paths(worktree: str, names: tuple[str, ...]) -> list[Path]:
    listed = git(worktree, "rev-parse", "--path-format=absolute", *(arg for name in names for arg in ("--git-path", name)))
    return [Path(line) for line in listed.splitlines()]


def hook_branch(worktree: str) -> str:
    named = current_branch(worktree)
    if named is not None:
        return named
    for head in state_paths(worktree, REBASE_HEADS):
        if head.is_file():
            return head.read_text(encoding="utf-8").strip().removeprefix("refs/heads/")
    return default_branch(worktree, branches(worktree)) or "HEAD"


def hook_targets(name: str, here: str) -> list[tuple[str, str, str]]:
    if name == "pre-push":
        return pushed(here, sys.stdin.read())
    actions = ["merge"]
    if name == "commit-msg":
        merging = any(path.exists() for path in state_paths(here, MERGE_STATES))
        actions = ["commit", "merge"] if merging else ["commit"]
    branch, tree = hook_branch(here), git(here, "write-tree")
    return [(branch, tree, action) for action in actions]


def record_after_checkout(here: str) -> None:
    try:
        record(here)
    except (SystemExit, OSError) as error:
        reason = error.strerror if isinstance(error, OSError) else "see the line above"
        print(f"gates: post-checkout recorded no parents ({reason}); the checkout itself succeeded", file=sys.stderr)


def run_hook(name: str, argv: list[str], db_path: Path) -> int:
    here = os.getcwd()
    if name == "pre-commit":
        return quick(here)
    if name == "post-checkout":
        if argv[2:3] == ["1"]:
            record_after_checkout(here)
        return 0
    targets = hook_targets(name, here)
    db = opened(db_path, False, watch.KEPT)
    refused = [text for branch, tree, action in targets if (text := refusal(db, here, branch, tree, action))]
    for text in refused:
        print(text, file=sys.stderr)
    return 1 if refused else 0


def show(db: sqlite3.Connection, repos: list[str]) -> dict:
    shown = {}
    for repo in repos:
        named = set(branches(repo)) | {row[0] for row in db.execute("SELECT branch FROM rules WHERE repo = ?", (repo,))}
        shown[repo] = {
            branch: {
                "parents": [{"parent": parent, "source": source} for parent, source in parents_of(db, repo, branch)],
                "rules": dict(db.execute("SELECT action, level FROM rules WHERE repo = ? AND branch = ?", (repo, branch))),
                "resolved": {
                    action: dict(zip(("level", "source"), resolve(db, repo, branch, action))) for action in ACTIONS
                },
            }
            for branch in sorted(named)
        }
    return shown


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    top.add_argument("--db", type=Path, default=Path(os.environ.get("GATES_DB", DEFAULT_DB)))
    sub = top.add_subparsers(dest="command", required=True)
    rule = sub.add_parser("rule").add_subparsers(dest="verb", required=True)
    for verb in ("set", "drop"):
        p = rule.add_parser(verb)
        p.add_argument("--repo", required=True)
        p.add_argument("--branch", required=True)
        p.add_argument("--action", required=True, choices=ACTIONS)
        if verb == "set":
            p.add_argument("--level", required=True, choices=LEVELS)
    parents = sub.add_parser("parents").add_subparsers(dest="verb", required=True)
    for verb in ("add", "drop"):
        p = parents.add_parser(verb)
        p.add_argument("--repo", required=True)
        p.add_argument("--branch", required=True)
        p.add_argument("--parent", required=True)
        if verb == "add":
            p.add_argument("--source", choices=SOURCES, default="operator")
    parents.add_parser("derive").add_argument("--repo", required=True)
    parents.add_parser("record").add_argument("--worktree", required=True)
    p = sub.add_parser("resolve")
    p.add_argument("--repo", required=True)
    p.add_argument("--branch", required=True)
    p.add_argument("--action", required=True, choices=ACTIONS)
    sub.add_parser("tree").add_argument("--worktree", required=True)
    sub.add_parser("quick").add_argument("--worktree", required=True)
    receipt = sub.add_parser("receipt").add_subparsers(dest="verb", required=True)
    for verb in ("add", "check"):
        p = receipt.add_parser(verb)
        p.add_argument("--repo", required=True)
        p.add_argument("--tree", required=True)
        p.add_argument("--level", required=True, choices=LEVELS)
        if verb == "add":
            p.add_argument("--log", required=True)
    sub.add_parser("hooks").add_subparsers(dest="verb", required=True).add_parser("install").add_argument(
        "--repo", required=True
    )
    p = sub.add_parser("hook")
    p.add_argument("name", choices=HOOKS)
    p.add_argument("args", nargs="*")
    p = sub.add_parser("show")
    p.add_argument("--json", action="store_true", required=True)
    p.add_argument("--repo")
    return top


def journal_command(args: argparse.Namespace) -> int:
    if args.command == "tree":
        print(worktree_tree(args.worktree))
    elif args.command == "quick":
        return quick(args.worktree)
    elif args.command == "hooks":
        for path in install(args.repo):
            print(path)
    elif args.command == "hook":
        return run_hook(args.name, args.args, args.db)
    elif args.verb == "add":
        add_receipt(root(args.repo), args.tree, args.level, args.log)
    elif args.verb == "check":
        return 0 if receipted(root(args.repo), args.tree, args.level) else 1
    else:
        for parent in record(args.worktree):
            print(parent)
    return 0


def database_command(args: argparse.Namespace, db: sqlite3.Connection, repo: str | None) -> None:
    if args.command == "rule" and args.verb == "set":
        db.execute("INSERT OR REPLACE INTO rules VALUES (?, ?, ?, ?, ?)", (repo, args.branch, args.action, args.level, time.time()))
    elif args.command == "rule":
        db.execute("DELETE FROM rules WHERE repo = ? AND branch = ? AND action = ?", (repo, args.branch, args.action))
    elif args.verb == "add":
        if args.parent == args.branch:
            fail(f"{args.branch} cannot be its own parent")
        db.execute("INSERT OR REPLACE INTO parents VALUES (?, ?, ?, ?)", (repo, args.branch, args.parent, args.source))
    elif args.verb == "drop":
        db.execute("INSERT OR REPLACE INTO parents VALUES (?, ?, ?, ?)", (repo, args.branch, args.parent, DROPPED))
    else:
        for branch, parent in derive(db, repo):
            print(f"{branch}\t{parent}\tderived")
    db.commit()


def main() -> int:
    args = parser().parse_args()
    verb = getattr(args, "verb", None)
    if args.command in ("tree", "quick", "hooks", "hook", "receipt") or verb == "record":
        return journal_command(args)
    db = opened(args.db, args.command in ("rule", "parents"), watch.KEPT)
    repo = root(args.repo) if getattr(args, "repo", None) else None
    if args.command == "resolve":
        level, source = resolve(db, repo, args.branch, args.action)
        print(f"{level}\t{source or '-'}")
    elif args.command == "show":
        known = [row[0] for row in db.execute(KNOWN)]
        print(json.dumps(show(db, [repo] if repo else known)))
    else:
        database_command(args, db, repo)
    return 0


if __name__ == "__main__":
    sys.exit(main())
