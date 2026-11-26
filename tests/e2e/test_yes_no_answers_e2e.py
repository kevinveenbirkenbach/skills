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
from kvb_orchestrator.jobs import UNRUNNABLE

OUT = Path(os.environ.get("E2E_OUT", "/tmp/hub-030-shots"))
ROWS = ["operator/free", "operator/loose", "operator/pick", "operator/runs", "operator/waits"]
READ = """
  const blockedTitles = (selector) => Object.fromEntries(all(selector).filter((node) => node.hasAttribute("data-blocked")).map((node) => [node.dataset.card || node.dataset.ref || node.dataset.operator, node.getAttribute("title") || ""]));
  const wide = () => document.documentElement.scrollWidth > innerWidth + 1;
"""
MATCH = """(async () => {@HELPERS@@READ@
  if (!(await until(() => document.querySelector("#main .match-card.front"), 15000))) {
    return {error: text(document.getElementById("main"))};
  }
  const toggle = document.querySelector("#main .match-peeks-toggle");
  if (toggle && toggle.getAttribute("aria-pressed") !== "true") {
    toggle.click();
  }
  await until(() => all("#main .match-peek").length === 4, 4000);
  const front = document.querySelector("#main .match-card.front");
  const accept = document.querySelector("#main .match-accept");
  const reject = document.querySelector("#main .match-reject");
  return {
    front: front.dataset.card, forms: all(".choice", front).length, accept: [accept.disabled, accept.getAttribute("title")], reject: [reject.disabled, reject.getAttribute("title")],
    peeks: all("#main .match-peek").map((peek) => peek.dataset.card), blocked: blockedTitles("#main .match-peek"), wide: wide(),
  };
})()"""
STREAM = """(async () => {@HELPERS@@READ@
  const rows = () => all("#main .feed > li.k-operator");
  if (!(await until(() => rows().length === 5, 15000))) {
    return {error: text(document.getElementById("main")), rows: rows().length};
  }
  const pick = rows().find((row) => row.dataset.ref === "operator:operator/pick");
  const buttons = (row) => all(":is(.line-actions, .code-foot) button", row).map((button) => [name(button), button.disabled]);
  const runs = rows().find((row) => row.dataset.ref === "operator:operator/runs");
  return {refs: rows().map((row) => row.dataset.ref).sort(), blocked: blockedTitles("#main .feed > li.k-operator"), pickForms: pick ? all(".choice", pick).length : null, pickButtons: pick ? buttons(pick) : null, runsButtons: runs ? buttons(runs) : null, wide: wide()};
})()"""
TASKS = """(async () => {@HELPERS@@READ@
  if (!(await until(() => all("#main .operator-list > li").length === 5, 15000))) {
    return {error: text(document.getElementById("main"))};
  }
  return {rows: all("#main .operator-list > li").map((row) => row.dataset.operator).sort(), blocked: Object.keys(blockedTitles("#main .operator-list > li")).length, runs: document.querySelector('#main .operator-list > li[data-operator="operator/runs"]').getAttribute("title"), wide: wide()};
})()"""


def probe(template: str) -> str:
    return template.replace("@HELPERS@", base.HELPERS).replace("@READ@", READ)


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestYesNoAnswers(HubCase):
    drive = base.OrchestratorE2ECase.drive

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        work = self.outside / "work"
        work.mkdir()
        row = {"title": "true", "workdir": str(work), "description": "ship the release notes", "check": "done", "roles": {"Skills": "A", "Operator": "R"}}
        yes_no = [{"label": "Yes", "description": "merge it"}, {"label": "No", "description": "leave it"}]
        register = {task: row for task in ("operator/free", "operator/runs", "operator/waits")}
        register |= {"operator/loose": {**row, "workdir": "relative/dir"}, "operator/pick": {**row, "title": "Merge the hub now?", "check": "decision", "options": yes_no}}
        self.write_council({"rasci.json": register})
        now = time.time()
        job = {"command": "true", "directory": str(work), "sha256": "0" * 64, "proof": None, "output": "", "finished": None, "dismissed": False, "code": None}
        self.httpd.hub.jobs.add({**job, "task": "operator/runs", "status": "running", "created_ts": now - 1800, "started": now - 1800})
        self.httpd.hub.jobs.add({**job, "task": "operator/waits", "status": "queued", "created_ts": now - 600, "started": None})
        self.page_url = f"http://localhost:{self.port}/"

    def test_chromium_shows_every_open_row_in_match_the_stream_and_tasks_greying_the_blocked_ones_at_three_widths(self):
        steps = []
        for width, height in base.WIDTHS:
            shot = OUT / f"chromium-{width}"
            steps += [
                {"width": width, "height": height, "url": f"{self.page_url}?{width}#tasks/match", "wait": 1500, "probe": probe(MATCH), "shot": f"{shot}-match.png"},
                {"width": width, "height": height, "url": f"{self.page_url}?{width}-stream#stream", "wait": 1500, "probe": probe(STREAM), "shot": f"{shot}-stream.png"},
                {"width": width, "height": height, "url": f"{self.page_url}?{width}-tasks#tasks/list", "wait": 1500, "probe": probe(TASKS), "shot": f"{shot}-tasks.png"},
            ]
        data = self.drive(steps, None)
        (OUT / "chromium-yes-no.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        results = iter(data["results"])
        blocked = {"operator/loose": UNRUNNABLE, "operator/runs": "The hub runner runs it for 30 min", "operator/waits": "Queued in the hub runner for 10 min behind operator/runs"}
        for width, _ in base.WIDTHS:
            match, stream, tasks = next(results), next(results), next(results)
            with self.subTest(width=width):
                self.assertNotIn("error", match, match)
                self.assertEqual(sorted([match["front"], *match["peeks"]]), sorted(f"operator:{task}" for task in ROWS))
                self.assertEqual(sorted(match["blocked"]), sorted(f"operator:{task}" for task in blocked))
                for task, reason in blocked.items():
                    self.assertIn(reason, match["blocked"][f"operator:{task}"])
                if match["front"] == "operator:operator/pick":
                    self.assertEqual(match["forms"], 0)
                    self.assertEqual(match["accept"][0], False)
                    self.assertTrue(match["accept"][1].startswith("Accept: Yes"), match["accept"])
                    self.assertTrue(match["reject"][1].startswith("Reject: No"), match["reject"])
                self.assertNotIn("error", stream, stream)
                self.assertEqual(stream["refs"], sorted(f"operator:{task}" for task in ROWS))
                self.assertEqual(sorted(stream["blocked"]), sorted(f"operator:{task}" for task in blocked))
                for task, reason in blocked.items():
                    self.assertIn(reason, stream["blocked"][f"operator:{task}"])
                self.assertEqual(stream["pickForms"], 0)
                self.assertEqual(stream["pickButtons"][:2], [["Yes", False], ["No", False]])
                self.assertIn(["Run", True], stream["runsButtons"])
                self.assertNotIn("error", tasks, tasks)
                self.assertEqual((tasks["rows"], tasks["blocked"]), (ROWS, 5))
                self.assertIn(blocked["operator/runs"], tasks["runs"])
                self.assertEqual((match["wide"], stream["wide"], tasks["wide"]), (False, False, False))


if __name__ == "__main__":
    unittest.main()
