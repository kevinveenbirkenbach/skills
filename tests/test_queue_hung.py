"""Exercise the kvb-org-queue hung-job guard: the process-tree probe, hold ending a tree that stands still and sparing one that works, the list mark and the learning that skips hung runs."""

from __future__ import annotations

import contextlib
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
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "skills" / "kvb-org-queue" / "scripts"
QUEUE = SCRIPTS / "queue.py"
HISTORY = SCRIPTS / "history.py"
STANDSTILL = SCRIPTS / "standstill.py"
NOW = 1_800_000_000.0
POLL = 0.1
HUNG = 2.0
GRACE = 0.5
OUTLAST = HUNG + 0.5
SAMPLE = {"free_gb": 50.0, "mem": 20.0, "cpu": 10.0}
PROBE_KEYS = {"cpu_s", "read_bytes", "written_bytes", "still_min", "members", "tree"}
OPEN_MEMORY = {
    "available": -1, "swap_free": -1, "psi_some": 1000, "psi_full": 1000, "swap_out_mb_min": 1e9, "container_swap_gb": 1e9,
}
SLEEP = "import time\ntime.sleep(60)\n"
PRINT = (
    f"import sys, time\nend = time.monotonic() + {OUTLAST}\n"
    "while time.monotonic() < end:\n    sys.stdout.write('x\\n')\n    sys.stdout.flush()\n    time.sleep(0.05)\n"
)
BURN = f"import time\nend = time.monotonic() + {OUTLAST}\nwhile time.monotonic() < end:\n    pass\n"
STUBBORN = (
    "import os, signal, sys, time\n"
    "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
    "with open(sys.argv[1] + '.part', 'w') as out:\n"
    "    out.write(str(os.getpid()))\n"
    "os.replace(sys.argv[1] + '.part', sys.argv[1])\n"
    "time.sleep(60)\n"
)
MEMBER = (
    "import os, signal, sys, time\n"
    "def ended(*_):\n"
    "    with open(sys.argv[1], 'w') as out:\n"
    "        out.write('term')\n"
    "    os._exit(0)\n"
    "signal.signal(signal.SIGTERM, ended)\n"
    "time.sleep(60)\n"
)
SAME_SESSION = f"import subprocess, sys\nsubprocess.run([sys.executable, '-c', {BURN!r}], check=True)\n"
NEW_SESSION = f"import subprocess, sys\nsubprocess.run([sys.executable, '-c', {BURN!r}], check=True, start_new_session=True)\n"
FAMILY = (
    "import subprocess, sys, time\n"
    f"subprocess.Popen([sys.executable, '-c', {MEMBER!r}, sys.argv[1]])\n"
    f"subprocess.Popen([sys.executable, '-c', {MEMBER!r}, sys.argv[2]], process_group=0)\n"
    "time.sleep(60)\n"
)
ABANDONED = (
    "import subprocess, sys, time\n"
    f"subprocess.Popen([sys.executable, '-c', {STUBBORN!r}, sys.argv[1]], process_group=0)\n"
    "time.sleep(60)\n"
)
CLEANUP_WORK = 0.5


def cleanup(own_session: bool, work: float) -> str:
    """Args:
        own_session: whether the process the SIGTERM handler starts leads a
            session of its own.
        work: seconds the handler works once that process is ready, 0 to
            exit at once; the session sweep alone, deterministically, is
            test_signals_reach_members_whose_start_time_still_matches_the_session_and_their_new_descendants.

    Returns:
        A command whose SIGTERM handler starts STUBBORN, works, and exits.
    """
    return (
        "import os, signal, subprocess, sys, time\n"
        "def ended(*_):\n"
        f"    subprocess.Popen([sys.executable, '-c', {STUBBORN!r}, sys.argv[1]], start_new_session={own_session})\n"
        "    while not os.path.exists(sys.argv[1]):\n"
        "        time.sleep(0.02)\n"
        f"    time.sleep({work})\n"
        "    os._exit(0)\n"
        "signal.signal(signal.SIGTERM, ended)\n"
        "time.sleep(60)\n"
    )


