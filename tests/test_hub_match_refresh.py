from __future__ import annotations

import json
import unittest

from hub_case import HubCase
from kvb_orchestrator import settings


class TestHubMatchRefresh(HubCase):
    def save(self, payload: dict) -> tuple[int, bytes]:
        status, _, body = self.post_json("/api/settings", {**payload, "proof": None}, self.guard(self.host))
        return status, body

    def refresh(self) -> int:
        return self.snapshot()["settings"]["match"]["refresh"]

    def test_the_match_refresh_defaults_to_2_s_and_is_stored_in_and_read_from_the_hub_settings(self):
        self.assertEqual(settings.SETTINGS["match"], {"refresh": 2})
        self.assertEqual(self.refresh(), 2)
        status, body = self.save({**self.snapshot()["settings"], "match": {"refresh": 10}})
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)["settings"]["match"], {"refresh": 10})
        self.assertEqual(self.refresh(), 10)
        stored = json.loads((self.state / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(stored["match"], {"refresh": 10})
        self.assertEqual(settings.Settings(self.state / "settings.json").get()["match"], {"refresh": 10})

    def test_a_page_without_the_match_section_keeps_the_saved_interval(self):
        self.assertEqual(self.save({**self.snapshot()["settings"], "match": {"refresh": 7}})[0], 200)
        older = {key: value for key, value in self.snapshot()["settings"].items() if key != "match"}
        self.assertEqual(self.save(older)[0], 200)
        self.assertEqual(self.refresh(), 7)

    def test_the_interval_takes_whole_seconds_from_1_to_60_only(self):
        for good in (1, 60):
            with self.subTest(good=good):
                status, body = self.save({**self.snapshot()["settings"], "match": {"refresh": good}})
                self.assertEqual(status, 200, body)
                self.assertEqual(self.refresh(), good)
        for bad in (0, 61, -1, 2.5, True, "10", None):
            with self.subTest(bad=bad):
                status, body = self.save({**self.snapshot()["settings"], "match": {"refresh": bad}})
                self.assertEqual((status, body), (400, b"match.refresh must be whole seconds from 1 to 60\n"))
                self.assertEqual(self.refresh(), 60)
        for broken in ({}, {"refresh": 5, "extra": 1}, 5):
            with self.subTest(broken=broken):
                self.assertEqual(self.save({**self.snapshot()["settings"], "match": broken})[0], 400)
                self.assertEqual(self.refresh(), 60)


if __name__ == "__main__":
    unittest.main()
