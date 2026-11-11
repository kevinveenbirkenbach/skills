"""Exercise the kvb-org-organize council script: election, staleness, release, list, gate."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
COUNCIL = REPO_ROOT / "skills" / "kvb-org-organize" / "scripts" / "council.py"


class TestCouncil(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "home"
        self.root = Path(self.tmp.name) / "council"
        self.sessions = self.home / ".claude" / "sessions"
        self.sessions.mkdir(parents=True)
        self._live("s1", "One")
        self._live("s2", "Two")

    def _live(self, sid: str, name: str) -> None:
        (self.sessions / f"{sid}.json").write_text(
            json.dumps({"sessionId": sid, "name": name}), encoding="utf-8"
        )

    def _run(self, sid: str, *args: str, stdin: str = "", cwd: str | None = None) -> subprocess.CompletedProcess:
        env = {
            "PATH": "/usr/bin:/bin",
            "HOME": str(self.home),
            "AGENTS_COUNCIL_ROOT": str(self.root),
            "CLAUDE_CODE_SESSION_ID": sid,
        }
        return subprocess.run(
            [sys.executable, str(COUNCIL), *args],
            capture_output=True,
            text=True,
            env=env,
            input=stdin,
            cwd=cwd,
            check=False,
            timeout=30,
        )

    def _repo(self) -> Path:
        repo = Path(self.tmp.name) / "repo"
        (repo / ".git").mkdir(parents=True)
        (repo / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        return repo

    def test_first_claim_wins_and_second_is_refused(self):
        self.assertEqual(self._run("s1", "claim", "work/x", "--work", "w").returncode, 0)
        second = self._run("s2", "claim", "work/x", "--work", "w")
        self.assertEqual(second.returncode, 3)
        self.assertIn('"session": "s1"', second.stdout)

    def test_dead_holder_is_stale_and_can_be_taken_over(self):
        self._run("s1", "claim", "work/x", "--work", "w")
        (self.sessions / "s1.json").unlink()
        self.assertEqual(self._run("s2", "claim", "work/x", "--work", "w").returncode, 4)
        self.assertEqual(self._run("s2", "takeover", "work/x", "--work", "w").returncode, 0)
        self.assertIn('"session": "s2"', (self.root / "work/x/claim.json").read_text())

    def test_takeover_of_a_live_holder_is_refused(self):
        self._run("s1", "claim", "work/x", "--work", "w")
        self.assertEqual(self._run("s2", "takeover", "work/x", "--work", "w").returncode, 3)

    def test_session_flag_cannot_hide_the_claude_code_session(self):
        self._run("s1", "claim", "work/x", "--work", "w", "--session", "One")
        self.assertIn('"session": "s1"', (self.root / "work/x/claim.json").read_text())
        self.assertEqual(self._run("s1", "release", "work/x", "--session", "One").returncode, 0)

    def test_only_the_holder_releases(self):
        self._run("s1", "claim", "work/x", "--work", "w")
        self.assertEqual(self._run("s2", "release", "work/x").returncode, 3)
        self.assertEqual(self._run("s1", "release", "work/x").returncode, 0)
        self.assertFalse((self.root / "work/x").exists())

    def test_no_flag_lets_an_agent_take_over_or_release_a_live_holder(self):
        self._run("s1", "claim", "security/gui", "--work", "w")
        before = (self.root / "security/gui/claim.json").read_text(encoding="utf-8")
        for args in (("takeover", "security/gui", "--work", "w2"), ("takeover", "security/gui", "--work", "w2", "--operator"), ("release", "security/gui"), ("release", "security/gui", "--operator")):
            with self.subTest(args=args):
                self.assertIn(self._run("s2", *args).returncode, (2, 3))
        self.assertEqual((self.root / "security/gui/claim.json").read_text(encoding="utf-8"), before)

    def test_no_office_operation_follows_a_planted_link(self):
        outside = Path(self.tmp.name) / "outside"
        (outside / "gui").mkdir(parents=True)
        (outside / "gui" / "keep.txt").write_text("x", encoding="utf-8")
        (outside / "gui" / "claim.json").write_text(json.dumps({"session": "s1", "runtime": "claude-code", "beat": 1.0}), encoding="utf-8")
        self.root.mkdir()
        (self.root / "security").symlink_to(outside)
        for args in (
            ("takeover", "security/gui", "--work", "w"),
            ("release", "security/gui"),
            ("claim", "security/new", "--work", "w"),
            ("claim", "security/gui", "--work", "w"),
        ):
            with self.subTest(args=args):
                self.assertNotEqual(self._run("s2", *args).stdout.split(" ")[0], "elected")
        self.assertEqual(sorted(path.name for path in outside.rglob("*")), ["claim.json", "gui", "keep.txt"])
        (self.root / "work").mkdir()
        (self.root / "work" / "x").symlink_to(outside / "gui")
        self.assertEqual(self._run("s2", "takeover", "work/x", "--work", "w").returncode, 3)
        self.assertTrue((outside / "gui" / "keep.txt").exists())

    def test_a_claim_from_the_root_directory_records_no_workdir_or_branch(self):
        self.assertEqual(self._run("s2", "claim", "work/y", "--work", "appointed", cwd="/").returncode, 0)
        row = json.loads((self.root / "rasci.json").read_text(encoding="utf-8"))["work/y"]
        self.assertEqual((row["worker"], row["description"], row["status"]), ("Two", "appointed", "running"))
        self.assertNotIn("workdir", row)
        self.assertNotIn("branch", row)

    def test_a_vacant_office_is_taken_over_without_a_council_root_or_group(self):
        self.assertEqual(self._run("s1", "takeover", "work/x", "--work", "w").stdout, "elected work/x\n")
        self.assertEqual(self._run("s1", "takeover", "security/gui", "--work", "w").stdout, "elected security/gui\n")

    def test_a_beat_racing_a_release_never_brings_the_office_back(self):
        spec = importlib.util.spec_from_file_location("council_beat_race", COUNCIL)
        council = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(council)
        self.root.mkdir()
        council.ROOT = self.root
        released = {"session": "s1", "runtime": "claude-code", "beat": 1.0}
        council.claims = lambda: [("work/gone", dict(released))]
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ID": "s1"}):
            self.assertEqual(council.cmd_beat(argparse.Namespace(session=None)), 0)
        self.assertEqual(sorted(self.root.rglob("*")), [])

    def test_gate_blocks_unclaimed_edits_in_a_git_worktree_only(self):
        repo = self._repo()
        inside = json.dumps({"session_id": "s1", "tool_input": {"file_path": str(repo / "f")}})
        outside = json.dumps(
            {"session_id": "s1", "tool_input": {"file_path": str(self.home / "f")}}
        )
        self.assertEqual(self._run("s1", "gate", stdin=inside).returncode, 2)
        self.assertEqual(self._run("s1", "gate", stdin=outside).returncode, 0)
        self._run("s1", "claim", "work/x", "--work", "w")
        self.assertEqual(self._run("s1", "gate", stdin=inside).returncode, 0)

    def test_gate_counts_only_a_git_dir_holding_head_or_a_gitdir_file(self):
        base = Path(self.tmp.name)
        (base / "stray" / ".git").mkdir(parents=True)
        (base / "linked").mkdir()
        (base / "linked" / ".git").write_text("gitdir: /elsewhere/.git/worktrees/linked\n", encoding="utf-8")
        (base / "fifo").mkdir()
        os.mkfifo(base / "fifo" / ".git", 0o600)
        for folder, code in (("stray", 0), ("linked", 2), ("fifo", 0)):
            with self.subTest(folder=folder):
                edit = json.dumps({"session_id": "s1", "tool_input": {"file_path": str(base / folder / "f")}})
                self.assertEqual(self._run("s1", "gate", stdin=edit).returncode, code)

    def test_gate_still_blocks_past_a_planted_fifo_or_malformed_claim(self):
        repo = self._repo()
        inside = json.dumps({"session_id": "s1", "tool_input": {"file_path": str(repo / "f")}})
        (self.root / "work" / "fifo").mkdir(parents=True)
        os.mkfifo(self.root / "work" / "fifo" / "claim.json", 0o600)
        for claim in ({}, [], {"session": "s2", "runtime": "claude-code"}):
            with self.subTest(claim=claim):
                (self.root / "work" / "bad").mkdir(exist_ok=True)
                (self.root / "work" / "bad" / "claim.json").write_text(json.dumps(claim), encoding="utf-8")
                env = {"PATH": "/usr/bin:/bin", "HOME": str(self.home), "AGENTS_COUNCIL_ROOT": str(self.root)}
                result = subprocess.run(
                    [sys.executable, str(COUNCIL), "gate"],
                    capture_output=True, text=True, env=env, input=inside, check=False, timeout=30,
                )
                self.assertEqual(result.returncode, 2, result.stderr)

    def _two_claims(self) -> str:
        work = "fix the failing deploy of web-app-x on branch fix/web-app-x/deploy"
        self._run("s1", "claim", "work/x", "--work", work)
        self._run("s2", "claim", "work/y", "--work", "short work")
        (self.sessions / "s2.json").unlink()
        return work

    def _since(self, office: str) -> str:
        return json.loads((self.root / office / "claim.json").read_text(encoding="utf-8"))["since"]

    def test_list_prints_office_holder_state_and_a_short_work_cell(self):
        self._two_claims()
        result = self._run("s1", "list")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["work/x\tOne\tlive\tfix the failing deploy of web-app-x on …", "work/y\tTwo\tstale\tshort work"],
        )

    def test_list_collapses_whitespace_in_the_short_work_cell(self):
        self._run("s1", "claim", "work/z", "--work", "a\tb\nc")
        self.assertEqual(self._run("s1", "list").stdout.splitlines(), ["work/z\tOne\tlive\ta b c"])

    def test_list_long_prints_since_and_the_whole_work_line(self):
        work = self._two_claims()
        self.assertEqual(
            self._run("s1", "list", "--long").stdout.splitlines(),
            [
                f"work/x\tOne\t{self._since('work/x')}\tlive\t{work}",
                f"work/y\tTwo\t{self._since('work/y')}\tstale\tshort work",
            ],
        )

    def test_list_mine_keeps_only_the_callers_claims_in_both_forms(self):
        work = self._two_claims()
        self.assertEqual(
            self._run("s1", "list", "--mine").stdout.splitlines(),
            ["work/x\tOne\tlive\tfix the failing deploy of web-app-x on …"],
        )
        self.assertEqual(
            self._run("s1", "list", "--mine", "--long").stdout.splitlines(),
            [f"work/x\tOne\t{self._since('work/x')}\tlive\t{work}"],
        )

    def test_invalid_office_is_a_usage_error(self):
        self.assertEqual(self._run("s1", "claim", "../x", "--work", "w").returncode, 2)


if __name__ == "__main__":
    unittest.main()
