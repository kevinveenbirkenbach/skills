"""Shared paths, script modules, synthetic logs and the CLI test case of the kvb-check-ansible tests."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1] / "skills" / "kvb-check-ansible"
sys.path.insert(0, str(SKILL / "scripts"))

import ansible_bench
import ansible_log
import ansible_tables

__all__ = [
    "BENCH",
    "MIDNIGHT_LOG",
    "PROFILE_DIR",
    "PROFILE_LOG",
    "SCRIPT",
    "WALL_KINDS",
    "WALL_LOG",
    "LogCase",
    "ansible_bench",
    "ansible_log",
    "ansible_tables",
]

SCRIPT = SKILL / "scripts" / "ansible_tasks.py"
PROFILE_DIR = SKILL / "scripts" / "profile"
BENCH = SKILL / "bench"
STARS = " " + "*" * 40

WALL_LOG = "\n".join(
    [
        "2026-11-07T06:45:40.0000000Z PLAY [deploy]" + STARS,
        "2026-11-07T06:45:40.5000000Z TASK [setup : install]" + STARS,
        "2026-11-07T06:45:43.0000000Z \x1b[0;33mchanged: [host]\x1b[0m",
        "2026-11-07T06:45:44.0000000Z TASK [setup : check]" + STARS,
        "2026-11-07T06:45:44.1000000Z skipping: [host]",
        "2026-11-07T06:45:44.2Z TASK [setup : install]" + STARS,
        "2026-11-07T06:45:44.5000000Z skipping: [host] => (item=a)",
        "2026-11-07T06:45:45.0000000Z ok: [host] => (item=b)",
        "2026-11-07T06:45:45.700000000Z TASK [setup : include]" + STARS,
        "2026-11-07T06:45:45.8000000Z included: /x/y.yml for host",
        "2026-11-07T06:45:46.0 TASK [setup : flush]" + STARS,
        "2026-11-07T06:45:46.5000000Z [WARNING]: nothing to flush",
        "2026-11-07T06:45:46.8000000Z RUNNING HANDLER [setup : restart]" + STARS,
        "2026-11-07T06:45:48.0000000Z fatal: [host]: FAILED! => {}",
        "2026-11-07T06:45:48.0000000Z PLAY RECAP" + STARS,
        "2026-11-07T06:45:48.0000000Z host : ok=2 changed=1 skipped=1 failed=1",
    ]
) + "\n"

PROFILE_LINE = "Saturday 07 November 2026  06:45:40 +0000 ({})       0:00:00.020 " + "*" * 20
PROFILE_LOG = "\n".join(
    [
        "PLAY [deploy]" + STARS,
        "",
        "TASK [Gathering Facts]" + STARS,
        PROFILE_LINE.format("0:00:00.020"),
        "ok: [host]",
        "TASK [setup : install]" + STARS,
        PROFILE_LINE.format("0:00:02.000"),
        "changed: [host]",
        "TASK [setup : check]" + STARS,
        PROFILE_LINE.format("0:00:03.500"),
        "skipping: [host]",
        "TASK [setup : install]" + STARS,
        PROFILE_LINE.format("0:00:00.100"),
        "included: /x/y.yml for host",
        "RUNNING HANDLER [setup : restart]" + STARS,
        PROFILE_LINE.format("0:01:01.500"),
        "ok: [host]",
        "PLAY RECAP" + STARS,
        "host : ok=3 changed=1 skipped=1",
        "TASKS RECAP" + STARS,
        PROFILE_LINE.format("0:00:00.400"),
        "=" * 40,
        "setup : install ----------------------- 63.50s",
    ]
) + "\n"

MIDNIGHT_LOG = chr(0xFEFF) + "2026-11-07T23:59:59.5Z TASK [late]" + STARS + "\n2026-11-08T00:00:00.25Z PLAY RECAP" + STARS + "\n"

WALL_KINDS = [
    "kind\tcount\tsum\tmean\t<0.25\t<0.5\t<1\t<2\t>=2",
    "ran\t3\t6.2\t2.0667\t0\t0\t0\t2\t1",
    "other\t1\t0.8\t0.8000\t0\t0\t1\t0\t0",
    "included\t1\t0.3\t0.3000\t0\t1\t0\t0\t0",
    "skipped\t1\t0.2\t0.2000\t1\t0\t0\t0\t0",
]


class LogCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.wall = self.write("wall.log", WALL_LOG)
        self.profile = self.write("profile.log", PROFILE_LOG)

    def write(self, name: str, text: str) -> Path:
        path = self.base / name
        path.write_text(text, encoding="utf-8")
        return path

    def run_script(self, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args], capture_output=True, text=True, check=False, env=env
        )

    def lines(self, *args: str) -> list[str]:
        result = self.run_script(*args)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.splitlines()

    def report(self, *args: str) -> dict:
        result = self.run_script(*args, "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)
