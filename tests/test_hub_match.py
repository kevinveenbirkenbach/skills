from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from hub_case import HubCase
from hub_support import APPROVAL, ASK, GIT_ENV, HUB, OPTIONS, REPO_ROOT, key, signing
from kvb_orchestrator import batches, payloads, scores, skill_scripts

MATCH = REPO_ROOT / "skills" / "kvb-match" / "scripts" / "match.py"
CLIENT = HUB / "client"
FEEDBACK = "app.py:2: name it after what it holds\nnotes.md:3: say why"
PICK = {"title": "Merge the hub now?", "workdir": "/repo", "description": "the gate is green", "check": "decision", "options": OPTIONS, "recommended": "Merge now", "roles": {"Skills": "A", "Operator": "R"}}
SCORED = "git commit -m 'fix 2 tests' -m '🎯 Fix: 95 %\n💥 Break: 2 %\n💰 Value: 1:4\n🏆 Score: 93'"
TOLD = "app.py:2: name it after what it holds notes.md:3: say why"


def git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, env={**os.environ, **GIT_ENV}, check=True, capture_output=True, text=True)
    return done.stdout


def staged_repo(root: Path) -> Path:
    repo = root / "demo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "feature/match")
    (repo / "app.py").write_text("keep = 1\nold = 2\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    (repo / "app.py").write_text("keep = 1\nnew = 3\nmore = 4\n", encoding="utf-8")
    (repo / "notes.md").write_text("# Notes\n\nfresh\n", encoding="utf-8")
    git(repo, "add", "-A")
    return repo


def merge_repo(root: Path) -> tuple[Path, str]:
    repo = root / "merge"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "app.py").write_text("keep = 1\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    git(repo, "checkout", "-q", "-b", "feature")
    (repo / "app.py").write_text("keep = 1\nadded = 2\n", encoding="utf-8")
    git(repo, "commit", "-q", "-am", "feature")
    target = git(repo, "rev-parse", "HEAD").strip()
    git(repo, "checkout", "-q", "main")
    return repo, target


def move_head(repo: Path) -> str:
    (repo / "other.txt").write_text("moved\n", encoding="utf-8")
    git(repo, "add", "other.txt")
    git(repo, "commit", "-q", "-m", "moved")
    return git(repo, "rev-parse", "HEAD").strip()


class MatchCase(HubCase):
    def setUp(self):
        super().setUp()
        work = tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.work = Path(work.name)
        self.sandbox_view([])

    def sandbox_view(self, denied: list[str]) -> None:
        folder = self.state / "firewall"
        folder.mkdir(parents=True, exist_ok=True)
        settings = {"sandbox": {"filesystem": {"denyRead": denied}}}
        files = [{"path": "/home/op/.claude/settings.json", "exists": True, "sha256": "", "settings": settings}]
        (folder / "view.json").write_text(json.dumps({"written": "2026-11-14T12:00:00+00:00", "files": files}), encoding="utf-8")

    def match(self, cwd: Path, *args: str) -> subprocess.CompletedProcess:
        command = [sys.executable, str(MATCH), *args, "--port", str(self.port), "--client", str(CLIENT)]
        return subprocess.run(command, cwd=cwd, env={**os.environ, **GIT_ENV}, capture_output=True, text=True, timeout=60, check=False)

    def add(self, repo: Path) -> str:
        done = self.match(repo, "add", "--repo", str(repo), "--title", "feat: match", "--score", "🎯 95 💥 3", "--gate", "pass", "--agent", "Skills", "--pages", str(self.pages))
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)["id"]

    def cards(self) -> list[dict]:
        status, _, body = self.get("/api/match")
        self.assertEqual(status, 200, body)
        return json.loads(body)["cards"]

    def card(self, card_id: str) -> dict:
        return next(card for card in self.cards() if card["id"] == card_id)

    def operator_row(self, task: str, command: str, directory: str) -> None:
        register = {task: {"title": command, "workdir": directory, "description": "ship the release notes", "check": "done", "roles": {"Skills": "A", "Operator": "R"}}}
        self.write_council({"rasci.json": register})


