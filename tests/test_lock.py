"""Validate skills-lock.json: shape, required fields, and hash format."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LOCK_FILE = REPO_ROOT / "skills-lock.json"

HASH_RE = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_FIELDS = ("source", "sourceType", "skillPath", "computedHash")


class TestSkillsLock(unittest.TestCase):
    def setUp(self):
        self.lock = json.loads(LOCK_FILE.read_text(encoding="utf-8"))

    def test_version_is_supported(self):
        self.assertEqual(self.lock.get("version"), 1)

    def test_skills_present(self):
        self.assertTrue(self.lock.get("skills"), "lock holds no skills")

    def test_every_skill_is_complete(self):
        for name, entry in self.lock["skills"].items():
            with self.subTest(skill=name):
                for field in REQUIRED_FIELDS:
                    self.assertTrue(
                        str(entry.get(field, "")).strip(),
                        f"{name}: missing or empty field '{field}'",
                    )
                self.assertRegex(
                    entry["computedHash"],
                    HASH_RE,
                    f"{name}: computedHash is not a sha256 hex digest",
                )
                self.assertTrue(
                    entry["skillPath"].endswith("SKILL.md"),
                    f"{name}: skillPath must point to a SKILL.md",
                )

    def test_skills_sorted_ascending(self):
        names = list(self.lock["skills"].keys())
        self.assertEqual(
            names,
            sorted(names),
            f"skills must be sorted ascending; expected {sorted(names)}",
        )

    def test_first_party_skills_have_valid_frontmatter(self):
        for skill_md in sorted((REPO_ROOT / "skills").glob("*/SKILL.md")):
            with self.subTest(skill=skill_md.parent.name):
                text = skill_md.read_text(encoding="utf-8")
                self.assertTrue(text.startswith("---\n"), "missing frontmatter")
                frontmatter = text.split("---", 2)[1]
                self.assertIn("name:", frontmatter, "frontmatter missing name")
                self.assertIn(
                    "description:", frontmatter, "frontmatter missing description"
                )

    def test_first_party_skills_do_not_shadow_locked_skills(self):
        locked = set(self.lock["skills"].keys())
        for skill_dir in sorted((REPO_ROOT / "skills").glob("*/")):
            self.assertNotIn(
                skill_dir.name.rstrip("/"),
                locked,
                f"first-party skill '{skill_dir.name}' collides with a locked skill",
            )


if __name__ == "__main__":
    unittest.main()
