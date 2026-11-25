from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import unittest
from pathlib import Path

from hub_case import HubCase
from hub_support import GIT_ENV, HUB
from test_hub_cleanup import (
    FAKE_PKGMGR,
    INSTALLED_PKGMGR,
    KEPT_PATCH,
    capture_local_plan,
)

LOCAL_PLAN = HUB / "client" / "local_plan.py"
TREE_UNIT = HUB / "systemd" / "kvb-orchestrator-tree.service"


class TestLocalPlan(HubCase):
    def fake(self) -> Path:
        fake = self.outside / "bin" / "pkgmgr"
        fake.parent.mkdir(parents=True)
        fake.write_text(FAKE_PKGMGR.format(python=sys.executable), encoding="utf-8")
        fake.chmod(0o755)
        return fake

    def argv(self, pkgmgr: Path, budget: int) -> list[str]:
        return [sys.executable, str(LOCAL_PLAN), "--tree", str(self.tree_file), "--pkgmgr", str(pkgmgr), "--budget", str(budget)]

    def plan(self, pkgmgr: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
        return subprocess.run(self.argv(pkgmgr, 240), env=env, capture_output=True, text=True, timeout=300, check=False)

    def repository(self, name: str) -> Path:
        repo = Path(os.path.realpath(self.outside)) / "repos" / name
        for folder in ("refs/heads", "refs/remotes/origin", "worktrees/demo-side"):
            (repo / ".git" / folder).mkdir(parents=True)
        for path, text in (("HEAD", "ref: refs/heads/main\n"), ("config", "[core]\n"), ("refs/heads/side", "a" * 40 + "\n"), ("worktrees/demo-side/index", "index")):
            (repo / ".git" / path).write_text(text, encoding="utf-8")
        return repo

    def calls(self, fake: Path) -> list[list[str]]:
        log = fake.parent / "calls.jsonl"
        found = [[json.loads(line)["cwd"], *json.loads(line)["argv"]] for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []
        log.unlink(missing_ok=True)
        return found

    def written(self) -> dict[str, dict]:
        data = json.loads(self.tree_file.with_name("local-plan.json").read_text(encoding="utf-8"))
        return {Path(entry["repo"]).name: entry for entry in data["repos"]}

    def test_it_plans_only_the_known_repositories_whose_refs_or_config_changed_since_their_last_plan(self):
        fake = self.fake()
        items = [{"branch": "side", "local_sha": "a" * 40, "state": "merged-clean", "skip": None, "actions": ["local-branch"]}]
        (fake.parent / "plan.json").write_text(json.dumps(items), encoding="utf-8")
        repo = self.repository("demo")
        stranger = self.outside / "repos" / "stranger"
        stranger.mkdir()
        self.tree_file.write_text(json.dumps({"repos": [{"path": str(repo), "known": True, "missing": False}, {"path": str(stranger), "known": False, "missing": False}]}), encoding="utf-8")
        written = self.tree_file.with_name("local-plan.json")

        def run(changes: dict[str, str]) -> tuple[int, list[list[str]], dict]:
            for name, text in changes.items():
                (repo / ".git" / name).parent.mkdir(parents=True, exist_ok=True)
                (repo / ".git" / name).write_text(text, encoding="utf-8")
            done = self.plan(fake, dict(os.environ))
            data = json.loads(written.read_text(encoding="utf-8"))
            self.assertTrue(all(len(entry.pop("fingerprint")) == 64 for entry in data["repos"]))
            return done.returncode, self.calls(fake), data

        code, calls, plan = run({})
        self.assertEqual((code, calls), (0, [[str(repo), "branch", "cleanup", "--local", "--json"]]))
        self.assertEqual(plan, {"repos": [{"repo": str(repo), "default": "origin/main", "merged_into": [], "warnings": [], "items": items}]})
        cases = (
            ("nothing changed", {}, []),
            ("a worktree index changed", {"worktrees/demo-side/index": "index, refreshed"}, []),
            ("a branch moved", {"refs/heads/side": "b" * 40 + "\n"}, [[str(repo), "branch", "cleanup", "--local", "--json"]]),
            ("an upstream or deleteMerged changed", {"config": "[core]\n[branch \"side\"]\n\tdeleteMerged = false\n"}, [[str(repo), "branch", "cleanup", "--local", "--json"]]),
            ("origin moved", {"refs/remotes/origin/main": "c" * 40 + "\n"}, [[str(repo), "branch", "cleanup", "--local", "--json"]]),
            ("a reftable table list changed", {"reftable/tables.list": "0x000000000001-0x000000000002-a.ref\n"}, [[str(repo), "branch", "cleanup", "--local", "--json"]]),
        )
        for name, changes, expected in cases:
            with self.subTest(name=name):
                code, calls, again = run(changes)
                self.assertEqual((code, calls, again), (0, expected, plan))
        (fake.parent / "plan.json").write_text("not json", encoding="utf-8")
        code, calls, stale = run({"refs/heads/side": "d" * 40 + "\n"})
        self.assertEqual((code, len(calls), stale["repos"][0]["items"]), (1, 1, items))
        self.assertRegex(stale["repos"][0]["stale"], r"^replan failed at \d{4}-\d\d-\d\dT")
        self.assertEqual(run({})[:2], (0, []))
        (fake.parent / "plan.json").write_text(json.dumps(items), encoding="utf-8")
        code, calls, plan = run({"refs/heads/side": "e" * 40 + "\n"})
        self.assertEqual((code, len(calls), plan["repos"][0].get("stale")), (0, 1, None))
        written.unlink()
        code, calls, plan = run({})
        self.assertEqual((code, len(calls), len(plan["repos"])), (0, 1, 1))
        self.assertEqual(sorted(path.name for path in written.parent.iterdir()), ["branch-tree.json", "local-plan.json"])

    def test_a_sigterm_during_one_slow_replan_keeps_the_plans_written_before_it_and_the_slow_one_is_not_replanned_unchanged(self):
        fake = self.fake()
        (fake.parent / "plan.json").write_text(json.dumps([{"branch": "fresh", "local_sha": "a" * 40}]), encoding="utf-8")
        fast, slow = self.repository("fast"), self.repository("slow")
        (fake.parent / "slow.txt").write_text(str(slow), encoding="utf-8")
        self.tree_file.write_text(json.dumps({"repos": [{"path": str(fast), "known": True}, {"path": str(slow), "known": True}]}), encoding="utf-8")
        self.tree_file.with_name("local-plan.json").write_text(json.dumps({"repos": [{"repo": str(fast), "fingerprint": "old", "items": [{"branch": "old", "local_sha": "b" * 40}]}]}), encoding="utf-8")
        child = subprocess.Popen(self.argv(fake, 240), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and "slow" not in self.written():
            time.sleep(0.2)
        os.killpg(child.pid, signal.SIGTERM)
        child.wait(timeout=20)
        plans = self.written()
        self.assertEqual({name: [item["branch"] for item in entry["items"]] for name, entry in plans.items()}, {"fast": ["fresh"], "slow": []})
        self.assertNotIn("stale", plans["fast"])
        self.assertRegex(plans["slow"]["stale"], r"^replan started \d{4}-\d\d-\d\dT\S+ has not finished$")
        self.calls(fake)
        done = self.plan(fake, dict(os.environ))
        self.assertEqual((done.returncode, self.calls(fake), self.written()), (0, [], plans))

    def test_a_replan_over_its_budget_is_marked_stale_and_retried_only_after_its_refs_change(self):
        fake = self.fake()
        (fake.parent / "plan.json").write_text(json.dumps([{"branch": "fresh", "local_sha": "a" * 40}]), encoding="utf-8")
        slow = self.repository("slow")
        self.tree_file.write_text(json.dumps({"repos": [{"path": str(slow), "known": True}]}), encoding="utf-8")
        self.assertEqual(self.plan(fake, dict(os.environ)).returncode, 0)
        self.assertEqual(len(self.calls(fake)), 1)
        (fake.parent / "slow.txt").write_text(str(slow), encoding="utf-8")
        (slow / ".git" / "refs" / "heads" / "side").write_text("b" * 40 + "\n", encoding="utf-8")
        started = time.monotonic()
        timed_out = subprocess.run(self.argv(fake, 1), capture_output=True, text=True, timeout=60, check=False)
        self.assertLess(time.monotonic() - started, 20)
        self.assertEqual((timed_out.returncode, len(self.calls(fake))), (1, 1))
        stale = self.written()["slow"]
        self.assertEqual([item["branch"] for item in stale["items"]], ["fresh"])
        self.assertRegex(stale["stale"], r"^replan timed out at \d{4}-\d\d-\d\dT")
        again = subprocess.run(self.argv(fake, 1), capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual((again.returncode, self.calls(fake), self.written()["slow"]), (0, [], stale))
        (fake.parent / "slow.txt").unlink()
        (slow / ".git" / "refs" / "heads" / "side").write_text("c" * 40 + "\n", encoding="utf-8")
        self.assertEqual(subprocess.run(self.argv(fake, 1), capture_output=True, text=True, timeout=60, check=False).returncode, 0)
        self.assertEqual((len(self.calls(fake)), self.written()["slow"].get("stale")), (1, None))

    def test_the_tree_timer_writes_the_local_dry_run_after_the_tree(self):
        starts = [line.split("=", 1)[1] for line in TREE_UNIT.read_text(encoding="utf-8").splitlines() if line.startswith("ExecStart=")]
        self.assertEqual(len(starts), 3)
        self.assertIn("pkgmgr branch tree --format json --output %h/.local/state/pkgmgr/tree/branch-tree.json", starts[0])
        self.assertEqual(starts[1], "/usr/bin/env python3 %h/.local/share/kvb-orchestrator/client/local_plan.py --tree %h/.local/state/pkgmgr/tree/branch-tree.json --pkgmgr %h/.local/share/kvb-orchestrator/pkgmgr/bin/pkgmgr --budget 240")
        self.assertIn("TimeoutStartSec=600", TREE_UNIT.read_text(encoding="utf-8").splitlines())

    @unittest.skipUnless(INSTALLED_PKGMGR, "no pkgmgr installed")
    def test_on_files_the_installed_pkgmgr_wrote_the_hub_offers_exactly_the_branches_whose_local_tip_it_deletes(self):
        root = Path(os.path.realpath(self.outside)) / "pkgmgr"
        home = root / "home"
        root.mkdir()
        repo, _ = capture_local_plan(root, Path(INSTALLED_PKGMGR))
        config = home / ".config" / "pkgmgr" / "fixture.yml"
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps({"directories": {"repositories": str(root)}, "repositories": [{"provider": "github.com", "account": "operator-example-01", "repository": "demo", "directory": str(repo)}]}), encoding="utf-8")
        env = {
            "PATH": os.environ["PATH"], "HOME": str(home), "LANG": "C.UTF-8", **GIT_ENV, "DBUS_SESSION_BUS_ADDRESS": f"unix:path={root / 'no-bus'}",
            "XDG_CACHE_HOME": str(home / ".cache"), "XDG_STATE_HOME": str(home / ".local" / "state"), "PKGMGR_TREE_FILE": str(self.tree_file),
        }
        built = subprocess.run([INSTALLED_PKGMGR, "branch", "tree", "--format", "json", "--output", str(self.tree_file)], cwd=root, env=env, capture_output=True, text=True, timeout=300, check=False)
        self.assertEqual(built.returncode, 0, built.stderr[-2000:])
        planned = self.plan(Path(INSTALLED_PKGMGR), env)
        self.assertEqual(planned.returncode, 0, planned.stderr[-2000:])
        status, _, body = self.get("/api/tree")
        self.assertEqual(status, 200, body)
        branches = {entry["name"]: entry for entry in json.loads(body)["repos"][0]["branches"]}
        shown = {name: (entry["merged_by"], entry["cleanup"] is not None, entry["kept"]) for name, entry in branches.items() if name != "main"}
        self.assertEqual(shown, {"side": ("ancestor", True, ""), "topic": ("patch", True, ""), "squashed": ("patch", False, f"pkgmgr branch cleanup --local keeps it: {KEPT_PATCH}; use branch gc (kvb-git-gc, pkgmgr gc)")})


if __name__ == "__main__":
    unittest.main()
