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
from hub_case import HubCase

OUT = Path(os.environ.get("E2E_OUT", "/tmp/workbench-w4-shots"))
GPU = "0000:01:00.0"
ROWS = 360
WAITED = (120, 180)
ASLEEP = 180
UNREAD = (300, 320)
PANELS = {"disks": "Disks", "host": "CPU, RAM and swap", "gpu": "GPU and VRAM", "tokens": "Tokens per agent"}
GUARD = """() => {
  window.e2eViolations = [];
  document.addEventListener("securitypolicyviolation", (event) => window.e2eViolations.push(`${event.violatedDirective} ${event.blockedURI}`));
}"""
CHARTS = """(async () => {@HELPERS@
  const counted = () => text(document.querySelector('#main [aria-label="Samples"]'));
  if (!(await until(() => all("#main svg.res-chart").length === 4 && counted() === "@ROWS@", 15000))) {
    return {error: text(document.getElementById("main")), count: counted()};
  }
  await sleep(300);
  const charts = all("#main svg.res-chart");
  const number = (node, key) => Number(node.dataset[key]);
  const attr = (node, key) => Number(node.getAttribute(key));
  const stacks = {};
  for (const rect of all("#main rect.res-bar")) {
    (stacks[rect.dataset.t] = stacks[rect.dataset.t] || []).push({agent: rect.dataset.agent, y: attr(rect, "y"), height: attr(rect, "height")});
  }
  const piles = Object.values(stacks).map((parts) => parts.sort((a, b) => b.y - a.y));
  const labelled = (node) => (node ? [node.getAttribute("title"), node.getAttribute("aria-label")] : null);
  return {
    panels: all("#main .res-panel").map((panel) => panel.dataset.panel),
    axes: [...new Set(charts.map((chart) => `${chart.dataset.from}|${chart.dataset.to}`))],
    since: number(charts[0], "from"),
    bands: charts.filter((chart) => chart.dataset.panel !== "tokens").map((chart) => {
      const [idle, saturated] = [chart.querySelector("rect.band.idle"), chart.querySelector("rect.band.saturated")];
      return [chart.dataset.panel, attr(idle, "height") / attr(saturated, "height"), attr(idle, "y") > attr(saturated, "y")];
    }),
    series: charts.map((chart) => [chart.dataset.panel, [...new Set(all("path.res-line", chart).map((path) => `${path.dataset.series}|${path.dataset.kind}`))]]),
    waits: all("#main rect.res-mark.wait").map((rect) => [number(rect, "from"), number(rect, "to"), number(rect, "peak")]),
    asleep: all("#main rect.res-mark.asleep").map((rect) => [number(rect, "from"), number(rect, "to")]),
    unknown: all("#main rect.res-mark.unknown").map((rect) => [number(rect, "from"), number(rect, "to")]),
    agents: [...new Set(all("#main rect.res-bar").map((rect) => rect.dataset.agent))].sort(),
    bottoms: [...new Set(piles.map((parts) => parts[0].agent))],
    stacked: piles.every((parts) => parts.every((part, index) => !index || Math.abs(part.y + part.height - parts[index - 1].y) < 0.2)),
    legend: all("#main .res-host .res-key").map(text),
    labels: {tab: labelled(document.getElementById("tab-resources")), reload: labelled(document.querySelector('#main [aria-label="Reload"]')), titles: all("#main .res-title").map(labelled)},
    unlabelled: all("#main svg.bi").map((svg) => svg.parentElement).filter((owner) => !text(owner) && !(owner.getAttribute("title") && owner.getAttribute("aria-label"))).length,
    plots: all("#main .res-plot").map((plot) => plot.getBoundingClientRect().height > 20),
    tall: document.documentElement.scrollHeight > innerHeight,
    wide: document.documentElement.scrollWidth > innerWidth + 1,
    violations: window.e2eViolations || null,
  };
})()"""
KEY = """(async () => {@HELPERS@
  document.body.dispatchEvent(new KeyboardEvent("keydown", {key: "5", bubbles: true}));
  const opened = Boolean(await until(() => location.hash === "#resources" && document.querySelector("#main svg.res-chart"), 8000));
  return {opened, current: document.getElementById("tab-resources").getAttribute("aria-current")};
})()"""


def probe(template: str) -> str:
    return template.replace("@HELPERS@", base.HELPERS).replace("@ROWS@", str(ROWS))


