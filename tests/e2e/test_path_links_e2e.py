from __future__ import annotations

import json
import os
import shutil
import sys
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

import hub_e2e_kit as base
from hub_case import HubCase
from hub_support import iso

OUT = Path(os.environ.get("E2E_OUT", "/tmp/hub-079-shots"))
WORKTREE = "/repo/.worktrees/feature/links"
FILE = "src/my app#1.py"
ACTIONS = "click opens in VS Code, right-click copies the path"
LINKS = """(async () => {@HELPERS@
  const card = () => document.querySelector("#main .match-card.front");
  await screenShown(8000);
  await until(() => card() && card().querySelector(".match-file .diff-head"), 8000);
  await sleep(400);
  const copied = [];
  navigator.clipboard.writeText = (value) => {
    copied.push(value);
    return Promise.resolve();
  };
  const chip = (place) => card().querySelector(`.match-place .match-where[data-place="${place}"]`);
  const head = card().querySelector(".match-file .diff-head a.path-link");
  const menuShut = () => all(".ctx-menu").every((menu) => menu.hidden);
  const rightClick = (node) => {
    const box = node.getBoundingClientRect();
    return !node.dispatchEvent(new MouseEvent("contextmenu", {bubbles: true, cancelable: true, clientX: box.left + 4, clientY: box.top + 4, button: 2}));
  };
  const leftClick = (node) => {
    document.addEventListener("click", (event) => event.preventDefault(), {capture: true, once: true});
    node.click();
  };
  const facts = {
    branch: [chip("branch").tagName, chip("branch").getAttribute("href")],
    repo: [chip("repo").tagName, chip("repo").getAttribute("href"), chip("repo").title],
    worktree: [chip("worktree").tagName, chip("worktree").getAttribute("href"), chip("worktree").title],
    head: head ? [head.getAttribute("href"), text(head.querySelector("code.path")), head.title] : null,
  };
  leftClick(chip("worktree"));
  await sleep(100);
  const clickCopied = copied.length;
  const prevented = [rightClick(chip("worktree")), rightClick(head)];
  await sleep(200);
  return {...facts, clickCopied, prevented, copied, menuShut: menuShut(), wide: document.documentElement.scrollWidth > window.innerWidth + 1};
})()"""


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestPathLinks(HubCase):
    drive = base.OrchestratorE2ECase.drive

    def setUp(self):
        super().setUp()
        now = time.time()
        self.write_council({"work/s1/claim.json": {"office": "work/s1", "session": "s1", "runtime": "claude", "name": "Skills", "since": iso(now - 86400), "beat": now, "work": "links"}})
        patch = "@@ -1,2 +1,3 @@\n first\n+added\n second"
        diff = [{"path": FILE, "status": "M", "mode": "100644", "additions": 1, "deletions": 0, "patch": patch, "note": ""}]
        arguments = {**self.arguments("feat: path links", "", self.page("links.html", "<!doctype html><title>p</title>")), "worktree": WORKTREE, "branch": "feature/links", "agent": "Skills", "diff": diff}
        result = self.tool("review_request", arguments)
        self.assertFalse(result["isError"], result)
        self.base = f"http://{self.host}/"

    def steps(self, browser: str) -> list[dict]:
        OUT.mkdir(parents=True, exist_ok=True)
        probe = LINKS.replace("@HELPERS@", base.HELPERS)
        return [{"width": width, "height": height, "url": f"{self.base}?{width}#tasks/match", "wait": 1500, "probe": probe, "shot": str(OUT / f"{browser}-{width}-links.png")} for width, height in base.WIDTHS]

    def check(self, data: dict) -> None:
        for (width, _), found in zip(base.WIDTHS, data["results"], strict=True):
            with self.subTest(width=width):
                self.assertEqual(found["branch"], ["BUTTON", None], found)
                self.assertEqual(found["repo"], ["A", "vscode://file/repo", f"Repository: /repo ({ACTIONS})"], found)
                self.assertEqual(found["worktree"], ["A", f"vscode://file{WORKTREE}", f"Worktree: {WORKTREE} ({ACTIONS})"], found)
                self.assertEqual(found["head"], [f"vscode://file{WORKTREE}/src/my%20app%231.py", FILE, f"{WORKTREE}/{FILE}: {ACTIONS}"], found)
                self.assertEqual(found["clickCopied"], 0, found)
                self.assertEqual(found["prevented"], [True, True], found)
                self.assertEqual(found["copied"], [WORKTREE, f"{WORKTREE}/{FILE}"], found)
                self.assertTrue(found["menuShut"], found)
                self.assertFalse(found["wide"], found)

    def test_chromium_links_chips_and_diff_heads_and_copies_on_right_click_at_three_widths(self):
        data = self.drive(self.steps("chromium"), None)
        (OUT / "chromium-links.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        self.check(data)

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_links_chips_and_diff_heads_and_copies_on_right_click_at_three_widths(self):
        data = self.drive(self.steps("firefox"), None, "bidi.mjs", os.environ.get("FIREFOX", "firefox"))
        (OUT / "firefox-links.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        self.check(data)


if __name__ == "__main__":
    unittest.main()