CLEANUP = cleanup(False, 0)
SETSID_CLEANUP = cleanup(True, CLEANUP_WORK)
SESSION_CLEANUP = (
    "import subprocess, sys, time\n"
    f"subprocess.Popen([sys.executable, '-c', {CLEANUP!r}, sys.argv[1]], start_new_session=True)\n"
    "time.sleep(60)\n"
)
CLEANUP_GRACE = 3.0
CLIENT = f"import subprocess, sys\nsubprocess.run([sys.argv[1], '{OUTLAST}'], check=True)\n"
STOPPED = (
    "import signal, subprocess, sys, time\n"
    "member = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
    "member.send_signal(signal.SIGSTOP)\n"
    f"time.sleep({OUTLAST})\n"
    "member.kill()\n"
    "member.wait()\n"
)
HOLD = (
    "import importlib.util, sys\n"
    "spec = importlib.util.spec_from_file_location('kvb_queue_hung', sys.argv[1])\n"
    "queue = importlib.util.module_from_spec(spec)\n"
    "spec.loader.exec_module(queue)\n"
    f"queue.POLL_SECONDS = {POLL}\n"
    f"queue.standstill.HUNG_SECONDS = {HUNG}\n"
    f"queue.standstill.KILL_GRACE_SECONDS = {GRACE}\n"
    "sys.argv = sys.argv[1:]\n"
    "sys.exit(queue.main())\n"
)


