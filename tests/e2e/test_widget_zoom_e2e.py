from __future__ import annotations

import json
import os
import shutil
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

import hub_e2e_kit as base
import test_home_bookmarks_e2e as bm
import test_home_dashboard_e2e as dash
import test_workbench_w4_e2e as w4

OUT = Path(os.environ.get("E2E_OUT", "/tmp/widget-zoom-shots"))
KEY = "panel:tasks/board"
TILE = """
  const pinned = () => tile("@KEY@");
  const body = () => pinned().querySelector(".home-body");
  const zoom = () => Number(body().dataset.zoom);
  const key = async (name, times) => {
    for (let index = 0; index < times; index += 1) {
      const before = zoom();
      pinned().focus();
      pinned().dispatchEvent(new KeyboardEvent("keydown", {key: name, bubbles: true, cancelable: true}));
      await until(() => zoom() !== before, 1500);
    }
    await sleep(200);
    return zoom();
  };
  const wheel = async (ctrlKey, deltaY) => {
    const before = zoom();
    const event = new WheelEvent("wheel", {deltaY, ctrlKey, bubbles: true, cancelable: true});
    body().dispatchEvent(event);
    await until(() => zoom() !== before, 1500);
    await sleep(200);
    return {zoom: zoom(), prevented: event.defaultPrevented};
  };
  const fit = () => {
    const style = getComputedStyle(body());
    const inner = body().clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
    return Math.abs(body().firstElementChild.offsetWidth * zoom() / 100 - inner) <= 2;
  };
"""
SEED = """(async () => {@HELPERS@
  await ViewStore.update("home.pins", () => [{kind: "panel", id: "tasks/board", w: innerWidth > 640 ? 6 : 4, h: 5}]);
  await ViewStore.update("home.zoom", () => ({}));
  return true;
})()"""
KEYS = """(async () => {@HELPERS@@HOME@@TILE@
  await go("home");
  if (!(await until(() => pinned() && body().dataset.zoom, 8000))) {
    return {error: text(document.getElementById("main"))};
  }
  await sleep(600);
  const head = pinned().querySelector(".home-head").getBoundingClientRect().height;
  const three = await key("+", 3);
  const kept = Math.abs(pinned().querySelector(".home-head").getBoundingClientRect().height - head) <= 0.5;
  const fits = fit();
  const scrolls = body().scrollHeight > body().clientHeight || body().scrollWidth > body().clientWidth;
  const reset = await key("0", 1);
  const floor = await key("-", 7);
  const ceiling = await key("+", 16);
  await key("0", 1);
  const up = await wheel(true, -100);
  const plain = await wheel(false, 100);
  await key("+", 2);
  const saved = await ViewStore.update("home.zoom", (zooms) => zooms);
  return {three, kept, fits, scrolls, reset, floor, ceiling, up, plain, stored: saved ? ViewStore.get("home.zoom")["@KEY@"] : null};
})()"""
MENU = """(async () => {@HELPERS@@HOME@@TILE@
  await until(() => pinned() && body().dataset.zoom, 8000);
  const box = pinned().querySelector(".home-title").getBoundingClientRect();
  const open = () => pinned().querySelector(".home-title").dispatchEvent(new MouseEvent("contextmenu", {bubbles: true, cancelable: true, button: 2, clientX: box.left + 4, clientY: box.top + 4}));
  open();
  const menu = await until(() => document.querySelector(".ctx-menu:not([hidden])"), 4000);
  const labels = menu ? all('.ctx-group[data-scope="element"] .ctx-item .ctx-label', menu).map(text) : [];
  const item = (label) => all(".ctx-item", document.querySelector(".ctx-menu:not([hidden])")).find((node) => text(node.querySelector(".ctx-label")) === label);
  const before = zoom();
  item("Zoom out").click();
  await until(() => zoom() !== before, 1500);
  const out = zoom();
  open();
  await until(() => document.querySelector(".ctx-menu:not([hidden])"), 4000);
  item("Zoom in").click();
  await until(() => zoom() !== out, 1500);
  const back = zoom();
  open();
  await until(() => document.querySelector(".ctx-menu:not([hidden])"), 4000);
  item(`Reset zoom (${back} %)`).click();
  await until(() => zoom() === 100, 1500);
  return {labels: labels.filter((label) => label.includes("oom")), out, back, reset: zoom()};
})()"""
KEPT = """(async () => {@HELPERS@@HOME@@TILE@
  await go("home");
  await until(() => pinned() && body().dataset.zoom, 8000);
  return {zoom: zoom()};
})()"""
HELP = """(async () => {@HELPERS@
  document.body.dispatchEvent(new KeyboardEvent("keydown", {key: "?", bubbles: true}));
  const sheet = await until(() => document.querySelector("#sheet:not([hidden]) dl.keys"), 4000);
  return {keys: sheet ? all("dt", sheet).map(text) : []};
})()"""


