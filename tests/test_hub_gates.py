from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

from hub_case import HubCase
from hub_support import GIT_ENV, REPO_ROOT, RUNNER, runner, signing

GATES = REPO_ROOT / "skills" / "kvb-check-gate" / "scripts" / "gates.py"
GATES_SPEC = importlib.util.spec_from_file_location("kvb_gates_for_hub", GATES)
gates = importlib.util.module_from_spec(GATES_SPEC)
GATES_SPEC.loader.exec_module(gates)
REPO = "/home/op/Repositories/demo"


def rule(action: str, level: str | None, branch: str = "feature/x", repo: str = REPO) -> list[str]:
    head = ["--repo", repo, "--branch", branch, "--action", action]
    return ["rule", "drop", *head] if level is None else ["rule", "set", *head, "--level", level]


def parent(name: str, drop: bool = False, branch: str = "feature/x", repo: str = REPO) -> list[str]:
    return ["parents", "drop" if drop else "add", "--repo", repo, "--branch", branch, "--parent", name]


class TestGateArgv(unittest.TestCase):
    def test_exactly_rule_set_drop_and_parents_add_drop_of_one_branch_pass(self):
        for argv in (rule("commit", "test"), rule("pr", "e2e"), rule("merge", None), parent("main"), parent("feature/base", drop=True), rule("push", "none", branch="fix/a-b_c.1")):
            with self.subTest(argv=argv):
                self.assertEqual(signing.gate_argv(argv), argv)
                self.assertEqual(signing.gate_item(argv), {"kind": "gate", "argv": argv})

    def test_every_other_argv_is_refused(self):
        cases = {
            "not a list": "rule set",
            "no texts": ["rule", "set", 1],
            "resolve": ["resolve", "--repo", REPO, "--branch", "b", "--action", "commit"],
            "derive": ["parents", "derive", "--repo", REPO],
            "receipt": ["receipt", "add", "--repo", REPO, "--tree", "a" * 40, "--level", "e2e", "--log", "/x"],
            "show": ["show", "--json"],
            "db flag": ["--db", "/tmp/x.db", *rule("commit", "test")],
            "source flag": [*parent("main"), "--source", "recorded"],
            "reordered": ["rule", "set", "--branch", "feature/x", "--repo", REPO, "--action", "commit", "--level", "test"],
            "missing level": rule("commit", "test")[:-1],
            "level on drop": [*rule("commit", None), "--level", "test"],
            "unknown level": rule("commit", "strict"),
            "unknown action": rule("deploy", "test"),
            "relative repo": rule("commit", "test", repo="repo"),
            "dotdot repo": rule("commit", "test", repo="/home/op/../root"),
            "control repo": rule("commit", "test", repo="/home/op/\nrepo"),
            "option branch": rule("commit", "test", branch="--level"),
            "pattern branch": rule("commit", "test", branch="feature/*"),
            "spaced branch": rule("commit", "test", branch="a b"),
            "dotdot branch": rule("commit", "test", branch="a..b"),
            "trailing slash": rule("commit", "test", branch="feature/"),
            "own parent": parent("feature/x"),
            "empty parent": parent(""),
        }
        for name, argv in cases.items():
            with self.subTest(name=name):
                self.assertRaises(signing.Refused, signing.gate_argv, argv)


class TestHubGates(HubCase):
    def stage(self, argvs: list[list[str]]) -> list[dict]:
        return [{"kind": "gate", "argv": argv} for argv in argvs]

    def test_a_signed_gate_batch_becomes_one_runner_job_per_change(self):
        items = self.stage([rule("commit", "test"), parent("main")])
        payload = self.prepare(items)["payload"]
        self.assertEqual(sorted(payload["items"]), sorted(signing.item_hash(signing.gate_item(item["argv"])) for item in items))
        signer = self.pin()
        proof = signer.proof(payload, self.origin)
        self.assertEqual(self.post_json("/api/gates", {"items": items, "proof": None}, self.guard(self.host))[0], 400)
        self.assertEqual(self.post_json("/api/gates", {"items": items, "proof": proof}, {"Host": self.host})[0], 403)
        status, _, body = self.post_json("/api/gates", {"items": items, "proof": proof}, self.guard(self.host))
        self.assertEqual(status, 202, body)
        self.assertEqual(len(json.loads(body)["jobs"]), 2)
        jobs = self.runner_jobs()
        self.assertEqual(sorted((job["kind"], job["argv"], job["command"].split()[0]) for job in jobs), sorted(("gate", item["argv"], "gates.py") for item in items))
        self.assertEqual(self.get("/api/gates")[0], 405)

    def test_the_hub_refuses_a_malformed_or_forged_gate_change_before_it_queues(self):
        for name, items in (("receipt", self.stage([["receipt", "add", "--repo", REPO, "--tree", "a" * 40, "--level", "e2e", "--log", "/x"]])), ("own parent", self.stage([parent("feature/x")])), ("twice", self.stage([parent("main"), parent("main")])), ("extra key", [{"kind": "gate", "argv": parent("main"), "id": "x"}])):
            with self.subTest(name=name):
                status, _, body = self.post_json("/api/sign", {"items": items}, self.guard(self.host))
                self.assertEqual(status, 400, body)
        signer = self.pin()
        proof = signer.proof(self.prepare(self.stage([rule("commit", "test")]))["payload"], self.origin)
        status, _, body = self.post_json("/api/gates", {"items": self.stage([rule("commit", "e2e")]), "proof": proof}, self.guard(self.host))
        self.assertEqual(status, 400, body)
        self.assertEqual(self.runner_jobs(), [])


