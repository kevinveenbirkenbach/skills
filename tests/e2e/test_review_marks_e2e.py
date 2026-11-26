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
import test_line_comments_e2e as comments

MARKS = """(async () => {@HELPERS@@UNLABELLED@
  const row = () => document.querySelector('#main .inbox-list > li[data-ref="@REVIEW@"]');
  if (!(await until(row, 8000))) {
    return {error: text(document.getElementById("main"))};
  }
  const to = row().dataset.to || null;
  const lines = () => all("#sheet .review-file[data-path='src/app.py'] tr[data-line]");
  const open = async () => {
    row().querySelector(".headline").click();
    return until(() => lines().length, 8000);
  };
  if (!(await open())) {
    return {error: text(document.getElementById("sheet")), to};
  }
  const cell = lines()[2].querySelector("td.code");
  const box = cell.getBoundingClientRect();
  cell.dispatchEvent(new MouseEvent("contextmenu", {bubbles: true, cancelable: true, clientX: box.left + 4, clientY: box.top + 4}));
  const field = await until(() => document.querySelector("#sheet tr.match-comment textarea"), 4000);
  if (!field) {
    return {error: "no inline comment field", to, menu: Boolean(document.querySelector(".ctx-menu:not([hidden])"))};
  }
  field.value = "c";
  all("#sheet tr.match-comment button").find((button) => name(button) === "Save comment").click();
  await until(() => document.querySelector("#sheet tr.match-mark"), 4000);
  const shown = all("#sheet tr.match-mark").map(text);
  document.body.dispatchEvent(new KeyboardEvent("keydown", {key: "Escape", bubbles: true}));
  await until(() => document.getElementById("sheet").hidden, 4000);
  await open();
  const kept = all("#sheet tr.match-mark").map(text);
  const via = all("#sheet .deny-split button").find((button) => name(button).startsWith("Deny via"));
  if (via) {
    via.click();
  }
  const reason = await until(() => document.querySelector(".sheet-box .deny-reason textarea"), 4000);
  return {to, shown, kept, via: Boolean(via), reason: reason ? reason.value : null, wide: document.documentElement.scrollWidth > innerWidth + 1};
})()"""


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestReviewMarks(base.OrchestratorE2ECase):
    def setUp(self):
        super().setUp()
        arguments = {**self.arguments(comments.TITLE, "", self.page("marks.html", comments.review_page())), "worktree": "/repo/.worktrees/feature/marks", "branch": "feature/marks"}
        result = self.tool("review_request", arguments)
        self.assertFalse(result["isError"], result)
        self.review = result["structuredContent"]["id"]

    def test_chromium_marks_a_line_in_the_review_modal_of_a_card_without_requester_and_keeps_it_for_the_deny_reason(self):
        probe = MARKS.replace("@HELPERS@", base.HELPERS).replace("@UNLABELLED@", base.UNLABELLED).replace("@REVIEW@", f"review:{self.review}")
        step = {"width": 1366, "height": 768, "url": f"http://localhost:{self.port}/?marks#stream/inbox", "wait": 1200, "probe": probe, "shot": self.shot("1366-review-marks")}
        data = self.drive([step], None)
        (Path(self.shot("1366-review-marks")).with_suffix(".json")).write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "(style-src-elem)" not in error and "/favicon.ico" not in error], [])
        found = data["results"][0]
        self.assertNotIn("error", found, found)
        self.assertIsNone(found["to"], found)
        self.assertEqual((found["shown"], found["kept"], found["via"], found["wide"]), (["c"], ["c"], True, False), found)
        self.assertIn("src/app.py:3: c", found["reason"] or "", found)


if __name__ == "__main__":
    unittest.main()
