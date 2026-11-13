from __future__ import annotations

import json
import os
import shutil
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

import test_orchestrator_e2e as base
from hub_case import HubCase
from hub_support import HUB, iso

OUT = Path(os.environ.get("E2E_OUT", "/tmp/hub-008-shots"))
REAL_STORE = (HUB / "templates" / "view-store.js").exists()
CUE = "e2e-home-change"
SCREENS = [
    "stream", "agents/orbit", "agents/chord", "agents/swimlane", "agents/3d", "agents/tree", "agents/hierarchy",
    "artifacts/orbit", "artifacts/chord", "artifacts/swimlane", "artifacts/tree", "artifacts/3d",
    "tasks/list", "tasks/board", "tasks/rasci", "tasks/gantt", "tasks/burn", "tasks/3d",
]
STUB = """() => {
  const KEY = "e2e-view-store";
  const read = () => JSON.parse(sessionStorage.getItem(KEY) || "{}");
  const listeners = {};
  window.ViewStore = {
    get: (path) => read()[path],
    update: (path, change) => {
      const all = read();
      all[path] = change(all[path]);
      sessionStorage.setItem(KEY, JSON.stringify(all));
      (listeners[path] || []).forEach((listen) => listen(all[path]));
      return Promise.resolve(true);
    },
    set: (path) => {
      throw new Error(`${path} holds a list: use update()`);
    },
    on: (path, listen) => {
      listeners[path] = [...(listeners[path] || []), listen];
    },
  };
}"""
HOME = """
  const go = async (hash) => {
    location.hash = hash;
    await screenShown(8000);
    await sleep(500);
  };
  const ownStar = (owner) => [...owner.querySelectorAll(".star")].find((node) => node.closest("[data-panel], [data-item]") === owner) || null;
  const starOf = (selector) => {
    const owner = document.querySelector(selector);
    return owner ? ownStar(owner) : null;
  };
  const press = async (selector) => {
    const button = await until(() => starOf(selector), 8000);
    if (!button) {
      return null;
    }
    button.click();
    await sleep(200);
    return button.getAttribute("aria-pressed");
  };
  const tiles = () => all("#main .home-tile").map((tile) => tile.dataset.pin);
  const tile = (key) => document.querySelector(`#main .home-tile[data-pin="${key}"]`);
  const centre = (node) => {
    const box = node.getBoundingClientRect();
    return {clientX: box.left + box.width / 2, clientY: box.top + box.height / 2};
  };
  const pointer = (node, type, at) => node.dispatchEvent(new PointerEvent(type, {bubbles: true, cancelable: true, pointerId: 1, button: 0, isPrimary: true, ...at}));
  const dragBy = async (handle, dx, dy) => {
    handle.scrollIntoView({block: "center"});
    const from = centre(handle);
    pointer(handle, "pointerdown", from);
    pointer(document, "pointermove", {clientX: from.clientX + dx, clientY: from.clientY + dy});
    pointer(document, "pointerup", {clientX: from.clientX + dx, clientY: from.clientY + dy});
    await sleep(300);
  };
  const sizeOf = (key) => {
    const found = tile(key);
    return found ? [Number(found.dataset.w), Number(found.dataset.h)] : null;
  };
  const grid = () => document.querySelector("#main .home-grid");
  const cell = () => {
    const look = getComputedStyle(grid());
    const gap = parseFloat(look.columnGap);
    return {column: (grid().clientWidth - gap * 11) / 12 + gap, row: parseFloat(look.gridAutoRows) + parseFloat(look.rowGap)};
  };
  const stored = () => (ViewStore.get("home.pins") || []).map((pin) => `${pin.kind}:${pin.id}`);
"""
CLEAR = """(async () => {
  sessionStorage.clear();
  await ViewStore.update("home.pins", () => []);
  sessionStorage.clear();
  return true;
})()"""
START_EMPTY = """(async () => {@HELPERS@
  await screenShown(8000);
  return {hash: location.hash, screen: document.getElementById("main").getAttribute("aria-labelledby"), first: name(document.querySelector("#tabs > .tab-group > button"))};
})()"""
STARS = """(async () => {@HELPERS@@HOME@
  const seen = [];
  const missing = [];
  const covered = [];
  const CONTROLS = 'button, a[href], input, select, textarea, summary, [role="button"], [role="tab"], [tabindex]:not([tabindex="-1"])';
  const shown = (node) => node.getClientRects().length > 0 && getComputedStyle(node).visibility !== "hidden";
  const overlap = (a, b) => Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left)) * Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top));
  const count = (where) => {
    const owners = all("[data-panel], [data-item]").filter((node) => node.namespaceURI === "http://www.w3.org/1999/xhtml");
    seen.push([where, owners.length]);
    missing.push(...owners.filter((node) => !ownStar(node)).map((node) => `${where}: ${node.outerHTML.slice(0, 120)}`));
    const controls = all(CONTROLS).filter(shown);
    for (const star of all(".star").filter(shown)) {
      const box = star.getBoundingClientRect();
      for (const other of controls) {
        if (other !== star && !other.contains(star) && !star.contains(other) && overlap(box, other.getBoundingClientRect()) > 1) {
          covered.push(`${where}: ${star.title} over ${other.outerHTML.slice(0, 100)}`);
        }
      }
    }
  };
  for (const hash of @SCREENS@) {
    await go(hash);
    await sleep(hash.endsWith("3d") || hash.startsWith("artifacts") ? 1500 : 300);
    count(hash);
  }
  await go("agents/orbit");
  const agent = document.querySelector('#main svg .node.k-session[data-pick]');
  if (agent) {
    agent.dispatchEvent(new MouseEvent("click", {bubbles: true}));
    await until(() => document.querySelector('#popup[open] [data-item^="agent:"]'), 5000);
    count("agent card");
    document.getElementById("popup").close();
  }
  document.getElementById("radio-open").click();
  await until(() => document.querySelector('[data-panel="radio-log"]'), 5000);
  count("radio spot");
  document.getElementById("radio-open").click();
  return {seen, missing, covered, total: seen.reduce((sum, [, size]) => sum + size, 0)};
})()"""
PIN = """(async () => {@HELPERS@@HOME@
  await go("tasks/gantt");
  const gantt = await press('#main [data-panel="tasks/gantt"]');
  await go("tasks/list");
  const feature = await press('#main li.task-row[data-task="work/feature"]');
  const docs = await press('#main li.task-row[data-task="work/docs"]');
  await go("stream");
  const streamed = await press('#main [data-panel="stream"]');
  await go("home");
  const pinned = tiles();
  const chart = Boolean(tile("panel:tasks/gantt") && tile("panel:tasks/gantt").querySelector("svg.chart.gantt"));
  await go("tasks/gantt");
  const off = await press('#main [data-panel="tasks/gantt"]');
  await go("home");
  const unpinned = tiles();
  await go("tasks/gantt");
  const again = await press('#main [data-panel="tasks/gantt"]');
  await go("home");
  return {gantt, feature, docs, streamed, pinned, chart, off, unpinned, again, final: tiles(), stored: stored()};
})()"""
RESIZE = """(async () => {@HELPERS@@HOME@
  await go("home");
  const key = "panel:tasks/gantt";
  const handle = () => tile(key).querySelector(".home-resize");
  const before = sizeOf(key);
  const {column, row} = cell();
  await dragBy(handle(), column * 3, row * 2);
  const grown = sizeOf(key);
  await dragBy(handle(), column * 40, row * 40);
  const most = sizeOf(key);
  const wide = [Math.round(tile(key).getBoundingClientRect().width), Math.round(grid().getBoundingClientRect().width)];
  await dragBy(handle(), -column * 40, -row * 40);
  const least = sizeOf(key);
  handle().focus();
  for (const key of ["ArrowRight", "ArrowRight", "ArrowDown"]) {
    document.activeElement.dispatchEvent(new KeyboardEvent("keydown", {key, bubbles: true, cancelable: true}));
    await sleep(100);
  }
  const keyed = sizeOf(key);
  await dragBy(handle(), column * 5, row * 3);
  const span = getComputedStyle(tile(key)).gridColumnEnd;
  return {before, grown, most, wide, least, keyed, final: sizeOf(key), span, stored: (ViewStore.get("home.pins") || []).find((pin) => pin.id === "tasks/gantt")};
})()"""
REORDER = """(async () => {@HELPERS@@HOME@
  await go("home");
  const before = tiles();
  const grip = tile(before[0]).querySelector(".home-grip");
  grip.scrollIntoView({block: "center"});
  const from = centre(grip);
  const target = tile(before[2]);
  target.scrollIntoView({block: "center"});
  const to = centre(target);
  pointer(grip, "pointerdown", centre(grip));
  pointer(document, "pointermove", to);
  pointer(document, "pointerup", to);
  await sleep(300);
  const dragged = tiles();
  const moving = tile(dragged[2]);
  moving.focus();
  moving.dispatchEvent(new KeyboardEvent("keydown", {key: "ArrowLeft", bubbles: true, cancelable: true}));
  await sleep(200);
  const keyed = tiles();
  const focused = document.activeElement === tile(keyed[1]);
  document.activeElement.dispatchEvent(new KeyboardEvent("keydown", {key: "ArrowDown", bubbles: true, cancelable: true}));
  await sleep(200);
  return {from: Boolean(from), before, dragged, keyed, focused, down: tiles(), stored: stored()};
})()"""
RELOADED = """(async () => {@HELPERS@@HOME@
  await screenShown(8000);
  await sleep(500);
  const narrow = all("#main .home-tile").map((node) => Math.round(node.getBoundingClientRect().width));
  return {hash: location.hash, screen: document.getElementById("main").getAttribute("aria-labelledby"), tiles: tiles(), widths: [...new Set(narrow)], grid: Math.round(grid().getBoundingClientRect().width), errors: all("#main .home-error").map(text)};
})()"""
CHANGE = """(async () => {@HELPERS@@HOME@
  await go("home");
  const lanes = () => all('#main .home-tile[data-pin="panel:tasks/gantt"] text.lane-label').map((node) => node.dataset.task);
  const before = lanes();
  await fetch("/api/tts", {method: "POST", headers: {"X-Kvb-Orchestrator": "1", "Content-Type": "application/json"}, body: JSON.stringify({text: "@CUE@", voice: ""}), cache: "no-store"});
  const grown = await until(() => lanes().includes("work/new") && tile("task:work/docs").classList.contains("gone"), 25000);
  const gone = tile("task:work/docs");
  const result = {
    before, after: lanes(), grown: Boolean(grown), goneWord: gone ? text(gone.querySelector(".home-gone-word")) : null,
    unpin: gone ? name(gone.querySelector(".home-gone .home-gone-unpin")) : null,
  };
  await go("tasks/gantt");
  result.source = all('#main [data-panel="tasks/gantt"] text.lane-label').map((node) => node.dataset.task);
  await go("home");
  return result;
})()"""
GONE_UNPIN = """(async () => {@HELPERS@@HOME@
  await go("home");
  const button = tile("task:work/docs").querySelector(".home-gone-unpin");
  button.click();
  await sleep(300);
  return {tiles: tiles(), stored: stored()};
})()"""
FULL = """(async () => {@HELPERS@@HOME@
  await ViewStore.update("home.pins", () => Array.from({length: 64}, (_, index) => ({kind: "task", id: `work/seed-${index}`, w: 2, h: 1})));
  await go("tasks/gantt");
  const before = all("#toasts .toast").length;
  const pressed = await press('#main [data-panel="tasks/gantt"]');
  const toast = await until(() => all("#toasts .toast").slice(before).map(text).find((words) => words.startsWith("Home is full")), 5000);
  return {pressed, toast, count: (ViewStore.get("home.pins") || []).length};
})()"""
START_PINNED = """(async () => {@HELPERS@
  await screenShown(8000);
  await sleep(300);
  return {hash: location.hash, screen: document.getElementById("main").getAttribute("aria-labelledby")};
})()"""


