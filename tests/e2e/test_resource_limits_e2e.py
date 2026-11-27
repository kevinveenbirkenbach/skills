"""Exercise requirement 084: limit lines and the target on the Hardware chart, the dial, the profile switch, the Limits sheet and the passkey to loosen."""

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

OUT = Path(os.environ.get("E2E_OUT", "/tmp/hub-084-shots"))
LEVELS = ("lower", "upper", "stop", "mayday")
PROFILES = {name: {metric: dict(zip(LEVELS, values, strict=True)) for metric, values in table.items()} for name, table in limiting.PROFILE_TABLE.items()}
TARGET = {"cpu": 84.0, "ram": 80.5, "psi": 0.2, "stepped": 1, "samples": []}
READ = """
  const chart = () => document.querySelector('#main svg.res-chart[data-chart="hardware"]');
  const lines = () => all("g.res-limit", chart() || document).map((node) => [node.dataset.metric, node.dataset.level, Number(node.dataset.value), text(node.querySelector("text")), text(node.querySelector("title"))]);
  const target = () => all("g.res-target", chart() || document).map((node) => [node.dataset.metric, Number(node.dataset.value), text(node.querySelector("text"))]);
  const line = (level) => (chart() ? chart().querySelector(`g.res-limit.${level}`) : null);
  const pressed = (group) => all(`#main [aria-label="${group}"] button[aria-pressed="true"]`).map(text);
  const button = (group, label) => all(`#main [aria-label="${group}"] button`).find((node) => text(node) === label);
  const sheet = () => {
    const box = document.querySelector("#sheet:not([hidden]) .sheet-box");
    return box ? box.getAttribute("aria-label") : null;
  };
  const dialRoot = () => document.querySelector("#sheet .limit-dial");
  const key = (name) => dialRoot().dispatchEvent(new KeyboardEvent("keydown", {key: name, bubbles: true, cancelable: true}));
  const toasts = () => all("#toasts .toast").map(text);
  const stored = async () => (await (await fetch("/api/limits", {cache: "no-store"})).json()).limits;
  const posts = [];
  const send = window.fetch.bind(window);
  window.fetch = (path, init) => {
    if (String(path).startsWith("/api/limits") && init && init.method === "POST") {
      posts.push([String(path), JSON.parse(init.body).proof === undefined ? "sign" : JSON.parse(init.body).proof === null ? "unsigned" : "signed"]);
    }
    return send(path, init);
  };
  const ready = () => until(() => lines().length === 4, 15000);
  const page = () => ({wide: document.documentElement.scrollWidth > innerWidth + 1, plot: Math.round(document.querySelector("#main .res-hardware .res-plot").getBoundingClientRect().height)});
"""
LINES = """(async () => {@HELPERS@@READ@
  if (!(await ready())) {
    return {error: text(document.getElementById("main"))};
  }
  const cpu = {lines: lines(), target: target(), profile: pressed("Profile"), metric: pressed("Limit lines")};
  button("Limit lines", "RAM").click();
  await until(() => lines().every(([metric]) => metric === "ram"), 4000);
  const ram = {lines: lines(), target: target(), metric: pressed("Limit lines")};
  button("Limit lines", "PSI").click();
  await until(() => lines().every(([metric]) => metric === "psi"), 4000);
  const psi = {lines: lines(), target: target()};
  button("Limit lines", "CPU").click();
  await until(() => lines().every(([metric]) => metric === "cpu"), 4000);
  return {cpu, ram, psi, page: page(), violations: window.e2eViolations || null};
})()"""
DIAL = """(async () => {@HELPERS@@READ@
  if (!(await ready())) {
    return {error: text(document.getElementById("main"))};
  }
  navigator.credentials.get = () => Promise.reject(new DOMException("No passkey for a tighter value.", "NotAllowedError"));
  line("upper").dispatchEvent(new MouseEvent("click", {bubbles: true}));
  const opened = await until(() => sheet() === "CPU upper" && dialRoot(), 4000);
  const before = dialRoot().getAttribute("aria-valuenow");
  ["ArrowDown", "ArrowDown", "ArrowDown", "ArrowDown", "ArrowDown"].forEach(key);
  const turned = dialRoot().getAttribute("aria-valuenow");
  document.querySelector("#sheet .limit-save").click();
  const closed = Boolean(await until(() => sheet() === null, 6000));
  await until(() => lines().some(([, level, value]) => level === "upper" && value === 85), 4000);
  const tighter = {opened: Boolean(opened), before, turned, closed, posts: [...posts], stored: (await stored()).cpu, lines: lines()};
  posts.length = 0;
  line("lower").dispatchEvent(new MouseEvent("click", {bubbles: true}));
  await until(() => sheet() === "CPU lower" && dialRoot(), 4000);
  key("End");
  document.querySelector("#sheet .limit-save").click();
  const error = await until(() => {
    const node = document.querySelector("#sheet .limit-error:not([hidden])");
    return node ? text(node) : null;
  }, 4000);
  const broken = {error, open: sheet(), posts: [...posts], stored: (await stored()).cpu};
  document.querySelector("#sheet .limit-cancel").click();
  return {tighter, broken, closed: sheet() === null};
})()"""
CANCEL = """(async () => {@HELPERS@@READ@
  if (!(await ready())) {
    return {error: text(document.getElementById("main"))};
  }
  navigator.credentials.get = () => Promise.reject(new DOMException("The operator canceled.", "NotAllowedError"));
  button("Profile", "Max").click();
  const toast = await until(() => toasts().find((words) => words.includes("not signed")), 6000);
  await sleep(500);
  return {toast, posts: [...posts], stored: await stored(), profile: pressed("Profile"), lines: lines()};
})()"""
SIGN = """(async () => {@HELPERS@@READ@
  if (!(await ready())) {
    return {error: text(document.getElementById("main"))};
  }
  button("Profile", "Max").click();
  const moved = await until(() => pressed("Profile").join() === "Max" && lines().some(([, level, value]) => level === "upper" && value === 95), 15000);
  return {moved: Boolean(moved), posts: [...posts], stored: await stored(), profile: pressed("Profile"), lines: lines()};
})()"""
SHEET = """(async () => {@HELPERS@@READ@
  if (!(await ready())) {
    return {error: text(document.getElementById("main"))};
  }
  document.getElementById("limits-open").click();
  await until(() => sheet() === "Limits", 4000);
  const table = all('#sheet table[aria-label="Limits"] tbody tr').map((row) => [row.dataset.metric, ...all("button.limit-cell", row).map(text)]);
  const head = all('#sheet table[aria-label="Limits"] thead th').map(text);
  document.querySelector('#sheet button.limit-cell[data-metric="disk"][data-level="stop"]').click();
  const dialed = await until(() => sheet() === "Disk STOP" && dialRoot(), 4000);
  const value = dialed ? dialRoot().getAttribute("aria-valuenow") : null;
  document.querySelector("#sheet .limit-cancel").click();
  const back = await until(() => sheet() === "Limits", 4000);
  return {table, head, dialed: Boolean(dialed), value, back: Boolean(back), wide: document.documentElement.scrollWidth > innerWidth + 1};
})()"""


