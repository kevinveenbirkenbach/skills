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
import test_match_review_e2e as matched
import test_workbench_w4_e2e as w4
from hub_case import HubCase

OUT = Path(os.environ.get("E2E_OUT", "/tmp/box-heads-shots"))
VIEWS = {
    "tasks/match": "Match",
    "tasks/list": "Tasks",
    "tasks/board": "Tasks",
    "resources": "Resources",
    "agents/orbit": "Agents",
    "artifacts/orbit": "Artifacts",
    "stream/rules": "Controls",
}
PINNED = ["tasks/match", "tasks/list", "tasks/board", "agents/orbit", "artifacts/orbit"]
PATTERNS = ["dots", "stripes", "waves", "grid", "rings"]
BUTTON = """
  const buttonHeight = (root, selector) => {
    const found = all(selector, root).find((node) => node.getClientRects().length);
    return found ? Math.round(found.getBoundingClientRect().height) : null;
  };
"""
BAND = """(async () => {@HELPERS@@BUTTON@
  if (!(await screenShown(8000))) {
    return {error: "no screen"};
  }
  const main = document.getElementById("main");
  const head = await until(() => main.querySelector(".box-head"), 8000);
  if (!head) {
    return {error: text(main).slice(0, 300)};
  }
  await sleep(400);
  let first = true;
  for (let node = head; node !== main; node = node.parentElement) {
    first = first && node.parentElement.firstElementChild === node;
  }
  const style = getComputedStyle(main);
  const outer = main.getBoundingClientRect();
  const box = head.getBoundingClientRect();
  const tops = [...head.querySelectorAll(":scope > *, :scope > .box-slot > *")].filter((node) => node.getClientRects().length).map((node) => Math.round(node.getBoundingClientRect().top));
  return {
    label: head.getAttribute("aria-label"), count: all(".box-head", main).length, cards: all(".card.controls", main).length, first,
    edges: [box.top - outer.top - parseFloat(style.borderTopWidth), box.left - outer.left - parseFloat(style.borderLeftWidth), outer.right - parseFloat(style.borderRightWidth) - box.right].map((value) => Math.round(value * 10) / 10),
    height: Math.round(box.height), rows: new Set(tops).size, button: buttonHeight(head, "button.btn.small, button.btn"),
    wide: document.documentElement.scrollWidth > innerWidth + 1, violations: window.e2eViolations || null,
  };
})()"""
SEED = """(async () => {@HELPERS@
  await ViewStore.update("home.pins", () => @PINNED@.map((id) => ({kind: "panel", id, w: innerWidth > 640 ? 6 : 4, h: 5})));
  return true;
})()"""
TILES = """(async () => {@HELPERS@@HOME@@BUTTON@
  await go("home");
  await until(() => all("#main .home-tile").length === @COUNT@, 8000);
  await sleep(1200);
  const head = document.querySelector("#main .home-tile .home-head");
  return {
    head: head ? Math.round(head.getBoundingClientRect().height) : null, button: head ? buttonHeight(head, ".home-unpin") : null,
    tiles: all("#main .home-tile").map((tile) => ({
      key: tile.dataset.pin, heads: all(".home-body .box-head", tile).length, kanban: Boolean(tile.querySelector(".home-head .kanban-bar")),
    })),
    wide: document.documentElement.scrollWidth > innerWidth + 1, violations: window.e2eViolations || null,
  };
})()"""
EDGE = """(async () => {@HELPERS@
  if (!(await screenShown(8000))) {
    return {error: "no screen"};
  }
  const card = await until(() => document.querySelector("#main .match-card.front"), 8000);
  if (!card) {
    return {error: text(document.getElementById("main")).slice(0, 300)};
  }
  const head = card.querySelector(".match-head");
  const kept = card.dataset.pattern;
  const found = {};
  for (const pattern of @PATTERNS@) {
    card.dataset.pattern = pattern;
    await sleep(60);
    const shown = getComputedStyle(card);
    const after = getComputedStyle(head, "::before");
    found[pattern] = {
      border: shown.borderTopWidth, bar: shown.backgroundImage.startsWith("linear-gradient"), size: shown.backgroundSize.split(",")[0].trim(),
      flush: Math.round(head.getBoundingClientRect().top - card.getBoundingClientRect().top), top: after.top,
      mask: (after.maskImage || after.webkitMaskImage || "").replace(/\\s+/g, " "), hatch: after.backgroundImage !== "none",
    };
  }
  card.dataset.pattern = kept;
  return {found};
})()"""