class TestMatchSkill(MatchCase):
    def test_add_takes_the_staged_patch_and_tree_and_list_and_show_print_them(self):
        repo = staged_repo(self.work)
        review = self.add(repo)
        card = self.card(f"review:{review}")
        self.assertEqual((card["kind"], card["hash"], card["stale"]), ("commit", git(repo, "write-tree").strip(), False))
        self.assertEqual((card["branch"], card["worktree"], card["agent"], card["title"]), ("feature/match", str(repo), "Skills", "feat: match"))
        self.assertEqual([entry["path"] for entry in card["files"]], ["app.py", "notes.md"])
        shown = self.match(repo, "show", f"review:{review}")
        self.assertEqual(shown.returncode, 0, shown.stderr)
        self.assertEqual(shown.stdout, git(repo, "diff", "--cached"))
        listed = self.match(repo, "list")
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertIn(f"review:{review}", listed.stdout)
        self.assertIn("feat: match", listed.stdout)

    def test_add_refuses_an_empty_stage(self):
        repo = staged_repo(self.work)
        git(repo, "commit", "-q", "-m", "all")
        done = self.match(repo, "add", "--repo", str(repo), "--title", "feat: none", "--score", "🎯 1", "--gate", "pass", "--agent", "Skills", "--pages", str(self.pages))
        self.assertEqual(done.returncode, 1)
        self.assertIn("nothing staged", done.stderr)
        self.assertEqual(self.cards(), [])

    def test_a_changed_stage_turns_the_card_stale_and_adding_it_again_gives_a_fresh_card(self):
        repo = staged_repo(self.work)
        first = self.add(repo)
        (repo / "notes.md").write_text("# Notes\n\nchanged\n", encoding="utf-8")
        git(repo, "add", "-A")
        listed = self.match(repo, "list")
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertIn("stale", listed.stdout)
        old = self.card(f"review:{first}")
        self.assertTrue(old["stale"], old)
        self.assertIn("changed", old["stale_reason"])
        second = self.add(repo)
        fresh = self.card(f"review:{second}")
        self.assertEqual((fresh["stale"], fresh["hash"]), (False, git(repo, "write-tree").strip()))
        self.assertTrue(self.card(f"review:{first}")["stale"])

    def test_a_stale_report_needs_the_local_guard_and_a_tree(self):
        repo = staged_repo(self.work)
        review = self.add(repo)
        status, _, _ = self.post_json("/api/match/stale", {"id": review, "tree": "f" * 40}, {"Host": self.host})
        self.assertEqual(status, 403)
        status, _, _ = self.post_json("/api/match/stale", {"id": review, "tree": "nope"}, self.local())
        self.assertEqual(status, 400)
        self.assertFalse(self.card(f"review:{review}")["stale"])

    def test_a_gone_review_or_operator_row_leaves_the_cards(self):
        repo = staged_repo(self.work)
        review = self.add(repo)
        self.operator_row("operator/ship", "make ship", str(self.work))
        self.assertEqual(sorted(card["id"] for card in self.cards()), sorted([f"review:{review}", "operator:operator/ship"]))
        status, _, body = self.post_json(f"/reviews/{review}/reject", {}, self.guard(self.host))
        self.assertEqual(status, 200, body)
        self.write_council({"rasci.json": {}})
        self.assertEqual(self.cards(), [])


