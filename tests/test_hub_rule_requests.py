from __future__ import annotations

import json
import time
import unittest
from unittest import mock

from hub_case import HubCase
from hub_support import ASK, PAGE, PRESENT, key, signing
from kvb_orchestrator import batches, denying, requesting, skill_scripts


class TestHubRuleRequests(HubCase):
    def ask_rule(self, **change: object) -> dict:
        return {"kind": "ask", "tool": "Bash", "pattern": "make test*", "scope": "/repo*", "expires": int(time.time()) + 86400, "agent": "Skills", "why": "the gate runs make test all day", **change}

    def requested(self, arguments: dict) -> str:
        result = self.tool("rule_request", arguments)
        self.assertFalse(result["isError"], result)
        return result["structuredContent"]["id"]

    def waited(self, request_id: str) -> dict:
        return self.tool("rule_request_wait", {"id": request_id, "timeout_seconds": 0})["structuredContent"]

    def item(self, request_id: str) -> dict | None:
        return next((item for item in self.snapshot()["inbox"] if item["kind"] == "rule" and item["id"] == request_id), None)

    def action(self, request_id: str, verb: str, payload: object, headers: dict[str, str]) -> tuple[int, dict]:
        status, _, body = self.post_json(f"/api/rule-requests/{request_id}/{verb}", payload, headers)
        return status, json.loads(body) if status < 300 else {}

    def test_a_requested_rule_is_shown_with_its_dry_run_and_stored_only_signed(self):
        now = time.time()
        for change in (
            {"expires": int(now) - 1},
            {"expires": int(now) + 400 * 86400},
            {"tool": ""},
            {"kind": "review"},
            {"kind": "decision", "tool": "", "scope": "/repo"},
            {"kind": "radio"},
            {"pattern": " "},
            {"scope": "two\nlines"},
            {"why": " "},
            {"agent": ""},
            {"extra": 1},
        ):
            with self.subTest(change=change):
                self.assertTrue(self.tool("rule_request", self.ask_rule(**change))["isError"])
        for command, cwd in (("make test", "/repo"), ("make test-unit", "/repo/sub"), ("make deploy", "/repo"), ("make test && rm -rf /", "/repo"), ("make test", "/elsewhere")):
            self.create_ask({**ASK, "command": command, "cwd": cwd})
        request_id = self.requested(self.ask_rule())
        item = self.item(request_id)
        arguments = self.ask_rule()
        self.assertEqual({name: item["rule"][name] for name in ("kind", "tool", "pattern", "scope")}, {name: arguments[name] for name in ("kind", "tool", "pattern", "scope")})
        self.assertEqual((item["agent"], item["detail"], item["green"], item["deniable"], item["dry_run"]), ("Skills", "the gate runs make test all day", False, True, {"matched": 2, "total": 5, "days": 7}))
        self.assertEqual(self.waited(request_id), {"id": request_id, "status": "pending", "rule": None, "reason": "", "decided": None})
        self.assertEqual(self.approve([self.entry("rule", request_id, "", "")], None)[0], 400)
        self.assertEqual(self.action(request_id, "sign", {}, self.client())[0], 403)
        self.assertEqual(self.action("0123456789abcdef", "sign", {}, self.guard(self.host))[0], 404)
        self.assertEqual(self.get(f"/api/rule-requests/{request_id}/sign")[0], 405)
        signer = self.pin()
        status, prepared = self.action(request_id, "sign", {}, self.guard(self.host))
        self.assertEqual(status, 200)
        rule = prepared["payload"]
        self.assertEqual((rule["kinds"], rule["tool"], rule["pattern"], rule["scope"], rule["expires"]), (["ask"], "Bash", "make test*", "/repo*", arguments["expires"]))
        self.assertEqual((prepared["challenge"], prepared["credentials"], prepared["sign"]), (signing.challenge(rule), [signer.id], True))
        signed = signer.assertion(rule, self.origin, "localhost", PRESENT, 0)
        wider = {**rule, "pattern": "*"}
        for payload in ({"rule": rule, "assertion": None}, {"rule": wider, "assertion": signer.assertion(wider, self.origin, "localhost", PRESENT, 0)}, {"rule": rule}, {"rule": {**rule, "kinds": ["ask", "review"]}, "assertion": signed}):
            with self.subTest(payload=str(payload)[:80]):
                self.assertEqual(self.action(request_id, "accept", payload, self.guard(self.host))[0], 400)
        self.assertEqual(self.action(request_id, "accept", {"rule": rule, "assertion": signed}, self.client())[0], 403)
        status, accepted = self.action(request_id, "accept", {"rule": rule, "assertion": signed}, self.guard(self.host))
        self.assertEqual((status, accepted["status"], accepted["rule"]), (201, "accepted", rule["id"]))
        stored = self.httpd.hub.rules.get(rule["id"])
        self.assertEqual({name: stored[name] for name in ("kind", "tool", "pattern", "scope", "expires", "enabled")}, {"kind": "ask", "tool": "Bash", "pattern": "make test*", "scope": "/repo*", "expires": float(arguments["expires"]), "enabled": True})
        self.assertEqual(stored["proof"], {"payload": rule, "assertion": signed})
        form = self.post_json("/api/rules/sign", {name: arguments[name] for name in ("kind", "tool", "pattern", "scope", "expires")}, self.guard(self.host))
        formed = json.loads(form[2])["payload"]
        self.post_json("/api/rules", {"rule": formed, "assertion": signer.assertion(formed, self.origin, "localhost", PRESENT, 0), "enabled": True}, self.guard(self.host))
        self.assertEqual(set(self.httpd.hub.rules.get(formed["id"])), set(stored))
        self.assertEqual(self.action(request_id, "accept", {"rule": rule, "assertion": signed}, self.guard(self.host))[0], 409)
        self.assertIsNone(self.item(request_id))
        answer = self.waited(request_id)
        self.assertEqual((answer["status"], answer["rule"]), ("accepted", rule["id"]))
        with mock.patch.object(batches, "UNDO", 0.05):
            matched = self.create_ask({**ASK, "command": "make test"})
            self.settle(lambda: self.ask_status(matched, "0") == "allowed")

    def test_review_and_decision_requests_count_their_own_history(self):
        self.request("feat: green", "")
        self.tool("review_request", {**self.arguments("feat: red", "", self.page("red.html", PAGE)), "gate": "fail"})
        self.decision("Merge now")
        self.decision("")
        review = self.requested(self.ask_rule(kind="review", tool="", pattern="feature/*", scope="/repo/*"))
        choice = self.requested(self.ask_rule(kind="decision", tool="", pattern="Sk*", scope="*"))
        self.assertEqual(self.item(review)["dry_run"], {"matched": 1, "total": 2, "days": 7})
        self.assertEqual(self.item(choice)["dry_run"], {"matched": 1, "total": 2, "days": 7})
        signer = self.pin()
        _, prepared = self.action(choice, "sign", {}, self.guard(self.host))
        self.assertEqual(self.action(choice, "accept", {"rule": prepared["payload"], "assertion": None}, self.guard(self.host))[0], 400)
        status, _ = self.action(choice, "accept", {"rule": prepared["payload"], "assertion": signer.assertion(prepared["payload"], self.origin, "localhost", PRESENT, 0)}, self.guard(self.host))
        self.assertEqual(status, 201)

    def test_an_assertion_the_hub_cannot_verify_stores_no_rule(self):
        signer = self.pin()
        request_id = self.requested(self.ask_rule())
        _, prepared = self.action(request_id, "sign", {}, self.guard(self.host))
        rule = prepared["payload"]
        for name, assertion in (("empty", {}), ("unpinned key", key(-8, "stranger").assertion(rule, self.origin, "localhost", PRESENT, 0)), ("other origin", signer.assertion(rule, "http://localhost:1", "localhost", PRESENT, 0)), ("other rule", signer.assertion({**rule, "pattern": "*"}, self.origin, "localhost", PRESENT, 0))):
            with self.subTest(name=name):
                status, _, body = self.post_json(f"/api/rule-requests/{request_id}/accept", {"rule": rule, "assertion": assertion}, self.guard(self.host))
                self.assertEqual(status, 400, body)
                self.assertIn("not signed", body.decode())
        self.assertEqual((self.waited(request_id)["status"], self.httpd.hub.rules.listed()), ("pending", []))
        self.assertIsNotNone(self.item(request_id))
        now = int(time.time())
        for fields in ({"kind": "ask", "tool": "Bash", "pattern": "make *", "scope": "/repo*"}, {"kind": "review", "tool": "", "pattern": "feature/*", "scope": "/repo/*"}, {"kind": "decision", "tool": "", "pattern": "*", "scope": "*"}):
            offer = json.loads(self.post_json("/api/rules/sign", {**fields, "expires": now + 3600}, self.guard(self.host))[2])
            self.assertTrue(offer["sign"])
            for assertion in (None, {}, key(-8, "stranger").assertion(offer["payload"], self.origin, "localhost", PRESENT, 0)):
                with self.subTest(kind=fields["kind"], assertion=str(assertion)[:40]):
                    self.assertEqual(self.post_json("/api/rules", {"rule": offer["payload"], "assertion": assertion, "enabled": True}, self.guard(self.host))[0], 400)
        self.assertEqual(self.httpd.hub.rules.listed(), [])
        with mock.patch.object(batches, "UNDO", 0.05):
            asked = self.create_ask({**ASK, "command": "make test"})
            time.sleep(0.3)
        self.assertEqual(self.ask_status(asked, "0"), "pending")

    def test_a_request_lapses_with_the_ask_lifetime_and_frees_its_cap(self):
        self.pin()
        first = [self.requested(self.ask_rule(pattern=f"make test{index}*")) for index in range(requesting.AGENT_CAP)]
        self.assertTrue(self.tool("rule_request", self.ask_rule(pattern="make lint*"))["isError"])
        with mock.patch.object(denying, "ASK_LIFETIME", 0):
            self.assertEqual(self.waited(first[0])["status"], "expired")
            self.assertIsNone(self.item(first[0]))
            self.assertEqual(self.action(first[0], "sign", {}, self.guard(self.host))[0], 409)
            entry = {**self.entry("rule", first[0], "", ""), "verb": "reject", "channel": "post", "reason": "", "to": "Skills"}
            self.assertEqual(self.post_json("/api/sign", {"items": [entry]}, self.guard(self.host))[0], 409)
            self.requested(self.ask_rule(pattern="make lint*"))
        self.assertEqual(self.waited(first[0])["status"], "pending")

    def test_pending_requests_are_capped_and_a_denial_reaches_the_agent(self):
        self.claim("s1", "Skills session")
        first = [self.requested(self.ask_rule(pattern=f"make test{index}*")) for index in range(requesting.AGENT_CAP)]
        refused = self.tool("rule_request", self.ask_rule(pattern="make lint*"))
        self.assertTrue(refused["isError"])
        self.assertIn("pending", refused["content"][0]["text"])
        other = self.requested(self.ask_rule(agent="Docs"))
        entry = {**self.entry("rule", first[0], "", ""), "verb": "reject", "channel": "post", "reason": "too broad", "to": self.item(first[0])["to"]}
        self.assertEqual(entry["to"], "Skills")
        self.assertEqual(self.prepare([entry])["payload"]["items"], [signing.item_hash(signing.denial_item(signing.rule_request_item(first[0], "ask", "Bash", "make test0*", "/repo*", self.httpd.hub.rule_requests.get(first[0])["expires"]), "post", "too broad", "Skills"))])
        with mock.patch.object(batches, "UNDO", 0.3):
            self.assertEqual(self.approve([entry], self.signed([entry], self.pin()))[0], 202)
            self.assertEqual(self.action(first[0], "sign", {}, self.guard(self.host))[0], 409)
            self.settle(lambda: self.waited(first[0])["status"] == "denied")
        answer = self.waited(first[0])
        self.assertEqual((answer["reason"], answer["rule"]), ("too broad", None))
        radio = [args for script, args in self.scripts.calls if script == skill_scripts.RADIO]
        self.assertEqual(radio[-1][:4], ["post", "--to", "Skills session", "--session"])
        self.assertTrue(radio[-1][-1].endswith("Denied by the operator: rule request ask Bash make test0* in /repo* (from Skills). Reason: too broad"), radio[-1])
        self.assertEqual(self.action(first[0], "sign", {}, self.guard(self.host))[0], 409)
        self.requested(self.ask_rule(pattern="make lint*"))
        with mock.patch.object(requesting, "TOTAL_CAP", len(first) + 1):
            self.assertTrue(self.tool("rule_request", self.ask_rule(agent="Third"))["isError"])
        self.assertIsNotNone(self.item(other))
        self.assertTrue(self.tool("rule_request_wait", {"id": "0123456789abcdef", "timeout_seconds": 0})["isError"])


if __name__ == "__main__":
    unittest.main()
