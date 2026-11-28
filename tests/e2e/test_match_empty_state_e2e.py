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
import test_home_dashboard_e2e as dash
from hub_case import HubCase

OUT = Path(os.environ.get("E2E_OUT", "/tmp/hub-085-empty-shots"))
EMPTY = """(async () => {@HELPERS@@HOME@
  if (@WIDGET@) {
    await ViewStore.update("home.pins", () => [{kind: "panel", id: "tasks/match", w: 12, h: 8}]);
    await go("#home");
  } else {
    await screenShown(8000);
  }
  const empty = await until(() => document.querySelector("#main .match-deck > .match-empty"), 8000);
  if (!empty) {
    return {error: text(document.getElementById("main")).slice(0, 300)};
  }
  await sleep(300);
  const deck = empty.closest(".match-deck").getBoundingClientRect();
  const box = empty.getBoundingClientRect();
  const look = getComputedStyle(empty);
  return {
    headed: all("#main .box-head .match-glass, #main .home-head .match-glass").length,
    glass: Boolean(empty.querySelector("button.match-glass.large .match-glass-face")),
    words: [text(empty.querySelector("h2")), text(empty.querySelector("p"))],
    frame: [look.borderTopStyle, look.borderTopWidth, look.backgroundImage, look.backgroundColor],
    dx: box.left + box.width / 2 - (deck.left + deck.width / 2),
    dy: box.top + box.height / 2 - (deck.top + deck.height / 2),
    fits: deck.height > box.height && deck.width >= box.width,
    wide: document.documentElement.scrollWidth > innerWidth + 1,
  };
})()"""
VIEWS = (*(("page", width, height) for width, height in base.WIDTHS), ("widget", 390, 844))


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestMatchEmptyState(HubCase):
    drive = base.OrchestratorE2ECase.drive

    def steps(self) -> list[dict]:
        OUT.mkdir(parents=True, exist_ok=True)
        steps = []
        for view, width, height in VIEWS:
            route = "stream" if view == "widget" else "tasks/match"
            probe = EMPTY.replace("@HELPERS@", base.HELPERS).replace("@HOME@", dash.HOME).replace("@WIDGET@", "true" if view == "widget" else "false")
            steps.append({"width": width, "height": height, "url": f"http://localhost:{self.port}/?{view}-{width}-empty#{route}", "wait": 1500, "probe": probe, "shot": str(OUT / f"chromium-{view}-{width}-empty.png")})
        return steps

    def test_chromium_shows_no_header_hourglass_and_a_bare_empty_state_in_the_middle_of_the_deck(self):
        data = self.drive(self.steps(), None)
        (OUT / "chromium-empty.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "(style-src-elem)" not in error and "/favicon.ico" not in error], [])
        self.assertEqual(len(data["results"]), len(VIEWS), data)
        for (view, width, _), found in zip(VIEWS, data["results"], strict=True):
            with self.subTest(view=view, width=width):
                self.assertNotIn("error", found, found)
                self.assertEqual((found["headed"], found["glass"]), (0, True), found)
                self.assertEqual(found["words"], ["No card waits", "Nothing waits on the operator."], found)
                self.assertEqual(found["frame"], ["none", "0px", "none", "rgba(0, 0, 0, 0)"], found)
                self.assertLessEqual(abs(found["dx"]), 4, found)
                self.assertLessEqual(abs(found["dy"]), 4, found)
                self.assertTrue(found["fits"], found)
                self.assertFalse(found["wide"], found)


if __name__ == "__main__":
    unittest.main()
