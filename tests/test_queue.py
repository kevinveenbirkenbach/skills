"""Exercise the kvb-org-queue grant order, its history learning and its hold, list, history, cancel and block commands."""

from __future__ import annotations

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
import unittest
from collections.abc import Callable
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
QUEUE = REPO_ROOT / "skills" / "kvb-org-queue" / "scripts" / "queue.py"
HISTORY = REPO_ROOT / "skills" / "kvb-org-queue" / "scripts" / "history.py"
GATES = REPO_ROOT / "skills" / "kvb-check-gate" / "scripts" / "gates.py"
NOW = 1_800_000_000.0
HOUR = 3600
OPEN_MEMORY = {
    "available": -1, "swap_free": -1, "psi_some": 1000, "psi_full": 1000, "swap_out_mb_min": 1e9, "container_swap_gb": 1e9,
}
BASE = {
    "free_gb": 100.0,
    "floor": 10.0,
    "stage": "ok",
    "memory": "ok",
    "silenced": False,
    "slot_limits": {"test": 5, "deploy": 1},
    "budget": {"ram": 75, "cpu": 100},
    "ranks": {"work/a": 0, "work/b": 1, "work/c": 2},
    "agents": {},
    "loaded": {},
    "exclusive": set(),
    "light": set(),
    "drain": None,
    "now": NOW,
}
CHILD = (
    "import json, os, sys, time\n"
    "deadline = time.monotonic() + 20\n"
    "while True:\n"
    "    with open(sys.argv[1], encoding='utf-8') as handle:\n"
    "        entries = json.load(handle)['entries']\n"
    "    if (entries and entries[0]['child'] == os.getpid()) or time.monotonic() > deadline:\n"
    "        break\n"
    "    time.sleep(0.05)\n"
    "with open(sys.argv[2], 'w', encoding='utf-8') as out:\n"
    "    json.dump(entries, out)\n"
    "sys.exit(7)\n"
)


