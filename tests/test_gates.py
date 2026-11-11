import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

GATES = Path(__file__).resolve().parents[1] / "skills" / "kvb-check-gate" / "scripts" / "gates.py"


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


class TestGates(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.base = Path(scratch.name)
        self.repo = self.base / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.email", "t@example.org")
        git(self.repo, "config", "user.name", "t")
        self.commit("a")
        self.env = {**os.environ, "GATES_DB": str(self.base / "gates.db")}

    def commit(self, name: str) -> None:
        (self.repo / name).write_text(name, encoding="utf-8")
        git(self.repo, "add", name)
        git(self.repo, "commit", "-q", "-m", name)

    def gates(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(GATES), *args], cwd=self.repo, env=self.env, capture_output=True, text=True, check=False
        )

    def resolve(self, branch: str, action: str = "merge") -> str:
        return self.gates("resolve", "--repo", str(self.repo), "--branch", branch, "--action", action).stdout.strip()

    def test_a_branch_takes_its_own_rule_else_the_strictest_of_all_parents_else_none(self):
        repo = str(self.repo)
        self.assertEqual(self.resolve("fix"), "none\t-")
        for parent, level in (("iam", "test"), ("production", "quality-high")):
            self.gates("rule", "set", "--repo", repo, "--branch", parent, "--action", "merge", "--level", level)
            self.gates("parents", "add", "--repo", repo, "--branch", "fix", "--parent", parent)
        self.assertEqual(self.resolve("fix"), "quality-high\tproduction")
        self.gates("rule", "set", "--repo", repo, "--branch", "fix", "--action", "merge", "--level", "quick")
        self.assertEqual(self.resolve("fix"), "quick\tfix")
        self.assertEqual(self.resolve("fix", "push"), "none\t-")

    def test_derive_gives_each_branch_its_nearest_ancestor_tips_and_the_default_branch_none(self):
        git(self.repo, "checkout", "-q", "-b", "feature")
        self.commit("b")
        git(self.repo, "checkout", "-q", "-b", "fix")
        self.commit("c")
        derived = self.gates("parents", "derive", "--repo", str(self.repo)).stdout.splitlines()
        self.assertEqual(sorted(derived), ["feature\tmain\tderived", "fix\tfeature\tderived"])
        shown = json.loads(self.gates("show", "--json", "--repo", str(self.repo)).stdout)
        branches = next(iter(shown.values()))
        self.assertEqual(branches["main"]["parents"], [])
        self.assertEqual(branches["fix"]["parents"], [{"parent": "feature", "source": "derived"}])

    def test_the_tree_covers_unstaged_and_untracked_files_but_not_ignored_ones(self):
        tree = lambda: self.gates("tree", "--worktree", str(self.repo)).stdout.strip()
        head = git(self.repo, "rev-parse", "HEAD^{tree}")
        self.assertEqual(tree(), head)
        (self.repo / ".gitignore").write_text("ignored\n", encoding="utf-8")
        git(self.repo, "add", ".gitignore")
        git(self.repo, "commit", "-q", "-m", "ignore")
        (self.repo / "ignored").write_text("x", encoding="utf-8")
        self.assertEqual(tree(), git(self.repo, "rev-parse", "HEAD^{tree}"))
        (self.repo / "a").write_text("changed", encoding="utf-8")
        (self.repo / "new").write_text("new", encoding="utf-8")
        dirty = tree()
        self.assertEqual(git(self.repo, "status", "--porcelain"), "M a\n?? new")
        git(self.repo, "add", "-A")
        self.assertEqual(dirty, git(self.repo, "write-tree"))

    def test_a_receipt_meets_its_own_level_and_every_lower_one(self):
        repo, tree = str(self.repo), git(self.repo, "rev-parse", "HEAD^{tree}")
        check = lambda level: self.gates("receipt", "check", "--repo", repo, "--tree", tree, "--level", level).returncode
        self.assertEqual(check("quick"), 1)
        self.gates("receipt", "add", "--repo", repo, "--tree", tree, "--level", "test", "--log", "/tmp/x.log")
        self.assertEqual((check("quick"), check("test"), check("quality-high")), (0, 0, 1))

    def test_a_branch_cannot_be_its_own_parent(self):
        result = self.gates("parents", "add", "--repo", str(self.repo), "--branch", "fix", "--parent", "fix")
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