def probe(template: str) -> str:
    for key, value in (("@HELPERS@", base.HELPERS), ("@HOME@", dash.HOME), ("@TILE@", TILE), ("@KEY@", KEY)):
        template = template.replace(key, value)
    return template


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestWidgetZoom(base.OrchestratorE2ECase):
    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)

    def steps(self, browser: str) -> list[dict]:
        steps = []
        for width, height in base.WIDTHS:
            at = {"width": width, "height": height}
            shot = OUT / f"{browser}-{width}"
            steps += [
                {**at, "url": f"{self.base}?{width}-clear#stream", "wait": 600, "probe": bm.CLEAR, "shot": None},
                {**at, "url": f"{self.base}?{width}-seed#stream", "wait": 800, "probe": probe(SEED), "shot": None},
                {**at, "url": f"{self.base}?{width}-keys#home", "wait": 1500, "probe": probe(KEYS), "shot": f"{shot}-zoomed.png"},
                {**at, "url": f"{self.base}?{width}-kept#home", "wait": 1500, "probe": probe(KEPT), "shot": None},
                {**at, "url": None, "wait": 0, "probe": probe(MENU), "shot": f"{shot}-menu.png"},
                {**at, "url": None, "wait": 0, "probe": probe(HELP), "shot": None},
            ]
        return steps

    def check(self, data: dict, browser: str) -> None:
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        results = iter(data["results"])
        for width, _ in base.WIDTHS:
            _, _, keys, kept, menu, shown = (next(results) for _ in range(6))
            with self.subTest(browser=browser, width=width):
                self.assertNotIn("error", keys, keys)
                self.assertEqual((keys["three"], keys["kept"], keys["fits"], keys["scrolls"]), (130, True, True, True), keys)
                self.assertEqual((keys["reset"], keys["floor"], keys["ceiling"]), (100, 50, 200), keys)
                self.assertEqual((keys["up"], keys["plain"]), ({"zoom": 110, "prevented": True}, {"zoom": 110, "prevented": False}), keys)
                self.assertEqual((keys["stored"], kept["zoom"]), (130, 130), (keys, kept))
                self.assertEqual(menu["labels"], ["Zoom in", "Zoom out", "Reset zoom (130 %)"], menu)
                self.assertEqual((menu["out"], menu["back"], menu["reset"]), (120, 130, 100), menu)
                self.assertIn("+ / − · 0 · Ctrl+wheel", shown["keys"], shown)

    def test_chromium_zooms_a_tile_by_keys_wheel_and_menu_and_keeps_it(self):
        data = self.drive(self.steps("chromium"), None, init=w4.GUARD)
        (OUT / "chromium-zoom.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.check(data, "chromium")

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_zooms_a_tile_by_keys_wheel_and_menu_and_keeps_it(self):
        data = self.drive(self.steps("firefox"), None, "bidi.mjs", os.environ.get("FIREFOX", "firefox"), init=w4.GUARD)
        (OUT / "firefox-zoom.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.check(data, "firefox")


if __name__ == "__main__":
    unittest.main()
