#!/usr/bin/env python3
"""Scan the files a change touches with MEDUSA and fold the findings into one security percentage.

Args:
    --repo: git repository whose working tree holds the change.
    --base: git ref the change starts from.
    --json: print the figures as JSON instead of the line.

Scan:
    The regular files `git diff <ref>` names plus untracked ones, symlinks left
    out, copied to a temporary tree and scanned once with
    `medusa scan <tree> --format json -o <dir> --no-cache`, read from
    `<dir>/medusa-scan-*.json`: a `findings` list whose entries carry
    `severity` (critical, high, medium, low or info), `file` and `line`.

Output:
    `🛡️ security <n> % (medusa: <k> findings in <m> files: <severity> <path>:<line>, ...)`,
    m the files scanned, the first 5 locations by severity and `+<rest> more`.
    n = 100 - 50 * critical - 25 * high - 10 * medium - 2 * low, at least 0. Matched
    values are never printed. --json adds the counts per severity and every location.

Exit codes:
    0 security 100, 1 a critical finding, 2 usage error, 3 under 100 without a
    critical finding, 4 medusa missing or its report unreadable: review the diff by hand.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

WEIGHTS = {"critical": 50, "high": 25, "medium": 10, "low": 2, "info": 0}
SAFE = 100
SHOWN = 5
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
        line = entry.get("line")
        found.append({
            "severity": severity,
            "path": located(str(entry.get("file") or "?"), tree),
            "line": line if isinstance(line, int) else None,
        })
    rank = list(WEIGHTS)
    return sorted(found, key=lambda f: (rank.index(f["severity"]), f["path"], f["line"] or 0))


def scan(medusa: str, root: Path, base: str) -> tuple[int, list[dict]]:
    with tempfile.TemporaryDirectory(prefix="kvb-security-") as scratch:
        work = Path(scratch)
        tree, reports = work / "tree", work / "reports"
        tree.mkdir()
        scanned = copy(root, changed(root, base), tree)
        if not scanned:
            return 0, []
        result = subprocess.run(
            [medusa, "scan", str(tree), "--format", "json", "-o", str(reports), "--no-cache"],
            cwd=work, stdin=subprocess.DEVNULL, capture_output=True, check=False,
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

    medusa = shutil.which("medusa")
    problem = None if medusa else "medusa missing"
    if medusa:
        try:
            scanned, found = scan(medusa, root, args.base)
        except Unreadable as error:
            problem = f"medusa report unreadable: {error}"
    if problem:
        if args.json:
            print(json.dumps({"security": None, "problem": problem}))
        else:
            print(f"🛡️ security – ({problem}: {HAND})")
        return 4

    counts = {severity: sum(f["severity"] == severity for f in found) for severity in WEIGHTS}
    value = max(0, SAFE - sum(WEIGHTS[s] * n for s, n in counts.items()))
    if args.json:
        print(json.dumps({"security": value, "files": scanned, **counts, "findings": found}))
    else:
        places = [f"{f['severity']} {f['path']}:{f['line'] if f['line'] is not None else '?'}" for f in found]
        listed = ", ".join(places[:SHOWN]) + (f", +{len(places) - SHOWN} more" if len(places) > SHOWN else "")
        detail = f": {listed}" if places else ""
        print(f"🛡️ security {value} % (medusa: {plural(len(found), 'finding')} in {plural(scanned, 'file')}{detail})")
    if counts["critical"]:
        return 1
    return 3 if value < SAFE else 0


if __name__ == "__main__":
    sys.exit(main())
