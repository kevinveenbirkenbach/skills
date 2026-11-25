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
from test_hub_match import git, merge_repo

OUT = Path(os.environ.get("E2E_OUT", "/tmp/match-content-shots"))
SCAN = """
  const stray = (root) => {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const found = [];
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      if (["null", "undefined"].includes(node.nodeValue.trim())) {
        found.push(node.parentElement ? node.parentElement.className || node.parentElement.tagName : "-");
      }
    }
    return found;
  };
"""
MERGE = """(async () => {@HELPERS@@CARD@@SCAN@
  await screenShown(8000);
  await until(card, 8000);
  const shown = await pick("@MERGE@");
  await sleep(400);
  const files = shown ? all(".match-file", shown).map((file) => file.dataset.path) : null;
  const added = shown ? all(".match-file tr", shown).some((row) => text(row).includes("added = 2")) : false;
  const visited = [];
  for (const tab of all("#main .match-peek")) {
    tab.click();
    await sleep(250);
    visited.push(stray(document.getElementById("main")));
  }
  return {files, added, none: text(shown && shown.querySelector(".match-body > p.muted")), stray: stray(document.getElementById("main")), visited: visited.flat(),
    reasons: all("#main .match-reason").filter((node) => ["", "-"].includes(text(node).trim())).length, wide: document.documentElement.scrollWidth > innerWidth + 1};
})()"""
SEED = """(async () => {@HELPERS@
  await ViewStore.update("home.pins", () => [{kind: "panel", id: "tasks/match", w: innerWidth > 640 ? 6 : 4, h: 6}]);
  return true;
})()"""
TILE = """(async () => {@HELPERS@@HOME@@SCAN@
  await go("home");
  const pinned = await until(() => tile("panel:tasks/match")?.querySelector(".match-card"), 8000);
  await sleep(600);
  return {found: Boolean(pinned), stray: stray(document.getElementById("main"))};
})()"""


def probe(template: str, **names: str) -> str:
    fills = {"@HELPERS@": base.HELPERS, "@HOME@": dash.HOME, "@CARD@": matched.CARD, "@SCAN@": SCAN}
    fills.update({f"@{key.upper()}@": value for key, value in names.items()})
    for key, value in fills.items():
        template = template.replace(key, value)
    return template


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestMatchContent(HubCase):
    drive = base.OrchestratorE2ECase.drive
    cards = matched.TestMatchReview.cards
    review = matched.TestMatchReview.review
    payload = matched.TestMatchReview.payload

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        self.cards()
        repo, target = merge_repo(self.work)
        git(repo, "merge", "--no-commit", "--no-ff", "-q", target)
        arguments = {**self.arguments("Merge feature into main", "", self.page("merge.html", "<!doctype html><title>m</title>")), "repo": str(repo / ".git"), "worktree": str(repo), "branch": "main", "tree": git(repo, "write-tree").strip()}
        self.merge = self.tool("review_request", arguments)["structuredContent"]["id"]
        self.run_runner(register=False)

    def steps(self, browser: str) -> list[dict]:
        steps = []
        for width, height in base.WIDTHS:
            at = {"width": width, "height": height}
            shot = OUT / f"{browser}-{width}"
            steps += [
                {**at, "url": f"{self.base}?{width}-merge#tasks/match", "wait": 1500, "probe": probe(MERGE, merge=f"review:{self.merge}"), "shot": f"{shot}-merge-diff.png"},
                {**at, "url": f"{self.base}?{width}-clear#stream", "wait": 600, "probe": bm.CLEAR, "shot": None},
                {**at, "url": f"{self.base}?{width}-seed#stream", "wait": 800, "probe": probe(SEED), "shot": None},
                {**at, "url": f"{self.base}?{width}-home#home", "wait": 1500, "probe": probe(TILE), "shot": f"{shot}-home-match.png"},
            ]
        return steps

    def check(self, data: dict, browser: str) -> None:
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        results = iter(data["results"])
        for width, _ in base.WIDTHS:
            merge, _, _, tile = (next(results) for _ in range(4))
            with self.subTest(browser=browser, width=width, step="merge"):
                self.assertEqual((merge["files"], merge["added"], merge["none"]), (["app.py"], True, None), merge)
                self.assertEqual((merge["stray"], merge["visited"], merge["reasons"], merge["wide"]), ([], [], 0, False), merge)
            with self.subTest(browser=browser, width=width, step="tile"):
                self.assertEqual((tile["found"], tile["stray"]), (True, []), tile)

    def test_chromium_shows_the_merge_diff_and_no_stray_text(self):
        data = self.drive(self.steps("chromium"), None, init=w4.GUARD)
        (OUT / "chromium-match-content.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.check(data, "chromium")

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_shows_the_merge_diff_and_no_stray_text(self):
        data = self.drive(self.steps("firefox"), None, "bidi.mjs", os.environ.get("FIREFOX", "firefox"), init=w4.GUARD)
        (OUT / "firefox-match-content.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.check(data, "firefox")


if __name__ == "__main__":
    unittest.main()
