#!/usr/bin/env python3
"""Gate rules, branch parents and gate receipts of every repository on this host.

Args:
    --db: the SQLite database, default ~/.local/state/agents-council/gates.db
        (GATES_DB overrides it); it survives reboots, the council root under
        /tmp does not.

    rule set --repo R --branch B --action A --level L: the branch's own level
        for one action. rule drop --repo R --branch B --action A removes it.
    parents add|drop --repo R --branch B --parent P [--source S]: one parent
        edge; S is recorded, derived or operator (default operator).
    parents derive --repo R: gives every local branch without a parent, except
        the default branch, the nearest local branches whose tip is its
        ancestor, as derived parents.
    resolve --repo R --branch B --action A: prints `<level>\t<source>`, the
        branch's own level, else the strictest resolved level of all its
        parents, else `none\t-`.
    tree --worktree W: prints the tree sha of everything W holds, tracked,
        staged, unstaged and untracked, ignored files left out.
    receipt add --repo R --tree T --level L --log P: records a green gate.
    receipt check --repo R --tree T --level L: exit 0 when a receipt for T
        meets L, else 1.
    show --json [--repo R]: {repo: {branch: {parents: [{parent, source}],
        rules: {action: level}, resolved: {action: {level, source}}}}} for the
        local branches of R, or of every repository the database knows.

    R is any path inside the repository; it is stored as the absolute path of
    the main checkout, so linked worktrees share it.

Exit codes:
    0 done, 1 a receipt check that fails, 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

LEVELS = ("none", "quick", "test", "quality-high", "e2e")
ACTIONS = ("commit", "merge", "push", "pr")
SOURCES = ("recorded", "derived", "operator")
DEFAULT_DB = Path.home() / ".local" / "state" / "agents-council" / "gates.db"
SCHEMA = """
CREATE TABLE IF NOT EXISTS rules (repo TEXT, branch TEXT, action TEXT, level TEXT, set_at REAL,
    PRIMARY KEY (repo, branch, action));
CREATE TABLE IF NOT EXISTS parents (repo TEXT, branch TEXT, parent TEXT, source TEXT,
    PRIMARY KEY (repo, branch, parent));
CREATE TABLE IF NOT EXISTS receipts (repo TEXT, tree TEXT, level TEXT, log TEXT, at REAL,
    PRIMARY KEY (repo, tree, level));
"""


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


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    return db


def branches(repo: str) -> dict[str, str]:
    listed = git(repo, "for-each-ref", "refs/heads", "--format=%(refname:short) %(objectname)")
    return dict(line.split(" ", 1) for line in listed.splitlines() if line)


def default_branch(repo: str, local: dict[str, str]) -> str | None:
    remote = subprocess.run(
        ["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"], cwd=repo, capture_output=True, text=True,
        check=False,
    ).stdout.strip()
    named = remote.removeprefix("origin/") if remote else None
    return next((name for name in (named, "main", "master") if name in local), None)


def parents_of(db: sqlite3.Connection, repo: str, branch: str) -> list[tuple[str, str]]:
    return db.execute(
        "SELECT parent, source FROM parents WHERE repo = ? AND branch = ? ORDER BY parent", (repo, branch)
    ).fetchall()


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


def worktree_tree(worktree: str) -> str:
    with tempfile.TemporaryDirectory(prefix="kvb-gates-") as scratch:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(scratch) / "index")}
        git(worktree, "read-tree", "HEAD", env=env)
        git(worktree, "add", "-A", ".", env=env)
        return git(worktree, "write-tree", env=env)


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
    p = sub.add_parser("resolve")
    p.add_argument("--repo", required=True)
    p.add_argument("--branch", required=True)
    p.add_argument("--action", required=True, choices=ACTIONS)
    sub.add_parser("tree").add_argument("--worktree", required=True)
    receipt = sub.add_parser("receipt").add_subparsers(dest="verb", required=True)
    for verb in ("add", "check"):
        p = receipt.add_parser(verb)
        p.add_argument("--repo", required=True)
        p.add_argument("--tree", required=True)
        p.add_argument("--level", required=True, choices=LEVELS)
        if verb == "add":
            p.add_argument("--log", required=True)
    p = sub.add_parser("show")
    p.add_argument("--json", action="store_true", required=True)
    p.add_argument("--repo")
    return top


def main() -> int:
    args = parser().parse_args()
    if args.command == "tree":
        print(worktree_tree(args.worktree))
        return 0
    db = connect(args.db)
    repo = root(args.repo) if getattr(args, "repo", None) else None
    if args.command == "rule" and args.verb == "set":
        db.execute("INSERT OR REPLACE INTO rules VALUES (?, ?, ?, ?, ?)", (repo, args.branch, args.action, args.level, time.time()))
    elif args.command == "rule":
        db.execute("DELETE FROM rules WHERE repo = ? AND branch = ? AND action = ?", (repo, args.branch, args.action))
    elif args.command == "parents" and args.verb == "add":
        if args.parent == args.branch:
            fail(f"{args.branch} cannot be its own parent")
        db.execute("INSERT OR REPLACE INTO parents VALUES (?, ?, ?, ?)", (repo, args.branch, args.parent, args.source))
    elif args.command == "parents" and args.verb == "drop":
        db.execute("DELETE FROM parents WHERE repo = ? AND branch = ? AND parent = ?", (repo, args.branch, args.parent))
    elif args.command == "parents":
        for branch, parent in derive(db, repo):
            print(f"{branch}\t{parent}\tderived")
    elif args.command == "resolve":
        level, source = resolve(db, repo, args.branch, args.action)
        print(f"{level}\t{source or '-'}")
    elif args.command == "receipt" and args.verb == "add":
        db.execute("INSERT OR REPLACE INTO receipts VALUES (?, ?, ?, ?, ?)", (repo, args.tree, args.level, args.log, time.time()))
    elif args.command == "receipt":
        levels = [row[0] for row in db.execute("SELECT level FROM receipts WHERE repo = ? AND tree = ?", (repo, args.tree))]
        return 0 if any(LEVELS.index(level) >= LEVELS.index(args.level) for level in levels) else 1
    else:
        known = {row[0] for row in db.execute("SELECT repo FROM rules")} | {row[0] for row in db.execute("SELECT repo FROM parents")}
        repos = [repo] if repo else sorted(known)
        print(json.dumps(show(db, repos)))
    db.commit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
