from __future__ import annotations

import itertools
import json
import subprocess
import time
import unittest

from hub_case import HubCase
from hub_support import HUB, NAV, PLAN

MODULE = HUB / "templates" / "resources.js"
PAGE = HUB / "templates" / "page-resources.js"
STYLE = HUB / "templates" / "style-resources.css"
T = 1_760_000_000
FIXTURE = """
const asleep = {name: "0000:01:00.0", asleep: true};
const awake = (util, used) => ({name: "0000:01:00.0", util, vram_used: used, vram_total: 1000});
const unread = {name: "0000:01:00.0", util: null, vram_used: null, vram_total: null, error: "@MISMATCH@"};
const row = (t, cpu, ram, waiting, gpu, disks, queued) => ({t, cpu, ram, swap: 0, load: 1, disks, gpus: [gpu], queue: {waiting, active: 1, ...queued}});
const head = (id, waited_s, reason) => ({id, kind: "job", waited_s, reason});
const root = [{mount: "/", used: 250, total: 1000}];
const samples = [
  row(T, 20, 30, 0, asleep, root),
  row(T + 60, 40, 45, 2, asleep, root),
  row(T + 120, 45, 40, 3, awake(80, 500), [...root, {mount: "/mnt", used: 1, total: 4}]),
  row(T + 180, 70, 40, 3, awake(90, 600), root, {head: head("quality-high-1002", 599, "@BESIDE@")}),
  row(T + 240, 30, 30, 1, awake(10, 100), root, {head: head("quality-high-1002", 600, "@ESCALATED@")}),
  row(T + 300, 35, 30, 0, unread, root, {head: head("quality-high-1002", 660, "@RAM@"), hung: ["test-1001"]}),
  row(T + 5000, 10, 10, 1, asleep, root, {hung: ["test-1001"]}),
  row(T + 5060, 10, 10, 0, asleep, root, {head: head("deploy-1003", 1200, "@BEHIND@")}),
];
const tokens = [
  {t: T, agent: "Skills", model: "opus", input: 10, output: 20, cache_read: 300, cache_write: 40},
  {t: T, agent: "Stage", model: "opus", input: 1, output: 2, cache_read: 3, cache_write: 4},
  {t: T, agent: "Skills", model: "haiku", input: 5, output: 0, cache_read: 0, cache_write: 0},
  {t: T + 3600, agent: "Stage", model: "opus", input: 500, output: 0, cache_read: 0, cache_write: 0},
  {t: "x", agent: "Bad", model: "opus", input: 1, output: 0, cache_read: 0, cache_write: 0},
];
"""
BESIDE = "quality-high runs only beside test-nostack, but test runs"
ESCALATED = f"escalated post: {BESIDE}"
RAM = "RAM 56 % used + 37 % still to come reach the limit 85 %"
BEHIND = "waits in line behind test-1001"
MISMATCH = "Failed to initialize NVML: Driver/library version mismatch"
FIXTURE = FIXTURE.replace("@BESIDE@", BESIDE).replace("@ESCALATED@", ESCALATED).replace("@RAM@", RAM).replace("@BEHIND@", BEHIND).replace("@MISMATCH@", MISMATCH)
QH = "quality-high-1002"
PROBE = """
const R = require(process.argv[1]);
const T = Number(process.argv[2]);
@FIXTURE@
const lines = R.lines(samples);
const pick = (list) => list.map((entry) => [entry.name, entry.kind, entry.points]);
console.log(JSON.stringify({
  zones: R.ZONES,
  disks: pick(lines.disks),
  host: pick(lines.host),
  gpu: pick(lines.gpu),
  segments: R.segments([[T, 1], [T + 60, null], [T + 120, 3], [T + 180, 4], [T + 4000, 5]]),
  waits: R.waits(samples),
  blocked: R.blocked(samples),
  hung: R.hung(samples),
  threshold: R.BLOCKED,
  under: R.blocked([...samples.slice(0, 4), row(T + 240, 1, 1, 1, asleep, root, {head: {id: 5, waited_s: 9000}}), row(T + 300, 1, 1, 1, asleep, root, {head: {id: "x", waited_s: "900"}, hung: "test-1"})]),
  quiet: R.hung(samples.slice(0, 5)),
  asleep: R.asleep(samples),
  unknown: R.unknown(samples),
  causeless: R.unknown([row(T, 1, 1, 0, {...unread, error: ""}, root), row(T + 60, 1, 1, 0, {...unread, error: 7}, root), row(T + 120, 1, 1, 0, {...unread, error: "other"}, root), row(T + 180, 1, 1, 0, asleep, root), row(T + 240, 1, 1, 0, unread, root)]),
  stack: R.stack(tokens),
  hardware: R.hardware(samples).map((entry) => [entry.name, entry.kind, entry.points.length]),
  accumulated: R.accumulate(tokens),
  many: (() => {
    let seed = 7;
    const next = () => {
      seed = (seed * 1103515245 + 12345) % 2147483648;
      return seed;
    };
    const rows = Array.from({length: 80}, () => ({t: T + 3600 * (next() % 12), agent: ["A", "B", "C"][next() % 3], model: "m", input: (next() % 900) - 100, output: next() % 50, cache_read: next() % 2 ? NaN : 7, cache_write: 0}));
    const sums = R.accumulate(rows);
    const totals = R.stack(rows).totals;
    return {
      rising: sums.lines.every((line) => line.points.every(([, value], index) => !index || value >= line.points[index - 1][1])),
      finals: Object.fromEntries(sums.lines.map((line) => [line.agent, line.points[line.points.length - 1][1]])),
      totals, top: sums.top, lengths: [...new Set(sums.lines.map((line) => line.points.length))],
    };
  })(),
  burnup: R.burnup([{t: 1, scope: 2, done: 0}, {t: 2, scope: 4, done: 1}, {t: 3, scope: 5, done: 5}, {t: 4, scope: 4, done: 4}]),
  empty: R.burnup([{t: 1, scope: 0, done: 0}]),
}));
""".replace("@FIXTURE@", FIXTURE)
PAGE_PROBE = """
const fs = require("fs");
const vm = require("vm");
const Resources = require(process.argv[1]);
const Plan = require(process.argv[2]);
const Limits = require(require("path").join(require("path").dirname(process.argv[1]), "limits.js"));
const code = process.argv.slice(3, -1).map((path) => fs.readFileSync(path, "utf8")).join("\\n");
const T = Number(process.argv[process.argv.length - 1]);
@FIXTURE@
const make = (tag, attrs, children) => {
  const node = {tag, attrs: {}, children: [], textContent: "", isConnected: true, listeners: {},
    set className(value) { this.attrs.class = value; }, set type(value) { this.attrs.type = value; },
    setAttribute(key, value) { this.attrs[key] = String(value); }, getAttribute(key) { return this.attrs[key]; },
    addEventListener(name, run) { this.listeners[name] = run; },
    append(...items) { this.children.push(...items); },
    replaceChildren(...items) { this.children = items; },
    getBoundingClientRect() { return {width: 800, height: 120}; }};
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "on") {
      Object.assign(node.listeners, value);
    } else if (value !== null && value !== undefined && value !== false) {
      node.attrs[key] = String(value);
    }
  }
  node.hidden = Object.hasOwn(node.attrs, "hidden");
  node.children = children.flat(Infinity).filter((child) => child !== null && child !== undefined && child !== false);
  return node;
};
const h = (tag, attrs, ...children) => make(tag, attrs, children);
const icon = (name) => make("svg", {class: "bi", "data-icon": name}, []);
const view = {resources: {hidden: [], tokens: "interval", panels: ["hardware", "tokens", "accounts"], combinedHidden: []}, burn: {overlays: []}, home: {pins: []}};
const served = JSON.parse(JSON.stringify(view));
const fetched = [];
const sheets = [];
const tasks = [
  {task: "a", kind: "task", status: "done", start: T - 300, end: T + 600, points: 0},
  {task: "b", kind: "task", status: "running", start: T + 1000, end: null, points: 0},
  {task: "c", kind: "task", status: "done", start: T + 2000, end: T + 3000, points: 0},
  {task: "q", kind: "queue", status: "done", start: T - 500, end: T - 400, points: 0},
];
const context = {
  Resources, Plan, Limits, h, s: h, icon, DAY: 86400, ui: {preset: 86400, from: null, to: null, asOf: null, offline: false},
  state: {tasks, now: T + 6000}, settings: {estimation: "none", forecast: false}, setTimeout, clearTimeout,
  named: (label, hint) => ({title: hint || label, "aria-label": label}),
  iconBtn: (name, label, cls, run, hint) => make("button", {title: hint, "aria-label": label}, [icon(name)]), caret: () => icon("bi-caret-down-fill"),
  boxHead: (label, cls, ...children) => make("div", {class: "box-head", "aria-label": label}, children),
  fixed: (value) => value.toFixed(1), dash: (value) => (value === null ? "–" : value), absolute: {format: () => "d"}, clock: {format: () => "c"}, stampOf: (t) => new Date(t * 1000),
  revealed: (text) => String(text), counter: (value) => make("span", {class: "count"}, [String(value)]), openSheet: (title, body, wide) => sheets.push({title, body, wide}),
  stored: (key, fallback) => fallback, keep: () => true,
  window: {setTimeout: (run) => run(), setInterval: () => 1, addEventListener: () => null},
  document: {
    hidden: false, activeElement: null, createElement: (tag) => make(tag, {}, []), getElementById: (name) => (name === "view" ? {textContent: JSON.stringify(view)} : null),
    querySelectorAll: (selector) => (selector === ".legend-chip" ? walk(context.screen, []).filter((node) => has(node, "legend-chip")) : []),
  },
  windowQuery: () => "from=1", nowSeconds: () => 0,
  fetch: async (url, options) => {
    if (url === "/api/limits") {
      return {ok: true, json: async () => ({limits: null, why: null, target: null, profiles: {}, metrics: Limits.METRICS, levels: Limits.LEVELS})};
    }
    if (url === "/api/accounts") {
      fetched.push(url);
      return {ok: true, json: async () => ({accounts: [], active: null, usage: {}})};
    }
    if (url !== "/api/view") {
      fetched.push(url);
      return {ok: true, json: async () => ({since: T - 600, until: T + 6000, samples, tokens})};
    }
    const changes = JSON.parse(options.body).set;
    fetched.push([options.method, url, changes]);
    for (const [path, value] of Object.entries(changes)) {
      const [section, key] = path.split(".");
      served[section][key] = value;
    }
    return {ok: true, json: async () => JSON.parse(JSON.stringify(served))};
  },
};
vm.runInNewContext(`${code}\\nscreen = resourcesScreen();\\nstore = ViewStore;`, context);
const walk = (node, found) => {
  if (node && typeof node === "object") {
    found.push(node);
    node.children.forEach((child) => walk(child, found));
  }
  return found;
};
const has = (node, name) => (node.attrs.class || "").split(" ").includes(name);
const settle = async () => {
  for (let round = 0; round < 5; round += 1) {
    await new Promise((resolve) => setImmediate(resolve));
  }
};
const read = () => {
  const all = walk(context.screen, []);
  const charts = all.filter((node) => has(node, "res-chart"));
  const marks = (kind) => all.filter((node) => has(node, "res-mark") && has(node, kind)).map((node) => [Number(node.attrs["data-from"]), Number(node.attrs["data-to"])]);
  return {
    count: all.find((node) => node.attrs["aria-label"] === "Samples").textContent,
    panels: all.filter((node) => has(node, "res-panel")).map((node) => [node.attrs["data-panel"], node.hidden]),
    charts: charts.map((chart) => [chart.attrs["data-chart"], chart.attrs["data-from"], chart.attrs["data-to"]]),
    bands: charts.map((chart) => walk(chart, []).filter((node) => has(node, "band")).map((node) => node.attrs["data-zone"])),
    lines: [...new Set(all.filter((node) => has(node, "res-line")).map((node) => `${node.attrs["data-series"]}|${node.attrs["data-kind"]}`))],
    ids: [...new Set(all.filter((node) => has(node, "res-line")).map((node) => node.attrs["data-id"]))],
    waits: marks("wait"),
    blocked: marks("blocked"),
    hung: marks("hung"),
    asleep: marks("asleep"),
    unknown: marks("unknown"),
    words: all.filter((node) => has(node, "res-mark") && has(node, "unknown")).map((node) => node.children[0].children.join("")),
    queueWords: all.filter((node) => has(node, "res-mark") && ["wait", "blocked", "hung"].some((kind) => has(node, kind))).map((node) => node.children[0].children.join("")),
    clickable: all.filter((node) => has(node, "res-mark") && node.listeners.click).map((node) => node.attrs.class),
    lanes: [...new Set(all.filter((node) => node.tag === "use" && has(node, "res-icon")).map((node) => [node.attrs.class, node.attrs.href, Number(node.attrs.y)].join("|")))],
    bars: all.filter((node) => has(node, "res-bar")).map((node) => [node.attrs["data-agent"], Number(node.attrs["data-t"]), has(node, "faint")]),
    sums: all.filter((node) => has(node, "res-sum")).map((node) => [node.attrs["data-agent"], JSON.parse(node.attrs["data-points"])]),
    burn: all.filter((node) => node.tag === "path" && has(node, "res-burn")).map((node) => [node.attrs["data-series"], Number(node.attrs["data-last"]), Number(node.attrs["data-top"])]),
    right: all.filter((node) => node.attrs["data-axis"] === "right").map((node) => node.children.join("")),
    chips: all.filter((node) => has(node, "legend-chip")).map((node) => [node.attrs["data-chip"], node.attrs["data-path"], node.attrs["aria-pressed"], node.textContent]),
    switches: all.filter((node) => has(node, "res-switch")).map((node) => [node.attrs["data-switch"], node.attrs["aria-pressed"]]),
    picks: all.filter((node) => node.attrs["data-pick"]).map((node) => [node.attrs["data-pick"], Boolean(node.checked), Boolean(node.disabled)]),
    accounts: textOf(all.find((node) => has(node, "acc-body"))),
    titles: all.filter((node) => has(node, "res-title")).map((node) => [node.attrs.title, node.attrs["aria-label"], node.children[0].attrs["data-icon"]]),
  };
};
const press = (selector) => walk(context.screen, []).find(selector).listeners.click();
const pick = (kind, on) => {
  const box = walk(context.screen, []).find((node) => node.attrs["data-pick"] === kind);
  box.checked = on;
  box.listeners.change();
};
const textOf = (node) => node.children.map((child) => (typeof child === "object" ? textOf(child) : String(child))).join("");
const sheetOf = ({title, body, wide}) => {
  const nodes = body.flatMap((node) => walk(node, []));
  return {
    title, wide,
    heads: nodes.filter((node) => node.attrs["data-head"]).map((node) => [node.attrs["data-head"], Number(node.attrs["data-from"]), Number(node.attrs["data-to"]), textOf(node.children[1])]),
    hung: nodes.filter((node) => node.attrs["data-hung"]).map((node) => node.attrs["data-hung"]),
    counts: nodes.filter((node) => has(node, "count")).map(textOf),
  };
};
(async () => {
  await settle();
  const normal = read();
  press((node) => has(node, "res-mark") && has(node, "blocked"));
  press((node) => has(node, "res-mark") && has(node, "hung"));
  press((node) => has(node, "res-mark") && has(node, "hung") && node.attrs["data-from"] === String(T + 5000));
  normal.sheets = sheets.map(sheetOf);
  press((node) => node.attrs["data-chip"] === "host:CPU");
  press((node) => node.attrs["data-chip"] === "agent:Stage");
  const hidden = read();
  press((node) => node.attrs["data-switch"] === "tokens");
  const accumulated = read();
  pick("combined", true);
  pick("hardware", false);
  pick("tokens", false);
  const combined = read();
  press((node) => node.attrs["data-chip"] === "burn:scope" && node.attrs["data-path"] === "resources.combinedHidden");
  press((node) => node.attrs["data-chip"] === "util:0000_3a_01_3a_00.0" && node.attrs["data-path"] === "resources.combinedHidden");
  const deselected = read();
  pick("accounts", false);
  const last = read();
  await new Promise((resolve) => setTimeout(resolve, 400));
  await settle();
  console.log(JSON.stringify({fetched, normal, hidden, accumulated, combined, deselected, last, stored: context.store.get("resources")}));
})();
""".replace("@FIXTURE@", FIXTURE)


