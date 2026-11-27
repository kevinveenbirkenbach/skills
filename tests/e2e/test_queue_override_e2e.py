"""Exercise requirement 073: Start now on a waiting queue job signs one override, and the job shows granted within one poll."""

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
import queue_kit
from hub_case import HubCase

OUT = Path(os.environ.get("E2E_OUT", "/tmp/hub-073-shots"))
PAGE = """(async () => {@HELPERS@
  await screenShown(8000);
  (await until(() => document.getElementById("controls-tab-queue"), 8000)).click();
  const start = () => document.querySelector('#main .queue-tab [data-start="@JOB@"]');
  if (!(await until(start, 8000))) {
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
  const before = {label: text(start()), disabled: start().disabled, others: all("#main .queue-tab [data-start]").map((node) => node.dataset.start)};
  start().click();
  const granted = await until(() => !start() && document.querySelector('#main .queue-tab .queue-waiting [data-job="@JOB@"]') === null, 45000);
  return {before, signs, granted: Boolean(granted), wide: document.documentElement.scrollWidth > innerWidth + 1};
})()"""


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestQueueOverride(HubCase):
    drive = base.OrchestratorE2ECase.drive
    authenticator = base.OrchestratorE2ECase.authenticator
    beside = base.OrchestratorE2ECase.beside

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        self.script = queue_kit.install(self, time.time())
        self.page_url = f"http://localhost:{self.port}/"

    def grant_once_signed(self) -> None:
        if queue_kit.queue_jobs(self):
            (self.script.parent / "rows.json").write_text(json.dumps(queue_kit.started_rows()), encoding="utf-8")

    def test_start_now_signs_one_override_and_the_job_shows_granted_within_one_poll(self):
        self.beside(self.grant_once_signed)
        width, height = base.WIDTHS[0]
        probe = PAGE.replace("@HELPERS@", base.HELPERS).replace("@JOB@", queue_kit.WAITING)
        steps = [{"width": width, "height": height, "url": f"{self.page_url}?{width}#stream/rules", "wait": 1500, "probe": probe, "shot": str(OUT / f"chromium-{width}-queue-start-now.png")}]
        data = self.drive(steps, self.authenticator())
        found = data["results"][0]
        self.assertNotIn("error", found, found)
        self.assertEqual((found["before"]["label"], found["before"]["disabled"]), ("Start now", False))
        self.assertEqual(sorted(found["before"]["others"]), ["q-2", "q-3", "q-4"])
        self.assertEqual(found["signs"], [[{"kind": "queue", "argv": ["override", queue_kit.WAITING]}]])
        self.assertTrue(found["granted"], found)
        self.assertFalse(found["wide"])
        jobs = queue_kit.queue_jobs(self)
        self.assertEqual([(job["argv"], job["status"]) for job in jobs], [(["override", queue_kit.WAITING], "queued")])

    def test_the_waiting_jobs_and_their_start_now_fit_every_width(self):
        probe = """(async () => {@HELPERS@
  await screenShown(8000);
  (await until(() => document.getElementById("controls-tab-queue"), 8000)).click();
  const buttons = await until(() => all("#main .queue-tab [data-start]").length === 3 && all("#main .queue-tab [data-start]"), 8000);
  if (!buttons) {
    return {error: text(document.getElementById("main"))};
  }
  return {shown: buttons.map((node) => node.getClientRects().length > 0), wide: document.documentElement.scrollWidth > innerWidth + 1};
})()""".replace("@HELPERS@", base.HELPERS)
        steps = [{"width": width, "height": height, "url": f"{self.page_url}?{width}#stream/rules", "wait": 1500, "probe": probe, "shot": str(OUT / f"chromium-{width}-queue-waiting.png")} for width, height in base.WIDTHS]
        data = self.drive(steps, None)
        for (width, _), found in zip(base.WIDTHS, data["results"], strict=True):
            with self.subTest(width=width):
                self.assertNotIn("error", found, found)
                self.assertEqual(found, {"shown": [True] * 3, "wide": False})


if __name__ == "__main__":
    unittest.main()