class TestRunnerGates(HubCase):
    def setUp(self):
        super().setUp()
        self.home = self.outside / "home"
        self.home.mkdir()
        self.repo = self.outside / "repo"
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.repo)], env={**os.environ, **GIT_ENV}, check=True)
        self.db = self.home / ".local" / "state" / "agents-council" / "gates.db"

    def run_gates_runner(self, flags: list[str]) -> None:
        trust = ["--approvers", str(self.approvers), "--replay", str(self.replay / "runner.json")]
        command = [sys.executable, str(RUNNER), "--port", str(self.port), "--interval", "0.1", *trust, *flags, "--once"]
        done = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False, env={**os.environ, "HOME": str(self.home)})
        self.assertEqual(done.returncode, 0, done.stderr)

    def queue(self, argvs: list[list[str]]) -> list[str]:
        items = [{"kind": "gate", "argv": argv} for argv in argvs]
        proof = self.signed(items, self.pin())
        status, _, body = self.post_json("/api/gates", {"items": items, "proof": proof}, self.guard(self.host))
        self.assertEqual(status, 202, body)
        return json.loads(body)["jobs"]

    def finished(self) -> list[tuple[str, int | None]]:
        jobs = sorted(self.httpd.hub.jobs.listed(), key=lambda job: job["created_ts"])
        return [(job["status"], job["code"]) for job in jobs]

    def test_the_runner_writes_a_signed_rule_and_parent_into_the_default_gates_db_of_the_operator(self):
        repo = str(self.repo.resolve())
        self.queue([rule("commit", "quality-high", branch="main", repo=repo), parent("main", branch="feature/x", repo=repo)])
        self.run_gates_runner(["--gates", str(GATES)])
        self.assertEqual(self.finished(), [("done", 0), ("done", 0)])
        with closing(gates.opened(self.db, False, self.db.parent)) as db:
            self.assertEqual(gates.resolve(db, repo, "feature/x", "commit"), ("quality-high", "main"))
            self.assertEqual(gates.parents_of(db, repo, "feature/x"), [("main", "operator")])
        self.assertEqual([call for call in self.scripts.calls if call[0].endswith("operator.py")], [])

    def test_without_gates_the_runner_refuses_and_writes_nothing(self):
        self.queue([rule("commit", "test", repo=str(self.repo))])
        self.run_gates_runner([])
        jobs = self.httpd.hub.jobs.listed()
        self.assertEqual([(job["status"], job["output"]) for job in jobs], [("refused", runner.UNGATED)])
        self.assertFalse(self.db.exists())

    def test_the_runner_refuses_an_argv_that_differs_from_the_signed_one(self):
        self.queue([rule("commit", "test", repo=str(self.repo))])
        job = self.httpd.hub.jobs.listed()[0]
        self.httpd.hub.jobs.change(job["id"], {"argv": rule("commit", "none", repo=str(self.repo))})
        self.run_gates_runner(["--gates", str(GATES)])
        refused = self.httpd.hub.jobs.listed()[0]
        self.assertEqual(refused["status"], "refused")
        self.assertIn("does not list this item", refused["output"])
        self.assertFalse(self.db.exists())

    def test_gate_refusal_checks_the_argv_shape_before_any_signature(self):
        reason = runner.gate_refusal({"argv": ["receipt", "add"], "proof": None}, mock.Mock(), time.time())
        self.assertIn("gates.py rule set|drop or parents add|drop", reason)
        with self.assertRaises(signing.Refused):
            runner.gate({"argv": ["show", "--json"]}, GATES, print)


