"""Exercise transcend.py: sources, secret and size filters, and the decision memory."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "skills" / "kvb-transcend" / "scripts" / "transcend.py"


class TestTranscend(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.home = root / "home"
        self.peers = root / "peers"
        self.own = self.peers / "proj" / "s1" / "scratchpad"
        self.peer = self.peers / "proj" / "s2" / "scratchpad"
        self.repo = root / "skills-repo"
        self.state = self.repo / ".state" / "transcend.json"
        for path in (self.own, self.peer, self.repo / "skills" / "kvb-x"):
            path.mkdir(parents=True)
        (self.repo / "skills-lock.json").write_text(
            json.dumps({"skills": {"caveman": {}}}), encoding="utf-8"
        )
        sessions = self.home / ".claude" / "sessions"
        sessions.mkdir(parents=True)
        (sessions / "s2.json").write_text(
            json.dumps({"sessionId": "s2", "name": "Peer"}), encoding="utf-8"
        )
        self._write(self.own / "probe.py", "print(1)")
        self._write(self.own / "test_probe.py", "assert True")
        self._write(self.own / "notes.log", "noise")
        self._write(self.own / "auth_token.py", "secret")
        self._write(self.own / "big.py", "x" * 1_000_001)
        self._write(self.peer / "helper.sh", "echo hi")
        self._write(self.peer / "probe" / "nested.py", "print(2)")
        self._write(self.peer / "probe" / "deep" / "too_deep.py", "print(3)")
        self._write(self.peer / "copy" / "pyproject.toml", "[project]")
        self._write(self.peer / "copy" / "copied.py", "print(4)")
        for name in ("kvb-x", "caveman", "custom"):
            self._write(self.home / ".claude" / "skills" / name / "SKILL.md", name)
        self._write(self.home / ".codex" / "rules" / "default.rules", "allow")

    def _write(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args], capture_output=True, text=True, check=False
        )

    def _scan(self) -> list[dict]:
        result = self._run(
            "scan",
            "--state", str(self.state),
            "--skills-repo", str(self.repo),
            "--session-dir", str(self.own),
            "--peers-root", str(self.peers),
            "--home", str(self.home),
            "--json",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def _found(self) -> dict[str, tuple[str, str, str]]:
        return {
            Path(i["path"]).name: (i["source"], i["owner"], i["kind"]) for i in self._scan()
        }

    def test_scan_finds_own_peer_and_home_candidates(self):
        self.assertEqual(
            self._found(),
            {
                "probe.py": ("own", "self", "script"),
                "test_probe.py": ("own", "self", "test"),
                "helper.sh": ("peer", "Peer", "script"),
                "nested.py": ("peer", "Peer", "script"),
                "custom": ("home", "operator", "skill"),
                "default.rules": ("home", "operator", "rule"),
            },
        )

    def test_settled_candidates_are_remembered_until_they_change(self):
        probe = self.own / "probe.py"
        self.assertEqual(self._run("mark", "--state", str(self.state), str(probe), "carried").returncode, 0)
        self._run("mark", "--state", str(self.state), str(self.own / "test_probe.py"), "later")
        found = {Path(i["path"]).name: i["previous"] for i in self._scan()}
        self.assertNotIn("probe.py", found)
        self.assertEqual(found["test_probe.py"], "later")

        probe.write_text("print(2)", encoding="utf-8")
        found = {Path(i["path"]).name: i["previous"] for i in self._scan()}
        self.assertEqual(found["probe.py"], "carried")

    def test_skill_directory_change_is_reoffered(self):
        custom = self.home / ".claude" / "skills" / "custom"
        self._run("mark", "--state", str(self.state), str(custom), "dropped")
        self.assertNotIn("custom", self._found())
        self._write(custom / "scripts" / "run.py", "print(3)")
        self.assertIn("custom", self._found())

    def test_invalid_input_exits_2(self):
        self.assertEqual(self._run("mark", "--state", str(self.state), "/no/such/path", "carried").returncode, 2)
        self.assertEqual(self._run("mark", "--state", str(self.state), str(self.own), "kept").returncode, 2)
        self.assertEqual(self._run("scan", "--state", str(self.state)).returncode, 2)
        self.assertFalse(self.state.exists())


if __name__ == "__main__":
    unittest.main()
