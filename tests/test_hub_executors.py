from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
import unittest
from unittest import mock

import hub_support
from hub_case import HubCase
from hub_support import (
    APPROVAL,
    ASK,
    GIT_ENV,
    PAGE,
    PRESENT,
    TREE,
    runner,
    signing,
    verifier,
)
from kvb_orchestrator import batches, rules, skill_scripts

# An import named key trips F402: test_rules_are_signed_once_and_checked_by_the_executor rebinds it in a comprehension.
key = hub_support.key


class TestHubExecutors(HubCase):
    def trust(self, name: str) -> verifier.Trust:
        return verifier.Trust(approvers=self.approvers, replay=self.replay / f"{name}.json", origin=self.origin)

    def test_an_operator_row_with_an_invisible_format_character_is_never_offered_for_a_signature(self):
        rows = {
            "operator/bidi": (f"echo safe{chr(0x202E)} && rm -rf ~", str(self.outside)),
            "operator/zero": (f"make{chr(0x200B)} test", str(self.outside)),
            "operator/dir": ("make test", f"{self.outside}{chr(0x2066)}"),
            "operator/plain": ("make test", str(self.outside)),
        }
        self.write_council({"rasci.json": {task: {"title": command, "workdir": workdir, "description": "run it", "check": "manual", "status": "queued", "roles": {}} for task, (command, workdir) in rows.items()}})
        self.pin()
        for task, code in (("operator/bidi", "U+202E"), ("operator/zero", "U+200B"), ("operator/dir", "U+2066")):
            with self.subTest(task=task):
                entry = self.entry("operator", task, "", hashlib.sha256(rows[task][0].encode()).hexdigest())
                status, _, body = self.post_json("/api/sign", {"items": [entry]}, self.guard(self.host))
                self.assertEqual(status, 400)
                self.assertIn(code, body.decode("utf-8"))
        plain = self.entry("operator", "operator/plain", "", hashlib.sha256(b"make test").hexdigest())
        self.assertEqual(len(self.prepare([plain])["payload"]["items"]), 1)

    def test_the_runner_runs_only_signed_commands_once(self):
        command = "echo hello && echo world >&2"
        register = {
            "operator/greet": {"title": command, "workdir": str(self.outside), "description": "say hi", "check": "manual", "status": "queued", "roles": {}},
            "operator/decide": {"title": "pick a name", "workdir": str(self.outside), "check": "decision", "status": "queued", "roles": {}},
        }
        self.write_council({"rasci.json": register})
        items = {item["id"]: item for item in self.snapshot()["inbox"]}
        greet = items["operator/greet"]
        digest = hashlib.sha256(command.encode()).hexdigest()
        self.assertEqual((greet["runnable"], greet["sha256"], items["operator/decide"]["runnable"]), (True, digest, False))
        self.assertEqual(self.approve([self.entry("operator", "operator/greet", "", "0" * 64)], None)[0], 409)
        self.assertEqual(self.approve([self.entry("operator", "operator/decide", "", "")], None)[0], 400)
        self.assertEqual(self.approve([self.entry("operator", "operator/greet", "", digest)], None)[0], 400)
        self.assertEqual(self.call("GET", "/api/runner/jobs", None, {"Host": self.host})[0], 403)
        self.assertEqual(self.call("GET", "/api/runner/jobs", None, self.guard(self.host))[0], 403)
        signer = self.pin()
        greeting = [self.entry("operator", "operator/greet", "", digest)]
        with mock.patch.object(batches, "UNDO", 0.05):
            self.assertEqual(self.approve(greeting, self.signed(greeting, signer))[0], 202)
            self.settle(lambda: self.runner_jobs() != [])
        queued = self.runner_jobs()
        self.assertEqual([(job["task"], job["command"], job["directory"], job["sha256"]) for job in queued], [("operator/greet", command, str(self.outside), digest)])
        proof = queued[0]["proof"]
        self.assertIn(signing.item_hash(signing.operator_item("operator/greet", command, str(self.outside))), proof["payload"]["items"])
        row = next(item for item in self.snapshot()["inbox"] if item["id"] == "operator/greet")
        self.assertEqual((row["runnable"], row["job"]["status"]), (False, "queued"))
        self.run_runner()
        job = self.snapshot()["jobs"][-1]
        self.assertEqual((job["status"], job["code"], job["output"]), ("done", 0, "hello\nworld\n"))
        self.assertNotIn("proof", job)
        self.assertEqual(self.scripts.calls[-1], (skill_scripts.OPERATOR_SCRIPT, ["ran", "greet", f"--command={command}", f"--dir={self.outside}"]))
        claim = {**self.client(), "Content-Type": "application/json"}
        self.assertEqual(self.call("POST", f"/api/runner/{job['id']}/claim", b"{}", claim)[0], 409)
        self.assertEqual(self.call("POST", f"/api/runner/{job['id']}/claim", b"{}", {**self.guard(self.host), "Content-Type": "application/json"})[0], 403)
        stranger = key(-8, "stranger").proof(proof["payload"], self.origin)
        forged = (
            ("echo evil", str(self.outside), proof, "does not list this item"),
            (command, "/", proof, "does not list this item"),
            (command, str(self.outside), proof, "already used"),
            (command, str(self.outside), None, "no signature"),
            (command, str(self.outside), stranger, "not pinned"),
        )
        for text, directory, relayed, reason in forged:
            with self.subTest(command=text, directory=directory, reason=reason):
                fields = {"task": "operator/greet", "command": text, "directory": directory, "sha256": digest, "status": "queued", "proof": relayed}
                tampered = self.httpd.hub.jobs.add({**fields, "code": None, "output": "", "created_ts": time.time(), "started": None, "finished": None})
                self.run_runner()
                record = self.httpd.hub.jobs.get(tampered["id"])
                self.assertEqual(record["status"], "refused")
                self.assertTrue(record["output"].startswith(runner.REFUSED), record["output"])
                self.assertIn(reason, record["output"])
        self.assertEqual(len([call for call in self.scripts.calls if call[0] == skill_scripts.OPERATOR_SCRIPT]), 1)
        self.approvers.unlink()
        job = {"task": "operator/greet", "command": command, "directory": str(self.outside), "proof": proof}
        self.assertIn("no key is pinned", runner.refusal(job, self.trust("other"), time.time()))
        reports = []
        self.assertEqual(runner.execute({"command": "exit 3", "directory": str(self.outside)}, reports.append), 3)
        self.assertEqual(reports[-1], {"output": "", "code": 3, "refused": False})

    def test_the_runner_closes_the_output_pipe_on_every_path(self):
        popen, spawned = subprocess.Popen, []
        job = {"command": "echo hi; sleep 0.3", "directory": str(self.outside)}

        def spawn(*args: object, **kwargs: object) -> subprocess.Popen:
            spawned.append(popen(*args, **kwargs))
            return spawned[-1]

        with mock.patch.object(subprocess, "Popen", spawn), mock.patch.object(runner, "BEAT", 0.05):
            self.assertEqual(runner.execute(job, [].append), 0)
            self.assertTrue(spawned[0].stdout.closed)
            self.assertRaises(RuntimeError, runner.execute, job, mock.Mock(side_effect=RuntimeError("the hub is gone")))
        self.settle(lambda: spawned[1].stdout.closed)
        self.assertEqual(spawned[1].wait(10), 0)

    def test_rules_are_signed_once_and_checked_by_the_executor(self):
        now = time.time()
        rule = {"kind": "ask", "tool": "Bash", "pattern": "make *", "scope": "/repo*", "expires": now + 3600}
        for payload in (
            {**rule, "expires": now - 1},
            {**rule, "expires": now + 400 * 86400},
            {**rule, "tool": ""},
            {**rule, "kind": "review"},
            {**rule, "pattern": " "},
            {**rule, "scope": "two\nlines"},
            {key: value for key, value in rule.items() if key != "scope"},
        ):
            with self.subTest(payload=payload):
                self.assertEqual(self.post_json("/api/rules/sign", payload, self.guard(self.host))[0], 400)
        self.assertEqual(self.post_json("/api/rules/sign", rule, self.client())[0], 403)
        signer = self.pin()

        def prepared(fields: dict) -> dict:
            status, _, body = self.post_json("/api/rules/sign", fields, self.guard(self.host))
            self.assertEqual(status, 200, body)
            return json.loads(body)

        def created(payload: dict, assertion: dict | None) -> tuple[int, dict, bytes]:
            return self.post_json("/api/rules", {"rule": payload, "assertion": assertion, "enabled": True}, self.guard(self.host))

        ask_rule = prepared(rule)
        self.assertEqual((ask_rule["sign"], ask_rule["challenge"], ask_rule["credentials"]), (True, signing.challenge(ask_rule["payload"]), [signer.id]))
        signed = signer.assertion(ask_rule["payload"], self.origin, "localhost", PRESENT, 0)
        for payload, assertion in (
            (ask_rule["payload"], None),
            (ask_rule["payload"], {}),
            (ask_rule["payload"], key(-8, "stranger").assertion(ask_rule["payload"], self.origin, "localhost", PRESENT, 0)),
            ({**ask_rule["payload"], "kinds": ["ask", "review"]}, signed),
            ({**ask_rule["payload"], "expires": now + 400 * 86400}, signed),
            ({**ask_rule["payload"], "id": "x"}, signed),
        ):
            with self.subTest(payload=payload):
                self.assertEqual(created(payload, assertion)[0], 400)
        self.assertEqual(self.post_json("/api/rules", {"rule": ask_rule["payload"], "assertion": signed, "enabled": True}, self.client())[0], 403)
        asks = json.loads(created(ask_rule["payload"], signed)[2])
        self.assertEqual(created(ask_rule["payload"], signed)[0], 409)
        review_rule = prepared({"kind": "review", "tool": "", "pattern": "feature/*", "scope": "/repo/*", "expires": now + 3600})
        self.assertEqual(created(review_rule["payload"], signer.assertion(review_rule["payload"], self.origin, "localhost", PRESENT, 0))[0], 201)
        decision_rule = prepared({"kind": "decision", "tool": "", "pattern": "*", "scope": "*", "expires": now + 3600})
        self.assertTrue(decision_rule["sign"])
        self.assertEqual(created(decision_rule["payload"], signed)[0], 400)
        self.assertEqual(created(decision_rule["payload"], None)[0], 400)
        self.assertEqual(created(decision_rule["payload"], signer.assertion(decision_rule["payload"], self.origin, "localhost", PRESENT, 0))[0], 201)
        forged_rule = prepared({**rule, "pattern": "cargo *"})
        self.assertEqual(created(forged_rule["payload"], key(-8, "stranger").assertion(forged_rule["payload"], self.origin, "localhost", PRESENT, 0))[0], 400)
        self.assertEqual(sorted((entry["kind"], entry["signed"]) for entry in self.snapshot()["rules"]), [("ask", True), ("decision", True), ("review", True)])
        with mock.patch.object(batches, "UNDO", 0.05):
            matched = self.create_ask(ASK)
            risky = self.create_ask({**ASK, "command": "make deploy && git push"})
            other = self.create_ask({**ASK, "tool": "Edit"})
            outside = self.create_ask({**ASK, "cwd": "/elsewhere"})
            cargo = self.create_ask({**ASK, "command": "cargo build"})
            green = self.request("feat: auto", "")
            red = self.tool("review_request", {**self.arguments("feat: red", "", self.page("red.html", PAGE)), "gate": "fail"})["structuredContent"]["id"]
            chosen = self.decision("Wait")
            plain = self.decision("")
            self.settle(lambda: self.ask_status(matched, "0") == "allowed")
            self.settle(lambda: self.status(green) == "approved")
            self.settle(lambda: self.choice(chosen) == "Wait")
            time.sleep(0.3)
        self.assertEqual([self.ask_status(ask, "0") for ask in (risky, other, outside, cargo)], ["pending", "pending", "pending", "pending"])
        self.assertEqual((self.status(red), self.choice(plain)), ("pending", None))
        self.assertEqual(len(self.events("kinds=rule")["events"]), 3)
        hook = self.trust("hook")
        verifier.check(json.loads(self.get(f"/api/asks/{matched}?wait=0")[2])["proof"], signing.ask_item(matched, "Bash", "make deploy", "/repo", "s1"), "", hook, time.time())
        relayed = json.loads(self.get(f"/api/reviews/{green}")[2])["proof"]
        commit = signing.review_item(green, "/repo/.git", "/repo/.worktrees/feature/x", "feature/x", TREE)
        verifier.check(relayed, commit, "pass", self.trust("commit"), time.time())
        with self.assertRaisesRegex(signing.Refused, "does not match"):
            verifier.check(relayed, commit, "fail", self.trust("commit"), time.time())
        self.assertEqual(self.call("POST", f"/api/rules/{asks['id']}/disable", b"", self.guard(self.host))[0], 200)
        with mock.patch.object(batches, "UNDO", 0.05):
            later = self.create_ask(ASK)
            time.sleep(0.3)
        self.assertEqual(self.ask_status(later, "0"), "pending")
        self.assertEqual(self.call("POST", f"/api/rules/{asks['id']}/delete", b"", self.guard(self.host))[0], 200)
        self.assertEqual(self.call("POST", f"/api/rules/{asks['id']}/delete", b"", self.guard(self.host))[0], 404)
        stored = {**asks, "enabled": True}
        subject = {"item": signing.ask_item(later, "Bash", "make deploy", "/repo", "s1"), "gate": ""}
        self.assertTrue(rules.rule_matches(stored, "ask", subject, now))
        self.assertFalse(rules.rule_matches({**stored, "expires": now - 1}, "ask", subject, now))
        self.assertFalse(rules.rule_matches({**stored, "proof": None}, "ask", subject, now))
        self.assertFalse(rules.rule_matches(stored, "ask", subject, stored["proof"]["payload"]["expires"] + 1))

    def test_the_commit_check_verifies_the_staged_tree_before_a_commit(self):
        repo = self.outside / "repo"
        repo.mkdir()
        self.git(repo, "init", "--quiet", "--initial-branch", "feature/x")
        (repo / "a.txt").write_text("one\n", encoding="utf-8")
        self.git(repo, "add", "a.txt")
        tree = self.git(repo, "write-tree").strip()
        common = self.git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
        top = self.git(repo, "rev-parse", "--show-toplevel").strip()
        arguments = {**self.arguments("feat: signed", "", self.page("signed.html", PAGE)), "repo": common, "worktree": top, "tree": tree}
        review_id = self.tool("review_request", arguments)["structuredContent"]["id"]

        def verify(gate: str) -> subprocess.CompletedProcess:
            argv = ["verify", "--port", str(self.port), "--approvers", str(self.approvers), "--replay", str(self.replay / "commit.json"), "--review", review_id, "--gate", gate]
            return subprocess.run([sys.executable, str(APPROVAL), *argv], cwd=repo, env={**os.environ, **GIT_ENV}, capture_output=True, text=True, timeout=60, check=False)

        done = verify("pass")
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn("the review is pending", done.stderr)
        signer = self.pin()
        entries = [self.entry("review", review_id, "", "")]
        with mock.patch.object(batches, "UNDO", 0.05):
            self.assertEqual(self.approve(entries, self.signed(entries, signer))[0], 202)
            self.settle(lambda: self.status(review_id) == "approved")
        (repo / "a.txt").write_text("two\n", encoding="utf-8")
        self.git(repo, "add", "a.txt")
        done = verify("pass")
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn("does not list this item", done.stderr)
        (repo / "a.txt").write_text("one\n", encoding="utf-8")
        self.git(repo, "add", "a.txt")
        done = verify("pass")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn(f"tree {tree} on feature/x", done.stdout)
        done = verify("pass")
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn("already used", done.stderr)


if __name__ == "__main__":
    unittest.main()
