"""update.sh must reach every locked source and install for Claude Code only."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
UPDATE = REPO_ROOT / "scripts" / "update.sh"


@unittest.skipUnless(shutil.which("jq") and shutil.which("bash"), "jq or bash missing")
class TestUpdate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bin = Path(self.tmp.name)
        self.log = self.bin / "calls.log"
        npx = self.bin / "npx"
        npx.write_text(f'#!/bin/sh\ncat >/dev/null\necho "$@" >> "{self.log}"\n', encoding="utf-8")
        npx.chmod(0o755)
        for tool in ("jq", "sort"):
            (self.bin / tool).symlink_to(shutil.which(tool))

    def test_every_source_is_updated_for_claude_code_only(self):
        lock = json.loads((REPO_ROOT / "skills-lock.json").read_text(encoding="utf-8"))
        sources = sorted({entry["source"] for entry in lock["skills"].values()})
        subprocess.run(
            ["bash", str(UPDATE)],
            check=True,
            capture_output=True,
            env={"PATH": f"{self.bin}:/usr/bin:/bin"},
            stdin=subprocess.DEVNULL,
        )
        calls = self.log.read_text(encoding="utf-8").splitlines()
        self.assertEqual([c.split()[-1] for c in calls], sources)
        for call in calls:
            self.assertIn("--agent claude-code", call)


if __name__ == "__main__":
    unittest.main()
