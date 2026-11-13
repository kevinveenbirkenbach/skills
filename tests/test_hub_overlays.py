from __future__ import annotations

import json
import subprocess
import unittest

from hub_support import HUB, PLAN, REPO_ROOT

GANTT = HUB / "templates" / "page-tasks-gantt.js"
LABELS = REPO_ROOT / "skills" / "kvb-check-score" / "labels.json"
SERIES_PROBE = """
const P = require(process.argv[1]);
const rows = [
  {task: "work/a", branch: "feature/a", worktree_branch: ""},
  {task: "work/b", branch: "-", worktree_branch: "fix/b"},
  {task: "work/c", branch: "-", worktree_branch: ""},
];
const values = (fix, score) => ({fix, break: 2, tokens: null, velocity: 130, security: 100, score});
const journal = [
  {time: 300, branch: "feature/a", values: values(95, 90)},
  {time: 100, branch: "fix/b", values: values(92, null)},
  {time: 200, branch: "feature/other", values: values(10, 10)},
  {time: 900, branch: "feature/a", values: values(1, 1)},
  {time: 150, branch: "", values: values(5, 5)},
  {time: 250, branch: "-", values: values(6, 6)},
];
const series = P.overlaySeries(rows, journal, ["fix", "tokens", "score"], {from: 100, to: 800});
console.log(JSON.stringify({
  keys: Object.keys(P),
  series,
  none: P.overlaySeries(rows, journal, [], {from: 0, to: 1000}),
  tops: [P.overlayTop(series), P.overlayTop(P.overlaySeries(rows, journal, ["velocity"], {from: 0, to: 1000})), P.overlayTop([])],
  labels: [null, "x", {}, {metrics: []}, {metrics: {}}, {metrics: {fix: null}}, {metrics: {fix: {emoji: 1, label: "Fix"}}},
    {metrics: {fix: {emoji: "🎯", label: "Fix"}, bad: {emoji: "x"}, score: {emoji: "🏆", label: "Score"}}}].map(P.overlayLabels),
}));
"""
BURN_PROBE = """
const fs = require("fs");
const [source, plan, labelFile] = process.argv.slice(1);
const P = require(plan);
const labels = JSON.parse(fs.readFileSync(labelFile, "utf8"));
const node = (tag, attrs, children) => ({tag, attrs, children: children.flat(Infinity).filter((child) => child !== null && child !== undefined && child !== false), append(...more) { this.children.push(...more); }});
const s = (tag, attrs, ...children) => node(tag, attrs, children);
const LEAF = /^[A-Za-z]{1,32}\\.[A-Za-z]{1,32}$/u;
const METRICS = Object.keys(labels.metrics);
const kept = {value: [], listeners: [], updates: 0};
const known = (path) => {
  if (path !== "burn.overlays") {
    throw new Error(`unknown view path ${path}`);
  }
};
const ViewStore = {
  get: (path) => {
    known(path);
    return [...kept.value];
  },
  set: (path) => {
    known(path);
    throw new Error(`${path} holds a list: change it through update`);
  },
  update: (path, change) => {
    if (!LEAF.test(String(path)) || typeof change !== "function") {
      throw new Error(`update needs a section.key path and a change function, not ${path}`);
    }
    known(path);
    const next = change([...kept.value]);
    if (!Array.isArray(next) || !next.every((item) => METRICS.includes(item)) || new Set(next).size !== next.length) {
      throw new Error(`burn.overlays must list distinct metrics, not ${JSON.stringify(next)}`);
    }
    kept.value = next;
    kept.updates += 1;
    return Promise.resolve(true);
  },
  on: (path, callback) => {
    known(path);
    kept.listeners.push([path, callback]);
  },
};
const rendered = [];
const LegendChips = {render: (series, path, mode) => {
  if (mode !== "hidden" && mode !== "shown") {
    throw new Error(`a legend chip mode must be hidden or shown, not ${mode}`);
  }
  if (!LEAF.test(String(path)) || !Array.isArray(series) || !series.every((entry) => entry && Object.keys(entry).sort().join() === "id,label,tone" && ["id", "label", "tone"].every((name) => typeof entry[name] === "string"))) {
    throw new Error("legend chips need a section.key path and series [{id, label, tone}]");
  }
  const press = (id) => ViewStore.update(path, (list) => (list.includes(id) ? list.filter((item) => item !== id) : [...list, id]));
  rendered.push({series, path, mode, press});
  return node("div", {class: "legend-chips"}, []);
}};
const refused = (call) => {
  try {
    call();
    return false;
  } catch {
    return true;
  }
};
const contract = [
  refused(() => LegendChips.render([{key: "fix", label: "Fix"}], "burn.overlays", "shown")),
  refused(() => LegendChips.render([{id: "fix", label: "Fix", tone: "k-fix"}], "burn.overlays", "on")),
  refused(() => LegendChips.render([{id: "fix", label: "Fix", tone: "k-fix"}], "burn.overlays")),
  refused(() => ViewStore.set("burn.overlays", ["fix"])),
  refused(() => ViewStore.update("burn.overlays", () => [null])),
];
const journal = [
  {time: 600, branch: "feature/a", values: {fix: 95, break: 2, tokens: 97, velocity: null, security: 100, score: 90}},
  {time: 300, branch: "feature/a", values: {fix: 92, break: 2, tokens: 97, velocity: null, security: 100, score: null}},
  {time: 400, branch: "feature/other", values: {fix: 10, break: 2, tokens: 97, velocity: null, security: 100, score: 10}},
];
const fetched = [];
const fetch = async (url) => {
  fetched.push(url);
  return {ok: true, json: async () => ({since: 0, until: 1000, labels, rows: journal})};
};
const counts = {draws: 0};
const taskView = {sig: "drawn"};
const drawTasks = () => {
  counts.draws += 1;
};
const build = new Function("Plan", "s", "h", "fixed", "stampOf", "absolute", "ViewStore", "LegendChips", "fetch", "drawTasks", "taskView", "ui", `${fs.readFileSync(source, "utf8")}\\nreturn {burnOverlays, overlaysReady, burnRight};`);
const helpers = [P, s, s, (value) => value.toFixed(1), (ts) => new Date(ts * 1000), {format: (date) => date.toISOString()}];
const api = build(...helpers, ViewStore, LegendChips, fetch, drawTasks, taskView, {});
const inert = build(...helpers, undefined, undefined, fetch, drawTasks, taskView, {});
const brokenStore = {get: () => ["fix"], update: () => Promise.resolve(true), on: () => {}};
const brokenFetch = async () => ({ok: true, json: async () => ({labels: {}, rows: "x"})});
const broken = build(...helpers, brokenStore, LegendChips, brokenFetch, () => {}, {sig: ""}, {});
const picked = {rows: [{task: "work/a", branch: "feature/a", worktree_branch: ""}], from: 0, to: 1000};
const shape = (svg) => ({
  overlays: svg.children.filter((child) => child.tag === "g").map((group) => ({cls: group.attrs.class, key: group.attrs["data-overlay"], points: group.children.filter((child) => child.tag === "circle").map((circle) => [circle.attrs.cx, circle.attrs.cy])})),
  axis: svg.children.filter((child) => child.tag === "text").map((text) => [text.attrs.x, text.children[0]]),
});
(async () => {
  const pending = api.burnOverlays(s("svg", {}), picked, (t) => t, api.burnRight());
  const brokenFirst = broken.burnOverlays(s("svg", {}), picked, (t) => t, broken.burnRight());
  await new Promise((resolve) => setTimeout(resolve, 0));
  const brokenSvg = s("svg", {});
  const brokenAfter = broken.burnOverlays(brokenSvg, picked, (t) => t, broken.burnRight());
  const brokenView = [brokenFirst, brokenAfter, brokenSvg.children.length, broken.burnRight()];
  const off = s("svg", {});
  const rights = {inert: [inert.overlaysReady(), inert.burnRight()], off: api.burnRight()};
  const offChips = api.burnOverlays(off, picked, (t) => t, rights.off);
  const stored = [await rendered[0].press("score"), await rendered[0].press("fix")];
  const pressed = {stored, value: [...kept.value], updates: kept.updates};
  rights.on = api.burnRight();
  const on = s("svg", {});
  api.burnOverlays(on, picked, (t) => t, rights.on);
  const drawsBefore = counts.draws;
  taskView.sig = "drawn";
  kept.listeners[0][1]();
  console.log(JSON.stringify({
    ready: api.overlaysReady(), pending, fetched, firstDraws: drawsBefore, listeners: kept.listeners.map(([path]) => path), redrawn: [counts.draws - drawsBefore, taskView.sig],
    off: shape(off), offChips: offChips.attrs.class, chips: rendered[0], on: shape(on), rights, brokenView, contract, pressed,
  }));
})();
"""


