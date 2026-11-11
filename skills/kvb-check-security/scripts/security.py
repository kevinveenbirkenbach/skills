#!/usr/bin/env python3
"""Scan the files a change touches with MEDUSA and fold the findings into one security percentage.

Args:
    --repo: git repository whose working tree holds the change.
    --base: git ref the change starts from.
    --json: print the figures as JSON instead of the line.

    accept --repo <root> --rule <rule_id> [--rule ...] --path <repo path> --sha1 <40 hex> --reason <one line>:
        record reviewed false positives of one line instead, a row per rule; --json
        of a scan prints rule, path and sha1 of every finding.

Scan:
    The regular files `git diff <ref>` names plus untracked ones, symlinks left
    out, copied to a temporary tree and scanned once with
    `medusa scan <tree> --format json -o <dir> --no-cache`, HOME pointing into
    the temporary directory because medusa creates ~/.medusa on start, read from
    `<dir>/medusa-scan-*.json`: a `findings` list whose entries carry
    `severity` (critical, high, medium, low or info), `rule_id`, `file` and `line`.

Accepted:
    One JSON row per reviewed false positive (id, rule, path, sha1 of the stripped
    source line, or of the whole file for a finding without a line, reason, repo,
    date), appended by accept to
    <council root>/security-accepted.jsonl of the kvb-org-organize watch.py, whose
    hook keeps the rows in ~/.local/state/agents-council/security-accepted.jsonl;
    a scan reads both. A finding with that rule, path and text is accepted and
    leaves the score; an edit of the line, or of the file, brings it back. A row
    without rule, path and sha1 is a usage error.

Output:
    `🛡️ security <n> % (medusa: <k> findings, <a> accepted in <m> files: <severity> <path>:<line>, ...)`,
    `, <a> accepted` only when a is above 0, m the files scanned, the first 5
    locations by severity and `+<rest> more`.
    n = 100 - 50 * critical - 25 * high - 10 * medium - 2 * low, at least 0. Matched
    values are never printed. --json adds the counts per severity, every location
    with its rule and sha1, and the accepted ones.

Exit codes:
    0 security 100, 1 a critical finding, 2 usage error, 3 under 100 without a
    critical finding, 4 medusa missing or its report unreadable: review the diff by hand.
"""

from __future__ import annotations

import argparse
import datetime
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

WEIGHTS = {"critical": 50, "high": 25, "medium": 10, "low": 2, "info": 0}
SAFE = 100
SHOWN = 5
SHA1 = re.compile(r"[0-9a-f]{40}")
WATCH = Path(__file__).resolve().parents[2] / "kvb-org-organize" / "scripts" / "watch.py"
HAND = (
    "review trust boundaries, secrets and injection in the diff by hand, "
    "then pass --security '~<n>' to kvb-check-score"
)


class Unreadable(Exception):
    pass


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


def copy(root: Path, paths: list[str], tree: Path) -> int:
    copied = 0
    for name in paths:
        source = root / name
        # Trip-wire: a symlink's target may lie outside the repository; even a copied link lets the scan read it.
        if source.is_symlink() or not source.is_file():
            continue
        target = tree / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied += 1
    return copied


def located(name: str, tree: Path) -> str:
    path = Path(name)
    if not path.is_absolute():
        path = tree / path if (tree / path).exists() else tree.parent / path
    try:
        return path.resolve().relative_to(tree.resolve()).as_posix()
    except ValueError:
        return name


