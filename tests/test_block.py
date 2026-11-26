"""Requirement 063: block.py builds the commit table and message block from one run of every scoring script."""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from score_fixture import git_env

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS = REPO_ROOT / "skills"
ORGANIZE = SKILLS / "kvb-org-organize" / "scripts"
FAKES = {
    "tokens": "kvb-check-efficiency",
    "measure": "kvb-check-efficiency",
    "security": "kvb-check-security",
    "gate": "kvb-check-gate",
}
FAKE = """import os, pathlib, sys
stem = pathlib.Path(sys.argv[0]).stem.upper()
with open(os.environ["FAKE_LOG"], "a", encoding="utf-8") as log:
    log.write(stem + " " + " ".join(sys.argv[1:]) + "\\n")
sys.stdout.write(os.environ.get("FAKE_" + stem, ""))
sys.stderr.write(os.environ.get("FAKE_" + stem + "_ERR", ""))
sys.exit(int(os.environ.get("FAKE_" + stem + "_CODE", "0")))
"""
OUTPUTS = {
    "TOKENS": "💸 tokens 98 % (skills 100→98 tokens; listing 10→10 words)\n💰 value ?:? (cost 1/day; pass --value with evidence)\n",
    "MEASURE": "💸 tokens 104 % (cpu 1→1.04 s, ram 10→10 MB) · ⏱️ velocity 97 % (wall 2→1.94 s)\n",
    "MEASURE_CODE": "3",
    "SECURITY": "🛡️ security 100 % critical 0 (medusa: 0 findings in 2 files)\n",
    "GATE": "green\ttest\t/tmp/gate-test.log\t2026-11-25T10:00\t-\ngate: green\n",
}
FIGURES = ["--fix", "95", "--break", "2"]
SKILL_NAME = re.compile(r"kvb-[a-z-]+[a-z]")
CHAIN = {"kvb-check-score", "kvb-check-efficiency", "kvb-check-security", "kvb-check-gate", "kvb-check-speed"}


class BlockCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        skills = self.tmp / "skills"
        shutil.copytree(SKILLS / "kvb-check-score", skills / "kvb-check-score",
                        ignore=shutil.ignore_patterns("__pycache__"))
        (skills / "kvb-org-organize" / "scripts").mkdir(parents=True)
        for name in ("nofollow.py", "councilroot.py"):
            shutil.copy(ORGANIZE / name, skills / "kvb-org-organize" / "scripts" / name)
        for stem, skill in FAKES.items():
            (skills / skill / "scripts").mkdir(parents=True, exist_ok=True)
            (skills / skill / "scripts" / f"{stem}.py").write_text(FAKE, encoding="utf-8")
        self.block = skills / "kvb-check-score" / "scripts" / "block.py"
        self.score = skills / "kvb-check-score" / "scripts" / "score.py"
        self.log = self.tmp / "calls.log"
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        env = git_env(self.tmp)
        for args in (("init", "-q", "-b", "feature/block"), ("commit", "-q", "--allow-empty", "-m", "base")):
            subprocess.run(["git", *args], cwd=self.repo, env=env, capture_output=True, check=True)
        (self.repo / "a.py").write_text("x = 1\n", encoding="utf-8")
        subprocess.run(["git", "add", "a.py"], cwd=self.repo, env=env, capture_output=True, check=True)
        self.env = {"PATH": os.environ["PATH"], "HOME": str(self.tmp), "AGENTS_COUNCIL_ROOT": str(self.tmp / "council"),
                    "FAKE_LOG": str(self.log), **{f"FAKE_{key}": value for key, value in OUTPUTS.items()}}

    def run_block(self, *args: str, **outputs: str) -> subprocess.CompletedProcess:
        env = {**self.env, **{f"FAKE_{key}": value for key, value in outputs.items()}}
        return subprocess.run([sys.executable, "-B", str(self.block), "--repo", str(self.repo), "--base", "HEAD", *args],
                              cwd=self.repo, env=env, capture_output=True, text=True, check=False)

    def run_score(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-B", str(self.score), *args], cwd=self.repo, env=self.env,
                              capture_output=True, text=True, check=False)

    def calls(self) -> list[str]:
        return self.log.read_text(encoding="utf-8").splitlines() if self.log.exists() else []


