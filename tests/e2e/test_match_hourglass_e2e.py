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
from hub_case import HubCase

OUT = Path(os.environ.get("E2E_OUT", "/tmp/hub-081-hourglass-shots"))
REDUCED = [{"name": "prefers-reduced-motion", "value": "reduce"}]
SPY = """() => {
  const real = window.fetch.bind(window);
  window.matchFetches = [];
  window.fetch = (input, options) => {
    const url = typeof input === "string" ? input : input.url;
    if (new URL(url, window.location.href).pathname === "/api/match") {
      window.matchFetches.push(performance.now());
    }
    return real(input, options);
  };
}"""
KIT = """@HELPERS@
  const headed = () => all("#main .box-head .match-glass").length;
  const large = () => document.querySelector("#main .match-glass.large");
  const fetches = () => window.matchFetches.length;
  const gaps = (times) => times.slice(1).map((at, index) => Math.round(at - times[index]));
  const flips = (glass) => glass.getAnimations({subtree: true}).filter((animation) => animation.animationName === "match-flip");
  const sheetOpen = () => !document.getElementById("sheet").hidden;
  const press = (target, key, times) => {
    for (let step = 0; step < times; step += 1) {
      target.dispatchEvent(new KeyboardEvent("keydown", {key, bubbles: true, cancelable: true}));
    }
  };
  const setDial = async (key, times) => {
    const box = large().getBoundingClientRect();
    const prevented = !large().dispatchEvent(new MouseEvent("contextmenu", {bubbles: true, cancelable: true, button: 2, clientX: box.left + 4, clientY: box.top + 4}));
    const dial = await until(() => document.querySelector("#sheet .match-refresh-dial"), 3000);
    if (!dial) {
      return {prevented, error: "no dial"};
    }
    const from = Number(dial.getAttribute("aria-valuenow"));
    press(dial, key, times);
    const to = Number(dial.getAttribute("aria-valuenow"));
    document.querySelector("#sheet .match-refresh-save").click();
    const closed = await until(() => !sheetOpen(), 5000);
    return {prevented, from, to, closed: Boolean(closed)};
  };"""
FIRST = """(async () => {@KIT@
  if (!(await until(() => large() && fetches() >= 2, 8000))) {
    return {error: text(document.getElementById("main"))};
  }
  const start = fetches();
  await until(() => fetches() >= start + 3, 9000);
  const rate = gaps(window.matchFetches.slice(start - 1, start + 3));
  await sleep(300);
  const turn = Number(large().dataset.turn);
  const fetched = await until(() => (fetches() > start + 3 ? window.matchFetches[window.matchFetches.length - 1] : null), 4000);
  await until(() => Number(large().dataset.turn) > turn, 1000);
  const running = flips(large());
  await sleep(Math.max(0, fetched + 1000 - performance.now()));
  const flip = {turned: Number(large().dataset.turn) > turn, ran: running.length, finished: running.every((animation) => animation.playState === "finished"),
    sand: getComputedStyle(large().querySelector(".match-glass-top")).animationDuration, grains: large().querySelectorAll(".match-grain").length};
  await sleep(700);
  const before = fetches();
  const clickedAt = performance.now();
  large().click();
  await until(() => fetches() > before, 1000);
  const click = {at: Math.round(window.matchFetches[before] - clickedAt)};
  await until(() => fetches() > before + 1, 4000);
  click.next = Math.round(window.matchFetches[before + 1] - window.matchFetches[before]);
  const sizes = {headed: headed(), large: large().getBoundingClientRect().height};
  const dial = await setDial("ArrowRight", 8);
  return {rate, flip, click, sizes, dial, wide: document.documentElement.scrollWidth > window.innerWidth + 1};
})()"""
RELOADED = """(async () => {@KIT@
  if (!(await until(() => large() && fetches() >= 1, 8000))) {
    return {error: text(document.getElementById("main"))};
  }
  const first = fetches();
  await sleep(3500);
  const kept = {quiet: fetches() === first, sand: large().style.getPropertyValue("--match-refresh"), title: large().title};
  const dial = await setDial("ArrowLeft", 8);
  return {kept, dial};
})()"""
STILL = """(async () => {@KIT@
  if (!(await until(() => large() && fetches() >= 1, 8000))) {
    return {error: text(document.getElementById("main"))};
  }
  const turn = Number(large().dataset.turn);
  await until(() => Number(large().dataset.turn) > turn, 4000);
  await sleep(200);
  const glasses = [large()];
  return {turned: Number(large().dataset.turn) > turn, running: glasses.map((glass) => glass.getAnimations({subtree: true}).length), face: glasses.map((glass) => getComputedStyle(glass.querySelector(".match-glass-face")).animationName)};
})()"""


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestMatchHourglass(HubCase):
    drive = base.OrchestratorE2ECase.drive

    def probe(self, flow: str) -> str:
        return flow.replace("@KIT@", KIT).replace("@HELPERS@", base.HELPERS)

    def steps(self) -> list[dict]:
        steps = []
        for width, height in base.WIDTHS:
            url = f"http://localhost:{self.port}/?{width}#tasks/match"
            steps.append({"width": width, "height": height, "url": url, "wait": 1500, "probe": self.probe(FIRST), "shot": str(OUT / f"chromium-{width}-hourglass.png")})
            steps.append({"width": width, "height": height, "url": url, "wait": 1500, "probe": self.probe(RELOADED)})
            steps.append({"width": width, "height": height, "url": url, "wait": 1500, "probe": self.probe(STILL), "media": REDUCED, "shot": str(OUT / f"chromium-{width}-hourglass-still.png")})
        return steps

    def test_chromium_fetches_on_the_hourglass_cycle_flips_it_and_keeps_the_dial_interval(self):
        OUT.mkdir(parents=True, exist_ok=True)
        data = self.drive(self.steps(), None, "cdp.mjs", os.environ.get("CHROMIUM", "chromium"), init=SPY)
        (OUT / "chromium-hourglass.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "(style-src-elem)" not in error and "/favicon.ico" not in error], [])
        self.assertEqual(len(data["results"]), 3 * len(base.WIDTHS), data)
        for index, (width, _) in enumerate(base.WIDTHS):
            first, reloaded, still = data["results"][3 * index : 3 * index + 3]
            with self.subTest(width=width):
                for found in (first, reloaded, still):
                    self.assertNotIn("error", found, found)
                self.assertEqual(len(first["rate"]), 3, first)
                for gap in first["rate"]:
                    self.assertAlmostEqual(gap, 2000, delta=300, msg=first)
                self.assertEqual(first["flip"], {"turned": True, "ran": 1, "finished": True, "sand": "2s", "grains": 3}, first)
                self.assertLess(first["click"]["at"], 300, first)
                self.assertAlmostEqual(first["click"]["next"], 2000, delta=300, msg=first)
                self.assertEqual(first["sizes"]["headed"], 0, first)
                self.assertGreater(first["sizes"]["large"], 80, first)
                self.assertEqual(first["dial"], {"prevented": True, "from": 2, "to": 10, "closed": True}, first)
                self.assertFalse(first["wide"], first)
                self.assertEqual(reloaded["kept"]["quiet"], True, reloaded)
                self.assertEqual(reloaded["kept"]["sand"], "10s", reloaded)
                self.assertIn("every 10 s", reloaded["kept"]["title"], reloaded)
                self.assertEqual(reloaded["dial"], {"prevented": True, "from": 10, "to": 2, "closed": True}, reloaded)
                self.assertEqual(still, {"turned": True, "running": [0], "face": ["none"]}, still)


if __name__ == "__main__":
    unittest.main()