def fingerprint(tree: Path, path: str, line: int | None) -> str | None:
    try:
        text = (tree / path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if line is None:
        return hashlib.sha1(text.encode()).hexdigest()
    rows = text.splitlines()
    if not 1 <= line <= len(rows):
        return None
    return hashlib.sha1(rows[line - 1].strip().encode()).hexdigest()


def watch():
    if not WATCH.is_file():
        fail(f"{WATCH} is missing; its council paths hold the accepted findings")
    spec = importlib.util.spec_from_file_location("kvb_security_watch", WATCH)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def accepted(listings: tuple[Path, ...]) -> set[tuple[str, str, str]]:
    entries = set()
    for listing in listings:
        if not listing.is_file():
            continue
        for number, line in enumerate(listing.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                entries.add((row["rule"], row["path"], row["sha1"]))
            except (ValueError, KeyError, TypeError):
                fail(f"{listing}:{number}: want a JSON row with rule, path and sha1")
    return entries


def accept(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="security.py accept", description="Record a reviewed false positive.")
    for flag in ("--repo", "--path", "--sha1", "--reason"):
        parser.add_argument(flag, required=True)
    parser.add_argument("--rule", action="append", required=True)
    args = parser.parse_args(argv)
    if not SHA1.fullmatch(args.sha1):
        parser.error("--sha1 must be 40 lowercase hex digits")
    if not args.reason.strip() or "\n" in args.reason:
        parser.error("--reason must be one non-empty line")
    root = git(Path(args.repo), "rev-parse", "--show-toplevel").strip()
    date = datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")
    rows = [
        {
            "id": hashlib.sha1(f"{rule}\t{args.path}\t{args.sha1}".encode()).hexdigest(), "rule": rule,
            "path": args.path, "sha1": args.sha1, "reason": args.reason, "repo": root, "date": date,
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


def findings(reports: Path, tree: Path) -> list[dict]:
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
    found = []
    for entry in entries:
        severity = str(entry.get("severity", "")).lower() if isinstance(entry, dict) else ""
        if severity not in WEIGHTS:
            raise Unreadable(f"{files[-1].name}: a finding without a known severity")
        line = entry.get("line") if isinstance(entry.get("line"), int) else None
        path = located(str(entry.get("file") or "?"), tree)
        found.append({
            "severity": severity,
            "rule": entry.get("rule_id") if isinstance(entry.get("rule_id"), str) else None,
            "path": path,
            "line": line,
            "sha1": fingerprint(tree, path, line),
        })
    rank = list(WEIGHTS)
    return sorted(found, key=lambda f: (rank.index(f["severity"]), f["path"], f["line"] or 0))


def scan(medusa: str, root: Path, base: str) -> tuple[int, list[dict]]:
    with tempfile.TemporaryDirectory(prefix="kvb-security-") as scratch:
        work = Path(scratch)
        tree, reports, home = work / "tree", work / "reports", work / "home"
        tree.mkdir()
        home.mkdir()
        scanned = copy(root, changed(root, base), tree)
        if not scanned:
            return 0, []
        result = subprocess.run(
            [medusa, "scan", str(tree), "--format", "json", "-o", str(reports), "--no-cache"],
            cwd=work, stdin=subprocess.DEVNULL, capture_output=True, check=False,
            env={**os.environ, "HOME": str(home)},
        )
        try:
            return scanned, findings(reports, tree)
        except Unreadable as error:
            raise Unreadable(f"{error} (medusa exit {result.returncode})") from None


def plural(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"


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
            scanned, every = scan(medusa, root, args.base)
        except Unreadable as error:
            problem = f"medusa report unreadable: {error}"
    if problem:
        if args.json:
            print(json.dumps({"security": None, "problem": problem}))
        else:
            print(f"🛡️ security – ({problem}: {HAND})")
        return 4

    passed = [f for f in every if (f["rule"], f["path"], f["sha1"]) in reviewed]
    found = [f for f in every if f not in passed]
    counts = {severity: sum(f["severity"] == severity for f in found) for severity in WEIGHTS}
    value = max(0, SAFE - sum(WEIGHTS[s] * n for s, n in counts.items()))
    if args.json:
        print(json.dumps({"security": value, "files": scanned, **counts, "findings": found, "accepted": passed}))
    else:
        places = [f"{f['severity']} {f['path']}:{f['line'] if f['line'] is not None else '?'}" for f in found]
        listed = ", ".join(places[:SHOWN]) + (f", +{len(places) - SHOWN} more" if len(places) > SHOWN else "")
        detail = f": {listed}" if places else ""
        waived = f", {len(passed)} accepted" if passed else ""
        print(
            f"🛡️ security {value} % (medusa: {plural(len(found), 'finding')}{waived} "
            f"in {plural(scanned, 'file')}{detail})"
        )
    if counts["critical"]:
        return 1
    return 3 if value < SAFE else 0


if __name__ == "__main__":
    sys.exit(accept(sys.argv[2:]) if sys.argv[1:2] == ["accept"] else main())
