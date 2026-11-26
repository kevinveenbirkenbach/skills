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

OUT = Path(os.environ.get("E2E_OUT", "/tmp/legend-toggle-shots"))
TILE = "metric:tokens/interval/all"
PINS = [
    {"kind": "metric", "id": "tokens/interval/all", "w": 6, "h": 4, "view": {"chart": "tokens", "tokens": "interval", "shown": None}},
    {"kind": "panel", "id": "tasks/burn", "w": 6, "h": 4},
    {"kind": "panel", "id": "stream", "w": 6, "h": 4},
]
OWN = ("agents/orbit", "agents/chord", "agents/swimlane", "artifacts/orbit", "artifacts/chord", "artifacts/swimlane", "tasks/rasci", "tasks/gantt", "tasks/burn")
EXPECTED = {
    **{screen: [] for screen in base.SCREENS},
    **{screen: [screen] for screen in OWN},
    "home": sorted([TILE, "panel:tasks/burn"]),
    "resources": ["resources-hardware", "resources-tokens"],
}
READ = """
  const PARTS = ".legend > :not(.legend-toggle), .res-legend, .home-metric > .legend-chips";
  const owners = () => [...all("#main [data-panel]").filter((host) => !host.closest(".home-tile")), ...all(".home-tile[data-pin]")];
  const keyOf = (owner) => owner.dataset.pin || owner.dataset.panel;
  const ownerOf = (key) => owners().find((node) => keyOf(node) === key) || null;
  const toggleOf = (owner) => (owner ? owner.querySelector(`.legend-toggle[data-legend-key="${keyOf(owner)}"]`) : null);
  const infoKeys = () => owners().filter((owner) => owner.getClientRects().length && toggleOf(owner)).map(keyOf).sort();
  const shownParts = (owner) => all(PARTS, owner).filter((node) => node.getClientRects().length).length;
  const stored = async () => (await (await fetch("/api/view", {cache: "no-store"})).json());
  const storedUntil = async (test, ms) => {
    const end = Date.now() + ms;
    while (Date.now() < end) {
      const found = await stored();
      if (test(found)) {
        return found;
      }
      await sleep(200);
    }
    return null;
  };
  const go = async (hash) => {
    location.hash = hash;
    return screenShown(8000);
  };
  const tile = () => document.querySelector(`.home-tile[data-pin="@TILE@"]`);
  const plot = () => tile() && tile().querySelector(".res-plot svg");
  const tokens = () => document.querySelector('#main [data-panel="resources-tokens"]');
  const agents = () => [...new Set(all("svg [data-agent]", tokens()).map((node) => node.dataset.agent))].sort();
  const wide = () => document.documentElement.scrollWidth > innerWidth + 1;
"""
SCAN = """(async () => {@HELPERS@@READ@
  const flip = async (key) => {
    const path = ownerOf(key).dataset.pin ? "tiles" : "views";
    const button = () => toggleOf(ownerOf(key));
    const placed = path === "tiles" ? button().nextElementSibling.classList.contains("home-open") : button().parentElement.matches("[data-legend-slot], .legend-row") && button().parentElement.lastElementChild === button();
    const before = shownParts(ownerOf(key));
    button().click();
    const hidden = Boolean(await until(() => ownerOf(key) && ownerOf(key).dataset.legend === "hidden" && shownParts(ownerOf(key)) === 0 && button().getAttribute("aria-pressed") === "false", 4000));
    const kept = Boolean(await storedUntil((view) => view.legend[path][key] === false, 4000));
    button().click();
    const back = Boolean(await until(() => ownerOf(key) && ownerOf(key).dataset.legend === "shown" && shownParts(ownerOf(key)) > 0 && button().getAttribute("aria-pressed") === "true", 4000));
    const cleared = Boolean(await storedUntil((view) => !Object.hasOwn(view.legend[path], key), 4000));
    return {key, placed, before: before > 0, hidden, kept, back, cleared};
  };
  await Promise.all([ViewStore.update("legend.views", () => ({})), ViewStore.update("legend.tiles", () => ({}))]);
  const seen = {};
  const flips = [];
  for (const [screen, expected] of Object.entries(@EXPECTED@)) {
    await go(`#${screen}`);
    const keys = await until(() => (JSON.stringify(infoKeys()) === JSON.stringify(expected) ? infoKeys() : null), 8000);
    seen[screen] = keys || infoKeys();
    for (const key of keys || []) {
      flips.push(await flip(key));
    }
  }
  return {seen, flips, wide: wide(), violations: window.e2eViolations || null};
})()"""
ROOM = """(async () => {@HELPERS@@READ@
  await Promise.all([ViewStore.update("legend.views", () => ({})), ViewStore.update("legend.tiles", () => ({})), ViewStore.update("resources.hidden", () => [])]);
  await go("#home");
  if (!(await until(() => plot() && tile().querySelector(".legend-chip"), 15000))) {
    return {error: text(document.getElementById("main"))};
  }
  await sleep(600);
  const tall = () => plot().getBoundingClientRect().height;
  const before = tall();
  toggleOf(tile()).click();
  const grown = Boolean(await until(() => plot() && tall() > before + 4, 6000));
  const tileHidden = shownParts(tile()) === 0;
  await go("#resources");
  const chip = () => tokens() && tokens().querySelector('.legend-chip[data-chip="agent:IAM"]');
  if (!(await until(chip, 15000))) {
    return {error: text(document.getElementById("main"))};
  }
  const viewShown = shownParts(tokens()) > 0 && toggleOf(tokens()).getAttribute("aria-pressed") === "true";
  chip().click();
  await storedUntil((view) => view.resources.hidden.includes("agent:IAM"), 4000);
  toggleOf(tokens()).click();
  await until(() => tokens().dataset.legend === "hidden" && shownParts(tokens()) === 0, 4000);
  await sleep(800);
  const chart = agents();
  await go("#home");
  await until(plot, 8000);
  const tileStill = tile().dataset.legend === "hidden";
  toggleOf(tile()).click();
  const tileBack = Boolean(await until(() => shownParts(tile()) > 0, 4000));
  const legend = await storedUntil((view) => view.legend.views["resources-tokens"] === false && !Object.hasOwn(view.legend.tiles, "@TILE@"), 4000);
  await sleep(600);
  return {grown, tileHidden, viewShown, chart, tileStill, tileBack, legend: legend && legend.legend, wide: wide(), violations: window.e2eViolations || null};
})()"""
HIDE = """(async () => {@HELPERS@@READ@
  await go("#home");
  await until(() => plot() && toggleOf(tile()), 15000);
  toggleOf(tile()).click();
  const hidden = Boolean(await until(() => shownParts(tile()) === 0, 4000));
  await storedUntil((view) => view.legend.tiles["@TILE@"] === false, 4000);
  await sleep(600);
  return {hidden, wide: wide()};
})()"""
KEPT = """(async () => {@HELPERS@@READ@
  if (!(await screenShown(8000)) || !(await until(() => tokens() && toggleOf(tokens()) && agents().length, 15000))) {
    return {error: text(document.getElementById("main"))};
  }
  await sleep(600);
  const view = {legend: tokens().dataset.legend, pressed: toggleOf(tokens()).getAttribute("aria-pressed"), parts: shownParts(tokens()), chart: agents()};
  const found = await stored();
  return {view, stored: found.legend, hidden: found.resources.hidden, wide: wide(), violations: window.e2eViolations || null};
})()"""


