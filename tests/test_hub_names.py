from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import hub_support  # noqa: F401
from kvb_orchestrator import names


class TestRenameOnce(unittest.TestCase):
    def test_two_state_builds_with_the_same_claims_add_no_second_rename(self):
        with tempfile.TemporaryDirectory() as folder:
            book = names.Names(Path(folder) / "names.json")
            claims = [("s1", "Stage", 100.0, "claim"), ("s1", "i18n 2.0", 200.0, "claim"), ("s2", "Main", 50.0, "claim")]
            counts = []
            for build in (1000.0, 2000.0):
                book.observe(claims, build)
                counts.append(len(names.Directory(book.listed()).renames(0, 3000)))
            self.assertEqual(counts, [0, 0])
            for build in (3000.0, 4000.0):
                book.observe([*claims, ("s1", "Skills", 300.0, "title")], build)
            self.assertEqual([row["title"] for row in names.Directory(book.listed()).renames(0, 5000)], ["i18n 2.0 is now called Skills"])

    def test_a_name_pair_shows_once_per_session(self):
        entries = [{"session": "s1", "name": name, "first_seen": ts, "source": "claim"} for name, ts in (("A", 1), ("B", 2), ("A", 3), ("B", 4))]
        self.assertEqual([row["title"] for row in names.Directory(entries).renames(0, 10)], ["A is now called B", "B is now called A"])


def flips(count: int) -> list[dict]:
    return [{"session": "s1", "name": "AB"[index % 2], "first_seen": float(index), "source": "claim"} for index in range(count)]


class TestDirectoryLookups(unittest.TestCase):
    def test_at_names_the_last_entry_seen_at_or_before_the_moment_and_the_first_one_before_any(self):
        directory = names.Directory(flips(6))
        scanned = flips(6)
        for ts in (-1.0, 0.0, 0.5, 1.0, 2.9, 3.0, 5.0, 99.0):
            valid = [entry for entry in scanned if entry["first_seen"] <= ts]
            self.assertEqual(directory.at("s1", ts), (valid[-1] if valid else scanned[0])["name"], ts)
        self.assertEqual(directory.at("s9", 1.0), "")

    def test_a_windowed_timeline_keeps_the_birth_and_every_name_from_the_last_one_before_the_window(self):
        directory = names.Directory(flips(10))
        self.assertEqual([entry["since"] for entry in directory.timeline("s1", 6.5)], [0.0, 6.0, 7.0, 8.0, 9.0])
        self.assertEqual(directory.timeline("s1", -5.0), directory.timeline("s1"))
        self.assertEqual(directory.timeline("s1", 0.0), directory.timeline("s1"))
        self.assertEqual(directory.timeline("s9", 3.0), [])

    def test_the_directory_is_rebuilt_only_after_a_new_entry(self):
        with tempfile.TemporaryDirectory() as folder:
            book = names.Names(Path(folder) / "names.json")
            book.observe([("s1", "A", 1.0, "claim")], 10.0)
            first = book.directory()
            book.observe([("s1", "A", 2.0, "claim")], 20.0)
            self.assertIs(book.directory(), first)
            book.observe([("s1", "B", 3.0, "claim")], 30.0)
            self.assertIsNot(book.directory(), first)
            self.assertEqual(book.directory().now("s1"), "B")


if __name__ == "__main__":
    unittest.main()
