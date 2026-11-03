"""Exercise news.py: post, the hook's once-only delivery, addressing, own posts, and a broken hook input."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
NEWS = REPO_ROOT / "skills" / "kvb-org-organize" / "scripts" / "news.py"


class TestNews(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name) / "home"
        self.root = Path(tmp.name) / "council"
        sessions = self.home / ".claude" / "sessions"
        sessions.mkdir(parents=True)
        for sid, name in (("s1", "One"), ("s2", "Two"), ("s3", "Three")):
            (sessions / f"{sid}.json").write_text(json.dumps({"sessionId": sid, "name": name}), encoding="utf-8")

    def _run(self, *args: str, sid: str | None = "s1", stdin: str = "") -> subprocess.CompletedProcess:
        env = {"PATH": "/usr/bin:/bin", "HOME": str(self.home), "AGENTS_COUNCIL_ROOT": str(self.root)}
        if sid:
            env["CLAUDE_CODE_SESSION_ID"] = sid
        return subprocess.run(
            [sys.executable, str(NEWS), *args], input=stdin, capture_output=True, text=True, env=env, check=False
        )

    def _hook(self, sid: str) -> list[str]:
        result = self._run("hook", sid=None, stdin=json.dumps({"session_id": sid, "prompt": "x"}))
        self.assertEqual(result.returncode, 0, result.stderr)
        return [line.split(" ", 2)[2] for line in result.stdout.splitlines()]

    def test_every_session_sees_a_post_once_except_its_author(self):
        self.assertEqual(self._run("post", "core #1358   merged").stdout, "posted to all\n")
        self.assertEqual(self._hook("s2"), ["One: core #1358 merged"])
        self.assertEqual(self._hook("s2"), [])
        self.assertEqual(self._hook("s3"), ["One: core #1358 merged"])
        self.assertEqual(self._hook("s1"), [])

    def test_addressed_post_reaches_only_its_target(self):
        self._run("post", "your gate is granted", "--to", "Two")
        self.assertEqual(self._hook("s3"), [])
        self.assertEqual(self._hook("s2"), ["One to Two: your gate is granted"])
        self.assertEqual(len(self._run("show", "--all").stdout.splitlines()), 1)

    def test_hook_never_fails_and_post_needs_a_session(self):
        self.assertEqual((self._run("hook", sid=None, stdin="not json").returncode), 0)
        self.assertEqual(self._run("hook", sid=None, stdin="{}").stdout, "")
        self.assertEqual(self._run("post", "x", sid=None).returncode, 2)
        self.assertEqual(self._run("post", "   ").returncode, 2)


if __name__ == "__main__":
    unittest.main()
