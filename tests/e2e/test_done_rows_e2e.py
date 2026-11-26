from __future__ import annotations

import json
import os
import shutil
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

import hub_e2e_kit as base
from hub_support import ASK
from kvb_orchestrator import batches

OUT = Path(os.environ.get("E2E_OUT", "/tmp/hub-048-shots"))
DONE = """(async () => {@HELPERS@
  const row = (ref) => document.querySelector(`#main .inbox-list > li[data-ref="${ref}"]`);
  if (!(await until(() => row("@OPEN@") && document.querySelector("#main details.inbox-done"), 8000))) {
    return {error: text(document.getElementById("main")).slice(0, 300)};
  }
  const fold = document.querySelector("#main details.inbox-done");
  const done = all(".inbox-list > li", fold).map((li) => ({ref: li.dataset.ref, done: li.hasAttribute("data-done"), pill: all(".msg-meta .pill", li).map(text).includes("done"), opacity: Number(getComputedStyle(li).opacity)}));
  const shown = {open: fold.open, summary: text(fold.querySelector("summary")), last: fold === document.querySelector("#main .inbox").lastElementChild, done,
    boxes: all('#main .inbox-list .item input[type="checkbox"]').length};
  await ViewStore.set("approval.mode", "select");
  await until(() => row("@OPEN@") && row("@OPEN@").hasAttribute("aria-selected"), 10000);
  const check = () => row("@OPEN@").querySelector("[aria-pressed]");
  const state = () => [row("@OPEN@").getAttribute("aria-selected"), check() ? check().getAttribute("aria-pressed") : null];
  const before = state();
  check().click();
  await until(() => state()[0] === "true", 3000);
  const picked = state();
  check().click();
  await until(() => state()[0] === "false", 3000);
  const cleared = state();
  await cursorTo("@OPEN@");
  await pressKey("x");
  await until(() => state()[0] === "true", 3000);
  const keyed = state();
  await pressKey("x");
  await until(() => state()[0] === "false", 3000);
  await ViewStore.set("approval.mode", "direct");
  fold.scrollIntoView({block: "center"});
  return {...shown, before, picked, cleared, keyed, wide: document.documentElement.scrollWidth > innerWidth + 1};
})()"""


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestDoneRows(base.OrchestratorE2ECase):
    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        now = time.time()
        greet = {"title": "echo greet", "workdir": str(self.outside), "description": "greets", "check": "manual", "status": "queued", "roles": {"Operator": "R", "Skills session": "A"}}
        self.write_council({"rasci.json": {"operator/greet": greet}})
        fields = {"task": "operator/greet", "command": "echo greet", "directory": str(self.outside), "sha256": "", "status": "done", "proof": None}
        self.httpd.hub.jobs.add({**fields, "code": 0, "output": "greet\n", "created_ts": now - 20, "started": now - 19, "finished": now - 10, "dismissed": False})
        self.open = f"ask:{self.create_ask({**ASK, 'command': 'make open', 'timeout': 3600})}"
        held = self.create_ask({**ASK, "command": "make held", "timeout": 3600})
        self.held = f"ask:{held}"
        entries = [self.entry("ask", held, "", "")]
        with mock.patch.object(batches, "UNDO", 120):
            self.assertEqual(self.approve(entries, self.signed(entries, self.pin()))[0], 202)
        self.base = f"http://{self.host}/"

    def test_chromium_folds_held_and_ended_rows_under_done_and_selects_by_the_green_check_without_a_checkbox_at_1920_and_390(self):
        probe = DONE.replace("@HELPERS@", base.HELPERS).replace("@OPEN@", self.open)
        steps = [{"width": width, "height": height, "url": f"{self.base}?{width}#tasks/operator", "wait": 1500, "probe": probe, "shot": str(OUT / f"chromium-{width}-done-rows.png")} for width, height in ((1920, 1080), (390, 844))]
        data = self.drive(steps, None)
        (OUT / "chromium-done-rows.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        for (width, _), found in zip(((1920, 1080), (390, 844)), data["results"], strict=True):
            with self.subTest(width=width):
                self.assertNotIn("error", found, found)
                self.assertEqual((found["open"], found["summary"], found["last"], found["boxes"], found["wide"]), (False, "Done (2)", True, 0, False), found)
                self.assertEqual(sorted(row["ref"] for row in found["done"]), sorted([self.held, "operator:operator/greet"]), found)
                for row in found["done"]:
                    self.assertTrue(row["done"] and row["pill"], row)
                    self.assertLessEqual(row["opacity"], 0.5, row)
                self.assertEqual((found["before"], found["picked"], found["cleared"], found["keyed"]), (["false", "false"], ["true", "true"], ["false", "false"], ["true", "true"]), found)


if __name__ == "__main__":
    unittest.main()
