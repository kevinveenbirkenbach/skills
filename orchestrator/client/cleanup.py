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
    --json --branch <name>` as a dry run and, only when that plan names
    exactly this branch as merged-clean without skip reason at the signed
    tip and worktree and deletes no remote branch, `pkgmgr branch cleanup
    --apply --json --branch <name>`. While the tree file says pkgmgr has no GitHub token
    (delete_ready false), only a branch the dry run shows merged by ancestry
    into the default branch and without a remote branch is deleted; the
    others are refused with "token needed". Every other item is refused and
    nothing changes for it. An applied item is done only when pkgmgr's
    result for it is done; a skipped one or one without result is failed
    with pkgmgr's reason. Writes each item's result, rewrites the tree file
    after a deletion and removes the job. The exit code is 0.
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
DONE = "done"
REMOTE_ACTION = "remote-branch:"
TOKEN_NEEDED = "token needed: without the GitHub token only a local branch merged by ancestry into the default branch and without a remote branch is deleted"
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


def tree_facts(tree: Path) -> tuple[dict[str, str], bool]:
    """Returns:
        The repositories the tree file says pkgmgr knows, each with its
        default branch, and whether pkgmgr found the GitHub token
        (delete_ready); nothing and False for an unreadable file.
    """
    try:
        data = json.loads(tree.read_text(encoding="utf-8"))
        known = {entry["path"]: entry.get("default") if isinstance(entry.get("default"), str) else "" for entry in data["repos"] if entry.get("known") is True and isinstance(entry.get("path"), str)}
        return known, data.get("delete_ready") is True
    except Exception:  # noqa: BLE001
        return {}, False


def run(pkgmgr: Path, argv: list[str], cwd: str) -> tuple[int, str, str]:
    try:
        done = subprocess.run([str(pkgmgr), *argv], cwd=cwd, env={**os.environ, **git_overrides()}, stdin=subprocess.DEVNULL, capture_output=True, text=True, errors="replace", timeout=TIMEOUT, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        return 127, "", str(error)
    return done.returncode, done.stdout, done.stderr[-OUTPUT_LIMIT:]


def plan_argv(branch: str, apply: bool) -> list[str]:
    """Args:
        branch: the exact branch name.
        apply: execute the plan instead of the dry run.

    Returns:
        The `pkgmgr branch cleanup` arguments for this branch's plan in JSON.
    """
    return ["branch", "cleanup", *(["--apply"] if apply else []), "--json", "--branch", branch]


def plan_items(stdout: str) -> list[dict] | None:
    """Returns:
        Every item of `pkgmgr branch cleanup --json`, which prints
        {"host_pid_namespace", "repos": [{"repo", "default", "merged_into",
        "warnings", "items"}]}; None for any other output.
    """
    try:
        data = json.loads(stdout)
    except ValueError:
        return None
    repos = data.get("repos") if isinstance(data, dict) else None
    if not isinstance(repos, list) or not all(isinstance(repo, dict) and isinstance(repo.get("items"), list) for repo in repos):
        return None
    items = [entry for repo in repos for entry in repo["items"]]
    return items if all(isinstance(entry, dict) for entry in items) else None


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
    remote = [str(action) for action in entry.get("actions") or [] if str(action).startswith(REMOTE_ACTION)]
    if remote:
        return f"the plan also deletes {', '.join(remote)[:200]}; a signed delete is local only"
    return None


class Cleanup:
    def __init__(self, trust: verifier.Trust, tree: Path, pkgmgr: Path) -> None:
        self.trust = trust
        self.tree = tree
        self.pkgmgr = pkgmgr

    def item(self, item: dict, proof: object, known: dict[str, str], ready: bool, now: float) -> dict:
        """Args:
            item: one signed item with repository, branch, worktree and tip.
            proof: the job's {"payload", "assertion"}.
            known: the repositories the tree file says pkgmgr knows, each
                with its default branch.
            ready: whether pkgmgr holds the GitHub token; without it only a
                branch signing.token_free() accepts in the dry run is deleted.
            now: the current time in epoch seconds.

        Returns:
            The item with status done, refused or failed and the reason;
            refused items changed nothing, failed ones are those pkgmgr did
            not report done.
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
        code, stdout, stderr = run(self.pkgmgr, plan_argv(item["branch"], False), item["repository"])
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
        if not ready and not signing.token_free(plan[0], known[item["repository"]]):
            return refused(TOKEN_NEEDED)
        code, stdout, stderr = run(self.pkgmgr, plan_argv(item["branch"], True), item["repository"])
        applied = plan_items(stdout) or []
        outcome = next((entry.get("result") for entry in applied if entry.get("branch") == item["branch"]), None)
        if code == 0 and isinstance(outcome, str) and outcome.split(";")[0] == DONE:
            return {**item, "status": "done", "reason": "", "code": code, "applied": applied}
        reason = outcome if isinstance(outcome, str) and outcome else stderr.strip()[-500:] or f"pkgmgr reported no result for {item['branch']}"
        return {**item, "status": "failed", "reason": reason[:500], "code": code, "applied": applied}

    def job(self, folder: int, path: Path, now: float) -> dict:
        try:
            job = json.loads(verifier.read_regular(path, folder))
        except (OSError, ValueError) as error:
            return {"id": path.stem, "finished": now, "items": [], "error": f"unreadable job: {error}"}
        items = job.get("items") if isinstance(job, dict) else None
        if not isinstance(items, list) or not items or not all(map(shaped, items)) or job.get("id") != path.stem:
            return {"id": path.stem, "finished": now, "items": [], "error": "malformed job: refused, nothing deleted"}
        known, ready = tree_facts(self.tree)
        results = [self.item(item, job.get("proof"), known, ready, now) for item in items]
        result = {"id": path.stem, "finished": time.time(), "items": results}
        if any(entry["status"] == "done" for entry in results):
            code, _, stderr = run(self.pkgmgr, ["branch", "tree", "--format", "json", "--output", str(self.tree)], str(self.tree.parent))
            result["tree"] = {"code": code, "error": stderr.strip()[-500:]}
        return result


def cycle(jobs: Path, results: Path, cleanup: Cleanup) -> int:
    def run(folder: int, name: str) -> dict | None:
        return cleanup.job(folder, Path(name), time.time()) if JOB.fullmatch(name) else None

    return verifier.drain(jobs, results, run)


def main() -> int:
    parser = argparse.ArgumentParser(prog="cleanup")
    parser.add_argument("--port", type=int, required=True)
    for name in ("--jobs", "--results", "--approvers", "--replay", "--tree", "--pkgmgr"):
        parser.add_argument(name, type=Path, required=True)
    args = parser.parse_args()
    trust = verifier.Trust(approvers=args.approvers, replay=args.replay, origin=signing.origin_of(args.port))
    cycle(args.jobs, args.results, Cleanup(trust, args.tree, args.pkgmgr))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
