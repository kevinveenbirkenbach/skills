"""Exercise legacy.py: renames chained through history, deletions, project and unknown skills."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "skills" / "kvb-skill-cleanup" / "scripts" / "legacy.py"
REWORDED = """---
name: {name}
description: probe
---

The probe keeps this first line as it is.
{name}: the first renamed line.
{name}: the second renamed line.
{name}: the third renamed line.
It keeps this closing line as it is too.
"""


@unittest.skipUnless(shutil.which("git"), "git not installed")
class TestLegacy(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.env = {
            "PATH": "/usr/bin:/bin",
            "HOME": str(base),
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
        }
        self.repo = base / "skills-repo"
        self._skill(self.repo / "skills" / "old")
        (self.repo / "skills-lock.json").write_text(
            json.dumps({"skills": {"caveman": {}}}), encoding="utf-8"
        )
        self._git(self.repo, "init", "-q", "-b", "main")
        self._commit(self.repo, "add old")
        self._git(self.repo, "mv", "skills/old", "skills/mid")
        self._commit(self.repo, "rename old to mid")
        self._git(self.repo, "mv", "skills/mid", "skills/kvb-x-new")
        self._commit(self.repo, "rename mid to kvb-x-new")
        self._skill(self.repo / "skills" / "gone")
        self._commit(self.repo, "add gone")
        self._git(self.repo, "rm", "-q", "-r", "skills/gone")
        self._commit(self.repo, "remove gone")

        self.home = base / "home" / ".claude" / "skills"
        for name in ("old", "mid", "gone", "kvb-x-new", "caveman", "mine"):
            self._skill(self.home / name)
        (self.home / "notaskill").mkdir()

        self.project = base / "project"
        self._skill(self.project / "skills" / "p-own")
        self._git(self.project, "init", "-q", "-b", "main")
        self._commit(self.project, "own skill")
        self.installed = self.project / ".claude" / "skills"
        for name in ("p-own", "old"):
            self._skill(self.installed / name)

    def _skill(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        (path / "SKILL.md").write_text(
            f"---\nname: {path.name}\ndescription: probe\n---\n\nBody of the probe skill.\n",
            encoding="utf-8",
        )

    def _git(self, cwd: Path, *args: str) -> None:
        subprocess.run(["git", *args], check=True, capture_output=True, env=self.env, cwd=cwd)

    def _commit(self, cwd: Path, message: str) -> None:
        self._git(cwd, "add", "-A")
        self._git(cwd, "commit", "-q", "-m", message)

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            check=False,
            capture_output=True,
            text=True,
            env=self.env,
        )

    def test_every_installed_skill_gets_its_verdict(self):
        result = self._run(
            "--skills-repo", str(self.repo),
            "--root", str(self.home),
            "--root", str(self.installed),
            "--json",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        home, project = str(self.home), str(self.installed)
        rows = sorted(
            (str(Path(row["path"]).parent), Path(row["path"]).name, row["verdict"], row["successor"])
            for row in json.loads(result.stdout)
        )
        self.assertEqual(
            rows,
            sorted(
                [
                    (home, "caveman", "current", None),
                    (home, "gone", "removed", None),
                    (home, "kvb-x-new", "current", None),
                    (home, "mid", "legacy", "kvb-x-new"),
                    (home, "mine", "unknown", None),
                    (home, "old", "legacy", "kvb-x-new"),
                    (project, "old", "legacy", "kvb-x-new"),
                    (project, "p-own", "project", None),
                ]
            ),
        )

    def test_a_rename_that_rewrites_its_name_throughout_keeps_its_successor(self):
        (self.repo / "skills" / "night-old").mkdir()
        (self.repo / "skills" / "night-old" / "SKILL.md").write_text(REWORDED.format(name="night-old"), encoding="utf-8")
        self._commit(self.repo, "add night-old")
        self._git(self.repo, "mv", "skills/night-old", "skills/kvb-x-night")
        (self.repo / "skills" / "kvb-x-night" / "SKILL.md").write_text(REWORDED.format(name="kvb-x-night"), encoding="utf-8")
        self._commit(self.repo, "rename night-old to kvb-x-night")
        default = subprocess.run(
            ["git", "diff", "-M", "--diff-filter=R", "--name-only", "HEAD~1", "HEAD"],
            cwd=self.repo, env=self.env, capture_output=True, text=True, check=True,
        )
        self.assertEqual(default.stdout.strip(), "", "the probe must stay below git's default rename similarity")
        self._skill(self.home / "night-old")
        result = self._run("--skills-repo", str(self.repo), "--root", str(self.home), "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = {Path(row["path"]).name: (row["verdict"], row["successor"]) for row in json.loads(result.stdout)}
        self.assertEqual(rows["night-old"], ("legacy", "kvb-x-night"))

    def test_invalid_input_exits_2(self):
        missing = self._run("--skills-repo", str(self.repo), "--root", str(self.home / "nope"))
        self.assertEqual(missing.returncode, 2)
        no_repo = self._run("--skills-repo", str(self.home), "--root", str(self.home))
        self.assertEqual(no_repo.returncode, 2)


if __name__ == "__main__":
    unittest.main()
