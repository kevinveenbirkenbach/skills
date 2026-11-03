"""Exercise stage_hunks.py: matching added lines, whole changed hunks, the rest stays unstaged."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "skills" / "kvb-git-commit-next" / "scripts" / "stage_hunks.py"


@unittest.skipUnless(shutil.which("git"), "git not installed")
class TestStageHunks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        self.env = {
            "PATH": "/usr/bin:/bin",
            "HOME": str(self.repo),
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
        }
        self.file = self.repo / "notes.txt"
        self.file.write_text("one\ntwo\nthree\nfour\nfive\n", encoding="utf-8")
        self._git("init", "-q")
        self._git("add", "notes.txt")
        self._git("commit", "-q", "-m", "base")
        self.file.write_text(
            "one\nalpha one\nbeta one\ntwo\nthree\nfour alpha\nfive\nbeta two\n", encoding="utf-8"
        )

    def _git(self, *args: str) -> str:
        return subprocess.run(
            ["git", *args], check=True, capture_output=True, text=True, env=self.env, cwd=self.repo
        ).stdout

    def _run(self, pattern: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--repo", str(self.repo), "--file", "notes.txt", "--match", pattern],
            check=False, capture_output=True, text=True, env=self.env,
        )

    def test_only_matching_changes_are_staged(self):
        result = self._run("alpha")
        self.assertEqual(result.returncode, 0, result.stderr)
        staged = [line for line in self._git("diff", "--cached", "-U0").splitlines() if line[:1] in "+-" and line[:3] not in ("+++", "---")]
        self.assertEqual(staged, ["+alpha one", "-four", "+four alpha"])
        unstaged = [line for line in self._git("diff", "-U0").splitlines() if line.startswith("+") and not line.startswith("+++")]
        self.assertEqual(unstaged, ["+beta one", "+beta two"])

    def test_no_match_exits_1_and_bad_pattern_exits_2(self):
        self.assertEqual(self._run("gamma").returncode, 1)
        self.assertEqual(self._run("(").returncode, 2)
        self.assertEqual(self._git("diff", "--cached"), "")


if __name__ == "__main__":
    unittest.main()
