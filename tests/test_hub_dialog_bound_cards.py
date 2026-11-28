"""Exercise requirement 094: a hub card lives as long as its Claude dialog and closes the moment either side answers."""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from hub_support import ASK, CLIENT, HOOK, signing
from kvb_orchestrator import batches, settings
from kvb_orchestrator.asking import (
    ENDED,
    IN_CLAUDE,
    IN_CLAUDE_WORDS,
    TERMINAL,
    dialog_state,
)
from kvb_orchestrator.errors import ToolError
from kvb_orchestrator.inbox import item_base, lapsed_item
from kvb_orchestrator.matching import claude_card, expired_card, lapsed_card
from kvb_orchestrator.triage import request_kind
from test_hub_match import MatchCase

permission_hook = importlib.import_module("permission_hook")

KEY = signing.call_key("Bash", {"command": "make deploy"})
OTHER = signing.call_key("Bash", {"command": "make other"})
TOKEN = "a" * 43
FOREIGN_TOKEN = "b" * 43
WRONG = "c" * 43
CLOSER = {"closer": TOKEN}
BOUND = {**ASK, "call_key": KEY, "bound": True, **CLOSER}
FIRST = "Clean up the two worktrees?"
SECOND = "Push the branch?"
QUESTIONS = {"questions": [{"question": FIRST, "options": [{"label": "Yes"}, {"label": "No"}]}, {"question": SECOND, "options": [{"label": "Now"}, {"label": "Later"}]}]}
ASKED = signing.call_key("AskUserQuestion", QUESTIONS)
OPTIONS = [{"label": "Yes", "description": ""}, {"label": "No", "description": ""}]


def question(text: str, session: str, extra: dict) -> dict:
    return {"question": text, "options": OPTIONS, "session": session, "timeout": 600, "multi": False, **extra}


class TestCardLifecycle(unittest.TestCase):
    def test_a_card_is_open_then_answered_in_the_hub_or_in_claude_or_open_in_claude(self):
        now = 10000.0
        live = {"status": "pending", "expires": now + 60, "bound": True}
        cases = {
            "open": (live, "pending"),
            "allowed in the hub": ({**live, "status": "allowed"}, "allowed"),
            "denied in the hub": ({**live, "status": "denied"}, "denied"),
            "picked in the hub": ({**live, "status": "decided"}, "decided"),
            "answered in Claude": ({**live, "status": TERMINAL}, TERMINAL),
            "answered in Claude after the wait": ({**live, "status": TERMINAL, "expires": now - 60}, TERMINAL),
            "open in Claude": ({**live, "expires": now - 1}, IN_CLAUDE),
            "open in Claude at the edge": ({**live, "expires": now}, IN_CLAUDE),
            "session ended": ({**live, "status": ENDED, "expires": now - 60}, ENDED),
            "unbound after the wait": ({**live, "bound": False, "expires": now - 1}, "expired"),
            "older hook after the wait": ({"status": "pending", "expires": now - 1}, "expired"),
            "decision without a wait": ({"status": "pending"}, "pending"),
        }
        for name, (record, state) in cases.items():
            with self.subTest(name=name):
                self.assertEqual(dialog_state(record, now), state)

    def test_a_card_open_in_claude_counts_as_open_and_carries_no_stale_or_expired_stamp(self):
        record = {"status": "pending", "expires": 990.0, "bound": True}
        item = lapsed_item({**item_base(), "kind": "ask", "id": "a1"}, record)
        self.assertEqual((item["claude"], item["blocked"], item["expires"], request_kind(item)), (True, IN_CLAUDE_WORDS, 990.0, "open"))
        card = lapsed_card({"id": "ask:a1", "kind": "ask", "stale": False}, item)
        self.assertEqual(card, claude_card({"id": "ask:a1", "kind": "ask", "stale": False}, 990.0))
        self.assertEqual((card["blocked_kind"], card["blocked"], card["expires"], card["stale"]), (IN_CLAUDE, IN_CLAUDE_WORDS, 990.0, False))
        self.assertTrue(card["blocked"].startswith("Open in Claude: answer it there"))
        self.assertNotIn("expired", card["blocked"].lower())
        self.assertNotIn("stale", card["blocked"].lower())

    def test_an_unbound_lapsed_card_stays_expired_as_080_has_it(self):
        item = lapsed_item({**item_base(), "kind": "ask", "id": "a1"}, {"status": "pending", "expires": 990.0})
        self.assertEqual((item["claude"], item["blocked"], request_kind(item)), (False, "", "expired"))
        self.assertEqual(lapsed_card({"id": "ask:a1", "kind": "ask", "stale": False}, item), expired_card({"id": "ask:a1", "kind": "ask", "stale": False}, 990.0))


