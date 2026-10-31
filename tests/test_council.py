"""Exercise the kvb-org-organize council script: election, staleness, release, gate."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
COUNCIL = REPO_ROOT / "skills" / "kvb-org-organize" / "scripts" / "council.py"


class TestCouncil(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "home"
        self.root = Path(self.tmp.name) / "council"
        self.sessions = self.home / ".claude" / "sessions"
        self.sessions.mkdir(parents=True)
        self._live("s1", "One")
        self._live("s2", "Two")

    def _live(self, sid: str, name: str) -> None:
        (self.sessions / f"{sid}.json").write_text(
            json.dumps({"sessionId": sid, "name": name}), encoding="utf-8"
        )

    def _run(self, sid: str, *args: str, stdin: str = "") -> subprocess.CompletedProcess:
        env = {
            "PATH": "/usr/bin:/bin",
            "HOME": str(self.home),
            "AGENTS_COUNCIL_ROOT": str(self.root),
            "CLAUDE_CODE_SESSION_ID": sid,
        }
        return subprocess.run(
            [sys.executable, str(COUNCIL), *args],
            capture_output=True,
            text=True,
            env=env,
            input=stdin,
            check=False,
        )

    def test_first_claim_wins_and_second_is_refused(self):
        self.assertEqual(self._run("s1", "claim", "work/x", "--work", "w").returncode, 0)
        second = self._run("s2", "claim", "work/x", "--work", "w")
        self.assertEqual(second.returncode, 3)
        self.assertIn('"session": "s1"', second.stdout)

    def test_dead_holder_is_stale_and_can_be_taken_over(self):
        self._run("s1", "claim", "work/x", "--work", "w")
        (self.sessions / "s1.json").unlink()
        self.assertEqual(self._run("s2", "claim", "work/x", "--work", "w").returncode, 4)
        self.assertEqual(self._run("s2", "takeover", "work/x", "--work", "w").returncode, 0)
        self.assertIn('"session": "s2"', (self.root / "work/x/claim.json").read_text())

    def test_takeover_of_a_live_holder_is_refused(self):
        self._run("s1", "claim", "work/x", "--work", "w")
        self.assertEqual(self._run("s2", "takeover", "work/x", "--work", "w").returncode, 3)

    def test_only_the_holder_releases(self):
        self._run("s1", "claim", "work/x", "--work", "w")
        self.assertEqual(self._run("s2", "release", "work/x").returncode, 3)
        self.assertEqual(self._run("s1", "release", "work/x").returncode, 0)
        self.assertFalse((self.root / "work/x").exists())

    def test_gate_blocks_unclaimed_edits_in_a_git_worktree_only(self):
        repo = Path(self.tmp.name) / "repo"
        (repo / ".git").mkdir(parents=True)
        inside = json.dumps({"session_id": "s1", "tool_input": {"file_path": str(repo / "f")}})
        outside = json.dumps(
            {"session_id": "s1", "tool_input": {"file_path": str(self.home / "f")}}
        )
        self.assertEqual(self._run("s1", "gate", stdin=inside).returncode, 2)
        self.assertEqual(self._run("s1", "gate", stdin=outside).returncode, 0)
        self._run("s1", "claim", "work/x", "--work", "w")
        self.assertEqual(self._run("s1", "gate", stdin=inside).returncode, 0)

    def test_invalid_office_is_a_usage_error(self):
        self.assertEqual(self._run("s1", "claim", "../x", "--work", "w").returncode, 2)


if __name__ == "__main__":
    unittest.main()