def probe(template: str) -> str:
    names = {"@HELPERS@": base.HELPERS, "@READ@": READ, "@EXPECTED@": json.dumps(EXPECTED), "@TILE@": TILE}
    for key, value in names.items():
        template = template.replace(key, value)
    return template


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestLegendToggle(HubCase):
    seed = base.OrchestratorE2ECase.seed
    subagents = base.OrchestratorE2ECase.subagents
    drive = base.OrchestratorE2ECase.drive
    sample = w4.TestWorkbenchResources.sample

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        self.seed()
        now = int(time.time())
        self.start = now - now % 60 - w4.ROWS * 60
        hour = self.start - self.start % 3600
        tokens = [{"t": hour + step * 3600, "agent": agent, "model": "claude-opus-5-5", "input": 1000 * (step + 1), "output": 500, "cache_read": 20000, "cache_write": 1000} for step in range(7) for agent in ("Skills", "IAM")]
        folder = self.kept / "resources"
        folder.mkdir()
        (folder / "samples.jsonl").write_text(self.jsonl([self.sample(index) for index in range(w4.ROWS)]), encoding="utf-8")
        (folder / "tokens.jsonl").write_text(self.jsonl([row for row in tokens if row["t"] <= now]), encoding="utf-8")
        status, _, body = self.call("PATCH", "/api/view", json.dumps({"set": {"home.pins": PINS}, "expect": {"home.pins": []}}).encode(), {**self.guard(self.host), "Content-Type": "application/json"})
        self.assertEqual(status, 200, body)

    def steps(self, browser: str) -> list[dict]:
        steps = []
        for width, height in base.WIDTHS:
            shot = OUT / f"{browser}-{width}"
            steps += [
                {"width": width, "height": height, "url": f"{self.base}?{width}-scan#home", "wait": 1200, "probe": probe(SCAN), "shot": None},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(ROOM), "shot": f"{shot}-home-shown.png"},
                {"width": width, "height": height, "url": f"{self.base}?{width}-kept#resources", "wait": 1200, "probe": probe(KEPT), "shot": f"{shot}-resources-hidden.png"},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(HIDE), "shot": f"{shot}-home-hidden.png"},
            ]
        return steps

    def check(self, data: dict, browser: str) -> None:
        results = iter(data["results"])
        for width, _ in base.WIDTHS:
            scan, room, kept, hide = (next(results) for _ in range(4))
            with self.subTest(browser=browser, width=width):
                self.assertEqual(scan["seen"], EXPECTED)
                self.assertEqual([flip for flip in scan["flips"] if set(flip.values()) != {flip["key"], True}], [])
                self.assertEqual(len(scan["flips"]), sum(len(keys) for keys in EXPECTED.values()))
                self.assertEqual((scan["wide"], w4.quiet(scan["violations"])), (False, []))
                self.assertNotIn("error", room, room)
                self.assertEqual({key: room[key] for key in ("grown", "tileHidden", "viewShown", "tileStill", "tileBack")}, dict.fromkeys(("grown", "tileHidden", "viewShown", "tileStill", "tileBack"), True), room)
                self.assertEqual(room["chart"], ["Skills"])
                self.assertEqual(room["legend"], {"views": {"resources-tokens": False}, "tiles": {}})
                self.assertEqual((room["wide"], w4.quiet(room["violations"])), (False, []))
                self.held(kept, {"views": {"resources-tokens": False}, "tiles": {}})
                self.assertEqual((hide["hidden"], hide["wide"]), (True, False))

    def held(self, kept: dict, legend: dict) -> None:
        self.assertNotIn("error", kept, kept)
        self.assertEqual(kept["view"], {"legend": "hidden", "pressed": "false", "parts": 0, "chart": ["Skills"]})
        self.assertEqual((kept["stored"], kept["hidden"]), (legend, ["agent:IAM"]))
        self.assertEqual((kept["wide"], w4.quiet(kept["violations"])), (False, []))

    def other(self, driver: str, binary: str) -> None:
        width, height = base.WIDTHS[0]
        data = self.drive([{"width": width, "height": height, "url": f"{self.base}?other#resources", "wait": 1200, "probe": probe(KEPT), "shot": None}], None, driver, binary, init=w4.GUARD)
        self.held(data["results"][0], {"views": {"resources-tokens": False}, "tiles": {TILE: False}})

    def test_chromium_hides_and_shows_legends_per_tile_and_view_and_firefox_sees_the_state(self):
        data = self.drive(self.steps("chromium"), None, init=w4.GUARD)
        (OUT / "chromium-legend.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        self.check(data, "chromium")
        firefox = shutil.which(os.environ.get("FIREFOX", "firefox"))
        if firefox:
            self.other("bidi.mjs", firefox)

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_hides_and_shows_legends_per_tile_and_view_and_chromium_sees_the_state(self):
        data = self.drive(self.steps("firefox"), None, "bidi.mjs", os.environ.get("FIREFOX", "firefox"), init=w4.GUARD)
        (OUT / "firefox-legend.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        self.check(data, "firefox")
        self.other("cdp.mjs", os.environ.get("CHROMIUM", "chromium"))


if __name__ == "__main__":
    unittest.main()
