from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hub_case import HubCase
from kvb_orchestrator import batches
from review_support import fixture, hub_home, install, review


class TestHubReviewWaiver(HubCase):
    def setUp(self):
        super().setUp()
        self.claim("s2", "Stage")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.env = hub_home(self.root, install(self.root, with_quality=False), self.port)
        self.repo = fixture(self.root)

    def review(self, *args: str) -> subprocess.CompletedProcess:
        return review(self.root, self.env, *args)

    def signed_choice(self, label: str) -> dict:
        card = json.loads(self.review("question", "--repo", str(self.repo)).stdout)
        result = self.tool("decision_request", {"question": card["question"], "options": card["options"], "agent": "Stage", "recommended": card["recommended"]})
        self.assertFalse(result["isError"], result)
        decision_id = result["structuredContent"]["id"]
        entry = self.entry("decision", decision_id, label, "")
        with mock.patch.object(batches, "UNDO", 0.05):
            self.assertEqual(self.approve([entry], self.signed([entry], self.pin()))[0], 202)
            self.settle(lambda: self.choice(decision_id) == label)
        return self.tool("decision_wait", {"id": decision_id, "timeout_seconds": 0})["structuredContent"]

    def waive(self, state: dict, agent: str) -> subprocess.CompletedProcess:
        return self.review("waive", "--repo", str(self.repo), "--message", state["message"], "--answer", state["answer"], "--agent", agent)

    def status(self) -> str:
        return self.review("status", "--repo", str(self.repo)).stdout.strip()

    def hook(self) -> subprocess.CompletedProcess:
        command = f"operator.py add skills-push --dir {self.repo} --command gipsn --reason push --check pushed:{self.repo}"
        script = self.root / "skills" / "kvb-code-review" / "scripts" / "review.py"
        event = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
        return subprocess.run(["/usr/bin/python3", "-I", str(script), "hook"], input=event, env=self.env, capture_output=True, text=True, timeout=60, check=False)

    def test_a_waiver_the_operator_signed_with_the_passkey_lets_the_push_row_through(self):
        state = self.signed_choice("Waive")
        self.assertTrue(state["answer"].endswith("): Waive"), state)
        self.assertEqual(self.waive(state, "Skills").returncode, 2)
        done = self.waive(state, "Stage")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.status(), "review: waived")
        self.assertEqual(self.hook().returncode, 0)

    def test_a_signed_keep_blocked_answer_waives_nothing_and_the_push_row_stays_refused(self):
        done = self.waive(self.signed_choice("Keep blocked"), "Stage")
        self.assertEqual(done.returncode, 2)
        self.assertIn("does not waive tree", done.stderr)
        self.assertEqual(self.status(), "review: missing")
        refused = self.hook()
        self.assertEqual(refused.returncode, 2)
        self.assertIn("no clean review for tree", refused.stderr)


if __name__ == "__main__":
    unittest.main()
