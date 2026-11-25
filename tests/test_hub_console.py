from __future__ import annotations

import hashlib
import json
import time
import unittest
from unittest import mock

from hub_case import HubCase
from hub_support import HUB
from kvb_orchestrator import batches, jobs, skill_scripts

COMMAND = "echo hi"
DIGEST = hashlib.sha256(COMMAND.encode()).hexdigest()


class TestHubConsole(HubCase):
    def item(self, item_id: str) -> dict | None:
        return next((item for item in self.snapshot()["inbox"] if item["id"] == item_id), None)

    def register(self, status: str) -> None:
        row = {"title": COMMAND, "workdir": str(self.outside), "description": "say hi", "check": "manual", "status": status, "roles": {"Operator": "R", "Skills session": "A"}}
        self.write_council({"rasci.json": {"operator/greet": row}})

    def runner(self, path: str, payload: dict) -> tuple[int, dict]:
        status, _, body = self.call("POST", path, json.dumps(payload).encode(), {**self.client(), "Content-Type": "application/json"})
        return status, json.loads(body) if status < 300 else {}

    def dismiss(self, payload: object, headers: dict[str, str]) -> int:
        return self.post_json("/api/inbox/dismiss", payload, headers)[0]

    def test_a_commit_row_lists_the_reviews_it_verifies_and_queues_its_job_only_after_them(self):
        self.claim("s1", "Skills session")
        review = self.request("feat: x", "notes")
        command = f"python3 approval.py verify --port 8737 --review {review} --gate pass && python3 approval.py verify --port 8737 --review {'f' * 16} --gate pass && git commit -m x"
        row = {"title": command, "workdir": str(self.outside), "description": "commit", "check": "manual", "status": "queued", "roles": {"Operator": "R", "Skills session": "A"}}
        self.write_council({"rasci.json": {"operator/commit": row}})
        self.assertEqual(self.item("operator/commit")["reviews"], [{"id": review, "status": "pending", "gate": "pass"}, {"id": "f" * 16, "status": "unknown", "gate": ""}])
        self.assertEqual(self.item(review)["reviews"], [])
        seen = []
        queue = jobs.Jobs.queue_job

        def spy(hub, item, proof):
            seen.append(hub.reviews.get(review)["status"])
            return queue(hub, item, proof)

        signer = self.pin()
        entries = [self.entry("operator", "operator/commit", "", hashlib.sha256(command.encode()).hexdigest()), self.entry("review", review, "", "")]
        with mock.patch.object(batches, "UNDO", 0.05), mock.patch.object(jobs.Jobs, "queue_job", spy):
            self.assertEqual(self.approve(entries, self.signed(entries, signer))[0], 202)
            self.settle(lambda: self.item("operator/commit")["job"] is not None)
        self.assertEqual(seen, ["approved"])
        self.assertEqual(self.item("operator/commit")["reviews"][0]["status"], "approved")

    def test_the_job_console_stays_under_the_command_until_the_row_is_dismissed(self):
        self.claim("s1", "Skills session")
        self.register("queued")
        row = self.item("operator/greet")
        self.assertEqual((row["job"], row["runnable"], row["deniable"], row["agent"], row["sha256"]), (None, True, True, "Skills", DIGEST))
        signer = self.pin()
        entries = [self.entry("operator", "operator/greet", "", DIGEST)]
        with mock.patch.object(batches, "UNDO", 0.05):
            self.assertEqual(self.approve(entries, self.signed(entries, signer))[0], 202)
            self.settle(lambda: self.item("operator/greet")["job"] is not None)
        row = self.item("operator/greet")
        job = row["job"]
        self.assertEqual((job["status"], job["output"], job["code"], job["started"], row["runnable"], row["deniable"]), ("queued", "", None, None, False, False))
        self.assertEqual(self.approve(entries, None)[0], 409)
        self.assertEqual(self.dismiss({"id": job["id"]}, self.guard(self.host)), 409)
        self.assertEqual(self.runner(f"/api/runner/{job['id']}/claim", {})[0], 200)
        self.assertEqual(self.runner(f"/api/runner/{job['id']}/report", {"output": "line 1\n", "code": None, "refused": False})[0], 200)
        running = self.item("operator/greet")["job"]
        self.assertEqual((running["status"], running["output"]), ("running", "line 1\n"))
        self.assertLessEqual(running["started"], time.time())
        self.assertEqual(self.runner(f"/api/runner/{job['id']}/report", {"output": "line 1\nline 2\n", "code": 0, "refused": False})[0], 200)
        row = self.item("operator/greet")
        self.assertEqual((row["job"]["status"], row["job"]["code"], row["job"]["output"], row["runnable"]), ("done", 0, "line 1\nline 2\n", True))
        self.assertGreaterEqual(row["job"]["finished"], row["job"]["started"])
        self.register("done")
        kept = self.item("operator/greet")
        self.assertEqual((kept["kind"], kept["title"], kept["command"], kept["directory"], kept["runnable"], kept["deniable"]), ("operator", COMMAND, COMMAND, str(self.outside), False, False))
        self.assertEqual((kept["job"]["output"], kept["settled"]), ("line 1\nline 2\n", True))
        self.assertEqual(self.snapshot()["badges"]["tasks"], 0)
        self.assertIn("<title>Agent Orchestrator</title>", self.index())
        for payload in ({"id": "nope"}, {"id": job["id"], "extra": 1}, {}, [job["id"]]):
            with self.subTest(payload=payload):
                self.assertEqual(self.dismiss(payload, self.guard(self.host)), 400)
        self.assertEqual(self.dismiss({"id": "0123456789abcdef"}, self.guard(self.host)), 404)
        self.assertEqual(self.dismiss({"id": job["id"]}, self.client()), 403)
        self.assertEqual(self.get("/api/inbox/dismiss")[0], 405)
        self.assertEqual(self.dismiss({"id": job["id"]}, self.guard(self.host)), 200)
        self.assertIsNone(self.item("operator/greet"))
        self.assertEqual(self.snapshot()["jobs"][-1]["dismissed"], True)

    def test_the_console_carries_only_the_tail_the_job_list_shows(self):
        self.register("queued")
        output = "".join(f"line {number}\n" for number in range(3000))
        fields = {"task": "operator/greet", "command": COMMAND, "directory": str(self.outside), "sha256": DIGEST, "status": "running", "proof": None}
        self.httpd.hub.jobs.add({**fields, "code": None, "output": output, "created_ts": time.time(), "started": time.time(), "finished": None, "dismissed": False})
        snapshot = self.snapshot()
        console = next(item for item in snapshot["inbox"] if item["id"] == "operator/greet")["job"]["output"]
        self.assertEqual(console, output[-skill_scripts.OUTPUT_LIMIT :])
        self.assertEqual(console, snapshot["jobs"][-1]["output"])

    def test_only_a_done_or_failed_command_job_reports_the_command_and_directory_it_ran(self):
        self.register("queued")
        fields = {"task": "operator/greet", "command": COMMAND, "directory": str(self.outside), "sha256": DIGEST, "status": "running", "proof": None}
        jobs = [
            self.httpd.hub.jobs.add({**fields, **extra, "code": None, "output": "", "created_ts": time.time(), "started": time.time(), "finished": None, "dismissed": False})
            for extra in ({}, {}, {}, {}, {}, {}, {}, {"kind": "gate", "argv": []})
        ]
        reports = (
            {"output": "token-42\n", "code": 0, "refused": False, "checked": True}, {"output": "", "code": 0, "refused": False, "checked": False},
            {"output": "", "code": 0, "refused": False}, {"output": "token-42\n", "code": 3, "refused": False},
            {"output": "", "code": -9, "refused": False}, {"output": "", "code": 130, "refused": False},
            {"output": "token-42\n", "code": None, "refused": True}, {"output": "", "code": 1, "refused": False},
        )
        answers = [self.runner(f"/api/runner/{job['id']}/report", report) for job, report in zip(jobs, reports)]
        self.assertEqual([(status, body["status"], len(body["runs"])) for status, body in answers], [
            (200, "done", 1), (200, "done", 1), (200, "done", 1), (200, "failed", 1), (200, "failed", 1), (200, "failed", 1), (200, "refused", 0), (200, "failed", 0),
        ])
        shown = ["greet", f"--command={COMMAND}", f"--dir={self.outside}"]
        where = [f"--where=the console of hub job {job['id']} under the row in Waits on Operator" for job in jobs[3:6]]
        self.assertEqual(self.scripts.calls, [
            (skill_scripts.OPERATOR_SCRIPT, ["ran", *shown]),
            (skill_scripts.OPERATOR_SCRIPT, ["ran", *shown, "--check-failed"]),
            (skill_scripts.OPERATOR_SCRIPT, ["ran", *shown, "--check-failed"]),
            (skill_scripts.OPERATOR_SCRIPT, ["failed", *shown, "--why", "exit 3", where[0]]),
            (skill_scripts.OPERATOR_SCRIPT, ["failed", *shown, "--why", "killed by signal 9", where[1]]),
            (skill_scripts.OPERATOR_SCRIPT, ["failed", *shown, "--why", "exit 130", where[2]]),
        ])
        self.assertNotIn("token-42", json.dumps(self.scripts.calls))

    def test_a_ran_the_installed_operator_refuses_never_falls_back_to_done(self):
        self.register("queued")
        fields = {"task": "operator/greet", "command": COMMAND, "directory": str(self.outside), "sha256": DIGEST, "status": "running", "proof": None}
        job = self.httpd.hub.jobs.add({**fields, "code": None, "output": "", "created_ts": time.time(), "started": time.time(), "finished": None, "dismissed": False})
        self.scripts.code = 2
        done = self.runner(f"/api/runner/{job['id']}/report", {"output": "", "code": 0, "refused": False, "checked": False})[1]
        shown = ["greet", f"--command={COMMAND}", f"--dir={self.outside}"]
        self.assertEqual(self.scripts.calls, [(skill_scripts.OPERATOR_SCRIPT, ["ran", *shown, "--check-failed"])])
        self.assertEqual(len(done["runs"]), 1)

    def test_a_report_with_a_checked_other_than_true_false_or_null_is_refused(self):
        self.register("queued")
        fields = {"task": "operator/greet", "command": COMMAND, "directory": str(self.outside), "sha256": DIGEST, "status": "running", "proof": None}
        job = self.httpd.hub.jobs.add({**fields, "code": None, "output": "", "created_ts": time.time(), "started": time.time(), "finished": None, "dismissed": False})
        for checked in ("yes", 1, [True]):
            with self.subTest(checked=checked):
                self.assertEqual(self.runner(f"/api/runner/{job['id']}/report", {"output": "", "code": 0, "refused": False, "checked": checked})[0], 400)
        self.assertEqual(self.runner(f"/api/runner/{job['id']}/report", {"output": "", "code": 0, "refused": False, "checked": None})[1]["status"], "done")
        self.assertEqual(self.scripts.calls[-1][1][-1], "--check-failed")

    def test_jobs_from_before_the_console_stay_out_of_the_inbox(self):
        self.register("done")
        fields = {"task": "operator/greet", "command": COMMAND, "directory": str(self.outside), "sha256": DIGEST, "status": "done", "proof": None}
        self.httpd.hub.jobs.add({**fields, "code": 0, "output": "old\n", "created_ts": time.time(), "started": time.time(), "finished": time.time()})
        self.assertIsNone(self.item("operator/greet"))

    def test_the_page_draws_the_console_as_text_and_follows_its_end(self):
        html = self.index()
        for text in ('"/api/inbox/dismiss"', "console-out", "waiting for the runner", "Exit code", "textContent", "scrollHeight"):
            with self.subTest(text=text):
                self.assertIn(text, html)
        for name in ("page-console.js", "page-deny.js", "page-rule-request.js"):
            with self.subTest(name=name):
                self.assertNotIn("innerHTML", (HUB / "templates" / name).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
