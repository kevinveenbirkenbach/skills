"""Exercise kvb-git-hotfix: hotfix rows in the rasci register, pending, match, void and the funnel sync."""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import importlib.util
import io
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
HOTFIX = REPO_ROOT / "skills" / "kvb-git-hotfix" / "scripts" / "hotfix.py"
RASCI = REPO_ROOT / "skills" / "kvb-org-rasci" / "scripts" / "rasci.py"
GATE = REPO_ROOT / "skills" / "kvb-check-gate" / "scripts" / "gate.py"
PROBE = (
    "import fcntl, sys\n"
    "with open(sys.argv[1], 'a', encoding='utf-8') as lock:\n"
    "    try:\n"
    "        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
    "    except BlockingIOError:\n"
    "        print('held', sys.argv[2])\n"
    "    else:\n"
    "        print('free', sys.argv[2])\n"
)
SIGNATURE = r"connection refused .* port 5432"
RUN_LOCK = "kvb-gate-run.lock"
SYNC_LOCK = "kvb-gate-sync.lock"
IDENTITY = {
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.org",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.org",
    "GIT_CONFIG_NOSYSTEM": "1",
}


def load_hotfix() -> object:
    spec = importlib.util.spec_from_file_location("hotfix", HOTFIX)
    hotfix = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hotfix)
    return hotfix


class TestOriginUrls(unittest.TestCase):
    def test_spellings_of_one_repository_normalize_alike(self):
        hotfix = load_hotfix()
        top = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, top)
        for url in (
            "https://github.com/Org/Repo.git",
            "https://GitHub.com/org/REPO/",
            "git@github.com:Org/Repo.git",
            "ssh://git@github.com:22/Org/Repo.git/",
            "https://user@github.com/Org/Repo",
        ):
            with self.subTest(url=url):
                self.assertEqual(hotfix.normalized(url, top), "github.com/org/repo")
        self.assertEqual(hotfix.normalized("https://GitLab.com/Group/Sub/App.git", top), "gitlab.com/group/sub/app")
        self.assertEqual(hotfix.normalized("https://git.example.org/Org/Repo.git", top), "git.example.org/Org/Repo")
        for url in ("file:///srv/repo.git", "/srv/repo.git", "/srv/repo/"):
            with self.subTest(url=url):
                self.assertEqual(hotfix.normalized(url, top), os.path.realpath("/srv/repo"))
        parent = os.path.dirname(os.path.realpath(top))
        self.assertEqual(hotfix.normalized("../up.git", top), os.path.join(parent, "up"))
        self.assertEqual(hotfix.normalized("up", top), os.path.join(os.path.realpath(top), "up"))
        self.assertEqual(hotfix.normalized("", top), "")
        self.assertNotEqual(hotfix.normalized("git@github.com:Org/Other.git", top), "github.com/org/repo")

    def test_differing_origins_mean_different_repositories_even_in_one_git_dir(self):
        hotfix = load_hotfix()
        self.assertFalse(hotfix.same(("/x/.git", "github.com/a/x"), ("/x/.git", "github.com/b/y")))
        self.assertTrue(hotfix.same(("/x/.git", "github.com/a/x"), ("/y/.git", "github.com/a/x")))
        self.assertTrue(hotfix.same(("/x/.git", ""), ("/x/.git", "github.com/a/x")))
        self.assertFalse(hotfix.same(("/x/.git", ""), ("/y/.git", "github.com/a/x")))


class TestSignatures(unittest.TestCase):
    def test_only_runaway_repeats_are_refused(self):
        hotfix = load_hotfix()
        for pattern in ("(a+)+", "(?:x|y+)*z", "((ab)*c)+", r"(\d{2,})+"):
            with self.subTest(pattern=pattern):
                self.assertEqual(hotfix.risk(pattern), hotfix.NESTED)
        for pattern in ("(a|a)*b", "(ab|a|b)*c", r"(\w|\d\d)+$", "([^x]|y)*z"):
            with self.subTest(pattern=pattern):
                self.assertEqual(hotfix.risk(pattern), hotfix.OVERLAP)
        for pattern in (
            r"(\d{1,3}\.){3}\d{1,3}", r"(\d{1,3}\.)+\d+", r"(ab)+ timeout \d+", "(foo|bar)+ failed",
            r"(\d|x)+", "(foo|fob)*x", "(?>a+)*b", "(a++)*b", "port (5432|5433) refused",
        ):
            with self.subTest(pattern=pattern):
                self.assertIsNone(hotfix.risk(pattern))


class TestBoundedChildren(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name).resolve()
        self.hotfix = load_hotfix()

    def test_match_exits_2_when_the_search_worker_fails_never_no_match(self):
        rows = {"hotfix/x": {"stage": "pr", "signature": "x", "branch": "fix/x", "sha": "0" * 40, "origin": "o"}}
        register = types.SimpleNamespace(load=lambda: rows)
        for name, patch in (
            ("no interpreter", mock.patch.object(self.hotfix.sys, "executable", str(self.base / "absent"))),
            ("worker exits 3", mock.patch.object(self.hotfix, "SEARCH", "import sys; sys.exit(3)")),
            ("worker answers short", mock.patch.object(self.hotfix, "SEARCH", "print('ready')")),
        ):
            with self.subTest(name):
                out, err = io.StringIO(), io.StringIO()
                with (
                    patch,
                    contextlib.redirect_stdout(out),
                    contextlib.redirect_stderr(err),
                    self.assertRaises(SystemExit) as raised,
                ):
                    self.hotfix.cmd_match(register, argparse.Namespace(line="x", repo=None))
                self.assertEqual(raised.exception.code, 2, err.getvalue())
                self.assertEqual(out.getvalue(), "")
                self.assertIn("signature search worker", err.getvalue())

    def test_a_fetch_never_prompts_and_stops_after_fetch_seconds(self):
        marker = self.base / "prompt"
        wrapper = self.base / "bin" / "git"
        wrapper.parent.mkdir()
        wrapper.write_text(
            f"#!/bin/sh\nprintf '%s' \"$GIT_TERMINAL_PROMPT\" > {marker}\nexec sleep 30\n", encoding="utf-8"
        )
        wrapper.chmod(0o755)
        began = time.monotonic()
        with (
            mock.patch.object(self.hotfix, "FETCH_SECONDS", 1),
            mock.patch.dict(os.environ, {"PATH": f"{wrapper.parent}:/usr/bin:/bin"}),
        ):
            result = self.hotfix.fetch(str(self.base))
        self.assertLess(time.monotonic() - began, 20)
        self.assertEqual((result.returncode, result.stderr), (124, "stopped after 1 s"))
        self.assertEqual(marker.read_text(encoding="utf-8"), "0")