class TestMatchRelease(MatchCase):
    def radio(self) -> list[list[str]]:
        return [args for script, args in self.scripts.calls if script == skill_scripts.RADIO]

    def stack(self) -> tuple[Path, str]:
        self.claim("s1", "Skills session")
        repo = staged_repo(self.work)
        review = self.add(repo)
        self.operator_row("operator/ship", "make ship", str(self.work))
        return repo, review

    def decisions(self, review: str, verdict: str) -> list[dict]:
        """Args:
            review: the review id of the commit card.
            verdict: accept or reject for the commit card; the command card
                is always rejected with FEEDBACK.

        Returns:
            The entries the Match page releases, built as matchEntry builds
            them from the cards.
        """
        commit, command = self.card(f"review:{review}"), self.card("operator:operator/ship")
        rejected = {"verb": "reject", "channel": "call", "reason": FEEDBACK}
        first = {"kind": "review", "id": commit["ref"], "verb": "approve", "label": "", "sha256": ""}
        second = {"kind": "operator", "id": command["ref"], "label": "", "sha256": command["sha256"], **rejected, "to": command["to"]}
        return [first if verdict == "accept" else {**first, **rejected, "to": commit["to"]}, second]

    def verify(self, repo: Path, review: str) -> subprocess.CompletedProcess:
        argv = ["verify", "--port", str(self.port), "--approvers", str(self.approvers), "--replay", str(self.replay / "commit.json"), "--review", review, "--gate", "pass"]
        return subprocess.run([sys.executable, str(APPROVAL), *argv], cwd=repo, env={**os.environ, **GIT_ENV}, capture_output=True, text=True, timeout=60, check=False)

    def test_a_commit_card_lists_its_score_line_as_metric_chips_and_a_command_card_none(self):
        _, review = self.stack()
        chips = {card["ref"]: [(metric["id"], metric["value"]) for metric in card["metrics"]] for card in self.cards()}
        self.assertEqual(chips, {review: [("fix", "95"), ("break", "3")], "operator/ship": []})

    def test_every_card_names_the_addressee_its_inbox_entry_shows(self):
        _, review = self.stack()
        shown = {item["id"]: item["to"] for item in self.snapshot()["inbox"]}
        self.assertEqual({card["ref"]: card["to"] for card in self.cards()}, {review: "Skills", "operator/ship": "Skills"})
        self.assertEqual((shown[review], shown["operator/ship"]), ("Skills", "Skills"))

    def test_one_signature_releases_an_accepted_commit_the_commit_check_verifies_and_a_rejection_told_by_call(self):
        repo, review = self.stack()
        entries = self.decisions(review, "accept")
        signer = self.pin()
        proof = self.signed(entries, signer)
        status, _, body = self.approve([entries[0], {**entries[1], "reason": "push it anyway"}], proof)
        self.assertEqual(status, 400, body)
        self.assertIn("list every approved item", body.decode())
        status, _, body = self.approve(entries, key(-8, "stranger").proof(proof["payload"], self.origin))
        self.assertEqual(status, 400, body)
        self.assertIn("not signed", body.decode())
        with mock.patch.object(batches, "UNDO", 0.4):
            status, _, body = self.approve(entries, proof)
            self.assertEqual(status, 202, body)
            self.assertEqual(self.call("POST", f"/api/inbox/undo/{json.loads(body)['id']}", b"", self.guard(self.host))[0], 200)
            self.assertIn("already used", self.approve(entries, proof)[2].decode())
            self.assertEqual(self.approve(entries, self.signed(entries, signer))[0], 202)
            self.settle(lambda: self.status(review) == "approved")
        self.settle(lambda: (skill_scripts.RASCI, ["set", "operator/ship", "--status", "stopped"]) in self.scripts.calls)
        self.settle(lambda: self.radio() != [])
        self.assertEqual(len(self.radio()), 1, self.radio())
        sent = self.radio()[0]
        self.assertEqual(sent[:6], ["send", "call", "--to", "Skills session", "--session", "Operator"])
        self.assertTrue(sent[6].endswith(f"Denied by the operator: operator command make ship in {self.work} (from Skills). Reason: {TOLD}"), sent)
        done = self.verify(repo, review)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn(f"tree {git(repo, 'write-tree').strip()} on feature/match", done.stdout)
        self.assertNotIn(f"review:{review}", [card["id"] for card in self.cards()])

    def test_a_rejected_commit_carries_its_feedback_by_call_and_the_commit_check_refuses_it(self):
        repo, review = self.stack()
        entries = self.decisions(review, "reject")
        with mock.patch.object(batches, "UNDO", 0.05):
            self.assertEqual(self.approve(entries, self.signed(entries, self.pin()))[0], 202)
            self.settle(lambda: self.status(review) == "rejected")
        self.settle(lambda: len(self.radio()) == 2)
        told = sorted(sent[6].split("] ", 1)[1] for sent in self.radio())
        self.assertEqual(told[0], f"Denied by the operator: commit feat: match on feature/match (from Skills). Reason: {TOLD}")
        self.assertEqual({tuple(sent[:4]) for sent in self.radio()}, {("send", "call", "--to", "Skills session")})
        stored = self.httpd.hub.reviews.get(review)
        self.assertEqual((stored["channel"], stored["reason"], stored["to"]), ("call", TOLD, "Skills"))
        done = self.verify(repo, review)
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn("rejected", done.stderr)

    def test_a_command_release_binds_the_payload_hash_its_card_showed(self):
        body = self.work / "body.md"
        body.write_text("# Release\n", encoding="utf-8")
        command = f"gh issue create --body-file {body}"
        self.operator_row("operator/ship", command, str(self.work))
        card = self.card("operator:operator/ship")
        inbox = {"kind": "operator", "id": "operator/ship", "verb": "approve", "label": "", "sha256": card["sha256"]}
        entry = {**inbox, "payload": card["hash"]}
        row = signing.item_hash(signing.operator_item("operator/ship", command, str(self.work)))
        bound = signing.match_item("operator:operator/ship", card["hash"])
        self.assertEqual(self.prepare([inbox])["payload"]["items"], [row])
        self.assertEqual(sorted(self.prepare([entry])["payload"]["items"]), sorted([row, signing.item_hash(bound)]))
        signer = self.pin()
        bare = signer.proof(signing.approval_payload([row], secrets.token_hex(16), int(time.time()) + 60), self.origin)
        status, _, answer = self.approve([entry], bare)
        self.assertEqual(status, 400, answer)
        self.assertIn("list every approved item", answer.decode())
        for bad, code in (({**entry, "payload": "x"}, 400), ({**entry, "payload": "0" * 64}, 409), ({**entry, "verb": "reject", "channel": "call", "reason": "", "to": "Skills"}, 400)):
            with self.subTest(bad=bad):
                self.assertEqual(self.post_json("/api/sign", {"items": [bad]}, self.guard(self.host))[0], code)
        body.write_text("# Release, changed\n", encoding="utf-8")
        status, _, answer = self.post_json("/api/sign", {"items": [entry]}, self.guard(self.host))
        self.assertEqual(status, 409, answer)
        self.assertIn("stale", answer.decode())
        status, _, answer = self.post_json("/api/match/snapshot", {"task": "operator/ship"}, self.local())
        self.assertEqual(status, 200, answer)
        self.assertNotEqual(json.loads(answer)["hash"], card["hash"])
        self.assertEqual(self.post_json("/api/sign", {"items": [entry]}, self.guard(self.host))[0], 409)
        body.write_text("# Release\n", encoding="utf-8")
        status, _, answer = self.post_json("/api/match/snapshot", {"task": "operator/ship"}, self.local())
        self.assertEqual(json.loads(answer)["hash"], card["hash"], answer)
        with mock.patch.object(batches, "UNDO", 0.4):
            self.assertEqual(self.approve([entry], self.signed([entry], signer))[0], 202)
            body.write_text("# Release, changed after the release\n", encoding="utf-8")
            self.settle(lambda: any("payload file changed" in row["text"] for row in self.events("kinds=approval")["events"]))
        self.assertEqual(self.httpd.hub.jobs.listed(), [])
        body.write_text("# Release\n", encoding="utf-8")
        with mock.patch.object(batches, "UNDO", 0.05):
            self.assertEqual(self.approve([entry], self.signed([entry], signer))[0], 202)
            self.settle(lambda: self.httpd.hub.jobs.listed() != [])
        self.assertEqual([(job["task"], job["status"]) for job in self.httpd.hub.jobs.listed()], [("operator/ship", "queued")])

    def test_a_commit_rejected_without_feedback_stays_a_plain_rejection(self):
        _, review = self.stack()
        entry = {"kind": "review", "id": review, "verb": "reject", "label": "", "sha256": ""}
        for bad in ({**entry, "channel": "call", "reason": "x"}, {**entry, "channel": "mayday", "reason": "x", "to": "Skills"}, {**entry, "reason": "x", "to": "Skills"}):
            with self.subTest(bad=bad):
                self.assertEqual(self.post_json("/api/sign", {"items": [bad]}, self.guard(self.host))[0], 400)
        with mock.patch.object(batches, "UNDO", 0.05):
            self.assertEqual(self.approve([entry], None)[0], 202)
            self.settle(lambda: self.status(review) == "rejected")
        self.assertEqual(self.radio(), [])


