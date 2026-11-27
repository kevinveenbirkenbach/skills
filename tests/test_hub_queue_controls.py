from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

from hub_case import HubCase
from hub_support import REPO_ROOT, RUNNER, runner, signing
from test_hub_queue_overlay import calls, fake_queue

QUEUE = REPO_ROOT / "skills" / "kvb-org-queue" / "scripts" / "queue.py"
LEARNED = {
    "kinds": {"test": {"runs": 7, "ram_share": 12.5, "cpu_share": 30.0, "limit": 2, "light": False, "ram_cap": None, "slot_limit": 2, "slot_source": "learned"}},
    "signatures": [{"kind": "test", "signature": "make test", "runs": 7, "minutes": 4.0, "longest": 6.0, "disk_gb": 1.0, "ram_share": 12.5, "cpu_share": 30.0, "need_gb": 2}],
    "budget_percent": {"ram": 75, "cpu": 100}, "ram_cap_percent": {}, "load_limits": {"cpu_percent": 90, "mem_percent": 85, "sample_seconds": 5}, "slot_limits": {},
    "history": [{"id": "r1", "kind": "test", "signature": "make test", "end": 1.0, "minutes": 4.0, "exit": 0, "override": True}],
}
LEARNED_QUEUE = """import json
import pathlib
import sys

here = pathlib.Path(__file__)
with here.with_suffix(".calls").open("a", encoding="utf-8") as calls:
    calls.write(" ".join(sys.argv[1:]) + "\\n")
if sys.argv[1:] != ["learned", "--json"]:
    sys.exit(2)
sys.stdout.write(here.with_name("rows.json").read_text(encoding="utf-8"))
"""


def override(entry_id: str) -> dict:
    return {"kind": "queue", "argv": ["override", entry_id]}


def setting(key: str, value: str) -> dict:
    return {"kind": "queue", "argv": ["config", "set", key, value]}


class TestQueueArgv(unittest.TestCase):
    def test_exactly_override_of_one_id_and_config_set_of_a_known_key_pass(self):
        for argv in (["override", "quality-high-1997"], ["config", "set", "budget_percent.cpu", "180"], ["config", "set", "slot_limits.gui-dind", "2"],
                     ["config", "set", "ram_cap_percent.test", "35.5"], ["config", "set", "load_limits.sample_seconds", "5"],
                     ["config", "set", "load_limits.band_low", "60"], ["config", "set", "load_limits.band_high", "85"]):
            with self.subTest(argv=argv):
                self.assertEqual(signing.queue_argv(argv), argv)
                self.assertEqual(signing.queue_item(argv), {"kind": "queue", "argv": argv})

    def test_every_other_argv_is_refused(self):
        cases = {
            "not a list": "override x-1", "no texts": ["override", 1], "hold": ["hold", "--kind", "test", "--task", "t", "--", "rm", "-rf", "/"],
            "cancel": ["cancel", "test-1"], "list": ["list", "--json"], "extra": ["override", "test-1", "--session", "x"], "bare id": ["override", "test"],
            "option id": ["override", "--help"], "unknown key": ["config", "set", "cpu_cap_percent.test", "50"], "section only": ["config", "set", "budget_percent", "50"],
            "foreign section": ["config", "set", "thresholds_gb.stop", "1"], "load kinds": ["config", "set", "load_limits.kinds", "1"], "pattern kind": ["config", "set", "slot_limits.*", "1"],
            "exponent": ["config", "set", "budget_percent.cpu", "1e3"], "negative": ["config", "set", "budget_percent.cpu", "-5"], "nan": ["config", "set", "budget_percent.cpu", "NaN"],
            "config get": ["config", "get", "budget_percent.cpu", "1"], "missing value": ["config", "set", "budget_percent.cpu"],
        }
        for name, argv in cases.items():
            with self.subTest(name=name):
                self.assertRaises(signing.Refused, signing.queue_argv, argv)


class TestHubQueue(HubCase):
    def test_two_staged_settings_take_one_signature_and_become_one_runner_job_each(self):
        items = [setting("budget_percent.cpu", "180"), setting("slot_limits.test", "2")]
        payload = self.prepare(items)["payload"]
        self.assertEqual(sorted(payload["items"]), sorted(signing.item_hash(signing.queue_item(item["argv"])) for item in items))
        proof = self.pin().proof(payload, self.origin)
        self.assertEqual(self.post_json("/api/queue", {"items": items, "proof": None}, self.guard(self.host))[0], 400)
        self.assertEqual(self.post_json("/api/queue", {"items": items, "proof": proof}, {"Host": self.host})[0], 403)
        status, _, body = self.post_json("/api/queue", {"items": items, "proof": proof}, self.guard(self.host))
        self.assertEqual(status, 202, body)
        self.assertEqual(len(json.loads(body)["jobs"]), 2)
        jobs = self.runner_jobs()
        self.assertEqual(sorted((job["kind"], job["argv"], job["command"]) for job in jobs), sorted(("queue", item["argv"], "queue.py " + " ".join(item["argv"])) for item in items))

    def test_the_hub_refuses_a_malformed_or_forged_queue_change_before_it_queues(self):
        for name, items in (("hold", [{"kind": "queue", "argv": ["hold", "--", "true"]}]), ("unknown key", [setting("cpu_cap_percent.test", "5")]), ("twice", [override("test-1"), override("test-1")]), ("extra key", [{**override("test-1"), "id": "x"}])):
            with self.subTest(name=name):
                status, _, body = self.post_json("/api/sign", {"items": items}, self.guard(self.host))
                self.assertEqual(status, 400, body)
        proof = self.signed([override("test-1")], self.pin())
        status, _, body = self.post_json("/api/queue", {"items": [override("test-2")], "proof": proof}, self.guard(self.host))
        self.assertEqual(status, 400, body)
        self.assertEqual(self.runner_jobs(), [])

    def test_the_queue_route_serves_learned_json_read_only_and_none_without_it(self):
        script = fake_queue(self.state.parent / "fake-skills", LEARNED_QUEUE, LEARNED)
        self.httpd.hub.queue_order.script = script
        status, _, body = self.get("/api/queue")
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body), {"learned": LEARNED})
        self.assertEqual(calls(script), ["learned --json"])
        broken = fake_queue(self.state.parent / "broken-skills", LEARNED_QUEUE, {**LEARNED, "kinds": []})
        self.httpd.hub.queue_order.script = broken
        self.assertEqual(json.loads(self.get("/api/queue")[2]), {"learned": None})

    def test_the_page_ships_the_queue_tab_and_start_now(self):
        html = self.index()
        for marker in ('["queue", "Queue", "bi-hourglass-split"]', "queue: [queuePanel()]", '"data-panel": "stream/queue"', '["override", job.id]', "startNow(job)"):
            with self.subTest(marker=marker):
                self.assertIn(marker, html)