def probe(template: str) -> str:
    return template.replace("@HELPERS@", base.HELPERS).replace("@HOME@", HOME).replace("@SCREENS@", json.dumps(SCREENS)).replace("@CUE@", CUE)


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestHomeDashboard(HubCase):
    setUp = base.TestOrchestratorE2E.setUp
    subagents = base.TestOrchestratorE2E.subagents
    drive = base.TestOrchestratorE2E.drive

    def cue(self) -> None:
        hub = self.httpd.hub
        spoken = base.tone(1, 8000)

        def synthesize(body: bytes) -> bytes:
            if json.loads(body)["text"] == CUE:
                path = self.council / "rasci.json"
                register = json.loads(path.read_text(encoding="utf-8"))
                register.pop("work/docs", None)
                register["work/new"] = {"title": "New line", "status": "running", "worker": "Skills session", "start": iso(time.time() - 1800), "roles": {"Skills session": "RA"}}
                path.write_text(json.dumps(register), encoding="utf-8")
            return spoken

        patch = mock.patch.object(hub.speech, "synthesize", synthesize)
        patch.start()
        self.addCleanup(patch.stop)

    def steps(self, browser: str) -> list[dict]:
        OUT.mkdir(parents=True, exist_ok=True)
        self.cue()
        steps = []
        for index, (width, height) in enumerate(base.WIDTHS):
            shot = str(OUT / f"{browser}-{width}")
            page = f"{self.base}?{width}"
            steps += [
                {"width": width, "height": height, "url": f"{page}-clear#stream", "wait": 600, "probe": CLEAR, "shot": None},
                {"width": width, "height": height, "url": f"{page}-empty", "wait": 1500, "probe": probe(START_EMPTY), "shot": f"{shot}-start-empty.png"},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(STARS), "shot": f"{shot}-stars.png"},
                {"width": width, "height": height, "url": f"{page}-pin#stream", "wait": 1200, "probe": probe(PIN), "shot": f"{shot}-pinned.png"},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(RESIZE), "shot": f"{shot}-resized.png"},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(REORDER), "shot": f"{shot}-reordered.png"},
                {"width": width, "height": height, "url": f"{page}-reloaded", "wait": 1500, "probe": probe(RELOADED), "shot": f"{shot}-reloaded.png"},
            ]
            if index == 0:
                steps += [
                    {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(CHANGE), "shot": f"{shot}-gone.png"},
                    {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(GONE_UNPIN), "shot": None},
                ]
            steps += [
                {"width": width, "height": height, "url": f"{page}-full#stream", "wait": 1200, "probe": probe(FULL), "shot": f"{shot}-full.png"},
                {"width": width, "height": height, "url": f"{page}-start-pinned", "wait": 1500, "probe": probe(START_PINNED), "shot": None},
                {"width": width, "height": height, "url": f"{page}-explicit#tasks", "wait": 1500, "probe": probe(START_PINNED), "shot": None},
            ]
        return steps

    def check(self, data: dict) -> None:
        results = iter(data["results"])
        for index, (width, _) in enumerate(base.WIDTHS):
            with self.subTest(width=width):
                next(results)
                empty = next(results)
                self.assertEqual((empty["hash"], empty["screen"], empty["first"]), ("", "tab-stream", "Home"), empty)
                stars = next(results)
                self.assertEqual(stars["missing"], [], stars)
                self.assertEqual(stars["covered"], [], stars)
                self.assertGreater(stars["total"], 20, stars)
                pinned = next(results)
                self.assertEqual((pinned["gantt"], pinned["feature"], pinned["docs"], pinned["streamed"], pinned["chart"], pinned["off"], pinned["again"]), ("true", "true", "true", "true", True, "false", "true"), pinned)
                self.assertEqual(pinned["pinned"], ["panel:tasks/gantt", "task:work/feature", "task:work/docs", "panel:stream"])
                self.assertEqual(pinned["unpinned"], ["task:work/feature", "task:work/docs", "panel:stream"])
                self.assertEqual(pinned["final"], ["task:work/feature", "task:work/docs", "panel:stream", "panel:tasks/gantt"])
                self.assertEqual(pinned["stored"], pinned["final"])
                resized = next(results)
                self.assertEqual((resized["before"], resized["grown"], resized["most"], resized["least"], resized["keyed"], resized["final"]), ([6, 4], [9, 6], [12, 12], [1, 1], [3, 2], [8, 5]), resized)
                self.assertEqual(resized["wide"][0], resized["wide"][1], resized)
                self.assertEqual(resized["span"], "-1" if width == 390 else "span 8", resized)
                self.assertEqual((resized["stored"]["w"], resized["stored"]["h"]), (8, 5))
                order = next(results)
                start = ["task:work/feature", "task:work/docs", "panel:stream", "panel:tasks/gantt"]
                self.assertEqual(order["before"], start)
                self.assertEqual(order["dragged"], ["task:work/docs", "panel:stream", "task:work/feature", "panel:tasks/gantt"], order)
                self.assertEqual(order["keyed"], ["task:work/docs", "task:work/feature", "panel:stream", "panel:tasks/gantt"], order)
                self.assertTrue(order["focused"], order)
                self.assertEqual(order["down"], ["task:work/docs", "panel:stream", "task:work/feature", "panel:tasks/gantt"], order)
                self.assertEqual(order["stored"], order["down"])
                reloaded = next(results)
                self.assertEqual((reloaded["hash"], reloaded["screen"], reloaded["tiles"], reloaded["errors"]), ("#home", "tab-home", order["down"], []), reloaded)
                if width == 390:
                    self.assertEqual(reloaded["widths"], [reloaded["grid"]], reloaded)
                else:
                    self.assertGreater(len(reloaded["widths"]), 1, reloaded)
                if index == 0:
                    change = next(results)
                    self.assertTrue(change["grown"], change)
                    self.assertNotIn("work/new", change["before"])
                    self.assertIn("work/new", change["after"])
                    self.assertEqual(sorted(change["after"]), sorted(change["source"]), change)
                    self.assertEqual((change["goneWord"], change["unpin"]), ("gone", "Unpin"), change)
                    unpinned = next(results)
                    self.assertNotIn("task:work/docs", unpinned["tiles"])
                    self.assertNotIn("task:work/docs", unpinned["stored"])
                full = next(results)
                self.assertEqual((full["pressed"], full["count"]), ("false", 64), full)
                self.assertTrue(full["toast"] and "At most 64 pins" in full["toast"], full)
                pinned_start = next(results)
                self.assertEqual((pinned_start["hash"], pinned_start["screen"]), ("#home", "tab-home"), pinned_start)
                explicit = next(results)
                self.assertEqual((explicit["hash"], explicit["screen"]), ("#tasks", "tab-tasks"), explicit)

    def init(self) -> str | None:
        return None if REAL_STORE else STUB

    def test_chromium_stars_pins_resizes_reorders_and_marks_gone_tiles_at_three_widths(self):
        data = self.drive(self.steps("chromium"), None, init=self.init())
        (OUT / "chromium-home.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        self.check(data)

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_stars_pins_resizes_reorders_and_marks_gone_tiles_at_three_widths(self):
        data = self.drive(self.steps("firefox"), None, "bidi.mjs", os.environ.get("FIREFOX", "firefox"), init=self.init())
        (OUT / "firefox-home.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        self.check(data)

    @unittest.skipUnless(REAL_STORE, "waits on 007: view-store.js and /api/view are not on this branch yet")
    def test_a_second_browser_shows_the_same_layout(self):
        first = self.drive([step for step in self.steps("chromium")[:6] if step["probe"] != probe(STARS)], None)
        second = self.drive([{"width": 1366, "height": 768, "url": f"{self.base}?second", "wait": 2000, "probe": probe(RELOADED), "shot": str(OUT / "chromium-second.png")}], None)
        self.assertEqual(second["results"][0]["tiles"], first["results"][-1]["down"])
        self.assertEqual((second["results"][0]["hash"], second["results"][0]["screen"]), ("#home", "tab-home"))


if __name__ == "__main__":
    unittest.main()
