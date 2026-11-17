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
from hub_support import iso
from kvb_orchestrator.viewstore import OVERLAYS, VIEW

OUT = Path(os.environ.get("E2E_OUT", "/tmp/hub-006-shots"))
PICKED = ["fix", "score"]
READ = """
  const chip = (key) => document.querySelector(`#main .legend-chip[data-path="burn.overlays"][data-chip="${key}"]`);
  const chips = () => Object.fromEntries(all('#main .legend-chip[data-path="burn.overlays"]').map((node) => [node.dataset.chip, node.getAttribute("aria-pressed")]));
  const drawn = () => Object.fromEntries(all("#main g.burn-overlay").map((group) => [group.dataset.overlay, Number(group.dataset.points)]));
  const axis = () => all("#main text.overlay-axis").length;
  const ready = () => Object.keys(chips()).length === @COUNT@ && document.querySelector("#main svg.burn");
  const stored = async () => (await (await fetch("/api/view", {cache: "no-store"})).json()).burn.overlays;
  const storedUntil = async (test, ms) => {
    const end = Date.now() + ms;
    while (Date.now() < end) {
      const kept = await stored();
      if (test(kept)) {
        return kept;
      }
      await sleep(200);
    }
    return null;
  };
  const look = () => ({chips: chips(), drawn: drawn(), axis: axis(), wide: document.documentElement.scrollWidth > innerWidth + 1});
"""
SWITCH = """(async () => {@HELPERS@@READ@
  if (!(await until(ready, 15000))) {
    return {error: text(document.getElementById("main"))};
  }
  const before = look();
  for (const key of @PICKED@) {
    chip(key).click();
  }
  const on = Boolean(await until(() => Object.keys(drawn()).length === @PICKED@.length, 6000));
  const saved = await storedUntil((kept) => kept.length === @PICKED@.length, 6000);
  return {before, on, after: look(), saved, violations: window.e2eViolations || null};
})()"""
KEPT = """(async () => {@HELPERS@@READ@
  if (!(await until(() => ready() && Object.keys(drawn()).length === @PICKED@.length, 15000))) {
    return {error: text(document.getElementById("main")), seen: look()};
  }
  const kept = look();
  if (@CLEAR@) {
    for (const key of @PICKED@) {
      chip(key).click();
    }
  }
  const off = @CLEAR@ ? Boolean(await until(() => !Object.keys(drawn()).length, 6000)) : null;
  const saved = @CLEAR@ ? await storedUntil((list) => !list.length, 6000) : await stored();
  return {kept, off, after: look(), saved, violations: window.e2eViolations || null};
})()"""
RESET = """(async () => {
  const current = await (await fetch("/api/view", {cache: "no-store"})).json();
  const reset = await fetch("/api/view", {method: "PATCH", headers: {"X-Kvb-Orchestrator": "1", "Content-Type": "application/json"}, body: JSON.stringify({set: @DEFAULTS@, expect: current}), cache: "no-store"});
  return {reset: reset.status};
})()"""


