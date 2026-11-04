"""Exercise kvb-check-efficiency: tokens.py on skill text changes and their value, measure.py on a command in a base worktree."""

from __future__ import annotations

import contextlib
import datetime
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
TOKENS_SPEC = importlib.util.spec_from_file_location("skill_tokens", TOKENS)
skill_tokens = importlib.util.module_from_spec(TOKENS_SPEC)
TOKENS_SPEC.loader.exec_module(skill_tokens)
BUDGET = REPO_ROOT / "scripts" / "budget.py"
SKILL_A = "---\nname: kvb-a\ndescription: >\n  one two three\n---\n"
SKILL_B = "---\nname: kvb-b\ndescription: >\n  four five\n---\n"
NO_VALUE = "💰 value ?:? (cost 0/day; pass --value with evidence)"
NEW_B = "💰 value ?:? (cost 0/day; pass --value with evidence; kvb-b new: all skills median 0 invocations/day)"
CHEAP = "print('cheap')\n"
COSTLY = "data = list(range(2_000_000))\nprint(sum(data))\n"
LINE = re.compile(
    r"^💸 cost (?P<mark>~?)(?P<efficiency>\d+) % \(cpu \d+\.\d\d→\d+\.\d\d s, ram \d+\.\d→\d+\.\d MB\) · "
    r"⏱️ time (?P<speed_mark>~?)(?P<speed>\d+) % \((?P<basis>wall|cpu) \d+\.\d\d→\d+\.\d\d s\)(?P<tail>.*)$"
)


def skill_md(name: str, words: str) -> str:
    return f"---\nname: {name}\ndescription: >\n  {words}\n---\n"


