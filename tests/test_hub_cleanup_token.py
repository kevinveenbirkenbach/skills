from __future__ import annotations

import importlib.util
import json
import os
import secrets
import shlex
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from hub_case import HubCase
from hub_support import GIT_ENV, HUB, ORIGIN, REPO_ROOT, key, signing, verifier

CLEANUP_SPEC = importlib.util.spec_from_file_location("kvb_orchestrator_cleanup_token_runner", HUB / "client" / "cleanup.py")
host = importlib.util.module_from_spec(CLEANUP_SPEC)
CLEANUP_SPEC.loader.exec_module(host)
OPERATOR_SPEC = importlib.util.spec_from_file_location("kvb_operator_for_token", REPO_ROOT / "skills" / "kvb-org-operator" / "scripts" / "operator.py")
operator_script = importlib.util.module_from_spec(OPERATOR_SPEC)
OPERATOR_SPEC.loader.exec_module(operator_script)
KEPT_TIP = "0c9d8e7f6a5b4c3d2e1f0a9b8c7d6e5f4a3b2c1d"
DONE_TIP = "5b1e6fd3a7c0e2d94f8a61b3c2d7e9f0a1b2c3d4"
# Param: format with python=<interpreter>; plans one branch of the real repository in its cwd as pkgmgr 2.4.0 `branch cleanup` does without a GitHub token: argv parsed as branch_cmd.py does (exit 2 on any other flag), merged_into the remote HEAD ref (gc.py symbolic-ref --short), an origin on github.com skips every item with "forge unavailable" (gc.py _skip), actions local-branch plus remote-branch:<remote> (gc.py _actions), --apply deletes only an item without skip (Item.eligible) and the output is gc.py _render's {"host_pid_namespace", "repos": [{"repo", "default", "merged_into", "warnings", "items"}]}.
SCRATCH_PKGMGR = """#!{python}
import argparse
import json
import os
import subprocess

parser = argparse.ArgumentParser(prog="pkgmgr")
branch = parser.add_subparsers(dest="command", required=True).add_parser("branch").add_subparsers(dest="subcommand", required=True)
tree = branch.add_parser("tree")
tree.add_argument("--format", choices=("json", "yaml"), default="json")
tree.add_argument("--output")
cleanup = branch.add_parser("cleanup")
for flag in ("--apply", "--json", "--all", "--sizes"):
    cleanup.add_argument(flag, action="store_true")
for option in ("--branch", "--exclude", "--merged-into"):
    cleanup.add_argument(option, action="append", default=[])
cleanup.add_argument("--min-age", type=float)
args = parser.parse_args()
if args.subcommand == "tree":
    raise SystemExit(0)


def git(*argv):
    return subprocess.run(["git", *argv], capture_output=True, text=True, check=False)


name = args.branch[0]
tip = git("rev-parse", "--verify", "refs/heads/" + name).stdout.strip()
default = git("symbolic-ref", "--short", "refs/remotes/origin/HEAD").stdout.strip()
merged = bool(tip) and git("merge-base", "--is-ancestor", tip, default).returncode == 0
listed = git("for-each-ref", "refs/remotes", "--format=%(refname:lstrip=2) %(objectname)").stdout.split("\\n")
remotes = {{line.split("/", 1)[0]: line.split(" ")[1] for line in listed if line and line.split(" ")[0].split("/", 1)[1] == name}}
skip = "forge unavailable" if "github.com" in git("remote", "get-url", "origin").stdout else None
actions = ["local-branch", *("remote-branch:" + remote for remote in remotes)] if merged else []
entry = {{"branch": name, "worktree": None, "local_sha": tip, "head": None, "state": "merged-clean" if merged else "unmerged", "skip": skip,
         "merged_by": "ancestor" if merged else None, "merged_into": default if merged else None, "remotes": remotes, "actions": actions, "result": None}}
if args.apply and skip is None:
    git("branch", "-D", "--", name)
    entry["result"] = "done"
print(json.dumps({{"host_pid_namespace": True, "repos": [{{"repo": os.getcwd(), "default": default, "merged_into": [], "warnings": [], "items": [entry]}}]}}))
"""


