"""Exercise kvb-check-ansible's log parsing: timestamps, sources, line ranges and the task boundaries."""

from __future__ import annotations

import calendar
import unittest

from ansible_support import MIDNIGHT_LOG, PROFILE_LOG, LogCase, ansible_log


class TestStamps(unittest.TestCase):
    def test_fraction_digits_zone_and_missing_z(self):
        base = calendar.timegm((2026, 11, 7, 6, 45, 47))
        for text, fraction in (
            ("2026-11-07T06:45:47.1234567Z x", 0.1234567),
            ("2026-11-07T06:45:47.1Z x", 0.1),
            ("2026-11-07T06:45:47Z x", 0.0),
            ("2026-11-07T06:45:47.123456789 x", 0.123456789),
            ("2026-11-07T07:45:47.5+01:00 x", 0.5),
            ("2026-11-07T01:45:47.5-0500 x", 0.5),
            ("2026-11-07 06:45:47,25 x", 0.25),
        ):
            with self.subTest(text=text):
                stamp, content = ansible_log.split_stamp(text)
                self.assertAlmostEqual(stamp, base + fraction, places=5)
                self.assertEqual(content, "x")
        self.assertEqual(ansible_log.split_stamp("TASK [x] ***"), (None, "TASK [x] ***"))


class TestWallParsing(LogCase):
    def test_line_range_drops_the_task_its_end_cuts_off(self):
        self.assertEqual(
            self.lines("gaps", "--log", str(self.wall), "--from", "4", "--to", "13"),
            [
                "1.5\t1\tsetup : install",
                "0.8\t1\tsetup : flush",
                "0.3\t1\tsetup : include",
                "0.2\t1\tsetup : check",
                "2.8\t4\tTOTAL",
            ],
        )

    def test_midnight_bom_and_recap_close_the_last_task(self):
        midnight = self.write("midnight.log", MIDNIGHT_LOG)
        self.assertEqual(self.report("gaps", "--log", str(midnight))["rows"], [{"name": "late", "sum": 0.75, "count": 1}])


class TestProfileParsing(LogCase):
    def test_durations_pair_each_header_with_the_next_elapsed_line(self):
        self.assertEqual(
            self.lines("durations", "--log", str(self.profile)),
            [
                "65.0\t2\tsetup : install",
                "2.0\t1\tGathering Facts",
                "0.4\t1\tsetup : restart",
                "0.1\t1\tsetup : check",
                "67.5\t5\tTOTAL",
            ],
        )

    def test_kinds_fall_back_to_the_profile_source(self):
        self.assertEqual(
            self.lines("kinds", "--log", str(self.profile)),
            [
                "kind\tcount\tsum\tmean\t<0.25\t<0.5\t<1\t<2\t>=2",
                "included\t1\t61.5\t61.5000\t0\t0\t0\t0\t1",
                "ran\t3\t5.9\t1.9667\t0\t1\t0\t0\t2",
                "skipped\t1\t0.1\t0.1000\t1\t0\t0\t0\t0",
            ],
        )
        self.assertEqual(self.report("kinds", "--log", str(self.profile))["source"], "profile")

    def test_profile_source_reads_a_timestamped_log_too(self):
        stamped = self.write("stamped.log", "".join(f"2026-11-07T06:45:40.1234Z {line}\n" for line in PROFILE_LOG.splitlines()))
        self.assertEqual(
            self.lines("kind", "--log", str(stamped), "--source", "profile", "--kind", "skipped"),
            ["0.1\t1\tsetup : check", "0.1\t1\tTOTAL"],
        )


class TestUnmeasurable(LogCase):
    def assertFails(self, needle: str, *args: str):
        result = self.run_script(*args)
        self.assertEqual((result.returncode, result.stdout), (2, ""))
        self.assertIn(needle, result.stderr)

    def test_wrong_source_or_range_exits_2(self):
        self.assertFails("ISO timestamp", "gaps", "--log", str(self.profile))
        self.assertFails("ISO timestamp", "kinds", "--log", str(self.profile), "--source", "wall")
        self.assertFails("profile_tasks", "durations", "--log", str(self.wall))
        self.assertFails("no task closed", "gaps", "--log", str(self.wall), "--from", "2", "--to", "2")
        self.assertFails("No such file", "gaps", "--log", str(self.base / "missing.log"))


if __name__ == "__main__":
    unittest.main()
