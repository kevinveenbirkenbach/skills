from __future__ import annotations

import ast
import importlib.util
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from hub_case import HubCase
from hub_support import GIT_ENV, HUB, ORIGIN, key, signing, verifier

CLEANUP = HUB / "client" / "cleanup.py"
CLEANUP_SPEC = importlib.util.spec_from_file_location("kvb_orchestrator_cleanup_runner", CLEANUP)
host = importlib.util.module_from_spec(CLEANUP_SPEC)
CLEANUP_SPEC.loader.exec_module(host)
INSTALLED_PKGMGR = shutil.which("pkgmgr")
DONE_TIP = "5b1e6fd3a7c0e2d94f8a61b3c2d7e9f0a1b2c3d4"
OTHER_TIP = "1111111111111111111111111111111111111111"
# Param: format with python=<interpreter>; parses argv as pkgmgr's branch_cmd.py does (argparse exits 2 on any other flag) and prints the plan as gc.py _render does, {"host_pid_namespace", "repos": [{"repo", "default", "merged_into", "warnings", "items"}]}; plan.json beside it is the plan's items, next-tree.json the rewritten tree, outcome.txt the result --apply reports per item (done without it), exit 0 also for a skipped item.
FAKE_PKGMGR = """#!{python}
import argparse
import json
import os
import sys
from pathlib import Path

here = Path(__file__).parent
with (here / "calls.jsonl").open("a", encoding="utf-8") as log:
    log.write(json.dumps({{"argv": sys.argv[1:], "cwd": os.getcwd()}}) + "\\n")
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
    following = here / "next-tree.json"
    rewritten = following.read_text(encoding="utf-8") if following.exists() else json.dumps({{"rewritten": True}})
    Path(args.output).write_text(rewritten, encoding="utf-8")
    raise SystemExit(0)
items = json.loads((here / "plan.json").read_text(encoding="utf-8"))
if args.apply:
    outcome = here / "outcome.txt"
    result = outcome.read_text(encoding="utf-8") if outcome.exists() else "done"
    items = [{{**item, "result": result}} for item in items]
plan = {{"host_pid_namespace": True, "repos": [{{"repo": os.getcwd(), "default": "origin/main", "merged_into": [], "warnings": [], "items": items}}]}}
print(json.dumps(plan) if args.json else "\\n".join(str(item["branch"]) for item in items))
"""