def probe(source: str) -> str:
    return source.replace("@HELPERS@", base.HELPERS).replace("@READ@", READ)


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestResourceLimits(HubCase):
    drive = base.OrchestratorE2ECase.drive
    authenticator = base.OrchestratorE2ECase.authenticator
    sample = w4.TestWorkbenchResources.sample

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

    def test_every_width_draws_four_labelled_lines_and_the_target_per_metric(self):
        data = self.drive([self.step(width, height, "lines", LINES) for width, height in base.WIDTHS], None, init=w4.GUARD)
        balanced = PROFILES["balanced"]
        for (width, _), found in zip(base.WIDTHS, data["results"], strict=True):
            with self.subTest(width=width):
                self.assertNotIn("error", found, found)
                cpu = found["cpu"]
                self.assertEqual([entry[:3] for entry in cpu["lines"]], [["cpu", level, balanced["cpu"][level]] for level in LEVELS])
                self.assertEqual([entry[3] for entry in cpu["lines"]], [f"{name} {balanced['cpu'][level]}" for name, level in zip(("lower", "upper", "STOP", "MAYDAY"), LEVELS, strict=True)])
                self.assertTrue(all(entry[4].startswith(f"CPU {entry[3]} %") for entry in cpu["lines"]), cpu["lines"])
                self.assertEqual(cpu["target"], [["cpu", 84, "target 84"]])
                self.assertEqual((cpu["profile"], cpu["metric"]), (["Balanced"], ["CPU"]))
                self.assertEqual([entry[2] for entry in found["ram"]["lines"]], [balanced["ram"][level] for level in LEVELS])
                self.assertEqual(found["ram"]["target"], [["ram", 80.5, "target 81"]])
                self.assertEqual(found["ram"]["metric"], ["RAM"])
                self.assertEqual(([entry[2] for entry in found["psi"]["lines"]], found["psi"]["target"]), ([balanced["psi"][level] for level in LEVELS], []))
                self.assertFalse(found["page"]["wide"])
                self.assertGreater(found["page"]["plot"], 40)
                self.assertEqual(w4.quiet(found["violations"]), [])

    def test_a_tighter_dial_value_saves_without_the_passkey_and_a_broken_order_does_not_save(self):
        found = self.drive([self.step(1366, 768, "dial", DIAL)], None, init=w4.GUARD)["results"][0]
        self.assertNotIn("error", found, found)
        tighter = found["tighter"]
        self.assertEqual((tighter["opened"], tighter["before"], tighter["turned"], tighter["closed"]), (True, "90", "85", True))
        self.assertEqual(tighter["posts"], [["/api/limits/sign", "sign"], ["/api/limits", "unsigned"]])
        self.assertEqual(tighter["stored"], {**PROFILES["balanced"]["cpu"], "upper": 85})
        broken = found["broken"]
        self.assertIn("breaks lower < upper < STOP < MAYDAY", broken["error"])
        self.assertEqual((broken["open"], broken["posts"], broken["stored"]), ("CPU lower", [], {**PROFILES["balanced"]["cpu"], "upper": 85}))
        self.assertTrue(found["closed"])
        self.assertEqual(self.stored()["cpu"]["upper"], 85)

    def test_a_canceled_passkey_keeps_the_old_limits_and_a_signed_one_switches_the_profile(self):
        self.pin()
        canceled = self.drive([self.step(1366, 768, "cancel", CANCEL)], None, init=w4.GUARD)["results"][0]
        self.assertNotIn("error", canceled, canceled)
        self.assertTrue(canceled["toast"].startswith("Profile Max"), canceled["toast"])
        self.assertEqual((canceled["posts"], canceled["stored"], canceled["profile"]), ([["/api/limits/sign", "sign"]], PROFILES["balanced"], ["Balanced"]))
        self.assertEqual(self.stored(), PROFILES["balanced"])
        steps = [self.step(width, height, "max", SIGN) for width, height in base.WIDTHS[:1]]
        signed = self.drive(steps, self.authenticator(), init=w4.GUARD)["results"][0]
        self.assertNotIn("error", signed, signed)
        self.assertTrue(signed["moved"], signed)
        self.assertEqual((signed["posts"], signed["profile"]), ([["/api/limits/sign", "sign"], ["/api/limits", "signed"]], ["Max"]))
        self.assertEqual(signed["stored"], PROFILES["max"])
        self.assertEqual([entry[2] for entry in signed["lines"]], [PROFILES["max"]["cpu"][level] for level in LEVELS])
        self.assertEqual(self.stored(), PROFILES["max"])

    def test_the_limits_sheet_lists_every_value_each_with_its_dial_at_every_width(self):
        data = self.drive([self.step(width, height, "sheet", SHEET) for width, height in base.WIDTHS], None, init=w4.GUARD)
        balanced = PROFILES["balanced"]
        for (width, _), found in zip(base.WIDTHS, data["results"], strict=True):
            with self.subTest(width=width):
                self.assertNotIn("error", found, found)
                self.assertEqual(found["head"], ["Metric", "lower", "upper", "STOP", "MAYDAY"])
                self.assertEqual(found["table"], [[metric, *(f"{balanced[metric][level]} %" for level in LEVELS)] for metric in balanced])
                self.assertEqual((found["dialed"], found["value"], found["back"]), (True, str(balanced["disk"]["stop"]), True))
                self.assertFalse(found["wide"])


if __name__ == "__main__":
    unittest.main()
