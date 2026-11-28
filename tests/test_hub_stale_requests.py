"""Exercise requirement 093: every request has one kind, and a signed dismissal hides many in the hub with an undo."""

from __future__ import annotations

import json
import time
import unittest
from unittest import mock

from hub_support import ASK, signing
from kvb_orchestrator import batches, skill_scripts
from kvb_orchestrator.inbox import item_base
from kvb_orchestrator.triage import REQUEST_KINDS, hides, request_kind, request_mark
from test_hub_match import MatchCase

CALLED = {**ASK, "call_key": signing.call_key("Bash", {"command": ASK["command"]})}
FAILED_JOB = {"id": "0123456789abcdef", "status": "failed", "code": 2, "output": "", "created_ts": 1.0, "started": 1.0, "finished": 2.0}


def job(status: str) -> dict:
    return {**FAILED_JOB, "status": status}


class TestRequestKind(unittest.TestCase):
    def test_every_request_has_exactly_one_kind(self):
        base = item_base()
        cases = {
            "open ask": ({**base, "kind": "ask"}, "open"),
            "open review": ({**base, "kind": "review"}, "open"),
            "lapsed ask": ({**base, "kind": "ask", "expires": 10.0}, "expired"),
            "lapsed decision": ({**base, "kind": "decision", "expires": 10.0}, "expired"),
            "stale review": ({**base, "kind": "review", "stale": True}, "stale"),
            "stale row": ({**base, "kind": "operator", "stale": True}, "stale"),
            "failed row": ({**base, "kind": "operator", "job": job("failed")}, "failed"),
            "refused row": ({**base, "kind": "operator", "job": job("refused")}, "failed"),
            "failed and stale row": ({**base, "kind": "operator", "stale": True, "job": job("failed")}, "failed"),
            "row that ran": ({**base, "kind": "operator", "job": job("done")}, "open"),
            "row running": ({**base, "kind": "operator", "job": job("running")}, "open"),
        }
        for name, (item, kind) in cases.items():
            with self.subTest(name=name):
                self.assertEqual(request_kind(item), kind)
                self.assertIn(request_kind(item), REQUEST_KINDS)

    def test_a_dismissal_hides_only_the_same_command_and_job_and_a_pending_one_hides_any(self):
        mark = request_mark("make deploy", FAILED_JOB)
        hidden = ({"operator:operator/greet": mark}, {"ask:a1"})
        self.assertTrue(hides(hidden, "operator:operator/greet", mark))
        self.assertFalse(hides(hidden, "operator:operator/greet", request_mark("make deploy", {**FAILED_JOB, "id": "1123456789abcdef"})))
        self.assertFalse(hides(hidden, "operator:operator/greet", request_mark("make other", FAILED_JOB)))
        self.assertTrue(hides(hidden, "ask:a1", request_mark("anything", None)))
        self.assertFalse(hides(hidden, "ask:a2", request_mark("", None)))


