from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import hub_support  # noqa: F401
import sessions
import settings_writer
import staged_diff

ENV = {"PATH": "/usr/bin:/bin", "HOME": "/nonexistent", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}


class TestHostWrites(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)

    def test_an_unchanged_sessions_snapshot_is_rewritten_only_after_the_refresh(self):
        output = self.base / "agent-sessions.json"
        data = {"written": 1000.0, "sessions": {"s1": {"name": "One", "running": True}}}
        sessions.write(output, data)
        first = output.stat().st_ino
        sessions.write(output, {**data, "written": 1000.0 + sessions.REFRESH - 1})
        self.assertEqual((output.stat().st_ino, json.loads(output.read_text(encoding="utf-8"))["written"]), (first, 1000.0))
        sessions.write(output, {**data, "written": 1000.0 + sessions.REFRESH})
        self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["written"], 1000.0 + sessions.REFRESH)
        changed = {"written": 1000.0 + sessions.REFRESH + 1, "sessions": {}}
        sessions.write(output, changed)
        self.assertEqual(json.loads(output.read_text(encoding="utf-8")), changed)

    def test_a_settings_view_that_differs_only_in_its_stamp_stays(self):
        folder = self.base / "firewall"
        folder.mkdir(mode=0o700)
        path = folder / "view.json"
        view = {"written": 1.0, "files": [{"path": "/x", "exists": True}], "known": []}
        settings_writer.write_view(path, view)
        first = path.stat().st_ino
        settings_writer.write_view(path, {**view, "written": 2.0})
        self.assertEqual((path.stat().st_ino, json.loads(path.read_text(encoding="utf-8"))["written"]), (first, 1.0))
        settings_writer.write_view(path, {**view, "written": 3.0, "known": ["server"]})
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["known"], ["server"])

    def test_a_toplevel_comes_from_git_once_until_head_moves(self):
        repo = self.base / "repo"
        sub = repo / "a" / "b"
        sub.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], env=ENV, check=True)
        staged_diff.TOPLEVELS.clear()
        with mock.patch.object(staged_diff, "git", wraps=staged_diff.git) as calls:
            self.assertEqual((staged_diff.toplevel(sub), staged_diff.toplevel(sub)), (repo.resolve(), repo.resolve()))
            self.assertEqual(calls.call_count, 1)
            subprocess.run(["git", "symbolic-ref", "HEAD", "refs/heads/other"], cwd=repo, env=ENV, check=True)
            self.assertEqual(staged_diff.toplevel(sub), repo.resolve())
            self.assertEqual(calls.call_count, 2)


if __name__ == "__main__":
    unittest.main()
