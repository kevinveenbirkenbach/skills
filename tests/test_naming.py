"""Pin every first-party skill name to kvb-<category>-<name> and the Agent Skills name rules."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS = REPO_ROOT / "skills"
README = REPO_ROOT / "README.md"
CATEGORIES = ("think", "create", "code", "ci", "git", "check", "org", "skill")
UNCATEGORIZED = frozenset(
    {"kvb-cleanup", "kvb-coach", "kvb-dream", "kvb-help", "kvb-optimize", "kvb-transcend"}
)
SPEC = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
SCHEMA = re.compile(rf"^kvb-(?:{'|'.join(CATEGORIES)})-[a-z0-9]+(?:-[a-z0-9]+)*$")
NAME_LINE = re.compile(r"^name:\s*(\S+)\s*$", re.MULTILINE)
ORGANIGRAM_EDGE = re.compile(r"^\s*(\w+) --> \w+\[(kvb-[a-z0-9-]+)\]\s*$", re.MULTILINE)


class TestSkillNames(unittest.TestCase):
    def setUp(self):
        self.names = sorted(p.name for p in SKILLS.iterdir() if p.is_dir())

    def test_name_field_matches_the_directory(self):
        for name in self.names:
            with self.subTest(skill=name):
                text = (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")
                match = NAME_LINE.search(text)
                self.assertIsNotNone(match, "SKILL.md has no name: line")
                self.assertEqual(match.group(1), name)

    def test_names_follow_the_agent_skills_rules(self):
        for name in self.names:
            with self.subTest(skill=name):
                self.assertRegex(name, SPEC)
                self.assertLessEqual(len(name), 64)
                self.assertNotRegex(name, "anthropic|claude")

    def test_names_use_a_listed_category(self):
        for name in self.names:
            if name in UNCATEGORIZED:
                continue
            with self.subTest(skill=name):
                self.assertRegex(name, SCHEMA)

    def test_every_category_and_exception_is_in_use(self):
        for category in CATEGORIES:
            with self.subTest(category=category):
                self.assertTrue(
                    any(n.startswith(f"kvb-{category}-") for n in self.names),
                    f"category {category} has no skill",
                )
        self.assertLessEqual(UNCATEGORIZED, set(self.names))

    def test_readme_organigram_places_every_skill_under_its_category(self):
        text = README.read_text(encoding="utf-8")
        section = text.split("## Organigram", 1)[1].split("\n## ", 1)[0]
        edges = ORGANIGRAM_EDGE.findall(section)
        self.assertEqual(sorted(name for _, name in edges), self.names)
        for parent, name in edges:
            with self.subTest(skill=name):
                expected = "none" if name in UNCATEGORIZED else name.split("-")[1]
                self.assertEqual(parent, expected)


if __name__ == "__main__":
    unittest.main()
