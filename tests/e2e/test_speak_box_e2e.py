from __future__ import annotations

import json
import os
import re
import shutil
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

import hub_e2e_kit as base
import hub_support
from hub_case import HubCase

OUT = Path(os.environ.get("E2E_OUT", "/tmp/hub-033-shots"))
COMPOSER = (hub_support.HUB / "templates" / "page-composer.js").read_text(encoding="utf-8")
HINTS = re.findall(r'^\s+"?[\w-]+"?: "([^"]+)",$', COMPOSER.split("const MAYDAY_ASK")[0], re.MULTILINE)
SHAPE = """
  const hints = @HINTS@;
  const role = (node) => [["channel", ".composer-grid"], ["text", "textarea"], ["chips", ".mic-chips"], ["foot", ".mic-foot"], ["file", ".mic-attach-file"], ["attach", ".mic-attach"], ["mic", "button.mic"], ["ptt", ".ptt-split"], ["mayday", ".mayday-toggle"],
    ["spacer", ".spacer"], ["status", ".composer-status"], ["record", "button[aria-pressed]"]].find(([, selector]) => node.matches(selector))?.[0] || node.tagName.toLowerCase();
  const edges = (node) => ["Top", "Right", "Bottom", "Left"].map((side) => getComputedStyle(node)[`border${side}Width`]);
  const shape = (form) => {
    const frame = form.querySelector(":scope > .mic-frame");
    const foot = frame.querySelector(":scope > .mic-foot");
    return {
      frame: [...frame.children].map(role), foot: [...foot.children].map(role),
      lines: {channel: edges(frame.querySelector(".composer-grid")), text: edges(frame.querySelector("textarea")), foot: getComputedStyle(foot).borderTopWidth},
      titles: all("[title]", form).map((node) => node.title).filter((title) => hints.some((hint) => title.includes(hint))),
    };
  };
"""
RADIO = """(async () => {@HELPERS@@SHAPE@
  const form = await until(() => document.querySelector("#radio-spot .radio-speak form.composer"), 15000);
  await sleep(300);
  return {shape: shape(form), wide: document.documentElement.scrollWidth > innerWidth + 1};
})()"""
HOME = """(async () => {@HELPERS@@SHAPE@
  const misfits = [];
  let first = null;
  for (let rows = 3; rows <= 8; rows += 1) {
    for (let cols = 4; cols <= 12; cols += 1) {
      await ViewStore.update("home.pins", () => [{kind: "panel", id: "radio-speak", w: cols, h: rows}]);
      const tile = await until(() => {
        const node = document.querySelector('#main .home-tile[data-pin="panel:radio-speak"]');
        return node && node.dataset.w === String(cols) && node.dataset.h === String(rows) && node.querySelector("form.composer .mayday-toggle") ? node : null;
      }, 4000);
      if (!tile) {
        misfits.push({cols, rows, missing: true});
        continue;
      }
      await sleep(40);
      const body = tile.querySelector(".home-body").getBoundingClientRect();
      const out = [".ptt-split > :first-child", ".ptt-split .ptt-more", ".mayday-toggle"].filter((selector) => {
        const edge = tile.querySelector(selector).getBoundingClientRect();
        return !(edge.width > 0 && edge.left >= body.left - 0.5 && edge.right <= body.right + 0.5 && edge.top >= body.top - 0.5 && edge.bottom <= body.bottom + 0.5);
      });
      if (out.length) {
        misfits.push({cols, rows, out});
      }
      if (!first) {
        first = {shape: shape(tile.querySelector("form.composer")), speak: tile.querySelector(".home-body").innerText.includes("Speak")};
      }
    }
  }
  await ViewStore.update("home.pins", () => [{kind: "panel", id: "radio-speak", w: 6, h: 5}]);
  await sleep(400);
  return {misfits, first, wide: document.documentElement.scrollWidth > innerWidth + 1};
})()"""
FRAME = ["channel", "status", "text", "chips", "foot"]
FOOT = ["record", "file", "attach", "mic", "ptt", "mayday"]
LINES = {"channel": ["0px", "0px", "1px", "0px"], "text": ["0px", "0px", "0px", "0px"], "foot": "1px"}


def probe(template: str) -> str:
    return template.replace("@HELPERS@", base.HELPERS).replace("@SHAPE@", SHAPE).replace("@HINTS@", json.dumps(HINTS))


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestSpeakBox(HubCase):
    drive = base.OrchestratorE2ECase.drive

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        self.claim("s1", "Skills")
        self.snapshot()
        self.page_url = f"http://localhost:{self.port}/"

    def check_shape(self, shape: dict) -> None:
        self.assertEqual((shape["frame"], shape["foot"]), (FRAME, FOOT), shape)
        self.assertEqual((shape["lines"], shape["titles"]), (LINES, []), shape)

    def test_the_hint_list_is_read_from_the_composer(self):
        self.assertEqual(len(HINTS), 6, HINTS)

    def test_chromium_draws_one_speak_frame_in_the_radio_view_and_keeps_ptt_and_mayday_inside_every_home_widget_size(self):
        steps = []
        for width, height in base.WIDTHS:
            shot = OUT / f"chromium-{width}"
            steps += [
                {"width": width, "height": height, "url": f"{self.page_url}?{width}-radio#stream/radio", "wait": 1200, "probe": probe(RADIO), "shot": f"{shot}-radio-speak.png"},
                {"width": width, "height": height, "url": f"{self.page_url}?{width}-home#home", "wait": 1200, "probe": probe(HOME), "shot": f"{shot}-home-speak.png"},
            ]
        data = self.drive(steps, None)
        (OUT / "chromium-speak-box.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        results = iter(data["results"])
        for width, _ in base.WIDTHS:
            radio, home = next(results), next(results)
            with self.subTest(width=width, view="radio"):
                self.assertNotIn("error", radio, radio)
                self.check_shape(radio["shape"])
                self.assertFalse(radio["wide"])
            with self.subTest(width=width, view="home"):
                self.assertNotIn("error", home, home)
                self.assertEqual(home["misfits"], [], home["misfits"][:5])
                self.check_shape(home["first"]["shape"])
                self.assertFalse(home["first"]["speak"])
                self.assertFalse(home["wide"])


if __name__ == "__main__":
    unittest.main()
