"""Exercise night.py: set, status per session, clear, and day on a bad state."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
NIGHT = REPO_ROOT / "skills" / "kvb-org-sunset" / "scripts" / "night.py"


class TestNight(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name) / "home"
        self.root = Path(tmp.name) / "council"
        sessions = self.home / ".claude" / "sessions"
        sessions.mkdir(parents=True)
        for sid, name in (("s1", "One"), ("s2", "Two"), ("s3", "Three")):
            (sessions / f"{sid}.json").write_text(json.dumps({"sessionId": sid, "name": name}), encoding="utf-8")

    def _run(self, *args: str, sid: str | None = "s1") -> subprocess.CompletedProcess:
        env = {"PATH": "/usr/bin:/bin", "HOME": str(self.home), "AGENTS_COUNCIL_ROOT": str(self.root)}
        if sid:
            env["CLAUDE_CODE_SESSION_ID"] = sid
        return subprocess.run(
            [sys.executable, str(NIGHT), *args], capture_output=True, text=True, env=env, check=False
        )

    def _out(self, *args: str, sid: str | None = "s1") -> list[str]:
        result = self._run(*args, sid=sid)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.splitlines()

    def test_day_by_default(self):
        self.assertEqual(self._out("status", sid="s2"), ["mode: day"])

    def test_sunset_keeps_the_caller_active_and_sends_the_others_to_sleep(self):
        self.assertEqual(self._out("set", "sunset"), ["s3\tThree", "s2\tTwo"])
        lines = self._out("status", sid="s2")
        self.assertEqual(lines[:2], ["mode: sunset", "active: One s1"])
        self.assertRegex(lines[2], r"^since: \d{4}-\d\d-\d\dT")
        self.assertEqual(lines[3], "you: sleep (kvb-agent-sleep)")
        self.assertEqual(self._out("status")[3], "you: active")
        self.assertEqual(self._out("status", "--session", "s3", sid=None)[3], "you: sleep (kvb-agent-sleep)")
        self.assertEqual(len(self._out("status", sid=None)), 3)

    def test_evening_relaxes_and_clear_returns_to_day(self):
        self._out("set", "evening", sid="s2")
        self.assertEqual(self._out("status")[3], "you: relax (kvb-agent-relax)")
        self.assertEqual(self._out("clear", sid="s2"), ["s1\tOne", "s3\tThree"])
        self.assertEqual(self._out("status"), ["mode: day"])

    def test_wake_lifts_one_session_until_the_next_set(self):
        self.assertEqual(self._out("wake", sid="s2"), ["mode: day"])
        self._out("set", "sunset")
        self.assertEqual(self._out("wake", sid="s2"), ["awake: s2"])
        self._out("wake", sid="s2")
        self.assertEqual(json.loads((self.root / "night.json").read_text(encoding="utf-8"))["awake"], ["s2"])
        self.assertEqual(self._out("status", sid="s2")[3], "you: awake")
        self.assertEqual(self._out("status", sid="s3")[3], "you: sleep (kvb-agent-sleep)")
        self._out("set", "sunset")
        self.assertEqual(self._out("status", sid="s2")[3], "you: sleep (kvb-agent-sleep)")

    def test_bad_state_means_day(self):
        self.root.mkdir()
        for text in (
            "{not json",
            json.dumps({"mode": "noon", "active": "s1"}),
            json.dumps(["sunset"]),
            json.dumps({"mode": "sunset", "active": "s1", "awake": "s2"}),
        ):
            with self.subTest(text=text):
                (self.root / "night.json").write_text(text, encoding="utf-8")
                result = self._run("status", sid="s2")
                self.assertEqual((result.returncode, result.stdout), (0, "mode: day\n"))
                self.assertIn("treated as day", result.stderr)

    def test_usage_errors_exit_2(self):
        self.assertEqual(self._run("set", "sunset", sid=None).returncode, 2)
        self.assertEqual(self._run("set", "noon").returncode, 2)
        self.assertFalse((self.root / "night.json").exists())


if __name__ == "__main__":
    unittest.main()