class TestRunnerQueue(HubCase):
    def setUp(self):
        super().setUp()
        self.home = self.outside / "home"
        self.config = self.home / ".claude" / "agents-council" / "config.json"
        self.config.parent.mkdir(parents=True)
        shipped = json.loads((REPO_ROOT / "skills" / "kvb-org-organize" / "config.default.json").read_text(encoding="utf-8"))
        self.config.write_text(json.dumps(shipped), encoding="utf-8")
        self.council.mkdir(exist_ok=True)
        me = os.getpid()
        entry = {"id": "test-1", "seq": 1, "kind": "test", "task": "work/a", "need_gb": 0, "hotfix": None, "workdir": "/w1", "session": "s1", "name": "s1",
                 "pid": me, "pid_start": None, "child": None, "child_start": None, "status": "waiting", "enqueued": time.time(), "granted": None, "cmd": "true"}
        (self.council / "queue.json").write_text(json.dumps({"seq": 1, "entries": [entry]}), encoding="utf-8")

    def run_queue_runner(self, flags: list[str]) -> None:
        trust = ["--approvers", str(self.approvers), "--replay", str(self.replay / "runner.json"), "--state", str(self.state)]
        command = [sys.executable, str(RUNNER), "--port", str(self.port), "--interval", "0.1", *trust, *flags, "--once"]
        done = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False, env={**os.environ, "HOME": str(self.home)})
        self.assertEqual(done.returncode, 0, done.stderr)

    def queue(self, items: list[dict]) -> None:
        proof = self.signed(items, self.pin())
        status, _, body = self.post_json("/api/queue", {"items": items, "proof": proof}, self.guard(self.host))
        self.assertEqual(status, 202, body)

    def finished(self) -> list[tuple[str, int | None]]:
        return [(job["status"], job["code"]) for job in sorted(self.httpd.hub.jobs.listed(), key=lambda job: job["created_ts"])]

    def flags(self) -> list[str]:
        return ["--queue", str(QUEUE), "--council", str(self.council), "--rasci", str(REPO_ROOT / "skills" / "kvb-org-rasci" / "scripts" / "rasci.py")]

    def test_the_runner_overrides_the_signed_job_and_sets_both_signed_settings_by_argv(self):
        self.queue([override("test-1"), setting("budget_percent.cpu", "180"), setting("load_limits.cpu_percent", "95")])
        self.run_queue_runner(self.flags())
        self.assertEqual(self.finished(), [("done", 0)] * 3)
        entry = json.loads((self.council / "queue.json").read_text(encoding="utf-8"))["entries"][0]
        self.assertIn("ts", entry["override"])
        cfg = json.loads(self.config.read_text(encoding="utf-8"))
        self.assertEqual((cfg["budget_percent"]["cpu"], cfg["load_limits"]["cpu_percent"]), (180, 95))

    def test_a_value_queue_py_refuses_fails_the_job_and_leaves_the_config(self):
        before = self.config.read_bytes()
        self.queue([setting("load_limits.mem_percent", "101")])
        self.run_queue_runner(self.flags())
        self.assertEqual(self.finished(), [("failed", 2)])
        self.assertEqual(self.config.read_bytes(), before)

    def test_without_queue_the_runner_refuses_and_writes_nothing(self):
        before = (self.council / "queue.json").read_bytes()
        self.queue([override("test-1")])
        self.run_queue_runner([])
        self.assertEqual([(job["status"], job["output"]) for job in self.httpd.hub.jobs.listed()], [("refused", runner.UNQUEUED)])
        self.assertEqual((self.council / "queue.json").read_bytes(), before)

    def test_the_runner_refuses_an_argv_that_differs_from_the_signed_one(self):
        self.queue([override("test-1")])
        job = self.httpd.hub.jobs.listed()[0]
        self.httpd.hub.jobs.change(job["id"], {"argv": ["override", "test-2"]})
        self.run_queue_runner(self.flags())
        refused = self.httpd.hub.jobs.listed()[0]
        self.assertEqual(refused["status"], "refused")
        self.assertIn("does not list this item", refused["output"])

    def test_queue_refusal_checks_the_argv_shape_before_any_signature(self):
        reason = runner.queue_refusal({"argv": ["hold", "--", "true"], "proof": None}, mock.Mock(), time.time())
        self.assertIn("queue.py override <id> or config set", reason)
        with self.assertRaises(signing.Refused):
            runner.queue({"argv": ["cancel", "test-1"]}, runner.Scripts(register=None, gates=None, queue=Path("/x/queue.py"), schedules=None, radio=None), print)


if __name__ == "__main__":
    unittest.main()
