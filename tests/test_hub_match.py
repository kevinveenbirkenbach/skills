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
from hub_support import APPROVAL, GIT_ENV, HUB, REPO_ROOT, key, signing
from kvb_orchestrator import batches, payloads, skill_scripts

MATCH = REPO_ROOT / "skills" / "kvb-match" / "scripts" / "match.py"
CLIENT = HUB / "client"
FEEDBACK = "app.py:2: name it after what it holds\nnotes.md:3: say why"
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

    def test_decision_rows_and_rows_at_the_runner_are_no_cards(self):
        self.write_council({"rasci.json": {"operator/pick": {"title": "-", "workdir": str(self.work), "check": "decision", "roles": {"Operator": "R"}}}})
        self.assertEqual(self.cards(), [])

    def test_show_prints_the_command_and_its_payload(self):
        command = self.payload_command()
        self.operator_row("operator/ship", command, str(self.work))
        shown = self.match(self.work, "show", "operator:operator/ship")
        self.assertEqual(shown.returncode, 0, shown.stderr)
        for words in (command, f"in {self.work}", "line two", "refused"):
            with self.subTest(words=words):
                self.assertIn(words, shown.stdout)


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


if __name__ == "__main__":
    unittest.main()