def _load(path: Path):
    spec = importlib.util.spec_from_file_location(f"{path.stem}_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def history_row(seq: int, **fields: object) -> dict:
    return {
        "id": f"r{seq}", "kind": "test", "signature": "make test", "workdir": "/w", "start": NOW - 600, "end": NOW,
        "minutes": 10.0, "exit": 0, "free_before_gb": 50.0, "min_free_gb": 49.0, "disk_gb": 1.0, "mem_before": 20.0,
        "mem_max": 30.0, "cpu_before": 10.0, "cpu_max": 40.0, "concurrent": 0, **fields,
    }


def job(seq: int, **fields: object) -> dict:
    return {
        "id": f"j{seq}", "seq": seq, "kind": "test", "task": "work/a", "need_gb": 1, "hotfix": None,
        "workdir": f"/w{seq}", "name": "s1", "status": "waiting", "enqueued": NOW, **fields,
    }


def idle() -> tuple[bool, list]:
    return False, []


def stored(seq: int, status: str, pid: int, pid_start: str | None, child: int | None,
           child_start: str | None) -> dict:
    return {
        "id": f"test-{seq}", "seq": seq, "kind": "test", "task": "work/a", "need_gb": 0, "hotfix": None,
        "workdir": f"/w{seq}", "session": "s1", "name": "s1", "pid": pid, "pid_start": pid_start,
        "child": child, "child_start": child_start, "status": status, "enqueued": time.time(),
        "granted": time.time() if status == "active" else None, "cmd": "true",
    }


class Passes:
    @classmethod
    def setUpClass(cls):
        cls.queue = _load(QUEUE)

    def run_pass(self, entries: list[dict], **overrides: object) -> tuple[dict, str | None, list[dict]]:
        footprints = {e["id"]: {"ram": 0, "cpu": 0} for e in entries} | overrides.pop("footprints", {})
        return self.queue.evaluate(entries, **{**BASE, "footprints": footprints, **overrides})

    def decide(self, entries: list[dict], **overrides: object) -> dict:
        return self.run_pass(entries, **overrides)[0]


class TestEvaluate(Passes, unittest.TestCase):
    def test_the_budget_refuses_a_job_whose_share_would_pass_it_and_a_smaller_one_backfills(self):
        running = job(1, kind="test", status="active")
        candidate = job(2, kind="gui-dind", workdir="/x")
        small = job(3, task="work/b", workdir="/y")
        shares = {"j1": {"ram": 60, "cpu": 40}, "j2": {"ram": 30, "cpu": 20}, "j3": {"ram": 10, "cpu": 5}}
        verdicts = self.decide([running, candidate, small], slot_limits={"test": 5, "gui-dind": 1}, footprints=shares)
        self.assertEqual(verdicts["j2"], "RAM 60 % in use or reserved + 30 % > budget 75 %")
        self.assertIsNone(verdicts["j3"])
        fat = {**shares, "j3": {"ram": 16, "cpu": 5}}
        verdicts = self.decide([running, candidate, small], slot_limits={"test": 5, "gui-dind": 1}, footprints=fat)
        self.assertEqual(verdicts["j3"], "RAM 60 % in use or reserved + 16 % > budget 75 %")
        unbounded = {"ram": 1000, "cpu": 1000}
        self.assertEqual(
            self.decide([running, candidate, small], slot_limits={"test": 5, "gui-dind": 1}, footprints=shares, budget=unbounded),
            {"j2": None, "j3": None},
        )

    def test_a_job_alone_always_fits_and_cpu_counts_like_ram(self):
        alone = self.decide([job(1)], footprints={"j1": {"ram": 90, "cpu": 150}})
        self.assertEqual(alone, {"j1": None})
        busy = self.decide([job(1, status="active"), job(2)], footprints={"j1": {"ram": 1, "cpu": 70}, "j2": {"ram": 1, "cpu": 40}})
        self.assertEqual(busy, {"j2": "CPU 70 % in use or reserved + 40 % > budget 100 %"})

    def test_a_share_beyond_the_budget_runs_only_alone_even_beside_a_job_of_no_share(self):
        whole = {"ram": 80, "cpu": 1}
        beside = self.decide([job(1, status="active"), job(2)], footprints={"j1": {"ram": 0, "cpu": 0}, "j2": whole})
        self.assertEqual(beside, {"j2": "RAM 0 % in use or reserved + 80 % > budget 75 %"})
        self.assertEqual(self.decide([job(2)], footprints={"j2": whole}), {"j2": None})

    def test_load_counts_the_ram_in_use_plus_what_is_still_to_come(self):
        limits = {"cpu_percent": 90, "mem_percent": 90}
        reason = self.queue.load_reason
        self.assertIsNone(reason(limits, 50, 60, 29))
        self.assertEqual(reason(limits, 50, 60, 30), "RAM 60 % used + 30 % still to come reach the limit 90 %")
        self.assertIsNone(reason(limits, 50, 89, 0))
        self.assertEqual(reason(limits, 90, 10, 0), "CPU 90 % busy reaches the limit 90 %")

    def test_pending_ram_adds_what_active_jobs_have_not_taken_yet_and_seeds_an_unlearned_kind(self):
        history = _load(HISTORY)
        rows = [history_row(n, kind=kind, signature=f"w: {kind}", mem_before=20, mem_max=20 + share)
                for n, (kind, share) in enumerate([("a", 30)] * 5 + [("b", 25)] * 5 + [("c", 10)] * 5)]
        signatures, kinds = history.learn(rows, NOW, {"load_limits": {"mem_percent": 90, "cpu_percent": 90}})
        self.assertEqual(history.seed_ram(kinds), 30)
        self.assertEqual(history.seed_ram({}), 0)
        cmd = {"workdir": "/w"}
        fresh = {**job(2, kind="b"), **cmd, "cmd": "b"}
        young = {**job(1, kind="a", status="active", granted=NOW - 60), **cmd, "cmd": "a"}
        overshooting = {**job(5, kind="c", status="active", granted=NOW - 120), **cmd, "cmd": "c"}
        old = {**job(4, kind="c", status="active", granted=NOW - self.queue.RAMP_SECONDS), **cmd, "cmd": "c"}
        pending = self.queue.pending_ram
        self.assertEqual(pending([young, overshooting, old, fresh], "j2", NOW, signatures, kinds, 50, 0), 30 + 10 + 25)
        undated = {k: v for k, v in old.items() if k != "granted"}
        self.assertEqual(pending([undated, fresh], "j2", NOW, signatures, kinds, 50, 0), 10 + 25)
        unknown = {**job(3, kind="new"), **cmd, "cmd": "new"}
        self.assertEqual(pending([unknown], "j3", NOW, signatures, kinds, 50, 0), 30)
        self.assertEqual(pending([fresh], "j2", NOW, signatures, kinds, 50, 12), 25 + 12)

    def test_a_young_job_counts_only_what_it_has_not_added_since_its_grant(self):
        history = _load(HISTORY)
        rows = [history_row(n, kind="b", signature="w: b", mem_before=20, mem_max=45) for n in range(5)]
        signatures, kinds = history.learn(rows, NOW, {"load_limits": {"mem_percent": 90, "cpu_percent": 90}})
        fresh = {**job(2, kind="b"), "workdir": "/w", "cmd": "b"}

        def gate(seq: int, ram: float, granted_mem: float) -> dict:
            return {**job(seq, kind="g", status="active", granted=NOW - 60), "workdir": "/w", "cmd": "g",
                    "footprint": {"ram": ram, "cpu": 1}, "granted_mem": granted_mem}

        pending = self.queue.pending_ram
        self.assertEqual(pending([gate(1, 40, 10), fresh], "j2", NOW, signatures, kinds, 10, 0), 25 + 40)
        self.assertEqual(pending([gate(1, 40, 10), fresh], "j2", NOW, signatures, kinds, 45, 0), 25 + 5)
        self.assertEqual(pending([gate(1, 40, 10), fresh], "j2", NOW, signatures, kinds, 60, 0), 25)
        self.assertEqual(pending([gate(1, 40, 10), gate(3, 20, 30), fresh], "j2", NOW, signatures, kinds, 45, 0), 25 + 25)
        undated = {k: v for k, v in gate(1, 40, 10).items() if k != "granted_mem"}
        self.assertEqual(pending([undated, fresh], "j2", NOW, signatures, kinds, 60, 0), 25 + 40)
        ramp = self.queue.ramping_ram
        for mem in (70, 40, 20):
            with self.subTest(mem=mem):
                self.assertEqual(ramp([gate(1, 40, 70)], NOW, signatures, kinds, mem), 40)
        self.assertEqual(ramp([gate(1, 40, 70), {**undated, "id": "j3"}], NOW, signatures, kinds, 20), 80)
        self.assertEqual(self.queue.admitted_ram({"admits": [{"ram": 7, "expires": NOW + 1}, {"ram": 9, "expires": NOW}]}, NOW), 7)
        self.assertEqual(self.queue.admitted_ram({"entries": []}, NOW), 0)

    def test_a_signature_names_the_repository_every_worktree_shares(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            main = base / "skills"
            main.mkdir()
            identity = {**os.environ, "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "T",
                        "GIT_COMMITTER_EMAIL": "t@x", "GIT_CONFIG_NOSYSTEM": "1"}
            for args in (["init", "-q"], ["commit", "-q", "--allow-empty", "-m", "x"], ["worktree", "add", "-q", str(base / "wt")]):
                subprocess.run(["git", *args], cwd=main, env=identity, check=True, capture_output=True)
            def qualified(workdir: Path, argv: list[str]) -> str:
                return self.queue.aliases(str(workdir), argv, None)[0]

            self.assertEqual(qualified(main, ["make", "test"]), "skills: make test")
            self.assertEqual(qualified(base / "wt", ["make", "test"]), "skills: make test")
            plain = base / "plain"
            plain.mkdir()
            self.assertEqual(qualified(plain, ["true"]), "plain: true")
            self.assertEqual(qualified(base / "gone", ["true"]), "gone: true")
            for argv, expected in {
                ("env", "TMPDIR=/t", "-i", "make", "test"): "make test",
                ("nice", "-n", "10", "make", "compose-deploy"): "make compose-deploy",
                ("timeout", "3600", "make", "lint"): "make lint",
                ("python3", "/s/gate.py", "hold", "--repo", ".", "--", "make", "verify-test"): "make verify-test",
                ("python3", "/s/operator.py", "granted", "operator/x", "--dir", "/a", "--check", "manual", "--",
                 "zsh", "-ic", "make -C /a/core compose-deploy"): "make compose-deploy",
                ("bash", "-c", "cd core && make test 2>&1 | tee /tmp/log"): "make test",
                ("python3", "/s/x.py", "--"): "x.py",
                ("bash", "-c", "set -e; make verify-test"): "make verify-test",
                ("bash", "-c", "source .venv/bin/activate && make test"): "make test",
            }.items():
                with self.subTest(argv=argv):
                    self.assertEqual(qualified(plain, list(argv)), f"plain: {expected}")
            module = ["python3", "-m", "pytest", "--", "tests/"]
            self.assertEqual(self.queue.command_words(module), module)
            single = ["env", "PYTHONDONTWRITEBYTECODE=1", "/v/bin/python", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                      "tests/unit/test_x.py"]
            self.assertEqual(qualified(plain, single), "plain: pytest files=1")
            self.assertEqual(self.queue.aliases(str(plain), single, None),
                             ("plain: pytest files=1", "plain: pytest no:cacheprovider"))
            self.assertEqual(self.queue.aliases(str(plain), ["make", "test"], None), ("plain: make test",))

    def test_a_test_run_is_named_by_the_files_or_paths_it_names_and_its_xdist_workers(self):
        nine = [f"tests/unit/test_{n}.py" for n in range(9)]
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("tests/test_x.py", "tree/a/test_main.py", "tree/b/test_main.py", "a/x/test_main.py",
                         "a/y/test_main.py"):
                (Path(tmp) / name).parent.mkdir(parents=True, exist_ok=True)
                (Path(tmp) / name).write_text("", encoding="utf-8")

            def runner(argv: list[str], cwd: str | None) -> str | None:
                return self.queue.runner_signature(self.queue.command_words(argv), argv, cwd)

            discover = ["python3", "-m", "unittest", "discover"]
            self.assertEqual(runner([*discover, "-s", "tests", "-p", "test_x.py"], tmp), "unittest files=1")
            self.assertEqual(runner(["env", "-C", "tree", "env", "--chdir=a", *discover, "-p", "test_main.py"], tmp),
                             "unittest files=1")
            self.assertEqual(runner([*discover, "-s", "tree", "-p", "test_main.py"], tmp), "unittest paths=1")
            self.assertEqual(runner([*discover, "-s", "tree", "-p", "test_main.py"], None), "unittest files=1")
            self.assertEqual(runner([*discover, "-s", "nowhere", "-p", "test_main.py"], tmp), "unittest files=1")
            self.assertEqual(runner([*discover, "-s", "nowhere", "-p", "test_*.py"], tmp), "unittest paths=1")
            there = ("env", "-C", tmp, "python3", "-m", "unittest", "discover")
            for argv, expected in {
                ("python3", "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/unit/test_x.py"): "pytest files=1",
                ("pytest", "tests/unit/test_x.py::TestA::test_b", "-k", "a or b"): "pytest files=1",
                ("python3", "-m", "pytest", "-q", "-p", "no:cacheprovider", *nine): "pytest files=9",
                ("python3", "-m", "pytest", "tests/unit", "tests/integration", "-p", "no:cacheprovider"): "pytest paths=2",
                ("pytest", "tests/unit/test_x.py", "tests/lint"): "pytest paths=2",
                ("python3", "-m", "pytest", "-q"): "pytest paths=0",
                ("pytest", "-n", "auto", "tests/x.py"): "pytest files=1 workers=auto",
                ("pytest", "-n4", "tests/"): "pytest paths=1 workers=4",
                ("pytest", "-n=4", "tests/x.py"): "pytest files=1 workers=4",
                ("pytest", "--numprocesses", "6", "tests/x.py"): "pytest files=1 workers=6",
                ("py.test", "--numprocesses=8"): "pytest paths=0 workers=8",
                ("env", "PYTEST_ADDOPTS=-q -n 4", "pytest", "tests/x.py"): "pytest files=1 workers=4",
                ("env", "PYTEST_ADDOPTS=-n 4", "pytest", "-n", "2", "tests/x.py"): "pytest files=1 workers=2",
                (*there, "-s", "tests", "-p", "test_x.py"): "unittest files=1",
                (*there, "--start-directory", "tests", "--pattern", "test_x.py"): "unittest files=1",
                (*there, "-s", "tree", "-p", "test_main.py"): "unittest paths=1",
                (*there, "-s", "tests", "-p", "test_gone.py"): "unittest paths=1",
                (*there, "-s", "tests", "-p", "test_*.py"): "unittest files=1",
                (*there, "-s", "tree", "-p", "test_*.py"): "unittest paths=1",
                (*there, "-s", "tests"): "unittest paths=0",
                ("python3", "-m", "unittest", "-v", "tests.test_queue", "tests.test_watch"): "unittest files=2",
                ("python3", "-m", "unittest"): "unittest paths=0",
            }.items():
                with self.subTest(argv=argv):
                    self.assertEqual(runner(list(argv), "/"), expected)
        for argv in (["make", "test"], ["python3", "/s/gate.py", "run"], ["python3", "-c", "print(1)"], ["true"]):
            with self.subTest(argv=argv):
                self.assertIsNone(self.queue.runner_signature(argv, argv, "/"))

    def test_an_active_entry_keeps_the_footprint_it_was_granted_on_while_history_moves(self):
        history = _load(HISTORY)
        rows = [history_row(n, signature="w: make test", mem_max=70, cpu_max=90) for n in range(5)]
        signatures, kinds = history.learn(rows, NOW, {"load_limits": {"mem_percent": 90, "cpu_percent": 90}})
        granted = {"ram": 12.0, "cpu": 30.0}
        running = {**job(1, status="active", granted=NOW - 60), "workdir": "/w", "cmd": "make test", "footprint": granted}
        self.assertEqual(self.queue.footprint(running, signatures, kinds), granted)
        unlearned = {**running, "footprint": None}
        self.assertIsNone(self.queue.footprint(unlearned, signatures, kinds))
        waiting = {**running, "status": "waiting"}
        self.assertEqual(self.queue.footprint(waiting, signatures, kinds), {"ram": 50, "cpu": 80})
        older = {k: v for k, v in running.items() if k != "footprint"}
        self.assertEqual(self.queue.footprint(older, signatures, kinds), {"ram": 50, "cpu": 80})
        self.assertEqual(self.queue.pending_ram([running], "j1", NOW, signatures, kinds, 50, 0), 12 + 12)

    def test_an_active_entry_an_older_queue_granted_never_books_less_than_that_queue_did(self):
        history = _load(HISTORY)
        light = [history_row(n, kind="test-nostack", signature="w: gate.py hold", mem_max=23, cpu_max=22) for n in range(5)]
        heavy = [history_row(n + 5, kind="quality-high", signature="w: gate.py hold", mem_max=60, cpu_max=80) for n in range(5)]
        signatures, kinds = history.learn([*light, *heavy], NOW, {"load_limits": {"mem_percent": 90, "cpu_percent": 90},
                                                                  "light_kinds": ["test-nostack"]})
        landed = {**job(1, kind="test-nostack", status="active", granted=NOW - 60), "workdir": "/w",
                  "cmd": "python3 /x/gate.py hold --repo ."}
        self.assertEqual(self.queue.footprint(landed, signatures, kinds), {"ram": 40, "cpu": 41})
        self.assertEqual(self.queue.footprint({**landed, "status": "waiting"}, signatures, kinds), {"ram": 3, "cpu": 12})
        self.assertEqual(self.queue.footprint({**landed, "footprint": {"ram": 3, "cpu": 12}}, signatures, kinds),
                         {"ram": 3, "cpu": 12})
        self.assertIsNone(self.queue.footprint({**landed, "kind": "gui-dind"}, signatures, kinds))

    def test_memory_stage_stop_blocks_every_job_and_warn_none(self):
        entries = [job(1, need_gb=0), job(2, task="work/b")]
        self.assertEqual(set(self.decide(entries, memory="stop").values()), {"memory stage stop"})
        self.assertEqual(self.decide(entries, memory="warn"), {"j1": None, "j2": None})

    def test_hotfix_goes_first_then_rank_then_arrival_and_unknown_tasks_last(self):
        entries = [
            job(1, task="work/c"), job(2, task="work/gone"), job(3), job(4), job(5, task="work/c", hotfix="fix-1"),
        ]
        self.assertEqual(list(self.decide(entries)), ["j5", "j3", "j4", "j1", "j2"])

    def test_each_whole_hour_waited_moves_one_rank_up(self):
        fresh = job(1)
        aged = job(2, task="work/c", enqueued=NOW - 3 * HOUR)
        almost = job(3, task="work/b", enqueued=NOW - HOUR + 1)
        self.assertEqual(list(self.decide([fresh, aged, almost])), ["j2", "j1", "j3"])
        tied = job(4, task="work/c", enqueued=NOW - 2 * HOUR)
        self.assertEqual(list(self.decide([tied, fresh])), ["j1", "j4"])

    def test_the_agent_order_breaks_ties_of_equal_rank_only(self):
        entries = [job(1, name="Beta"), job(2, name="Alpha"), job(3, task="work/b", name="Alpha"), job(4, name="Stranger")]
        self.assertEqual(list(self.decide(entries)), ["j1", "j2", "j4", "j3"])
        self.assertEqual(list(self.decide(entries, agents={"Alpha": 0, "Beta": 1})), ["j2", "j1", "j4", "j3"])
        tied = [job(5, task="work/b", name="Beta", enqueued=NOW - HOUR), job(6, name="Alpha")]
        self.assertEqual(list(self.decide(tied)), ["j5", "j6"])
        self.assertEqual(list(self.decide(tied, agents={"Alpha": 0, "Beta": 1})), ["j6", "j5"])

    def test_an_exclusive_kind_runs_only_beside_light_kinds_in_both_directions(self):
        gates = {"exclusive": {"quality-high", "test"}, "light": {"test-nostack"}}
        slots = {"slot_limits": {"quality-high": 1, "iteration": 2, "test-nostack": 2}}
        gate, deploy, light = job(1, kind="quality-high", status="active"), job(2, kind="iteration", workdir="/d"), job(3, kind="test-nostack", workdir="/l")
        self.assertEqual(self.decide([gate, deploy, light], **slots), {"j2": None, "j3": None})
        self.assertEqual(
            self.decide([gate, deploy, light], **slots, **gates),
            {"j2": "quality-high runs only beside test-nostack", "j3": None},
        )
        running, waiting = job(2, kind="iteration", status="active", workdir="/d"), job(1, kind="quality-high")
        self.assertEqual(
            self.decide([running, waiting], **slots, **gates),
            {"j1": "quality-high runs only beside test-nostack, but iteration runs"},
        )

    def test_r5_an_exclusive_entry_kept_out_by_a_running_job_holds_back_lower_non_light_entries_at_once(self):
        gates = {
            "exclusive": {"quality-high"}, "light": {"test-nostack"},
            "slot_limits": {"quality-high": 1, "iteration": 2, "test-nostack": 2},
        }
        running = job(1, kind="iteration", status="active")
        gate, deploy, light = job(2, kind="quality-high"), job(3, kind="iteration", task="work/b"), job(4, kind="test-nostack", task="work/c")
        held = {"j2": "quality-high runs only beside test-nostack, but iteration runs", "j3": "drained for j2", "j4": None}
        verdicts, drain, _ = self.run_pass([running, gate, deploy, light], **gates)
        self.assertEqual((verdicts, drain), (held, None))
        self.assertEqual(self.decide([running, gate, deploy, light], drain="j2", **gates), held)
        greedy = {"j1": {"ram": 30, "cpu": 30}, "j2": {"ram": 40, "cpu": 40}, "j3": {"ram": 5, "cpu": 5}, "j4": {"ram": 30, "cpu": 5}}
        self.assertEqual(self.decide([running, gate, deploy, light], footprints=greedy, **gates)["j4"], None)
        self.assertEqual(self.decide([running, gate, deploy, light], footprints=greedy | {"j4": {"ram": 40, "cpu": 70}}, **gates)["j4"],
                         "drained for j2")
        self.assertEqual(
            self.decide([gate, deploy, light], **gates),
            {"j2": None, "j3": "quality-high runs only beside test-nostack", "j4": None},
        )

    def test_the_slot_limit_counts_active_jobs_per_kind(self):
        verdicts = self.decide([job(1, kind="deploy", status="active"), job(2, kind="deploy"), job(3)])
        self.assertEqual(verdicts, {"j2": "all 1 deploy slots taken", "j3": None})

    def test_a_higher_waiter_is_granted_virtually_before_a_lower_one(self):
        verdicts = self.decide([job(1, task="work/b", kind="deploy"), job(2, kind="deploy")])
        self.assertEqual(verdicts, {"j2": None, "j1": "all 1 deploy slots taken"})

    def test_a_waiter_that_stopped_polling_reserves_nothing_and_the_next_one_is_granted(self):
        behind = job(3, task="work/b", kind="deploy", polled=NOW)
        verdicts = self.decide([job(2, kind="deploy", polled=NOW - 61), behind])
        self.assertEqual(verdicts, {"j3": None, "j2": "no poll for 61 s; reserves nothing until it polls again"})
        for polling in (job(2, kind="deploy", polled=NOW - 59), job(2, kind="deploy")):
            self.assertEqual(self.decide([polling, behind]), {"j2": None, "j3": "all 1 deploy slots taken"})

    def test_a_silent_waiter_rejoins_at_the_back_once_it_polls_again(self):
        data = {"seq": 7, "entries": []}
        silent = job(2, polled=NOW - 61, enqueued=NOW - 2 * HOUR)
        self.queue.rejoin(data, silent, NOW)
        self.assertEqual((silent["seq"], silent["enqueued"], silent["polled"], data["seq"]), (8, NOW, NOW, 8))
        polling = job(3, polled=NOW - 30, enqueued=NOW - HOUR)
        self.queue.rejoin(data, polling, NOW)
        self.assertEqual((polling["seq"], polling["enqueued"], polling["polled"], data["seq"]), (3, NOW - HOUR, NOW, 8))

    def test_a_smaller_job_backfills_past_a_big_head_the_disk_floor_blocks(self):
        big, small = job(1, need_gb=50), job(2, task="work/b", need_gb=5)
        verdicts, drain, _ = self.run_pass([big, small], free_gb=40.0)
        self.assertEqual(verdicts, {"j1": "50 GB would cut into the 10 GB floor", "j2": None})
        self.assertIsNone(drain)
        self.assertIsNone(self.decide([small], free_gb=40.0)["j2"])
        running = job(3, need_gb=25, status="active")
        self.assertIsNone(self.decide([running, job(4, need_gb=5)], free_gb=40.0)["j4"])
        self.assertIsNotNone(self.decide([running, job(4, need_gb=6)], free_gb=40.0)["j4"])

    def test_warn_admits_only_jobs_without_disk_and_stop_admits_none(self):
        entries = [job(1, need_gb=0), job(2, task="work/b")]
        verdicts = self.decide(entries, stage="warn")
        self.assertEqual(verdicts, {"j1": None, "j2": "disk stage warn admits only jobs that need no disk"})
        for stage in ("stop", "critical"):
            with self.subTest(stage=stage):
                self.assertEqual(set(self.decide(entries, stage=stage).values()), {f"disk stage {stage}"})

    def test_radio_silence_blocks_every_job(self):
        verdicts = self.decide([job(1, need_gb=0), job(2)], silenced=True)
        self.assertEqual(set(verdicts.values()), {"radio silence"})

    def test_a_busy_workdir_blocks_a_second_job_there(self):
        verdicts = self.decide([
            job(1, workdir="/w", status="active"), job(2, workdir="/w"), job(3, workdir="/x"),
            job(4, task="work/b", workdir="/x"),
        ])
        self.assertEqual(verdicts, {"j2": "waits in line behind j1", "j3": None, "j4": "waits in line behind j3"})

    def test_a_hotfix_the_host_load_holds_back_holds_back_every_entry_after_it_and_a_normal_one_does_not(self):
        load = "RAM 55 % used + 42 % still to come reach the limit 90 %"
        hotfix, light = job(1, hotfix="main-red"), job(2, task="work/b")
        self.assertEqual(self.decide([hotfix, light], loaded={"j1": load}), {"j1": load, "j2": "waits behind hotfix j1"})
        self.assertEqual(self.decide([job(1), light], loaded={"j1": load}), {"j1": load, "j2": None})
        self.assertEqual(self.decide([hotfix, light]), {"j1": None, "j2": None})

    def test_r5_a_head_the_host_load_keeps_out_reserves_nothing_and_exclusive_kinds_share_no_line(self):
        load = "RAM 55 % used + 41 % still to come reach the limit 90 %"
        head, twin = job(1, kind="quality-high"), job(2, kind="quality-high", task="work/b")
        gate, light = job(3, task="work/b"), job(4, kind="test-nostack", task="work/c")
        shares = {"j1": {"ram": 41, "cpu": 62}, "j2": {"ram": 41, "cpu": 62}, "j3": {"ram": 20, "cpu": 40}, "j4": {"ram": 6, "cpu": 40}}
        rules = {"slot_limits": {"quality-high": 1, "test": 5, "test-nostack": 6}, "exclusive": {"quality-high", "test"}, "light": {"test-nostack"}}
        loaded = {"j1": load, "j2": load}
        line = {"j2": load, "j3": None, "j4": None}
        self.assertEqual(self.decide([head, twin, gate, light], loaded=loaded, footprints=shares, **rules), {"j1": load, **line})
        running = job(5, kind="test-nostack", task="work/c", status="active")
        self.assertEqual(
            self.decide([running, head, twin, gate, light], loaded=loaded, footprints=shares | {"j5": {"ram": 6, "cpu": 11}}, **rules),
            {"j1": load, **line},
        )

    def test_a_blocked_entry_reserves_nothing_for_light_and_heavy_kinds_alike(self):
        rules = {"slot_limits": {"test": 5, "test-nostack": 5, "deploy": 1}, "light": {"test-nostack"}}
        with self.subTest("budget"):
            running, head, twin = job(1, status="active"), job(2), job(3, task="work/b")
            light, heavy = job(4, kind="test-nostack", task="work/c", need_gb=0), job(5, task="work/c")
            shares = {
                "j1": {"ram": 30, "cpu": 50}, "j2": {"ram": 50, "cpu": 60}, "j3": {"ram": 50, "cpu": 60},
                "j4": {"ram": 6, "cpu": 11}, "j5": {"ram": 5, "cpu": 5},
            }
            self.assertEqual(self.decide([running, head, twin, light, heavy], footprints=shares, **rules), {
                "j2": "RAM 30 % in use or reserved + 50 % > budget 75 %, CPU 50 % in use or reserved + 60 % > budget 100 %",
                "j3": "RAM 30 % in use or reserved + 50 % > budget 75 %, CPU 50 % in use or reserved + 60 % > budget 100 %",
                "j4": None,
                "j5": None,
            })
        with self.subTest("disk"):
            big, small, late = job(1, need_gb=50), job(2, kind="test-nostack", task="work/b", need_gb=0), job(3, task="work/c", need_gb=5)
            self.assertEqual(self.decide([big, small, late], free_gb=40.0, **rules), {
                "j1": "50 GB would cut into the 10 GB floor", "j2": None, "j3": None,
            })
        with self.subTest("a granted light counts for every later entry"):
            running = job(1, status="active")
            first, second = job(2, kind="test-nostack", need_gb=0), job(3, kind="test-nostack", task="work/b", need_gb=0)
            heavy = job(4, task="work/c")
            shares = {"j1": {"ram": 10, "cpu": 60}, "j2": {"ram": 0, "cpu": 30}, "j3": {"ram": 0, "cpu": 30}, "j4": {"ram": 5, "cpu": 5}}
            self.assertEqual(self.decide([running, first, second, heavy], footprints=shares, **rules), {
                "j2": None, "j3": "CPU 90 % in use or reserved + 30 % > budget 100 %", "j4": None,
            })
        with self.subTest("a head the host load keeps out while a job runs"):
            load = "RAM 55 % used + 41 % still to come reach the limit 90 %"
            running, head = job(1, kind="test-nostack", status="active", need_gb=0), job(2, kind="deploy")
            heavy, light = job(3, task="work/b"), job(4, kind="test-nostack", task="work/c", need_gb=0)
            shares = {"j1": {"ram": 0, "cpu": 10}, "j2": {"ram": 0, "cpu": 60}, "j3": {"ram": 0, "cpu": 40}, "j4": {"ram": 0, "cpu": 40}}
            self.assertEqual(self.decide([running, head, heavy, light], loaded={"j2": load}, footprints=shares, **rules), {
                "j2": load, "j3": None, "j4": None,
            })


class TestBackfill(Passes, unittest.TestCase):
    def test_the_live_case_small_jobs_backfill_past_a_65_gb_head_and_the_head_takes_the_next_capacity(self):
        rules = {"floor": 15.0, "slot_limits": {"gui-dind": 1, "iteration": 8}}
        head = job(1926, kind="gui-dind", need_gb=65, workdir="/store")
        small = [job(n, kind="iteration", task="work/b", need_gb=gb) for n, gb in enumerate((9, 12, 20, 15, 10, 18, 14, 11), 1)]

        def queue(running: set[int], waiting: list[int]) -> list[dict]:
            return [head] + [{**small[n - 1], "status": "active", "granted": NOW - 60} for n in running] + [
                small[n - 1] for n in waiting
            ]

        verdicts, drain, _ = self.run_pass(queue(set(), list(range(1, 9))), free_gb=47.0, **rules)
        self.assertEqual(self.queue.labelled(verdicts, []), {
            "j1926": "65 GB would cut into the 15 GB floor", "j1": "backfilled", "j2": "backfilled",
            "j3": "20 GB would cut into the 15 GB floor", "j4": "15 GB would cut into the 15 GB floor", "j5": "backfilled",
            "j6": "18 GB would cut into the 15 GB floor", "j7": "14 GB would cut into the 15 GB floor",
            "j8": "11 GB would cut into the 15 GB floor",
        })
        self.assertIsNone(drain)
        verdicts, drain, order = self.run_pass(queue({1, 2, 5}, [3, 4, 6, 7, 8]), free_gb=47.0, **rules)
        self.assertNotIn(None, verdicts.values())
        self.assertIsNone(drain, "47 GB free never holds 65 GB above the floor, so draining would only idle the host")
        self.assertEqual(self.queue.stalled({"entries": queue({1, 2, 5}, [])}, order, verdicts, 15.0, 47.0, lambda: (False, []), NOW)[:2], ([], True))
        verdicts, drain, _ = self.run_pass(queue({1, 2, 5}, [3, 4, 6, 7, 8]), free_gb=85.0, **rules)
        self.assertEqual((verdicts["j3"], verdicts["j4"], drain), (None, None, None))
        verdicts, drain, _ = self.run_pass(queue({1, 2, 3, 4, 5}, [6, 7, 8]), free_gb=85.0, **rules)
        self.assertNotIn(None, verdicts.values())
        self.assertEqual(drain, "j1926")
        backfill = self.decide(queue({2, 3, 4, 5}, [6, 7, 8]), free_gb=85.0, **rules)
        drained = self.decide(queue({2, 3, 4, 5}, [6, 7, 8]), free_gb=85.0, drain="j1926", **rules)
        self.assertEqual((backfill["j8"], drained["j8"]), (None, "drained for j1926"))
        self.assertEqual(drained["j6"], "18 GB would cut into the 15 GB floor")
        verdicts, _, order = self.run_pass(queue(set(), [6, 7, 8]), free_gb=85.0, drain="j1926", **rules)
        self.assertEqual((order[0]["id"], verdicts["j1926"]), ("j1926", None))

    def test_a_line_runs_strictly_in_order_by_worktree_and_stack_and_exclusive_kinds_form_none(self):
        load = "CPU 95 % busy reaches the limit 90 %"
        disk, older = job(13, status="active", workdir="/z", need_gb=10), job(1, workdir="/core", need_gb=25)
        younger, other, last = job(2, task="work/b", workdir="/core"), job(3, task="work/b", workdir="/x"), job(4, task="work/c", workdir="/core")
        self.assertEqual(self.decide([disk, older, younger, other, last], free_gb=40.0), {
            "j1": "25 GB would cut into the 10 GB floor", "j2": "waits in line behind j1", "j3": None,
            "j4": "waits in line behind j1",
        })
        self.assertEqual(self.decide([{**older, "need_gb": 50}, younger, other, last], free_gb=40.0), {
            "j1": "50 GB would cut into the 10 GB floor", "j2": None, "j3": None, "j4": "waits in line behind j2",
        })
        stacked = [job(5, claims=["/a", "stack:core"]), job(6, task="work/b", claims=["/b", "stack:core"]), job(7, task="work/b", claims=["/c"])]
        self.assertEqual(self.decide(stacked, loaded={"j5": load}), {"j5": load, "j6": "waits in line behind j5", "j7": None})
        rules = {"exclusive": {"test"}, "slot_limits": {"test": 5, "deploy": 1}}
        machine = [job(8, workdir="/g"), job(9, task="work/b", workdir="/h"), job(10, kind="deploy", task="work/c", workdir="/i")]
        self.assertEqual(self.decide(machine, loaded={"j8": load}, **rules), {"j8": load, "j9": None, "j10": "test runs only beside nothing"})
        running = [job(11, workdir="/core", status="active"), job(12, task="work/b", workdir="/core", hotfix="fix-1")]
        self.assertEqual(self.decide(running), {"j12": "waits in line behind j11"})

    def test_r5_a_blocked_hotfix_head_that_could_start_is_passed_only_by_light_jobs_taking_nothing_it_lacks(self):
        rules = {"free_gb": 40.0, "light": {"test-nostack"}, "slot_limits": {"test": 5, "test-nostack": 5}}
        light = job(3, kind="test-nostack", task="work/c", need_gb=0, workdir="/l")
        hotfix, small, disk = job(1, need_gb=15, hotfix="main-red"), job(2, task="work/b", workdir="/s"), job(8, status="active", need_gb=20, workdir="/d")
        self.assertEqual(self.decide([disk, hotfix, small, light], **rules), {
            "j1": "15 GB would cut into the 10 GB floor", "j2": "waits behind hotfix j1", "j3": None,
        })
        self.assertEqual(self.decide([{**hotfix, "need_gb": 50}, small, light], **rules),
                         {"j1": "50 GB would cut into the 10 GB floor", "j2": None, "j3": None})
        running, fixing = job(9, status="active", workdir="/r"), job(1, hotfix="main-red")
        shares = {"j9": {"ram": 50, "cpu": 10}, "j1": {"ram": 30, "cpu": 10}, "j2": {"ram": 5, "cpu": 5}, "j3": {"ram": 10, "cpu": 5}}
        self.assertEqual(self.decide([running, fixing, small, light], footprints=shares, **rules), {
            "j1": "RAM 50 % in use or reserved + 30 % > budget 75 %", "j2": "waits behind hotfix j1", "j3": "waits behind hotfix j1",
        })
        self.assertEqual(self.decide([running, fixing, light], footprints=shares | {"j3": {"ram": 0, "cpu": 5}}, **rules)["j3"], None)
        pressed = self.decide([running, fixing, light], loaded={"j1": "CPU 95 % busy reaches the limit 90 %"}, **rules)
        self.assertEqual(pressed["j3"], "waits behind hotfix j1")
        second = job(4, task="work/c", hotfix="fix-2", workdir="/f")
        self.assertEqual(self.decide([disk, hotfix, second], **rules)["j4"], "waits behind hotfix j1")
        normal = {**hotfix, "hotfix": None, "need_gb": 50}
        self.assertEqual(self.decide([normal, small, light], **rules), {"j1": "50 GB would cut into the 10 GB floor", "j2": None, "j3": None})

    def test_a_drain_starts_only_once_nothing_fits_and_ends_when_its_head_leaves_or_cannot_fit_the_disk(self):
        running = job(9, need_gb=40, status="active", workdir="/r")
        big, small = job(1, need_gb=50), job(2, task="work/b", need_gb=25, workdir="/s")
        late, light = job(3, task="work/c", need_gb=5, workdir="/t"), job(4, kind="test-nostack", task="work/c", need_gb=0, workdir="/l")
        rules = {"free_gb": 70.0, "light": {"test-nostack"}, "slot_limits": {"test": 5, "test-nostack": 5}}
        self.assertIsNone(self.run_pass([running, big, small, late], **rules)[1])
        self.assertEqual(self.run_pass([running, big, small], **rules)[1], "j1")
        self.assertEqual(self.decide([running, big, small, late, light], drain="j1", **rules), {
            "j1": "50 GB would cut into the 10 GB floor", "j2": "25 GB would cut into the 10 GB floor",
            "j3": "drained for j1", "j4": None,
        })
        self.assertEqual(self.run_pass([running, big, small, late], drain="j1", **rules)[1], "j1")
        self.assertEqual(self.decide([big, small, late], drain="j1", **rules), {
            "j1": None, "j2": "25 GB would cut into the 10 GB floor", "j3": None,
        })
        self.assertIsNone(self.run_pass([running, small, late], drain="j1", **rules)[1])
        self.assertIsNone(self.run_pass([running, big, small], drain="j1", **{**rules, "free_gb": 55.0})[1])
        deploying, head = job(9, kind="deploy", need_gb=0, status="active", workdir="/r"), job(1, kind="deploy", need_gb=20)
        fits, wide = job(3, task="work/c", need_gb=5, workdir="/t"), job(5, task="work/c", need_gb=45, workdir="/u")
        slots = {**rules, "slot_limits": {"test": 5, "deploy": 1}}
        self.assertEqual(self.decide([deploying, head, fits, wide], drain="j1", **slots), {
            "j1": "all 1 deploy slots taken", "j3": None, "j5": "drained for j1",
        })

    def test_claims_name_the_worktree_and_the_compose_stack_its_directory_derives(self):
        with tempfile.TemporaryDirectory() as tmp:
            plain, named, stack = Path(tmp, "plain"), Path(tmp, "Core.Stack_1"), Path(tmp, "pinned")
            for path in (plain, named, stack):
                path.mkdir()
            (named / "compose.yml").write_text("services: {}\n", encoding="utf-8")
            (stack / "docker-compose.yaml").write_text("services: {}\n", encoding="utf-8")
            (stack / ".env").write_text("A=1\nCOMPOSE_PROJECT_NAME='shared'\n", encoding="utf-8")
            self.assertEqual(self.queue.claims_of(str(plain)), [str(plain)])
            self.assertEqual(self.queue.claims_of(str(named)), [str(named), "stack:corestack_1"])
            self.assertEqual(self.queue.claims_of(str(stack)), [str(stack), "stack:shared"])
        self.assertEqual(self.queue.claims(job(1, kind="test")), ["/w1"])
        self.assertEqual(self.queue.claims(job(1, claims=["/a", "stack:x"])), ["/a", "stack:x"])

    def test_r2_worktrees_pinned_to_one_slot_share_a_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            pins = {"a": ("custom.env", "INFINITO_INSTANCE=174\n"), "b": (".env", 'X=1\nINFINITO_INSTANCE="174"\n'),
                    "c": ("custom.env", "INFINITO_INSTANCE=175\n"), "core": ("default.env", "INFINITO_INSTANCE=0\n")}
            for name, (pin, text) in pins.items():
                (base / name).mkdir()
                (base / name / "compose.yml").write_text("services: {}\n", encoding="utf-8")
                (base / name / pin).write_text(text, encoding="utf-8")
            (base / "a" / "default.env").write_text("INFINITO_INSTANCE=0\n", encoding="utf-8")
            claims = {name: self.queue.claims_of(str(base / name)) for name in pins}
            (base / "d").mkdir()
            (base / "d" / "custom.env").write_text("INFINITO_INSTANCE=174\n", encoding="utf-8")
            (base / "d" / ".env").write_text("INFINITO_INSTANCE=180\n", encoding="utf-8")
            drifted = self.queue.claims_of(str(base / "d"))
        self.assertEqual(claims["a"], [str(base / "a"), "stack:a", "slot:174"])
        self.assertEqual(claims["b"], [str(base / "b"), "stack:b", "slot:174"])
        self.assertEqual(claims["core"], [str(base / "core"), "stack:core", "slot:0"])
        self.assertEqual(drifted, [str(base / "d"), "slot:174"])
        load = "CPU 95 % busy reaches the limit 90 %"
        entries = [job(1, claims=claims["a"]), job(2, task="work/b", claims=claims["b"]), job(3, task="work/b", claims=claims["c"])]
        self.assertEqual(self.decide(entries, loaded={"j1": load}), {"j1": load, "j2": "waits in line behind j1", "j3": None})

    def test_disk_reservation_keeps_smaller_jobs_from_starving_a_big_one(self):
        big, small, later = job(1, workdir="/w", need_gb=50, enqueued=NOW - 60), job(2, workdir="/w", need_gb=5, enqueued=NOW - 30), job(3, workdir="/w", need_gb=5)
        verdicts, _, order = self.run_pass([big, small], free_gb=64.0, floor=15.0)
        self.assertEqual(verdicts, {"j1": "50 GB would cut into the 15 GB floor", "j2": None})
        data = {"entries": [big, small], "granted_at": NOW}
        self.assertEqual(self.queue.stalled(data, order, verdicts, 15.0, 64.0, idle, NOW)[:2], ([], True))
        sends, clean, _ = self.queue.stalled(data, order, verdicts, 15.0, 64.0, idle, NOW + 60)
        self.assertEqual(([label for label, _ in sends], clean), (["noticed that the head cannot fit"], False))
        self.assertIn("head j1 needs 50 GB, max reachable 49 GB", " ".join(word for _, words in sends for word in words))
        self.assertEqual(self.decide([big, later], free_gb=66.0, floor=15.0), {"j1": None, "j3": "waits in line behind j1"})

    def test_labels_mark_backfilled_entries_and_the_escalated_head(self):
        verdicts = {"h": "blocked", "a": None, "b": "waits in line behind h"}
        self.assertEqual(self.queue.labelled(verdicts, ["post", "call"]), {
            "h": "escalated call: blocked", "a": "backfilled", "b": "waits in line behind h",
        })
        self.assertEqual(self.queue.labelled({"a": None, "h": "blocked"}, []), {"a": None, "h": "blocked"})

    def test_r3_p1_disk_alone_in_the_warn_and_stop_bands_starts_the_cleanup_and_the_notice(self):
        head = job(1, kind="deploy", need_gb=20, enqueued=NOW - 60)
        bands = ((30.0, "ok", "20 GB would cut into the 15 GB floor", 15), (35.0, "warn", "disk stage warn admits only jobs that need no disk", 0),
                 (14.0, "stop", "disk stage stop", 0))
        for free, stage, reason, reach in bands:
            with self.subTest(stage=stage):
                verdicts, _, order = self.run_pass([head], free_gb=free, stage=stage, floor=15.0)
                data = {"entries": [head], "granted_at": NOW - 60}
                polls = [self.queue.stalled(data, order, verdicts, 15.0, free, idle, NOW + at) for at in (0, 20, 40)]
                text = f"kvb-org-queue: head j1 needs 20 GB, max reachable {reach} GB after cleanup ({reason}); operator cleanup needed"
                self.assertEqual(verdicts, {"j1": reason})
                self.assertEqual(polls, [
                    ([], True, None), ([("noticed that the head cannot fit", ["post", text, "--to", "Main"])], False,
                                       "low-risk cleanup ended without a report"), ([], False, None),
                ])

    def test_r3_s2_a_head_live_load_holds_behind_the_floor_is_no_disk_alone_stall(self):
        head, load = job(1, need_gb=70), "CPU 95 % busy reaches the limit 90 %"
        verdicts, _, order = self.run_pass([head], free_gb=80.0, floor=15.0, loaded={"j1": load})
        self.assertEqual(verdicts, {"j1": "70 GB would cut into the 15 GB floor"})
        self.assertEqual(self.queue.stalled({"entries": [head], "granted_at": NOW}, order, verdicts, 15.0, 80.0, idle, NOW), ([], False, None))

    def test_r3_p4_a_line_runs_by_enqueue_time_whatever_the_rank(self):
        load = "CPU 95 % busy reaches the limit 90 %"
        older, younger, other = job(1, task="work/c", workdir="/core", enqueued=NOW - 1800), job(2, workdir="/core"), job(3, task="work/b", workdir="/x")
        verdicts = self.decide([younger, other, older], loaded={"j1": load})
        self.assertEqual(list(verdicts.items()), [("j1", load), ("j2", "waits in line behind j1"), ("j3", None)])
        normal, hotfix = job(4, workdir="/core", need_gb=50, enqueued=NOW - 60), job(5, workdir="/core", hotfix="main-red")
        self.assertEqual(self.decide([hotfix, normal, job(6, task="work/b", workdir="/s")], free_gb=40.0), {
            "j5": None, "j4": "waits in line behind j5", "j6": None,
        })

    def test_r3_p5_a_drain_head_that_live_load_holds_holds_back_every_entry_after_it(self):
        running, head, small = job(9, status="active", workdir="/r", granted=NOW - HOUR), job(1), job(2, task="work/b", workdir="/s")
        shares = {"j9": {"ram": 30, "cpu": 10}, "j1": {"ram": 40, "cpu": 10}, "j2": {"ram": 5, "cpu": 5}}
        ram = "RAM 60 % used + 40 % still to come reach the limit 90 %"
        self.assertEqual(self.run_pass([running, head, small], footprints=shares, loaded={"j1": ram, "j2": ram})[1], "j1")
        self.assertEqual(self.decide([running, head, small], footprints=shares, loaded={"j1": ram}, drain="j1"), {
            "j1": ram, "j2": "drained for j1",
        })
        self.assertEqual(self.decide([running, head, small], footprints=shares, loaded={"j1": ram}), {"j1": ram, "j2": None})

    def test_r3_p6_a_light_job_takes_nothing_the_drain_head_still_lacks(self):
        rules = {"light": {"test-nostack"}, "slot_limits": {"test": 5, "test-nostack": 5}, "drain": "j1"}
        running, head = job(9, status="active", workdir="/r"), job(1)
        light = job(2, kind="test-nostack", task="work/b", workdir="/l")
        shares = {"j9": {"ram": 40, "cpu": 0}, "j1": {"ram": 45, "cpu": 0}, "j2": {"ram": 35, "cpu": 0}}
        self.assertEqual(self.decide([running, head, light], footprints=shares, **rules), {
            "j1": "RAM 40 % in use or reserved + 45 % > budget 75 %", "j2": "drained for j1",
        })
        self.assertIsNone(self.decide([running, head, light], footprints={**shares, "j2": {"ram": 0, "cpu": 0}}, **rules)["j2"])

    def test_r3_p7_one_spike_poll_never_starts_a_drain_and_a_minute_of_blocked_polls_does(self):
        running, head = job(9, need_gb=40, status="active", workdir="/r"), job(1, need_gb=50)
        small, spike = job(2, task="work/b", need_gb=5, workdir="/s"), "CPU 99 % busy reaches the limit 90 %"
        data: dict = {"drain": None}

        def poll(at: float, loaded: dict[str, str]) -> str | None:
            _, drain, _ = self.run_pass([running, head, small], free_gb=70.0, loaded=loaded, drain=data["drain"], now=at)
            data["drain"] = self.queue.latched(data, drain, at)
            return data["drain"]

        self.assertEqual([poll(NOW, {"j1": spike, "j2": spike}), poll(NOW + 20, {})], [None, None])
        self.assertNotIn(self.queue.BLOCKED, data)
        self.assertEqual([poll(NOW + 40 + 20 * n, {"j2": spike}) for n in range(4)], [None, None, None, "j1"])

    def test_r3_s1_a_steady_stream_starts_the_head_within_the_age_limit_plus_one_job(self):
        rules = {"free_gb": 100.0, "floor": 15.0, "slot_limits": {"test": 1000}}
        head = job(1, need_gb=70, workdir="/h")
        active, waiting, data = [job(2, need_gb=20, status="active", granted=NOW - 60, workdir="/w2")], [head], {"drain": None}
        for poll in range(4 * 180):
            at = NOW + poll * 20
            active = [e for e in active if at - e["granted"] < 1800]
            waiting.append(job(poll + 3, task="work/b", need_gb=0 if poll % 45 else 20, enqueued=at))
            verdicts, drain, _ = self.run_pass([*active, *waiting], drain=data["drain"], now=at, **rules)
            data["drain"] = self.queue.latched(data, drain, at)
            if verdicts["j1"] is None:
                self.assertLessEqual(at - NOW, self.queue.DRAIN_AFTER_SECONDS + 1800 + self.queue.DEBOUNCE_SECONDS)
                return
            active += [{**e, "status": "active", "granted": at} for e in waiting if verdicts[e["id"]] is None]
            waiting = [e for e in waiting if verdicts[e["id"]] is not None]
        self.fail("a steady stream starved the head")

    def test_r4_load_from_outside_the_queue_drains_for_no_head_and_holds_back_no_job(self):
        rules = {"exclusive": {"quality-high", "test"}, "light": {"test-nostack"},
                 "slot_limits": {"quality-high": 1, "test": 1, "test-nostack": 4, "iteration": 3}}
        head, light = job(1, kind="quality-high", enqueued=NOW - 3700), job(2, kind="test-nostack", task="work/b", workdir="/l")
        heavy, running = job(3, kind="iteration", task="work/b", workdir="/i"), job(9, kind="test-nostack", status="active", workdir="/r")
        ram = "RAM 45 % used + 41 % still to come reach the limit 85 %"
        outside = self.queue.Outside(ram)
        self.assertEqual(self.run_pass([head, light, heavy], loaded={"j1": ram}, drain="j1", **rules)[:2],
                         ({"j1": ram, "j2": None, "j3": None}, None))
        self.assertEqual(self.run_pass([running, head, light, heavy], loaded={"j1": outside}, drain="j1", **rules)[:2],
                         ({"j1": ram, "j2": None, "j3": None}, None))
        self.assertEqual(self.run_pass([running, head, light, heavy], loaded={"j1": ram}, drain="j1", **rules)[:2],
                         ({"j1": ram, "j2": None, "j3": "drained for j1"}, "j1"))
        twin = job(4, kind="test", task="work/c", workdir="/w1")
        self.assertEqual((self.decide([head, twin], loaded={"j1": outside}, **rules), self.decide([head, twin], loaded={"j1": ram}, **rules)),
                         ({"j1": ram, "j4": None}, {"j1": ram, "j4": "waits in line behind j1"}))

    def test_r4_a_head_aged_out_waiting_only_for_an_exclusive_job_holds_back_no_light_job(self):
        rules = {"exclusive": {"quality-high", "test"}, "light": {"test-nostack"}, "budget": {"ram": 75, "cpu": 100},
                 "slot_limits": {"quality-high": 1, "test": 1, "test-nostack": 4}}
        running = job(9, kind="test", status="active", workdir="/r", granted=NOW - 300)
        head, light = job(1, kind="quality-high", enqueued=NOW - 3700), job(2, kind="test-nostack", task="work/b", workdir="/l")
        shares = {"j9": {"ram": 34.5, "cpu": 24.5}, "j1": {"ram": 40.6, "cpu": 59.8}, "j2": {"ram": 7.2, "cpu": 9.8}}
        verdicts, drain, _ = self.run_pass([running, head, light], footprints=shares, drain="j1", **rules)
        self.assertEqual((verdicts, drain), ({"j1": "quality-high runs only beside test-nostack, but test runs", "j2": None}, "j1"))
        greedy = {**shares, "j2": {"ram": 40.0, "cpu": 9.8}}
        self.assertEqual(self.decide([running, head, light], footprints=greedy, drain="j1", **rules)["j2"], "drained for j1")


class TestTrace(Passes, unittest.TestCase):
    def traced(self, entries: list[dict], **overrides: object) -> tuple[dict, dict]:
        trace: dict[str, list[str]] = {}
        verdicts = self.run_pass(entries, trace=trace, **overrides)[0]
        again: dict[str, list[str]] = {}
        self.run_pass(entries, trace=again, **overrides)
        self.assertEqual(again, trace)
        return verdicts, trace

    def test_r5_the_trace_names_the_order_and_the_fit_of_a_granted_entry(self):
        fit = "RAM 0 % + 0 %, CPU 0 % + 0 %, 1 GB of 100 GB fits"
        cases = {
            "hotfix first": ([job(1, hotfix="main-red")], {}, ["hotfix first", "rank 0", "arrival 1", fit]),
            "rank and age": ([job(1, task="work/c", enqueued=NOW - 2 * HOUR)], {}, ["rank 2, 2 h waited: 0", "arrival 1", fit]),
            "unranked with agent order": ([job(1, task="work/z")], {"agents": {"s1": 0}}, ["unranked", "agent order 0", "arrival 1", fit]),
            "backfill": ([job(1, need_gb=95), job(2, task="work/b")], {},
                         ["rank 1", "arrival 2", "RAM 0 % + 0 %, CPU 0 % + 0 %, 1 GB of 100 GB fits", "backfilled past j1"]),
        }
        for name, (entries, overrides, steps) in cases.items():
            with self.subTest(name):
                verdicts, trace = self.traced(entries, **overrides)
                self.assertEqual((verdicts[entries[-1]["id"]], trace[entries[-1]["id"]]), (None, steps))

    def test_r5_the_trace_ends_in_the_rule_that_blocked_the_entry(self):
        load = "CPU 95 % busy reaches the limit 90 %"
        running = job(9, status="active", workdir="/r")
        gates = {"exclusive": {"quality-high"}, "light": {"test-nostack"}, "slot_limits": {"quality-high": 1, "iteration": 2, "test-nostack": 2, "test": 5}}
        greedy = {"j9": {"ram": 30, "cpu": 30}, "j1": {"ram": 40, "cpu": 40}, "j2": {"ram": 40, "cpu": 70}, "j3": {"ram": 0, "cpu": 5}}
        machine = [job(9, kind="iteration", status="active", workdir="/r"), job(1, kind="quality-high"), job(2, kind="iteration", task="work/b")]
        cases = {
            "line": ([job(9, kind="deploy", status="active", workdir="/r"), job(1, kind="deploy", workdir="/core"), job(2, task="work/b", workdir="/core")],
                     {}, "j2", "line /core behind j1"),
            "hotfix ahead that could start": ([job(9, kind="deploy", status="active", workdir="/r"), job(1, kind="deploy", hotfix="main-red"),
                                               job(2, task="work/b")], {}, "j2", "hotfix j1 blocked ahead"),
            "hotfix pressed": ([running, job(1, hotfix="main-red"), job(2, kind="test-nostack", task="work/b")],
                               {"loaded": {"j1": load}, **gates}, "j2", "hotfix j1 blocked ahead: load holds it"),
            "exclusive head": (machine, gates, "j2", "drained for j1: quality-high is exclusive"),
            "load head": ([running, job(1), job(2, task="work/b")], {"loaded": {"j1": load}, "drain": "j1"}, "j2",
                          "drained for j1: load holds it"),
            "takes what the head lacks": ([*machine[:2], job(2, kind="test-nostack", task="work/b")], {"footprints": greedy, **gates}, "j2",
                                          "drained for j1: takes RAM and CPU"),
            "disk stage": ([job(1)], {"stage": "stop"}, "j1", "disk stage stop"),
            "memory stage": ([job(1)], {"memory": "stop"}, "j1", "memory stage stop"),
            "slot": ([job(1, kind="deploy", status="active"), job(2, kind="deploy", task="work/b")], {}, "j2", "all 1 deploy slots taken"),
            "alone": (machine, gates, "j1", "quality-high runs only beside test-nostack, but iteration runs"),
            "budget": ([running, job(1)], {"footprints": {"j9": {"ram": 50, "cpu": 0}, "j1": {"ram": 30, "cpu": 0}}}, "j1",
                       "RAM 50 % in use or reserved + 30 % > budget 75 %"),
            "floor": ([job(1, need_gb=95)], {}, "j1", "95 GB would cut into the 10 GB floor"),
            "load": ([job(1)], {"loaded": {"j1": load}}, "j1", load),
        }
        for name, (entries, overrides, target, step) in cases.items():
            with self.subTest(name):
                verdicts, trace = self.traced(entries, **overrides)
                self.assertIsNotNone(verdicts[target])
                self.assertEqual(trace[target][-1], step)

    def test_r5_the_trace_marks_the_drain_head_a_head_a_light_job_takes_nothing_from_and_a_silent_entry(self):
        gates = {"exclusive": {"quality-high"}, "light": {"test-nostack"}, "slot_limits": {"quality-high": 1, "iteration": 2, "test-nostack": 2}}
        machine = [job(9, kind="iteration", status="active", workdir="/r"), job(1, kind="quality-high"), job(2, kind="test-nostack", task="work/b")]
        _, trace = self.traced(machine, drain="j1", **gates)
        self.assertEqual(trace["j1"][-2:], ["drain head", "quality-high runs only beside test-nostack, but iteration runs"])
        self.assertEqual(trace["j2"][-3:], ["takes nothing j1 lacks", "RAM 0 % + 0 %, CPU 0 % + 0 %, 1 GB of 99 GB fits", "backfilled past j1"])
        verdicts, trace = self.traced([job(1, polled=NOW - 600)])
        self.assertEqual(trace["j1"], [verdicts["j1"]])

    def test_r6_a_light_job_passes_an_older_job_of_its_worktree_only_while_that_one_waits_for_the_machine(self):
        gates = {"exclusive": {"quality-high"}, "light": {"test-nostack"}, "slot_limits": {"quality-high": 1, "iteration": 2, "test-nostack": 2}}
        gate = job(9, kind="quality-high", status="active", workdir="/r")
        heavy, light = job(1, kind="iteration", workdir="/core"), job(2, kind="test-nostack", task="work/b", workdir="/core")
        verdicts, trace = self.traced([gate, heavy, light], **gates)
        self.assertEqual(verdicts, {"j1": "quality-high runs only beside test-nostack", "j2": None})
        self.assertIn("passes j1: it waits for the machine", trace["j2"])
        self.assertEqual(self.decide([{**light, "status": "active"}, heavy], **gates), {"j1": "waits in line behind j2"})
        stacked = [gate, job(8, kind="iteration", status="active", claims=["/x", "stack:core"]),
                   {**heavy, "claims": ["/core", "stack:core"]}, {**light, "claims": ["/core"]}]
        self.assertEqual(self.decide(stacked, **gates)["j2"], "waits in line behind j1")
        self.assertEqual(self.decide([gate, {**heavy, "hotfix": "main-red"}, light], **gates)["j2"], "waits in line behind j1")

    def test_r6_beside_a_head_waiting_for_an_exclusive_job_only_light_jobs_count(self):
        gates = {"exclusive": {"quality-high"}, "light": {"test-nostack"}, "slot_limits": {"quality-high": 1, "gui-dind": 1, "test-nostack": 2}}
        gate, head = job(9, kind="quality-high", status="active", workdir="/r"), job(1, kind="gui-dind")
        light = job(2, kind="test-nostack", task="work/b")
        shares = {"j9": {"ram": 40.6, "cpu": 59.8}, "j1": {"ram": 20.7, "cpu": 63.6}, "j2": {"ram": 7.2, "cpu": 9.8}}
        verdicts, trace = self.traced([gate, head, light], footprints=shares, drain="j1", **gates)
        self.assertEqual(verdicts["j2"], None)
        self.assertIn("takes nothing j1 lacks", trace["j2"])
        greedy = shares | {"j2": {"ram": 7.2, "cpu": 40.0}}
        self.assertEqual(self.decide([gate, head, light], footprints=greedy, drain="j1", **gates)["j2"], "drained for j1")

    def test_r7_a_hotfix_never_waits_in_line_behind_an_older_waiting_entry_that_is_no_hotfix(self):
        gates = {"exclusive": {"quality-high"}, "light": {"test-nostack"},
                 "slot_limits": {"quality-high": 1, "iteration": 3, "test-nostack": 1}}
        filled = job(9, id="A", kind="test-nostack", status="active", workdir="/a")
        older = job(1, id="L", kind="test-nostack", workdir="/main", enqueued=NOW - 20, name="Main")
        hotfix = job(2, id="H", kind="quality-high", workdir="/main", enqueued=NOW - 10, name="Main", hotfix="main-red")
        self.assertEqual(self.decide([filled, older, hotfix], **gates), {"H": None, "L": "waits in line behind H"})
        gate = job(8, id="Q", kind="quality-high", status="active", workdir="/other")
        main = {**older, "id": "X", "kind": "quality-high"}
        other = job(3, id="I", kind="iteration", task="work/b", workdir="/b", enqueued=NOW)
        verdicts, trace = self.traced([gate, main, hotfix, other], **gates)
        self.assertEqual(verdicts, {"H": "all 1 quality-high slots taken", "X": "waits behind hotfix H", "I": "waits behind hotfix H"})
        self.assertEqual(trace["H"][0], "hotfix first")
        self.assertEqual(self.decide([main, hotfix, other], **gates), {
            "H": None, "X": "waits in line behind H", "I": "quality-high runs only beside test-nostack",
        })

    def test_r7_a_drain_head_keeps_its_slot_and_its_line_delays_it_by_one_light_run_at_most(self):
        gates = {"exclusive": {"quality-high"}, "light": {"test-nostack"}, "slot_limits": {"iteration": 3, "test-nostack": 4}}
        busy = [job(7, id="Ib", kind="iteration", status="active", workdir="/b"), job(8, id="Ic", kind="iteration", status="active", workdir="/c")]
        head = job(1, id="H", kind="iteration", workdir="/h", enqueued=NOW - 5000)
        rival = job(2, id="I2", kind="iteration", workdir="/v", enqueued=NOW - 4000)
        running = job(9, id="L1", kind="test-nostack", status="active", workdir="/h")
        verdicts, trace = self.traced([*busy, running, head, rival], drain="H", **gates)
        self.assertEqual(verdicts, {"H": "waits in line behind L1", "I2": "drained for H"})
        self.assertEqual(trace["I2"][-1], "drained for H: takes its iteration slot")
        later = job(3, id="L2", kind="test-nostack", workdir="/h", enqueued=NOW - 100)
        elsewhere = job(4, id="L3", kind="test-nostack", workdir="/z", enqueued=NOW - 50)
        verdicts, trace = self.traced([*busy, {**rival, "status": "active"}, head, later, elsewhere], drain="H", **gates)
        self.assertEqual(verdicts, {"H": "all 3 iteration slots taken", "L2": None, "L3": None})
        self.assertEqual(trace["L2"][-4:-2], ["passes H: it waits for the machine", "takes nothing H lacks"])
        self.assertIn("takes nothing H lacks", trace["L3"])
        next_one = job(5, id="L4", kind="test-nostack", workdir="/h", enqueued=NOW - 20)
        third = job(6, id="I3", kind="iteration", workdir="/w", enqueued=NOW - 10)
        freed = [busy[0], {**rival, "status": "active"}, {**later, "status": "active"}, head, next_one, third]
        self.assertEqual(self.decide(freed, drain="H", **gates), {"H": "waits in line behind L2", "L4": "waits in line behind L2", "I3": "drained for H"})
        self.assertEqual(self.decide([busy[0], {**rival, "status": "active"}, head, next_one, third], drain="H", **gates),
                         {"H": None, "L4": "waits in line behind H", "I3": "all 3 iteration slots taken"})

    def test_r7_a_granted_entry_owns_its_line_for_the_rest_of_the_pass(self):
        gates = {"exclusive": {"quality-high"}, "light": {"test-nostack"}, "slot_limits": {"quality-high": 1, "test-nostack": 4}}
        gate = job(9, id="Q", kind="quality-high", status="active", workdir="/other")
        waiting = job(1, id="M", kind="quality-high", workdir="/x", enqueued=NOW - 30)
        first, second = (job(n, id=f"L{n - 1}", kind="test-nostack", workdir="/x", enqueued=NOW - 30 + n) for n in (2, 3))
        verdicts, trace = self.traced([gate, waiting, first, second], **gates)
        self.assertEqual(verdicts, {"M": "all 1 quality-high slots taken", "L1": None, "L2": "waits in line behind L1"})
        self.assertEqual(trace["L2"][-1], "line /x behind L1")

    def test_r8_a_main_job_whose_line_runs_or_waits_for_the_machine_reserves_against_younger_lines(self):
        gates = {"exclusive": {"quality-high", "test"}, "light": {"test-nostack"},
                 "slot_limits": {"quality-high": 1, "test": 1, "iteration": 2, "test-nostack": 4}}
        filled = [job(10 + n, id=f"F{n}", kind="test-nostack", status="active", workdir=f"/f{n}") for n in range(4)]
        light = job(1, id="L", kind="test-nostack", workdir="/main", enqueued=NOW - 30, name="Main")
        gate = job(2, id="X", kind="quality-high", workdir="/main", enqueued=NOW - 20, name="Main")
        rival = job(3, id="T", kind="test", task="work/b", workdir="/t", enqueued=NOW - 10)
        verdicts, trace = self.traced([*filled, light, gate, rival], **gates)
        self.assertEqual(verdicts, {"L": "all 4 test-nostack slots taken", "X": "waits in line behind L", "T": "reserved for X"})
        self.assertEqual(trace["T"][-1], "reserved for X: quality-high is exclusive")
        self.assertEqual(self.decide([*filled[:3], {**light, "status": "active"}, gate, rival], **gates)["T"], "reserved for X")
        self.assertEqual(self.decide([*filled, light, {**gate, "name": "s1"}, rival], **gates)["T"], None)
        running = job(4, id="R", kind="iteration", status="active", workdir="/w")
        deploy, other = job(5, id="D", kind="iteration", workdir="/w", name="Main"), job(6, id="E", kind="iteration", task="work/b", workdir="/e")
        small = job(7, id="S", kind="test-nostack", task="work/c", workdir="/s")
        verdicts, trace = self.traced([running, deploy, other, small], **gates)
        self.assertEqual(verdicts, {"D": "waits in line behind R", "E": "reserved for D", "S": None})
        self.assertEqual(trace["E"][-1], "reserved for D: takes its iteration slot")
        chained = [job(4, id="Z", kind="iteration", status="active", claims=["/z"]), job(5, id="Y", kind="iteration", claims=["/z", "/main"], enqueued=NOW - 600),
                   {**gate, "claims": ["/main"]}, {**other, "id": "T"}]
        self.assertEqual(self.decide(chained, **gates), {"Y": "waits in line behind Z", "X": "waits in line behind Y", "T": None})

    def test_r10_a_job_passes_a_holder_of_its_line_that_can_never_start_and_takes_its_place(self):
        gates = {"exclusive": {"quality-high"}, "light": {"test-nostack"},
                 "slot_limits": {"quality-high": 1, "iteration": 2, "gui-dind": 1, "swarm": 0}}
        holder = job(1, id="O", kind="swarm", workdir="/main", enqueued=NOW - 30, name="Main")
        gate = job(2, id="X", kind="quality-high", workdir="/main", enqueued=NOW - 20, name="Main")
        others = [job(3, id="I", kind="iteration", task="work/b", workdir="/b"), job(4, id="G", kind="gui-dind", task="work/c", workdir="/c")]
        verdicts, trace = self.traced([holder, gate, *others], **gates)
        beside = "quality-high runs only beside test-nostack"
        self.assertEqual(verdicts, {"O": "all 0 swarm slots taken", "X": None, "I": beside, "G": beside})
        self.assertIn("passes O: O can never start, 0 swarm slots", trace["X"])
        running, later = job(9, id="Q", kind="quality-high", status="active", workdir="/q"), job(5, id="Y", kind="iteration", workdir="/main")
        self.assertEqual(self.decide([running, holder, gate, later], **gates),
                         {"O": "all 0 swarm slots taken", "X": "all 1 quality-high slots taken", "Y": "waits in line behind X"})
        huge = {**holder, "kind": "iteration", "need_gb": 200}
        verdicts, trace = self.traced([huge, gate], **gates)
        self.assertEqual(verdicts["X"], None)
        self.assertIn("passes O: O can never start, 200 GB would cut into the 10 GB floor", trace["X"])

    def test_r11_a_hotfix_that_can_never_start_holds_no_one_back_and_heads_nothing(self):
        gates = {"exclusive": {"quality-high"}, "light": {"test-nostack"},
                 "slot_limits": {"swarm": 0, "iteration": 2, "gui-dind": 1, "test-nostack": 2, "quality-high": 1}}
        doomed = job(1, id="H", kind="swarm", workdir="/main", hotfix="main-red", name="Main", enqueued=NOW - 30)
        others = [job(2, id="I", kind="iteration", task="work/b", workdir="/b"), job(3, id="G", kind="gui-dind", task="work/c", workdir="/c"),
                  job(4, id="L", kind="test-nostack", task="work/c", workdir="/d")]
        self.assertEqual(self.decide([doomed, *others], **gates), {"H": "all 0 swarm slots taken", "I": None, "G": None, "L": None})
        gate, able = job(9, id="Q", kind="quality-high", status="active", workdir="/q"), job(5, id="H2", kind="quality-high", workdir="/h2",
                                                                                              hotfix="main-red", enqueued=NOW - 20)
        self.assertEqual(self.decide([gate, doomed, able, others[0]], **gates),
                         {"H": "all 0 swarm slots taken", "H2": "all 1 quality-high slots taken", "I": "waits behind hotfix H2"})

    def test_r11_a_holder_that_could_not_start_regains_its_place_once_it_can(self):
        gates = {"exclusive": {"quality-high"}, "light": {"test-nostack"}, "slot_limits": {"quality-high": 1, "iteration": 2, "swarm": 0}}
        line = [job(1, id="O", kind="swarm", workdir="/main", enqueued=NOW - 30), job(2, id="X", kind="quality-high", workdir="/main", enqueued=NOW - 20),
                job(3, id="Y", kind="iteration", workdir="/main", enqueued=NOW - 10)]
        self.assertEqual(self.decide(line, **gates), {"O": "all 0 swarm slots taken", "X": None, "Y": "waits in line behind X"})
        back = {**gates, "slot_limits": {**gates["slot_limits"], "swarm": 1}}
        self.assertEqual(self.decide(line, **back), {"O": None, "X": "waits in line behind O", "Y": "waits in line behind O"})

    def test_r7_the_stack_comes_from_the_env_then_the_compose_name_then_the_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            files = {
                "a/compose.yml": "name: security-check-inspect\nservices: {}\n",
                "b/compose.yaml": 'name: "security-check-inspect"  # shared\nservices:\n  web:\n    name: other\n',
                "c/compose.yml": "name: security-check-inspect\n", "c/.env": "COMPOSE_PROJECT_NAME=own\n",
                "d/docker-compose.yml": "services:\n  name: nested\n",
            }
            for name, text in files.items():
                Path(tmp, name).parent.mkdir(exist_ok=True)
                Path(tmp, name).write_text(text, encoding="utf-8")
            stacks = {name: self.queue.claims_of(str(Path(tmp, name)))[1:] for name in "abcd"}
        self.assertEqual(stacks, {"a": ["stack:security-check-inspect"], "b": ["stack:security-check-inspect"], "c": ["stack:own"], "d": ["stack:d"]})


class TestEscalation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.queue = _load(QUEUE)

    def climb(self, stall: dict, grant: float, minutes: list[float], **flags: bool) -> tuple[dict, list]:
        steps = []
        for minute in minutes:
            stall, step = self.queue.escalate(json.loads(json.dumps(stall)), grant, grant, flags.get("hotfix", False),
                                              grant + minute * 60)
            steps.append(step)
        return stall, steps

    def test_each_step_fires_once_at_its_threshold_and_the_state_survives_a_restart(self):
        minutes = [29, 30, 31, 59, 60, 119, 120, 239, 240, 24 * 60 - 1, 24 * 60, 48 * 60]
        stall, steps = self.climb({}, NOW, minutes)
        self.assertEqual(steps, [None, "post", None, None, "call", None, "security", None, "pan-pan", None, "mayday", None])
        self.assertEqual(stall["fired"], ["post", "call", "security", "pan-pan", "mayday"])
        self.assertEqual([threshold for threshold, _, _ in self.queue.ESCALATION], [30, 60, 120, 240, 24 * 60])

    def test_a_new_grant_resets_the_stall_and_a_late_first_look_fires_only_the_highest_due_step(self):
        stall, _ = self.climb({}, NOW, [30])
        stall, steps = self.climb(stall, NOW + 3600, [29, 30])
        self.assertEqual((steps, stall["fired"]), ([None, "post"], ["post"]))
        stall, step = self.queue.escalate({}, NOW, NOW, False, NOW + 5 * HOUR)
        self.assertEqual((step, stall["fired"]), ("pan-pan", ["post", "call", "security", "pan-pan"]))
        self.assertIsNone(self.queue.escalate({}, NOW, NOW + HOUR, False, NOW + HOUR + 29 * 60)[1])

    def test_the_clock_stands_still_while_a_hotfix_runs_ahead_of_the_head(self):
        stall, steps = self.climb({}, NOW, [20, 50], hotfix=True)
        self.assertEqual(steps, [None, None])
        stall, steps = self.climb(stall, NOW, [79, 80])
        self.assertEqual(steps, [None, "post"])

    def test_r3_p3_a_restart_at_50_min_keeps_the_clock_and_an_idle_queue_restarts_it(self):
        data, fired = {"entries": [], "granted_at": NOW}, {}
        for minute in range(130):
            head = job(1 if minute < 50 else 2, kind="deploy", enqueued=NOW if minute < 50 else NOW + 50 * 60)
            data["entries"] = [head]
            sends, _, _ = self.queue.stalled(data, [head], {head["id"]: "all 1 deploy slots taken"}, 15.0, 100.0, idle, NOW + minute * 60)
            fired.update((label, minute) for label, _ in sends)
        self.assertEqual(fired, {"escalated post": 30, "escalated call": 60, "escalated security": 120})
        late = job(3, kind="deploy", enqueued=NOW + 10 * HOUR)
        data["entries"] = [late]
        self.assertEqual(self.queue.stalled(data, [late], {"j3": "all 1 deploy slots taken"}, 15.0, 100.0, idle, NOW + 10 * HOUR + 60)[0], [])

    def test_r4_a_head_that_never_fits_gets_one_cleanup_and_one_notice_whatever_starts_beside_it(self):
        head = job(1, kind="test", need_gb=60, enqueued=NOW - 600)
        data, now, cleanups, notices = {"entries": [head], "granted_at": NOW - 600}, NOW, 0, []
        for cycle in range(3):
            for _ in range(3):
                sends, clean, _ = self.queue.stalled(data, [head], {"j1": self.queue.Disk("60 GB would cut into the 15 GB floor")},
                                                     15.0, 40.0, idle, now)
                cleanups += clean
                notices += [label for label, _ in sends if label.startswith("noticed")]
                now += 20
            data["granted_at"] = now
            data.pop("stall", None)
            now += 20
        self.assertEqual((cleanups, notices), (1, ["noticed that the head cannot fit"]))
        other = job(2, kind="test", need_gb=60)
        self.assertTrue(self.queue.stalled(data, [other], {"j2": self.queue.Disk("60 GB would cut into the 15 GB floor")},
                                           15.0, 40.0, idle, now)[1])

    def test_the_cleanup_runs_once_per_head_when_disk_alone_blocks_it(self):
        state, clean = self.queue.cleanup_due({}, "j1", True, NOW)
        again = self.queue.cleanup_due(state, "j1", True, NOW + 60)
        fresh = self.queue.cleanup_due(again[0], "j2", True, NOW + 180)
        self.assertEqual((clean, again[1], fresh[1], state["cleaned_at"]), (True, False, True, NOW))
        self.assertFalse(self.queue.cleanup_due({}, "j1", False, NOW)[1])

    def test_stalled_reads_the_store_names_the_head_and_skips_a_hotfix_ahead(self):
        head = job(1926, kind="gui-dind", need_gb=65, enqueued=NOW - 40 * 60)
        verdicts = {"j1926": self.queue.Disk("65 GB would cut into the 15 GB floor"), "j2": "all 1 test slots taken"}
        order = [head, job(2)]
        data = {"entries": [head, job(2)], "granted_at": NOW - 31 * 60}
        text = "kvb-org-queue: no grant for 30 min; head j1926 (gui-dind, work/a) waits: 65 GB would cut into the 15 GB floor"
        notice = ("noticed that the head cannot fit", ["post", (
            f"kvb-org-queue: head j1926 needs 65 GB, max reachable 32 GB after cleanup ({verdicts['j1926']}); operator cleanup needed"
        ), "--to", "Main"])
        self.assertEqual(self.queue.stalled(data, order, verdicts, 15.0, 47.0, idle, NOW),
                         ([("escalated post", ["post", text, "--to", "Main"])], True, None))
        self.assertEqual(self.queue.stalled(data, order, verdicts, 15.0, 47.0, idle, NOW + 60),
                         ([notice], False, "low-risk cleanup ended without a report"))
        self.assertEqual(self.queue.stalled(data, order, verdicts, 15.0, 47.0, idle, NOW + 120), ([], False, None))
        hotfix = {"entries": [head, job(3, status="active", hotfix="main-red", granted=NOW - 9 * HOUR)], "granted_at": NOW - 9 * HOUR}
        self.assertEqual(self.queue.stalled(hotfix, order, verdicts, 15.0, 100.0, idle, NOW)[0], [])
        self.assertEqual(self.queue.stalled({"entries": []}, order, {**verdicts, "j2": None}, 15.0, 100.0, idle, NOW), ([], True, None))
        self.assertEqual(self.queue.stalled({"entries": []}, order, {**verdicts, "j1926": None}, 15.0, 100.0, idle, NOW), ([], False, None))

    def test_r2_a_head_that_cannot_fit_after_the_cleanup_gets_one_notice_per_head(self):
        head = job(1926, kind="gui-dind", need_gb=65, enqueued=NOW - 5 * 60)
        floored = self.queue.Disk("65 GB would cut into the 15 GB floor")
        order, data = [head], {"entries": [head], "granted_at": NOW - 60}
        report = "RESOURCE CLEANUP: freed 1.0 GB (0.0 GB caches), / now 47.0 GB free; 3 commands ok."
        notice = ("noticed that the head cannot fit", [
            "post", f"kvb-org-queue: head j1926 needs 65 GB, max reachable 32 GB after cleanup ({floored}); operator cleanup needed",
            "--to", "Main",
        ])

        def poll(at: float, cleaning: bool, reason: str = floored) -> tuple:
            return self.queue.stalled(
                data, order, {"j1926": reason}, 15.0, 47.0, lambda: (cleaning, [(NOW - 600, "older"), (at - 10, report)]), at
            )

        self.assertEqual(poll(NOW, False), ([], True, None))
        self.assertEqual(poll(NOW + 20, True), ([], False, None))
        self.assertEqual(poll(NOW + 40, False), ([notice], False, f"low-risk cleanup: {report}"))
        self.assertEqual(poll(NOW + 60, False), ([], False, None))
        data["granted_at"] = NOW + 100
        self.assertEqual([poll(NOW + 200, False), poll(NOW + 220, False)], [([], False, None)] * 2)
        data.pop("cleanup")
        self.assertEqual(poll(NOW + 400, False), ([], True, None))
        self.assertEqual(poll(NOW + 420, False, "all 1 gui-dind slots taken"), ([], False, f"low-risk cleanup: {report}"))

    def test_r2_a_cleanup_that_fails_in_the_sandbox_is_logged_once_and_the_queue_keeps_polling(self):
        failed = "RESOURCE CLEANUP: freed 0.0 GB (0.0 GB caches), / now 47.0 GB free; 0 commands ok, failed: exit 1: docker image prune"
        stall, clean = self.queue.cleanup_due({}, "j1", True, NOW)
        lines = []
        for _ in range(3):
            stall, log, _ = self.queue.settle(stall, lambda: (False, [(NOW + 5, failed)]), False)
            lines.append(log)
        self.assertEqual((clean, lines), (True, [f"low-risk cleanup: {failed}", None, None]))
        refused = mock.Mock(side_effect=PermissionError(13, "Permission denied"))
        stall, _ = self.queue.cleanup_due({}, "j1", True, NOW)
        with mock.patch.object(self.queue.watch, "spawn_cleanup", refused):
            stall, started = self.queue.cleaned(stall)
        self.assertEqual(started, "low-risk cleanup did not start: [Errno 13] Permission denied")
        stall, log, notice = self.queue.settle(stall, idle, True)
        self.assertEqual((log, notice, self.queue.settle(stall, idle, True)[1:]), (None, True, (None, False)))
        stamp = 1_800_000_005 * 10**9
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with mock.patch.object(self.queue.watch, "ROOT", root), mock.patch.object(self.queue.watch, "ALERTS", root / "alerts.jsonl"):
                self.assertEqual(self.queue.cleanup_outcome(NOW), (False, []))
                (root / "alerts.jsonl").write_text("\n".join([
                    json.dumps({"id": stamp, "stage": "cleanup", "text": failed}), "{broken",
                    json.dumps({"id": 7, "stage": "stop", "text": "RESOURCE STOP"}),
                ]) + "\n", encoding="utf-8")
                (root / "cleanup.lock").mkdir()
                now = time.time()
                self.assertEqual(self.queue.cleanup_outcome(now), (True, []))
                self.assertEqual(self.queue.cleanup_outcome(now + 3600), (False, [(stamp / 1e9, failed)]))

    def test_act_starts_the_cleanup_and_sends_each_step_with_the_radio_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            seen = Path(tmp, "argv.json")
            fake = Path(tmp, "radio.py")
            fake.write_text(f"import json, sys\njson.dump(sys.argv[1:], open({str(seen)!r}, 'w'))\n", encoding="utf-8")
            spawn = mock.Mock()
            with mock.patch.object(self.queue, "RADIO", fake), mock.patch.object(self.queue.watch, "spawn_cleanup", spawn), \
                    contextlib.redirect_stderr(io.StringIO()) as err:
                stall, started = self.queue.cleaned({"settled": False})
                self.queue.act([("escalated call", self.queue.radio_words("call", "head waits"))], ["low-risk cleanup: x", started], "s1")
                self.queue.act([], [], "s1")
            self.assertEqual(json.loads(seen.read_text(encoding="utf-8")), ["send", "call", "head waits", "--to", "Main", "--session", "s1"])
            spawn.assert_called_once_with("--full")
            self.assertEqual(stall, {"settled": False})
            self.assertEqual(err.getvalue(), (
                "queue: low-risk cleanup: x\nqueue: disk alone blocks the head; low-risk cleanup started\nqueue: escalated call\n"
            ))

    def council_env(self, tmp: str) -> tuple[Path, dict[str, str]]:
        root = Path(tmp).resolve() / "council"
        return root, {"PATH": os.environ["PATH"], "HOME": tmp, "AGENTS_COUNCIL_ROOT": str(root),
                      "AGENTS_COUNCIL_CONFIG": str(Path(tmp, "none.json"))}

    def test_every_step_is_a_command_the_installed_radio_accepts_and_its_mayday_sets_no_silence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, env = self.council_env(tmp)
            with mock.patch.dict(os.environ, env, clear=True), contextlib.redirect_stderr(io.StringIO()) as err:
                for _, step, _ in self.queue.ESCALATION:
                    self.queue.act([(f"escalated {step}", self.queue.radio_words(step, f"kvb-org-queue: stall {step}"))], [], "s1")
            rows = [json.loads(line) for line in (root / "news.jsonl").read_text(encoding="utf-8").splitlines()]
            silent = (root / "radio-silence.json").exists()
        self.assertEqual(err.getvalue().splitlines(), [f"queue: escalated {step}" for _, step, _ in self.queue.ESCALATION])
        self.assertEqual([(row["class"], row["to"], row["text"]) for row in rows], [
            ("post", ["Main"], "kvb-org-queue: stall post"), ("call", ["Main"], "kvb-org-queue: stall call"),
            ("security", [], "kvb-org-queue: stall security"), ("pan-pan", [], "kvb-org-queue: stall pan-pan"),
            ("mayday", [], "kvb-org-queue: stall mayday"),
        ])
        self.assertFalse(silent)

    def test_r3_p2_a_mayday_never_replaces_the_silence_of_another_sender_and_any_silence_stops_grants(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, env = self.council_env(tmp)
            root.mkdir()
            silence, now = root / "radio-silence.json", time.time()
            spoof = {"since": now, "until": now + HOUR, "by": "Operator", "text": "kvb-org-queue: no grant for 1440 min"}
            silence.write_text(json.dumps(spoof), encoding="utf-8")

            def send(*words: str) -> int:
                return subprocess.run(
                    [sys.executable, str(self.queue.RADIO), "send", *words, "--session", "s2"], env=env,
                    stdin=subprocess.DEVNULL, capture_output=True, timeout=60, check=False,
                ).returncode

            codes = [send("mayday", "disk full"), send("mayday", "disk full", "--no-silence"),
                     send("call", "x", "--to", "Main", "--no-silence")]
            kept = json.loads(silence.read_text(encoding="utf-8"))
            with mock.patch.object(self.queue.watch, "ROOT", root), mock.patch.object(self.queue, "SILENCE", silence):
                stops = self.queue.silenced(now)
            silence.unlink()
            quiet = [send("mayday", "disk full", "--no-silence"), silence.exists()]
            send("mayday", "disk full")
            own = json.loads(silence.read_text(encoding="utf-8"))
        self.assertEqual((codes, kept, stops, quiet), ([0, 0, 2], spoof, True, [0, False]))
        self.assertEqual((own["text"], own["by"] != "Operator", own["until"] - own["since"]), ("disk full", True, 7200))


class TestHistory(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.history = _load(HISTORY)

    def learn(self, rows: list[dict]) -> tuple[dict, dict]:
        return self.history.learn(rows, NOW, {"load_limits": {"mem_percent": 80, "cpu_percent": 90},
                                              "light_kinds": ["test-nostack"]})

    def test_signature_names_a_command_apart_from_paths_options_and_variables(self):
        cases = {
            ("make", "-C", "/repo", "-j4", "VAR=1", "compose-deploy", "apps=x"): "make compose-deploy",
            ("/usr/bin/make", "-j", "8", "-f", "Other.mk", "test"): "make test",
            ("make", "-k"): "make",
            ("python3", "/s/kvb-check-gate/scripts/gate.py", "run", "--repo", ".", "--target", "test"): "gate.py run",
            ("/usr/bin/python3.14", "-u", "x.py", "--flag", "sub"): "x.py sub",
            ("python3", "-m", "unittest", "tests.test_queue"): "unittest tests.test_queue",
            ("python3", "-c", "print(1)"): "python3 -c",
            ("bash", "scripts/install.sh"): "install.sh",
            ("python3", "/s/security.py", "--repo", "/w/.worktrees/fix/a", "--base", "HEAD"): "security.py",
            ("docker", "compose", "up", "-d"): "docker compose",
            ("/bin/true",): "true",
        }
        for argv, expected in cases.items():
            with self.subTest(argv=argv):
                self.assertEqual(self.history.signature(list(argv)), expected)

    def test_learn_waits_for_min_runs_inside_the_30_day_window(self):
        four = [history_row(n) for n in range(4)]
        signatures, kinds = self.learn(four)
        self.assertEqual((signatures["test", "make test"]["runs"], signatures["test", "make test"]["need_gb"]), (4, None))
        self.assertEqual((kinds["test"]["runs"], kinds["test"]["limit"]), (4, None))
        stale = history_row(4, end=NOW - self.history.WINDOW_SECONDS - 1)
        self.assertIsNone(self.learn([*four, stale])[0]["test", "make test"]["need_gb"])
        signatures, kinds = self.learn([*four, history_row(4, end=NOW - self.history.WINDOW_SECONDS)])
        self.assertEqual((signatures["test", "make test"]["need_gb"], signatures["test", "make test"]["minutes"]), (2, 10))
        self.assertEqual(kinds["test"]["limit"], 2)

    def test_learn_needs_the_p90_disk_plus_one_gb_and_takes_the_median_minutes(self):
        runs = zip((4, 1, 10, 3, 2), (5, 9, 7, 1, 30))
        rows = [history_row(n, disk_gb=gb, minutes=m) for n, (gb, m) in enumerate(runs)]
        stats = self.learn(rows)[0]["test", "make test"]
        self.assertAlmostEqual(stats["disk_gb"], 7.6)
        self.assertEqual((stats["need_gb"], stats["minutes"]), (9, 7))

    def test_a_signature_learns_per_kind_once_the_kind_has_its_own_runs_and_over_every_kind_until_then(self):
        heavy = [history_row(n, mem_max=60, cpu_max=95, disk_gb=9) for n in range(5)]
        light = [history_row(n + 5, kind="test-nostack", mem_max=21, cpu_max=12, disk_gb=0) for n in range(5)]
        signatures, kinds = self.learn([*heavy, *light])
        footprint, need, tests = self.history.footprint, self.history.need_gb, ("make test",)
        self.assertEqual(footprint("test-nostack", tests, signatures, kinds), {"ram": 1, "cpu": 2})
        self.assertEqual(footprint("test", tests, signatures, kinds), {"ram": 40, "cpu": 85})
        self.assertEqual((need(signatures, kinds, "test-nostack", tests), need(signatures, kinds, "test", tests)), (1, 10))
        self.assertEqual(need(signatures, kinds, "deploy", tests), 10)
        self.assertIsNone(need(signatures, kinds, "test", ("make lint",)))
        other = [history_row(n + 10, kind="test-nostack", signature="true", mem_max=20, cpu_max=10) for n in range(5)]
        signatures, kinds = self.learn([*heavy, *light[:4], *other])
        self.assertEqual(footprint("test-nostack", tests, signatures, kinds), {"ram": 40, "cpu": 85})

    def test_a_shape_below_min_runs_books_the_largest_of_its_kind_and_every_alias_so_it_never_under_reserves(self):
        heavy = [history_row(n, mem_max=60, cpu_max=95) for n in range(2)]
        light = [history_row(n + 2, kind="test-nostack", mem_max=21, cpu_max=12) for n in range(5)]
        lint = [history_row(n + 7, signature="make lint", mem_max=50, cpu_max=60) for n in range(5)]
        signatures, kinds = self.learn([*heavy, *light, *lint])
        self.assertEqual(self.history.footprint("test", ("make test",), signatures, kinds), {"ram": 40, "cpu": 50})
        heavy = [history_row(n, mem_max=60, cpu_max=95) for n in range(5)]
        tiny = [history_row(n + 5, kind="test-nostack", signature="true", mem_max=21, cpu_max=11) for n in range(5)]
        signatures, kinds = self.learn([*heavy, *light[:2], *tiny])
        self.assertEqual(self.history.footprint("test-nostack", ("make test",), signatures, kinds), {"ram": 40, "cpu": 85})

    def test_a_new_signature_without_runs_learns_from_the_rows_older_queues_wrote_under_its_old_signature(self):
        old, new = "core: pytest no:cacheprovider", "core: pytest files=1"
        legacy = [history_row(n, kind="test-nostack", signature=old, mem_max=35, cpu_max=70, disk_gb=4) for n in range(5)]
        tiny = [history_row(n + 5, kind="test-nostack", signature="true", mem_max=21, cpu_max=11, disk_gb=0) for n in range(5)]
        signatures, kinds = self.learn([*legacy, *tiny])
        footprint, need = self.history.footprint, self.history.need_gb
        self.assertEqual(footprint("test-nostack", (new, old), signatures, kinds), {"ram": 15, "cpu": 60})
        self.assertEqual(need(signatures, kinds, "test-nostack", (new, old)), 5)
        self.assertEqual(footprint("test-nostack", (new,), signatures, kinds)["ram"], kinds["test-nostack"]["ram_share"])
        fresh = [history_row(n + 10, kind="test-nostack", signature=new, legacy_signature=old, mem_max=21, cpu_max=12,
                             disk_gb=0) for n in range(5)]
        signatures, kinds = self.learn([*legacy, *tiny, *fresh])
        self.assertEqual(footprint("test-nostack", (new, old), signatures, kinds), {"ram": 1, "cpu": 2})
        self.assertEqual(need(signatures, kinds, "test-nostack", (new, old)), 1)
        self.assertEqual(signatures[self.history.ANY_KIND, old]["runs"], 5)

    def test_a_heavy_kind_never_books_less_than_the_queue_before_the_per_kind_learning_and_a_light_one_may(self):
        gate, plain, suite = "w: gate.py hold", "core: pytest no:cacheprovider", "core: pytest paths=1"
        shared = [history_row(n, signature=gate, mem_max=40, cpu_max=30, disk_gb=2) for n in range(5)]
        shared += [history_row(n + 5, kind="quality-high", signature=gate, mem_max=80, cpu_max=70, disk_gb=9)
                   for n in range(5)]
        diluted = [history_row(n, signature=plain, mem_max=50, cpu_max=40, disk_gb=6) for n in range(5)]
        diluted += [history_row(n + 5, signature="core: make lint", mem_max=25, cpu_max=15, disk_gb=0) for n in range(50)]
        diluted += [history_row(n + 55, kind="test-nostack", signature="core: pytest files=1", legacy_signature=plain,
                                mem_max=21, cpu_max=11, disk_gb=0) for n in range(60)]
        booked_at_7c0872e = [
            (shared, "test", (gate,), {"ram": 60, "cpu": 40}, 10),
            (shared, "quality-high", (gate,), {"ram": 60, "cpu": 40}, 10),
            (diluted, "test", (suite, plain), {"ram": 30, "cpu": 30}, 7),
        ]
        for rows, kind, aliases, old, old_need in booked_at_7c0872e:
            with self.subTest(kind=kind, aliases=aliases):
                signatures, kinds = self.learn(rows)
                for booked in (self.history.footprint, self.history.ceiling):
                    new = booked(kind, aliases, signatures, kinds)
                    self.assertTrue(all(new[resource] >= old[resource] for resource in old), (booked.__name__, new))
                self.assertGreaterEqual(self.history.need_gb(signatures, kinds, kind, aliases), old_need)
        signatures, kinds = self.learn(diluted)
        light = ("core: pytest files=1", plain)
        self.assertEqual(self.history.footprint("test-nostack", light, signatures, kinds), {"ram": 1, "cpu": 1})
        self.assertEqual(self.history.need_gb(signatures, kinds, "test-nostack", light), 1)
        xdist = "core: pytest paths=1 workers=auto"
        signatures, kinds = self.learn([history_row(n, signature=xdist, disk_gb=25) for n in range(5)])
        self.assertEqual(self.history.need_gb(signatures, kinds, "test", (xdist, "core: pytest auto")), 26)
        self.assertIsNone(self.history.need_gb(signatures, kinds, "test", (suite, plain)))

    def test_a_neighbours_cpu_spike_in_one_row_does_not_lift_the_learned_cpu_share(self):
        rows = [*(history_row(n, cpu_before=10, cpu_max=12) for n in range(4)), history_row(4, cpu_before=10, cpu_max=90)]
        signatures, kinds = self.learn(rows)
        self.assertEqual((signatures["test", "make test"]["cpu_share"], kinds["test"]["cpu_share"]), (2, 2))
        self.assertEqual(kinds["test"]["ram_share"], 10)

    def test_learn_fits_the_slot_limit_between_the_median_load_and_the_load_limits(self):
        loads = ((10, 5), (20, 5), (20, 10), (30, 15), (40, 15))
        rows = [history_row(n, mem_before=before, mem_max=before + share) for n, (before, share) in enumerate(loads)]
        kind = self.learn(rows)[1]["test"]
        self.assertEqual((kind["ram_share"], kind["cpu_share"], kind["limit"]), (15, 30, 2))
        idle_cpu = [{**row, "cpu_max": row["cpu_before"]} for row in rows]
        self.assertEqual(self.learn(idle_cpu)[1]["test"]["limit"], 4)
        idle = [{**row, "mem_max": row["mem_before"]} for row in idle_cpu]
        self.assertEqual(self.learn(idle)[1]["test"]["limit"], 60)
        crowded = [history_row(n, mem_before=90, mem_max=95) for n in range(5)]
        self.assertEqual(self.learn(crowded)[1]["test"]["limit"], 1)

    def test_a_light_command_of_a_heavy_kind_and_an_unlearned_one_are_not_booked_at_the_heaviest_share(self):
        light, heavy = {"runs": 5, "ram_share": 3.3, "cpu_share": 4}, {"runs": 5, "ram_share": 42.6, "cpu_share": 93.5}
        signatures = {
            ("test", "skills: make test"): light, (self.history.ANY_KIND, "skills: make test"): light,
            ("test", "gate.py hold"): heavy, (self.history.ANY_KIND, "gate.py hold"): heavy,
        }
        kinds = {"test": {"ram_share": 35.2, "cpu_share": 83.6, "light": False},
                 "test-nostack": {"ram_share": 5.6, "cpu_share": 73.8, "light": True}}
        footprint = self.history.footprint
        self.assertEqual(footprint("test", ("skills: make test",), signatures, kinds), {"ram": 3.3, "cpu": 4})
        self.assertEqual(footprint("test-nostack", ("core: docker build",), signatures, kinds), {"ram": 5.6, "cpu": 73.8})

    def test_footprint_takes_the_learned_signature_else_the_kind_at_least_the_minimum_and_none_for_a_new_kind(self):
        small = [history_row(n, signature="make test", mem_max=25, cpu_max=20) for n in range(5)]
        big = [
            history_row(n + 5, kind="quality-high", signature="make verify-test", mem_max=80, cpu_max=90)
            for n in range(5)
        ]
        idle = [history_row(n + 10, kind="idle", signature="true", mem_max=20, cpu_max=5) for n in range(5)]
        signatures, kinds = self.learn([*small, *big, *idle])
        footprint = self.history.footprint
        self.assertEqual(footprint("test", ("make test",), signatures, kinds), {"ram": 5, "cpu": 10})
        self.assertEqual(footprint("quality-high", ("make verify-test",), signatures, kinds), {"ram": 60, "cpu": 80})
        self.assertEqual(footprint("test", ("make verify-test",), signatures, kinds), {"ram": 60, "cpu": 80})
        self.assertEqual(footprint("test", ("make unseen",), signatures, kinds), {"ram": 5, "cpu": 10})
        self.assertEqual(footprint("idle", ("true",), signatures, kinds), {"ram": 1, "cpu": 1})
        self.assertIsNone(footprint("gui-dind", ("make test-up",), signatures, kinds))
        signatures, kinds = self.learn(small[:4])
        self.assertIsNone(footprint("test", ("make test",), signatures, kinds))

    def test_the_ram_cap_lowers_what_footprint_and_ceiling_book_and_leaves_the_learned_shares_raw(self):
        small = [history_row(n, signature="make test", mem_max=25, cpu_max=20) for n in range(5)]
        big = [history_row(n + 5, kind="quality-high", signature="make verify-test", mem_max=80, cpu_max=90) for n in range(5)]
        cfg = {"load_limits": {"mem_percent": 80, "cpu_percent": 90}, "ram_cap_percent": {"quality-high": 30, "test": 90}}
        signatures, kinds = self.history.learn([*small, *big], NOW, cfg)
        for booked in (self.history.footprint, self.history.ceiling):
            with self.subTest(booked=booked.__name__):
                self.assertEqual(booked("quality-high", ("make verify-test",), signatures, kinds), {"ram": 30, "cpu": 80})
                self.assertEqual(booked("test", ("make test",), signatures, kinds), {"ram": 5, "cpu": 10})
        self.assertEqual((kinds["quality-high"]["ram_share"], signatures["quality-high", "make verify-test"]["ram_share"]), (60, 60))
        self.assertEqual((kinds["quality-high"]["ram_cap"], kinds["test"]["ram_cap"]), (30, 90))
        signatures, kinds = self.learn([*small, *big])
        self.assertIsNone(kinds["quality-high"]["ram_cap"])
        self.assertEqual(self.history.footprint("quality-high", ("make verify-test",), signatures, kinds), {"ram": 60, "cpu": 80})

    def test_slot_limits_take_the_learned_limit_else_the_seed_and_a_smaller_cap(self):
        kinds = {"deploy": {"limit": 3}, "build": {"limit": None}}
        self.assertEqual(self.history.slot_limits(kinds, {"deploy": 2, "swarm": 0, "test": 9}, ["test", "gate"]), {
            "build": (1, "seed"), "deploy": (2, "capped by config"), "gate": (1, "seed"),
            "swarm": (0, "capped by config"), "test": (1, "seed"),
        })
        self.assertEqual(self.history.slot_limits(kinds, {"deploy": 5}, [])["deploy"], (3, "learned"))

    def test_row_keeps_the_extremes_and_floors_the_disk_taken_at_zero(self):
        samples = [
            {"free_gb": 50, "mem": 20, "cpu": 5}, {"free_gb": 47.5, "mem": 60, "cpu": 90},
            {"free_gb": 49, "mem": 30, "cpu": 1},
        ]
        row = self.history.row({"id": "j"}, NOW, NOW + 90, 3, samples, 2)
        self.assertEqual(row, {
            "id": "j", "start": NOW, "end": NOW + 90, "minutes": 1.5, "exit": 3, "free_before_gb": 50,
            "min_free_gb": 47.5, "disk_gb": 2.5, "mem_before": 20, "mem_max": 60, "cpu_before": 5, "cpu_max": 90,
            "concurrent": 2,
        })
        grown = self.history.row({"id": "j"}, NOW, NOW, 0, [samples[0], {**samples[0], "free_gb": 55}], 0)
        self.assertEqual(grown["disk_gb"], 0)

    def test_read_merges_the_files_by_id_and_skips_broken_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            first, second = Path(tmp) / "a.jsonl", Path(tmp) / "b.jsonl"
            first.write_text('{"id": "x", "v": 1}\n{broken\n[1]\n', encoding="utf-8")
            second.write_text('{"id": "x", "v": 2}\n{"id": "y"}\n', encoding="utf-8")
            rows = self.history.read([first, second, Path(tmp) / "missing.jsonl"])
        self.assertEqual(rows, [{"id": "x", "v": 1}, {"id": "y"}])

    def test_eta_adds_the_remaining_and_the_waiting_median_minutes(self):
        signatures = self.learn([history_row(n) for n in range(5)])[0]
        eta = self.history.eta
        tests = ("test", ("make test",))
        self.assertEqual(eta(signatures, [(tests, NOW - 240)], [tests], NOW), 16)
        self.assertEqual(eta(signatures, [(tests, NOW - 900)], [], NOW), 0)
        self.assertEqual(eta(signatures, [], [], NOW), 0)
        self.assertIsNone(eta(signatures, [], [tests, ("test", ("true",))], NOW))
        self.assertEqual(eta(signatures, [], [("deploy", ("make test",))], NOW), 10)


class TestQueueCommands(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name).resolve()
        self.root = self.base / "council"
        self.root.mkdir()
        home = self.base / "home"
        home.mkdir()
        self.history_file = self.root / "queue-history.jsonl"
        self.kept = home / ".local" / "state" / "agents-council" / "queue-history.jsonl"
        self.config = self.base / "config.json"
        self.cfg = {
            "disk": str(self.base),
            "thresholds_gb": {"warn": 0, "stop": 0, "critical": 0},
            "projection_minutes": 30,
            "slot_need_gb": {"test": 0.001, "deploy": 0},
            "slot_limits": {"test": 1, "deploy": 1},
            "load_limits": {"cpu_percent": 101, "mem_percent": 101, "sample_seconds": 0.1},
            "budget_percent": {"ram": 75, "cpu": 100},
            "memory_limits": {stage: OPEN_MEMORY for stage in ("warn", "stop")},
            "heavy_commands": ["^make compose-deploy"],
            "never_block": ["^make compose-down"],
        }
        self.write_config()
        (self.root / "rasci.json").write_text(json.dumps({
            "work/a": {"roles": {}, "status": "running"},
            "work/done": {"roles": {}, "status": "done"},
            "hotfix/fix-1": {"roles": {}, "status": "running", "stage": "pr"},
        }), encoding="utf-8")
        self.env = {
            "PATH": os.environ["PATH"],
            "HOME": str(home),
            "GIT_CEILING_DIRECTORIES": str(self.base.parent),
            "AGENTS_COUNCIL_ROOT": str(self.root),
            "AGENTS_COUNCIL_CONFIG": str(self.config),
            "CLAUDE_PROJECT_DIR": str(self.base / "project"),
        }

    def write_config(self) -> None:
        self.config.write_text(json.dumps(self.cfg), encoding="utf-8")

    def write_store(self, entries: list[dict]) -> None:
        (self.root / "queue.json").write_text(json.dumps({"seq": len(entries), "entries": entries}), encoding="utf-8")

    def entries(self) -> list[dict]:
        return json.loads((self.root / "queue.json").read_text(encoding="utf-8"))["entries"]

    def write_history(self, path: Path, rows: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    def blocked_hold(self, *command: str) -> tuple[subprocess.Popen, Path]:
        err = self.base / "hold.err"
        with open(err, "w", encoding="utf-8") as handle:
            hold = subprocess.Popen(
                [sys.executable, str(QUEUE), "hold", "--kind", "deploy", "--task", "work/a", "--session", "s1",
                 "--", *command],
                cwd=self.base, env=self.env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=handle,
            )
        self.addCleanup(hold.wait)
        self.addCleanup(hold.kill)
        self.wait_for(lambda: "waits at position 1" in err.read_text(encoding="utf-8"))
        return hold, err

    def run_queue(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(QUEUE), *args], cwd=self.base, env=self.env, stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=60, check=False,
        )

    def hook(self, payload: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(QUEUE), "block"], cwd=self.base, env=self.env, input=payload,
            capture_output=True, text=True, timeout=60, check=False,
        )

    def bash(self, command: str) -> int:
        return self.bash_in(command, self.base)

    def bash_in(self, command: str, cwd: Path | None) -> int:
        payload = {"tool_input": {"command": command}, **({} if cwd is None else {"cwd": str(cwd)})}
        return self.hook(json.dumps(payload)).returncode

    def wait_for(self, condition: Callable[[], bool]) -> None:
        deadline = time.monotonic() + 30
        while not condition():
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.05)

    def test_hold_runs_the_command_on_its_grant_passes_its_exit_code_and_leaves(self):
        seen = self.base / "seen.json"
        result = self.run_queue(
            "hold", "--kind", "test", "--task", "work/a", "--hotfix", "fix-1", "--session", "s1", "--",
            sys.executable, "-c", CHILD, str(self.root / "queue.json"), str(seen),
        )
        self.assertEqual((result.returncode, result.stderr), (7, ""))
        [entry] = json.loads(seen.read_text(encoding="utf-8"))
        self.assertEqual(
            [entry[k] for k in ("id", "status", "kind", "task", "need_gb", "hotfix", "workdir", "session")],
            ["test-1", "active", "test", "work/a", 0.001, "fix-1", str(self.base), "s1"],
        )
        signature = f"{self.base.name}: {Path(sys.executable).name} -c"
        self.assertEqual((entry["aliases"], entry["footprint"]), ([signature], None))
        self.assertTrue(0 < entry["granted_mem"] < 100, entry)
        self.assertEqual(self.entries(), [])
        self.assertGreaterEqual(json.loads((self.root / "queue.json").read_text(encoding="utf-8"))["granted_at"], entry["enqueued"])
        [row] = [json.loads(line) for line in self.history_file.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(
            [row[k] for k in ("kind", "signature", "workdir", "exit", "concurrent")],
            ["test", signature, str(self.base), 7, 0],
        )
        self.assertTrue(row["id"].startswith("test-1-"))
        self.assertLessEqual(row["start"], row["end"])
        self.assertEqual(row["disk_gb"], round(max(0.0, row["free_before_gb"] - row["min_free_gb"]), 2))
        self.assertLessEqual(row["mem_before"], row["mem_max"])

    def test_a_command_that_did_no_work_leaves_no_history_row(self):
        result = self.run_queue(
            "hold", "--kind", "test", "--task", "work/a", "--session", "s1", "--", sys.executable, "-c",
            "import sys; sys.exit(75)",
        )
        self.assertEqual(result.returncode, 75)
        self.assertFalse(self.history_file.exists())
        self.assertEqual(self.run_queue("hold", "--kind", "test", "--task", "work/a", "--session", "s1", "--", "false").returncode, 1)
        self.assertEqual(len(self.history_file.read_text(encoding="utf-8").splitlines()), 1)

    def test_hold_runs_without_slot_limits_on_the_seed_limit(self):
        del self.cfg["slot_limits"]
        self.write_config()
        result = self.run_queue("hold", "--kind", "test", "--task", "work/a", "--session", "s1", "--", "true")
        self.assertEqual((result.returncode, result.stderr), (0, ""))

    def test_a_blocked_hold_reports_once_shows_in_list_and_leaves_on_sigterm(self):
        self.cfg["slot_limits"]["deploy"] = 0
        self.write_config()
        hold, err = self.blocked_hold("true")
        listing = self.run_queue("list")
        self.assertEqual(listing.returncode, 0, listing.stderr)
        row = ["1", "deploy-1", "waiting", "deploy", "work/a", "0", "0", "0", str(self.base), "all 0 deploy slots taken"]
        self.assertEqual(listing.stdout.splitlines()[1], "\t".join(row))
        hold.send_signal(signal.SIGTERM)
        self.assertEqual(hold.wait(timeout=30), 128 + signal.SIGTERM)
        self.assertEqual(
            err.read_text(encoding="utf-8"), "queue: deploy-1 waits at position 1: all 0 deploy slots taken\n"
        )
        self.assertEqual(self.entries(), [])

    def test_list_shows_the_host_load_the_holder_saw_at_its_last_poll(self):
        self.cfg["load_limits"]["mem_percent"] = 0
        self.write_config()
        self.blocked_hold("true")
        reason = self.run_queue("list").stdout.splitlines()[1].split("\t")[-1]
        self.assertRegex(reason, r"^RAM \d+ % used \+ \d+ % still to come reach the limit 0 %$")

    def install_host_skills(self) -> Path:
        skills = self.base / "home" / ".agents" / "skills"
        for name in ("kvb-org-queue", "kvb-org-organize", "kvb-org-rasci"):
            shutil.copytree(QUEUE.parents[2] / name, skills / name)
        return skills / "kvb-org-queue" / "scripts" / "queue.py"

    def test_a_hold_on_other_code_than_the_host_install_restarts_with_it_before_any_grant(self):
        host = self.install_host_skills()
        ran = self.base / "ran"
        args = ("hold", "--kind", "test", "--task", "work/a", "--session", "s1", "--", "touch", str(ran))
        same = self.run_queue(*args)
        self.assertEqual((same.returncode, same.stderr), (0, ""))
        self.assertTrue(ran.exists())
        ran.unlink()
        seen = self.base / "argv.json"
        host.write_text(f"import json, sys\njson.dump(sys.argv[1:], open({str(seen)!r}, 'w'))\nsys.exit(9)\n", encoding="utf-8")
        other = self.run_queue(*args)
        self.assertEqual(other.returncode, 9, other.stderr)
        self.assertIn(f"grants nothing on its own code. Restarting this hold with {host};", other.stderr)
        self.assertEqual(json.loads(seen.read_text(encoding="utf-8")), list(args))
        self.assertFalse(ran.exists())
        self.assertEqual(self.entries(), [])

    def test_r4_a_restart_onto_the_installed_code_keeps_the_entry_its_place_and_its_enqueue_time(self):
        host = self.install_host_skills()
        host.write_text(host.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        self.cfg["slot_limits"]["deploy"] = 0
        self.write_config()
        hold, err = self.blocked_hold("true")
        data = json.loads((self.root / "queue.json").read_text(encoding="utf-8"))
        hold.send_signal(signal.SIGTERM)
        self.assertEqual(hold.wait(timeout=30), 128 + signal.SIGTERM)
        self.assertIn("Restarting this hold with", err.read_text(encoding="utf-8"))
        self.assertEqual(([e["id"] for e in data["entries"]], data["seq"], data.get("handover")), (["deploy-1"], 1, {}))

    def test_list_marks_an_entry_on_other_code_than_the_host_install(self):
        queue = _load(QUEUE)
        me, mine = os.getpid(), queue.identity(os.getpid())
        self.install_host_skills()
        self.write_store([
            {**stored(1, "waiting", me, mine, None, None), "code": queue.CODE},
            stored(2, "waiting", me, mine, None, None),
        ])
        reasons = [line.split("\t")[-1] for line in self.run_queue("list").stdout.splitlines()[1:]]
        self.assertEqual(reasons[0], "granted on its next poll")
        self.assertTrue(reasons[1].startswith(f"queue code without a stamp, the host runs {queue.CODE}: "), reasons[1])

    def test_list_names_the_line_the_backfill_and_the_escalated_head(self):
        queue = _load(QUEUE)
        me, mine = os.getpid(), queue.identity(os.getpid())
        self.cfg["slot_limits"] = {"test": 5, "deploy": 1}
        self.write_config()

        def entry(seq: int, status: str, **fields: object) -> dict:
            return {**stored(seq, status, me, mine, me if status == "active" else None, mine if status == "active" else None),
                    "code": queue.CODE, **fields}

        (self.root / "queue.json").write_text(json.dumps({"seq": 4, "entries": [
            entry(1, "waiting", id="deploy-1", kind="deploy", workdir="/core"),
            entry(2, "waiting", workdir="/core"),
            entry(3, "waiting", workdir="/x"),
            entry(4, "active", kind="deploy", workdir="/y", reason="backfilled", footprint={"ram": 0, "cpu": 0}),
        ], "stall": {"grant": 0, "since": 0, "fired": ["post"], "cleaned": False}}), encoding="utf-8")
        listing = self.run_queue("list")
        self.assertEqual(listing.returncode, 0, listing.stderr)
        self.assertEqual({line.split("\t")[1]: line.split("\t")[-1] for line in listing.stdout.splitlines()[1:]}, {
            "test-4": "backfilled", "deploy-1": "escalated post: all 1 deploy slots taken",
            "test-2": "waits in line behind deploy-1", "test-3": "backfilled",
        })

    def test_r5_list_json_gives_each_row_its_class_prio_wsjf_waits_and_the_trace_of_the_pass_that_set_its_reason(self):
        queue = _load(QUEUE)
        me, mine = os.getpid(), queue.identity(os.getpid())
        self.cfg["slot_limits"] = {"test": 5, "deploy": 0}
        self.write_config()
        register = json.loads((self.root / "rasci.json").read_text(encoding="utf-8"))
        register["work/a"].update(prio=2, estimates={"Operator": {"value": 8, "complexity": 2}})
        (self.root / "rasci.json").write_text(json.dumps(register), encoding="utf-8")
        now = time.time()

        def entry(seq: int, status: str, **fields: object) -> dict:
            return {**stored(seq, status, me, mine, me if status == "active" else None, mine if status == "active" else None),
                    "code": queue.CODE, "enqueued": now - 120, **fields}

        polled = ["unranked", "arrival 2", "line /core behind deploy-1"]
        (self.root / "queue.json").write_text(json.dumps({"seq": 3, "entries": [
            entry(1, "waiting", id="deploy-1", kind="deploy", workdir="/core", hotfix="fix-1"),
            entry(2, "waiting", workdir="/core", name="Main", polled=now, reason="waits in line behind deploy-1", trace=polled),
            entry(3, "active", workdir="/y", granted=now - 60, reason="backfilled", trace=["arrival 3"], footprint={"ram": 0, "cpu": 0}),
        ]}), encoding="utf-8")
        listing = self.run_queue("list", "--json")
        self.assertEqual(listing.returncode, 0, listing.stderr)
        rows = json.loads(listing.stdout)
        self.assertEqual([list(row) for row in rows], [[
            "position", "id", "status", "kind", "task", "session", "agent", "class", "prio", "wsjf", "waited_s", "eta_s", "reason", "trace",
        ]] * 3)
        shown = {row["id"]: row for row in rows}
        self.assertEqual([(row["position"], row["id"]) for row in rows], [(None, "test-3"), (1, "deploy-1"), (2, "test-2")])
        self.assertEqual({i: (r["class"], r["prio"], r["wsjf"], r["agent"]) for i, r in shown.items()}, {
            "test-3": ("fix", 2, 4.0, "s1"), "deploy-1": ("hotfix", 2, 4.0, "s1"), "test-2": ("main", 2, 4.0, "Main"),
        })
        self.assertEqual({i: (r["reason"], r["trace"]) for i, r in shown.items()}, {
            "test-3": ("backfilled", ["arrival 3"]),
            "deploy-1": ("all 0 deploy slots taken", ["hotfix first", "rank 0", "arrival 1", "all 0 deploy slots taken"]),
            "test-2": ("waits in line behind deploy-1", polled),
        })
        self.assertTrue(all(118 <= r["waited_s"] <= 180 for i, r in shown.items() if i != "test-3"))
        self.assertEqual((shown["test-3"]["waited_s"], shown["test-2"]["eta_s"]), (60, None))

    def test_a_poll_of_a_stalled_queue_escalates_over_the_radio_once(self):
        self.cfg["slot_limits"]["deploy"] = 0
        self.write_config()
        holds = self.root / "holds"
        holds.mkdir()
        script = "import fcntl, sys, time; h = open(sys.argv[1], 'w'); fcntl.flock(h, fcntl.LOCK_EX); print('locked', flush=True); time.sleep(60)"
        holder = subprocess.Popen([sys.executable, "-c", script, str(holds / "5-6.lock")], stdout=subprocess.PIPE, text=True)
        self.addCleanup(holder.wait)
        self.addCleanup(holder.kill)
        self.addCleanup(holder.stdout.close)
        self.assertEqual(holder.stdout.readline().strip(), "locked")
        now = time.time()
        head = {**stored(1, "waiting", 1, "1", None, None), "id": "deploy-1", "kind": "deploy", "lock": "5-6",
                "workdir": "/core", "enqueued": now - 40 * 60, "polled": now}
        (self.root / "queue.json").write_text(json.dumps({"seq": 1, "entries": [head], "granted_at": now - 31 * 60}),
                                              encoding="utf-8")
        err = self.base / "hold.err"
        with open(err, "w", encoding="utf-8") as handle:
            hold = subprocess.Popen(
                [sys.executable, str(QUEUE), "hold", "--kind", "deploy", "--task", "work/a", "--session", "s1", "--", "true"],
                cwd=self.base, env=self.env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=handle,
            )
        self.addCleanup(hold.wait)
        self.addCleanup(hold.kill)
        self.wait_for(lambda: "waits at position 2" in err.read_text(encoding="utf-8"))
        hold.send_signal(signal.SIGTERM)
        self.assertEqual(hold.wait(timeout=30), 128 + signal.SIGTERM)
        self.assertEqual(err.read_text(encoding="utf-8").splitlines(), [
            "queue: escalated post", "queue: deploy-2 waits at position 2: all 0 deploy slots taken",
        ])
        [row] = [json.loads(line) for line in (self.root / "news.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual((row["class"], row["to"], row["from"], row["text"]), (
            "post", ["Main"], "s1",
            "kvb-org-queue: no grant for 30 min; head deploy-1 (deploy, work/a) waits: all 0 deploy slots taken",
        ))
        data = json.loads((self.root / "queue.json").read_text(encoding="utf-8"))
        self.assertEqual((data["stall"]["fired"], data["cleanup"]["head"], data["cleanup"]["cleaned"]), (["post"], "deploy-1", False))

    def test_r3_any_radio_silence_stops_a_grant_even_one_in_the_queues_own_words(self):
        now = time.time()
        silence = {"since": now, "until": now + 7200, "by": "s1",
                   "text": "kvb-org-queue: no grant for 1440 min; head deploy-9 (deploy, work/a) waits: x"}
        (self.root / "radio-silence.json").write_text(json.dumps(silence), encoding="utf-8")
        hold, err = self.blocked_hold("true")
        hold.send_signal(signal.SIGTERM)
        self.assertEqual(hold.wait(timeout=30), 128 + signal.SIGTERM)
        self.assertEqual(err.read_text(encoding="utf-8"), "queue: deploy-1 waits at position 1: radio silence\n")

    def test_hold_refuses_bad_input_with_exit_2_and_enqueues_nothing(self):
        def hold(*args: str) -> list[str]:
            return ["hold", "--session", "s1", *args]

        cases = (
            ("unknown kind", hold("--kind", "nope", "--task", "work/a", "--", "true"), "kind 'nope'"),
            ("unknown task", hold("--kind", "test", "--task", "work/zzz", "--", "true"), "no open task"),
            ("ended task", hold("--kind", "test", "--task", "work/done", "--", "true"), "no open task"),
            ("missing hotfix row", hold("--kind", "test", "--task", "work/a", "--hotfix", "nope", "--", "true"),
             "hotfix/nope"),
            ("negative need", hold("--kind", "test", "--task", "work/a", "--need-gb", "-1", "--", "true"),
             "--need-gb"),
            ("no command", hold("--kind", "test", "--task", "work/a"), "required"),
        )
        for name, args, message in cases:
            with self.subTest(name):
                result = self.run_queue(*args)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn(message, result.stderr)
        self.config.unlink()
        missing_config = self.run_queue(*hold("--kind", "test", "--task", "work/a", "--", "true"))
        self.assertEqual(missing_config.returncode, 2)
        self.assertIn("no config", missing_config.stderr)
        self.assertFalse((self.root / "queue.json").exists())

    def test_list_drops_entries_of_dead_holders(self):
        queue = _load(QUEUE)
        gone = subprocess.Popen(["true"])
        gone.wait()
        me, mine = os.getpid(), queue.identity(os.getpid())
        self.write_store([
            stored(1, "waiting", gone.pid, "1", None, None),
            stored(2, "waiting", me, "0", None, None),
            stored(3, "active", gone.pid, "1", gone.pid, "1"),
            stored(4, "active", gone.pid, "1", me, mine),
            stored(5, "waiting", me, mine, None, None),
        ])
        listing = self.run_queue("list")
        self.assertEqual(listing.returncode, 0, listing.stderr)
        self.assertEqual([e["id"] for e in self.entries()], ["test-4", "test-5"])
        self.assertEqual(
            [line.split("\t")[:3] for line in listing.stdout.splitlines()[1:]],
            [["run", "test-4", "active"], ["1", "test-5", "waiting"]],
        )

    def test_list_keeps_a_lock_holder_whose_pid_another_namespace_hides(self):
        gone = subprocess.Popen(["true"])
        gone.wait()
        holds = self.root / "holds"
        holds.mkdir(parents=True)
        script = (
            "import fcntl, sys, time; h = open(sys.argv[1], 'w'); fcntl.flock(h, fcntl.LOCK_EX); "
            "print('locked', flush=True); time.sleep(60)"
        )
        holder = subprocess.Popen(
            [sys.executable, "-c", script, str(holds / "5-6.lock")], stdout=subprocess.PIPE, text=True
        )
        self.addCleanup(holder.wait)
        self.addCleanup(holder.kill)
        self.addCleanup(holder.stdout.close)
        self.assertEqual(holder.stdout.readline().strip(), "locked")
        (holds / "1-2.lock").write_text("", encoding="utf-8")
        outside = self.root / "outside.lock"
        outside.write_text("", encoding="utf-8")
        self.write_store([
            {**stored(1, "waiting", gone.pid, "1", None, None), "lock": "5-6"},
            {**stored(2, "waiting", gone.pid, "1", None, None), "lock": "1-2"},
            {**stored(3, "active", gone.pid, "1", gone.pid, "1"), "lock": "3-4"},
            {**stored(4, "waiting", gone.pid, "1", None, None), "lock": "../outside"},
        ])
        listing = self.run_queue("list")
        self.assertEqual(listing.returncode, 0, listing.stderr)
        self.assertEqual([e["id"] for e in self.entries()], ["test-1"])
        self.assertFalse((holds / "1-2.lock").exists())
        self.assertTrue(outside.exists())
        holder.kill()
        holder.wait()
        self.assertEqual(self.run_queue("list").returncode, 0)
        self.assertEqual(self.entries(), [])

    def test_hold_locks_while_waiting_and_cleans_up(self):
        self.cfg["slot_limits"]["deploy"] = 0
        self.write_config()
        hold, _ = self.blocked_hold("true")
        entry = self.entries()[0]
        lock = self.root / "holds" / f"{entry['lock']}.lock"
        with lock.open(encoding="utf-8") as handle, self.assertRaises(BlockingIOError):
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        hold.send_signal(signal.SIGTERM)
        self.assertEqual(hold.wait(timeout=30), 128 + signal.SIGTERM)
        self.assertFalse(lock.exists())
        self.assertEqual(self.entries(), [])

    def test_a_waiting_hold_is_granted_once_the_config_it_waits_on_changes(self):
        self.cfg["slot_limits"]["deploy"] = 0
        self.write_config()
        hold, _ = self.blocked_hold("true")
        self.cfg["slot_limits"]["deploy"] = 1
        self.write_config()
        self.assertEqual(hold.wait(timeout=60), 0)
        self.assertEqual(self.entries(), [])

    def test_fresh_takes_the_new_config_and_keeps_the_last_good_one_on_a_broken_or_partial_file(self):
        queue = _load(QUEUE)
        good = dict(self.cfg)
        new = {**self.cfg, "slot_limits": {"test": 2, "deploy": 2}}
        partial = {key: value for key, value in self.cfg.items() if key != "budget_percent"}
        for loaded, expected in ((new, new), (None, good), (partial, good), ([], good)):
            with self.subTest(loaded=loaded), mock.patch.object(queue.watch, "load_config", return_value=loaded):
                self.assertEqual(queue.fresh(good), expected)
        for error in (ValueError("half-saved"), OSError("gone")):
            with self.subTest(error=error), mock.patch.object(queue.watch, "load_config", side_effect=error):
                self.assertEqual(queue.fresh(good), good)

    def test_a_broken_ram_cap_keeps_the_last_good_config_and_a_hold_refuses_it(self):
        queue = _load(QUEUE)
        good = {**self.cfg, "ram_cap_percent": {"test": 30}}
        capped = {**self.cfg, "ram_cap_percent": {"test": 30, "quality-high": 100}}
        with mock.patch.object(queue.watch, "load_config", return_value=capped):
            self.assertEqual(queue.fresh(good), capped)
        for caps in ({"test": 0}, {"test": 101}, {"test": "30"}, {"test": True}, {"test": float("nan")}, [30]):
            with self.subTest(caps=caps), mock.patch.object(queue.watch, "load_config", return_value={**self.cfg, "ram_cap_percent": caps}):
                self.assertEqual(queue.fresh(good), good)
        self.config.write_text(json.dumps({**self.cfg, "ram_cap_percent": {"test": 101}}), encoding="utf-8")
        result = self.run_queue("hold", "--kind", "test", "--task", "work/a", "--session", "s1", "--", "true")
        self.assertEqual(result.returncode, 2)
        self.assertIn("ram_cap_percent is no {kind: percent above 0 up to 100} map", result.stderr)
        self.assertFalse((self.root / "queue.json").exists())

    def test_hold_takes_the_need_learned_for_its_command_from_both_history_files(self):
        self.cfg["slot_limits"]["deploy"] = 0
        self.write_config()
        now = time.time()
        rows = [
            history_row(n, kind="deploy", signature=f"{self.base.name}: true", end=now, disk_gb=gb)
            for n, gb in enumerate((4, 1, 10, 3, 2))
        ]
        self.write_history(self.history_file, rows[:3])
        self.write_history(self.kept, [{**rows[0], "disk_gb": 100}, *rows[3:]])
        hold, _ = self.blocked_hold("true")
        listing = self.run_queue("list")
        self.assertEqual(listing.returncode, 0, listing.stderr)
        self.assertEqual(listing.stdout.splitlines()[1].split("\t")[5], "9")
        hold.send_signal(signal.SIGTERM)
        self.assertEqual(hold.wait(timeout=30), 128 + signal.SIGTERM)

    def test_list_estimates_from_the_learned_median_minutes(self):
        queue = _load(QUEUE)
        me, mine = os.getpid(), queue.identity(os.getpid())
        now = time.time()
        self.write_history(
            self.history_file, [history_row(n, signature="w: make compose-deploy", end=now) for n in range(5)]
        )
        deploy = {"cmd": "make compose-deploy apps=x", "workdir": "/w"}
        self.write_store([
            {**stored(1, "active", me, mine, me, mine), **deploy, "granted": now - 240},
            {**stored(2, "waiting", me, mine, None, None), **deploy},
            {**stored(3, "waiting", me, mine, None, None), **deploy},
            stored(4, "waiting", me, mine, None, None),
            stored(5, "waiting", me, mine, None, None),
        ])
        listing = self.run_queue("list")
        self.assertEqual(listing.returncode, 0, listing.stderr)
        self.assertEqual([line.split("\t")[7] for line in listing.stdout.splitlines()], [
            "eta_min", "6", "6", "16", "26", "-",
        ])

    def test_history_prints_a_table_per_signature_and_per_kind(self):
        self.cfg["slot_need_gb"]["build"] = 5
        self.cfg["slot_limits"] = {"deploy": 9, "test": 0}
        self.write_config()
        now = time.time()
        deploys = [
            history_row(n, kind="deploy", signature="make compose-deploy", end=now, disk_gb=n + 1, minutes=10 + n,
                        cpu_before=1, cpu_max=21)
            for n in range(5)
        ]
        self.write_history(self.history_file, [*deploys, *(history_row(n, signature="true", end=now) for n in (5, 6))])
        result = self.run_queue("history")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, (
            "| Signature | Kind | Runs | Median min | p90 disk GB | p90 RAM % | Need GB |\n"
            "| --- | --- | --- | --- | --- | --- | --- |\n"
            "| make compose-deploy | deploy | 5 | 12.0 | 4.6 | 10.0 | 6 |\n"
            "| true | test | 2 | - | - | - | - |\n"
            "\n"
            "| Kind | Runs | p90 RAM share % | Median CPU share % | Slot limit | Source |\n"
            "| --- | --- | --- | --- | --- | --- |\n"
            "| build | 0 | - | - | 1 | seed |\n"
            "| deploy | 5 | 10.0 | 20.0 | 5 | learned |\n"
            "| test | 2 | - | - | 0 | capped by config |\n"
        ))

    def after_task(self, status: str) -> dict:
        register = json.loads((self.root / "rasci.json").read_text(encoding="utf-8"))
        register["work/x"] = {"roles": {}, "status": status}
        register["work/a"]["after"] = ["work/done", "work/x"]
        (self.root / "rasci.json").write_text(json.dumps(register), encoding="utf-8")
        return register

    def test_a_stopped_after_task_holds_nothing_back(self):
        self.after_task("stopped")
        result = self.run_queue("hold", "--kind", "deploy", "--task", "work/a", "--session", "s1", "--", "true")
        self.assertEqual((result.returncode, result.stderr), (0, ""))

    def test_a_hold_waits_for_an_after_task_until_it_is_done_or_stopped(self):
        register = self.after_task("running")
        hold, err = self.blocked_hold("true")
        reason = (
            "waits for work/x, an after task of work/a not yet done or stopped; "
            "rasci.py set work/a --drop-after work/x lifts it"
        )
        self.assertEqual(self.run_queue("list").stdout.splitlines()[1].split("\t")[-1], reason)
        hold.send_signal(signal.SIGTERM)
        self.assertEqual(hold.wait(timeout=30), 128 + signal.SIGTERM)
        self.assertEqual(err.read_text(encoding="utf-8"), f"queue: deploy-1 waits at position 1: {reason}\n")
        for status in ("stopped", "done"):
            register["work/x"]["status"] = status
            (self.root / "rasci.json").write_text(json.dumps(register), encoding="utf-8")
            result = self.run_queue("hold", "--kind", "deploy", "--task", "work/a", "--session", "s1", "--", "true")
            self.assertEqual((result.returncode, result.stderr), (0, ""), status)

    def test_hold_with_a_receipt_records_one_only_for_a_green_run_on_an_unchanged_tree(self):
        repo = self.base / "repo"
        repo.mkdir()

        def git(*args: str) -> str:
            return subprocess.run(
                ["git", *args], cwd=repo, env=self.env, capture_output=True, text=True, check=True
            ).stdout.strip()

        git("init", "-q", "-b", "main")
        git("config", "user.email", "t@example.org")
        git("config", "user.name", "t")
        (repo / "a").write_text("a", encoding="utf-8")
        git("add", "a")
        git("commit", "-q", "-m", "a")
        (repo / "staged").write_text("s", encoding="utf-8")
        git("add", "staged")
        (repo / "untracked").write_text("u", encoding="utf-8")
        log = self.base / "gate.log"
        receipts = self.root / "gate-receipts.jsonl"

        def hold(*command: str, receipt: tuple[str, ...] = ("--receipt", "test")) -> subprocess.CompletedProcess:
            return subprocess.run(
                [sys.executable, str(QUEUE), "hold", "--kind", "test", "--task", "work/a", "--session", "s1", *receipt,
                 "--log", str(log), "--", *command],
                cwd=repo, env={**self.env, "INFINITO_TEST_GPU": "false"}, capture_output=True, text=True, timeout=60,
                check=False,
            )

        tree = subprocess.run(
            [sys.executable, str(GATES), "tree", "--worktree", str(repo)], env=self.env, capture_output=True, text=True,
            check=True,
        ).stdout.strip()
        self.assertNotEqual(tree, git("rev-parse", "HEAD^{tree}"))
        green = hold(sys.executable, "-c", "print('ran')")
        self.assertEqual((green.returncode, green.stderr), (0, f"queue: receipt test for tree {tree}\n"))
        self.assertEqual(log.read_text(encoding="utf-8"), "ran\n")
        [row] = [json.loads(line) for line in receipts.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(
            [row[k] for k in ("repo", "tree", "level", "gpu", "log")], [str(repo), tree, "test", "false", str(log)]
        )
        self.assertEqual(hold("false").returncode, 1)
        changed = hold("touch", str(repo / "made"))
        self.assertEqual(changed.returncode, 0)
        self.assertIn(f"queue: the command changed the tree from {tree} to ", changed.stderr)
        self.assertEqual(len(receipts.read_text(encoding="utf-8").splitlines()), 1)
        refused = hold("true", receipt=())
        self.assertEqual(refused.returncode, 2)
        self.assertIn("--log goes with --receipt", refused.stderr)

    def test_cancel_removes_only_the_callers_waiting_entry(self):
        queue = _load(QUEUE)
        me, mine = os.getpid(), queue.identity(os.getpid())
        self.write_store([stored(1, "waiting", me, mine, None, None), stored(2, "active", me, mine, me, mine)])
        self.assertEqual(self.run_queue("cancel", "test-1", "--session", "s2").returncode, 2)
        self.assertEqual(self.run_queue("cancel", "test-2", "--session", "s1").returncode, 2)
        result = self.run_queue("cancel", "test-1", "--session", "s1")
        self.assertEqual((result.returncode, result.stdout), (0, "cancelled test-1\n"))
        self.assertEqual([e["id"] for e in self.entries()], ["test-2"])

    def test_block_allows_everything_without_queue_enforce(self):
        self.assertEqual(self.bash("make compose-deploy"), 0)
        self.cfg["queue_enforce"] = False
        self.write_config()
        self.assertEqual(self.bash("make compose-deploy"), 0)

    def test_list_and_hold_on_a_broken_config_warn_and_use_the_shipped_default(self):
        self.config.write_text(json.dumps(self.cfg)[:-1] + ",}", encoding="utf-8")
        listing = self.run_queue("list")
        self.assertEqual(listing.returncode, 0, listing.stderr)
        self.assertIn("built-in defaults", listing.stderr)
        held = self.run_queue("hold", "--kind", "nosuch", "--task", "work/a", "--session", "s1", "--", "true")
        self.assertEqual(held.returncode, 2, held.stderr)
        self.assertIn("built-in defaults", held.stderr)
        self.assertIn("'nosuch' is not in slot_need_gb", held.stderr)
        for done in (listing, held):
            self.assertNotIn("Traceback", done.stderr)

    def test_a_broken_config_falls_back_to_defaults_so_light_commands_pass_and_heavy_ones_stay_refused(self):
        self.cfg["queue_enforce"] = True
        good = json.dumps(self.cfg)

        def text(content: str) -> Callable[[], None]:
            return lambda: self.config.write_text(content, encoding="utf-8")

        shapes = {
            "comma": text(good[:-1] + ",}"), "empty": text(""), "list": text("[]"),
            "string enforce": text(json.dumps({**self.cfg, "queue_enforce": "yes"})),
            "empty-matching heavy": text(json.dumps({**self.cfg, "heavy_commands": [""]})),
            "dot heavy": text(json.dumps({**self.cfg, "heavy_commands": ["."]})),
            "word-boundary heavy": text(json.dumps({**self.cfg, "heavy_commands": [r"\b"]})),
            "dot never_block": text(json.dumps({**self.cfg, "never_block": ["."]})),
            "dangling link": lambda: self.config.symlink_to(self.base / "absent.json"),
            "link loop": lambda: self.config.symlink_to(self.config),
            "directory": lambda: self.config.mkdir(),
        }
        for name, make in shapes.items():
            with self.subTest(config=name):
                if self.config.is_dir() and not self.config.is_symlink():
                    self.config.rmdir()
                self.config.unlink(missing_ok=True)
                make()
                passed = self.hook(json.dumps({"tool_input": {"command": "ls -la"}}))
                self.assertEqual(passed.returncode, 0, passed.stderr)
                self.assertIn(str(self.config), passed.stderr)
                self.assertIn("built-in defaults", passed.stderr)
                self.assertEqual(self.bash("make test"), 2)
                live = ("make compose-deploy ROLE=x", "docker build .", "docker pull nginx", "make swarm-deploy", "make roundtrip",
                        "make worktree-up")
                for command in live if name in ("comma", "directory") else live[:1]:
                    self.assertEqual(self.bash(command), 2, command)

    def test_block_with_queue_enforce_refuses_heavy_commands_outside_the_queue(self):
        self.cfg["queue_enforce"] = True
        self.write_config()
        refused = self.hook(json.dumps({"tool_input": {"command": "make compose-deploy apps=x"}}))
        self.assertEqual(refused.returncode, 2)
        self.assertIn("queue.py hold --kind <kind> --task <register task> -- <command>", refused.stderr)
        self.assertEqual(self.bash("python3 skills/kvb-check-gate/scripts/gate.py run --repo . --target test"), 2)
        for command in ("make -j4 compose-deploy apps=x", "make 'compose-deploy'", "cd x && make compose-deploy"):
            with self.subTest(command=command):
                self.assertEqual(self.bash(command), 2)
        for command in (
            "python3 /x/queue.py hold --kind deploy --task work/a -- make compose-deploy",
            "make compose-down",
            "ls",
            'git commit -m "make compose-deploy"',
        ):
            with self.subTest(command=command):
                self.assertEqual(self.bash(command), 0)
        for payload in ("not json", json.dumps({"tool_input": ["make test"]})):
            with self.subTest(payload=payload):
                crashed = self.hook(payload)
                self.assertEqual(crashed.returncode, 2, crashed.stderr)
                self.assertIn("counts as heavy", crashed.stderr)
        self.assertEqual(self.bash("CARGO_BUILD_JOBS=² cargo build ; make test"), 2)
        self.config.unlink()
        self.assertEqual(self.bash("make compose-deploy"), 0)

    def test_block_with_queue_enforce_refuses_builds_installs_and_full_suites_by_itself(self):
        self.cfg["queue_enforce"] = True
        self.cfg["heavy_commands"] = []
        self.write_config()
        for name in ("tests/test_queue.py", "tests/test_watch.py", "sub/tests/test_queue.py", "tree/a/test_main.py",
                     "tree/b/test_main.py"):
            (self.base / name).parent.mkdir(parents=True, exist_ok=True)
            (self.base / name).write_text("", encoding="utf-8")
        for command in (
            "python3 -m unittest discover -s tree -p test_main.py",
            "python3 -m unittest discover -s tests -p test_gone.py",
            "python3 -m unittest discover -s . -p test_queue.py",
            "python3 -m unittest discover tree test_main.py",
            "docker compose up -d --build",
            "docker compose -f x.yml build web",
            "docker-compose up --build",
            "make install",
            "make -C core verify-test",
            "pytest tests/",
            "python3 -m pytest -q",
            ".venv/bin/pytest tests/lint tests/unit",
            "pytest tests/a.py tests/b.py",
            "python3 -m unittest discover -s tests",
            "python3 -m unittest discover -s tests -p 'test_*.py'",
            "pytest tests/x.py tests/lint",
            "pytest tests/lint --ignore=tests/lint/y.py",
            "python3 -m unittest",
            "make -j4 install",
            "make VAR=x install",
            "cd core && env A=1 timeout 600 python3 -m pytest -q 2>&1 | tee /tmp/log",
            "bash -c 'pytest tests/'",
            "pytest tests/  # queue.py hold",
            "python3 /x/queue.py hold --kind test --task work/a -- true & pytest tests/",
            "make compose-down; make install",
            "uv run pytest tests/",
            "coverage run -m pytest",
            "python3 -mpytest tests/",
            "python3 -X dev -m pytest",
            "timeout -s KILL 900 pytest tests/",
            "sudo -u nobody pytest tests/",
            "env -u FOO pytest",
            "{ pytest tests/; }",
            "! pytest tests/",
            "if pytest tests/; then echo ok; fi",
            "echo `pytest tests/`",
            "bash -c -- 'pytest tests/'",
            "bash <<'EOF'\npytest tests/\nEOF",
            'OUT="$(pytest tests/ 2>&1)"',
            'echo "r: $(make install)"',
            "cat <<EOF\n`make install`\nEOF",
            "uv run --extra dev pytest tests/",
            "uv run --with pytest-xdist pytest -n 8 tests/",
            "coverage run --source pkg -m pytest tests/",
            "poetry -C core run pytest tests/",
            "python3 -m coverage run -m pytest tests/",
            "uvx pytest tests/",
            "uv tool run pytest tests/",
            "time -p pytest tests/",
            "/usr/bin/time -v pytest tests/",
            "/usr/bin/time -f %M make install",
            "make 2>&1 install",
            ">/tmp/log pytest tests/",
            "2>/dev/null make install",
            "pytest tests/test_watch.py 2>/dev/null tests/",
            "make compose-down install",
            "make -C core compose-down verify-test",
            "make --directory core install",
            "command pytest tests/",
            "command -p pytest tests/",
            "command make install",
            "env -S 'pytest tests/'",
            "bash -Ec 'pytest tests/'",
            "exec -a x pytest tests/",
            "sudo --user root pytest tests/",
            "env $(printenv | grep -o -E '^INFINITO_[A-Z0-9_]+' | sed 's/^/-u /') -C /x python3 -m pytest tests/",
            "env $(cat .env) -u X make install",
            "sudo -u $(id -un) -- pytest tests/",
            "timeout --signal=$(echo KILL) 900 pytest tests/",
            "sudo --chdir /x pytest tests/",
            "sudo bash <<'EOF'\npytest tests/\nEOF",
            "bash -s <<'END-MSG'\nmake install\nEND-MSG",
            "out=$(bash <<'EOF'\nmake install\nEOF\n)",
            "bash -c 'bash <<EOF\nmake install\nEOF\n'",
            "bash <<'A'\nbash <<'B'\nmake install\nB\nA",
            "bash -euo pipefail <<'EOF'\nmake test\nmake install\nEOF",
            "bash -o pipefail <<'EOF'\npytest tests/\nEOF",
            "bash -s -- one <<'EOF'\nmake install\nEOF",
            "bash --rcfile x <<'EOF'\nmake install\nEOF",
            "make -Cinfinito install",
            "make -Oline install",
            "bash <<'EOF'\nmake install \ud800\nEOF",
        ):
            with self.subTest(command=command):
                self.assertEqual(self.bash(command), 2)
        for command in (
            "docker compose up -d",
            "docker compose ps",
            "make install-skills",
            "pytest tests/unit/test_x.py",
            "python3 -m pytest tests/unit/test_x.py::TestA -q",
            "pip install pytest",
            "python3 -m unittest discover -s tests -p test_queue.py",
            "python3 -m unittest tests.test_queue",
            "python3 /x/queue.py hold --kind test --task work/a -- pytest tests/",
            'pytest "tests/unit/test_x.py"',
            "python3 -m unittest discover -s tests -p 'test_queue.py'",
            "env -C sub python3 -m unittest discover -s tests -p test_queue.py",
            f"env --chdir={self.base / 'sub'} python3 -m unittest discover -s tests -p 'test_q*.py'",
            "grep -rn pytest tests/",
            "which pytest",
            "pytest --version",
            "pytest tests/unit/test_x.py -p no:cacheprovider 2>&1 | tee /tmp/log",
            "command -v pytest",
            "make -n install",
            "cat <<'EOF'\npytest tests/\nEOF",
            "pytest >/tmp/out.log tests/test_watch.py",
            "git commit -m \"$(cat <<'EOF'\nfix: run `make install` once\nEOF\n)\"",
            "gh pr create --body-file - <<'EOF'\nruns `make verify-test`\nEOF",
            "echo '$(make install)'",
            "uv pip install pytest",
            "command -V pytest",
            "time pytest tests/unit/test_x.py",
            "docker compose -f compose.yml -f build/compose/runner-mirror.override.yml config --services",
            "docker compose --project-directory build up -d",
            'echo "see \\`make install\\` and \\$(make install) docs"',
            "pytest -n auto --dist loadscope tests/x.py",
            "pytest --cov src --timeout 30 tests/x.py",
            "cat > /tmp/run.sh <<'EOF'\npytest tests/\nEOF",
            "gh pr create --title \"fix(bash): quoting\" --body \"$(cat <<'EOF'\nruns `make install`\nEOF\n)\"",
            "ls # it's $(make install)",
            "make -nC core install",
            "make -kn install",
            "python3 /x/queue.py hold --kind test --task work/a -- bash <<'EOF'\nmake install\nEOF",
            "python3 /x/queue.py hold --kind test --task work/a -- bash -c \"$(cat <<'EOF'\nmake install\nEOF\n)\"",
            "cat <<'END-MSG'\nmake install\nEND-MSG",
            "cat <<\\EOF\n$(make install)\nEOF",
            "pytest --numprocesses 4 tests/x.py",
            "pytest tests/lint --collect-only",
            "bash script.sh <<'EOF'\nmake install\nEOF",
            "out=$(cat <<'EOF'\nmake install\nEOF\n)",
            "echo kvbheredoc1 kvbheredoczz",
            "cd sub && python3 -m unittest discover -s . -p test_queue.py",
        ):
            with self.subTest(command=command):
                self.assertEqual(self.bash(command), 0)
        self.assertEqual(self.bash_in("python3 -m unittest discover -s tests -p 'test_*.py'", self.base / "sub"), 0)
        self.assertEqual(self.bash_in("python3 -m unittest discover -s tree -p test_main.py", None), 0)

    def test_block_matches_a_config_regex_on_the_wrapped_program_too(self):
        self.cfg["queue_enforce"] = True
        self.cfg["heavy_commands"] = [r"^docker compose up"]
        self.write_config()
        for command in ("timeout 900 docker compose up -d", "sudo docker compose up -d", "docker compose up -d"):
            with self.subTest(command=command):
                self.assertEqual(self.bash(command), 2)
        self.assertEqual(self.bash("docker compose ps"), 0)

    def test_a_queue_grant_counts_a_live_admit_record_and_ignores_an_expired_one(self):
        def admitted(expires: float) -> None:
            (self.root / "queue.json").write_text(
                json.dumps({"seq": 0, "entries": [], "admits": [{"ram": 300, "expires": expires}]}), encoding="utf-8"
            )

        admitted(time.time() + 300)
        _, err = self.blocked_hold("true")
        self.assertRegex(err.read_text(encoding="utf-8"), r"RAM \d+ % used \+ 300 % still to come reach the limit 101 %")
        admitted(time.time() - 1)
        result = self.run_queue("hold", "--kind", "deploy", "--task", "work/a", "--session", "s2", "--", "true")
        self.assertEqual((result.returncode, result.stderr), (0, ""))

    def test_a_light_kind_refuses_a_heavy_command_names_the_test_kind_and_enqueues_nothing(self):
        self.cfg["slot_need_gb"] |= {"test-nostack": 0, "quick": 0}
        self.cfg["light_kinds"] = ["quick"]
        self.write_config()
        (self.base / "tests" / "e2e").mkdir(parents=True)
        (self.base / "tests" / "e2e" / "test_orchestrator_e2e.py").write_text("", encoding="utf-8")
        for kind, command, shown in (
            ("test-nostack", ("python", "-m", "unittest"), "python -m unittest"),
            ("test-nostack", ("pytest", "tests/e2e/test_orchestrator_e2e.py"), "pytest tests/e2e/test_orchestrator_e2e.py"),
            ("quick", ("bash", "-c", "make test"), "bash -c 'make test'"),
            ("quick", ("python3", "gate.py", "run", "--target", "test-unit"), "python3 gate.py run --target test-unit"),
        ):
            with self.subTest(kind=kind, command=command):
                result = self.run_queue("hold", "--kind", kind, "--task", "work/a", "--session", "s1", "--", *command)
                self.assertEqual(result.returncode, 2)
                self.assertIn(f"the light kind {kind} skips every reservation", result.stderr)
                self.assertIn(f"run `queue.py hold --kind test --task <register task> -- {shown}`", result.stderr)
                self.assertFalse((self.root / "queue.json").exists())
        light = self.run_queue("hold", "--kind", "test-nostack", "--task", "work/a", "--session", "s1", "--", "true")
        self.assertEqual((light.returncode, light.stderr), (0, ""))

    def test_hold_refuses_a_config_without_the_budget_or_the_memory_limits(self):
        for key, cfg in (
            ("budget_percent", {k: v for k, v in self.cfg.items() if k != "budget_percent"}),
            ("memory_limits", {k: v for k, v in self.cfg.items() if k != "memory_limits"}),
            ("budget_percent.cpu", {**self.cfg, "budget_percent": {"ram": 75}}),
            ("budget_percent.ram", {**self.cfg, "budget_percent": {"ram": "75", "cpu": 100}}),
            ("budget_percent.cpu", {**self.cfg, "budget_percent": {"ram": 75, "cpu": float("nan")}}),
            ("memory_limits.warn.container_swap_gb", {**self.cfg, "memory_limits": {
                "warn": {k: v for k, v in OPEN_MEMORY.items() if k != "container_swap_gb"}, "stop": OPEN_MEMORY,
            }}),
        ):
            with self.subTest(key=key):
                self.config.write_text(json.dumps(cfg), encoding="utf-8")
                result = self.run_queue("hold", "--kind", "test", "--task", "work/a", "--session", "s1", "--", "true")
                self.assertEqual(result.returncode, 2)
                self.assertIn(f"lacks {key};", result.stderr)
                self.assertFalse((self.root / "queue.json").exists())

    def test_block_holds_a_held_command_to_the_bash_rules_of_the_settings(self):
        project = self.base / "project"
        (project / ".claude").mkdir(parents=True)
        (project / ".claude" / "settings.json").write_text(
            json.dumps({"permissions": {"ask": ["Bash(docker build:*)"]}}), encoding="utf-8"
        )
        user = Path(self.env["HOME"]) / ".claude"
        user.mkdir()
        (user / "settings.json").write_text(
            json.dumps({"permissions": {"allow": ["Bash"], "deny": ["Bash(git push *)"]}}), encoding="utf-8"
        )
        self.env["CLAUDE_PROJECT_DIR"] = str(project)
        hold = "python3 /x/queue.py hold --kind deploy --task work/a "
        for command in (hold + "-- docker build -t 'a b' .", hold + "-- nice -n 5 docker build ."):
            with self.subTest(command=command):
                asked = self.hook(json.dumps({"tool_input": {"command": command}}))
                self.assertEqual(asked.returncode, 0)
                self.assertEqual(json.loads(asked.stdout)["hookSpecificOutput"]["permissionDecision"], "ask")
        for command in (
            hold + "-- git push origin main",
            hold + "git push",
            hold + "-- git push origin main # don't",
            hold + "-- timeout 60 git push",
            hold + "-- true; " + hold + "-- git push origin main",
            'python3 "/x/queue.py" hold --kind deploy --task work/a -- git push origin main',
            'python3 /x/queue.py "hold" --kind deploy --task work/a -- git push origin main',
            "python3 /x/queue.p''y ho''ld --kind deploy --task work/a -- git push origin main",
            "python3 /x/queue.py \\\nhold --kind deploy --task work/a -- git push origin main",
            "curl -s http://x/#top && " + hold + "-- git push origin main",
            "true a#b && " + hold + "-- git push origin main # it's",
            "echo '#' && " + hold + "-- git push origin main",
            "echo \\# x && " + hold + "-- git push origin main",
        ):
            with self.subTest(command=command):
                denied = self.hook(json.dumps({"tool_input": {"command": command}}))
                self.assertEqual(denied.returncode, 2)
                self.assertIn("deny rule", denied.stderr)
        for command in (
            hold + "-- make test",
            hold + "-- docker buildx ls",
            "docker build .",
            "git push",
            "# " + hold + "-- git push origin main",
        ):
            with self.subTest(command=command):
                allowed = self.hook(json.dumps({"tool_input": {"command": command}}))
                self.assertEqual((allowed.returncode, allowed.stdout), (0, ""))

    def test_block_refuses_a_hold_it_cannot_check(self):
        hold = "python3 /x/queue.py hold --kind deploy --task work/a -- "
        unchecked = {"unbalanced quote": (hold + "echo 'x", self.env)}
        broken = self.base / "project" / ".claude"
        broken.mkdir(parents=True)
        (broken / "settings.json").write_text("{", encoding="utf-8")
        unchecked["broken settings"] = (hold + "make test", self.env)
        unchecked["no project dir"] = (
            hold + "make test", {k: v for k, v in self.env.items() if k != "CLAUDE_PROJECT_DIR"}
        )
        for name, (command, env) in unchecked.items():
            with self.subTest(name=name):
                result = subprocess.run(
                    [sys.executable, str(QUEUE), "block"], cwd=self.base, env=env, check=False,
                    input=json.dumps({"tool_input": {"command": command}}), capture_output=True, text=True,
                )
                self.assertEqual(result.returncode, 2)
                self.assertIn("cannot check the held command", result.stderr)
        self.assertEqual(self.bash("ls"), 0)
        self.assertEqual(self.bash("echo it's"), 0)

    def test_hold_creates_no_lock_in_a_planted_holds_directory(self):
        victims = self.base / "victims"
        victims.mkdir()
        (self.root / "holds").symlink_to(victims)
        seen = self.base / "seen.txt"
        listing = "import os, sys; open(sys.argv[2], 'w').write(repr(os.listdir(sys.argv[1])))"
        result = self.run_queue(
            "hold", "--kind", "test", "--task", "work/a", "--session", "s1", "--",
            sys.executable, "-c", listing, str(victims), str(seen),
        )
        self.assertEqual(seen.read_text(encoding="utf-8") if seen.exists() else "[]", "[]")
        self.assertEqual(os.listdir(victims), [])
        self.assertNotEqual(result.returncode, 0)

    def test_list_unlinks_no_lock_in_a_planted_holds_directory(self):
        victims = self.base / "victims"
        victims.mkdir()
        (victims / "1-2.lock").write_text("", encoding="utf-8")
        (self.root / "holds").symlink_to(victims)
        gone = subprocess.Popen(["true"])
        gone.wait()
        self.write_store([{**stored(1, "waiting", gone.pid, "1", None, None), "lock": "1-2"}])
        self.run_queue("list")
        self.assertEqual(os.listdir(victims), ["1-2.lock"])

    def test_the_store_lock_creates_no_file_through_a_planted_name(self):
        created = self.base / "created"
        (self.root / "queue.lock").symlink_to(created)
        result = self.run_queue("list")
        self.assertFalse(created.exists())
        self.assertNotEqual(result.returncode, 0)

    def test_hold_appends_no_history_row_through_a_planted_name(self):
        victim = self.base / "victim"
        victim.write_text("keep\n", encoding="utf-8")
        self.history_file.symlink_to(victim)
        result = self.run_queue("hold", "--kind", "test", "--task", "work/a", "--session", "s1", "--", "true")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("no history row", result.stderr)
        self.assertEqual(victim.read_text(encoding="utf-8"), "keep\n")

    def test_a_council_root_others_can_write_stops_commands_but_not_the_hook(self):
        self.root.chmod(0o777)
        refused = self.run_queue("list")
        self.assertEqual(refused.returncode, 2)
        self.assertIn("cannot write", refused.stderr)
        hook = self.hook(json.dumps({"tool_input": {"command": "make compose-deploy"}}))
        self.assertEqual(hook.returncode, 0)
        self.assertIn("council hooks stay off", hook.stdout)


if __name__ == "__main__":
    unittest.main()
