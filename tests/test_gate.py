"""Exercise gate.py: static `make test*` listing, runs judged per target, and the per-HEAD gate."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "skills" / "kvb-check-gate" / "scripts" / "gate.py"
GREEN = {
    "Makefile": (
        "include mk/*.mk\n"
        "-include absent.mk\n"
        "include $(EXTRA_MK)\n"
        ".PHONY: test build\n"
        "VERSION := 1:2\n"
        "test: test-green\n"
        "\t@echo all green\n"
        "build:\n"
        "\t@echo build\n"
        "test-%:\n"
        "\t@echo pattern $@\n"
        "define BLOCK\n"
        "test-in-define:\n"
        "\t@echo never\n"
        "endef\n"
    ),
    "mk/green.mk": (
        "test-green:\n"
        "\t@echo green\n"
        "test-green: FOO = bar\n"
        "test-only-var: FOO = bar\n"
    ),
    "tracked.txt": "one\n",
}
RED = {
    "Makefile": (
        ".PHONY: test test-red test-quiet test-swallow test-dirty\n"
        "test:\n"
        "\t@echo fine\n"
        "test-red:\n"
        "\t@echo boom\n"
        "\t@exit 1\n"
        "test-quiet:\n"
        '\t@echo "FAILED TARGETS: test-x"\n'
        "test-swallow:\n"
        "\t-@$(MAKE) --no-print-directory test-red\n"
        "test-dirty:\n"
        "\t@echo changed >> tracked.txt\n"
    ),
    "tracked.txt": "one\n",
}
USAGE = {"Makefile": "test:\n\t@true\nbuild:\n\t@true\n"}
FAILED = ("--fail-regex", r"FAILED TARGETS: \S")


class GateCase(unittest.TestCase):
    files: ClassVar[dict[str, str]]

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.repo = self.root / "repo"
        self.logs = self.root / "logs"
        self.repo.mkdir()
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
        for name, text in self.files.items():
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        self._git("add", ".")
        self._git("commit", "-q", "-m", "init")

    def _git(self, *args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=self.repo, env=self.env, capture_output=True, text=True, check=True
        ).stdout

    def gate(self, *argv: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *argv], env=self.env, capture_output=True, text=True, check=False
        )

    def run_targets(self, *targets: str, extra: tuple[str, ...]) -> subprocess.CompletedProcess:
        flags = [part for target in targets for part in ("--target", target)]
        return self.gate("run", "--repo", str(self.repo), *flags, "--log-dir", str(self.logs), *extra)

    def status(self, repo: Path) -> tuple[int, dict]:
        result = self.gate("status", "--repo", str(repo), "--json")
        self.assertIn(result.returncode, (0, 1), result.stderr)
        return result.returncode, json.loads(result.stdout)

    def last_status_line(self) -> str:
        return self.gate("status", "--repo", str(self.repo)).stdout.splitlines()[-1]


class TestGreenPath(GateCase):
    files = GREEN

    def test_list_reads_includes_and_skips_non_test_names(self):
        result = self.gate("list", "--repo", str(self.repo), "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout),
            [{"target": "test", "defined": "Makefile:6"}, {"target": "test-green", "defined": "mk/green.mk:1"}],
        )
        self.assertIn("include $(EXTRA_MK) not resolved", result.stderr)
        self.assertNotIn("absent.mk", result.stderr)

    def test_gate_turns_green_and_a_new_commit_reopens_it(self):
        code, before = self.status(self.repo)
        self.assertEqual((code, before["gate"], before["open"]), (1, "open", ["missing: test, test-green"]))
        self.assertEqual(self.last_status_line(), "gate: open (missing: test, test-green)")

        result = self.run_targets("test", "test-green", extra=())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        log = self.logs / f"gate-test-{self._git('rev-parse', 'HEAD')[:8]}.log"
        self.assertEqual(result.stdout.splitlines()[0], f"green\ttest\t{log}\t-")
        self.assertIn("all green", log.read_text(encoding="utf-8"))

        code, after = self.status(self.repo)
        self.assertEqual((code, after["gate"]), (0, "green"))
        self.assertEqual({r["target"]: r["status"] for r in after["targets"]}, {"test": "green", "test-green": "green"})
        self.assertEqual(self.last_status_line(), "gate: green")

        self._git("commit", "-q", "--allow-empty", "-m", "next")
        code, reopened = self.status(self.repo)
        self.assertEqual((code, reopened["open"]), (1, ["missing: test, test-green"]))

    def test_results_are_shared_by_linked_worktrees(self):
        self.assertEqual(self.run_targets("test", "test-green", extra=()).returncode, 0)
        worktree = self.root / "wt"
        self._git("worktree", "add", "-q", "--detach", str(worktree))
        self.assertEqual(self.status(worktree)[0], 0)

    def test_dirty_tracked_file_blocks_run_untracked_is_reported(self):
        (self.repo / "scratch.txt").write_text("x\n", encoding="utf-8")
        result = self.run_targets("test-green", extra=())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("untracked\t1 file(s), not part of the gate", result.stdout)

        (self.repo / "tracked.txt").write_text("two\n", encoding="utf-8")
        result = self.run_targets("test", extra=())
        self.assertEqual(result.returncode, 2)
        self.assertIn("tracked files are dirty", result.stderr)
        self.assertIn("tracked.txt", result.stderr)
        code, status = self.status(self.repo)
        self.assertEqual((code, status["open"]), (1, ["missing: test", "dirty: 1 tracked file(s)"]))


class TestRedPath(GateCase):
    files = RED

    def results(self) -> dict[str, dict]:
        return {r["target"]: r for r in self.status(self.repo)[1]["targets"]}

    def test_exit_code_fail_regex_and_swallowed_make_error_are_red(self):
        result = self.run_targets("test", "test-red", "test-quiet", "test-swallow", extra=FAILED)
        self.assertEqual(result.returncode, 1, result.stderr)
        rows = self.results()
        self.assertEqual(rows["test"]["status"], "green")
        self.assertEqual(rows["test-red"]["status"], "red")
        self.assertRegex(rows["test-red"]["reason"], r"^exit 2; make: \*\*\* \[Makefile:\d+: test-red\] Error 1$")
        self.assertEqual(rows["test-quiet"]["status"], "red")
        self.assertEqual(rows["test-quiet"]["reason"], "FAILED TARGETS: test-x")
        self.assertEqual(rows["test-quiet"]["fail_regex"], [FAILED[1]])
        self.assertEqual(rows["test-swallow"]["status"], "red")
        self.assertRegex(rows["test-swallow"]["reason"], r"^make\[1\]: \*\*\* ")
        self.assertEqual(rows["test-dirty"]["status"], "missing")
        self.assertEqual(
            self.last_status_line(), "gate: open (missing: test-dirty; red: test-quiet, test-red, test-swallow)"
        )

    def test_a_fail_pattern_without_its_regex_stays_green(self):
        self.assertEqual(self.run_targets("test-quiet", extra=()).returncode, 0)
        self.assertEqual(self.results()["test-quiet"]["status"], "green")

    def test_a_target_that_modifies_tracked_files_is_red_and_stops_the_run(self):
        result = self.run_targets("test-dirty", "test", extra=())
        self.assertEqual(result.returncode, 2)
        self.assertIn("test-dirty left tracked files dirty", result.stderr)
        rows = self.results()
        self.assertEqual(rows["test-dirty"]["reason"], "modified tracked files: tracked.txt")
        self.assertEqual(rows["test"]["status"], "missing")


class TestUsage(GateCase):
    files = USAGE

    def test_usage_errors_exit_2(self):
        bare = self.root / "bare"
        bare.mkdir()
        cases = {
            "no command": self.gate(),
            "run without log dir": self.gate("run", "--repo", str(self.repo), "--target", "test"),
            "run without target": self.gate("run", "--repo", str(self.repo), "--log-dir", str(self.logs)),
            "non-test target": self.run_targets("build", extra=()),
            "unknown target": self.run_targets("test-nope", extra=()),
            "bad regex": self.run_targets("test", extra=("--fail-regex", "(")),
            "no Makefile": self.gate("list", "--repo", str(bare)),
            "missing repo": self.gate("status", "--repo", str(self.root / "absent")),
        }
        (bare / "Makefile").write_text("test:\n\t@true\n", encoding="utf-8")
        cases["not a git repository"] = self.gate("status", "--repo", str(bare))
        for name, result in cases.items():
            with self.subTest(case=name):
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertFalse(self.logs.exists())


if __name__ == "__main__":
    unittest.main()
