#!/usr/bin/env python3
"""List the default-branch commits that reference each open issue.

Args:
    stdin: JSON list of open issues, as `gh issue list --state open --json
        number` prints it.
    --repo: owner/name of the repository; its own references count, foreign
        ones do not.
    --git-dir: path of a local clone, fetched.
    --ref: the default branch to scan, e.g. origin/main.
    --json: print the result as JSON instead of tab-separated lines.

Output:
    one line per open issue that a commit references: issue, closing or
    mention, the short shas.

Exit codes:
    0 done, 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

from issues import PATTERN, fail


def references(log: str, own: str, open_issues: set[int]) -> dict[int, dict]:
    found: dict[int, dict] = {}
    for record in filter(None, log.split("\x1e")):
        sha, _, message = record.strip("\n").partition("\x1f")
        for match in PATTERN.finditer(message):
            repo = match.group("repo") or match.group("url") or ""
            number = int(match.group("num"))
            if number not in open_issues or (repo and repo.lower() != own.lower()):
                continue
            entry = found.setdefault(number, {"closing": False, "commits": []})
            entry["closing"] = entry["closing"] or bool(match.group("kw"))
            if sha[:10] not in entry["commits"]:
                entry["commits"].append(sha[:10])
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", required=True)
    parser.add_argument("--git-dir", required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        issues = json.load(sys.stdin)
        open_issues = {int(issue["number"]) for issue in issues}
    except (ValueError, TypeError, KeyError):
        fail("stdin is not the JSON of gh issue list --json number")
    log = subprocess.run(
        ["git", "log", "--format=%H%x1f%B%x1e", args.ref],
        cwd=args.git_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if log.returncode != 0:
        fail(log.stderr.strip() or f"git log {args.ref} failed")
    found = references(log.stdout, args.repo, open_issues)
    rows = [{"issue": number, **found[number]} for number in sorted(found)]
    if args.json:
        print(json.dumps(rows, indent=1))
        return 0
    for row in rows:
        kind = "closing" if row["closing"] else "mention"
        print(f"{row['issue']}\t{kind}\t{', '.join(row['commits'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
