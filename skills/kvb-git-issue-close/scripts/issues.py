#!/usr/bin/env python3
"""List the issues a pull request references, from `gh pr view --json` on stdin.

Args:
    stdin: JSON with number, body, headRefName, commits and
        closingIssuesReferences, as `gh pr view <pr> --json
        number,body,headRefName,commits,closingIssuesReferences` prints it.
    --repo: owner/name of the pull request's repository; its own references
        are reported without a repository.
    --json: print the candidates as JSON instead of tab-separated lines.

Exit codes:
    0 done, 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import re
import sys

KEYWORD = r"(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)"
REF = r"(?:(?P<repo>[\w.-]+/[\w.-]+)#|https://github\.com/(?P<url>[\w.-]+/[\w.-]+)/issues/|(?<![\w/])#)(?P<num>[1-9]\d*)"
PATTERN = re.compile(rf"(?P<kw>\b{KEYWORD}\b:?\s+)?{REF}", re.IGNORECASE)
BRANCH = re.compile(r"[/-](\d+)$")


def fail(message: str) -> None:
    print(f"issues: {message}", file=sys.stderr)
    sys.exit(2)


def scan(text: str, source: str, found: dict) -> None:
    for match in PATTERN.finditer(text or ""):
        repo = match.group("repo") or match.group("url") or ""
        entry = found.setdefault(
            (repo, int(match.group("num"))), {"closing": False, "sources": []}
        )
        entry["closing"] = entry["closing"] or bool(match.group("kw"))
        if source not in entry["sources"]:
            entry["sources"].append(source)


def candidates(pr: dict, own: str) -> list[dict]:
    found: dict = {}
    scan(pr.get("body", ""), "body", found)
    for commit in pr.get("commits", []):
        text = f"{commit.get('messageHeadline', '')}\n{commit.get('messageBody', '')}"
        scan(text, f"commit {commit.get('oid', '')[:10]}", found)
    branch = BRANCH.search(pr.get("headRefName", ""))
    if branch:
        found.setdefault(("", int(branch.group(1))), {"closing": False, "sources": []})[
            "sources"
        ].append("branch")
    for linked in pr.get("closingIssuesReferences", []):
        url = re.search(r"github\.com/([\w.-]+/[\w.-]+)/issues/", linked.get("url", ""))
        key = (url.group(1) if url else "", int(linked["number"]))
        entry = found.setdefault(key, {"closing": False, "sources": []})
        entry["closing"] = True
        entry["sources"].append("linked")
    merged: dict = {}
    for (repo, num), entry in found.items():
        key = ("" if repo.lower() == own.lower() else repo, num)
        if key == ("", pr.get("number")):
            continue
        target = merged.setdefault(key, {"closing": False, "sources": []})
        target["closing"] = target["closing"] or entry["closing"]
        target["sources"] += [s for s in entry["sources"] if s not in target["sources"]]
    return [{"repo": repo, "issue": num, **entry} for (repo, num), entry in sorted(merged.items())]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        pr = json.load(sys.stdin)
    except ValueError:
        fail("stdin is not the JSON of gh pr view --json")
    if not isinstance(pr, dict):
        fail("stdin is not a pull request object")
    rows = candidates(pr, args.repo)
    if args.json:
        print(json.dumps(rows, indent=1))
        return 0
    for row in rows:
        kind = "closing" if row["closing"] else "mention"
        print(f"{row['repo'] or '-'}\t{row['issue']}\t{kind}\t{', '.join(row['sources'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
