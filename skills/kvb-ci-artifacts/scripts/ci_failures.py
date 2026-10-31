#!/usr/bin/env python3
"""Fetch the failed jobs of a GitHub Actions run and cluster them by error line.

Usage:
    ci_failures.py RUN_ID [--repo OWNER/REPO] [--out DIR] [--artifacts]

Prints how far HEAD moved since the run's commit, saves each finished failed
job's log (colour stripped) under DIR (default /tmp/ci-logs-RUN_ID), and
groups the jobs by the normalised error line that ended them (the last one). Jobs still running are
listed but not fetched: their API log can stop hours early. The clustering is
a heuristic; confirm a cluster's boundary against the logs.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

FAILED = {"failure", "cancelled", "timed_out"}
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
STAMP = re.compile(r"^\d{4}-\d\d-\d\dT[\d:.]+Z\s?")
GENERIC = re.compile(r"failed=0\b|FAILED - RETRYING|^make(\[\d+\])?: \*\*\* \[.*\] Error \d+")
PROCESS_END = re.compile(r"##\[error\]Process completed with exit code")
ANNOTATION = re.compile(r"##\[error\]")
FATAL = re.compile(r"fatal: \[|FAILED!|Traceback|AssertionError|panic:")
LINT_AT = re.compile(r"\S+:\d+:\d+:? ((error|warning) )?[A-Z]{1,4}\d{3,4}\b")
LINT_CODE = re.compile(r"^[A-Z]{1,4}\d{3,4}\b")
LINT_ARROW = re.compile(r"^-->\s+\S+:\d+:\d+")
SIGNAL = re.compile(r"\b(ERROR|Error|FAILED|FAIL|fatal|Exception|failed)\b")
TASK = re.compile(r"^TASK \[")
REFUSAL = "terminal escape sequences"


def run(*cmd: str) -> subprocess.CompletedProcess:
    return subprocess.run(list(cmd), capture_output=True, text=True, check=False)


def clean(line: str) -> str:
    return STAMP.sub("", ANSI.sub("", line)).strip()


def normalise(line: str) -> str:
    line = re.sub(r"\b[0-9a-f]{7,}\b", "<hex>", line)
    line = re.sub(r"\d+", "<n>", line)
    return line[:200]


def output_lines(text: str) -> list[tuple[str, str]]:
    kept, echo, task = [], False, ""
    for raw in text.splitlines():
        line = clean(raw)
        if PROCESS_END.search(line):
            break
        if line.startswith("##[group]Run "):
            echo = True
        elif line.startswith("##[endgroup]"):
            echo = False
        elif TASK.match(line):
            task = line
        elif line and not echo and not GENERIC.search(line):
            kept.append((task, line))
    return kept


def is_lint(lines: list[tuple[str, str]], index: int) -> bool:
    line = lines[index][1]
    if LINT_AT.search(line):
        return True
    following = lines[index + 1][1] if index + 1 < len(lines) else ""
    return bool(LINT_CODE.match(line) and LINT_ARROW.match(following))


def signature(text: str) -> str:
    lines = output_lines(text)
    tiers = (
        (lambda i: ANNOTATION.search(lines[i][1]), False),
        (lambda i: FATAL.search(lines[i][1]), True),
        (lambda i: is_lint(lines, i), False),
        (lambda i: SIGNAL.search(lines[i][1]), False),
    )
    for matches, with_task in tiers:
        for index in reversed(range(len(lines))):
            if matches(index):
                task, line = lines[index]
                found = ANNOTATION.sub("", line).strip()
                return normalise(f"{task} {found}" if with_task and task else found)
    return normalise(lines[-1][1]) if lines else "<empty log>"


def cluster(jobs: list[tuple[str, str]]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for job, text in jobs:
        groups.setdefault(signature(text), []).append(job)
    return dict(sorted(groups.items(), key=lambda item: -len(item[1])))


def behind(sha: str) -> str:
    if run("git", "cat-file", "-e", f"{sha}^{{commit}}").returncode:
        return "behind=unknown (run commit not in this clone)"
    count = run("git", "rev-list", "--count", f"{sha}..HEAD").stdout.strip()
    moved = {p.split("/")[0] for p in run("git", "diff", "--name-only", f"{sha}..HEAD").stdout.split()}
    return f"behind={count} moved={','.join(sorted(moved)) or '-'}"


def main() -> int:
    parser = argparse.ArgumentParser(prog="ci_failures")
    parser.add_argument("run_id")
    parser.add_argument("--repo")
    parser.add_argument("--out")
    parser.add_argument("--artifacts", action="store_true")
    args = parser.parse_args()
    repo = args.repo or run("gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner").stdout.strip()
    if not repo:
        parser.error("no --repo and gh cannot resolve the current repository")
    meta = run("gh", "api", f"/repos/{repo}/actions/runs/{args.run_id}")
    # per_page=100 on a large matrix answers HTTP 502; 30 per page goes through.
    listing = run("gh", "api", "--paginate", f"/repos/{repo}/actions/runs/{args.run_id}/jobs?per_page=30",
                  "--jq", ".jobs[] | {id, name, status, conclusion}")
    if meta.returncode or listing.returncode:
        print((meta.stderr or listing.stderr).strip(), file=sys.stderr)
        return 1
    data = json.loads(meta.stdout)
    jobs = [json.loads(line) for line in listing.stdout.splitlines() if line]
    out = Path(args.out or f"/tmp/ci-logs-{args.run_id}")
    out.mkdir(parents=True, exist_ok=True)
    print(f"run={args.run_id} repo={repo} head={data['head_sha'][:10]} status={data['status']} "
          f"jobs={len(jobs)} {behind(data['head_sha'])}")
    running = [j["name"] for j in jobs if j["status"] != "completed"]
    if running:
        print(f"running ({len(running)}, not fetched): {', '.join(running)}")
    fetched, missing = [], []
    for job in jobs:
        if job["status"] != "completed" or job["conclusion"] not in FAILED:
            continue
        log = run("gh", "api", "--allow-escape-sequences", f"/repos/{repo}/actions/jobs/{job['id']}/logs")
        if log.returncode or REFUSAL in log.stdout[:200]:
            missing.append(f"{job['conclusion']}\t{job['name']}\t{log.stderr.strip()[:80]}")
            continue
        slug = re.sub(r"[^A-Za-z0-9._-]+", "_", job["name"])[:80]
        path = out / f"{job['id']}-{slug}.log"
        path.write_text("\n".join(ANSI.sub("", line) for line in log.stdout.splitlines()), encoding="utf-8")
        text = "##[error]cancelled" if job["conclusion"] == "cancelled" else log.stdout
        fetched.append((f"{job['conclusion']}\t{job['name']}\t{path}", text))
    if missing:
        (out / "no-log.txt").write_text("\n".join(missing) + "\n", encoding="utf-8")
        counts = {c: sum(m.startswith(c) for m in missing) for c in FAILED}
        summary = ", ".join(f"{n} {c}" for c, n in sorted(counts.items()) if n)
        print(f"no log for {len(missing)} jobs ({summary}; never started or expired): {out / 'no-log.txt'}")
    for number, (sig, jobs) in enumerate(cluster(fetched).items(), 1):
        print(f"cluster {number} ({len(jobs)} jobs): {sig}")
        for job in jobs[:3]:
            print(f"  {job}")
        if len(jobs) > 3:
            members = out / f"cluster-{number}.txt"
            members.write_text("\n".join(jobs) + "\n", encoding="utf-8")
            print(f"  ... +{len(jobs) - 3} more: {members}")
    if args.artifacts:
        listing = run("gh", "api", f"/repos/{repo}/actions/runs/{args.run_id}/artifacts", "--paginate",
                      "--jq", '.artifacts[] | "\\(.name)\\t\\(.size_in_bytes)"')
        print("artifacts:")
        print(listing.stdout.rstrip() or "  none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
