import json
import subprocess
import unittest
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parents[1] / "orchestrator" / "templates"
LOAD = TEMPLATES / "page-load.js"
BOOT = TEMPLATES / "page-boot.js"
PROBE = """
const fs = require("fs");
const vm = require("vm");
const code = fs.readFileSync(process.argv[1], "utf8");
const steps = JSON.parse(process.argv[2]);
const loads = [];
const page = {now: 0, selection: ""};
const context = vm.createContext({
  ui: {busy: false, playing: false},
  document: {hidden: false},
  window: {getSelection: () => page.selection},
  Date: {now: () => page.now * 1000},
});
vm.runInContext(code, context);
context.load = () => loads.push(page.now);
for (const step of steps) {
  page.now = step.at;
  page.selection = step.selection || "";
  context.ui.busy = Boolean(step.busy);
  context.document.hidden = Boolean(step.hidden);
  vm.runInContext("refresh()", context);
}
console.log(JSON.stringify(loads));
"""


def loads(steps: list[dict]) -> list[int]:
    done = subprocess.run(["node", "-e", PROBE, str(LOAD), json.dumps(steps)], capture_output=True, text=True, timeout=60, check=True)
    return json.loads(done.stdout)


class TestHubRefresh(unittest.TestCase):
    def test_a_selection_holds_the_poll_back_for_twenty_seconds_only(self):
        steps = [
            {"at": 0},
            {"at": 10, "selection": "git push"},
            {"at": 20, "selection": "git push"},
            {"at": 30, "selection": "git push"},
            {"at": 40, "selection": "git push"},
            {"at": 50},
            {"at": 60, "selection": "other"},
            {"at": 70, "selection": "other"},
        ]
        self.assertEqual(loads(steps), [0, 30, 40, 50])

    def test_busy_and_hidden_pages_still_skip_the_poll(self):
        self.assertEqual(loads([{"at": 0, "busy": True}, {"at": 10, "hidden": True}, {"at": 20}]), [20])

    def test_returning_to_the_window_reloads_at_once(self):
        boot = BOOT.read_text(encoding="utf-8")
        self.assertIn('window.addEventListener("focus", refresh);', boot)
        self.assertIn('document.addEventListener("visibilitychange", refresh);', boot)


if __name__ == "__main__":
    unittest.main()
