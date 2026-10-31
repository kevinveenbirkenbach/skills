"""Exercise ci_failures clustering and find_fix's ref search."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CI_FAILURES = REPO_ROOT / "skills" / "kvb-ci-artifacts" / "scripts" / "ci_failures.py"
FIND_FIX = REPO_ROOT / "skills" / "kvb-git-merge-fix" / "scripts" / "find_fix.py"


def _load(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestCiFailures(unittest.TestCase):
    def setUp(self):
        self.ci = _load(CI_FAILURES)

    def test_jobs_differing_only_in_identifiers_share_a_cluster(self):
        one = "2026-10-30T10:00:00.1Z setup ok\n##[error]Timeout on host 10.0.0.12 after 300s\n"
        two = "\x1b[31m2026-10-30T11:00:00.1Z ##[error]Timeout on host 10.0.0.47 after 299s\x1b[0m\n"
        other = "PLAY RECAP failed=0\nfatal: unable to reach registry\n"
        groups = self.ci.cluster([("a", one), ("b", two), ("c", other)])
        self.assertEqual(list(groups.values()), [["a", "b"], ["c"]])

    def test_command_echo_and_retries_are_skipped_and_task_named(self):
        text = (
            '##[group]Run make deploy || echo "failed"\n'
            "make deploy\n"
            "##[endgroup]\n"
            "FAILED - RETRYING: wait (3 retries left)\n"
            "TASK [web-app-y : Probe] ****\n"
            "Traceback (most recent call last): recovered on retry\n"
            "TASK [web-app-x : Wait for health] ****\n"
            'fatal: [localhost]: FAILED! => {"msg": "timeout 120"}\n'
            "##[error]Process completed with exit code 2.\n"
        )
        self.assertEqual(
            self.ci.signature(text),
            'TASK [web-app-x : Wait for health] **** fatal: [localhost]: FAILED! => {"msg": "timeout <n>"}',
        )

    def test_lint_finding_beats_make_error_and_later_steps(self):
        text = (
            "Ran 41 tests in 1.0s\n"
            "OK\n"
            "UP017 [*] Use `datetime.UTC` alias\n"
            "  --> skills/kvb-org-organize/scripts/council.py:92:40\n"
            "Found 1 error.\n"
            "make: *** [Makefile:15: test] Error 1\n"
            "##[error]Process completed with exit code 2.\n"
            "Post job cleanup.\n"
            "SHA256 digest of uploaded artifact is 0123456789abcdef\n"
        )
        self.assertEqual(self.ci.signature(text), "UP<n> [*] Use `datetime.UTC` alias")

    def test_generic_exit_code_line_is_not_the_signature(self):
        text = "Error: disk full\n##[error]Process completed with exit code 1.\n"
        self.assertEqual(self.ci.signature(text), "Error: disk full")


@unittest.skipUnless(shutil.which("git"), "git not installed")
class TestFindFix(unittest.TestCase):
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
        self._git("init", "-q", "-b", "main")
        self._git("commit", "-q", "--allow-empty", "-m", "fix: probe in head")
        self._git("switch", "-q", "-c", "side")
        self._git("commit", "-q", "--allow-empty", "-m", "fix: probe on side")
        self._git("switch", "-q", "main")

    def _git(self, *args: str) -> None:
        subprocess.run(["git", *args], check=True, capture_output=True, env=self.env, cwd=self.repo)

    def test_only_commits_outside_head_are_candidates(self):
        result = subprocess.run(
            [sys.executable, str(FIND_FIX), "--grep", "probe"],
            capture_output=True,
            text=True,
            check=True,
            env=self.env,
            cwd=self.repo,
        )
        self.assertIn("hits=2 in_head=1 candidates=1", result.stdout)
        self.assertIn("fix: probe on side", result.stdout)
        self.assertNotIn("probe in head", result.stdout)


if __name__ == "__main__":
    unittest.main()
