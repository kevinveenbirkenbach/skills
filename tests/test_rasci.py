"""Exercise the kvb-org-rasci register: fields, roles, priority order, claims, artifacts, tools."""

from __future__ import annotations

import datetime
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RASCI = REPO_ROOT / "skills" / "kvb-org-rasci" / "scripts" / "rasci.py"
COUNCIL = REPO_ROOT / "skills" / "kvb-org-organize" / "scripts" / "council.py"
HEADER = "| Prio | WSJF | Task | OKR | Status | Worker | Artifacts | Start | End | R | A | S | C | I |"


def local(iso: str) -> str:
    return datetime.datetime.fromisoformat(iso).astimezone().strftime("%m-%d %H:%M")


class TestRasci(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "home"
        self.root = Path(self.tmp.name) / "council"
        self.sessions = self.home / ".claude" / "sessions"
        self.sessions.mkdir(parents=True)
        for sid, name in (("s1", "One"), ("s2", "Two")):
            (self.sessions / f"{sid}.json").write_text(
                json.dumps({"sessionId": sid, "name": name}), encoding="utf-8"
            )

    def _run(self, *args: str, script: Path = RASCI, sid: str = "s1") -> subprocess.CompletedProcess:
        env = {
            "PATH": "/usr/bin:/bin",
            "HOME": str(self.home),
            "AGENTS_COUNCIL_ROOT": str(self.root),
            "CLAUDE_CODE_SESSION_ID": sid,
        }
        return subprocess.run(
            [sys.executable, str(script), *args],
            capture_output=True,
            text=True,
            env=env,
            cwd=self.tmp.name,
            check=False,
        )

    def _out(self, *args: str) -> list[str]:
        result = self._run(*args)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.splitlines()

    def _claim(self, office: str, session: str, name: str, work: str) -> None:
        path = self.root / office
        path.mkdir(parents=True)
        claim = {
            "office": office,
            "session": session,
            "runtime": "claude-code",
            "name": name,
            "since": "2026-11-01T00:00:00+00:00",
            "beat": time.time(),
            "work": work,
        }
        (path / "claim.json").write_text(json.dumps(claim), encoding="utf-8")

    def test_matrix_orders_by_priority_and_lists_roles(self):
        start = "2026-11-01T10:00:00+00:00"
        self._run("set", "work/a", "--title", "Alpha", "--objective", "Ship A", "--prio", "2",
                  "--status", "running", "--worker", "Skills", "--start", start)
        self._run("role", "work/a", "Skills", "ar")
        self._run("role", "work/a", "Operator", "ic")
        self._run("role", "work/a", "Pkgmgr", "C")
        self._run("set", "work/b", "--title", "Beta", "--prio", "1", "--worker", "subagent Explore (haiku)")
        self._run("role", "work/b", "Pkgmgr", "R")
        lines = self._out("show")
        self.assertEqual(lines[0], HEADER)
        self.assertEqual(
            lines[2], "| 1 | - | work/b: Beta | - | queued | subagent Explore (haiku) | - | - | - | Pkgmgr |  |  |  |  |"
        )
        self.assertEqual(
            lines[3],
            f"| 2 | - | work/a: Alpha | Ship A | running | Skills | - | {local(start)} | - "
            "| Skills | Skills |  | Operator, Pkgmgr | Operator |",
        )
        self.assertEqual(
            lines[4], "gaps: work/b has 0 A; work/b has no key result; work/a has no key result"
        )

    def test_key_results_gate_done_and_fill_the_okr_column(self):
        self._run("set", "work/a", "--objective", "Ship A", "--status", "running")
        self._run("role", "work/a", "Skills", "RA")
        self._run("kr", "work/a", "add", "tests green")
        self._run("kr", "work/a", "add", "released")
        self._run("kr", "work/a", "met", "1")
        lines = self._out("show")
        self.assertIn("| Ship A (1/2 KR) | running |", lines[2])
        self.assertEqual(len(lines), 3)
        self.assertEqual(self._run("set", "work/a", "--status", "done").returncode, 2)
        self.assertIn("key result 2 [ ]: released", self._out("get", "work/a"))
        self._run("kr", "work/a", "met", "2")
        self.assertEqual(self._run("set", "work/a", "--status", "done").returncode, 0)
        self.assertEqual(self._out("show"), ["no tasks"])

    def test_status_sets_start_and_end(self):
        self._run("set", "work/a", "--status", "running")
        self._run("set", "work/a", "--status", "done", "--description", "long text")
        lines = self._out("get", "work/a")
        self.assertIn("status: done", lines)
        self.assertIn("description: long text", lines)
        self.assertTrue(any(line.startswith("start: 20") for line in lines))
        self.assertTrue(any(line.startswith("end: 20") for line in lines))
        self._run("set", "work/a", "--status", "running")
        self.assertFalse(any(line.startswith("end:") for line in self._out("get", "work/a")))

    def test_done_tasks_show_only_with_all(self):
        self._run("set", "work/a", "--status", "done", "--end", "2026-11-01T12:00:00+00:00")
        self._run("role", "work/a", "Skills", "RA")
        self.assertEqual(self._out("show"), ["no tasks"])
        self.assertIn("| done | - |", self._out("show", "--all")[2])

    def test_artifacts_and_tools(self):
        self._run("set", "work/a", "--workdir", "/w/a", "--branch", "feat/a", "--status", "done",
                  "--artifact", "image:core:dev", "--artifact", "volume:db",
                  "--tool", "council.py", "--tool", "make test")
        self._run("set", "work/b", "--worker", "Two", "--tool", "make test", "--artifact", "dir:/tmp/b")
        self._run("set", "work/a", "--drop-artifact", "volume:db")
        self._run("set", "work/b", "--branch", "")
        rows = [line.split("\t") for line in self._out("artifacts")]
        self.assertEqual(
            [row[:4] for row in rows],
            [
                ["done", "work/a", "-", "workdir:/w/a"],
                ["done", "work/a", "-", "branch:feat/a"],
                ["done", "work/a", "-", "image:core:dev"],
                ["queued", "work/b", "Two", "dir:/tmp/b"],
            ],
        )
        self.assertEqual(rows[0][4], "-")
        self.assertRegex(rows[2][4], r"^\d\d-\d\d \d\d:\d\d$")
        self.assertEqual([r.split("\t")[1] for r in self._out("artifacts", "--ended")], ["work/a"] * 3)
        self.assertEqual(len(self._out("artifacts", "--task", "work/b")), 1)
        self.assertIn("| queued | Two | 1 |", self._out("show")[2])
        self.assertTrue(any(line.startswith("artifact: image:core:dev (since ") for line in self._out("get", "work/a")))
        self.assertEqual(
            self._out("tools"), ["2\tmake test\twork/a work/b", "1\tcouncil.py\twork/a"]
        )
        self.assertIn("tool: council.py", self._out("get", "work/a"))

    def test_claims_join_the_matrix_with_holder_as_ra(self):
        self._claim("work/live", "s1", "One", "Gamma")
        self._claim("cluster/dead", "s9", "Gone", "Delta")
        self._claim("chair", "s1", "One", "allocator")
        self._run("set", "work/live", "--prio", "1", "--status", "running")
        self._run("role", "work/live", "Two", "S")
        lines = self._out("show")
        self.assertTrue(lines[2].startswith("| 1 | - | work/live | - | running | One |"))
        self.assertTrue(lines[2].endswith("| One | One | Two |  |  |"))
        self.assertTrue(lines[3].startswith("| 2 | - | cluster/dead | - | stale | Gone |"))
        self.assertFalse(any("chair" in line for line in lines))

    def test_council_claim_takeover_and_release_write_through(self):
        self.assertEqual(self._run("claim", "work/x", "--work", "Do X", script=COUNCIL).returncode, 0)
        lines = self._out("get", "work/x")
        self.assertIn("status: running", lines)
        self.assertIn("worker: One", lines)
        self.assertIn("description: Do X", lines)
        self.assertIn(f"workdir: {self.tmp.name}", lines)
        self.assertIn("roles: One=RA", lines)
        (self.sessions / "s1.json").unlink()
        self.assertEqual(self._run("takeover", "work/x", "--work", "Do X", script=COUNCIL, sid="s2").returncode, 0)
        lines = self._out("get", "work/x")
        self.assertIn("worker: Two", lines)
        self.assertIn("roles: Two=RA", lines)
        self._run("kr", "work/x", "add", "X shipped")
        self.assertEqual(self._run("release", "work/x", script=COUNCIL, sid="s2").returncode, 0)
        lines = self._out("get", "work/x")
        self.assertIn("status: stopped", lines)
        self.assertTrue(any(line.startswith("end: 20") for line in lines))

    def test_rm_and_clear_a_party(self):
        self._run("set", "work/a", "--title", "Alpha")
        self._run("role", "work/a", "Skills", "RA")
        self._run("role", "work/a", "Pkgmgr", "C")
        self._run("role", "work/a", "Pkgmgr", "-")
        self.assertTrue(self._out("show")[2].endswith("| Skills | Skills |  |  |  |"))
        self.assertEqual(self._out("rm", "work/a"), ["removed work/a"])
        self.assertEqual(self._out("show"), ["no tasks"])

    def test_invalid_input_exits_2(self):
        for args in (
            ("role", "work/a", "Skills", "RR"),
            ("role", "work/a", "Skills", "Q"),
            ("set", "Bad Task"),
            ("set", "work/a", "--prio", "0"),
            ("set", "work/a", "--status", "finished"),
            ("set", "work/a", "--start", "yesterday"),
            ("get", "work/none"),
            ("kr", "work/a", "met", "1"),
            ("set", "work/a", "--artifact", "no-kind"),
            ("estimate", "work/a", "One", "--value", "4", "--complexity", "2"),
            ("estimate", "work/a", "One", "--value", "8"),
        ):
            with self.subTest(args=args):
                self.assertEqual(self._run(*args).returncode, 2)
        self.assertFalse((self.root / "rasci.json").exists())

    def test_pipe_in_a_title_does_not_break_the_table(self):
        self._run("set", "work/a", "--title", "a | b")
        self._run("role", "work/a", "Skills", "RA")
        self.assertTrue(self._out("show")[2].startswith("| 1 | - | work/a: a \\| b | - | queued |"))

    def test_wsjf_ranks_by_median_estimates(self):
        self._run("set", "work/a", "--objective", "Ship A")
        self._run("kr", "work/a", "add", "released")
        self._run("estimate", "work/a", "One", "--value", "8", "--complexity", "2")
        self._run("estimate", "work/a", "Two", "--value", "13", "--complexity", "3")
        self._run("estimate", "work/b", "One", "--value", "5", "--complexity", "5")
        self._run("set", "work/c", "--title", "Gamma")
        lines = self._out("wsjf")
        self.assertEqual(
            lines[0], "| Rank | Task | OKR | Business value | Complexity | WSJF | Estimators | Status |"
        )
        self.assertEqual(lines[2], "| 1 | work/a | Ship A (0/1 KR) | 10.5 | 2.5 | 4.2 | One, Two | queued |")
        self.assertEqual(lines[3], "| 2 | work/b | - | 5 | 5 | 1 | One | queued |")
        self.assertEqual(lines[4], "| 3 | work/c | - | - | - | - | - | queued |")
        self.assertEqual(lines[5], "unestimated: work/c")
        self.assertTrue(self._out("show")[2].startswith("| 1 | 4.2 | work/a |"))
        self.assertIn("wsjf: 4.2", self._out("get", "work/a"))
        self._run("set", "work/c", "--prio", "1")
        self.assertTrue(self._out("show")[2].startswith("| 1 | - | work/c: Gamma |"))
        self._run("estimate", "work/b", "One", "--drop")
        self.assertFalse(any(line.startswith("estimate ") for line in self._out("get", "work/b")))

    def test_order_pins_the_agents_in_the_operators_order(self):
        self._run("set", "work/a1", "--worker", "Alpha", "--prio", "1")
        self._run("set", "work/a2", "--worker", "Alpha", "--prio", "2")
        self._run("set", "work/b1", "--worker", "Beta", "--prio", "3")
        self._run("set", "work/c1", "--worker", "Gamma")
        self._run("estimate", "work/c1", "One", "--value", "8", "--complexity", "2")
        self.assertEqual(
            self._out("agents"),
            ["1\tAlpha\t2\twork/a1, work/a2", "2\tBeta\t1\twork/b1", "3\tGamma\t1\twork/c1"],
        )
        self.assertEqual(
            self._out("order", "Gamma, Beta"), ["pinned 2 tasks of 2 agents; the others rank by WSJF after them"]
        )
        self.assertEqual(
            self._out("agents"),
            ["1\tGamma\t1\twork/c1", "2\tBeta\t1\twork/b1", "3\tAlpha\t2\twork/a1, work/a2"],
        )
        self.assertTrue(self._out("show")[2].startswith("| 1 | 4 | work/c1 |"))
        self.assertNotIn("prio: 1", self._out("get", "work/a1"))
        for args in (("order", "Gamma,Nobody"), ("order", "Beta,Beta"), ("order", " , ")):
            with self.subTest(args=args):
                self.assertEqual(self._run(*args).returncode, 2)


class TestOrgSkillsUseTheRegister(unittest.TestCase):
    def test_every_org_skill_names_the_register(self):
        for skill in sorted((REPO_ROOT / "skills").glob("kvb-org-*/SKILL.md")):
            if skill.parent.name == "kvb-org-rasci":
                continue
            with self.subTest(skill=skill.parent.name):
                self.assertIn("`kvb-org-rasci`", skill.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
