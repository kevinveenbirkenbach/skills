#!/usr/bin/env python3
"""Backfill the score journal of journal.py from the message blocks in git history.

Args:
    --repo <dir>...: repositories whose local and origin branches git log reads;
        repeatable, every one given counts.
    --since <rev>: only commits not reachable from <rev>, in every repository.
    --labels <file>: the label file mapping current and former labels to metric
        keys, ../labels.json when left out.

Output:
    One line per repository, `<top level>: <n> blocks, <m> rows added`; one stderr
    line per unknown block label, `backfill: unknown label <label>, skipped`.

Exit codes:
    0 done, 2 usage error, a repository git cannot read or a journal that is
    linked, not a regular file or not writable, with one stderr line; nothing
    is written then.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import deque
from pathlib import Path
from typing import NamedTuple

from journal import (
    LABELS,
    append,
    entry,
    git_read,
    journal_path,
    load_labels,
    origin,
    read,
)

FIELD = "\x00"
RECORD = "\x1e"
LOG_FORMAT = "%H%x00%P%x00%ct%x00%B%x1e"
REFS = ("refs/heads/", "refs/remotes/origin/")
LINE = re.compile(r"([^\x00-\x7f]\S*) ([A-Z][A-Za-z]*): (.+)")
AMOUNT = re.compile(r"~?(\d+(?:\.\d+)?)(?: ?%)?")
PARAGRAPH = re.compile(r"\n[ \t]*\n")
MERGES = (
    re.compile(r"Merge pull request #\d+ from [^/\s]+/(\S+)"),
    re.compile(r"Merge (?:remote-tracking )?branch '(?:origin/)?([^']+)'"),
    re.compile(r"Merge (\S+) into \S+"),
)


class Commit(NamedTuple):
    parents: list[str]
    time: int
    message: str


def aliases(labels: dict) -> tuple[dict[str, str], set[str]]:
    """Args:
        labels: load_labels() of a label file.

    Returns:
        (metric of each current and former label, labels of the extra lines).
    """
    named = {name: key for key, metric in labels["metrics"].items() for name in (metric["label"], *metric["former"])}
    extras = {name for extra in labels["extras"].values() for name in (extra["label"], *extra["former"])}
    return named, extras


def amount(text: str) -> float | int | None:
    found = AMOUNT.fullmatch(text.strip())
    if not found:
        return None
    value = float(found.group(1))
    return int(value) if value.is_integer() else value


def parse(message: str, named: dict[str, str], extras: set[str], unknown: set[str]) -> tuple[dict, str] | None:
    """Args:
        message: a commit message.
        named: aliases() metrics.
        extras: aliases() extra labels, read and left out.
        unknown: collects the labels of block lines neither names.

    Returns:
        (values per metric key, block text) of the last block, None without one.
    """
    found = None
    for paragraph in PARAGRAPH.split(message):
        lines = [match for match in (LINE.fullmatch(text.strip()) for text in paragraph.splitlines()) if match]
        if not any(named.get(match.group(2)) == "score" for match in lines):
            continue
        values = dict.fromkeys(named.values())
        for match in lines:
            label = match.group(2)
            if label in named:
                values[named[label]] = amount(match.group(3))
            elif label not in extras:
                unknown.add(label)
        if values["score"] is not None:
            found = (values, "\n".join(match.group(0) for match in lines))
    return found


def history(repo: Path, tips: list[str], since: str | None) -> dict[str, Commit]:
    text = git_read(repo, "log", f"--format={LOG_FORMAT}", *tips, *([f"^{since}"] if since else []), "--")
    if text is None:
        raise LookupError(f"git log in {repo} failed")
    commits = {}
    for record in text.split(RECORD):
        fields = record.strip("\n").split(FIELD, 3)
        if len(fields) == 4:
            sha, parents, stamp, message = fields
            commits[sha] = Commit(parents.split(), int(stamp), message)
    return commits


def heads(repo: Path) -> list[tuple[str, str]]:
    """Args:
        repo: a git repository.

    Returns:
        (branch, tip sha) of every local and origin branch, the default branch
        (origin/HEAD, else the checked out one) first, then by name, local first.
    """
    listing = git_read(repo, "for-each-ref", "--format=%(refname)%00%(objectname)", *REFS)
    if listing is None:
        raise LookupError(f"git for-each-ref in {repo} failed")
    pointed = git_read(repo, "symbolic-ref", "-q", "refs/remotes/origin/HEAD") or git_read(repo, "symbolic-ref", "-q", "HEAD") or ""
    default = next((pointed.removeprefix(prefix) for prefix in REFS if pointed.startswith(prefix)), None)
    found = []
    for row in listing.splitlines():
        ref, sha = row.split(FIELD)
        rank, prefix = next((rank, prefix) for rank, prefix in enumerate(REFS) if ref.startswith(prefix))
        name = ref.removeprefix(prefix)
        if name != "HEAD":
            found.append((name != default, name, rank, sha))
    return [(name, sha) for _, name, _, sha in sorted(found)]


def merged(message: str) -> str | None:
    subject = message.split("\n", 1)[0]
    return next((match.group(1) for match in (pattern.match(subject) for pattern in MERGES) if match), None)


def owners(commits: dict[str, Commit], tips: list[tuple[str, str]]) -> dict[str, str]:
    """Args:
        commits: history() of the repository.
        tips: heads() of the repository.

    Returns:
        The branch of every commit: the first tip whose first-parent line holds
        it, else the branch a merge subject names for its side, else the merge's.
    """
    owner: dict[str, str] = {}
    queue = deque((sha, name) for name, sha in tips)
    while queue:
        sha, name = queue.popleft()
        while sha in commits and sha not in owner:
            owner[sha] = name
            commit = commits[sha]
            side = merged(commit.message) or name
            queue.extend((other, side) for other in commit.parents[1:])
            sha = commit.parents[0] if commit.parents else None
    return owner


def scan(repo: Path, since: str | None, named: dict[str, str], extras: set[str], unknown: set[str]) -> tuple[str, list[dict]]:
    place = origin(repo)
    if place[1] is None:
        raise LookupError(f"{repo} is not a git work tree")
    tips = heads(repo)
    commits = history(repo, [sha for _, sha in tips], since) if tips else {}
    owner = owners(commits, tips)
    rows = []
    for sha, commit in commits.items():
        found = parse(commit.message, named, extras, unknown)
        if found:
            values, block = found
            rows.append(entry(commit.time, place, owner.get(sha), sha, values, block))
    return place[1], rows


def known(path: Path) -> set[tuple[str | None, str]]:
    try:
        text = read(path)
    except FileNotFoundError:
        return set()
    keys = set()
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and isinstance(row.get("sha"), str):
            keys.add((row.get("remote"), row["sha"]))
    return keys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", type=Path, nargs="+", action="extend", required=True)
    parser.add_argument("--since", metavar="REV")
    parser.add_argument("--labels", type=Path, default=LABELS)
    args = parser.parse_args()
    try:
        named, extras = aliases(load_labels(args.labels))
    except (OSError, ValueError, LookupError, TypeError, AttributeError) as error:
        parser.error(f"--labels {args.labels}: {error!r}")
    unknown: set[str] = set()
    try:
        scanned = [scan(repo, args.since, named, extras, unknown) for repo in args.repo]
    except LookupError as error:
        print(f"backfill: {error}", file=sys.stderr)
        return 2
    path = journal_path()
    try:
        keys = known(path)
    except (OSError, ValueError) as error:
        return refused(path, error)
    added, summary = [], []
    for top, rows in scanned:
        fresh = []
        for row in sorted(rows, key=lambda row: (row["time"], row["sha"])):
            key = (row["remote"], row["sha"])
            if key not in keys:
                keys.add(key)
                fresh.append(row)
        added += fresh
        summary.append(f"{top}: {len(rows)} blocks, {len(fresh)} rows added")
    if added:
        try:
            append(path, added)
        except (OSError, ValueError) as error:
            return refused(path, error)
    print("\n".join(summary))
    for label in sorted(unknown):
        print(f"backfill: unknown label {label}, skipped", file=sys.stderr)
    return 0


def refused(path: Path, error: Exception) -> int:
    print(f"backfill: journal {path}: {getattr(error, 'strerror', None) or error}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
