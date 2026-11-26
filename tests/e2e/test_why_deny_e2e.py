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
import test_line_comments_e2e as comments
from hub_support import iso

WHY = """(async () => {@HELPERS@@UNLABELLED@
  const row = () => document.querySelector('#main .inbox-list > li[data-ref="@REVIEW@"]');
  if (!(await until(row, 8000))) {
    return {error: text(document.getElementById("main"))};
  }
  const described = (button) => {
    const note = document.getElementById(button.getAttribute("aria-describedby") || "");
    return note ? note.textContent : null;
  };
  const main = all(".deny-split button", row()).find((button) => name(button) === "Deny");
  const split = {disabled: main.disabled, title: main.closest(".why-off").title, described: described(main)};
  all(".deny-split button", row()).find((button) => name(button).startsWith("Deny via")).click();
  const confirm = await until(() => all(".sheet-box .actions button").find((button) => text(button) === "Deny"), 4000);
  const call = document.querySelector('.sheet-box .deny-channels input[value="call"]');
  const look = () => ({disabled: confirm.disabled, title: confirm.closest(".why-off").title, described: described(confirm)});
  const off = {checked: call.checked, ...look()};
  const select = document.querySelector(".sheet-box .deny-recipient select");
  select.value = "Skills";
  select.dispatchEvent(new Event("change", {bubbles: true}));
  await sleep(100);
  return {split, off, on: look(), wide: document.documentElement.scrollWidth > innerWidth + 1};
})()"""


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestWhyDeny(base.OrchestratorE2ECase):
    def setUp(self):
        super().setUp()
        now = time.time()
        self.write_council({"work/s1/claim.json": {"office": "work/s1", "session": "s1", "runtime": "claude", "name": "Skills", "since": iso(now - 3600), "beat": now, "work": "hub"}})
        arguments = {**self.arguments(comments.TITLE, "", self.page("why.html", comments.review_page())), "worktree": "/repo/.worktrees/feature/why", "branch": "feature/why"}
        result = self.tool("review_request", arguments)
        self.assertFalse(result["isError"], result)
        self.review = result["structuredContent"]["id"]

    def test_chromium_names_why_deny_is_off_on_hover_and_for_keyboard_users_until_a_recipient_is_picked(self):
        probe = WHY.replace("@HELPERS@", base.HELPERS).replace("@UNLABELLED@", base.UNLABELLED).replace("@REVIEW@", f"review:{self.review}")
        step = {"width": 1366, "height": 768, "url": f"http://localhost:{self.port}/?why#stream/inbox", "wait": 1200, "probe": probe, "shot": self.shot("1366-why-deny")}
        data = self.drive([step], None)
        Path(self.shot("1366-why-deny")).with_suffix(".json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "(style-src-elem)" not in error and "/favicon.ico" not in error], [])
        found = data["results"][0]
        self.assertNotIn("error", found, found)
        missing = "No agent to tell: the item names no recipient"
        self.assertTrue(found["split"]["disabled"], found)
        self.assertTrue(found["split"]["title"].startswith(missing) and found["split"]["described"].startswith(missing), found)
        needs = "Pick the agent to tell: a post or call needs a recipient"
        self.assertEqual(found["off"], {"checked": True, "disabled": True, "title": needs, "described": needs}, found)
        self.assertFalse(found["on"]["disabled"], found)
        self.assertNotIn("needs a recipient", found["on"]["title"], found)
        self.assertEqual(found["on"]["title"], found["on"]["described"], found)
        self.assertIn("Skills", found["on"]["title"], found)
        self.assertFalse(found["wide"], found)


if __name__ == "__main__":
    unittest.main()
