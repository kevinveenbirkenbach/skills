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

OUT = Path(os.environ.get("E2E_OUT", "/tmp/hub-header-rates-shots"))
HOUR = 3600
GIB = 1 << 30
PERIODS = {1920: "day", 1366: "week", 390: "minute"}
BEFORE = {1920: "hour", 1366: "day", 390: "week"}
CHOSEN = {1920: ["tasks", "tokens", "commits"], 1366: ["tasks", "tokens", "cpu"], 390: ["tasks", "tokens", "commits"]}
TASKS = {"minute": ("≈ 0.02/min", "true"), "hour": ("1/h", "false"), "day": ("2/d", "false"), "week": ("2/wk", "false"), "month": ("2/mo", "false"), "year": ("2/yr", "false"), "total": ("2", "false")}
METRICS = ["tasks", "commits", "krs", "tokens", "cpu", "ram", "vram", "swap", "disk"]
HEAD = ["Metric", "Chip", "min", "h", "d", "wk", "mo", "yr", "all"]
READ = """
  const chip = () => document.querySelector("#rates summary.rates-chip");
  const period = () => document.querySelector('#rates select[aria-label="Rate period"]');
  const menu = () => document.querySelector("#rates details.rates-menu");
  const box = () => document.querySelector("#rates .rates-box");
  const pick = (id) => document.querySelector(`#rates tr[data-metric="${id}"] input[type="checkbox"]`);
  const metrics = () => all("#rates summary .rate").map((node) => node.dataset.metric);
  const values = () => Object.fromEntries(all("#rates summary .rate").map((node) => [node.dataset.metric, text(node)]));
  const loaded = () => Boolean(chip() && metrics().length && !text(chip()).includes("…"));
  const stored = async () => (await (await fetch("/api/state", {cache: "no-store"})).json()).settings.rates;
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
  const inside = (node) => {
    const rect = node.getBoundingClientRect();
    return rect.width > 0 && rect.left >= -1 && rect.right <= innerWidth + 1;
  };
  const fits = () => {
    const bar = document.querySelector(".navbar");
    return {wide: document.documentElement.scrollWidth > innerWidth + 1, bar: bar.scrollWidth > bar.clientWidth + 1, chip: inside(chip()), period: inside(period())};
  };
"""
CHOOSE = """(async () => {@HELPERS@@READ@
  if (!(await until(loaded, 15000))) {
    return {error: text(document.getElementById("rates"))};
  }
  const before = {period: period().value, metrics: metrics()};
  period().value = "@PERIOD@";
  period().dispatchEvent(new Event("change", {bubbles: true}));
  const saved = await storedUntil((found) => found.period === "@PERIOD@", 8000);
  await until(() => period().value === "@PERIOD@" && loaded(), 4000);
  return {before, saved, after: {period: period().value, metrics: metrics(), values: values(), label: chip().getAttribute("aria-label")}, fits: fits(), open: menu().open, violations: window.e2eViolations || null};
})()"""
OPEN = """(async () => {@HELPERS@@READ@
  if (!(await until(loaded, 15000))) {
    return {error: text(document.getElementById("rates"))};
  }
  const kept = {period: period().value, metrics: metrics(), values: values()};
  chip().click();
  const opened = Boolean(await until(() => menu().open && box().getClientRects().length, 4000));
  const head = all("#rates .rates-table thead th").map(text);
  const rows = all("#rates .rates-table tbody tr").map((row) => [row.dataset.metric, all("td[data-period]", row).length]);
  const current = all('#rates .rates-table td[aria-current="true"]').map((cell) => cell.dataset.period);
  const tasks = Object.fromEntries(all('#rates tr[data-metric="tasks"] td[data-period]').map((cell) => [cell.dataset.period, [text(cell), cell.dataset.approx]]));
  const hint = document.querySelector('#rates tr[data-metric="tasks"] td[data-period="minute"]').title;
  const [drop, add] = metrics().includes("cpu") ? ["cpu", "commits"] : ["commits", "cpu"];
  const locked = pick(add).disabled;
  pick(drop).click();
  await storedUntil((found) => !found.metrics.includes(drop), 8000);
  await until(() => !metrics().includes(drop) && pick(add) && !pick(add).disabled, 4000);
  const fewest = all("#rates tbody input:checked").map((input) => input.disabled);
  pick(add).click();
  const swapped = await storedUntil((found) => found.metrics.includes(add), 8000);
  await until(() => metrics().includes(add), 4000);
  return {kept, opened, head, rows, current, tasks, hint, locked, fewest, swapped, chip: metrics(), box: inside(box()), fits: fits(), open: menu().open, violations: window.e2eViolations || null};
})()"""
CLOSE = """(async () => {@HELPERS@@READ@
  const was = menu().open;
  document.body.dispatchEvent(new KeyboardEvent("keydown", {key: "Escape", bubbles: true}));
  const escaped = Boolean(await until(() => !menu().open, 3000));
  chip().click();
  const reopened = Boolean(await until(() => menu().open, 3000));
  chip().click();
  const clicked = Boolean(await until(() => !menu().open, 3000));
  chip().click();
  await until(() => menu().open, 3000);
  document.getElementById("main").click();
  const outside = Boolean(await until(() => !menu().open, 3000));
  return {was, escaped, reopened, clicked, outside, fits: fits(), violations: window.e2eViolations || null};
})()"""


