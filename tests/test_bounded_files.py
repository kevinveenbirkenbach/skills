"""Exercise requirement 061: the council files on hot paths stay small and are read only when they changed."""

from __future__ import annotations

import contextlib
import io
import json
import os
import signal
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from test_council_root import QUEUE, WATCH, load, rows
from test_queue_cleanup import CLEANUP, FakeClock

DAY = 86400
CFG = {"load_limits": {"cpu_percent": 90, "mem_percent": 90}}


def clock(wall: float) -> FakeClock:
    return FakeClock(wall, lambda _seconds: None)


class Council(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name).resolve()
        self.root = self.base / "council"
        self.root.mkdir(mode=0o700)
        self.kept = self.base / "state" / "agents-council"
        self.home = self.base / "home"
        (self.home / ".claude" / "sessions").mkdir(parents=True)
        env = mock.patch.dict(os.environ, {
            "AGENTS_COUNCIL_ROOT": str(self.root), "XDG_STATE_HOME": str(self.base / "state"), "HOME": str(self.home),
            "AGENTS_COUNCIL_CONFIG": str(self.base / "config.json"),
        })
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("CLAUDE_CODE_SESSION_ID", None)

    def watch(self):
        return load(WATCH, f"bounded_watch_{id(self)}")


class TestAlerts(Council):
    def test_ten_prompts_with_an_unchanged_alerts_file_read_it_once(self):
        watch = self.watch()
        watch.alert("warn", "RESOURCE WARN: low", False)
        with mock.patch.object(watch, "history_rows", wraps=watch.history_rows) as parsed:
            shown = [watch.unseen_alerts("s1") for _ in range(10)]
        self.assertEqual(shown, [["RESOURCE WARN: low"]] + [[]] * 9)
        self.assertEqual(parsed.call_count, 1)
        watch.alert("stop", "RESOURCE STOP: lower", False)
        self.assertEqual(watch.unseen_alerts("s1"), ["RESOURCE STOP: lower"])

    def test_an_older_bare_seen_mark_still_counts(self):
        watch = self.watch()
        watch.alert("warn", "seen before", False)
        newest = json.loads(watch.ALERTS.read_text(encoding="utf-8").splitlines()[-1])["id"]
        (self.root / "seen").mkdir()
        (self.root / "seen" / "s1").write_text(str(newest), encoding="utf-8")
        self.assertEqual(watch.unseen_alerts("s1"), [])

    def test_an_append_drops_the_rows_past_the_ttl(self):
        watch = self.watch()
        now = time.time_ns()
        old = {"id": now - (watch.ALERT_TTL + 1) * 10**9, "stage": "warn", "text": "old", "chair": False}
        young = {"id": now - 10**9, "stage": "warn", "text": "young", "chair": False}
        watch.ALERTS.write_text(f"{json.dumps(old)}\nnot json\n{json.dumps(young)}\n", encoding="utf-8")
        watch.alert("stop", "new", False)
        texts = [json.loads(line)["text"] for line in watch.ALERTS.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(texts, ["young", "new"])

    def test_a_recovered_line_reaches_only_the_chair(self):
        watch = self.watch()
        (self.root / "chair").mkdir()
        (self.root / "chair" / "claim.json").write_text(json.dumps({"office": "chair", "session": "s0"}), encoding="utf-8")
        watch.alert("ok", "RESOURCE OK: recovered", True)
        watch.alert("warn", "RESOURCE WARN: low", False)
        self.assertEqual(watch.unseen_alerts("s1"), ["RESOURCE WARN: low"])
        self.assertEqual(watch.unseen_alerts("s0"), ["RESOURCE OK: recovered", "RESOURCE WARN: low"])
        self.assertEqual(watch.unseen_alerts("s1"), [])

    def test_a_memory_value_flapping_around_its_threshold_alerts_once_per_stage_change(self):
        watch = self.watch()
        cfg = {"thresholds_gb": {"warn": -1, "stop": -2, "critical": -3}, "projection_minutes": 30, "cache_interval_seconds": DAY}
        measured = ["warn", "ok", "warn", "ok", "warn", "ok", "ok", "ok"]
        state = {"caches_checked": time.time()}
        with (
            mock.patch.object(watch, "disk", return_value=(100.0, 200.0)),
            mock.patch.object(watch, "memory", return_value={}),
            mock.patch.object(watch, "memory_stage", side_effect=measured),
            mock.patch.object(watch, "act_memory") as acted,
        ):
            for step in range(len(measured)):
                watch.measure_and_act(cfg, state, time.time() + step, None)
        self.assertEqual([(call.args[1], call.args[2]) for call in acted.call_args_list], [("warn", "ok"), ("ok", "warn")])
        self.assertEqual(state["memory_stage"], "ok")

    def test_a_higher_stage_is_entered_at_once_and_a_lower_one_after_two_samples(self):
        settle = self.watch().settled_memory
        self.assertEqual(settle("ok", "stop", 0), ("stop", 0))
        self.assertEqual(settle("stop", "warn", 0), ("stop", 1))
        self.assertEqual(settle("stop", "stop", 1), ("stop", 0))
        self.assertEqual(settle("stop", "ok", 1), ("ok", 0))


class TestMirror(Council):
    def setUp(self):
        super().setUp()
        self.mirror = self.watch()
        self.source = self.mirror.ACCEPTED
        self.target = self.mirror.KEPT_ACCEPTED
        self.stamp = time.time_ns()

    def keep(self) -> list[str]:
        self.mirror.keep_rows(self.source, self.target)
        return rows(self.target)

    def touch(self) -> None:
        self.stamp += 10**6
        os.utime(self.source, ns=(self.stamp, self.stamp))

    def write(self, text: str) -> None:
        with self.source.open("a", encoding="utf-8") as source:
            source.write(text)
        self.touch()

    def add(self, *ids: str) -> None:
        self.write("".join(json.dumps({"id": row_id}) + "\n" for row_id in ids))

    def test_a_grown_source_mirrors_only_its_new_rows(self):
        self.add("r1", "r2")
        self.assertEqual(self.keep(), ["r1", "r2"])
        self.target.write_text(json.dumps({"id": "r2"}) + "\n", encoding="utf-8")
        self.add("r3")
        self.assertEqual(self.keep(), ["r2", "r3"])

    def test_a_rewritten_or_shrunk_source_merges_every_missing_row(self):
        self.add("r1", "r2")
        self.keep()
        fresh = self.base / "fresh.jsonl"
        fresh.write_text(json.dumps({"id": "r1"}) + "\n" + json.dumps({"id": "r4"}) + "\n", encoding="utf-8")
        fresh.replace(self.source)
        self.touch()
        self.assertEqual(self.keep(), ["r1", "r2", "r4"])
        self.source.write_text(json.dumps({"id": "r5"}) + "\n", encoding="utf-8")
        self.touch()
        self.assertEqual(self.keep(), ["r1", "r2", "r4", "r5"])

    def test_a_fresh_copy_sharing_the_source_mtime_still_mirrors_every_row(self):
        self.add("r1", "r2")
        self.target.parent.mkdir(parents=True, exist_ok=True)
        self.target.write_text("", encoding="utf-8")
        os.utime(self.target, ns=(self.stamp, self.stamp))
        self.assertEqual(self.keep(), ["r1", "r2"])

    def test_a_row_appended_within_the_same_mtime_tick_mirrors_next_round(self):
        self.add("r1")
        self.assertEqual(self.keep(), ["r1"])
        with self.source.open("a", encoding="utf-8") as source:
            source.write(json.dumps({"id": "r2"}) + "\n")
        os.utime(self.source, ns=(self.stamp, self.stamp))
        self.assertEqual(self.keep(), ["r1", "r2"])

    def test_a_line_still_being_written_waits_for_the_next_mirror(self):
        self.add("r1")
        self.write('{"id": "r2"')
        self.assertEqual(self.keep(), ["r1"])
        self.write("}\n")
        self.assertEqual(self.keep(), ["r1", "r2"])


class TestTrim(Council):
    def test_a_cleanup_round_drops_the_history_rows_over_30_days_old_and_keeps_the_rest_byte_for_byte(self):
        cleanup = load(CLEANUP, f"bounded_cleanup_{id(self)}")
        now = float(int(time.time()))
        old = json.dumps({"id": "old", "end": now - 31 * DAY}) + "\n"
        young = '{"end": %s,  "id": "young"}\n' % (now - DAY)
        kept = young + "not json\n"
        self.kept.mkdir(parents=True, mode=0o700)
        for path in (cleanup.watch.HISTORY, cleanup.watch.KEPT_HISTORY):
            path.write_text(old + young + "not json\n" + old, encoding="utf-8")
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = cleanup.run_round(900, clock(now))
        self.assertEqual(code, 0)
        self.assertIn("dropped 4 queue history rows that ended over 30 days ago", out.getvalue())
        for path in (cleanup.watch.HISTORY, cleanup.watch.KEPT_HISTORY):
            with self.subTest(path=path.parent.name):
                self.assertEqual(path.read_text(encoding="utf-8"), kept)
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            cleanup.run_round(900, clock(now))
        self.assertNotIn("dropped", out.getvalue())


class TestQueue(Council):
    def setUp(self):
        super().setUp()
        self.queue = load(QUEUE, f"bounded_queue_{id(self)}")

    def test_learned_reads_the_histories_once_until_one_changes(self):
        queue = self.queue
        now = time.time()
        row = {"id": "j1", "kind": "test", "signature": "make test", "workdir": "/w", "start": now - 60, "end": now,
               "minutes": 1, "disk_gb": 0, "mem_before": 10, "mem_max": 20, "cpu_before": 10, "cpu_max": 20}
        queue.watch.HISTORY.write_text(json.dumps(row) + "\n", encoding="utf-8")
        with mock.patch.object(queue.history, "read", wraps=queue.history.read) as reads:
            first = queue.learned(CFG, now)
            self.assertIs(queue.learned(CFG, now + 20), first)
            self.assertEqual(reads.call_count, 1)
            with queue.watch.HISTORY.open("a", encoding="utf-8") as history:
                history.write(json.dumps({**row, "id": "j2"}) + "\n")
            self.assertEqual(queue.learned(CFG, now)[0][("test", "make test")]["runs"], 2)
            queue.learned({**CFG, "light_kinds": ["test"]}, now)
            self.assertEqual(reads.call_count, 3)

    def test_a_waiting_hold_pauses_a_whole_poll_and_wakes_at_once_on_a_signal(self):
        queue = self.queue
        wake, alarm = os.pipe()
        self.addCleanup(os.close, wake)
        self.addCleanup(os.close, alarm)
        os.set_blocking(alarm, False)
        previous = signal.set_wakeup_fd(alarm, warn_on_full_buffer=False)
        self.addCleanup(signal.set_wakeup_fd, previous)
        caught: list[int] = []
        handler = signal.signal(signal.SIGUSR1, lambda signum, _frame: caught.append(signum))
        self.addCleanup(signal.signal, signal.SIGUSR1, handler)
        with mock.patch.object(queue, "POLL_SECONDS", 0.5):
            start = time.monotonic()
            queue.pause(wake)
            quiet = time.monotonic() - start
        with mock.patch.object(queue, "POLL_SECONDS", 30):
            timer = threading.Timer(0.1, os.kill, (os.getpid(), signal.SIGUSR1))
            timer.start()
            self.addCleanup(timer.cancel)
            start = time.monotonic()
            queue.pause(wake)
            woken = time.monotonic() - start
        self.assertGreaterEqual(quiet, 0.5)
        self.assertLess(woken, 5)
        self.assertEqual(caught, [signal.SIGUSR1])


if __name__ == "__main__":
    unittest.main()
