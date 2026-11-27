from __future__ import annotations

import json
import subprocess
import sys
import time
import unittest
from unittest import mock

from hub_support import ASK, CLIENT, HOOK, signing
from kvb_orchestrator import batches, skill_scripts
from kvb_orchestrator.asking import TERMINAL
from kvb_orchestrator.denying import LAPSED
from kvb_orchestrator.inbox import LAPSE_WINDOW, lapsed_of
from kvb_orchestrator.matching import EXPIRED, EXPIRED_REASONS, expired_card
from test_hub_match import MatchCase

FEEDBACK = "run it again after the gate"
PICK = "Execute (Recommended)"
CALL = signing.call_key("Bash", {"command": "make deploy"})
OTHER = signing.call_key("Bash", {"command": "make deploy", "run_in_background": True})
CALLED = {**ASK, "call_key": CALL}
QUESTION = {"question": "Clean up the two worktrees?", "options": [{"label": PICK, "description": "Both are merged"}], "session": "s1", "timeout": 60, "multi": False}


class TestExpiredFilter(unittest.TestCase):
    def test_the_expired_filter_keeps_a_pending_expired_ask_of_an_unrun_call_and_drops_a_decided_or_live_one(self):
        now = 100000.0
        records = [
            {"id": "gone", "status": "pending", "expires": now - 1, "call_key": CALL},
            {"id": "edge", "status": "pending", "expires": now, "call_key": CALL},
            {"id": "live", "status": "pending", "expires": now + 1, "call_key": CALL},
            {"id": "denied", "status": "denied", "expires": now - 1, "call_key": CALL},
            {"id": "ran", "status": TERMINAL, "expires": now - 1, "call_key": CALL},
            {"id": "hub", "status": "pending", "call_key": CALL},
        ]
        self.assertEqual([record["id"] for record in lapsed_of(records, now, True)], ["gone", "edge"])

    def test_the_expired_filter_drops_an_ask_without_call_key_and_anything_expired_more_than_24_hours_ago(self):
        now = 200000.0
        records = [
            {"id": "old-hook", "status": "pending", "expires": now - 60},
            {"id": "blank", "status": "pending", "expires": now - 60, "call_key": ""},
            {"id": "day", "status": "pending", "expires": now - LAPSE_WINDOW, "call_key": CALL},
            {"id": "older", "status": "pending", "expires": now - LAPSE_WINDOW - 1, "call_key": CALL},
        ]
        self.assertEqual([record["id"] for record in lapsed_of(records, now, True)], ["day"])
        self.assertEqual([record["id"] for record in lapsed_of(records, now, False)], ["old-hook", "blank", "day"])

    def test_an_expired_card_is_greyed_with_blocked_kind_expired_and_keeps_its_expires(self):
        card = expired_card({"id": "ask:a1", "kind": "ask", "blocked": "", "stale": False}, 990.0)
        self.assertEqual((card["blocked_kind"], card["blocked"], card["expires"], card["stale"]), (EXPIRED, EXPIRED_REASONS["ask"], 990.0, False))
        self.assertIn(LAPSED, card["blocked"].lower())

    def test_an_expired_decision_says_its_agent_stopped_waiting_not_that_a_tool_call_returned(self):
        card = expired_card({"id": "decision:d1", "kind": "decision", "blocked": "", "stale": False}, 990.0)
        self.assertEqual(card["blocked"], EXPIRED_REASONS["decision"])
        self.assertNotIn("tool call", card["blocked"])


