"""Exercise kvb-check-ansible's bench: the synthetic carrier fact and a real run of the bench playbook."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ansible_support import BENCH, SCRIPT, LogCase, ansible_bench, ansible_log


class TestBenchCarrier(LogCase):
    def test_writes_exactly_the_asked_size(self):
        out = self.base / "carrier.json"
        result = self.run_script("bench-carrier", "--kb", "3", "--out", str(out))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(out.stat().st_size, 3 * 1024)
        fact = json.loads(out.read_text(encoding="ascii"))
        self.assertEqual(result.stdout, f"{out}\t3072 bytes\t{len(fact) - 1} entries\n")
        self.assertIn("pad", fact)
        for size in (1024, 1500, 400 * 1024):
            with self.subTest(size=size):
                self.assertEqual(len(json.dumps(ansible_bench.carrier(size))), size)
        self.assertGreater(len(ansible_bench.carrier(400 * 1024)), 100)

    def test_bench_inventory_pins_no_interpreter_path(self):
        self.assertNotRegex((BENCH / "hosts.yml").read_text(encoding="utf-8"), r"interpreter:\s*/")


@unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook not installed")
class TestBench(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        base = Path(tmp.name)
        carrier = base / "carrier.json"
        carrier.write_text(json.dumps(ansible_bench.carrier(8 * 1024)), encoding="ascii")
        cls.log = base / "bench.log"
        env = {
            "PATH": os.environ["PATH"],
            "HOME": str(base),
            "ANSIBLE_LOCAL_TEMP": str(base / "tmp"),
            "ANSIBLE_NOCOLOR": "1",
            "ANSIBLE_CALLBACKS_ENABLED": "ansible.posix.profile_tasks",
        }
        cls.result = subprocess.run(
            [
                "ansible-playbook", "-i", str(BENCH / "hosts.yml"), str(BENCH / "bench.yml"),
                "-e", "bench_count=3", "-e", f"bench_carrier_file={carrier}",
            ],
            cwd=base, env=env, capture_output=True, text=True, check=False,
        )
        cls.log.write_text(cls.result.stdout, encoding="utf-8")

    def test_runs_one_skipped_and_one_ran_task_per_item(self):
        self.assertEqual(self.result.returncode, 0, self.result.stdout + self.result.stderr)
        self.assertEqual(self.result.stdout.count("skipping: [bench]"), 3)
        self.assertEqual(self.result.stdout.count("included: "), 3)

    def test_profile_tasks_output_ranks_by_kind(self):
        if ansible_log.ELAPSED.search(self.result.stdout) is None:
            self.skipTest("ansible.posix.profile_tasks not installed")
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "kinds", "--log", str(self.log), "--json"],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        counts = {row["kind"]: row["count"] for row in json.loads(result.stdout)["kinds"]}
        self.assertEqual(counts, {"ran": 4, "skipped": 3, "included": 1})


if __name__ == "__main__":
    unittest.main()
