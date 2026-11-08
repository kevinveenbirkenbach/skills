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


if __name__ == "__main__":
    unittest.main()