def quiet(found: list[str] | None) -> list[str] | None:
    return None if found is None else [seen for seen in found if not seen.endswith("/favicon.ico")]


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestWorkbenchResources(HubCase):
    drive = base.TestOrchestratorE2E.drive

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        now = int(time.time())
        self.start = now - now % 60 - ROWS * 60
        samples = [self.sample(index) for index in range(ROWS)]
        hour = self.start - self.start % 3600
        tokens = [{"t": hour + step * 3600, "agent": "Skills", "model": "claude-opus-5-5", "input": 1000 * (step + 1), "output": 500, "cache_read": 20000, "cache_write": 1000} for step in range(7)]
        tokens += [{"t": hour + step * 3600, "agent": "Stage", "model": "claude-haiku-4-5", "input": 200, "output": 100, "cache_read": 3000, "cache_write": 0} for step in range(0, 7, 2)]
        folder = self.kept / "resources"
        folder.mkdir()
        (folder / "samples.jsonl").write_text(self.jsonl(samples), encoding="utf-8")
        (folder / "tokens.jsonl").write_text(self.jsonl([row for row in tokens if row["t"] <= now]), encoding="utf-8")
        self.base = f"http://{self.host}/"

    def sample(self, index: int) -> dict:
        waited, saturated = WAITED[0] <= index < WAITED[1], WAITED[1] <= index < WAITED[1] + 60
        cpu, ram, waiting = (25, 35, 2) if waited else (95, 60, 1) if saturated else (10, 20, 0) if index < WAITED[0] else (60, 55, 0)
        gpu = {"name": GPU, "asleep": True} if index < ASLEEP else {"name": GPU, "util": None, "vram_used": None, "vram_total": None} if UNREAD[0] <= index < UNREAD[1] else {"name": GPU, "util": 50, "vram_used": 2048 << 20, "vram_total": 8192 << 20}
        root = 950 if index >= ROWS - 60 else 400
        disks = [{"mount": "/", "used": root << 30, "total": 1000 << 30}, {"mount": "/boot/efi", "used": 3 << 20, "total": 100 << 20}]
        return {"t": self.start + index * 60, "disks": disks, "cpu": cpu, "ram": ram, "swap": 5, "load": cpu / 25, "gpus": [gpu], "queue": {"waiting": waiting, "active": 1}}

    def steps(self, browser: str) -> list[dict]:
        steps = [{"width": width, "height": height, "url": f"{self.base}?{width}#resources", "wait": 1200, "probe": probe(CHARTS), "shot": str(OUT / f"{browser}-{width}-resources.png")} for width, height in base.WIDTHS]
        steps.append({"width": 1366, "height": 768, "url": f"{self.base}?key#stream", "wait": 1200, "probe": probe(KEY), "shot": None})
        return steps

    def check(self, data: dict, browser: str) -> None:
        results = data["results"]
        for (width, _), found in zip(base.WIDTHS, results, strict=False):
            with self.subTest(browser=browser, width=width):
                self.assertNotIn("error", found, found)
                self.assertEqual(found["panels"], list(PANELS))
                self.assertEqual(len(found["axes"]), 1, found["axes"])
                self.assertLess(abs(found["since"] - (time.time() - 86400)), 600)
                self.assertEqual([(panel, lower) for panel, _, lower in found["bands"]], [("disks", True), ("host", True), ("gpu", True)])
                for panel, ratio, _ in found["bands"]:
                    self.assertAlmostEqual(ratio, 3, delta=0.2, msg=panel)
                self.assertEqual(found["series"], [["disks", ["/|disk", "/boot/efi|disk"]], ["host", ["CPU|host", "RAM|host", "Swap|host"]], ["gpu", [f"{GPU}|util", f"{GPU}|vram"]], ["tokens", []]])
                self.assertEqual(found["waits"], [[self.start + WAITED[0] * 60, self.start + WAITED[1] * 60, 2]])
                self.assertEqual(found["asleep"], [[self.start, self.start + ASLEEP * 60]])
                self.assertEqual(found["unknown"], [[self.start + UNREAD[0] * 60, self.start + UNREAD[1] * 60]])
                self.assertEqual((found["agents"], found["bottoms"], found["stacked"]), (["Skills", "Stage"], ["Skills"], True))
                self.assertEqual(found["legend"], ["CPU 60 %", "RAM 55 %", "Swap 5 %"])
                self.assertEqual(found["labels"], {"tab": ["Resources (key 6)", "Resources"], "reload": ["Reload: read the sampler files again", "Reload"], "titles": [[name, name] for name in PANELS.values()]})
                self.assertEqual((found["unlabelled"], found["plots"]), (0, [True] * 4))
                self.assertEqual((found["tall"], found["wide"]), (False, False), "the page scrolls")
                self.assertEqual(quiet(found["violations"]), [])
        self.assertEqual(results[len(base.WIDTHS)], {"opened": True, "current": "page"})

    def test_chromium_draws_the_resources_charts_from_the_sampler_files_at_three_widths(self):
        data = self.drive(self.steps("chromium"), None, init=GUARD)
        (OUT / "chromium-resources.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        self.check(data, "chromium")

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_draws_the_resources_charts_from_the_sampler_files_at_three_widths(self):
        data = self.drive(self.steps("firefox"), None, "bidi.mjs", os.environ.get("FIREFOX", "firefox"), init=GUARD)
        (OUT / "firefox-resources.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        self.check(data, "firefox")


if __name__ == "__main__":
    unittest.main()
