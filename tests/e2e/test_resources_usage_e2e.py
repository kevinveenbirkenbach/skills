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
import test_resources_view_e2e as res
import test_workbench_w4_e2e as w4
from hub_case import HubCase

OUT = Path(os.environ.get("E2E_OUT", "/tmp/hub-070-shots"))
OPUS = "claude-opus-5-5"
KIT = """
  const box = () => document.querySelector("#main .res-usage");
  const rows = () => all("#main .res-usage tbody tr.use-row");
  const keys = () => rows().map((row) => row.dataset.key);
  const cells = (column) => rows().map((row) => text(row.querySelector(`[data-column="${column}"]`)));
  const group = () => document.querySelector("#main [data-usage-group]");
  const choose = (select, value) => {
    select.value = value;
    select.dispatchEvent(new Event("change", {bubbles: true}));
  };
  const sortBy = (key) => document.querySelector(`#main .res-usage [data-sort="${key}"]`).click();
  const sorted = () => all("#main .res-usage [data-usage-table] thead th").map((th) => th.getAttribute("aria-sort"));
  const filters = () => all("#main .res-usage [data-filter]").map((node) => node.dataset.filter);
  const split = () => Boolean(document.querySelector("#main .res-usage [data-usage-split]"));
  const context = () => all("#main .res-usage [data-usage-context] tbody tr").map((row) => all("td", row).map((cell) => text(cell)));
  const rowOf = (key) => rows().find((row) => row.dataset.key === key);
  const wide = () => ({wide: document.documentElement.scrollWidth > innerWidth + 1});
"""
EXPLORE = """(async () => {@HELPERS@@READ@@KIT@
  if (!(await until(() => document.querySelector("#main .res-panels-menu") && box(), 15000))) {
    return {error: text(document.getElementById("main"))};
  }
  await pickPanel("usage", true);
  if (!(await until(() => rows().length === 3, 8000))) {
    return {error: text(box())};
  }
  const bySkill = {group: group().value, keys: keys(), split: split(), context: context(), panels: panelsShown()};
  sortBy("cost");
  const byCost = {keys: keys(), costs: cells("cost"), sorted: sorted()};
  rowOf("kvb-help").click();
  const drilled = Boolean(await until(() => filters().join() === "skill" && keys().join() === "kvb-help", 6000));
  choose(group(), "tool");
  const regrouped = Boolean(await until(() => keys().join() === "Bash,Read," && split(), 6000));
  const byTool = {group: group().value, keys: keys(), shares: cells("share"), split: split(), filters: filters()};
  box().scrollIntoView({block: "start"});
  return {bySkill, byCost, drilled, switched: regrouped, byTool, page: wide(), violations: window.e2eViolations || null};
})()"""
RESET = """(async () => {@HELPERS@@READ@@KIT@
  document.querySelector('#main .res-usage [data-filter="skill"]').click();
  const cleared = Boolean(await until(() => !filters().length && keys().length === 4, 6000));
  const after = {keys: keys(), filters: filters()};
  await pickPanel("usage", false);
  return {cleared, after, panels: panelsShown(), page: wide(), violations: window.e2eViolations || null};
})()"""


