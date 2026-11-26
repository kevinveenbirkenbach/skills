from __future__ import annotations

import json
import time
import unittest

from hub_case import HubCase
from kvb_orchestrator import settings


class TestHubUndoWindow(HubCase):
    real_undo = True

    def window(self, seconds: int) -> None:
        payload = {**self.snapshot()["settings"], "undo": seconds, "proof": None}
        self.assertEqual(self.post_json("/api/settings", payload, self.guard(self.host))[0], 200)

    def granted(self, title: str, signer) -> tuple[str, float, dict]:
        review = self.request(title, "")
        entries = [self.entry("review", review, "", "")]
        sent = time.time()
        status, _, body = self.approve(entries, self.signed(entries, signer))
        self.assertEqual(status, 202, body)
        return review, sent, json.loads(body)

    def test_a_new_batch_takes_the_saved_window_and_0_applies_at_once(self):
        self.assertEqual(settings.SETTINGS["undo"], 3)
        signer = self.pin()
        self.window(10)
        review, sent, batch = self.granted("feat: ten", signer)
        self.assertAlmostEqual(batch["due"] - sent, 10, delta=0.5)
        self.assertEqual(self.status(review), "pending")
        self.assertEqual(self.call("POST", f"/api/inbox/undo/{batch['id']}", b"", self.guard(self.host))[0], 200)
        self.window(0)
        review, sent, batch = self.granted("feat: zero", signer)
        self.assertLessEqual(batch["due"] - sent, 0.5)
        self.settle(lambda: self.status(review) == "approved")


if __name__ == "__main__":
    unittest.main()