class TestHotfix(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name).resolve()
        home = self.base / "home"
        sessions = home / ".claude" / "sessions"
        sessions.mkdir(parents=True)
        (sessions / "s1.json").write_text(json.dumps({"sessionId": "s1", "name": "One"}), encoding="utf-8")
        self.root = self.base / "council"
        self.env = {
            "PATH": "/usr/bin:/bin",
            "HOME": str(home),
            "AGENTS_COUNCIL_ROOT": str(self.root),
            "CLAUDE_CODE_SESSION_ID": "s1",
            "GIT_CEILING_DIRECTORIES": str(self.base),
            **IDENTITY,
        }
        self.origin = self.base / "origin.git"
        self.seed = self.published(self.origin, self.base / "seed", "app.txt")

        self.work = self.base / "work"
        self.git(self.base, "clone", "-q", str(self.origin), str(self.work))
        self.feature = self.base / "feature"
        self.git(self.work, "worktree", "add", "-q", "-b", "feature", str(self.feature), "origin/main")
        self.git(self.work, "switch", "-q", "-c", "line")
        self.commit(self.work, "line.txt", "line\n", "line work")
        self.git(self.work, "switch", "-q", "-c", "sidetree")
        self.commit(self.work, "side.txt", "side\n", "side work")
        self.git(self.work, "switch", "-q", "line")
        self.commit(self.work, "line2.txt", "more\n", "more line work")
        self.git(self.work, "switch", "-q", "sidetree")
        self.rasci("set", "work/line", "--branch", "line", "--base", "main", "--workdir", str(self.work))
        self.rasci("set", "work/side", "--branch", "sidetree", "--base", "line", "--workdir", str(self.work))
        self.rasci("set", "work/feature", "--branch", "feature", "--workdir", str(self.feature))

        self.git(self.seed, "switch", "-q", "-c", "fix/db")
        self.fix = self.commit(self.seed, "db.txt", "retry\n", "fix db")
        self.git(self.seed, "switch", "-q", "main")
        self.git(self.seed, "merge", "-q", "--ff-only", "fix/db")
        self.git(self.seed, "push", "-q", "origin", "main")
        self.git(self.seed, "switch", "-q", "-c", "fix/lint")
        self.lint = self.commit(self.seed, "lint.txt", "ok\n", "fix lint")
        self.git(self.seed, "switch", "-q", "main")
        self.out("add", "db", *self.flags({"--branch": "fix/db", "--sha": self.fix, "--signature": SIGNATURE,
                                            "--status": "merged", "--target": "test-deploy", "--pr": "12"}))
        self.out("add", "lint", *self.flags({"--branch": "fix/lint", "--sha": self.lint[:10],
                                              "--signature": r"ruff: E\d+", "--target": "test-lint"}))
        self.assertEqual(self.out("update", "lint", "--status", "pr", "--pr", "13"), ["updated hotfix/lint"])

        self.other = self.published(self.base / "other.git", self.base / "other", "o.txt")
        self.loose = self.git(self.other, "commit-tree", "HEAD^{tree}", "-p", "HEAD", "-m", "loose").strip()
        self.git(self.other, "push", "-q", "origin", f"{self.loose}:refs/heads/main")
        self.out("add", "other", *self.flags({"--repo": str(self.other), "--sha": self.loose,
                                               "--signature": "disk full", "--status": "merged"}))

    def published(self, origin: Path, repo: Path, name: str) -> Path:
        self.git(self.base, "init", "-q", "--bare", "-b", "main", str(origin))
        repo.mkdir()
        self.git(repo, "init", "-q", "-b", "main")
        self.commit(repo, name, "one\n", "init")
        self.git(repo, "remote", "add", "origin", str(origin))
        self.git(repo, "push", "-q", "-u", "origin", "main")
        self.git(repo, "remote", "set-head", "origin", "main")
        return repo

    def git(self, cwd: Path, *args: str) -> str:
        return subprocess.run(["git", *args], cwd=cwd, env=self.env, capture_output=True, text=True, check=True).stdout

    def commit(self, repo: Path, name: str, text: str, message: str) -> str:
        (repo / name).write_text(text, encoding="utf-8")
        self.git(repo, "add", name)
        self.git(repo, "commit", "-q", "-m", message)
        return self.git(repo, "rev-parse", "HEAD").strip()

    def flags(self, changes: dict[str, str | None]) -> list[str]:
        values = {"--repo": str(self.seed), "--branch": "fix/x", "--sha": self.lint, "--signature": "x",
                  "--status": "staged", **changes}
        return [part for flag, value in values.items() if value is not None for part in (flag, value)]

    def hotfix(self, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(HOTFIX), *args],
            capture_output=True, text=True, env=env or self.env, cwd=self.base, check=False,
        )

    def out(self, *args: str) -> list[str]:
        result = self.hotfix(*args)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.splitlines()

    def rasci(self, *args: str) -> list[str]:
        result = subprocess.run(
            [sys.executable, str(RASCI), *args],
            capture_output=True, text=True, env=self.env, cwd=self.base, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.splitlines()

    def rows(self) -> dict[str, dict]:
        return json.loads((self.root / "rasci.json").read_text(encoding="utf-8"))

    def write_rows(self, rows: dict[str, dict]) -> None:
        (self.root / "rasci.json").write_text(json.dumps(rows), encoding="utf-8")

    def sync(self, repo: Path, task: str, *extra: str) -> subprocess.CompletedProcess:
        return self.hotfix("sync", "--repo", str(repo), "--task", task, *extra)

    def merges(self, result: subprocess.CompletedProcess) -> list[list[str]]:
        self.assertEqual(result.returncode, 0, result.stderr)
        return [line.split("\t")[:2] for line in result.stdout.splitlines()]

    def head(self, repo: Path) -> str:
        return self.git(repo, "rev-parse", "HEAD").strip()

    def contains(self, repo: Path, sha: str) -> bool:
        return subprocess.run(
            ["git", "merge-base", "--is-ancestor", sha, "HEAD"], cwd=repo, env=self.env, capture_output=True,
            check=False,
        ).returncode == 0

    def test_rows_are_register_tasks_with_the_author_as_r_and_a(self):
        rows = self.rows()
        db = rows["hotfix/db"]
        keys = ("common_dir", "origin", "branch", "sha", "pr", "signature", "targets", "stage", "status", "roles")
        self.assertEqual(
            {key: db[key] for key in keys},
            {"common_dir": str(self.seed / ".git"), "origin": str(self.base / "origin"), "branch": "fix/db",
             "sha": self.fix, "pr": 12, "signature": SIGNATURE, "targets": ["test-deploy"], "stage": "merged",
             "status": "done", "roles": {"One": "RA"}},
        )
        self.assertNotIn("repo", db)
        lint = rows["hotfix/lint"]
        self.assertEqual((lint["sha"], lint["stage"], lint["status"], lint["pr"]), (self.lint, "pr", "running", 13))
        self.assertEqual(rows["hotfix/other"]["targets"], [])
        shown = "\n".join(self.rasci("show"))
        self.assertIn("| hotfix/lint | running | - | One |", shown)
        self.assertNotIn("hotfix/db", shown)

    def test_pending_reports_missing_and_open_hotfixes_of_the_repository(self):
        expected = [
            f"missing (merge main)\thotfix/db\tmerged\tfix/db\t{self.fix}\t#12",
            f"open, not merged\thotfix/lint\tpr\tfix/lint\t{self.lint}\t#13",
            "hotfix: 1 missing, 1 open",
        ]
        for repo in (self.work, self.feature):
            with self.subTest(repo=repo.name):
                result = self.hotfix("pending", "--repo", str(repo))
                self.assertEqual((result.returncode, result.stdout.splitlines()), (1, expected), result.stderr)
        self.assertEqual(self.out("pending", "--repo", str(self.seed)), [expected[1], "hotfix: 0 missing, 1 open"])
        self.assertEqual(self.sync(self.work, "work/side").returncode, 0)
        self.assertEqual(self.out("pending", "--repo", str(self.work)), [expected[1], "hotfix: 0 missing, 1 open"])
        copy = self.base / "copy"
        self.git(self.base, "clone", "-q", f"file://{self.origin}", str(copy))
        self.assertEqual(self.out("pending", "--repo", str(copy)), [expected[1], "hotfix: 0 missing, 1 open"])

    def test_a_row_outlives_the_worktree_it_was_recorded_in(self):
        self.git(self.work, "fetch", "-q", "origin")
        tree = self.base / "fixtree"
        self.git(self.work, "worktree", "add", "-q", "-b", "fix/tree", str(tree), "origin/main")
        sha = self.commit(tree, "tree.txt", "tree\n", "fix tree")
        self.out("add", "tree", *self.flags({"--repo": str(tree), "--branch": "fix/tree", "--sha": sha,
                                              "--target": "test-tree"}))
        self.git(tree, "push", "-q", "origin", "HEAD:main")
        self.git(self.work, "worktree", "remove", "--force", str(tree))
        self.assertEqual(self.out("update", "tree", "--status", "merged", "--sha", sha), ["updated hotfix/tree"])
        line = f"missing (merge main)\thotfix/tree\tmerged\tfix/tree\t{sha}\t-"
        copy = self.base / "copy"
        self.git(self.base, "clone", "-q", f"file://{self.origin}", str(copy))
        self.git(copy, "reset", "-q", "--hard", "HEAD~1")
        for repo in (self.work, self.feature, self.seed, copy):
            with self.subTest(repo=repo.name):
                result = self.hotfix("pending", "--repo", str(repo))
                self.assertEqual((result.returncode, result.stderr), (1, ""))
                self.assertIn(line, result.stdout.splitlines())
        result = self.hotfix("void", "--repo", str(copy), "--target", "test-tree")
        self.assertEqual((result.returncode, result.stdout), (3, f"void\thotfix/tree\t{sha}\ttest-tree\n"))

    def test_a_row_of_an_unknown_repository_is_named_on_stderr_and_changes_no_exit_code(self):
        rows = self.rows()
        legacy = {key: value for key, value in rows["hotfix/db"].items() if key not in ("common_dir", "origin")}
        rows["hotfix/legacy"] = {**legacy, "repo": str(self.base / "gone"), "targets": ["test-legacy"]}
        self.write_rows(rows)
        hint = (
            "hotfix/legacy: repository unknown (no origin URL, git dir - gone); record it with "
            f"`hotfix.py update legacy --status merged --sha {self.fix} --repo <clone>`"
        )
        result = self.hotfix("pending", "--repo", str(self.work))
        self.assertEqual(result.returncode, 1)
        self.assertIn(hint, result.stderr)
        self.assertIn(f"missing (merge main)\thotfix/db\tmerged\tfix/db\t{self.fix}\t#12", result.stdout)
        result = self.hotfix("void", "--repo", str(self.work), "--target", "test-lint")
        self.assertEqual((result.returncode, result.stdout), (0, ""))
        self.assertIn(hint, result.stderr)
        self.assertEqual(self.hotfix("void", "--repo", str(self.work), "--target", "test-deploy").returncode, 3)
        self.out("update", "legacy", "--status", "merged", "--sha", self.fix, "--repo", str(self.work))
        result = self.hotfix("pending", "--repo", str(self.work))
        self.assertEqual((result.returncode, result.stderr), (1, ""))
        self.assertIn(f"missing (merge main)\thotfix/legacy\tmerged\tfix/db\t{self.fix}\t#12", result.stdout)

    def test_update_resolves_the_sha_in_the_recorded_git_dir_or_an_explicit_clone(self):
        lone = self.base / "lone"
        self.git(self.base, "clone", "-q", str(self.origin), str(lone))
        sha = self.commit(lone, "lone.txt", "lone\n", "fix lone")
        self.out("add", "lone", *self.flags({"--repo": str(lone), "--branch": "fix/lone", "--sha": sha}))
        self.git(lone, "push", "-q", "origin", "HEAD:main")
        shutil.rmtree(lone)
        self.assertEqual(self.out("update", "lone", "--status", "pr", "--pr", "7"), ["updated hotfix/lone"])
        result = self.hotfix("update", "lone", "--status", "merged", "--sha", sha)
        self.assertEqual(result.returncode, 2)
        self.assertIn(f"hotfix/lone: its git dir {lone / '.git'} is gone; pass --repo", result.stderr)
        result = self.hotfix("update", "lone", "--status", "merged", "--sha", sha, "--repo", str(self.other))
        self.assertEqual(result.returncode, 2)
        self.assertIn("is another repository than hotfix/lone's", result.stderr)
        self.out("update", "lone", "--status", "merged", "--sha", sha, "--repo", str(self.seed))
        row = self.rows()["hotfix/lone"]
        self.assertEqual((row["common_dir"], row["stage"], row["sha"], row["pr"]), (str(self.seed / ".git"), "merged", sha, 7))

    def squash_merged(self) -> tuple[str, str]:
        self.git(self.seed, "switch", "-q", "-c", "fix/sq")
        branch_sha = self.commit(self.seed, "sq.txt", "sq\n", "fix sq")
        self.git(self.seed, "switch", "-q", "main")
        self.out("add", "sq", *self.flags({"--branch": "fix/sq", "--sha": branch_sha, "--status": "pr",
                                            "--target": "test-sq"}))
        self.git(self.seed, "merge", "-q", "--squash", "fix/sq")
        self.git(self.seed, "commit", "-q", "-m", "fix sq, squashed")
        self.git(self.seed, "push", "-q", "origin", "main")
        return branch_sha, self.head(self.seed)

    def test_merged_needs_the_sha_as_it_sits_on_the_default_branch(self):
        branch_sha, squashed = self.squash_merged()
        result = self.hotfix("update", "sq", "--status", "merged")
        self.assertEqual(result.returncode, 2)
        self.assertIn("--status merged needs --sha", result.stderr)
        for args in (
            ("update", "sq", "--status", "merged", "--sha", branch_sha),
            ("add", "sq2", *self.flags({"--branch": "fix/sq", "--sha": branch_sha, "--status": "merged"})),
        ):
            with self.subTest(args=args[0]):
                result = self.hotfix(*args)
                self.assertEqual(result.returncode, 2)
                self.assertIn(f"--sha {branch_sha} is not on origin/main", result.stderr)
        self.assertEqual(self.rows()["hotfix/sq"]["stage"], "pr")
        self.out("update", "sq", "--status", "merged", "--sha", squashed)
        self.assertEqual(self.rows()["hotfix/sq"]["sha"], squashed)

    def test_a_merged_sha_off_the_default_branch_warns_and_never_voids(self):
        branch_sha, squashed = self.squash_merged()
        self.out("update", "sq", "--status", "merged", "--sha", squashed)
        rows = self.rows()
        rows["hotfix/sq"]["sha"] = branch_sha
        self.write_rows(rows)
        for _ in range(2):
            self.assertEqual(self.sync(self.work, "work/side").returncode, 0)
            result = self.hotfix("void", "--repo", str(self.work), "--target", "test-sq")
            self.assertEqual((result.returncode, result.stdout), (0, ""))
            self.assertIn(f"hotfix/sq: {branch_sha} is not on origin/main", result.stderr)
        result = self.hotfix("pending", "--repo", str(self.work))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"not on origin/main\thotfix/sq\tmerged\tfix/sq\t{branch_sha}\t-", result.stdout.splitlines())

    def test_match_finds_hotfixes_by_their_signature(self):
        origin = str(self.base / "origin")
        self.assertEqual(
            self.out("match", "--line", "psql: connection refused to db at port 5432"),
            [f"hotfix/db\tmerged\tfix/db\t{self.fix}\t#12\t{origin}"],
        )
        self.assertEqual(
            self.out("match", "--line", "ruff: E501 line too long", "--repo", str(self.work)),
            [f"hotfix/lint\tpr\tfix/lint\t{self.lint}\t#13\t{origin}"],
        )
        result = self.hotfix("match", "--line", "all green")
        self.assertEqual((result.returncode, result.stdout), (1, "hotfix: no signature matches\n"))
        foreign = f"hotfix/other\tmerged\tfix/x\t{self.loose}\t-\t{self.base / 'other'}"
        result = self.hotfix("match", "--line", "disk full on /var", "--repo", str(self.work))
        self.assertEqual(
            (result.returncode, result.stdout.splitlines()),
            (1, [f"foreign\t{foreign}", "hotfix: no signature of this repository matches"]),
        )
        self.assertEqual(self.out("match", "--line", "disk full on /var", "--repo", str(self.other)), [foreign])

    def test_add_refuses_only_a_signature_that_backtracks_without_end(self):
        for pattern, reason in (("(a+)+", "repeats a group that repeats itself"),
                                ("(a|a)*b", "repeats an alternation whose branches can start alike")):
            with self.subTest(pattern=pattern):
                result = self.hotfix("add", "nest", *self.flags({"--signature": pattern}))
                self.assertEqual(result.returncode, 2)
                self.assertIn(reason, result.stderr)
        self.out("add", "plain", *self.flags({"--signature": r"(ab)+ timeout \d+"}))
        self.out("add", "address", *self.flags({"--signature": r"no route to (\d{1,3}\.){3}\d{1,3}"}))

    def test_match_names_a_signature_that_runs_too_long_and_searches_the_rest(self):
        rows = self.rows()
        rows["hotfix/slow"] = {**rows["hotfix/lint"], "signature": "(x+x+)+y"}
        rows["hotfix/tail"] = {**rows["hotfix/lint"], "signature": "x{40}"}
        self.write_rows(rows)
        began = time.monotonic()
        result = self.hotfix("match", "--line", "ruff: E501 " + "x" * 40, "--repo", str(self.work))
        self.assertLess(time.monotonic() - began, 30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), [f"{task}\tpr\tfix/lint\t{self.lint}\t#13\t{self.base / 'origin'}"
                                                      for task in ("hotfix/lint", "hotfix/tail")])
        self.assertIn("hotfix/slow: signature '(x+x+)+y' still searched this line at the 3 s deadline, skipped",
                      result.stderr)

    def test_void_only_for_a_missing_merged_hotfix_of_the_targets(self):
        result = self.hotfix("void", "--repo", str(self.work), "--target", "test", "--target", "test-deploy")
        self.assertEqual((result.returncode, result.stdout), (3, f"void\thotfix/db\t{self.fix}\ttest-deploy\n"))
        result = self.hotfix("void", "--repo", str(self.work), "--target", "test-lint")
        self.assertEqual((result.returncode, result.stdout), (0, ""))
        self.assertEqual(self.sync(self.work, "work/side").returncode, 0)
        self.assertEqual(self.hotfix("void", "--repo", str(self.work), "--target", "test-deploy").returncode, 0)

        self.git(self.seed, "switch", "-q", "-c", "fix/any")
        anything = self.commit(self.seed, "any.txt", "any\n", "fix any")
        self.git(self.seed, "push", "-q", "origin", "HEAD:main")
        self.out("add", "any", *self.flags({"--branch": "fix/any", "--sha": anything, "--status": "merged"}))
        for target in ("test-lint", "deploy"):
            with self.subTest(target=target):
                result = self.hotfix("void", "--repo", str(self.work), "--target", target)
                self.assertEqual((result.returncode, result.stdout), (3, f"void\thotfix/any\t{anything}\tall targets\n"))

    def test_test_star_targets_void_the_umbrella_and_a_deploy_needs_deploy(self):
        result = self.hotfix("void", "--repo", str(self.work), "--target", "test")
        self.assertEqual((result.returncode, result.stdout), (3, f"void\thotfix/db\t{self.fix}\ttest-deploy\n"))
        self.assertEqual(self.hotfix("void", "--repo", str(self.work), "--target", "deploy").returncode, 0)
        self.git(self.seed, "switch", "-q", "-c", "fix/deploy")
        rollout = self.commit(self.seed, "deploy.txt", "deploy\n", "fix deploy")
        self.git(self.seed, "push", "-q", "origin", "HEAD:main")
        self.out("add", "deploy", *self.flags({"--branch": "fix/deploy", "--sha": rollout, "--status": "merged",
                                                "--target": "deploy"}))
        result = self.hotfix("void", "--repo", str(self.work), "--target", "deploy")
        self.assertEqual((result.returncode, result.stdout), (3, f"void\thotfix/deploy\t{rollout}\tdeploy\n"))
        result = self.hotfix("void", "--repo", str(self.work), "--target", "test-lint")
        self.assertEqual((result.returncode, result.stdout), (0, ""))

    def test_sync_merges_main_then_the_base_chain_and_skips_contained_refs(self):
        hooks = self.work / ".git" / "hooks"
        for hook in ("pre-merge-commit", "commit-msg"):
            (hooks / hook).write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
            (hooks / hook).chmod(0o755)
        result = self.sync(self.work, "work/side")
        self.assertEqual(self.merges(result), [["merged", "origin/main"], ["merged", "line"]])
        self.assertEqual(result.stdout.splitlines()[1].split("\t")[2], self.head(self.work))
        for name in ("db.txt", "line2.txt", "side.txt"):
            self.assertTrue((self.work / name).is_file(), name)
        self.assertEqual(self.git(self.work, "rev-list", "--count", "--merges", "HEAD").strip(), "2")
        self.assertEqual(self.merges(self.sync(self.work, "work/side")), [["contained", "origin/main"],
                                                                            ["contained", "line"]])

        result = self.sync(self.feature, "work/feature")
        self.assertEqual((result.returncode, result.stdout), (0, f"merged\torigin/main\t{self.fix}\n"), result.stderr)

    def fake_flow(self, flow: dict) -> None:
        fake = self.base / "bin" / "pkgmgr"
        fake.parent.mkdir(exist_ok=True)
        fake.write_text(f"#!/bin/sh\nprintf '%s' '{json.dumps(flow)}'\n", encoding="utf-8")
        fake.chmod(0o755)
        self.env["PATH"] = f"{fake.parent}:/usr/bin:/bin"
        (self.work / ".git" / "pkgmgr").mkdir()
        (self.work / ".git" / "pkgmgr" / "flow.yml").write_text("read by pkgmgr only\n", encoding="utf-8")

    def test_sync_starts_no_pkgmgr_without_a_flow_file(self):
        fake = self.base / "bin" / "pkgmgr"
        fake.parent.mkdir()
        fake.write_text(f"#!/bin/sh\ntouch {self.base / 'pkgmgr-ran'}\nexit 2\n", encoding="utf-8")
        fake.chmod(0o755)
        self.env["PATH"] = f"{fake.parent}:/usr/bin:/bin"
        self.assertEqual(self.merges(self.sync(self.work, "work/side")), [["merged", "origin/main"], ["merged", "line"]])
        self.assertFalse((self.base / "pkgmgr-ran").exists())

    def test_sync_merges_the_pull_list_of_the_merge_flow_after_the_base_chain(self):
        self.commit(self.feature, "feat.txt", "feat\n", "feature work")
        self.fake_flow({"source": "file", "pull": ["origin/main", "feature"], "push": ["line"], "warnings": []})
        result = self.sync(self.work, "work/side")
        self.assertEqual(self.merges(result), [["merged", "origin/main"], ["merged", "line"], ["merged", "feature"]])
        self.assertTrue((self.work / "feat.txt").is_file())

    def test_sync_refuses_an_invalid_merge_flow_before_any_merge(self):
        self.fake_flow({"source": "invalid", "pull": [], "push": [], "warnings": ["pkgmgr/flow.yml ignored: not a mapping"]})
        before = self.head(self.work)
        result = self.sync(self.work, "work/side")
        self.assertEqual((result.returncode, result.stdout), (2, ""))
        self.assertIn("is invalid", result.stderr)
        self.assertIn("not a mapping", result.stderr)
        self.assertEqual(self.head(self.work), before)

    def test_the_base_chain_follows_only_open_rows_of_this_repository(self):
        self.git(self.other, "branch", "line")
        gone = self.base / "gone"
        self.rasci("set", "work/gui", "--branch", "line", "--base", "feature", "--workdir", str(self.other))
        self.rasci("set", "work/old", "--branch", "line", "--base", "fix/db", "--workdir", str(self.work),
                   "--status", "done")
        self.rasci("set", "work/ghost", "--branch", "line", "--base", "feature", "--workdir", str(gone))
        result = self.sync(self.work, "work/side")
        self.assertEqual(self.merges(result), [["merged", "origin/main"], ["merged", "line"]])
        self.assertIn(f"work/ghost: workdir {gone} is no git repository, its base is not followed", result.stderr)

    def test_a_chain_row_without_workdir_counts_when_its_branch_resolves_here(self):
        self.rasci("set", "work/line", "--workdir", "", "--base", "feature")
        self.assertEqual(self.merges(self.sync(self.work, "work/side")),
                         [["merged", "origin/main"], ["merged", "line"], ["contained", "feature"]])
        self.rasci("set", "work/up", "--branch", "nowhere", "--base", "main")
        self.rasci("set", "work/side", "--base", "nowhere")
        before = self.head(self.work)
        result = self.sync(self.work, "work/side")
        self.assertEqual((result.returncode, result.stdout), (2, ""))
        self.assertIn("work/up records no workdir and its branch nowhere resolves neither as nowhere nor as "
                      f"origin/nowhere in {self.work}; record it with `rasci.py set work/up --workdir <dir>`",
                      result.stderr)
        self.assertEqual(self.head(self.work), before)

    def test_sync_without_an_origin_merges_local_branches_and_skips_the_fetch(self):
        lone = self.base / "lone"
        lone.mkdir()
        self.git(lone, "init", "-q", "-b", "main")
        self.commit(lone, "a.txt", "a\n", "init")
        self.git(lone, "switch", "-q", "-c", "line")
        self.commit(lone, "l1.txt", "l1\n", "line one")
        self.git(lone, "switch", "-q", "-c", "feat")
        self.commit(lone, "f.txt", "f\n", "feat")
        self.git(lone, "switch", "-q", "line")
        self.commit(lone, "l2.txt", "l2\n", "line two")
        self.git(lone, "switch", "-q", "main")
        self.commit(lone, "m.txt", "m\n", "main two")
        self.git(lone, "switch", "-q", "feat")
        self.rasci("set", "work/lone", "--branch", "feat", "--base", "line", "--workdir", str(lone))
        self.rasci("set", "work/loneline", "--branch", "line", "--base", "main", "--workdir", str(lone))
        result = self.sync(lone, "work/lone")
        self.assertEqual(result.returncode, 2)
        self.assertIn(f"{lone} has no origin remote; pass --default <branch>", result.stderr)
        self.assertEqual(self.merges(self.sync(lone, "work/lone", "--default", "main")),
                         [["merged", "main"], ["merged", "line"]])
        for name in ("m.txt", "l2.txt", "f.txt"):
            self.assertTrue((lone / name).is_file(), name)

    def test_relative_origins_resolve_against_each_worktree(self):
        clones = []
        for name in ("p1", "p2"):
            clone = self.base / name / "app"
            clone.mkdir(parents=True)
            self.git(clone, "init", "-q", "-b", "main")
            self.git(clone, "remote", "add", "origin", "../up")
            clones.append((clone, self.commit(clone, "a.txt", f"{name}\n", "init")))
        (one, sha), (two, _) = clones
        self.out("add", "rel", *self.flags({"--repo": str(one), "--branch": "fix/rel", "--sha": sha,
                                             "--signature": "relative boom"}))
        self.assertEqual(self.rows()["hotfix/rel"]["origin"], str(self.base / "p1" / "up"))
        found = f"hotfix/rel\tstaged\tfix/rel\t{sha}\t-\t{self.base / 'p1' / 'up'}"
        self.assertEqual(self.out("match", "--line", "relative boom", "--repo", str(one)), [found])
        result = self.hotfix("match", "--line", "relative boom", "--repo", str(two))
        self.assertEqual((result.returncode, result.stdout.splitlines()[0]), (1, f"foreign\t{found}"))

    def test_another_origin_in_the_same_git_dir_is_another_repository(self):
        lint = f"hotfix/lint\tpr\tfix/lint\t{self.lint}\t#13\t{self.base / 'origin'}"
        self.assertEqual(self.out("match", "--line", "ruff: E501", "--repo", str(self.seed)), [lint])
        self.git(self.seed, "remote", "set-url", "origin", str(self.base / "elsewhere.git"))
        result = self.hotfix("match", "--line", "ruff: E501", "--repo", str(self.seed))
        self.assertEqual((result.returncode, result.stdout.splitlines()[0]), (1, f"foreign\t{lint}"))

    def test_origins_apply_insteadof_and_fold_case_on_caseless_hosts(self):
        first = self.base / "gh1"
        first.mkdir()
        self.git(first, "init", "-q", "-b", "main")
        self.git(first, "config", "url.https://github.com/.insteadOf", "gh:")
        self.git(first, "remote", "add", "origin", "gh:Org/App.git")
        sha = self.commit(first, "a.txt", "a\n", "init")
        self.out("add", "gh", *self.flags({"--repo": str(first), "--branch": "fix/gh", "--sha": sha,
                                            "--signature": "github boom"}))
        self.assertEqual(self.rows()["hotfix/gh"]["origin"], "github.com/org/app")
        second = self.base / "gh2"
        self.git(self.base, "clone", "-q", str(first), str(second))
        self.git(second, "remote", "set-url", "origin", "https://GitHub.com/ORG/app/")
        self.assertEqual(self.out("match", "--line", "github boom", "--repo", str(second)),
                         [f"hotfix/gh\tstaged\tfix/gh\t{sha}\t-\tgithub.com/org/app"])

    def test_pending_filters_by_targets_as_void_does(self):
        lint = f"open, not merged\thotfix/lint\tpr\tfix/lint\t{self.lint}\t#13"
        result = self.hotfix("pending", "--repo", str(self.work), "--target", "test-lint")
        self.assertEqual((result.returncode, result.stdout.splitlines()), (0, [lint, "hotfix: 0 missing, 1 open"]))
        result = self.hotfix("pending", "--repo", str(self.work), "--target", "deploy")
        self.assertEqual((result.returncode, result.stdout.splitlines()), (0, ["hotfix: 0 missing, 0 open"]))
        result = self.hotfix("pending", "--repo", str(self.work), "--target", "test")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn(f"missing (merge main)\thotfix/db\tmerged\tfix/db\t{self.fix}\t#12", result.stdout)

    def test_a_base_merges_from_whichever_of_origin_and_local_contains_the_other(self):
        self.git(self.work, "push", "-q", "origin", "line")
        upstream = self.git(self.work, "commit-tree", "line^{tree}", "-p", "line", "-m", "upstream").strip()
        self.git(self.work, "push", "-q", "origin", f"{upstream}:refs/heads/line")
        self.assertEqual(self.merges(self.sync(self.work, "work/side")),
                         [["merged", "origin/main"], ["merged", "origin/line"]])
        self.assertTrue(self.contains(self.work, upstream))

        ahead = self.git(self.work, "commit-tree", f"{upstream}^{{tree}}", "-p", upstream, "-m", "ahead").strip()
        self.git(self.work, "update-ref", "refs/heads/line", ahead)
        self.assertEqual(self.merges(self.sync(self.work, "work/side")),
                         [["contained", "origin/main"], ["merged", "line"]])

        apart = self.git(self.work, "commit-tree", f"{upstream}^{{tree}}", "-p", upstream, "-m", "apart").strip()
        self.git(self.work, "push", "-q", "origin", f"{apart}:refs/heads/line")
        before = self.head(self.work)
        result = self.sync(self.work, "work/side")
        self.assertEqual((result.returncode, result.stdout), (2, ""))
        self.assertIn("line and origin/line have diverged", result.stderr)
        self.assertEqual(self.head(self.work), before)

        self.git(self.work, "branch", "-D", "line")
        self.assertEqual(self.merges(self.sync(self.work, "work/side")),
                         [["contained", "origin/main"], ["merged", "origin/line"]])
        self.assertTrue(self.contains(self.work, apart))

    def test_sync_aborts_the_first_conflicting_merge_with_exit_4(self):
        line = self.base / "line"
        self.git(self.work, "worktree", "add", "-q", str(line), "line")
        self.commit(line, "side.txt", "other\n", "clashing line work")
        result = self.sync(self.work, "work/side")
        self.assertEqual(result.returncode, 4, result.stderr)
        self.assertEqual([row.split("\t")[0] for row in result.stdout.splitlines()], ["merged", "conflict"])
        self.assertEqual(result.stdout.splitlines()[1], "conflict\tline\tside.txt")
        self.assertIn("merging line conflicts in side.txt; merge aborted", result.stderr)
        self.assertFalse((self.work / ".git" / "MERGE_HEAD").exists())
        self.assertEqual(self.git(self.work, "status", "--porcelain", "--untracked-files=no"), "")
        self.assertTrue(self.contains(self.work, self.fix))
        self.assertFalse(self.contains(self.work, self.head(line)))

    def test_a_merge_failing_without_a_conflict_exits_2_with_gits_message(self):
        before = self.head(self.work)
        (self.work / "db.txt").write_text("untracked\n", encoding="utf-8")
        result = self.sync(self.work, "work/side")
        self.assertEqual((result.returncode, result.stdout), (2, ""))
        self.assertIn("untracked working tree files would be overwritten by merge", result.stderr)
        (self.work / "db.txt").unlink()
        self.git(self.work, "config", "commit.gpgsign", "true")
        self.git(self.work, "config", "gpg.program", "false")
        result = self.sync(self.work, "work/side")
        self.assertEqual((result.returncode, result.stdout), (2, ""))
        self.assertIn("gpg failed to sign the data", result.stderr)
        self.assertFalse((self.work / ".git" / "MERGE_HEAD").exists())
        self.assertEqual(self.git(self.work, "status", "--porcelain", "--untracked-files=no"), "")
        self.assertEqual(self.head(self.work), before)

    def test_sync_needs_the_tasks_branch_checked_out(self):
        before = self.head(self.work)
        self.git(self.work, "switch", "-q", "--detach")
        result = self.sync(self.work, "work/side")
        self.assertEqual(result.returncode, 2)
        self.assertIn(f"{self.work} has a detached HEAD checked out, work/side works on sidetree", result.stderr)
        self.git(self.work, "switch", "-q", "line")
        line = self.head(self.work)
        result = self.sync(self.work, "work/side")
        self.assertEqual(result.returncode, 2)
        self.assertIn(f"{self.work} has line checked out, work/side works on sidetree", result.stderr)
        self.assertEqual((self.git(self.work, "rev-parse", "sidetree").strip(), self.head(self.work)), (before, line))
        self.rasci("set", "work/loose")
        self.assertIn("work/loose records no branch", self.sync(self.work, "work/loose").stderr)

    def test_sync_refuses_while_a_gate_or_a_busy_process_holds_the_worktree(self):
        before = self.head(self.work)
        git_dir = Path(self.git(self.work, "rev-parse", "--absolute-git-dir").strip())
        with open(git_dir / RUN_LOCK, "a", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            result = self.sync(self.work, "work/side")
        self.assertEqual(result.returncode, 2)
        self.assertIn(f"a gate.py run or hold holds {self.work}", result.stderr)
        config = self.base / "config.json"
        config.write_text(json.dumps({"busy_processes": ["sleep"]}), encoding="utf-8")
        self.env["AGENTS_COUNCIL_CONFIG"] = str(config)
        deploy = subprocess.Popen(["sleep", "60"], cwd=self.work)
        self.addCleanup(deploy.wait)
        self.addCleanup(deploy.kill)
        result = self.sync(self.work, "work/side")
        self.assertEqual(result.returncode, 2)
        self.assertIn(f"a busy process (watch.py busy_processes) runs in {self.work}", result.stderr)
        self.assertEqual(self.head(self.work), before)
        deploy.kill()
        deploy.wait()
        self.assertEqual(self.sync(self.work, "work/side").returncode, 0)

    def wait_for(self, path: Path, process: subprocess.Popen) -> None:
        deadline = time.monotonic() + 30
        while not path.exists():
            if process.poll() is not None:
                self.fail(f"exited {process.returncode} before {path} appeared: {process.stderr.read()}")
            self.assertLess(time.monotonic(), deadline, f"{path} never appeared")
            time.sleep(0.05)

    def kill(self, pid: int) -> None:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)

    def lock_free(self, lock: Path) -> bool:
        with open(lock, "a", encoding="utf-8") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return False
            return True

    def test_sync_refuses_while_an_orphan_of_gate_py_hold_runs_where_no_process_check_sees_it(self):
        before = self.head(self.work)
        pid_file, cwd_file = self.base / "deploy.pid", self.base / "deploy.cwd"
        holder = subprocess.Popen(
            [sys.executable, str(GATE), "hold", "--repo", str(self.work), "--",
             "sh", "-c", f"pwd > {cwd_file}; echo $$ > {pid_file}.tmp; mv {pid_file}.tmp {pid_file}; exec sleep 60"],
            env=self.env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
        )
        self.addCleanup(holder.stderr.close)
        self.addCleanup(holder.wait)
        self.addCleanup(holder.kill)
        self.wait_for(pid_file, holder)
        deploy = int(pid_file.read_text(encoding="utf-8"))
        self.addCleanup(self.kill, deploy)
        self.assertEqual(cwd_file.read_text(encoding="utf-8").strip(), str(self.work))
        holder.kill()
        holder.wait()
        result = self.sync(self.work, "work/side")
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn(f"a gate.py run or hold holds {self.work} (pid {holder.pid}: "
                      f"gate.py hold --repo {self.work} -- sh", result.stderr)
        self.assertEqual(self.head(self.work), before)
        lock = Path(self.git(self.work, "rev-parse", "--absolute-git-dir").strip()) / RUN_LOCK
        os.kill(deploy, signal.SIGKILL)
        deadline = time.monotonic() + 30
        while not self.lock_free(lock):
            self.assertLess(time.monotonic(), deadline, "the killed deploy kept the lock")
            time.sleep(0.05)
        self.assertEqual(self.sync(self.work, "work/side").returncode, 0)

    def test_sync_fetches_before_the_locks_and_holds_them_through_every_merge_and_abort(self):
        line = self.base / "line"
        self.git(self.work, "worktree", "add", "-q", str(line), "line")
        self.commit(line, "side.txt", "other\n", "clashing line work")
        lock = Path(self.git(self.work, "rev-parse", "--absolute-git-dir").strip()) / RUN_LOCK
        probe, calls = self.base / "probe.py", self.base / "lock-states.log"
        probe.write_text(PROBE, encoding="utf-8")
        wrapper = self.base / "bin" / "git"
        wrapper.parent.mkdir()
        real = shutil.which("git", path=self.env["PATH"])
        wrapper.write_text(
            "#!/bin/sh\n"
            f"case \" $* \" in *\" fetch \"*|*\" merge \"*) {sys.executable} {probe} {lock} \"$*\" >> {calls} ;; esac\n"
            f"exec {real} \"$@\"\n",
            encoding="utf-8",
        )
        wrapper.chmod(0o755)
        traced = {**self.env, "PATH": f"{wrapper.parent}:{self.env['PATH']}"}
        result = self.hotfix("sync", "--repo", str(self.work), "--task", "work/side", env=traced)
        self.assertEqual(result.returncode, 4, result.stderr)
        states = [entry.split(" ", 1) for entry in calls.read_text(encoding="utf-8").splitlines()]
        commands = [command.split(" ")[2] + (" --abort" if command.endswith("--abort") else "") for _, command in states]
        self.assertEqual(commands, ["fetch", "merge", "merge", "merge --abort"])
        self.assertEqual([state for state, _ in states], ["free", "held", "held", "held"], states)
        self.assertTrue(self.lock_free(lock))
        self.assertIn(f"\thotfix.py sync --repo {self.work} --task work/side\n",
                      lock.with_name(SYNC_LOCK).read_text(encoding="utf-8"))

    def test_sync_and_update_keep_git_maintenance_off(self):
        calls = self.base / "git-calls.log"
        wrapper = self.base / "bin" / "git"
        wrapper.parent.mkdir()
        real = shutil.which("git", path=self.env["PATH"])
        wrapper.write_text(f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> {calls}\nexec {real} \"$@\"\n", encoding="utf-8")
        wrapper.chmod(0o755)
        traced = {**self.env, "PATH": f"{wrapper.parent}:{self.env['PATH']}"}
        self.assertEqual(self.hotfix("sync", "--repo", str(self.work), "--task", "work/side", env=traced).returncode, 0)
        result = self.hotfix("update", "lint", "--status", "merged", "--sha", self.fix, env=traced)
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = calls.read_text(encoding="utf-8").splitlines()
        self.assertTrue(any(line.startswith("-c maintenance.auto=false merge ") for line in lines), lines)
        self.assertEqual([line for line in lines if not line.startswith("-c maintenance.auto=false ")], [])
        fetches = [line for line in lines if " fetch " in f" {line} "]
        self.assertEqual(len(fetches), 2, lines)
        self.assertTrue(all("--no-auto-maintenance" in line for line in fetches), fetches)

    def test_sync_needs_a_clean_tree_and_names_the_default_branch_explicitly(self):
        before = self.head(self.work)
        (self.work / "side.txt").write_text("changed\n", encoding="utf-8")
        result = self.sync(self.work, "work/side")
        self.assertEqual(result.returncode, 2)
        self.assertIn("tracked files are dirty, commit them first: side.txt", result.stderr)
        self.assertEqual(self.head(self.work), before)
        (self.work / "side.txt").write_text("side\n", encoding="utf-8")
        (self.work / "notes.txt").write_text("untracked\n", encoding="utf-8")

        self.git(self.work, "remote", "set-head", "origin", "-d")
        result = self.sync(self.work, "work/side")
        self.assertEqual(result.returncode, 2)
        self.assertIn("pass --default <branch>", result.stderr)
        self.assertEqual(self.head(self.work), before)
        self.assertEqual(self.sync(self.work, "work/side", "--default", "main").returncode, 0)
        self.git(self.work, "remote", "set-head", "origin", "main")
        result = self.sync(self.work, "work/side", "--default", "line")
        self.assertEqual(result.returncode, 2)
        self.assertIn("origin/HEAD names main, --default says line", result.stderr)

    def test_invalid_input_exits_2_and_leaves_the_register_alone(self):
        register = self.root / "rasci.json"
        before = register.read_text(encoding="utf-8")
        for args in (
            ("add", "Bad Slug", *self.flags({})),
            ("add", "db", *self.flags({})),
            ("add", "x", *self.flags({"--repo": "seed"})),
            ("add", "x", *self.flags({"--repo": str(self.base / "home")})),
            ("add", "x", *self.flags({"--sha": "HEAD"})),
            ("add", "x", *self.flags({"--sha": "0" * 40})),
            ("add", "x", *self.flags({"--signature": "("})),
            ("add", "x", *self.flags({"--signature": " "})),
            ("add", "x", *self.flags({"--signature": "(a+)+"})),
            ("add", "x", *self.flags({"--branch": "a..b"})),
            ("add", "x", *self.flags({"--status": "done"})),
            ("add", "x", *self.flags({"--status": None})),
            ("add", "x", *self.flags({"--pr": "0"})),
            ("add", "x", *self.flags({"--target": "a b"})),
            ("update", "none", "--status", "pr"),
            ("update", "db", "--status", "merged", "--sha", "zzz"),
            ("update", "db", "--status", "merged"),
            ("update", "db", "--status", "pr", "--repo", "seed"),
            ("update", "db"),
            ("pending", "--repo", str(self.base / "absent")),
            ("pending", "--repo", str(self.base / "home")),
            ("match", "--line", "x", "--repo", str(self.base / "absent")),
            ("void", "--repo", str(self.work)),
            ("match",),
            ("sync", "--repo", str(self.work), "--task", "work/none"),
        ):
            with self.subTest(args=args):
                self.assertEqual(self.hotfix(*args).returncode, 2)
        self.assertEqual(register.read_text(encoding="utf-8"), before)

        self.rasci("set", "work/twin", "--branch", "line", "--base", "feature", "--workdir", str(self.feature))
        result = self.sync(self.work, "work/side")
        self.assertEqual(result.returncode, 2)
        self.assertIn("branch line has several bases in the register: work/line=main, work/twin=feature", result.stderr)


if __name__ == "__main__":
    unittest.main()
