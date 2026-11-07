"""Exercise the kvb-org-rasci register: fields, roles, priority order, claims, artifacts, tools."""

from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RASCI = REPO_ROOT / "skills" / "kvb-org-rasci" / "scripts" / "rasci.py"
COUNCIL = REPO_ROOT / "skills" / "kvb-org-organize" / "scripts" / "council.py"
WIDE_HEADER = "| Prio | WSJF | Task | OKR | Status | Worker | Artifacts | Start | End | R | A | S | C | I |"
COMPACT_HEADER = "| Prio | WSJF | Task | Status | Worker | A |"


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

    def _run(self, *args: str, script: Path = RASCI, sid: str = "s1", timeout: float | None = None) -> subprocess.CompletedProcess:
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
            timeout=timeout,
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

    def _two_tasks(self) -> str:
        start = "2026-11-01T10:00:00+00:00"
        self._run("set", "work/a", "--title", "Alpha", "--objective", "Ship A", "--prio", "2",
                  "--status", "running", "--worker", "Skills", "--start", start)
        self._run("role", "work/a", "Skills", "ar")
        self._run("role", "work/a", "Operator", "ic")
        self._run("role", "work/a", "Pkgmgr", "C")
        self._run("set", "work/b", "--title", "Beta", "--prio", "1", "--worker", "subagent Explore (haiku)")
        self._run("role", "work/b", "Pkgmgr", "R")
        return start

    def test_wide_matrix_orders_by_priority_and_lists_roles(self):
        start = self._two_tasks()
        lines = self._out("show", "--wide")
        self.assertEqual(lines[0], WIDE_HEADER)
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

    def test_show_prints_the_compact_table_by_default(self):
        self._two_tasks()
        self.assertEqual(
            self._out("show"),
            [
                COMPACT_HEADER,
                "|---|---|---|---|---|---|",
                "| 1 | - | work/b: Beta | queued | subagent Explore (haiku) |  |",
                "| 2 | - | work/a: Alpha | running | Skills | Skills |",
                "gaps: work/b has 0 A; work/b has no key result; work/a has no key result",
            ],
        )

    def test_compact_cells_keep_the_slug_and_truncate_title_worker_and_a(self):
        slug = "work/" + "s" * 45
        self._run("set", slug, "--title", "Hidden", "--prio", "1")
        self._run("set", "work/a", "--title", "A title far longer than the forty character cell",
                  "--prio", "2", "--worker", "subagent general-purpose (default)")
        self._run("role", "work/a", "Accountable Party With A Long Name", "A")
        lines = self._out("show")
        self.assertEqual(lines[2], f"| 1 | - | {slug}… | queued | - |  |")
        self.assertEqual(
            lines[3],
            "| 2 | - | work/a: A title far longer than the for… | queued | subagent general-purpos… "
            "| Accountable Party With … |",
        )

    def test_key_results_gate_done_and_fill_the_okr_column(self):
        self._run("set", "work/a", "--objective", "Ship A", "--status", "running")
        self._run("role", "work/a", "Skills", "RA")
        self._run("kr", "work/a", "add", "tests green")
        self._run("kr", "work/a", "add", "released")
        self._run("kr", "work/a", "met", "1")
        lines = self._out("show", "--wide")
        self.assertIn("| Ship A (1/2 KR) | running |", lines[2])
        self.assertEqual(len(lines), 3)
        self.assertNotIn("Ship A", self._out("show")[2])
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

    def test_base_names_the_upstream_branch_after_the_branch(self):
        self._run("set", "work/side", "--branch", "sidetree", "--base", "line")
        lines = self._out("get", "work/side")
        self.assertIn("base: line", lines)
        self.assertEqual(lines.index("base: line"), lines.index("branch: sidetree") + 1)
        self.assertEqual(json.loads((self.root / "rasci.json").read_text(encoding="utf-8"))["work/side"]["base"], "line")
        self._run("set", "work/side", "--base", "")
        self.assertFalse(any(line.startswith("base:") for line in self._out("get", "work/side")))

    def test_done_tasks_show_only_with_all(self):
        self._run("set", "work/a", "--status", "done", "--end", "2026-11-01T12:00:00+00:00")
        self._run("role", "work/a", "Skills", "RA")
        self.assertEqual(self._out("show"), ["no tasks"])
        self.assertEqual(self._out("show", "--wide"), ["no tasks"])
        self.assertEqual(self._out("show", "--all")[2], "| 1 | - | work/a | done | - | Skills |")
        self.assertIn(
            f"| done | - | - | - | {local('2026-11-01T12:00:00+00:00')} |", self._out("show", "--all", "--wide")[2]
        )

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
        self.assertIn("| queued | Two | 1 |", self._out("show", "--wide")[2])
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
        lines = self._out("show", "--wide")
        self.assertTrue(lines[2].startswith("| 1 | - | work/live | - | running | One |"))
        self.assertTrue(lines[2].endswith("| One | One | Two |  |  |"))
        self.assertTrue(lines[3].startswith("| 2 | - | cluster/dead | - | stale | Gone |"))
        self.assertFalse(any("chair" in line for line in lines))
        lines = self._out("show")
        self.assertEqual(lines[2], "| 1 | - | work/live | running | One | One |")
        self.assertEqual(lines[3], "| 2 | - | cluster/dead | stale | Gone | Gone |")
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
        self.assertTrue(self._out("show", "--wide")[2].endswith("| Skills | Skills |  |  |  |"))
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
        self.assertTrue(self._out("show", "--wide")[2].startswith("| 1 | - | work/a: a \\| b | - | queued |"))
        self.assertEqual(self._out("show")[2], "| 1 | - | work/a: a \\| b | queued | - | Skills |")

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

    def test_hotfix_and_operator_rows_are_no_work_tasks_for_gaps_and_wsjf(self):
        self._run("set", "work/a")
        self._run("role", "work/a", "Skills", "RA")
        self._run("kr", "work/a", "add", "released")
        self._run("set", "hotfix/db", "--status", "running")
        self._run("set", "operator/push", "--status", "running")
        shown = self._out("show")
        self.assertEqual([line.split(" | ")[2] for line in shown[2:]], ["hotfix/db", "operator/push", "work/a"])
        self.assertFalse(any(line.startswith("gaps:") for line in shown))
        self.assertEqual(
            self._out("wsjf")[2:], ["| 1 | work/a | - (0/1 KR) | - | - | - | - | queued |", "unestimated: work/a"]
        )
        self._run("set", "work/b", "--title", "Beta")
        self.assertEqual(self._out("show")[-1], "gaps: work/b has 0 A; work/b has no R; work/b has no key result")
        self._run("set", "hotfix/db", "--status", "done", "--branch", "fix/db", "--workdir", "/w/db")
        self._run("set", "operator/push", "--branch", "main", "--artifact", "dir:/tmp/push")
        self._run("set", "work/a", "--branch", "feat/a")
        for args in (("artifacts",), ("artifacts", "--ended"), ("artifacts", "--task", "hotfix/db")):
            with self.subTest(args=args):
                self.assertEqual([line.split("\t")[1] for line in self._out(*args)],
                                 ["work/a"] if args == ("artifacts",) else [])

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

    def test_a_symlinked_register_is_refused_and_never_copied_into_the_council(self):
        outside = Path(self.tmp.name) / "outside.json"
        outside.write_text(json.dumps({"outside": {"title": "marker-outside"}}), encoding="utf-8")
        self.root.mkdir()
        (self.root / "rasci.json").symlink_to(outside)
        for args in (("show", "--all"), ("set", "work/a", "--title", "A")):
            with self.subTest(args=args):
                result = self._run(*args, timeout=60)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertNotIn("outside", result.stdout)
        self.assertTrue((self.root / "rasci.json").is_symlink())
        copies = [p.name for p in self.root.iterdir() if p.is_file() and not p.is_symlink()
                  and "marker-outside" in p.read_text(encoding="utf-8")]
        self.assertEqual(copies, [])

    def test_a_hard_linked_register_is_refused(self):
        outside = Path(self.tmp.name) / "outside.json"
        outside.write_text(json.dumps({"outside": {"title": "marker-outside"}}), encoding="utf-8")
        self.root.mkdir()
        os.link(outside, self.root / "rasci.json")
        result = self._run("show", "--all", timeout=60)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertNotIn("outside", result.stdout)

    def test_a_symlinked_lock_is_refused_and_creates_nothing_at_its_target(self):
        aimed = Path(self.tmp.name) / "elsewhere" / "aimed"
        aimed.parent.mkdir()
        self.root.mkdir()
        (self.root / "rasci.lock").symlink_to(aimed)
        result = self._run("set", "work/a", "--title", "A", timeout=60)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertFalse(aimed.exists())
        self.assertFalse((self.root / "rasci.json").exists())

    def test_a_fifo_register_fails_instead_of_hanging(self):
        self.root.mkdir()
        os.mkfifo(self.root / "rasci.json")
        for args in (("show",), ("set", "work/a")):
            with self.subTest(args=args):
                self.assertEqual(self._run(*args, timeout=20).returncode, 2)

    def test_a_register_that_is_no_object_of_tasks_exits_2(self):
        self.root.mkdir()
        for text in ("[1, 2]", json.dumps({"work/a": 3}), "[" * 100000):
            with self.subTest(text=text[:12]):
                (self.root / "rasci.json").write_text(text, encoding="utf-8")
                result = self._run("show", "--all", timeout=60)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("rasci:", result.stderr)


class TestOrgSkillsUseTheRegister(unittest.TestCase):
    def test_every_org_skill_names_the_register(self):
        for skill in sorted((REPO_ROOT / "skills").glob("kvb-org-*/SKILL.md")):
            if skill.parent.name == "kvb-org-rasci":
                continue
            with self.subTest(skill=skill.parent.name):
                self.assertIn("`kvb-org-rasci`", skill.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