class TestGolden(BlockCase):
    def test_block_prints_what_the_single_scripts_print(self):
        done = self.run_block(*FIGURES, "--transcripts", "/t", "--", "true")
        values = [*FIGURES, "--efficiency", "104", "--speed", "97", "--security", "100", "--critical", "0", "--value", "?"]
        table = self.run_score(*values, "--commit-table", str(self.repo))
        block = self.run_score(*values, "--message-block")
        after = shlex.join(["python3", str(self.score.resolve()), *values, "--commit-table", str(self.repo)])
        self.assertEqual(done.stdout, f"{table.stdout}\ngate: green\n\n{block.stdout}\nafter the commit: {after} --commit <hash>\n")
        self.assertEqual((done.returncode, table.returncode, block.returncode), (3, 3, 3))

    def test_every_script_gets_the_tree_and_the_base(self):
        self.run_block(*FIGURES, "--transcripts", "/t", "--saves", "500", "--evidence", "e", "--", "make", "test")
        self.assertEqual(self.calls(), [
            f"TOKENS --repo {self.repo} --base HEAD --transcripts /t --value 500 --evidence e",
            "MEASURE --base HEAD -- make test",
            f"SECURITY --repo {self.repo} --base HEAD",
            f"GATE status --repo {self.repo}",
        ])

    def test_a_new_skill_and_a_priced_value_reach_the_block(self):
        done = self.run_block(*FIGURES, "--transcripts", "/t",
                              TOKENS="💸 tokens new (+40 tokens; listing 10→12 words)\n💰 value 1:20 (cost 1/day, value 20/day; e)\n")
        self.assertIn("💸 Tokens: new\n⏱️ Velocity: –\n", done.stdout)
        self.assertIn("💰 Value: 1:20\n", done.stdout)
        self.assertEqual(done.returncode, 3)


class TestExitCodes(BlockCase):
    def test_exit_codes_are_score_py_s(self):
        cases = {
            "pass": ((), {}, 0),
            "below 90/5": (("--fix", "80"), {}, 1),
            "ask again": (("--", "true"), {}, 3),
            "critical": ((), {"SECURITY": "🛡️ security 50 % critical 1 (medusa: 1 finding)\n", "SECURITY_CODE": "1"}, 4),
        }
        for name, (extra, outputs, code) in cases.items():
            with self.subTest(name):
                done = self.run_block(*FIGURES, *extra, **outputs)
                self.assertEqual(done.returncode, code, done.stderr)


class TestFailures(BlockCase):
    def test_a_failing_script_is_named_and_nothing_is_printed(self):
        cases = {
            "security.py exited 4: 🛡️ security – (not covered: a.py: review by hand)": {
                "SECURITY": "🛡️ security – (not covered: a.py: review by hand)\n", "SECURITY_CODE": "4"},
            "gate.py exited 2: gate: kvb-gate.json cannot be trusted": {
                "GATE_ERR": "gate: kvb-gate.json cannot be trusted\n", "GATE_CODE": "2"},
            "tokens.py printed no figure: nothing changed": {"TOKENS": "nothing changed\n"},
            "measure.py exited 2: base: make exited 2": {"MEASURE_ERR": "base: make exited 2\n", "MEASURE_CODE": "2"},
        }
        for message, outputs in cases.items():
            with self.subTest(message):
                done = self.run_block(*FIGURES, "--transcripts", "/t", "--", "make", **outputs)
                self.assertEqual((done.returncode, done.stdout, done.stderr), (2, "", f"block: {message}\n"))

    def test_saves_without_evidence_is_a_usage_error_before_any_script(self):
        done = self.run_block(*FIGURES, "--transcripts", "/t", "--saves", "500")
        self.assertEqual(done.returncode, 2)
        self.assertIn("--saves needs --evidence and --transcripts", done.stderr)
        self.assertEqual(self.calls(), [])

    def test_an_out_of_range_fix_is_a_usage_error_before_any_script(self):
        done = self.run_block("--fix", "120", "--break", "2")
        self.assertEqual(done.returncode, 2)
        self.assertEqual(self.calls(), [])


class TestCommitPath(unittest.TestCase):
    def test_the_commit_skill_runs_block_py_and_loads_no_scoring_skill(self):
        text = (SKILLS / "kvb-git-commit-no-verify" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("kvb-check-score/scripts/block.py", text)
        loaded = set(SKILL_NAME.findall(re.sub(r"kvb-[a-z-]+/\S+", "", text)))
        self.assertEqual(loaded & CHAIN, set())
        self.assertLessEqual({"kvb-check-confidence", "kvb-check-break-risk"}, loaded)


if __name__ == "__main__":
    unittest.main()
