from __future__ import annotations

import json
import time
import unittest
from pathlib import Path
from unittest import mock

from hub_case import HubCase
from hub_support import ASK, PAGE, key
from kvb_orchestrator import approving

MASKED = "masked"
WITHHELD = "content withheld"
APP_CLEAR = '@@ -1 +1 @@\n-old\n+api_key = "plain-example-words"'
CONF_CLEAR = '@@ -0,0 +1 @@\n+token = "plain-other-words"'
DIFF = [
    {"path": "app.py", "status": "M", "mode": "100644", "additions": 1, "deletions": 1, "patch": "@@ -1 +1 @@\n-old\n+••••", "note": MASKED},
    {"path": "conf.py", "status": "A", "mode": "100644", "additions": 1, "deletions": 0, "patch": "", "note": WITHHELD},
    {"path": "open.txt", "status": "A", "mode": "100644", "additions": 1, "deletions": 0, "patch": "@@ -0,0 +1 @@\n+seen", "note": ""},
]
SEALED = {"app.py": APP_CLEAR, "conf.py": CONF_CLEAR}


class TestSealedReveal(HubCase):
    def review(self) -> str:
        result = self.tool("review_request", {**self.arguments("feat: sealed", "", self.page("sealed.html", PAGE)), "agent": "Skills", "diff": DIFF, "sealed": SEALED})
        self.assertFalse(result["isError"], result)
        return result["structuredContent"]["id"]

    def ask(self, timeout: float) -> str:
        return self.create_ask({**ASK, "command": "git commit -m x", "timeout": timeout, "diff": DIFF, "sealed": SEALED})

    def sealed(self, kind: str, item_id: str) -> Path:
        return self.state / "pages" / f"{item_id}.{kind}-sealed.json"

    def assert_no_clear_text(self, body: bytes) -> None:
        for word in (b"plain-example", b"plain-other"):
            self.assertNotIn(word, body)

    def test_the_sealed_patches_sit_apart_with_mode_0600_and_never_reach_the_diff_the_state_or_the_stream(self):
        items = {"review": self.review(), "ask": self.ask(60)}
        for kind, item_id in items.items():
            with self.subTest(kind=kind):
                self.assertEqual(self.sealed(kind, item_id).stat().st_mode & 0o777, 0o600)
                status, _, body = self.get(f"/api/diffs/{kind}/{item_id}")
                self.assertEqual((status, json.loads(body)["diff"]), (200, DIFF))
                self.assert_no_clear_text(body)
                for route in ("page", "files"):
                    self.assert_no_clear_text(self.get(f"/reviews/{item_id}/{route}")[2])
        self.assert_no_clear_text(json.dumps(self.snapshot()).encode("utf-8"))
        self.assert_no_clear_text(json.dumps(self.events("kinds=approval,review,ask")).encode("utf-8"))
        self.assert_no_clear_text(self.index().encode("utf-8"))

    def test_a_sealed_path_outside_the_hidden_files_or_without_a_diff_is_refused(self):
        arguments = {**self.arguments("feat: sealed", "", self.page("bad.html", PAGE)), "agent": "Skills"}
        for extra in ({"diff": DIFF, "sealed": {"open.txt": "x"}}, {"diff": DIFF, "sealed": {"app.py": 1}}, {"sealed": SEALED}):
            with self.subTest(extra=sorted(extra)):
                self.assertTrue(self.tool("review_request", {**arguments, **extra})["isError"])
        self.assertEqual(self.post_json("/api/asks", {**ASK, "diff": DIFF, "sealed": {"open.txt": "x"}}, self.local())[0], 400)
        self.assertEqual(sorted(path.name for path in (self.state / "pages").glob("*-sealed.json")), [])

    def test_a_signed_reveal_answers_exactly_the_requested_paths_per_file_and_per_item_and_logs_no_content(self):
        signer = self.pin()
        for kind, item_id in (("review", self.review()), ("ask", self.ask(60))):
            with self.subTest(kind=kind):
                status, _, body = self.reveal(kind, item_id, ["app.py"], self.reveal_proof(kind, item_id, ["app.py"], signer))
                self.assertEqual((status, json.loads(body)), (200, {"kind": kind, "id": item_id, "patches": {"app.py": APP_CLEAR}}), body)
                status, _, body = self.reveal(kind, item_id, ["conf.py", "app.py"], self.reveal_proof(kind, item_id, ["app.py", "conf.py"], signer))
                self.assertEqual((status, json.loads(body)["patches"]), (200, SEALED), body)
        rows = [row for row in self.events("kinds=approval")["events"] if row["title"].startswith("Reveal ")]
        self.assertEqual([row["text"] for row in rows], ["app.py", "app.py, conf.py"] * 2)
        self.assertEqual([row["ref"]["verb"] for row in rows], ["reveal"] * 4)
        self.assert_no_clear_text(json.dumps(rows).encode("utf-8"))

    def test_a_reveal_without_a_pinned_unexpired_unused_signature_over_exactly_its_paths_answers_4xx_without_content(self):
        signer = self.pin()
        review_id = self.review()
        one = self.reveal_proof("review", review_id, ["app.py"], signer)
        stranger = self.reveal_proof("review", review_id, ["app.py"], key(-7, "stranger"))
        cases = {
            "no proof": (["app.py"], None, 400),
            "other paths": (["app.py", "conf.py"], one, 400),
            "unpinned key": (["app.py"], stranger, 400),
            "unsealed path": (["open.txt"], one, 400),
            "repeated path": (["app.py", "app.py"], one, 400),
        }
        for case, (paths, proof, expected) in cases.items():
            with self.subTest(case=case):
                status, _, body = self.reveal("review", review_id, paths, proof)
                self.assertEqual(status, expected, body)
                self.assert_no_clear_text(body)
        self.assertEqual(self.reveal("review", review_id, ["app.py"], one)[0], 200)
        status, _, body = self.reveal("review", review_id, ["app.py"], one)
        self.assertEqual(status, 400, body)
        self.assert_no_clear_text(body)
        self.assertEqual(self.post_json(f"/api/diffs/review/{review_id}/reveal/sign", {"paths": ["open.txt"]}, self.guard(self.host))[0], 400)
        self.assertEqual(self.reveal("review", "0123456789abcdef", ["app.py"], one)[0], 404)
        expired = self.reveal_proof("review", review_id, ["app.py"], signer)
        later = time.time() + approving.signing.LIFETIME + 60
        with mock.patch.object(approving, "time", mock.Mock(time=lambda: later)):
            self.assertEqual(self.reveal("review", review_id, ["app.py"], expired)[0], 400)
        self.assertEqual(self.reveal("review", review_id, ["app.py"], expired)[0], 200)
        plain = self.request("feat: nothing sealed", "")
        self.assertEqual(self.post_json(f"/api/diffs/review/{plain}/reveal/sign", {"paths": ["app.py"]}, self.guard(self.host))[0], 404)

    def test_the_sealed_file_is_deleted_after_the_grant_the_denial_or_the_expiry_and_a_reveal_then_conflicts(self):
        signer = self.pin()
        granted, rejected = self.review(), self.review()
        proven = self.proven([self.entry("review", granted, "", "")], signer)
        self.assertEqual(self.call("POST", f"/reviews/{granted}/approve", proven, self.guard(self.host))[0], 200)
        self.assertEqual(self.call("POST", f"/reviews/{rejected}/reject", b"", self.guard(self.host))[0], 200)
        denied = self.ask(60)
        self.assertEqual(self.call("POST", f"/api/asks/{denied}/deny", b"", self.guard(self.host))[0], 200)
        waited, swept = self.ask(0), self.ask(0)
        self.assertEqual(self.ask_status(waited, "0"), "expired")
        self.assertFalse(self.sealed("ask", waited).exists())
        self.assertTrue(self.sealed("ask", swept).exists())
        self.snapshot()
        for kind, item_id in (("review", granted), ("review", rejected), ("ask", denied), ("ask", waited), ("ask", swept)):
            with self.subTest(kind=kind, item=item_id):
                self.assertFalse(self.sealed(kind, item_id).exists())
                status, _, body = self.post_json(f"/api/diffs/{kind}/{item_id}/reveal/sign", {"paths": ["app.py"]}, self.guard(self.host))
                self.assertEqual(status, 409, body)
                self.assert_no_clear_text(body)

    def test_a_reveal_of_a_decided_item_drops_a_sealed_file_left_behind(self):
        review_id = self.review()
        left = self.sealed("review", review_id).read_bytes()
        self.assertEqual(self.call("POST", f"/reviews/{review_id}/reject", b"", self.guard(self.host))[0], 200)
        self.sealed("review", review_id).write_bytes(left)
        self.assertEqual(self.post_json(f"/api/diffs/review/{review_id}/reveal/sign", {"paths": ["app.py"]}, self.guard(self.host))[0], 409)
        self.assertFalse(self.sealed("review", review_id).exists())


if __name__ == "__main__":
    unittest.main()