class TestHubCleanupToken(HubCase):
    def tree(self, ready: bool, kept_skip: str | None) -> Path:
        root = self.write_tree()
        data = json.loads(self.tree_file.read_text(encoding="utf-8"))
        data["delete_ready"], data["delete_reason"] = ready, "" if ready else "no GitHub token in the Secret Service"
        kept = next(item for item in data["repos"][0]["items"] if item["branch"] == "feature/kept")
        kept["skip"] = kept_skip
        done = next(item for item in data["repos"][0]["items"] if item["branch"] == "feature/done")
        done.update(worktree=None, worktree_state=None, actions=["local-branch"], compose_projects=[], images=[])
        self.tree_file.write_text(json.dumps(data), encoding="utf-8")
        return root

    def items(self, root: Path) -> tuple[dict, dict]:
        repo = f"{root}/repos/github.com/me/demo"
        return (signing.cleanup_item(repo, "feature/kept", "", KEPT_TIP),
                signing.cleanup_item(repo, "feature/done", "", DONE_TIP))

    def branches(self) -> dict:
        status, _, body = self.get("/api/tree")
        self.assertEqual(status, 200, body)
        demo = next(repo for repo in json.loads(body)["repos"] if repo["name"] == "github.com/me/demo")
        return {entry["name"]: entry for entry in demo["branches"]}

    def test_only_a_local_branch_merged_by_ancestry_into_the_default_branch_without_remote_is_token_free(self):
        self.tree(False, None)
        branches = self.branches()
        self.assertEqual({name: entry["token_free"] for name, entry in branches.items()}, {"feature": False, "feature/done": False, "feature/kept": True, "main": False})
        entry = {"merged_by": "ancestor", "merged_into": "main", "remotes": {}}
        cases = (("ancestry, no remote", entry, "main", True), ("pull request", {**entry, "merged_by": "#12"}, "main", False),
                 ("remote branch", {**entry, "remotes": {"origin": "a" * 40}}, "main", False), ("other line", {**entry, "merged_into": "store-i18n"}, "main", False),
                 ("no default", entry, None, False), ("line merge", {**entry, "merged_by": "line:main"}, "main", False),
                 ("pkgmgr names the remote HEAD", {**entry, "merged_into": "origin/main"}, "main", True), ("other remote line", {**entry, "merged_into": "origin/store-i18n"}, "main", False),
                 ("nested name", {**entry, "merged_into": "origin/feature/main"}, "main", False), ("no merged_into", {**entry, "merged_into": None}, "main", False))
        for name, candidate, default, free in cases:
            with self.subTest(name=name):
                self.assertEqual(signing.token_free(candidate, default), free)

    def test_without_the_token_the_dry_run_offers_the_token_free_branch_and_blocks_the_rest(self):
        kept, done = self.items(self.tree(False, None))
        status, _, body = self.post_json("/api/sign", {"items": [kept]}, self.guard(self.host))
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)["payload"]["items"], [signing.item_hash(kept)])
        for items in ([done], [kept, done]):
            with self.subTest(items=[item["branch"] for item in items]):
                status, _, body = self.post_json("/api/sign", {"items": items}, self.guard(self.host))
                self.assertEqual((status, body.decode()), (400, "delete blocked: no GitHub token in the Secret Service\n"))
        signer = self.pin()
        proof = signer.proof(self.prepare([kept])["payload"], self.origin)
        status, _, body = self.post_json("/api/cleanup", {"items": [kept], "proof": proof}, self.guard(self.host))
        self.assertEqual(status, 202, body)

    def test_on_the_real_tokenless_tree_the_ancestor_merged_local_branch_is_token_free_and_only_the_forge_free_one_is_offered(self):
        root = self.write_fixture("branch-tree-tokenless.json")
        status, _, body = self.get("/api/tree")
        self.assertEqual(status, 200, body)
        repos = {repo["name"]: {entry["name"]: entry for entry in repo["branches"]} for repo in json.loads(body)["repos"]}
        shown = {name: {branch: (entry["token_free"], entry["cleanup"] is not None, entry["skip"]) for branch, entry in branches.items()} for name, branches in repos.items()}
        self.assertEqual(shown, {
            "github.com/anon/web": {"chore/ancestor-local": (True, False, "forge unavailable"), "fix/remote-merged": (False, False, "forge unavailable"), "feature/open": (False, False, "forge unavailable"), "main": (False, False, None)},
            "git.example.org/anon/notes": {"topic/ancestor-local": (True, True, None), "topic/patch-local": (False, True, None), "master": (False, False, None)},
        })
        notes = repos["git.example.org/anon/notes"]
        free, patch = notes["topic/ancestor-local"]["cleanup"], notes["topic/patch-local"]["cleanup"]
        self.assertEqual(free, signing.cleanup_item(f"{root}/repos/git.example.org/anon/notes", "topic/ancestor-local", "", "5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f"))
        status, _, body = self.post_json("/api/sign", {"items": [free]}, self.guard(self.host))
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)["payload"]["items"], [signing.item_hash(free)])
        status, _, body = self.post_json("/api/sign", {"items": [patch]}, self.guard(self.host))
        self.assertEqual((status, body.decode()), (400, "delete blocked: no GitHub token in the Secret Service\n"))

    def test_with_the_token_every_merged_clean_branch_without_skip_reason_is_offered(self):
        kept, done = self.items(self.tree(True, None))
        status, _, body = self.post_json("/api/sign", {"items": [kept, done]}, self.guard(self.host))
        self.assertEqual(status, 200, body)
        self.assertEqual(sorted(json.loads(body)["payload"]["items"]), sorted(signing.item_hash(item) for item in (kept, done)))
        kept, _ = self.items(self.tree(True, "ignored files beyond known caches: notes.txt"))
        self.assertEqual(self.post_json("/api/sign", {"items": [kept]}, self.guard(self.host))[0], 400)

    def test_store_token_adds_one_operator_row_whose_command_stores_the_token_under_pkgmgrs_key(self):
        status, _, body = self.post_json("/api/cleanup/token", {}, self.guard(self.host))
        self.assertEqual((status, json.loads(body)), (201, {"task": "operator/pkgmgr-github-token", "status": "queued"}))
        self.assertEqual(len(self.scripts.calls), 1)
        script, args = self.scripts.calls[0]
        self.assertEqual((script, args[:4]), ("kvb-org-operator/scripts/operator.py", ["add", "pkgmgr-github-token", "--dir", "/"]))
        command = args[args.index("--command") + 1]
        self.assertEqual(shlex.split(command), ["env", "secret-tool", "store", "--label=pkgmgr-github", "service", "pkgmgr:github", "username", "github.com|-", "</dev/tty"])
        self.assertEqual(args[args.index("--check") + 1], "manual")
        self.assertIsNone(operator_script.unrunnable(command, "/"))
        self.assertEqual(self.post_json("/api/cleanup/token", {"extra": 1}, self.guard(self.host))[0], 400)
        self.assertEqual(self.post_json("/api/cleanup/token", {}, {"Host": self.host})[0], 403)
        self.assertEqual(self.get("/api/cleanup/token")[0], 405)


