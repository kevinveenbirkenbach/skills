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

OUT = Path(os.environ.get("E2E_OUT", "/tmp/hub-037-shots"))
FRAME = """
  const frame = () => {
    const look = getComputedStyle(document.getElementById("main"));
    return {background: look.backgroundColor, image: look.backgroundImage, border: look.borderLeftWidth, shadow: look.boxShadow};
  };
"""
PINS = """(async () => {@HELPERS@@FRAME@
  await ViewStore.update("home.pins", () => [{kind: "panel", id: "stream", w: 6, h: 4}, {kind: "panel", id: "radio-log", w: 6, h: 4}]);
  location.hash = "home";
  await screenShown(8000);
  const tile = await until(() => document.querySelector("#main .home-tile"), 8000);
  await sleep(600);
  const nav = document.querySelector(".navbar");
  const edge = nav.getBoundingClientRect().left + parseFloat(getComputedStyle(nav).paddingLeft);
  return {frame: frame(), offset: Math.round((tile.getBoundingClientRect().left - edge) * 10) / 10, wide: document.documentElement.scrollWidth > innerWidth + 1};
})()"""
EMPTY = """(async () => {@HELPERS@@FRAME@
  await ViewStore.update("home.pins", () => []);
  location.hash = "home";
  await screenShown(8000);
  const empty = await until(() => document.querySelector("#main .home > .empty:not([hidden])"), 8000);
  await sleep(300);
  const look = empty ? getComputedStyle(empty) : null;
  return {frame: frame(), card: look ? [look.backgroundColor !== "rgba(0, 0, 0, 0)", look.borderTopStyle, text(empty.querySelector("h2"))] : null};
})()"""
STREAM = """(async () => {@HELPERS@@FRAME@
  location.hash = "stream";
  await screenShown(8000);
  await sleep(300);
  return {frame: frame()};
})()"""
CLEAR = "rgba(0, 0, 0, 0)"


def probe(template: str) -> str:
    return template.replace("@HELPERS@", base.HELPERS).replace("@FRAME@", FRAME)


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestHomeFrame(HubCase):
    drive = base.OrchestratorE2ECase.drive

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        self.claim("s1", "Skills")
        self.snapshot()
        self.page_url = f"http://localhost:{self.port}/"

    def test_chromium_draws_home_without_a_box_and_keeps_the_box_on_the_stream(self):
        steps = []
        for width, height in base.WIDTHS:
            shot = OUT / f"chromium-{width}"
            steps += [
                {"width": width, "height": height, "url": f"{self.page_url}?{width}-pins#home", "wait": 1200, "probe": probe(PINS), "shot": f"{shot}-home-pins.png"},
                {"width": width, "height": height, "url": f"{self.page_url}?{width}-empty#home", "wait": 1200, "probe": probe(EMPTY), "shot": f"{shot}-home-empty.png"},
                {"width": width, "height": height, "url": f"{self.page_url}?{width}-stream#stream", "wait": 1200, "probe": probe(STREAM), "shot": None},
            ]
        data = self.drive(steps, None)
        (OUT / "chromium-home-frame.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        results = iter(data["results"])
        for width, _ in base.WIDTHS:
            pins, empty, stream = next(results), next(results), next(results)
            with self.subTest(width=width):
                for found in (pins, empty, stream):
                    self.assertNotIn("error", found, found)
                for bare in (pins["frame"], empty["frame"]):
                    self.assertEqual(bare, {"background": CLEAR, "image": "none", "border": "0px", "shadow": "none"}, bare)
                self.assertLessEqual(abs(pins["offset"]), 2, pins)
                self.assertFalse(pins["wide"])
                self.assertEqual(empty["card"], [True, "dashed", "Nothing pinned yet"], empty)
                self.assertNotEqual(stream["frame"]["background"], CLEAR, stream)
                self.assertEqual(stream["frame"]["border"], "1px", stream)
                self.assertNotEqual(stream["frame"]["shadow"], "none", stream)


if __name__ == "__main__":
    unittest.main()
