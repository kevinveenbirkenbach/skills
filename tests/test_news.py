"""Exercise the news.py shim: it forwards post, hook, mailbox and show to radio.py, and a missing radio.py never blocks a prompt."""

from __future__ import annotations

import json
import shutil
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
        self.tmp = Path(tmp.name)
        self.home = self.tmp / "home"
        self.root = self.tmp / "council"
        sessions = self.home / ".claude" / "sessions"
        sessions.mkdir(parents=True)
        for sid, name in (("s1", "One"), ("s2", "Two"), ("s3", "Three")):
            (sessions / f"{sid}.json").write_text(json.dumps({"sessionId": sid, "name": name}), encoding="utf-8")

    def _exec(self, news: Path, sid: str | None, stdin: str, args: tuple[str, ...]) -> subprocess.CompletedProcess:
        env = {
            "PATH": "/usr/bin:/bin",
            "HOME": str(self.home),
            "AGENTS_COUNCIL_ROOT": str(self.root),
            "AGENTS_COUNCIL_CONFIG": str(self.tmp / "config.json"),
        }
        if sid:
            env["CLAUDE_CODE_SESSION_ID"] = sid
        return subprocess.run(
            [sys.executable, str(news), *args], input=stdin, capture_output=True, text=True, env=env, check=False
        )

    def _cli(self, sid: str | None, *args: str) -> subprocess.CompletedProcess:
        return self._exec(NEWS, sid, "", args)

    def _hook(self, sid: str) -> list[str]:
        result = self._exec(NEWS, None, json.dumps({"session_id": sid, "prompt": "x"}), ("hook",))
        self.assertEqual(result.returncode, 0, result.stderr)
        return [line.split(" ", 3)[3] for line in result.stdout.splitlines()]

    def _mailbox(self, sid: str) -> list[str]:
        result = self._exec(NEWS, None, json.dumps({"session_id": sid}), ("mailbox",))
        self.assertIn(result.returncode, (0, 2), result.stderr)
        return [line.split(" ", 3)[3] for line in result.stderr.splitlines()]

    def test_every_session_sees_a_post_once_when_its_turn_ends_except_its_author(self):
        stamp, sent = self._cli("s1", "post", "core #1358   merged").stdout.splitlines()
        self.assertEqual((stamp.startswith("ts: "), sent), (True, "sent newsletter to all"))
        self.assertEqual(self._hook("s2"), [])
        self.assertEqual(self._mailbox("s2"), ["One: core #1358 merged"])
        self.assertEqual(self._mailbox("s2"), [])
        self.assertEqual(self._mailbox("s3"), ["One: core #1358 merged"])
        self.assertEqual(self._mailbox("s1"), [])

    def test_addressed_post_reaches_only_its_target(self):
        self._cli("s1", "post", "your gate is granted", "--to", "Two")
        self.assertEqual(self._mailbox("s3"), [])
        self.assertEqual(self._mailbox("s2"), ["One to Two: your gate is granted"])
        self.assertEqual(len(self._cli("s1", "show", "--all").stdout.splitlines()), 1)

    def test_hook_never_fails_and_post_needs_a_session(self):
        self.assertEqual(self._exec(NEWS, None, "not json", ("hook",)).returncode, 0)
        self.assertEqual(self._exec(NEWS, None, "{}", ("hook",)).stdout, "")
        self.assertEqual(self._cli(None, "post", "x").returncode, 2)
        self.assertEqual(self._cli("s1", "post", "   ").returncode, 2)

    def test_without_radio_the_hook_passes_and_the_rest_fail(self):
        lone = self.tmp / "skills" / "kvb-org-organize" / "scripts" / "news.py"
        lone.parent.mkdir(parents=True)
        shutil.copy(NEWS, lone)
        hook = self._exec(lone, None, json.dumps({"session_id": "s2"}), ("hook",))
        self.assertEqual((hook.returncode, hook.stdout), (0, ""))
        for args in (("post", "x"), ("show",)):
            with self.subTest(args=args):
                result = self._exec(lone, "s1", "", args)
                self.assertEqual(result.returncode, 2)
                self.assertIn("kvb-org-radio", result.stderr)
        self.assertFalse(self.root.exists())


if __name__ == "__main__":
    unittest.main()