class TestHostCleanupWithoutToken(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        self.repo = base / "repo"
        self.git("init", "-q", "-b", "main", str(self.repo), cwd=base)
        self.git("commit", "-q", "--allow-empty", "-m", "one")
        self.git("branch", "local-merged")
        self.git("branch", "remote-merged")
        self.git("branch", "squash-candidate")
        self.git("commit", "-q", "--allow-empty", "-m", "two")
        self.git("checkout", "-q", "squash-candidate")
        self.git("commit", "-q", "--allow-empty", "-m", "side")
        self.git("checkout", "-q", "main")
        self.git("remote", "add", "origin", "ssh://git@git.example.org/anon/repo.git")
        self.git("update-ref", "refs/remotes/origin/main", self.tip("main"))
        self.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        self.git("update-ref", "refs/remotes/origin/remote-merged", self.tip("remote-merged"))
        self.jobs, self.results = base / "jobs", base / "results"
        self.jobs.mkdir(mode=0o700)
        self.results.mkdir(mode=0o700)
        self.fake = base / "bin" / "pkgmgr"
        self.fake.parent.mkdir()
        self.fake.write_text(SCRATCH_PKGMGR.format(python=sys.executable), encoding="utf-8")
        self.fake.chmod(0o755)
        self.tree = base / "tree" / "branch-tree.json"
        self.tree.parent.mkdir()
        self.tree.write_text(json.dumps({"delete_ready": False, "delete_reason": "no GitHub token in the Secret Service", "repos": [{"path": str(self.repo), "known": True, "default": "main"}]}), encoding="utf-8")
        self.approvers = base / "config" / "approvers.json"
        self.trust = verifier.Trust(approvers=self.approvers, replay=base / "replay" / "cleanup.json", origin=ORIGIN)
        self.signer = key(-7, "main")
        self.signer.pin(self.approvers, ORIGIN)

    def git(self, *args: str, cwd: Path | None = None) -> str:
        return subprocess.run(["git", *args], cwd=cwd or self.repo, env={**os.environ, **GIT_ENV}, check=True, capture_output=True, text=True).stdout.strip()

    def tip(self, branch: str) -> str:
        return self.git("rev-parse", f"refs/heads/{branch}")

    def branches(self) -> set[str]:
        return set(self.git("for-each-ref", "refs/heads", "--format=%(refname:short)").split())

    def run_job(self, names: list[str]) -> dict:
        items = [{"repository": str(self.repo), "branch": name, "worktree": "", "tip": self.tip(name)} for name in names]
        hashes = [signing.item_hash(signing.cleanup_item(**item)) for item in items]
        proof = self.signer.proof(signing.approval_payload(hashes, secrets.token_hex(16), int(time.time()) + 600), ORIGIN)
        job_id = secrets.token_hex(8)
        (self.jobs / f"{job_id}.json").write_text(json.dumps({"v": 1, "id": job_id, "created": "x", "items": items, "proof": proof}), encoding="utf-8")
        self.assertEqual(host.cycle(self.jobs, self.results, host.Cleanup(self.trust, self.tree, self.fake)), 1)
        result = json.loads((self.results / f"{job_id}.json").read_text(encoding="utf-8"))
        return {entry["branch"]: entry for entry in result["items"]}

    def test_the_executor_deletes_a_local_merged_branch_without_token_and_refuses_a_remote_one(self):
        result = self.run_job(["local-merged", "remote-merged"])
        self.assertEqual(result["local-merged"]["status"], "done", result["local-merged"]["reason"])
        self.assertEqual(result["remote-merged"]["status"], "refused")
        self.assertIn("a signed delete is local only", result["remote-merged"]["reason"])
        self.assertEqual(self.branches(), {"main", "remote-merged", "squash-candidate"})

    def test_without_token_an_unmerged_squash_candidate_stays_and_with_the_token_a_plan_that_deletes_the_remote_branch_is_refused(self):
        result = self.run_job(["squash-candidate"])
        self.assertEqual(result["squash-candidate"]["status"], "refused")
        self.assertIn("not merged-clean", result["squash-candidate"]["reason"])
        data = json.loads(self.tree.read_text(encoding="utf-8"))
        self.tree.write_text(json.dumps({**data, "delete_ready": True}), encoding="utf-8")
        remote = self.run_job(["remote-merged"])["remote-merged"]
        self.assertEqual((remote["status"], remote["reason"]), ("refused", "the plan also deletes remote-branch:origin; a signed delete is local only"))
        self.assertEqual(self.branches(), {"main", "local-merged", "remote-merged", "squash-candidate"})

    def test_without_token_pkgmgr_skips_every_item_of_a_github_repository_so_the_executor_refuses_and_keeps_even_the_token_free_branch(self):
        self.git("remote", "set-url", "origin", "git@github.com:anon/repo.git")
        result = self.run_job(["local-merged"])["local-merged"]
        self.assertEqual((result["status"], result["reason"]), ("refused", "gc skip reason: forge unavailable"))
        self.assertIn("local-merged", self.branches())


if __name__ == "__main__":
    unittest.main()
