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
  const row = await until(() => all("#main .inbox-list > li").find((li) => li.textContent.includes(@COMMAND@) && li.querySelector(".deny-split")), 10000);
  if (!row) {
    return {error: text(document.getElementById("main"))};
  }
  const shown = new Set(all("#toasts .toast"));
  const options = all(".options button.option", row).length;
  if (@TYPED@) {
    all(".deny-split button", row).find((button) => name(button) === "Deny via …").click();
    const reason = await until(() => document.querySelector(".sheet-box .deny-reason textarea"), 4000);
    if (!reason) {
      return {error: "no Deny via sheet"};
    }
    reason.value = @TYPED@;
    document.querySelector('.sheet-box .deny-channels input[value="post"]').click();
    all(".sheet-box .actions button").find((button) => text(button) === "Deny").click();
  } else {
    all(".deny-split button", row).find((button) => name(button) === "Deny").click();
  }
  return {options, toast: await until(() => all("#toasts .toast").filter((box) => !shown.has(box)).map(text).find((entry) => entry.startsWith("Denial")), 20000)};
})()"""


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestAskAnswers(base.OrchestratorE2ECase):
    def step(self, command: str, typed: str) -> dict:
        script = ANSWER.replace("@HELPERS@", base.HELPERS).replace("@COMMAND@", json.dumps(command)).replace("@TYPED@", json.dumps(typed))
        return {"width": 1366, "height": 768, "url": f"http://localhost:{self.port}/#stream/inbox", "wait": 1200, "probe": script, "shot": self.shot(f"1366-ask-answer-{'typed' if typed else 'no'}")}

    def test_chromium_deny_and_deny_via_with_a_reason_deny_the_boolean_ask_and_tell_its_requester(self):
        self.create_ask({**ASK, "command": "make clean", "timeout": 3600})
        with mock.patch.object(batches, "UNDO", 0.3):
            data = self.drive([self.step("make deploy", ""), self.step("make clean", TYPED)], self.authenticator())
            (OUT / "chromium-ask-answers.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
            for found in data["results"]:
                self.assertNotIn("error", found, found)
                self.assertEqual(found["options"], 0, found)
                self.assertTrue(found["toast"].startswith("Denial (Post): Bash: make"), found)
            self.settle(lambda: all(ask["status"] == "denied" for ask in self.httpd.hub.asks.listed()))
        self.assertEqual([error for error in data["errors"] if "(style-src-elem)" not in error and "/favicon.ico" not in error], [])
        asks = {ask["command"]: (ask["status"], ask["channel"], ask["reason"]) for ask in self.httpd.hub.asks.listed()}
        self.assertEqual(asks, {"make deploy": ("denied", "post", ""), "make clean": ("denied", "post", TYPED)})
        radio = [args for script, args in self.scripts.calls if script == skill_scripts.RADIO]
        self.assertEqual([args[:3] for args in radio], [["post", "--to", "Skills session"]] * 2)


if __name__ == "__main__":
    unittest.main()
