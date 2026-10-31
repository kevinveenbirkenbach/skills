#!/usr/bin/env python3
"""Find commits on any ref that match a fix, skipping those already in HEAD.

Usage:
    find_fix.py [--grep KEYWORD]... [-S LITERAL]... [--path PATH]... [--fetch]

Prints one line per candidate: sha, up to three branches, subject, files
touched. The filters are alternatives: a commit is a hit when it matches any
one of them. -S also matches commits that removed the literal; read the diff.
Run it inside the repository; it never checks anything out.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

LIMIT = 30
WORKERS = os.cpu_count() or 1
SLICES_PER_WORKER = 4


def git(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], input=stdin, capture_output=True, text=True, check=False)


def log_all(pool: ThreadPoolExecutor, *query: str) -> Callable[[], list[str]]:
    job = pool.submit(git, "log", "--all", "--format=%H", *query)
    return lambda: job.result().stdout.split()


def pickaxe(pool: ThreadPoolExecutor, literal: str, rank: dict[str, int]) -> Callable[[], list[str]]:
    """Run `git log --all -S<literal>` as parallel slices of the commit list.

    The slices are strided because the costly commits cluster in time.

    Args:
        pool: executor the slice runs are submitted to.
        literal: the -S literal.
        rank: every commit of `git rev-list --all`, mapped to its position.

    Returns:
        A callable yielding the matching commits in `git log --all` order.
    """
    commits = list(rank)
    parts = min(len(commits), WORKERS * SLICES_PER_WORKER)
    jobs = [
        pool.submit(
            git, "log", "--no-walk=unsorted", "--stdin", "--format=%H", f"-S{literal}", stdin="\n".join(commits[i::parts]) + "\n"
        )
        for i in range(parts)
    ]
    return lambda: sorted((sha for job in jobs for sha in job.result().stdout.split()), key=rank.__getitem__)


def search(args: argparse.Namespace, pool: ThreadPoolExecutor) -> list[str]:
    queries = [log_all(pool, "--regexp-ignore-case", f"--grep={k}") for k in args.grep]
    if args.S:
        rank = {sha: i for i, sha in enumerate(git("rev-list", "--all").stdout.split())}
        queries += [pickaxe(pool, s, rank) for s in args.S]
    queries += [log_all(pool, "--", p) for p in args.path]
    found: dict[str, None] = {}
    for query in queries:
        for sha in query():
            found.setdefault(sha)
    return list(found)


def describe(sha: str) -> str:
    subject = git("log", "-1", "--format=%h %s", sha).stdout.strip()
    branches = git("branch", "-a", "--contains", sha, "--format=%(refname:short)").stdout.split()
    files = [f for f in git("show", "--name-only", "--format=", sha).stdout.split("\n") if f]
    shown = ",".join(branches[:3]) + (f",+{len(branches) - 3}" if len(branches) > 3 else "")
    return f"{subject}\t{shown or '-'}\t{len(files)} files: {','.join(files[:5])}"


def main() -> int:
    parser = argparse.ArgumentParser(prog="find_fix")
    parser.add_argument("--grep", action="append", default=[])
    parser.add_argument("-S", action="append", default=[])
    parser.add_argument("--path", action="append", default=[])
    parser.add_argument("--fetch", action="store_true")
    args = parser.parse_args()
    if not (args.grep or args.S or args.path):
        parser.error("give at least one --grep, -S or --path")
    if args.fetch:
        git("fetch", "--all", "--prune", "--tags")
    pool = ThreadPoolExecutor(max_workers=WORKERS)
    try:
        head = pool.submit(git, "rev-list", "HEAD")
        hits = search(args, pool)
        in_head = set(head.result().stdout.split())
        outside = [sha for sha in hits if sha not in in_head]
        print(f"hits={len(hits)} in_head={len(hits) - len(outside)} candidates={len(outside)}")
        for line in pool.map(describe, outside[:LIMIT]):
            print(line)
    finally:
        # A plain `with` would start every queued git slice after Ctrl-C.
        pool.shutdown(cancel_futures=True)
    if len(outside) > LIMIT:
        print(f"... {len(outside) - LIMIT} more, narrow the search")
    return 0


if __name__ == "__main__":
    sys.exit(main())
