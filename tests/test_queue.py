"""Exercise the kvb-org-queue grant order, its history learning and its hold, list, history, cancel and block commands."""

from __future__ import annotations

import fcntl
import importlib.util
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
NOW = 1_800_000_000.0
HOUR = 3600
OPEN_MEMORY = {"available": -1, "swap_free": -1, "psi_full": 1000, "container_swap_gb": 1e9}
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


def stored(seq: int, status: str, pid: int, pid_start: str | None, child: int | None,
           child_start: str | None) -> dict:
    return {
        "id": f"test-{seq}", "seq": seq, "kind": "test", "task": "work/a", "need_gb": 0, "hotfix": None,
        "workdir": f"/w{seq}", "session": "s1", "name": "s1", "pid": pid, "pid_start": pid_start,
        "child": child, "child_start": child_start, "status": status, "enqueued": time.time(),
        "granted": time.time() if status == "active" else None, "cmd": "true",
    }


class TestEvaluate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.queue = _load(QUEUE)

    def decide(self, entries: list[dict], **overrides: object) -> dict:
        footprints = {e["id"]: {"ram": 0, "cpu": 0} for e in entries} | overrides.pop("footprints", {})
        return self.queue.evaluate(entries, **{**BASE, "footprints": footprints, **overrides})

    def test_the_budget_refuses_a_job_whose_share_would_pass_it_and_reserves_it(self):
        running = job(1, kind="test", status="active")
        candidate = job(2, kind="gui-dind", workdir="/x")
        small = job(3, task="work/b", workdir="/y")
        shares = {"j1": {"ram": 60, "cpu": 40}, "j2": {"ram": 30, "cpu": 20}, "j3": {"ram": 10, "cpu": 5}}
        verdicts = self.decide([running, candidate, small], slot_limits={"test": 5, "gui-dind": 1}, footprints=shares)
        self.assertEqual(verdicts["j2"], "RAM 60 % in use or reserved + 30 % > budget 75 %; reserved")
        self.assertEqual(verdicts["j3"], "RAM 90 % in use or reserved + 10 % > budget 75 %; reserved")
        unbounded = {"ram": 1000, "cpu": 1000}
        self.assertEqual(
            self.decide([running, candidate, small], slot_limits={"test": 5, "gui-dind": 1}, footprints=shares, budget=unbounded),
            {"j2": None, "j3": None},
        )

    def test_a_job_alone_always_fits_and_cpu_counts_like_ram(self):
        alone = self.decide([job(1)], footprints={"j1": {"ram": 90, "cpu": 150}})
        self.assertEqual(alone, {"j1": None})
        busy = self.decide([job(1, status="active"), job(2)], footprints={"j1": {"ram": 1, "cpu": 70}, "j2": {"ram": 1, "cpu": 40}})
        self.assertEqual(busy, {"j2": "CPU 70 % in use or reserved + 40 % > budget 100 %; reserved"})

    def test_a_share_beyond_the_budget_runs_only_alone_even_beside_a_job_of_no_share(self):
        whole = {"ram": 80, "cpu": 1}
        beside = self.decide([job(1, status="active"), job(2)], footprints={"j1": {"ram": 0, "cpu": 0}, "j2": whole})
        self.assertEqual(beside, {"j2": "RAM 0 % in use or reserved + 80 % > budget 75 %; reserved"})
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
        self.assertEqual(self.queue.pending_ram([young, overshooting, old, fresh], "j2", NOW, signatures, kinds), 30 + 10 + 25)
        undated = {k: v for k, v in old.items() if k != "granted"}
        self.assertEqual(self.queue.pending_ram([undated, fresh], "j2", NOW, signatures, kinds), 10 + 25)
        unknown = {**job(3, kind="new"), **cmd, "cmd": "new"}
        self.assertEqual(self.queue.pending_ram([unknown], "j3", NOW, signatures, kinds), 30)

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
        self.assertEqual(self.queue.pending_ram([running], "j1", NOW, signatures, kinds), 12 + 12)

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

    def test_an_exclusive_entry_kept_out_by_a_running_job_holds_back_lower_non_light_entries(self):
        gates = {
            "exclusive": {"quality-high"}, "light": {"test-nostack"},
            "slot_limits": {"quality-high": 1, "iteration": 2, "test-nostack": 2},
        }
        running = job(1, kind="iteration", status="active")
        gate, deploy, light = job(2, kind="quality-high"), job(3, kind="iteration", task="work/b"), job(4, kind="test-nostack", task="work/c")
        self.assertEqual(self.decide([running, gate, deploy, light], **gates), {
            "j2": "quality-high runs only beside test-nostack, but iteration runs",
            "j3": "waits behind j2, which needs the host beside light kinds only",
            "j4": None,
        })
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

    def test_disk_reservation_keeps_smaller_jobs_from_starving_a_big_one(self):
        big, small = job(1, need_gb=50), job(2, task="work/b", need_gb=5)
        verdicts = self.decide([big, small], free_gb=40.0)
        self.assertEqual(verdicts["j1"], "50 GB would cut into the 10 GB floor; reserved")
        self.assertEqual(verdicts["j2"], "5 GB would cut into the 10 GB floor; reserved")
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
        self.assertEqual(verdicts, {"j2": "/w runs another job", "j3": None, "j4": "/x runs another job"})

    def test_a_hotfix_the_host_load_holds_back_holds_back_every_entry_after_it_and_a_normal_one_does_not(self):
        load = "RAM 55 % used + 42 % still to come reach the limit 90 %"
        hotfix, light = job(1, hotfix="main-red"), job(2, task="work/b")
        self.assertEqual(
            self.decide([hotfix, light], loaded={"j1": load}),
            {"j1": load, "j2": "waits behind hotfix j1, which the host load holds back"},
        )
        self.assertEqual(self.decide([job(1), light], loaded={"j1": load}), {"j1": load, "j2": None})
        self.assertEqual(self.decide([hotfix, light]), {"j1": None, "j2": None})

    def test_with_no_job_active_a_head_the_host_load_alone_keeps_out_reserves_nothing_and_with_one_active_it_does(self):
        load = "RAM 55 % used + 41 % still to come reach the limit 90 %"
        head, twin = job(1, kind="quality-high"), job(2, kind="quality-high", task="work/b")
        gate, light = job(3, task="work/b"), job(4, kind="test-nostack", task="work/c")
        shares = {"j1": {"ram": 41, "cpu": 62}, "j2": {"ram": 41, "cpu": 62}, "j3": {"ram": 20, "cpu": 40}, "j4": {"ram": 6, "cpu": 40}}
        rules = {"slot_limits": {"quality-high": 1, "test": 5, "test-nostack": 6}, "exclusive": {"quality-high", "test"}, "light": {"test-nostack"}}
        loaded = {"j1": load, "j2": load}
        self.assertEqual(
            self.decide([head, twin, gate, light], loaded=loaded, footprints=shares, **rules),
            {"j1": load, "j2": load, "j3": None, "j4": None},
        )
        running = job(5, kind="test-nostack", task="work/c", status="active")
        self.assertEqual(
            self.decide([running, head, twin, gate, light], loaded=loaded, footprints=shares | {"j5": {"ram": 6, "cpu": 11}}, **rules),
            {"j1": None, "j2": "all 1 quality-high slots taken", "j3": "test runs only beside test-nostack, but quality-high runs", "j4": None},
        )

    def test_a_light_entry_meets_only_running_and_granted_jobs_while_heavy_ones_keep_every_reservation(self):
        rules = {"slot_limits": {"test": 5, "test-nostack": 5, "deploy": 1}, "light": {"test-nostack"}}
        with self.subTest("budget reservations hold back heavy kinds only"):
            running, head, twin = job(1, status="active"), job(2), job(3, task="work/b")
            light, heavy = job(4, kind="test-nostack", task="work/c", need_gb=0), job(5, task="work/c")
            shares = {
                "j1": {"ram": 30, "cpu": 50}, "j2": {"ram": 50, "cpu": 60}, "j3": {"ram": 50, "cpu": 60},
                "j4": {"ram": 6, "cpu": 11}, "j5": {"ram": 5, "cpu": 5},
            }
            self.assertEqual(self.decide([running, head, twin, light, heavy], footprints=shares, **rules), {
                "j2": "RAM 30 % in use or reserved + 50 % > budget 75 %, CPU 50 % in use or reserved + 60 % > budget 100 %; reserved",
                "j3": "RAM 80 % in use or reserved + 50 % > budget 75 %, CPU 110 % in use or reserved + 60 % > budget 100 %; reserved",
                "j4": None,
                "j5": "RAM 136 % in use or reserved + 5 % > budget 75 %, CPU 181 % in use or reserved + 5 % > budget 100 %; reserved",
            })
        with self.subTest("disk reservations hold back heavy kinds only"):
            big, small, late = job(1, need_gb=50), job(2, kind="test-nostack", task="work/b", need_gb=0), job(3, task="work/c", need_gb=5)
            self.assertEqual(self.decide([big, small, late], free_gb=40.0, **rules), {
                "j1": "50 GB would cut into the 10 GB floor; reserved", "j2": None, "j3": "5 GB would cut into the 10 GB floor; reserved",
            })
        with self.subTest("a granted light counts for later lights, a blocked one reserves against heavy kinds"):
            running = job(1, status="active")
            first, second = job(2, kind="test-nostack", need_gb=0), job(3, kind="test-nostack", task="work/b", need_gb=0)
            heavy = job(4, task="work/c")
            shares = {"j1": {"ram": 10, "cpu": 60}, "j2": {"ram": 0, "cpu": 30}, "j3": {"ram": 0, "cpu": 30}, "j4": {"ram": 5, "cpu": 5}}
            self.assertEqual(self.decide([running, first, second, heavy], footprints=shares, **rules), {
                "j2": None, "j3": "CPU 90 % in use or reserved + 30 % > budget 100 %; reserved",
                "j4": "CPU 120 % in use or reserved + 5 % > budget 100 %; reserved",
            })
        with self.subTest("a head the host load keeps out while a job runs reserves against heavy kinds only"):
            load = "RAM 55 % used + 41 % still to come reach the limit 90 %"
            running, head = job(1, kind="test-nostack", status="active", need_gb=0), job(2, kind="deploy")
            heavy, light = job(3, task="work/b"), job(4, kind="test-nostack", task="work/c", need_gb=0)
            shares = {"j1": {"ram": 0, "cpu": 10}, "j2": {"ram": 0, "cpu": 60}, "j3": {"ram": 0, "cpu": 40}, "j4": {"ram": 0, "cpu": 40}}
            self.assertEqual(self.decide([running, head, heavy, light], loaded={"j2": load}, footprints=shares, **rules), {
                "j2": None, "j3": "CPU 70 % in use or reserved + 40 % > budget 100 %; reserved", "j4": None,
            })


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
        self.assertEqual(self.entries(), [])
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
        self.assertEqual(self.hook("not json").returncode, 0)
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
