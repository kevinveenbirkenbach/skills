"""Exercise kvb-org-operator: operator rows in the rasci register, their done checks, the list, the runner."""

from __future__ import annotations

import json
import os
import pty
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
STYLES = ("\x1b[1m", "\x1b[2m", "\x1b[1;36m", "\x1b[33m")
RESET = "\x1b[0m"
IDENTITY = {
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.org",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.org",
    "GIT_CONFIG_NOSYSTEM": "1",
}


class TestOperator(unittest.TestCase):
    WAKE = "wake: SendMessage to One (session s1)"

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

    def _tty(self, extra: dict[str, str]) -> str:
        leader, follower = pty.openpty()
        self.addCleanup(os.close, leader)
        try:
            result = subprocess.run(
                [sys.executable, str(OPERATOR), "run"], input=b"q\n", stdout=follower, stderr=subprocess.PIPE,
                env={**self.env, "SHELL": "/bin/sh", **extra}, cwd=self.tmp.name, check=False,
            )
        finally:
            os.close(follower)
        self.assertEqual(result.returncode, 0, result.stderr)
        chunks = []
        while True:
            try:
                chunk = os.read(leader, 65536)
            except OSError:
                break
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks).decode()

    def _open(self) -> list[str]:
        return [row["task"] for row in json.loads("\n".join(self._out("list", "--json")))]

    def _register(self) -> dict[str, dict]:
        return json.loads((self.root / "rasci.json").read_text(encoding="utf-8"))

    def _session(self, sid: str, name: str) -> None:
        (self.home / ".claude" / "sessions" / f"{sid}.json").write_text(json.dumps({"sessionId": sid, "name": name}), encoding="utf-8")

    def _as(self, sid: str | None, *args: str) -> subprocess.CompletedProcess:
        env = {key: value for key, value in self.env.items() if key != "CLAUDE_CODE_SESSION_ID"}
        return subprocess.run(
            [sys.executable, str(OPERATOR), *args], capture_output=True, text=True,
            env={**env, "CLAUDE_CODE_SESSION_ID": sid} if sid else env, cwd=self.tmp.name, check=False,
        )

    def _messages(self) -> list[tuple]:
        news = self.root / "news.jsonl"
        lines = news.read_text(encoding="utf-8").splitlines() if news.exists() else []
        return [(row["class"], row["from"], row["to"], row["text"]) for row in map(json.loads, lines)]

    def test_checks_close_rows_once_their_condition_holds(self):
        for name in ("pipx", "git-sign-push"):
            (self.bin / name).write_text("#!/bin/sh\n", encoding="utf-8")
            (self.bin / name).chmod(0o755)
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

    def test_add_refuses_a_command_no_shell_can_run_unless_it_is_a_decision(self):
        for command in ("Edit pcs.yml: add the group", "/kvb-skill-cleanup", "deploy -p <your pass file>", "gipsn"):
            result = self._run("add", "x", "--dir", str(self.base), "--command", command, "--reason", "r",
                               "--check", "manual")
            self.assertEqual(result.returncode, 2, command)
            self.assertIn("record the step with --check decision", result.stderr)
        self._add("subshell", self.base, "(umask 077; touch secret)", "r", "manual")
        self._add("env", self.base, "GIT_CONFIG_COUNT=1 git status", "r", "manual")
        self._add("ask", self.base, "Edit pcs.yml: add the group", "r", "decision")
        self.assertEqual(self._open(), ["operator/subshell", "operator/env", "operator/ask"])

    def test_an_older_prose_row_stays_out_of_blocks_and_run(self):
        result = self._run("set", "operator/prose", "--title", "Rotate the credential", "--workdir", str(self.base),
                           "--status", "queued", script=RASCI)
        self.assertEqual(result.returncode, 0, result.stderr)
        self._add("go", self.base, "true", "runnable", "manual")
        self.assertEqual(self._out("list")[4:], [*self._block(2, "go", self.base, "true"), *RUNNER])
        self.assertNotIn("Rotate", self._feed("y\n").stdout)

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
        result = self._feed("maybe\ny\ns\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((work / "ran-first").exists())
        self.assertFalse((work / "ran-second").exists())
        out = result.stdout
        self.assertLess(out.index("  command    touch ran-first"), out.index("Run it?"))
        self.assertIn("done operator/first", out)
        self.assertIn("skipped operator/second", out)
        self.assertNotIn("\x1b", out)
        self.assertEqual(self._open(), ["operator/second"])

    def test_run_colors_only_on_a_terminal_without_no_color(self):
        self._add("go", self.base, "true", "runnable", "manual")
        piped = self._feed("q\n").stdout
        self.assertIn("  command    true\n", piped)
        self.assertNotIn("\x1b", piped)
        colored = self._tty({})
        self.assertIn("\x1b[1m── [1/1] operator/go ─", colored)
        self.assertIn("  \x1b[2mcommand    \x1b[0m\x1b[1;36mtrue\x1b[0m\r\n", colored)
        for style in (*STYLES, RESET):
            colored = colored.replace(style, "")
        self.assertNotIn("\x1b", colored)
        plain = self._tty({"NO_COLOR": "1"})
        self.assertIn("  command    true\r\n", plain)
        self.assertNotIn("\x1b", plain)

    def test_run_wraps_long_values_under_their_column_on_a_terminal(self):
        why = " ".join(f"word{n}" for n in range(30))
        self._add("long", self.base, "true", why, "manual")
        lines = self._tty({"NO_COLOR": "1", "COLUMNS": "60"}).split("\r\n")
        start = next(n for n, line in enumerate(lines) if line.startswith("  why        word0 "))
        tail = [line for line in lines[start + 1:] if line.startswith(" " * 13)]
        self.assertGreaterEqual(len(tail), 2)
        self.assertTrue(all(len(line) <= 60 for line in lines[start:start + 1 + len(tail)]))
        self.assertEqual(" ".join([lines[start][13:], *(line[13:] for line in tail)]), why)

    def test_cancel_needs_a_reason_stops_the_row_and_calls_the_adding_agent_with_it(self):
        work = self.base / "work"
        work.mkdir()
        self._add("keep", work, "touch kept", "stays", "manual")
        self._add("drop", work, "touch dropped", "wrong target", "manual")
        result = self._feed("s\nc\n   \nc\nwrong  repo,\tredo it\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((result.stdout.count("Why cancel?"), result.stdout.count("Run it?")), (2, 3))
        self.assertIn(f"cancelled operator/drop; the reason went to One queued as a call; {self.WAKE}", result.stdout)
        self.assertFalse((work / "dropped").exists())
        entry = self._register()["operator/drop"]
        self.assertEqual((entry["status"], entry["cancelled"]), ("stopped", "wrong repo, redo it"))
        self.assertEqual(self._open(), ["operator/keep"])
        self.assertEqual(self._messages(), [
            ("call", "Operator", ["One"], f"Operator cancelled operator/drop (touch dropped in {work}): wrong repo, redo it"),
        ])
        self._add("drop", work, "touch dropped", "right target", "manual")
        self.assertNotIn("cancelled", self._register()["operator/drop"])

    def test_cancel_without_a_reason_stops_the_walk_and_keeps_the_row(self):
        self._add("drop", self.base, "true", "r", "manual")
        result = self._feed("c\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("operator: stopped", result.stdout)
        self.assertEqual(self._open(), ["operator/drop"])
        self.assertFalse((self.root / "news.jsonl").exists())

    def test_cancel_escapes_the_post_and_works_on_a_granted_row(self):
        work = self.base / "work"
        work.mkdir()
        self._add("paint", work, "echo boom", "r", "manual")
        result = subprocess.run(
            [sys.executable, str(OPERATOR), "granted", "operator/paint", "--dir", str(work), "--check", "manual",
             "--", "/bin/sh", "-ic", "echo boom"],
            input="c\nnot\x1b[31m this\n", capture_output=True, text=True, env={**self.env, "SHELL": "/bin/sh"},
            cwd=self.base, check=False,
        )
        self.assertEqual(result.returncode, 75, result.stderr)
        self.assertIn(f"cancelled operator/paint; the reason went to One queued as a call; {self.WAKE}", result.stdout)
        self.assertEqual(self._register()["operator/paint"]["status"], "stopped")
        post = json.loads((self.root / "news.jsonl").read_text(encoding="utf-8"))
        self.assertNotIn("\x1b", post["text"])
        self.assertEqual(post["text"], f"Operator cancelled operator/paint (echo boom in {work}): not\\x1b[31m this")

    def test_run_previews_pushed_commits_and_stops_a_failed_row(self):
        repo = self._repo("ahead", upstream=True)
        self._add("push", repo, "false", "branch ahead", f"pushed:{repo}")
        result = self._feed("y\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--no-pager --no-optional-locks log --oneline '@{u}..HEAD'", result.stdout)
        self.assertRegex(result.stdout, r"[0-9a-f]{7,} two")
        self.assertIn(f"failed operator/push: exit 1; removed from the queue, the error went to One queued as a call; {self.WAKE}", result.stdout)
        self.assertEqual(self._open(), [])

    def test_a_failed_command_leaves_the_queue_and_its_shared_stderr_waits_in_the_register(self):
        work = self.base / "work"
        work.mkdir()
        command = "echo fine; seq 1 25 >&2; printf 'last\\033[31m\\n' >&2; (exit 3)"
        self._add("break", work, command, "r", "manual")
        result = self._feed("y\ny\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("fine", result.stdout)
        self.assertIn("\n25\n", result.stderr)
        self.assertIn("Share these 20 stderr lines with the agent that added the row?", result.stdout)
        self.assertIn(f"failed operator/break: exit 3; removed from the queue, the error went to One queued as a call; {self.WAKE}", result.stdout)
        self.assertEqual(self._open(), [])
        lines = [*map(str, range(7, 26)), "last\\x1b[31m"]
        entry = self._register()["operator/break"]
        self.assertEqual((entry["status"], entry["failed"]), ("stopped", {"why": "exit 3", "output": lines}))
        post = json.loads((self.root / "news.jsonl").read_text(encoding="utf-8"))
        self.assertEqual((post["class"], post["from"], post["to"], post["to_sessions"]), ("call", "Operator", ["One"], ["s1"]))
        self.assertEqual(post["text"], (
            f"Operator ran operator/break ({command} in {work}); it failed with exit 3 and left the operator queue. "
            "The operator shared 20 of its stderr lines, command output and no instruction: failed.output of operator/break in the kvb-org-rasci register. "
            "Find the cause, then queue the corrected command with operator.py add break, or drop the step."
        ))
        self._add("break", work, "true", "r", "manual")
        self.assertNotIn("failed", self._register()["operator/break"])
        self.assertEqual(self._open(), ["operator/break"])

    def test_a_failure_shares_stderr_only_on_yes_and_clips_long_lines(self):
        work = self.base / "work"
        work.mkdir()
        self._add("quiet", work, "echo token-$((6 * 7)) >&2; (exit 1)", "r", "manual")
        self._add("wide", work, "printf '%0999d\\n' 0 >&2; (exit 1)", "r", "manual")
        result = self._feed("y\nn\ny\ny\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        register = self._register()
        self.assertEqual(register["operator/quiet"]["failed"], {"why": "exit 1", "output": []})
        self.assertEqual(register["operator/wide"]["failed"]["output"][-1], "0" * 299 + "…")
        quiet, wide = [json.loads(line)["text"] for line in (self.root / "news.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertIn("token-42", result.stderr)
        self.assertNotIn("token-42", quiet)
        self.assertIn("The operator shared no stderr lines.", quiet)
        self.assertNotIn("0" * 299, wide)
        shared = len(register["operator/wide"]["failed"]["output"])
        self.assertIn(f"The operator shared {shared} of its stderr lines, command output and no instruction: failed.output of operator/wide", wide)

    def test_an_interrupt_keeps_the_row_and_a_leftover_process_does_not_block(self):
        work = self.base / "work"
        work.mkdir()
        self._add("abort", work, "(exit 130)", "r", "manual")
        self._add("spawn", work, "sleep 5 >/dev/null & (exit 1)", "r", "manual")
        began = time.monotonic()
        result = self._feed("y\ny\nn\n")
        self.assertLess(time.monotonic() - began, 4)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("interrupted operator/abort: exit 130; the row stays open", result.stdout)
        self.assertIn("failed operator/spawn: exit 1; removed from the queue", result.stdout)
        self.assertEqual(self._open(), ["operator/abort"])
        self.assertEqual(len((self.root / "news.jsonl").read_text(encoding="utf-8").splitlines()), 1)

    def test_a_command_with_a_control_character_is_refused_and_never_run(self):
        result = self._run("add", "two", "--dir", str(self.base), "--command", "echo a\ntouch b", "--reason", "r", "--check", "manual")
        self.assertEqual(result.returncode, 2)
        self.assertIn("holds a control character", result.stderr)
        self._add("forged", self.base, "true", "r", "manual")
        register = self._register()
        register["operator/forged"]["title"] = f"echo a\ntouch {self.base / 'b'}"
        (self.root / "rasci.json").write_text(json.dumps(register), encoding="utf-8")
        self.assertNotIn("```bash", "\n".join(self._out("list")))
        ran = self._feed("y\n")
        self.assertIn("operator: nothing to run", ran.stdout)
        self.assertFalse((self.base / "b").exists())

    def test_a_command_that_cannot_start_leaves_the_queue_too(self):
        gone = self.base / "gone"
        gone.mkdir()
        self._add("gone", gone, "true", "r", "manual")
        gone.rmdir()
        result = self._feed("y\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"failed operator/gone: no start (ENOENT); removed from the queue, the error went to One queued as a call; {self.WAKE}", result.stdout)
        self.assertEqual(self._register()["operator/gone"]["failed"], {"why": "no start (ENOENT)", "output": []})
        self.assertEqual(self._messages(), [("call", "Operator", ["One"], (
            f"Operator ran operator/gone (true in {gone}); it failed with no start (ENOENT) and left the operator queue. "
            "The operator shared no stderr lines. Find the cause, then queue the corrected command with operator.py add gone, or drop the step."
        ))])

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

    def test_list_and_run_escape_control_characters_a_register_row_carries(self):
        self._add("forged", self.base, "true", "r", "manual")
        register = self._register()
        register["operator/forged"].update(workdir=f"{self.base}/\x1bM\x1bM\x08\x08FAKE", check="absent:/x/\x1bM")
        (self.root / "rasci.json").write_text(json.dumps(register), encoding="utf-8")
        listed = "\n".join(self._out("list"))
        ran = self._feed("d\ns\n")
        self.assertEqual(ran.returncode, 0, ran.stderr)
        for out in (listed, ran.stdout):
            with self.subTest(out=out[:40]):
                self.assertNotIn("\x1b", out)
                self.assertNotIn("\x08", out)
                self.assertIn("\\x1bM\\x1bM\\x08\\x08FAKE", out)

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
        self._add("heavy", work, "touch heavy", "build", "manual")
        result = self._feed("y\nh\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        light, heavy = result.stdout.split("[2/2]")
        self.assertIn("[s]kip", light)
        self.assertNotIn("heavy:", light)
        self.assertIn("  heavy      memory stage ok", heavy)
        self.assertRegex(heavy, r"\n    position +id +status +task +eta_min\n")
        self.assertNotIn("workdir", heavy)
        self.assertIn("[h]old in the queue", heavy)
        self.assertNotIn("\x1b", heavy)
        self.assertIn("granted operator/heavy: the queue lets it run now", heavy)
        self.assertEqual(heavy.count("not run operator/heavy"), 2)
        self.assertNotIn("failed", heavy)
        self.assertTrue((work / "light").exists())
        self.assertFalse((work / "heavy").exists())
        self.assertEqual(self._open(), ["operator/heavy"])
        self.assertFalse((self.root / "queue-history.jsonl").exists())

    def test_hold_queues_the_command_as_operator_without_the_claude_session(self):
        self._queue_config({"operator": 0})
        work = self.base / "work"
        work.mkdir()
        self._add("heavy", work, "touch heavy", "build", "manual")
        fake = self.base / "queue.py"
        fake.write_text(
            "import json, os, sys\n"
            "with open(sys.argv[0] + '.calls', 'a', encoding='utf-8') as calls:\n"
            "    calls.write(json.dumps([sys.argv[1:3], os.environ.get('CLAUDE_CODE_SESSION_ID')]) + '\\n')\n"
            "sys.exit(75 if sys.argv[1] == 'hold' else 0)\n",
            encoding="utf-8",
        )
        wrapper = (
            "import importlib.util, sys\n"
            "spec = importlib.util.spec_from_file_location('kvb_operator', sys.argv[1])\n"
            "operator = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(operator)\n"
            "operator.QUEUE = operator.Path(sys.argv[2])\n"
            "sys.argv = [sys.argv[1], 'run']\n"
            "sys.exit(operator.main())\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", wrapper, str(OPERATOR), str(fake)], input="h\n", capture_output=True, text=True,
            env={**self.env, "SHELL": "/bin/sh"}, cwd=self.tmp.name, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("not run operator/heavy", result.stdout)
        calls = [json.loads(line) for line in (self.base / "queue.py.calls").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(calls, [[["list"], "s1"], [["hold", "--kind"], None]])

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

    def test_a_done_run_calls_the_renamed_adder_by_its_stored_name_and_session(self):
        work = self.base / "work"
        work.mkdir()
        self._add("go", work, "true", "r", "manual")
        self._add("later", work, "true", "r", "manual")
        self.assertEqual(self._register()["operator/go"]["sessions"], {"One": "s1"})
        self._session("s1", "Uno")
        listener = self.root / "radio-listen" / "s1.pid"
        listener.parent.mkdir()
        listener.write_text(str(os.getpid()), encoding="utf-8")
        result = self._feed("y\ns\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("done operator/go; the result went to One as a call", result.stdout)
        self.assertIn("skipped operator/later", result.stdout)
        self.assertEqual(self._messages(), [("call", "Operator", ["One"], "Operator ran operator/go: done, exit 0")])
        radio = REPO_ROOT / "skills" / "kvb-org-radio" / "scripts" / "radio.py"
        seen = subprocess.run([sys.executable, str(radio), "show"], capture_output=True, text=True, env=self.env, check=False)
        self.assertEqual([line.split(" ", 3)[3] for line in seen.stdout.splitlines()], ["Operator to One: Operator ran operator/go: done, exit 0"], seen.stderr)

    def test_run_calls_the_stored_session_with_every_outcome_even_when_its_channel_says_post(self):
        work = self.base / "work"
        work.mkdir()
        stale = self.base / "stale"
        stale.write_text("x", encoding="utf-8")
        radio = REPO_ROOT / "skills" / "kvb-org-radio" / "scripts" / "radio.py"
        chosen = subprocess.run([sys.executable, str(radio), "feedback", "set", "post"], capture_output=True, text=True, env=self.env, check=False)
        self.assertEqual(chosen.returncode, 0, chosen.stderr)
        self._add("open", work, "echo out-$((7 * 8)) >&2", "r", f"absent:{stale}")
        self._add("go", work, "echo out-$((6 * 7))", "r", "manual")
        self._add("drop", work, "true", "r", "manual")
        self._add("break", work, "echo out-$((8 * 9)); echo err-$((9 * 9)) >&2; (exit 3)", "r", "manual")
        self._session("s1", "Uno")
        result = self._feed("y\ny\nc\nwrong repo\ny\ny\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.count(f"One queued as a call; {self.WAKE}"), 4, result.stdout)
        rows = [json.loads(line) for line in (self.root / "news.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([(row["class"], row["from"], row["to"], row["to_sessions"]) for row in rows], [("call", "Operator", ["One"], ["s1"])] * 4)
        still, done, dropped, broke = (row["text"] for row in rows)
        self.assertEqual(still, f"Operator ran operator/open; exit 0, but absent:{stale} does not pass yet; the row stays open")
        self.assertEqual(done, "Operator ran operator/go: done, exit 0")
        self.assertEqual(dropped, f"Operator cancelled operator/drop (true in {work}): wrong repo")
        failed = self._register()["operator/break"]["failed"]
        self.assertEqual((failed["why"], failed["output"][-1]), ("exit 3", "err-81"))
        self.assertTrue(broke.startswith("Operator ran operator/break ("), broke)
        self.assertIn(f"; it failed with exit 3 and left the operator queue. The operator shared {len(failed['output'])} of its stderr lines", broke)
        for text in (still, done, dropped, broke):
            for output in ("out-56", "out-42", "out-72", "err-81"):
                with self.subTest(text=text[:30], output=output):
                    self.assertNotIn(output, text)
        self.assertEqual(subprocess.run([sys.executable, str(radio), "feedback", "show"], capture_output=True, text=True, env=self.env, check=False).stdout, "post\n")

    def test_an_older_row_without_a_session_calls_its_party_name_and_an_open_check_is_reported(self):
        stale = self.base / "stale"
        stale.write_text("x", encoding="utf-8")
        self._add("old", self.base, "true", "r", f"absent:{stale}")
        register = self._register()
        register["operator/old"].pop("sessions")
        (self.root / "rasci.json").write_text(json.dumps(register), encoding="utf-8")
        self._session("s1", "Uno")
        result = self._feed("y\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        pending = f"absent:{stale} does not pass yet; the row stays open"
        self.assertIn(f"ran operator/old, but {pending}; the result went to One queued as a call; wake: SendMessage to One\n", result.stdout)
        self.assertEqual(self._messages(), [("call", "Operator", ["One"], f"Operator ran operator/old; exit 0, but {pending}")])
        self.assertNotIn("to_sessions", json.loads((self.root / "news.jsonl").read_text(encoding="utf-8")))
        self.assertEqual(self._open(), ["operator/old"])

    def test_list_and_done_tell_every_holder_but_the_caller(self):
        self._session("s2", "Two")
        stale = self.base / "stale"
        stale.write_text("x", encoding="utf-8")
        for slug in ("mine", "theirs"):
            self._add(slug, self.base, "true", "r", f"absent:{stale}")
        self._add("manual", self.base, "true", "r", "manual")
        self._add("hub", self.base, "true", "r", "manual")
        self._add("self", self.base, "true", "r", "manual")
        stale.unlink()
        self.assertEqual(self._out("list", "--json")[0], "[")
        self._add("mine", self.base, "true", "r", f"absent:{self.base / 'gone'}")
        self.assertEqual(self._as(None, "list", "--session", "s1").stderr, "")
        self.assertEqual(self._messages(), [])
        self._add("theirs", self.base, "true", "r", f"absent:{self.base / 'gone'}")
        listed = self._as("s2", "list", "--json")
        self.assertEqual((listed.returncode, listed.stderr), (0, f"operator: operator/theirs done; the result went to One queued as a call; {self.WAKE}\n"))
        self.assertEqual([row["task"] for row in json.loads(listed.stdout)], ["operator/manual", "operator/hub", "operator/self"])
        self.assertEqual(self._as("s2", "done", "manual").stdout, f"done operator/manual; the result went to One queued as a call; {self.WAKE}\n")
        self.assertEqual(self._as("s2", "done", "manual").stdout, "done operator/manual\n")
        self.assertEqual(self._as(None, "done", "hub").returncode, 0)
        self.assertEqual(self._out("done", "self"), ["done operator/self"])
        self.assertEqual(self._messages(), [
            ("call", "Operator", ["One"], f"operator/theirs done: check passed (absent:{self.base / 'gone'})"),
            ("call", "Operator", ["One"], "operator/manual marked done by Two"),
            ("call", "Operator", ["One"], "operator/hub marked done by Operator"),
        ])
        self._add("flag", self.base, "true", "r", "manual")
        self.assertEqual(self._as(None, "done", "flag", "--session", "s2").returncode, 0)
        self.assertEqual(self._messages()[-1][-1], "operator/flag marked done by Two")
        self._add("late", self.base, "true", "r", f"absent:{self.base / 'gone'}")
        victim = self.base / "victim"
        victim.write_text("keep", encoding="utf-8")
        (self.root / "news.lock").unlink()
        (self.root / "news.lock").symlink_to(victim)
        unsent = self._as("s2", "list")
        self.assertEqual(unsent.returncode, 0, unsent.stderr)
        self.assertRegex(unsent.stderr, r"^operator: operator/late done; the message to One failed: .+\n$")
        self.assertEqual(victim.read_text(encoding="utf-8"), "keep")

    def test_failed_stops_only_the_row_the_hub_ran_and_tells_the_adder(self):
        work = self.base / "work"
        work.mkdir()
        self._add("break", work, "false", "r", "manual")
        self._add("moved", work, "true", "r", "manual")
        shown = ("--command", "false", "--dir", str(work))
        result = self._as(None, "failed", "break", "--why", "exit 3", *shown)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, f"failed operator/break: exit 3; removed from the queue, the error went to One queued as a call; {self.WAKE}\n")
        for args in (("--command", "true", "--dir", str(self.base)), ("--command", "echo evil", "--dir", str(work))):
            with self.subTest(args=args):
                stale = self._as(None, "failed", "moved", "--why", "exit 1", *args)
                self.assertIn("it changed or closed meanwhile and stays as it is", stale.stdout)
        register = self._register()
        self.assertEqual((register["operator/break"]["status"], register["operator/break"]["failed"]), ("stopped", {"why": "exit 3", "output": []}))
        self.assertEqual((register["operator/moved"]["status"], "failed" in register["operator/moved"]), ("queued", False))
        self.assertEqual(self._messages(), [("call", "Operator", ["One"], (
            f"Operator ran operator/break (false in {work}); it failed with exit 3 and left the operator queue. "
            "The operator shared no stderr lines. Find the cause, then queue the corrected command with operator.py add break, or drop the step."
        ))])
        again = self._as(None, "failed", "break", "--why", "exit 3", *shown)
        self.assertIn("it changed or closed meanwhile and stays as it is", again.stdout)
        self.assertEqual(len(self._messages()), 1)
        for args in (("failed", "missing", "--why", "exit 1", *shown), ("failed", "break", "--why", " ", *shown), ("failed", "break", "--why", "exit 1")):
            with self.subTest(args=args):
                self.assertEqual(self._as(None, *args).returncode, 2)

    def test_ran_in_the_hub_container_closes_whatever_the_check_and_reaches_the_pinned_session_and_the_stored_name(self):
        tool = self.bin / "kvb-host-only-tool"
        tool.write_text("#!/bin/sh\n", encoding="utf-8")
        tool.chmod(0o755)
        self._add("go", self.base, "true", "r", "manual")
        self._add("inst", self.base, "true", "r", "binary:kvb-host-only-tool")
        self._add("other", self.base, "true", "r", "manual")
        radio = REPO_ROOT / "skills" / "kvb-org-radio" / "scripts" / "radio.py"
        chosen = subprocess.run([sys.executable, str(radio), "feedback", "set", "call"], capture_output=True, text=True, env=self.env, check=False)
        self.assertEqual(chosen.returncode, 0, chosen.stderr)
        self._session("s1", "Uno")
        hub_home = self.base / "hub-home"
        hub_home.mkdir()
        hub = {"PATH": "/usr/bin:/bin", "HOME": str(hub_home), "AGENTS_COUNCIL_ROOT": str(self.root)}

        def ran(*args: str) -> str:
            result = subprocess.run([sys.executable, str(OPERATOR), "ran", *args], capture_output=True, text=True, env=hub, cwd=self.tmp.name, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout

        shown = ("--command", "true", "--dir", str(self.base))
        wake = "wake: SendMessage to One (session s1)"
        self.assertEqual(ran("go", *shown), f"done operator/go; the result went to One queued as a call; {wake}\n")
        self.assertEqual(ran("inst", *shown), f"done operator/inst; the result went to One queued as a call; {wake}\n")
        self.assertEqual(ran("other", "--command", "true", "--dir", str(hub_home)), "ran operator/other; it changed or closed meanwhile and stays as it is\n")
        self.assertEqual(self._open(), ["operator/other"])
        self.assertEqual(self._messages(), [
            ("call", "Operator", ["One"], "Operator ran operator/go: done, exit 0"),
            ("call", "Operator", ["One"], "Operator ran operator/inst: done, exit 0"),
        ])
        rows = [json.loads(line) for line in (self.root / "news.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([row["to_sessions"] for row in rows], [["s1"], ["s1"]])
        self._session("s2", "One")
        self._session("s3", "Uno")
        expected = ["Operator to One: Operator ran operator/go: done, exit 0", "Operator to One: Operator ran operator/inst: done, exit 0"]
        for sid, seen in (("s1", expected), ("s2", expected), ("s3", [])):
            with self.subTest(sid=sid):
                read = subprocess.run([sys.executable, str(radio), "show"], capture_output=True, text=True, env={**self.env, "CLAUDE_CODE_SESSION_ID": sid}, check=False)
                self.assertEqual([line.split(" ", 3)[3] for line in read.stdout.splitlines()], seen, read.stderr)
        view = (
            "import json, sys\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "from kvb_orchestrator.council import radio_rows\n"
            "rows = [json.loads(line) for line in open(sys.argv[2], encoding='utf-8')]\n"
            "print(json.dumps([row['to'] for row in radio_rows(rows, 0, 1e12)]))\n"
        )
        hub_view = subprocess.run(
            [sys.executable, "-c", view, str(REPO_ROOT / "orchestrator"), str(self.root / "news.jsonl")],
            capture_output=True, text=True, env={**hub, "PYTHONDONTWRITEBYTECODE": "1"}, check=False,
        )
        self.assertEqual(json.loads(hub_view.stdout or "null"), [["One"], ["One"]], hub_view.stderr)
        for args in (("ran", "missing", *shown), ("ran", "go", "--command", "true")):
            with self.subTest(args=args):
                self.assertEqual(self._as(None, *args).returncode, 2)

    def test_the_hub_runner_calls_the_stored_session_with_ran_and_failed_even_when_its_channel_says_post(self):
        radio = REPO_ROOT / "skills" / "kvb-org-radio" / "scripts" / "radio.py"
        chosen = subprocess.run([sys.executable, str(radio), "feedback", "set", "post"], capture_output=True, text=True, env=self.env, check=False)
        self.assertEqual(chosen.returncode, 0, chosen.stderr)
        self._add("go", self.base, "true", "r", "manual")
        self._add("break", self.base, "false", "r", "manual")
        hub_home = self.base / "hub-home"
        hub_home.mkdir()
        runner = (
            "import json, sys, types\n"
            "from pathlib import Path\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "from kvb_orchestrator.jobs import Jobs\n"
            "from kvb_orchestrator.skill_scripts import Scripts\n"
            "hub = types.SimpleNamespace(scripts=Scripts(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4])))\n"
            "print(json.dumps([Jobs.close_row(hub, job, status, code) for job, status, code in json.loads(sys.argv[5])]))\n"
        )
        jobs = [
            [{"task": "operator/go", "command": "true", "directory": str(self.base)}, "done", 0],
            [{"task": "operator/break", "command": "false", "directory": str(self.base)}, "failed", 1],
        ]
        result = subprocess.run(
            [sys.executable, "-c", runner, str(REPO_ROOT / "orchestrator"), str(REPO_ROOT / "skills"), str(self.root), str(hub_home), json.dumps(jobs)],
            capture_output=True, text=True, env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"}, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        runs = json.loads(result.stdout)
        self.assertEqual([[(run["code"], run["stderr"]) for run in job] for job in runs], [[(0, "")], [(0, "")]])
        self.assertEqual([job[0]["stdout"] for job in runs], [
            f"done operator/go; the result went to One queued as a call; {self.WAKE}\n",
            f"failed operator/break: exit 1; removed from the queue, the error went to One queued as a call; {self.WAKE}\n",
        ])
        rows = [json.loads(line) for line in (self.root / "news.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([(row["class"], row["from"], row["to"], row["to_sessions"]) for row in rows], [("call", "Operator", ["One"], ["s1"])] * 2)
        self.assertEqual([row["text"] for row in rows], [
            "Operator ran operator/go: done, exit 0",
            (
                f"Operator ran operator/break (false in {self.base}); it failed with exit 1 and left the operator queue. "
                "The operator shared no stderr lines. Find the cause, then queue the corrected command with operator.py add break, or drop the step."
            ),
        ])
        register = self._register()
        self.assertEqual((register["operator/go"]["status"], register["operator/break"]["status"]), ("done", "stopped"))

    def test_done_leaves_out_the_caller_by_session_id_and_by_name_each_on_its_own(self):
        self._add("by-sid", self.base, "true", "r", "manual")
        self._add("by-name", self.base, "true", "r", "manual")
        register = self._register()
        register["operator/by-name"].pop("sessions")
        (self.root / "rasci.json").write_text(json.dumps(register), encoding="utf-8")
        hub_home = self.base / "hub-home"
        hub_home.mkdir()
        hub = {"PATH": "/usr/bin:/bin", "HOME": str(hub_home), "AGENTS_COUNCIL_ROOT": str(self.root)}
        by_sid = subprocess.run([sys.executable, str(OPERATOR), "done", "by-sid", "--session", "s1"], capture_output=True, text=True, env=hub, check=False)
        self.assertEqual((by_sid.returncode, by_sid.stdout), (0, "done operator/by-sid\n"), by_sid.stderr)
        self.assertEqual(self._out("done", "by-name"), ["done operator/by-name"])
        self.assertEqual(self._messages(), [])

    def test_a_row_closed_outside_run_calls_its_initiator_once_even_when_its_channel_says_post(self):
        radio = REPO_ROOT / "skills" / "kvb-org-radio" / "scripts" / "radio.py"
        chosen = subprocess.run([sys.executable, str(radio), "feedback", "set", "post"], capture_output=True, text=True, env=self.env, check=False)
        self.assertEqual(chosen.returncode, 0, chosen.stderr)
        marks = {slug: self.base / slug for slug in ("swept", "legacy", "later")}
        for slug, mark in marks.items():
            mark.write_text("x", encoding="utf-8")
            self._add(slug, self.base, "true", "r", f"absent:{mark}")
        self._add("manual", self.base, "true", "r", "manual")
        register = self._register()
        register["operator/legacy"].pop("sessions")
        (self.root / "rasci.json").write_text(json.dumps(register), encoding="utf-8")
        self._session("s1", "Uno")
        marks["swept"].unlink()
        marks["legacy"].unlink()
        listed = self._as(None, "list")
        self.assertEqual(listed.stderr, (
            "operator: operator/legacy done; the result went to One queued as a call; wake: SendMessage to One\n"
            f"operator: operator/swept done; the result went to One queued as a call; {self.WAKE}\n"
        ))
        self.assertEqual(self._as(None, "done", "swept").stdout, "done operator/swept\n")
        self.assertEqual(self._as(None, "done", "manual").stdout, f"done operator/manual; the result went to One queued as a call; {self.WAKE}\n")
        self.assertEqual(self._as(None, "done", "manual").stdout, "done operator/manual\n")
        marks["later"].unlink()
        ran = self._feed("q\n")
        self.assertEqual(ran.returncode, 0, ran.stderr)
        self.assertIn("operator: nothing to run", ran.stdout)
        self.assertEqual(self._as(None, "done", "later").stdout, "done operator/later\n")
        self.assertEqual(self._as(None, "list").stdout, "operator: nothing open\n")
        rows = [json.loads(line) for line in (self.root / "news.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([(row["class"], row["from"], row["to"], row.get("to_sessions"), row["text"]) for row in rows], [
            ("call", "Operator", ["One"], None, f"operator/legacy done: check passed (absent:{marks['legacy']})"),
            ("call", "Operator", ["One"], ["s1"], f"operator/swept done: check passed (absent:{marks['swept']})"),
            ("call", "Operator", ["One"], ["s1"], "operator/manual marked done by Operator"),
            ("call", "Operator", ["One"], ["s1"], f"operator/later done: check passed (absent:{marks['later']})"),
        ])

    def test_done_by_the_successor_holding_the_stored_name_reaches_the_renamed_adder_by_its_session_only(self):
        self._add("go", self.base, "true", "r", "manual")
        self._session("s1", "Uno")
        self._session("s2", "One")
        done = self._as("s2", "done", "go")
        self.assertEqual((done.returncode, done.stdout), (0, "done operator/go; the result went to s1 queued as a call; wake: SendMessage to s1 (session s1)\n"), done.stderr)
        self.assertEqual(self._messages(), [("call", "Operator", ["s1"], "operator/go marked done by One")])
        radio = REPO_ROOT / "skills" / "kvb-org-radio" / "scripts" / "radio.py"
        for sid, seen in (("s1", 1), ("s2", 0)):
            with self.subTest(sid=sid):
                read = subprocess.run([sys.executable, str(radio), "show"], capture_output=True, text=True, env={**self.env, "CLAUDE_CODE_SESSION_ID": sid}, check=False)
                self.assertEqual(len(read.stdout.splitlines()), seen, read.stderr)
        self._add("own", self.base, "true", "r", "manual")
        self.assertEqual(self._as("s1", "done", "own").stdout, "done operator/own\n")
        self.assertEqual(len(self._messages()), 1)

    def test_ran_closes_a_stopped_or_running_row_the_hub_ran_and_tells_the_adder(self):
        for slug in ("stopped", "running", "done"):
            self._add(slug, self.base, "true", "r", "manual")
        register = self._register()
        for slug in ("stopped", "running", "done"):
            register[f"operator/{slug}"]["status"] = slug
        register["operator/stopped"].update(failed={"why": "exit 1", "output": []}, cancelled="wrong repo")
        (self.root / "rasci.json").write_text(json.dumps(register), encoding="utf-8")
        shown = ("--command", "true", "--dir", str(self.base))
        for slug in ("stopped", "running"):
            with self.subTest(slug=slug):
                self.assertEqual(self._as(None, "ran", slug, *shown).stdout, f"done operator/{slug}; the result went to One queued as a call; {self.WAKE}\n")
                entry = self._register()[f"operator/{slug}"]
                self.assertEqual((entry["status"], "failed" in entry, "cancelled" in entry), ("done", False, False))
        self.assertEqual(self._as(None, "ran", "done", *shown).stdout, "ran operator/done; it changed or closed meanwhile and stays as it is\n")
        self.assertEqual([message[3] for message in self._messages()], ["Operator ran operator/stopped: done, exit 0", "Operator ran operator/running: done, exit 0"])

    def test_done_drops_the_stale_failure_of_a_stopped_row_like_ran(self):
        self._add("go", self.base, "false", "r", "manual")
        self.assertEqual(self._as(None, "failed", "go", "--why", "exit 1", "--command", "false", "--dir", str(self.base)).returncode, 0)
        register = self._register()
        register["operator/go"]["cancelled"] = "wrong repo"
        (self.root / "rasci.json").write_text(json.dumps(register), encoding="utf-8")
        self.assertEqual(self._out("done", "go"), ["done operator/go"])
        entry = self._register()["operator/go"]
        self.assertEqual((entry["status"], "failed" in entry, "cancelled" in entry), ("done", False, False))

    def test_feedback_for_an_ended_adder_reaches_the_session_now_holding_its_name(self):
        self._add("go", self.base, "true", "r", "manual")
        sessions = self.home / ".claude" / "sessions"
        (sessions / "s1.json").unlink()
        self._session("s2", "One")
        self.assertEqual(self._as(None, "failed", "go", "--why", "exit 1", "--command", "true", "--dir", str(self.base)).returncode, 0)
        radio = REPO_ROOT / "skills" / "kvb-org-radio" / "scripts" / "radio.py"
        seen = subprocess.run([sys.executable, str(radio), "show"], capture_output=True, text=True, env={**self.env, "CLAUDE_CODE_SESSION_ID": "s2"}, check=False)
        self.assertEqual(len(seen.stdout.splitlines()), 1, seen.stderr)
        self.assertIn("Operator to One: Operator ran operator/go (true in", seen.stdout)

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
            ("add", "x", *good, "--check", "absent:/x/\x1bM\x08FAKE"),
            ("add", "x", "--dir", "/srv/\x1bM", "--command", "c", "--reason", "r", "--check", "manual"),
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
