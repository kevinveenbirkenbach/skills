"""Exercise requirements 084 and 091: limit lines dragged on the Hardware chart, staged changes with one Save and the passkey to loosen, the Limits and View menus, the right-click matrix, the tooltips and the GPU cause."""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

import hub_e2e_kit as base
import test_workbench_w4_e2e as w4
from hub_case import HubCase
from kvb_orchestrator import limiting

OUT = Path(os.environ.get("E2E_OUT", "/tmp/hub-091-shots"))
LEVELS = ("lower", "upper", "stop", "mayday")
NAMES = ("lower", "upper", "STOP", "MAYDAY")
PROFILES = {name: {metric: dict(zip(LEVELS, values, strict=True)) for metric, values in table.items()} for name, table in limiting.PROFILE_TABLE.items()}
TARGET = {"cpu": 84.0, "ram": 80.5, "psi": 0.2, "stepped": 1, "samples": []}
MISMATCH = "Failed to initialize NVML: Driver/library version mismatch"
BLOCKED = (200, 215)
HUNG = (230, 240)
ORDER = "breaks lower < upper < STOP < MAYDAY"
UPPER = "upper: the queue starts no job whose footprint would lift the load above it"
READ = """
  const FRAME = 6;
  const chart = () => document.querySelector('#main svg.res-chart[data-chart="hardware"]');
  const lines = () => all("g.res-limit", chart() || document).map((node) => ({
    metric: node.dataset.metric, level: node.dataset.level, value: Number(node.dataset.value), label: text(node.querySelector("text")), title: text(node.querySelector("title")),
    moved: node.classList.contains("moved"), was: Boolean(node.querySelector(".res-limit-was")), dash: getComputedStyle(node.querySelector(".res-limit-mark")).strokeDasharray,
    role: node.getAttribute("role"), now: node.getAttribute("aria-valuenow"),
  }));
  const target = () => all("g.res-target", chart() || document).map((node) => [node.dataset.metric, Number(node.dataset.value), text(node.querySelector("text")), text(node.querySelector("title"))]);
  const line = (level) => (chart() ? chart().querySelector(`g.res-limit.${level}`) : null);
  const pressed = (group) => all(`#main [aria-label="${group}"] button[aria-pressed="true"]`).map(text);
  const button = (group, label) => all(`#main [aria-label="${group}"] button`).find((node) => text(node) === label);
  const sheet = () => {
    const box = document.querySelector("#sheet:not([hidden]) .sheet-box");
    return box ? box.getAttribute("aria-label") : null;
  };
  const stage = (root) => {
    const bar = (root || document.querySelector("#main .res-limits")).querySelector(".limit-stage");
    const error = bar.querySelector(".limit-error");
    return {shown: !bar.hidden, save: text(bar.querySelector(".limit-save")), disabled: bar.querySelector(".limit-save").disabled, error: error.hidden ? null : text(error), note: text(bar.querySelector(".limit-stage-note"))};
  };
  const yOf = (value) => {
    const svg = chart();
    const box = svg.getBoundingClientRect();
    const height = svg.viewBox.baseVal.height;
    return box.top + Limits.pixelOf(value, FRAME, height - FRAME) * box.height / height;
  };
  const drag = async (level, value) => {
    const node = line(level);
    const box = node.ownerSVGElement.getBoundingClientRect();
    const at = (y, buttons) => ({clientX: box.left + box.width / 2, clientY: y, pointerId: 7, pointerType: "touch", isPrimary: true, button: 0, buttons, bubbles: true, cancelable: true});
    node.dispatchEvent(new PointerEvent("pointerdown", at(yOf(Number(node.dataset.value)), 1)));
    node.dispatchEvent(new PointerEvent("pointermove", at(yOf(value), 1)));
    const during = {label: text(node.querySelector("text")), moved: node.classList.contains("moved"), same: line(level) === node};
    node.dispatchEvent(new PointerEvent("pointerup", at(yOf(value), 0)));
    await until(() => line(level) && line(level) !== node, 4000);
    return during;
  };
  const press = async (level, key, times) => {
    for (let round = 0; round < times; round += 1) {
      const node = line(level);
      node.focus();
      node.dispatchEvent(new KeyboardEvent("keydown", {key, bubbles: true, cancelable: true}));
      await until(() => line(level) !== node, 2000);
    }
  };
  const toasts = () => all("#toasts .toast").map(text);
  const stored = async () => (await (await fetch("/api/limits", {cache: "no-store"})).json()).limits;
  const posts = [];
  const asked = [];
  const send = window.fetch.bind(window);
  window.fetch = (path, init) => {
    if (String(path).startsWith("/api/limits") && init && init.method === "POST") {
      posts.push([String(path), JSON.parse(init.body).proof === undefined ? "sign" : JSON.parse(init.body).proof === null ? "unsigned" : "signed"]);
    }
    return send(path, init);
  };
  const credentials = navigator.credentials.get.bind(navigator.credentials);
  navigator.credentials.get = (options) => {
    asked.push(1);
    return credentials(options);
  };
  const ready = () => until(() => lines().length === 4, 15000);
  const page = () => ({wide: document.documentElement.scrollWidth > innerWidth + 1, plot: Math.round(document.querySelector("#main .res-hardware .res-plot").getBoundingClientRect().height)});
  const menu = (selector) => {
    const details = document.querySelector(selector);
    if (!details.open) {
      details.querySelector("summary").click();
    }
    return details;
  };
  const tick = async (selector, on) => {
    const box = document.querySelector(selector);
    if (box.checked !== on) {
      box.click();
    }
    await sleep(150);
    return box.checked;
  };
"""
LINES = """(async () => {@HELPERS@@READ@
  if (!(await ready())) {
    return {error: text(document.getElementById("main"))};
  }
  const cpu = {lines: lines(), target: target(), metric: pressed("Limit lines")};
  button("Limit lines", "RAM").click();
  await until(() => lines().every(({metric}) => metric === "ram"), 4000);
  const ram = {lines: lines(), target: target()};
  button("Limit lines", "PSI").click();
  await until(() => lines().every(({metric}) => metric === "psi"), 4000);
  const psi = {lines: lines(), target: target()};
  button("Limit lines", "CPU").click();
  await until(() => lines().every(({metric}) => metric === "cpu"), 4000);
  await press("upper", "ArrowDown", 5);
  const staged = {line: lines().find(({level}) => level === "upper"), stage: stage(), focused: document.activeElement === line("upper")};
  const unknown = all("#main rect.res-mark.unknown").map((rect) => text(rect.querySelector("title")));
  return {cpu, ram, psi, staged, unknown, page: page(), violations: window.e2eViolations || null};
})()"""
COORDS = """(async () => {@HELPERS@@READ@
  if (!(await ready())) {
    return {error: text(document.getElementById("main"))};
  }
  const svg = chart();
  const box = svg.getBoundingClientRect();
  const height = svg.viewBox.baseVal.height;
  const band = (value) => {
    const found = [];
    for (let y = Math.floor(box.top); y <= Math.ceil(box.bottom); y += 1) {
      if (Limits.valueAt((y - box.top) * height / box.height, FRAME, height - FRAME) === value) {
        found.push(y);
      }
    }
    return found.length ? found[Math.floor(found.length / 2)] : Math.round(yOf(value));
  };
  return {x: Math.round(box.left + box.width / 2), from: band(90), to: band(85)};
})()"""
MOUSE = """(async () => {@HELPERS@@READ@
  if (!(await ready())) {
    return {error: text(document.getElementById("main"))};
  }
  const dragged = {line: lines().find(({level}) => level === "upper"), others: lines().filter(({level}) => level !== "upper").map(({moved}) => moved), stage: stage()};
  document.querySelector("#main .res-limits .limit-save").click();
  const saved = Boolean(await until(() => posts.length === 2 && !stage().shown, 8000));
  return {dragged, saved, posts: [...posts], asked: asked.length, stored: (await stored()).cpu, after: lines().find(({level}) => level === "upper")};
})()"""
STAGE = """(async () => {@HELPERS@@READ@
  if (!(await ready())) {
    return {error: text(document.getElementById("main"))};
  }
  const during = await drag("upper", 85);
  const moved = {during, line: lines().find(({level}) => level === "upper"), stage: stage()};
  document.querySelector("#main .res-limits .limit-discard").click();
  await until(() => !stage().shown, 4000);
  const discarded = {line: lines().find(({level}) => level === "upper"), stage: stage()};
  await drag("upper", 96);
  const broken = {line: lines().find(({level}) => level === "upper"), stage: stage()};
  document.querySelector("#main .res-limits .limit-save").click();
  await sleep(500);
  broken.posts = [...posts];
  await press("upper", "Escape", 1);
  const escaped = {line: lines().find(({level}) => level === "upper"), stage: stage()};
  await press("upper", "ArrowDown", 5);
  const keyed = {line: lines().find(({level}) => level === "upper"), stage: stage(), focused: document.activeElement === line("upper")};
  document.querySelector("#main .res-limits .limit-save").click();
  const saved = Boolean(await until(() => posts.length === 2 && !stage().shown, 8000));
  return {moved, discarded, broken, escaped, keyed, saved, posts: [...posts], asked: asked.length, stored: (await stored()).cpu, after: lines().find(({level}) => level === "upper")};
})()"""
LOOSER = """(async () => {@HELPERS@@READ@
  if (!(await ready())) {
    return {error: text(document.getElementById("main"))};
  }
  await press("upper", "ArrowUp", 2);
  button("Limit lines", "RAM").click();
  await until(() => lines().every(({metric}) => metric === "ram"), 4000);
  await press("upper", "ArrowDown", 5);
  const staged = stage();
  document.querySelector("#main .res-limits .limit-save").click();
  const saved = Boolean(await until(() => posts.length === 2 && !stage().shown, 15000));
  await sleep(300);
  return {staged, saved, posts: [...posts], asked: asked.length, stored: await stored(), toasts: toasts()};
})()"""
CANCEL = """(async () => {@HELPERS@@READ@
  if (!(await ready())) {
    return {error: text(document.getElementById("main"))};
  }
  navigator.credentials.get = () => {
    asked.push(1);
    return Promise.reject(new DOMException("The operator canceled.", "NotAllowedError"));
  };
  await press("upper", "ArrowUp", 2);
  document.querySelector("#main .res-limits .limit-save").click();
  const toast = await until(() => toasts().find((words) => words.includes("not signed")), 6000);
  await sleep(500);
  return {toast, posts: [...posts], asked: asked.length, stored: await stored(), line: lines().find(({level}) => level === "upper"), stage: stage()};
})()"""
PROFILE = """(async () => {@HELPERS@@READ@
  if (!(await ready())) {
    return {error: text(document.getElementById("main"))};
  }
  menu("#main .res-limits-menu");
  button("Profile", "Max").click();
  const moved = await until(() => pressed("Profile").join() === "Max" && lines().some(({level, value}) => level === "upper" && value === 95), 15000);
  return {moved: Boolean(moved), posts: [...posts], asked: asked.length, stored: await stored(), profile: pressed("Profile"), lines: lines()};
})()"""
MENUS = """(async () => {@HELPERS@@READ@
  if (!(await until(() => lines().length >= 3, 15000))) {
    return {error: text(document.getElementById("main"))};
  }
  const limits = menu("#main .res-limits-menu");
  await tick('#main .res-limits-menu input[data-level="mayday"]', true);
  await until(() => lines().length === 4, 4000);
  const entries = all("label.limit-level", limits).map((label) => [text(label), label.getAttribute("title"), label.querySelector("input").checked]);
  const off = {upper: await tick('#main .res-limits-menu input[data-level="upper"]', false), target: await tick('#main .res-limits-menu input[data-level="target"]', false)};
  const hidden = {levels: lines().map(({level}) => level), target: target().length, open: limits.open};
  await tick('#main .res-limits-menu input[data-level="upper"]', true);
  await tick('#main .res-limits-menu input[data-level="target"]', true);
  const back = {levels: lines().map(({level}) => level), target: target().length};
  await tick('#main .res-limits-menu input[data-level="mayday"]', false);
  document.getElementById("limits-open").click();
  const opened = Boolean(await until(() => sheet() === "Limits", 4000));
  const closedMenu = !limits.open;
  const heads = all('#sheet table[aria-label="Limits"] thead th').map((node) => [text(node), node.getAttribute("title")]);
  const cells = all('#sheet table[aria-label="Limits"] tbody tr').map((row) => [row.dataset.metric, ...all("input.limit-cell", row).map((input) => Number(input.value))]);
  const dials = all("#sheet .limit-dial, #sheet [role=slider]").length;
  const cell = document.querySelector('#sheet input.limit-cell[data-metric="disk"][data-level="stop"]');
  cell.value = "94";
  cell.dispatchEvent(new Event("input", {bubbles: true}));
  await sleep(200);
  const sheetStage = stage(document.querySelector("#sheet"));
  const chartStage = stage();
  const cellMoved = cell.classList.contains("moved");
  document.querySelector("#sheet .limit-discard").click();
  await sleep(200);
  const discarded = {value: cell.value, stage: stage(document.querySelector("#sheet")), moved: cell.classList.contains("moved")};
  document.querySelector('#sheet [aria-label="Close"]').click();
  await until(() => sheet() === null, 4000);
  const right = new MouseEvent("contextmenu", {bubbles: true, cancelable: true, button: 2, clientX: chart().getBoundingClientRect().left + 40, clientY: chart().getBoundingClientRect().top + 20});
  chart().dispatchEvent(right);
  const context = {prevented: right.defaultPrevented, opened: Boolean(await until(() => sheet() === "Limits", 4000))};
  document.querySelector('#sheet [aria-label="Close"]').click();
  await until(() => sheet() === null, 4000);
  return {entries, off, hidden, back, opened, closedMenu, heads, cells, dials, sheetStage, chartStage, cellMoved, discarded, context, levels: lines().map(({level}) => level), posts: [...posts], wide: document.documentElement.scrollWidth > innerWidth + 1};
})()"""
KEPT = """(async () => {@HELPERS@@READ@
  if (!(await until(() => chart() && document.querySelector("#main .res-limits-menu"), 15000))) {
    return {error: text(document.getElementById("main"))};
  }
  await until(() => lines().length === 3, 6000);
  const levels = lines().map(({level}) => level);
  const box = document.querySelector('#main .res-limits-menu input[data-level="mayday"]').checked;
  await tick('#main .res-limits-menu input[data-level="mayday"]', true);
  await until(() => lines().length === 4, 4000);
  return {levels, box, after: lines().map(({level}) => level)};
})()"""
VIEW = """(async () => {@HELPERS@@READ@
  if (!(await ready())) {
    return {error: text(document.getElementById("main"))};
  }
  const count = () => ({
    legend: !document.querySelector("#main .res-hardware .res-legend").hidden, chips: all("#main .res-hardware .legend-chip").length, wait: all("#main svg.res-chart[data-chart=hardware] rect.res-mark.wait").length,
    queue: all("#main svg.res-chart[data-chart=hardware] rect.res-mark.blocked, #main svg.res-chart[data-chart=hardware] rect.res-mark.hung").length,
    limits: lines().length, target: target().length, unknown: all("#main svg.res-chart[data-chart=hardware] rect.res-mark.unknown").length,
  });
  const before = count();
  const view = menu("#main .res-view-menu");
  const entries = all("label.res-pick", view).map((label) => [text(label), label.getAttribute("title")]);
  const chip = document.querySelector('#main .res-hardware .legend-chip[data-chip="host:CPU"]');
  chip.click();
  await sleep(400);
  const chipped = all('#main svg.res-chart[data-chart=hardware] path.res-line[data-series="CPU"]').length;
  document.querySelector('#main .res-hardware .legend-chip[data-chip="host:CPU"]').click();
  await sleep(400);
  for (const key of ["legend", "queue", "waits", "limits"]) {
    await tick(`#main .res-view-menu input[data-show="${key}"]`, false);
  }
  await sleep(300);
  return {before, entries, chipped, after: count(), open: view.open};
})()"""
VIEW_KEPT = """(async () => {@HELPERS@@READ@
  if (!(await until(() => chart() && document.querySelector("#main .res-view-menu"), 15000))) {
    return {error: text(document.getElementById("main"))};
  }
  await sleep(1500);
  const count = () => ({legend: !document.querySelector("#main .res-hardware .res-legend").hidden, wait: all("#main rect.res-mark.wait").length, queue: all("#main rect.res-mark.blocked, #main rect.res-mark.hung").length, limits: lines().length});
  const kept = {view: count(), boxes: all("#main .res-view-menu input[data-show]").map((box) => [box.dataset.show, box.checked])};
  menu("#main .res-view-menu");
  for (const key of ["legend", "queue", "waits", "limits"]) {
    await tick(`#main .res-view-menu input[data-show="${key}"]`, true);
  }
  await until(() => lines().length === 4, 4000);
  return {kept, back: count()};
})()"""


