from __future__ import annotations

import ast
import importlib.util
import json
import os
import re
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
from kvb_orchestrator import tree

CLEANUP = HUB / "client" / "cleanup.py"
CLEANUP_SPEC = importlib.util.spec_from_file_location("kvb_orchestrator_cleanup_runner", CLEANUP)
host = importlib.util.module_from_spec(CLEANUP_SPEC)
CLEANUP_SPEC.loader.exec_module(host)
INSTALLED_PKGMGR = shutil.which("pkgmgr")
DONE_TIP = "5b1e6fd3a7c0e2d94f8a61b3c2d7e9f0a1b2c3d4"
OTHER_TIP = "1111111111111111111111111111111111111111"
# Param: format with python=<interpreter>; parses argv as pkgmgr's branch_cmd.py does (argparse exits 2 on any other flag) and prints the plan as gc.py _render does, {"host_pid_namespace", "repos": [{"repo", "default", "merged_into", "warnings", "items"}]}; plan.json beside it is the plan's items, apply.json the items --apply plans instead when present, next-tree.json the rewritten tree, outcome.txt the result --apply reports per item without skip (done without it; an item with skip gets none, as pkgmgr applies only eligible items), killed makes --apply exit 137 without output, unknown.json {"plan": [names], "apply": [names]} the branches that vanished before that run (pkgmgr's "Unknown --branch: a, b" on stderr and exit 2 when one is asked for, else left out of the plan), slow.txt names a cwd it sleeps 30 s in before planning, exit 0 also for a skipped item.
FAKE_PKGMGR = """#!{python}
import argparse
import json
import os
import sys
import time
from pathlib import Path

here = Path(__file__).parent
with (here / "calls.jsonl").open("a", encoding="utf-8") as log:
    log.write(json.dumps({{"argv": sys.argv[1:], "cwd": os.getcwd()}}) + "\\n")
slow = here / "slow.txt"
if slow.exists() and slow.read_text(encoding="utf-8") == os.getcwd():
    time.sleep(30)
parser = argparse.ArgumentParser(prog="pkgmgr")
branch = parser.add_subparsers(dest="command", required=True).add_parser("branch").add_subparsers(dest="subcommand", required=True)
tree = branch.add_parser("tree")
tree.add_argument("--format", choices=("json", "yaml"), default="json")
tree.add_argument("--output")
cleanup = branch.add_parser("cleanup")
for flag in ("--apply", "--json", "--local", "--all", "--sizes"):
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
if args.apply and (here / "apply.json").exists():
    items = json.loads((here / "apply.json").read_text(encoding="utf-8"))
unknown = here / "unknown.json"
vanished = json.loads(unknown.read_text(encoding="utf-8")).get("apply" if args.apply else "plan", []) if unknown.exists() else []
missing = [name for name in args.branch if name in vanished]
if missing:
    print(f"Unknown --branch: {{', '.join(missing)}}", file=sys.stderr)
    raise SystemExit(2)
items = [item for item in items if item["branch"] not in vanished]
if args.apply and (here / "killed").exists():
    raise SystemExit(137)
if args.apply:
    outcome = here / "outcome.txt"
    result = outcome.read_text(encoding="utf-8") if outcome.exists() else "done"
    items = [item if item.get("skip") else {{**item, "result": result}} for item in items]
plan = {{"host_pid_namespace": True, "repos": [{{"repo": os.getcwd(), "default": "origin/main", "merged_into": [], "warnings": [], "items": items}}]}}
print(json.dumps(plan) if args.json else "\\n".join(str(item["branch"]) for item in items))
"""
RECORDED = Path(__file__).parent / "branch-cleanup-local.json"
RECORDED_REPO = "@REPO@"
CAPTURE_DATE = "2026-11-14T12:00:00+00:00"
KEPT_PATCH = "merged by patch, tip is no ancestor of refs/remotes/origin/main"


def capture_local_plan(base: Path, pkgmgr: Path) -> tuple[Path, dict]:
    """Args:
        base: an empty directory for the origin and the repository.
        pkgmgr: the pkgmgr to plan with.

    Returns:
        The repository and the plan pkgmgr prints for `branch cleanup
        --local --json` in it, built with fixed dates so every sha repeats:
        side merged by ancestry; squashed squash-merged, so its tip is no
        ancestor of main; topic, whose local tip is an ancestor of main
        while its remote tip was cherry-picked onto main.
    """
    env = {**os.environ, **GIT_ENV, "GIT_AUTHOR_DATE": CAPTURE_DATE, "GIT_COMMITTER_DATE": CAPTURE_DATE}

    def git(cwd: Path, *args: str) -> str:
        return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout.strip()

    def commit(repo: Path, name: str) -> str:
        (repo / f"{name}.txt").write_text(name, encoding="utf-8")
        git(repo, "add", f"{name}.txt")
        git(repo, "commit", "-q", "-m", name)
        return git(repo, "rev-parse", "HEAD")

    origin, repo = base / "origin.git", base / "repo"
    git(base, "init", "-q", "--bare", "-b", "main", str(origin))
    git(base, "init", "-q", "-b", "main", str(repo))
    git(repo, "remote", "add", "origin", origin.as_uri())
    git(repo, "commit", "-q", "--allow-empty", "-m", "one")
    for name in ("side", "squashed", "topic"):
        git(repo, "checkout", "-q", "-b", name, "main")
        commit(repo, name)
    git(repo, "checkout", "-q", "topic")
    remote_tip = commit(repo, "topic-remote")
    git(repo, "push", "-q", "origin", "topic:topic")
    git(repo, "reset", "-q", "--hard", "topic~1")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--no-ff", "-m", "merge side and topic", "side", "topic")
    git(repo, "merge", "-q", "--squash", "squashed")
    git(repo, "commit", "-q", "-m", "squashed as one commit")
    git(repo, "cherry-pick", remote_tip)
    git(repo, "push", "-q", "origin", "main:main")
    git(repo, "fetch", "-q", "origin")
    git(repo, "remote", "set-head", "origin", "main")
    code, stdout, stderr = host.run(pkgmgr, ["branch", "cleanup", "--local", "--json"], str(repo), host.TIMEOUT)
    if code != 0:
        raise AssertionError(stderr)
    return repo, json.loads(stdout)


