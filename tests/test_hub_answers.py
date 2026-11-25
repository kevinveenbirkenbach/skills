from __future__ import annotations

import json
import subprocess
import unittest

import hub_support
from kvb_orchestrator.jobs import UNRUNNABLE, row_blocked

MODULE = hub_support.HUB / "templates" / "answers.js"
CLASSIFY = r"""
const A = require(process.argv[1]);
const option = (label) => ({label, description: ""});
const items = {
  ask: {kind: "ask"},
  yesNo: {kind: "decision", options: [option("Yes"), option("No")], multi: false},
  row: {kind: "operator", check: "decision", options: [option(" no "), option("YES")], multi: false},
  named: {kind: "decision", options: [option("Commit B11"), option("Don't commit")], multi: false},
  multi: {kind: "decision", options: [option("Yes"), option("No")], multi: true},
  three: {kind: "decision", options: [option("Yes"), option("No"), option("Later")], multi: false},
  command: {kind: "operator", check: "done", options: []},
};
console.log(JSON.stringify({
  boolean: Object.fromEntries(Object.entries(items).map(([name, item]) => [name, A.boolean(item)])),
  pair: A.pair(items.yesNo),
  declined: [A.declined("No", "", 1000), A.declined("No", "  rebase first,\n then merge  ", 1000), A.declined("No", "x".repeat(20), 10), A.declined("No", "Yes", 1000)],
}));
"""


class TestAnswers(unittest.TestCase):
    def test_asks_and_yes_no_choices_are_boolean_while_named_multi_and_longer_choices_keep_their_form(self):
        done = subprocess.run(["node", "-e", CLASSIFY, str(MODULE)], capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        found = json.loads(done.stdout)
        self.assertEqual(found["boolean"], {"ask": True, "yesNo": True, "row": True, "named": False, "multi": False, "three": False, "command": False})
        self.assertEqual(found["pair"], {"yes": "Yes", "no": "No"})
        self.assertEqual(found["declined"], ["No", "No: rebase first, then merge", "No: xxxxxx", "No: Yes"])


class TestRowBlocked(unittest.TestCase):
    def test_a_queued_or_running_job_names_its_reason_a_free_row_none_and_a_decision_row_is_never_unrunnable(self):
        row = {"task": "operator/x", "command": "true", "directory": "/repo", "check": "done"}
        reasons = {"operator/q": "Queued in the hub runner for 3 min", "operator/r": "The hub runner runs it for 9 min"}
        self.assertEqual(row_blocked(row, reasons), "")
        self.assertEqual(row_blocked({**row, "task": "operator/q"}, reasons), reasons["operator/q"])
        self.assertEqual(row_blocked({**row, "task": "operator/r", "directory": "relative"}, reasons), reasons["operator/r"])
        self.assertEqual(row_blocked({**row, "directory": "relative"}, reasons), UNRUNNABLE)
        self.assertEqual(row_blocked({**row, "command": "-"}, reasons), UNRUNNABLE)
        self.assertEqual(row_blocked({**row, "check": "decision", "directory": "-"}, reasons), "")


if __name__ == "__main__":
    unittest.main()
