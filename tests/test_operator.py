"""Exercise kvb-org-operator: operator rows in the rasci register, their done checks, the list, the runner."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OPERATOR = REPO_ROOT / "skills" / "kvb-org-operator" / "scripts" / "operator.py"
RASCI = REPO_ROOT / "skills" / "kvb-org-rasci" / "scripts" / "rasci.py"
HEADER = "| # | Directory | Command | Why | Check |"
RUNNER = ["", "Every step with preview and yes/skip:", "```bash", f"python3 {OPERATOR} run", "```"]
IDENTITY = {
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.org",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.org",
    "GIT_CONFIG_NOSYSTEM": "1",
}


class TestOperator(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.home = self.base / "home"
        self.root = self.base / "council"
        self.bin = self.base / "bin"
        self.bin.mkdir()
        sessions = self.home / ".claude" / "sessions"
        sessions.mkdir(parents=True)
        (sessions / "s1.json").write_text(json.dumps({"sessionId": "s1", "name": "One"}), encoding="utf-8")
        self.env = {
            "PATH": f"{self.bin}:/usr/bin:/bin",
            "HOME": str(self.home),
            "AGENTS_COUNCIL_ROOT": str(self.root),
            "CLAUDE_CODE_SESSION_ID": "s1",
        }

    def _run(self, *args: str, script: Path = OPERATOR) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(script), *args],
            capture_output=True, text=True, env=self.env, cwd=self.tmp.name, check=False,
        )

    def _out(self, *args: str) -> list[str]:
        result = self._run(*args)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.splitlines()

    def _git(self, cwd: Path, *args: str) -> None:
        subprocess.run(["git", *args], cwd=cwd, env={**self.env, **IDENTITY}, check=True, capture_output=True)

    def _repo(self, name: str, upstream: bool) -> Path:
        repo = self.base / name
        repo.mkdir()
        self._git(repo, "init", "-q", "-b", "main")
        (repo / "one").write_text("1", encoding="utf-8")
        self._git(repo, "add", "one")
        self._git(repo, "commit", "-qm", "one")
        if upstream:
            bare = self.base / f"{name}.git"
            self._git(self.base, "init", "-q", "--bare", str(bare))
            self._git(repo, "remote", "add", "origin", str(bare))
            self._git(repo, "push", "-q", "-u", "origin", "main")
            (repo / "two").write_text("2", encoding="utf-8")
            self._git(repo, "add", "two")
            self._git(repo, "commit", "-qm", "two")
        return repo

    def _add(self, slug: str, workdir: Path, command: str, reason: str, check: str) -> None:
        self.assertEqual(
            self._out("add", slug, "--dir", str(workdir), "--command", command, "--reason", reason,
                      "--check", check),
            [f"added operator/{slug}"],
        )

    @staticmethod
    def _block(number: int, slug: str, workdir: Path, command: str) -> list[str]:
        return ["", f"{number}. operator/{slug}", "```bash", f"cd {workdir}", command, "```"]

    def _feed(self, answers: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(OPERATOR), "run"],
            input=answers, capture_output=True, text=True, env={**self.env, "SHELL": "/bin/sh"},
            cwd=self.tmp.name, check=False,
        )

    def _open(self) -> list[str]:
        return [row["task"] for row in json.loads("\n".join(self._out("list", "--json")))]

    def _register(self) -> dict[str, dict]:
        return json.loads((self.root / "rasci.json").read_text(encoding="utf-8"))

    def test_checks_close_rows_once_their_condition_holds(self):
        repo = self._repo("repo", upstream=True)
        src, dst = self.base / "src", self.base / "dst"
        (src / "sub").mkdir(parents=True)
        (src / "__pycache__").mkdir()
        (src / "a.txt").write_text("alpha", encoding="utf-8")
        (src / "sub" / "b.txt").write_text("beta", encoding="utf-8")
        (src / "__pycache__" / "a.pyc").write_bytes(b"\0")
        stale = self.base / "stale"
        stale.write_text("x", encoding="utf-8")
        base = self.base
        self._add("zeta", base, "sudo reboot", "new kernel", "manual")
        self._add("absent-row", base, f"sudo rm {stale}", "root owned", f"absent:{stale}")
        self._add("binary-row", base, "pipx install kvb-fake-tool", "tool missing", "binary:kvb-fake-tool")
        self._add("installed-row", src, "make install", "copy | stale", f"installed:{src}={dst}")
        self._add("push-row", repo, "git-sign-push", "branch ahead", f"pushed:{repo}")
        self._add("commit-row", repo, "git commit -m wip", "work uncommitted", "manual")
        self._add("alpha", base, "sudo systemctl restart docker", "daemon config", "manual")
        self.assertEqual(
            self._out("list"),
            [
                HEADER,
                "|---|---|---|---|---|",
                f"| 1 | {repo} | git commit -m wip | work uncommitted | manual |",
                f"| 2 | {repo} | git-sign-push | branch ahead | pushed:{repo} |",
                f"| 3 | {src} | make install | copy \\| stale | installed:{src}={dst} |",
                f"| 4 | {base} | pipx install kvb-fake-tool | tool missing | binary:kvb-fake-tool |",
                f"| 5 | {base} | sudo rm {stale} | root owned | absent:{stale} |",
                f"| 6 | {base} | sudo reboot | new kernel | manual |",
                f"| 7 | {base} | sudo systemctl restart docker | daemon config | manual |",
                *self._block(1, "commit-row", repo, "git commit -m wip"),
                *self._block(2, "push-row", repo, "git-sign-push"),
                *self._block(3, "installed-row", src, "make install"),
                *self._block(4, "binary-row", base, "pipx install kvb-fake-tool"),
                *self._block(5, "absent-row", base, f"sudo rm {stale}"),
                *self._block(6, "zeta", base, "sudo reboot"),
                *self._block(7, "alpha", base, "sudo systemctl restart docker"),
                *RUNNER,
            ],
        )
        row = self._register()["operator/installed-row"]
        self.assertEqual(row["title"], "make install")
        self.assertEqual(row["workdir"], str(src))
        self.assertEqual(row["description"], "copy | stale")
        self.assertEqual(row["status"], "queued")
        self.assertEqual(row["roles"], {"Operator": "R", "One": "A"})
        self.assertEqual(row["check"], f"installed:{src}={dst}")

        shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))
        (dst / "a.txt").write_text("alphA", encoding="utf-8")
        self._git(repo, "push", "-q")
        self.assertEqual(
            self._open(),
            ["operator/commit-row", "operator/installed-row", "operator/binary-row", "operator/absent-row",
             "operator/zeta", "operator/alpha"],
        )
        (dst / "a.txt").write_text("alpha", encoding="utf-8")
        tool = self.bin / "kvb-fake-tool"
        tool.write_text("#!/bin/sh\n", encoding="utf-8")
        tool.chmod(0o755)
        self.assertEqual(
            self._open(), ["operator/commit-row", "operator/absent-row", "operator/zeta", "operator/alpha"]
        )
        stale.unlink()
        for slug in ("commit-row", "zeta"):
            self.assertEqual(self._out("done", slug), [f"done operator/{slug}"])
        self.assertEqual(self._open(), ["operator/alpha"])
        self._out("done", "alpha")
        self.assertEqual(self._out("list"), ["operator: nothing open"])
        rows = {task: row for task, row in self._register().items() if task.startswith("operator/")}
        self.assertEqual(len(rows), 7)
        for task, row in rows.items():
            with self.subTest(task=task):
                self.assertEqual(row["status"], "done")
                self.assertRegex(row["end"], r"^20\d\d-")

    def test_pushed_stays_open_without_upstream_or_repository(self):
        repo = self._repo("lonely", upstream=False)
        self._add("no-upstream", repo, "git push -u origin main", "no upstream", f"pushed:{repo}")
        gone = self.base / "gone"
        self._add("no-repo", self.base, "git clone x gone", "not cloned", f"pushed:{gone}")
        self.assertEqual(self._open(), ["operator/no-upstream", "operator/no-repo"])

    def test_readd_updates_the_row_and_keeps_its_place(self):
        self._add("first", self.base, "sudo reboot", "kernel", "manual")
        self._add("second", self.base, "sudo poweroff", "hardware", "manual")
        self._add("first", self.base, "sudo reboot now", "kernel 7.2.9", "manual")
        self._out("done", "second")
        self._add("second", self.base, "sudo poweroff", "hardware", "manual")
        self.assertEqual(self._open(), ["operator/first", "operator/second"])
        row = self._register()["operator/first"]
        self.assertEqual((row["title"], row["description"]), ("sudo reboot now", "kernel 7.2.9"))
        self.assertNotIn("end", self._register()["operator/second"])

    def test_legacy_row_without_check_counts_as_manual(self):
        result = self._run("set", "operator/legacy", "--title", "sudo reboot", "--status", "queued", script=RASCI)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self._out("list"),
            [HEADER, "|---|---|---|---|---|", "| 1 | - | sudo reboot | - | manual |"],
        )

    def test_bash_block_skips_legacy_rows_without_directory(self):
        result = self._run("set", "operator/legacy", "--title", "Rotate leaked credentials", "--status", "queued",
                           script=RASCI)
        self.assertEqual(result.returncode, 0, result.stderr)
        self._add("reboot", self.base, "sudo reboot", "kernel", "manual")
        self.assertEqual(
            self._out("list")[4:],
            [*self._block(2, "reboot", self.base, "sudo reboot"), *RUNNER],
        )

    def test_run_shows_each_step_and_runs_only_approved_ones(self):
        work = self.base / "work"
        work.mkdir()
        self._add("first", work, "touch ran-first", "approve me", "manual")
        self._add("second", work, "touch ran-second", "skip me", "manual")
        self._add("third", work, "echo \x1b[2Kx", "hidden escape", "manual")
        result = self._feed("maybe\ny\ns\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((work / "ran-first").exists())
        self.assertFalse((work / "ran-second").exists())
        out = result.stdout
        self.assertLess(out.index("command:   touch ran-first"), out.index("Run it?"))
        self.assertIn("done operator/first", out)
        self.assertIn("skipped operator/second", out)
        self.assertIn("command:   echo \\x1b[2Kx", out)
        self.assertIn("operator: stopped", out)
        self.assertNotIn("\x1b", out)
        self.assertEqual(self._open(), ["operator/second", "operator/third"])

    def test_run_previews_pushed_commits_and_keeps_failed_rows_open(self):
        repo = self._repo("ahead", upstream=True)
        self._add("push", repo, "false", "branch ahead", f"pushed:{repo}")
        result = self._feed("y\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--no-pager --no-optional-locks log --oneline '@{u}..HEAD'", result.stdout)
        self.assertRegex(result.stdout, r"[0-9a-f]{7,} two")
        self.assertIn("failed operator/push: exit 1; the row stays open", result.stdout)
        self.assertEqual(self._open(), ["operator/push"])

    def test_run_preview_runs_no_command_a_repo_config_names(self):
        marker = self.base / "ran"
        trap = self._repo("trap", upstream=False)
        (trap / "keep").write_text("k", encoding="utf-8")
        self._git(trap, "add", "keep")
        self._git(trap, "commit", "-qm", "keep")
        self._git(trap, "config", "core.fsmonitor", f"touch {marker}")
        self._git(trap, "config", "diff.external", f"touch {marker}")
        hook = trap / ".git" / "hooks" / "post-index-change"
        hook.write_text(f"#!/bin/sh\ntouch {marker}\n", encoding="utf-8")
        hook.chmod(0o755)
        future = time.time() + 1000
        os.utime(trap / "keep", (future, future))
        filtered = self._repo("filtered", upstream=False)
        self._git(filtered, "config", "filter.x.clean", f"touch {marker}")
        (filtered / ".gitattributes").write_text("* filter=x\n", encoding="utf-8")
        for repo in (trap, filtered):
            (repo / "one").write_text("changed", encoding="utf-8")
            self._add(repo.name, repo, "true", "r", "manual")
        result = self._feed("d\ns\nd\ns\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(" M one", result.stdout)
        self.assertIn("+changed", result.stdout)
        self.assertNotIn("?? 2", result.stdout)
        self.assertFalse(marker.exists())

    def test_list_and_preview_never_fetch_a_missing_object(self):
        marker = self.base / "fetched"
        repo = self._repo("lazy", upstream=True)
        self._git(repo, "config", "remote.origin.promisor", "true")
        self._git(repo, "config", "remote.origin.uploadpack", f"touch {marker}; git-upload-pack")
        (repo / ".git" / "refs" / "remotes" / "origin" / "main").write_text("1" * 40 + "\n", encoding="utf-8")
        self._add("lazy", repo, "true", "r", f"pushed:{repo}")
        self._out("list")
        self.assertEqual(self._feed("s\n").returncode, 0)
        self.assertFalse(marker.exists())

    def test_run_shows_control_characters_of_the_preview(self):
        repo = self._repo("spoof", upstream=True)
        (repo / "three").write_text("3", encoding="utf-8")
        self._git(repo, "add", "three")
        self._git(repo, "commit", "-qm", "x\x1b[1A\x1b[2Kfake")
        self._add("spoof", repo, "true", "r", f"pushed:{repo}")
        out = self._feed("s\n").stdout
        self.assertNotIn("\x1b", out)
        self.assertIn("x\\x1b[1A\\x1b[2Kfake", out)

    def test_decision_rows_stay_out_of_blocks_and_run(self):
        self._add("ask", self.base, "decide: keep fix B", "operator only", "decision")
        self._add("go", self.base, "true", "runnable", "manual")
        listed = self._out("list")
        self.assertIn(f"| 2 | {self.base} | decide: keep fix B | operator only | decision |", listed)
        self.assertEqual(listed[4:], [*self._block(1, "go", self.base, "true"), *RUNNER])
        result = self._feed("y\n")
        self.assertNotIn("decide", result.stdout)
        self.assertEqual(self._open(), ["operator/ask"])

    def _queue_config(self, slot_need_gb: dict) -> None:
        config = self.base / "config.json"
        open_memory = {"available": -1, "swap_free": -1, "psi_full": 1000, "container_swap_gb": 1e9}
        config.write_text(json.dumps({
            "disk": str(self.base), "thresholds_gb": {"warn": 0, "stop": 0, "critical": 0}, "projection_minutes": 30,
            "slot_need_gb": slot_need_gb, "heavy_commands": [r"\btouch heavy\b"], "never_block": [],
            "load_limits": {"cpu_percent": 101, "mem_percent": 101, "sample_seconds": 0.1},
            "budget_percent": {"ram": 75, "cpu": 100}, "memory_limits": {"warn": open_memory, "stop": open_memory},
        }), encoding="utf-8")
        self.env["AGENTS_COUNCIL_CONFIG"] = str(config)

    def test_run_offers_the_queue_for_a_heavy_command_and_asks_again_on_the_grant(self):
        self._queue_config({"operator": 0})
        work = self.base / "work"
        work.mkdir()
        self._add("light", work, "touch light", "plain", "manual")
        self._add("heavy", work, "touch heavy\x1b[2K", "build", "manual")
        result = self._feed("y\nh\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        light, heavy = result.stdout.split("[2/2]")
        self.assertIn("[s]kip", light)
        self.assertNotIn("heavy:", light)
        self.assertIn("heavy:     memory stage ok", heavy)
        self.assertIn("position\tid\tstatus", heavy)
        self.assertIn("[h]old in the queue", heavy)
        self.assertNotIn("\x1b", heavy)
        self.assertIn("granted operator/heavy: the queue lets it run now", heavy)
        self.assertIn("not run operator/heavy", heavy)
        self.assertIn("failed operator/heavy: exit 75; the row stays open", heavy)
        self.assertTrue((work / "light").exists())
        self.assertFalse((work / "heavy\x1b[2K").exists())
        self.assertEqual(self._open(), ["operator/heavy"])
        self.assertFalse((self.root / "queue-history.jsonl").exists())

    def test_run_offers_no_hold_while_the_config_lacks_the_operator_kind(self):
        self._queue_config({"test": 0})
        work = self.base / "work"
        work.mkdir()
        self._add("heavy", work, "touch heavy", "build", "manual")
        result = self._feed("h\ns\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("lacks slot_need_gb.operator;", result.stdout)
        self.assertIn("no [h]old until it does", result.stdout)
        self.assertNotIn("[h]old in the queue", result.stdout)
        self.assertIn("skipped operator/heavy", result.stdout)

    def test_run_offers_no_hold_for_sudo_whose_prompt_needs_the_terminal(self):
        self._queue_config({"operator": 0})
        work = self.base / "work"
        work.mkdir()
        self._add("heavy", work, "bash -c 'sudo -n touch heavy'", "build", "manual")
        result = self._feed("h\ns\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("sudo asks on the terminal, which a queued command lacks", result.stdout)
        self.assertNotIn("[h]old in the queue", result.stdout)

    def test_granted_runs_only_the_approved_row_in_its_directory_after_a_new_yes(self):
        work = self.base / "work"
        work.mkdir()
        self._add("heavy", work, "touch heavy", "build", "manual")
        env = {**self.env, "SHELL": "/bin/sh"}

        def granted(answers: str, directory: Path, *argv: str) -> subprocess.CompletedProcess:
            return subprocess.run(
                [sys.executable, str(OPERATOR), "granted", "operator/heavy", "--dir", str(directory), "--check",
                 "manual", "--", *argv],
                input=answers, capture_output=True, text=True, env=env, cwd=self.base, check=False,
            )

        changed = granted("y\n", work, "/bin/sh", "-ic", "touch other")
        self.assertEqual(changed.returncode, 75)
        self.assertIn("no longer open with the approved directory, check and command", changed.stderr)
        moved = granted("y\n", self.base, "/bin/sh", "-ic", "touch heavy")
        self.assertEqual((moved.returncode, (self.base / "heavy").exists()), (75, False))
        declined = granted("s\n", work, "/bin/sh", "-ic", "touch heavy")
        self.assertEqual((declined.returncode, (work / "heavy").exists()), (75, False))
        silent = granted("", work, "/bin/sh", "-ic", "touch heavy")
        self.assertEqual((silent.returncode, (work / "heavy").exists()), (75, False))
        ran = granted("d\ny\n", work, "/bin/sh", "-ic", "touch heavy")
        self.assertEqual(ran.returncode, 0, ran.stderr)
        self.assertIn("granted operator/heavy", ran.stdout)
        self.assertTrue((work / "heavy").exists())
        self.assertFalse((self.base / "heavy").exists() or (work / "other").exists())

    def test_run_needs_shell(self):
        self._add("x", self.base, "true", "r", "manual")
        result = subprocess.run(
            [sys.executable, str(OPERATOR), "run"], input="y\n", capture_output=True, text=True,
            env=self.env, cwd=self.tmp.name, check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("SHELL is not set", result.stderr)

    def test_invalid_input_exits_2(self):
        good = ("--dir", "/srv", "--command", "sudo reboot", "--reason", "kernel")
        for args in (
            ("add", "x", *good, "--check", "shell:/usr/bin/true"),
            ("add", "x", *good, "--check", "run:reboot"),
            ("add", "x", *good, "--check", "manual:yes"),
            ("add", "x", *good, "--check", "pushed:relative/repo"),
            ("add", "x", *good, "--check", "absent:tmp/x"),
            ("add", "x", *good, "--check", "installed:/a"),
            ("add", "x", *good, "--check", "installed:/a=relative"),
            ("add", "x", *good, "--check", "absent:/tmp/x;rm -rf /"),
            ("add", "x", *good, "--check", "pushed:/tmp/$(id)"),
            ("add", "x", *good, "--check", "absent:/tmp/`id`"),
            ("add", "x", *good, "--check", "installed:/a=/b|c"),
            ("add", "x", *good, "--check", "binary:a b"),
            ("add", "x", *good, "--check", "binary:/usr/bin/git"),
            ("add", "x", *good, "--check", "pushed:"),
            ("add", "x", "--dir", "relative", "--command", "c", "--reason", "r", "--check", "manual"),
            ("add", "x", "--dir", "/srv", "--command", " ", "--reason", "r", "--check", "manual"),
            ("add", "x", "--dir", "/srv", "--command", "c", "--check", "manual"),
            ("add", "Bad Slug", *good, "--check", "manual"),
            ("done", "missing"),
            ("list", "--wide"),
        ):
            with self.subTest(args=args):
                self.assertEqual(self._run(*args).returncode, 2)
        self.assertFalse((self.root / "rasci.json").exists())


if __name__ == "__main__":
    unittest.main()
