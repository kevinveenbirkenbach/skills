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
from hub_support import ASK, iso

OUT = Path(os.environ.get("E2E_OUT", "/tmp/hub-stream-keep-shots"))
COMMAND = "git commit -m 'stream keeps typing'"
TYPED = "rebase onto main first"
LINES = 300
DIFF = [{"path": "long.txt", "status": "M", "mode": "100644", "additions": LINES, "deletions": 0, "patch": f"@@ -0,0 +1,{LINES} @@\n" + "\n".join(f"+line {n}" for n in range(LINES)), "note": ""}]
PROBE = """(async () => {@HELPERS@
  const rowOf = () => all("#main .feed > li.k-ask").find((li) => li.textContent.includes(@COMMAND@) && li.querySelector(".diff-scroll") && li.querySelector(".option.other input"));
  const row = await until(rowOf, 10000);
  if (!row) {
    return {error: text(document.getElementById("main"))};
  }
  row.dataset.probe = "old";
  const scroller = row.querySelector(".diff-scroll");
  const field = row.querySelector(".option.other input");
  scroller.scrollTop = 200;
  field.focus();
  field.value = @TYPED@;
  field.dispatchEvent(new Event("input", {bubbles: true}));
  field.setSelectionRange(6, 6);
  const top = scroller.scrollTop;
  const redrawn = await until(() => {
    const now = rowOf();
    return now && now.dataset.probe !== "old" ? now : null;
  }, 15000);
  if (!redrawn) {
    return {error: "the stream never redrew", top};
  }
  const again = redrawn.querySelector(".option.other input");
  return {top, after: redrawn.querySelector(".diff-scroll").scrollTop, focused: document.activeElement === again, value: again.value, caret: [again.selectionStart, again.selectionEnd]};
})()"""


class TestStreamKeepsTyping(HubCase):
    drive = base.OrchestratorE2ECase.drive

    def setUp(self):
        super().setUp()
        now = time.time()
        self.write_council({"work/s1/claim.json": {"office": "work/s1", "session": "s1", "runtime": "claude", "name": "Skills session", "since": iso(now - 86400), "beat": now, "work": "stream"}})
        status, _, body = self.post_json("/api/asks", {**ASK, "command": COMMAND, "session": "s1", "diff": DIFF}, self.local())
        self.assertEqual(status, 201, body)
        OUT.mkdir(parents=True, exist_ok=True)

    def check(self, browser: str, driver: str, binary: str) -> None:
        script = PROBE.replace("@HELPERS@", base.HELPERS).replace("@COMMAND@", json.dumps(COMMAND)).replace("@TYPED@", json.dumps(TYPED))
        steps = [{"width": 1366, "height": 768, "url": f"http://localhost:{self.port}/?1366#stream", "wait": 1500, "probe": script, "shot": str(OUT / f"{browser}-1366-stream.png")}]
        data = self.drive(steps, None, driver, binary)
        (OUT / f"{browser}-stream.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "(style-src-elem)" not in error and "/favicon.ico" not in error], [])
        found = data["results"][0]
        self.assertNotIn("error", found, found)
        self.assertGreater(found["top"], 0, found)
        self.assertEqual((found["after"], found["focused"], found["value"], found["caret"]), (found["top"], True, TYPED, [6, 6]), found)

    @unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
    def test_chromium_keeps_the_typed_answer_its_focus_and_the_diff_scroll_across_a_stream_redraw(self):
        self.check("chromium", "cdp.mjs", os.environ.get("CHROMIUM", "chromium"))

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_keeps_the_typed_answer_its_focus_and_the_diff_scroll_across_a_stream_redraw(self):
        self.check("firefox", "bidi.mjs", os.environ.get("FIREFOX", "firefox"))


if __name__ == "__main__":
    unittest.main()