def probe(template: str, clear: bool = True) -> str:
    names = {
        "@HELPERS@": base.HELPERS, "@READ@": READ, "@COUNT@": str(len(OVERLAYS)), "@PICKED@": json.dumps(PICKED),
        "@CLEAR@": json.dumps(clear), "@DEFAULTS@": json.dumps(VIEW),
    }
    for key, value in names.items():
        template = template.replace(key, value)
    return template


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestScoreOverlays(HubCase):
    drive = base.OrchestratorE2ECase.drive

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        now = int(time.time())
        journal = [
            {"time": now - age, "branch": "master", "values": {"fix": fix, "break": 100 - fix, "tokens": 80, "velocity": 90, "security": 100, "score": fix - 5}}
            for age, fix in ((15000, 70), (8000, 85), (2000, 95))
        ]
        self.write_council({
            "scores.jsonl": self.jsonl(journal),
            "rasci.json": {
                "work/first": {"title": "First", "branch": "master", "status": "done", "worker": "Skills", "start": iso(now - 20000), "end": iso(now - 9000), "updated": iso(now - 9000), "roles": {"Skills": "RA"}},
                "work/second": {"title": "Second", "branch": "master", "status": "running", "worker": "Stage", "start": iso(now - 15000), "updated": iso(now - 600), "roles": {"Stage": "RA"}},
            },
        })
        self.base = f"http://{self.host}/"

    def steps(self, browser: str) -> list[dict]:
        steps = []
        for width, height in base.WIDTHS:
            shot = OUT / f"{browser}-{width}"
            steps += [
                {"width": width, "height": height, "url": f"{self.base}?{width}#tasks/burn", "wait": 1200, "probe": probe(SWITCH), "shot": f"{shot}-on.png"},
                {"width": width, "height": height, "url": f"{self.base}?{width}-reloaded#tasks/burn", "wait": 1200, "probe": probe(KEPT), "shot": f"{shot}-kept.png"},
            ]
        return steps

    def check_switch(self, found: dict, label: str) -> None:
        with self.subTest(step=label, part="switch"):
            self.assertNotIn("error", found, found)
            self.assertEqual(found["before"], {"chips": dict.fromkeys(OVERLAYS, "false"), "drawn": {}, "axis": 0, "wide": False})
            self.assertTrue(found["on"], found)
            after = found["after"]
            self.assertEqual(after["chips"], {key: str(key in PICKED).lower() for key in OVERLAYS})
            self.assertEqual(after["drawn"], dict.fromkeys(PICKED, 3))
            self.assertEqual((after["axis"], after["wide"]), (3, False))
            self.assertEqual(sorted(found["saved"]), PICKED)
            self.assertEqual(w4.quiet(found["violations"]), [])

    def check_kept(self, found: dict, label: str, cleared: bool) -> None:
        with self.subTest(step=label, part="kept"):
            self.assertNotIn("error", found, found)
            self.assertEqual(found["kept"]["chips"], {key: str(key in PICKED).lower() for key in OVERLAYS})
            self.assertEqual(found["kept"]["drawn"], dict.fromkeys(PICKED, 3))
            if cleared:
                self.assertTrue(found["off"], found)
                self.assertEqual((found["after"]["drawn"], found["after"]["axis"], found["saved"]), ({}, 0, []))
            else:
                self.assertEqual(sorted(found["saved"]), PICKED)
            self.assertEqual(w4.quiet(found["violations"]), [])

    def run_browser(self, browser: str, *driver: str) -> None:
        data = self.drive(self.steps(browser), None, *driver, init=w4.GUARD)
        (OUT / f"{browser}-score-overlays.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        results = iter(data["results"])
        for width, _ in base.WIDTHS:
            self.check_switch(next(results), f"{browser}-{width}")
            self.check_kept(next(results), f"{browser}-{width}", cleared=True)
        self.assertEqual(self.httpd.hub.view_store.get(), VIEW)

    def test_chromium_switches_score_overlays_that_persist_across_a_reload_at_three_widths(self):
        self.run_browser("chromium")

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_switches_score_overlays_that_persist_across_a_reload_at_three_widths(self):
        self.run_browser("firefox", "bidi.mjs", os.environ.get("FIREFOX", "firefox"))

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_overlays_switched_in_chromium_show_in_firefox(self):
        width, height = 1366, 768
        url = f"{self.base}?{width}-second#tasks/burn"
        first = self.drive([{"width": width, "height": height, "url": f"{self.base}?{width}#tasks/burn", "wait": 1200, "probe": probe(SWITCH), "shot": str(OUT / "chromium-second-on.png")}], None, init=w4.GUARD)
        self.check_switch(first["results"][0], "chromium-first")
        second = self.drive(
            [{"width": width, "height": height, "url": url, "wait": 1200, "probe": probe(KEPT, clear=False), "shot": str(OUT / "firefox-second-seen.png")},
             {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(RESET), "shot": None}],
            None, "bidi.mjs", os.environ.get("FIREFOX", "firefox"), init=w4.GUARD,
        )
        self.check_kept(second["results"][0], "firefox-second", cleared=False)
        self.assertEqual(second["results"][1], {"reset": 200})
        self.assertEqual(self.httpd.hub.view_store.get(), VIEW)


if __name__ == "__main__":
    unittest.main()
