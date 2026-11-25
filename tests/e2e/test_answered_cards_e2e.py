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
from hub_e2e_kit import OUT
from hub_support import OPTIONS
from kvb_orchestrator.records import digest

ROW = {"workdir": "/repo", "description": "the gate is green", "check": "decision", "options": OPTIONS, "recommended": "Merge now", "status": "queued", "roles": {"Operator": "R", "Skills session": "A"}}
PICKED = "Merge the hub now?"
OPEN = "Merge the radio now?"
PROBE = """(async () => {@HELPERS@
  const rowOf = (task) => all("#main .feed > li.k-operator").find((li) => (li.dataset.item || "").endsWith(`/operator:${task}`));
  const rows = await until(() => (rowOf("operator/picked") && rowOf("operator/open") ? [rowOf("operator/picked"), rowOf("operator/open")] : null), 10000);
  if (!rows) {
    return {error: text(document.getElementById("main"))};
  }
  const seen = (li) => ({answered: li.hasAttribute("data-answered"), grey: getComputedStyle(li).filter, options: all(".options button.option", li).length, pills: all(".msg-meta .pill", li).map(text), actions: all(".line-actions button", li).length});
  return {picked: seen(rows[0]), open: seen(rows[1])};
})()"""


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestAnsweredCards(base.OrchestratorE2ECase):
    def test_chromium_greys_an_answered_decision_row_without_options_or_actions_and_keeps_an_open_one(self):
        self.write_council({"rasci.json": {"operator/picked": {**ROW, "title": PICKED}, "operator/open": {**ROW, "title": OPEN}}})
        self.httpd.hub.answers.insert("operator/picked", {"sha256": digest(PICKED), "label": "Wait", "message": "m-1"})
        step = {"width": 1366, "height": 768, "url": f"http://localhost:{self.port}/#stream", "wait": 1200, "probe": PROBE.replace("@HELPERS@", base.HELPERS), "shot": self.shot("1366-answered-cards")}
        data = self.drive([step], None)
        (OUT / "chromium-answered-cards.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "(style-src-elem)" not in error and "/favicon.ico" not in error], [])
        found = data["results"][0]
        self.assertNotIn("error", found, found)
        picked, opened = found["picked"], found["open"]
        self.assertEqual((picked["answered"], picked["options"], picked["actions"], picked["pills"][-2:]), (True, 0, 0, ["decided", "Wait"]), picked)
        self.assertIn("grayscale(1)", picked["grey"])
        self.assertEqual((opened["answered"], opened["options"], opened["grey"]), (False, 2, "none"), opened)
        self.assertGreater(opened["actions"], 0, opened)


if __name__ == "__main__":
    unittest.main()