class TestHookWaitSetting(unittest.TestCase):
    def test_the_wait_defaults_to_60_minutes_takes_whole_minutes_from_1_to_60_and_an_older_page_keeps_it(self):
        self.assertEqual(settings.SETTINGS["hook"], {"wait": 60})
        for good in (1, 30, 60):
            with self.subTest(good=good):
                self.assertEqual(settings.hook_setting({"wait": good}), {"wait": good})
        for bad in ({"wait": 0}, {"wait": 61}, {"wait": True}, {"wait": "5"}, {"wait": 5.5}, {}, {"wait": 5, "extra": 1}, 5):
            with self.subTest(bad=bad), self.assertRaises(ToolError):
                settings.hook_setting(bad)
        saved = settings.valid_settings({**settings.SETTINGS, "hook": {"wait": 7}})
        older = {key: value for key, value in saved.items() if key != "hook"}
        self.assertEqual(settings.valid_settings(settings.completed(older, saved))["hook"], {"wait": 7})


class TestHookClient(unittest.TestCase):
    def test_an_ask_user_question_is_keyed_without_the_answers_its_post_tool_use_input_carries(self):
        asked = {"tool_name": "AskUserQuestion", "tool_input": QUESTIONS}
        answered = {"tool_name": "AskUserQuestion", "tool_input": {**QUESTIONS, "answers": {FIRST: "Yes"}}}
        self.assertEqual(permission_hook.call_key_of(asked), ASKED)
        self.assertEqual(permission_hook.call_key_of(answered), ASKED)
        bash = {"tool_name": "Bash", "tool_input": {"command": "make deploy", "answers": {}}}
        self.assertNotEqual(permission_hook.call_key_of(bash), KEY)

    def test_the_answers_come_from_the_tool_response_else_the_tool_input_and_only_within_the_hub_limits(self):
        response = {"tool_name": "AskUserQuestion", "tool_input": QUESTIONS, "tool_response": {"questions": QUESTIONS["questions"], "answers": {FIRST: "Yes", SECOND: "Later"}}}
        self.assertEqual(permission_hook.ran_answers(response), {FIRST: "Yes", SECOND: "Later"})
        fallback = {"tool_name": "AskUserQuestion", "tool_input": {**QUESTIONS, "answers": {FIRST: "No"}}, "tool_response": "done"}
        self.assertEqual(permission_hook.ran_answers(fallback), {FIRST: "No"})
        for bad in ({**response, "tool_name": "Bash"}, {**response, "tool_response": {"answers": {FIRST: "x" * (permission_hook.ANSWER_LIMIT + 1)}}}, {**response, "tool_response": {"answers": {FIRST: 7}}}, {"tool_name": "AskUserQuestion", "tool_input": QUESTIONS}):
            with self.subTest(bad=str(bad)[:80]):
                self.assertIsNone(permission_hook.ran_answers(bad))