class TestCommandCards(MatchCase):
    def payload_command(self) -> str:
        body = self.work / "body.md"
        body.write_text("# Release\n\nline two\n", encoding="utf-8")
        (self.work / "link.md").symlink_to(body)
        (self.work / "big.txt").write_text("x" * (payloads.PAYLOAD_LIMIT + 1), encoding="utf-8")
        (self.work / "secret.txt").write_text("hidden\n", encoding="utf-8")
        return f"gh issue create --body-file {body} --list link.md --big=big.txt --key {self.work / 'secret.txt'} --base origin/main"

    def test_an_operator_row_is_a_card_with_command_directory_reason_and_payload_files(self):
        self.sandbox_view([str(self.work / "secret.txt")])
        command = self.payload_command()
        self.operator_row("operator/ship", command, str(self.work))
        card = self.card("operator:operator/ship")
        self.assertEqual((card["kind"], card["command"], card["directory"], card["reason"], card["agent"], card["stale"]), ("command", command, str(self.work), "ship the release notes", "Skills", False))
        files = {Path(entry["path"]).name: entry for entry in card["files"]}
        self.assertEqual(sorted(files), ["big.txt", "body.md", "link.md", "secret.txt"])
        self.assertEqual((files["body.md"]["state"], files["body.md"]["content"]), ("read", "# Release\n\nline two\n"))
        for name, words in (("link.md", "symlink"), ("big.txt", "bytes"), ("secret.txt", "sandbox")):
            with self.subTest(name=name):
                self.assertEqual((files[name]["state"], files[name]["content"]), ("refused", ""))
                self.assertIn(words, files[name]["reason"])

    def test_without_a_sandbox_view_every_payload_file_is_refused(self):
        (self.state / "firewall" / "view.json").unlink()
        command = self.payload_command()
        self.operator_row("operator/ship", command, str(self.work))
        states = {entry["state"] for entry in self.card("operator:operator/ship")["files"]}
        self.assertEqual(states, {"refused"})

    def test_a_changed_payload_file_turns_the_card_stale_until_it_is_added_again(self):
        command = self.payload_command()
        self.operator_row("operator/ship", command, str(self.work))
        before = self.card("operator:operator/ship")
        (self.work / "body.md").write_text("# Release\n\nswapped\n", encoding="utf-8")
        after = self.card("operator:operator/ship")
        self.assertTrue(after["stale"], after)
        self.assertEqual(after["files"], before["files"])
        self.assertNotEqual(after["live_hash"], after["hash"])
        done = self.match(self.work, "add", "--task", "operator/ship")
        self.assertEqual(done.returncode, 0, done.stderr)
        fresh = self.card("operator:operator/ship")
        self.assertFalse(fresh["stale"], fresh)
        self.assertIn("swapped", next(entry["content"] for entry in fresh["files"] if entry["path"].endswith("body.md")))

    def test_a_command_card_shows_the_scores_its_command_carries_with_their_emoji_only(self):
        self.operator_row("operator/commit", SCORED, str(self.work))
        chips = [(chip["id"], chip["value"]) for chip in self.card("operator:operator/commit")["metrics"]]
        self.assertEqual(chips, [("fix", "95 %"), ("break", "2 %"), ("score", "93"), ("value", "1:4")])

    def test_show_prints_the_command_and_its_payload(self):
        command = self.payload_command()
        self.operator_row("operator/ship", command, str(self.work))
        shown = self.match(self.work, "show", "operator:operator/ship")
        self.assertEqual(shown.returncode, 0, shown.stderr)
        for words in (command, f"in {self.work}", "line two", "refused"):
            with self.subTest(words=words):
                self.assertIn(words, shown.stdout)


