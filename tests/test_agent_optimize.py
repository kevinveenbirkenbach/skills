"""Exercise agents.py: runtime-specific files, dead links, index pointer, binary and snapshot state."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "skills" / "kvb-agent-optimize" / "scripts" / "agents.py"
GIT = shutil.which("git")


class TestAgents(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        os.symlink(GIT, self.bin / "git")

    def _run(self, repo: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--repo", str(repo)],
            capture_output=True,
            text=True,
            env={"PATH": str(self.bin), "HOME": str(self.tmp)},
            check=False,
        )

    def _report(self, repo: Path) -> dict[str, tuple[str, str]]:
        result = self._run(repo)
        self.assertEqual(result.returncode, 0, result.stderr)
        return {check: (state, detail) for check, state, detail in (line.split("\t") for line in result.stdout.splitlines())}

    def test_ready_repository_with_drift(self):
        repo = self.tmp / "repo"
        (repo / "docs").mkdir(parents=True)
        (repo / "docs" / "a.md").write_text("a", encoding="utf-8")
        (repo / "AGENTS.md").write_text(
            "Query codebase-memory-mcp first. [a](docs/a.md) [b](docs/b.md#x) [web](https://x.org) [top](#top)\n",
            encoding="utf-8",
        )
        (repo / "CLAUDE.md").write_text("@AGENTS.md\n", encoding="utf-8")
        (repo / "GEMINI.md").write_text("own rules\n", encoding="utf-8")
        (repo / ".claude").mkdir()
        (repo / ".claude" / "CLAUDE.md").write_text("x\n", encoding="utf-8")
        (repo / "CLAUDE.local.md").write_text("x\n", encoding="utf-8")
        (repo / ".codebase-memory").mkdir()
        (repo / ".codebase-memory" / "graph.db.zst").write_bytes(b"x")
        (repo / ".gitignore").write_text(".codebase-memory/\n", encoding="utf-8")
        subprocess.run([GIT, "init", "-q"], cwd=repo, check=True)
        executable = self.bin / "codebase-memory-mcp"
        executable.write_text("#!/bin/sh\n", encoding="utf-8")
        executable.chmod(0o755)
        self.assertEqual(
            self._report(repo),
            {
                "AGENTS.md": ("ok", "single source of the agent instructions"),
                "CLAUDE.md": ("drift", "runtime-specific; fold into AGENTS.md and remove"),
                ".claude/CLAUDE.md": ("drift", "runtime-specific; fold into AGENTS.md and remove"),
                "CLAUDE.local.md": ("drift", "runtime-specific; fold into AGENTS.md and remove"),
                "GEMINI.md": ("drift", "runtime-specific; fold into AGENTS.md and remove"),
                "links": ("drift", "docs/b.md"),
                "index-pointer": ("ok", "AGENTS.md names codebase-memory-mcp"),
                "index-binary": ("ok", "codebase-memory-mcp on PATH"),
                "snapshot": ("ignored", ".codebase-memory/graph.db.zst"),
            },
        )

    def test_bare_directory(self):
        report = self._report(self.tmp)
        self.assertEqual(
            {check: state for check, (state, _) in report.items()},
            {
                "AGENTS.md": "missing",
                "links": "ok",
                "index-pointer": "missing",
                "index-binary": "missing",
                "snapshot": "missing",
            },
        )

    def test_missing_repository_exits_2(self):
        self.assertEqual(self._run(self.tmp / "none").returncode, 2)


if __name__ == "__main__":
    unittest.main()
