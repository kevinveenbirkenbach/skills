from __future__ import annotations

import hashlib
import json
import time
import unittest
from unittest import mock

from hub_case import HubCase
from hub_support import HUB
from kvb_orchestrator import batches, skill_scripts

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
        self.assertEqual(kept["job"]["output"], "line 1\nline 2\n")
        self.assertEqual(self.snapshot()["badges"]["tasks"], 1)
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
