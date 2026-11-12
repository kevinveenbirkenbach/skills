from __future__ import annotations

import json
import re
import subprocess
import unittest

from hub_case import HubCase
from hub_support import HUB, signing

ANCESTRY = HUB / "templates" / "ancestry.js"
PAGE = HUB / "templates" / "page-ancestry.js"
STYLE = HUB / "templates" / "style-ancestry.css"
REPO = "/home/op/Repositories/demo"
# Param: argv[1] is ancestry.js; prints the layouts, gate marks and argv the page builds.
PROBE = """
const A = require(process.argv[1]);
const node = (id) => ({id, label: id});
const shape = (plan) => ({
  rows: plan.nodes.map((entry) => [entry.id, entry.generation]),
  ys: Object.fromEntries(plan.nodes.map((entry) => [entry.id, entry.y])),
  xs: Object.fromEntries(plan.nodes.map((entry) => [entry.id, entry.x])),
  links: plan.links.map((link) => [link.parent, link.child, link.derived, link.y1 < link.y2]),
  size: [plan.width, plan.height],
});
const family = shape(A.layout(["main", "feature/a", "feature/b", "feature/ab", "lonely"].map(node), [
  {child: "feature/a", parent: "main", source: "recorded"},
  {child: "feature/b", parent: "main", source: "derived"},
  {child: "feature/ab", parent: "feature/a", source: "operator"},
  {child: "feature/ab", parent: "feature/b", source: "derived"},
  {child: "ghost", parent: "main", source: "recorded"},
]));
const looped = shape(A.layout(["x", "y", "z"].map(node), [{child: "x", parent: "y"}, {child: "y", parent: "x"}, {child: "z", parent: "z"}]));
const chain = shape(A.layout(["main", "mid", "leaf"].map(node), [{child: "leaf", parent: "main"}, {child: "leaf", parent: "mid"}, {child: "mid", parent: "main"}]));
const roots = Array.from({length: 20}, (_, index) => `b${String(index).padStart(2, "0")}`);
const wide = shape(A.layout([...roots, "child"].map(node), [{child: "child", parent: "b00"}]));
const shown = {resolved: {commit: {level: "test", source: "feature/a"}, merge: {level: "quality-high", source: "main"}, push: {level: "none", source: null}, pr: {level: "e2e", source: "feature/a"}}, rules: {commit: "test", pr: "e2e"}};
console.log(JSON.stringify({
  family, looped, chain, wide, spacing: A.SPACING,
  marks: A.gateMarks("feature/a", shown),
  bare: A.gateMarks("lonely", null),
  cycle: [null, "none", "quick", "test", "quality-high", "e2e"].map(A.nextRule),
  argv: [A.ruleArgv("/r", "b", "push", "test"), A.ruleArgv("/r", "b", "push", null), A.parentArgv("/r", "b", "p", false), A.parentArgv("/r", "b", "p", true)],
  icons: A.LEVEL_ICONS,
}));
"""


class TestAncestryLayout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        done = subprocess.run(["node", "-e", PROBE, str(ANCESTRY)], capture_output=True, text=True, timeout=60, check=True)
        cls.data = json.loads(done.stdout)

    def test_generations_run_top_down_and_a_node_with_several_parents_sits_below_the_deepest(self):
        family = self.data["family"]
        self.assertEqual(family["rows"], [["main", 0], ["feature/a", 1], ["feature/b", 1], ["feature/ab", 2], ["lonely", 0]])
        self.assertLess(family["ys"]["main"], family["ys"]["feature/a"])
        self.assertLess(family["ys"]["feature/a"], family["ys"]["feature/ab"])
        self.assertEqual(family["ys"]["feature/a"], family["ys"]["feature/b"])
        self.assertEqual(self.data["chain"]["rows"], [["main", 0], ["mid", 1], ["leaf", 2]])

    def test_every_parent_edge_is_drawn_downwards_and_only_derived_ones_are_marked_dashed(self):
        self.assertEqual(self.data["family"]["links"], [
            ["main", "feature/a", False, True],
            ["main", "feature/b", True, True],
            ["feature/a", "feature/ab", False, True],
            ["feature/b", "feature/ab", True, True],
        ])

    def test_a_child_sits_between_its_parents_and_unknown_or_looping_edges_do_not_break_the_layout(self):
        xs = self.data["family"]["xs"]
        self.assertTrue(min(xs["feature/a"], xs["feature/b"]) <= xs["feature/ab"] <= max(xs["feature/a"], xs["feature/b"]))
        looped = self.data["looped"]
        self.assertEqual(sorted(generation for _, generation in looped["rows"]), [0, 0, 1])
        self.assertEqual([link[:2] for link in looped["links"] if link[0] == link[1]], [])

    def test_a_wide_generation_wraps_into_bands_and_the_next_generation_starts_below_them(self):
        wide, spacing = self.data["wide"], self.data["spacing"]
        self.assertEqual(wide["size"], [spacing["wrap"] * spacing["column"], 4 * spacing["row"]])
        roots = [name for name, generation in wide["rows"] if generation == 0]
        self.assertEqual(len(roots), 20)
        self.assertEqual(len({(wide["xs"][name], wide["ys"][name]) for name in roots}), 20)
        self.assertEqual(sorted({wide["ys"][name] for name in roots}), [spacing["row"] * band + spacing["row"] / 2 for band in range(3)])
        self.assertEqual(wide["ys"]["child"], 3.5 * spacing["row"])
        self.assertTrue(all(0 < x < wide["size"][0] for x in wide["xs"].values()))


