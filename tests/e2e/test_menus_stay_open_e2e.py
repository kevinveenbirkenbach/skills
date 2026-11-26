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

OUT = Path(os.environ.get("E2E_OUT", "/tmp/hub-050-shots"))
MENU = """(async () => {@HELPERS@
  const menu = await until(() => document.querySelector("#main .stream-head details.menu"), 8000);
  if (!menu) {
    return {error: text(document.getElementById("main")).slice(0, 300)};
  }
  const open = async () => {
    if (!menu.open) {
      menu.querySelector("summary").click();
    }
    await until(() => menu.open, 2000);
  };
  const chips = () => all('.menu-box [aria-label="Kinds"] .chip', menu);
  const states = () => chips().map((chip) => chip.getAttribute("aria-pressed"));
  const leave = () => menu.dispatchEvent(new PointerEvent("pointerleave", {pointerType: "mouse"}));
  const enter = () => menu.dispatchEvent(new PointerEvent("pointerenter", {pointerType: "mouse"}));
  await open();
  const before = states();
  for (const index of [0, 1, 2]) {
    chips()[index].click();
    await sleep(300);
  }
  const after = states();
  const kept = menu.open;
  leave();
  await sleep(2500);
  const at25 = menu.open;
  await sleep(1000);
  const at35 = menu.open;
  await open();
  leave();
  await sleep(2000);
  enter();
  await sleep(1500);
  const back = menu.open;
  document.getElementById("main").click();
  await sleep(50);
  const outside = menu.open;
  await open();
  document.body.dispatchEvent(new KeyboardEvent("keydown", {key: "Escape", bubbles: true, cancelable: true}));
  await sleep(50);
  const escaped = menu.open;
  await open();
  return {before, after, kept, at25, at35, back, outside, escaped};
})()"""


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestMenusStayOpen(base.OrchestratorE2ECase):
    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)

    def test_chromium_keeps_the_stream_filter_open_through_chip_clicks_and_closes_it_3_s_after_the_pointer_left(self):
        step = {"width": 1920, "height": 1080, "url": f"{self.base}?menu#stream", "wait": 1500, "probe": MENU.replace("@HELPERS@", base.HELPERS), "shot": str(OUT / "chromium-1920-filter-menu.png")}
        data = self.drive([step], None)
        (OUT / "chromium-menu.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        found = data["results"][0]
        self.assertNotIn("error", found, found)
        self.assertEqual(len(found["before"]), len(found["after"]), found)
        self.assertEqual([found["before"][index] != found["after"][index] for index in range(3)], [True, True, True], found)
        self.assertEqual((found["kept"], found["at25"], found["at35"], found["back"]), (True, True, False, True), found)
        self.assertEqual((found["outside"], found["escaped"]), (False, False), found)


if __name__ == "__main__":
    unittest.main()
