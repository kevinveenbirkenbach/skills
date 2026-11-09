from __future__ import annotations

import json
import re
import time
import unittest
from unittest import mock

from hub_case import HubCase
from hub_support import ASK, HUB, OPTIONS, key, signing
from kvb_orchestrator import batches, choosing, messaging, skill_scripts

REQUEST = "send me your open decisions as choices"


class TestHubChoices(HubCase):
    def setUp(self):
        super().setUp()
        self.claim("s1", "Skills session")
        self.claim("s2", "Stage")

    def choices_proof(self, payload: dict, signer) -> dict:
        status, _, body = self.post_json("/api/choices/sign", payload, self.guard(self.host))
        self.assertEqual(status, 200, body)
        return signer.proof(json.loads(body)["payload"], self.origin)

    def ask_choices(self, payload: dict, proof: dict | None) -> tuple[int, dict, bytes]:
        return self.post_json("/api/choices", {**payload, "proof": proof}, self.guard(self.host))

    def check(self, message_id: str, text: str, to: str) -> dict:
        return self.tool("operator_message", {"id": message_id, "text": text, "to": to})

    def test_the_request_text_is_the_fixed_one_of_decision_28(self):
        self.assertEqual(choosing.CHOICE_REQUEST, REQUEST)
        self.assertEqual(list(choosing.CHANNELS), ["post", "call", "newsletter", "broadcast", "pan-pan", "security", "mayday"])
        self.assertIn(REQUEST, {entry["name"]: entry["description"] for entry in self.rpc("tools/list", {})["result"]["tools"]}["decision_request"])

    def test_a_post_or_call_request_signs_each_picked_agent_once_and_operator_message_verifies_it(self):
        signer = self.pin()
        payload = {"class": "post", "to": ["Skills", "Stage"]}
        status, _, body = self.post_json("/api/choices/sign", payload, self.guard(self.host))
        self.assertEqual(status, 200, body)
        listed = [signing.item_hash(signing.message_item(name, "post", REQUEST, "", "", "")) for name in ("Skills", "Stage")]
        self.assertEqual(sorted(json.loads(body)["payload"]["items"]), sorted(listed))
        proof = signer.proof(json.loads(body)["payload"], self.origin)
        status, _, body = self.ask_choices(payload, proof)
        self.assertEqual(status, 201, body)
        sent = json.loads(body)
        self.assertTrue(sent["ok"])
        first, second = sent["ids"]
        self.assertEqual(self.scripts.calls, [
            (skill_scripts.RADIO, ["post", "--to", "Skills session", "--session", "Operator", f"[kvb-orchestrator msg {first}] {REQUEST}"]),
            (skill_scripts.RADIO, ["post", "--to", "Stage", "--session", "Operator", f"[kvb-orchestrator msg {second}] {REQUEST}"]),
        ])
        for message_id, to in ((first, "Skills session"), (second, "Stage")):
            with self.subTest(to=to):
                found = self.check(message_id, REQUEST, to)["structuredContent"]
                self.assertEqual((found["match"], found["text"], found["class"]), (True, REQUEST, "post"))
        self.assertTrue(self.check(first, REQUEST, "Stage")["isError"])
        self.assertTrue(self.check(second, "send me your open decisions", "Stage")["isError"])
        self.assertEqual(self.ask_choices(payload, proof)[:3:2], (400, b"not signed: this signature was already used for this item\n"))
        self.assertEqual(len(self.scripts.calls), 2)
        call = {"class": "call", "to": ["Stage"]}
        status, _, body = self.ask_choices(call, self.choices_proof(call, signer))
        self.assertEqual(status, 201, body)
        called = json.loads(body)["ids"][0]
        self.assertEqual(self.scripts.calls[-1], (skill_scripts.RADIO, ["send", "call", "--to", "Stage", "--session", "Operator", f"[kvb-orchestrator msg {called}] {REQUEST}"]))
        self.assertEqual(self.check(called, REQUEST, "Stage")["structuredContent"]["class"], "call")

    def test_every_channel_to_all_sends_the_request_to_everyone(self):
        signer = self.pin()
        for cls, command in messaging.TO_ALL.items():
            with self.subTest(cls=cls):
                payload = {"class": cls, "to": ["*"]}
                status, _, body = self.ask_choices(payload, self.choices_proof(payload, signer))
                self.assertEqual(status, 201, body)
                message_id = json.loads(body)["ids"][0]
                self.assertEqual(self.scripts.calls[-1], (skill_scripts.RADIO, [*command, "--session", "Operator", f"[kvb-orchestrator msg {message_id}] {REQUEST}"]))
                found = self.check(message_id, REQUEST, "*")["structuredContent"]
                self.assertEqual((found["match"], found["to"], found["class"]), (True, "*", cls))
        self.assertEqual(len(self.scripts.calls), len(messaging.TO_ALL))

    def test_a_request_carries_no_text_and_names_only_valid_recipients(self):
        signer = self.pin()
        for payload in (
            {"class": "post", "to": ["Stage"], "text": "anything"},
            {"class": "post", "to": []},
            {"class": "post", "to": ["*"]},
            {"class": "call", "to": ["Stage", "* session"]},
            {"class": "post", "to": ["* (x) session"]},
            {"class": "post", "to": "Stage"},
            {"class": "post", "to": ["two\nlines"]},
            {"class": "post", "to": ["Stage", "Stage session"]},
            {"class": "call", "to": [f"Agent {n}" for n in range(choosing.RECIPIENT_LIMIT + 1)]},
            {"class": "newsletter", "to": ["Stage"]},
            {"class": "receipt", "to": ["*"]},
            {"class": "post"},
        ):
            with self.subTest(payload=payload):
                self.assertEqual(self.post_json("/api/choices/sign", payload, self.guard(self.host))[0], 400)
        self.assertEqual(self.post_json("/api/choices/sign", {"class": "post", "to": ["Stage"]}, self.client())[0], 403)
        self.assertEqual(self.get("/api/choices/sign")[0], 405)
        self.assertEqual(self.get("/api/choices")[0], 405)
        both = {"class": "post", "to": ["Skills", "Stage"]}
        partial = self.choices_proof({"class": "post", "to": ["Skills"]}, signer)
        stranger = key(-7, "stranger").proof(partial["payload"], self.origin)
        for proof, reason in ((None, b"not signed: no signature\n"), (partial, b"not signed: the signature does not list this item\n"), (stranger, b"not signed: the signing key is not pinned\n")):
            with self.subTest(reason=reason):
                self.assertEqual(self.ask_choices(both, proof)[:3:2], (400, reason))
        self.assertEqual((self.scripts.calls, self.httpd.hub.messages.listed()), ([], []))

    def decide(self, question: str) -> tuple[str, dict]:
        result = self.tool("decision_request", {"question": question, "options": OPTIONS, "agent": "Stage", "recommended": ""})
        self.assertFalse(result["isError"], result)
        decision_id = result["structuredContent"]["id"]
        answer = signing.message_item("Stage", "post", f"Choice for decision {decision_id} ({' '.join(question.split())}): Wait", "", "", "")
        return decision_id, answer

    def test_a_click_on_a_choice_option_sends_a_signed_answer_operator_message_verifies(self):
        signer = self.pin()
        decision_id, answer = self.decide("Pick a  name?")
        self.assertEqual(answer["text"], f"Choice for decision {decision_id} (Pick a name?): Wait")
        entry = self.entry("decision", decision_id, "Wait", "")
        prepared = self.prepare([entry])
        self.assertEqual(prepared["payload"]["items"], [signing.item_hash(answer)])
        self.assertEqual(self.approve([entry], None)[:3:2], (400, b"not signed: an approval of an ask, review, choice or operator command needs the passkey signature\n"))
        proof = signer.proof(prepared["payload"], self.origin)
        with mock.patch.object(batches, "UNDO", 0.05):
            self.assertEqual(self.approve([entry], proof)[0], 202)
            self.settle(lambda: self.choice(decision_id) == "Wait")
        state = self.tool("decision_wait", {"id": decision_id, "timeout_seconds": 0})["structuredContent"]
        self.assertEqual((state["status"], state["answer"]), ("decided", answer["text"]))
        found = self.check(state["message"], state["answer"], "Stage")["structuredContent"]
        self.assertEqual((found["match"], found["to"], found["class"], found["text"]), (True, "Stage", "post", answer["text"]))
        self.assertTrue(self.check(state["message"], state["answer"], "Skills")["isError"])
        self.assertTrue(self.check(state["message"], f"Choice for decision {decision_id} (Pick a name?): Merge now", "Stage")["isError"])
        self.assertEqual(self.scripts.calls, [(skill_scripts.RADIO, ["post", "--to", "Stage", "--session", "Operator", f"[kvb-orchestrator msg {state['message']}] {answer['text']}"])])
        self.assertEqual(self.approve([entry], proof)[0], 409)
        titles = [row["text"] for row in self.events("kinds=approval")["events"]]
        self.assertIn("decided · post to Stage (operator)", titles)

    def test_an_answer_signed_by_no_pinned_key_decides_nothing_and_sends_nothing(self):
        self.pin()
        decision_id, _ = self.decide("Pick a name?")
        entry = self.entry("decision", decision_id, "Wait", "")
        stranger = key(-7, "stranger").proof(self.prepare([entry])["payload"], self.origin)
        with mock.patch.object(batches, "UNDO", 0.05):
            self.assertEqual(self.approve([entry], stranger)[0], 202)
            self.settle(lambda: any(row["text"].startswith("failed: not signed") for row in self.events("kinds=approval")["events"]))
        state = self.tool("decision_wait", {"id": decision_id, "timeout_seconds": 0})["structuredContent"]
        self.assertEqual((state["status"], state["message"], state["answer"]), ("pending", None, None))
        self.assertEqual((self.scripts.calls, self.httpd.hub.messages.listed()), ([], []))

    def test_the_tasks_feed_lists_every_kind_that_waits_on_the_operator_and_no_choices_column(self):
        self.create_ask(ASK)
        greet = {"title": "echo hi", "workdir": "/repo", "check": "manual", "status": "queued", "roles": {"Operator": "R", "Skills": "A"}}
        self.write_council({"rasci.json": {"operator/greet": greet}})
        rule = {"kind": "ask", "tool": "Bash", "pattern": "make deploy", "scope": "/repo*", "expires": int(time.time()) + 86400, "agent": "Skills", "why": "deploys after green gates"}
        self.assertFalse(self.tool("rule_request", rule)["isError"])
        decision_id, _ = self.decide("Pick a name?")
        inbox = self.snapshot()["inbox"]
        self.assertEqual(sorted(item["kind"] for item in inbox), ["ask", "decision", "operator", "rule"])
        card = next(item for item in inbox if item["id"] == decision_id)
        self.assertEqual((card["agent"], [option["label"] for option in card["options"]]), ("Stage", ["Merge now", "Wait"]))
        page = (HUB / "templates" / "page-tasks.js").read_text(encoding="utf-8")
        columns = re.search(r"const TASK_COLUMNS = (.*);", page).group(1)
        self.assertNotIn("choice", columns.lower())
        self.assertIn('["operator", "Waits on Operator", "bi-person-raised-hand", null]', page)
        self.assertIn('decision: "Choice"', (HUB / "templates" / "page-constants.js").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