def probe(template: str, **names: str) -> str:
    fills = {"@HELPERS@": base.HELPERS, "@HOME@": dash.HOME, "@BUTTON@": BUTTON, "@PINNED@": json.dumps(PINNED), "@COUNT@": str(len(PINNED)), "@PATTERNS@": json.dumps(PATTERNS)}
    fills.update({f"@{key.upper()}@": value for key, value in names.items()})
    for key, value in fills.items():
        template = template.replace(key, value)
    return template


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestBoxHeads(HubCase):
    seed = base.OrchestratorE2ECase.seed
    subagents = base.OrchestratorE2ECase.subagents
    drive = base.OrchestratorE2ECase.drive
    cards = matched.TestMatchReview.cards
    review = matched.TestMatchReview.review
    payload = matched.TestMatchReview.payload

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        self.seed()
        self.cards()

    def steps(self, browser: str) -> list[dict]:
        steps = []
        for width, height in base.WIDTHS:
            at = {"width": width, "height": height}
            shot = OUT / f"{browser}-{width}"
            steps += [{**at, "url": f"{self.base}?{width}-{view.replace('/', '-')}#{view}", "wait": 1500, "probe": probe(BAND), "shot": f"{shot}-{view.replace('/', '-')}.png"} for view in VIEWS]
            steps += [
                {**at, "url": f"{self.base}?{width}-clear#stream", "wait": 600, "probe": bm.CLEAR, "shot": None},
                {**at, "url": f"{self.base}?{width}-seed#stream", "wait": 800, "probe": probe(SEED), "shot": None},
                {**at, "url": f"{self.base}?{width}-home#home", "wait": 1500, "probe": probe(TILES), "shot": f"{shot}-home-tiles.png"},
                {**at, "url": f"{self.base}?{width}-edge#tasks/match", "wait": 1500, "probe": probe(EDGE), "shot": f"{shot}-match-edge.png"},
            ]
        return steps

    def check_band(self, row: dict, view: str, width: int, home: dict) -> None:
        self.assertNotIn("error", row, row)
        self.assertEqual((row["label"], row["count"], row["cards"], row["first"]), (VIEWS[view], 1, 0, True), row)
        self.assertEqual(row["edges"], [0, 0, 0], row)
        self.assertEqual((row["wide"], w4.quiet(row["violations"])), (False, []), row)
        if width == 1920 and row["rows"] == 1:
            self.assertLessEqual(abs(row["height"] - home["head"]), 1, (row, home["head"]))
            self.assertLessEqual(abs(row["button"] - home["button"]), 1, (row, home["button"]))
        else:
            self.assertLessEqual(row["height"], row["rows"] * (home["head"] + 6) + 1, (row, home["head"]))

    def check(self, data: dict, browser: str) -> None:
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        results = iter(data["results"])
        for width, _ in base.WIDTHS:
            bands = {view: next(results) for view in VIEWS}
            next(results)
            next(results)
            home = next(results)
            edge = next(results)
            with self.subTest(browser=browser, width=width, step="tiles"):
                self.assertEqual(sorted(tile["key"] for tile in home["tiles"]), sorted(f"panel:{view}" for view in PINNED), home)
                self.assertEqual([tile["key"] for tile in home["tiles"] if tile["heads"]], [], home)
                self.assertEqual([tile["key"] for tile in home["tiles"] if tile["kanban"]], ["panel:tasks/board"], home)
                self.assertEqual((home["wide"], w4.quiet(home["violations"])), (False, []), home)
            for view, row in bands.items():
                with self.subTest(browser=browser, width=width, view=view):
                    self.check_band(row, view, width, home)
            with self.subTest(browser=browser, width=width, step="edge"):
                self.assertNotIn("error", edge, edge)
                for pattern, found in edge["found"].items():
                    self.assertEqual((found["border"], found["bar"], found["size"], found["flush"], found["top"], found["hatch"]), ("0px", True, "100% 6px", 0, "0px", True), (pattern, found))
                    self.assertTrue(found["mask"].startswith("linear-gradient(rgba(0, 0, 0, 0) 6px"), (pattern, found))

    def test_chromium_puts_one_flush_band_on_every_box_and_keeps_the_card_bar_on_the_edge(self):
        data = self.drive(self.steps("chromium"), None, init=w4.GUARD)
        (OUT / "chromium-box-heads.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.check(data, "chromium")

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_puts_one_flush_band_on_every_box_and_keeps_the_card_bar_on_the_edge(self):
        data = self.drive(self.steps("firefox"), None, "bidi.mjs", os.environ.get("FIREFOX", "firefox"), init=w4.GUARD)
        (OUT / "firefox-box-heads.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.check(data, "firefox")


if __name__ == "__main__":
    unittest.main()
