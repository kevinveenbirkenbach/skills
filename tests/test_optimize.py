"""The self-improving skills must share the optimize objective."""

from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS = REPO_ROOT / "skills"
ROUTERS = ("autotune", "autoskill", "confidence")


class TestOptimizeObjective(unittest.TestCase):
    def test_skill_names_the_three_axes(self):
        text = (SKILLS / "optimize" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("name: optimize", text)
        for axis in ("**Tokens**", "**Time**", "**Quality**"):
            self.assertIn(axis, text)

    def test_routers_point_at_it(self):
        for skill in ROUTERS:
            text = (SKILLS / skill / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn(
                "`optimize` skill", text, f"{skill} does not route to optimize"
            )


if __name__ == "__main__":
    unittest.main()
