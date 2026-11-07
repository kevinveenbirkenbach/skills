"""Exercise kvb-check-ansible's reporting subcommands: name, kind and occurrence tables, JSON and usage errors."""

from __future__ import annotations

import unittest

from ansible_support import WALL_KINDS, LogCase, ansible_tables


class TestNameTables(LogCase):
    def test_gaps_sum_per_name_biggest_first_with_total(self):
        self.assertEqual(
            self.lines("gaps", "--log", str(self.wall)),
            [
                "5.0\t2\tsetup : install",
                "1.2\t1\tsetup : restart",
                "0.8\t1\tsetup : flush",
                "0.3\t1\tsetup : include",
                "0.2\t1\tsetup : check",
                "7.5\t6\tTOTAL",
            ],
        )

    def test_gaps_json_and_top_keep_the_full_total(self):
        self.assertEqual(
            self.report("gaps", "--log", str(self.wall), "--top", "2"),
            {
                "source": "wall",
                "rows": [
                    {"name": "setup : install", "sum": 5.0, "count": 2},
                    {"name": "setup : restart", "sum": 1.2, "count": 1},
                ],
                "total": {"sum": 7.5, "count": 6},
            },
        )

    def test_kind_sums_one_kind_per_name(self):
        self.assertEqual(
            self.lines("kind", "--log", str(self.wall), "--kind", "ran"),
            ["5.0\t2\tsetup : install", "1.2\t1\tsetup : restart", "6.2\t3\tTOTAL"],
        )
        self.assertEqual(self.lines("kind", "--log", str(self.wall), "--kind", "other"), ["0.8\t1\tsetup : flush", "0.8\t1\tTOTAL"])


class TestKindTable(LogCase):
    def test_kinds_detect_ran_before_skipped_and_fill_the_buckets(self):
        self.assertEqual(self.lines("kinds", "--log", str(self.wall)), WALL_KINDS)
        found = self.report("kinds", "--log", str(self.wall))
        self.assertEqual(found["source"], "wall")
        self.assertEqual(
            found["kinds"][0],
            {"kind": "ran", "count": 3, "sum": 6.2, "mean": 2.0667,
             "buckets": {"<0.25": 0, "<0.5": 0, "<1": 0, "<2": 2, ">=2": 1}},
        )

    def test_bucket_edges(self):
        for seconds, label in ((0.0, "<0.25"), (0.2499, "<0.25"), (0.25, "<0.5"), (0.5, "<1"), (1.0, "<2"), (1.999, "<2"), (2.0, ">=2")):
            with self.subTest(seconds=seconds):
                self.assertEqual(ansible_tables.bucket(seconds), label)


class TestOccurrences(LogCase):
    def test_task_lists_every_occurrence_of_the_needle(self):
        self.assertEqual(
            self.lines("task", "--log", str(self.wall), "--needle", "install"),
            ["2\t3.500\tran\tsetup : install", "6\t1.500\tran\tsetup : install"],
        )
        found = self.report("task", "--log", str(self.wall), "--needle", "install", "--top", "1")
        self.assertEqual(
            found,
            {
                "source": "wall",
                "needle": "install",
                "count": 2,
                "sum": 5.0,
                "occurrences": [{"line": 2, "seconds": 3.5, "kind": "ran", "name": "setup : install"}],
            },
        )


class TestUsage(LogCase):
    def test_usage_errors_exit_2(self):
        for args in (
            ("gaps",),
            ("gaps", "--log", str(self.wall), "--from", "5", "--to", "4"),
            ("gaps", "--log", str(self.wall), "--top", "0"),
            ("kind", "--log", str(self.wall), "--kind", "slow"),
            ("task", "--log", str(self.wall)),
            ("profile-report", "--dir", str(self.base)),
            ("bench-carrier", "--kb", "0", "--out", str(self.base / "c.json")),
        ):
            with self.subTest(args=args):
                self.assertEqual(self.run_script(*args).returncode, 2)


if __name__ == "__main__":
    unittest.main()
