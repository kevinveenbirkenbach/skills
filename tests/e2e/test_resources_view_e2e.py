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

import test_orchestrator_e2e as base
import test_workbench_w4_e2e as w4
from hub_case import HubCase
from hub_support import iso
from kvb_orchestrator.viewstore import VIEW

OUT = Path(os.environ.get("E2E_OUT", "/tmp/hub-007-shots"))
CPU = "host:CPU"
STAGE = "agent:Stage"
UTIL = "util:0000_3a_01_3a_00.0"
SCOPE = "burn:scope"
READ = """
  const charts = () => all("#main svg.res-chart").map((chart) => chart.dataset.chart);
  const chip = (id) => document.querySelector(`#main .res-panel:not([hidden]) .legend-chip[data-chip="${id}"]`);
  const pressed = () => Object.fromEntries(all("#main .res-panel:not([hidden]) .legend-chip").map((node) => [node.dataset.chip, node.getAttribute("aria-pressed")]));
  const lines = () => [...new Set(all("#main path.res-line").map((path) => path.dataset.id))];
  const agents = () => [...new Set(all("#main rect.res-bar").map((rect) => rect.dataset.agent))].sort();
  const sums = () => all("#main path.res-sum").map((path) => path.dataset.agent).sort();
  const rising = () => all("#main path.res-sum").every((path) => JSON.parse(path.dataset.points).every((value, index, list) => !index || value >= list[index - 1]));
  const burn = () => all("#main path.res-burn").map((path) => path.dataset.series);
  const switched = (key) => document.querySelector(`#main [data-switch="${key}"]`);
  const stored = async () => (await (await fetch("/api/view", {cache: "no-store"})).json()).resources;
  const storedUntil = async (test, ms) => {
    const end = Date.now() + ms;
    while (Date.now() < end) {
      const view = await stored();
      if (test(view)) {
        return view;
      }
      await sleep(200);
    }
    return null;
  };
  const legendFits = () => all("#main .res-panel:not([hidden])").every((panel) => panel.querySelector(".res-plot").getBoundingClientRect().height > 40);
  const page = () => ({tall: document.documentElement.scrollHeight > innerHeight, wide: document.documentElement.scrollWidth > innerWidth + 1, fits: legendFits()});
"""
TOGGLE = """(async () => {@HELPERS@@READ@
  if (!(await until(() => charts().length === 2 && chip("@CPU@") && chip("@STAGE@") && agents().length === 2, 15000))) {
    return {error: text(document.getElementById("main")), charts: charts()};
  }
  const before = {charts: charts(), lines: lines(), agents: agents(), pressed: pressed(), panels: all("#main .res-panel").map((panel) => [panel.dataset.panel, panel.hidden])};
  chip("@CPU@").click();
  await until(() => chip("@STAGE@") && !lines().includes("@CPU@"), 4000);
  chip("@STAGE@").click();
  const hidden = Boolean(await until(() => !lines().includes("@CPU@") && agents().join() === "Skills", 4000));
  const saved = await storedUntil((view) => view.hidden.includes("@CPU@") && view.hidden.includes("@STAGE@"), 6000);
  return {before, hidden, after: {charts: charts(), lines: lines(), agents: agents(), pressed: pressed()}, saved, page: page(), violations: window.e2eViolations || null};
})()"""
COMBINE = """(async () => {@HELPERS@@READ@
  if (!(await until(() => charts().length === 2 && chip("@CPU@"), 15000))) {
    return {error: text(document.getElementById("main")), charts: charts()};
  }
  const kept = {charts: charts(), lines: lines(), agents: agents(), cpu: pressed()["@CPU@"], stage: pressed()["@STAGE@"]};
  switched("tokens").click();
  const accumulated = Boolean(await until(() => sums().length === 1 && !agents().length, 4000));
  const sumsAt = {sums: sums(), rising: rising(), pressed: switched("tokens").getAttribute("aria-pressed")};
  switched("combined").click();
  const combinedOn = Boolean(await until(() => charts().join() === "combined" && burn().length === 2, 4000));
  const combined = {charts: charts(), lines: lines(), sums: sums(), burn: burn(), right: all('#main text[data-axis="right"]').length, pressed: pressed(), panels: all("#main .res-panel").map((panel) => [panel.dataset.panel, panel.hidden]), switch: switched("combined").getAttribute("aria-pressed")};
  return {kept, accumulated, sumsAt, combinedOn, combined, page: page(), violations: window.e2eViolations || null};
})()"""
DESELECT = """(async () => {@HELPERS@@READ@
  chip("@SCOPE@").click();
  await until(() => burn().join() === "done" && chip("@UTIL@"), 4000);
  chip("@UTIL@").click();
  const deselected = Boolean(await until(() => burn().join() === "done" && !lines().includes("@UTIL@"), 4000));
  const saved = await storedUntil((view) => view.combinedHidden.length === 2, 6000);
  const current = await (await fetch("/api/view", {cache: "no-store"})).json();
  const reset = await fetch("/api/view", {method: "PATCH", headers: {"X-Kvb-Orchestrator": "1", "Content-Type": "application/json"}, body: JSON.stringify({set: @DEFAULTS@, expect: current}), cache: "no-store"});
  return {deselected, burn: burn(), lines: lines(), saved, reset: reset.status, violations: window.e2eViolations || null};
})()"""


