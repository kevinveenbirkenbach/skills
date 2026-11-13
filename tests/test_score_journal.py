"""Exercise labels.json and the score journal of kvb-check-score: labels in every layout, one row per block, failed appends, no gate reader."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import ModuleType
from unittest import mock

from score_fixture import git_env

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL = REPO_ROOT / "skills" / "kvb-check-score"
REQUIREMENTS = REPO_ROOT / "docs" / "requirements"
SCORE = SKILL / "scripts" / "score.py"
EFFICIENCY = REPO_ROOT / "skills" / "kvb-check-efficiency" / "scripts"
NOFOLLOW = REPO_ROOT / "skills" / "kvb-org-organize" / "scripts" / "nofollow.py"
HANG = 20
FORMER = re.compile(r"💸 Cost|⏱️ Time|(?i:💸 cost|⏱️ time|\bcost (?:and|or) time\b|\bcost, time\b|\b(?:cost|time) from the `kvb-check-(?:efficiency|speed)`)")
REMOTES = (
    "git@github.com:org/repo.git",
    "github.com:org/repo.git",
    "GitHub.com:org/repo",
    "https://github.com/org/repo",
    "https://user@github.com:443/org/repo.git/",
    "ssh://git@github.com/org/repo.git",
)
BASE = {"fix": "95", "break": "2", "efficiency": "97", "speed": "-", "security": "100", "critical": "0"}
VARIANTS = (
    {},
    {"efficiency": "120", "speed": "130"},
    {"efficiency": "new", "speed": "new", "security": "~90"},
    {"fix": "80", "break": "10", "efficiency": "150"},
    {"critical": "1"},
)
LAYOUTS = ((), ("--table",), ("--message-block",))
OLD = re.compile(r"cost|time", re.IGNORECASE)
JOURNAL_NAME = "scores.jsonl"
READERS = {
    "skills/kvb-check-score/SKILL.md",
    "skills/kvb-check-score/scripts/journal.py",
    "orchestrator/kvb_orchestrator/scores.py",
}


def flags(values: dict[str, str]) -> list[str]:
    return [item for key, value in {**BASE, **values}.items() for item in (f"--{key}", value)]


def module(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"copied_{path.stem}", path)
    found = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(found)
    return found


class ScoreCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.council = self.tmp / "council"
        self.env = {"PATH": os.environ["PATH"], "AGENTS_COUNCIL_ROOT": str(self.council)}

    def score(self, script: Path, *args: str, cwd: Path) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-B", str(script), *args], cwd=cwd, env=self.env, capture_output=True, text=True, check=False)

    def rows(self) -> list[dict]:
        path = self.council / JOURNAL_NAME
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []

    def copy_skills(self, labels: str) -> Path:
        """Args:
            labels: the text of the copied labels.json.

        Returns:
            The copied score.py, beside kvb-check-efficiency's copied tokens.py and measure.py.
        """
        skill, efficiency = self.tmp / "skills" / "kvb-check-score", self.tmp / "skills" / "kvb-check-efficiency" / "scripts"
        (skill / "scripts").mkdir(parents=True)
        efficiency.mkdir(parents=True)
        for name in ("score.py", "journal.py"):
            shutil.copy(SKILL / "scripts" / name, skill / "scripts" / name)
        for name in ("tokens.py", "measure.py"):
            shutil.copy(EFFICIENCY / name, efficiency / name)
        organize = self.tmp / "skills" / "kvb-org-organize" / "scripts"
        organize.mkdir(parents=True)
        shutil.copy(NOFOLLOW, organize / "nofollow.py")
        (skill / "labels.json").write_text(labels, encoding="utf-8")
        return skill / "scripts" / "score.py"


class TestScoreLabels(ScoreCase):
    def test_line_table_and_block_print_tokens_and_velocity_never_cost_or_time(self):
        expected = {(): ("💸 tokens", "⏱️ velocity"), ("--table",): ("| 💸 Tokens |", "| ⏱️ Velocity |"), ("--message-block",): ("💸 Tokens: ", "⏱️ Velocity: ")}
        for values in VARIANTS:
            for layout in LAYOUTS:
                with self.subTest(values=values, layout=layout):
                    out = self.score(SCORE, *flags(values), *layout, cwd=self.tmp).stdout
                    for label in expected[layout]:
                        self.assertIn(label, out)
                    self.assertIsNone(OLD.search(out), out)

    def test_no_skill_text_or_doc_names_the_former_labels(self):
        found = [
            f"{path.relative_to(REPO_ROOT)}:{number}"
            for top in ("skills", "docs")
            for path in sorted((REPO_ROOT / top).rglob("*"))
            if path.is_file() and path.suffix != ".pyc" and REQUIREMENTS not in path.parents
            for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1)
            if FORMER.search(line)
        ]
        self.assertEqual(found, [])
        labels = json.loads((SKILL / "labels.json").read_text(encoding="utf-8"))["metrics"]
        self.assertEqual({key: metric["former"] for key, metric in labels.items() if metric["former"]}, {"tokens": ["Cost", "Efficiency"], "velocity": ["Time", "Speed"]})
        self.assertEqual((labels["tokens"]["emoji"], labels["velocity"]["emoji"]), ("💸", "⏱️"))

    def test_a_label_changed_in_a_temporary_label_file_shows_in_every_layout(self):
        labels = json.loads((SKILL / "labels.json").read_text(encoding="utf-8"))
        labels["metrics"]["tokens"]["label"] = "Pennies"
        labels["metrics"]["velocity"].update(emoji="🐢", label="Pace")
        script = self.copy_skills(json.dumps(labels, ensure_ascii=False))
        line = self.score(script, *flags({}), cwd=self.tmp).stdout.splitlines()
        self.assertEqual(line[0], "🎯 fix 95 % · 💥 break 2 % · 💸 pennies 97 % · 🐢 pace – · 🛡️ security 100 % · 🏆 score 96")
        self.assertEqual(line[1], "✅ gate: 90/5, pennies and pace <= 100, security 100 %")
        table = self.score(script, *flags({}), "--table", "--value", "1:2", cwd=self.tmp).stdout.splitlines()
        self.assertEqual(table[0], "| 🎯 Fix | 💥 Break | 💸 Pennies | 💰 Value | 🐢 Pace | 🛡️ Security | 🏆 Score | Gate |")
        block = self.score(script, *flags({}), "--message-block", cwd=self.tmp).stdout.splitlines()
        self.assertEqual(block[2:4], ["💸 Pennies: 97 %", "🐢 Pace: –"])
        efficiency = self.tmp / "skills" / "kvb-check-efficiency" / "scripts"
        tokens = module(efficiency / "tokens.py")
        name = tokens.labelled(("tokens",))["tokens"]
        self.assertEqual(tokens.headline(name, 97, 100, 97, "listing 3→3 words"), "💸 pennies 97 % (skills 100→97 tokens; listing 3→3 words)")
        self.assertEqual(tokens.headline(name, None, 0, 50, "listing 3→5 words"), "💸 pennies new (+50 tokens; listing 3→5 words)")
        side = {"cpu": 1.0, "ram": 10.0, "wall": 2.0}
        found = {"estimated": False, "base": side, "head": side, "efficiency": 97, "speed": 90, "runs": 1}
        measure = module(efficiency / "measure.py")
        self.assertEqual(measure.line(found, measure.labelled(("tokens", "velocity"))), "💸 pennies 97 % (cpu 1.00→1.00 s, ram 10.0→10.0 MB) · 🐢 pace 90 % (wall 2.00→2.00 s)")

    def test_a_malformed_label_file_exits_2_or_4_with_one_stderr_line_in_every_layout(self):
        labels = json.loads((SKILL / "labels.json").read_text(encoding="utf-8"))
        broken = [
            "{broken",
            json.dumps({"metrics": [], "extras": {}}),
            json.dumps({**labels, "metrics": {key: value for key, value in labels["metrics"].items() if key != "velocity"}}),
            json.dumps({**labels, "metrics": {**labels["metrics"], "fix": {"emoji": 1, "label": "Fix", "former": []}}}),
        ]
        script = self.copy_skills("{}")
        cases = [(index, text, layout, critical, code) for index, text in enumerate(broken) for layout in LAYOUTS for critical, code in (("0", 2), ("1", 4))]
        for index, text, layout, critical, code in cases:
            (script.parents[1] / "labels.json").write_text(text, encoding="utf-8")
            with self.subTest(labels=index, layout=layout, critical=critical):
                done = self.score(script, *flags({"critical": critical}), *layout, cwd=self.tmp)
                self.assertEqual((done.returncode, done.stdout), (code, ""))
                self.assertEqual(len(done.stderr.splitlines()), 1, done.stderr)
                self.assertTrue(done.stderr.startswith("score: labels "), done.stderr)


class TestJournalPlace(unittest.TestCase):
    def setUp(self):
        self.journal = module(SKILL / "scripts" / "journal.py")

    def test_an_empty_council_root_means_the_default(self):
        for value in ("", None):
            with self.subTest(value=value), mock.patch.dict(os.environ, {} if value is None else {"AGENTS_COUNCIL_ROOT": value}):
                if value is None:
                    os.environ.pop("AGENTS_COUNCIL_ROOT", None)
                self.assertEqual(self.journal.journal_path(), Path("/tmp/agents-council/scores.jsonl"))

    def test_ssh_scp_and_https_remotes_share_one_key(self):
        self.assertEqual({self.journal.identity(url) for url in REMOTES}, {"github.com/org/repo"})
        for url in ("/srv/git/repo.git", "./repo", "file:///srv/git/repo.git", None):
            with self.subTest(url=url):
                self.assertEqual(self.journal.identity(url), url)


class TestScoreJournal(ScoreCase):
    def repo(self) -> Path:
        repo = self.tmp / "repo"
        repo.mkdir()
        env = git_env(self.tmp)
        for args in (("init", "-q", "-b", "feature/journal"), ("remote", "add", "origin", "git@github.com:example/fixture.git"), ("commit", "-q", "--allow-empty", "-m", "base")):
            subprocess.run(["git", *args], cwd=repo, env=env, capture_output=True, check=True)
        return repo

    def test_each_message_block_appends_exactly_one_row_with_the_journal_fields(self):
        repo = self.repo()
        before = int(time.time())
        first = self.score(SCORE, *flags({}), "--message-block", cwd=repo)
        second = self.score(SCORE, *flags({"security": "~80"}), "--message-block", "--value", "1:20", cwd=repo)
        self.assertEqual((first.returncode, second.returncode, first.stderr, second.stderr), (0, 3, "", ""))
        rows = self.rows()
        self.assertEqual(len(rows), 2)
        for row, done in zip(rows, (first, second)):
            self.assertEqual(list(row), ["time", "remote", "path", "branch", "sha", "values", "digest"])
            self.assertEqual((row["remote"], row["path"], row["branch"], row["sha"]), ("github.com/example/fixture", str(repo.resolve()), "feature/journal", None))
            self.assertEqual(row["digest"], hashlib.sha256(done.stdout.rstrip("\n").encode("utf-8")).hexdigest())
            self.assertLessEqual(before, row["time"])
            self.assertLessEqual(row["time"], int(time.time()))
        self.assertEqual(rows[0]["values"], {"fix": 95, "break": 2, "tokens": 97, "velocity": None, "security": 100, "score": 96})
        self.assertEqual(rows[1]["values"], {"fix": 95, "break": 2, "tokens": 97, "velocity": None, "security": 80, "score": 77})
        self.score(SCORE, *flags({}), cwd=repo)
        self.score(SCORE, *flags({}), "--table", cwd=repo)
        self.assertEqual(len(self.rows()), 2)

    def test_a_failed_append_prints_one_stderr_line_and_keeps_the_exit_code(self):
        self.council.write_text("not a directory", encoding="utf-8")
        for values, code in (({}, 0), ({"efficiency": "120"}, 3), ({"break": "9"}, 1), ({"critical": "1"}, 4)):
            with self.subTest(values=values):
                done = self.score(SCORE, *flags(values), "--message-block", cwd=self.tmp)
                self.assertEqual(done.returncode, code)
                self.assertEqual(len(done.stderr.splitlines()), 1, done.stderr)
                self.assertTrue(done.stderr.startswith(f"score: journal {self.council / JOURNAL_NAME}: "), done.stderr)
                self.assertEqual(len(done.stdout.splitlines()), 7)

    def test_a_deleted_working_directory_keeps_the_exit_code(self):
        gone = self.tmp / "gone"
        wrapper = "import os, subprocess, sys; os.chdir(sys.argv[1]); os.rmdir(sys.argv[1]); sys.exit(subprocess.run(sys.argv[2:]).returncode)"
        for values, code in (({}, 0), ({"critical": "1"}, 4)):
            with self.subTest(values=values):
                gone.mkdir(exist_ok=True)
                done = subprocess.run([sys.executable, "-B", "-c", wrapper, str(gone), sys.executable, "-B", str(SCORE), *flags(values), "--message-block"], env=self.env, capture_output=True, text=True, check=False)
                self.assertEqual(done.returncode, code, done.stderr)
                self.assertEqual(len(done.stderr.splitlines()), 1, done.stderr)
                self.assertTrue(done.stderr.startswith(f"score: journal {self.council / JOURNAL_NAME}: "), done.stderr)
                self.assertEqual(len(done.stdout.splitlines()), 7)

    def test_git_output_outside_utf8_keeps_the_exit_code_and_the_row(self):
        repo = self.repo()
        subprocess.run([b"git", b"remote", b"set-url", b"origin", b"https://example.org/caf\xe9.git"], cwd=repo, env=git_env(self.tmp), capture_output=True, check=True)
        done = self.score(SCORE, *flags({"critical": "1"}), "--message-block", cwd=repo)
        self.assertEqual((done.returncode, done.stderr), (4, ""))
        self.assertEqual(self.rows()[0]["remote"], "example.org/caf�")

    def test_a_link_at_the_journal_is_not_followed(self):
        self.council.mkdir()
        target = self.tmp / "elsewhere"
        target.write_text("kept\n", encoding="utf-8")
        (self.council / JOURNAL_NAME).symlink_to(target)
        done = self.score(SCORE, *flags({"critical": "1"}), "--message-block", cwd=self.tmp)
        self.assertEqual(done.returncode, 4)
        self.assertEqual(len(done.stderr.splitlines()), 1, done.stderr)
        self.assertEqual(target.read_text(encoding="utf-8"), "kept\n")

    def test_a_fifo_at_the_journal_does_not_block_the_exit_code(self):
        self.council.mkdir()
        os.mkfifo(self.council / JOURNAL_NAME)
        done = subprocess.run([sys.executable, "-B", str(SCORE), *flags({"critical": "1"}), "--message-block"], cwd=self.tmp, env=self.env, capture_output=True, text=True, check=False, timeout=HANG)
        self.assertEqual(done.returncode, 4)
        self.assertEqual(len(done.stderr.splitlines()), 1, done.stderr)
        self.assertTrue(done.stderr.startswith(f"score: journal {self.council / JOURNAL_NAME}: "), done.stderr)

    def test_a_linked_council_root_is_refused(self):
        real = self.tmp / "worktree"
        real.mkdir()
        (real / ".git").write_text("gitdir: /elsewhere\n", encoding="utf-8")
        self.council.symlink_to(real)
        done = self.score(SCORE, *flags({"critical": "1"}), "--message-block", cwd=self.tmp)
        self.assertEqual(done.returncode, 4)
        self.assertEqual(len(done.stderr.splitlines()), 1, done.stderr)
        self.assertEqual(sorted(path.name for path in real.iterdir()), [".git"])

    def test_a_missing_or_broken_nofollow_helper_is_named_in_the_one_stderr_line(self):
        script = self.copy_skills((SKILL / "labels.json").read_text(encoding="utf-8"))
        helper = self.tmp.resolve() / "skills" / "kvb-org-organize" / "scripts" / "nofollow.py"
        cases = {"FileNotFoundError": None, "AttributeError": "VERSION = 0\n", "SyntaxError": "def (:\n"}
        if os.geteuid() != 0:
            cases["PermissionError"] = NOFOLLOW.read_text(encoding="utf-8")
        for kind, text in cases.items():
            helper.unlink(missing_ok=True)
            if text is not None:
                helper.write_text(text, encoding="utf-8")
            if kind == "PermissionError":
                helper.chmod(0)
            for values, code in (({}, 0), ({"critical": "1"}, 4)):
                with self.subTest(kind=kind, values=values):
                    done = self.score(script, *flags(values), "--message-block", cwd=self.tmp)
                    self.assertEqual(done.returncode, code)
                    self.assertEqual(done.stderr, f"score: journal {self.council / JOURNAL_NAME}: helper {helper} unusable ({kind}): install or update kvb-org-organize\n")
                    self.assertEqual(len(done.stdout.splitlines()), 7)
                    self.assertFalse(self.council.exists())

    def test_a_branch_or_commit_outside_utf8_keeps_the_score_exit(self):
        repo = self.tmp / "latin"
        env = git_env(self.tmp)
        subprocess.run(["git", "init", "-q", "-b", "caf\udce9", str(repo)], env=env, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "base"], cwd=repo, env=env, capture_output=True, check=True)
        for values, code in (({}, 0), ({"critical": "1"}, 4)):
            with self.subTest(values=values):
                done = self.score(SCORE, *flags(values), "--commit-table", str(repo), cwd=self.tmp)
                self.assertEqual((done.returncode, done.stderr), (code, ""))
                self.assertIn("| caf� |", done.stdout)
                failed = self.score(SCORE, *flags(values), "--commit-table", str(repo), "--commit", "\udce9", cwd=self.tmp)
                self.assertEqual((failed.returncode, failed.stdout), (code or 2, ""))
                self.assertEqual(len(failed.stderr.splitlines()), 1, failed.stderr)
                self.assertTrue(failed.stderr.startswith("score: git show in "), failed.stderr)

    def test_a_critical_finding_wins_over_a_commit_table_git_cannot_read(self):
        repo = self.repo()
        plain = self.tmp / "plain"
        plain.mkdir()
        self.env["GIT_CEILING_DIRECTORIES"] = str(self.tmp)
        tables = {"non-git": (str(plain),), "deleted": (str(self.tmp / "deleted"),), "unknown commit": (str(repo), "--commit", "0" * 40)}
        for name, (target, *commit) in tables.items():
            for values, code in (({}, 2), ({"fix": "80"}, 2), ({"critical": "1"}, 4), ({"fix": "80", "critical": "1"}, 4)):
                with self.subTest(table=name, values=values):
                    done = self.score(SCORE, *flags(values), "--commit-table", target, *commit, cwd=self.tmp)
                    self.assertEqual((done.returncode, done.stdout), (code, ""))
                    self.assertEqual(len(done.stderr.splitlines()), 1, done.stderr)
                    self.assertTrue(done.stderr.startswith("score: git "), done.stderr)

    def test_a_new_journal_and_council_root_are_private(self):
        self.score(SCORE, *flags({}), "--message-block", cwd=self.tmp)
        self.assertEqual(stat.S_IMODE((self.council / JOURNAL_NAME).stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.council.stat().st_mode), 0o700)

    def test_no_gate_reads_the_journal(self):
        found = set()
        for top in ("skills", "orchestrator", "scripts"):
            for path in (REPO_ROOT / top).rglob("*"):
                text = path.suffix in {".py", ".sh", ".md", ".js", ".j2", ".json", ".yml"} and path.is_file()
                if text and JOURNAL_NAME in path.read_text(encoding="utf-8", errors="replace"):
                    found.add(str(path.relative_to(REPO_ROOT)))
        self.assertEqual(found, READERS)
        importers = {str(path.relative_to(REPO_ROOT)) for path in (REPO_ROOT / "skills").rglob("*.py") if re.search(r"^from journal import|^import journal", path.read_text(encoding="utf-8"), re.MULTILINE)}
        self.assertEqual(importers, {"skills/kvb-check-score/scripts/score.py", "skills/kvb-check-score/scripts/backfill.py"})
        self.council.mkdir()
        (self.council / JOURNAL_NAME).write_text('{"time": 1, "values": {"score": 0}}\n{broken\n', encoding="utf-8")
        self.assertEqual(self.score(SCORE, *flags({}), cwd=self.tmp).returncode, 0)


if __name__ == "__main__":
    unittest.main()
