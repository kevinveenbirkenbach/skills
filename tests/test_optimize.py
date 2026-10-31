"""The self-improving skills must share the objective held by kvb-skills-tune."""

from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS = REPO_ROOT / "skills"
ROUTERS = ("kvb-skills-auto", "kvb-check-confidence")


class TestOptimizeObjective(unittest.TestCase):
    def test_autotune_names_the_three_axes(self):
        text = (SKILLS / "kvb-skills-tune" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("## Objective", text)
        for axis in ("**Tokens**", "**Time**", "**Quality**"):
            self.assertIn(axis, text)

    def test_routers_point_at_it(self):
        for skill in ROUTERS:
            text = (SKILLS / skill / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn(
                "`kvb-skills-tune` skill's **Objective**",
                text,
                f"{skill} does not route to the kvb-skills-tune objective",
            )


if __name__ == "__main__":
    unittest.main()
