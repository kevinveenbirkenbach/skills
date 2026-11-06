from __future__ import annotations

import json
import unittest

from hub_case import HubCase
from hub_support import PAGE


class TestHubTree(HubCase):
    def test_tree_lists_repos_branches_and_worktrees(self):
        origin = self.outside / "origin.git"
        self.git(self.outside, "init", "--quiet", "--bare", "--initial-branch=main", str(origin))
        repo = self.repos / "github.com" / "me" / "demo"
        repo.mkdir(parents=True)
        self.git(repo, "init", "--quiet", "--initial-branch=main")
        (repo / "a.txt").write_text("a", encoding="utf-8")
        self.git(repo, "add", "a.txt")
        self.git(repo, "commit", "--quiet", "-m", "a")
        self.git(repo, "remote", "add", "origin", str(origin))
        self.git(repo, "push", "--quiet", "-u", "origin", "main")
        (repo / "b.txt").write_text("b", encoding="utf-8")
        self.git(repo, "add", "b.txt")
        self.git(repo, "commit", "--quiet", "-m", "b")
        feature = self.worktrees / "github.com" / "me" / "demo" / "feature"
        self.git(repo, "worktree", "add", "--quiet", "-b", "feature", str(feature))
        (feature / "dirty.txt").write_text("x", encoding="utf-8")
        other = self.outside / "elsewhere"
        other.mkdir()
        self.git(other, "init", "--quiet", "--initial-branch=main")
        (other / "c.txt").write_text("c", encoding="utf-8")
        self.git(other, "add", "c.txt")
        self.git(other, "commit", "--quiet", "-m", "c")
        lone = self.worktrees / "x" / "y" / "lone"
        self.git(other, "worktree", "add", "--quiet", "-b", "lone", str(lone))
        feature, repo, other, lone = (path.resolve() for path in (feature, repo, other, lone))
        self.write_council({"rasci.json": {"work/feature": {"title": "F", "status": "running", "worker": "Skills session", "workdir": str(feature)}}})
        self.tool("review_request", {**self.arguments("feat: tree", "", self.page("tree.html", PAGE)), "worktree": str(feature), "branch": "feature"})
        status, _, body = self.get("/api/tree")
        self.assertEqual(status, 200, body)
        data = json.loads(body)
        repos = {entry["name"]: entry for entry in data["repos"]}
        self.assertEqual(set(repos), {"github.com/me/demo", str(other)})
        demo = {entry["name"]: entry for entry in repos["github.com/me/demo"]["branches"]}
        self.assertEqual((demo["main"]["upstream"], demo["main"]["ahead"], demo["main"]["behind"]), ("origin/main", 1, 0))
        trees = [(tree["path"], tree["dirty"], tree["workers"], tree["review"]) for tree in demo["main"]["worktrees"] + demo["feature"]["worktrees"]]
        self.assertEqual(trees, [(str(repo), False, [], None), (str(feature), True, ["Skills"], {"status": "pending", "gate": "pass", "title": "feat: tree"})])
        self.assertEqual([tree["path"] for tree in {entry["name"]: entry for entry in repos[str(other)]["branches"]}["lone"]["worktrees"]], [str(lone)])
        self.assertEqual(json.loads(self.get("/api/tree")[2])["scanned"], data["scanned"])

    def test_tree_runs_no_command_a_repo_config_names(self):
        marker = self.outside / "ran"
        trap, filtered = (self.repos / "github.com" / "me" / name for name in ("trap", "filtered"))
        for repo in (trap, filtered):
            repo.mkdir(parents=True)
            self.git(repo, "init", "--quiet", "--initial-branch=main")
            (repo / "a.txt").write_text("a", encoding="utf-8")
            self.git(repo, "add", "a.txt")
            self.git(repo, "commit", "--quiet", "-m", "a")
        self.git(trap, "config", "core.fsmonitor", f"touch {marker}")
        self.git(filtered, "config", "filter.x.clean", f"touch {marker}")
        (filtered / ".gitattributes").write_text("* filter=x\n", encoding="utf-8")
        (filtered / "a.txt").write_text("b", encoding="utf-8")
        status, _, body = self.get("/api/tree")
        self.assertEqual(status, 200, body)
        dirty = {entry["name"]: entry["branches"][0]["worktrees"][0]["dirty"] for entry in json.loads(body)["repos"]}
        self.assertEqual(dirty, {"github.com/me/trap": False, "github.com/me/filtered": None})
        self.assertFalse(marker.exists())

    def test_tree_never_fetches_a_missing_object(self):
        marker = self.outside / "fetched"
        origin = self.outside / "lazy.git"
        self.git(self.outside, "init", "--quiet", "--bare", "--initial-branch=main", str(origin))
        repo = self.repos / "github.com" / "me" / "lazy"
        repo.mkdir(parents=True)
        self.git(repo, "init", "--quiet", "--initial-branch=main")
        (repo / "a.txt").write_text("a", encoding="utf-8")
        self.git(repo, "add", "a.txt")
        self.git(repo, "commit", "--quiet", "-m", "a")
        self.git(repo, "remote", "add", "origin", str(origin))
        self.git(repo, "push", "--quiet", "-u", "origin", "main")
        self.git(repo, "config", "remote.origin.promisor", "true")
        self.git(repo, "config", "remote.origin.uploadpack", f"touch {marker}; git-upload-pack")
        (repo / ".git" / "refs" / "remotes" / "origin" / "main").write_text("1" * 40 + "\n", encoding="utf-8")
        status, _, body = self.get("/api/tree")
        self.assertEqual(status, 200, body)
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
