"""Exercise night.py: drain, suspend, status per session, resume, states from before the rename, and day on a bad state."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
NIGHT = REPO_ROOT / "skills" / "kvb-org-suspend" / "scripts" / "night.py"


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

    def _state(self, state: dict) -> None:
        self.root.mkdir(exist_ok=True)
        (self.root / "night.json").write_text(json.dumps(state), encoding="utf-8")

    def test_day_by_default(self):
        self.assertEqual(self._out("status", sid="s2"), ["mode: day"])

    def test_suspend_keeps_the_caller_active_and_suspends_the_others(self):
        self.assertEqual(self._out("suspend"), ["s3\tThree", "s2\tTwo"])
        lines = self._out("status", sid="s2")
        self.assertEqual(lines[:2], ["mode: suspend", "active: One s1"])
        self.assertRegex(lines[2], r"^since: \d{4}-\d\d-\d\dT")
        self.assertEqual(lines[3], "you: suspend (kvb-agent-suspend)")
        self.assertEqual(self._out("status")[3], "you: active")
        self.assertEqual(self._out("status", "--session", "s3", sid=None)[3], "you: suspend (kvb-agent-suspend)")
        self.assertEqual(len(self._out("status", sid=None)), 3)

    def test_drain_and_resume_return_to_day(self):
        self._out("drain", sid="s2")
        self.assertEqual(json.loads((self.root / "night.json").read_text(encoding="utf-8"))["mode"], "drain")
        self.assertEqual(self._out("status")[3], "you: drain (kvb-agent-drain)")
        self.assertEqual(self._out("resume", sid="s2"), ["s1\tOne", "s3\tThree"])
        self.assertEqual(self._out("status"), ["mode: day"])

    def test_resume_alone_lifts_one_session_until_the_next_suspend(self):
        self.assertEqual(self._out("resume", "--alone", sid="s2"), ["mode: day"])
        self._out("suspend")
        self.assertEqual(self._out("resume", "--alone", sid="s2"), ["resumed: s2"])
        self._out("resume", "--alone", sid="s2")
        self.assertEqual(json.loads((self.root / "night.json").read_text(encoding="utf-8"))["resumed"], ["s2"])
        self.assertEqual(self._out("status", sid="s2")[3], "you: resumed")
        self.assertEqual(self._out("status", sid="s3")[3], "you: suspend (kvb-agent-suspend)")
        self._out("suspend")
        self.assertEqual(self._out("status", sid="s2")[3], "you: suspend (kvb-agent-suspend)")

    def test_a_state_from_before_the_rename_keeps_working(self):
        for old, new in (("evening", "drain"), ("sunset", "suspend")):
            with self.subTest(old=old):
                self._state({"mode": old, "active": "s1", "name": "One", "since": "2026-11-08T20:00:00+00:00", "awake": ["s3"]})
                self.assertEqual(self._out("status", sid="s2"), ["mode: " + new, "active: One s1", "since: 2026-11-08T20:00:00+00:00", f"you: {new} (kvb-agent-{new})"])
                self.assertEqual(self._out("status", sid="s3")[3], "you: resumed")
                self.assertEqual(self._out("resume", "--alone", sid="s2"), ["resumed: s2"])
                state = json.loads((self.root / "night.json").read_text(encoding="utf-8"))
                self.assertEqual((state["mode"], state["resumed"], "awake" in state), (new, ["s3", "s2"], False))
        self._state({"mode": "sunset", "active": "s1"})
        self.assertEqual(self._out("resume", sid="s2"), ["s1\tOne", "s3\tThree"])
        self.assertFalse((self.root / "night.json").exists())

    def test_bad_state_means_day(self):
        self.root.mkdir()
        for text in (
            "{not json",
            json.dumps({"mode": "noon", "active": "s1"}),
            json.dumps({"mode": ["suspend"], "active": "s1"}),
            json.dumps(["suspend"]),
            json.dumps({"mode": "suspend", "active": "s1", "resumed": "s2"}),
            json.dumps({"mode": "sunset", "active": "s1", "awake": "s2"}),
        ):
            with self.subTest(text=text):
                (self.root / "night.json").write_text(text, encoding="utf-8")
                result = self._run("status", sid="s2")
                self.assertEqual((result.returncode, result.stdout), (0, "mode: day\n"))
                self.assertIn("treated as day", result.stderr)

    def test_usage_errors_exit_2(self):
        self.assertEqual(self._run("suspend", sid=None).returncode, 2)
        self.assertEqual(self._run("resume", "--alone", sid=None).returncode, 2)
        for old in (("set", "sunset"), ("sunset",), ("evening",), ("clear",), ("wake",), ("noon",)):
            with self.subTest(command=old):
                self.assertEqual(self._run(*old).returncode, 2)
        self.assertFalse((self.root / "night.json").exists())


if __name__ == "__main__":
    unittest.main()