class TestWaitingCards(MatchCase):
    def radio(self) -> list[list[str]]:
        return [args for script, args in self.scripts.calls if script == skill_scripts.RADIO]

    def answered(self, task: str) -> str:
        return next(item["answered"] for item in self.snapshot()["inbox"] if item["id"] == task)

    def waiting(self) -> dict[str, str]:
        self.claim("s1", "Skills session")
        self.add(staged_repo(self.work))
        self.write_council({"rasci.json": {"operator/pick": PICK, "operator/ship": {"title": "make ship", "workdir": str(self.work), "check": "done", "roles": {"Skills": "A"}}}})
        rule = {"kind": "ask", "tool": "Bash", "pattern": "make test*", "scope": "/repo*", "expires": int(time.time()) + 86400, "agent": "Skills", "why": "the gate runs make test"}
        requested = self.tool("rule_request", rule)
        self.assertFalse(requested["isError"], requested)
        return {"ask": self.create_ask({**ASK, "command": SCORED}), "decision": self.decision("Merge now"), "rule": requested["structuredContent"]["id"]}

    def test_every_entry_that_waits_on_the_operator_is_one_card_of_its_kind(self):
        ids = self.waiting()
        cards = self.cards()
        inbox = self.snapshot()["inbox"]
        self.assertEqual(sorted(card["id"] for card in cards), sorted(f"{item['kind']}:{item['id']}" for item in inbox))
        kinds = {card["id"]: (card["kind"], card["entry"]) for card in cards if "entry" in card}
        self.assertEqual(kinds, {f"ask:{ids['ask']}": ("ask", "ask"), f"decision:{ids['decision']}": ("decision", "decision"), "operator:operator/pick": ("decision", "operator"), f"rule:{ids['rule']}": ("rule", "rule")})
        pick = self.card("operator:operator/pick")
        self.assertEqual((pick["options"], pick["recommended"], pick["reason"], pick["agent"], pick["to"]), (OPTIONS, "Merge now", "the gate is green", "Skills", "Skills"))
        ask = self.card(f"ask:{ids['ask']}")
        self.assertEqual((ask["command"], ask["directory"], ask["files"]), (SCORED, "/repo", []))
        self.assertEqual([(chip["id"], chip["value"]) for chip in ask["metrics"]], [("fix", "95 %"), ("break", "2 %"), ("score", "93"), ("value", "1:4")])
        rule = self.card(f"rule:{ids['rule']}")
        self.assertEqual((rule["rule"]["pattern"], rule["reason"], rule["dry_run"]["days"]), ("make test*", "the gate runs make test", 7))

    def test_a_picked_option_of_a_decision_row_is_signed_once_with_the_rest_posted_to_its_agent_and_leaves_the_stack(self):
        ids = self.waiting()
        pick = self.card("operator:operator/pick")
        entries = [
            {"kind": "operator", "id": "operator/pick", "verb": "approve", "label": "Wait", "sha256": pick["sha256"]},
            {"kind": "decision", "id": ids["decision"], "verb": "approve", "label": "Merge now", "sha256": ""},
            {"kind": "ask", "id": ids["ask"], "verb": "approve", "label": "", "sha256": ""},
        ]
        answer = signing.message_item("Skills", "post", "Decision operator/pick\nAnswer: Wait", "", "", "")
        self.assertIn(signing.item_hash(answer), self.prepare(entries)["payload"]["items"])
        for bad, code in (({**entries[0], "label": "Later"}, 400), ({**entries[0], "payload": "0" * 64}, 400), ({**entries[0], "sha256": "0" * 64}, 409)):
            with self.subTest(bad=bad):
                self.assertEqual(self.post_json("/api/sign", {"items": [bad]}, self.guard(self.host))[0], code)
        with mock.patch.object(batches, "UNDO", 0.4):
            self.assertEqual(self.approve(entries, self.signed(entries, self.pin()))[0], 202)
            self.assertNotIn("operator:operator/pick", [card["id"] for card in self.cards()])
            self.settle(lambda: self.choice(ids["decision"]) == "Merge now" and self.ask_status(ids["ask"], "0") == "allowed")
        self.settle(lambda: any(sent[0] == "post" and sent[-1].endswith("Decision operator/pick Answer: Wait") for sent in self.radio()))
        sent = next(sent for sent in self.radio() if sent[-1].endswith("Answer: Wait"))
        self.assertEqual(sent[:5], ["post", "--to", "Skills session", "--session", "Operator"])
        self.assertNotIn((skill_scripts.RASCI, ["set", "operator/pick", "--status", "stopped"]), self.scripts.calls)
        self.assertEqual({card["kind"] for card in self.cards()}, {"commit", "command", "rule"})
        self.assertEqual(self.post_json("/api/sign", {"items": [entries[0]]}, self.guard(self.host))[0], 409)
        self.assertEqual(self.answered("operator/pick"), "Wait")
        self.write_council({"rasci.json": {"operator/pick": {**PICK, "title": "Merge the hub tonight?"}}})
        self.assertEqual((self.card("operator:operator/pick")["title"], self.answered("operator/pick")), ("Merge the hub tonight?", ""))

    def test_a_rejected_decision_row_stops_and_its_agent_hears_the_question_and_the_feedback(self):
        self.waiting()
        pick = self.card("operator:operator/pick")
        entry = {"kind": "operator", "id": "operator/pick", "verb": "reject", "label": "", "sha256": pick["sha256"], "channel": "call", "reason": FEEDBACK, "to": pick["to"]}
        with mock.patch.object(batches, "UNDO", 0.05):
            self.assertEqual(self.approve([entry], self.signed([entry], self.pin()))[0], 202)
            self.settle(lambda: (skill_scripts.RASCI, ["set", "operator/pick", "--status", "stopped"]) in self.scripts.calls)
        self.settle(lambda: self.radio() != [])
        self.assertTrue(self.radio()[0][6].endswith(f"Denied by the operator: decision operator/pick: Merge the hub now? (from Skills). Reason: {TOLD}"), self.radio())


