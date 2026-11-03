"""Exercise branches.py: lag behind the base, ownership by commits and by PR author, forks."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "skills" / "kvb-git-update-branches" / "scripts" / "branches.py"
ME = "me@example.org"


@unittest.skipUnless(shutil.which("git"), "git not installed")
class TestBranches(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.env = {"PATH": "/usr/bin:/bin", "HOME": str(base)}
        self.origin = base / "origin.git"
        self.clone = base / "clone"
        self._git(base, "init", "-q", "--bare", "-b", "main", str(self.origin))
        self._git(base, "clone", "-q", str(self.origin), str(self.clone))
        self._commit(ME, "base")
        self._git(self.clone, "branch", "-M", "main")
        self._git(self.clone, "push", "-q", "origin", "main")
        for branch, email in (("feat/mine", ME), ("feat/theirs", "other@example.org"), ("feat/pr-mine", "other@example.org")):
            self._git(self.clone, "switch", "-q", "-c", branch, "main")
            self._commit(email, branch)
            self._git(self.clone, "push", "-q", "origin", branch)
        self._git(self.clone, "switch", "-q", "-c", "feat/merged", "main")
        self._git(self.clone, "push", "-q", "origin", "feat/merged")
        self._git(self.clone, "switch", "-q", "main")
        self._commit(ME, "main moves on")
        self._commit(ME, "and again")
        self._git(self.clone, "push", "-q", "origin", "main")
        self._git(self.clone, "fetch", "-q", "--prune")
        self.prs = base / "prs.json"
        self.prs.write_text(
            json.dumps(
                [
                    {"number": 5, "headRefName": "feat/pr-mine", "author": {"login": "me"}, "isCrossRepository": False},
                    {"number": 6, "headRefName": "fix", "author": {"login": "stranger"}, "isCrossRepository": True},
                ]
            ),
            encoding="utf-8",
        )

    def _git(self, cwd: Path, *args: str) -> None:
        subprocess.run(["git", *args], check=True, capture_output=True, env=self.env, cwd=cwd)

    def _commit(self, email: str, message: str) -> None:
        env = {**self.env, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": email, "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": email}
        subprocess.run(
            ["git", "commit", "-q", "--allow-empty", "-m", message],
            check=True, capture_output=True, env=env, cwd=self.clone,
        )

    def _run(self, *extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--repo", str(self.clone), "--remote", "origin", "--base", "main",
             "--email", ME, "--login", "me", *extra],
            check=False, capture_output=True, text=True, env=self.env,
        )

    def test_open_branches_carry_lag_and_owner(self):
        result = self._run("--prs", str(self.prs), "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = {row["branch"]: row for row in json.loads(result.stdout)}
        self.assertEqual(set(rows), {"feat/mine", "feat/theirs", "feat/pr-mine", "fix"})
        self.assertEqual((rows["feat/mine"]["behind"], rows["feat/mine"]["mine"]), (2, True))
        self.assertEqual((rows["feat/theirs"]["mine"], rows["feat/theirs"]["pr"]), (False, None))
        self.assertEqual((rows["feat/pr-mine"]["pr"], rows["feat/pr-mine"]["mine"]), (5, True))
        self.assertEqual((rows["fix"]["mine"], rows["fix"].get("fork")), (False, True))

    def test_invalid_input_exits_2(self):
        self.assertEqual(self._run("--prs", str(self.tmp.name) + "/missing.json").returncode, 2)
        broken = subprocess.run(
            [sys.executable, str(SCRIPT), "--repo", str(self.clone), "--remote", "origin", "--base", "nope",
             "--email", ME, "--login", "me"],
            check=False, capture_output=True, text=True, env=self.env,
        )
        self.assertEqual(broken.returncode, 2)


if __name__ == "__main__":
    unittest.main()
