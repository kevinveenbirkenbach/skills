"""Validate the autotune reminder hook and its settings registration."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL = REPO_ROOT / "skills" / "autotune" / "SKILL.md"
HOOK = REPO_ROOT / "skills" / "autotune" / "hooks" / "reminder.sh"
PATCHER = REPO_ROOT / "scripts" / "enable-plugins.js"


def _run_hook(stamp: Path, interval: str = "3600") -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(HOOK)],
        capture_output=True,
        text=True,
        check=True,
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": str(stamp.parent),
            "AUTOTUNE_STAMP": str(stamp),
            "AUTOTUNE_INTERVAL_SECONDS": interval,
        },
    )


class TestAutotuneSkill(unittest.TestCase):
    def test_skill_is_trigger_only(self):
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("name: autotune", text)
        self.assertIn("multiSelect: false", text)


class TestAutotuneHook(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.stamp = Path(self.tmp.name) / ".claude" / ".autotune-stamp"

    def test_first_run_hints_and_stamps(self):
        result = _run_hook(self.stamp)
        self.assertIn("/autotune", result.stdout)
        self.assertTrue(self.stamp.is_file())

    def test_second_run_is_silent_within_interval(self):
        _run_hook(self.stamp)
        self.assertEqual(_run_hook(self.stamp).stdout, "")

    def test_hint_returns_after_the_interval(self):
        _run_hook(self.stamp)
        self.assertIn("/autotune", _run_hook(self.stamp, interval="0").stdout)

    def test_corrupt_stamp_does_not_crash(self):
        self.stamp.parent.mkdir(parents=True, exist_ok=True)
        self.stamp.write_text("not-a-timestamp\n", encoding="utf-8")
        self.assertIn("/autotune", _run_hook(self.stamp).stdout)


@unittest.skipUnless(shutil.which("node"), "node not installed")
class TestSettingsRegistration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.settings = Path(self.tmp.name) / "settings.json"

    def _patch(self) -> dict:
        subprocess.run(["node", str(PATCHER), str(self.settings)], check=True, capture_output=True)
        return json.loads(self.settings.read_text(encoding="utf-8"))

    def test_hook_registered_once(self):
        self._patch()
        data = self._patch()
        entries = json.dumps(data["hooks"]["UserPromptSubmit"])
        self.assertEqual(entries.count("autotune/hooks/reminder.sh"), 1)

    def test_existing_hooks_preserved(self):
        self.settings.write_text(
            json.dumps({"hooks": {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": "true"}]}]}}),
            encoding="utf-8",
        )
        data = self._patch()
        self.assertEqual(len(data["hooks"]["UserPromptSubmit"]), 2)


if __name__ == "__main__":
    unittest.main()
