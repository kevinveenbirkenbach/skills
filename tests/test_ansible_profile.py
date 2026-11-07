"""Exercise kvb-check-ansible's controller profiler and its profile-report subcommand."""

from __future__ import annotations

import cProfile
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ansible_support import PROFILE_DIR, LogCase

FORKING = (
    "import multiprocessing\n"
    "def work():\n"
    "    return sum(range(1000))\n"
    "if __name__ == '__main__':\n"
    "    child = multiprocessing.get_context('fork').Process(target=work)\n"
    "    child.start()\n"
    "    child.join()\n"
)


def busy() -> int:
    return sum(number * number for number in range(20000))


class TestProfileReport(LogCase):
    def setUp(self):
        super().setUp()
        self.profiles = self.base / "profiles"
        self.profiles.mkdir()
        for name in ("main-1.prof", "worker-2.prof", "worker-3.prof"):
            profiler = cProfile.Profile()
            profiler.enable()
            busy()
            profiler.disable()
            profiler.dump_stats(self.profiles / name)

    def test_merges_main_and_worker_profiles(self):
        found = self.report("profile-report", "--dir", str(self.profiles), "--top", "3")
        self.assertEqual((found["main"]["profiles"], found["worker"]["profiles"]), (1, 2))
        for role, calls in (("main", 1), ("worker", 2)):
            with self.subTest(role=role):
                self.assertLessEqual(len(found[role]["cumulative"]), 3)
                self.assertLessEqual(len(found[role]["tottime"]), 3)
                rows = [row for row in found[role]["cumulative"] if row["function"].endswith("(busy)")]
                self.assertEqual([row["calls"] for row in rows], [calls])
        lines = self.lines("profile-report", "--dir", str(self.profiles), "--top", "2")
        self.assertRegex(lines[0], r"^== main: 1 profiles, \d+\.\d{3} s ==$")
        self.assertIn("-- tottime: cumtime, tottime, calls, function --", lines)
        self.assertTrue(any(line.startswith("== worker: 2 profiles") for line in lines))

    def test_dir_comes_from_the_environment_and_empty_exits_2(self):
        env = {"PATH": os.environ["PATH"], "ANSIBLE_PROFILE_DIR": str(self.profiles)}
        result = self.run_script("profile-report", "--top", "1", env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.startswith("== main: 1 profiles"))
        empty = self.base / "empty"
        empty.mkdir()
        result = self.run_script("profile-report", "--dir", str(empty), "--top", "1")
        self.assertEqual(result.returncode, 2)
        self.assertIn("no main-*.prof or worker-*.prof", result.stderr)


class TestProfiler(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)

    def fork(self, program: str, **env: str) -> None:
        script = self.base / program
        script.write_text(FORKING, encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(script)],
            env={"PATH": os.environ["PATH"], "PYTHONPATH": str(PROFILE_DIR), "TMPDIR": str(self.base), **env},
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_ansible_playbook_and_its_workers_land_under_tmpdir(self):
        self.fork("ansible-playbook")
        out = self.base / "ansible-profile"
        self.assertEqual(len(list(out.glob("main-*.prof"))), 1)
        self.assertEqual(len(list(out.glob("worker-*.prof"))), 1)

    def test_profile_dir_wins_and_other_programs_stay_unprofiled(self):
        self.fork("ansible-playbook", ANSIBLE_PROFILE_DIR=str(self.base / "chosen"))
        self.assertEqual(len(list((self.base / "chosen").glob("*.prof"))), 2)
        self.fork("ansible", ANSIBLE_PROFILE_DIR=str(self.base / "other"))
        self.assertFalse((self.base / "other").exists())


if __name__ == "__main__":
    unittest.main()
