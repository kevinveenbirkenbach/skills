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
import hub_support
from hub_case import HubCase

OUT = Path(os.environ.get("E2E_OUT", "/tmp/hub-038-shots"))
WIDTHS = tuple(size for size in base.WIDTHS if size[0] in (1366, 390))
BADGE = """
  const tasks = () => document.getElementById("tab-tasks");
  const badge = () => {
    const next = tasks().nextElementSibling;
    return next && next.matches("a.badge") && !next.hidden ? next : null;
  };
"""
CLICK = """(async () => {@HELPERS@@BADGE@
  await screenShown(8000);
  const count = await until(badge, 8000);
  if (!count) {
    return {error: "no count"};
  }
  const [icon, edge, own] = [tasks().querySelector("svg").getBoundingClientRect(), count.getBoundingClientRect(), tasks().getBoundingClientRect()];
  const pad = parseFloat(getComputedStyle(tasks()).paddingLeft);
  const gap = parseFloat(getComputedStyle(tasks()).columnGap);
  const found = {
    text: text(count), label: count.getAttribute("aria-label"), nested: Boolean(tasks().querySelector(".badge")),
    icon: Math.round((icon.left - own.left - pad) * 10) / 10, count: Math.round((edge.left - icon.right - gap) * 10) / 10,
  };
  count.click();
  found.hash = await until(() => location.hash === "#tasks/match" && location.hash, 4000);
  location.hash = "stream";
  await screenShown(8000);
  tasks().click();
  await sleep(400);
  found.icon_hash = location.hash;
  return found;
})()"""
FOCUS = """(async () => {@HELPERS@@BADGE@
  await screenShown(8000);
  const count = await until(badge, 8000);
  count.focus();
  return {focused: document.activeElement === count};
})()"""
READ = """(async () => {@HELPERS@
  await sleep(400);
  return {hash: location.hash};
})()"""


def probe(template: str) -> str:
    return template.replace("@HELPERS@", base.HELPERS).replace("@BADGE@", BADGE)


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestBadgeToMatch(HubCase):
    drive = base.OrchestratorE2ECase.drive

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        self.claim("s1", "Skills")
        decided = self.tool("decision_request", {"question": "Open the Match view?", "options": hub_support.OPTIONS, "agent": "Skills", "recommended": ""})
        self.assertFalse(decided["isError"], decided)
        self.snapshot()
        self.page_url = f"http://localhost:{self.port}/"

    def test_chromium_opens_match_from_the_count_by_click_and_enter_and_tasks_from_the_icon(self):
        steps = []
        for width, height in WIDTHS:
            at = {"width": width, "height": height}
            steps += [
                {**at, "url": f"{self.page_url}?{width}-click#stream", "wait": 1200, "probe": probe(CLICK), "shot": str(OUT / f"chromium-{width}-badge-match.png")},
                {**at, "url": f"{self.page_url}?{width}-key#stream", "wait": 1200, "probe": probe(FOCUS), "shot": None},
                {**at, "url": None, "wait": 0, "keys": ["Enter"], "probe": probe(READ), "shot": None},
            ]
        data = self.drive(steps, None)
        (OUT / "chromium-badge-match.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        results = iter(data["results"])
        for width, _ in WIDTHS:
            click, focus, read = next(results), next(results), next(results)
            with self.subTest(width=width):
                self.assertNotIn("error", click, click)
                self.assertEqual((click["text"], click["label"], click["nested"]), ("1", "1 open operator task: open Match", False), click)
                self.assertLessEqual(abs(click["icon"]), 1, click)
                self.assertLessEqual(abs(click["count"]), 1, click)
                self.assertEqual(click["hash"], "#tasks/match", click)
                self.assertTrue(click["icon_hash"].startswith("#tasks") and not click["icon_hash"].startswith("#tasks/match"), click)
                self.assertEqual((focus["focused"], read["hash"]), (True, "#tasks/match"), (focus, read))


if __name__ == "__main__":
    unittest.main()