def stamp(moment: datetime.datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def assistant(mid: str, moment: datetime.datetime, *uses: tuple[str, str]) -> str:
    content = [{"type": "tool_use", "id": use, "name": "Skill", "input": {"skill": skill}} for use, skill in uses]
    return json.dumps({"type": "assistant", "timestamp": stamp(moment), "message": {"id": mid, "content": content}})


def turn(day: datetime.date, mid: str, size: int) -> str:
    usage = {"input_tokens": size, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    return json.dumps({"timestamp": f"{day.isoformat()}T10:00:00Z", "message": {"id": mid, "usage": usage}})


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

    def transcribe(self, lines: list[str]) -> None:
        session = self.base / "projects" / "project" / "session.jsonl"
        session.parent.mkdir(parents=True, exist_ok=True)
        session.write_text("\n".join(lines) + "\n", encoding="utf-8")

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
        self.transcribe([])
        self.recent = datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=1)

    def tokens(self, *extra: str) -> subprocess.CompletedProcess:
        return self.run_script(
            TOKENS, "--repo", str(self.repo), "--base", "HEAD", "--transcripts", str(self.base / "projects"), *extra,
            cwd=self.base,
        )

    def test_shrunk_file_is_under_100(self):
        self.write("skills/kvb-a/notes.md", "x" * 200)
        self.write("skills/kvb-a/scripts/tool.py", "print(1)\n" * 50)
        result = self.tokens()
        self.assertEqual(
            result.stdout.splitlines(), ["💸 cost 50 % (skills 100→50 tokens; listing 3→3 words)", NO_VALUE]
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_changed_and_new_skill_files_over_100(self):
        self.write("skills/kvb-a/notes.md", "x" * 600)
        self.write("skills/kvb-b/SKILL.md", SKILL_B.ljust(200, "y"))
        result = self.tokens()
        self.assertEqual(
            result.stdout.splitlines(), ["💸 cost 200 % (skills 100→200 tokens; listing 3→5 words)", NEW_B]
        )
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
                "value": {
                    "quotient": "?:?",
                    "cost": 0,
                    "value": None,
                    "evidence": None,
                    "requests_per_day": 0,
                    "invocations_per_day": {"kvb-b": 0},
                    "median_for_new": {"kvb-b": "all skills"},
                },
            },
        )

    def test_only_new_files_print_new(self):
        self.write("skills/kvb-b/SKILL.md", SKILL_B.ljust(200, "y"))
        result = self.tokens()
        self.assertEqual(result.stdout.splitlines(), ["💸 cost new (+50 tokens; listing 3→5 words)", NEW_B])
        self.assertEqual(result.returncode, 3)
        self.assertIsNone(json.loads(self.tokens("--json").stdout)["efficiency"])

    def test_rename_counts_both_sides(self):
        self.git("mv", "skills/kvb-a/notes.md", "skills/kvb-a/moved.md")
        result = self.tokens()
        self.assertEqual(
            result.stdout.splitlines(), ["💸 cost 100 % (skills 100→100 tokens; listing 3→3 words)", NO_VALUE]
        )
        self.assertEqual(result.returncode, 0)

    def test_no_change_is_100(self):
        result = self.tokens()
        self.assertEqual(
            result.stdout.splitlines(), ["💸 cost 100 % (skills 0→0 tokens; listing 3→3 words)", NO_VALUE]
        )
        self.assertEqual(result.returncode, 0)

    def test_cost_counts_cached_listing_reads_and_skill_invocations(self):
        old = self.recent - datetime.timedelta(days=8)
        lines = [assistant(f"m{n}", self.recent) for n in range(56)]
        lines += [assistant(f"m{n}", self.recent, (f"t{n}", "kvb-a")) for n in range(56, 69)]
        lines += [
            assistant("m69", self.recent, ("t69", "skills:kvb-a")),
            assistant("m60", self.recent, ("t60", "kvb-a")),
            assistant("old", old, ("t-old", "kvb-a")),
            json.dumps({"type": "api-request-blob", "timestamp": stamp(self.recent), "message": {"id": "blob"}, "role": "assistant"}),
            '{"type": "assistant", broken',
        ]
        self.transcribe(lines)
        self.write("skills/kvb-a/SKILL.md", SKILL_A.replace("three", "three four five").ljust(451, "y"))
        result = self.tokens()
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "💸 cost 869 % (skills 13→113 tokens; listing 3→5 words)",
                "💰 value ?:? (cost 203/day; pass --value with evidence)",
            ],
        )
        self.assertEqual(result.returncode, 3)
        for value, line in (
            ("4053", "💰 value 1:20 (cost 203/day, value 4053/day; 4053 tokens/day saved)"),
            ("50", "💰 value 4.1:1 (cost 203/day, value 50/day; 4053 tokens/day saved)"),
        ):
            with self.subTest(value=value):
                result = self.tokens("--value", value, "--evidence", "4053 tokens/day saved")
                self.assertEqual((result.stdout.splitlines()[1], result.returncode), (line, 3))
        found = json.loads(self.tokens("--json", "--value", "4053", "--evidence", "e").stdout)["value"]
        self.assertEqual(
            found,
            {
                "quotient": "1:20",
                "cost": 202.66,
                "value": 4053,
                "evidence": "e",
                "requests_per_day": 10,
                "invocations_per_day": {"kvb-a": 2},
                "median_for_new": {},
            },
        )

    def test_new_skill_takes_its_category_median(self):
        self.write("skills/kvb-c-one/SKILL.md", skill_md("kvb-c-one", "one"))
        self.write("skills/kvb-c-two/SKILL.md", skill_md("kvb-c-two", "two"))
        self.commit()
        lines = [assistant(f"m{n}", self.recent, (f"t{n}", "kvb-c-one")) for n in range(7)]
        lines += [assistant(f"m{n}", self.recent, (f"t{n}", "kvb-c-two")) for n in range(7, 28)]
        lines += [assistant(f"m{n}", self.recent, (f"t{n}", "kvb-a")) for n in range(28, 98)]
        self.transcribe(lines)
        self.write("skills/kvb-c-new/SKILL.md", skill_md("kvb-c-new", "six").ljust(400, "y"))
        result = self.tokens()
        self.assertEqual(
            result.stdout.splitlines()[1],
            "💰 value ?:? (cost 202/day; pass --value with evidence; kvb-c-new new: kvb-c median 2 invocations/day)",
        )
        self.assertEqual(result.returncode, 3)

    def test_usage_errors_exit_2(self):
        self.assertEqual(self.tokens("--value", "5").returncode, 2)
        self.assertEqual(self.tokens("--evidence", "why").returncode, 2)
        self.assertEqual(self.tokens("--value", "x", "--evidence", "why").returncode, 2)
        self.assertEqual(self.tokens("--value", "5", "--evidence", "two\nlines").returncode, 2)
        self.assertEqual(self.tokens("--value", "5", "--evidence", " ").returncode, 2)
        missing = str(self.base / "none")
        self.assertEqual(self.run_script(TOKENS, "--repo", str(self.repo), "--base", "HEAD", "--transcripts", missing, cwd=self.base).returncode, 2)
        self.assertEqual(self.run_script(TOKENS, "--repo", str(self.repo), "--base", "HEAD", cwd=self.base).returncode, 2)
        self.assertEqual(self.tokens("--base", "nope").returncode, 2)
        self.assertEqual(self.run_script(TOKENS, "--repo", str(self.base), "--base", "HEAD", "--transcripts", missing, cwd=self.base).returncode, 2)
        (self.repo / "scripts" / "budget.py").unlink()
        self.assertEqual(self.tokens().returncode, 2)
        self.assertEqual(self.run_script(TOKENS, "--repo", str(self.repo), cwd=self.base).returncode, 2)


