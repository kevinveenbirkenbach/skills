"""Exercise requirement 072: the Controls tab Queue shows the learnings and the settings, stages two changes and signs them with one passkey assertion."""

from __future__ import annotations

import os
import shutil
import sys
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

import hub_e2e_kit as base
import queue_kit
from hub_case import HubCase

OUT = Path(os.environ.get("E2E_OUT", "/tmp/hub-072-shots"))
READ = """
  const panel = () => document.querySelector("#main .queue-tab");
  const field = (key) => panel().querySelector(`[data-setting="${key}"] input`);
  const table = (label) => panel().querySelector(`table[aria-label="${label}"]`);
  const rows = (label) => all("tbody tr", table(label)).map((row) => all("th, td", row).map((cell) => text(cell)));
  const wide = () => document.documentElement.scrollWidth > innerWidth + 1;
  const open = async () => {
    await screenShown(8000);
    (await until(() => document.getElementById("controls-tab-queue"), 8000)).click();
    return until(() => panel() && table("Kinds") && field("budget_percent.cpu"), 8000);
  };
"""
SHOW = """(async () => {@HELPERS@@READ@
  if (!(await open())) {
    return {error: text(document.getElementById("main"))};
  }
  return {
    kinds: rows("Kinds").map((row) => row.slice(0, 5)), signatures: rows("Signatures"), last: rows("Last runs").map((row) => row.slice(1)),
    settings: ["budget_percent.ram", "budget_percent.cpu", "load_limits.cpu_percent", "load_limits.mem_percent", "load_limits.sample_seconds", "slot_limits.test", "ram_cap_percent.test"].map((key) => [key, field(key).value]),
    wide: wide(),
  };
})()"""
STAGE = """(async () => {@HELPERS@@READ@
  if (!(await open())) {
    return {error: text(document.getElementById("main"))};
  }
  const signs = [];
  const send = window.fetch.bind(window);
  window.fetch = (path, init) => {
    if (String(path) === "/api/sign") {
      signs.push(JSON.parse(init.body).items);
    }
    return send(path, init);
  };
  const set = (key, value) => {
    field(key).value = value;
    field(key).dispatchEvent(new Event("change", {bubbles: true}));
  };
  set("budget_percent.cpu", "180");
  set("slot_limits.test", "2");
  const apply = await until(() => panel().querySelector("[data-queue-apply]"), 4000);
  const staged = all('[aria-label="Staged settings"] li', panel()).map((node) => node.dataset.staged);
  apply.click();
  await until(() => !panel().querySelector("[data-queue-apply]"), 8000);
  return {staged, signs, wide: wide()};
})()"""


def probe(source: str) -> str:
    return source.replace("@HELPERS@", base.HELPERS).replace("@READ@", READ)


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestQueueTab(HubCase):
    drive = base.OrchestratorE2ECase.drive
    authenticator = base.OrchestratorE2ECase.authenticator

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        self.script = queue_kit.install(self, time.time())
        self.page_url = f"http://localhost:{self.port}/"

    def test_the_tab_shows_the_learnings_and_the_settings_at_every_width(self):
        steps = [{"width": width, "height": height, "url": f"{self.page_url}?{width}#stream/rules", "wait": 1500, "probe": probe(SHOW), "shot": str(OUT / f"chromium-{width}-queue-tab.png")} for width, height in base.WIDTHS]
        data = self.drive(steps, None)
        for (width, _), found in zip(base.WIDTHS, data["results"], strict=True):
            with self.subTest(width=width):
                self.assertNotIn("error", found, found)
                self.assertEqual(found["kinds"], [["test", "7", "12.5", "30", "2 (learned)"]])
                self.assertEqual(found["signatures"], [["make test", "test", "7", "4", "1", "12.5", "30", "2"]])
                self.assertEqual(found["last"], [["test", "make test", "4", "0", "override"]])
                self.assertEqual(dict(found["settings"]), {"budget_percent.ram": "75", "budget_percent.cpu": "100", "load_limits.cpu_percent": "90", "load_limits.mem_percent": "85", "load_limits.sample_seconds": "5", "slot_limits.test": "", "ram_cap_percent.test": ""})
                self.assertFalse(found["wide"])

    def test_two_staged_settings_ask_one_passkey_assertion_and_queue_one_runner_job_each(self):
        steps = [{"width": 1366, "height": 768, "url": f"{self.page_url}?1366#stream/rules", "wait": 1500, "probe": probe(STAGE), "shot": str(OUT / "chromium-1366-queue-tab-applied.png")}]
        found = self.drive(steps, self.authenticator())["results"][0]
        self.assertNotIn("error", found, found)
        self.assertEqual(found["staged"], ["budget_percent.cpu", "slot_limits.test"])
        self.assertEqual(found["signs"], [[{"kind": "queue", "argv": ["config", "set", "budget_percent.cpu", "180"]}, {"kind": "queue", "argv": ["config", "set", "slot_limits.test", "2"]}]])
        jobs = queue_kit.queue_jobs(self)
        self.assertEqual(sorted(job["argv"][2:] for job in jobs), [["budget_percent.cpu", "180"], ["slot_limits.test", "2"]])
        self.assertEqual(len({str(job["proof"]) for job in jobs}), 1)
        self.assertFalse(found["wide"])


if __name__ == "__main__":
    unittest.main()
