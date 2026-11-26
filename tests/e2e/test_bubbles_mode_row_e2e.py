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
from hub_support import ASK

OUT = Path(os.environ.get("E2E_OUT", "/tmp/bubbles-mode-row-shots"))
PROBE = """(async () => {@HELPERS@
  await screenShown(8000);
  location.hash = "#stream/radio";
  const toggle = await until(() => document.querySelector("#radio-spot:not([hidden]) .radio-bubbles"), 8000);
  if (!toggle) {
    return {error: "no bubbles toggle in the mode row"};
  }
  const header = document.getElementById("bubbles-toggle");
  const row = toggle.closest(".radio-mode-row");
  const modes = row.querySelector(".radio-modes");
  const stored = async () => (await (await fetch("/api/state", {cache: "no-store"})).json()).settings.bubbles;
  const mode = () => all("#radio-spot .radio-modes button[aria-pressed='true']").map((button) => button.dataset.mode);
  const look = async () => ({radio: toggle.getAttribute("aria-pressed"), header: header.getAttribute("aria-pressed"), stored: await stored(), mode: mode()});
  const flip = async (button, want) => {
    button.click();
    await until(() => toggle.getAttribute("aria-pressed") === want && header.getAttribute("aria-pressed") === want, 8000);
    const end = Date.now() + 8000;
    while (Date.now() < end && String(await stored()) !== want) {
      await sleep(200);
    }
    return look();
  };
  const divider = row.querySelector(".mode-divider");
  const [lane, bar, switcher] = [modes, divider, toggle].map((node) => node.getBoundingClientRect());
  const layout = {
    order: [...row.children].map((node) => node.className),
    divider: [Math.round(bar.width), bar.height > 0, getComputedStyle(divider).backgroundColor !== "rgba(0, 0, 0, 0)"],
    sameLine: switcher.top < lane.bottom && switcher.bottom > lane.top,
    after: bar.left >= lane.right - 1 || bar.top >= lane.bottom - 1,
    named: [toggle.getAttribute("aria-label"), Boolean(toggle.title), toggle.getAttribute("aria-controls")],
    inModes: Boolean(modes.querySelector(".radio-bubbles")),
  };
  const before = await look();
  const want = before.radio === "true" ? "false" : "true";
  const flipped = await flip(toggle, want);
  const back = await flip(header, before.radio);
  return {layout, before, flipped, back, wide: document.documentElement.scrollWidth > innerWidth + 1};
})()"""


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestBubblesModeRow(HubCase):
    drive = base.OrchestratorE2ECase.drive
    authenticator = base.OrchestratorE2ECase.authenticator

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        self.claim("s1", "Skills session")
        self.create_ask({**ASK, "timeout": 3600})

    def test_chromium_switches_bubbles_from_the_mode_row_and_the_header_toggle_follows_at_three_widths(self):
        authenticator = self.authenticator()
        for width, height in base.WIDTHS:
            with self.subTest(width=width):
                probe = PROBE.replace("@HELPERS@", base.HELPERS)
                data = self.drive([{"width": width, "height": height, "url": f"http://{self.host}/?{width}#stream", "wait": 1200, "probe": probe, "shot": str(OUT / f"chromium-{width}-bubbles-row.png")}], authenticator)
                (OUT / f"chromium-{width}-bubbles-row.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
                self.assertEqual(data["errors"], [])
                found = data["results"][0]
                self.assertNotIn("error", found, found)
                layout = found["layout"]
                self.assertEqual(layout["order"][1:], ["mode-divider", "btn small ghost icon-only radio-bubbles"])
                self.assertIn("radio-modes", layout["order"][0])
                self.assertEqual((layout["divider"], layout["after"], layout["inModes"]), ([1, True, True], True, False), layout)
                self.assertEqual(layout["named"], ["Speech bubbles", True, "bubbles"])
                if width >= 1024:
                    self.assertTrue(layout["sameLine"], layout)
                before, flipped, back = found["before"], found["flipped"], found["back"]
                self.assertEqual((before["radio"], before["stored"]), (before["header"], before["radio"] == "true"), before)
                self.assertEqual((flipped["radio"], flipped["header"], flipped["stored"]), (str(not before["stored"]).lower(), str(not before["stored"]).lower(), not before["stored"]), flipped)
                self.assertEqual((back["radio"], back["header"], back["stored"]), (before["radio"], before["radio"], before["stored"]), back)
                self.assertEqual((flipped["mode"], back["mode"]), (before["mode"], before["mode"]))
                self.assertEqual(len(before["mode"]), 1)
                self.assertFalse(found["wide"])


if __name__ == "__main__":
    unittest.main()
