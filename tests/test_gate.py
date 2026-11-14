"""Exercise gate.py: static `make test*` listing, runs judged per target, hotfix voids, and the per-HEAD gate."""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import importlib.util
import io
import json
import os
import pwd
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import ClassVar
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "skills" / "kvb-check-gate" / "scripts" / "gate.py"
HOTFIX = REPO_ROOT / "skills" / "kvb-git-hotfix" / "scripts" / "hotfix.py"
RUN_LOCK = "kvb-gate-run.lock"
SYNC_LOCK = "kvb-gate-sync.lock"
STATE = "kvb-gate.json"
LOCK_BASE = Path("/tmp/agents-locks")
EARLIER_GATE = (
    "import fcntl, sys\n"
    "with open(sys.argv[1], 'a', encoding='utf-8') as lock:\n"
    "    try:\n"
    "        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
    "    except BlockingIOError:\n"
    "        print('held')\n"
    "    else:\n"
    "        print('free')\n"
)
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
MARKING = {"Makefile": ".PHONY: test\ntest:\n\t@touch \"$$MARKER\"\n"}
VOID = {"Makefile": ".PHONY: test test-a test-b\ntest:\n\t@echo all\ntest-a:\n\t@echo a\ntest-b:\n\t@echo b\n"}
ORACLE = {"Makefile": ".PHONY: test test-oracle\ntest:\n\t@echo all\ntest-oracle:\n\t@echo oracle\n"}
FAILED = ("--fail-regex", r"FAILED TARGETS: \S")
SYNC_HOLDER = "4242\thotfix.py sync --task t\n"
COUNTING_CHILD = (
    "import os, signal, sys, time\n"
    "got = []\n"
    "signal.signal(signal.SIGINT, lambda signum, frame: got.append(signum))\n"
    "with open(sys.argv[1] + '.tmp', 'w', encoding='utf-8') as out:\n"
    "    out.write(str(os.getpid()))\n"
    "os.replace(sys.argv[1] + '.tmp', sys.argv[1])\n"
    "while not got:\n"
    "    time.sleep(0.05)\n"
    "time.sleep(0.5)\n"
    "sys.exit(10 + len(got))\n"
)


def load_gate() -> object:
    spec = importlib.util.spec_from_file_location("gate_under_test", SCRIPT)
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    return gate


def lock_dir(worktree: Path) -> Path:
    return LOCK_BASE / hashlib.sha256(os.fsencode(str(worktree))).hexdigest()[:16]


def drop_lock_dir(path: Path) -> None:
    if path.is_symlink():
        path.unlink()
    else:
        shutil.rmtree(path, ignore_errors=True)


class GateCase(unittest.TestCase):
    files: ClassVar[dict[str, str]]

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.repo = self.root / "repo"
        self.logs = self.root / "logs"
        self.repo.mkdir()
        self.addCleanup(drop_lock_dir, lock_dir(self.repo))
        self.env = {
            "PATH": "/usr/bin:/bin",
            "HOME": tmp.name,
            "AGENTS_COUNCIL_ROOT": str(self.root / "council"),
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


class TestExcluded(GateCase):
    files = ORACLE

    def call(self, gate: object, command: str, **fields: object) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, self.env, clear=True), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = getattr(gate, command)(argparse.Namespace(repo=str(self.repo), **fields))
            except SystemExit as stop:
                code = stop.code
        return code, out.getvalue(), err.getvalue()

    def exclude(self, gate: object, listed: object) -> None:
        gate.CONFIG.write_text(json.dumps({"gate_excluded_targets": listed}), encoding="utf-8")

    def test_an_excluded_target_is_shown_excluded_never_required_and_refused_by_run(self):
        gate = load_gate()
        gate.CONFIG = self.root / "config.json"
        run = {"log_dir": str(self.logs), "fail_regex": None}
        self.assertEqual(self.call(gate, "cmd_run", target=["test"], **run)[0], 0)
        code, out, _ = self.call(gate, "cmd_status", json=True)
        self.assertEqual((code, json.loads(out)["open"]), (1, ["missing: test-oracle"]))
        self.exclude(gate, ["test-oracle"])
        code, out, _ = self.call(gate, "cmd_status", json=True)
        after = json.loads(out)
        self.assertEqual((code, after["gate"]), (0, "green"))
        self.assertEqual({r["target"]: r["status"] for r in after["targets"]}, {"test": "green", "test-oracle": "excluded"})
        self.assertEqual(self.call(gate, "cmd_status", json=False)[1].splitlines()[-1], f"gate: green (excluded: test-oracle by {gate.CONFIG})")
        code, _, err = self.call(gate, "cmd_run", target=["test-oracle"], **run)
        self.assertEqual(code, 2)
        self.assertIn("excluded from every gate by gate_excluded_targets", err)
        self.exclude(gate, ["test", "test-oracle"])
        code, out, _ = self.call(gate, "cmd_status", json=True)
        self.assertEqual((code, json.loads(out)["open"]), (1, ["every make test* target is excluded"]))
        self.exclude(gate, "test-oracle")
        self.assertEqual(self.call(gate, "cmd_status", json=False)[0], 2)

    def test_the_exclusion_list_ignores_home_and_environment_overrides(self):
        with mock.patch.dict(os.environ, {"HOME": str(self.root), "AGENTS_COUNCIL_CONFIG": str(self.root / "config.json")}):
            gate = load_gate()
        self.assertEqual(gate.CONFIG, Path(pwd.getpwuid(os.getuid()).pw_dir) / ".claude" / "agents-council" / "config.json")


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


