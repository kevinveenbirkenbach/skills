from __future__ import annotations

import json
import os
import unittest

import test_queue as fixtures

LOAD = "CPU 95 % busy reaches the limit 90 %"
MARK = {"override": {"ts": fixtures.NOW - 30}}


class TestOverridePass(fixtures.Passes, unittest.TestCase):
    def busy(self, **fields: object) -> list[dict]:
        return [fixtures.job(1, status="active"), fixtures.job(2, **fields)]

    def shares(self) -> dict[str, dict[str, float]]:
        return {"j1": {"ram": 1, "cpu": 70}, "j2": {"ram": 1, "cpu": 40}}

    def test_the_band_holds_a_job_and_its_override_grants_it_first(self):
        held = self.decide(self.busy(), footprints=self.shares())
        self.assertEqual(held["j2"], "would reach 110 % CPU > 100 %")
        granted = self.decide(self.busy(**MARK), footprints=self.shares())
        self.assertEqual(granted, {"j2": None})

    def test_the_override_skips_slots_and_rank_and_counts_against_the_disk_of_the_next(self):
        entries = [fixtures.job(1, kind="deploy", status="active"), fixtures.job(2, kind="deploy", task="work/c", **MARK), fixtures.job(3, need_gb=89)]
        verdicts = self.decide(entries, free_gb=100.0)
        self.assertEqual(next(iter(verdicts)), "j2")
        self.assertIsNone(verdicts["j2"])
        self.assertIn("floor", verdicts["j3"])

    def test_the_live_guard_still_holds_an_overridden_job_and_its_reason_names_it(self):
        steps: dict[str, list[str]] = {}
        verdicts = self.decide(self.busy(**MARK), footprints=self.shares(), loaded={"j2": LOAD}, trace=steps)
        self.assertEqual(verdicts["j2"], f"override held by the live guard load_limits: {LOAD}")
        self.assertEqual(steps["j2"][0], "override: skips the band, slots, reservations and rank")

    def test_the_disk_the_memory_stage_and_a_running_job_of_its_line_still_hold_it(self):
        cases = {
            "floor": ({"free_gb": 12.0}, {"need_gb": 5}, "would cut into the 10 GB floor"),
            "stage": ({"stage": "stop"}, {}, "disk stage stop"),
            "memory": ({"memory": "stop"}, {}, "memory stage stop"),
            "line": ({}, {"workdir": "/w1"}, "its line runs j1"),
        }
        for name, (rules, fields, reason) in cases.items():
            with self.subTest(case=name):
                verdicts = self.decide(self.busy(**MARK, **fields), footprints=self.shares(), **rules)
                self.assertTrue(verdicts["j2"].startswith("override held by "), verdicts)
                self.assertIn(reason, verdicts["j2"])

    def test_a_silent_holder_is_never_forced(self):
        verdicts = self.decide(self.busy(polled=fixtures.NOW - 120, **MARK), footprints=self.shares())
        self.assertTrue(verdicts["j2"].startswith("no poll for"))

    def test_the_history_row_of_an_overridden_run_carries_override_true(self):
        queue, history = self.queue, fixtures._load(fixtures.HISTORY)
        entry = fixtures.job(2)
        sample = {"free_gb": 50.0, "mem": 20.0, "cpu": 10.0}
        row = history.row(queue.finished(entry, "make test", None, True, None), fixtures.NOW - 60, fixtures.NOW, 0, [sample], 1)
        self.assertIs(row["override"], True)
        self.assertNotIn("override", queue.finished(entry, "make test", None, False, None))


class TestOverrideCommand(unittest.TestCase):
    setUp = fixtures.TestQueueCommands.setUp
    write_config = fixtures.TestQueueCommands.write_config
    write_store = fixtures.TestQueueCommands.write_store
    entries = fixtures.TestQueueCommands.entries
    run_queue = fixtures.TestQueueCommands.run_queue

    def stored_entries(self) -> list[dict]:
        me = os.getpid()
        return [fixtures.stored(1, "waiting", me, None, None, None), fixtures.stored(2, "active", me, None, me, None)]

    def test_override_marks_a_waiting_entry_of_any_session(self):
        self.write_store(self.stored_entries())
        done = self.run_queue("override", "test-1")
        self.assertEqual(done.returncode, 0, done.stderr)
        marked = {entry["id"]: entry.get("override") for entry in self.entries()}
        self.assertIsInstance(marked["test-1"]["ts"], float)
        self.assertIsNone(marked["test-2"])

    def test_an_unknown_or_running_id_exits_2_and_changes_nothing(self):
        self.write_store(self.stored_entries())
        store = self.root / "queue.json"
        before = store.read_bytes()
        for entry_id in ("test-9", "test-2"):
            with self.subTest(id=entry_id):
                done = self.run_queue("override", entry_id)
                self.assertEqual(done.returncode, 2, done.stderr)
                self.assertIn(f"no waiting entry {entry_id}", done.stderr)
                self.assertEqual(store.read_bytes(), before)

    def test_list_json_shows_which_entry_is_overridden(self):
        me = os.getpid()
        mine = fixtures._load(fixtures.QUEUE).identity(me)
        self.write_store([{**fixtures.stored(1, "waiting", me, mine, None, None), **MARK}])
        listing = self.run_queue("list", "--json")
        self.assertEqual(listing.returncode, 0, listing.stderr)
        self.assertEqual([(row["id"], row["override"]) for row in json.loads(listing.stdout)], [("test-1", True)])


if __name__ == "__main__":
    unittest.main()
