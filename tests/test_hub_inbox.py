from __future__ import annotations

import dataclasses
import json
import time
import unittest
from unittest import mock

from hub_case import HubCase
from hub_support import ASK, PAGE, TREE, key, signing
from kvb_orchestrator import batches


class TestHubInbox(HubCase):
    def test_inbox_bulk_approval_waits_for_the_undo_window(self):
        green = self.request("feat: green", "")
        red = self.tool("review_request", {**self.arguments("feat: red", "", self.page("red.html", PAGE)), "gate": "fail"})["structuredContent"]["id"]
        ask_id = self.create_ask(ASK)
        risky = self.create_ask({**ASK, "command": "rm -rf build"})
        decision_id = self.decision("Merge now")
        inbox = {item["id"]: item for item in self.snapshot()["inbox"]}
        self.assertEqual([inbox[key]["green"] for key in (green, red, ask_id, risky, decision_id)], [True, False, True, False, True])
        self.assertEqual(inbox[risky]["warnings"], ["deletes recursively"])
        batch = [self.entry("review", green, "", ""), self.entry("ask", ask_id, "", ""), self.entry("decision", decision_id, "Merge now", "")]
        signer = key(-7, "main")
        self.assertEqual(self.approve([self.entry("review", green, "", ""), self.entry("review", red, "", "")], None)[0], 400)
        self.assertEqual(self.approve([self.entry("decision", decision_id, "Later", "")], None)[0], 400)
        self.assertEqual(self.approve([self.entry("review", green, "", ""), self.entry("review", green, "", "")], None)[0], 400)
        self.assertEqual(self.approve([self.entry("review", "0123456789abcdef", "", "")], None)[0], 404)
        self.assertEqual(self.post_json("/api/inbox/approve", {"items": batch, "proof": None}, self.client())[0], 403)
        prepared = self.prepare(batch)
        listed = [signing.item_hash(signing.review_item(green, "/repo/.git", "/repo/.worktrees/feature/x", "feature/x", TREE)), signing.item_hash(signing.ask_item(ask_id, "Bash", "make deploy", "/repo", "s1"))]
        self.assertEqual((prepared["payload"]["items"], prepared["challenge"]), (sorted(listed), signing.challenge(prepared["payload"])))
        unsigned = [self.entry("decision", decision_id, "Merge now", ""), {**self.entry("review", red, "", ""), "verb": "reject"}]
        self.assertIsNone(self.prepare(unsigned)["payload"])
        partial = signer.proof(self.prepare(batch[:1])["payload"], self.origin)
        for proof in (None, partial, {"payload": prepared["payload"]}, {"payload": {**prepared["payload"], "expires": int(time.time()) - 1}, "assertion": {}}):
            with self.subTest(proof=str(proof)[:80]):
                self.assertEqual(self.approve(batch, proof)[0], 400)
        self.assertEqual(self.approve(unsigned, partial)[0], 400)
        proof = signer.proof(prepared["payload"], self.origin)
        with mock.patch.object(batches, "UNDO", 0.5):
            status, _, body = self.approve(batch, proof)
            self.assertEqual(status, 202, body)
            first = json.loads(body)
            self.assertNotIn("proof", first)
            self.assertEqual(self.approve([batch[0]], None)[0], 409)
            self.assertTrue(all(item["held"] for item in self.snapshot()["inbox"] if item["id"] in (green, ask_id, decision_id)))
            self.assertEqual(self.call("POST", f"/api/inbox/undo/{first['id']}", b"", self.guard(self.host))[0], 200)
            time.sleep(0.8)
            self.assertEqual((self.status(green), self.ask_status(ask_id, "0"), self.choice(decision_id)), ("pending", "pending", None))
            self.assertIsNone(json.loads(self.get(f"/api/reviews/{green}")[2])["proof"])
            second = json.loads(self.approve(batch, proof)[2])
            self.assertEqual(self.status(green), "pending")
            self.assertIsNone(json.loads(self.get(f"/api/asks/{ask_id}?wait=0")[2])["proof"])
            self.settle(lambda: self.status(green) == "approved")
        self.settle(lambda: self.choice(decision_id) == "Merge now")
        self.assertEqual(self.ask_status(ask_id, "0"), "allowed")
        self.assertEqual(json.loads(self.get(f"/api/asks/{ask_id}?wait=0")[2])["proof"], proof)
        self.assertEqual(json.loads(self.get(f"/api/reviews/{green}")[2])["proof"], proof)
        self.assertNotIn(b'"assertion"', self.get("/api/state")[2])
        self.assertEqual(self.call("POST", f"/api/inbox/undo/{second['id']}", b"", self.guard(self.host))[0], 409)
        self.assertEqual(self.call("POST", "/api/inbox/undo/0123456789abcdef", b"", self.guard(self.host))[0], 404)
        with mock.patch.object(batches, "UNDO", 0.05):
            self.assertEqual(self.approve([self.entry("review", red, "", "")], self.signed([self.entry("review", red, "", "")], signer))[0], 202)
            self.settle(lambda: self.status(red) == "approved")
        until = time.time() + 3600
        self.assertEqual(self.post_json("/api/inbox/mark", {"kind": "ask", "id": risky, "until": until, "pinned": True}, self.guard(self.host))[0], 200)
        top = self.snapshot()["inbox"][0]
        self.assertEqual((top["id"], top["pinned"], round(top["until"])), (risky, True, round(until)))
        for payload in (
            {"kind": "ask", "id": risky, "until": time.time() - 5, "pinned": False},
            {"kind": "ask", "id": risky, "until": time.time() + 9 * 86400, "pinned": False},
            {"kind": "ask", "id": risky, "until": 0, "pinned": "yes"},
            {"kind": "radio", "id": risky, "until": 0, "pinned": False},
        ):
            with self.subTest(payload=payload):
                self.assertEqual(self.post_json("/api/inbox/mark", payload, self.guard(self.host))[0], 400)
        titles = [row["title"] for row in self.events("kinds=approval")["events"]]
        self.assertIn("Grant review: feat: green", titles)
        self.assertTrue(any(title.startswith("Undone: ") for title in titles))

    def test_the_sign_endpoint_and_the_page_offer_the_pinned_keys_only(self):
        ask_id = self.create_ask(ASK)
        prepared = self.prepare([self.entry("ask", ask_id, "", "")])
        self.assertEqual((prepared["credentials"], self.snapshot()["approvers"]), ([], []))
        self.assertEqual(prepared["payload"]["items"], [signing.item_hash(signing.ask_item(ask_id, "Bash", "make deploy", "/repo", "s1"))])
        self.assertTrue(time.time() < prepared["payload"]["expires"] <= time.time() + signing.LIFETIME)
        self.assertRegex(prepared["payload"]["nonce"], r"^[0-9a-f]{32}$")
        self.assertNotEqual(prepared["payload"]["nonce"], self.prepare([self.entry("ask", ask_id, "", "")])["payload"]["nonce"])
        self.assertEqual(self.post_json("/api/sign", {"items": [self.entry("ask", ask_id, "", "")]}, self.client())[0], 403)
        signer = self.pin()
        key(-8, "main").pin(self.approvers, self.origin)
        self.assertEqual(self.prepare([self.entry("ask", ask_id, "", "")])["credentials"], [signer.id, key(-8, "main").id])
        self.assertEqual(self.snapshot()["approvers"], [{"id": signer.id, "alg": "ES256"}, {"id": key(-8, "main").id, "alg": "EdDSA"}])
        self.approvers.chmod(0o666)
        self.assertEqual(self.snapshot()["approvers"], [])
        html = self.index()
        for text in ("Register passkey", "navigator.credentials.get", "navigator.credentials.create", "approval.py pin --port", "~/.config/kvb-orchestrator/approvers.json", "not signed"):
            with self.subTest(text=text):
                self.assertIn(text, html)

    def test_an_nl_command_records_new_operator_rows_like_the_state_does(self):
        self.write_council({"rasci.json": {"operator/greet": {"title": "echo hi", "workdir": "/repo", "check": "manual", "status": "queued", "roles": {}}}})
        model = mock.Mock(**{"enabled.return_value": True, "complete.return_value": '{"actions": []}'})
        self.httpd.hub = dataclasses.replace(self.httpd.hub, model=model)
        before = time.time()
        self.assertEqual(self.post_json("/api/nl", {"text": "status"}, self.guard(self.host))[0], 200)
        after = time.time()
        row = next(item for item in self.snapshot()["inbox"] if item["id"] == "operator/greet")
        self.assertTrue(before <= row["ts"] <= after, (before, row["ts"], after))

    def test_the_title_counts_the_items_that_are_not_snoozed(self):
        asks = [self.create_ask(ASK), self.create_ask({**ASK, "command": "make other"})]
        self.assertIn("<title>(2) Agent Orchestrator</title>", self.index())
        for ask_id, title in zip(asks, ("(1) Agent Orchestrator", "Agent Orchestrator"), strict=True):
            snooze = {"kind": "ask", "id": ask_id, "until": time.time() + 3600, "pinned": False}
            self.assertEqual(self.post_json("/api/inbox/mark", snooze, self.guard(self.host))[0], 200)
            with self.subTest(title=title):
                self.assertIn(f"<title>{title}</title>", self.index())


if __name__ == "__main__":
    unittest.main()