class TestMergeCards(MatchCase):
    def merge_row(self) -> tuple[Path, str, str]:
        repo, target = merge_repo(self.work)
        command = f"git merge --ff-only {target}"
        self.operator_row("operator/merge", command, str(repo))
        return repo, target, command

    def released(self) -> tuple[Path, str, dict]:
        repo, target, _ = self.merge_row()
        self.card("operator:operator/merge")
        self.run_runner(register=False)
        card = self.card("operator:operator/merge")
        entry = {"kind": "operator", "id": "operator/merge", "verb": "approve", "label": "", "sha256": card["sha256"], "payload": card["hash"]}
        with mock.patch.object(batches, "UNDO", 0.05):
            self.assertEqual(self.approve([entry], self.signed([entry], self.pin()))[0], 202)
            self.settle(lambda: self.httpd.hub.jobs.listed() != [])
        self.assertEqual([job["head"] for job in self.runner_jobs()], [card["merge"]["head"]])
        return repo, target, card

    def test_the_runner_previews_a_merge_row_and_its_card_turns_stale_once_head_moves(self):
        repo, target, command = self.merge_row()
        self.assertIsNone(self.card("operator:operator/merge")["merge"])
        self.run_runner(register=False)
        card = self.card("operator:operator/merge")
        head = git(repo, "rev-parse", "HEAD").strip()
        self.assertEqual((card["merge"], card["stale"]), ({"head": head, "base": head, "target": target, "error": ""}, False))
        shown = {"": "@@ -1 +1,2 @@\n keep = 1\n+added = 2", "content withheld": ""}
        self.assertEqual([(entry["path"], entry["status"], entry["additions"], entry["patch"] == shown[entry["note"]]) for entry in card["files"]], [("app.py", "M", 1, True)])
        status, _, body = self.call("GET", "/api/runner/previews", None, self.client())
        self.assertEqual((status, json.loads(body)["rows"]), (200, [{"task": "operator/merge", "command": command, "directory": str(repo), "head": head}]))
        taken = self.httpd.hub.merge_previews.get("operator:operator/merge")["taken"]
        self.run_runner(register=False)
        self.assertEqual(self.httpd.hub.merge_previews.get("operator:operator/merge")["taken"], taken)
        moved = move_head(repo)
        self.run_runner(register=False)
        after = self.card("operator:operator/merge")
        self.assertEqual((after["stale"], after["stale_reason"], after["merge"]["head"]), (True, "HEAD or the merge base moved since it was added", moved))

    def test_only_the_runner_posts_a_preview_and_only_for_an_open_row_and_its_command(self):
        _, target, command = self.merge_row()
        shown = {"task": "operator/merge", "command": command, "head": "a" * 40, "base": "a" * 40, "target": target, "diff": []}
        self.assertEqual(self.post_json("/api/runner/previews", shown, self.guard(self.host))[0], 403)
        self.assertEqual(self.call("GET", "/api/runner/previews", None, self.guard(self.host))[0], 403)
        for bad, code in (({**shown, "command": "git merge main"}, 409), ({**shown, "task": "operator/gone"}, 404), ({**shown, "head": "HEAD"}, 400), ({**shown, "diff": "x"}, 400)):
            with self.subTest(bad=bad):
                self.assertEqual(self.post_json("/api/runner/previews", bad, self.client())[0], code)
        self.assertEqual(self.post_json("/api/runner/previews", shown, self.client())[0], 200)

    def test_a_released_merge_runs_while_head_stays_the_previewed_one(self):
        repo, target, _ = self.released()
        self.run_runner(register=False)
        self.settle(lambda: self.httpd.hub.jobs.listed()[0]["status"] == "done")
        self.assertEqual(git(repo, "rev-parse", "HEAD").strip(), target)

    def test_a_released_merge_is_refused_once_head_moved_after_the_preview(self):
        repo, _, card = self.released()
        moved = move_head(repo)
        self.run_runner(register=False)
        job = self.httpd.hub.jobs.listed()[0]
        self.assertEqual((job["status"], git(repo, "rev-parse", "HEAD").strip()), ("refused", moved))
        self.assertIn(f"HEAD moved from {card['merge']['head'][:12]} to {moved[:12]}", job["output"])


