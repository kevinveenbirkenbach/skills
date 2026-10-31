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
CI_FAILURES = REPO_ROOT / "skills" / "ci-artifacts" / "scripts" / "ci_failures.py"
FIND_FIX = REPO_ROOT / "skills" / "merge-fix" / "scripts" / "find_fix.py"


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
            "  --> skills/democracy/scripts/council.py:92:40\n"
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

    def _git(self, *args: str) -> str:
        return subprocess.run(
            ["git", *args], check=True, capture_output=True, text=True, env=self.env, cwd=self.repo
        ).stdout

    def _find_fix(self, *args: str) -> list[str]:
        result = subprocess.run(
            [sys.executable, str(FIND_FIX), *args],
            capture_output=True,
            text=True,
            check=True,
            env=self.env,
            cwd=self.repo,
        )
        return result.stdout.splitlines()

    def _commit_on_side(self, name: str, text: str, message: str) -> None:
        self._git("switch", "-q", "side")
        (self.repo / name).write_text(text)
        self._git("add", name)
        self._git("commit", "-q", "-m", message)
        self._git("switch", "-q", "main")

    def test_only_commits_outside_head_are_candidates(self):
        lines = self._find_fix("--grep", "probe")
        self.assertEqual(lines[0], "hits=2 in_head=1 candidates=1")
        self.assertIn("fix: probe on side", "\n".join(lines))
        self.assertNotIn("probe in head", "\n".join(lines))

    def test_pickaxe_lists_what_git_log_all_finds_in_its_order(self):
        for step in range(12):
            self._commit_on_side("probe.txt", "needle\n" * (step % 3), f"step {step}")
        expected = self._git("log", "--all", "--format=%h %s", "-Sneedle").splitlines()
        lines = self._find_fix("-S", "needle")
        self.assertEqual(lines[0], f"hits={len(expected)} in_head=0 candidates={len(expected)}")
        self.assertEqual([line.split("\t")[0] for line in lines[1:]], expected)

    def test_filters_are_alternatives_not_narrowing(self):
        self._commit_on_side("other.txt", "x\n", "chore: unrelated")
        lines = self._find_fix("--grep", "probe", "--path", "other.txt")
        self.assertEqual(lines[0], "hits=3 in_head=1 candidates=2")


if __name__ == "__main__":
    unittest.main()
