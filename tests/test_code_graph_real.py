from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "skills" / "kvb-agent-optimize" / "scripts" / "graph.py"
BINARY = os.environ.get("KVB_CODE_GRAPH_BIN") or shutil.which("codebase-memory-mcp")
QUEUED = os.environ.get("KVB_CODE_GRAPH_INTEGRATION") == "1"
REASON = (
    "real codebase-memory-mcp run: needs the binary, a permanent daemon, write access to its cache root "
    "(outside the agent sandbox) and KVB_CODE_GRAPH_INTEGRATION=1, which only the operator's command line sets"
)
PROBE = "kvb_graph_probe_marker"
LATER = "kvb_graph_probe_later"
INDEX_SECONDS = 300
WATCH_SECONDS = 120
GIT_ENV = {
    "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.invalid", "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
}


def load_graph():
    spec = importlib.util.spec_from_file_location("kvb_code_graph_real", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GRAPH = load_graph()


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, env={**os.environ, **GIT_ENV}, check=True, capture_output=True, text=True)


def until(check, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(1)
    return check()


@unittest.skipUnless(QUEUED and BINARY, REASON)
class TestCodeGraphReal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        status = subprocess.run([BINARY, "daemon", "status"], capture_output=True, text=True, timeout=30, check=False)
        if "permanent" not in status.stdout:
            raise unittest.SkipTest(f"no permanent daemon: {status.stdout.strip() or status.stderr.strip()}")

    def setUp(self):
        work = tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.work = Path(work.name).resolve()
        origin = self.work / "origin"
        origin.mkdir()
        git(origin, "init", "-q", "-b", "main")
        (origin / "probe.py").write_text(f"def {PROBE}():\n    return 1\n\n\ndef caller():\n    return {PROBE}()\n", encoding="utf-8")
        git(origin, "add", "-A")
        git(origin, "commit", "-q", "-m", "base")
        self.clone = self.work / "clone"
        git(self.work, "clone", "-q", str(origin), str(self.clone))
        self.root = str(self.clone)
        self.project = GRAPH.project_name(self.root)
        self.state = self.work / "state"
        config = self.work / "config.json"
        config.write_text(json.dumps({"queue_file_threshold": 10000, "queue_task": "work/code-graph-index"}), encoding="utf-8")
        self.env = {**os.environ, "KVB_CODE_GRAPH_STATE": str(self.state), "KVB_CODE_GRAPH_CONFIG": str(config), "KVB_CODE_GRAPH_BIN": BINARY}
        self.addCleanup(self.forget)

    def forget(self) -> None:
        self.mcp(str(self.work), "delete_project", {"project": self.project})

    def mcp(self, cwd: str, name: str, arguments: dict) -> dict:
        """Args:
            cwd: the root the stdio session starts in; it is the session's
                project.
            name: the tool to call once.
            arguments: its arguments.
        """
        session = GRAPH.Session(BINARY, cwd)
        try:
            end = time.monotonic() + 120
            session.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "kvb-code-graph-test", "version": "1"}}, end)
            session.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
            return session.tool(name, arguments, end)
        finally:
            session.close()

    def hook(self, session: str, cwd: Path, path: Path) -> None:
        event = {"session_id": session, "cwd": str(cwd), "tool_input": {"file_path": str(path)}}
        done = subprocess.run([sys.executable, "-I", str(SCRIPT), "hook"], input=json.dumps(event), env=self.env, capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(done.returncode, 0, done.stderr)

    def log(self, suffix: str) -> str:
        path = self.state / "logs" / f"{self.project}{suffix}"
        return path.read_text(encoding="utf-8") if path.is_file() else ""

    def indexed_by_helper(self) -> None:
        settled = until(lambda: f"graph: {self.root} succeeded" in self.log(".index.log"), INDEX_SECONDS)
        self.assertTrue(settled, f"{self.log('.log')}\n{self.log('.index.log')}")
        self.assertTrue(GRAPH.indexed(self.root))

    def entries(self) -> list[dict]:
        listed = self.mcp(str(self.work), "list_projects", {"format": "json", "detail": "stats", "limit": 500})
        return [entry for entry in listed["projects"] if entry["root_path"] == self.root]

    def test_code_graph_fresh_clone(self):
        self.hook("first", self.clone, self.clone / "probe.py")
        self.assertIn("graph: spawn", self.log(".log"))
        self.indexed_by_helper()
        entries = self.entries()
        self.assertEqual(len(entries), 1, entries)
        self.assertGreater(entries[0]["nodes"], 0, entries)
        found = self.mcp(self.root, "search_graph", {"project": self.project, "name_pattern": PROBE, "format": "json"})
        self.assertIn(PROBE, json.dumps(found))
        decided, ran = self.log(".log"), self.log(".index.log")
        self.hook("second", self.clone, self.clone / "probe.py")
        self.assertEqual((self.log(".log"), self.log(".index.log")), (decided, ran))
        self.assertEqual(len(self.entries()), 1)

    def test_code_graph_helper_watch(self):
        plain = self.work / "plain"
        plain.mkdir()
        self.hook("other-root", plain, self.clone / "probe.py")
        self.indexed_by_helper()
        status = self.mcp(str(self.work), "index_status", {"project": self.project, "format": "json"})
        self.assertTrue(status["watch"]["watched"], status)
        (self.clone / "later.py").write_text(f"def {LATER}():\n    return 2\n", encoding="utf-8")
        git(self.clone, "add", "-A")
        git(self.clone, "commit", "-q", "-m", "later")

        def seen() -> bool:
            return LATER in json.dumps(self.mcp(str(self.work), "search_graph", {"project": self.project, "name_pattern": LATER, "format": "json"}))

        found = until(seen, WATCH_SECONDS)
        after = self.mcp(str(self.work), "index_status", {"project": self.project, "format": "json"})
        self.assertTrue(found, f"{LATER} not in the graph after {WATCH_SECONDS} s; before: {json.dumps(status)}; after: {json.dumps(after)}")
        self.assertEqual(self.log(".log").count("graph: spawn"), 1, self.log(".log"))


if __name__ == "__main__":
    unittest.main()