class TestExpiredRelease(MatchCase):
    def radio(self) -> list[list[str]]:
        return [args for script, args in self.scripts.calls if script == skill_scripts.RADIO]

    def lapsed_ask(self, payload: dict) -> str:
        self.claim("s1", "Skills session")
        ask = self.create_ask(payload)
        self.httpd.hub.asks.change(ask, {"expires": time.time() - 600})
        return ask

    def lapsed_question(self) -> str:
        self.claim("s1", "Skills session")
        status, _, body = self.post_json("/api/decisions", QUESTION, self.local())
        self.assertEqual(status, 201, body)
        decision = json.loads(body)["id"]
        self.httpd.hub.decisions.change(decision, {"expires": time.time() - 60})
        return decision

    def ran(self, payload: dict, headers: dict[str, str]) -> tuple[int, dict]:
        status, _, body = self.post_json("/api/asks/ran", payload, headers)
        return status, json.loads(body) if status == 200 else {}

    def denial(self, kind: str, ident: str, to: str) -> dict:
        return {"kind": kind, "id": ident, "verb": "reject", "label": "", "sha256": "", "channel": "call", "reason": FEEDBACK, "to": to}

    def test_an_expired_ask_stays_a_greyed_card_with_its_expiry_but_leaves_the_inbox_and_the_badge(self):
        ask = self.lapsed_ask(CALLED)
        card = self.card(f"ask:{ask}")
        self.assertEqual((card["kind"], card["blocked_kind"], card["blocked"], card["to"]), ("ask", EXPIRED, EXPIRED_REASONS["ask"], "Skills"))
        self.assertEqual(card["expires"], self.httpd.hub.asks.get(ask)["expires"])
        snapshot = self.snapshot()
        self.assertNotIn(ask, [item["id"] for item in snapshot["inbox"]])
        self.assertEqual(snapshot["badges"]["tasks"], 0)

    def test_an_expired_ask_without_its_call_key_or_expired_over_a_day_ago_never_becomes_a_card(self):
        unknown = self.lapsed_ask(ASK)
        old = self.lapsed_ask(CALLED)
        self.httpd.hub.asks.change(old, {"expires": time.time() - LAPSE_WINDOW - 60})
        shown = [card["id"] for card in self.cards()]
        self.assertNotIn(f"ask:{unknown}", shown)
        self.assertNotIn(f"ask:{old}", shown)

    def test_the_call_key_is_the_digest_of_the_canonical_tool_name_and_input(self):
        self.assertEqual(signing.call_key("Bash", {"command": "make deploy", "description": "d"}), signing.call_key("Bash", {"description": "d", "command": "make deploy"}))
        self.assertNotEqual(CALL, OTHER)
        self.assertNotEqual(CALL, signing.call_key("Edit", {"command": "make deploy"}))
        self.assertRegex(CALL, r"^[0-9a-f]{64}$")

    def test_the_ask_takes_a_call_key_digest_and_refuses_another_shape(self):
        for bad in ("", "x" * 64, CALL.upper(), CALL[:63], 7):
            with self.subTest(bad=bad):
                self.assertEqual(self.post_json("/api/asks", {**ASK, "call_key": bad}, self.local())[0], 400)
        self.assertEqual(self.post_json("/api/asks", {**ASK, "tool_use_id": "toolu_01"}, self.local())[0], 400)
        self.assertEqual(self.httpd.hub.asks.get(self.create_ask(CALLED))["call_key"], CALL)
        self.assertEqual(self.httpd.hub.asks.get(self.create_ask(ASK))["call_key"], "")

    def test_the_terminal_report_closes_the_oldest_pending_ask_of_its_key_and_session_as_answered_in_the_terminal(self):
        first = self.lapsed_ask(CALLED)
        self.httpd.hub.asks.change(first, {"created_ts": time.time() - 900})
        second = self.lapsed_ask(CALLED)
        report = {"call_key": CALL, "session": "s1"}
        self.assertEqual(self.ran(report, {"Host": self.host})[0], 403)
        self.assertEqual(self.ran(report, {**self.local(), "Origin": "http://evil.example"})[0], 403)
        self.assertEqual(self.ran(report, self.local()), (200, {"closed": first}))
        record = self.httpd.hub.asks.get(first)
        self.assertEqual((record["status"], record["proof"]), (TERMINAL, None))
        self.assertEqual(self.ask_status(first, "0"), TERMINAL)
        self.assertEqual(self.httpd.hub.asks.get(second)["status"], "pending")
        self.assertNotIn(f"ask:{first}", [card["id"] for card in self.cards()])
        self.assertEqual(self.ran(report, self.local()), (200, {"closed": second}))
        self.assertEqual(self.ran(report, self.local()), (200, {"closed": None}))
        self.assertEqual(self.post_json("/api/sign", {"items": [self.denial("ask", first, "Skills")]}, self.guard(self.host))[0], 409)

    def test_a_report_never_closes_an_ask_created_after_it(self):
        ask = self.lapsed_ask(CALLED)
        self.httpd.hub.asks.change(ask, {"created_ts": time.time() + 60})
        self.assertEqual(self.ran({"call_key": CALL, "session": "s1"}, self.local()), (200, {"closed": None}))
        self.assertEqual(self.httpd.hub.asks.get(ask)["status"], "pending")

    def test_the_hook_client_keys_its_ask_and_reports_the_call_that_ran_and_prints_nothing(self):
        key = signing.call_key(HOOK["tool_name"], HOOK["tool_input"])
        ask = self.lapsed_ask({**ASK, "call_key": key})
        trust = ["--approvers", str(self.approvers), "--replay", str(self.replay / "hook.json")]
        event = {**HOOK, "hook_event_name": "PostToolUse", "tool_use_id": "toolu_01Ran", "tool_response": {"stdout": ""}}
        done = subprocess.run([sys.executable, str(CLIENT), "--port", str(self.port), "--timeout", "5", *trust], input=json.dumps(event), capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual((done.returncode, done.stdout), (0, ""), done.stderr)
        self.assertEqual(self.httpd.hub.asks.get(ask)["status"], TERMINAL)

    def test_a_foreign_session_a_different_input_or_a_bad_report_closes_nothing(self):
        ask = self.lapsed_ask(CALLED)
        self.assertEqual(self.ran({"call_key": CALL, "session": "s2"}, self.local()), (200, {"closed": None}))
        self.assertEqual(self.ran({"call_key": OTHER, "session": "s1"}, self.local()), (200, {"closed": None}))
        for bad in ({"call_key": CALL}, {"call_key": CALL, "session": ""}, {"call_key": "../x", "session": "s1"}, {"call_key": CALL, "session": "s1", "status": "allowed"}):
            with self.subTest(bad=bad):
                self.assertEqual(self.ran(bad, self.local())[0], 400)
        self.assertEqual(self.httpd.hub.asks.get(ask)["status"], "pending")
        self.assertIn(f"ask:{ask}", [card["id"] for card in self.cards()])

    def test_an_approve_of_an_expired_ask_or_decision_stays_refused(self):
        ask = self.lapsed_ask(CALLED)
        decision = self.lapsed_question()
        for entry in (self.entry("ask", ask, "", ""), self.entry("decision", decision, PICK, "")):
            with self.subTest(kind=entry["kind"]):
                self.assertEqual(self.post_json("/api/sign", {"items": [entry]}, self.guard(self.host))[0], 409)
                self.assertEqual(self.approve([entry], None)[0], 409)
        self.assertEqual((self.httpd.hub.asks.get(ask)["status"], self.httpd.hub.decisions.get(decision)["status"]), ("pending", "pending"))

    def test_a_denied_expired_ask_goes_through_the_release_and_tells_its_agent_why_by_call(self):
        ask = self.lapsed_ask(CALLED)
        card = self.card(f"ask:{ask}")
        entries = [self.denial(card["entry"], card["ref"], card["to"])]
        signer = self.pin()
        status, _, body = self.approve(entries, None)
        self.assertEqual(status, 400, body)
        self.assertIn("not signed", body.decode())
        with mock.patch.object(batches, "UNDO", 0.05):
            status, _, body = self.approve(entries, self.signed(entries, signer))
            self.assertEqual(status, 202, body)
            self.settle(lambda: self.httpd.hub.asks.get(ask)["status"] == "denied")
        self.settle(lambda: self.radio() != [])
        sent = self.radio()[0]
        self.assertEqual(sent[:4], ["send", "call", "--to", "Skills session"])
        self.assertTrue(sent[6].endswith(f"Denied by the operator: ask Bash: make deploy, {LAPSED} (from Skills). Reason: {FEEDBACK}"), sent)
        self.assertNotIn(f"ask:{ask}", [card["id"] for card in self.cards()])

    def test_a_denied_expired_question_is_marked_denied_and_its_agent_hears_why_while_a_live_one_takes_no_deny(self):
        self.claim("s1", "Skills session")
        status, _, body = self.post_json("/api/decisions", QUESTION, self.local())
        self.assertEqual(status, 201, body)
        live = json.loads(body)["id"]
        self.assertEqual(self.post_json("/api/sign", {"items": [self.denial("decision", live, "Skills")]}, self.guard(self.host))[0], 400)
        decision = self.lapsed_question()
        card = self.card(f"decision:{decision}")
        self.assertEqual((card["kind"], card["entry"], card["blocked_kind"], card["to"]), ("decision", "decision", EXPIRED, "Skills"))
        entries = [self.denial(card["entry"], card["ref"], card["to"])]
        with mock.patch.object(batches, "UNDO", 0.05):
            status, _, body = self.approve(entries, self.signed(entries, self.pin()))
            self.assertEqual(status, 202, body)
            self.settle(lambda: self.httpd.hub.decisions.get(decision)["status"] == "denied")
        self.settle(lambda: self.radio() != [])
        sent = self.radio()[0]
        self.assertEqual(sent[:4], ["send", "call", "--to", "Skills session"])
        self.assertTrue(sent[6].endswith(f"Denied by the operator: decision {QUESTION['question']}, {LAPSED} (from Skills). Reason: {FEEDBACK}"), sent)
        self.assertEqual(self.httpd.hub.decisions.get(live)["status"], "pending")
        self.assertNotIn(f"decision:{decision}", [card["id"] for card in self.cards()])


if __name__ == "__main__":
    unittest.main()
