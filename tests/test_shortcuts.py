"""Validate the shortcuts skill table: rows present, sorted, ``soc``-prefixed,
no two adjacent consonants."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL = REPO_ROOT / "skills" / "shortcuts" / "SKILL.md"

ROW_RE = re.compile(r"^\|\s*`(?P<shortcut>[^`]+)`\s*\|")
VOWELS = frozenset("aeiou")


def _has_consonant_cluster(name: str) -> bool:
    prev_consonant = False
    for char in name:
        if not char.isalpha():
            prev_consonant = False
            continue
        is_consonant = char.lower() not in VOWELS
        if is_consonant and prev_consonant:
            return True
        prev_consonant = is_consonant
    return False


class TestShortcuts(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SKILL.is_file(), f"missing {SKILL}")
        self.shortcuts = [
            match.group("shortcut")
            for line in SKILL.read_text(encoding="utf-8").splitlines()
            if (match := ROW_RE.match(line))
        ]

    def test_shortcuts_present(self):
        self.assertTrue(self.shortcuts, "no shortcut rows found in shortcuts skill")

    def test_shortcuts_sorted_ascending(self):
        self.assertEqual(
            self.shortcuts,
            sorted(self.shortcuts),
            f"shortcuts table not sorted; expected {sorted(self.shortcuts)}",
        )

    def test_shortcuts_start_with_so(self):
        bad = [s for s in self.shortcuts if not s.startswith("so")]
        self.assertFalse(bad, f"shortcuts not starting with 'so': {bad}")

    def test_no_consecutive_consonants(self):
        bad = [s for s in self.shortcuts if _has_consonant_cluster(s)]
        self.assertFalse(bad, f"shortcuts with two adjacent consonants: {bad}")


if __name__ == "__main__":
    unittest.main()