def probe(template: str) -> str:
    for key, value in {"@HELPERS@": base.HELPERS, "@READ@": res.READ, "@KIT@": KIT}.items():
        template = template.replace(key, value)
    return template


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestResourcesUsage(HubCase):
    drive = base.OrchestratorE2ECase.drive
    sample = w4.TestWorkbenchResources.sample

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        now = int(time.time())
        self.start = now - now % 60 - w4.ROWS * 60
        hour = now - now % 3600 - 3600
        tokens = [
            {"t": hour, "agent": "Skills", "model": OPUS, "input": 1000, "output": 100, "cache_read": 3000, "cache_write": 0, "skill": "kvb-help", "tool": "Bash,Read"},
            {"t": hour, "agent": "Skills", "model": "claude-haiku-5-5", "input": 500, "output": 50, "cache_read": 0, "cache_write": 0, "skill": "kvb-help"},
            {"t": hour, "agent": "Stage", "model": OPUS, "input": 4000, "output": 1000, "cache_read": 0, "cache_write": 1000, "tool": "Edit"},
            {"t": hour, "agent": "Stage", "model": "mystery", "input": 50000, "output": 0, "cache_read": 0, "cache_write": 0, "skill": "i8-test", "tool": "Bash"},
        ]
        folder = self.kept / "resources"
        folder.mkdir()
        (folder / "samples.jsonl").write_text(self.jsonl([self.sample(index) for index in range(w4.ROWS)]), encoding="utf-8")
        (folder / "tokens.jsonl").write_text(self.jsonl([{name: value for name, value in row.items() if name not in ("skill", "tool")} for row in tokens]), encoding="utf-8")
        (folder / "usage.jsonl").write_text(self.jsonl(tokens), encoding="utf-8")
        (folder / "context.jsonl").write_text(self.jsonl([{"t": hour - hour % 86400, "agent": "Skills", "turns": {"12": 1, "30": 2, "99": 1}, "compactions": 2}]), encoding="utf-8")
        self.base = f"http://{self.host}/"

    def steps(self, browser: str) -> list[dict]:
        steps = []
        for width, height in base.WIDTHS:
            shot = OUT / f"{browser}-{width}"
            steps += [
                {"width": width, "height": height, "url": f"{self.base}?{width}#resources", "wait": 1200, "probe": probe(EXPLORE), "shot": f"{shot}-usage.png"},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(RESET), "shot": f"{shot}-usage-reset.png"},
            ]
        return steps

    def check(self, data: dict, browser: str) -> None:
        results = iter(data["results"])
        for width, _ in base.WIDTHS:
            explore, reset = next(results), next(results)
            with self.subTest(browser=browser, width=width):
                self.assertNotIn("error", explore, explore)
                by_skill = explore["bySkill"]
                self.assertEqual((by_skill["group"], by_skill["keys"], by_skill["split"]), ("skill", ["i8-test", "", "kvb-help"], False))
                self.assertEqual(by_skill["panels"][-1], ["resources-usage", False])
                self.assertEqual([(row[1], row[2], row[5]) for row in by_skill["context"]], [("Skills", "4", "2")])
                self.assertEqual(explore["byCost"]["keys"], ["", "kvb-help", "i8-test"])
                self.assertEqual(explore["byCost"]["costs"], ["$0.04", "$0.01", "–"])
                self.assertEqual(explore["byCost"]["sorted"], ["none"] * 7 + ["descending", "none"])
                self.assertTrue(explore["drilled"], explore)
                self.assertTrue(explore["switched"], explore)
                self.assertEqual(explore["byTool"], {"group": "tool", "keys": ["Bash", "Read", ""], "shares": ["88.2 %", "88.2 %", "11.8 %"], "split": True, "filters": ["skill"]})
                self.assertEqual(explore["page"], {"wide": False})
                self.assertEqual(w4.quiet(explore["violations"]), [])
                self.assertTrue(reset["cleared"], reset)
                self.assertEqual(reset["after"], {"keys": ["Edit", "Read", "", "Bash"], "filters": []})
                self.assertEqual(reset["panels"][-1], ["resources-usage", True])
                self.assertEqual(reset["page"], {"wide": False})
                self.assertEqual(w4.quiet(reset["violations"]), [])

    def test_chromium_groups_drills_down_and_sorts_the_usage_by_estimated_cost_at_three_widths(self):
        data = self.drive(self.steps("chromium"), None, init=w4.GUARD)
        (OUT / "chromium-resources-usage.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        self.check(data, "chromium")

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_groups_drills_down_and_sorts_the_usage_by_estimated_cost_at_three_widths(self):
        data = self.drive(self.steps("firefox"), None, "bidi.mjs", os.environ.get("FIREFOX", "firefox"), init=w4.GUARD)
        (OUT / "firefox-resources-usage.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        self.check(data, "firefox")


if __name__ == "__main__":
    unittest.main()
