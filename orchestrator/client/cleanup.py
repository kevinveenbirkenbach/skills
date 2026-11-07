#!/usr/bin/env python3
"""Args:
    --port: port of the Agent Orchestrator; the signature's origin is
        http://localhost:<port>.
    --jobs: the directory the hub writes signed jobs into, e.g.
        ~/.local/state/kvb-orchestrator/cleanup/jobs.
    --results: the directory each job's result goes to as <id>.json.
    --approvers: the pinned passkeys, e.g. ~/.config/kvb-orchestrator/approvers.json.
    --replay: this runner's replay store, outside the hub's reach, e.g.
        ~/.local/state/kvb-orchestrator-approvals/cleanup.json.
    --tree: the tree file `pkgmgr branch tree` writes; it names the
        repositories pkgmgr knows and is rewritten after a deletion.
    --pkgmgr: the pkgmgr executable built from a signed tag.

Returns:
    Runs once over every job in --jobs, as the operator on the host: per item
    it verifies the operator's passkey signature over repository, branch,
    worktree and tip, then in the repository runs `pkgmgr branch cleanup
    --json --local --branch <name>` as a dry run and, only when that plan
    names exactly this branch as merged-clean without skip reason at the
    signed tip and worktree, `pkgmgr branch cleanup --apply --json --local
    --branch <name>`. Every other item is refused and nothing changes for
    it. Writes each item's result, rewrites the tree file after a deletion
    and removes the job. The exit code is 0.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from pathlib import Path

import signing
import verifier

JOB = re.compile(r"[0-9a-f]{16}\.json")
ITEM_KEYS = ("repository", "branch", "worktree", "tip")
TIP = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
UNSAFE = re.compile(r"[*?\[\]\\\s\x00-\x1f\x7f]|^-|\.\.|@\{")
OUTPUT_LIMIT = 16 << 10
TIMEOUT = 600
# the cwd is a repository agents can write: its config may name hooks, and
# pkgmgr releases before 4c8b137 run git branch -D without scan mode
GIT_OVERRIDES = (
    ("core.hooksPath", "/dev/null"),
    ("core.fsmonitor", "false"),
    ("hook.reference-transaction.enabled", "false"),
    ("hook.post-checkout.enabled", "false"),
    ("hook.post-index-change.enabled", "false"),
)


def git_overrides() -> dict[str, str]:
    env = {"GIT_CONFIG_COUNT": str(len(GIT_OVERRIDES))}
    for index, (name, value) in enumerate(GIT_OVERRIDES):
        env[f"GIT_CONFIG_KEY_{index}"] = name
        env[f"GIT_CONFIG_VALUE_{index}"] = value
    return env


def known_repositories(tree: Path) -> set[str]:
    try:
        data = json.loads(tree.read_text(encoding="utf-8"))
        return {entry["path"] for entry in data["repos"] if entry.get("known") is True and isinstance(entry.get("path"), str)}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return set()


def run(pkgmgr: Path, argv: list[str], cwd: str) -> tuple[int, str, str]:
    try:
        done = subprocess.run([str(pkgmgr), *argv], cwd=cwd, env={**os.environ, **git_overrides()}, stdin=subprocess.DEVNULL, capture_output=True, text=True, errors="replace", timeout=TIMEOUT, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        return 127, "", str(error)
    return done.returncode, done.stdout, done.stderr[-OUTPUT_LIMIT:]


def plan_items(stdout: str) -> list[dict] | None:
    try:
        data = json.loads(stdout)
    except ValueError:
        return None
    items = data.get("items") if isinstance(data, dict) else data
    if not isinstance(items, list) or not all(isinstance(entry, dict) for entry in items):
        return None
    return items


def shaped(item: object) -> bool:
    if not isinstance(item, dict) or set(item) != set(ITEM_KEYS) or not all(isinstance(item[key], str) for key in ITEM_KEYS):
        return False
    return item["repository"].startswith("/") and bool(TIP.fullmatch(item["tip"])) and (item["worktree"] == "" or item["worktree"].startswith("/"))


def mismatch(entry: dict, item: dict) -> str | None:
    if entry.get("state") != "merged-clean":
        return f"state is {entry.get('state')}, not merged-clean"
    if entry.get("skip"):
        return f"gc skip reason: {entry['skip']}"
    tip = entry.get("local_sha") or entry.get("head")
    if tip != item["tip"]:
        return f"tip changed: signed {item['tip'][:12]}, now {str(tip)[:12]}"
    if (entry.get("worktree") or "") != item["worktree"]:
        return f"worktree changed: signed {item['worktree'] or 'none'}, now {entry.get('worktree') or 'none'}"
    return None


class Cleanup:
    def __init__(self, trust: verifier.Trust, tree: Path, pkgmgr: Path) -> None:
        self.trust = trust
        self.tree = tree
        self.pkgmgr = pkgmgr

    def item(self, item: dict, proof: object, known: set[str], now: float) -> dict:
        """Args:
            item: one signed item with repository, branch, worktree and tip.
            proof: the job's {"payload", "assertion"}.
            known: the repositories the tree file says pkgmgr knows.
            now: the current time in epoch seconds.

        Returns:
            The item with status done, refused or failed and the reason;
            refused and failed items changed nothing.
        """
        def refused(reason: str) -> dict:
            return {**item, "status": "refused", "reason": reason}

        try:
            verifier.check(proof, signing.cleanup_item(item["repository"], item["branch"], item["worktree"], item["tip"]), "", self.trust, now)
        except (signing.Refused, OSError) as error:
            return refused(f"no valid operator signature: {error}")
        if item["repository"] not in known or not Path(item["repository"]).is_dir():
            return refused("unknown repository: pkgmgr does not list it")
        if UNSAFE.search(item["branch"]) or not item["branch"]:
            return refused("the branch name holds pattern or option characters; only an exact branch name is deleted")
        selector = ["--json", "--local", "--branch", item["branch"]]
        code, stdout, stderr = run(self.pkgmgr, ["branch", "cleanup", *selector], item["repository"])
        plan = plan_items(stdout) if code == 0 else None
        if plan is None:
            return refused(f"the dry run failed ({code}): {stderr.strip()[-500:]}")
        others = sorted({str(entry.get("branch")) for entry in plan} - {item["branch"]})
        if others:
            return refused(f"the dry run names other branches too, a pattern match: {', '.join(others)[:500]}")
        if len(plan) != 1:
            return refused(f"the dry run names {len(plan)} items for {item['branch']}")
        reason = mismatch(plan[0], item)
        if reason:
            return refused(reason)
        code, stdout, stderr = run(self.pkgmgr, ["branch", "cleanup", "--apply", *selector], item["repository"])
        applied = plan_items(stdout)
        status = "done" if code == 0 else "failed"
        return {**item, "status": status, "reason": "" if code == 0 else stderr.strip()[-500:], "code": code, "applied": applied if applied is not None else []}

    def job(self, path: Path, now: float) -> dict:
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            return {"id": path.stem, "finished": now, "items": [], "error": f"unreadable job: {error}"}
        items = job.get("items") if isinstance(job, dict) else None
        if not isinstance(items, list) or not items or not all(map(shaped, items)) or job.get("id") != path.stem:
            return {"id": path.stem, "finished": now, "items": [], "error": "malformed job: refused, nothing deleted"}
        known = known_repositories(self.tree)
        results = [self.item(item, job.get("proof"), known, now) for item in items]
        result = {"id": path.stem, "finished": time.time(), "items": results}
        if any(entry["status"] == "done" for entry in results):
            code, _, stderr = run(self.pkgmgr, ["branch", "tree", "--format", "json", "--output", str(self.tree)], str(self.tree.parent))
            result["tree"] = {"code": code, "error": stderr.strip()[-500:]}
        return result


def cycle(jobs: Path, results: Path, cleanup: Cleanup) -> int:
    handled = 0
    for path in sorted(jobs.iterdir()):
        if not JOB.fullmatch(path.name) or not path.is_file():
            path.unlink(missing_ok=True)
            continue
        verifier.write_private(results / path.name, cleanup.job(path, time.time()))
        path.unlink(missing_ok=True)
        handled += 1
    return handled


def main() -> int:
    parser = argparse.ArgumentParser(prog="cleanup")
    parser.add_argument("--port", type=int, required=True)
    for name in ("--jobs", "--results", "--approvers", "--replay", "--tree", "--pkgmgr"):
        parser.add_argument(name, type=Path, required=True)
    args = parser.parse_args()
    trust = verifier.Trust(approvers=args.approvers, replay=args.replay, origin=signing.origin_of(args.port))
    args.results.mkdir(mode=0o700, parents=True, exist_ok=True)
    cycle(args.jobs, args.results, Cleanup(trust, args.tree, args.pkgmgr))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
