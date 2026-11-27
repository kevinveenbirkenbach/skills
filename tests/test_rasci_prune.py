"""Exercise requirement 075: rasci.py keep touches a task's change time, rasci.py prune stops only the unkept listed tasks."""

from __future__ import annotations

import datetime
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RASCI = REPO_ROOT / "skills" / "kvb-org-rasci" / "scripts" / "rasci.py"
OLD = "2026-11-01T08:00:00+00:00"
SINCE = int(datetime.datetime.fromisoformat("2026-11-20T00:00:00+00:00").timestamp())


def row(status: str, updated: str, **fields: object) -> dict:
    return {"roles": {"Docs": "RA"}, "status": status, "updated": updated, "title": "t", **fields}


class TestRasciPrune(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "home"
        self.root = Path(self.tmp.name) / "council"
        self.home.mkdir()
        self.root.mkdir()
        self.write({
            "work/stale": row("queued", OLD),
            "work/blocked": row("blocked", OLD),
            "work/fresh": row("running", "2026-11-25T08:00:00+00:00"),
            "work/queued-job": row("running", OLD),
            "work/done": row("done", OLD, end=OLD),
            "work/other": row("queued", OLD),
        })

    def write(self, tasks: dict) -> None:
        (self.root / "rasci.json").write_text(json.dumps(tasks), encoding="utf-8")

    def tasks(self) -> dict:
        return json.loads((self.root / "rasci.json").read_text(encoding="utf-8"))

    def run_rasci(self, *args: str) -> subprocess.CompletedProcess:
        env = {"PATH": "/usr/bin:/bin", "HOME": str(self.home), "AGENTS_COUNCIL_ROOT": str(self.root)}
        return subprocess.run([sys.executable, str(RASCI), *args], capture_output=True, text=True, env=env, cwd=self.tmp.name, check=False, timeout=120)

    def queue(self, entries: list[dict]) -> None:
        (self.root / "queue.json").write_text(json.dumps({"seq": len(entries), "entries": entries}), encoding="utf-8")

    def test_keep_moves_only_the_change_time_of_an_open_task(self):
        before = self.tasks()["work/stale"]
        done = self.run_rasci("keep", "work/stale")
        self.assertEqual(done.returncode, 0, done.stderr)
        after = self.tasks()["work/stale"]
        self.assertGreater(datetime.datetime.fromisoformat(after["updated"]), datetime.datetime.fromisoformat(OLD))
        self.assertEqual({key: value for key, value in after.items() if key != "updated"}, {key: value for key, value in before.items() if key != "updated"})

    def test_keep_refuses_an_unknown_or_ended_task_and_writes_nothing(self):
        before = (self.root / "rasci.json").read_bytes()
        for task in ("work/missing", "work/done"):
            with self.subTest(task=task):
                done = self.run_rasci("keep", task)
                self.assertEqual(done.returncode, 2)
                self.assertIn("no open task", done.stderr)
        self.assertEqual((self.root / "rasci.json").read_bytes(), before)

    def test_prune_stops_the_unchanged_open_listed_tasks_and_reports_every_other_as_kept(self):
        self.queue([{"id": "test-1", "task": "work/queued-job", "status": "active"}, {"id": "test-2", "task": "work/stale", "status": "waiting"}])
        done = self.run_rasci("prune", "--since", str(SINCE), "work/stale", "work/blocked", "work/fresh", "work/queued-job", "work/done", "work/missing")
        self.assertEqual(done.returncode, 0, done.stderr)
        lines = done.stdout.splitlines()
        self.assertEqual(lines[:2], ["stopped work/stale", "stopped work/blocked"])
        self.assertTrue(lines[2].startswith("kept work/fresh: changed at 2026-11-25T08:00:00+00:00"), lines)
        self.assertEqual(lines[3:], ["kept work/queued-job: a queue job runs for it", "kept work/done: already done", "kept work/missing: not in the register"])
        tasks = self.tasks()
        self.assertEqual({task: tasks[task]["status"] for task in tasks}, {"work/stale": "stopped", "work/blocked": "stopped", "work/fresh": "running", "work/queued-job": "running", "work/other": "queued"})
        self.assertIn("end", tasks["work/stale"])
        archived = json.loads((self.root / "rasci-archive.json").read_text(encoding="utf-8"))
        self.assertEqual(archived["work/done"]["status"], "done")

    def test_a_task_kept_after_the_list_was_taken_stays_open(self):
        self.assertEqual(self.run_rasci("keep", "work/stale").returncode, 0)
        done = self.run_rasci("prune", "--since", str(SINCE), "work/stale", "work/other")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue(done.stdout.startswith("kept work/stale: changed at "), done.stdout)
        self.assertEqual((self.tasks()["work/stale"]["status"], self.tasks()["work/other"]["status"]), ("queued", "stopped"))

    def test_a_task_never_listed_is_never_changed(self):
        before = self.tasks()["work/other"]
        self.assertEqual(self.run_rasci("prune", "--since", str(SINCE), "work/stale").returncode, 0)
        self.assertEqual(self.tasks()["work/other"], before)

    def test_a_second_prune_stops_nothing_more(self):
        first = self.run_rasci("prune", "--since", str(SINCE), "work/stale")
        snapshot = self.tasks()
        second = self.run_rasci("prune", "--since", str(SINCE), "work/stale")
        self.assertEqual((first.stdout, second.stdout), ("stopped work/stale\n", "kept work/stale: already stopped\n"))
        self.assertEqual(self.tasks(), snapshot)

    def test_an_unreadable_queue_file_fails_and_stops_nothing(self):
        before = (self.root / "rasci.json").read_bytes()
        (self.root / "queue.json").write_text("{not json", encoding="utf-8")
        done = self.run_rasci("prune", "--since", str(SINCE), "work/stale")
        self.assertEqual(done.returncode, 2)
        self.assertIn("running queue jobs are unknown", done.stderr)
        self.assertEqual((self.root / "rasci.json").read_bytes(), before)

    def test_prune_refuses_an_invalid_slug_or_a_missing_since(self):
        self.assertEqual(self.run_rasci("prune", "--since", str(SINCE), "Not A Slug").returncode, 2)
        self.assertEqual(self.run_rasci("prune", "work/stale").returncode, 2)
        self.assertEqual(self.tasks()["work/stale"]["status"], "queued")


if __name__ == "__main__":
    unittest.main()