def probe(source: str) -> str:
    return source.replace("@HELPERS@", base.HELPERS).replace("@READ@", READ)


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestResourceLimits(HubCase):
    drive = base.OrchestratorE2ECase.drive
    authenticator = base.OrchestratorE2ECase.authenticator

    def sample(self, index: int) -> dict:
        row = w4.TestWorkbenchResources.sample(self, index)
        gpu = row["gpus"][0]
        if gpu.get("asleep") is not True and gpu["util"] is None:
            gpu["error"] = MISMATCH
        if BLOCKED[0] <= index < BLOCKED[1]:
            row["queue"]["head"] = {"id": "quality-high-1002", "kind": "quality-high", "waited_s": 900, "reason": "RAM 56 % used + 37 % still to come reach the limit 85 %"}
        if HUNG[0] <= index < HUNG[1]:
            row["queue"]["hung"] = ["test-1001"]
        return row

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        now = int(time.time())
        self.start = now - now % 60 - w4.ROWS * 60
        folder = self.kept / "resources"
        folder.mkdir()
        (folder / "samples.jsonl").write_text(self.jsonl([self.sample(index) for index in range(w4.ROWS)]), encoding="utf-8")
        (folder / "tokens.jsonl").write_text("", encoding="utf-8")
        self.write_council({"limits.json": PROFILES["balanced"], "limits-target.json": TARGET})
        self.page_url = f"http://localhost:{self.port}/"

    def stored(self) -> dict:
        return json.loads((self.council / "limits.json").read_text(encoding="utf-8"))

    def step(self, width: int, height: int, name: str, source: str) -> dict:
        return {"width": width, "height": height, "url": f"{self.page_url}?{width}-{name}#resources", "wait": 1200, "probe": probe(source), "shot": str(OUT / f"chromium-{width}-{name}.png")}

    def test_every_width_draws_four_draggable_lines_and_the_target_and_a_staged_line_turns_dashed(self):
        data = self.drive([self.step(width, height, "lines", LINES) for width, height in base.WIDTHS], None, init=w4.GUARD)
        balanced = PROFILES["balanced"]
        for (width, _), found in zip(base.WIDTHS, data["results"], strict=True):
            with self.subTest(width=width):
                self.assertNotIn("error", found, found)
                cpu = found["cpu"]["lines"]
                self.assertEqual([(entry["metric"], entry["level"], entry["value"]) for entry in cpu], [("cpu", level, balanced["cpu"][level]) for level in LEVELS])
                self.assertEqual([entry["label"] for entry in cpu], [f"{name} {balanced['cpu'][level]}" for name, level in zip(NAMES, LEVELS, strict=True)])
                self.assertEqual({(entry["role"], entry["moved"], entry["was"], entry["dash"]) for entry in cpu}, {("slider", False, False, "none")})
                self.assertTrue(all(entry["title"].startswith(f"CPU {entry['label']} %: {name}: ") for entry, name in zip(cpu, NAMES, strict=True)), cpu)
                self.assertIn(UPPER, cpu[1]["title"])
                self.assertEqual([entry[:3] for entry in found["cpu"]["target"]], [["cpu", 84, "target 84"]])
                self.assertIn("target: the live AIMD target", found["cpu"]["target"][0][3])
                self.assertEqual(found["cpu"]["metric"], ["CPU"])
                self.assertEqual([entry["value"] for entry in found["ram"]["lines"]], [balanced["ram"][level] for level in LEVELS])
                self.assertEqual([entry[:3] for entry in found["ram"]["target"]], [["ram", 80.5, "target 81"]])
                self.assertEqual(([entry["value"] for entry in found["psi"]["lines"]], found["psi"]["target"]), ([balanced["psi"][level] for level in LEVELS], []))
                staged = found["staged"]
                self.assertEqual((staged["line"]["value"], staged["line"]["moved"], staged["line"]["was"], staged["line"]["label"], staged["line"]["now"]), (85, True, True, "upper 85 (was 90)", "85"))
                self.assertNotEqual(staged["line"]["dash"], "none")
                self.assertTrue(staged["focused"])
                self.assertEqual((staged["stage"]["shown"], staged["stage"]["save"], staged["stage"]["disabled"], staged["stage"]["note"]), (True, "Save 1 change", False, "CPU upper 90 → 85 %"))
                self.assertTrue(found["unknown"])
                self.assertTrue(all(words == f"{w4.GPU} unknown: {MISMATCH}" for words in found["unknown"]), found["unknown"])
                self.assertFalse(found["page"]["wide"])
                self.assertGreater(found["page"]["plot"], 40)
                self.assertEqual(w4.quiet(found["violations"]), [])
        self.assertEqual(self.stored(), balanced)

    def test_a_mouse_drag_of_cpu_upper_from_90_to_85_stages_a_dashed_line_that_saves_without_the_passkey(self):
        coords = self.drive([self.step(1366, 768, "coords", COORDS)], None, init=w4.GUARD)["results"][0]
        self.assertNotIn("error", coords, coords)
        step = {**self.step(1366, 768, "mouse", MOUSE), "wait": 3000, "drag": [[coords["x"], coords["from"]], [coords["x"], coords["to"]]]}
        found = self.drive([step], None, init=w4.GUARD)["results"][0]
        self.assertNotIn("error", found, found)
        dragged = found["dragged"]
        self.assertEqual((dragged["line"]["value"], dragged["line"]["moved"], dragged["line"]["label"]), (85, True, "upper 85 (was 90)"), dragged)
        self.assertNotEqual(dragged["line"]["dash"], "none")
        self.assertEqual(dragged["others"], [False, False, False])
        self.assertEqual((dragged["stage"]["save"], dragged["stage"]["disabled"]), ("Save 1 change", False))
        self.assertTrue(found["saved"], found)
        self.assertEqual((found["posts"], found["asked"]), ([["/api/limits/sign", "sign"], ["/api/limits", "unsigned"]], 0))
        self.assertEqual(found["stored"], {**PROFILES["balanced"]["cpu"], "upper": 85})
        self.assertEqual((found["after"]["value"], found["after"]["moved"]), (85, False))
        self.assertEqual(self.stored()["cpu"]["upper"], 85)

    def test_touch_drag_stages_discard_restores_an_order_break_blocks_save_and_keys_stage_a_tighter_value(self):
        found = self.drive([self.step(1366, 768, "stage", STAGE)], None, init=w4.GUARD)["results"][0]
        self.assertNotIn("error", found, found)
        moved = found["moved"]
        self.assertEqual(moved["during"], {"label": "upper 85 (was 90)", "moved": True, "same": True})
        self.assertEqual((moved["line"]["value"], moved["line"]["moved"]), (85, True))
        self.assertEqual((moved["stage"]["save"], moved["stage"]["disabled"], moved["stage"]["note"]), ("Save 1 change", False, "CPU upper 90 → 85 %"))
        discarded = found["discarded"]
        self.assertEqual((discarded["line"]["value"], discarded["line"]["moved"], discarded["line"]["dash"], discarded["stage"]["shown"]), (90, False, "none", False))
        broken = found["broken"]
        self.assertEqual((broken["line"]["value"], broken["stage"]["disabled"], broken["posts"]), (96, True, []))
        self.assertEqual(broken["stage"]["error"], f"CPU upper 96 % {ORDER}: it must stay below STOP 95 %")
        self.assertEqual((found["escaped"]["line"]["value"], found["escaped"]["stage"]["shown"]), (90, False))
        keyed = found["keyed"]
        self.assertEqual((keyed["line"]["value"], keyed["line"]["moved"], keyed["stage"]["save"], keyed["focused"]), (85, True, "Save 1 change", True))
        self.assertTrue(found["saved"], found)
        self.assertEqual((found["posts"], found["asked"]), ([["/api/limits/sign", "sign"], ["/api/limits", "unsigned"]], 0))
        self.assertEqual(found["stored"], {**PROFILES["balanced"]["cpu"], "upper": 85})
        self.assertEqual(self.stored(), {**PROFILES["balanced"], "cpu": {**PROFILES["balanced"]["cpu"], "upper": 85}})

    def test_a_looser_batch_asks_one_passkey_signature_for_every_staged_value_and_a_cancel_keeps_them_staged(self):
        self.pin()
        canceled = self.drive([self.step(1366, 768, "cancel", CANCEL)], None, init=w4.GUARD)["results"][0]
        self.assertNotIn("error", canceled, canceled)
        self.assertIn("not signed", canceled["toast"])
        self.assertEqual((canceled["posts"], canceled["asked"], canceled["stored"]), ([["/api/limits/sign", "sign"]], 1, PROFILES["balanced"]))
        self.assertEqual((canceled["line"]["value"], canceled["line"]["moved"], canceled["stage"]["shown"]), (92, True, True))
        self.assertEqual(self.stored(), PROFILES["balanced"])
        found = self.drive([self.step(1366, 768, "looser", LOOSER)], self.authenticator(), init=w4.GUARD)["results"][0]
        self.assertNotIn("error", found, found)
        self.assertEqual((found["staged"]["save"], found["staged"]["disabled"]), ("Save 2 changes", False))
        self.assertEqual(found["staged"]["note"], "CPU upper 90 → 92 %, RAM upper 90 → 85 % · passkey")
        self.assertTrue(found["saved"], found)
        self.assertEqual((found["posts"], found["asked"]), ([["/api/limits/sign", "sign"], ["/api/limits", "signed"]], 1))
        balanced = PROFILES["balanced"]
        expected = {**balanced, "cpu": {**balanced["cpu"], "upper": 92}, "ram": {**balanced["ram"], "upper": 85}}
        self.assertEqual((found["stored"], self.stored()), (expected, expected))

    def test_a_signed_profile_from_the_limits_menu_moves_every_line(self):
        found = self.drive([self.step(1920, 1080, "max", PROFILE)], self.authenticator(), init=w4.GUARD)["results"][0]
        self.assertNotIn("error", found, found)
        self.assertTrue(found["moved"], found)
        self.assertEqual((found["posts"], found["asked"], found["profile"]), ([["/api/limits/sign", "sign"], ["/api/limits", "signed"]], 1, ["Max"]))
        self.assertEqual([entry["value"] for entry in found["lines"]], [PROFILES["max"]["cpu"][level] for level in LEVELS])
        self.assertEqual(self.stored(), PROFILES["max"])

    def test_the_limits_menu_hides_levels_and_opens_the_matrix_and_a_right_click_opens_it_too(self):
        steps = [self.step(width, height, "menus", MENUS) for width, height in base.WIDTHS]
        steps.append({**self.step(1366, 768, "kept", KEPT), "shot": None})
        data = self.drive(steps, None, init=w4.GUARD)["results"]
        balanced = PROFILES["balanced"]
        for (width, _), found in zip(base.WIDTHS, data, strict=True):
            with self.subTest(width=width):
                self.assertNotIn("error", found, found)
                self.assertEqual([entry[0] for entry in found["entries"]], ["lower", "upper", "STOP", "MAYDAY", "target"])
                self.assertTrue(all(title.startswith(f"{name}: ") for name, title, _ in found["entries"]), found["entries"])
                self.assertEqual(found["entries"][1][1], f"{UPPER}; for RAM, swap, PSI and disk the watch warns above it, and a load above it drops the live target")
                self.assertEqual(found["off"], {"upper": False, "target": False})
                self.assertEqual(found["hidden"], {"levels": ["lower", "stop", "mayday"], "target": 0, "open": True})
                self.assertEqual(found["back"], {"levels": list(LEVELS), "target": 1})
                self.assertTrue(found["opened"])
                self.assertTrue(found["closedMenu"])
                self.assertEqual([head for head, _ in found["heads"]], ["Metric", *NAMES])
                self.assertTrue(all(title.startswith(f"{name}: ") for (name, title) in found["heads"][1:]), found["heads"])
                self.assertEqual(found["cells"], [[metric, *(balanced[metric][level] for level in LEVELS)] for metric in balanced])
                self.assertEqual(found["dials"], 0)
                self.assertEqual((found["sheetStage"]["save"], found["sheetStage"]["note"], found["cellMoved"]), ("Save 1 change", "Disk STOP 95 → 94 %", True))
                self.assertEqual(found["chartStage"]["save"], "Save 1 change")
                self.assertEqual((found["discarded"]["value"], found["discarded"]["stage"]["shown"], found["discarded"]["moved"]), ("95", False, False))
                self.assertEqual(found["context"], {"prevented": True, "opened": True})
                self.assertEqual(found["levels"], ["lower", "upper", "stop"])
                self.assertEqual(found["posts"], [])
                self.assertFalse(found["wide"])
        kept = data[-1]
        self.assertNotIn("error", kept, kept)
        self.assertEqual((kept["levels"], kept["box"], kept["after"]), (["lower", "upper", "stop"], False, list(LEVELS)))
        self.assertEqual(self.stored(), balanced)

    def test_the_view_menu_hides_legend_markers_bands_and_lines_and_the_choice_survives_a_reload(self):
        steps = [self.step(1366, 768, "view", VIEW), {**self.step(1366, 768, "view-kept", VIEW_KEPT), "wait": 1500}]
        first, second = self.drive(steps, None, init=w4.GUARD)["results"]
        self.assertNotIn("error", first, first)
        before = first["before"]
        self.assertTrue(before["legend"] and before["chips"] and before["wait"] and before["queue"] and before["unknown"], before)
        self.assertEqual((before["limits"], before["target"]), (4, 1))
        self.assertEqual([label for label, _ in first["entries"]], ["Legend", "Queue markers", "Wait bands", "Limit lines"])
        self.assertTrue(all(title.startswith(f"{label}: ") for label, title in first["entries"]), first["entries"])
        self.assertEqual(first["chipped"], 0)
        self.assertEqual(first["after"], {"legend": False, "chips": before["chips"], "wait": 0, "queue": 0, "limits": 0, "target": 0, "unknown": before["unknown"]})
        self.assertTrue(first["open"])
        self.assertNotIn("error", second, second)
        self.assertEqual(second["kept"]["view"], {"legend": False, "wait": 0, "queue": 0, "limits": 0})
        self.assertEqual(second["kept"]["boxes"], [["legend", False], ["queue", False], ["waits", False], ["limits", False]])
        self.assertTrue(second["back"]["legend"] and second["back"]["wait"] and second["back"]["queue"], second["back"])
        self.assertEqual(second["back"]["limits"], 4)


if __name__ == "__main__":
    unittest.main()
