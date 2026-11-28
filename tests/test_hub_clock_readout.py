"""Exercise requirement 087: the readout of every analog clock, m:ss on a clock that runs out and HH:MM:SS on a wall clock."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import unittest

from hub_support import HUB

DIAL = HUB / "templates" / "dial.js"
MORNING = 1_795_770_307_250
PROBE = """
const D = require(process.argv[1]);
const morning = Number(process.argv[2]);
const until = 1_000_000;
const count = D.counting(until, 60);
const seconds = D.counting(until, 1);
const at = (left) => (until - left) * 1000;
console.log(JSON.stringify({
  countdown: [0, 0.2, 59, 60, 65, 599.4, 600, 3599, -3].map(D.countdown),
  wall: [D.wall(morning), D.wall(morning - (9 * 3600 + 5 * 60 + 7.25) * 1000), D.wall(morning + (14 * 3600 + 54 * 60 + 52.749) * 1000)],
  counting: [count(at(125.5)), count(at(0)), count(at(-30)), seconds(at(9.5))],
  ticking: [0, 1000, 2000, 3000].map((later) => count(at(125) + later).text),
  walled: D.walled()(morning),
  angle: [D.angle(15, 60), D.angle(0.5, 60), D.angle(60, 60)],
  eased: [D.eased(0), D.eased(0.5), D.eased(1)],
  readout: D.READOUT,
}));
"""


@unittest.skipUnless(shutil.which("node"), "no node")
class TestClockReadout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        done = subprocess.run(["node", "-e", PROBE, str(DIAL), str(MORNING)], capture_output=True, text=True, timeout=60, check=True, env={**os.environ, "TZ": "UTC"})
        cls.data = json.loads(done.stdout)

    def test_a_clock_that_runs_out_reads_the_seconds_left_as_m_ss_rounded_up_and_never_below_zero(self):
        self.assertEqual(self.data["countdown"], ["0:00", "0:01", "0:59", "1:00", "1:05", "10:00", "10:00", "59:59", "0:00"])

    def test_a_wall_clock_reads_the_local_time_of_day_as_hh_mm_ss(self):
        self.assertEqual(self.data["wall"], ["09:05:07", "00:00:00", "23:59:59"])
        self.assertEqual(self.data["walled"], {"at": 7.25, "value": 7, "text": "09:05:07"})

    def test_a_running_countdown_turns_the_hand_by_the_exact_time_left_and_its_readout_drops_one_second_each_second(self):
        self.assertEqual(self.data["counting"], [
            {"at": 125.5 / 60, "value": 3, "text": "2:06"},
            {"at": 0, "value": 0, "text": "0:00"},
            {"at": 0, "value": 0, "text": "0:00"},
            {"at": 9.5, "value": 10, "text": "0:10"},
        ])
        self.assertEqual(self.data["ticking"], ["2:05", "2:04", "2:03", "2:02"])

    def test_the_hand_angle_follows_the_value_and_a_sweep_eases_into_its_place(self):
        self.assertEqual(self.data["angle"], [90, 3, 360])
        self.assertEqual(self.data["eased"], [0, 0.875, 1])
        self.assertGreater(self.data["readout"], 4)


if __name__ == "__main__":
    unittest.main()