class TestOverlaySeries(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        done = subprocess.run(["node", "-e", SERIES_PROBE, str(PLAN)], capture_output=True, text=True, timeout=60, check=True)
        cls.data = json.loads(done.stdout)

    def test_only_rows_of_the_scope_branches_within_the_span_are_drawn_in_the_given_order(self):
        self.assertIn("overlaySeries", self.data["keys"])
        self.assertNotIn("OVERLAYS", self.data["keys"])
        self.assertEqual(self.data["series"], [
            {"key": "fix", "points": [{"t": 100, "value": 92, "branch": "fix/b"}, {"t": 300, "value": 95, "branch": "feature/a"}]},
            {"key": "tokens", "points": []},
            {"key": "score", "points": [{"t": 300, "value": 90, "branch": "feature/a"}]},
        ])
        self.assertEqual(self.data["none"], [])

    def test_the_right_axis_runs_to_100_or_the_largest_value_above_it(self):
        self.assertEqual(self.data["tops"], [100, 130, 100])

    def test_labels_of_another_shape_switch_the_overlays_off(self):
        self.assertEqual(self.data["labels"], [None, None, None, None, None, None, None, {"fix": "🎯 Fix", "score": "🏆 Score"}])


class TestBurnOverlays(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        done = subprocess.run(["node", "-e", BURN_PROBE, str(GANTT), str(PLAN), str(LABELS)], capture_output=True, text=True, timeout=60, check=True)
        cls.data = json.loads(done.stdout)

    def test_six_metric_chips_all_off_on_first_load_keyed_burn_overlays(self):
        data = self.data
        self.assertEqual((data["ready"], data["pending"], data["fetched"], data["firstDraws"]), (True, None, ["/api/scores?from=0&to=1000"], 1))
        self.assertEqual((data["chips"]["path"], data["chips"]["mode"]), ("burn.overlays", "shown"))
        self.assertEqual(data["chips"]["series"], [
            {"id": key, "label": label, "tone": f"k-{key}"}
            for key, label in (("fix", "🎯 Fix"), ("break", "💥 Break"), ("tokens", "💸 Tokens"), ("velocity", "⏱️ Velocity"), ("security", "🛡️ Security"), ("score", "🏆 Score"))
        ])
        self.assertEqual((data["off"], data["offChips"]), ({"overlays": [], "axis": []}, "legend-chips"))

    def test_the_contract_stub_refuses_another_shape_mode_or_write(self):
        self.assertEqual(self.data["contract"], [True] * 5)

    def test_a_chip_press_stores_its_metric_through_update(self):
        self.assertEqual(self.data["pressed"], {"stored": [True, True], "value": ["score", "fix"], "updates": 2})

    def test_labels_of_another_shape_draw_no_overlay_and_never_throw(self):
        self.assertEqual(self.data["brokenView"], [None, None, 0, 24])

    def test_the_right_margin_widens_only_while_an_overlay_is_on(self):
        self.assertEqual(self.data["rights"], {"inert": [False, 24], "off": 24, "on": 56})

    def test_a_switched_on_chip_draws_its_series_on_the_right_axis(self):
        on = self.data["on"]
        self.assertEqual(on["axis"], [[850, "0 %"], [850, "50 %"], [850, "100 %"]])
        self.assertEqual(on["overlays"], [
            {"cls": "burn-overlay k-fix", "key": "fix", "points": [["300.0", "42.4"], ["600.0", "34.0"]]},
            {"cls": "burn-overlay k-score", "key": "score", "points": [["600.0", "48.0"]]},
        ])

    def test_a_view_store_change_redraws_the_burndown(self):
        self.assertEqual(self.data["listeners"], ["burn.overlays"])
        self.assertEqual(self.data["redrawn"], [1, ""])


class TestOverlayTones(unittest.TestCase):
    def test_every_metric_chip_has_a_tone_colour(self):
        css = (HUB / "templates" / "style-tasks.css").read_text(encoding="utf-8")
        for key in json.loads(LABELS.read_text(encoding="utf-8"))["metrics"]:
            with self.subTest(key=key):
                self.assertRegex(css, rf"\.burn-box \.legend-chip\.k-{key}\s*\{{\s*--c: var\(--[a-z]+\); \}}")


if __name__ == "__main__":
    unittest.main()
