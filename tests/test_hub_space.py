from __future__ import annotations

import itertools
import json
import math
import subprocess
import unittest

from hub_support import SPACE
from kvb_orchestrator import settings

SPACE_NOW = 1_800_000_000
SPACE_LOW = SPACE_NOW - 86400
SPACE_PROBE = """
const S = require(process.argv[1]);
const now = Number(process.argv[2]);
const low = Number(process.argv[3]);
let seed = 7;
const next = () => {
  seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
  return seed / 4294967296;
};
const median = (list) => [...list].sort((a, b) => a - b)[Math.floor(list.length / 2)];
const clock = (run) => {
  const began = process.hrtime.bigint();
  const value = run();
  return [Number(process.hrtime.bigint() - began) / 1e6, value];
};
const sessions = Array.from({length: 30}, (_, index) => `s${index}`);
const keys = ["name:Maintainer", ...sessions];
const nodes = [
  {id: "Operator", kind: "operator", parent: null, label: "Operator", timeline: [{name: "Operator", since: now}]},
  {id: "name:Maintainer", kind: "chair", parent: null, label: "Maintainer", timeline: [{name: "Maintainer", since: low}]},
  ...sessions.map((id, index) => ({id, kind: "session", parent: null, label: `Renamed ${index}`, timeline: [{name: `Agent ${index}`, since: low - 10}, {name: `Renamed ${index}`, since: low + 43200}]})),
  {id: "subagent x @ s1", kind: "subagent", parent: "s1", label: "subagent x", timeline: [{name: "subagent x", since: now}]},
];
const track = Array.from({length: 13}, (_, step) => ({ts: low + 7200 * step, orbit: Object.fromEntries(keys.map((key, at) => [key, {angle: -Math.PI / 2 + at * 0.2 + step * 0.05, radius: 150 + ((at * 37 + step * 11) % 150)}]))}));
const classes = ["direct", "direct", "direct", "broadcast", "security", "mayday", "pan-pan"];
const radio = Array.from({length: 5000}, (_, index) => {
  const cls = classes[Math.floor(next() * classes.length)];
  return {ts: low + 17.28 * index, source: keys[Math.floor(next() * keys.length)], targets: cls === "broadcast" ? [] : [keys[Math.floor(next() * keys.length)]], class: cls, text: "x"};
});
const grants = Array.from({length: 50}, (_, index) => ({ts: low + 1700 * index, target: sessions[index % sessions.length]}));
const subagents = {s1: [
  {id: "root", depth: 1, since: low + 3600, until: low + 7200, started: low + 3600, type: "Explore", description: "scan", finished: true},
  {id: "leaf", depth: 2, since: low + 4000, until: null, started: low + 4000, type: "Plan", description: "plan", finished: false},
  {id: "late", depth: 1, since: null, until: null, started: low + 80000, type: "", description: "late", finished: false},
]};
const spots = Object.fromEntries(keys.map((key, at) => [key, {x: 200 * Math.cos(at), y: 200 * Math.sin(at)}]));
const input = {axis: "time", range: [low, now], span: [low, now], cursor: now, nodes, track, now: spots, lives: {s2: [low + 600, low + 1200]}, subagents, radio, grants, chair: "name:Maintainer", cap: S.ARC_CAP};
const built = S.scene(input);
const spawnOf = (scene, sub) => scene.arcs.find((arc) => arc.kind === "spawn" && arc.sub === sub);
const flat = (view) => S.camera({yaw: 0, pitch: 0, zoom: 1, pan_x: 0, pan_y: 0, ...view}, 860, 860);
const spawn = S.scene({...input, axis: "spawn"});
const calls = {count: 0};
const ctx = Object.fromEntries(["clearRect", "beginPath", "moveTo", "lineTo", "quadraticCurveTo", "closePath", "stroke", "fill", "arc", "strokeText", "fillText"].map((name) => [name, () => {
  calls.count += 1;
}]));
const colors = Object.fromEntries(["line", "accent", "muted", "violet", "direct", "broadcast", "alarm", "security", "grant", "panel", "text"].map((role) => [role, "#123456"]));
const style = {colors, font: "12px sans", strong: "bold 12px sans", level: "Depth", cursor: "As of", selected: "s3", format: String};
const builds = Array.from({length: 15}, () => clock(() => S.scene(input))[0]);
let stats = null;
const paints = Array.from({length: 30}, (_, frame) => {
  const [spent, result] = clock(() => S.paint(ctx, built, S.camera({...S.DEFAULTS.graph, yaw: frame * 12}, 1280, 760), style));
  stats = result;
  return spent;
});
const mini = {...input, nodes: nodes.slice(0, 4), track: [], subagents: {}, lives: {}, grants: [], radio: [{ts: low + 43200, source: "s0", targets: ["s1"], class: "direct", text: "x"}], now: {s0: {x: 200, y: 0}, s1: {x: -200, y: 0}, "name:Maintainer": {x: 0, y: -200}}};
const small = S.scene(mini);
const cam = S.camera(S.DEFAULTS.graph, 860, 860);
const wire = small.arcs[0];
const [a, b, c] = [wire.from, wire.via, wire.to].map((entry) => S.project(cam, entry));
const tail = S.project(cam, small.lines.find((entry) => entry.node === "s0").points[0]);
const hit = (x, y) => {
  const found = S.pick(small, cam, x, y, 10);
  return found ? `${found.kind}:${found.kind === "line" ? found.line.node : found.arc.kind}` : null;
};
const sight = S.lens(S.DEFAULTS.sky, 1600, 900);
const synthetic = Array.from({length: 5000}, (_, index) => ({tone: ["direct", "broadcast", "alarm", "security", "grant", "spawn"][index % 6], ts: index}));
const capped = S.capArcs(synthetic, 2000);
console.log(JSON.stringify({
  defaults: S.DEFAULTS, limits: S.LIMITS, axes: S.AXES, cap: S.ARC_CAP,
  matrices: [[0, 0], [30, 20], [-135, 60], [90, -90], [179.5, 45], [12.3, -77.7]].map(([yaw, pitch]) => S.rotation(yaw, pitch)),
  projected: [
    [flat({}), {x: 0, y: 0, z: 0}], [flat({}), {x: 100, y: 0, z: 0}], [flat({}), {x: 100, y: 50, z: 400}], [flat({yaw: 90}), {x: 100, y: 0, z: 0}],
    [flat({pitch: 90}), {x: 0, y: 100, z: 0}], [S.camera({yaw: 0, pitch: 0, zoom: 2, pan_x: 10, pan_y: -20}, 1720, 860), {x: 100, y: 0, z: 0}], [flat({}), {x: 0, y: 0, z: -1500}],
  ].map(([view, point]) => S.project(view, point)),
  sorted: S.depthSort([{id: "a", depth: 5}, {id: "b", depth: 50}, {id: "c", depth: -20}, {id: "d", depth: 50}]).map((item) => item.id),
  axis: {
    time: [low, (low + now) / 2, now, low - 100, now + 100].map((ts) => S.depthOf("time", {ts, level: 0}, [low, now])),
    still: S.depthOf("time", {ts: now, level: 0}, [now, now]),
    spawn: [0, 1, 2, 4, 9].map((level) => S.depthOf("spawn", {ts: now, level}, [low, now])),
    none: [S.depthOf("none", {ts: low, level: 3}, [low, now]), S.depthOf("none", {ts: now, level: 0}, [low, now])],
  },
  parents: S.notBeforeParent([
    {id: "c", kind: "chair", ts: 200}, {id: "s", kind: "session", parent: "c", ts: 100}, {id: "w", kind: "twig", parent: "v", ts: 120},
    {id: "t", kind: "twig", parent: "s", ts: 50}, {id: "u", kind: "twig", parent: "t"}, {id: "v", kind: "twig", parent: "s", ts: 150},
    {id: "x", kind: "subagent", parent: "gone", ts: 30}, {id: "y", kind: "twig", parent: "z", ts: 5}, {id: "z", kind: "twig", parent: "y", ts: 7},
  ], new Set(["twig", "subagent"])).map((node) => [node.id, node.ts]),
  same: [S.scene(input), S.scene(JSON.parse(JSON.stringify(input)))].every((other) => JSON.stringify(other) === JSON.stringify(built)),
  lines: Object.fromEntries(built.lines.map((entry) => [entry.sub || entry.node, {kind: entry.kind, level: entry.level, alive: entry.alive, stamps: entry.points.map((point) => point.ts), first: entry.points[0], name: entry.timeline[0].name}])),
  labels: built.labels.filter((label) => built.lines[label.line].node === "s5").map((label) => [label.at.ts, label.text]),
  spawns: Object.fromEntries(["root", "leaf"].map((sub) => [sub, spawnOf(built, sub)])),
  plane: built.plane, guides: built.guides, total: built.total, dropped: built.dropped, arcs: built.arcs.length,
  alarms: built.arcs.filter((arc) => arc.tone === "alarm").length,
  spawned: {
    points: spawn.lines.map((entry) => entry.points.length), leaf: spawn.lines.find((entry) => entry.sub === "leaf").points[0].z, session: spawn.lines.find((entry) => entry.node === "s1").points[0].z,
    arc: spawnOf(spawn, "leaf"), plane: spawn.plane, messages: spawn.arcs.filter((arc) => arc.kind !== "spawn").length,
  },
  capped: {kept: capped.kept.map((arc) => arc.ts), dropped: capped.dropped, small: S.capArcs(synthetic.slice(0, 100), 1500).kept.length},
  frame: {build: median(builds), paint: median(paints), stats, calls: calls.count / 30},
  picks: [hit(tail.x, tail.y), hit(0.25 * a.x + 0.5 * b.x + 0.25 * c.x, 0.25 * a.y + 0.5 * b.y + 0.25 * c.y), hit(3, 3)],
  names: [5, 10, 15, 20, 99].map((ts) => S.nameAt([{name: "A", since: 10}, {name: "B", since: 20}], ts)),
  tree: S.tree([{id: "x", depth: 1, since: 10, until: 50, started: 10}, {id: "y", depth: 1, since: 20, until: 30, started: 20}, {id: "z", depth: 2, since: 40, until: null, started: 40}, {id: "w", depth: 2, since: 25, until: null, started: 25}]).parents,
  clamped: [S.clampView("graph", {axis: "time", yaw: 190, pitch: 100, zoom: 9, pan_x: -5000, pan_y: 1}), S.clampView("sky", {azimuth: -10, altitude: 99, fov: 5})],
  tweened: S.tween("graph", {axis: "time", yaw: 170, pitch: 0, zoom: 1, pan_x: 0, pan_y: 0}, {axis: "spawn", yaw: -170, pitch: 10, zoom: 2, pan_x: 0, pan_y: 0}, 0.5),
  tidy: S.tidy({axis: "time", yaw: 12.3456, zoom: 0.999}),
  sky: {
    south: [[30, 135], [0, 90], [0, 270], [45, 180]].map(([alt, az]) => S.place(sight, alt, az)),
    horizon: S.horizon(sight, 8).map((point) => point.y),
    east: S.place(S.lens({azimuth: 90, altitude: 0, fov: 180}, 1600, 900), 0, 90),
    up: S.place(S.lens({azimuth: 180, altitude: 30, fov: 180}, 1600, 900), 30, 180),
    narrow: S.place(S.lens({azimuth: 180, altitude: 0, fov: 90}, 1600, 900), 0, 225),
  },
  compass: [0, 22.4, 22.6, 180, 359, -90, 404].map(S.compass),
}));
"""


