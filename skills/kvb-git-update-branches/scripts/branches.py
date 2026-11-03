#!/usr/bin/env python3
"""List the open branches of a remote with their lag behind the base and their owner.

Args:
    --repo: path of the local clone.
    --remote: remote whose branches are listed, e.g. origin.
    --base: base branch on that remote, e.g. main.
    --email: the operator's commit email; a branch whose own commits all carry
        it belongs to the operator.
    --login: the operator's forge login, matched against pull request authors.
    --prs: file with `gh pr list --state open --json
        number,headRefName,author,isCrossRepository`; omit it for branches only.
    --json: print the rows as JSON instead of tab-separated lines.

Exit codes:
    0 done, 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def fail(message: str) -> None:
    print(f"branches: {message}", file=sys.stderr)
    sys.exit(2)


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        fail(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout


def load_prs(path: str | None) -> list[dict]:
    if path is None:
        return []
    try:
        prs = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        fail(f"{path} is not the JSON of gh pr list")
    if not isinstance(prs, list):
        fail(f"{path} is not a list of pull requests")
    return prs


def rows(repo: Path, remote: str, base: str, email: str, login: str, prs: list[dict]) -> list[dict]:
    target = f"{remote}/{base}"
    git(repo, "rev-parse", "--verify", target)
    by_branch = {pr["headRefName"]: pr for pr in prs if not pr.get("isCrossRepository")}
    found = []
    refs = git(repo, "for-each-ref", "--format=%(refname:short)", f"refs/remotes/{remote}/")
    for ref in refs.split():
        branch = ref.removeprefix(f"{remote}/")
        if branch in (base, "HEAD") or ref == remote:
            continue
        ahead = int(git(repo, "rev-list", "--count", f"{target}..{ref}"))
        if ahead == 0:
            continue
        behind = int(git(repo, "rev-list", "--count", f"{ref}..{target}"))
        authors = sorted(set(git(repo, "log", "--format=%ae", f"{target}..{ref}").split()))
        pr = by_branch.get(branch)
        mine = (pr["author"]["login"] == login) if pr else authors == [email]
        found.append(
            {
                "branch": branch,
                "pr": pr["number"] if pr else None,
                "ahead": ahead,
                "behind": behind,
                "authors": authors,
                "mine": mine,
            }
        )
    for pr in prs:
        if pr.get("isCrossRepository"):
            found.append(
                {
                    "branch": pr["headRefName"],
                    "pr": pr["number"],
                    "ahead": None,
                    "behind": None,
                    "authors": [pr["author"]["login"]],
                    "mine": pr["author"]["login"] == login,
                    "fork": True,
                }
            )
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for name in ("--repo", "--remote", "--base", "--email", "--login"):
        parser.add_argument(name, required=True)
    parser.add_argument("--prs")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    repo = Path(args.repo)
    if not repo.is_dir():
        fail(f"{repo} is not a directory")
    found = rows(repo, args.remote, args.base, args.email, args.login, load_prs(args.prs))
    if args.json:
        print(json.dumps(found, indent=1))
        return 0
    for row in found:
        print(
            f"{row['branch']}\t#{row['pr'] or '-'}\tahead {row['ahead']}\tbehind {row['behind']}"
            f"\t{'mine' if row['mine'] else ', '.join(row['authors'])}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
