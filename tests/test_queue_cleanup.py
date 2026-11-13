"""Exercise kvb-org-queue-cleanup: jobs whose hold lock no living process holds leave the queue after a pan-pan and a security, every other job stays."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from collections.abc import Callable
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
CLEANUP = REPO_ROOT / "skills" / "kvb-org-queue-cleanup" / "scripts" / "cleanup.py"
SYSTEMD = CLEANUP.parents[1] / "systemd"
SESSIONS = {"s0": "Main", "s1": "Skills", "s2": "IAM"}
WINDOW = 900
WORKER = "systemd kvb-org-queue-cleanup"
HOLD = (
    "import ctypes, fcntl, struct, subprocess, sys\n"
    "ctypes.CDLL(None).prctl(1, 9)\n"
    "handle = open(sys.argv[1], 'a')\n"
    "if sys.argv[2] == 'posix':\n"
    "    fcntl.lockf(handle, fcntl.LOCK_EX)\n"
    "elif sys.argv[2] == 'ofd':\n"
    "    fcntl.fcntl(handle, fcntl.F_OFD_SETLK, struct.pack('hhqqi4x', fcntl.F_WRLCK, 0, 0, 0, 0))\n"
    "else:\n"
    "    fcntl.flock(handle, fcntl.LOCK_EX)\n"
    "if sys.argv[2] == 'child':\n"
    "    subprocess.Popen([sys.executable, '-c', 'import sys; sys.stdin.read()'], pass_fds=[handle.fileno()])\n"
    "print('ready', flush=True)\n"
    "sys.stdin.read()\n"
)
FORGED = {"session": "s9", "name": "Main", "pid": 1, "pid_start": "1", "child": 2, "child_start": "2", "beat": 0,
          "host": True, "granted": 0, "workdir": "/elsewhere"}


def _load(path: Path):
    spec = importlib.util.spec_from_file_location(f"{path.stem}_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ids_of(entries: list[dict]) -> list[str]:
    return [entry["id"] for entry in entries]


class Killed(BaseException):
    pass


class FakeClock:
    def __init__(self, wall: float, hook: Callable[[float], None]):
        self.wall, self.mono, self.hook = wall, 0.0, hook

    def time(self) -> float:
        return self.wall

    def monotonic(self) -> float:
        return self.mono

    def sleep(self, seconds: float) -> None:
        self.hook(seconds)
        self.wall += seconds
        self.mono += seconds


class TestQueueCleanup(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name).resolve()
        self.root = base / "council"
        self.holds = self.root / "holds"
        self.holds.mkdir(parents=True, mode=0o700)
        self.home = base / "home"
        sessions = self.home / ".claude" / "sessions"
        sessions.mkdir(parents=True)
        for sid, name in SESSIONS.items():
            (sessions / f"{sid}.json").write_text(json.dumps({"sessionId": sid, "name": name}), encoding="utf-8")
        self.kept = self.home / ".local" / "state" / "agents-council"
        self.kept.mkdir(parents=True, mode=0o700)
        env = mock.patch.dict(os.environ, {
            "AGENTS_COUNCIL_ROOT": str(self.root), "HOME": str(self.home), "AGENTS_COUNCIL_CONFIG": str(base / "config.json"),
        })
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
        self.cleanup = _load(CLEANUP)
        self.last = WINDOW // self.cleanup.POLL_SECONDS - 1
        self.clock = FakeClock(float(int(time.time())), self.tick)
        for module in (self.cleanup, self.cleanup.radio):
            patch = mock.patch.object(module, "time", self.clock)
            patch.start()
            self.addCleanup(patch.stop)
        self.actions: dict[tuple[str, int], Callable[[], object]] = {}
        self.jumps: dict[tuple[str, int], tuple[float, float]] = {}
        self.slept: list[tuple[str, float]] = []
        self.seq = 0
        self.chair("s0")

    def tick(self, seconds: float) -> None:
        phase = self.state()["phase"]
        step = (phase, sum(p == phase for p, _ in self.slept))
        self.slept.append((phase, seconds))
        if step in self.actions:
            self.actions[step]()
        if step in self.jumps:
            wall, mono = self.jumps[step]
            self.clock.wall += wall
            self.clock.mono += mono

    def state(self) -> dict:
        return json.loads((self.kept / "queue-cleanup.json").read_text(encoding="utf-8"))

    def write_state(self, state: dict) -> None:
        (self.kept / "queue-cleanup.json").write_text(json.dumps(state), encoding="utf-8")

    def chair(self, session: str) -> None:
        office = self.root / "chair"
        office.mkdir(exist_ok=True)
        claim = {"office": "chair", "session": session, "runtime": "claude-code", "name": SESSIONS.get(session),
                 "beat": time.time(), "work": "chair"}
        (office / "claim.json").write_text(json.dumps(claim), encoding="utf-8")

    def entry(self, status: str, born: float = 0) -> dict:
        self.seq += 1
        return {
            "id": f"test-{self.seq}", "seq": self.seq, "kind": "test", "task": "work/a", "need_gb": 0, "hotfix": None,
            "workdir": f"/w{self.seq}", "session": "s1", "name": "Skills", "lock": f"{self.seq}-{time.time_ns() + int(born * 1e9)}",
            "host": False, "pid": 1, "pid_start": None, "child": None, "child_start": None, "status": status,
            "enqueued": time.time(), "granted": None, "cmd": "true",
        }

    def lock_file(self, entry: dict) -> Path:
        return self.holds / f"{entry['lock']}.lock"

    def holder(self, path: Path, mode: str = "flock") -> subprocess.Popen:
        proc = subprocess.Popen([sys.executable, "-c", HOLD, str(path), mode], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        self.addCleanup(proc.wait)
        self.addCleanup(proc.stdin.close)
        self.addCleanup(proc.stdout.close)
        self.assertEqual(proc.stdout.readline(), "ready\n")
        return proc

    def kill(self, proc: subprocess.Popen) -> None:
        proc.kill()
        proc.wait()

    def held(self, status: str, mode: str = "flock") -> dict:
        entry = self.entry(status)
        self.holder(self.lock_file(entry), mode)
        return entry

    def dead(self, status: str, born: float = 0) -> dict:
        entry = self.entry(status, born)
        self.kill(self.holder(self.lock_file(entry)))
        return entry

    def verdict(self, job: dict) -> str:
        [found] = [verdict for verdict, jobs in self.cleanup.judge([job]).items() if jobs]
        return found

    def queue(self, *entries: object) -> None:
        (self.root / "queue.json").write_text(json.dumps({"seq": self.seq, "entries": list(entries)}), encoding="utf-8")

    def entries(self) -> list[object]:
        return json.loads((self.root / "queue.json").read_text(encoding="utf-8"))["entries"]

    def ids(self) -> list[str]:
        return ids_of(self.entries())

    def rows(self) -> list[dict]:
        news = self.root / "news.jsonl"
        return [json.loads(line) for line in news.read_text(encoding="utf-8").splitlines()] if news.exists() else []

    def classes(self) -> list[str]:
        return [row["class"] for row in self.rows()]

    def register(self) -> dict:
        return json.loads((self.root / "rasci.json").read_text(encoding="utf-8"))["queue-cleanup"]

    def cli(self, *args: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = self.cleanup.main(list(args))
            except SystemExit as stop:
                code = stop.code
        return code, out.getvalue(), err.getvalue()

    def silence(self) -> None:
        hush = {"since": self.clock.wall, "until": self.clock.wall + 7200, "by": "IAM", "text": "disk full"}
        (self.root / "radio-silence.json").write_text(json.dumps(hush), encoding="utf-8")

    def round(self) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = self.cleanup.run_round(WINDOW, self.clock)
        return code, out.getvalue()

    def nothing(self, held: int, unclear: int, malformed: int) -> tuple[int, str]:
        return 0, f"queue-cleanup: no queue job without a living lock holder ({held} held, {unclear} unclear, {malformed} malformed); nothing sent\n"

    def waited(self, phase: str) -> float:
        return sum(seconds for p, seconds in self.slept if p == phase)

    def ends(self, out: str, tail: str) -> None:
        self.assertTrue(out.endswith(tail + "\n"), out)

    def at_the_close(self, action: Callable[[], None]) -> tuple[int, str, str]:
        original = self.cleanup.top_chair

        def chair_then_act() -> tuple[str | None, str]:
            if (self.kept / "queue-cleanup.json").exists() and self.state()["phase"] == "closing":
                action()
            return original()

        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(self.cleanup, "top_chair", chair_then_act), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = self.cleanup.run_round(WINDOW, self.clock)
        return code, out.getvalue(), err.getvalue()

    def install_unit(self) -> Path:
        unit = self.home / ".config" / "systemd" / "user" / "kvb-org-queue-cleanup.path"
        unit.parent.mkdir(parents=True)
        unit.write_text((SYSTEMD / "kvb-org-queue-cleanup.path").read_text(encoding="utf-8"), encoding="utf-8")
        return unit

    def test_a_vacant_or_stale_chair_deletes_nothing_and_sends_nothing(self):
        entries = [self.dead("waiting"), self.dead("active")]
        self.queue(*entries)
        for name, vacate in (("stale", lambda: self.chair("gone")), ("vacant", (self.root / "chair" / "claim.json").unlink)):
            with self.subTest(name):
                vacate()
                code, out = self.round()
                self.assertEqual(code, 0)
                self.ends(out, "; no one is accountable, nothing is deleted")
                self.assertEqual((self.entries(), self.rows()), (entries, []))

    def test_jobs_whose_hold_died_or_whose_lock_file_is_gone_leave_the_queue_after_a_pan_pan_and_a_security(self):
        waiting, active, gone, alive = self.dead("waiting"), self.dead("active"), self.entry("waiting"), self.held("active")
        self.queue(waiting, active, gone, alive)
        code, out = self.round()
        self.assertEqual((code, self.entries()), (0, [alive]))
        self.assertFalse((self.kept / "queue-stops.json").exists())
        self.assertEqual(
            [(row["class"], row["from"], row["to"]) for row in self.rows()],
            [("pan-pan", "queue-cleanup", []), ("security", "queue-cleanup", []), ("post", "queue-cleanup", ["Main"])],
        )
        pan_pan, security, post = (row["text"] for row in self.rows())
        self.assertRegex(
            pan_pan,
            r"^queue cleanup \d\d:\d\d, chair Main: no living process holds the lock of 3 queue jobs: test-1, test-2, test-3\. "
            r"A security at \d\d:\d\d names those still dead, deleted 15 min after it; nothing is signalled\. "
            r"1 held and 0 unclear jobs stay; ",
        )
        self.assertRegex(
            security,
            r"^queue cleanup \d\d:\d\d, chair Main: still no living lock holder, deleted at \d\d:\d\d: test-1, test-2, test-3; "
            r"held by a living process, not deleted: test-4\.$",
        )
        self.assertTrue(post.endswith(f": deleted 3; left the queue 0; python3 {CLEANUP} status lists the ids"), post)
        self.ends(out, ": deleted test-1, test-2, test-3; left the queue none")

    def test_a_hold_that_died_while_its_child_keeps_the_inherited_lock_is_not_deleted(self):
        inherited = self.entry("active")
        self.kill(self.holder(self.lock_file(inherited), "child"))
        dead = self.dead("waiting")
        self.queue(inherited, dead)
        self.assertEqual(self.cleanup.lock_file(inherited["lock"]), self.cleanup.HELD)
        code, out = self.round()
        self.assertEqual((code, self.entries()), (0, [inherited]))
        self.assertTrue(self.rows()[1]["text"].endswith(": test-2; held by a living process, not deleted: test-1."), self.rows()[1]["text"])
        self.ends(out, ": deleted test-2; left the queue none")

    def test_waiting_and_active_jobs_with_a_living_holder_of_any_lock_type_stay_whatever_their_entry_says(self):
        living = [{**self.held(status, mode), **FORGED} for status, mode in
                  (("waiting", "flock"), ("active", "flock"), ("waiting", "posix"), ("active", "ofd"))]
        self.queue(*living)
        self.assertEqual(self.round(), self.nothing(4, 0, 0))
        self.assertEqual((self.entries(), self.rows()), (living, []))
        dead = self.dead("waiting")
        self.queue(*living, dead)
        code, out = self.round()
        self.assertEqual((code, self.entries()), (0, living))
        self.assertTrue(self.rows()[1]["text"].endswith("; held by a living process, not deleted: test-1, test-2, test-3, test-4."))
        self.ends(out, ": deleted test-5; left the queue none")

    def test_a_lock_file_swapped_linked_redirected_unreadable_or_odd_is_never_dead(self):
        swapped = self.entry("waiting", born=-60)
        self.holder(self.lock_file(swapped))
        fresh = self.holds / "fresh"
        fresh.write_text("", encoding="utf-8")
        fresh.rename(self.lock_file(swapped))
        left, right = self.held("waiting"), self.held("active")
        self.lock_file(left).rename(self.holds / "spare")
        self.lock_file(right).rename(self.lock_file(left))
        (self.holds / "spare").rename(self.lock_file(right))
        redirected = self.dead("waiting")
        self.lock_file(redirected).rename(self.root / "target.lock")
        self.lock_file(redirected).symlink_to(self.root / "target.lock")
        linked = self.dead("waiting")
        os.link(self.lock_file(linked), self.root / "second.lock")
        unreadable = self.dead("active")
        self.lock_file(unreadable).chmod(0)
        directory, fifo = self.entry("waiting"), self.entry("active")
        self.lock_file(directory).mkdir()
        os.mkfifo(self.lock_file(fifo))
        future = self.dead("waiting", born=60)
        untagged = {**self.dead("waiting"), "lock": "1-2-3"}
        cases = {
            "swapped after its hold started": (swapped, "unclear"), "exchanged with another living one": (left, "held"),
            "the other one exchanged": (right, "held"), "a symlink": (redirected, "unclear"), "a second link": (linked, "unclear"),
            "unreadable": (unreadable, "unclear"), "a directory": (directory, "unclear"), "a fifo": (fifo, "unclear"),
            "a tag from the future": (future, "unclear"), "no lock tag": (untagged, "unclear"),
        }
        for name, (job, expected) in cases.items():
            with self.subTest(name):
                self.assertEqual(self.verdict(job), expected)
        jobs = [job for job, _ in cases.values()]
        self.queue(*jobs)
        self.assertEqual(self.round(), self.nothing(2, 8, 0))
        self.assertEqual((self.entries(), self.rows()), (jobs, []))

    def test_proc_locks_unreadable_unparsable_or_without_the_rounds_own_flock_makes_nothing_dead(self):
        job = self.dead("waiting")
        self.queue(job)
        info = os.stat(self.holds)
        own = f"1: FLOCK  ADVISORY  READ  1 {os.major(info.st_dev):02x}:{os.minor(info.st_dev):02x}:{info.st_ino} 0 EOF\n"
        fakes = {
            "missing": None, "a directory": "", "empty": "", "without the round's flock": "1: FLOCK  ADVISORY  WRITE 9 00:01:5 0 EOF\n",
            "with a line without an inode": own + "2: FLOCK  ADVISORY  WRITE 9 <none>:0 0 EOF\n", "with garbage": own + "garbage\n",
        }
        for index, (name, text) in enumerate(fakes.items()):
            with self.subTest(name):
                proc = self.home / f"proc-{index}"
                proc.mkdir()
                if name == "a directory":
                    (proc / "locks").mkdir()
                elif text is not None:
                    (proc / "locks").write_text(text, encoding="utf-8")
                with mock.patch.object(self.cleanup, "PROC", proc):
                    self.assertEqual(self.round(), self.nothing(0, 1, 0))
        self.assertEqual((self.entries(), self.rows()), ([job], []))
        control = self.home / "control"
        control.mkdir()
        (control / "locks").write_text(own, encoding="utf-8")
        with mock.patch.object(self.cleanup, "PROC", control):
            self.assertEqual(self.verdict(job), "dead")

    def test_lock_lines_name_every_line_of_any_type_pid_or_waiting_state_and_refuse_any_other(self):
        proc = self.home / "proc"
        proc.mkdir()
        first = "1: FLOCK  ADVISORY  WRITE 100 00:2d:555 0 EOF\n"
        (proc / "locks").write_text(
            first
            + "1: -> FLOCK  ADVISORY  WRITE 101 00:2d:556 0 EOF\n"
            "2: POSIX  ADVISORY  WRITE 102 00:2d:557 0 0\n"
            "3: OFDLCK ADVISORY  WRITE -1 00:2d:558 10 10\n"
            "4: FLOCK  ADVISORY  READ  0 fd:01:777 0 EOF\n"
            "5: LEASE  ACTIVE    READ  105 103:02:888 0 EOF\n"
            "6: POSIX  ADVISORY  WRITE 106 00:2d:12345678901 0 EOF\n",
            encoding="utf-8",
        )
        self.assertEqual(
            self.cleanup.lock_lines(proc),
            {(0, 0x2D, 555), (0, 0x2D, 556), (0, 0x2D, 557), (0, 0x2D, 558), (0xFD, 1, 777), (0x103, 2, 888), (0, 0x2D, 12345678901)},
        )
        odd = {"garbage": "garbage\n", "no inode": "7: FLOCK  ADVISORY  WRITE 106 <none>:0 0 EOF\n", "blank": "\n",
               "two devices": "8: FLOCK  ADVISORY  WRITE 1 00:2d:1 00:2d:2 EOF\n"}
        for name, line in odd.items():
            with self.subTest(name):
                (proc / "locks").write_text(first + line, encoding="utf-8")
                self.assertIsNone(self.cleanup.lock_lines(proc))
        (proc / "locks").write_text("", encoding="utf-8")
        self.assertEqual(self.cleanup.lock_lines(proc), set())
        (proc / "locks").unlink()
        self.assertIsNone(self.cleanup.lock_lines(proc))

    def test_a_job_that_dies_after_the_snapshot_waits_for_the_next_round_and_one_living_again_stays(self):
        revived, later = self.dead("waiting"), self.entry("active")
        hold = self.holder(self.lock_file(later))
        self.queue(revived, later)
        self.actions[("need", 0)] = lambda: (self.holder(self.lock_file(revived)), self.kill(hold))
        code, out = self.round()
        self.assertEqual((code, self.entries(), self.classes()), (0, [revived, later], ["pan-pan", "post"]))
        self.ends(out, ": deleted none; held by a living process, not deleted test-1; left the queue none")

    def test_a_job_alive_at_the_security_and_dead_again_at_the_end_is_not_deleted(self):
        flapping, other = self.dead("waiting"), self.dead("waiting")
        self.queue(flapping, other)
        holds = {}
        self.actions[("need", 0)] = lambda: holds.update(proc=self.holder(self.lock_file(flapping)))
        self.actions[("warn", 0)] = lambda: self.kill(holds["proc"])
        code, out = self.round()
        self.assertEqual((code, self.entries()), (0, [flapping]))
        self.assertRegex(self.rows()[1]["text"], r": still no living lock holder, deleted at \d\d:\d\d: test-2; held by a living process, not deleted: test-1\.$")
        self.ends(out, ": deleted test-2; not deleted, alive at the security test-1; left the queue none")

    def test_a_job_living_again_replaced_or_gone_by_the_delete_is_left_alone(self):
        revived, replaced, gone = self.dead("waiting"), self.dead("active"), self.dead("waiting")
        self.queue(revived, replaced, gone)
        swap = {**self.dead("active"), "id": replaced["id"]}

        def act() -> None:
            self.holder(self.lock_file(revived))
            self.queue(revived, swap)

        code, out, _ = self.at_the_close(act)
        self.assertEqual((code, self.entries()), (0, [revived, swap]))
        self.ends(out, ": deleted none; held by a living process, not deleted test-1; left the queue test-2, test-3")

    def test_an_entry_replaced_in_the_first_window_is_no_candidate_for_the_security(self):
        old = self.dead("waiting")
        self.queue(old)
        replaced = {**self.dead("waiting"), "id": old["id"]}
        self.actions[("need", 0)] = lambda: self.queue(replaced)
        code, out = self.round()
        self.assertEqual((code, self.entries(), self.classes()), (0, [replaced], ["pan-pan", "post"]))
        self.ends(out, ": deleted none; left the queue test-1")

    def test_a_dead_job_queued_after_the_snapshot_is_neither_named_nor_deleted(self):
        old, new = self.dead("waiting"), self.dead("waiting")
        self.queue(old)
        self.actions[("need", 0)] = lambda: self.queue(old, new)
        code, out = self.round()
        self.assertEqual((code, self.entries()), (0, [new]))
        self.ends(out, ": deleted test-1; left the queue none")
        self.assertNotIn("test-2", " ".join(row["text"] for row in self.rows()))

    def test_malformed_entries_stay_counted_and_block_no_round(self):
        job = self.dead("waiting")
        odd = [1, {"id": "x"}, {"seq": 2, "status": "waiting", "kind": "test", "lock": "2-2"},
               {"id": 5, "status": "waiting", "kind": "test", "lock": "3-3"}, {"id": "y", "status": "waiting", "lock": "4-4"},
               {"id": "z", "status": "waiting", "kind": "test"}, {**self.dead("waiting"), "status": "done"}]
        self.queue(job, *odd)
        code, out = self.round()
        self.assertEqual((code, self.entries()), (0, odd))
        self.ends(out, f": deleted {job['id']}; left the queue none")
        self.assertIn(" 0 held and 0 unclear jobs, 7 malformed entries stay; ", self.rows()[0]["text"])

    def test_the_alarms_stay_bounded_for_50_long_ids(self):
        ids = [f"test-nostack-{1000 + n}-" + "x" * 50 for n in range(50)]
        state = {"round": "12:00", "chair": "Main", "jobs": [{"id": i, "lock": f"{n}-{n}", "status": "waiting", "kind": "test"}
                 for n, i in enumerate(ids)], "held": ids, "unclear": ids, "malformed": 3, "deadline": time.time() + WINDOW,
                 "window": WINDOW, "delete": ids}
        for text in (self.cleanup.ask(state), self.cleanup.warn(state)):
            with self.subTest(text=text[:40]):
                self.assertLess(len(text), self.cleanup.watch.CLIP)
                self.assertIn(", +44 more", text)

    def test_each_window_lasts_its_length_on_both_clocks_from_its_own_alarm(self):
        cases = (
            ("wall ahead within the stall limit", {("need", 0): (100, 0)}, 900, 900),
            ("wall back", {("need", 0): (-600, 0)}, 1500, 900),
            ("monotonic ahead", {("need", 0): (0, 2000)}, 900, 900),
            ("monotonic ahead in the second window", {("warn", 0): (0, 2000)}, 900, 900),
        )
        for name, jumps, need, warn in cases:
            with self.subTest(name):
                self.slept.clear()
                self.jumps = jumps
                self.queue(self.dead("waiting"))
                self.assertEqual(self.round()[0], 0)
                self.assertGreaterEqual(self.waited("need"), need)
                self.assertGreaterEqual(self.waited("warn"), warn)
                self.assertEqual(self.entries(), [])

    def test_a_killed_round_counts_as_dead_and_blocks_no_next_one(self):
        self.queue(self.dead("waiting"))

        def die() -> None:
            raise Killed

        self.actions[("need", 0)] = die
        with contextlib.suppress(Killed), contextlib.redirect_stdout(io.StringIO()):
            self.cleanup.run_round(WINDOW, self.clock)
        self.actions = {}
        self.assertEqual(self.round()[0], 3)
        self.clock.wall += self.cleanup.DEAD_SECONDS + 1
        self.assertEqual(self.cli("status")[1], "no open round\n")
        code, out = self.round()
        self.assertEqual((code, self.classes().count("pan-pan")), (0, 2))
        self.ends(out, ": deleted test-1; left the queue none")

    def test_a_stall_above_the_dead_limit_ends_the_round_without_deleting(self):
        job = self.dead("active")
        self.queue(job)
        self.jumps[("need", 5)] = (self.cleanup.DEAD_SECONDS + 30, 0)
        code, out = self.round()
        self.assertEqual((code, self.ids()), (0, [job["id"]]))
        self.ends(out, f": not deleted, the round stalled for {self.cleanup.DEAD_SECONDS + 35} s {job['id']}; left the queue none")
        self.assertEqual(self.register()["status"], "stopped")

    def test_a_gap_of_exactly_the_dead_limit_is_no_stall(self):
        self.queue(self.dead("waiting"))
        self.jumps[("need", 5)] = (self.cleanup.DEAD_SECONDS - self.cleanup.POLL_SECONDS, 0)
        code, out = self.round()
        self.assertEqual((code, self.entries()), (0, []))
        self.ends(out, ": deleted test-1; left the queue none")

    def test_the_round_age_limits_are_inclusive(self):
        cleanup, beat = self.cleanup, 1000.0
        dead = cleanup.DEAD_SECONDS
        self.assertTrue(cleanup.alive({"phase": "warn", "beat": beat}, beat + dead))
        self.assertFalse(cleanup.alive({"phase": "warn", "beat": beat}, beat + dead + 1))
        self.assertFalse(cleanup.alive({"phase": "closing", "beat": beat}, beat))
        self.assertTrue(cleanup.busy({"phase": "closing", "beat": beat}, beat + dead))
        self.assertFalse(cleanup.busy({"phase": "closing", "beat": beat}, beat + dead + 1))
        self.assertFalse(cleanup.busy({"phase": "done", "beat": beat}, beat))
        self.assertFalse(cleanup.busy({}, beat))
        self.assertIsNone(cleanup.stalled({"beat": beat}, beat + dead))
        self.assertEqual(cleanup.stalled({"beat": beat}, beat + dead + 1), f"the round stalled for {dead + 1} s")

    def test_a_round_taken_over_by_a_newer_one_stops_without_deleting(self):
        job = self.dead("waiting")
        self.queue(job)
        self.actions[("need", 2)] = lambda: self.write_state({**self.state(), "start": self.state()["start"] + 1})
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = self.cleanup.run_round(WINDOW, self.clock)
        self.assertEqual((code, self.entries(), self.classes()), (0, [job], ["pan-pan"]))
        self.assertEqual(err.getvalue(), "queue-cleanup: a newer round took over this one; nothing more is deleted\n")

    def test_radio_silence_at_the_start_on_a_poll_or_on_the_last_poll_deletes_nothing(self):
        for when in ("start", "poll", "last poll"):
            with self.subTest(when):
                (self.root / "radio-silence.json").unlink(missing_ok=True)
                (self.root / "news.jsonl").unlink(missing_ok=True)
                self.slept.clear()
                job = self.dead("waiting")
                self.queue(job)
                if when == "start":
                    self.silence()
                self.actions = {"poll": {("need", 1): self.silence}, "last poll": {("warn", self.last): self.silence}}.get(when, {})
                code, out = self.round()
                self.assertEqual((code, self.entries()), (0, [job]))
                self.ends(out, f": not deleted, radio silence by IAM holds {job['id']}; left the queue none")
                self.assertEqual(self.register()["status"], "stopped")
                expected = {"start": ["post"], "poll": ["pan-pan", "post"], "last poll": ["pan-pan", "security", "post"]}
                self.assertEqual(self.classes(), expected[when])

    def test_radio_silence_found_by_the_close_deletes_nothing(self):
        job = self.dead("waiting")
        self.queue(job)
        code, out, _ = self.at_the_close(self.silence)
        self.assertEqual((code, self.entries()), (0, [job]))
        self.ends(out, f": not deleted, radio silence by IAM holds {job['id']}; left the queue none")

    def test_a_stall_after_the_closing_publish_deletes_nothing(self):
        job = self.dead("active")
        self.queue(job)

        def stall() -> None:
            self.clock.wall += self.cleanup.DEAD_SECONDS + 10

        code, out, _ = self.at_the_close(stall)
        self.assertEqual((code, self.ids()), (0, [job["id"]]))
        self.ends(out, f": not deleted, the round stalled for {self.cleanup.DEAD_SECONDS + 10} s {job['id']}; left the queue none")

    def test_a_newer_round_found_right_before_the_delete_deletes_nothing(self):
        job = self.dead("waiting")
        self.queue(job)
        code, _, err = self.at_the_close(lambda: self.write_state({**self.state(), "start": self.state()["start"] + 1}))
        self.assertEqual((code, self.entries(), self.classes()), (0, [job], ["pan-pan", "security"]))
        self.assertEqual(err, "queue-cleanup: a newer round took over this one; nothing more is deleted\n")

    def test_an_unexpected_error_after_the_claim_stops_the_round_posts_once_and_fails(self):
        job = self.dead("waiting")
        self.queue(job)
        err = io.StringIO()
        with mock.patch.object(self.cleanup, "standing", side_effect=RuntimeError("boom")), contextlib.redirect_stderr(err), \
                contextlib.redirect_stdout(io.StringIO()):
            code = self.cleanup.run_round(WINDOW, self.clock)
        self.assertEqual((code, self.entries()), (1, [job]))
        self.assertEqual(self.classes(), ["pan-pan", "post"])
        self.assertRegex(self.rows()[-1]["text"], r"^queue cleanup \d\d:\d\d: the round failed \(RuntimeError\); nothing more is deleted$")
        self.assertEqual((self.state()["phase"], self.register()["status"]), ("stopped", "stopped"))
        self.assertIn("RuntimeError('boom')", err.getvalue())
        self.assertEqual(self.round()[0], 0)

    def test_a_queue_store_gone_invalid_mid_round_stops_it_posts_once_and_fails(self):
        cases = {"invalid JSON": ("{", "SystemExit"), "too deep": ("[" * 100000 + "]" * 100000, "RecursionError"),
                 "no entries": ("{}", "KeyError"), "a list": ("[]", "TypeError")}
        for name, (text, kind) in cases.items():
            with self.subTest(name):
                (self.root / "news.jsonl").unlink(missing_ok=True)
                self.slept.clear()
                self.queue(self.dead("waiting"))
                self.actions = {("need", 0): lambda text=text: (self.root / "queue.json").write_text(text, encoding="utf-8")}
                with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
                    code = self.cleanup.run_round(WINDOW, self.clock)
                self.assertEqual((code, self.classes()), (1, ["pan-pan", "post"]))
                self.assertRegex(self.rows()[-1]["text"], rf"^queue cleanup \d\d:\d\d: the round failed \({kind}\); nothing more is deleted$")
                self.assertEqual((self.state()["phase"], self.register()["status"]), ("stopped", "stopped"))
                self.assertEqual((self.root / "queue.json").read_text(encoding="utf-8"), text)

    def test_a_queue_lock_won_past_the_stall_limit_or_after_a_newer_round_deletes_nothing(self):
        original = self.cleanup.queue.store
        cases = {
            "stall": (lambda: setattr(self.clock, "wall", self.clock.wall + self.cleanup.DEAD_SECONDS + 10),
                      f": not deleted, the round stalled for {self.cleanup.DEAD_SECONDS + 10} s test-1; left the queue none\n"),
            "newer round": (lambda: self.write_state({**self.state(), "start": self.state()["start"] + 1}), ""),
        }
        for name, (wait, tail) in cases.items():
            with self.subTest(name):
                job = self.dead("waiting")
                self.queue(job)

                @contextlib.contextmanager
                def slow(wait=wait):
                    if (self.kept / "queue-cleanup.json").exists() and self.state()["phase"] == "closing":
                        wait()
                    with original() as data:
                        yield data

                with mock.patch.object(self.cleanup.queue, "store", slow):
                    code, out = self.round()
                self.assertEqual((code, self.entries()), (0, [job]))
                self.assertTrue(out.endswith(tail), out)

    def test_status_shows_the_phase_and_each_judged_job(self):
        self.queue(self.dead("waiting"), self.held("active"), {**self.dead("waiting"), "lock": "x"})
        shown = {}
        self.actions[("need", 1)] = lambda: shown.update(status=self.cli("status"))
        self.round()
        lines = shown["status"][1].splitlines()
        self.assertRegex(lines[0], r"^round \d\d:\d\d need until \d\d:\d\d$")
        self.assertEqual(lines[1:], ["test-1 waiting test delete", "test-2 held", "test-3 unclear"])
        code, out, _ = self.cli("status")
        self.assertEqual(code, 0)
        self.assertRegex(out, r"^no open round; last: queue cleanup \d\d:\d\d: deleted test-1; left the queue none\n$")

    def test_the_round_lands_in_the_register_with_the_chair_accountable(self):
        self.queue(self.dead("waiting"))
        self.round()
        row = self.register()
        self.assertEqual(
            (row["status"], row["worker"], row["roles"], row["objective"]),
            ("done", WORKER, {"Main": "A", WORKER: "R"}, self.cleanup.OBJECTIVE),
        )
        self.assertTrue(row["description"].endswith(": deleted test-1; left the queue none"))

    def test_a_chair_gone_before_the_delete_stops_the_round_and_deletes_nothing(self):
        job = self.dead("waiting")
        self.queue(job)
        self.actions[("warn", 0)] = lambda: self.chair("gone")
        code, out = self.round()
        self.assertEqual((code, self.entries()), (0, [job]))
        self.ends(out, ": not deleted, the chair gone is stale test-1; left the queue none")
        self.assertEqual(self.register()["status"], "stopped")

    def test_a_second_round_refuses_while_one_runs(self):
        self.queue(self.dead("waiting"))
        inner = {}
        self.actions[("need", 0)] = lambda: inner.update(need=self.round()[0])
        self.actions[("warn", 0)] = lambda: inner.update(warn=self.round()[0])
        self.round()
        self.assertEqual(inner, {"need": 3, "warn": 3})
        self.assertEqual(self.classes(), ["pan-pan", "security", "post"])

    def test_run_refuses_an_agent_session_a_short_window_and_a_read_only_host_state(self):
        self.queue(self.dead("waiting"))
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ID": "s1"}):
            inside = self.cli("run", "--window", "900")
        short = self.cli("run", "--window", "899")
        self.kept.chmod(0o500)
        self.addCleanup(self.kept.chmod, 0o700)
        sandboxed = self.cli("run", "--window", "900")
        self.assertEqual(inside, (2, "", "queue-cleanup: run starts from kvb-org-queue-cleanup.service, never in an agent session; agents use request\n"))
        self.assertEqual(short, (2, "", "queue-cleanup: --window must be at least 900 seconds\n"))
        self.assertEqual(sandboxed, (2, "", f"queue-cleanup: cannot write {self.kept}; run starts outside the sandbox only\n"))
        self.assertEqual(self.rows(), [])
        self.assertFalse((self.kept / "queue-cleanup.json").exists())

    def test_request_needs_the_path_unit_and_appends_in_place(self):
        request = self.root / "queue-cleanup.request"
        unit = self.home / ".config" / "systemd" / "user" / "kvb-org-queue-cleanup.path"
        self.assertEqual(self.cli("request"), (2, "", f"queue-cleanup: {unit} is missing, so no round would start; make install enables it\n"))
        self.assertFalse(request.exists())
        self.install_unit()
        code, out, _ = self.cli("request")
        self.assertEqual((code, out), (0, f"requested a queue-cleanup round through {request}\n"))
        inode = request.stat().st_ino
        self.cli("request")
        self.assertEqual((request.stat().st_ino, len(request.read_text(encoding="utf-8").splitlines())), (inode, 2))
        self.assertIn("PathModified=/tmp/agents-council/queue-cleanup.request\n", unit.read_text(encoding="utf-8"))

    def test_request_refuses_during_a_round_and_for_30_minutes_after_one(self):
        self.install_unit()
        now, clock = self.clock.wall, self.cleanup.radio.clock
        self.write_state({"round": "12:00", "start": now - 100, "beat": now, "phase": "closing"})
        self.assertEqual(self.cli("request"), (2, "", "queue-cleanup: round 12:00 runs; status shows it\n"))
        ended = now - 600
        self.write_state({"round": "12:00", "start": now - 2000, "beat": ended, "phase": "done", "end": ended})
        self.assertEqual(
            self.cli("request"),
            (2, "", f"queue-cleanup: the last round ended at {clock(ended)}; request again from {clock(ended + 1800)}\n"),
        )
        self.write_state({"round": "12:00", "start": now - 4000, "beat": now - 1800, "phase": "done", "end": now - 1800})
        self.assertEqual(self.cli("request")[0], 0)

    def test_the_units_run_at_midnight_and_noon_without_catch_up_and_outlast_both_windows(self):
        timer = (SYSTEMD / "kvb-org-queue-cleanup.timer").read_text(encoding="utf-8")
        service = (SYSTEMD / "kvb-org-queue-cleanup.service").read_text(encoding="utf-8")
        self.assertIn("OnCalendar=*-*-* 00,12:00:00\nPersistent=false\n", timer)
        self.assertIn("Type=oneshot\n", service)
        window = int(re.search(r"^ExecStart=/usr/bin/python3 -I \S+/cleanup\.py run --window (\d+)$", service, re.MULTILINE)[1])
        self.assertEqual(window, WINDOW)
        budget = 2 * window + 4 * self.cleanup.POLL_SECONDS
        self.assertGreater(int(re.search(r"^TimeoutStartSec=(\d+)$", service, re.MULTILINE)[1]), budget)


if __name__ == "__main__":
    unittest.main()
