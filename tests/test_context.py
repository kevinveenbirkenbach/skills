"""Exercise context.py: one count per message id, days, compactions and the threshold shares."""

from __future__ import annotations

import datetime
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "skills" / "kvb-skill-silence" / "scripts" / "context.py"


def turn(day: str, mid: str, cached: int) -> str:
    usage = {"input_tokens": 100, "cache_read_input_tokens": cached, "cache_creation_input_tokens": 0}
    return json.dumps({"timestamp": f"{day}T10:00:00Z", "message": {"id": mid, "usage": usage}})


class TestContext(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        today = datetime.datetime.now(datetime.UTC).date()
        self.today, self.yesterday = today.isoformat(), (today - datetime.timedelta(days=1)).isoformat()
        lines = [
            turn(self.today, "m1", 400_000),
            turn(self.today, "m1", 400_000),
            turn(self.today, "m2", 49_900),
            turn(self.yesterday, "m3", 599_900),
            json.dumps({"timestamp": f"{self.today}T11:00:00Z", "type": "system", "subtype": "compact_boundary"}),
            "not json",
        ]
        (self.root / "project").mkdir()
        (self.root / "project" / "session.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(self.root), *args], capture_output=True, text=True, check=False
        )

    def test_days_turns_compactions_and_shares(self):
        result = self._run("--days", "2", "--threshold", "300000", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        yesterday, today = json.loads(result.stdout)
        self.assertEqual(
            (yesterday["day"], yesterday["turns"], yesterday["compactions"], yesterday["over"]["300000"]),
            (self.yesterday, 1, 0, {"turns": 100, "tokens": 50}),
        )
        self.assertEqual(
            (today["day"], today["turns"], today["tokens"], today["compactions"], today["over"]["300000"]),
            (self.today, 2, 450_100, 1, {"turns": 50, "tokens": 22}),
        )

    def test_usage_errors_exit_2(self):
        self.assertEqual(self._run("--days", "0", "--threshold", "1").returncode, 2)
        self.assertEqual(self._run("--days", "1").returncode, 2)


if __name__ == "__main__":
    unittest.main()
