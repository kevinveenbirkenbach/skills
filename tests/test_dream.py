"""Validate the dream reminder hook and its settings registration."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL = REPO_ROOT / "skills" / "dream" / "SKILL.md"
HOOK = REPO_ROOT / "skills" / "dream" / "hooks" / "reminder.sh"
PATCHER = REPO_ROOT / "scripts" / "enable-plugins.js"


def _run_hook(
    cwd: Path, stamp: Path | None = None, interval: str = "43200"
) -> subprocess.CompletedProcess:
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(cwd),
        "DREAM_INTERVAL_SECONDS": interval,
    }
    if stamp is not None:
        env["DREAM_STAMP"] = str(stamp)
    return subprocess.run(
        ["bash", str(HOOK)],
        capture_output=True,
        text=True,
        check=True,
        cwd=str(cwd),
        env=env,
    )


class TestDreamSkill(unittest.TestCase):
    def test_skill_is_trigger_only(self):
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("name: dream", text)
        self.assertIn("multiSelect: false", text)


class TestDreamHook(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cwd = Path(self.tmp.name)
        self.stamp = self.cwd / ".claude" / ".dream-stamp"

    def test_first_run_hints_and_stamps(self):
        result = _run_hook(self.cwd, self.stamp)
        self.assertIn("/dream", result.stdout)
        self.assertTrue(self.stamp.is_file())

    def test_second_run_is_silent_within_interval(self):
        _run_hook(self.cwd, self.stamp)
        self.assertEqual(_run_hook(self.cwd, self.stamp).stdout, "")

    def test_hint_returns_after_the_interval(self):
        _run_hook(self.cwd, self.stamp)
        self.assertIn("/dream", _run_hook(self.cwd, self.stamp, interval="0").stdout)

    def test_corrupt_stamp_does_not_crash(self):
        self.stamp.parent.mkdir(parents=True, exist_ok=True)
        self.stamp.write_text("not-a-timestamp\n", encoding="utf-8")
        self.assertIn("/dream", _run_hook(self.cwd, self.stamp).stdout)

    def test_outside_a_repository_it_stays_silent(self):
        self.assertEqual(_run_hook(self.cwd).stdout, "")

    @unittest.skipUnless(shutil.which("git"), "git not installed")
    def test_stamp_is_per_repository(self):
        for name in ("one", "two"):
            repo = self.cwd / name
            repo.mkdir()
            subprocess.run(
                ["git", "init", "-q", str(repo)], check=True, capture_output=True
            )
            self.assertIn("/dream", _run_hook(repo).stdout)
            self.assertTrue((repo / ".git" / ".dream-stamp").is_file())
            self.assertEqual(_run_hook(repo).stdout, "")

    @unittest.skipUnless(shutil.which("git"), "git not installed")
    def test_linked_worktrees_share_the_stamp(self):
        repo = self.cwd / "main"
        tree = self.cwd / "tree"
        env = {
            "PATH": "/usr/bin:/bin",
            "HOME": str(self.cwd),
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
        }
        repo.mkdir()
        for args in (
            ["init", "-q"],
            ["commit", "-q", "--allow-empty", "-m", "init"],
            ["worktree", "add", "-q", str(tree)],
        ):
            subprocess.run(
                ["git", *args], check=True, capture_output=True, env=env, cwd=str(repo)
            )
        self.assertIn("/dream", _run_hook(repo).stdout)
        self.assertEqual(_run_hook(tree).stdout, "")


@unittest.skipUnless(shutil.which("node"), "node not installed")
class TestSettingsRegistration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.settings = Path(self.tmp.name) / "settings.json"

    def _patch(self) -> dict:
        subprocess.run(
            ["node", str(PATCHER), str(self.settings)], check=True, capture_output=True
        )
        return json.loads(self.settings.read_text(encoding="utf-8"))

    def test_hook_registered_once(self):
        self._patch()
        data = self._patch()
        entries = json.dumps(data["hooks"]["UserPromptSubmit"])
        self.assertEqual(entries.count("dream/hooks/reminder.sh"), 1)
        self.assertEqual(entries.count("autotune/hooks/reminder.sh"), 1)
        gate = json.dumps(data["hooks"]["PreToolUse"])
        self.assertEqual(gate.count("democracy/scripts/council.py"), 1)
        self.assertEqual(gate.count("democracy/scripts/watch.py"), 1)
        self.assertEqual(entries.count("democracy/scripts/watch.py"), 1)
        post = json.dumps(data["hooks"]["PostToolUse"])
        self.assertEqual(post.count("democracy/scripts/watch.py"), 1)
        self.assertEqual(gate.count("subagent-model/scripts/log.py"), 1)
        self.assertEqual(post.count("subagent-model/scripts/log.py"), 1)


if __name__ == "__main__":
    unittest.main()