class TestHubCleanup(HubCase):
    def ready(self, ready: bool, held: bool) -> dict:
        """Args:
            ready: delete_ready of the tree file.
            held: keep feature/done in its worktree; otherwise it is a local
                branch without one.
        """
        root = self.write_tree()
        data = json.loads(self.tree_file.read_text(encoding="utf-8"))
        data["delete_ready"], data["delete_reason"] = ready, "" if ready else "Secret Service locked"
        done = next(item for item in data["repos"][0]["items"] if item["branch"] == "feature/done")
        if not held:
            done.update(worktree=None, worktree_state=None, actions=["local-branch", "remote-branch"], compose_projects=[], images=[])
        self.tree_file.write_text(json.dumps(data), encoding="utf-8")
        return signing.cleanup_item(f"{root}/repos/github.com/me/demo", "feature/done", done["worktree"] or "", DONE_TIP)

    def branches(self) -> dict:
        status, _, body = self.get("/api/tree")
        self.assertEqual(status, 200, body)
        demo = next(repo for repo in json.loads(body)["repos"] if repo["name"] == "github.com/me/demo")
        return {entry["name"]: entry for entry in demo["branches"]}

    def sign(self, items: list[dict]) -> tuple[int, bytes]:
        status, _, body = self.post_json("/api/sign", {"items": items}, self.guard(self.host))
        return status, body

    def test_the_tree_offers_a_delete_only_for_merged_clean_branches_without_skip_reason(self):
        item = self.ready(False, False)
        branches = self.branches()
        done = branches["feature/done"]
        self.assertEqual((done["cleanup"], done["held"]), (item, ""))
        self.assertEqual(done["plan"], [
            "feature/done @ 5b1e6fd3a7c0: merged-clean, merged by #12",
            "deletes the local branch feature/done",
            "stays: remote-branch (local only; the host refuses a plan that deletes it)",
        ])
        self.assertEqual((done["merged_by"], done["merged_into"], done["gone"]), ("#12", "main", True))
        self.assertEqual({name: entry["cleanup"] for name, entry in branches.items() if name != "feature/done"}, {"feature": None, "feature/kept": None, "main": None})
        self.assertEqual(branches["feature/kept"]["skip"], "ignored files beyond known caches: notes.txt")

    def test_signing_a_delete_needs_delete_ready_and_exactly_an_offered_item(self):
        item = self.ready(False, False)
        status, body = self.sign([item])
        self.assertEqual((status, body.decode()), (400, "delete blocked: Secret Service locked\n"))
        item = self.ready(True, False)
        kept = {**item, "branch": "feature/kept", "worktree": "", "tip": "0c9d8e7f6a5b4c3d2e1f0a9b8c7d6e5f4a3b2c1d"}
        for name, items in (("changed tip", [{**item, "tip": OTHER_TIP}]), ("skip reason", [kept]), ("pattern", [{**item, "branch": "feature/*"}]), ("twice", [item, item]), ("extra key", [{**item, "command": "rm -rf /"}])):
            with self.subTest(name=name):
                self.assertEqual(self.sign(items)[0], 400)
        status, body = self.sign([item])
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)["payload"]["items"], [signing.item_hash(item)])

    def test_a_branch_held_by_a_worktree_offers_no_delete_and_names_branch_gc(self):
        item = self.ready(True, True)
        done = self.branches()["feature/done"]
        held = f"held by worktree {item['worktree']}: pkgmgr branch cleanup skips it, use branch gc (kvb-git-gc, pkgmgr gc)"
        self.assertEqual((done["cleanup"], done["held"], done["plan"][1]), (None, held, held))
        status, body = self.sign([item])
        self.assertEqual((status, body.decode()), (400, f"feature/done in {item['repository']} is no merged-clean branch without skip reason at that tip in the tree file\n"))
        page = (HUB / "templates" / "page-tree.js").read_text(encoding="utf-8")
        self.assertIn('if (entry.held) {\n      return h("span", {class: "hint held", title: entry.held}, chip("bi-folder-symlink", entry.held, "neutral"));', page)
        self.assertIn("deleteDialog(items, locked, held)", page)
        self.assertIn("held by a worktree: not deleted here", (HUB / "templates" / "page-cleanup.js").read_text(encoding="utf-8"))

    @unittest.skipUnless(INSTALLED_PKGMGR, "no pkgmgr installed")
    def test_every_volume_text_states_the_compose_down_argv_of_the_installed_pkgmgr(self):
        found = subprocess.run([str(Path(INSTALLED_PKGMGR).parent / "python"), "-I", "-c", "import pkgmgr.actions.branch.gc as gc; print(gc.__file__)"], capture_output=True, text=True, timeout=60, check=True)
        calls = [node for node in ast.walk(ast.parse(Path(found.stdout.strip()).read_text(encoding="utf-8"))) if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "_docker" and node.args and isinstance(node.args[0], ast.List)]
        downs = [["docker", *(part.value if isinstance(part, ast.Constant) else "{project}" for part in call.args[0].elts)] for call in calls if any(isinstance(part, ast.Constant) and part.value == "down" for part in call.args[0].elts)]
        self.assertEqual(len(downs), 1, downs)
        command = " ".join(downs[0]).format(project="demo-feature-done")
        self.ready(True, True)
        plan = self.branches()["feature/done"]["plan"]
        self.assertIn(f"branch gc would run {command}, which deletes the volumes of demo-feature-done", plan)
        self.assertIn("-v", downs[0])
        dialog = (HUB / "templates" / "page-cleanup.js").read_text(encoding="utf-8")
        self.assertIn("never touches a worktree, Compose stack or volume", dialog)
        self.assertIn("its docker compose down -v deletes the stack's volumes", dialog)
        texts = [*plan, dialog, (HUB / "kvb_orchestrator" / "tree.py").read_text(encoding="utf-8")]
        self.assertFalse([text for text in texts if "without -v" in text])

    def test_a_signed_delete_becomes_a_job_without_any_command(self):
        item = self.ready(True, False)
        signer = self.pin()
        proof = signer.proof(self.prepare([item])["payload"], self.origin)
        self.assertEqual(self.post_json("/api/cleanup", {"items": [item], "proof": None}, self.guard(self.host))[0], 400)
        self.assertEqual(self.post_json("/api/cleanup", {"items": [item], "proof": proof}, {"Host": self.host})[0], 403)
        status, _, body = self.post_json("/api/cleanup", {"items": [item], "proof": proof}, self.guard(self.host))
        self.assertEqual(status, 202, body)
        job_id = json.loads(body)["id"]
        written = self.cleanup / "jobs" / f"{job_id}.json"
        job = json.loads(written.read_text(encoding="utf-8"))
        self.assertEqual(sorted(job), ["created", "id", "items", "proof", "v"])
        self.assertEqual(job["items"], [{key_name: item[key_name] for key_name in ("repository", "branch", "worktree", "tip")}])
        self.assertEqual(job["proof"], proof)
        self.assertNotIn("command", written.read_text(encoding="utf-8"))
        self.assertEqual((written.stat().st_mode & 0o777, (self.cleanup / "jobs").stat().st_mode & 0o777), (0o600, 0o700))
        self.assertEqual(json.loads(self.get(f"/api/cleanup/{job_id}")[2])["status"], "queued")
        self.assertEqual(self.get("/api/cleanup/0000000000000000")[0], 404)
        result = {"id": job_id, "finished": time.time(), "items": [{**job["items"][0], "status": "done", "reason": ""}]}
        (self.cleanup / "results" / f"{job_id}.json").write_text(json.dumps(result), encoding="utf-8")
        self.assertEqual(json.loads(self.get(f"/api/cleanup/{job_id}")[2])["status"], "done")
        self.assertEqual(json.loads(self.get("/api/tree")[2])["cleanups"], [result])