def probe(template: str) -> str:
    names = {"@HELPERS@": base.HELPERS, "@READ@": READ, "@CPU@": CPU, "@STAGE@": STAGE, "@UTIL@": UTIL, "@SCOPE@": SCOPE, "@DEFAULTS@": json.dumps(VIEW)}
    for key, value in names.items():
        template = template.replace(key, value)
    return template


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestResourcesView(HubCase):
    drive = base.TestOrchestratorE2E.drive
    sample = w4.TestWorkbenchResources.sample

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        now = int(time.time())
        self.start = now - now % 60 - w4.ROWS * 60
        hour = self.start - self.start % 3600
        tokens = [{"t": hour + step * 3600, "agent": "Skills", "model": "claude-opus-5-5", "input": 1000 * (step + 1), "output": 500, "cache_read": 20000, "cache_write": 1000} for step in range(7)]
        tokens += [{"t": hour + step * 3600, "agent": "Stage", "model": "claude-haiku-4-5", "input": 200, "output": 100, "cache_read": 3000, "cache_write": 0} for step in range(0, 7, 2)]
        folder = self.kept / "resources"
        folder.mkdir()
        (folder / "samples.jsonl").write_text(self.jsonl([self.sample(index) for index in range(w4.ROWS)]), encoding="utf-8")
        (folder / "tokens.jsonl").write_text(self.jsonl([row for row in tokens if row["t"] <= now]), encoding="utf-8")
        self.write_council({"rasci.json": {
            "work/first": {"title": "First", "status": "done", "worker": "Skills", "start": iso(now - 20000), "end": iso(now - 9000), "updated": iso(now - 9000), "roles": {"Skills": "RA"}},
            "work/second": {"title": "Second", "status": "running", "worker": "Stage", "start": iso(now - 15000), "updated": iso(now - 600), "roles": {"Stage": "RA"}},
            "work/third": {"title": "Third", "status": "done", "worker": "Skills", "start": iso(now - 7000), "end": iso(now - 3000), "updated": iso(now - 3000), "roles": {"Skills": "RA"}},
        }})
        self.base = f"http://{self.host}/"

    def steps(self, browser: str) -> list[dict]:
        steps = []
        for width, height in base.WIDTHS:
            shot = OUT / f"{browser}-{width}"
            steps += [
                {"width": width, "height": height, "url": f"{self.base}?{width}#resources", "wait": 1200, "probe": probe(TOGGLE), "shot": f"{shot}-chips.png"},
                {"width": width, "height": height, "url": f"{self.base}?{width}-reloaded#resources", "wait": 1200, "probe": probe(COMBINE), "shot": f"{shot}-combined.png"},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(DESELECT), "shot": f"{shot}-deselected.png"},
            ]
        return steps

    def check(self, data: dict, browser: str) -> None:
        results = iter(data["results"])
        hardware = ["disk:/", "disk:/boot/efi", CPU, "host:RAM", "host:Swap", UTIL, "vram:0000_3a_01_3a_00.0"]
        for width, _ in base.WIDTHS:
            toggle, combine, deselect = next(results), next(results), next(results)
            with self.subTest(browser=browser, width=width):
                self.assertNotIn("error", toggle, toggle)
                before = toggle["before"]
                self.assertEqual(before["charts"], ["hardware", "tokens"])
                self.assertEqual(before["panels"], [["resources-hardware", False], ["resources-tokens", False], ["resources-combined", True]])
                self.assertEqual((before["lines"], before["agents"]), (hardware, ["Skills", "Stage"]))
                self.assertEqual(set(before["pressed"].values()), {"true"})
                self.assertEqual(set(before["pressed"]), {*hardware, "agent:Skills", STAGE})
                self.assertTrue(toggle["hidden"], toggle)
                after = toggle["after"]
                self.assertEqual((after["charts"], after["lines"], after["agents"]), (["hardware", "tokens"], [line for line in hardware if line != CPU], ["Skills"]))
                self.assertEqual((after["pressed"][CPU], after["pressed"][STAGE], after["pressed"]["host:RAM"]), ("false", "false", "true"))
                self.assertEqual(toggle["saved"], {**VIEW["resources"], "hidden": [CPU, STAGE]})
                self.assertEqual(toggle["page"], {"tall": False, "wide": False, "fits": True})
                self.assertEqual(w4.quiet(toggle["violations"]), [])
                self.assertNotIn("error", combine, combine)
                self.assertEqual(combine["kept"], {"charts": ["hardware", "tokens"], "lines": [line for line in hardware if line != CPU], "agents": ["Skills"], "cpu": "false", "stage": "false"})
                self.assertTrue(combine["accumulated"], combine)
                self.assertEqual(combine["sumsAt"], {"sums": ["Skills"], "rising": True, "pressed": "true"})
                self.assertTrue(combine["combinedOn"], combine)
                combined = combine["combined"]
                self.assertEqual((combined["charts"], combined["lines"], combined["sums"], combined["burn"]), (["combined"], hardware, ["Skills", "Stage"], ["done", "scope"]))
                self.assertEqual((combined["right"], combined["switch"]), (2, "true"))
                self.assertEqual(combined["panels"], [["resources-hardware", True], ["resources-tokens", True], ["resources-combined", False]])
                self.assertEqual(set(combined["pressed"].values()), {"true"})
                self.assertEqual(set(combined["pressed"]), {*hardware, "agent:Skills", STAGE, "burn:done", SCOPE})
                self.assertEqual(combine["page"], {"tall": False, "wide": False, "fits": True})
                self.assertEqual(w4.quiet(combine["violations"]), [])
                self.assertTrue(deselect["deselected"], deselect)
                self.assertEqual((deselect["burn"], deselect["lines"]), (["done"], [line for line in hardware if line != UTIL]))
                self.assertEqual(deselect["saved"], {"hidden": [CPU, STAGE], "tokens": "accumulated", "combined": True, "combinedHidden": [SCOPE, UTIL]})
                self.assertEqual(deselect["reset"], 200)
                self.assertEqual(w4.quiet(deselect["violations"]), [])
        self.assertEqual(self.httpd.hub.view_store.get(), VIEW)

    def test_chromium_draws_two_charts_whose_chips_toggle_and_persist_and_a_combined_chart_at_three_widths(self):
        data = self.drive(self.steps("chromium"), None, init=w4.GUARD)
        (OUT / "chromium-resources-view.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        self.check(data, "chromium")

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_draws_two_charts_whose_chips_toggle_and_persist_and_a_combined_chart_at_three_widths(self):
        data = self.drive(self.steps("firefox"), None, "bidi.mjs", os.environ.get("FIREFOX", "firefox"), init=w4.GUARD)
        (OUT / "firefox-resources-view.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        self.check(data, "firefox")


if __name__ == "__main__":
    unittest.main()
