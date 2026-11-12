from __future__ import annotations

import json
import subprocess
import unittest

from hub_support import FACES, HUB

ANCESTRY = HUB / "templates" / "ancestry.js"
SPAWN = HUB / "templates" / "page-spawn.js"
PAGE = HUB / "templates" / "page-ancestry.js"
GRAPH3D = HUB / "templates" / "page-graph3d.js"
FACED = {"Operator": "operator", "s1": "chair", "s2": "session"}
PLAIN = {"s2/x": "subagent", "s1/abc": "twig"}
SPAWN_PROBE = """
const fs = require("fs");
const vm = require("vm");
const [faces, ancestry, spawn, page, graph3d] = process.argv.slice(1);
const Faces = require(faces);
const Ancestry = require(ancestry);
const code = [spawn, page].map((path) => fs.readFileSync(path, "utf8")).join("\\n");
const TOP = vm.runInNewContext(`(${/const TOP = (\\{[^}]*\\});/.exec(fs.readFileSync(graph3d, "utf8"))[1]})`);
const s = (tag, attrs, ...children) => {
  const node = {tag, attrs: Object.fromEntries(Object.entries(attrs).filter(([key, value]) => key !== "on" && value !== null && value !== undefined)), children: []};
  node.append = (...kids) => node.children.push(...kids.flat(Infinity).filter((child) => child !== null && child !== undefined && child !== false));
  node.append(...children);
  return node;
};
const entry = (id, kind, children) => ({id, kind, label: id, children: children || []});
const root = entry("Operator", "operator", [entry("s1", "chair", [entry("s2", "session", [entry("s2/x", "subagent")]), entry("s1/abc", "twig")])]);
const nodes = (tree) => (tree.attrs && String(tree.attrs.class || "").includes("ancestry-node") ? [tree] : (tree.children || []).filter((child) => typeof child === "object").flatMap(nodes));
const mark = (node) => {
  const art = node.children.find((child) => child.attrs.class === "face-art");
  return {
    kind: node.attrs["data-kind"], face: node.attrs["data-face"] ?? null, tags: node.children.map((child) => child.tag),
    r: node.children.find((child) => child.tag === "circle").attrs.r, label: node.children.find((child) => child.tag === "text").attrs.y,
    art: art ? {transform: art.attrs.transform, parts: art.children.map((part) => [part.tag, part.attrs])} : null,
  };
};
const drawn = (on) => {
  const context = {
    Faces, Ancestry, TOP, s, h: s, root, look: {faces: on, hidden: new Set()}, NODE_KINDS: {operator: "Operator", chair: "Chair", session: "Session", subagent: "Subagent"},
    fixed: (value) => value.toFixed(1), short: (text) => text, faceParts: (key) => Faces.of(key).parts.map(([tag, attrs]) => s(tag, attrs)), document: {addEventListener() {}},
  };
  return Object.fromEntries(nodes(vm.runInNewContext(`${code}\\nagentAncestry(root);`, context)).map((node) => [node.attrs["data-agent"], mark(node)]));
};
const keys = ["Operator", "s1", "s2", "s2/x", "s1/abc"];
console.log(JSON.stringify({on: drawn(true), off: drawn(false), faces: Object.fromEntries(keys.map((key) => [key, Faces.of(key).parts]))}));
"""


class TestSpawnAncestryFaces(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        done = subprocess.run(["node", "-e", SPAWN_PROBE, str(FACES), str(ANCESTRY), str(SPAWN), str(PAGE), str(GRAPH3D)], capture_output=True, text=True, timeout=60, check=True)
        cls.data = json.loads(done.stdout)

    def test_every_agent_of_the_spawn_tree_gets_one_node(self):
        for case in ("on", "off"):
            with self.subTest(case=case):
                self.assertEqual({key: node["kind"] for key, node in self.data[case].items()}, {**FACED, **PLAIN})

    def test_with_faces_on_operator_chair_and_sessions_wear_the_face_the_graph_and_3d_draw_for_their_key(self):
        for key in FACED:
            node = self.data["on"][key]
            with self.subTest(key=key):
                self.assertEqual(node["tags"], ["title", "circle", "g", "text"])
                self.assertEqual(node["art"]["parts"], self.data["faces"][key])
                self.assertEqual(node["face"], key)

    def test_the_face_fills_its_ring_and_the_label_moves_below_it(self):
        for key in FACED:
            node = self.data["on"][key]
            with self.subTest(key=key):
                self.assertEqual((node["r"], node["art"]["transform"], node["label"]), (13, "translate(-13 -13) scale(0.65)", 30))

    def test_subagents_and_transcript_twigs_keep_the_plain_circle_as_in_the_graph_and_3d_views(self):
        for key in PLAIN:
            node = self.data["on"][key]
            with self.subTest(key=key):
                self.assertEqual((node["tags"], node["r"], node["label"], node["art"], node["face"]), (["title", "circle", "text"], 9, 26, None, None))

    def test_with_faces_off_every_node_is_the_plain_circle_with_the_label_below_it_as_before(self):
        for key, node in self.data["off"].items():
            with self.subTest(key=key):
                self.assertEqual((node["tags"], node["r"], node["label"], node["art"], node["face"]), (["title", "circle", "text"], 9, 26, None, None))


if __name__ == "__main__":
    unittest.main()
