"""Exercise principles.py: principle-lens tool hits on the changed lines of a temporary git repository."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "skills" / "kvb-check-principles" / "scripts" / "principles.py"
SPEC = importlib.util.spec_from_file_location("principles_under_test", SCRIPT)
principles = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = principles
SPEC.loader.exec_module(principles)

GIT = shutil.which("git")
RUFF = shutil.which("ruff")
LIMITS = ("--ccn", "10", "--nloc", "50", "--params", "5", "--min-tokens", "40")
SWALLOW = "def old():\n    try:\n        return 1\n    except Exception:\n        pass\n"
ADDED = SWALLOW + "\n\ndef new(unused):\n    try:\n        return 2\n    except Exception:\n        pass\n"
RUFF_HITS = sorted(
    [
        ("app.py:8", "KISS/YAGNI", "ruff", "ARG001"),
        ("app.py:11", "fail fast", "ruff", "BLE001"),
        ("app.py:11", "fail fast", "ruff", "S110"),
    ]
)
LIZARD_TEXT = (
    "/src/app.py:3: warning: grow has 31 NLOC, 12 CCN, 140 token, 2 PARAM, 40 length, 3 ND\n"
    "/src/a b.cpp:7: warning: Foo::operator () has 5 NLOC, 16 CCN, 50 token, 7 PARAM, 6 length, 1 ND\n"
    "/src/x.py:1: warning: f has 1 NLOC, 20 CCN, 5 token, 0 PARAM, 1 length\n"
    "================================================\n"
    "No thresholds exceeded (cyclomatic_complexity > 10)\n"
)
JSCPD_REPORT = {
    "duplicates": [
        {
            "format": "python",
            "lines": 6,
            "fragment": "x = 1\n",
            "tokens": 55,
            "firstFile": {
                "name": "/src/a.py",
                "start": 1,
                "end": 6,
                "startLoc": {"line": 1, "column": 1, "position": 0},
                "endLoc": {"line": 6, "column": 9, "position": 80},
            },
            "secondFile": {
                "name": "/src/b.py",
                "start": 10,
                "end": 15,
                "startLoc": {"line": 10, "column": 1, "position": 120},
                "endLoc": {"line": 15, "column": 9, "position": 200},
            },
            "isNew": False,
            "kind": "exact",
        }
    ],
    "statistics": {"total": {"clones": 1}},
}
LINES = "".join(f"x{n} = {n}\n" for n in range(1, 31))
OTHER = "".join(f"y{n} = {n}\n" for n in range(1, 11))
FAKE_LIZARD = """#!{python}
import json
import sys
from pathlib import Path

Path({log!r}).write_text(json.dumps(sys.argv[1:]), encoding="utf-8")
for path in [arg for arg in sys.argv[1:] if arg.endswith(".py")]:
    print(path + ":1: warning: before has 4 NLOC, 12 CCN, 40 token, 1 PARAM, 4 length, 1 ND")
    print(path + ":3: warning: around has 5 NLOC, 12 CCN, 40 token, 1 PARAM, 5 length, 1 ND")
    print(path + ":5: warning: single has 1 NLOC, 12 CCN, 9 token, 1 PARAM, 1 length, 1 ND")
    print(path + ":6: warning: after has 5 NLOC, 12 CCN, 40 token, 1 PARAM, 5 length, 1 ND")
sys.exit(1)
"""
FAKE_JSCPD = """#!{python}
import json
import sys
from pathlib import Path