class TestDismissRequests(MatchCase):
    def setUp(self):
        super().setUp()
        self.claim("s1", "Skills session")
        self.expired = self.create_ask(CALLED)
        self.httpd.hub.asks.change(self.expired, {"expires": time.time() - 600})
        self.open = self.create_ask({**ASK, "command": "make open", "timeout": 3600})
        self.review = self.request("feat: stale", "notes")
        status, _, body = self.post_json("/api/match/stale", {"id": self.review, "tree": "f" * 40}, self.local())
        self.assertEqual(status, 200, body)
        greet = {"title": "echo greet", "workdir": str(self.outside), "description": "greets", "check": "manual", "status": "queued", "roles": {"Operator": "R", "Skills session": "A"}}
        self.write_council({"rasci.json": {"operator/greet": greet}})
        fields = {"task": "operator/greet", "command": "echo greet", "directory": str(self.outside), "sha256": "", "status": "failed", "proof": None}
        now = time.time()
        self.httpd.hub.jobs.add({**fields, "code": 2, "output": "boom\n", "created_ts": now - 20, "started": now - 19, "finished": now - 10, "dismissed": False})

    def kinds(self) -> dict[str, str]:
        snapshot = self.snapshot()
        return {f"{item['kind']}:{item['id']}": item["request"] for item in snapshot["inbox"] + snapshot["lapsed"]}

    def entry(self, target: str, ident: str, scope: str) -> dict:
        return {"kind": "dismiss", "target": target, "id": ident, "scope": scope}

    def dismiss(self, entries: list[dict], proof: object) -> tuple[int, dict, bytes]:
        return self.post_json("/api/requests/dismiss", {"items": entries, "proof": proof}, self.guard(self.host))

    def backlog(self) -> list[dict]:
        return [self.entry("ask", self.expired, "expired"), self.entry("review", self.review, "stale"), self.entry("operator", "operator/greet", "failed")]

    def test_the_snapshot_names_each_requests_kind(self):
        kinds = self.kinds()
        self.assertEqual(kinds[f"ask:{self.expired}"], "expired")
        self.assertEqual(kinds[f"ask:{self.open}"], "open")
        self.assertEqual(kinds[f"review:{self.review}"], "stale")
        self.assertEqual(kinds["operator:operator/greet"], "failed")
        self.assertNotIn(f"ask:{self.expired}", [item["id"] for item in self.snapshot()["inbox"]])

    def test_the_endpoint_refuses_an_unsigned_or_foreign_call_and_malformed_entries(self):
        entries = self.backlog()
        status, _, body = self.dismiss(entries, None)
        self.assertEqual(status, 400, body)
        self.assertIn("not signed", body.decode())
        foreign = {**self.guard(self.host), "Origin": "http://evil.example"}
        self.assertEqual(self.post_json("/api/requests/dismiss", {"items": entries, "proof": None}, foreign)[0], 403)
        self.assertEqual(self.post_json("/api/requests/dismiss", {"items": entries, "proof": None}, {"Host": self.host})[0], 403)
        signer = self.pin()
        proof = self.signed(entries, signer)
        forged = {**proof, "payload": {**proof["payload"], "nonce": "0" * 32}}
        self.assertEqual(self.dismiss(entries, forged)[0], 400)
        for bad in ([], "x", [{**entries[0], "extra": 1}], [{**entries[0], "scope": "bogus"}], [{**entries[0], "target": 7}], [entries[0], entries[0]]):
            with self.subTest(bad=bad):
                self.assertEqual(self.post_json("/api/sign", {"items": bad}, self.guard(self.host))[0], 400)
        self.assertEqual(self.post_json("/api/sign", {"items": [self.entry("ask", "0123456789abcdef", "expired")]}, self.guard(self.host))[0], 404)
        self.assertEqual(self.kinds()[f"ask:{self.expired}"], "expired")
        self.assertEqual(self.httpd.hub.dismissals.listed(), [])

    def test_a_signed_dismissal_hides_the_list_at_once_and_the_undo_brings_it_back(self):
        entries = self.backlog()
        signer = self.pin()
        with mock.patch.object(batches, "UNDO", 60):
            status, _, body = self.dismiss(entries, self.signed(entries, signer))
            self.assertEqual(status, 202, body)
            batch = json.loads(body)
            self.assertEqual(sorted((item["kind"], item["id"], item["verb"]) for item in batch["items"]), sorted([("ask", self.expired, "dismiss"), ("review", self.review, "dismiss"), ("operator", "operator/greet", "dismiss")]))
            kinds = self.kinds()
            for key in (f"ask:{self.expired}", f"review:{self.review}", "operator:operator/greet"):
                self.assertNotIn(key, kinds)
            self.assertIn(f"ask:{self.open}", kinds)
            self.assertNotIn(f"review:{self.review}", [card["id"] for card in self.cards()])
            status, _, body = self.post_json(f"/api/inbox/undo/{batch['id']}", {}, self.guard(self.host))
            self.assertEqual(status, 200, body)
        kinds = self.kinds()
        self.assertEqual((kinds[f"ask:{self.expired}"], kinds[f"review:{self.review}"], kinds["operator:operator/greet"]), ("expired", "stale", "failed"))
        self.assertEqual(self.httpd.hub.dismissals.listed(), [])

    def test_an_applied_dismissal_stays_for_every_browser_and_tells_no_agent(self):
        entries = self.backlog()
        with mock.patch.object(batches, "UNDO", 0.05):
            status, _, body = self.dismiss(entries, self.signed(entries, self.pin()))
            self.assertEqual(status, 202, body)
            self.settle(lambda: self.httpd.hub.dismissals.listed() != [])
        kinds = self.kinds()
        self.assertEqual([key for key in (f"ask:{self.expired}", f"review:{self.review}", "operator:operator/greet") if key in kinds], [])
        shown = [card["id"] for card in self.cards()]
        self.assertNotIn(f"ask:{self.expired}", shown)
        self.assertNotIn(f"review:{self.review}", shown)
        self.assertEqual(self.httpd.hub.asks.get(self.expired)["status"], "pending")
        self.assertEqual(self.status(self.review), "pending")
        self.assertEqual([args for script, args in self.scripts.calls if script == skill_scripts.RADIO], [])

    def test_an_open_request_is_deleted_only_from_open_or_all_and_its_ask_is_denied_without_a_message(self):
        for scope in ("expired", "stale", "failed"):
            with self.subTest(scope=scope):
                status, _, body = self.post_json("/api/sign", {"items": [self.entry("ask", self.open, scope)]}, self.guard(self.host))
                self.assertEqual(status, 409, body)
                self.assertEqual(json.loads(body)["status"], "open")
        self.assertEqual(self.post_json("/api/sign", {"items": [self.entry("ask", self.expired, "open")]}, self.guard(self.host))[0], 409)
        entries = [self.entry("ask", self.open, "all")]
        with mock.patch.object(batches, "UNDO", 0.05):
            status, _, body = self.dismiss(entries, self.signed(entries, self.pin()))
            self.assertEqual(status, 202, body)
            self.settle(lambda: self.httpd.hub.asks.get(self.open)["status"] == "denied")
        record = self.httpd.hub.asks.get(self.open)
        self.assertEqual((record["proof"], record.get("reason")), (None, None))
        self.assertEqual(self.ask_status(self.open, "0"), "denied")
        self.assertNotIn(f"ask:{self.open}", self.kinds())
        self.assertEqual([args for script, args in self.scripts.calls if script == skill_scripts.RADIO], [])

    def test_a_row_that_ran_again_shows_again_after_its_dismissal(self):
        entries = [self.entry("operator", "operator/greet", "failed")]
        with mock.patch.object(batches, "UNDO", 0.05):
            self.assertEqual(self.dismiss(entries, self.signed(entries, self.pin()))[0], 202)
            self.settle(lambda: self.httpd.hub.dismissals.listed() != [])
        self.assertNotIn("operator:operator/greet", self.kinds())
        fields = {"task": "operator/greet", "command": "echo greet", "directory": str(self.outside), "sha256": "", "status": "refused", "proof": None}
        now = time.time()
        self.httpd.hub.jobs.add({**fields, "code": None, "output": "", "created_ts": now, "started": now, "finished": now, "dismissed": False})
        self.assertEqual(self.kinds()["operator:operator/greet"], "failed")


if __name__ == "__main__":
    unittest.main()
