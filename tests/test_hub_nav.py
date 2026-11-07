from __future__ import annotations

import json
import subprocess
import unittest

from hub_support import NAV

NAV_PROBE = """
const N = require(process.argv[1]);
const hashes = ["", "#stream", "#stream/inbox", "#stream/rules", "#stream/nope", "#agents/chord", "#agents/3d", "#agents", "#agents/nope",
  "#artifacts/tree", "#artifacts/orbit", "#graph", "#graph/swimlane", "#graph/orbit", "#tree", "#bogus", "#agents%2Fswimlane",
  "#agents/hierarchy", "#artifacts/hierarchy", "#graph/hierarchy", "#tree/hierarchy", "#stream/radio", "#radio",
  "#tasks", "#tasks/board", "#tasks/rasci", "#tasks/orbit", "#agents/board", "#tasks/hierarchy"];
console.log(JSON.stringify({
  tabs: N.TABS.map(([id, label]) => [id, label, (N.SUBS[id] || []).map(([sub, name]) => [sub, name])]),
  views: N.VIEWS.map(([id, label]) => [id, label]),
  taskViews: N.TASK_VIEWS.map(([id, label]) => [id, label]),
  agents: N.viewsOf("agents").map(([id, label]) => [id, label]),
  artifacts: N.viewsOf("artifacts").map(([id, label]) => [id, label]),
  tasks: N.viewsOf("tasks").map(([id, label]) => [id, label]),
  icon: N.ICONS.hierarchy,
  routes: hashes.map((hash) => N.route(hash)),
  hashes: [["stream", null], ["inbox", null], ["rules", null], ["radio", null], ["agents", "chord"], ["artifacts", "3d"], ["tasks", "board"]].map(([screen, view]) => N.hashOf(screen, view)),
  tabOf: ["stream", "inbox", "rules", "radio", "agents", "artifacts", "tasks"].map((screen) => N.tabOf(screen)),
}));
"""


class TestNavModule(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        done = subprocess.run(["node", "-e", NAV_PROBE, str(NAV)], capture_output=True, text=True, timeout=60, check=True)
        cls.data = json.loads(done.stdout)

    def test_the_navigation_has_four_entries_and_stream_has_inbox_rules_and_radio(self):
        stream = ["stream", "Stream", [["inbox", "Inbox"], ["rules", "Regeln"], ["radio", "Radio"]]]
        self.assertEqual(self.data["tabs"], [stream, ["agents", "Agents", []], ["artifacts", "Artifacts", []], ["tasks", "Tasks", []]])

    def test_agents_and_artifacts_offer_five_views_in_order_and_tasks_three(self):
        shared = [["orbit", "Orbit"], ["chord", "Chord"], ["swimlane", "Swimlane"], ["tree", "Tree"], ["3d", "3D"]]
        self.assertEqual((self.data["views"], self.data["artifacts"]), (shared, shared))
        self.assertEqual((self.data["taskViews"], self.data["tasks"]), ([["list", "Liste"], ["board", "Board"], ["rasci", "RASCI"]],) * 2)

    def test_only_agents_add_the_hierarchy_after_3d(self):
        self.assertEqual(self.data["agents"][-2:], [["3d", "3D"], ["hierarchy", "Hierarchie"]])
        self.assertEqual(self.data["icon"], "bi-diagram-2")

    def test_hashes_route_and_the_old_ones_redirect(self):
        stream = {"screen": "stream", "view": None, "redirect": None}
        self.assertEqual(self.data["routes"], [
            stream,
            stream,
            {"screen": "inbox", "view": None, "redirect": None},
            {"screen": "rules", "view": None, "redirect": None},
            stream,
            {"screen": "agents", "view": "chord", "redirect": None},
            {"screen": "agents", "view": "3d", "redirect": None},
            {"screen": "agents", "view": None, "redirect": None},
            {"screen": "agents", "view": None, "redirect": None},
            {"screen": "artifacts", "view": "tree", "redirect": None},
            {"screen": "artifacts", "view": "orbit", "redirect": None},
            {"screen": "agents", "view": "orbit", "redirect": "#agents/orbit"},
            {"screen": "agents", "view": "swimlane", "redirect": "#agents/swimlane"},
            {"screen": "agents", "view": "orbit", "redirect": "#agents/orbit"},
            {"screen": "artifacts", "view": "tree", "redirect": "#artifacts/tree"},
            stream,
            {"screen": "agents", "view": "swimlane", "redirect": None},
            {"screen": "agents", "view": "hierarchy", "redirect": None},
            {"screen": "artifacts", "view": None, "redirect": None},
            {"screen": "agents", "view": "hierarchy", "redirect": "#agents/hierarchy"},
            {"screen": "artifacts", "view": "tree", "redirect": "#artifacts/tree"},
            {"screen": "radio", "view": None, "redirect": None},
            stream,
            {"screen": "tasks", "view": None, "redirect": None},
            {"screen": "tasks", "view": "board", "redirect": None},
            {"screen": "tasks", "view": "rasci", "redirect": None},
            {"screen": "tasks", "view": None, "redirect": None},
            {"screen": "agents", "view": None, "redirect": None},
            {"screen": "tasks", "view": None, "redirect": None},
        ])

    def test_every_screen_has_its_own_hash_and_tab(self):
        self.assertEqual(self.data["hashes"], ["#stream", "#stream/inbox", "#stream/rules", "#stream/radio", "#agents/chord", "#artifacts/3d", "#tasks/board"])
        self.assertEqual(self.data["tabOf"], ["stream", "stream", "stream", "stream", "agents", "artifacts", "tasks"])


if __name__ == "__main__":
    unittest.main()
