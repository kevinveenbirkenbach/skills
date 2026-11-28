"""Exercise requirement 074: the board marks what runs now from queue.json, the presence beats and runner-job.json."""

from __future__ import annotations

import json
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from hub_case import HubCase
from hub_support import HUB, iso, runner
from kvb_orchestrator.presence import beats
from kvb_orchestrator.running import RUNNER_JOB, running_job

KANBAN = HUB / "templates" / "kanban.js"
NOW = 1_000_000
LONG = "make test-unit-python-with-a-very-long-target-name"
MARKS_PROBE = """
const K = require(process.argv[1]);
const now = Number(process.argv[2]);
const long = process.argv[3];
const row = (task, fields) => ({task, kind: "task", status: "running", worker: "-", roles: {}, ...fields});
const queue = (id, parent, status, start, kind) => ({task: `queue/${id}`, kind: "queue", status, worker: "Docs", roles: {}, start, queue: {kind, parent, enqueued: now - 9999, exit: null}});
const tasks = [
  row("work/all", {worker: "Stage", roles: {Main: "RA"}}),
  row("work/queue", {}),
  row("work/agent", {roles: {Docs: "R", Skills: "C"}}),
  row("work/stale", {worker: "Late"}),
  row("work/consulted", {roles: {Skills: "CI"}}),
  queue("q-1", "work/all", "running", now - 125, "test"),
  queue("q-2", "work/queue", "running", now - 3725, "quality-high"),
  queue("q-3", "work/queue", "running", now - 60, "deploy"),
  queue("q-4", "work/agent", "awaiting", null, "test"),
];
const beats = {Stage: now - 120, Main: now - 30, Docs: now - 120, Late: now - 600, Skills: now - 10};
const runner = {job: "j-1", task: "work/all", started: now - 45, command: `${long}\\nsecond`};
const sources = {now, tasks, beats, runner};
const shown = (task) => K.marks(tasks.find((entry) => entry.task === task), sources);
const edge = (age) => K.marks(row("work/edge", {worker: "Edge"}), {...sources, beats: {Edge: now - age}}).map((mark) => mark.key);
console.log(JSON.stringify({
  order: K.MARKS, window: K.BEAT_S,
  marks: Object.fromEntries(["work/all", "work/queue", "queue/q-1", "work/agent", "work/stale", "work/consulted"].map((task) => [task, shown(task)])),
  edges: [edge(K.BEAT_S), edge(K.BEAT_S + 1), edge(-5), edge(-3600)],
  bare: K.marks(row("work/all", {worker: "Stage"}), {now, tasks: [], beats: {}, runner: null}),
  headless: K.marks(row("work/x"), {now, tasks: [], beats: {}, runner: {job: "j-2", task: "work/x", started: now - 5, command: ""}}),
  other: K.marks(row("work/x"), {now, tasks, beats, runner}),
  heads: [K.head("  git push\\n  next"), K.head("x".repeat(40)), K.head("y".repeat(32))],
}));
"""


def mark(key: str, text: str, hint: str, at: float) -> dict:
    icon = {"queue": "bi-cpu", "agent": "bi-person-workspace", "hub": "bi-terminal"}[key]
    return {"key": key, "icon": icon, "text": text, "hint": hint, "at": at}