def probe(template: str, width: int) -> str:
    names = {"@HELPERS@": base.HELPERS, "@READ@": READ, "@PERIOD@": PERIODS[width]}
    for key, value in names.items():
        template = template.replace(key, value)
    return template


def sample(t: int) -> dict:
    gpus = [{"name": "0000:01:00.0", "util": 30.0, "vram_used": 2 * GIB, "vram_total": 8 * GIB}]
    return {"t": t, "disks": [{"mount": "/", "used": 400 << 30, "total": 1000 << 30}], "cpu": 25.0, "ram": 40.0, "swap": 5.0, "load": 1.0, "gpus": gpus, "queue": {"waiting": 0, "active": 0}}


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestRatesChip(HubCase):
    drive = base.OrchestratorE2ECase.drive

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        now = int(time.time())
        hour = now - now % HOUR
        folder = self.kept / "resources"
        folder.mkdir()
        (folder / "samples.jsonl").write_text(self.jsonl([sample(now - 2 * HOUR + step * 60) for step in range(140)]), encoding="utf-8")
        tokens = [{"t": t, "agent": "Skills", "model": "claude-opus-5-5", "input": 4000, "output": 1000, "cache_read": 20000, "cache_write": 500} for t in (hour - HOUR, hour)]
        (folder / "tokens.jsonl").write_text(self.jsonl(tokens), encoding="utf-8")
        self.write_council({"rasci.json": {
            "work/first": {"title": "First", "status": "done", "worker": "Skills", "start": iso(now - 5 * HOUR), "end": iso(now - 3 * HOUR), "roles": {"Skills": "RA"}},
            "work/second": {"title": "Second", "status": "done", "worker": "Skills", "start": iso(now - 2 * HOUR), "end": iso(now - 1200), "roles": {"Skills": "RA"}, "key_results": [{"text": "shipped", "met": True, "met_at": iso(now - 1300)}]},
            "work/third": {"title": "Third", "status": "running", "worker": "Stage", "start": iso(now - HOUR), "roles": {"Stage": "RA"}},
        }})
        (self.council / "scores.jsonl").write_text(json.dumps({"time": now - 2 * HOUR, "remote": "example.org/skills", "path": "/repo", "branch": "main", "sha": "d" * 40, "values": {"score": 90}, "digest": "0" * 64}) + "\n", encoding="utf-8")
        self.base = f"http://{self.host}/"

    def steps(self, browser: str) -> list[dict]:
        steps = []
        for width, height in base.WIDTHS:
            shot = OUT / f"{browser}-{width}"
            steps += [
                {"width": width, "height": height, "url": f"{self.base}?{width}#home", "wait": 1200, "probe": probe(CHOOSE, width), "shot": f"{shot}-chip.png"},
                {"width": width, "height": height, "url": f"{self.base}?{width}-reloaded#home", "wait": 1200, "probe": probe(OPEN, width), "shot": f"{shot}-popover.png"},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(CLOSE, width), "shot": None},
            ]
        return steps

    def check(self, data: dict, browser: str) -> None:
        results = iter(data["results"])
        fitting = {"wide": False, "bar": False, "chip": True, "period": True}
        previous = ["tasks", "tokens", "cpu"]
        for width, _ in base.WIDTHS:
            chosen, opened, closed = next(results), next(results), next(results)
            chip = {"day": "2/d", "week": "2/wk", "minute": "≈ 0.02/min"}[PERIODS[width]]
            with self.subTest(browser=browser, width=width):
                self.assertNotIn("error", chosen, chosen)
                self.assertEqual(chosen["before"], {"period": BEFORE[width], "metrics": previous})
                self.assertEqual(chosen["saved"], {"period": PERIODS[width], "metrics": previous})
                self.assertEqual((chosen["after"]["period"], chosen["after"]["metrics"], chosen["after"]["values"]["tasks"]), (PERIODS[width], previous, chip))
                self.assertTrue(chosen["after"]["label"].startswith("Rates per "), chosen["after"])
                self.assertEqual((chosen["fits"], chosen["open"]), (fitting, False))
                self.assertEqual(w4.quiet(chosen["violations"]), [])
                self.assertNotIn("error", opened, opened)
                self.assertEqual((opened["kept"]["period"], opened["kept"]["metrics"], opened["kept"]["values"]["tasks"]), (PERIODS[width], previous, chip))
                self.assertTrue(opened["opened"], opened)
                self.assertEqual((opened["head"], opened["rows"], opened["current"]), (HEAD, [[metric, 7] for metric in METRICS], [PERIODS[width]] * len(METRICS)))
                self.assertEqual({period: tuple(cell) for period, cell in opened["tasks"].items()}, TASKS)
                self.assertIn("scaled from the last hour", opened["hint"])
                self.assertEqual((opened["locked"], opened["fewest"]), (True, [True, True]))
                self.assertEqual((opened["swapped"], opened["chip"]), ({"period": PERIODS[width], "metrics": CHOSEN[width]}, CHOSEN[width]))
                self.assertEqual((opened["box"], opened["fits"], opened["open"]), (True, fitting, True))
                self.assertEqual(w4.quiet(opened["violations"]), [])
                self.assertEqual({key: closed[key] for key in ("was", "escaped", "reopened", "clicked", "outside")}, dict.fromkeys(("was", "escaped", "reopened", "clicked", "outside"), True))
                self.assertEqual((closed["fits"], w4.quiet(closed["violations"])), (fitting, []))
            previous = CHOSEN[width]
        self.assertEqual(self.httpd.hub.settings.get()["rates"], {"period": PERIODS[390], "metrics": CHOSEN[390]})

    def test_chromium_shows_the_rates_chip_keeps_its_period_over_a_reload_and_opens_and_closes_the_table_at_three_widths(self):
        data = self.drive(self.steps("chromium"), None, init=w4.GUARD)
        (OUT / "chromium-rates.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        self.check(data, "chromium")

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_shows_the_rates_chip_keeps_its_period_over_a_reload_and_opens_and_closes_the_table_at_three_widths(self):
        data = self.drive(self.steps("firefox"), None, "bidi.mjs", os.environ.get("FIREFOX", "firefox"), init=w4.GUARD)
        (OUT / "firefox-rates.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        self.check(data, "firefox")


if __name__ == "__main__":
    unittest.main()