class ClosingCase(MatchCase):
    def setUp(self):
        super().setUp()
        self.claim("s1", "Skills session")
        self.claim("s2", "Other session")

    def ran(self, payload: dict) -> tuple[int, dict]:
        status, _, body = self.post_json("/api/asks/ran", payload, self.local())
        return status, json.loads(body) if status == 200 else {}

    def closed(self, payload: dict) -> tuple[int, set[str], set[str]]:
        status, found = self.ran(payload)
        return status, set(found.get("asks", [])), set(found.get("decisions", []))

    def decide(self, payload: dict) -> str:
        status, _, body = self.post_json("/api/decisions", payload, self.local())
        self.assertEqual(status, 201, body)
        return json.loads(body)["id"]

    def statuses(self) -> dict[str, str]:
        return {**{record["id"]: record["status"] for record in self.httpd.hub.asks.listed()}, **{record["id"]: record["status"] for record in self.httpd.hub.decisions.listed()}}

    def shown(self) -> set[str]:
        return {card["ref"] for card in self.cards()}


class TestClosingEvents(ClosingCase):
    def test_post_tool_use_closes_only_the_oldest_ask_of_its_session_and_call_key_as_answered_in_claude(self):
        mine, twin = self.create_ask(BOUND), self.create_ask(BOUND)
        self.httpd.hub.asks.change(mine, {"created_ts": time.time() - 60})
        foreign, other = self.create_ask({**BOUND, "session": "s2"}), self.create_ask({**BOUND, "call_key": OTHER})
        self.assertEqual(self.ran({"event": "PostToolUse", "call_key": KEY, "session": "s1", **CLOSER}), (200, {"asks": [mine], "decisions": []}))
        self.assertEqual(self.statuses(), {mine: TERMINAL, twin: "pending", foreign: "pending", other: "pending"})
        self.assertEqual(self.ask_status(mine, "0"), TERMINAL)
        self.assertEqual(self.shown() & {mine, twin, foreign, other}, {twin, foreign, other})
        self.assertEqual([item["id"] for item in self.snapshot()["inbox"] if item["kind"] == "ask"].count(mine), 0)

    def test_post_tool_use_of_an_ask_user_question_closes_its_decisions_with_the_answers_and_no_other_sessions(self):
        tied = {"call_key": ASKED, "bound": True, **CLOSER}
        first, second = self.decide(question(FIRST, "s1", tied)), self.decide(question(SECOND, "s1", tied))
        foreign, loose = self.decide(question(FIRST, "s2", tied)), self.decide(question(FIRST, "s1", CLOSER))
        report = {"event": "PostToolUse", "call_key": ASKED, "session": "s1", "answers": {f" {FIRST} ": "Yes", SECOND: "Later"}, **CLOSER}
        self.assertEqual(self.closed(report), (200, set(), {first, second}))
        self.assertEqual(self.statuses(), {first: TERMINAL, second: TERMINAL, foreign: "pending", loose: "pending"})
        self.assertEqual((self.httpd.hub.decisions.get(first)["choice"], self.httpd.hub.decisions.get(second)["choice"]), ("Yes", "Later"))
        status, _, body = self.get(f"/api/decisions/{first}?wait=0")
        self.assertEqual((status, json.loads(body)["status"], json.loads(body)["proof"]), (200, TERMINAL, None))
        refs = {event["ref"]["id"]: event["ref"] for event in self.events("kinds=decision")["events"]}
        self.assertEqual((refs[first]["status"], refs[first]["choice"]), (TERMINAL, "Yes"))
        self.assertEqual(self.shown() & {first, second, foreign, loose}, {foreign, loose})

    def test_stop_and_user_prompt_submit_close_every_open_card_of_the_main_agent_of_their_session_only(self):
        for event in ("Stop", "UserPromptSubmit"):
            with self.subTest(event=event):
                ask, lapsed = self.create_ask(BOUND), self.create_ask({**BOUND, "call_key": OTHER})
                self.httpd.hub.asks.change(lapsed, {"expires": time.time() - 60})
                decision = self.decide(question(FIRST, "s1", {"bound": True, **CLOSER}))
                sub, sub_decision = self.create_ask({**BOUND, "agent": "Explore"}), self.decide(question(SECOND, "s1", {"subagent": "Explore", **CLOSER}))
                foreign = self.create_ask({**BOUND, "session": "s2"})
                self.assertEqual(self.closed({"event": event, "session": "s1", **CLOSER}), (200, {ask, lapsed}, {decision}))
                self.assertEqual({key: value for key, value in self.statuses().items() if key in (ask, lapsed, decision, sub, sub_decision, foreign)}, {ask: TERMINAL, lapsed: TERMINAL, decision: TERMINAL, sub: "pending", sub_decision: "pending", foreign: "pending"})
                self.assertEqual(self.shown() & {ask, lapsed, decision, sub, sub_decision, foreign}, {sub, sub_decision, foreign})
                self.ran({"event": "SessionEnd", "session": "s1", **CLOSER})
                self.ran({"event": "SessionEnd", "session": "s2", **CLOSER})

    def test_session_end_closes_every_card_of_its_session_as_ended_subagents_included_and_no_other(self):
        ask, sub = self.create_ask(BOUND), self.create_ask({**BOUND, "agent": "Explore"})
        decision = self.decide(question(FIRST, "s1", {"subagent": "Explore", "bound": True, **CLOSER}))
        foreign, foreign_decision = self.create_ask({**BOUND, "session": "s2"}), self.decide(question(FIRST, "s2", CLOSER))
        self.assertEqual(self.closed({"event": "SessionEnd", "session": "s1", **CLOSER}), (200, {ask, sub}, {decision}))
        self.assertEqual(self.statuses(), {ask: ENDED, sub: ENDED, decision: ENDED, foreign: "pending", foreign_decision: "pending"})
        self.assertEqual(self.ran({"event": "SessionEnd", "session": "s1", **CLOSER}), (200, {"asks": [], "decisions": []}))
        self.assertEqual(self.shown() & {ask, sub, decision, foreign, foreign_decision}, {foreign, foreign_decision})
        refs = {event["ref"]["id"]: event["ref"]["status"] for event in self.events("kinds=ask")["events"]}
        self.assertEqual((refs[ask], refs[foreign]), (ENDED, "pending"))

    def test_a_closing_report_needs_the_local_guard_and_valid_fields_and_never_closes_a_card_created_after_it(self):
        ask = self.create_ask(BOUND)
        later = self.create_ask({**BOUND, "call_key": OTHER})
        self.httpd.hub.asks.change(later, {"created_ts": time.time() + 60})
        stop = {"event": "Stop", "session": "s1", **CLOSER}
        self.assertEqual(self.post_json("/api/asks/ran", stop, {"Host": self.host})[0], 403)
        self.assertEqual(self.post_json("/api/asks/ran", stop, {**self.local(), "Origin": "http://evil.example"})[0], 403)
        bad = (
            {"event": "Notification", "session": "s1"}, {"event": ["Stop"], "session": "s1"}, {"event": "Stop"}, {"event": "Stop", "session": ""}, {"event": "Stop", "session": "s" * 201},
            {"event": "Stop", "session": "s1", "call_key": KEY}, {"event": "SessionEnd", "session": "s1", "answers": {}}, {"event": "PostToolUse", "session": "s1"},
            {"event": "PostToolUse", "call_key": KEY, "session": "s1", "answers": {FIRST: "x" * 4001}}, {"event": "PostToolUse", "call_key": KEY, "session": "s1", "answers": {FIRST: "a\u200bb"}},
            {"event": "PostToolUse", "call_key": KEY, "session": "s1", "answers": [FIRST]}, {"event": "Stop", "session": "s1", "status": "allowed"},
            {**stop, "closer": "short"}, {**stop, "closer": 7}, {**stop, "closer": "a" * 129}, {**stop, "closer": "a/" * 20}, {**stop, "closer": TOKEN + "\u200b"},
            {"event": "PostToolUse", "call_key": KEY, "session": "s1", "closer": "../" * 12},
        )
        for payload in bad:
            with self.subTest(payload=str(payload)[:80]):
                self.assertEqual(self.ran(payload)[0], 400)
        self.assertEqual(self.statuses(), {ask: "pending", later: "pending"})
        self.assertEqual(self.ran(stop), (200, {"asks": [ask], "decisions": []}))
        self.assertEqual(self.httpd.hub.asks.get(later)["status"], "pending")

    def test_a_bound_card_whose_hook_timed_out_reads_open_in_claude_until_a_closing_event_and_an_unbound_one_expires(self):
        bound, unbound = self.create_ask(BOUND), self.create_ask({**ASK, "call_key": OTHER})
        for ask in (bound, unbound):
            self.httpd.hub.asks.change(ask, {"expires": time.time() - 600})
        card = self.card(f"ask:{bound}")
        self.assertEqual((card["blocked_kind"], card["blocked"], card["stale"], card["stale_reason"]), (IN_CLAUDE, IN_CLAUDE_WORDS, False, ""))
        self.assertEqual(self.card(f"ask:{unbound}")["blocked_kind"], "expired")
        lapsed = {item["id"]: item for item in self.snapshot()["lapsed"]}
        self.assertEqual((lapsed[bound]["request"], lapsed[bound]["claude"], lapsed[unbound]["request"]), ("open", True, "expired"))
        self.assertEqual(self.ask_status(bound, "0"), "expired")
        refs = {event["ref"]["id"]: event["ref"]["status"] for event in self.events("kinds=ask")["events"]}
        self.assertEqual((refs[bound], refs[unbound]), (IN_CLAUDE, "expired"))
        self.assertEqual(self.ran({"event": "PostToolUse", "call_key": KEY, "session": "s1", **CLOSER}), (200, {"asks": [bound], "decisions": []}))
        self.assertNotIn(f"ask:{bound}", [card["id"] for card in self.cards()])

    def test_a_dismissed_card_open_in_claude_leaves_the_hub_but_stays_pending_for_its_dialog(self):
        ask = self.create_ask(BOUND)
        self.httpd.hub.asks.change(ask, {"expires": time.time() - 600})
        entries = [{"kind": "dismiss", "target": "ask", "id": ask, "scope": "open"}]
        with mock.patch.object(batches, "UNDO", 0.05):
            status, _, body = self.post_json("/api/requests/dismiss", {"items": entries, "proof": self.signed(entries, self.pin())}, self.guard(self.host))
            self.assertEqual(status, 202, body)
            self.settle(lambda: self.httpd.hub.dismissals.listed() != [])
        self.assertEqual(self.httpd.hub.asks.get(ask)["status"], "pending")
        self.assertNotIn(f"ask:{ask}", [card["id"] for card in self.cards()])

    def client(self, event: dict, timeout: str) -> subprocess.CompletedProcess:
        trust = ["--approvers", str(self.approvers), "--replay", str(self.replay / "hook.json"), "--bound"]
        return subprocess.run([sys.executable, str(CLIENT), "--port", str(self.port), "--timeout", timeout, *trust], input=json.dumps(event), capture_output=True, text=True, timeout=60, check=False)

    def test_the_hook_client_reports_stop_user_prompt_submit_and_session_end_of_its_own_session_and_prints_nothing(self):
        base = {"session_id": "s1", "transcript_path": HOOK["transcript_path"], "cwd": "/repo"}
        replay = self.replay / "hook.json"
        for event, extra, closed in (("Stop", {"stop_hook_active": False}, TERMINAL), ("UserPromptSubmit", {"prompt": "go on"}, TERMINAL), ("SessionEnd", {"reason": "prompt_input_exit"}, ENDED)):
            with self.subTest(event=event):
                token = permission_hook.closer_token(replay, "s1")
                ask, foreign = self.create_ask({**BOUND, "closer": token}), self.create_ask({**BOUND, "session": "s2", "closer": token})
                done = self.client({**base, "hook_event_name": event, **extra}, "5")
                self.assertEqual((done.returncode, done.stdout), (0, ""), done.stderr)
                self.assertEqual((self.httpd.hub.asks.get(ask)["status"], self.httpd.hub.asks.get(foreign)["status"]), (closed, "pending"))
                self.assertEqual(permission_hook.closer_path(replay, "s1").exists(), event != "SessionEnd")
                self.ran({"event": "SessionEnd", "session": "s2", "closer": token})

    def test_a_waiting_hook_whose_dialog_claude_answered_returns_at_once_without_a_decision(self):
        trust = ["--approvers", str(self.approvers), "--replay", str(self.replay / "hook.json"), "--bound"]
        argv = [sys.executable, str(CLIENT), "--port", str(self.port), "--timeout", "3600", *trust]
        with subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as hook:
            hook.stdin.write(json.dumps(HOOK))
            hook.stdin.close()
            self.settle(lambda: any(ask["status"] == "pending" for ask in self.httpd.hub.asks.listed()))
            ask = next(ask for ask in self.httpd.hub.asks.listed() if ask["status"] == "pending")
            self.assertEqual((ask["bound"], ask["call_key"]), (True, signing.call_key(HOOK["tool_name"], HOOK["tool_input"])))
            token = permission_hook.closer_path(self.replay / "hook.json", HOOK["session_id"]).read_text(encoding="ascii")
            self.assertEqual(ask["closer_digest"], hashlib.sha256(token.encode()).hexdigest())
            self.assertNotIn(token, json.dumps(ask))
            self.assertAlmostEqual(ask["expires"] - ask["created_ts"], 3600.0, places=3)
            done = self.client({**HOOK, "hook_event_name": "PostToolUse", "tool_use_id": "toolu_01Ran", "tool_response": {"stdout": ""}}, "5")
            self.assertEqual((done.returncode, done.stdout), (0, ""), done.stderr)
            started = time.monotonic()
            self.assertEqual(hook.wait(timeout=30), 0)
            self.assertLess(time.monotonic() - started, 10)
            self.assertEqual(hook.stdout.read(), "")
        self.assertEqual(self.httpd.hub.asks.get(ask["id"])["status"], TERMINAL)