class TestMarks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        done = subprocess.run(["node", "-e", MARKS_PROBE, str(KANBAN), str(NOW), LONG], capture_output=True, text=True, timeout=60, check=True)
        cls.data = json.loads(done.stdout)

    def test_the_three_marks_come_in_queue_agent_hub_order_with_their_icon(self):
        self.assertEqual(self.data["order"], [["queue", "bi-cpu"], ["agent", "bi-person-workspace"], ["hub", "bi-terminal"]])
        self.assertEqual(self.data["marks"]["work/all"], [
            mark("queue", "test · 2 min", "work/all: queue job queue/q-1 runs test for 2 min", NOW - 125),
            mark("agent", "Main · 30 s", "work/all: Main works on it, last beat 30 s ago", NOW - 30),
            mark("hub", f"{LONG[:31]}…", f"work/all: the hub runs j-1 for 45 s: {LONG}\nsecond", NOW - 45),
        ])

    def test_the_queue_mark_names_the_longest_running_job_and_counts_the_others(self):
        self.assertEqual(self.data["marks"]["work/queue"], [mark("queue", "quality-high · 1 h 2 min", "work/queue: queue job queue/q-2 runs quality-high for 1 h 2 min, 1 more running", NOW - 3725)])
        self.assertEqual(self.data["marks"]["queue/q-1"], [
            mark("queue", "test · 2 min", "queue/q-1: queue job queue/q-1 runs test for 2 min", NOW - 125),
            mark("agent", "Docs · 2 min", "queue/q-1: Docs works on it, last beat 2 min ago", NOW - 120),
        ])

    def test_an_r_or_worker_beat_two_minutes_ago_marks_the_card_and_one_ten_minutes_ago_does_not(self):
        self.assertEqual(self.data["window"], 300)
        self.assertEqual(self.data["marks"]["work/agent"], [mark("agent", "Docs · 2 min", "work/agent: Docs works on it, last beat 2 min ago", NOW - 120)])
        self.assertEqual((self.data["marks"]["work/stale"], self.data["marks"]["work/consulted"]), ([], []))
        self.assertEqual(self.data["edges"], [["agent"], [], ["agent"], []])

    def test_without_sources_no_mark_shows_and_the_hub_mark_falls_back_to_the_job_id(self):
        self.assertEqual((self.data["bare"], self.data["other"]), ([], []))
        self.assertEqual(self.data["headless"], [mark("hub", "j-2", "work/x: the hub runs j-2 for 5 s: j-2", NOW - 5)])
        self.assertEqual(self.data["heads"], ["git push", f"{'x' * 31}…", "y" * 32])


