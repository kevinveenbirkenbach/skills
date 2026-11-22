from __future__ import annotations

import json
import subprocess
import sys
import time
import unittest
from unittest import mock

from hub_case import HubCase
from hub_support import CLIENT, HOOK, PRESENT, Key, key
from kvb_orchestrator import batches

PICK = "Execute (Recommended)"
QUESTION = {
    "question": "Clean up the two worktrees?",
    "header": "Cleanup",
    "options": [{"label": PICK, "description": "Both are merged"}, {"label": "Keep", "description": "Nothing changes", "preview": "a\nb"}],
    "multiSelect": False,
}
SECOND = {"question": "Post the report?", "header": "Report", "options": [{"label": "Post", "description": ""}, {"label": "Skip", "description": ""}], "multiSelect": False}
GROUPS = ["Scratch (Recommended)", "Logs", "Worktrees (Recommended)"]
MULTI = {"question": "Which groups go?", "header": "Groups", "options": [{"label": label, "description": ""} for label in GROUPS], "multiSelect": True}
ASKED = {**HOOK, "tool_name": "AskUserQuestion", "tool_input": {"questions": [QUESTION, SECOND]}}
BODY = {"question": QUESTION["question"], "options": [{"label": PICK, "description": "Both are merged"}], "session": "s1", "timeout": 60, "multi": False}
MULTI_BODY = {**BODY, "question": MULTI["question"], "options": MULTI["options"], "multi": True}


