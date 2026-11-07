from __future__ import annotations

import ast
import datetime
import json
import os
import unittest

from hub_case import HubCase
from hub_support import HUB, PAGE

GENERATED = datetime.datetime(2026, 11, 6, 12, tzinfo=datetime.UTC).timestamp()


def starts_git(path) -> list[int]:
    lines = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.split(" ")[0] in ("git", "/usr/bin/git"):
            lines.append(node.lineno)
    return lines


class TestHubTree(HubCase):
    def test_tree_serves_the_pkgmgr_file_with_workers_and_reviews(self):
        root = self.write_tree()
        demo, feature = f"{root}/repos/github.com/me/demo", f"{root}/worktrees/github.com/me/demo/feature"
        self.write_council({"rasci.json": {"work/feature": {"title": "F", "status": "running", "worker": "Skills session", "workdir": feature}}})
        self.tool("review_request", {**self.arguments("feat: tree", "", self.page("tree.html", PAGE)), "worktree": feature, "branch": "feature"})
        status, _, body = self.get("/api/tree")
        self.assertEqual(status, 200, body)
        data = json.loads(body)
        repos = {entry["path"]: entry for entry in data["repos"]}
        self.assertEqual((repos[demo]["name"], repos[demo]["known"], repos[f"{root}/outside/elsewhere"]["known"]), ("github.com/me/demo", True, False))
        self.assertEqual((data["scanned"], data["delete_ready"], data["delete_reason"]), (GENERATED, False, "Secret Service locked"))
        branches = {entry["name"]: entry for entry in repos[demo]["branches"]}
        main = branches["main"]
        self.assertEqual((main["upstream"], main["ahead"], main["behind"], main["gone"], main["state"]), ("origin/main", 1, 0, False, "protected"))
        self.assertEqual((branches["feature"]["state"], branches["feature"]["reason"]), ("dirty", "dirty: 1 paths"))
        trees = [(tree["path"], tree["dirty"], tree["untracked"], tree["workers"], tree["review"]) for tree in main["worktrees"] + branches["feature"]["worktrees"]]
        self.assertEqual(trees, [(demo, False, 0, [], None), (feature, True, 1, ["Skills"], {"status": "pending", "gate": "pass", "title": "feat: tree"})])
        self.assertEqual([(tree["path"], tree["workers"]) for tree in repos[demo]["detached"]], [(f"{root}/worktrees/github.com/me/demo/detached", [])])

    def test_tree_reads_the_file_again_once_it_changes(self):
        self.write_tree()
        self.assertEqual(len(json.loads(self.get("/api/tree")[2])["repos"]), 2)
        data = json.loads(self.tree_file.read_text(encoding="utf-8"))
        data["repos"] = data["repos"][:1]
        self.tree_file.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(len(json.loads(self.get("/api/tree")[2])["repos"]), 1)

    def test_a_missing_or_broken_file_answers_with_the_reason(self):
        status, _, body = self.get("/api/tree")
        self.assertEqual(status, 200, body)
        self.assertEqual((json.loads(body)["repos"], json.loads(body)["scanned"]), ([], None))
        self.assertIn("no pkgmgr tree file", json.loads(body)["error"])
        self.tree_file.write_text('{"repos": [{"path": "/x"}]}', encoding="utf-8")
        self.assertIn("unreadable", json.loads(self.get("/api/tree")[2])["error"])

    def test_the_state_poll_beats_the_heartbeat_the_tree_timer_waits_for(self):
        heartbeat = self.state / "tree-heartbeat"
        self.assertFalse(heartbeat.exists())
        self.snapshot()
        self.assertTrue(heartbeat.is_file())
        os.utime(heartbeat, (0, 0))
        self.snapshot()
        self.assertGreater(heartbeat.stat().st_mtime, 0)

    def test_no_module_of_the_orchestrator_starts_git(self):
        sources = [HUB / "server.py", *sorted((HUB / "kvb_orchestrator").glob("*.py"))]
        found = {path.name: starts_git(path) for path in sources}
        self.assertEqual({name: lines for name, lines in found.items() if lines}, {})


if __name__ == "__main__":
    unittest.main()