class TestSources(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.marker = self.base / RUNNER_JOB

    def write(self, data: object) -> None:
        self.marker.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")

    def test_beats_keep_the_freshest_busy_session_or_claim_beat_per_agent(self):
        sessions = {
            "s1": {"name": "Stage session", "status": "busy", "statusUpdatedAt": (NOW - 120) * 1000, "running": True},
            "s2": {"name": "Stage", "status": "busy", "statusUpdatedAt": (NOW - 300) * 1000, "running": True},
            "s3": {"name": "Idle", "status": "idle", "statusUpdatedAt": NOW * 1000, "running": True},
            "s4": {"name": "Gone", "status": "busy", "statusUpdatedAt": NOW * 1000, "running": False},
            "s5": {"name": "Odd", "status": "busy", "statusUpdatedAt": True, "running": True},
        }
        claims = [{"agent": "Docs", "beat": NOW - 30}, {"agent": "Stage", "beat": NOW - 500}, {"agent": "Operator", "beat": NOW}, {"agent": "Quiet", "beat": None}, {"agent": "", "beat": NOW}]
        self.assertEqual(beats(sessions, claims), {"Stage": NOW - 120, "Docs": NOW - 30})
        self.assertEqual(beats({}, []), {})

    def test_the_runner_marker_serves_its_job_with_the_command_and_nothing_once_it_ended_or_is_malformed(self):
        self.assertEqual(RUNNER_JOB, runner.MARKER)
        jobs = [{"id": "j-1", "status": "running", "command": "make deploy"}, {"id": "j-2", "status": "done", "command": "make test"}]
        self.assertIsNone(running_job(self.marker, jobs))
        self.write({"pid": 7, "job": "j-1", "task": "work/a", "started": NOW})
        self.assertEqual(running_job(self.marker, jobs), {"job": "j-1", "task": "work/a", "started": float(NOW), "command": "make deploy"})
        self.write({"pid": 7, "job": "j-9", "task": "work/a", "started": NOW})
        self.assertEqual(running_job(self.marker, jobs), {"job": "j-9", "task": "work/a", "started": float(NOW), "command": ""})
        for data in ({"pid": 7, "job": "j-2", "task": "work/a", "started": NOW}, {"job": "j-1", "task": "", "started": NOW}, {"job": 5, "task": "work/a", "started": NOW},
                     {"job": "j-1", "task": "work/a", "started": "soon"}, {"job": "j-1", "task": "work/a", "started": True}, [1], "not json"):
            with self.subTest(data=data):
                self.write(data)
                self.assertIsNone(running_job(self.marker, jobs))

    def test_a_linked_marker_is_never_followed(self):
        target = self.base / "elsewhere.json"
        target.write_text(json.dumps({"job": "j-1", "task": "work/a", "started": NOW}), encoding="utf-8")
        self.marker.symlink_to(target)
        self.assertIsNone(running_job(self.marker, []))


class TestPayload(HubCase):
    def test_the_state_carries_the_beats_and_the_runner_job_the_board_reads(self):
        now = time.time()
        stamp = int((now - 120) * 1000)
        self.write_council({
            "rasci.json": {"work/alpha": {"title": "Alpha", "status": "running", "worker": "Stage"}},
            "work/alpha/claim.json": {"session": "c1", "runtime": "claude", "name": "Docs", "since": iso(now - 600), "beat": now - 30, "work": "alpha"},
            "chair/claim.json": {"session": "op", "runtime": "-", "name": "Operator", "since": iso(now - 600), "beat": now, "work": "chair"},
        })
        sessions = {"s1": {"name": "Stage session", "status": "busy", "statusUpdatedAt": stamp, "running": True}, "s2": {"name": "Idle", "status": "idle", "statusUpdatedAt": stamp, "running": True}}
        self.httpd.hub.agent_sessions.write_text(json.dumps({"written": now, "sessions": sessions}), encoding="utf-8")
        state = self.snapshot()
        self.assertEqual((state["beats"], state["runner"]), ({"Stage": stamp / 1000, "Docs": now - 30}, None))
        job = self.httpd.hub.jobs.add({"task": "work/alpha", "command": "make deploy", "directory": "/", "sha256": "", "status": "running", "proof": None, "head": "", "code": None, "output": "", "created_ts": now, "started": now - 45, "finished": None, "dismissed": False})
        self.assertEqual(self.httpd.hub.runner_marker, self.state / RUNNER_JOB)
        self.httpd.hub.runner_marker.write_text(json.dumps({"pid": 1, "job": job["id"], "task": "work/alpha", "started": now - 45}), encoding="utf-8")
        self.assertEqual(self.snapshot()["runner"], {"job": job["id"], "task": "work/alpha", "started": now - 45, "command": "make deploy"})
        self.httpd.hub.jobs.change(job["id"], {"status": "done"})
        self.assertIsNone(self.snapshot()["runner"])
        self.httpd.hub.runner_marker.write_text("{broken", encoding="utf-8")
        self.assertIsNone(self.snapshot()["runner"])

    def test_the_page_ships_the_marks_module_before_the_board_and_draws_from_both_sources(self):
        html = self.index()
        marks = (HUB / "templates" / "kanban-marks.js").read_text(encoding="utf-8").strip()
        self.assertIn(marks, html)
        self.assertLess(html.index(marks), html.index((HUB / "templates" / "kanban.js").read_text(encoding="utf-8").strip()))
        page = (HUB / "templates" / "page-running.js").read_text(encoding="utf-8")
        self.assertIn("state.beats, runner: state.runner", page)
        self.assertIn("state.beats, state.runner", (HUB / "templates" / "page-tasks.js").read_text(encoding="utf-8"))
        self.assertIn("Kanban.marks(row, sources)", (HUB / "templates" / "page-kanban.js").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
