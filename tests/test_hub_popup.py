from __future__ import annotations

import json
import subprocess
import unittest

from hub_support import POPUP

POPUP_PROBE = """
const P = require(process.argv[1]);
let seed = 11;
const next = () => {
  seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
  return seed / 4294967296;
};
const node = (left, top) => ({left, top, width: 20, height: 20});
const wide = {width: 1366, height: 768};
const phone = {width: 390, height: 844};
const random = Array.from({length: 600}, () => {
  const view = {width: 300 + Math.round(next() * 1700), height: 300 + Math.round(next() * 900)};
  const size = {width: Math.min(440, view.width - 2 * P.GAP), height: Math.round(80 + next() * (view.height - 2 * P.GAP - 80))};
  const anchor = {left: Math.round(next() * view.width) - 10, top: Math.round(next() * view.height) - 10, width: 20, height: 20};
  return {view, size, anchor, at: P.place(anchor, size, view)};
});
const nodes = [
  {id: "s1", label: "Skills session"}, {id: "s2", label: "Stage"}, {id: "agent:Stage@/a", label: "Stage"}, {id: "agent:Stage@/b", label: "Stage"},
  {id: "b1", label: "feature/stage-fix"}, {id: "b2", label: "main"}, {id: "b3", label: "main"}, {id: "x", label: "Backstage"},
];
const ids = (list) => list.map((entry) => entry.id);
console.log(JSON.stringify({
  constants: [P.GAP, P.REACH, P.MIN],
  right: P.place(node(100, 300), {width: 440, height: 300}, wide),
  left: P.place(node(1200, 300), {width: 440, height: 300}, wide),
  below: P.place(node(185, 100), {width: 358, height: 300}, phone),
  above: P.place(node(185, 700), {width: 358, height: 300}, phone),
  capped: P.place(node(185, 400), {width: 358, height: 700}, phone),
  covered: P.place(node(185, 180), {width: 358, height: 368}, {width: 390, height: 400}),
  centre: P.place(null, {width: 440, height: 300}, wide),
  random,
  hits: {
    stage: ids(P.hits(nodes, "sta", 8)),
    main: ids(P.hits(nodes, "  MAIN ", 8)),
    blank: P.hits(nodes, "   ", 8),
    limit: ids(P.hits(nodes, "a", 2)),
    none: P.hits(nodes, "zzz", 8),
    same: P.hits(nodes, "stage", 8)[0] === nodes[1],
  },
}));
"""
SLACK = 0.06


class TestPopupModule(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        done = subprocess.run(["node", "-e", POPUP_PROBE, str(POPUP)], capture_output=True, text=True, timeout=60, check=True)
        cls.data = json.loads(done.stdout)
        cls.gap, cls.reach, cls.min = cls.data["constants"]

    def test_the_popup_sits_right_of_the_node_and_the_leader_spans_the_gap_between_them(self):
        self.assertEqual(self.data["right"], {"left": 160, "top": 160, "height": None, "line": {"x1": 120, "y1": 310, "x2": 160, "y2": 310}})
        self.assertEqual(self.data["right"]["line"]["x2"] - self.data["right"]["line"]["x1"], self.reach)

    def test_a_node_near_the_right_edge_gets_the_popup_on_its_left(self):
        self.assertEqual(self.data["left"], {"left": 720, "top": 160, "height": None, "line": {"x1": 1200, "y1": 310, "x2": 1160, "y2": 310}})

    def test_on_a_phone_the_popup_goes_below_or_above_the_node(self):
        self.assertEqual(self.data["below"], {"left": 16, "top": 160, "height": None, "line": {"x1": 195, "y1": 120, "x2": 195, "y2": 160}})
        self.assertEqual(self.data["above"], {"left": 16, "top": 360, "height": None, "line": {"x1": 195, "y1": 700, "x2": 195, "y2": 660}})

    def test_a_popup_too_tall_for_either_side_is_capped_to_the_larger_room_and_keeps_its_leader(self):
        self.assertEqual(self.data["capped"], {"left": 16, "top": 460, "height": 368, "line": {"x1": 195, "y1": 420, "x2": 195, "y2": 460}})

    def test_without_room_the_popup_covers_the_node_and_draws_no_leader(self):
        self.assertEqual(self.data["covered"], {"left": 16, "top": 16, "height": None, "line": None})

    def test_a_popup_without_a_node_is_centred_without_a_leader(self):
        self.assertEqual(self.data["centre"], {"left": 463, "top": 234, "height": None, "line": None})

    def test_every_placement_stays_in_the_viewport_and_every_leader_runs_from_the_node_edge_to_the_popup_edge(self):
        leaders = 0
        for case in self.data["random"]:
            view, size, anchor, at = case["view"], case["size"], case["anchor"], case["at"]
            height = size["height"] if at["height"] is None else at["height"]
            box = (at["left"], at["top"], at["left"] + size["width"], at["top"] + height)
            with self.subTest(case=case):
                self.assertGreaterEqual(min(box[0], box[1]), self.gap - SLACK)
                self.assertLessEqual(box[2], view["width"] - self.gap + SLACK)
                self.assertLessEqual(box[3], view["height"] - self.gap + SLACK)
                if at["height"] is not None:
                    self.assertGreaterEqual(at["height"], self.min - SLACK)
                    self.assertLess(at["height"], size["height"])
                rect = (anchor["left"], anchor["top"], anchor["left"] + anchor["width"], anchor["top"] + anchor["height"])
                line = at["line"]
                if line is None:
                    self.assertTrue(box[0] <= rect[2] + SLACK and rect[0] <= box[2] + SLACK and box[1] <= rect[3] + SLACK and rect[1] <= box[3] + SLACK, "no leader although the popup misses the node")
                    continue
                leaders += 1
                self.assertTrue(any(abs(line["x2"] - edge) <= SLACK for edge in (box[0], box[2])) or any(abs(line["y2"] - edge) <= SLACK for edge in (box[1], box[3])))
                self.assertTrue(any(abs(line["x1"] - edge) <= SLACK for edge in (rect[0], rect[2])) or any(abs(line["y1"] - edge) <= SLACK for edge in (rect[1], rect[3])))
                self.assertTrue(rect[0] - SLACK <= line["x1"] <= rect[2] + SLACK and rect[1] - SLACK <= line["y1"] <= rect[3] + SLACK)
        self.assertGreater(leaders, len(self.data["random"]) * 0.9)

    def test_search_hits_are_one_per_label_prefix_first_case_insensitive_and_limited(self):
        hits = self.data["hits"]
        self.assertEqual(hits["stage"], ["s2", "b1", "x"])
        self.assertEqual(hits["main"], ["b2"])
        self.assertEqual(hits["limit"], ["s2", "b1"])
        self.assertTrue(hits["same"])

    def test_a_blank_or_unknown_query_finds_nothing(self):
        self.assertEqual((self.data["hits"]["blank"], self.data["hits"]["none"]), ([], []))


if __name__ == "__main__":
    unittest.main()
