from __future__ import annotations

import json
import re
import time
import unittest
from unittest import mock

from hub_support import ASK, HUB, REPO_ROOT
from kvb_orchestrator import scores
from test_hub_match import MatchCase, git, merge_repo, move_head

ORDER = ["fix", "break", "tokens", "velocity", "security", "legal", "architecture", "score"]
FULL = "🎯 Fix: 95 % · 💥 Break: 3 % · 💸 Tokens: 100 % · ⏱️ Velocity: 100 % · 🛡️ Security: 99 · ⚖️ Legal: 98 · 🏛️ Architecture: 97 · 🏆 Score: 96"
OLD = "🎯 Fix: 95 % · 💥 Break: 3 % · 💸 Tokens: 100 % · ⏱️ Velocity: 100 % · 🛡️ Security: 99 · 🏆 Score: 96"
BUSY = ("operator/one", "operator/two", "operator/three")


class TestMergeDiff(MatchCase):
    def staged_merge(self) -> tuple[str, str]:
        repo, target = merge_repo(self.work)
        git(repo, "merge", "--no-commit", "--no-ff", "-q", target)
        tree = git(repo, "write-tree").strip()
        arguments = {**self.arguments("Merge feature into main", "", self.page("merge.html", "<!doctype html><title>m</title>")), "repo": str(repo / ".git"), "worktree": str(repo), "branch": "main", "tree": tree}
        result = self.tool("review_request", arguments)
        self.assertFalse(result["isError"], result)
        self.repo = repo
        return result["structuredContent"]["id"], tree

    def test_a_merge_review_without_a_diff_shows_the_merge_onto_its_first_parent(self):
        review, tree = self.staged_merge()
        before = self.card(f"review:{review}")
        self.assertFalse(before["files"], before)
        status, _, body = self.call("GET", "/api/runner/previews", None, self.client())
        self.assertEqual(status, 200, body)
        self.assertEqual([(row["id"], row["worktree"], row["tree"], row["head"]) for row in json.loads(body)["reviews"]], [(review, str(self.repo), tree, None)])
        self.run_runner(register=False)
        card = self.card(f"review:{review}")
        self.assertEqual([(entry["path"], entry["status"], entry["additions"]) for entry in card["files"]], [("app.py", "M", 1)])
        self.assertIn("+added = 2", card["files"][0]["patch"])
        self.assertEqual((card["stale"], card["diff_error"]), (False, None))

    def test_the_merge_card_turns_stale_once_head_moves(self):
        review, _ = self.staged_merge()
        self.run_runner(register=False)
        taken = self.httpd.hub.merge_previews.get(f"review:{review}")["taken"]
        self.run_runner(register=False)
        self.assertEqual(self.httpd.hub.merge_previews.get(f"review:{review}")["taken"], taken)
        move_head(self.repo)
        self.run_runner(register=False)
        card = self.card(f"review:{review}")
        self.assertEqual((card["stale"], card["stale_reason"]), (True, "HEAD moved since it was added"))
        self.assertEqual([entry["path"] for entry in card["files"]], ["app.py"])

    def test_a_review_whose_tree_is_missing_shows_the_read_error(self):
        repo, _ = merge_repo(self.work)
        arguments = {**self.arguments("Merge gone", "", self.page("gone.html", "<!doctype html><title>g</title>")), "repo": str(repo / ".git"), "worktree": str(repo), "branch": "main", "tree": "0" * 40}
        review = self.tool("review_request", arguments)["structuredContent"]["id"]
        self.run_runner(register=False)
        card = self.card(f"review:{review}")
        self.assertIsNone(card["files"], card)
        self.assertTrue(card["diff_error"], card)

    def test_only_the_runner_posts_a_review_preview_and_only_for_a_pending_review(self):
        review, _ = self.staged_merge()
        shown = {"id": review, "head": "a" * 40, "diff": []}
        self.assertEqual(self.post_json("/api/runner/previews", shown, self.guard(self.host))[0], 403)
        for bad, code in (({**shown, "id": "f" * 16}, 404), ({**shown, "id": "../x"}, 400), ({**shown, "head": "HEAD"}, 400), ({**shown, "diff": "x"}, 400), ({**shown, "extra": 1}, 400)):
            with self.subTest(bad=bad):
                self.assertEqual(self.post_json("/api/runner/previews", bad, self.client())[0], code)
        self.assertEqual(self.post_json("/api/runner/previews", shown, self.client())[0], 200)


class TestChips(unittest.TestCase):
    def labels(self) -> dict:
        return scores.score_labels(REPO_ROOT / "skills")

    def test_legal_and_architecture_sit_between_security_and_score(self):
        self.assertEqual([chip["id"] for chip in scores.metric_chips(FULL, self.labels(), True)], ORDER)
        self.assertEqual([(chip["emoji"], chip["value"]) for chip in scores.metric_chips(FULL, self.labels(), True)][5:7], [("⚖️", "98"), ("🏛️", "97")])

    def test_a_score_without_them_shows_no_empty_legal_or_architecture_chip(self):
        self.assertEqual([chip["id"] for chip in scores.metric_chips(OLD, self.labels(), True)], [key for key in ORDER if key not in ("legal", "architecture")])


class TestStrayText(unittest.TestCase):
    def test_no_native_dom_call_of_the_match_view_takes_a_value_that_can_be_null(self):
        source = (HUB / "templates" / "page-match.js").read_text(encoding="utf-8")
        self.assertEqual(re.findall(r"\.replaceChildren\([^;]*\bpeeks\)", source), [])
        self.assertIn('card.reason && card.reason !== "-" ? h("p", {class: "match-reason"}', source)


class TestCount(MatchCase):
    def test_the_tasks_badge_counts_exactly_the_open_match_cards(self):
        self.claim("s1", "Skills session")
        self.write_council({"rasci.json": {task: {"title": f"make {task[9:]}", "workdir": "/repo", "check": "done", "roles": {"Operator": "R"}} for task in BUSY}})
        ask = self.create_ask(ASK)
        hub = type(self.httpd.hub)
        with mock.patch.object(hub, "open_jobs", return_value=set(BUSY)), mock.patch.object(hub, "blocked_rows", return_value=dict.fromkeys(BUSY, "Queued in the hub runner")):
            cards = self.cards()
            self.assertEqual([card["id"] for card in cards if not card.get("blocked")], [f"ask:{ask}"])
            self.assertEqual(sorted(card["id"] for card in cards if card.get("blocked")), sorted(f"operator:{task}" for task in BUSY))
            self.assertEqual(self.snapshot()["badges"]["tasks"], 1)
            self.assertIn("<title>(1) Agent Orchestrator</title>", self.index())
            self.httpd.hub.asks.change(ask, {"expires": time.time() - 1})
            self.assertEqual(([card["id"] for card in self.cards() if not card.get("blocked")], self.snapshot()["badges"]["tasks"]), ([], 0))
            self.assertIn("<title>Agent Orchestrator</title>", self.index())


if __name__ == "__main__":
    unittest.main()
