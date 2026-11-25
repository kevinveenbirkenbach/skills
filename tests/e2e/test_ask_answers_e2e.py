from __future__ import annotations

import json
import os
import shutil
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

import hub_e2e_kit as base
from hub_e2e_kit import OUT
from hub_support import ASK
from kvb_orchestrator import batches, skill_scripts

TYPED = "run make test first"
ANSWER = """(async () => {@HELPERS@
  const row = await until(() => all("#main .inbox-list > li").find((li) => li.textContent.includes(@COMMAND@) && li.querySelector(".options button.option")), 10000);
  if (!row) {
    return {error: text(document.getElementById("main"))};
  }
  const shown = new Set(all("#toasts .toast"));
  if (@TYPED@) {
    row.querySelector(".option.other input").value = @TYPED@;
    row.querySelector(".option.other button[type=submit]").click();
  } else {
    all(".options button.option", row).find((option) => text(option.querySelector("strong")) === "No").click();
  }
  return {toast: await until(() => all("#toasts .toast").filter((box) => !shown.has(box)).map(text).find((entry) => entry.startsWith("Denial")), 20000)};
})()"""


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestAskAnswers(base.OrchestratorE2ECase):
    def step(self, command: str, typed: str) -> dict:
        script = ANSWER.replace("@HELPERS@", base.HELPERS).replace("@COMMAND@", json.dumps(command)).replace("@TYPED@", json.dumps(typed))
        return {"width": 1366, "height": 768, "url": f"http://localhost:{self.port}/#stream/inbox", "wait": 1200, "probe": script, "shot": self.shot(f"1366-ask-answer-{'typed' if typed else 'no'}")}

    def test_chromium_no_and_a_typed_answer_deny_the_ask_and_tell_its_requester(self):
        self.create_ask({**ASK, "command": "make clean", "timeout": 3600})
        with mock.patch.object(batches, "UNDO", 0.3):
            data = self.drive([self.step("make deploy", ""), self.step("make clean", TYPED)], self.authenticator())
            self.settle(lambda: all(ask["status"] == "denied" for ask in self.httpd.hub.asks.listed()))
        (OUT / "chromium-ask-answers.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "(style-src-elem)" not in error and "/favicon.ico" not in error], [])
        for found in data["results"]:
            self.assertNotIn("error", found, found)
            self.assertTrue(found["toast"].startswith("Denial (Post): Bash: make"), found)
        asks = {ask["command"]: (ask["status"], ask["channel"], ask["reason"]) for ask in self.httpd.hub.asks.listed()}
        self.assertEqual(asks, {"make deploy": ("denied", "post", ""), "make clean": ("denied", "post", TYPED)})
        radio = [args for script, args in self.scripts.calls if script == skill_scripts.RADIO]
        self.assertEqual([args[:4] for args in radio], [["send", "post", "--to", "Skills session"]] * 2)


if __name__ == "__main__":
    unittest.main()
