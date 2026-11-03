"""Validate the kvb-skill-tune skill text and its persistence targets."""

from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL = REPO_ROOT / "skills" / "kvb-skill-tune" / "SKILL.md"


class TestAutotuneSkill(unittest.TestCase):
    def test_skill_is_trigger_only(self):
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("name: kvb-skill-tune", text)
        self.assertIn("multiSelect: false", text)

    def test_skill_has_no_own_reminder_hook(self):
        self.assertFalse((SKILL.parent / "hooks").exists())


class TestSkillPersistence(unittest.TestCase):
    """Both skill writers must persist to the skills repository AND the live dirs."""

    def test_autotune_names_every_target(self):
        text = SKILL.read_text(encoding="utf-8")
        for target in (
            "SKILLS_REPO",
            "skills/<name>/SKILL.md",
            "~/.claude/skills/",
            "~/.agents/skills/",
        ):
            self.assertIn(target, text)

    def test_autoskill_routes_to_the_same_persistence(self):
        text = (REPO_ROOT / "skills" / "kvb-skill-auto" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        for target in ("Persistence", "~/.claude/skills/", "~/.agents/skills/"):
            self.assertIn(target, text)


if __name__ == "__main__":
    unittest.main()
