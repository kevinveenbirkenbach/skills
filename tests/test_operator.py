"""Exercise kvb-org-operator: operator rows in the rasci register, their done checks, the printed list."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OPERATOR = REPO_ROOT / "skills" / "kvb-org-operator" / "scripts" / "operator.py"
RASCI = REPO_ROOT / "skills" / "kvb-org-rasci" / "scripts" / "rasci.py"
HEADER = "| # | Directory | Command | Why | Check |"
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
                "",
                "```bash",
                f"cd {repo}",
                "git commit -m wip",
                f"cd {repo}",
                "git-sign-push",
                f"cd {src}",
                "make install",
                f"cd {base}",
                "pipx install kvb-fake-tool",
                f"cd {base}",
                f"sudo rm {stale}",
                f"cd {base}",
                "sudo reboot",
                f"cd {base}",
                "sudo systemctl restart docker",
                "```",
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
            self._out("list")[-4:],
            ["```bash", f"cd {self.base}", "sudo reboot", "```"],
        )

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