class TestSpaceModule(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        command = ["node", "-e", SPACE_PROBE, str(SPACE), str(SPACE_NOW), str(SPACE_LOW)]
        done = subprocess.run(command, capture_output=True, text=True, timeout=120, check=True)
        cls.data = json.loads(done.stdout)

    def assert_close(self, actual: dict, expected: dict) -> None:
        for key, value in expected.items():
            with self.subTest(key=key):
                self.assertAlmostEqual(actual[key], value, places=6)

    def test_the_defaults_limits_and_axes_match_the_server_validation(self):
        self.assertEqual(self.data["defaults"], settings.SETTINGS["space"])
        self.assertEqual(self.data["limits"], {view: {key: list(pair) for key, pair in limits.items()} for view, limits in settings.SPACE_LIMITS.items()})
        self.assertEqual(tuple(self.data["axes"]), settings.SPACE_AXES)

    def test_rotation_matrices_are_orthonormal(self):
        self.assertEqual(len(self.data["matrices"]), 6)
        for matrix in self.data["matrices"]:
            rows = [matrix[0:3], matrix[3:6], matrix[6:9]]
            with self.subTest(matrix=matrix):
                for first, second in itertools.product(range(3), repeat=2):
                    self.assertAlmostEqual(sum(rows[first][k] * rows[second][k] for k in range(3)), float(first == second), places=12)
                    self.assertAlmostEqual(sum(rows[k][first] * rows[k][second] for k in range(3)), float(first == second), places=12)
                (a, b, c), (d, e, f), (g, h, i) = rows
                self.assertAlmostEqual(a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g), 1.0, places=12)

    def test_known_points_project_to_the_expected_screen_coordinates(self):
        expected = [
            {"x": 430, "y": 430, "depth": 0, "size": 1},
            {"x": 530, "y": 430, "depth": 0, "size": 1},
            {"x": 510, "y": 470, "depth": 400, "size": 0.8},
            {"x": 430, "y": 430, "depth": -100, "size": 1600 / 1500},
            {"x": 430, "y": 430, "depth": 100, "size": 1600 / 1700},
            {"x": 1080, "y": 390, "depth": 0, "size": 2},
        ]
        projected = self.data["projected"]
        for actual, wanted in zip(projected[:-1], expected, strict=True):
            self.assert_close(actual, wanted)
        self.assertIsNone(projected[-1])

    def test_depth_sort_draws_far_before_near_and_keeps_ties_in_order(self):
        self.assertEqual(self.data["sorted"], ["b", "d", "a", "c"])

    def test_the_axis_maps_time_spawn_depth_or_nothing(self):
        axis = self.data["axis"]
        self.assertEqual(axis["time"], [300, 0, -300, 300, -300])
        self.assertEqual(axis["still"], -300)
        self.assertEqual(axis["spawn"], [-300, -150, 0, 300, 300])
        self.assertEqual(axis["none"], [0, 0])

    def test_a_subagent_never_lies_before_the_agent_that_spawned_it(self):
        self.assertEqual(self.data["parents"], [["c", 200], ["s", 100], ["w", 150], ["t", 100], ["u", 100], ["v", 150], ["x", 30], ["y", 7], ["z", 7]])

    def test_world_lines_are_deterministic_and_follow_the_layout_of_their_time(self):
        self.assertTrue(self.data["same"])
        lines = self.data["lines"]
        self.assertLessEqual({"Operator", "name:Maintainer", "subagent x @ s1", *(f"s{n}" for n in range(30))}, set(lines))
        root, leaf, late = lines["root"], lines["leaf"], lines["late"]
        self.assertEqual((root["kind"], root["level"], root["alive"], root["stamps"]), ("twig", 1, False, [SPACE_LOW + 3600, SPACE_LOW + 7200]))
        self.assertEqual((leaf["level"], leaf["alive"], leaf["stamps"][0], leaf["stamps"][-1]), (2, True, SPACE_LOW + 4000, SPACE_NOW))
        self.assertEqual((late["stamps"], late["name"]), ([SPACE_LOW + 80000, SPACE_NOW], "Subagent"))
        self.assertEqual((lines["s2"]["stamps"], lines["s2"]["alive"]), ([SPACE_LOW + 600, SPACE_LOW + 1200], False))
        self.assertEqual(lines["s5"]["stamps"], [SPACE_LOW + 7200 * step for step in range(13)])
        self.assertEqual((lines["subagent x @ s1"]["level"], lines["subagent x @ s1"]["kind"]), (1, "subagent"))
        angle, radius = -math.pi / 2 + 0.425, 229.5
        born = self.data["spawns"]["root"]
        self.assert_close(born["from"], {"x": radius * math.cos(angle), "y": radius * math.sin(angle), "z": 275, "ts": SPACE_LOW + 3600})
        for sub in ("root", "leaf"):
            with self.subTest(sub=sub):
                self.assertEqual(self.data["spawns"][sub]["to"], lines[sub]["first"])
                self.assertEqual(self.data["spawns"][sub]["from"]["z"], lines[sub]["first"]["z"])
        self.assertEqual(self.data["labels"], [[SPACE_NOW, "Renamed 5"], [SPACE_LOW + 43200, "Renamed 5"], [SPACE_LOW, "Agent 5"]])
        self.assertEqual(self.data["plane"], {"z": -300, "ts": SPACE_NOW})
        self.assertEqual([(guide["z"], guide["ts"]) for guide in self.data["guides"]], [(300, SPACE_LOW), (-300, SPACE_NOW)])
        spawned = self.data["spawned"]
        self.assertEqual(set(spawned["points"]), {1})
        self.assertEqual((spawned["session"], spawned["leaf"], spawned["plane"]), (-300, 0, None))
        self.assertEqual((spawned["arc"]["from"]["z"], spawned["arc"]["to"]["z"]), (-150, 0))
        self.assertLessEqual(spawned["messages"], self.data["cap"])

    def test_arcs_are_capped_by_urgency_then_recency(self):
        self.assertEqual((self.data["arcs"], self.data["dropped"]), (self.data["cap"], self.data["total"] - self.data["cap"]))
        self.assertGreater(self.data["total"], self.data["cap"])
        capped = self.data["capped"]
        kept = capped["kept"]
        self.assertEqual((len(kept), capped["dropped"], capped["small"]), (2000, 3000, 100))
        self.assertEqual(kept, sorted(kept))
        tones = ["direct", "broadcast", "alarm", "security", "grant", "spawn"]
        by_tone = {tone: [ts for ts in kept if tones[ts % 6] == tone] for tone in tones}
        self.assertEqual({tone: len(found) for tone, found in by_tone.items()}, {"direct": 0, "broadcast": 0, "alarm": 833, "security": 334, "grant": 0, "spawn": 833})
        self.assertEqual(by_tone["security"], [ts for ts in range(5000) if ts % 6 == 3][-334:])

    def test_a_frame_of_5000_events_draws_capped_batched_arcs_inside_the_frame_budget(self):
        frame = self.data["frame"]
        self.assertLessEqual(frame["stats"]["arcs"], self.data["cap"])
        self.assertLess(frame["stats"]["batches"], 400)
        self.assertLess(frame["paint"], 1000 / 60)

    def test_picking_finds_the_world_line_the_arc_or_nothing(self):
        self.assertEqual(self.data["picks"], ["line:s0", "arc:message", None])

    def test_names_trees_and_views_follow_their_rules(self):
        self.assertEqual(self.data["names"], ["A", "A", "A", "B", "B"])
        self.assertEqual(self.data["tree"], {"x": "", "y": "", "w": "y", "z": "x"})
        self.assertEqual(self.data["clamped"], [{"axis": "time", "yaw": -170, "pitch": 90, "zoom": 4, "pan_x": -2000, "pan_y": 1}, {"azimuth": 350, "altitude": 85, "fov": 20}])
        self.assert_close(self.data["tweened"], {"pitch": 5, "zoom": 1.5, "pan_x": 0, "pan_y": 0})
        self.assertAlmostEqual(abs(self.data["tweened"]["yaw"]), 180, places=6)
        self.assertEqual((self.data["tweened"]["axis"], self.data["tidy"]), ("spawn", {"axis": "time", "yaw": 12.35, "zoom": 1}))

    def test_the_sky_faces_south_by_default_and_turns_with_the_view(self):
        sky = self.data["sky"]
        width, height = 1600, 900
        horizon = 0.86 * height
        today = [{"x": width / 2 + ((az - 180) / 180) * width, "y": horizon - (alt / 90) * horizon * 0.94} for alt, az in ((30, 135), (0, 90), (0, 270), (45, 180))]
        for actual, wanted in zip(sky["south"], today, strict=True):
            self.assert_close(actual, wanted)
        for y in sky["horizon"]:
            self.assertAlmostEqual(y, horizon, places=6)
        for name, wanted in (("east", {"x": 800, "y": horizon}), ("up", {"x": 800, "y": horizon}), ("narrow", {"x": width, "y": horizon})):
            with self.subTest(name=name):
                self.assert_close(sky[name], wanted)
        self.assertEqual(self.data["compass"], [0, 0, 1, 4, 0, 6, 1])


if __name__ == "__main__":
    unittest.main()