def _load(path: Path):
    spec = importlib.util.spec_from_file_location(f"{path.stem}_hung_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def history_row(seq: int, **fields: object) -> dict:
    return {
        "id": f"r{seq}", "kind": "test", "signature": "w: make test", "workdir": "/w", "start": NOW - 600, "end": NOW,
        "minutes": 10.0, "exit": 0, "free_before_gb": 50.0, "min_free_gb": 49.0, "disk_gb": 1.0, "mem_before": 20.0,
        "mem_max": 30.0, "cpu_before": 10.0, "cpu_max": 40.0, "concurrent": 0, **fields,
    }


def stat_line(pid: int, comm: str, parent: int, session: int, times: tuple[int, int, int, int], state: str, start: int) -> bytes:
    after = [state, str(parent), str(pid), str(session), "0", "-1", "4194560", "100", "0", "0", "0",
             *map(str, times), "20", "0", "1", "0", str(start), "0", "0"]
    return f"{pid} ({comm}) {' '.join(after)}\n".encode()


def plain(pid: int, parent: int, session: int, utime: int) -> bytes:
    return stat_line(pid, "make", parent, session, (utime, 0, 0, 0), "S", 1000 + pid)


def io_lines(rchar: int, wchar: int, read_bytes: int, write_bytes: int) -> bytes:
    return (f"rchar: {rchar}\nwchar: {wchar}\nsyscr: 1\nsyscw: 1\nread_bytes: {read_bytes}\n"
            f"write_bytes: {write_bytes}\ncancelled_write_bytes: 0\n").encode()


def awaited(path: Path) -> int:
    deadline = time.monotonic() + 30
    while not path.exists():
        if time.monotonic() > deadline:
            raise AssertionError(f"{path} never appeared")
        time.sleep(0.02)
    return int(path.read_text(encoding="utf-8"))


def ended(pid: int) -> bool:
    try:
        stat = Path(f"/proc/{pid}/stat").read_bytes()
    except OSError:
        return True
    return stat.rsplit(b")", 1)[1].split()[0] in (b"Z", b"X")


def kill_quietly(pid: int) -> None:
    with contextlib.suppress(ProcessLookupError):
        os.kill(pid, signal.SIGKILL)


class TestProbe(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.standstill = _load(STANDSTILL)

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.proc = Path(tmp.name) / "proc"
        self.proc.mkdir()
        patched = mock.patch.object(self.standstill, "PROC", self.proc)
        patched.start()
        self.addCleanup(patched.stop)

    def process(self, pid: int, stat: bytes | None, io: bytes | None) -> None:
        folder = self.proc / str(pid)
        folder.mkdir(exist_ok=True)
        if stat is not None:
            (folder / "stat").write_bytes(stat)
        if io is not None:
            (folder / "io").write_bytes(io)

    def test_stat_splits_after_the_last_parenthesis_so_a_command_name_with_parentheses_reads_right(self):
        line = stat_line(4242, "a) (b c) 9 9", 7, 4242, (7, 3, 2, 1), "T", 999)
        self.assertEqual(self.standstill.parse_stat(line), (4242, b"a) (b c) 9 9", b"T", 7, 4242, 13, 999))
        self.assertNotEqual(line.split(b")", 1)[1].split()[3], b"4242")

    def test_the_probe_walks_the_whole_tree_whatever_its_session_and_skips_vanished_and_foreign_processes(self):
        self.process(4242, plain(4242, 100, 4242, 10), io_lines(0, 100, 0, 0))
        self.process(4243, plain(4243, 4242, 4243, 5), None)
        self.process(4244, plain(4244, 4243, 4244, 7), io_lines(30, 0, 0, 0))
        self.process(4245, plain(4245, 1, 4242, 1), None)
        self.process(4246, plain(4246, 1, 1, 100), io_lines(9000, 9000, 0, 0))
        self.process(4247, None, None)
        (self.proc / "self").mkdir()
        seen = self.standstill.probe(4242)
        self.assertEqual(seen.members, {(pid, 1000 + pid) for pid in (4242, 4243, 4244, 4245)})
        self.assertEqual((seen.ticks, seen.io, seen.elsewhere, seen.paused), (23, (30, 100, 0, 0), (), False))
        self.assertEqual(self.standstill.probe(4246).ticks, 100)
        self.assertIsNone(self.standstill.probe(4999))

    def test_cpu_time_reads_writes_and_a_new_process_each_count_as_progress(self):
        self.process(4242, plain(4242, 1, 4242, 1), io_lines(5, 10, 0, 0))
        clock = self.standstill.Clock(4242)
        changes = (
            (4242, plain(4242, 1, 4242, 2), None),
            (4242, None, io_lines(6, 10, 0, 0)),
            (4242, None, io_lines(6, 11, 0, 0)),
            (4242, None, io_lines(6, 11, 1, 0)),
            (4242, None, io_lines(6, 11, 1, 1)),
            (4243, plain(4243, 4242, 4243, 0), None),
        )
        with mock.patch.object(self.standstill, "HUNG_SECONDS", 0.2):
            self.assertFalse(clock.hung())
            for pid, stat, counters in changes:
                time.sleep(0.25)
                self.assertTrue(clock.hung())
                self.process(pid, stat, counters)
                self.assertFalse(clock.hung(), (pid, stat, counters))
            time.sleep(0.25)
            self.assertTrue(clock.hung())
        report = clock.report()
        self.assertEqual((report["cpu_s"], report["read_bytes"], report["written_bytes"]), (round(2 / self.standstill.TICKS, 2), 6, 11))
        self.assertGreaterEqual(report["still_min"], 0)
        self.assertEqual((report["members"], report["tree"]), (2, ["4243 make S", "4242 make S"]))

    def test_the_trace_names_the_leaves_first_with_state_and_wait_channel_but_never_a_command_line(self):
        self.process(4242, plain(4242, 1, 4242, 0), None)
        self.process(4243, stat_line(4243, "sleep", 4242, 4242, (0, 0, 0, 0), "D", 5243), None)
        self.process(4244, plain(4244, 4242, 4242, 0), None)
        self.process(4245, stat_line(4245, "x\x1b[2J", 4242, 4242, (0, 0, 0, 0), "S", 5245), None)
        for pid, wchan in ((4242, "do_wait"), (4243, "folio_wait_bit"), (4244, "0")):
            (self.proc / str(pid) / "wchan").write_text(wchan, encoding="ascii")
        (self.proc / "4243" / "cmdline").write_bytes(b"sleep\0--token=secret\0")
        leaves = ["4243 sleep D folio_wait_bit", "4244 make S", "4245 x\\x1b[2J S"]
        self.assertEqual(self.standstill.trace(4242), [*leaves, "4242 make S do_wait"])
        with mock.patch.object(self.standstill, "TRACE_LIMIT", 2):
            self.assertEqual(self.standstill.trace(4242), leaves[:2])
        self.assertEqual(self.standstill.trace(4999), [])

    def test_a_stopped_member_or_a_client_whose_work_runs_elsewhere_never_fires_and_the_client_is_told_once(self):
        self.process(4242, plain(4242, 1, 4242, 1), None)
        held = (("docker", "S"), ("docker-compose", "S"), ("podman", "S"), ("ssh", "S"), ("sleep", "T"), ("python3", "t"))
        with mock.patch.object(self.standstill, "HUNG_SECONDS", 0), contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertTrue(self.standstill.Clock(4242).hung())
            for comm, state in held:
                self.process(4243, stat_line(4243, comm, 4242, 4243, (0, 0, 0, 0), state, 5000), None)
                clock = self.standstill.Clock(4242)
                self.assertEqual([clock.hung() for _ in range(3)], [False, False, False], comm)
        self.assertEqual(err.getvalue().count("holds off"), 4)

    def test_an_unreadable_proc_never_fires_and_says_so_once(self):
        self.process(4242, plain(4242, 1, 4242, 1), io_lines(0, 10, 0, 0))
        with mock.patch.object(self.standstill, "HUNG_SECONDS", 0):
            self.assertTrue(self.standstill.Clock(4242).hung())
            clock = self.standstill.Clock(4242)
            with mock.patch.object(self.standstill, "PROC", self.proc / "missing"), \
                    contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertEqual([clock.hung() for _ in range(3)], [False, False, False])
        self.assertEqual(err.getvalue().count("hung-job guard is off"), 1)

    def test_signals_reach_members_whose_start_time_still_matches_the_session_and_their_new_descendants(self):
        self.process(4242, plain(4242, 1, 4242, 0), None)
        self.process(4243, plain(4243, 4242, 4242, 0), None)
        self.process(4244, stat_line(4244, "make", 4242, 4242, (0, 0, 0, 0), "Z", 5244), None)
        self.process(4245, plain(4245, 1, 4242, 0), None)
        self.process(4250, plain(4250, 4243, 4250, 0), None)
        self.process(4260, plain(4260, 1, 1, 0), None)
        self.process(4270, plain(4270, 1, 4270, 0), None)
        self.process(4271, plain(4271, 4270, 4271, 0), None)
        self.process(4281, plain(4281, 1, 4280, 0), None)
        self.assertEqual(self.standstill.members(4242), {pid: 1000 + pid for pid in (4242, 4243, 4244, 4245, 4250)})
        self.assertEqual(self.standstill.members(4999), {})
        with mock.patch.object(self.standstill.os, "kill") as kill:
            living = self.standstill.signal_all({4242: 5242, 4244: 5244, 4270: 1, 4280: 5280}, signal.SIGTERM)
        self.assertEqual(living, {4242: 5242, 4243: 5243, 4245: 5245, 4250: 5250, 4281: 5281})
        self.assertEqual(sorted(call.args for call in kill.call_args_list),
                         [(pid, signal.SIGTERM) for pid in (4242, 4243, 4245, 4250, 4281)])

    def test_the_suspect_runtime_is_three_times_the_longest_run_with_a_floor(self):
        self.assertEqual(self.standstill.suspect_seconds(20), 3600)
        self.assertEqual(self.standstill.suspect_seconds(5), self.standstill.SUSPECT_FLOOR_SECONDS)
        self.assertEqual(self.standstill.suspect_seconds(None), self.standstill.SUSPECT_FLOOR_SECONDS)


class TestSupervise(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.queue = _load(QUEUE)

    def start(self, code: str, *args: str) -> subprocess.Popen:
        child = subprocess.Popen([sys.executable, "-c", code, *args], start_new_session=True,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(child.wait, 30)
        self.addCleanup(self.queue.send, child, signal.SIGKILL)
        return child

    def scratch(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name)

    def supervised(self, child: subprocess.Popen, *extra) -> tuple[tuple[int, dict | None], float, str]:
        """Args:
            child: the started command.
            extra: patches entered after the defaults, so they win.
        """
        patches = (
            mock.patch.object(self.queue, "POLL_SECONDS", POLL),
            mock.patch.object(self.queue.standstill, "HUNG_SECONDS", HUNG),
            mock.patch.object(self.queue.standstill, "KILL_GRACE_SECONDS", GRACE),
            mock.patch.object(self.queue, "measure", return_value=SAMPLE),
            *extra,
        )
        with contextlib.ExitStack() as stack, contextlib.redirect_stderr(io.StringIO()) as err:
            for patch in patches:
                stack.enter_context(patch)
            started = time.monotonic()
            result = self.queue.supervise({}, child, [])
        return result, time.monotonic() - started, err.getvalue()

    def test_a_sleeping_command_is_ended_with_124_and_its_probe(self):
        child = self.start(SLEEP)
        (code, probe), took, err = self.supervised(child)
        self.assertEqual(code, 124)
        self.assertEqual(set(probe), PROBE_KEYS)
        self.assertEqual(probe["members"], 1)
        self.assertRegex(probe["tree"][0], rf"^{child.pid} \S+ S")
        self.assertEqual(child.returncode, -signal.SIGTERM)
        self.assertLess(took, HUNG + 10)
        self.assertIn("stood still", err)
        self.assertIn(f"tree of 1: {child.pid} ", err)

    def test_a_command_that_keeps_printing_is_not_ended(self):
        self.assertEqual(self.supervised(self.start(PRINT))[0], (0, None))

    def test_a_command_that_burns_cpu_without_printing_is_not_ended(self):
        self.assertEqual(self.supervised(self.start(BURN))[0], (0, None))

    def test_a_command_ignoring_sigterm_is_killed_after_the_grace(self):
        ready = self.scratch() / "ready"
        child = self.start(STUBBORN, str(ready))
        awaited(ready)
        (code, probe), took, _ = self.supervised(child)
        self.assertEqual((code, child.returncode, set(probe)), (124, -signal.SIGKILL, PROBE_KEYS))
        self.assertGreaterEqual(took, HUNG + GRACE)

    def test_a_working_grandchild_counts_in_the_same_session_and_in_a_new_one(self):
        self.assertEqual(self.supervised(self.start(SAME_SESSION))[0], (0, None))
        self.assertEqual(self.supervised(self.start(NEW_SESSION))[0], (0, None))

    def test_a_sleeping_tree_is_ended_and_every_member_gets_sigterm_whatever_its_process_group(self):
        folder = self.scratch()
        marks = [folder / "same-group", folder / "own-group"]
        child = self.start(FAMILY, *map(str, marks))
        (code, _), _, _ = self.supervised(child)
        self.assertEqual((code, child.returncode), (124, -signal.SIGTERM))
        self.assertEqual([mark.read_text(encoding="utf-8") for mark in marks], ["term", "term"])

    def test_a_member_ignoring_sigterm_is_killed_after_the_grace_although_the_leader_already_exited(self):
        ready = self.scratch() / "ready"
        child = self.start(ABANDONED, str(ready))
        member = awaited(ready)
        (code, _), took, _ = self.supervised(child)
        self.assertEqual((code, child.returncode), (124, -signal.SIGTERM))
        self.assertTrue(ended(member))
        self.assertGreaterEqual(took, HUNG + GRACE)

    def test_a_process_a_member_starts_during_the_grace_is_killed_although_its_parent_exited(self):
        cases = (("same session", CLEANUP, 0), ("member in own session", SESSION_CLEANUP, -signal.SIGTERM),
                 ("orphan in own session", SETSID_CLEANUP, 0))
        for case, script, leader_exit in cases:
            with self.subTest(case):
                ready = self.scratch() / "ready"
                child = self.start(script, str(ready))
                grace = mock.patch.object(self.queue.standstill, "KILL_GRACE_SECONDS", CLEANUP_GRACE)
                (code, _), _, _ = self.supervised(child, grace)
                orphan = awaited(ready)
                self.addCleanup(kill_quietly, orphan)
                self.assertEqual((code, child.returncode), (124, leader_exit))
                self.assertTrue(ended(orphan))

    def test_a_process_forked_while_sigkill_goes_out_is_killed_on_the_next_pass(self):
        proc = self.scratch() / "proc"

        def spawn(pid: int, parent: int) -> None:
            (proc / str(pid)).mkdir(parents=True)
            (proc / str(pid) / "stat").write_bytes(plain(pid, parent, 4242, 0))

        def kill(pid: int, signum: int) -> None:
            if signum == signal.SIGKILL:
                shutil.rmtree(proc / str(pid))
                if pid == 4243:
                    spawn(4250, 1)

        spawn(4242, 1)
        spawn(4243, 4242)
        child = mock.Mock(pid=4242, returncode=None, poll=lambda: None if (proc / "4242").exists() else 0)
        with mock.patch.object(self.queue.standstill, "PROC", proc), \
                mock.patch.object(self.queue.standstill, "KILL_GRACE_SECONDS", GRACE), \
                mock.patch.object(self.queue.standstill.os, "kill", side_effect=kill) as sent, \
                mock.patch.object(self.queue.os, "killpg") as group:
            self.assertEqual(self.queue.stop(child), 124)
        self.assertIn(mock.call(4250, signal.SIGKILL), sent.call_args_list)
        self.assertEqual(sorted(path.name for path in proc.iterdir()), [])
        group.assert_not_called()

    def test_a_tree_running_a_container_client_never_fires_and_says_so_once(self):
        sleep = shutil.which("sleep")
        if sleep is None:
            self.skipTest("no sleep binary on PATH")
        docker = self.scratch() / "docker"
        docker.symlink_to(sleep)
        result, _, err = self.supervised(self.start(CLIENT, str(docker)))
        self.assertEqual(result, (0, None))
        self.assertEqual(err.count("the command runs docker,"), 1)

    def test_a_tree_with_a_stopped_member_never_fires(self):
        self.assertEqual(self.supervised(self.start(STOPPED))[0], (0, None))

    def test_stop_falls_back_to_the_process_group_when_proc_shows_nothing(self):
        child = self.start(SLEEP)
        with mock.patch.object(self.queue.standstill, "PROC", self.scratch() / "missing"), \
                mock.patch.object(self.queue.standstill, "KILL_GRACE_SECONDS", GRACE):
            self.assertEqual(self.queue.stop(child), 124)
        self.assertEqual(child.returncode, -signal.SIGTERM)


class TestHungHistory(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.history = _load(HISTORY)
        cls.queue = _load(QUEUE)

    def learn(self, rows: list[dict]) -> dict:
        return self.history.learn(rows, NOW, {"load_limits": {"mem_percent": 80, "cpu_percent": 90}})[0]

    def test_a_hung_row_stays_out_of_the_learned_durations_and_shares(self):
        rows = [history_row(n) for n in range(5)]
        probe = {"cpu_s": 1.0, "read_bytes": 0, "written_bytes": 0, "still_min": 60.0}
        stuck = history_row(5, minutes=500.0, mem_max=95.0, exit=124)
        stats = self.learn([*rows, {**stuck, self.history.HUNG: probe}])["test", "w: make test"]
        self.assertEqual((stats["runs"], stats["minutes"], stats["longest"], stats["ram_share"]), (5, 10.0, 10.0, 10.0))
        counted = self.learn([*rows, stuck])["test", "w: make test"]
        self.assertEqual((counted["runs"], counted["longest"]), (6, 500.0))

    def test_list_marks_an_active_job_past_three_times_its_longest_run_and_past_the_floor(self):
        signatures = self.learn([history_row(n, minutes=20.0 - n) for n in range(5)])
        entry = {"kind": "test", "aliases": ["w: make test"], "granted": NOW}
        suspected = self.queue.suspected
        self.assertIsNone(suspected({**entry, "granted": NOW - 59 * 60}, None, signatures, NOW))
        self.assertEqual(suspected({**entry, "granted": NOW - 61 * 60}, None, signatures, NOW), "suspect hung (61 min)")
        self.assertEqual(suspected({**entry, "granted": NOW - 61 * 60}, "backfilled", signatures, NOW),
                         "suspect hung (61 min); backfilled")
        unknown = {**entry, "aliases": ["w: make lint"]}
        self.assertEqual(suspected({**unknown, "granted": NOW - 29 * 60}, "backfilled", signatures, NOW), "backfilled")
        self.assertEqual(suspected({**unknown, "granted": NOW - 31 * 60}, None, signatures, NOW), "suspect hung (31 min)")
        short = self.learn([history_row(n, minutes=5.0) for n in range(5)])
        self.assertIsNone(suspected({**entry, "granted": NOW - 20 * 60}, None, short, NOW))


class TestHungHold(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name).resolve()
        self.root = self.base / "council"
        self.root.mkdir()
        home = self.base / "home"
        home.mkdir()
        self.history_file = self.root / "queue-history.jsonl"
        self.config = self.base / "config.json"
        self.config.write_text(json.dumps({
            "disk": str(self.base),
            "thresholds_gb": {"warn": 0, "stop": 0, "critical": 0},
            "projection_minutes": 30,
            "slot_need_gb": {"test": 0.001},
            "slot_limits": {"test": 1},
            "load_limits": {"cpu_percent": 101, "mem_percent": 101, "sample_seconds": 0.1},
            "budget_percent": {"ram": 75, "cpu": 100},
            "memory_limits": {stage: OPEN_MEMORY for stage in ("warn", "stop")},
            "heavy_commands": ["^make compose-deploy"],
            "never_block": ["^make compose-down"],
        }), encoding="utf-8")
        (self.root / "rasci.json").write_text(json.dumps({"work/a": {"roles": {}, "status": "running"}}), encoding="utf-8")
        self.env = {
            "PATH": os.environ["PATH"],
            "HOME": str(home),
            "GIT_CEILING_DIRECTORIES": str(self.base.parent),
            "AGENTS_COUNCIL_ROOT": str(self.root),
            "AGENTS_COUNCIL_CONFIG": str(self.config),
            "CLAUDE_PROJECT_DIR": str(self.base / "project"),
        }

    def run_queue(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-c", HOLD, str(QUEUE), *args], cwd=self.base, env=self.env, stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=60, check=False,
        )

    def hold(self, code: str) -> subprocess.CompletedProcess:
        return self.run_queue("hold", "--kind", "test", "--task", "work/a", "--session", "s1", "--", sys.executable, "-c", code)

    def rows(self) -> list[dict]:
        return [json.loads(line) for line in self.history_file.read_text(encoding="utf-8").splitlines()]

    def test_a_hold_whose_command_sleeps_exits_124_and_its_history_row_marks_it_hung(self):
        result = self.hold(SLEEP)
        self.assertEqual(result.returncode, 124, result.stderr)
        self.assertIn("stood still", result.stderr)
        [row] = self.rows()
        self.assertEqual((row["exit"], set(row["hung"])), (124, PROBE_KEYS))
        self.assertEqual(json.loads((self.root / "queue.json").read_text(encoding="utf-8"))["entries"], [])

    def test_a_hold_whose_command_works_keeps_its_exit_code_and_an_unmarked_row(self):
        result = self.hold(BURN + "raise SystemExit(5)\n")
        self.assertEqual((result.returncode, result.stderr), (5, ""))
        [row] = self.rows()
        self.assertEqual(row["exit"], 5)
        self.assertNotIn("hung", row)

    def test_list_marks_an_active_job_past_the_floor_when_nothing_is_learned(self):
        queue = _load(QUEUE)
        me, mine = os.getpid(), queue.identity(os.getpid())
        now = time.time()
        floor = queue.standstill.SUSPECT_FLOOR_SECONDS
        entry = {
            "seq": 1, "kind": "test", "task": "work/a", "need_gb": 0, "hotfix": None, "workdir": "/w", "session": "s1",
            "name": "s1", "pid": me, "pid_start": mine, "child": me, "child_start": mine, "status": "active",
            "enqueued": now - floor - 120, "cmd": "make test", "code": queue.CODE,
        }
        entries = [{**entry, "id": "test-1", "granted": now - floor - 60}, {**entry, "id": "test-2", "seq": 2, "granted": now - floor + 60}]
        (self.root / "queue.json").write_text(json.dumps({"seq": 2, "entries": entries}), encoding="utf-8")
        listing = self.run_queue("list")
        self.assertEqual(listing.returncode, 0, listing.stderr)
        reasons = [line.split("\t")[-1] for line in listing.stdout.splitlines()[1:]]
        self.assertEqual(reasons, [f"suspect hung ({(floor + 60) // 60} min)", "-"])


if __name__ == "__main__":
    unittest.main()