class TestHostCleanup(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        self.repo = base / "repos" / "demo"
        self.repo.mkdir(parents=True)
        self.jobs, self.results = base / "jobs", base / "results"
        self.jobs.mkdir()
        self.results.mkdir()
        self.fake = base / "bin" / "pkgmgr"
        self.fake.parent.mkdir()
        self.fake.write_text(FAKE_PKGMGR.format(python=sys.executable), encoding="utf-8")
        self.fake.chmod(0o755)
        self.calls = self.fake.parent / "calls.jsonl"
        self.tree = base / "tree" / "branch-tree.json"
        self.tree.parent.mkdir()
        self.tree.write_text(json.dumps({"delete_ready": True, "repos": [{"path": str(self.repo), "known": True}, {"path": str(base / "stranger"), "known": False}]}), encoding="utf-8")
        self.approvers = base / "config" / "approvers.json"
        self.trust = verifier.Trust(approvers=self.approvers, replay=base / "replay" / "cleanup.json", origin=ORIGIN)
        self.signer = key(-7, "main")
        self.signer.pin(self.approvers, ORIGIN)
        self.item = {"repository": str(self.repo), "branch": "feature/done", "worktree": f"{self.repo}/.worktrees/feature-done", "tip": DONE_TIP}

    def proof(self, items: list[dict], signer) -> dict:
        hashes = [signing.item_hash(signing.cleanup_item(**item)) for item in items]
        return signer.proof(signing.approval_payload(hashes, secrets.token_hex(16), int(time.time()) + 600), ORIGIN)

    def entry(self, **changes: object) -> dict:
        return {"branch": self.item["branch"], "worktree": self.item["worktree"], "local_sha": DONE_TIP, "head": DONE_TIP, "state": "merged-clean", "skip": None, **changes}

    def run_job(self, items: list[dict], proof: object, plan: list[dict]) -> tuple[dict, list[dict]]:
        (self.fake.parent / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
        job_id = secrets.token_hex(8)
        (self.jobs / f"{job_id}.json").write_text(json.dumps({"v": 1, "id": job_id, "created": "x", "items": items, "proof": proof}), encoding="utf-8")
        self.assertEqual(host.cycle(self.jobs, self.results, host.Cleanup(self.trust, self.tree, self.fake)), 1)
        self.assertEqual(list(self.jobs.iterdir()), [])
        calls = [json.loads(line) for line in self.calls.read_text(encoding="utf-8").splitlines()] if self.calls.exists() else []
        self.calls.unlink(missing_ok=True)
        return json.loads((self.results / f"{job_id}.json").read_text(encoding="utf-8")), calls

    def test_a_signed_merged_clean_item_is_dry_run_then_deleted_by_exact_name(self):
        result, calls = self.run_job([self.item], self.proof([self.item], self.signer), [self.entry()])
        self.assertEqual([(entry["status"], entry["reason"]) for entry in result["items"]], [("done", "")])
        selector = ["--json", "--branch", "feature/done"]
        self.assertEqual(calls, [
            {"argv": ["branch", "cleanup", *selector], "cwd": str(self.repo)},
            {"argv": ["branch", "cleanup", "--apply", *selector], "cwd": str(self.repo)},
            {"argv": ["branch", "tree", "--format", "json", "--output", str(self.tree)], "cwd": str(self.tree.parent)},
        ])
        self.assertEqual(json.loads(self.tree.read_text(encoding="utf-8")), {"rewritten": True})
        self.assertEqual(result["tree"], {"code": 0, "error": ""})

    def test_an_apply_that_exits_0_but_skips_or_reports_no_result_is_failed_with_pkgmgrs_reason_and_keeps_the_tree(self):
        outcome = self.fake.parent / "outcome.txt"
        before = self.tree.read_text(encoding="utf-8")
        cases = (("skipped", "skipped: changed since plan (dirty: 1 paths)", "skipped: changed since plan (dirty: 1 paths)"), ("no result", "", "pkgmgr reported no result for feature/done"))
        for name, result, reason in cases:
            with self.subTest(name=name):
                outcome.write_text(result, encoding="utf-8")
                done, calls = self.run_job([self.item], self.proof([self.item], self.signer), [self.entry()])
                self.assertEqual([(entry["status"], entry["reason"], entry["code"]) for entry in done["items"]], [("failed", reason, 0)])
                self.assertEqual([call["argv"][:3] for call in calls], [["branch", "cleanup", "--json"], ["branch", "cleanup", "--apply"]])
                self.assertNotIn("tree", done)
                self.assertEqual(self.tree.read_text(encoding="utf-8"), before)
        outcome.write_text("done; image kept: demo:feature-done", encoding="utf-8")
        done, _ = self.run_job([self.item], self.proof([self.item], self.signer), [self.entry()])
        self.assertEqual([(entry["status"], entry["reason"]) for entry in done["items"]], [("done", "")])

    def test_every_doubtful_item_is_refused_and_changes_nothing(self):
        pattern = {**self.item, "branch": "feature/*"}
        option = {**self.item, "branch": "--all"}
        stranger = {**self.item, "repository": str(self.repo.parent.parent / "stranger")}
        rule = self.signer.proof(signing.rule_payload(secrets.token_hex(8), ["review"], "", "*", "*", int(time.time()) + 600), ORIGIN)
        cases = (
            ("bad signature", [self.item], self.proof([self.item], key(-7, "intruder")), [self.entry()], "no valid operator signature", 0),
            ("missing signature", [self.item], None, [self.entry()], "no signature", 0),
            ("rule instead of approval", [self.item], rule, [self.entry()], "no valid operator signature", 0),
            ("other item signed", [self.item], self.proof([{**self.item, "tip": OTHER_TIP}], self.signer), [self.entry()], "does not list this item", 0),
            ("unknown repository", [stranger], self.proof([stranger], self.signer), [self.entry()], "unknown repository", 0),
            ("pattern characters", [pattern], self.proof([pattern], self.signer), [self.entry(branch="feature/*")], "pattern or option characters", 0),
            ("option name", [option], self.proof([option], self.signer), [self.entry(branch="--all")], "pattern or option characters", 0),
            ("changed tip", [self.item], self.proof([self.item], self.signer), [self.entry(local_sha=OTHER_TIP)], "tip changed", 1),
            ("not merged-clean", [self.item], self.proof([self.item], self.signer), [self.entry(state="dirty")], "state is dirty", 1),
            ("skip reason", [self.item], self.proof([self.item], self.signer), [self.entry(skip="ignored files")], "gc skip reason", 1),
            ("other worktree", [self.item], self.proof([self.item], self.signer), [self.entry(worktree="/elsewhere")], "worktree changed", 1),
            ("pattern match in pkgmgr", [self.item], self.proof([self.item], self.signer), [self.entry(), self.entry(branch="feature/done-too")], "other branches too", 1),
            ("remote branch delete", [self.item], self.proof([self.item], self.signer), [self.entry(actions=["local-branch", "remote-branch:origin"])], "a signed delete is local only", 1),
        )
        for name, items, proof, plan, reason, dry_runs in cases:
            with self.subTest(name=name):
                result, calls = self.run_job(items, proof, plan)
                self.assertEqual([entry["status"] for entry in result["items"]], ["refused"])
                self.assertIn(reason, result["items"][0]["reason"])
                self.assertEqual([call["argv"] for call in calls], [["branch", "cleanup", "--json", "--branch", items[0]["branch"]]] * dry_runs)
                self.assertNotIn("tree", result)

    def test_a_signature_deletes_once_and_a_malformed_job_nothing(self):
        proof = self.proof([self.item], self.signer)
        self.assertEqual(self.run_job([self.item], proof, [self.entry()])[0]["items"][0]["status"], "done")
        again, calls = self.run_job([self.item], proof, [self.entry()])
        self.assertEqual((again["items"][0]["status"], calls), ("refused", []))
        self.assertIn("already used", again["items"][0]["reason"])
        for name, items in (("command smuggled in", [{**self.item, "command": "rm -rf ~"}]), ("relative repository", [{**self.item, "repository": "demo"}]), ("no items", [])):
            with self.subTest(name=name):
                result, calls = self.run_job(items, proof, [self.entry()])
                self.assertEqual((result["items"], calls), ([], []))
                self.assertIn("malformed job", result["error"])

    def test_the_unit_runs_the_script_once_over_the_job_directory(self):
        (self.fake.parent / "plan.json").write_text(json.dumps([self.entry()]), encoding="utf-8")
        job_id = secrets.token_hex(8)
        (self.jobs / f"{job_id}.json").write_text(json.dumps({"v": 1, "id": job_id, "created": "x", "items": [self.item], "proof": self.proof([self.item], self.signer)}), encoding="utf-8")
        (self.jobs / "stray.tmp").write_text("x", encoding="utf-8")
        trust = ["--approvers", str(self.approvers), "--replay", str(self.trust.replay)]
        command = [sys.executable, str(CLEANUP), "--port", ORIGIN.rsplit(":", 1)[1], "--jobs", str(self.jobs), "--results", str(self.results), *trust, "--tree", str(self.tree), "--pkgmgr", str(self.fake)]
        done = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(list(self.jobs.iterdir()), [])
        result = json.loads((self.results / f"{job_id}.json").read_text(encoding="utf-8"))
        self.assertEqual(result["items"][0]["status"], "done")
        self.assertEqual((self.results / f"{job_id}.json").stat().st_mode & 0o777, 0o600)


@unittest.skipUnless(INSTALLED_PKGMGR, "no pkgmgr installed")
class TestInstalledPkgmgrContract(unittest.TestCase):
    def git(self, cwd: Path, *args: str) -> str:
        return subprocess.run(["git", *args], cwd=cwd, env={**os.environ, **GIT_ENV}, check=True, capture_output=True, text=True).stdout.strip()

    def test_the_installed_pkgmgr_takes_the_runners_dry_run_argv_and_prints_a_plan_the_runner_parses_and_accepts(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            origin, repo = base / "origin.git", base / "repo"
            self.git(base, "init", "-q", "--bare", "-b", "main", str(origin))
            self.git(base, "init", "-q", "-b", "main", str(repo))
            self.git(repo, "remote", "add", "origin", origin.as_uri())
            self.git(repo, "commit", "-q", "--allow-empty", "-m", "one")
            self.git(repo, "checkout", "-q", "-b", "side")
            self.git(repo, "commit", "-q", "--allow-empty", "-m", "side")
            tip = self.git(repo, "rev-parse", "HEAD")
            self.git(repo, "checkout", "-q", "main")
            self.git(repo, "merge", "-q", "--no-ff", "-m", "merge side", "side")
            self.git(origin, "fetch", "-q", str(repo), "main:main")
            self.git(repo, "fetch", "-q", "origin")
            self.git(repo, "remote", "set-head", "origin", "main")
            code, stdout, stderr = host.run(Path(INSTALLED_PKGMGR), host.plan_argv("side", False), str(repo))
            self.assertEqual(code, 0, stderr)
            plan = host.plan_items(stdout)
            self.assertIsNotNone(plan, stdout[:500])
            self.assertEqual([(entry["branch"], entry["state"], entry["merged_by"], entry["merged_into"], entry["skip"], entry["actions"]) for entry in plan], [("side", "merged-clean", "ancestor", "origin/main", None, ["local-branch"])])
            self.assertIsNone(host.mismatch(plan[0], {"tip": tip, "worktree": ""}))
            self.assertTrue(signing.token_free(plan[0], "main"))
            self.assertEqual(self.git(repo, "rev-parse", "refs/heads/side"), tip)
            held = base / "held"
            self.git(repo, "worktree", "add", "-q", str(held), "side")
            code, stdout, stderr = host.run(Path(INSTALLED_PKGMGR), host.plan_argv("side", False), str(repo))
            self.assertEqual(code, 0, stderr)
            plan = host.plan_items(stdout)
            self.assertEqual([(entry["worktree"], entry["actions"], bool(entry["skip"])) for entry in plan], [(os.path.realpath(held), [], True)], plan)
            self.assertIn("gc skip reason", host.mismatch(plan[0], {"tip": tip, "worktree": os.path.realpath(held)}))


class TestHostCleanupGitConfig(unittest.TestCase):
    def test_pkgmgr_runs_no_hook_the_repository_config_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            repo, hooks, marker = base / "repo", base / "hooks", base / "hook-ran"
            hooks.mkdir()
            (hooks / "reference-transaction").write_text(f"#!/bin/sh\necho path >> {marker}\n", encoding="utf-8")
            (hooks / "reference-transaction").chmod(0o755)
            git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false"]
            subprocess.run([*git, "init", "-q", str(repo)], check=True)
            subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "x"], cwd=repo, check=True)
            subprocess.run(["git", "branch", "control"], cwd=repo, check=True)
            subprocess.run(["git", "branch", "doomed"], cwd=repo, check=True)
            subprocess.run(["git", "config", "core.hooksPath", str(hooks)], cwd=repo, check=True)
            subprocess.run(["git", "config", "hook.spy.event", "reference-transaction"], cwd=repo, check=True)
            subprocess.run(["git", "config", "hook.spy.command", f"echo config >> {marker}"], cwd=repo, check=True)
            subprocess.run(["git", "branch", "-D", "control"], cwd=repo, check=True, capture_output=True)
            self.assertEqual({line.split()[0] for line in marker.read_text(encoding="utf-8").splitlines()}, {"path", "config"})
            marker.unlink()
            fake = base / "pkgmgr"
            fake.write_text(f"#!{sys.executable}\nimport subprocess\nsubprocess.run(['git', 'branch', '-D', '--', 'doomed'], check=True)\n", encoding="utf-8")
            fake.chmod(0o755)
            code, _, error = host.run(fake, ["branch", "cleanup", "--apply"], str(repo))
            self.assertEqual(code, 0, error)
            self.assertFalse(marker.exists())
            branches = subprocess.run(["git", "branch", "--format=%(refname:short)"], cwd=repo, capture_output=True, text=True, check=True).stdout.split()
            self.assertNotIn("doomed", branches)


if __name__ == "__main__":
    unittest.main()
