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
    worktree and tip; then per repository it runs one `pkgmgr branch cleanup
    --local --json --branch <name>...` dry run over its signed branches and
    one `pkgmgr branch cleanup --apply --local --json --branch <name>...`
    over those the plan names exactly at the signed tip and worktree and
    deletes exactly the local branch of (signing.local_keeps, the predicate
    the hub offers by); pkgmgr deletes only a local branch whose planned tip
    is an ancestor of the default branch, by update-ref with that tip. While
    the tree file says pkgmgr has no GitHub token (delete_ready false), only
    a branch the dry run shows merged by ancestry into the default branch
    and without a remote branch is deleted; the others are refused with
    "token needed". Every other item is refused and nothing changes for it.
    An applied item is done only when pkgmgr's result for it is done, with a
    warning when pkgmgr deleted it at another merged tip than the signed
    one; one the apply keeps is failed with pkgmgr's skip reason. A signed
    branch pkgmgr did not report deleted whose ref is gone is gone, never
    done: "deleted outside this run" when pkgmgr answered without deleting
    it (a failed result, no result, or "Unknown --branch"), "gone after an
    interrupted apply" when the apply ended without JSON; a present one is
    failed. When a dry run or apply answers "Unknown --branch" for gone
    branches, it runs once more without them.
    Writes each item's result, rewrites the tree file after a deletion or a
    gone branch and removes the job. The exit code is 0.
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
GONE = "gone"
DELETED_OUTSIDE = "deleted outside this run"
GONE_INTERRUPTED = "gone after an interrupted apply"
UNKNOWN = re.compile(r"^Unknown --branch: (.*)$", re.MULTILINE)
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


