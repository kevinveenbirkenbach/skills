"""Exercise score.py of kvb-check-score: formula, dash and new values, security, capping, gate verdicts, tables."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCORE = REPO_ROOT / "skills" / "kvb-check-score" / "scripts" / "score.py"
PASS = "✅ gate: 90/5, cost and time <= 100, security 100 %"
BASE = {"fix": "95", "break": "2", "efficiency": "100", "speed": "100", "security": "100", "critical": "0"}
HEADER = "| 🎯 Fix | 💥 Break | 💸 Cost | ⏱️ Time | 🛡️ Security | 🏆 Score | Gate |"
ASK = ": ask the operator before the commit"
ENV = {"PATH": os.environ["PATH"]}


def flags(values: dict[str, str]) -> list[str]:
    return [item for key, value in values.items() for item in (f"--{key}", value)]


class TestScore(unittest.TestCase):
    def _run(self, *args: str, cwd: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SCORE), *args], cwd=cwd, env=ENV, capture_output=True, text=True, check=False
        )

    def _score(self, **values: str) -> tuple[list[str], int]:
        result = self._run(*flags({**BASE, **values}), cwd=REPO_ROOT)
        self.assertEqual(result.stderr, "")
        return result.stdout.splitlines(), result.returncode

    def test_formula_and_line_format(self):
        self.assertEqual(
            self._score(fix="95", **{"break": "4"}),
            (["🎯 fix 95 % · 💥 break 4 % · 💸 cost 100 % · ⏱️ time 100 % · 🛡️ security 100 % · 🏆 score 91",
              PASS], 0),
        )
        lines, code = self._score(efficiency="97", speed="-")
        self.assertEqual(
            lines[0], "🎯 fix 95 % · 💥 break 2 % · 💸 cost 97 % · ⏱️ time – · 🛡️ security 100 % · 🏆 score 96"
        )
        self.assertEqual(code, 0)
        self.assertEqual(self._score(fix="92.5")[0][0].split(" · ")[0], "🎯 fix 92.5 %")

    def test_dash_values_count_as_100(self):
        lines, code = self._score(fix="92", efficiency="-", speed="-", **{"break": "3"})
        self.assertEqual(
            (lines, code),
            (["🎯 fix 92 % · 💥 break 3 % · 💸 cost – · ⏱️ time – · 🛡️ security 100 % · 🏆 score 89", PASS], 0),
        )

    def test_security_multiplies_and_asks_below_100(self):
        lines, code = self._score(fix="100", efficiency="-", speed="-", security="75", **{"break": "0"})
        self.assertEqual(
            (lines, code),
            (["🎯 fix 100 % · 💥 break 0 % · 💸 cost – · ⏱️ time – · 🛡️ security 75 % · 🏆 score 75",
              f"⚠️ gate: security 75 % < 100{ASK}"], 3),
        )
        lines, code = self._score(security="~80")
        self.assertIn("🛡️ security ~80 % · 🏆 score 74", lines[0])
        self.assertEqual((lines[1], code), (f"⚠️ gate: security ~80 % < 100{ASK}", 3))
        self.assertEqual(self._score(security="~100")[1], 0)

    def test_score_rounds_half_up(self):
        for values, total in (
            ({"fix": "94.5", "break": "0"}, 95),
            ({"fix": "90", "break": "5"}, 86),
            ({"fix": "91", "break": "5"}, 86),
            ({"fix": "97", "break": "0", "efficiency": "97"}, 100),
        ):
            with self.subTest(values=values):
                self.assertTrue(self._score(**values)[0][0].endswith(f"🏆 score {total}"))

    def test_score_is_capped(self):
        lines, code = self._score(fix="100", efficiency="50", speed="50", **{"break": "0"})
        self.assertTrue(lines[0].endswith("🏆 score 100"))
        self.assertEqual((lines[1], code), (PASS, 0))
        lines, code = self._score(fix="0", **{"break": "100"})
        self.assertTrue(lines[0].endswith("🏆 score 0"))
        self.assertEqual(code, 1)

    def test_boundaries_pass(self):
        self.assertEqual(self._score(fix="90", **{"break": "5"})[1], 0)

    def test_90_5_failures_exit_1(self):
        for values, verdict in (
            ({"fix": "89.5", "break": "1"}, "⛔ gate: fix 89.5 % < 90"),
            ({"break": "6"}, "⛔ gate: break 6 % > 5"),
            ({"fix": "80", "break": "10"}, "⛔ gate: fix 80 % < 90, break 10 % > 5"),
            (
                {"fix": "85", "efficiency": "150", "speed": "new", "security": "50"},
                f"⛔ gate: fix 85 % < 90; cost 150 % > 100, time new, security 50 % < 100{ASK}",
            ),
        ):
            with self.subTest(values=values):
                lines, code = self._score(**values)
                self.assertEqual((lines[1], code), (verdict, 1))

    def test_costs_ask_the_operator_exit_3(self):
        for values, verdict in (
            ({"efficiency": "120"}, f"⚠️ gate: cost 120 % > 100{ASK}"),
            ({"efficiency": "-", "speed": "130"}, f"⚠️ gate: time 130 % > 100{ASK}"),
            ({"efficiency": "100.5", "speed": "-"}, f"⚠️ gate: cost 100.5 % > 100{ASK}"),
            ({"efficiency": "new", "speed": "-"}, f"⚠️ gate: cost new{ASK}"),
            (
                {"efficiency": "120", "speed": "130", "security": "90"},
                f"⚠️ gate: cost 120 % > 100, time 130 % > 100, security 90 % < 100{ASK}",
            ),
        ):
            with self.subTest(values=values):
                lines, code = self._score(**values)
                self.assertEqual((lines[1], code), (verdict, 3))

    def test_critical_finding_wins_exit_4(self):
        for values in (
            {"critical": "1", "security": "50"},
            {"critical": "2", "fix": "80", "break": "10", "efficiency": "150", "security": "0"},
        ):
            with self.subTest(values=values):
                lines, code = self._score(**values)
                self.assertEqual((lines[1], code), ("⛔ gate: critical security finding: do not commit", 4))

    def test_new_counts_as_100_in_the_score(self):
        lines, _ = self._score(efficiency="new", speed="-", **{"break": "0"})
        self.assertEqual(
            lines[0], "🎯 fix 95 % · 💥 break 0 % · 💸 cost new · ⏱️ time – · 🛡️ security 100 % · 🏆 score 95"
        )

    def test_table(self):
        result = self._run(*flags({**BASE, "efficiency": "97", "speed": "-"}), "--table", cwd=REPO_ROOT)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                HEADER,
                "| --- | --- | --- | --- | --- | --- | --- |",
                "| 95 % | 2 % | 97 % | – | 100 % | 96 | ✅ 90/5, cost and time <= 100, security 100 % |",
            ],
        )
        self.assertEqual(result.returncode, 0)
        result = self._run(*flags({**BASE, "critical": "1"}), "--table", cwd=REPO_ROOT)
        self.assertTrue(result.stdout.splitlines()[2].endswith("| ⛔ critical security finding: do not commit |"))
        self.assertEqual(result.returncode, 4)

    def test_message_block_lists_one_value_per_line(self):
        result = self._run(*flags({**BASE, "efficiency": "97", "speed": "-"}), "--message-block", cwd=REPO_ROOT)
        self.assertEqual(
            (result.stdout.splitlines(), result.returncode),
            (
                [
                    "🎯 Fix: 95 %", "💥 Break: 2 %", "💸 Cost: 97 %", "⏱️ Time: –", "🛡️ Security: 100 %",
                    "🏆 Score: 96", "🚦 Gate: ✅ 90/5, cost and time <= 100, security 100 %",
                ],
                0,
            ),
        )
        result = self._run(
            *flags({**BASE, "security": "~80"}), "--message-block", "--value", "1:20", cwd=REPO_ROOT
        )
        self.assertEqual(
            (result.stdout.splitlines(), result.returncode),
            (
                [
                    "🎯 Fix: 95 %", "💥 Break: 2 %", "💸 Cost: 100 %", "⏱️ Time: 100 %", "🛡️ Security: ~80 %",
                    "💰 Value: 1:20", "🏆 Score: 74", f"🚦 Gate: ⚠️ security ~80 % < 100{ASK}",
                ],
                3,
            ),
        )

    def test_message_block_gate_matches_the_gate_line(self):
        for values, code in (
            ({}, 0),
            ({"break": "6"}, 1),
            ({"efficiency": "new"}, 3),
            ({"critical": "1"}, 4),
        ):
            with self.subTest(values=values):
                lines, line_code = self._score(**values)
                block = self._run(*flags({**BASE, **values}), "--message-block", cwd=REPO_ROOT)
                self.assertEqual((block.returncode, line_code), (code, code))
                self.assertEqual(block.stdout.splitlines()[-1], "🚦 Gate: " + lines[1].replace(" gate: ", " ", 1))
                self.assertEqual(len(block.stdout.splitlines()), 7)

    def test_value_column_changes_neither_score_nor_gate(self):
        for value, verdict, code in (
            ("1:20", "✅ 90/5, cost and time <= 100, security 100 %", 0),
            ("4.1:1", "✅ 90/5, cost and time <= 100, security 100 %", 0),
            ("?", "⚠️ cost 120 % > 100" + ASK, 3),
        ):
            with self.subTest(value=value):
                efficiency = "97" if code == 0 else "120"
                result = self._run(
                    *flags({**BASE, "efficiency": efficiency, "speed": "-"}), "--table", "--value", value, cwd=REPO_ROOT
                )
                score = "96" if code == 0 else "78"
                self.assertEqual(
                    result.stdout.splitlines(),
                    [
                        HEADER.replace("💸 Cost |", "💸 Cost | 💰 Value |"),
                        "|" + " --- |" * 8,
                        f"| 95 % | 2 % | {efficiency} % | {value} | – | 100 % | {score} | {verdict} |",
                    ],
                )
                self.assertEqual(result.returncode, code)

    def test_commit_table(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        repo = Path(tmp.name) / "repo"
        repo.mkdir()
        env = {
            "PATH": os.path.dirname(shutil.which("git")),
            "HOME": tmp.name,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.org",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.org",
        }

        def git(*args: str) -> str:
            return subprocess.run(
                ["git", *args], cwd=repo, env=env, capture_output=True, text=True, check=True
            ).stdout.strip()

        git("init", "-q", "-b", "main")
        (repo / "a.txt").write_text("one\n", encoding="utf-8")
        git("add", "a.txt")
        git("commit", "-qm", "base")
        (repo / "a.txt").write_text("two\n", encoding="utf-8")
        (repo / "b.txt").write_text("three\nfour\n", encoding="utf-8")
        git("add", "a.txt", "b.txt")
        head = ["🌿 Branch", "📊 Diff stat"]
        score = "| 95 % | 2 % | 100 % | 100 % | 100 % | 93 | ✅ 90/5, cost and time <= 100, security 100 % |"
        worktree = ["", "📁 Worktree:", "", "```text", str(repo.resolve()), "```"]

        result = self._run(*flags(BASE), "--commit-table", str(repo), cwd=repo)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "| " + " | ".join(head) + " " + HEADER,
                "|" + " --- |" * 9,
                "| main | 2 files +3/-1 " + score,
                *worktree,
            ],
        )
        git("commit", "-qm", "change")
        sha = git("rev-parse", "--short", "HEAD")
        result = self._run(*flags(BASE), "--commit-table", str(repo), "--commit", "HEAD", cwd=repo)
        self.assertEqual(result.stdout.splitlines()[0], "| " + " | ".join([*head, "🔖 Commit"]) + " " + HEADER)
        self.assertEqual(result.stdout.splitlines()[2], f"| main | 2 files +3/-1 | {sha} " + score)
        self.assertEqual(result.stdout.splitlines()[3:], worktree)
        result = self._run(*flags(BASE), "--commit-table", str(repo), "--commit", "HEAD", "--value", "?", cwd=repo)
        self.assertEqual(
            result.stdout.splitlines()[0],
            "| " + " | ".join([*head, "🔖 Commit"]) + " " + HEADER.replace("💸 Cost |", "💸 Cost | 💰 Value |"),
        )
        self.assertEqual(
            result.stdout.splitlines()[2],
            f"| main | 2 files +3/-1 | {sha} " + score.replace("| 100 % |", "| 100 % | ? |", 1),
        )
        git("checkout", "-q", "--detach", "HEAD")
        result = self._run(*flags(BASE), "--commit-table", str(repo), cwd=repo)
        self.assertEqual(result.stdout.splitlines()[2], f"| detached at {sha} | 0 files +0/-0 " + score)
        self.assertEqual(self._run(*flags(BASE), "--commit-table", tmp.name, cwd=repo).returncode, 2)

    def test_usage_errors_exit_2(self):
        bad = (
            ("fix", "101"), ("fix", "-1"), ("fix", "nan"), ("break", "x"), ("break", "-"),
            ("efficiency", "0"), ("efficiency", "-5"), ("efficiency", "abc"), ("speed", "inf"),
            ("security", "101"), ("security", "~"), ("security", "~x"), ("security", "-"),
            ("critical", "-1"), ("critical", "a"), ("critical", "1.5"),
        )
        for key, value in bad:
            with self.subTest(flag=key, value=value):
                result = self._run(*flags({**BASE, key: value}), cwd=REPO_ROOT)
                self.assertEqual((result.returncode, result.stdout), (2, ""))
        for missing in ("security", "critical"):
            with self.subTest(missing=missing):
                values = {k: v for k, v in BASE.items() if k != missing}
                self.assertEqual(self._run(*flags(values), cwd=REPO_ROOT).returncode, 2)
        for extra in (
            ("--commit", "HEAD"),
            ("--table", "--commit-table", str(REPO_ROOT)),
            ("--message-block", "--table"),
            ("--message-block", "--commit-table", str(REPO_ROOT)),
            ("--value", "1:20"),
            ("--table", "--value", "1-20"),
            ("--table", "--value", "?:?"),
            ("--table", "--value", "a:b"),
            ("--table", "--value", ""),
        ):
            with self.subTest(extra=extra):
                self.assertEqual(self._run(*flags(BASE), *extra, cwd=REPO_ROOT).returncode, 2)


if __name__ == "__main__":
    unittest.main()