class TestCloserBinding(ClosingCase):
    def test_a_close_without_or_with_a_wrong_closer_closes_nothing(self):
        ask = self.create_ask(BOUND)
        decision = self.decide(question(FIRST, "s1", {"call_key": ASKED, "bound": True, **CLOSER}))
        for closer in ({}, {"closer": WRONG}, {"closer": FOREIGN_TOKEN}):
            for report in ({"event": "Stop", "session": "s1"}, {"event": "UserPromptSubmit", "session": "s1"}, {"event": "SessionEnd", "session": "s1"}, {"event": "PostToolUse", "call_key": KEY, "session": "s1"}, {"event": "PostToolUse", "call_key": ASKED, "session": "s1", "answers": {FIRST: "No"}}):
                with self.subTest(report=report, closer=closer):
                    self.assertEqual(self.closed({**report, **closer}), (200, set(), set()))
        self.assertEqual(self.statuses(), {ask: "pending", decision: "pending"})
        self.assertIsNone(self.httpd.hub.decisions.get(decision)["choice"])

    def test_the_right_closer_closes_only_the_cards_of_its_own_session(self):
        mine, theirs = self.create_ask(BOUND), self.create_ask({**BOUND, "session": "s2", "closer": FOREIGN_TOKEN})
        mine_decision, their_decision = self.decide(question(FIRST, "s1", CLOSER)), self.decide(question(FIRST, "s2", {"closer": FOREIGN_TOKEN}))
        self.assertEqual(self.closed({"event": "SessionEnd", "session": "s2", **CLOSER}), (200, set(), set()))
        self.assertEqual(self.closed({"event": "SessionEnd", "session": "s1", "closer": FOREIGN_TOKEN}), (200, set(), set()))
        self.assertEqual(self.closed({"event": "SessionEnd", "session": "s1", **CLOSER}), (200, {mine}, {mine_decision}))
        self.assertEqual(self.statuses(), {mine: ENDED, mine_decision: ENDED, theirs: "pending", their_decision: "pending"})
        self.assertEqual(self.closed({"event": "SessionEnd", "session": "s2", "closer": FOREIGN_TOKEN}), (200, {theirs}, {their_decision}))

    def test_a_forged_choice_is_never_recorded(self):
        bound = self.decide(question(FIRST, "s1", {"call_key": ASKED, "bound": True, **CLOSER}))
        older = self.decide(question(SECOND, "s1", {"call_key": ASKED}))
        forged = {"event": "PostToolUse", "call_key": ASKED, "session": "s1", "answers": {FIRST: "No", SECOND: "Now"}}
        self.assertEqual(self.closed({**forged, "closer": WRONG}), (200, set(), {older}))
        self.assertEqual((self.httpd.hub.decisions.get(older)["status"], self.httpd.hub.decisions.get(older)["choice"]), (TERMINAL, None))
        self.assertEqual((self.httpd.hub.decisions.get(bound)["status"], self.httpd.hub.decisions.get(bound)["choice"]), ("pending", None))
        self.assertEqual(self.closed({**forged, "answers": {FIRST: "Yes"}, **CLOSER}), (200, set(), {bound}))
        self.assertEqual(self.httpd.hub.decisions.get(bound)["choice"], "Yes")

    def test_an_older_hook_card_closes_by_its_call_key_but_never_by_a_session_wide_event(self):
        ask = self.create_ask({**ASK, "call_key": KEY})
        decision = self.decide(question(FIRST, "s1", {"call_key": ASKED}))
        self.assertEqual((self.httpd.hub.asks.get(ask)["closer_digest"], self.httpd.hub.decisions.get(decision)["closer_digest"]), ("", ""))
        for closer in ({}, CLOSER):
            for event in ("Stop", "UserPromptSubmit", "SessionEnd"):
                with self.subTest(event=event, closer=closer):
                    self.assertEqual(self.closed({"event": event, "session": "s1", **closer}), (200, set(), set()))
        self.assertEqual(self.closed({"event": "PostToolUse", "call_key": KEY, "session": "s1"}), (200, {ask}, set()))
        self.assertEqual(self.closed({"event": "PostToolUse", "call_key": ASKED, "session": "s1"}), (200, set(), {decision}))
        self.assertEqual(self.statuses(), {ask: TERMINAL, decision: TERMINAL})

    def test_the_hub_keeps_only_the_digest_of_the_closer(self):
        ask = self.httpd.hub.asks.get(self.create_ask(BOUND))
        decision = self.httpd.hub.decisions.get(self.decide(question(FIRST, "s1", CLOSER)))
        digest = hashlib.sha256(TOKEN.encode()).hexdigest()
        for record in (ask, decision):
            with self.subTest(record=record["id"]):
                self.assertEqual(record["closer_digest"], digest)
                self.assertNotIn(TOKEN, json.dumps(record))
                self.assertNotIn("closer", record)
        for bad in ("short", 7, "a" * 129, "../" * 12):
            with self.subTest(bad=bad):
                self.assertEqual(self.post_json("/api/asks", {**BOUND, "closer": bad}, self.local())[0], 400)
                self.assertEqual(self.post_json("/api/decisions", question(FIRST, "s1", {"closer": bad}), self.local())[0], 400)