def run(pkgmgr: Path, argv: list[str], cwd: str, timeout: int) -> tuple[int, str, str]:
    """Args:
        pkgmgr: the pkgmgr executable.
        argv: its arguments.
        cwd: the repository it runs in, without hooks or fsmonitor.
        timeout: seconds before pkgmgr is killed.

    Returns:
        Exit code, stdout and the tail of stderr; 127 with the error when
        pkgmgr could not start or was killed at the timeout.
    """
    try:
        done = subprocess.run([str(pkgmgr), *argv], cwd=cwd, env={**os.environ, **git_overrides()}, stdin=subprocess.DEVNULL, capture_output=True, text=True, errors="replace", timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        return 127, "", str(error)
    return done.returncode, done.stdout, done.stderr[-OUTPUT_LIMIT:]


def branch_tip(repository: str, branch: str) -> str | None:
    """Returns:
        The local branch's tip as git reads it in the repository and no
        parent of it, "" when the repository has no such branch, None when
        git cannot tell.
    """
    env = {**os.environ, **git_overrides(), "GIT_CEILING_DIRECTORIES": str(Path(repository).parent)}
    try:
        done = subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"], cwd=repository, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if done.returncode == 0 and TIP.fullmatch(done.stdout.strip()):
        return done.stdout.strip()
    return "" if done.returncode == 1 and not done.stdout.strip() else None


def unknown(stderr: str) -> set[str]:
    """Returns:
        The branch names pkgmgr's "Unknown --branch: a, b" line names.
    """
    return {name for found in UNKNOWN.findall(stderr) for name in found.split(", ")}


def plan_argv(branches: list[str], apply: bool) -> list[str]:
    """Args:
        branches: the exact branch names of one repository.
        apply: execute the plan instead of the dry run.

    Returns:
        The `pkgmgr branch cleanup --local` arguments for these branches'
        plan in JSON: local branches only, no forge token, no remote delete.
    """
    return ["branch", "cleanup", *(["--apply"] if apply else []), "--local", "--json", *[part for branch in branches for part in ("--branch", branch)]]


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


def tip_changed(entry: dict, item: dict) -> str | None:
    tip = entry.get("local_sha") or entry.get("head")
    return None if tip == item["tip"] else f"tip changed: signed {item['tip'][:12]}, now {str(tip)[:12]}"


def mismatch(entry: dict, item: dict) -> str | None:
    changed = tip_changed(entry, item)
    if changed:
        return changed
    if (entry.get("worktree") or "") != item["worktree"]:
        return f"worktree changed: signed {item['worktree'] or 'none'}, now {entry.get('worktree') or 'none'}"
    kept = signing.local_keeps(entry)
    return f"pkgmgr branch cleanup --local keeps it: {kept}" if kept else None


def refused(item: dict, reason: str) -> dict:
    return {**item, "status": "refused", "reason": reason}


def applied_result(item: dict, applied: list[dict] | None, code: int, stderr: str) -> dict:
    """Args:
        item: one signed item the apply chose.
        applied: every item `--apply` printed for its repository, None when
            it printed no JSON.
        code: the apply's exit code, 1 when any of its items failed.
        stderr: the apply's error output.

    Returns:
        The item done only when pkgmgr's result for it is done, with a
        warning as reason when pkgmgr deleted it at another tip than the
        signed one, which update-ref only does for the tip pkgmgr planned as
        merged; failed with pkgmgr's skip reason when the apply kept it.
        Without a done result its ref decides: gone is gone, "gone after an
        interrupted apply" when the apply printed no JSON and named no
        unknown branch, else "deleted outside this run"; present is failed
        with pkgmgr's reason.
    """
    mine = next((entry for entry in applied or [] if entry.get("branch") == item["branch"]), {})
    outcome = mine.get("result")
    moved = tip_changed(mine, item) if mine else None
    if isinstance(outcome, str) and outcome.split(";")[0] == DONE:
        warning = f"deleted at another merged tip than the signed dry run: {moved}" if moved else ""
        return {**item, "status": DONE, "reason": warning, "code": code, "applied": [mine]}
    if mine.get("skip") and not outcome:
        reason = f"pkgmgr branch cleanup --local keeps it: {mine['skip']}"
    elif moved:
        reason = f"the apply planned another tip than the signed dry run: {moved}"
    elif not (isinstance(outcome, str) and outcome.startswith("skipped")) and branch_tip(item["repository"], item["branch"]) == "":
        why = GONE_INTERRUPTED if applied is None and not unknown(stderr) else DELETED_OUTSIDE
        return {**item, "status": GONE, "reason": why, "code": code, "applied": [mine] if mine else []}
    else:
        reason = outcome if isinstance(outcome, str) and outcome else stderr.strip()[-500:] or f"pkgmgr reported no result for {item['branch']}"
    return {**item, "status": "failed", "reason": reason[:500], "code": code, "applied": [mine] if mine else []}


def screened(items: list[dict], plan: list[dict], default: str, ready: bool) -> dict[str, dict]:
    """Args:
        items: admitted items of one repository, each branch once.
        plan: the items of their dry run.
        default: the repository's default branch.
        ready: whether pkgmgr holds the GitHub token.

    Returns:
        The refusal by branch of each item the plan does not delete exactly
        at its signed tip and worktree, or without the token not token-free;
        of every item when the plan names other branches too.
    """
    others = sorted({str(entry.get("branch")) for entry in plan} - {item["branch"] for item in items})
    if others:
        return {item["branch"]: refused(item, f"the dry run names other branches too, a pattern match: {', '.join(others)[:500]}") for item in items}
    refusals = {}
    for item in items:
        mine = [entry for entry in plan if entry.get("branch") == item["branch"]]
        reason = mismatch(mine[0], item) if len(mine) == 1 else f"the dry run names {len(mine)} items for {item['branch']}"
        if reason is None and not ready and not signing.token_free(mine[0], default):
            reason = TOKEN_NEEDED
        if reason is not None:
            refusals[item["branch"]] = refused(item, reason)
    return refusals


class Cleanup:
    def __init__(self, trust: verifier.Trust, tree: Path, pkgmgr: Path) -> None:
        self.trust = trust
        self.tree = tree
        self.pkgmgr = pkgmgr

    def admitted(self, item: dict, proof: object, known: dict[str, str], now: float) -> str | None:
        """Args:
            item: one signed item with repository, branch, worktree and tip.
            proof: the job's {"payload", "assertion"}.
            known: the repositories the tree file says pkgmgr knows.
            now: the current time in epoch seconds.

        Returns:
            Why the item is refused before any dry run; None when the
            operator's signature lists it, pkgmgr knows its repository and
            its branch is an exact name.
        """
        try:
            verifier.check(proof, signing.cleanup_item(item["repository"], item["branch"], item["worktree"], item["tip"]), "", self.trust, now)
        except (signing.Refused, OSError) as error:
            return f"no valid operator signature: {error}"
        if item["repository"] not in known or not Path(item["repository"]).is_dir():
            return "unknown repository: pkgmgr does not list it"
        if UNSAFE.search(item["branch"]) or not item["branch"]:
            return "the branch name holds pattern or option characters; only an exact branch name is deleted"
        return None

    def attempt(self, items: list[dict], apply: bool, results: dict[str, dict]) -> tuple[list[dict], int, str, str]:
        """Args:
            items: items of one repository to plan or apply.
            apply: run the apply instead of the dry run.
            results: gets, by branch, each item that run names unknown whose
                ref is gone, as gone "deleted outside this run".

        Returns:
            The items of the last run with its exit code, stdout and stderr;
            after an "Unknown --branch" for gone branches the run repeats
            once without them.
        """
        location = items[0]["repository"]
        code, stdout, stderr = run(self.pkgmgr, plan_argv([item["branch"] for item in items], apply), location, TIMEOUT)
        named = unknown(stderr) if code != 0 else set()
        gone = [item for item in items if item["branch"] in named and branch_tip(location, item["branch"]) == ""]
        if gone:
            results.update({item["branch"]: {**item, "status": GONE, "reason": DELETED_OUTSIDE, "code": code} for item in gone})
            items = [item for item in items if item not in gone]
            if items:
                code, stdout, stderr = run(self.pkgmgr, plan_argv([item["branch"] for item in items], apply), location, TIMEOUT)
        return items, code, stdout, stderr

    def repository(self, items: list[dict], default: str, ready: bool) -> list[dict]:
        """Args:
            items: admitted items of one repository, each branch once.
            default: the repository's default branch.
            ready: whether pkgmgr holds the GitHub token; without it only a
                branch signing.token_free() accepts in the dry run is deleted.

        Returns:
            Each item with status done, gone, refused or failed and the
            reason, from one dry run over all of them and one apply over
            those the dry run plans to delete at the signed tip and worktree,
            each repeated once without the branches it names unknown and
            gone; refused items changed nothing.
        """
        results: dict[str, dict] = {}
        planned, code, stdout, stderr = self.attempt(items, False, results)
        plan = plan_items(stdout) if code == 0 else None
        if plan is None:
            results.update({item["branch"]: refused(item, f"the dry run failed ({code}): {stderr.strip()[-500:]}") for item in planned})
        else:
            results.update(screened(planned, plan, default, ready))
        chosen = [item for item in planned if item["branch"] not in results]
        if chosen:
            applying, code, stdout, stderr = self.attempt(chosen, True, results)
            applied = plan_items(stdout)
            results.update({item["branch"]: applied_result(item, applied, code, stderr) for item in applying})
        return [results[item["branch"]] for item in items]

    def job(self, folder: int, path: Path, now: float) -> dict:
        try:
            job = json.loads(verifier.read_regular(path, folder))
        except (OSError, ValueError) as error:
            return {"id": path.stem, "finished": now, "items": [], "error": f"unreadable job: {error}"}
        items = job.get("items") if isinstance(job, dict) else None
        if not isinstance(items, list) or not items or not all(map(shaped, items)) or job.get("id") != path.stem:
            return {"id": path.stem, "finished": now, "items": [], "error": "malformed job: refused, nothing deleted"}
        known, ready = tree_facts(self.tree)
        results: list[dict | None] = [None] * len(items)
        groups: dict[str, list[int]] = {}
        seen: set[tuple[str, str]] = set()
        for index, item in enumerate(items):
            reason = self.admitted(item, job.get("proof"), known, now)
            if reason is None and (item["repository"], item["branch"]) in seen:
                reason = "the job lists this branch twice"
            if reason is not None:
                results[index] = refused(item, reason)
                continue
            seen.add((item["repository"], item["branch"]))
            groups.setdefault(item["repository"], []).append(index)
        for location, indexes in groups.items():
            for index, outcome in zip(indexes, self.repository([items[index] for index in indexes], known[location], ready)):
                results[index] = outcome
        result = {"id": path.stem, "finished": time.time(), "items": results}
        if any(entry["status"] in (DONE, GONE) for entry in results):
            code, _, stderr = run(self.pkgmgr, ["branch", "tree", "--format", "json", "--output", str(self.tree)], str(self.tree.parent), TIMEOUT)
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
