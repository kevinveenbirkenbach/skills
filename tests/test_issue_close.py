"""Exercise issues.py (one pull request's issues) and done.py (open issues the default branch references)."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "skills" / "kvb-git-issue-close" / "scripts" / "issues.py"
DONE = SCRIPT.with_name("done.py")
PR = {
    "number": 40,
    "body": (
        "Fixes #12 and touches #13.\nCloses: other/repo#7\nSee https://github.com/a/b/issues/9\n"
        "Rows WordPress#0 and docs#1 are not issues; this is #40."
    ),
    "headRefName": "fix/sys-ctl-hlth-runtime/vulnerability-engines/1324",
    "commits": [
        {"oid": "abcdef1234567", "messageHeadline": "fix: guard", "messageBody": "Resolved #13"},
        {"oid": "1111111111111", "messageHeadline": "chore: tidy", "messageBody": ""},
    ],
    "closingIssuesReferences": [
        {"number": 21, "url": "https://github.com/owner/repo/issues/21"}
    ],
}


def _run(payload: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", "Owner/repo", "--json"],
        input=payload,
        check=False,
        capture_output=True,
        text=True,
    )


class TestIssues(unittest.TestCase):
    def test_every_reference_is_found_with_its_kind_and_source(self):
        result = _run(json.dumps(PR))
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = {(r["repo"], r["issue"]): r for r in json.loads(result.stdout)}
        self.assertEqual(
            {key: (row["closing"], row["sources"]) for key, row in rows.items()},
            {
                ("", 12): (True, ["body"]),
                ("", 13): (True, ["body", "commit abcdef1234"]),
                ("other/repo", 7): (True, ["body"]),
                ("a/b", 9): (False, ["body"]),
                ("", 1324): (False, ["branch"]),
                ("", 21): (True, ["linked"]),
            },
        )

    def test_invalid_input_exits_2(self):
        self.assertEqual(_run("not json").returncode, 2)
        self.assertEqual(_run("[]").returncode, 2)


class TestDone(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name)
        self.env = {
            "PATH": "/usr/bin:/bin",
            "HOME": tmp.name,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.org",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.org",
        }
        self._git("init", "-q", "-b", "main")
        for message in (
            "fix: guard\n\nFixes #3",
            "docs: mention #4 and other/repo#6",
            "fix: port\n\nCloses Owner/repo#5",
            "chore: tidy #3",
        ):
            self._git("commit", "-q", "--allow-empty", "-m", message)
        self.shas = self._git("log", "--format=%H", "main").split()

    def _git(self, *args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=self.repo, env=self.env, capture_output=True, text=True, check=True
        ).stdout

    def _run(self, payload: str, ref: str = "main") -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(DONE), "--repo", "owner/Repo", "--git-dir", str(self.repo), "--ref", ref, "--json"],
            input=payload,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_open_issues_with_their_commits(self):
        result = self._run(json.dumps([{"number": n} for n in (3, 4, 5, 6, 7)]))
        self.assertEqual(result.returncode, 0, result.stderr)
        newest, closes5, mentions4, fixes3 = (sha[:10] for sha in self.shas)
        self.assertEqual(
            json.loads(result.stdout),
            [
                {"issue": 3, "closing": True, "commits": [newest, fixes3]},
                {"issue": 4, "closing": False, "commits": [mentions4]},
                {"issue": 5, "closing": True, "commits": [closes5]},
            ],
        )

    def test_bad_input_or_ref_exits_2(self):
        self.assertEqual(self._run("not json").returncode, 2)
        self.assertEqual(self._run('[{"id": 1}]').returncode, 2)
        self.assertEqual(self._run("[]", ref="nope").returncode, 2)


if __name__ == "__main__":
    unittest.main()
