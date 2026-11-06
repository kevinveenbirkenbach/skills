"""Exercise coach.py: preferences flip between like and dislike, the log feeds hours since."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "skills" / "kvb-coach" / "scripts" / "coach.py"
HOOK = REPO_ROOT / "skills" / "kvb-coach" / "hooks" / "reminder.sh"


class TestCoach(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.profile = Path(self.tmp.name) / "state" / "coach.json"

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--profile", str(self.profile), *args],
            check=False,
            capture_output=True,
            text=True,
        )

    def _show(self, now: str) -> dict:
        result = self._run("show", "--now", now, "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        return {row["area"]: row for row in json.loads(result.stdout)}

    def test_a_dislike_replaces_a_like_and_forget_drops_it(self):
        self._run("like", "body", "Laufen")
        self._run("like", "body", "Laufen")
        self._run("like", "body", "Yoga")
        self._run("dislike", "body", "Laufen")
        body = self._show("2026-11-03T18:00:00+00:00")["body"]
        self.assertEqual(body["likes"], ["Yoga"])
        self.assertEqual(body["dislikes"], ["Laufen"])
        self._run("forget", "body", "Laufen")
        self.assertEqual(self._show("2026-11-03T18:00:00+00:00")["body"]["dislikes"], [])

    def test_the_latest_done_per_area_gives_the_hours_since(self):
        self._run("done", "food", "Frühstück", "--at", "2026-11-03T08:00:00+00:00")
        self._run("done", "food", "Mittagessen", "--at", "2026-11-03T12:30:00+00:00")
        self._run("done", "sleep", "Nacht", "--at", "2026-11-02T23:00:00+00:00")
        rows = self._show("2026-11-03T18:00:00+00:00")
        self.assertEqual((rows["food"]["last"], rows["food"]["hours_ago"]), ("Mittagessen", 5.5))
        self.assertEqual(rows["sleep"]["hours_ago"], 19.0)
        self.assertIsNone(rows["psyche"]["last"])

    def test_invalid_input_exits_2_and_keeps_the_profile(self):
        self.assertEqual(self._run("like", "work", "x").returncode, 2)
        self.assertEqual(self._run("done", "body", "x", "--at", "gestern").returncode, 2)
        self.assertFalse(self.profile.exists())
        self.profile.parent.mkdir(parents=True)
        self.profile.write_text("{broken", encoding="utf-8")
        self.assertEqual(self._run("show").returncode, 2)
        self.assertEqual(self.profile.read_text(encoding="utf-8"), "{broken")


class TestCoachHour(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.hours = Path(self.tmp.name) / "hours"

    def _run(self, hour: str) -> str:
        return subprocess.run(
            ["bash", str(HOOK)],
            check=True,
            capture_output=True,
            text=True,
            env={
                "PATH": "/usr/bin:/bin",
                "HOME": self.tmp.name,
                "COACH_STAMP_DIR": str(self.hours),
                "COACH_HOUR": hour,
            },
        ).stdout

    def test_first_prompt_of_each_hour_triggers_the_coach_once(self):
        self.assertIn("kvb-coach", self._run("2026-11-03T14"))
        self.assertEqual(self._run("2026-11-03T14"), "")
        self.assertIn("kvb-coach", self._run("2026-11-03T15"))
        self.assertEqual(sorted(p.name for p in self.hours.iterdir()), ["2026-11-03T15"])

    def test_a_binary_planted_on_the_inherited_path_never_runs(self):
        planted = Path(self.tmp.name) / "planted"
        planted.mkdir()
        marker = Path(self.tmp.name) / "ran"
        for name in ("mkdir", "find", "cat", "date"):
            fake = planted / name
            fake.write_text(f"#!/bin/sh\n/usr/bin/touch '{marker}'\n", encoding="utf-8")
            fake.chmod(0o755)
        subprocess.run(
            ["bash", str(HOOK)],
            check=True,
            capture_output=True,
            text=True,
            env={
                "PATH": f"{planted}:/usr/bin:/bin",
                "HOME": self.tmp.name,
                "COACH_STAMP_DIR": str(self.hours),
                "COACH_HOUR": "2026-11-03T14",
            },
        )
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
