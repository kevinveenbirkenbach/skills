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

OUT = Path(os.environ.get("E2E_OUT", "/tmp/hub-034-shots"))
BAND = """(async () => {@HELPERS@
  if (!(await screenShown(8000))) {
    return {error: "no screen"};
  }
  const main = document.getElementById("main");
  const band = await until(() => main.querySelector(".stream-head"), 8000);
  if (!band) {
    return {error: text(main).slice(0, 300)};
  }
  await sleep(400);
  const look = getComputedStyle(band);
  const tile = document.body.appendChild(Object.assign(document.createElement("div"), {className: "home-tile"}));
  const tint = getComputedStyle(tile).backgroundColor;
  tile.remove();
  const inner = () => main.getBoundingClientRect().top + parseFloat(getComputedStyle(main).borderTopWidth);
  const before = band.getBoundingClientRect().top - inner();
  band.parentElement.append(Object.assign(document.createElement("div"), {style: "height: 3000px"}));
  main.scrollTop = 600;
  await sleep(200);
  const after = band.getBoundingClientRect().top - inner();
  return {
    first: band.parentElement.firstElementChild === band && main.firstElementChild === band.parentElement,
    line: [look.borderBottomWidth, look.borderBottomStyle], lineColor: look.borderBottomColor === getComputedStyle(main.appendChild(Object.assign(document.createElement("i"), {style: "color: var(--line)"}))).color,
    background: look.backgroundColor === tint, before: Math.round(before * 10) / 10, after: Math.round(after * 10) / 10, scrolled: main.scrollTop,
  };
})()"""


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestStreamBand(HubCase):
    drive = base.OrchestratorE2ECase.drive

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        self.claim("s1", "Skills")
        self.snapshot()
        self.page_url = f"http://localhost:{self.port}/"

    def test_chromium_keeps_the_stream_controls_in_a_flush_sticky_head_band(self):
        steps = [
            {"width": width, "height": height, "url": f"{self.page_url}?{width}#stream", "wait": 1200, "probe": BAND.replace("@HELPERS@", base.HELPERS), "shot": str(OUT / f"chromium-{width}-stream-band.png")}
            for width, height in base.WIDTHS
        ]
        data = self.drive(steps, None)
        (OUT / "chromium-stream-band.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        for result, (width, _) in zip(data["results"], base.WIDTHS, strict=True):
            with self.subTest(width=width):
                self.assertNotIn("error", result, result)
                self.assertEqual((result["first"], result["line"], result["lineColor"], result["background"]), (True, ["1px", "solid"], True, True), result)
                self.assertLessEqual(abs(result["before"]), 1, result)
                self.assertGreaterEqual(result["scrolled"], 600, result)
                self.assertLessEqual(abs(result["after"] - result["before"]), 1, result)


if __name__ == "__main__":
    unittest.main()
