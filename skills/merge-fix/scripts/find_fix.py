#!/usr/bin/env python3
"""Find commits on any ref that match a fix, skipping those already in HEAD.

Usage:
    find_fix.py [--grep KEYWORD]... [-S LITERAL]... [--path PATH]... [--fetch]

Prints one line per candidate: sha, up to three branches, subject, files
touched. -S also matches commits that removed the literal; read the diff.
Run it inside the repository; it never checks anything out.
"""

from __future__ import annotations

import argparse
import subprocess
import sys

LIMIT = 30


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=False)


def search(args: argparse.Namespace) -> list[str]:
    queries = [["--regexp-ignore-case", f"--grep={k}"] for k in args.grep]
    queries += [[f"-S{s}"] for s in args.S]
    queries += [["--", p] for p in args.path]
    found: list[str] = []
    for query in queries:
        for sha in git("log", "--all", "--format=%H", *query).stdout.split():
            if sha not in found:
                found.append(sha)
    return found


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
    hits = search(args)
    outside = [sha for sha in hits if git("merge-base", "--is-ancestor", sha, "HEAD").returncode]
    print(f"hits={len(hits)} in_head={len(hits) - len(outside)} candidates={len(outside)}")
    for sha in outside[:LIMIT]:
        print(describe(sha))
    if len(outside) > LIMIT:
        print(f"... {len(outside) - LIMIT} more, narrow the search")
    return 0


if __name__ == "__main__":
    sys.exit(main())
