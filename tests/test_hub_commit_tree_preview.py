from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from unittest import mock

from hub_support import ASK
from test_hub_match import MatchCase, git, merge_repo
from test_hub_operator_tasks import rules_dir, staged_diff

TREE = "a" * 40
PARENT = "b" * 40
MISSING = "0" * 40
ROW = {"description": "commit the feature tree", "check": "done", "roles": {"Skills": "A", "Operator": "R"}}


class TestCommitTreeArgv(unittest.TestCase):
    def test_a_commit_tree_argv_yields_its_tree_and_first_parent_and_one_without_a_parent_none(self):
        cases = {
            f"git commit-tree {TREE} -p {PARENT} -m 'feat: x'": ("/w", TREE, PARENT),
            f"git -C sub commit-tree -S -p{PARENT} -p {'c' * 40} {TREE} -m x": ("/w/sub", TREE, PARENT),
            f"git commit-tree {TREE} -m root": None,
            f"git commit-tree {TREE} --no-gpg-sign -F msg.txt": None,
            f"git commit-tree {TREE} -p HEAD -m x": None,
            f"git commit-tree {TREE} -p {PARENT} -m x && git update-ref refs/heads/main {PARENT}": None,
            f"git merge --ff-only {TREE}": None,
        }
        for command, expected in cases.items():
            with self.subTest(command=command):
                found = staged_diff.commit_tree_of(command, "/w")
                self.assertEqual(None if found is None else (str(found[0]), found[1], found[2]), expected)


class TestCommitTreePreview(MatchCase):
    def setUp(self):
        super().setUp()
        self.repo, target = merge_repo(self.work)
        self.tree = git(self.repo, "rev-parse", f"{target}^{{tree}}").strip()
        self.parent = git(self.repo, "rev-parse", "main").strip()
        self.home = self.outside / "medusa-home"
        rules_dir(self.home / staged_diff.RULES_HOME.relative_to(Path.home()) / Path(staged_diff.RULES_TAIL.replace("*", "")).parent)

    def previewed(self) -> None:
        with mock.patch.dict(os.environ, {"HOME": str(self.home), "XDG_CACHE_HOME": str(self.home / ".cache")}):
            self.run_runner(register=False)

    def rows(self, commands: dict[str, str]) -> None:
        self.write_council({"rasci.json": {task: {**ROW, "title": command, "workdir": str(self.repo)} for task, command in commands.items()}})

    def written(self) -> tuple[str, str]:
        return git(self.repo, "for-each-ref"), git(self.repo, "count-objects")

    def test_the_runner_previews_a_commit_tree_row_as_the_diff_of_its_parent_to_its_tree_and_writes_nothing(self):
        command = f"git commit-tree {self.tree} -p {self.parent} -m 'feat: added'"
        self.rows({"operator/commit": command})
        self.assertIsNone(self.card("operator:operator/commit")["merge"])
        before = self.written()
        self.previewed()
        card = self.card("operator:operator/commit")
        self.assertEqual((card["merge"], card["stale"]), ({"kind": "commit-tree", "head": self.parent, "base": self.parent, "target": self.tree, "error": ""}, False))
        self.assertEqual([(entry["path"], entry["status"], entry["additions"]) for entry in card["files"]], [("app.py", "M", 1)])
        self.assertIn("+added = 2", card["files"][0]["patch"])
        self.assertEqual(self.written(), before)
        self.assertEqual(git(self.repo, "rev-parse", "HEAD").strip(), self.parent)
        status, _, body = self.call("GET", "/api/runner/previews", None, self.client())
        self.assertEqual((status, json.loads(body)["rows"]), (200, [{"task": "operator/commit", "command": command, "directory": str(self.repo), "head": self.parent}]))
        taken = self.httpd.hub.merge_previews.get("operator:operator/commit")["taken"]
        self.previewed()
        self.assertEqual(self.httpd.hub.merge_previews.get("operator:operator/commit")["taken"], taken)

    def test_an_unresolvable_tree_or_parent_shows_its_git_error_line_instead_of_the_diff(self):
        self.rows({"operator/no-tree": f"git commit-tree {MISSING} -p {self.parent} -m x", "operator/no-parent": f"git commit-tree {self.tree} -p {MISSING} -m x"})
        before = self.written()
        self.previewed()
        for task in ("operator/no-tree", "operator/no-parent"):
            with self.subTest(task=task):
                card = self.card(f"operator:{task}")
                self.assertEqual((card["merge"]["kind"], card["files"]), ("commit-tree", []), card)
                self.assertRegex(card["merge"]["error"], rf"{MISSING}.*fatal: ", card)
        self.assertEqual(self.written(), before)

    def test_the_runner_previews_a_commit_tree_ask_that_shipped_no_diff(self):
        command = f"git commit-tree {self.tree} -p {self.parent} -m x"
        ask = self.create_ask({**ASK, "command": command, "cwd": str(self.repo), "timeout": 3600})
        shipped = self.create_ask({**ASK, "command": command, "cwd": str(self.repo), "timeout": 3600, "diff": []})
        status, _, body = self.call("GET", "/api/runner/previews", None, self.client())
        self.assertEqual((status, json.loads(body)["asks"]), (200, [{"id": ask, "command": command, "cwd": str(self.repo), "head": None}]))
        self.previewed()
        card = self.card(f"ask:{ask}")
        self.assertEqual((card["merge"]["kind"], card["merge"]["target"], card["merge"]["error"]), ("commit-tree", self.tree, ""))
        self.assertEqual([(entry["path"], entry["status"], entry["additions"]) for entry in card["files"]], [("app.py", "M", 1)])
        self.assertIsNone(self.card(f"ask:{shipped}")["merge"])
        self.assertEqual(self.post_json("/api/runner/previews", {"ask": shipped, "head": self.parent, "error": "x"}, self.client())[0], 404)


if __name__ == "__main__":
    unittest.main()
