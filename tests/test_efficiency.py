"""Exercise kvb-check-efficiency: tokens.py on skill text changes, measure.py on a command in a base worktree."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "skills" / "kvb-check-efficiency" / "scripts"
TOKENS = SCRIPTS / "tokens.py"
SPEC = importlib.util.spec_from_file_location("measure", SCRIPTS / "measure.py")
measure = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(measure)
BUDGET = REPO_ROOT / "scripts" / "budget.py"
SKILL_A = "---\nname: kvb-a\ndescription: >\n  one two three\n---\n"
SKILL_B = "---\nname: kvb-b\ndescription: >\n  four five\n---\n"
CHEAP = "print('cheap')\n"
COSTLY = "data = list(range(2_000_000))\nprint(sum(data))\n"
LINE = re.compile(
    r"^🌱 efficiency (?P<mark>~?)(?P<efficiency>\d+) % \(cpu \d+\.\d\d→\d+\.\d\d s, ram \d+\.\d→\d+\.\d MB\) · "
    r"⚡ speed (?P<speed_mark>~?)(?P<speed>\d+) % \((?P<basis>wall|cpu) \d+\.\d\d→\d+\.\d\d s\)(?P<tail>.*)$"
)


class GitRepo(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.repo = self.base / "repo"
        self.repo.mkdir()
        self.env = {
            "PATH": os.environ["PATH"],
            "HOME": str(self.base),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.org",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.org",
        }
        self.git("init", "-q", "-b", "main")

    def git(self, *args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=self.repo, env=self.env, capture_output=True, text=True, check=True
        ).stdout

    def write(self, path: str, text: str) -> None:
        file = self.repo / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text, encoding="utf-8")

    def commit(self) -> None:
        self.git("add", "-A")
        self.git("commit", "-qm", "base")

    def run_script(self, script: Path, *args: str, cwd: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(script), *args], cwd=cwd, env=self.env, capture_output=True, text=True, check=False
        )


class TestTokens(GitRepo):
    def setUp(self):
        super().setUp()
        self.write("scripts/budget.py", BUDGET.read_text(encoding="utf-8"))
        self.write("skills/kvb-a/SKILL.md", SKILL_A)
        self.write("skills/kvb-a/notes.md", "x" * 400)
        self.write("skills/kvb-a/scripts/tool.py", "print(1)\n")
        self.commit()

    def tokens(self, *extra: str) -> subprocess.CompletedProcess:
        return self.run_script(TOKENS, "--repo", str(self.repo), "--base", "HEAD", *extra, cwd=self.base)

    def test_shrunk_file_is_under_100(self):
        self.write("skills/kvb-a/notes.md", "x" * 200)
        self.write("skills/kvb-a/scripts/tool.py", "print(1)\n" * 50)
        result = self.tokens()
        self.assertEqual(result.stdout, "🌱 efficiency 50 % (skills 100→50 tokens; listing 3→3 words)\n")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_changed_and_new_skill_files_over_100(self):
        self.write("skills/kvb-a/notes.md", "x" * 600)
        self.write("skills/kvb-b/SKILL.md", SKILL_B.ljust(200, "y"))
        result = self.tokens()
        self.assertEqual(result.stdout, "🌱 efficiency 200 % (skills 100→200 tokens; listing 3→5 words)\n")
        self.assertEqual(result.returncode, 3)
        result = self.tokens("--json")
        self.assertEqual(result.returncode, 3)
        self.assertEqual(
            json.loads(result.stdout),
            {
                "efficiency": 200,
                "skills": {"before": 100, "after": 200},
                "listing": {"before": 3, "after": 5},
                "per_skill": {"kvb-a": {"before": 100, "after": 150}, "kvb-b": {"before": 0, "after": 50}},
            },
        )

    def test_only_new_files_print_new(self):
        self.write("skills/kvb-b/SKILL.md", SKILL_B.ljust(200, "y"))
        result = self.tokens()
        self.assertEqual(result.stdout, "🌱 efficiency new (+50 tokens; listing 3→5 words)\n")
        self.assertEqual(result.returncode, 3)
        self.assertIsNone(json.loads(self.tokens("--json").stdout)["efficiency"])

    def test_rename_counts_both_sides(self):
        self.git("mv", "skills/kvb-a/notes.md", "skills/kvb-a/moved.md")
        result = self.tokens()
        self.assertEqual(result.stdout, "🌱 efficiency 100 % (skills 100→100 tokens; listing 3→3 words)\n")
        self.assertEqual(result.returncode, 0)

    def test_no_change_is_100(self):
        result = self.tokens()
        self.assertEqual(result.stdout, "🌱 efficiency 100 % (skills 0→0 tokens; listing 3→3 words)\n")
        self.assertEqual(result.returncode, 0)

    def test_usage_errors_exit_2(self):
        self.assertEqual(self.run_script(TOKENS, "--repo", str(self.repo), "--base", "nope", cwd=self.base).returncode, 2)
        self.assertEqual(self.run_script(TOKENS, "--repo", str(self.base), "--base", "HEAD", cwd=self.base).returncode, 2)
        (self.repo / "scripts" / "budget.py").unlink()
        self.assertEqual(self.tokens().returncode, 2)
        self.assertEqual(self.run_script(TOKENS, "--repo", str(self.repo), cwd=self.base).returncode, 2)


class Ticks:
    def __init__(self, busy: int):
        self.busy = busy
        self.calls = 0

    def __call__(self) -> tuple[int, int]:
        self.calls += 1
        return self.calls * self.busy, self.calls * 100


class TestMeasure(GitRepo):
    def setUp(self):
        super().setUp()
        self.write("pkg/work.py", COSTLY)
        self.commit()
        self.leftovers = set(Path("/tmp").glob("kvb-measure-*"))

    def measured(self, *args: str, ticks=None, cwd: Path | None = None) -> tuple[int, str, str, int]:
        out, err = io.StringIO(), io.StringIO()
        with (
            mock.patch.dict(os.environ, self.env, clear=True),
            mock.patch.object(measure, "cpu_ticks", ticks or Ticks(0)),
            mock.patch.object(measure, "SAMPLE_SECONDS", 0),
            mock.patch.object(measure, "sample", wraps=measure.sample) as samples,
            contextlib.chdir(cwd or self.repo / "pkg"),
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
        ):
            try:
                code = measure.main(list(args))
            except SystemExit as stop:
                code = stop.code
        return code, out.getvalue(), err.getvalue(), samples.call_count

    def line(self, out: str) -> re.Match:
        match = LINE.match(out.strip())
        self.assertIsNotNone(match, out)
        return match

    def assertCleanedUp(self):
        trees = [line for line in self.git("worktree", "list", "--porcelain").splitlines() if line.startswith("worktree ")]
        self.assertEqual(trees, [f"worktree {self.repo.resolve()}"])
        self.assertLessEqual(set(Path("/tmp").glob("kvb-measure-*")), self.leftovers)

    def test_cheaper_head_stops_after_one_run_each(self):
        self.write("pkg/work.py", CHEAP)
        code, out, err, samples = self.measured("--base", "HEAD", "--", sys.executable, "work.py")
        self.assertEqual((code, samples), (0, 2), err)
        match = self.line(out)
        self.assertEqual((match["mark"], match["speed_mark"], match["basis"], match["tail"]), ("", "", "wall", ""))
        self.assertLess(int(match["efficiency"]), 100)
        self.assertLess(int(match["speed"]), 100)
        self.assertCleanedUp()

    def test_costlier_head_takes_the_mean_of_5_and_exits_3(self):
        self.write("pkg/work.py", CHEAP)
        self.commit()
        self.write("pkg/work.py", COSTLY)
        code, out, err, samples = self.measured("--base", "HEAD", "--", sys.executable, "work.py")
        self.assertEqual((code, samples), (3, 10), err)
        match = self.line(out)
        self.assertEqual((match["basis"], match["tail"]), ("wall", " · mean of 5"))
        self.assertGreater(int(match["efficiency"]), 100)
        self.assertGreater(int(match["speed"]), 100)
        code, out, _, _ = self.measured("--base", "HEAD", "--json", "--", sys.executable, "work.py")
        found = json.loads(out)
        self.assertEqual((code, found["runs"], found["estimated"], found["other_load"]), (3, 5, False, 0))
        self.assertGreater(found["head"]["ram"], found["base"]["ram"])
        self.assertCleanedUp()

    def test_other_load_over_30_makes_an_estimate_from_cpu_time(self):
        self.write("pkg/work.py", CHEAP)
        code, out, err, samples = self.measured("--base", "HEAD", "--", sys.executable, "work.py", ticks=Ticks(50))
        self.assertEqual((code, samples), (0, 2), err)
        match = self.line(out)
        self.assertEqual(
            (match["mark"], match["speed_mark"], match["basis"], match["tail"]),
            ("~", "~", "cpu", " (estimated: other load 50 %)"),
        )
        _, out, _, _ = self.measured("--base", "HEAD", "--json", "--", sys.executable, "work.py", ticks=Ticks(50))
        found = json.loads(out)
        self.assertEqual((found["estimated"], found["other_load"]), (True, 50))
        self.assertEqual(found["speed"], round(measure.ratio(found["head"]["cpu"], found["base"]["cpu"]) * 100))
        _, out, _, _ = self.measured("--base", "HEAD", "--json", "--", sys.executable, "work.py", ticks=Ticks(30))
        self.assertEqual({k: json.loads(out)[k] for k in ("estimated", "other_load")}, {"estimated": False, "other_load": 30})
        self.assertCleanedUp()

    def test_unreadable_load_is_an_estimate(self):
        self.write("pkg/work.py", CHEAP)
        code, out, err, _ = self.measured("--base", "HEAD", "--", sys.executable, "work.py", ticks=lambda: None)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.line(out)["tail"], " (estimated: other load unknown)")

    @unittest.skipUnless(measure.PROC_STAT.is_file(), "no /proc/stat on this platform")
    def test_proc_stat_yields_busy_and_total_jiffies(self):
        busy, total = measure.cpu_ticks()
        self.assertLessEqual(0, busy)
        self.assertLessEqual(busy, total)

    def test_failing_command_names_the_tree_and_exits_2(self):
        self.write("pkg/work.py", "import sys\nsys.exit('broken here')\n")
        code, out, err, _ = self.measured("--base", "HEAD", "--", sys.executable, "work.py")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("exited 1 in the head tree", err)
        self.assertIn("broken here", err)
        self.assertCleanedUp()

    def test_usage_errors_exit_2(self):
        for args in (
            ("--base", "HEAD", sys.executable, "work.py"),
            ("--base", "HEAD", "--"),
            ("--base", "HEAD", "--runs", "1", "--", sys.executable, "work.py"),
            ("--base", "nope", "--", sys.executable, "work.py"),
            ("--", sys.executable, "work.py"),
        ):
            with self.subTest(args=args):
                self.assertEqual(self.measured(*args)[0], 2)
        self.assertCleanedUp()

    def test_missing_directory_at_base_exits_2(self):
        self.write("new/work.py", CHEAP)
        code, _, err, _ = self.measured("--base", "HEAD", "--", sys.executable, "work.py", cwd=self.repo / "new")
        self.assertEqual(code, 2)
        self.assertIn("new does not exist at HEAD", err)
        self.assertCleanedUp()


if __name__ == "__main__":
    unittest.main()
