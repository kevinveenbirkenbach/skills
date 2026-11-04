"""Validate the kvb-dream reminder, its GNOME notification, timer and settings registration."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DREAM = REPO_ROOT / "skills" / "kvb-dream"
SKILL = DREAM / "SKILL.md"
HOOK = DREAM / "hooks" / "reminder.sh"
NOTIFY = DREAM / "hooks" / "notify.sh"
TIMER = DREAM / "systemd" / "kvb-dream-notify.timer"
SERVICE = DREAM / "systemd" / "kvb-dream-notify.service"
PATCHER = REPO_ROOT / "scripts" / "enable-plugins.js"


class TestDreamSkill(unittest.TestCase):
    def test_skill_runs_optimize_and_the_cleanups(self):
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("name: kvb-dream", text)
        self.assertIn("multiSelect: false", text)
        for skill in ("`kvb-optimize`", "`kvb-cleanup`", "`kvb-git-branch-gc`"):
            self.assertIn(skill, text)

    def test_optimize_covers_every_optimization_skill(self):
        text = (REPO_ROOT / "skills" / "kvb-optimize" / "SKILL.md").read_text(encoding="utf-8")
        for skill in (
            "kvb-skill-cleanup",
            "kvb-transcend",
            "kvb-skill-auto",
            "kvb-skill-tune",
            "kvb-skill-compile",
            "kvb-skill-essence",
            "kvb-skill-silence",
            "kvb-code-refactor",
            "kvb-code-tune",
            "kvb-agent-optimize",
            "kvb-think-gaps",
        ):
            self.assertIn(f"`{skill}`", text)


class TestDreamHook(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.stamps = Path(self.tmp.name) / "stamps"

    def _run(self, payload: str, interval: str = "43200") -> str:
        return subprocess.run(
            ["bash", str(HOOK)],
            input=payload,
            capture_output=True,
            text=True,
            check=True,
            env={
                "PATH": "/usr/bin:/bin",
                "HOME": self.tmp.name,
                "DREAM_STAMP_DIR": str(self.stamps),
                "DREAM_INTERVAL_SECONDS": interval,
            },
        ).stdout

    @staticmethod
    def _session(sid: str) -> str:
        return json.dumps({"session_id": sid, "prompt": "hi"})

    def test_first_run_hints_and_stamps_the_session(self):
        self.assertIn("/kvb-dream", self._run(self._session("a1")))
        self.assertTrue((self.stamps / "a1").is_file())

    def test_second_run_of_the_same_agent_is_silent(self):
        self._run(self._session("a1"))
        self.assertEqual(self._run(self._session("a1")), "")

    def test_every_agent_gets_its_own_hint(self):
        self._run(self._session("a1"))
        self.assertIn("/kvb-dream", self._run(self._session("b2")))

    def test_hint_returns_after_the_interval(self):
        self._run(self._session("a1"))
        self.assertIn("/kvb-dream", self._run(self._session("a1"), interval="0"))

    def test_corrupt_stamp_does_not_crash(self):
        self.stamps.mkdir()
        (self.stamps / "a1").write_text("not-a-timestamp\n", encoding="utf-8")
        self.assertIn("/kvb-dream", self._run(self._session("a1")))

    def test_without_a_valid_session_it_stays_silent(self):
        for payload in ("", "not json", self._session(""), self._session("../escape")):
            with self.subTest(payload=payload):
                self.assertEqual(self._run(payload), "")
        self.assertFalse(self.stamps.exists())


class TestDreamNotification(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bin = Path(self.tmp.name) / "bin"
        self.bin.mkdir()
        self.calls = Path(self.tmp.name) / "calls"
        fake = self.bin / "notify-send"
        fake.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" >> "{self.calls}"\n', encoding="utf-8")
        fake.chmod(0o755)

    def _run(self, desktop: str) -> None:
        subprocess.run(
            ["bash", str(NOTIFY)],
            capture_output=True,
            check=True,
            env={"PATH": f"{self.bin}:/usr/bin:/bin", "XDG_CURRENT_DESKTOP": desktop},
        )

    def test_gnome_session_gets_the_popup(self):
        self._run("ubuntu:GNOME")
        self.assertIn("/kvb-dream", self.calls.read_text(encoding="utf-8"))

    def test_other_desktops_stay_silent(self):
        self._run("KDE")
        self.assertFalse(self.calls.exists())

    def test_timer_fires_daily_at_five_pm_and_catches_up(self):
        timer = TIMER.read_text(encoding="utf-8")
        self.assertIn("OnCalendar=*-*-* 17:00:00", timer)
        self.assertIn("Persistent=true", timer)
        self.assertIn("kvb-dream/hooks/notify.sh", SERVICE.read_text(encoding="utf-8"))


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

    @staticmethod
    def _hooks(data: dict, event: str, script: str) -> list[dict]:
        return [
            hook
            for entry in data["hooks"].get(event, [])
            for hook in entry.get("hooks", [])
            if script in hook.get("command", "")
        ]

    def test_hook_registered_once(self):
        self._patch()
        data = self._patch()
        expected = {
            ("UserPromptSubmit", "kvb-dream/hooks/reminder.sh"): 1,
            ("UserPromptSubmit", "kvb-coach/hooks/reminder.sh"): 1,
            ("UserPromptSubmit", "tune/hooks/reminder.sh"): 0,
            ("UserPromptSubmit", "kvb-org-organize/scripts/watch.py"): 1,
            ("UserPromptSubmit", "kvb-org-radio/scripts/radio.py"): 1,
            ("UserPromptSubmit", "kvb-org-organize/scripts/news.py"): 0,
            ("PostToolBatch", "kvb-org-radio/scripts/radio.py"): 1,
            ("Stop", "kvb-org-radio/scripts/radio.py"): 1,
            ("PreToolUse", "kvb-org-organize/scripts/council.py"): 1,
            ("PreToolUse", "kvb-org-organize/scripts/watch.py"): 1,
            ("PreToolUse", "kvb-org-queue/scripts/queue.py"): 1,
            ("PreToolUse", "kvb-org-perform/scripts/log.py"): 1,
            ("PostToolUse", "kvb-org-organize/scripts/watch.py"): 1,
            ("PostToolUse", "kvb-org-perform/scripts/log.py"): 1,
        }
        for (event, script), count in expected.items():
            with self.subTest(event=event, script=script):
                self.assertEqual(len(self._hooks(data, event, script)), count)

    def test_radio_listener_wakes_asynchronously_and_hooks_survive_a_missing_script(self):
        data = self._patch()
        (listen,) = self._hooks(data, "Stop", "kvb-org-radio/scripts/radio.py")
        self.assertIs(listen["asyncRewake"], True)
        self.assertGreater(listen["timeout"], 3600)
        self.assertTrue(listen["command"].endswith(" listen"))
        (gate,) = self._hooks(data, "PreToolUse", "kvb-org-queue/scripts/queue.py")
        result = subprocess.run(["sh", "-c", gate["command"]], capture_output=True, check=False)
        self.assertEqual(result.returncode, 1)

    def test_news_hook_moves_to_radio(self):
        base = Path(self.tmp.name) / "skills"
        self.settings.write_text(
            json.dumps({"hooks": {"UserPromptSubmit": [
                {"hooks": [{"type": "command", "command": f'python3 "{base}/kvb-org-organize/scripts/news.py" hook'}]}
            ]}}),
            encoding="utf-8",
        )
        data = self._patch()
        self.assertEqual(self._hooks(data, "UserPromptSubmit", "kvb-org-organize/scripts/news.py"), [])
        self.assertEqual(len(self._hooks(data, "UserPromptSubmit", "kvb-org-radio/scripts/radio.py")), 1)

    def test_code_graph_plugin_is_retired_for_the_agent_agnostic_installer(self):
        self.settings.write_text(
            json.dumps({
                "enabledPlugins": {"codebase-memory@codebase-memory": True},
                "extraKnownMarketplaces": {"codebase-memory": {"source": {"source": "github", "repo": "x/y"}}},
            }),
            encoding="utf-8",
        )
        data = self._patch()
        self.assertNotIn("codebase-memory@codebase-memory", data["enabledPlugins"])
        self.assertNotIn("codebase-memory", data["extraKnownMarketplaces"])
        self.assertTrue(data["enabledPlugins"]["caveman@caveman"])

    def test_compact_window_is_set_once_and_never_overwritten(self):
        self.assertEqual(self._patch()["env"]["CLAUDE_CODE_AUTO_COMPACT_WINDOW"], "500000")
        self.settings.write_text(json.dumps({"env": {"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "300000"}}), encoding="utf-8")
        self.assertEqual(self._patch()["env"]["CLAUDE_CODE_AUTO_COMPACT_WINDOW"], "300000")

    def test_plugin_skills_are_not_copied_twice(self):
        skills = Path(self.tmp.name) / "skills"
        for name in ("caveman", "ponytail-review", "cavecrew", "archify", "kvb-dream"):
            (skills / name).mkdir(parents=True)
        self._patch()
        self.assertEqual(sorted(p.name for p in skills.iterdir()), ["archify", "kvb-dream"])

    def test_existing_hooks_preserved(self):
        self.settings.write_text(
            json.dumps({"hooks": {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": "true"}]}]}}),
            encoding="utf-8",
        )
        data = self._patch()
        self.assertIn('"true"', json.dumps(data["hooks"]["UserPromptSubmit"]))

    def test_tune_reminders_retire_and_dream_reminders_are_repointed(self):
        base = Path(self.tmp.name) / "skills"

        def hook(command):
            return {"hooks": [{"type": "command", "command": command}]}

        self.settings.write_text(
            json.dumps(
                {
                    "hooks": {
                        "UserPromptSubmit": [
                            hook(f'bash "{base}/autotune/hooks/reminder.sh"'),
                            hook(f'bash "{base}/kvb-skill-tune/hooks/reminder.sh"'),
                            hook(f'bash "{base}/kvb-skill-dream/hooks/reminder.sh"'),
                            hook(f'python3 "{base}/democracy/scripts/watch.py" watch'),
                            hook("echo keep"),
                        ],
                        "PreToolUse": [
                            hook(f'python3 "{base}/democracy/scripts/council.py" gate'),
                            hook(f'python3 "{base}/democracy/scripts/watch.py" block'),
                            hook(f'python3 "{base}/subagent-model/scripts/log.py" spawn'),
                        ],
                        "PostToolUse": [
                            hook(f'python3 "{base}/democracy/scripts/watch.py" watch'),
                            hook(f'python3 "{base}/subagent-model/scripts/log.py" persist'),
                        ],
                    }
                }
            ),
            encoding="utf-8",
        )
        data = self._patch()
        text = json.dumps(data["hooks"])
        for old in ("/autotune/", "/kvb-skill-tune/", "/kvb-skill-dream/", "/democracy/", "/subagent-model/"):
            self.assertNotIn(f"skills{old}", text)
        self.assertIn("echo keep", text)
        self.assertEqual(len(self._hooks(data, "UserPromptSubmit", "kvb-dream/hooks/reminder.sh")), 1)
        self.assertEqual(len(self._hooks(data, "UserPromptSubmit", "kvb-org-organize/scripts/watch.py")), 1)
        self.assertEqual(len(self._hooks(data, "PreToolUse", "kvb-org-organize/scripts/council.py")), 1)
        self.assertEqual(len(self._hooks(data, "PreToolUse", "kvb-org-perform/scripts/log.py")), 1)


if __name__ == "__main__":
    unittest.main()
