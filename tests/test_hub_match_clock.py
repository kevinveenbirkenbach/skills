from __future__ import annotations

import json
import shutil
import subprocess
import unittest

from hub_support import HUB

CLOCK = HUB / "templates" / "matchclock.js"
PROBE = """
const C = require(process.argv[1]);
const start = 1_000_000;
const clicked = start + 700;
console.log(JSON.stringify({
  ends: [C.MIN, C.MAX, C.PAGE, C.SECOND],
  next: [C.next(start, 2), C.next(start, 10), C.next(start, 60)],
  wait: [C.wait(start, start, 2), C.wait(start + 1500, start, 2), C.wait(start + 2000, start, 2), C.wait(start + 9000, start, 2)],
  due: [C.due(start + 1999, start, 2), C.due(start + 2000, start, 2), C.due(start + 5000, start, 2)],
  restart: {before: C.wait(clicked, start, 2), after: C.wait(clicked, clicked, 2), next: C.next(clicked, 2)},
  bounded: [0, 1, 2, 10.4, 10.6, 60, 61, -5].map(C.bounded),
  clamped: [C.next(start, 0), C.next(start, 600)],
}));
"""


@unittest.skipUnless(shutil.which("node"), "no node")
class TestMatchClock(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        done = subprocess.run(["node", "-e", PROBE, str(CLOCK)], capture_output=True, text=True, timeout=60, check=True)
        cls.data = json.loads(done.stdout)

    def test_the_next_fetch_is_due_one_interval_after_the_last_fetch_started(self):
        self.assertEqual(self.data["ends"], [1, 60, 5, 1000])
        self.assertEqual(self.data["next"], [1_002_000, 1_010_000, 1_060_000])
        self.assertEqual(self.data["wait"], [2000, 500, 0, 0])
        self.assertEqual(self.data["due"], [False, True, True])

    def test_a_click_fetches_at_once_and_the_cycle_restarts_from_the_click(self):
        self.assertEqual(self.data["restart"], {"before": 1300, "after": 2000, "next": 1_002_700})

    def test_the_interval_is_held_to_whole_seconds_from_1_to_60(self):
        self.assertEqual(self.data["bounded"], [1, 1, 2, 10, 11, 60, 60, 1])
        self.assertEqual(self.data["clamped"], [1_001_000, 1_060_000])


if __name__ == "__main__":
    unittest.main()
