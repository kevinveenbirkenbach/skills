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
import test_box_heads_e2e as heads
import test_home_bookmarks_e2e as bm
import test_home_dashboard_e2e as dash
import test_match_review_e2e as matched
import test_workbench_w4_e2e as w4
from hub_case import HubCase

OUT = Path(os.environ.get("E2E_OUT", "/tmp/pin-by-menu-shots"))
OLD = {"kind": "panel", "id": "tasks/list", "w": 6, "h": 4}
SEED = f"""(async () => {{
  await ViewStore.update("home.pins", () => [{json.dumps(OLD)}]);
  return true;
}})()"""
VIEW = """(async () => {@HELPERS@
  await screenShown(8000);
  await sleep(600);
  return {owners: all("#main [data-panel], #main [data-item]").length, stars: all(".star, .star-row").length, slots: all("[data-star-slot]").length};
})()"""
MENU = """(async () => {@HELPERS@@HOME@
  const read = async (hash, selector) => {
    await go(hash);
    const owner = await until(() => document.querySelector(selector), 8000);
    if (!owner) {
      return {error: hash};
    }
    const spotOf = (node) => [...node.children].find((child) => child.closest("[data-panel], [data-item]") === node) || node;
    const label = async () => {
      const live = document.querySelector(selector);
      const item = live ? await pinItem(spotOf(live)) : null;
      return [item ? menuLabel(item) : null, item];
    };
    const [before, item] = await label();
    if (item) {
      item.click();
      await sleep(800);
    }
    const target = Panels.targetOf(owner);
    const added = stored().includes(`${target.kind}:${target.id}`);
    const [after] = await label();
    await closeMenu();
    return {before, added, after};
  };
  return {gantt: await read("tasks/gantt", '#main [data-panel="tasks/gantt"]'), stream: await read("stream", '#main [data-panel="stream"]')};
})()"""
TILES = """(async () => {@HELPERS@@HOME@
  await go("home");
  await until(() => tile("panel:tasks/list") && tile("panel:tasks/gantt") && tile("panel:stream"), 8000);
  await sleep(400);
  return {tiles: tiles(), stars: all(".star, .star-row").length, slots: all("[data-star-slot]").length};
})()"""


def probe(template: str) -> str:
    return template.replace("@HELPERS@", base.HELPERS).replace("@HOME@", dash.HOME)


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestPinByMenu(HubCase):
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

    def steps(self) -> list[dict]:
        steps = []
        for width, height in base.WIDTHS:
            at = {"width": width, "height": height}
            shot = OUT / f"chromium-{width}"
            steps += [
                {**at, "url": f"{self.base}?{width}-clear#stream", "wait": 600, "probe": bm.CLEAR, "shot": None},
                {**at, "url": f"{self.base}?{width}-seed#stream", "wait": 800, "probe": SEED, "shot": None},
            ]
            steps += [{**at, "url": f"{self.base}?{width}-{view.replace('/', '-')}#{view}", "wait": 1500, "probe": probe(VIEW), "shot": f"{shot}-{view.replace('/', '-')}.png"} for view in heads.VIEWS]
            steps += [
                {**at, "url": None, "wait": 0, "probe": probe(MENU), "shot": f"{shot}-menu.png"},
                {**at, "url": None, "wait": 0, "probe": probe(TILES), "shot": f"{shot}-home.png"},
            ]
        return steps

    def test_chromium_shows_no_star_and_pins_and_unpins_through_the_context_menu_keeping_an_old_pin(self):
        data = self.drive(self.steps(), None, init=w4.GUARD)
        (OUT / "chromium-pin-by-menu.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        results = iter(data["results"])
        for width, _ in base.WIDTHS:
            next(results)
            next(results)
            views = {view: next(results) for view in heads.VIEWS}
            menu = next(results)
            home = next(results)
            with self.subTest(width=width, step="views"):
                self.assertEqual({view: (row["stars"], row["slots"]) for view, row in views.items()}, dict.fromkeys(heads.VIEWS, (0, 0)), views)
                self.assertGreater(sum(row["owners"] for row in views.values()), 0, views)
            with self.subTest(width=width, step="menu"):
                pinned = {"before": "Pin to Home", "added": True, "after": "Unpin from Home"}
                self.assertEqual((menu["gantt"], menu["stream"]), (pinned, pinned), menu)
            with self.subTest(width=width, step="home"):
                self.assertEqual(home["tiles"], ["panel:tasks/list", "panel:tasks/gantt", "panel:stream"], home)
                self.assertEqual((home["stars"], home["slots"]), (0, 0), home)


if __name__ == "__main__":
    unittest.main()
