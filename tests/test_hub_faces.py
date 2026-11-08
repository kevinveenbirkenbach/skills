from __future__ import annotations

import json
import math
import re
import subprocess
import unittest
from collections import Counter

from hub_support import FACES

FACES_PROBE = """
const F = require(process.argv[1]);
let seed = 7;
const hex = (digits) => Array.from({length: digits}, () => {
  seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
  return (seed >>> 28).toString(16);
}).join("");
const ids = Array.from({length: 5000}, () => `${hex(8)}-${hex(4)}-${hex(4)}-${hex(4)}-${hex(12)}`);
const fixed = ["s1", "s2", "name:Stage", "Operator", "", "名前"];
console.log(JSON.stringify({
  size: F.SIZE,
  counts: F.COUNTS,
  combinations: F.COMBINATIONS,
  picks: ids.map((id) => F.of(id).pick),
  again: ids.slice(0, 200).every((id) => JSON.stringify(F.of(id)) === JSON.stringify(F.of(id))),
  fixed: fixed.map((id) => F.of(id)),
  parts: ids.slice(0, 400).map((id) => F.of(id).parts),
}));
"""
ATTRIBUTES = ["shape", "colour", "eyes", "brows", "mouth", "hair", "accessory"]
TAGS = {"ellipse", "rect", "path"}
COLOUR = re.compile(r"^#[0-9a-f]{3}(?:[0-9a-f]{3})?$")


def probe() -> dict:
    done = subprocess.run(["node", "-e", FACES_PROBE, str(FACES)], capture_output=True, text=True, timeout=60, check=True)
    return json.loads(done.stdout)


class TestFacesModule(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = probe()
        cls.rerun = probe()

    def test_seven_independent_attributes_multiply_to_at_least_1000_combinations(self):
        counts = self.data["counts"]
        self.assertEqual(list(counts), ATTRIBUTES)
        self.assertTrue(all(count >= 2 for count in counts.values()), counts)
        self.assertEqual(self.data["combinations"], math.prod(counts.values()))
        self.assertGreaterEqual(self.data["combinations"], 1000)

    def test_many_ids_reach_at_least_1000_distinct_faces(self):
        distinct = {tuple(pick[name] for name in ATTRIBUTES) for pick in self.data["picks"]}
        self.assertGreaterEqual(len(distinct), 1000)
        self.assertGreater(len(distinct), len(self.data["picks"]) * 0.9)

    def test_the_same_id_gets_the_same_face_in_every_call_and_every_run(self):
        self.assertTrue(self.data["again"])
        self.assertEqual(self.data["fixed"], self.rerun["fixed"])
        self.assertEqual(self.data["picks"], self.rerun["picks"])
        self.assertEqual(len({json.dumps(face["pick"]) for face in self.data["fixed"]}), len(self.data["fixed"]))

    def test_different_ids_spread_evenly_over_every_variant_of_every_attribute(self):
        total = len(self.data["picks"])
        for name, count in self.data["counts"].items():
            seen = Counter(pick[name] for pick in self.data["picks"])
            with self.subTest(attribute=name):
                self.assertEqual(sorted(seen), list(range(count)))
                for variant, hits in seen.items():
                    self.assertTrue(0.6 < hits * count / total < 1.4, (variant, hits))

    def test_the_svg_description_has_a_coloured_head_one_mouth_and_no_missing_values(self):
        for parts in [*self.data["parts"], *(face["parts"] for face in self.data["fixed"])]:
            with self.subTest(parts=parts[0]):
                self.assertEqual({tag for tag, _ in parts} - TAGS, set())
                self.assertRegex(parts[0][1]["fill"], COLOUR)
                self.assertEqual([attrs.get("class") for _, attrs in parts].count("mouth"), 1)
                for _, attrs in parts:
                    for key, value in attrs.items():
                        if isinstance(value, str):
                            self.assertTrue(value and "undefined" not in value and "NaN" not in value, (key, value))
                        else:
                            self.assertIsInstance(value, (int, float), (key, value))
                            self.assertTrue(math.isfinite(value) and -1 <= value <= self.data["size"] + 1, (key, value))

    def test_faces_draw_no_circle_because_graph_node_styles_target_every_circle_in_a_node(self):
        tags = {tag for parts in self.data["parts"] for tag, _ in parts}
        self.assertNotIn("circle", tags)


if __name__ == "__main__":
    unittest.main()
