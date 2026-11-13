from __future__ import annotations

import ast
import datetime
import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path

from hub_case import HubCase
from hub_support import GIT_ENV, HUB, PAGE

GENERATED = datetime.datetime(2026, 11, 6, 12, tzinfo=datetime.UTC).timestamp()
PKGMGR = shutil.which("pkgmgr")
FIXTURE = Path(__file__).parent / "branch-tree.json"


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

    @unittest.skipUnless(PKGMGR, "pkgmgr is not on PATH: the check that /api/tree serves a file pkgmgr branch tree wrote cannot run, install package-manager to cover 001 S12")
    def test_tree_serves_the_file_pkgmgr_branch_tree_wrote_for_a_fixture_repository_in_the_fields_of_the_fixture(self):
        root = Path(os.path.realpath(self.outside)) / "pkgmgr"
        home, origin, repo = root / "home", root / "origin.git", root / "repos" / "github.com" / "me" / "demo"
        repo.mkdir(parents=True)
        self.git(root, "init", "--bare", "-b", "main", str(origin))
        self.git(repo, "init", "-b", "main")
        self.git(repo, "remote", "add", "origin", str(origin))
        (repo / ".git" / "info" / "exclude").write_text(".worktrees/\n", encoding="utf-8")
        (repo / "init.txt").write_text("init\n", encoding="utf-8")
        self.git(repo, "add", "init.txt")
        self.git(repo, "commit", "-m", "init")
        self.git(repo, "switch", "-c", "feature/done")
        (repo / "done.txt").write_text("done\n", encoding="utf-8")
        self.git(repo, "add", "done.txt")
        self.git(repo, "commit", "-m", "done")
        self.git(repo, "switch", "main")
        self.git(repo, "merge", "--no-ff", "-m", "merge feature/done", "feature/done")
        self.git(repo, "push", "-u", "origin", "main")
        opened = repo / ".worktrees" / "feature" / "open"
        self.git(repo, "worktree", "add", "-b", "feature/open", str(opened), "main")
        (opened / "loose.txt").write_text("new\n", encoding="utf-8")
        config = home / ".config" / "pkgmgr" / "fixture.yml"
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps({"directories": {"repositories": str(root / "repos")}, "repositories": [{"provider": "github.com", "account": "me", "repository": "demo", "directory": str(repo)}]}), encoding="utf-8")
        env = {
            "PATH": os.environ["PATH"], "HOME": str(home), "LANG": "C.UTF-8", **GIT_ENV, "DBUS_SESSION_BUS_ADDRESS": f"unix:path={root / 'no-bus'}",
            "XDG_CACHE_HOME": str(home / ".cache"), "XDG_STATE_HOME": str(home / ".local" / "state"), "PKGMGR_TREE_FILE": str(self.tree_file),
        }
        done = subprocess.run([PKGMGR, "branch", "tree", "--format", "json", "--output", str(self.tree_file)], cwd=root, env=env, capture_output=True, text=True, timeout=300, check=False)
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        written = json.loads(self.tree_file.read_text(encoding="utf-8"))
        status, _, body = self.get("/api/tree")
        self.assertEqual(status, 200, body)
        data = json.loads(body)
        self.assertNotIn("error", data, data)
        self.assertEqual(data["scanned"], datetime.datetime.fromisoformat(written["generated_at"]).timestamp())
        self.assertEqual([(entry["path"], entry["name"], entry["known"]) for entry in data["repos"]], [(str(repo), "github.com/me/demo", True)])
        branches = {entry["name"]: entry for entry in data["repos"][0]["branches"]}
        self.assertEqual(sorted(branches), ["feature/done", "feature/open", "main"])
        self.assertEqual((branches["main"]["state"], branches["feature/done"]["state"], branches["feature/done"]["merged_by"]), ("protected", "merged-clean", "ancestor"))
        trees = [(tree["path"], tree["dirty"], tree["untracked"]) for tree in branches["feature/open"]["worktrees"]]
        self.assertEqual(trees, [(str(opened), True, 1)])
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.assertLessEqual(set(fixture), set(written))
        self.assertLessEqual({key for entry in fixture["repos"] for key in entry}, set(written["repos"][0]))
        self.assertLessEqual({key for entry in fixture["repos"] for item in entry["items"] for key in item}, {key for item in written["repos"][0]["items"] for key in item})

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
        for words in ("no pkgmgr tree file", "`pkgmgr branch tree`", "release pkgmgr"):
            with self.subTest(words=words):
                self.assertIn(words, json.loads(body)["error"])
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