class TestHotfixes(GateCase):
    files = VOID

    def setUp(self):
        super().setUp()
        origin = self.root / "origin.git"
        self._git("init", "-q", "--bare", "-b", "main", str(origin))
        self._git("remote", "add", "origin", str(origin))
        self._git("push", "-q", "-u", "origin", "main")
        self._git("remote", "set-head", "origin", "main")

    def hotfix(self, slug: str, status: str, *targets: str) -> str:
        parent = "refs/remotes/origin/main" if status == "merged" else "HEAD"
        sha = self._git("commit-tree", "HEAD^{tree}", "-p", parent, "-m", slug).strip()
        if status == "merged":
            self._git("push", "-q", "origin", f"{sha}:refs/heads/main")
        flags = [part for target in targets for part in ("--target", target)]
        result = subprocess.run(
            [sys.executable, str(HOTFIX), "add", slug, "--repo", str(self.repo), "--branch", f"fix/{slug}",
             "--sha", sha, "--signature", "boom", "--status", status, "--session", "t", *flags],
            env=self.env, capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return sha

    def results(self) -> dict[str, str]:
        return {r["target"]: r["status"] for r in self.status(self.repo)[1]["targets"]}

    def test_a_hotfix_for_any_remaining_target_voids_the_run_before_it_starts(self):
        self.hotfix("lint", "pr")
        self.hotfix("b", "merged", "test-b")
        void = "void: merge main for hotfix b, then rerun\n"
        result = self.run_targets("test-a", "test-b", extra=())
        self.assertEqual((result.returncode, result.stdout), (3, void), result.stderr)
        self.assertEqual(self.results(), {"test": "missing", "test-a": "missing", "test-b": "missing"})
        self.assertEqual(self.run_targets("test-a", extra=()).returncode, 0)
        self.assertEqual((self.run_targets("test", extra=()).returncode, self.results()["test"]), (3, "missing"))

        self._git("merge", "-q", "--ff-only", "origin/main")
        self.assertEqual(self.run_targets("test", "test-a", "test-b", extra=()).returncode, 0)
        self.hotfix("any", "merged")
        result = self.run_targets("test-a", extra=())
        self.assertEqual((result.returncode, result.stdout), (3, "void: merge main for hotfix any, then rerun\n"))

    def test_status_keeps_the_gate_open_while_a_merged_hotfix_is_missing(self):
        self.assertEqual(self.run_targets("test", "test-a", "test-b", extra=()).returncode, 0)
        self.hotfix("lint", "pr", "test-a")
        self.assertEqual(self.last_status_line(), "gate: green")
        self.hotfix("rollout", "merged", "deploy")
        self.assertEqual(self.last_status_line(), "gate: green")
        self.hotfix("db", "merged", "test-a")
        code, status = self.status(self.repo)
        self.assertEqual((code, status["gate"], status["open"]), (1, "open", ["missing hotfix: db"]))
        self.assertEqual(self.last_status_line(), "gate: open (missing hotfix: db)")

    def test_a_failing_or_missing_hotfix_check_warns_and_the_run_goes_on(self):
        register = self.root / "council" / "rasci.json"
        register.parent.mkdir()
        legacy = {"stage": "merged", "repo": str(self.root / "gone"), "branch": "fix/legacy", "sha": "0" * 40,
                  "signature": "boom", "targets": [], "status": "done", "roles": {}}
        register.write_text(json.dumps({"hotfix/legacy": legacy}), encoding="utf-8")
        result = self.run_targets("test-a", extra=())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("hotfix/legacy: repository unknown", result.stderr)
        self.assertNotIn("going on without its check", result.stderr)
        register.write_text("{", encoding="utf-8")
        result = self.run_targets("test-a", extra=())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("gate: hotfix.py void exited 2; going on without its check", result.stderr)
        status = self.gate("status", "--repo", str(self.repo))
        self.assertIn("gate: hotfix.py pending exited 2; going on without its check", status.stderr)

        skills = self.root / "lone" / "skills"
        shutil.copytree(SCRIPT.parents[1], skills / "kvb-check-gate", ignore=shutil.ignore_patterns("__pycache__"))
        lone = subprocess.run(
            [sys.executable, str(skills / "kvb-check-gate" / "scripts" / "gate.py"), "run", "--repo", str(self.repo),
             "--target", "test-b", "--log-dir", str(self.logs)],
            env=self.env, capture_output=True, text=True, check=False,
        )
        self.assertEqual(lone.returncode, 0, lone.stderr)
        self.assertIn("kvb-git-hotfix/scripts/hotfix.py is missing; merged hotfixes are not checked", lone.stderr)
        self.assertEqual(self.results()["test-b"], "green")

    def test_verdict_lines_count_even_when_hotfix_exits_non_zero(self):
        gate = load_gate()
        stub = self.root / "stub.py"
        gate.HOTFIX = stub
        for printed, slugs, warned in (("void\thotfix/x\tabc\tall targets\n", ["x"], False), ("", [], True)):
            with self.subTest(printed=printed):
                stub.write_text(f"import sys\nsys.stdout.write({printed!r})\nsys.exit(2)\n", encoding="utf-8")
                with contextlib.redirect_stderr(io.StringIO()) as err:
                    self.assertEqual(gate.voiding_hotfixes(self.repo, ["test-a"]), slugs)
                self.assertEqual("hotfix.py void exited 2; going on without its check" in err.getvalue(), warned)


class TestWorktreeLock(GateCase):
    files = VOID

    def lock(self, name: str) -> Path:
        LOCK_BASE.mkdir(mode=0o700, exist_ok=True)
        lock_dir(self.repo).mkdir(mode=0o700, exist_ok=True)
        return lock_dir(self.repo) / name

    def test_a_read_only_git_dir_holds_no_lock_and_the_hold_still_runs(self):
        git_dir = self.repo / ".git"
        git_dir.chmod(0o555)
        self.addCleanup(git_dir.chmod, 0o755)
        result = self.gate("hold", "--repo", str(self.repo), "--", "sh", "-c", "exit 7")
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertEqual(list(git_dir.glob("kvb-gate-*.lock")), [])
        locks = lock_dir(self.repo)
        self.assertEqual(sorted(path.name for path in locks.iterdir()), [RUN_LOCK, SYNC_LOCK])
        self.assertEqual(stat.S_IMODE(locks.stat().st_mode), 0o700)
        self.assertEqual({stat.S_IMODE((locks / name).stat().st_mode) for name in (RUN_LOCK, SYNC_LOCK)}, {0o600})

    def test_the_lock_path_ignores_tmpdir_council_root_state_and_home(self):
        with open(self.lock(RUN_LOCK), "a", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            for name in ("TMPDIR", "AGENTS_COUNCIL_ROOT", "XDG_STATE_HOME", "HOME"):
                for value in (str(self.root / f"other-{name}"), "relative"):
                    with self.subTest(name=name, value=value):
                        result = subprocess.run(
                            [sys.executable, str(SCRIPT), "hold", "--repo", str(self.repo), "--", "true"],
                            cwd=self.root, env={**self.env, name: value}, capture_output=True, text=True, check=False,
                        )
                        self.assertEqual(result.returncode, 75, result.stderr)
        self.assertEqual([path.name for path in self.root.iterdir() if path.name.startswith(("other-", "relative"))], [])

    def test_a_link_shared_directory_or_second_name_at_any_level_is_refused(self):
        gate = load_gate()
        elsewhere, victim = self.root / "elsewhere", self.root / "victim"
        elsewhere.mkdir()
        victim.write_text("keep\n", encoding="utf-8")
        key = lock_dir(self.repo).name
        for case, refusal in (
            ("base link", "cannot open the worktree lock {base}:"),
            ("key link", "cannot open the worktree lock {base}/{key}:"),
            ("run link", f"cannot open the worktree lock {{base}}/{{key}}/{RUN_LOCK}:"),
            ("sync link", f"cannot open the worktree lock {{base}}/{{key}}/{SYNC_LOCK}:"),
            ("base shared", f"{{base}} must be a directory of uid {os.getuid()} that group and others cannot write"),
            ("key shared", f"{{base}}/{{key}} must be a directory of uid {os.getuid()} that group and others cannot write"),
            ("run hardlink", f"{{base}}/{{key}}/{RUN_LOCK} must be a regular file of uid {os.getuid()} with one link"),
            ("run fifo", f"{{base}}/{{key}}/{RUN_LOCK} must be a regular file of uid {os.getuid()} with one link"),
        ):
            with self.subTest(case):
                base = self.root / case.replace(" ", "-")
                level, kind = case.split()
                path = {"base": base, "key": base / key, "run": base / key / RUN_LOCK, "sync": base / key / SYNC_LOCK}[level]
                for directory in {"base": (), "key": (base,)}.get(level, (base, base / key)):
                    directory.mkdir(mode=0o700)
                if kind == "link":
                    path.symlink_to(elsewhere if level in ("base", "key") else elsewhere / path.name)
                elif kind == "shared":
                    path.mkdir()
                    path.chmod(0o777)
                elif kind == "hardlink":
                    os.link(victim, path)
                else:
                    os.mkfifo(path, 0o600)
                with (
                    contextlib.redirect_stderr(io.StringIO()) as err,
                    self.assertRaises(SystemExit) as raised,
                ):
                    gate.lock_files(self.repo, base)
                self.assertEqual(raised.exception.code, 2)
                self.assertIn(refusal.format(base=base, key=key), err.getvalue())
                self.assertEqual(list(elsewhere.iterdir()), [])
                self.assertEqual(victim.read_text(encoding="utf-8"), "keep\n")
        marker = self.root / "ran"
        lock_dir(self.repo).parent.mkdir(mode=0o700, exist_ok=True)
        lock_dir(self.repo).symlink_to(elsewhere, target_is_directory=True)
        result = self.gate("hold", "--repo", str(self.repo), "--", "touch", str(marker))
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn(f"gate: cannot open the worktree lock {lock_dir(self.repo)}:", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual((list(elsewhere.iterdir()), marker.exists()), ([], False))

    def test_a_held_git_dir_lock_keeps_run_and_hold_out_and_a_read_only_one_is_still_held(self):
        git_lock = self.repo / ".git" / RUN_LOCK
        with open(git_lock, "a", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            lock.write("4242\tgate.py hold -- make deploy\n")
            lock.flush()
            run = self.run_targets("test-a", extra=())
            hold = self.gate("hold", "--repo", str(self.repo), "--", "true")
        for result in (run, hold):
            with self.subTest(command=result.args[2]):
                self.assertEqual(result.returncode, 75, result.stderr)
                self.assertIn(f"another gate.py run or hold or a hotfix.py sync holds the git dir lock of {self.repo} "
                              "(last recorded pid 4242: gate.py hold -- make deploy, possibly stale)", result.stderr)
        git_lock.chmod(0o400)
        git_dir = self.repo / ".git"
        git_dir.chmod(0o555)
        self.addCleanup(git_dir.chmod, 0o755)
        reader = EARLIER_GATE.replace("'a'", "'r'")
        result = self.gate("hold", "--repo", str(self.repo), "--", sys.executable, "-c", reader, str(git_lock))
        self.assertEqual((result.returncode, result.stdout), (0, "held\n"), result.stderr)
        self.assertEqual(git_lock.read_text(encoding="utf-8"), "4242\tgate.py hold -- make deploy\n")

    def test_a_missing_git_dir_lock_is_created_and_held_so_an_earlier_gate_py_stays_out(self):
        git_lock = self.repo / ".git" / RUN_LOCK
        self.assertFalse(git_lock.exists())
        result = self.gate("hold", "--repo", str(self.repo), "--", sys.executable, "-c", EARLIER_GATE, str(git_lock))
        self.assertEqual((result.returncode, result.stdout), (0, "held\n"), result.stderr)
        self.assertEqual(stat.S_IMODE(git_lock.stat().st_mode), 0o600)
        self.assertIn(f"\tgate.py hold --repo {self.repo} -- {sys.executable} -c ", git_lock.read_text(encoding="utf-8"))
        self.assertTrue(self.free(git_lock))

    def test_a_gate_py_with_a_tmp_of_its_own_is_kept_out_by_the_git_dir_lock(self):
        host, box = load_gate(), load_gate()
        for gate, name in ((host, "host-tmp"), (box, "box-tmp")):
            (self.root / name).mkdir(mode=0o700)
            gate.LOCK_BASE = self.root / name / "agents-locks"
        with (
            host.worktree_lock(self.repo, ["gate.py", "hold", "--", "make", "deploy"], []),
            contextlib.redirect_stderr(io.StringIO()) as err,
            self.assertRaises(SystemExit) as raised,
            box.worktree_lock(self.repo, ["gate.py", "hold"], []),
        ):
            self.fail("a gate.py with a /tmp of its own took the worktree lock")
        self.assertEqual(raised.exception.code, 75)
        self.assertIn(f"holds the git dir lock of {self.repo} (last recorded pid {os.getpid()}: gate.py hold -- make "
                      "deploy, possibly stale)", err.getvalue())
        with box.worktree_lock(self.repo, ["gate.py", "hold"], []) as fds:
            self.assertEqual(len(fds), 2)

    def test_a_read_only_git_dir_lock_holder_is_named_live_by_its_tmp_lock_and_the_git_dir_line_as_stale(self):
        git_lock = self.repo / ".git" / RUN_LOCK
        git_lock.write_text("4242\tgate.py run --repo OLD-FINISHED-RUN\n", encoding="utf-8")
        git_lock.chmod(0o400)
        self.addCleanup(git_lock.chmod, 0o600)
        live, box = load_gate(), load_gate()
        (self.root / "box-tmp").mkdir(mode=0o700)
        box.LOCK_BASE = self.root / "box-tmp" / "agents-locks"
        with live.worktree_lock(self.repo, ["gate.py", "hold", "--", "live"], []):
            same_tmp = self.gate("hold", "--repo", str(self.repo), "--", "true")
            with (
                contextlib.redirect_stderr(io.StringIO()) as err,
                self.assertRaises(SystemExit) as raised,
                box.worktree_lock(self.repo, ["gate.py", "hold"], []),
            ):
                self.fail("a gate.py with a /tmp of its own took the worktree lock")
        self.assertEqual(same_tmp.returncode, 75, same_tmp.stderr)
        self.assertIn(f"another gate.py run or hold holds {self.repo} (pid {os.getpid()}: gate.py hold -- live)",
                      same_tmp.stderr)
        self.assertEqual(raised.exception.code, 75)
        self.assertIn("(last recorded pid 4242: gate.py run --repo OLD-FINISHED-RUN, possibly stale)", err.getvalue())
        self.assertEqual(git_lock.read_text(encoding="utf-8"), "4242\tgate.py run --repo OLD-FINISHED-RUN\n")

    def test_a_recorded_holder_reaches_the_message_with_control_characters_escaped(self):
        gate, lock = load_gate(), self.root / "holder.lock"
        for recorded, named in (
            ("4242\tgate.py run \x1b[2Jforged\nERROR: done\x07\n", "pid 4242: gate.py run \\x1b[2Jforged\\nERROR: done\\x07"),
            ("4242 \x1b[2J\tgate.py run\n", "holder not recorded"),
            ("4242\tgate.py hold -- make test-é\n", "pid 4242: gate.py hold -- make test-é"),
        ):
            with self.subTest(recorded=recorded):
                lock.write_text(recorded, encoding="utf-8")
                with lock.open("rb") as handle:
                    self.assertEqual(gate.holder(handle.fileno()), named)

    def test_a_fifo_link_or_second_name_as_git_dir_lock_ends_the_hold_with_2_at_once(self):
        git_lock = self.repo / ".git" / RUN_LOCK
        victim, marker = self.root / "victim", self.root / "ran"
        victim.write_text("keep\n", encoding="utf-8")
        second_name = f"{git_lock} must be a regular file of uid {os.getuid()} with one link"
        for case, plant, refusal in (
            ("fifo", lambda: os.mkfifo(git_lock, 0o600), second_name),
            ("hardlink", lambda: os.link(victim, git_lock), second_name),
            ("symlink", lambda: git_lock.symlink_to(victim), f"cannot open the git dir lock {git_lock}:"),
        ):
            with self.subTest(case):
                plant()
                try:
                    result = subprocess.run(
                        [sys.executable, str(SCRIPT), "hold", "--repo", str(self.repo), "--", "touch", str(marker)],
                        env=self.env, capture_output=True, text=True, timeout=30, check=False,
                    )
                finally:
                    git_lock.unlink()
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn(refusal, result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                self.assertFalse(marker.exists())
                self.assertEqual(victim.read_text(encoding="utf-8"), "keep\n")

    def test_record_and_status_never_follow_a_link_or_second_name_in_the_git_common_dir(self):
        gate = load_gate()
        victim = self.root / "victim.json"
        secret = '{"auths": {"registry": "secret"}}\n'
        for case in ("lock link", "lock hardlink", "state link", "state hardlink"):
            with self.subTest(case):
                common = self.root / case.replace(" ", "-")
                common.mkdir()
                victim.write_text(secret, encoding="utf-8")
                planted = common / (f"{STATE}.lock" if case.startswith("lock") else STATE)
                if case.endswith("hardlink"):
                    os.link(victim, planted)
                else:
                    planted.symlink_to(victim)
                with (
                    contextlib.redirect_stderr(io.StringIO()) as err,
                    self.assertRaises(SystemExit) as raised,
                    gate.state_lock(common / STATE) as lock,
                ):
                    gate.record(lock, common / STATE, "0" * 40, "test-a", {"status": "green"})
                self.assertEqual(raised.exception.code, 2)
                self.assertIn(str(planted), err.getvalue())
                self.assertEqual(victim.read_text(encoding="utf-8"), secret)
                self.assertEqual(planted.is_symlink(), case.endswith(" link"))
                self.assertEqual([path.name for path in common.iterdir() if path.name.startswith(f".{STATE}.")], [])
                self.assertEqual((common / STATE).exists() and not (common / STATE).is_symlink(),
                                 case == "state hardlink")
        state = self.repo / ".git" / STATE
        for case, plant, refusal in (
            ("link", lambda: state.symlink_to(victim), f"gate: cannot read {state}:"),
            ("fifo", lambda: os.mkfifo(state, 0o600), f"gate: {state} must be a regular file of uid {os.getuid()}"),
        ):
            with self.subTest(f"status through a {case}"):
                plant()
                try:
                    result = subprocess.run(
                        [sys.executable, str(SCRIPT), "status", "--repo", str(self.repo), "--json"],
                        env=self.env, capture_output=True, text=True, timeout=30, check=False,
                    )
                finally:
                    state.unlink()
                self.assertEqual((result.returncode, result.stdout), (2, ""), result.stderr)
                self.assertIn(refusal, result.stderr)
                self.assertNotIn("secret", result.stdout + result.stderr)

    def test_each_worktree_has_its_own_lock_and_a_subdirectory_shares_its_worktrees(self):
        other = self.root / "other"
        self._git("worktree", "add", "-q", "-b", "other", str(other))
        self.addCleanup(drop_lock_dir, lock_dir(other))
        (self.repo / "sub").mkdir()
        self.assertNotEqual(lock_dir(self.repo), lock_dir(other))
        with open(self.lock(RUN_LOCK), "a", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            busy = self.gate("hold", "--repo", str(self.repo / "sub"), "--", "true")
            free = self.gate("hold", "--repo", str(other), "--", "true")
        self.assertEqual((busy.returncode, free.returncode), (75, 0), busy.stderr + free.stderr)
        self.assertTrue((lock_dir(other) / RUN_LOCK).is_file())

    def test_a_lock_or_command_that_cannot_start_ends_the_hold_non_zero(self):
        marker = self.root / "ran"
        locks = self.lock(RUN_LOCK).parent
        locks.chmod(0o500)
        self.addCleanup(locks.chmod, 0o700)
        unwritable = self.gate("hold", "--repo", str(self.repo), "--", "touch", str(marker))
        locks.chmod(0o700)
        missing = self.gate("hold", "--repo", str(self.repo), "--", str(self.root / "no-such-command"))
        for result, message in (
            (unwritable, f"gate: cannot open the worktree lock {locks / RUN_LOCK}: Permission denied"),
            (missing, "gate: cannot start"),
        ):
            with self.subTest(message):
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn(message, result.stderr)
                self.assertNotIn("Traceback", result.stderr)
        self.assertFalse(marker.exists())

    def free(self, path: Path) -> bool:
        with open(path, "a", encoding="utf-8") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return False
            return True

    def lock_free(self) -> bool:
        return self.free(self.lock(RUN_LOCK))

    def test_a_busy_worktree_makes_run_and_hold_exit_75_naming_the_holder(self):
        with open(self.lock(RUN_LOCK), "a", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            lock.write("4242\tgate.py hold -- make deploy\n")
            lock.flush()
            run = self.run_targets("test-a", extra=())
            hold = self.gate("hold", "--repo", str(self.repo), "--", "true")
        for result in (run, hold):
            with self.subTest(command=result.args[2]):
                self.assertEqual(result.returncode, 75, result.stderr)
                self.assertIn(f"another gate.py run or hold holds {self.repo} (pid 4242: gate.py hold -- make deploy)",
                              result.stderr)
        self.assertEqual(self.run_targets("test-a", extra=()).returncode, 0)
        self.assertIn(f"\tgate.py run --repo {self.repo} --target test-a\n",
                      self.lock(RUN_LOCK).read_text(encoding="utf-8"))

    def test_hold_passes_the_commands_own_exit_codes_through(self):
        for code in (1, 2, 3, 75):
            with self.subTest(code=code):
                result = self.gate("hold", "--repo", str(self.repo), "--", "sh", "-c", f"exit {code}")
                self.assertEqual(result.returncode, code)

    def test_hold_forwards_signals_to_the_command_and_waits_for_it(self):
        for name, signum, group, code in (
            ("SIGINT to the process group, as Ctrl-C sends it", signal.SIGINT, True, 11),
            ("SIGTERM to hold only", signal.SIGTERM, False, 128 + signal.SIGTERM),
            ("SIGHUP to hold only", signal.SIGHUP, False, 128 + signal.SIGHUP),
        ):
            with self.subTest(name):
                pid_file = self.root / f"child-{signum}.pid"
                holder = subprocess.Popen(
                    [sys.executable, str(SCRIPT), "hold", "--repo", str(self.repo), "--",
                     sys.executable, "-c", COUNTING_CHILD, str(pid_file)],
                    env=self.env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                    text=True, start_new_session=True,
                )
                self.addCleanup(holder.stderr.close)
                self.addCleanup(holder.wait)
                self.addCleanup(holder.kill)
                deadline = time.monotonic() + 30
                while not pid_file.exists():
                    self.assertIsNone(holder.poll())
                    self.assertLess(time.monotonic(), deadline)
                    time.sleep(0.05)
                child = int(pid_file.read_text(encoding="utf-8"))
                self.addCleanup(self.kill, child)
                (os.killpg if group else os.kill)(holder.pid, signum)
                returned = holder.wait(timeout=30)
                self.kill(child)
                err = holder.stderr.read()
                self.assertEqual(returned, code, err)
                self.assertNotIn("Traceback", err)
                self.assertTrue(self.lock_free())

    def test_hold_runs_the_command_in_the_worktree_under_the_lock(self):
        probe = (
            "import fcntl, os, sys\n"
            "with open(sys.argv[1], 'a', encoding='utf-8') as lock:\n"
            "    try:\n"
            "        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
            "    except BlockingIOError:\n"
            "        print('held', os.getcwd())\n"
            "sys.exit(5)\n"
        )
        result = self.gate("hold", "--repo", str(self.repo), "--", sys.executable, "-c", probe, str(self.lock(RUN_LOCK)))
        self.assertEqual((result.returncode, result.stdout), (5, f"held {self.repo}\n"), result.stderr)
        self.assertTrue(self.lock_free())
        result = self.gate("hold", "--repo", str(self.repo), "--", "sh", "-c", "kill -TERM $$")
        self.assertEqual(result.returncode, 128 + signal.SIGTERM)
        self.assertEqual(self.gate("hold", "--repo", str(self.repo)).returncode, 2)

    def test_an_orphan_of_a_hold_keeps_both_locks(self):
        pid_file = self.root / "deploy.pid"
        git_lock = self.repo / ".git" / RUN_LOCK
        git_lock.touch(mode=0o600)
        holder = subprocess.Popen(
            [sys.executable, str(SCRIPT), "hold", "--repo", str(self.repo), "--",
             "sh", "-c", f"echo $$ > {pid_file}.tmp; mv {pid_file}.tmp {pid_file}; exec sleep 60"],
            env=self.env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        self.addCleanup(holder.wait)
        self.addCleanup(holder.kill)
        deadline = time.monotonic() + 30
        while not pid_file.exists():
            self.assertIsNone(holder.poll())
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.05)
        deploy = int(pid_file.read_text(encoding="utf-8"))
        self.addCleanup(self.kill, deploy)
        holder.kill()
        holder.wait()
        self.assertFalse(self.free(git_lock), "the git dir lock died with the hold")
        result = self.run_targets("test-a", extra=())
        self.assertEqual(result.returncode, 75)
        self.assertIn(f"another gate.py run or hold holds {self.repo} (pid {holder.pid}: "
                      f"gate.py hold --repo {self.repo} -- sh -c", result.stderr)
        self.kill(deploy)
        deadline = time.monotonic() + 30
        while not (self.lock_free() and self.free(git_lock)):
            self.assertLess(time.monotonic(), deadline, "the killed deploy kept a lock")
            time.sleep(0.05)
        self.assertEqual(self.run_targets("test-a", extra=()).returncode, 0)

    def kill(self, pid: int) -> None:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)

    def test_a_run_waits_for_a_running_sync_instead_of_failing(self):
        with (
            open(self.lock(SYNC_LOCK), "a", encoding="utf-8") as sync,
            open(self.lock(RUN_LOCK), "a", encoding="utf-8") as lock,
        ):
            fcntl.flock(sync, fcntl.LOCK_EX)
            sync.write(SYNC_HOLDER)
            sync.flush()
            fcntl.flock(lock, fcntl.LOCK_EX)
            run = subprocess.Popen(
                [sys.executable, str(SCRIPT), "run", "--repo", str(self.repo), "--target", "test-a",
                 "--log-dir", str(self.logs)],
                env=self.env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            self.addCleanup(run.wait)
            self.addCleanup(run.kill)
            self.assertEqual(
                run.stderr.readline(),
                f"gate: a hotfix.py sync merges in {self.repo} (pid 4242: hotfix.py sync --task t); waiting for it at "
                f"most {load_gate().SYNC_WAIT_SECONDS} s\n",
            )
        out, err = run.communicate(timeout=60)
        self.assertEqual(run.returncode, 0, err)
        self.assertTrue(out.startswith("green\ttest-a\t"), out)

    def test_a_sync_outlasting_the_wait_ends_it_with_75_naming_the_sync(self):
        gate = load_gate()
        gate.SYNC_WAIT_SECONDS = 1
        with open(self.lock(SYNC_LOCK), "a", encoding="utf-8") as sync:
            fcntl.flock(sync, fcntl.LOCK_EX)
            sync.write(SYNC_HOLDER)
            sync.flush()
            with (
                contextlib.redirect_stderr(io.StringIO()) as err,
                self.assertRaises(SystemExit) as raised,
                gate.worktree_lock(self.repo, ["gate.py", "hold"], []),
            ):
                self.fail("the worktree lock was taken during a sync")
        self.assertEqual(raised.exception.code, 75)
        self.assertIn(f"a hotfix.py sync still holds {self.repo} after 1 s (pid 4242: hotfix.py sync --task t)",
                      err.getvalue())
        self.assertTrue(self.lock_free())


class TestReadOnlyCommonDir(GateCase):
    files = MARKING

    def test_a_read_only_common_dir_ends_run_with_2_before_any_target_runs(self):
        marker = self.root / "ran"
        self.env["MARKER"] = str(marker)
        git_dir = self.repo / ".git"
        self.addCleanup(git_dir.chmod, 0o755)
        for case in ("no state yet", "state of an earlier run"):
            with self.subTest(case):
                git_dir.chmod(0o755)
                if case == "state of an earlier run":
                    self.assertEqual(self.run_targets("test", extra=()).returncode, 0)
                    marker.unlink()
                before = {path.name: path.read_bytes() for path in git_dir.glob(f"{STATE}*")}
                git_dir.chmod(0o555)
                result = self.run_targets("test", extra=())
                self.assertEqual((result.returncode, marker.exists()), (2, False), result.stdout + result.stderr)
                self.assertIn("nothing ran", result.stderr)
                self.assertIn("as an operator row on the host", result.stderr)
                self.assertIn("`make <target>` alone runs but records nothing", result.stderr)
                self.assertNotIn("queue.py", result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                self.assertEqual({path.name: path.read_bytes() for path in git_dir.glob(f"{STATE}*")}, before)
                self.assertEqual(list(git_dir.glob(f".{STATE}.*")), [])

    def test_a_linked_or_invalid_state_file_ends_run_with_2_before_any_target_runs(self):
        marker, victim = self.root / "ran", self.root / "victim.json"
        self.env["MARKER"] = str(marker)
        victim.write_text('{"auths": {"registry": "secret"}}\n', encoding="utf-8")
        state = self.repo / ".git" / STATE
        for case, plant, refusal in (
            ("link", lambda: state.symlink_to(victim), f"gate: cannot read {state}:"),
            ("invalid JSON", lambda: state.write_text("{broken\n", encoding="utf-8"), f"gate: {state} is not valid JSON"),
        ):
            with self.subTest(case):
                plant()
                try:
                    result = self.run_targets("test", extra=())
                finally:
                    state.unlink()
                self.assertEqual((result.returncode, marker.exists()), (2, False), result.stdout + result.stderr)
                self.assertIn(refusal, result.stderr)
                self.assertNotIn("secret", result.stdout + result.stderr)
                self.assertEqual(victim.read_text(encoding="utf-8"), '{"auths": {"registry": "secret"}}\n')
                self.assertEqual(list((self.repo / ".git").glob(f".{STATE}.*")), [])


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
