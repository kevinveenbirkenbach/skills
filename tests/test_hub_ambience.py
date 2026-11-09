from __future__ import annotations

import json
import subprocess
import unittest

from hub_support import AMBIENCE, STREAMS

SLOTS = [(0, 420, "Morning"), (0, 539, "Morning"), (0, 540, None), (1, 419, None), (5, 480, None), (5, 1380, "Night"), (6, 90, "Night"), (6, 120, None), (4, 1380, None), (6, 1380, None)]
PROBE = """
const A = require(process.argv[1]);
const at = (text) => Date.parse(text);
const pick = (body, keys) => Object.fromEntries(keys.map((key) => [key, body[key]]));
const surfaces = [];
for (const mode of ["light", "dark"]) {
  for (const surface of ["bg", "panel"]) {
    for (const sky of A.SKY.flatMap(([, top, bottom]) => [top, bottom])) {
      const behind = A.mix(A.hex(sky), A.hex(A.THEMES[mode][surface]), A.GLASS);
      surfaces.push({mode, surface, sky, text: A.contrast(A.hex(A.THEMES[mode].text), behind), muted: A.contrast(A.hex(A.THEMES[mode].muted), behind)});
    }
  }
}
const slots = JSON.parse(process.argv[3]).map(([day, minute]) => ({day, minute}));
console.log(JSON.stringify({
  sun: pick(A.sun(at("1992-10-13T00:00:00Z"), 0, 0), ["ra", "dec", "eot"]),
  solstice: A.sun(at("2024-06-20T20:51:00Z"), 0, 0).dec,
  london: A.sun(at("2024-06-21T03:43:00Z"), 51.5074, -0.1278).alt,
  moon: pick(A.moon(at("1992-04-12T00:00:00Z"), 0, 0), ["ra", "dec", "lambda", "beta", "distance", "lit", "limb", "waxing"]),
  full: A.moon(at("2024-04-23T23:49:00Z"), 52.5, 13.4).lit,
  fresh: A.moon(at("2024-04-08T18:21:00Z"), 52.5, 13.4).lit,
  quarter: pick(A.moon(at("2024-04-15T19:13:00Z"), 52.5, 13.4), ["lit", "waxing"]),
  sidereal: [A.sidereal(at("1987-04-10T00:00:00Z")), A.sidereal(at("1987-04-10T19:21:00Z"))],
  stages: [-30, -15, -9, -3, 3, 20].map(A.stage),
  modes: [-10, 3.9, 4, 40].map(A.modeAt),
  black: A.contrast([0, 0, 0], [255, 255, 255]),
  surfaces,
  slot: A.slotOf(new Date(2024, 5, 21, 7, 30)),
  playing: slots.map((slot) => (A.activeStream(JSON.parse(process.argv[2]), slot) || {name: null}).name),
}));
"""


class TestAmbience(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        command = ["node", "-e", PROBE, str(AMBIENCE), json.dumps(STREAMS), json.dumps([slot[:2] for slot in SLOTS])]
        done = subprocess.run(command, capture_output=True, text=True, timeout=60, check=True)
        cls.data = json.loads(done.stdout)

    def test_the_sun_matches_meeus_and_noaa_references(self):
        sun = self.data["sun"]
        self.assertAlmostEqual(sun["ra"], 198.38083, delta=0.01)
        self.assertAlmostEqual(sun["dec"], -7.78507, delta=0.01)
        self.assertAlmostEqual(sun["eot"], 13.71, delta=0.1)
        self.assertAlmostEqual(self.data["solstice"], 23.438, delta=0.01)
        self.assertAlmostEqual(self.data["london"], -0.833, delta=0.3)
        self.assertAlmostEqual(self.data["sidereal"][0], 197.693195, delta=0.001)
        self.assertAlmostEqual(self.data["sidereal"][1], 128.7378734, delta=0.001)

    def test_the_moon_matches_meeus_within_the_low_precision_series(self):
        moon = self.data["moon"]
        for key, expected, delta in (("lambda", 133.162655, 0.5), ("beta", -3.229126, 0.3), ("ra", 134.68847, 0.5), ("dec", 13.768368, 0.3), ("distance", 368409.7, 3000), ("lit", 0.6786, 0.01), ("limb", 285.0, 2.0)):
            with self.subTest(key=key):
                self.assertAlmostEqual(moon[key], expected, delta=delta)
        self.assertTrue(moon["waxing"])
        self.assertGreater(self.data["full"], 0.99)
        self.assertLess(self.data["fresh"], 0.01)
        self.assertAlmostEqual(self.data["quarter"]["lit"], 0.5, delta=0.03)
        self.assertTrue(self.data["quarter"]["waxing"])

    def test_sky_stages_modes_and_text_contrast_hold_in_every_sky(self):
        self.assertEqual(self.data["stages"], ["night", "astronomical", "nautical", "civil", "golden", "day"])
        self.assertEqual(self.data["modes"], ["dark", "dark", "light", "light"])
        self.assertAlmostEqual(self.data["black"], 21.0, places=6)
        self.assertEqual(len(self.data["surfaces"]), 88)
        for row in self.data["surfaces"]:
            with self.subTest(mode=row["mode"], surface=row["surface"], sky=row["sky"]):
                self.assertGreaterEqual(row["text"], 7.0)
                self.assertGreaterEqual(row["muted"], 4.5)

    def test_streams_play_on_their_weekdays_and_hours(self):
        self.assertEqual(self.data["slot"], {"day": 4, "minute": 450})
        self.assertEqual(self.data["playing"], [slot[2] for slot in SLOTS])


if __name__ == "__main__":
    unittest.main()
