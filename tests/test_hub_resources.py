from __future__ import annotations

import json
import subprocess
import time
import unittest

from hub_case import HubCase
from hub_support import HUB, NAV

MODULE = HUB / "templates" / "resources.js"
PAGE = HUB / "templates" / "page-resources.js"
STYLE = HUB / "templates" / "style-resources.css"
T = 1_760_000_000
FIXTURE = """
const asleep = {name: "0000:01:00.0", asleep: true};
const awake = (util, used) => ({name: "0000:01:00.0", util, vram_used: used, vram_total: 1000});
const unread = {name: "0000:01:00.0", util: null, vram_used: null, vram_total: null};
const row = (t, cpu, ram, waiting, gpu, disks) => ({t, cpu, ram, swap: 0, load: 1, disks, gpus: [gpu], queue: {waiting, active: 1}});
const root = [{mount: "/", used: 250, total: 1000}];
const samples = [
  row(T, 20, 30, 0, asleep, root),
  row(T + 60, 40, 45, 2, asleep, root),
  row(T + 120, 45, 40, 3, awake(80, 500), [...root, {mount: "/mnt", used: 1, total: 4}]),
  row(T + 180, 70, 40, 3, awake(90, 600), root),
  row(T + 240, 30, 30, 1, awake(10, 100), root),
  row(T + 300, 35, 30, 0, unread, root),
  row(T + 5000, 10, 10, 1, asleep, root),
  row(T + 5060, 10, 10, 0, asleep, root),
];
const tokens = [
  {t: T, agent: "Skills", model: "opus", input: 10, output: 20, cache_read: 300, cache_write: 40},
  {t: T, agent: "Stage", model: "opus", input: 1, output: 2, cache_read: 3, cache_write: 4},
  {t: T, agent: "Skills", model: "haiku", input: 5, output: 0, cache_read: 0, cache_write: 0},
  {t: T + 3600, agent: "Stage", model: "opus", input: 500, output: 0, cache_read: 0, cache_write: 0},
  {t: "x", agent: "Bad", model: "opus", input: 1, output: 0, cache_read: 0, cache_write: 0},
];
"""
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
  asleep: R.asleep(samples),
  unknown: R.unknown(samples),
  stack: R.stack(tokens),
}));
""".replace("@FIXTURE@", FIXTURE)
PAGE_PROBE = """
const fs = require("fs");
const vm = require("vm");
const Resources = require(process.argv[1]);
const code = fs.readFileSync(process.argv[2], "utf8");
const T = Number(process.argv[3]);
@FIXTURE@
const make = (tag, attrs, children) => {
  const node = {tag, attrs: {}, children: [], textContent: "", isConnected: true,
    append(...items) { this.children.push(...items); },
    replaceChildren(...items) { this.children = items; },
    getBoundingClientRect() { return {width: 800, height: 120}; }};
  for (const [key, value] of Object.entries(attrs)) {
    if (key !== "on" && value !== null && value !== undefined && value !== false) {
      node.attrs[key] = String(value);
    }
  }
  node.children = children.flat(Infinity).filter((child) => child !== null && child !== undefined && child !== false);
  return node;
};
const h = (tag, attrs, ...children) => make(tag, attrs, children);
const icon = (name) => make("svg", {class: "bi", "data-icon": name}, []);
const fetched = [];
const context = {
  Resources, h, s: h, icon, DAY: 86400, ui: {preset: 86400, from: null, to: null, asOf: null, offline: false},
  iconBtn: (name, label, cls, run, hint) => make("button", {title: hint, "aria-label": label}, [icon(name)]),
  fixed: (value) => value.toFixed(1), dash: (value) => (value === null ? "–" : value), absolute: {format: () => "d"}, clock: {format: () => "c"}, stampOf: (t) => new Date(t * 1000),
  window: {setTimeout: (run) => run(), setInterval: () => 1, addEventListener: () => null}, document: {hidden: false},
  windowQuery: () => "from=1", nowSeconds: () => 0,
  fetch: async (url) => {
    fetched.push(url);
    return {ok: true, json: async () => ({since: T - 600, until: T + 6000, samples, tokens})};
  },
};
vm.runInNewContext(`${code}\\nscreen = resourcesScreen();`, context);
const walk = (node, found) => {
  if (node && typeof node === "object") {
    found.push(node);
    node.children.forEach((child) => walk(child, found));
  }
  return found;
};
const has = (node, name) => (node.attrs.class || "").split(" ").includes(name);
(async () => {
  for (let round = 0; round < 5; round += 1) {
    await new Promise((resolve) => setImmediate(resolve));
  }
  const all = walk(context.screen, []);
  const charts = all.filter((node) => has(node, "res-chart"));
  const marks = (kind) => all.filter((node) => has(node, "res-mark") && has(node, kind)).map((node) => [Number(node.attrs["data-from"]), Number(node.attrs["data-to"])]);
  console.log(JSON.stringify({
    fetched,
    count: all.find((node) => node.attrs["aria-label"] === "Samples").textContent,
    charts: charts.map((chart) => [chart.attrs["data-panel"], chart.attrs["data-from"], chart.attrs["data-to"]]),
    bands: charts.map((chart) => walk(chart, []).filter((node) => has(node, "band")).map((node) => node.attrs["data-zone"])),
    lines: [...new Set(all.filter((node) => has(node, "res-line")).map((node) => `${node.attrs["data-series"]}|${node.attrs["data-kind"]}`))],
    waits: marks("wait"),
    asleep: marks("asleep"),
    unknown: marks("unknown"),
    words: all.filter((node) => has(node, "res-mark") && has(node, "unknown")).map((node) => node.children[0].children.join("")),
    bars: all.filter((node) => has(node, "res-bar")).map((node) => [node.attrs["data-agent"], Number(node.attrs["data-t"])]),
    legends: all.filter((node) => has(node, "res-key")).map((node) => node.children.join("")),
    titles: all.filter((node) => has(node, "res-title")).map((node) => [node.attrs.title, node.attrs["aria-label"], node.children[0].attrs["data-icon"]]),
  }));
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

    def test_an_asleep_gpu_gets_its_own_spans(self):
        self.assertEqual(self.data["asleep"], [{"name": "0000:01:00.0", "spans": [{"from": T, "to": T + 120, "peak": 1}, {"from": T + 5000, "to": T + 5120, "peak": 1}]}])

    def test_an_awake_gpu_without_a_reading_gets_unknown_spans_apart_from_asleep_ones(self):
        self.assertEqual(self.data["unknown"], [{"name": "0000:01:00.0", "spans": [{"from": T + 300, "to": T + 360, "peak": 1}]}])

    def test_tokens_stack_per_hour_with_the_biggest_agent_at_the_bottom(self):
        stack = self.data["stack"]
        self.assertEqual((stack["agents"], stack["top"]), (["Stage", "Skills"], 500))
        first, second = stack["bars"]
        self.assertEqual((first["t"], first["total"]), (T, 385))
        self.assertEqual([(part["agent"], part["from"], part["to"], part["models"]) for part in first["parts"]], [("Stage", 0, 10, ["opus"]), ("Skills", 10, 385, ["opus", "haiku"])])
        self.assertEqual({key: first["parts"][1][key] for key in ("input", "output", "cache_read", "cache_write")}, {"input": 15, "output": 20, "cache_read": 300, "cache_write": 40})
        self.assertEqual((second["t"], [(part["agent"], part["to"]) for part in second["parts"]]), (T + 3600, [("Stage", 500)]))


class TestResourcesPage(unittest.TestCase):
    def test_the_view_draws_four_panels_on_one_time_axis_from_the_api_rows_alone(self):
        done = subprocess.run(["node", "-e", PAGE_PROBE, str(MODULE), str(PAGE), str(T)], capture_output=True, text=True, timeout=60, check=True)
        found = json.loads(done.stdout)
        self.assertEqual((found["fetched"], found["count"]), (["/api/resources?from=1"], "8"))
        axis = [str(T - 600), str(T + 6000)]
        self.assertEqual(found["charts"], [[panel, *axis] for panel in ("disks", "host", "gpu", "tokens")])
        self.assertEqual(found["bands"], [["idle", "saturated"]] * 3 + [[]])
        self.assertEqual(found["lines"], ["/|disk", "/mnt|disk", "CPU|host", "RAM|host", "Swap|host", "0000:01:00.0|util", "0000:01:00.0|vram"])
        self.assertEqual(found["waits"], [[T + 60, T + 180], [T + 240, T + 300], [T + 5000, T + 5060]])
        self.assertEqual(found["asleep"], [[T, T + 120], [T + 5000, T + 5120]])
        self.assertEqual((found["unknown"], found["words"]), ([[T + 300, T + 360]], ["0000:01:00.0 unknown: no reading"]))
        self.assertEqual(found["bars"], [["Stage", T], ["Skills", T], ["Stage", T + 3600]])
        self.assertEqual(found["legends"], ["/ 25 %", "/mnt 25 %", "CPU 10 %", "RAM 10 %", "Swap 0 %", "0000:01:00.0 10 %", "0000:01:00.0 VRAM 10 %", "Stage 510", "Skills 375"])
        names = [("Disks", "bi-hdd-stack"), ("CPU, RAM and swap", "bi-cpu"), ("GPU and VRAM", "bi-gpu-card"), ("Tokens per agent", "bi-coin")]
        self.assertEqual(found["titles"], [[name, name, icon] for name, icon in names])


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
        for name in ("speedometer2", "hdd-stack", "cpu", "gpu-card", "coin", "hourglass-split", "moon", "question-circle"):
            with self.subTest(icon=name):
                self.assertIn(f'<symbol id="bi-{name}"', html)
        done = subprocess.run(["node", "-e", "const N = require(process.argv[1]); console.log(JSON.stringify([N.TABS.at(-1), N.ICONS.resources, N.route('#resources')]));", str(NAV)], capture_output=True, text=True, timeout=60, check=True)
        self.assertEqual(json.loads(done.stdout), [["resources", "Resources"], "bi-speedometer2", {"screen": "resources", "view": None, "redirect": None}])


if __name__ == "__main__":
    unittest.main()
