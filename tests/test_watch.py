"""Exercise the democracy resource watch: stages, projection, block, admit, alerts, caches."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WATCH = REPO_ROOT / "skills" / "democracy" / "scripts" / "watch.py"
LIMITS = {"warn": 40, "stop": 15, "critical": 12}


def _load():
    spec = importlib.util.spec_from_file_location("watch", WATCH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestStage(unittest.TestCase):
    def setUp(self):
        self.watch = _load()
        self.cfg = {"thresholds_gb": LIMITS, "projection_minutes": 30}

    def test_thresholds(self):
        now = time.time()
        for free, stage in ((50, "ok"), (30, "warn"), (14, "stop"), (5, "critical")):
            self.assertEqual(self.watch.stage_for(free, [], self.cfg, now), stage)

    def test_cpu_and_ram_percentages(self):
        self.assertEqual(self.watch.cpu_busy_percent((100, 40), (200, 60)), 80.0)
        meminfo = "MemTotal:       1000 kB\nMemFree:  100 kB\nMemAvailable:    250 kB\n"
        self.assertEqual(self.watch.mem_used_percent(meminfo), 75.0)

    def test_fast_fall_escalates_one_stage(self):
        now = time.time()
        self.assertEqual(self.watch.stage_for(32, [[now - 600, 48]], self.cfg, now), "stop")
        self.assertEqual(self.watch.stage_for(32, [[now - 600, 32.1]], self.cfg, now), "warn")


class TestWatchCommands(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / "council"
        self.config = self.base / "config.json"
        self.cache = self.base / "cache"
        self.cache.mkdir()
        self.cfg = {
            "disk": str(self.base),
            "thresholds_gb": LIMITS,
            "projection_minutes": 30,
            "interval_seconds": 0,
            "cache_interval_seconds": 86400,
            "heavy_commands": ["^make compose-deploy", "^make swarm-"],
            "never_block": ["^make swarm-down"],
            "cleanup": [],
            "worktree_cleanup": [],
            "worktrees_command": "true",
            "worktree_marker": "Makefile",
            "busy_processes": ["sleep"],
            "cache_dirs": [str(self.cache)],
            "cache_budget_percent": 3,
            "slot_need_gb": {"swarm": 30, "test": 0.001},
            "notify": ["true"],
            "load_limits": {"cpu_percent": 101, "mem_percent": 101, "sample_seconds": 0.1, "kinds": ["test"]},
        }
        self._write_config()

    def _write_config(self):
        self.config.write_text(json.dumps(self.cfg), encoding="utf-8")

    def _run(self, *args: str, stdin: str = "") -> subprocess.CompletedProcess:
        env = {
            "PATH": str(self.base),
            "HOME": str(self.base),
            "AGENTS_COUNCIL_ROOT": str(self.root),
            "AGENTS_COUNCIL_CONFIG": str(self.config),
        }
        return subprocess.run(
            [sys.executable, str(WATCH), *args],
            capture_output=True, text=True, env=env, input=stdin, check=False,
        )

    def _stage(self, stage: str) -> None:
        self.root.mkdir(exist_ok=True)
        (self.root / "watch.json").write_text(json.dumps({"stage": stage}), encoding="utf-8")

    def _bash(self, command: str) -> str:
        return json.dumps({"tool_input": {"command": command}})

    def test_block_only_heavy_jobs_at_stop_and_never_teardown(self):
        self._stage("stop")
        self.assertEqual(self._run("block", stdin=self._bash("make compose-deploy apps=x")).returncode, 2)
        self.assertEqual(self._run("block", stdin=self._bash("make swarm-down")).returncode, 0)
        self.assertEqual(self._run("block", stdin=self._bash("ls")).returncode, 0)
        self._stage("warn")
        self.assertEqual(self._run("block", stdin=self._bash("make compose-deploy")).returncode, 0)

    def test_block_ignores_heavy_words_inside_quotes_and_heredocs(self):
        self.cfg["heavy_commands"] = [r"\bmake\s+(-C\s+\S+\s+)?(compose-deploy|test|swarm-\S+)(\s|$)"]
        self._write_config()
        self._stage("stop")
        message = "$(cat <<'EOF'\nfix: run \"make test\" and make swarm-zombie\nEOF\n)"
        for command in (
            'git commit --no-verify -m "fix: passes the vars to make swarm-zombie app=x"',
            "grep -n 'make test' Makefile",
            f'git commit --no-verify -m "{message}"',
        ):
            self.assertEqual(self._run("block", stdin=self._bash(command)).returncode, 0, command)
        for command in (
            "make -C x swarm-zombie app=y",
            "env FOO=1 make swarm-zombie",
            'make compose-deploy apps="web-app-x"',
        ):
            self.assertEqual(self._run("block", stdin=self._bash(command)).returncode, 2, command)

    def test_admit_keeps_the_stop_floor(self):
        self.cfg["thresholds_gb"] = {"warn": 0, "stop": 0, "critical": 0}
        self._write_config()
        self.assertEqual(self._run("admit", "--need-gb", "0.001").returncode, 0)
        self.assertEqual(self._run("admit", "--need-gb", "1e9").returncode, 3)

    def test_admit_for_a_load_kind_also_needs_cpu_and_ram_below_the_limits(self):
        self.cfg["thresholds_gb"] = {"warn": 0, "stop": 0, "critical": 0}
        self._write_config()
        self.assertEqual(self._run("admit", "--kind", "test").returncode, 0)
        self.cfg["load_limits"]["cpu_percent"] = 0
        self._write_config()
        denied = self._run("admit", "--kind", "test")
        self.assertEqual(denied.returncode, 3)
        self.assertIn("cpu", denied.stdout)
        self.assertEqual(self._run("admit", "--need-gb", "0.001").returncode, 0)

    def test_warn_alert_reaches_each_session_once(self):
        self.cfg["thresholds_gb"] = {"warn": 1e9, "stop": -1, "critical": -2}
        self._write_config()

        def hook(session: str) -> str:
            payload = {"session_id": session, "hook_event_name": "UserPromptSubmit"}
            return self._run("watch", stdin=json.dumps(payload)).stdout

        self.assertIn("RESOURCE WARN", hook("s1"))
        self.assertEqual(hook("s1"), "")
        self.assertIn("RESOURCE WARN", hook("s2"))

    def test_cache_trim_evicts_least_recently_used_first(self):
        old, new = self.cache / "old", self.cache / "new"
        old.write_bytes(b"x" * 4096)
        new.write_bytes(b"y" * 4096)
        os.utime(old, (1_000_000, 1_000_000))
        os.utime(new, (2_000_000, 2_000_000))
        st = os.statvfs(self.base)
        self.cfg["cache_budget_percent"] = (4096 + 100) / (st.f_blocks * st.f_frsize) * 100
        self._write_config()
        self.assertEqual(self._run("cleanup", "--caches").returncode, 0)
        self.assertFalse(old.exists())
        self.assertTrue(new.exists())

    def test_full_cleanup_reaches_only_marked_running_worktrees(self):
        marked, foreign = self.base / "marked", self.base / "foreign"
        for tree in (marked, foreign):
            tree.mkdir()
        (marked / "Makefile").write_text("", encoding="utf-8")
        self.cfg["worktrees_command"] = f"echo {marked}; echo {foreign}; echo {marked}"
        self.cfg["worktree_cleanup"] = ["echo x >> {worktree}/cleaned"]
        self._write_config()
        self.assertEqual(self._run("cleanup", "--full").returncode, 0)
        self.assertEqual((marked / "cleaned").read_text(encoding="utf-8"), "x\n")
        self.assertFalse((foreign / "cleaned").exists())

    def test_full_cleanup_skips_a_worktree_where_a_busy_process_runs(self):
        idle, gated = self.base / "idle", self.base / "gated"
        for tree in (idle, gated):
            (tree / "sub").mkdir(parents=True)
            (tree / "Makefile").write_text("", encoding="utf-8")
        gate = subprocess.Popen(["sleep", "60"], cwd=gated / "sub")
        self.addCleanup(gate.wait)
        self.addCleanup(gate.kill)
        self.cfg["worktrees_command"] = f"echo {idle}; echo {gated}"
        self.cfg["worktree_cleanup"] = ["echo x >> {worktree}/cleaned"]
        self._write_config()
        self.assertEqual(self._run("cleanup", "--full").returncode, 0)
        self.assertTrue((idle / "cleaned").exists())
        self.assertFalse((gated / "cleaned").exists())

    def test_without_config_every_command_is_a_no_op(self):
        self.config.unlink()
        result = self._run("status")
        self.assertEqual((result.returncode, result.stdout), (0, ""))


if __name__ == "__main__":
    unittest.main()