class TestHubGateView(HubCase):
    def write_db(self, repo: str) -> Path:
        db_path = self.kept / "gates.db"
        db = gates.opened(db_path, True, self.kept)
        db.executemany("INSERT INTO rules VALUES (?, ?, ?, ?, ?)", [(repo, "main", "commit", "test", 0.0), (repo, "main", "merge", "quality-high", 0.0), (repo, "feature", "pr", "e2e", 0.0), (repo, "feature/kept", "merge", "quick", 0.0)])
        db.executemany("INSERT INTO parents VALUES (?, ?, ?, ?)", [(repo, "feature", "main", "recorded"), (repo, "feature/done", "feature", "derived"), (repo, "feature/done", "feature/kept", "operator"), (repo, "feature/kept", "main", "derived")])
        db.commit()
        db.close()
        return db_path

    def test_the_tree_carries_gates_py_show_json_for_every_branch_from_the_read_only_database(self):
        root = self.write_tree()
        repo = f"{root}/repos/github.com/me/demo"
        db_path = self.write_db(repo)
        before = db_path.read_bytes()
        db_path.chmod(0o444)
        self.kept.chmod(0o555)
        self.addCleanup(self.kept.chmod, 0o755)
        status, _, body = self.get("/api/tree")
        self.assertEqual(status, 200, body)
        shown = json.loads(body)["gates"]
        self.assertEqual(sorted(shown[repo]), ["feature", "feature/done", "feature/kept", "main"])
        with closing(gates.opened(db_path, False, self.kept)) as db, mock.patch.object(gates, "branches", return_value={name: "0" * 40 for name in shown[repo]}):
            self.assertEqual(shown[repo], gates.show(db, [repo])[repo])
        done = shown[repo]["feature/done"]
        self.assertEqual(done["parents"], [{"parent": "feature", "source": "derived"}, {"parent": "feature/kept", "source": "operator"}])
        self.assertEqual(done["resolved"], {"commit": {"level": "test", "source": "main"}, "merge": {"level": "quality-high", "source": "main"}, "push": {"level": "none", "source": None}, "pr": {"level": "e2e", "source": "feature"}})
        self.assertEqual(db_path.read_bytes(), before)
        self.assertEqual(sorted(path.name for path in self.kept.iterdir()), ["gates.db"])

    def test_a_parent_in_the_kept_journal_of_the_mount_shows_as_recorded(self):
        root = self.write_tree()
        repo = f"{root}/repos/github.com/me/demo"
        self.write_db(repo)
        row = {"id": "1-1", "repo": repo, "branch": "main", "parent": "feature/kept"}
        (self.kept / "gate-parents.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
        status, _, body = self.get("/api/tree")
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)["gates"][repo]["main"]["parents"], [{"parent": "feature/kept", "source": "recorded"}])

    def test_without_a_database_or_with_a_broken_one_the_tree_carries_no_gates(self):
        self.write_tree()
        self.assertEqual(json.loads(self.get("/api/tree")[2])["gates"], {})
        (self.kept / "gates.db").write_bytes(b"not sqlite")
        self.assertEqual(json.loads(self.get("/api/tree")[2])["gates"], {})

    def test_a_stored_level_outside_levels_or_an_older_gates_py_without_parents_of_keeps_the_tree_up_without_gates(self):
        root = self.write_tree()
        repo = f"{root}/repos/github.com/me/demo"
        db = gates.opened(self.write_db(repo), True, self.kept)
        db.execute("UPDATE rules SET level = 'bogus' WHERE branch = 'main' AND action = 'commit'")
        db.commit()
        status, _, body = self.get("/api/tree")
        self.assertEqual((status, json.loads(body)["gates"] if status == 200 else body), (200, {}))
        db.execute("UPDATE rules SET level = 'test' WHERE branch = 'main' AND action = 'commit'")
        db.commit()
        db.close()
        self.assertEqual(json.loads(self.get("/api/tree")[2])["gates"][repo]["main"]["rules"]["commit"], "test")
        older = self.kept.parent / "older-skills"
        script = older / "kvb-check-gate" / "scripts" / "gates.py"
        script.parent.mkdir(parents=True)
        script.write_text('ACTIONS = ("commit",)\n\n\ndef resolve(db, repo, branch, action):\n    return ("none", None)\n', encoding="utf-8")
        self.scripts.skills = older
        status, _, body = self.get("/api/tree")
        self.assertEqual((status, json.loads(body)["gates"] if status == 200 else body), (200, {}))


if __name__ == "__main__":
    unittest.main()
