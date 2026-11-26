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
from hub_case import HubCase
from kvb_orchestrator import schedules

OUT = Path(os.environ.get("E2E_OUT", "/tmp/hub-057-shots"))
FOREIGN = {"name": "backup.timer", "kind": "timer", "owner": "other", "unit": "backup.timer", "file": "/u/backup.timer", "schedule": "OnCalendar=daily", "next": 1_900_000_000, "last": None, "event": "", "command": "", "off": "systemctl --user disable --now backup.timer"}
HUB_UNIT = {**FOREIGN, "name": "kvb-orchestrator-tree.timer", "owner": "hub", "unit": "kvb-orchestrator-tree.timer", "off": ""}
PROBE = """(async () => {@HELPERS@@HOME@
  const row = (name) => document.querySelector(`#main [data-schedule="${name}"]`);
  const rows = async () => (await (await fetch("/api/state")).json()).schedules.rows;
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
  const owner = await until(() => document.querySelector('#main [data-panel="stream/schedules"]') && row("coach"), 8000);
  if (!owner) {
    return {error: text(document.getElementById("main"))};
  }
  const tabs = all('#main [role="tab"]').map((tab) => [tab.dataset.tab, tab.getAttribute("aria-selected")]);
  const foreign = all("#main [data-schedule-foreign]").map((node) => ({name: node.dataset.scheduleForeign, switches: node.querySelectorAll('input[role="switch"]').length, copy: Boolean(node.querySelector('button[aria-label="Copy"]')), off: text(node.querySelector(".sched-off code"))}));
  const flip = async (wanted) => {
    row("coach").querySelector('input[role="switch"]').click();
    return settle(async () => (await rows()).coach.on === wanted && row("coach") && row("coach").querySelector('input[role="switch"]').checked === wanted, 8000);
  };
  const on = await flip(true);
  const off = await flip(false);
  const times = row("dream-popup").querySelector("input.sched-times");
  times.value = "21:30, 06:00";
  times.dispatchEvent(new Event("change", {bubbles: true}));
  const retimed = await settle(async () => JSON.stringify((await rows())["dream-popup"].at) === '["06:00","21:30"]', 8000);
  const wide = document.documentElement.scrollWidth > innerWidth + 1;
  const panel = document.querySelector('#main [data-panel="stream/schedules"]');
  const spot = [...panel.children].find((node) => node.closest("[data-panel], [data-item]") === panel) || panel;
  const item = await pinItem(spot);
  const label = item ? menuLabel(item) : null;
  if (item) {
    item.click();
    await sleep(300);
  }
  await closeMenu();
  return {hash: location.hash, tabs, foreign, on, off, retimed, wide, label, pinned: stored().includes("panel:stream/schedules")};
})()"""
TILE = """(async () => {@HELPERS@@HOME@
  await go("home");
  const shown = await until(() => tile("panel:stream/schedules") && tile("panel:stream/schedules").querySelector('[data-schedule="coach"]'), 8000);
  return {tile: Boolean(shown), switches: shown ? tile("panel:stream/schedules").querySelectorAll('input[role="switch"]').length : 0};
})()"""


def probe(template: str) -> str:
    return template.replace("@HELPERS@", base.HELPERS).replace("@HOME@", dash.HOME)


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestSchedules(HubCase):
    drive = base.OrchestratorE2ECase.drive

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        self.council.mkdir(parents=True, exist_ok=True)
        (self.council / schedules.SCHEDULES_VIEW).write_text(json.dumps({"at": 1_800_000_000, "rows": [FOREIGN, HUB_UNIT]}), encoding="utf-8")
        self.page_url = f"http://localhost:{self.port}/"

    def test_chromium_opens_schedules_switches_coach_retimes_the_popup_shows_foreign_rows_read_only_and_pins_it_at_three_widths(self):
        steps = []
        for width, height in base.WIDTHS:
            at = {"width": width, "height": height}
            shot = OUT / f"chromium-{width}"
            steps += [
                {**at, "url": f"{self.page_url}?{width}-clear#stream", "wait": 600, "probe": bm.CLEAR, "shot": None},
                {**at, "url": f"{self.page_url}?{width}#stream/schedules", "wait": 1500, "probe": probe(PROBE), "shot": f"{shot}-schedules.png"},
                {**at, "url": None, "wait": 0, "probe": probe(TILE), "shot": f"{shot}-home.png"},
            ]
        data = self.drive(steps, None)
        (OUT / "chromium-schedules.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        results = iter(data["results"])
        for width, _ in base.WIDTHS:
            _, found, home = next(results), next(results), next(results)
            with self.subTest(width=width):
                self.assertNotIn("error", found, found)
                self.assertEqual(found["tabs"], [["tools", "false"], ["rules", "false"], ["groups", "false"], ["schedules", "true"]])
                self.assertEqual(found["hash"], "#stream/schedules")
                self.assertEqual((found["on"], found["off"], found["retimed"], found["wide"]), (True, True, True, False))
                self.assertEqual(found["foreign"], [
                    {"name": "backup.timer", "switches": 0, "copy": True, "off": "systemctl --user disable --now backup.timer"},
                    {"name": "kvb-orchestrator-tree.timer", "switches": 0, "copy": False, "off": None},
                ])
                self.assertEqual((found["label"], found["pinned"]), ("Pin to Home", True))
                self.assertEqual(home, {"tile": True, "switches": 5})
        stored = json.loads((self.council / schedules.SCHEDULES).read_text(encoding="utf-8"))
        self.assertEqual((stored["coach"], stored["dream-popup"]), ({"on": False, "every": 1}, {"on": False, "at": ["06:00", "21:30"]}))


if __name__ == "__main__":
    unittest.main()
