from __future__ import annotations

import json
import subprocess
import unittest

from hub_support import NAV

NAV_PROBE = """
const N = require(process.argv[1]);
const hashes = ["", "#stream", "#stream/inbox", "#stream/rules", "#stream/nope", "#agents/chord", "#agents/3d", "#agents", "#agents/nope",
  "#artifacts/tree", "#artifacts/orbit", "#graph", "#graph/swimlane", "#graph/orbit", "#tree", "#bogus", "#agents%2Fswimlane"];
console.log(JSON.stringify({
  tabs: N.TABS.map(([id, label]) => [id, label, (N.SUBS[id] || []).map(([sub, name]) => [sub, name])]),
  views: N.VIEWS.map(([id, label]) => [id, label]),
  routes: hashes.map((hash) => N.route(hash)),
  hashes: [["stream", null], ["inbox", null], ["rules", null], ["agents", "chord"], ["artifacts", "3d"]].map(([screen, view]) => N.hashOf(screen, view)),
  tabOf: ["stream", "inbox", "rules", "agents", "artifacts"].map((screen) => N.tabOf(screen)),
}));
"""


class TestNavModule(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        done = subprocess.run(["node", "-e", NAV_PROBE, str(NAV)], capture_output=True, text=True, timeout=60, check=True)
        cls.data = json.loads(done.stdout)

    def test_the_navigation_has_three_entries_and_stream_has_inbox_and_rules(self):
        self.assertEqual(self.data["tabs"], [["stream", "Stream", [["inbox", "Inbox"], ["rules", "Regeln"]]], ["agents", "Agents", []], ["artifacts", "Artifacts", []]])

    def test_agents_and_artifacts_offer_five_views_in_order(self):
        self.assertEqual(self.data["views"], [["orbit", "Orbit"], ["chord", "Chord"], ["swimlane", "Swimlane"], ["tree", "Tree"], ["3d", "3D"]])

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
        ])

    def test_every_screen_has_its_own_hash_and_tab(self):
        self.assertEqual(self.data["hashes"], ["#stream", "#stream/inbox", "#stream/rules", "#agents/chord", "#artifacts/3d"])
        self.assertEqual(self.data["tabOf"], ["stream", "stream", "stream", "agents", "artifacts"])


if __name__ == "__main__":
    unittest.main()