class TestPayloadHash(unittest.TestCase):
    def test_the_hash_binds_command_directory_and_every_file_state(self):
        files = [{"path": "/tmp/a", "state": "read", "reason": "", "sha256": "1" * 64, "size": 3, "content": "abc"}]
        base = payloads.payload_hash("make ship", "/repo", files)
        self.assertEqual(base, payloads.payload_hash("make ship", "/repo", [dict(files[0])]))
        self.assertRegex(base, "^[0-9a-f]{64}$")
        for changed in (payloads.payload_hash("make ship ", "/repo", files), payloads.payload_hash("make ship", "/other", files), payloads.payload_hash("make ship", "/repo", [{**files[0], "sha256": "2" * 64}]), payloads.payload_hash("make ship", "/repo", [{**files[0], "state": "refused"}])):
            self.assertNotEqual(changed, base)

    def test_named_paths_come_from_words_and_option_values_resolved_in_the_directory(self):
        named = payloads.named_paths("gh issue create --body-file /tmp/x/body.md --list=list.txt scripts/run.sh 'quoted file.md' https://example.org/a.md", "/repo")
        self.assertEqual(named, ["/tmp/x/body.md", "/repo/list.txt", "/repo/scripts/run.sh", "/repo/quoted file.md"])


class TestMetricChips(unittest.TestCase):
    def test_score_lines_of_every_shape_give_one_chip_per_metric_in_label_order(self):
        labels = scores.score_labels(REPO_ROOT / "skills")
        line = scores.metric_chips("🎯 fix 94 % · 💥 break 4 % · 💸 tokens 100 % · ⏱️ velocity 100 % · 🛡️ security 100 % · 🏆 score 90", labels, True)
        self.assertEqual([(chip["id"], chip["emoji"], chip["label"], chip["value"]) for chip in line], [
            ("fix", "🎯", "Fix", "94 %"), ("break", "💥", "Break", "4 %"), ("tokens", "💸", "Tokens", "100 %"),
            ("velocity", "⏱️", "Velocity", "100 %"), ("security", "🛡️", "Security", "100 %"), ("score", "🏆", "Score", "90"),
        ])
        block = scores.metric_chips("🎯 Fix: 85 %\n💥 Break: 5 %\n⏱ Speed: new\n🏆 Score: 81\n🚦 Gate: ⛔ fix 85 % < 90", labels, True)
        self.assertEqual([(chip["id"], chip["value"]) for chip in block], [("fix", "85 %"), ("break", "5 %"), ("velocity", "new"), ("score", "81")])
        self.assertEqual([(chip["id"], chip["value"]) for chip in scores.metric_chips("Fix 92% Break 2.5%", labels, True)], [("fix", "92%"), ("break", "2.5%")])
        for text in ("", "looks good", "🎯 high", "prefix 90 %"):
            with self.subTest(text=text):
                self.assertEqual(scores.metric_chips(text, labels, True), [])
        self.assertEqual(scores.metric_chips("fix 2 tests, score 3 · 🏆 7", labels, False), [{"id": "score", "emoji": "🏆", "label": "Score", "value": "7"}])
        self.assertEqual([(chip["id"], chip["value"]) for chip in scores.metric_chips("💰 Value: 1:4 · 💰 2", labels, True)], [("value", "1:4")])
        self.assertEqual(scores.metric_chips("🎯 95 💥 3", None, True), [])


if __name__ == "__main__":
    unittest.main()
