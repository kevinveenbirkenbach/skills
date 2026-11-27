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

OUT = Path(os.environ.get("E2E_OUT", "/tmp/hub-066-shots"))
GROWN = (1920, 390)
LABELLED = 480
GEOMETRY = """
  const px = (value) => parseFloat(value) || 0;
  const wide = () => document.documentElement.scrollWidth > innerWidth + 1;
  const footer = (form) => {
    const frame = form.querySelector(".mic-frame");
    const foot = frame.querySelector(":scope > .composer-foot");
    const cells = [foot.querySelector(":scope > button:first-child"), foot.querySelector(":scope > .mic-attach"), foot.querySelector(":scope > .mic"), foot.querySelector(".ptt"), foot.querySelector(".ptt-menu"), foot.querySelector(":scope > .mayday-toggle")];
    const boxes = cells.map((cell) => cell.getBoundingClientRect());
    const looks = cells.map((cell) => getComputedStyle(cell));
    const clickable = cells.map((cell) => getComputedStyle(cell.matches("details") ? cell.querySelector(":scope > summary") : cell));
    const frameLook = getComputedStyle(frame);
    const inner = Math.max(0, px(frameLook.borderBottomLeftRadius) - px(frameLook.borderBottomWidth));
    return {
      level: boxes.every((box) => Math.abs(box.top - boxes[0].top) <= 1 && Math.abs(box.bottom - boxes[0].bottom) <= 1),
      gaps: boxes.slice(1).map((box, index) => Math.round(Math.abs(box.left - boxes[index].right))),
      corners: [Math.abs(px(looks[0].borderBottomLeftRadius) - inner) <= 0.5, Math.abs(px(looks[looks.length - 1].borderBottomRightRadius) - inner) <= 0.5],
      dividers: looks.map((look) => look.borderLeftWidth),
      outer: looks.map((look) => [look.borderTopWidth, look.borderRightWidth, look.borderBottomWidth]).flat().filter((width) => width !== "0px"),
      moves: clickable.map((look) => look.transitionProperty.split(", ").filter((name) => /border|padding|shadow|transform|width|height/.test(name))),
      eases: clickable.every((look) => ["background-color", "color"].every((name) => look.transitionProperty.split(", ").includes(name)) && look.transitionDuration.split(", ").every((time) => time === "0.15s")),
      area: Math.round(frame.getBoundingClientRect().width),
      labels: all(".cell-label", foot).map((label) => label.getBoundingClientRect().width > 1),
      icons: all("svg.bi", foot).every((svg) => svg.getBoundingClientRect().width > 0),
      resize: getComputedStyle(frame.querySelector("textarea")).resize,
    };
  };
  const growth = async (form) => {
    const field = form.querySelector("textarea");
    const typed = async (lines) => {
      field.value = Array.from({length: lines}, (_, index) => `line ${index + 1}`).join("\\n");
      field.dispatchEvent(new Event("input", {bubbles: true}));
      await sleep(80);
      return {scrolls: field.scrollHeight > field.clientHeight + 1, height: field.getBoundingClientRect().height};
    };
    const three = await typed(3);
    const eight = await typed(8);
    const cap = px(getComputedStyle(field).maxHeight);
    field.value = "";
    field.dispatchEvent(new Event("input", {bubbles: true}));
    return {three: three.scrolls, eight: eight.scrolls, capped: Math.abs(eight.height - cap) <= 2};
  };
"""
SPOT = """(async () => {@HELPERS@@GEOMETRY@
  const form = await until(() => document.querySelector("#radio-spot .radio-speak form.composer"), 15000);
  await sleep(300);
  return {footer: footer(form), growth: @GROW@ ? await growth(form) : null, wide: wide()};
})()"""
WIDGET = """(async () => {@HELPERS@@GEOMETRY@
  await ViewStore.update("home.pins", () => [{kind: "panel", id: "radio-speak", w: 6, h: 5}]);
  const tile = await until(() => document.querySelector('#main .home-tile[data-pin="panel:radio-speak"] form.composer') && document.querySelector('#main .home-tile[data-pin="panel:radio-speak"]'), 8000);
  await sleep(300);
  const body = tile.querySelector(".home-body").getBoundingClientRect();
  const form = tile.querySelector("form.composer").getBoundingClientRect();
  return {footer: footer(tile.querySelector("form.composer")), width: Math.round(Math.abs(form.width - body.width)), wide: wide()};
})()"""


def probe(template: str, grow: bool) -> str:
    return template.replace("@HELPERS@", base.HELPERS).replace("@GEOMETRY@", GEOMETRY).replace("@GROW@", "true" if grow else "false")


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestRadioComposer(HubCase):
    drive = base.OrchestratorE2ECase.drive

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        self.claim("s1", "Skills")
        self.snapshot()
        self.page_url = f"http://localhost:{self.port}/"

    def steps(self, browser: str) -> list[dict]:
        steps = []
        for width, height in base.WIDTHS:
            shot = OUT / f"{browser}-{width}"
            steps += [
                {"width": width, "height": height, "url": f"{self.page_url}?{width}-spot#stream/radio", "wait": 1200, "probe": probe(SPOT, width in GROWN), "shot": f"{shot}-composer-spot.png"},
                {"width": width, "height": height, "url": f"{self.page_url}?{width}-home#home", "wait": 1200, "probe": probe(WIDGET, False), "shot": f"{shot}-composer-widget.png"},
            ]
        return steps

    def check_footer(self, footer: dict) -> None:
        self.assertTrue(footer["level"], footer)
        self.assertEqual(footer["gaps"], [0, 0, 0, 0, 0], footer)
        self.assertEqual(footer["corners"], [True, True], footer)
        self.assertEqual(footer["dividers"], ["0px", "1px", "1px", "1px", "1px", "1px"], footer)
        self.assertEqual(footer["outer"], [], footer)
        self.assertEqual(footer["moves"], [[], [], [], [], [], []], footer)
        self.assertTrue(footer["eases"], footer)
        self.assertTrue(footer["icons"], footer)
        self.assertEqual(footer["resize"], "none", footer)
        self.assertEqual(set(footer["labels"]), {footer["area"] > LABELLED}, footer)

    def check(self, data: dict) -> None:
        results = iter(data["results"])
        for width, _ in base.WIDTHS:
            spot, widget = next(results), next(results)
            with self.subTest(width=width, view="spot"):
                self.assertNotIn("error", spot, spot)
                self.check_footer(spot["footer"])
                self.assertFalse(spot["wide"])
                if width in GROWN:
                    self.assertEqual(spot["growth"], {"three": False, "eight": True, "capped": True}, spot)
            with self.subTest(width=width, view="widget"):
                self.assertNotIn("error", widget, widget)
                self.check_footer(widget["footer"])
                self.assertLessEqual(widget["width"], 1, widget)
                self.assertFalse(widget["wide"])

    def test_chromium_draws_one_flush_footer_strip_in_the_spot_and_the_full_width_widget(self):
        data = self.drive(self.steps("chromium"), None)
        (OUT / "chromium-composer.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        self.check(data)

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_draws_one_flush_footer_strip_in_the_spot_and_the_full_width_widget(self):
        data = self.drive(self.steps("firefox"), None, "bidi.mjs", os.environ.get("FIREFOX", "firefox"))
        (OUT / "firefox-composer.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        self.check(data)


if __name__ == "__main__":
    unittest.main()