class TestHubQuestions(HubCase):
    def ask_question(self, payload: dict) -> str:
        status, _, body = self.post_json("/api/decisions", payload, self.local())
        self.assertEqual(status, 201, body)
        return json.loads(body)["id"]

    def state(self, decision_id: str) -> dict:
        status, _, body = self.get(f"/api/decisions/{decision_id}?wait=0")
        self.assertEqual(status, 200, body)
        return json.loads(body)

    def pick(self, decision_id: str, label: str, signer: Key) -> None:
        self.counted(decision_id, label, signer, 0)

    def counted(self, decision_id: str, label: str, signer: Key, count: int) -> None:
        """Args:
            count: the signature counter the authenticator reports.
        """
        items = [self.entry("decision", decision_id, label, "")]
        payload = self.prepare(items)["payload"]
        proof = {"payload": payload, "assertion": signer.assertion(payload, self.origin, "localhost", PRESENT, count)}
        with mock.patch.object(batches, "UNDO", 0.05):
            status, _, body = self.approve(items, proof)
            self.assertEqual(status, 202, body)
            self.settle(lambda: self.httpd.hub.decisions.get(decision_id)["status"] == "decided")

    def hook(self, payload: dict, timeout: str) -> subprocess.Popen:
        trust = ["--approvers", str(self.approvers), "--replay", str(self.replay / "hook.json")]
        process = subprocess.Popen([sys.executable, str(CLIENT), "--port", str(self.port), "--timeout", timeout, *trust], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        process.stdin.write(json.dumps(payload))
        process.stdin.close()
        self.addCleanup(process.stdout.close)
        self.addCleanup(process.stderr.close)
        return process

    def waiting(self, count: int) -> list[dict]:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            found = [item for item in self.snapshot()["inbox"] if item["kind"] == "decision"]
            if len(found) >= count:
                return sorted(found, key=lambda item: item["ts"])
            time.sleep(0.05)
        self.fail("the questions did not arrive")

    def test_a_question_is_a_local_expiring_decision_card_in_the_inbox_and_on_match(self):
        self.claim("s1", "Skills session")
        for headers in ({"Host": self.host}, {**self.local(), "Origin": "http://evil.example"}):
            with self.subTest(headers=headers):
                self.assertEqual(self.post_json("/api/decisions", BODY, headers)[0], 403)
        for payload in ({**BODY, "extra": 1}, {**BODY, "session": " "}, {**BODY, "options": []}, {**BODY, "timeout": -1}, {**BODY, "multi": "yes"}, {name: value for name, value in BODY.items() if name != "session"}):
            with self.subTest(payload=payload):
                self.assertEqual(self.post_json("/api/decisions", payload, self.local())[0], 400)
        decision_id = self.ask_question(BODY)
        self.assertEqual(self.state(decision_id), {"id": decision_id, "status": "pending", "choice": None, "proof": None, "to": "Skills"})
        item = next(item for item in self.snapshot()["inbox"] if item["id"] == decision_id)
        self.assertEqual((item["kind"], item["agent"], item["recommended"]), ("decision", "Skills", PICK))
        cards = json.loads(self.get("/api/match")[2])["cards"]
        self.assertEqual([card["kind"] for card in cards if card["ref"] == decision_id], ["decision"])
        self.assertEqual(self.get(f"/api/decisions/{self.decision('')}?wait=0")[0], 404)
        self.assertEqual(self.get("/api/decisions/0123456789abcdef?wait=0")[0], 404)
        expired = self.ask_question({**BODY, "timeout": 0})
        self.assertEqual(self.state(expired)["status"], "expired")
        self.assertNotIn(expired, [item["id"] for item in self.snapshot()["inbox"]])
        self.assertNotIn(f"decision:{expired}", [card["id"] for card in json.loads(self.get("/api/match")[2])["cards"]])
        self.assertNotIn(expired, [row["id"] for row in self.snapshot()["decisions"]])
        self.assertEqual(self.approve([self.entry("decision", expired, PICK, "")], None)[0], 409)

    def test_a_signed_pick_is_kept_for_the_hook_and_posts_nothing(self):
        self.claim("s1", "Skills session")
        signer = self.pin()
        decision_id = self.ask_question(BODY)
        self.pick(decision_id, PICK, signer)
        state = self.state(decision_id)
        self.assertEqual((state["status"], state["choice"], state["to"]), ("decided", PICK, "Skills"))
        self.assertEqual(set(state["proof"]), {"payload", "assertion"})
        self.assertEqual(self.scripts.calls, [])
        self.assertEqual(self.snapshot()["messages"], [])

    def test_a_multi_question_takes_one_or_more_labels_in_option_order_and_recommends_every_marked_one(self):
        self.claim("s1", "Skills session")
        signer = self.pin()
        decision_id = self.ask_question(MULTI_BODY)
        item = next(item for item in self.snapshot()["inbox"] if item["id"] == decision_id)
        self.assertEqual((item["multi"], item["recommended"]), (True, f"{GROUPS[0]}\n{GROUPS[2]}"))
        card = next(card for card in json.loads(self.get("/api/match")[2])["cards"] if card["ref"] == decision_id)
        self.assertEqual((card["multi"], card["recommended"]), (True, item["recommended"]))
        for label in ("", f"{GROUPS[2]}\n{GROUPS[0]}", f"{GROUPS[0]}\n{GROUPS[0]}", f"{GROUPS[0]}\nOther", f"{GROUPS[0]}\n"):
            with self.subTest(label=label):
                self.assertEqual(self.approve([self.entry("decision", decision_id, label, "")], None)[0], 400)
        self.pick(decision_id, f"{GROUPS[1]}\n{GROUPS[2]}", signer)
        self.assertEqual(self.state(decision_id)["choice"], f"{GROUPS[1]}\n{GROUPS[2]}")
        single = self.ask_question(BODY)
        self.assertEqual(self.approve([self.entry("decision", single, f"{PICK}\n{PICK}", "")], None)[0], 400)

    def test_every_decision_takes_one_trimmed_line_of_other_text_as_an_ask_user_question_does(self):
        self.claim("s1", "Skills session")
        signer = self.pin()
        single, multi, mcp = self.ask_question(BODY), self.ask_question(MULTI_BODY), self.decision("")
        for decision_id, label in ((single, " padded"), (single, "x" * 1001), (single, "tab\there"), (mcp, "two\nlines"), (mcp, "padded ")):
            with self.subTest(label=label[:20]):
                self.assertEqual(self.approve([self.entry("decision", decision_id, label, "")], None)[0], 400)
        self.pick(single, "Keep the old one", signer)
        self.pick(multi, "None of these", signer)
        self.pick(mcp, "Ask Main first", signer)
        self.assertEqual([self.httpd.hub.decisions.get(found)["choice"] for found in (single, multi, mcp)], ["Keep the old one", "None of these", "Ask Main first"])
        self.assertTrue(all("other" not in item for item in self.snapshot()["inbox"]))

    def test_the_hook_passes_a_signed_other_text_on_as_the_answer(self):
        self.claim("s1", "Skills session")
        signer = self.pin()
        process = self.hook({**ASKED, "tool_input": {"questions": [QUESTION, MULTI]}}, "20")
        first, second = self.waiting(2)
        self.pick(first["id"], "Only the first one", signer)
        self.pick(second["id"], "Logs only, keep the rest", signer)
        process.wait(30)
        decision = json.loads(process.stdout.read())["hookSpecificOutput"]["decision"]
        self.assertEqual(decision["updatedInput"]["answers"], {QUESTION["question"]: "Only the first one", MULTI["question"]: "Logs only, keep the rest"})

    def test_the_hook_answers_a_multi_select_question_with_the_picked_labels_joined_by_commas(self):
        self.claim("s1", "Skills session")
        signer = self.pin()
        process = self.hook({**ASKED, "tool_input": {"questions": [MULTI]}}, "20")
        card = self.waiting(1)[0]
        self.assertTrue(card["multi"])
        self.pick(card["id"], f"{GROUPS[0]}\n{GROUPS[2]}", signer)
        process.wait(30)
        decision = json.loads(process.stdout.read())["hookSpecificOutput"]["decision"]
        self.assertEqual(decision["updatedInput"]["answers"], {MULTI["question"]: f"{GROUPS[0]}, {GROUPS[2]}"})

    def test_the_hook_answers_every_question_with_the_signed_picks(self):
        self.claim("s1", "Skills session")
        signer = self.pin()
        process = self.hook(ASKED, "20")
        first, second = self.waiting(2)
        self.assertEqual([option["label"] for option in first["options"]], [PICK, "Keep"])
        self.assertEqual(first["options"][1]["preview"], "a\nb")
        self.pick(first["id"], PICK, signer)
        self.pick(second["id"], "Skip", signer)
        process.wait(30)
        decision = json.loads(process.stdout.read())["hookSpecificOutput"]["decision"]
        self.assertEqual(decision, {"behavior": "allow", "updatedInput": {"questions": [QUESTION, SECOND], "answers": {QUESTION["question"]: PICK, SECOND["question"]: "Skip"}}})

    def test_the_hook_takes_the_picks_of_a_counting_authenticator_signed_out_of_question_order(self):
        self.claim("s1", "Skills session")
        signer = self.pin()
        process = self.hook(ASKED, "20")
        first, second = self.waiting(2)
        self.counted(second["id"], "Skip", signer, 1)
        self.counted(first["id"], PICK, signer, 2)
        process.wait(30)
        decision = json.loads(process.stdout.read())["hookSpecificOutput"]["decision"]
        self.assertEqual(decision["updatedInput"]["answers"], {QUESTION["question"]: PICK, SECOND["question"]: "Skip"})

    def test_the_hook_leaves_the_question_to_the_terminal_without_a_pinned_signature_over_the_pick(self):
        self.claim("s1", "Skills session")
        signer = self.pin()
        single = {**ASKED, "tool_input": {"questions": [QUESTION]}}
        relayed = {
            "unpinned key": lambda card: (PICK, self.signed([self.entry("decision", card, PICK, "")], key(-8, "stranger"))),
            "no proof": lambda card: (PICK, None),
            "other label": lambda card: (PICK, self.signed([self.entry("decision", card, "Keep", "")], signer)),
        }
        for case, relay in relayed.items():
            with self.subTest(case=case):
                process = self.hook(single, "20")
                card = self.waiting(1)[0]["id"]
                choice, proof = relay(card)
                self.httpd.hub.decisions.decide(card, {"status": "decided", "choice": choice, "proof": proof})
                process.wait(30)
                self.assertEqual((process.returncode, process.stdout.read()), (0, ""))
        process = self.hook({**ASKED, "tool_input": {"questions": [{**QUESTION, "options": "Keep"}]}}, "20")
        process.wait(30)
        self.assertEqual((process.returncode, process.stdout.read()), (0, ""))
        self.assertEqual(len(self.httpd.hub.decisions.listed()), len(relayed))
        process = self.hook(single, "0.5")
        process.wait(30)
        self.assertEqual((process.returncode, process.stdout.read()), (0, ""))


if __name__ == "__main__":
    unittest.main()