class TestGateMarks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        done = subprocess.run(["node", "-e", PROBE, str(ANCESTRY)], capture_output=True, text=True, timeout=60, check=True)
        cls.data = json.loads(done.stdout)

    def test_each_action_shows_its_resolved_level_with_own_rules_solid_and_inherited_faint_with_the_source(self):
        marks = {mark["action"]: mark for mark in self.data["marks"]}
        self.assertEqual(list(marks), ["commit", "merge", "push", "pr"])
        self.assertEqual([(marks[a]["level"], marks[a]["own"], marks[a]["inherited"]) for a in marks], [("test", True, False), ("quality-high", False, True), ("none", False, True), ("e2e", True, False)])
        self.assertEqual([marks[a]["title"] for a in marks], ["commit: test · own rule", "merge: quality-high · from main", "push: none · no rule", "pr: e2e · own rule"])
        self.assertEqual([marks[a]["icon"] for a in marks], ["bi-check2-circle", "bi-shield-check", "bi-circle", "bi-browser-chrome"])

    def test_a_branch_gates_py_does_not_know_shows_none_inherited_for_every_action(self):
        self.assertEqual([(mark["level"], mark["inherited"], mark["source"]) for mark in self.data["bare"]], [("none", True, "")] * 4)

    def test_a_click_cycles_the_own_rule_through_every_level_and_back_to_inherited(self):
        self.assertEqual(self.data["cycle"], ["none", "quick", "test", "quality-high", "e2e", None])

    def test_the_staged_argv_is_exactly_what_signing_gate_argv_accepts(self):
        for argv in self.data["argv"]:
            with self.subTest(argv=argv):
                self.assertEqual(signing.gate_argv(argv), argv)
        self.assertEqual(self.data["argv"][1], ["rule", "drop", "--repo", "/r", "--branch", "b", "--action", "push"])

    def test_the_level_icons_are_the_page_levels_of_gates_py(self):
        self.assertEqual(list(self.data["icons"]), list(signing.GATE_LEVELS))


class TestAncestryAssets(unittest.TestCase):
    def test_the_layout_module_parses_on_its_own_and_derived_edges_are_dashed(self):
        done = subprocess.run(["node", "--check", str(ANCESTRY)], capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("svg .ancestry-edge.derived { stroke-dasharray: 5 5; }", STYLE.read_text(encoding="utf-8"))
        self.assertIn(".gate-mark.inherited { opacity: .4; }", STYLE.read_text(encoding="utf-8"))

    def test_every_new_control_is_an_icon_with_title_and_aria_label(self):
        page = PAGE.read_text(encoding="utf-8")
        for control in re.findall(r'iconBtn\("(bi-[a-z0-9-]+)", "([^"]+)"', page):
            with self.subTest(control=control):
                self.assertTrue(control[1])
        self.assertIn('...named(`${mark.action} gate`, title)', page)
        self.assertIn('role: "button", "aria-label": node.label', page)


class TestHubAncestry(HubCase):
    def test_the_page_ships_the_layout_module_and_the_gate_level_icons(self):
        html = self.index()
        self.assertIn(ANCESTRY.read_text(encoding="utf-8").strip(), html)
        for name in ("bi-circle", "bi-lightning-charge", "bi-check2-circle", "bi-shield-check", "bi-browser-chrome", "bi-key", "bi-key-fill", "bi-check2-all"):
            with self.subTest(name=name):
                self.assertIn(f'<symbol id="{name}"', html)


if __name__ == "__main__":
    unittest.main()