def recorded_plan(repo: str) -> dict:
    """Returns:
        The plan the installed pkgmgr printed for capture_local_plan(),
        recorded in branch-cleanup-local.json, its repository named repo.
    """
    return json.loads(RECORDED.read_text(encoding="utf-8").replace(RECORDED_REPO, repo))


class TestHubCleanup(HubCase):
    def ready(self, ready: bool, held: bool, merged_by: str, local: dict[str, dict]) -> dict:
        """Args:
            ready: delete_ready of the tree file.
            held: keep feature/done in its worktree; otherwise it is a local
                branch without one.
            merged_by: what merged feature/done over all its tips, as pkgmgr
                gc.py _merged_by names it: ancestor, pr#N, line:X or patch.
            local: branch -> fields of its `--local` dry run item that
                replace the ones HubCase.write_local_plan models.
        """
        root = self.write_tree()
        data = json.loads(self.tree_file.read_text(encoding="utf-8"))
        data["delete_ready"], data["delete_reason"] = ready, "" if ready else "Secret Service locked"
        done = next(item for item in data["repos"][0]["items"] if item["branch"] == "feature/done")
        done["merged_by"] = merged_by
        if not held:
            done.update(worktree=None, worktree_state=None, actions=["local-branch", "remote-branch"], remotes={"origin": DONE_TIP}, compose_projects=[], images=[])
        self.tree_file.write_text(json.dumps(data), encoding="utf-8")
        self.write_local_plan(data, local)
        return signing.cleanup_item(f"{root}/repos/github.com/me/demo", "feature/done", done["worktree"] or "", DONE_TIP)

    def refusal(self, item: dict) -> str:
        return f"{item['branch']} in {item['repository']} is no merged-clean branch without skip reason that the --local dry run deletes at that tip\n"

    def branches(self) -> dict:
        status, _, body = self.get("/api/tree")
        self.assertEqual(status, 200, body)
        demo = next(repo for repo in json.loads(body)["repos"] if repo["name"] == "github.com/me/demo")
        return {entry["name"]: entry for entry in demo["branches"]}

    def sign(self, items: list[dict]) -> tuple[int, bytes]:
        status, _, body = self.post_json("/api/sign", {"items": items}, self.guard(self.host))
        return status, body

    def test_the_tree_offers_a_delete_only_for_merged_clean_branches_without_skip_reason(self):
        item = self.ready(False, False, "ancestor", {})
        branches = self.branches()
        done = branches["feature/done"]
        self.assertEqual((done["cleanup"], done["held"], done["kept"]), (item, "", ""))
        self.assertEqual(done["plan"], [
            "feature/done @ 5b1e6fd3a7c0: merged-clean, merged by ancestor",
            "deletes the local branch feature/done",
            "stays: remote-branch (local only; the host refuses a plan that deletes it)",
        ])
        self.assertEqual((done["merged_by"], done["merged_into"], done["gone"]), ("ancestor", "main", True))
        self.assertEqual({name: entry["cleanup"] for name, entry in branches.items() if name != "feature/done"}, {"feature": None, "feature/kept": None, "main": None})
        self.assertEqual(branches["feature/kept"]["skip"], "ignored files beyond known caches: notes.txt")

    def test_the_local_dry_run_decides_by_its_actions_not_by_what_merged_the_branch(self):
        deletes = {"state": "merged-clean", "merged_by": "ancestor", "skip": None, "actions": ["local-branch"]}
        cases = (
            ("ancestry", deletes, ""),
            ("local tip an ancestor, remote tip patch-merged", {**deletes, "merged_by": "patch"}, ""),
            ("tip no ancestor", {**deletes, "merged_by": "patch", "skip": KEPT_PATCH, "actions": []}, KEPT_PATCH),
            ("not merged", {**deletes, "state": "unmerged", "actions": []}, "state is unmerged, not merged-clean"),
            ("no state", {"actions": ["local-branch"]}, "state is None, not merged-clean"),
            ("remote delete", {**deletes, "actions": ["local-branch", "remote-branch:origin"]}, "the plan also deletes remote-branch:origin; a signed delete is local only"),
            ("nothing planned", {**deletes, "actions": []}, "the dry run plans no delete, not exactly the local branch"),
            ("no actions", {key: value for key, value in deletes.items() if key != "actions"}, "the dry run plans no delete, not exactly the local branch"),
            ("worktree too", {**deletes, "actions": ["worktree", "local-branch"]}, "the dry run plans worktree, local-branch, not exactly the local branch"),
        )
        for name, entry, kept in cases:
            with self.subTest(name=name):
                self.assertEqual(signing.local_keeps(entry), kept)

    def test_a_branch_the_local_dry_run_keeps_offers_no_delete_and_its_dry_run_says_why_from_that_dry_run(self):
        for merged_by in ("pr#12", "patch"):
            with self.subTest(merged_by=merged_by):
                item = self.ready(True, False, merged_by, {})
                done = self.branches()["feature/done"]
                kept = f"pkgmgr branch cleanup --local keeps it: merged by {merged_by}, tip is no ancestor of refs/remotes/origin/main; use branch gc (kvb-git-gc, pkgmgr gc)"
                self.assertEqual((done["cleanup"], done["held"], done["kept"], done["token_free"]), (None, "", kept, False))
                self.assertEqual(done["plan"], [
                    f"feature/done @ 5b1e6fd3a7c0: merged-clean, merged by {merged_by}",
                    kept,
                    "branch gc would delete the local branch feature/done",
                    "branch gc would delete remote-branch",
                ])
                status, body = self.sign([item])
                self.assertEqual((status, body.decode()), (400, self.refusal(item)))
        page = (HUB / "templates" / "page-tree.js").read_text(encoding="utf-8")
        self.assertIn('if (entry.kept) {\n      return h("span", {class: "hint kept", title: entry.kept}, chip("bi-sign-merge-left", entry.kept, "neutral"));\n    }\n    if (!entry.cleanup) {', page)
        self.assertIn("!entry.held && !entry.kept && (entry.cleanup", page)
        self.assertIn("deleteDialog(items, locked, held, kept)", page)
        self.assertIn('keeps ? chip("bi-sign-merge-left", "kept by the --local dry run: not deleted here", "neutral")', (HUB / "templates" / "page-cleanup.js").read_text(encoding="utf-8"))

    def test_a_branch_whose_local_tip_the_local_dry_run_deletes_is_offered_although_its_remote_tip_was_patch_merged(self):
        item = self.ready(True, False, "patch", {"feature/done": {"skip": None, "actions": ["local-branch"]}})
        done = self.branches()["feature/done"]
        self.assertEqual((done["cleanup"], done["kept"], done["merged_by"]), (item, "", "patch"))
        self.assertEqual(done["plan"][1], "deletes the local branch feature/done")
        status, body = self.sign([item])
        self.assertEqual(status, 200, body)

    def test_a_branch_another_branch_tracks_as_local_upstream_is_kept_as_pkgmgr_keeps_it_when_the_host_chooses_it_alone(self):
        kept = "pkgmgr branch cleanup --local keeps it: kept: local upstream of feature; use branch gc (kvb-git-gc, pkgmgr gc)"
        cases = (
            ("local upstream", {"feature": {"upstream": "feature/done"}}, kept),
            ("local upstream git shortens with heads/", {"feature": {"upstream": "heads/feature/done"}}, kept),
            ("remote upstream of the same name", {"feature": {"upstream": "origin/feature/done"}}, ""),
            ("its own upstream", {"feature/done": {"upstream": "feature/done"}}, ""),
        )
        for name, local, expected in cases:
            with self.subTest(name=name):
                item = self.ready(True, False, "ancestor", local)
                done = self.branches()["feature/done"]
                self.assertEqual((done["cleanup"], done["kept"]), (None, expected) if expected else (item, ""))
                if expected:
                    self.assertEqual(done["plan"][1], expected)
                    self.assertEqual(self.sign([item]), (400, self.refusal(item).encode()))

    def test_a_repository_whose_replan_did_not_finish_offers_no_delete_and_says_why(self):
        item = self.ready(True, False, "ancestor", {})
        planned = self.tree_file.with_name("local-plan.json")
        data = json.loads(planned.read_text(encoding="utf-8"))
        data["repos"][0]["stale"] = "replan timed out at 2026-11-14T18:00:00+00:00"
        planned.write_text(json.dumps(data), encoding="utf-8")
        done = self.branches()["feature/done"]
        stale = "pkgmgr branch cleanup --local plan stale: replan timed out at 2026-11-14T18:00:00+00:00; use branch gc (kvb-git-gc, pkgmgr gc)"
        self.assertEqual((done["cleanup"], done["kept"], done["plan"][1]), (None, stale, stale))
        self.assertEqual(self.sign([item]), (400, self.refusal(item).encode()))

    def test_without_a_local_dry_run_of_the_tip_the_tree_offers_no_delete(self):
        pending = "no pkgmgr branch cleanup --local dry run of 5b1e6fd3a7c0 yet: the tree timer writes local-plan.json within a minute"
        for name, local in (("dry run of another tip", {"feature/done": {"local_sha": OTHER_TIP}}), ("no dry run file", None)):
            with self.subTest(name=name):
                item = self.ready(True, False, "ancestor", local or {})
                if local is None:
                    self.tree_file.with_name("local-plan.json").unlink()
                done = self.branches()["feature/done"]
                self.assertEqual((done["cleanup"], done["kept"], done["plan"][1]), (None, pending, pending))
                self.assertEqual(self.sign([item]), (400, self.refusal(item).encode()))

    def test_signing_a_delete_needs_delete_ready_and_exactly_an_offered_item(self):
        item = self.ready(False, False, "ancestor", {})
        status, body = self.sign([item])
        self.assertEqual((status, body.decode()), (400, "delete blocked: Secret Service locked\n"))
        item = self.ready(True, False, "ancestor", {})
        kept = {**item, "branch": "feature/kept", "worktree": "", "tip": "0c9d8e7f6a5b4c3d2e1f0a9b8c7d6e5f4a3b2c1d"}
        for name, items in (("changed tip", [{**item, "tip": OTHER_TIP}]), ("skip reason", [kept]), ("pattern", [{**item, "branch": "feature/*"}]), ("twice", [item, item]), ("extra key", [{**item, "command": "rm -rf /"}])):
            with self.subTest(name=name):
                self.assertEqual(self.sign(items)[0], 400)
        status, body = self.sign([item])
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)["payload"]["items"], [signing.item_hash(item)])

    def test_a_branch_held_by_a_worktree_offers_no_delete_and_names_branch_gc(self):
        item = self.ready(True, True, "pr#12", {})
        done = self.branches()["feature/done"]
        held = f"held by worktree {item['worktree']}: pkgmgr branch cleanup skips it, use branch gc (kvb-git-gc, pkgmgr gc)"
        self.assertEqual((done["cleanup"], done["held"], done["kept"], done["plan"][1]), (None, held, "", held))
        status, body = self.sign([item])
        self.assertEqual((status, body.decode()), (400, self.refusal(item)))
        page = (HUB / "templates" / "page-tree.js").read_text(encoding="utf-8")
        self.assertIn('if (entry.held) {\n      return h("span", {class: "hint held", title: entry.held}, chip("bi-folder-symlink", entry.held, "neutral"));', page)
        self.assertIn("deleteDialog(items, locked, held, kept)", page)
        self.assertIn("held by a worktree: not deleted here", (HUB / "templates" / "page-cleanup.js").read_text(encoding="utf-8"))

    def test_the_delete_sheet_renders_the_dry_run_note_as_visible_text(self):
        dialog = (HUB / "templates" / "page-cleanup.js").read_text(encoding="utf-8")
        sheet = dialog[dialog.index("openSheet("):]
        note = re.search(r'\[\n\s*h\("p", \{class: "muted"\}, "([^"]+)"\),\n', sheet)
        self.assertIsNotNone(note, sheet[:400])
        for part in ("it deletes the local branch", "never touches a worktree, Compose stack or volume", "A branch held by a worktree is not deleted here", "its docker compose down -v deletes the stack's volumes", "the host refuses an entry whose plan deletes one", "refuses every entry whose state has changed since",
                     "Neither is a branch the pkgmgr branch cleanup --local dry run keeps, such as one merged by pull request, squash or patch whose local tip is no ancestor of the default branch: branch gc removes it"):
            self.assertIn(part, note.group(1))
        self.assertEqual(dialog.count(note.group(1)), 1)

    @unittest.skipUnless(INSTALLED_PKGMGR, "no pkgmgr installed")
    def test_every_volume_text_states_the_compose_down_argv_of_the_installed_pkgmgr(self):
        found = subprocess.run([str(Path(INSTALLED_PKGMGR).parent / "python"), "-I", "-c", "import pkgmgr.actions.branch.gc as gc; print(gc.__file__)"], capture_output=True, text=True, timeout=60, check=True)
        calls = [node for node in ast.walk(ast.parse(Path(found.stdout.strip()).read_text(encoding="utf-8"))) if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "_docker" and node.args and isinstance(node.args[0], ast.List)]
        downs = [["docker", *(part.value if isinstance(part, ast.Constant) else "{project}" for part in call.args[0].elts)] for call in calls if any(isinstance(part, ast.Constant) and part.value == "down" for part in call.args[0].elts)]
        self.assertEqual(len(downs), 1, downs)
        command = " ".join(downs[0]).format(project="demo-feature-done")
        self.ready(True, True, "pr#12", {})
        plan = self.branches()["feature/done"]["plan"]
        self.assertIn(f"branch gc would run {command}, which deletes the volumes of demo-feature-done", plan)
        self.assertIn("-v", downs[0])
        dialog = (HUB / "templates" / "page-cleanup.js").read_text(encoding="utf-8")
        self.assertIn("never touches a worktree, Compose stack or volume", dialog)
        self.assertIn("its docker compose down -v deletes the stack's volumes", dialog)
        texts = [*plan, dialog, (HUB / "kvb_orchestrator" / "tree.py").read_text(encoding="utf-8")]
        self.assertFalse([text for text in texts if "without -v" in text])

    def test_a_signed_delete_becomes_a_job_without_any_command(self):
        item = self.ready(True, False, "ancestor", {})
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
        self.jobs.mkdir(mode=0o700)
        self.results.mkdir(mode=0o700)
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
        return {"branch": self.item["branch"], "worktree": self.item["worktree"], "local_sha": DONE_TIP, "head": DONE_TIP, "state": "merged-clean", "merged_by": "ancestor", "skip": None, "actions": ["local-branch"], **changes}

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
        selector = ["--local", "--json", "--branch", "feature/done"]
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
                self.assertEqual([call["argv"][:3] for call in calls], [["branch", "cleanup", "--local"], ["branch", "cleanup", "--apply"]])
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
            ("skip reason", [self.item], self.proof([self.item], self.signer), [self.entry(skip="ignored files")], "pkgmgr branch cleanup --local keeps it: ignored files", 1),
            ("other worktree", [self.item], self.proof([self.item], self.signer), [self.entry(worktree="/elsewhere")], "worktree changed", 1),
            ("pattern match in pkgmgr", [self.item], self.proof([self.item], self.signer), [self.entry(), self.entry(branch="feature/done-too")], "other branches too", 1),
            ("remote branch delete", [self.item], self.proof([self.item], self.signer), [self.entry(actions=["local-branch", "remote-branch:origin"])], "a signed delete is local only", 1),
        )
        for name, items, proof, plan, reason, dry_runs in cases:
            with self.subTest(name=name):
                result, calls = self.run_job(items, proof, plan)
                self.assertEqual([entry["status"] for entry in result["items"]], ["refused"])
                self.assertIn(reason, result["items"][0]["reason"])
                self.assertEqual([call["argv"] for call in calls], [["branch", "cleanup", "--local", "--json", "--branch", items[0]["branch"]]] * dry_runs)
                self.assertNotIn("tree", result)

    def test_a_signed_item_the_local_dry_run_keeps_is_refused_with_its_reason_and_never_applied(self):
        cases = (("tip no ancestor", {"merged_by": "patch", "skip": KEPT_PATCH, "actions": []}, KEPT_PATCH), ("nothing planned", {"actions": []}, "the dry run plans no delete, not exactly the local branch"))
        for name, changes, kept in cases:
            with self.subTest(name=name):
                result, calls = self.run_job([self.item], self.proof([self.item], self.signer), [self.entry(**changes)])
                self.assertEqual([(entry["status"], entry["reason"]) for entry in result["items"]], [("refused", f"pkgmgr branch cleanup --local keeps it: {kept}")])
                self.assertEqual([call["argv"] for call in calls], [["branch", "cleanup", "--local", "--json", "--branch", "feature/done"]])
                self.assertNotIn("tree", result)

    def test_a_signed_item_whose_local_tip_the_dry_run_deletes_is_deleted_whatever_merged_its_remote_tip(self):
        result, calls = self.run_job([self.item], self.proof([self.item], self.signer), [self.entry(merged_by="patch", remotes={"origin": OTHER_TIP})])
        self.assertEqual([(entry["status"], entry["reason"]) for entry in result["items"]], [("done", "")])
        self.assertEqual([call["argv"][:4] for call in calls][:2], [["branch", "cleanup", "--local", "--json"], ["branch", "cleanup", "--apply", "--local"]])

    def test_an_apply_that_deletes_the_branch_at_another_merged_tip_is_done_with_a_warning_and_rewrites_the_tree(self):
        (self.fake.parent / "apply.json").write_text(json.dumps([self.entry(local_sha=OTHER_TIP, head=OTHER_TIP)]), encoding="utf-8")
        result, calls = self.run_job([self.item], self.proof([self.item], self.signer), [self.entry()])
        self.assertEqual([(entry["status"], entry["reason"]) for entry in result["items"]], [("done", "deleted at another merged tip than the signed dry run: tip changed: signed 5b1e6fd3a7c0, now 111111111111")])
        self.assertEqual([call["argv"][:3] for call in calls], [["branch", "cleanup", "--local"], ["branch", "cleanup", "--apply"], ["branch", "tree", "--format"]])
        self.assertEqual((result["tree"], json.loads(self.tree.read_text(encoding="utf-8"))), ({"code": 0, "error": ""}, {"rewritten": True}))

    def test_an_apply_that_skips_the_branch_at_another_tip_is_failed_and_keeps_the_tree(self):
        before = self.tree.read_text(encoding="utf-8")
        (self.fake.parent / "apply.json").write_text(json.dumps([self.entry(local_sha=OTHER_TIP, head=OTHER_TIP)]), encoding="utf-8")
        (self.fake.parent / "outcome.txt").write_text("skipped: changed since plan (merged by patch, tip is no ancestor of refs/remotes/origin/main)", encoding="utf-8")
        result, _ = self.run_job([self.item], self.proof([self.item], self.signer), [self.entry()])
        self.assertEqual([(entry["status"], entry["reason"]) for entry in result["items"]], [("failed", "the apply planned another tip than the signed dry run: tip changed: signed 5b1e6fd3a7c0, now 111111111111")])
        self.assertNotIn("tree", result)
        self.assertEqual(self.tree.read_text(encoding="utf-8"), before)

    def test_an_item_the_apply_keeps_is_failed_with_pkgmgrs_skip_reason(self):
        kept = self.entry(skip="kept: local upstream of stack", actions=[])
        (self.fake.parent / "apply.json").write_text(json.dumps([kept]), encoding="utf-8")
        result, _ = self.run_job([self.item], self.proof([self.item], self.signer), [self.entry()])
        self.assertEqual([(entry["status"], entry["reason"]) for entry in result["items"]], [("failed", "pkgmgr branch cleanup --local keeps it: kept: local upstream of stack")])
        self.assertNotIn("tree", result)

    def git(self, repo: Path, *args: str) -> str:
        return subprocess.run(["git", *args], cwd=repo, env={**os.environ, **GIT_ENV}, check=True, capture_output=True, text=True).stdout.strip()

    def scratch(self, *branches: str) -> tuple[Path, str, list[dict], list[dict]]:
        """Args:
            branches: the branches the job signs and the dry run plans, each
                at the first commit.

        Returns:
            A scratch repository the tree file names, holding only main and
            feature/two of them, that commit, the signed items and the plan.
        """
        repo = self.repo.parent / "scratch"
        self.git(self.repo.parent, "init", "-q", "-b", "main", str(repo))
        self.git(repo, "commit", "-q", "--allow-empty", "-m", "one")
        tip = self.git(repo, "rev-parse", "HEAD")
        if "feature/two" in branches:
            self.git(repo, "branch", "feature/two")
        self.tree.write_text(json.dumps({"delete_ready": True, "repos": [{"path": str(repo), "known": True}]}), encoding="utf-8")
        (self.fake.parent / "next-tree.json").write_text(self.tree.read_text(encoding="utf-8"), encoding="utf-8")
        items = [{"repository": str(repo), "branch": name, "worktree": "", "tip": tip} for name in branches]
        return repo, tip, items, [self.entry(branch=name, worktree=None, local_sha=tip, head=tip) for name in branches]

    def test_after_an_interrupted_apply_a_gone_branch_is_gone_never_done_and_one_at_its_signed_tip_failed(self):
        repo, _, items, plan = self.scratch("feature/done")
        self.git(repo, "branch", "feature/done")
        (self.fake.parent / "killed").write_text("", encoding="utf-8")
        result, _ = self.run_job(items, self.proof(items, self.signer), plan)
        self.assertEqual([entry["status"] for entry in result["items"]], ["failed"])
        self.assertNotIn("tree", result)
        self.git(repo, "branch", "-D", "feature/done")
        result, _ = self.run_job(items, self.proof(items, self.signer), plan)
        self.assertEqual([(entry["status"], entry["reason"]) for entry in result["items"]], [("gone", "gone after an interrupted apply")])
        self.assertEqual(result["tree"], {"code": 0, "error": ""})

    def test_a_branch_gone_although_pkgmgr_answered_without_deleting_it_is_gone_outside_this_run_never_done(self):
        _, tip, items, plan = self.scratch("feature/done")
        failed = f"failed: Git command failed: git update-ref --no-deref -d refs/heads/feature/done {tip}"
        cases = (("update-ref failed", "outcome.txt", failed), ("unknown at the apply", "unknown.json", json.dumps({"apply": ["feature/done"]})))
        for name, knob, content in cases:
            with self.subTest(name=name):
                (self.fake.parent / knob).write_text(content, encoding="utf-8")
                result, calls = self.run_job(items, self.proof(items, self.signer), plan)
                (self.fake.parent / knob).unlink()
                self.assertEqual([(entry["status"], entry["reason"]) for entry in result["items"]], [("gone", "deleted outside this run")])
                self.assertEqual([call["argv"][:3] for call in calls], [["branch", "cleanup", "--local"], ["branch", "cleanup", "--apply"], ["branch", "tree", "--format"]])
                self.assertEqual(result["tree"], {"code": 0, "error": ""})

    def test_a_branch_that_vanished_is_gone_and_its_repository_runs_once_more_without_it(self):
        _, _, items, plan = self.scratch("feature/done", "feature/two")
        unknown = self.fake.parent / "unknown.json"
        both = ["--local", "--json", "--branch", "feature/done", "--branch", "feature/two"]
        two = ["--local", "--json", "--branch", "feature/two"]
        rewrite = ["branch", "tree", "--format", "json", "--output", str(self.tree)]
        cases = (
            ("before the apply", {"apply": ["feature/done"]}, [("gone", "deleted outside this run"), ("done", "")], [["branch", "cleanup", *both], ["branch", "cleanup", "--apply", *both], ["branch", "cleanup", "--apply", *two], rewrite]),
            ("before the dry run", {"plan": ["feature/done"]}, [("gone", "deleted outside this run"), ("done", "")], [["branch", "cleanup", *both], ["branch", "cleanup", *two], ["branch", "cleanup", "--apply", *two], rewrite]),
            ("once only, never a present branch", {"apply": ["feature/done", "feature/two"]}, [("gone", "deleted outside this run"), ("failed", "Unknown --branch: feature/two")], [["branch", "cleanup", *both], ["branch", "cleanup", "--apply", *both], ["branch", "cleanup", "--apply", *two], rewrite]),
        )
        for name, vanished, outcomes, argvs in cases:
            with self.subTest(name=name):
                unknown.write_text(json.dumps(vanished), encoding="utf-8")
                result, calls = self.run_job(items, self.proof(items, self.signer), plan)
                self.assertEqual([(entry["status"], entry["reason"]) for entry in result["items"]], outcomes)
                self.assertEqual([call["argv"] for call in calls], argvs)

    def test_a_job_plans_and_applies_each_repository_once_for_all_its_items(self):
        two = {**self.item, "branch": "feature/two", "worktree": ""}
        items = [self.item, two]
        (self.fake.parent / "next-tree.json").write_text(self.tree.read_text(encoding="utf-8"), encoding="utf-8")
        result, calls = self.run_job(items, self.proof(items, self.signer), [self.entry(), self.entry(branch="feature/two", worktree=None)])
        self.assertEqual([(entry["branch"], entry["status"], entry["reason"]) for entry in result["items"]], [("feature/done", "done", ""), ("feature/two", "done", "")])
        both = ["--local", "--json", "--branch", "feature/done", "--branch", "feature/two"]
        self.assertEqual([call["argv"] for call in calls][:2], [["branch", "cleanup", *both], ["branch", "cleanup", "--apply", *both]])
        result, calls = self.run_job(items, self.proof(items, self.signer), [self.entry(local_sha=OTHER_TIP), self.entry(branch="feature/two", worktree=None)])
        self.assertEqual([(entry["branch"], entry["status"]) for entry in result["items"]], [("feature/done", "refused"), ("feature/two", "done")], result["items"])
        self.assertIn("tip changed", result["items"][0]["reason"])
        self.assertEqual([call["argv"] for call in calls][:2], [["branch", "cleanup", *both], ["branch", "cleanup", "--apply", "--local", "--json", "--branch", "feature/two"]])

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
            code, stdout, stderr = host.run(Path(INSTALLED_PKGMGR), host.plan_argv(["side"], False), str(repo), host.TIMEOUT)
            self.assertEqual(code, 0, stderr)
            plan = host.plan_items(stdout)
            self.assertIsNotNone(plan, stdout[:500])
            self.assertEqual([(entry["branch"], entry["state"], entry["merged_by"], entry["merged_into"], entry["skip"], entry["actions"]) for entry in plan], [("side", "merged-clean", "ancestor", "refs/remotes/origin/main", None, ["local-branch"])])
            self.assertIsNone(host.mismatch(plan[0], {"tip": tip, "worktree": ""}))
            self.assertTrue(signing.token_free(plan[0], "main"))
            shown = tree.branch(plan[0], str(repo), "main", plan[0], "", "")
            self.assertEqual((shown["cleanup"], shown["kept"]), (signing.cleanup_item(str(repo), "side", "", tip), ""))
            self.assertEqual(self.git(repo, "rev-parse", "refs/heads/side"), tip)
            held = base / "held"
            self.git(repo, "worktree", "add", "-q", str(held), "side")
            code, stdout, stderr = host.run(Path(INSTALLED_PKGMGR), host.plan_argv(["side"], False), str(repo), host.TIMEOUT)
            self.assertEqual(code, 0, stderr)
            plan = host.plan_items(stdout)
            self.assertEqual([(entry["worktree"], entry["actions"], bool(entry["skip"])) for entry in plan], [(os.path.realpath(held), [], True)], plan)
            self.assertIn("pkgmgr branch cleanup --local keeps it", host.mismatch(plan[0], {"tip": tip, "worktree": os.path.realpath(held)}))

    def test_the_hub_keeps_the_local_upstream_of_a_merged_branch_exactly_as_the_hosts_dry_run_of_it_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            origin, repo = base / "origin.git", base / "repo"
            self.git(base, "init", "-q", "--bare", "-b", "main", str(origin))
            self.git(base, "init", "-q", "-b", "main", str(repo))
            self.git(repo, "remote", "add", "origin", origin.as_uri())
            self.git(repo, "commit", "-q", "--allow-empty", "-m", "one")
            self.git(repo, "checkout", "-q", "-b", "base")
            self.git(repo, "commit", "-q", "--allow-empty", "-m", "base")
            tip = self.git(repo, "rev-parse", "HEAD")
            self.git(repo, "checkout", "-q", "main")
            self.git(repo, "merge", "-q", "--no-ff", "-m", "merge base", "base")
            self.git(repo, "branch", "stack", "base")
            self.git(repo, "branch", "-q", "--set-upstream-to=base", "stack")
            self.git(origin, "fetch", "-q", str(repo), "main:main")
            self.git(repo, "fetch", "-q", "origin")
            self.git(repo, "remote", "set-head", "origin", "main")
            code, stdout, stderr = host.run(Path(INSTALLED_PKGMGR), ["branch", "cleanup", "--local", "--json"], str(repo), host.TIMEOUT)
            self.assertEqual(code, 0, stderr)
            planned = base / "local-plan.json"
            planned.write_text(stdout, encoding="utf-8")
            hub = {branch: tree.kept_by(item, tip, child, "") for (_, branch), (item, child) in tree.local_plan(planned)[0].items() if branch in ("base", "stack")}
            refusals = {}
            for name in ("base", "stack"):
                code, stdout, stderr = host.run(Path(INSTALLED_PKGMGR), host.plan_argv([name], False), str(repo), host.TIMEOUT)
                self.assertEqual(code, 0, stderr)
                refusals[name] = host.mismatch(host.plan_items(stdout)[0], {"tip": tip, "worktree": ""})
            self.assertEqual(refusals, {"base": "pkgmgr branch cleanup --local keeps it: kept: local upstream of stack", "stack": None})
            self.assertEqual(hub, {"base": f"{refusals['base']}; use branch gc (kvb-git-gc, pkgmgr gc)", "stack": ""})

    def test_the_installed_pkgmgr_plans_the_recorded_fixture_exactly(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, plan = capture_local_plan(Path(tmp), Path(INSTALLED_PKGMGR))
            self.assertEqual(plan["repos"], recorded_plan(str(repo))["repos"])


class TestRecordedLocalPlan(HubCase):
    def setUp(self):
        super().setUp()
        self.repo = "/home/operator-example-01/repos/demo"
        self.items = {entry["branch"]: entry for entry in recorded_plan(self.repo)["repos"][0]["items"]}

    def test_the_runner_and_the_tree_agree_on_every_recorded_branch(self):
        expected = {"side": "", "topic": "", "squashed": f"pkgmgr branch cleanup --local keeps it: {KEPT_PATCH}"}
        self.assertEqual({name: self.items[name]["merged_by"] for name in expected}, {"side": "ancestor", "topic": "patch", "squashed": "patch"})
        for name, refused in expected.items():
            with self.subTest(branch=name):
                entry = self.items[name]
                self.assertEqual(host.mismatch(entry, {"tip": entry["local_sha"], "worktree": ""}), refused or None)
                shown = tree.branch(entry, self.repo, "main", entry, "", "")
                offered = signing.cleanup_item(self.repo, name, "", entry["local_sha"])
                self.assertEqual((shown["cleanup"], shown["kept"]), (None, f"{refused}; use branch gc (kvb-git-gc, pkgmgr gc)") if refused else (offered, ""))

    def test_the_tree_offers_the_branch_whose_local_tip_is_an_ancestor_although_its_remote_tip_was_cherry_picked(self):
        plan = recorded_plan(self.repo)
        tree_data = {"generated_at": "2026-11-14T12:00:00+00:00", "delete_ready": True, "delete_reason": "", "repos": [{"path": self.repo, "remote": None, "default": "main", "missing": False, "known": True, "forge": "live", "scanned_at": "2026-11-14T12:00:00+00:00", "warnings": [], "items": [{**entry, "flow": None} for entry in plan["repos"][0]["items"]]}]}
        self.tree_file.write_text(json.dumps(tree_data), encoding="utf-8")
        self.tree_file.with_name("local-plan.json").write_text(json.dumps(plan), encoding="utf-8")
        status, _, body = self.get("/api/tree")
        self.assertEqual(status, 200, body)
        branches = {entry["name"]: entry for entry in json.loads(body)["repos"][0]["branches"]}
        self.assertEqual({name: (entry["cleanup"] is not None, entry["kept"]) for name, entry in branches.items()}, {
            "main": (False, ""), "side": (True, ""), "topic": (True, ""), "squashed": (False, f"pkgmgr branch cleanup --local keeps it: {KEPT_PATCH}; use branch gc (kvb-git-gc, pkgmgr gc)"),
        })
        topic = self.items["topic"]
        self.assertEqual(self.post_json("/api/sign", {"items": [signing.cleanup_item(self.repo, "topic", "", topic["local_sha"])]}, self.guard(self.host))[0], 200)


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
            code, _, error = host.run(fake, ["branch", "cleanup", "--apply"], str(repo), host.TIMEOUT)
            self.assertEqual(code, 0, error)
            self.assertFalse(marker.exists())
            branches = subprocess.run(["git", "branch", "--format=%(refname:short)"], cwd=repo, capture_output=True, text=True, check=True).stdout.split()
            self.assertNotIn("doomed", branches)


RESULT_VIEW = """
const fs = require("fs");
const vm = require("vm");
const context = {h: (tag, attrs, ...kids) => ({tag, attrs: attrs || {}, kids}), named: (label) => ({"aria-label": label}), icon: (name) => name, pill: (label, tone) => ({pill: label, tone})};
vm.runInNewContext(`${fs.readFileSync(process.argv[1], "utf8")}\\n${fs.readFileSync(process.argv[2], "utf8")}\\nglobalThis.probe = {resultChip, showJob, RESULT_LABELS};`, context);
const statuses = ["done", "gone", "failed", "refused"];
const chips = statuses.map((status) => {
  const chip = context.probe.resultChip({status, reason: "why"});
  return [status, chip.attrs["data-tone"], chip.attrs["aria-label"], chip.kids[0]];
});
const outcome = {replaceChildren: (list) => { outcome.list = list; }};
const shown = context.probe.showJob({items: statuses.map((status) => ({branch: status, status, reason: ""}))}, outcome, "branch", context.probe.RESULT_LABELS);
console.log(JSON.stringify({chips, pills: outcome.list.kids[0].map((row) => [row.attrs["data-result"], row.kids[0].kids[1]]), good: shown.good}));
"""


@unittest.skipUnless(shutil.which("node"), "no node")
class TestCleanupResultView(unittest.TestCase):
    def test_the_tree_and_the_delete_sheet_show_a_gone_branch_apart_from_deleted_and_failed(self):
        pages = [str(HUB / "templates" / name) for name in ("page-tree.js", "page-cleanup.js")]
        done = subprocess.run(["node", "-e", RESULT_VIEW, *pages], capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        shown = json.loads(done.stdout)
        self.assertEqual(shown["chips"], [
            ["done", "ok", "deleted: why", "bi-check2-all"],
            ["gone", "warn", "gone: why", "bi-question-octagon"],
            ["failed", "bad", "failed: why", "bi-exclamation-triangle"],
            ["refused", "bad", "refused: why", "bi-x-octagon"],
        ])
        self.assertEqual(shown["pills"], [["done", {"pill": "deleted", "tone": "ok"}], ["gone", {"pill": "gone", "tone": "warn"}], ["failed", {"pill": "failed", "tone": "bad"}], ["refused", {"pill": "refused", "tone": "bad"}]])
        self.assertFalse(shown["good"])


if __name__ == "__main__":
    unittest.main()
