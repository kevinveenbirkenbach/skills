"""Pin the operator order of 2026-11-10: every release skill listens, then brainstorms, before it writes."""

from __future__ import annotations

import unittest
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[1] / "skills"
RELEASE = ["kvb-release", "kvb-release-article", "kvb-release-changelog", "kvb-release-post"]


def body(name: str) -> str:
    return (SKILLS / name / "SKILL.md").read_text(encoding="utf-8").split("---", 2)[2]


class TestReleaseSkills(unittest.TestCase):
    def test_the_release_skills_are_exactly_the_four_methods(self):
        self.assertEqual(sorted(path.parent.name for path in SKILLS.glob("kvb-release*/SKILL.md")), RELEASE)

    def test_every_release_skill_listens_before_it_brainstorms(self):
        for name in RELEASE:
            with self.subTest(skill=name):
                text = body(name)
                listen, brainstorm = text.find("kvb-think-listen"), text.find("kvb-think-brainstorm")
                self.assertGreaterEqual(listen, 0)
                self.assertGreater(brainstorm, listen)

    def test_the_collector_hands_every_form_to_its_method(self):
        text = body("kvb-release")
        for method in RELEASE[1:]:
            with self.subTest(method=method):
                self.assertIn(f"`{method}`", text)


if __name__ == "__main__":
    unittest.main()