class TestQuotient(unittest.TestCase):
    def test_normalised_to_cost_1_and_rounded(self):
        for (cost, value), expected in (
            ((100, 4000), "1:40"),
            ((2, 3), "1:1.5"),
            ((202.66, 4053), "1:20"),
            ((3, 3), "1:1"),
            ((200, 50), "4:1"),
            ((300, 7), "43:1"),
            ((0, 5), "0:1"),
            ((-5, 5), "0:1"),
            ((5, 0), "1:0"),
            ((5, -1), "1:0"),
            ((0, 0), "0:0"),
        ):
            with self.subTest(cost=cost, value=value):
                self.assertEqual(skill_tokens.quotient(cost, value), expected)

    def test_figures(self):
        for amount, expected in ((3829.4, "3829"), (12.5, "12"), (9.96, "10"), (1.04, "1"), (-0.04, "0"), (-12.6, "-13")):
            with self.subTest(amount=amount):
                self.assertEqual(skill_tokens.figure(amount), expected)


class TestValueSince(GitRepo):
    def setUp(self):
        super().setUp()
        self.write("skills/kvb-a/SKILL.md", SKILL_A)
        self.day = datetime.datetime.now(datetime.UTC).date() - datetime.timedelta(days=10)
        self.env["GIT_COMMITTER_DATE"] = f"{self.day.isoformat()}T12:00:00+00:00"
        self.commit()
        del self.env["GIT_COMMITTER_DATE"]
        self.sha = self.git("rev-parse", "--short", "HEAD").strip()
        day = self.day
        self.transcribe([
            turn(day - datetime.timedelta(days=8), "early", 100_000),
            turn(day - datetime.timedelta(days=6), "b1", 1_000),
            turn(day - datetime.timedelta(days=4), "b2", 2_000),
            turn(day - datetime.timedelta(days=4), "b3", 1_000),
            turn(day - datetime.timedelta(days=2), "b4", 5_000),
            turn(day - datetime.timedelta(days=2), "b4", 5_000),
            turn(day, "same", 900_000),
            turn(day + datetime.timedelta(days=1), "a1", 1_000),
            turn(day + datetime.timedelta(days=5), "a2", 2_000),
            turn(datetime.datetime.now(datetime.UTC).date(), "today", 900_000),
        ])

    def value(self, *extra: str) -> subprocess.CompletedProcess:
        return self.run_script(
            TOKENS, "value", "--repo", str(self.repo), "--transcripts", str(self.base / "projects"), *extra, cwd=self.base
        )

    def test_median_daily_context_before_minus_after(self):
        result = self.value("--since", "HEAD")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout,
            f"💰 measured value 1500/day (median daily context 3000→1500 tokens over 3 active days before and 2 after "
            f"{self.sha} of {self.day})\n",
        )
        self.assertEqual(
            json.loads(self.value("--since", "HEAD", "--json").stdout),
            {
                "since": self.sha,
                "day": self.day.isoformat(),
                "before": {"days": 3, "median": 3000},
                "after": {"days": 2, "median": 1500},
                "value": 1500,
            },
        )

    def test_no_full_day_after_and_usage_errors_exit_2(self):
        self.write("skills/kvb-a/notes.md", "x")
        self.commit()
        result = self.value("--since", "HEAD")
        self.assertEqual((result.returncode, result.stdout), (2, ""))
        self.assertIn("no active day in the 7 days after", result.stderr)
        self.assertEqual(self.value("--since", "nope").returncode, 2)
        self.assertEqual(self.value().returncode, 2)
        result = self.run_script(
            TOKENS, "value", "--repo", str(self.repo), "--since", "HEAD~1", "--transcripts", str(self.base / "none"),
            cwd=self.base,
        )
        self.assertEqual(result.returncode, 2)


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