class TestResourcesModule(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        done = subprocess.run(["node", "-e", PROBE, str(MODULE), str(T)], capture_output=True, text=True, timeout=60, check=True)
        cls.data = json.loads(done.stdout)

    def test_bands_mark_idle_below_thirty_and_saturated_above_ninety_percent(self):
        self.assertEqual(self.data["zones"], [{"kind": "idle", "from": 0, "to": 30}, {"kind": "saturated", "from": 90, "to": 100}])

    def test_disks_cpu_ram_swap_gpu_and_vram_become_percent_lines_on_one_time_axis(self):
        times = [T, T + 60, T + 120, T + 180, T + 240, T + 300, T + 5000, T + 5060]
        self.assertEqual(self.data["disks"], [["/", "disk", [[t, 25] for t in times]], ["/mnt", "disk", [[T + 120, 25]]]])
        self.assertEqual([name for name, _, _ in self.data["host"]], ["CPU", "RAM", "Swap"])
        self.assertEqual(self.data["host"][0][2], [[t, cpu] for t, cpu in zip(times, (20, 40, 45, 70, 30, 35, 10, 10), strict=True)])
        gpu, vram = self.data["gpu"]
        self.assertEqual((gpu[0], gpu[1], vram[0], vram[1]), ("0000:01:00.0", "util", "0000:01:00.0", "vram"))
        self.assertEqual(gpu[2], [[T, None], [T + 60, None], [T + 120, 80], [T + 180, 90], [T + 240, 10], [T + 300, None], [T + 5000, None], [T + 5060, None]])
        self.assertEqual(vram[2][2:5], [[T + 120, 50], [T + 180, 60], [T + 240, 10]])

    def test_a_line_breaks_at_a_missing_value_and_at_a_gap_of_more_than_half_an_hour(self):
        self.assertEqual(self.data["segments"], [[[T, 1]], [[T + 120, 3], [T + 180, 4]], [[T + 4000, 5]]])

    def test_a_marker_spans_rows_where_jobs_waited_while_cpu_and_ram_stayed_under_half(self):
        self.assertEqual(self.data["waits"], [{"from": T + 60, "to": T + 180, "peak": 3}, {"from": T + 240, "to": T + 300, "peak": 1}, {"from": T + 5000, "to": T + 5060, "peak": 1}])

    def test_a_blocked_span_needs_a_head_that_waited_ten_minutes_and_keeps_its_last_reason_and_steps(self):
        self.assertEqual(self.data["threshold"], 600)
        self.assertEqual(self.data["blocked"], [
            {
                "from": T + 240, "to": T + 360, "peak": 660, "head": QH, "reason": RAM,
                "steps": [{"id": QH, "reason": ESCALATED, "from": T + 240, "to": T + 240}, {"id": QH, "reason": RAM, "from": T + 300, "to": T + 300}],
                "hung": ["test-1001"],
            },
            {"from": T + 5060, "to": T + 5120, "peak": 1200, "head": "deploy-1003", "reason": BEHIND, "steps": [{"id": "deploy-1003", "reason": BEHIND, "from": T + 5060, "to": T + 5060}], "hung": []},
        ])

    def test_a_head_under_ten_minutes_or_without_an_id_or_a_numeric_wait_is_not_blocked(self):
        self.assertEqual(self.data["under"], [])

    def test_a_hung_span_marks_rows_listing_a_suspect_hung_job_independent_of_the_head(self):
        self.assertEqual(self.data["hung"], [
            {"from": T + 300, "to": T + 360, "peak": 1, "steps": [{"id": QH, "reason": RAM, "from": T + 300, "to": T + 300}], "hung": ["test-1001"]},
            {"from": T + 5000, "to": T + 5060, "peak": 1, "steps": [], "hung": ["test-1001"]},
        ])
        self.assertEqual(self.data["quiet"], [])

    def test_an_asleep_gpu_gets_its_own_spans(self):
        self.assertEqual(self.data["asleep"],[{"name": "0000:01:00.0", "spans": [{"from": T, "to": T + 120, "peak": 1}, {"from": T + 5000, "to": T + 5120, "peak": 1}]}])

    def test_an_awake_gpu_without_a_reading_gets_unknown_spans_apart_from_asleep_ones(self):
        self.assertEqual(self.data["unknown"], [{"name": "0000:01:00.0", "spans": [{"from": T + 300, "to": T + 360, "peak": 1, "causes": [MISMATCH]}]}])

    def test_an_unknown_span_names_each_distinct_nvidia_smi_error_of_its_rows_once(self):
        self.assertEqual(self.data["causeless"], [{"name": "0000:01:00.0", "spans": [
            {"from": T, "to": T + 180, "peak": 1, "causes": ["other"]},
            {"from": T + 240, "to": T + 300, "peak": 1, "causes": [MISMATCH]},
        ]}])

    def test_tokens_stack_per_hour_with_the_biggest_agent_at_the_bottom(self):
        stack = self.data["stack"]
        self.assertEqual((stack["agents"], stack["top"]), (["Stage", "Skills"], 500))
        first, second = stack["bars"]
        self.assertEqual((first["t"], first["total"]), (T, 385))
        self.assertEqual([(part["agent"], part["from"], part["to"], part["models"]) for part in first["parts"]], [("Stage", 0, 10, ["opus"]), ("Skills", 10, 385, ["opus", "haiku"])])
        self.assertEqual({key: first["parts"][1][key] for key in ("input", "output", "cache_read", "cache_write")}, {"input": 15, "output": 20, "cache_read": 300, "cache_write": 40})
        self.assertEqual((second["t"], [(part["agent"], part["to"]) for part in second["parts"]]), (T + 3600, [("Stage", 500)]))

    def test_the_hardware_series_merge_disks_host_and_gpu_lines_onto_one_axis(self):
        self.assertEqual(self.data["hardware"], [["/", "disk", 8], ["/mnt", "disk", 1], ["CPU", "host", 8], ["RAM", "host", 8], ["Swap", "host", 8], ["0000:01:00.0", "util", 8], ["0000:01:00.0", "vram", 8]])

    def test_accumulated_tokens_are_per_agent_running_sums_from_zero_at_each_hour_end(self):
        found = self.data["accumulated"]
        self.assertEqual((found["agents"], found["top"]), (["Stage", "Skills"], 510))
        self.assertEqual(found["lines"], [{"agent": "Stage", "points": [[T, 0], [T + 3600, 10], [T + 7200, 510]]}, {"agent": "Skills", "points": [[T, 0], [T + 3600, 375], [T + 7200, 375]]}])

    def test_accumulated_sums_never_decrease_and_end_at_each_agents_total(self):
        many = self.data["many"]
        self.assertTrue(many["rising"])
        self.assertEqual(many["finals"], many["totals"])
        self.assertEqual(many["top"], max(many["totals"].values()))
        self.assertEqual(len(many["lengths"]), 1)

    def test_burnup_scales_done_and_scope_to_percent_of_the_largest_scope_in_the_window(self):
        found = self.data["burnup"]
        self.assertEqual(found["top"], 5)
        self.assertEqual(found["done"], [[1, 0], [2, 20], [3, 100], [4, 80]])
        self.assertEqual(found["scope"], [[1, 40], [2, 80], [3, 100], [4, 80]])
        self.assertEqual(self.data["empty"], {"top": 0, "done": [[1, 0]], "scope": [[1, 0]]})


LINES = ["/|disk", "/mnt|disk", "CPU|host", "RAM|host", "Swap|host", "0000:01:00.0|util", "0000:01:00.0|vram"]
GPU_ID = "0000_3a_01_3a_00.0"
HARDWARE_CHIPS = [["disk:/", "/ 25 %"], ["disk:/mnt", "/mnt 25 %"], ["host:CPU", "CPU 10 %"], ["host:RAM", "RAM 10 %"], ["host:Swap", "Swap 0 %"], [f"util:{GPU_ID}", "0000:01:00.0 10 %"], [f"vram:{GPU_ID}", "0000:01:00.0 VRAM 10 %"]]
AGENT_CHIPS = [["agent:Stage", "Stage 510"], ["agent:Skills", "Skills 375"]]


def chips(entries: list[list[str]], path: str, hidden: set[str]) -> list[list[str]]:
    return [[chip, path, "false" if chip in hidden else "true", label] for chip, label in entries]


class TestResourcesPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sources = [str(HUB / "templates" / name) for name in ("view-store.js", "legend-chips.js", "page-resources.js", "page-limits.js", "page-accounts.js", "page-usage.js", "page-account-bar.js")]
        done = subprocess.run(["node", "-e", PAGE_PROBE, str(MODULE), str(PLAN), *sources, str(T)], capture_output=True, text=True, timeout=60, check=False)
        if done.returncode != 0:
            raise AssertionError(done.stderr[-2000:])
        cls.found = json.loads(done.stdout)

    def test_normal_mode_draws_exactly_a_hardware_and_a_tokens_chart_on_one_time_axis(self):
        found = self.found["normal"]
        self.assertEqual(found["count"], "8")
        self.assertEqual(found["panels"], [["resources-hardware", False], ["resources-tokens", False], ["resources-combined", True], ["resources-accounts", False], ["resources-usage", True]])
        self.assertEqual(found["picks"], [["hardware", True, False], ["tokens", True, False], ["combined", False, False], ["accounts", True, False], ["usage", False, False]])
        self.assertIn("No account yet", found["accounts"])
        axis = [str(T - 600), str(T + 6000)]
        self.assertEqual(found["charts"], [["hardware", *axis], ["tokens", *axis]])
        self.assertEqual(found["bands"], [["idle", "saturated"], []])
        self.assertEqual(found["lines"], LINES)
        self.assertEqual(found["waits"], [[T + 60, T + 180], [T + 240, T + 300], [T + 5000, T + 5060]])
        self.assertEqual(found["asleep"], [[T, T + 120], [T + 5000, T + 5120]])
        self.assertEqual((found["unknown"], found["words"]), ([[T + 300, T + 360]], [f"0000:01:00.0 unknown: {MISMATCH}"]))
        self.assertEqual(found["bars"], [["Stage", T, False], ["Skills", T, False], ["Stage", T + 3600, False]])
        self.assertEqual(found["chips"], chips(HARDWARE_CHIPS + AGENT_CHIPS, "resources.hidden", set()))
        self.assertEqual(found["switches"], [["tokens", "false"]])
        names = [("Hardware: disks, CPU, RAM, swap, GPU and VRAM", "bi-cpu"), ("Tokens per agent", "bi-coin"), ("Hardware, tokens and burnup", "bi-layers"), ("Accounts", "bi-person-badge"), ("Usage", "bi-pie-chart")]
        self.assertEqual(found["titles"], [[name, name, icon] for name, icon in names])

    def test_blocked_and_hung_marks_sit_in_lanes_of_their_own_and_name_head_wait_reason_and_ids(self):
        found = self.found["normal"]
        self.assertEqual((found["blocked"], found["hung"]), ([[T + 240, T + 360], [T + 5060, T + 5120]], [[T + 300, T + 360], [T + 5000, T + 5060]]))
        idle = "jobs waited while CPU and RAM stayed under 50 %"
        self.assertEqual(found["queueWords"], [
            f"Idle waiting: 3 {idle}", f"Idle waiting: 1 {idle}", f"Idle waiting: 1 {idle}",
            f"{QH} waited 11 min: {RAM}", f"deploy-1003 waited 20 min: {BEHIND}", "suspect hung: test-1001", "suspect hung: test-1001",
        ])
        self.assertEqual(found["clickable"], ["res-mark blocked"] * 2 + ["res-mark hung"] * 2)
        self.assertEqual(found["lanes"], [
            "res-icon wait|#bi-hourglass-split|8", "res-icon blocked|#bi-sign-stop|21", "res-icon hung|#bi-pause-circle|34", "res-icon asleep|#bi-moon|8", "res-icon unknown|#bi-question-circle|8",
        ])

    def test_a_click_on_a_blocked_or_hung_mark_opens_a_sheet_of_each_head_reason_with_its_first_and_last_time_and_the_hung_ids(self):
        blocked, hung, alone = self.found["normal"]["sheets"]
        self.assertEqual(blocked, {"title": f"{QH} waited 11 min", "wide": False, "heads": [[QH, T + 240, T + 240, ESCALATED], [QH, T + 300, T + 300, RAM]], "hung": ["test-1001"], "counts": ["2", "1"]})
        self.assertEqual(hung, {"title": "Suspect hung: test-1001", "wide": False, "heads": [[QH, T + 300, T + 300, RAM]], "hung": ["test-1001"], "counts": ["1", "1"]})
        self.assertEqual(alone, {"title": "Suspect hung: test-1001", "wide": False, "heads": [], "hung": ["test-1001"], "counts": ["0", "1"]})

    def test_hiding_a_chip_removes_its_line_or_its_agent_and_stores_the_list(self):
        found = self.found["hidden"]
        self.assertEqual(found["lines"], [line for line in LINES if line != "CPU|host"])
        self.assertEqual(found["bars"], [["Skills", T, False]])
        self.assertEqual(found["chips"], chips(HARDWARE_CHIPS + AGENT_CHIPS, "resources.hidden", {"host:CPU", "agent:Stage"}))

    def test_the_accumulated_switch_draws_running_sums_of_the_shown_agents_instead_of_bars(self):
        found = self.found["accumulated"]
        self.assertEqual((found["bars"], found["sums"]), ([], [["Skills", [0, 375]]]))
        self.assertEqual(found["switches"], [["tokens", "true"]])

    def test_the_panels_menu_shows_the_combined_chart_with_every_series_switched_on_instead_of_both(self):
        found = self.found["combined"]
        self.assertEqual(found["panels"], [["resources-hardware", True], ["resources-tokens", True], ["resources-combined", False], ["resources-accounts", False], ["resources-usage", True]])
        self.assertEqual(found["charts"], [["combined", str(T - 600), str(T + 6000)]])
        self.assertEqual(found["lines"], LINES)
        self.assertEqual(found["sums"], [["Stage", [0, 10, 510]], ["Skills", [0, 375, 375]]])
        self.assertEqual(found["right"], ["0", "510"])
        (done, done_last, done_top), (scope, scope_last, scope_top) = found["burn"]
        self.assertEqual((done, scope, done_top, scope_top, scope_last), ("done", "scope", 3, 3, 100))
        self.assertAlmostEqual(done_last, 200 / 3)
        burn = [["burn:done", "Done 67 %"], ["burn:scope", "Scope 100 %"]]
        self.assertEqual(found["chips"], chips(HARDWARE_CHIPS + AGENT_CHIPS + burn, "resources.combinedHidden", set()))
        self.assertEqual(found["picks"], [["hardware", False, False], ["tokens", False, False], ["combined", True, False], ["accounts", True, False], ["usage", False, False]])

    def test_the_last_checked_panel_cannot_be_switched_off(self):
        found = self.found["last"]
        self.assertEqual(found["panels"], [["resources-hardware", True], ["resources-tokens", True], ["resources-combined", False], ["resources-accounts", True], ["resources-usage", True]])
        self.assertEqual(found["picks"], [["hardware", False, False], ["tokens", False, False], ["combined", True, True], ["accounts", False, False], ["usage", False, False]])

    def test_each_combined_series_is_deselectable_and_every_switch_is_stored_in_one_patch(self):
        found = self.found["deselected"]
        self.assertEqual([series for series, _, _ in found["burn"]], ["done"])
        self.assertEqual(found["lines"], [line for line in LINES if line != "0000:01:00.0|util"])
        stored = {"hidden": ["host:CPU", "agent:Stage"], "tokens": "accumulated", "panels": ["combined"], "combinedHidden": ["burn:scope", f"util:{GPU_ID}"]}
        self.assertEqual(self.found["stored"], stored)
        changes = {f"resources.{key}": value for key, value in stored.items()}
        self.assertEqual(self.found["fetched"], ["/api/resources?from=1", "/api/accounts", ["PATCH", "/api/view", changes]])


AXIS_PROBE = """
const fs = require("fs");
const vm = require("vm");
const s = (tag, attrs, ...children) => ({tag, attrs, children: children.flat(), append(...more) { this.children.push(...more); }});
const Resources = require(require("path").join(require("path").dirname(process.argv[1]), "resources.js"));
const context = {s, h: s, DAY: 86400, Resources, fixed: (value) => value.toFixed(1), stampOf: (t) => t, absolute: {format: () => "14 Nov 2026, 10:00"}, clock: {format: () => "10:00"}};
vm.runInNewContext(`${fs.readFileSync(process.argv[1], "utf8")}\\nglobalThis.frame = resourceFrame;`, context);
const labels = (width, days) => context.frame({kind: "tokens", label: "Tokens"}, {from: 0, to: days * 86400}, {width, height: 120}, false).svg.children
  .filter((node) => node.tag === "text").map((node) => [Number(node.attrs.x), node.attrs["text-anchor"], node.children.join("")]);
console.log(JSON.stringify([[1600, 2], [390, 2], [340, 2], [150, 2], [340, 0.5]].map(([width, days]) => labels(width, days))));
"""
GLYPH = 6.2


class TestResourcesAxis(unittest.TestCase):
    def test_time_labels_never_overlap_and_a_plot_too_narrow_for_two_keeps_the_last(self):
        done = subprocess.run(["node", "-e", AXIS_PROBE, str(PAGE)], capture_output=True, text=True, timeout=60, check=True)
        found = json.loads(done.stdout)
        self.assertEqual([len(labels) for labels in found], [5, 2, 2, 1, 5])
        self.assertEqual(found[3][0][1:], ["end", "14 Nov 2026, 10:00"])
        for labels in found:
            spans = sorted((x - {"start": 0, "middle": 0.5, "end": 1}[anchor] * len(words) * GLYPH, x + {"start": 1, "middle": 0.5, "end": 0}[anchor] * len(words) * GLYPH) for x, anchor, words in labels)
            with self.subTest(labels=labels):
                self.assertTrue(all(left[1] <= right[0] for left, right in itertools.pairwise(spans)), spans)


class TestHubResources(HubCase):
    def write(self, name: str, rows: list[dict], tail: str = "") -> None:
        folder = self.kept / "resources"
        folder.mkdir(exist_ok=True)
        (folder / name).write_text(self.jsonl(rows) + tail, encoding="utf-8")

    def fetch(self, query: str) -> tuple[int, bytes]:
        status, _, body = self.get(f"/api/resources?{query}")
        return status, body

    def test_the_view_reads_only_the_sampler_files_within_the_window(self):
        samples = [{"t": T + step, "cpu": step / 60, "ram": 1, "swap": 0, "load": 0, "disks": [], "gpus": [], "queue": {"waiting": 0, "active": 0}} for step in (0, 60, 120, 180)]
        tokens = [{"t": T - 3600, "agent": "Skills", "model": "opus", "input": 1, "output": 0, "cache_read": 0, "cache_write": 0}, {"t": T + 3600, "agent": "Skills", "model": "opus", "input": 2, "output": 0, "cache_read": 0, "cache_write": 0}]
        self.write("samples.jsonl", samples, "{broken\n[1]\n")
        self.write("tokens.jsonl", tokens)
        status, body = self.fetch(f"from={T + 60}&to={T + 120}")
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body), {"since": T + 60, "until": T + 120, "samples": samples[1:3], "tokens": []})
        status, body = self.fetch(f"from={T - 1800}&to={T + 3600}")
        self.assertEqual(json.loads(body)["tokens"], tokens)
        self.assertEqual(json.loads(body)["samples"], samples)

    def test_missing_files_answer_empty_rows_and_a_reversed_window_is_refused(self):
        status, body = self.fetch("")
        self.assertEqual(status, 200, body)
        found = json.loads(body)
        self.assertEqual((found["samples"], found["tokens"]), ([], []))
        self.assertAlmostEqual(found["until"] - found["since"], 86400)
        self.assertLess(abs(found["until"] - time.time()), 30)
        self.assertEqual(self.fetch(f"from={T + 10}&to={T}")[0], 400)
        self.assertEqual(self.fetch("from=x")[0], 400)

    def test_the_page_carries_the_resources_tab_module_view_and_icons(self):
        html = self.index()
        self.assertIn(MODULE.read_text(encoding="utf-8").strip(), html)
        self.assertIn(PAGE.read_text(encoding="utf-8").strip(), html)
        self.assertIn(STYLE.read_text(encoding="utf-8").strip(), html)
        for name in ("speedometer2", "cpu", "coin", "layers", "graph-up-arrow", "hourglass-split", "sign-stop", "pause-circle", "moon", "question-circle"):
            with self.subTest(icon=name):
                self.assertIn(f'<symbol id="bi-{name}"', html)
        done = subprocess.run(["node", "-e", "const N = require(process.argv[1]); console.log(JSON.stringify([N.TABS.at(-1), N.ICONS.resources, N.route('#resources')]));", str(NAV)], capture_output=True, text=True, timeout=60, check=True)
        self.assertEqual(json.loads(done.stdout), [["resources", "Resources"], "bi-speedometer2", {"screen": "resources", "view": None, "redirect": None}])


if __name__ == "__main__":
    unittest.main()