class TestCloserToken(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.replay = self.root / "approvals" / "hook.json"

    def test_the_token_file_is_made_once_per_session_with_mode_0600_and_kept(self):
        token = permission_hook.closer_token(self.replay, "s1")
        path = permission_hook.closer_path(self.replay, "s1")
        self.assertRegex(token, r"^[A-Za-z0-9_-]{43}$")
        self.assertEqual((path.parent, path.read_text(encoding="ascii")), (self.replay.parent / permission_hook.CLOSERS, token))
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode) & 0o077, 0)
        self.assertEqual(permission_hook.closer_token(self.replay, "s1"), token)
        self.assertNotEqual(permission_hook.closer_token(self.replay, "s2"), token)
        self.assertEqual(sorted(name.name for name in path.parent.iterdir()), ["s1.token", "s2.token"])

    def test_a_file_a_concurrent_hook_linked_first_wins(self):
        path = permission_hook.closer_path(self.replay, "s1")
        path.parent.mkdir(parents=True)
        path.write_text(TOKEN, encoding="ascii")
        real = permission_hook.read_closer
        reads = iter([None])
        with mock.patch.object(permission_hook, "read_closer", side_effect=lambda found: next(reads, real(found))), mock.patch.object(permission_hook.os, "link", wraps=os.link) as link:
            self.assertEqual(permission_hook.closer_token(self.replay, "s1"), TOKEN)
        self.assertEqual(link.call_count, 1)
        self.assertEqual((path.read_text(encoding="ascii"), sorted(name.name for name in path.parent.iterdir())), (TOKEN, ["s1.token"]))

    def test_a_session_id_outside_the_pattern_never_names_a_path_and_gets_no_token(self):
        for bad in ("", "..", "../s1", "a/b", "-s1", "s1.token", "s" * 129, "s1\n", "/etc/passwd"):
            with self.subTest(bad=bad):
                self.assertIsNone(permission_hook.closer_path(self.replay, bad))
                self.assertEqual(permission_hook.closer_token(self.replay, bad), "")
        self.assertEqual(list(self.root.iterdir()), [])

    def test_a_linked_or_malformed_token_file_is_refused(self):
        path = permission_hook.closer_path(self.replay, "s1")
        path.parent.mkdir(parents=True)
        target = self.root / "elsewhere"
        target.write_text(TOKEN, encoding="ascii")
        path.symlink_to(target)
        with self.assertRaises(OSError):
            permission_hook.closer_token(self.replay, "s1")
        path.unlink()
        path.write_text("x", encoding="ascii")
        with self.assertRaises(ValueError):
            permission_hook.closer_token(self.replay, "s1")

    def reports(self, hook: dict) -> list[dict]:
        sent: list[dict] = []
        with mock.patch.object(permission_hook.hub_api, "call", side_effect=lambda request, _: sent.append(json.loads(request.data))):
            permission_hook.report_ran("http://127.0.0.1:9", hook, self.replay)
        return sent

    def test_every_report_carries_the_token_and_session_end_deletes_its_file_even_when_the_report_fails(self):
        self.assertEqual(self.reports({"hook_event_name": "Stop", "session_id": "s1"}), [])
        token = permission_hook.closer_token(self.replay, "s1")
        ran = {"hook_event_name": "PostToolUse", "session_id": "s1", "tool_name": "Bash", "tool_input": {"command": "make deploy"}}
        self.assertEqual(self.reports(ran), [{"event": "PostToolUse", "call_key": KEY, "session": "s1", "closer": token}])
        self.assertEqual(self.reports({"hook_event_name": "Stop", "session_id": "s1"}), [{"event": "Stop", "session": "s1", "closer": token}])
        self.assertEqual(self.reports({"hook_event_name": "SessionEnd", "session_id": "s1"}), [{"event": "SessionEnd", "session": "s1", "closer": token}])
        self.assertFalse(permission_hook.closer_path(self.replay, "s1").exists())
        self.assertEqual(self.reports({**ran, "session_id": "s2"}), [{"event": "PostToolUse", "call_key": KEY, "session": "s2"}])
        permission_hook.closer_token(self.replay, "s1")
        with mock.patch.object(permission_hook.hub_api, "call", side_effect=OSError("hub down")), self.assertRaises(OSError):
            permission_hook.report_ran("http://127.0.0.1:9", {"hook_event_name": "SessionEnd", "session_id": "s1"}, self.replay)
        self.assertFalse(permission_hook.closer_path(self.replay, "s1").exists())


if __name__ == "__main__":
    unittest.main()
