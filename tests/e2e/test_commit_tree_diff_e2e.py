from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

import hub_e2e_kit as base
import test_match_review_e2e as matched
from hub_case import HubCase
from hub_support import iso
from test_hub_match import git, merge_repo
from test_hub_operator_tasks import rules_dir, staged_diff

OUT = Path(os.environ.get("E2E_OUT", "/tmp/commit-tree-diff-shots"))
MISSING = "0" * 40
SHOWN = "operator:operator/commit-tree"
BROKEN = "operator:operator/commit-tree-missing"
ROW = {"description": "commit the feature tree", "check": "done", "roles": {"Skills": "A", "Operator": "R"}}
DIFF = """(async () => {@HELPERS@@CARD@
  await screenShown(8000);
  await until(card, 8000);
  const shown = await pick("@SHOWN@");
  await sleep(400);
  if (!shown) {
    return {error: text(document.getElementById("main")).slice(0, 300)};
  }
  const box = shown.querySelector(".code-box");
  const eye = box.querySelector(".code-eye");
  const state = () => ({open: box.dataset.open, expanded: eye.getAttribute("aria-expanded")});
  const first = state();
  eye.click();
  await sleep(250);
  const hidden = state();
  eye.click();
  await sleep(250);
  const line = shown.querySelector(".match-merge");
  return {
    files: all(".match-file", box).map((file) => file.dataset.path), added: all(".match-file tr", box).some((row) => text(row).includes("added = 2")),
    line: text(line), kind: line ? line.dataset.kind : null, failed: line ? line.dataset.error : null, first, hidden, again: state(),
    wide: document.documentElement.scrollWidth > innerWidth + 1,
  };
})()"""
ERROR = """(async () => {@HELPERS@@CARD@
  await screenShown(8000);
  await until(card, 8000);
  const shown = await pick("@BROKEN@");
  await sleep(400);
  if (!shown) {
    return {error: text(document.getElementById("main")).slice(0, 300)};
  }
  const line = shown.querySelector(".match-merge");
  return {line: text(line), failed: line ? line.dataset.error : null, files: all(".match-file", shown).length, none: text(shown.querySelector(".code-box p.muted")),
    wide: document.documentElement.scrollWidth > innerWidth + 1};
})()"""


def probe(template: str, **names: str) -> str:
    fills = {"@HELPERS@": base.HELPERS, "@CARD@": matched.CARD, **{f"@{key.upper()}@": value for key, value in names.items()}}
    for key, value in fills.items():
        template = template.replace(key, value)
    return template


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestCommitTreeDiff(HubCase):
    drive = base.OrchestratorE2ECase.drive

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        work = tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        repo, target = merge_repo(Path(work.name))
        tree = git(repo, "rev-parse", f"{target}^{{tree}}").strip()
        self.parent = git(repo, "rev-parse", "main").strip()
        now = time.time()
        self.write_council({
            "work/s1/claim.json": {"office": "work/s1", "session": "s1", "runtime": "claude", "name": "Skills", "since": iso(now - 86400), "beat": now, "work": "commit-tree"},
            "rasci.json": {
                "operator/commit-tree": {**ROW, "title": f"git commit-tree {tree} -p {self.parent} -m 'feat: added'", "workdir": str(repo)},
                "operator/commit-tree-missing": {**ROW, "title": f"git commit-tree {MISSING} -p {self.parent} -m 'feat: gone'", "workdir": str(repo)},
            },
        })
        home = self.outside / "medusa-home"
        rules_dir(home / staged_diff.RULES_HOME.relative_to(Path.home()) / Path(staged_diff.RULES_TAIL.replace("*", "")).parent)
        with mock.patch.dict(os.environ, {"HOME": str(home), "XDG_CACHE_HOME": str(home / ".cache")}):
            self.run_runner(register=False)
        self.base = f"http://{self.host}/"

    def steps(self, browser: str) -> list[dict]:
        steps = []
        for width, height in base.WIDTHS:
            at = {"width": width, "height": height}
            shot = OUT / f"{browser}-{width}"
            steps += [
                {**at, "url": f"{self.base}?{width}-diff#tasks/match", "wait": 1500, "probe": probe(DIFF, shown=SHOWN), "shot": f"{shot}-commit-tree-diff.png"},
                {**at, "url": f"{self.base}?{width}-error#tasks/match", "wait": 1500, "probe": probe(ERROR, broken=BROKEN), "shot": f"{shot}-commit-tree-error.png"},
            ]
        return steps

    def check(self, data: dict, browser: str) -> None:
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        results = iter(data["results"])
        for width, _ in base.WIDTHS:
            shown, broken = next(results), next(results)
            with self.subTest(browser=browser, width=width, step="diff"):
                self.assertNotIn("error", shown, shown)
                self.assertEqual((shown["files"], shown["added"], shown["kind"], shown["failed"], shown["wide"]), (["app.py"], True, "commit-tree", "false", False), shown)
                self.assertIn(f"onto parent {self.parent[:12]}", shown["line"])
                self.assertEqual((shown["first"], shown["hidden"], shown["again"]), ({"open": "true", "expanded": "true"}, {"open": "false", "expanded": "false"}, {"open": "true", "expanded": "true"}), shown)
            with self.subTest(browser=browser, width=width, step="error"):
                self.assertNotIn("error", broken, broken)
                self.assertEqual((broken["failed"], broken["files"], broken["none"], broken["wide"]), ("true", 0, "No diff to show.", False), broken)
                self.assertIn(f"No commit-tree diff: git cat-file -t {MISSING} failed: fatal: Not a valid object name {MISSING}", broken["line"])

    def test_chromium_shows_the_commit_tree_diff_its_eye_toggle_and_the_git_error_line(self):
        data = self.drive(self.steps("chromium"), None)
        (OUT / "chromium-commit-tree-diff.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.check(data, "chromium")

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_shows_the_commit_tree_diff_its_eye_toggle_and_the_git_error_line(self):
        data = self.drive(self.steps("firefox"), None, "bidi.mjs", os.environ.get("FIREFOX", "firefox"))
        (OUT / "firefox-commit-tree-diff.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.check(data, "firefox")


if __name__ == "__main__":
    unittest.main()