args = sys.argv[1:]
Path({log!r}).write_text(json.dumps(args), encoding="utf-8")
Path(args[args.index("--output") + 1], "jscpd-report.json").write_text({report!r}, encoding="utf-8")
"""


def clone(first: tuple[str, int, int], second: tuple[str, int, int], tokens: int) -> dict:
    return {
        "tokens": tokens,
        "firstFile": dict(zip(("name", "start", "end"), first)),
        "secondFile": dict(zip(("name", "start", "end"), second)),
    }


class TestParsers(unittest.TestCase):
    def test_lizard_warnings_with_their_spans(self):
        self.assertEqual(
            principles.parse_lizard(LIZARD_TEXT),
            [
                ("/src/app.py", 3, 42, "grow has 31 NLOC, 12 CCN, 140 token, 2 PARAM, 40 length, 3 ND"),
                ("/src/a b.cpp", 7, 12, "Foo::operator () has 5 NLOC, 16 CCN, 50 token, 7 PARAM, 6 length, 1 ND"),
                ("/src/x.py", 1, 1, "f has 1 NLOC, 20 CCN, 5 token, 0 PARAM, 1 length"),
            ],
        )

    def test_jscpd_report_sides(self):
        self.assertEqual(principles.parse_jscpd(JSCPD_REPORT), [(("/src/a.py", 1, 6), ("/src/b.py", 10, 15), 55)])

    def test_span_overlap_bounds(self):
        target = principles.Target(Path("/src/app.py"), frozenset({5}))
        self.assertEqual(
            [target.overlaps(*span) for span in ((1, 4), (3, 7), (5, 5), (6, 10))], [False, True, True, False]
        )
        self.assertTrue(principles.Target(Path("/src/app.py"), None).overlaps(100, 200))


class TestPrinciples(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()
        self.repo = self.tmp / "repo"
        self.bin = self.tmp / "bin"
        self.repo.mkdir()
        self.bin.mkdir()
        (self.bin / "git").symlink_to(GIT)
        self.env = {
            "PATH": str(self.bin),
            "HOME": str(self.tmp),
            "TMPDIR": str(self.tmp),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CEILING_DIRECTORIES": str(self.tmp),
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.org",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.org",
        }
        self._git("init", "-q", "-b", "main")

    def _git(self, *args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=self.repo, env=self.env, capture_output=True, text=True, check=True
        ).stdout

    def _write(self, files: dict[str, str]) -> None:
        for name, text in files.items():
            (self.repo / name).write_text(text, encoding="utf-8")

    def _commit(self, files: dict[str, str]) -> None:
        self._write(files)
        self._git("add", ".")
        self._git("commit", "-q", "-m", "base")

    def _fake(self, name: str, template: str, **values: str) -> Path:
        log = self.tmp / f"{name}.argv"
        script = self.bin / name
        script.write_text(template.format(python=sys.executable, log=str(log), **values), encoding="utf-8")
        script.chmod(0o755)
        return log

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args], env=self.env, capture_output=True, text=True, check=False
        )

    def _hits(self, *args: str) -> tuple[int, list[tuple]]:
        result = self._run("--repo", str(self.repo), "--json", *LIMITS, *args)
        self.assertIn(result.returncode, (0, 1), result.stderr)
        rows = json.loads(result.stdout)
        return result.returncode, sorted(
            (f"{r['file']}:{r['line']}", r["lens"], r["tool"], r["message"].split()[0]) for r in rows
        )

    def test_spans_and_clone_sides_filter_to_changed_lines(self):
        self._commit({"app.py": LINES, "other.py": OTHER})
        self._write({"app.py": LINES.replace("x5 = 5\n", "x5 = 50\n")})
        app, other = str(self.repo / "app.py"), str(self.repo / "other.py")
        report = {
            "duplicates": [
                clone((app, 4, 6), (other, 1, 3), 50),
                clone((app, 20, 25), (other, 1, 6), 60),
                clone((other, 2, 4), (app, 1, 5), 70),
                clone((other, 1, 3), (other, 5, 7), 80),
            ]
        }
        lizard_log = self._fake("lizard", FAKE_LIZARD)
        jscpd_log = self._fake("jscpd", FAKE_JSCPD, report=json.dumps(report))
        result = self._run("--repo", str(self.repo), *LIMITS)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(result.stderr, "skip: ruff missing\n")
        self.assertEqual(
            result.stdout,
            "app.py:1\tDRY\tjscpd\tclone of other.py:2-4, 70 tokens\n"
            "app.py:3\tSRP\tlizard\taround has 5 NLOC, 12 CCN, 40 token, 1 PARAM, 5 length, 1 ND\n"
            "app.py:4\tDRY\tjscpd\tclone of other.py:1-3, 50 tokens\n"
            "app.py:5\tSRP\tlizard\tsingle has 1 NLOC, 12 CCN, 9 token, 1 PARAM, 1 length, 1 ND\n",
        )
        self.assertEqual(
            json.loads(lizard_log.read_text(encoding="utf-8")),
            ["--warnings_only", "--CCN", "10", "--arguments", "5", "--Threshold", "nloc=50", app],
        )
        jscpd_args = json.loads(jscpd_log.read_text(encoding="utf-8"))
        self.assertEqual(jscpd_args[:4], ["--min-tokens", "40", "--reporters", "json"])
        self.assertEqual(jscpd_args[6:], ["--absolute", "--silent", str(self.repo)])

    def test_missing_tools_are_skipped(self):
        self._commit({"app.py": SWALLOW})
        self._write({"app.py": ADDED})
        result = self._run("--repo", str(self.repo), *LIMITS)
        self.assertEqual(
            (result.returncode, result.stdout, result.stderr),
            (0, "", "skip: ruff missing\nskip: lizard missing\nskip: jscpd missing\n"),
        )

    @unittest.skipUnless(RUFF, "ruff not installed")
    def test_ruff_flags_added_swallow_not_the_untouched_one(self):
        (self.bin / "ruff").symlink_to(RUFF)
        self._commit({"app.py": SWALLOW})
        self._write({"app.py": ADDED})
        code, hits = self._hits()
        self.assertEqual((code, hits), (1, RUFF_HITS))
        self.assertNotIn("app.py:4", [hit[0] for hit in hits])

    @unittest.skipUnless(RUFF, "ruff not installed")
    def test_staged_reads_the_index_snapshot(self):
        (self.bin / "ruff").symlink_to(RUFF)
        self._commit({"app.py": SWALLOW})
        self._write({"app.py": ADDED})
        self._git("add", "app.py")
        self._write({"app.py": SWALLOW})
        self.assertEqual(self._hits("--staged"), (1, RUFF_HITS))
        self.assertEqual(self._hits(), (0, []))

    @unittest.skipUnless(RUFF, "ruff not installed")
    def test_file_counts_every_line_of_an_untracked_file(self):
        (self.bin / "ruff").symlink_to(RUFF)
        self._commit({"app.py": SWALLOW})
        self._write({"extra.py": SWALLOW})
        self.assertEqual(self._hits(), (0, []))
        self.assertEqual(
            self._hits("--file", "extra.py"),
            (1, [("extra.py:4", "fail fast", "ruff", "BLE001"), ("extra.py:4", "fail fast", "ruff", "S110")]),
        )

    def test_usage_and_git_errors(self):
        self._commit({"app.py": SWALLOW})
        missing = self._run("--repo", str(self.repo), "--ccn", "10", "--nloc", "50", "--params", "5")
        self.assertEqual(missing.returncode, 2)
        self.assertIn("--min-tokens", missing.stderr)
        self.assertEqual(self._run("--repo", str(self.repo)).returncode, 2)
        outside = self.tmp / "plain"
        outside.mkdir()
        self.assertEqual(self._run("--repo", str(outside), *LIMITS).returncode, 2)
        self.assertEqual(self._run("--repo", str(self.repo), *LIMITS, "--file", "missing.py").returncode, 2)


if __name__ == "__main__":
    unittest.main()
