"""Exercise requirement 068: one Schedules table of all four sources, source chips, inline edit on click and the passkey prompt for a foreign row."""

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
from kvb_orchestrator import schedules

OUT = Path(os.environ.get("E2E_OUT", "/tmp/hub-068-shots"))
ROW = {"kind": "timer", "file": "", "task": "", "next": 1_900_000_000, "last": None, "on": True, "dropin": False, "error": "", "command": ""}
SYSTEM = {**ROW, "name": "backup.timer", "source": "system", "unit": "backup.timer", "file": "/u/backup.timer", "schedule": "OnCalendar=daily", "dropin": True}
HUB_UNIT = {**ROW, "name": "kvb-orchestrator-tree.timer", "source": "hub", "unit": "kvb-orchestrator-tree.timer", "schedule": "OnCalendar=*:0/5"}
CLAUDE = {**ROW, "name": "repo f08cfd39", "source": "claude", "kind": "cron", "file": "/home/u/Repositories/github.com/me/repo/.claude/scheduled_tasks.json", "task": "f08cfd39",
          "schedule": "7 * * * *", "next": None, "last": 1_799_000_000, "command": "Triage the last two CI runs"}
PROBE = """(async () => {@HELPERS@
  const panel = () => document.querySelector('#main [data-panel="stream/schedules"]');
  const row = (key) => panel().querySelector(`tr[data-schedule="${CSS.escape(key)}"]`);
  const sources = () => all("tbody tr", panel()).map((node) => node.dataset.source);
  const stored = async () => (await (await fetch("/api/state")).json()).schedules.rows;
  const settle = async (check, ms) => {
    const end = Date.now() + ms;
    while (Date.now() < end) {
      if (await check()) {
        return true;
      }
      await sleep(200);
    }
    return false;
  };
  const edit = (key, value) => {
    row(key).querySelector("td[data-edit]").click();
    const field = row(key).querySelector("input.sched-input");
    field.value = value;
    field.dispatchEvent(new KeyboardEvent("keydown", {key: "Enter", bubbles: true}));
  };
  if (!(await until(() => panel() && row("coach") && row("backup.timer"), 8000))) {
    return {error: text(document.getElementById("main"))};
  }
  const head = all("thead th", panel()).map((cell) => text(cell));
  const all4 = [...new Set(sources())];
  panel().querySelector('[data-source-chip="system"]').click();
  const withoutSystem = [...new Set(sources())];
  panel().querySelector('[data-source-chip="system"]').click();
  const back = [...new Set(sources())];
  edit("dream-popup", "21:30, 06:00");
  const retimed = await settle(async () => JSON.stringify((await stored())["dream-popup"].at) === '["06:00","21:30"]', 8000);
  const prompts = [];
  new MutationObserver(() => {
    const prompt = document.getElementById("passkey-prompt");
    if (prompt && !prompts.length) {
      prompts.push(text(prompt));
    }
  }).observe(document.body, {childList: true, subtree: true});
  await until(() => row("backup.timer"), 4000);
  edit("backup.timer", "08:00");
  await until(() => prompts.length, 8000);
  await sleep(1500);
  return {head, all4, withoutSystem, back, retimed, prompt: prompts[0] || null, reset: Boolean(row("backup.timer").querySelector("[data-reset]")), wide: document.documentElement.scrollWidth > innerWidth + 1};
})()"""


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestSchedulesEditor(HubCase):
    drive = base.OrchestratorE2ECase.drive
    authenticator = base.OrchestratorE2ECase.authenticator

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        self.council.mkdir(parents=True, exist_ok=True)
        (self.council / schedules.SCHEDULES_VIEW).write_text(json.dumps({"at": 1_800_000_000, "rows": [SYSTEM, HUB_UNIT, CLAUDE]}), encoding="utf-8")
        self.page_url = f"http://localhost:{self.port}/"

    def test_chips_filter_a_click_edits_a_schedule_and_a_foreign_row_asks_the_passkey_at_three_widths(self):
        probe = PROBE.replace("@HELPERS@", base.HELPERS)
        steps = [{"width": width, "height": height, "url": f"{self.page_url}?{width}#stream/schedules", "wait": 1500, "probe": probe, "shot": str(OUT / f"chromium-{width}-schedules.png")} for width, height in base.WIDTHS]
        data = self.drive(steps, self.authenticator())
        (OUT / "chromium-schedules.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        for (width, _), found in zip(base.WIDTHS, data["results"], strict=True):
            with self.subTest(width=width):
                self.assertNotIn("error", found, found)
                self.assertEqual(found["head"], ["Source", "Name", "Schedule", "Next", "Last", "On"])
                self.assertEqual(found["all4"], ["skills", "hub", "claude", "system"])
                self.assertEqual(found["withoutSystem"], ["skills", "hub", "claude"])
                self.assertEqual(found["back"], found["all4"])
                self.assertTrue(found["retimed"])
                self.assertIn("Retime backup.timer", found["prompt"] or "")
                self.assertTrue(found["reset"])
                self.assertFalse(found["wide"])
        stored = json.loads((self.council / schedules.SCHEDULES).read_text(encoding="utf-8"))
        self.assertEqual(stored["dream-popup"], {"on": False, "at": ["06:00", "21:30"]})
        jobs = [job for job in self.httpd.hub.jobs.listed() if job.get("kind") == "schedule"]
        self.assertEqual({tuple(job["argv"]) for job in jobs}, {("timer", "backup.timer", "--at", "08:00")})
        self.assertEqual(len(jobs), len(base.WIDTHS))


if __name__ == "__main__":
    unittest.main()
