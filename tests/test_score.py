"""Exercise score.py of kvb-check-score: formula, dash and new values, capping, every gate verdict and exit code."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCORE = REPO_ROOT / "skills" / "kvb-check-score" / "scripts" / "score.py"
PASS = "✅ gate: 90/5, efficiency and speed <= 100"


class TestScore(unittest.TestCase):
    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(SCORE), *args], capture_output=True, text=True, check=False)

    def _score(self, fix: str, risk: str, efficiency: str, speed: str) -> tuple[list[str], int]:
        result = self._run("--fix", fix, "--break", risk, "--efficiency", efficiency, "--speed", speed)
        self.assertEqual(result.stderr, "")
        return result.stdout.splitlines(), result.returncode

    def test_formula_and_line_format(self):
        self.assertEqual(
            self._score("95", "4", "100", "100"),
            (["🎯 fix 95 % · 💥 break 4 % · 🌱 efficiency 100 % · ⚡ speed 100 % · 🏆 score 91", PASS], 0),
        )
        lines, code = self._score("95", "2", "97", "-")
        self.assertEqual(lines[0], "🎯 fix 95 % · 💥 break 2 % · 🌱 efficiency 97 % · ⚡ speed – · 🏆 score 96")
        self.assertEqual(code, 0)
        self.assertEqual(self._score("92.5", "0", "100", "100")[0][0].split(" · ")[0], "🎯 fix 92.5 %")

    def test_dash_values_count_as_100(self):
        self.assertEqual(
            self._score("92", "3", "-", "-"),
            (["🎯 fix 92 % · 💥 break 3 % · 🌱 efficiency – · ⚡ speed – · 🏆 score 89", PASS], 0),
        )

    def test_score_rounds_half_up(self):
        for args, total in (
            (("94.5", "0", "-", "-"), 95),
            (("90", "5", "100", "100"), 86),
            (("91", "5", "-", "-"), 86),
            (("97", "0", "97", "-"), 100),
        ):
            with self.subTest(args=args):
                self.assertTrue(self._score(*args)[0][0].endswith(f"🏆 score {total}"))

    def test_score_is_capped(self):
        lines, code = self._score("100", "0", "50", "50")
        self.assertTrue(lines[0].endswith("🏆 score 100"))
        self.assertEqual((lines[1], code), (PASS, 0))
        lines, code = self._score("0", "100", "-", "-")
        self.assertTrue(lines[0].endswith("🏆 score 0"))
        self.assertEqual(code, 1)

    def test_boundaries_pass(self):
        self.assertEqual(self._score("90", "5", "100", "100")[1], 0)

    def test_90_5_failures_exit_1(self):
        for args, verdict in (
            (("89.5", "1", "-", "-"), "⛔ gate: fix 89.5 % < 90"),
            (("95", "6", "-", "-"), "⛔ gate: break 6 % > 5"),
            (("80", "10", "-", "-"), "⛔ gate: fix 80 % < 90, break 10 % > 5"),
            (("85", "2", "150", "new"), "⛔ gate: fix 85 % < 90"),
        ):
            with self.subTest(args=args):
                lines, code = self._score(*args)
                self.assertEqual((lines[1], code), (verdict, 1))

    def test_cost_over_100_asks_the_operator_exit_3(self):
        cases = {
            ("120", "100"): "⚠️ gate: efficiency 120 % > 100: ask the operator before the commit",
            ("-", "130"): "⚠️ gate: speed 130 % > 100: ask the operator before the commit",
            ("120", "130"): "⚠️ gate: efficiency 120 % > 100, speed 130 % > 100: ask the operator before the commit",
            ("100.5", "-"): "⚠️ gate: efficiency 100.5 % > 100: ask the operator before the commit",
            ("new", "-"): "⚠️ gate: efficiency new: ask the operator before the commit",
        }
        for (efficiency, speed), verdict in cases.items():
            with self.subTest(efficiency=efficiency, speed=speed):
                lines, code = self._score("95", "2", efficiency, speed)
                self.assertEqual((lines[1], code), (verdict, 3))

    def test_new_counts_as_100_in_the_score(self):
        lines, _ = self._score("95", "0", "new", "-")
        self.assertEqual(lines[0], "🎯 fix 95 % · 💥 break 0 % · 🌱 efficiency new · ⚡ speed – · 🏆 score 95")

    def test_usage_errors_exit_2(self):
        good = {"--fix": "95", "--break": "2", "--efficiency": "100", "--speed": "100"}
        bad = (
            ("--fix", "101"), ("--fix", "-1"), ("--fix", "nan"), ("--break", "x"), ("--break", "-"),
            ("--efficiency", "0"), ("--efficiency", "-5"), ("--efficiency", "abc"), ("--speed", "inf"),
        )
        for flag, value in bad:
            with self.subTest(flag=flag, value=value):
                args = [item for key, val in {**good, flag: value}.items() for item in (key, val)]
                result = self._run(*args)
                self.assertEqual((result.returncode, result.stdout), (2, ""))
        self.assertEqual(self._run("--fix", "95", "--break", "2", "--efficiency", "100").returncode, 2)


if __name__ == "__main__":
    unittest.main()
