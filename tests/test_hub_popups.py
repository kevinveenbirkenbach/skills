from __future__ import annotations

import json
import time
import unittest

from hub_case import HubCase
from hub_support import key, signing
from kvb_orchestrator import settings

ALL_ON = {source: {"on": True, "until": 0} for source in settings.POPUP_SOURCES}


class TestHubPopups(HubCase):
    def notified(self) -> dict | None:
        file = self.council / settings.NOTIFY
        return json.loads(file.read_text(encoding="utf-8")) if file.exists() else None

    def request(self, payload: dict) -> dict | None:
        status, _, body = self.post_json("/api/settings/sign", payload, self.guard(self.host))
        self.assertEqual(status, 200, body)
        return json.loads(body)["payload"]

    def test_every_save_writes_notify_json_and_a_popup_change_needs_the_passkey(self):
        good = self.guard(self.host)
        current = self.snapshot()["settings"]
        self.assertEqual(current["popups"], ALL_ON)
        quiet = {**current, "channels": {**current["channels"], "sounds": False}}
        self.assertIsNone(self.request(quiet))
        self.assertEqual(self.post_json("/api/settings", {**quiet, "proof": None}, good)[0], 200)
        self.assertEqual(self.notified(), ALL_ON)
        muted = {**quiet, "popups": {**ALL_ON, "resources": {"on": False, "until": 0}}}
        self.assertEqual(self.post_json("/api/settings", {**muted, "proof": None}, good)[:3:2], (400, b"not signed: no signature\n"))
        self.assertEqual(self.notified(), ALL_ON)
        signer = self.pin()
        request = self.request(muted)
        self.assertEqual(request["items"], [signing.item_hash(signing.popups_item(muted["popups"]))])
        stranger = self.post_json("/api/settings", {**muted, "proof": key(-7, "stranger").proof(request, self.origin)}, good)
        self.assertEqual(stranger[:3:2], (400, b"not signed: the signing key is not pinned\n"))
        snoozed = {**quiet, "popups": {**ALL_ON, "mayday": {"on": True, "until": int(time.time()) + 3600}}}
        self.assertEqual(self.post_json("/api/settings", {**snoozed, "proof": signer.proof(request, self.origin)}, good)[:3:2], (400, b"not signed: the signature does not list this item\n"))
        self.assertEqual(self.notified(), ALL_ON)
        status, _, body = self.post_json("/api/settings", {**muted, "proof": signer.proof(request, self.origin)}, good)
        self.assertEqual((status, json.loads(body)["settings"]["popups"]), (200, muted["popups"]), body)
        self.assertEqual(self.notified(), muted["popups"])
        self.assertEqual(settings.Settings(self.state / "settings.json").get()["popups"], muted["popups"])

    def test_a_popup_entry_must_name_every_source_with_a_bool_and_a_whole_second(self):
        current = self.snapshot()["settings"]
        wrongs = [
            {**ALL_ON, "dream": {"on": "yes", "until": 0}},
            {**ALL_ON, "dream": {"on": True, "until": -1}},
            {**ALL_ON, "dream": {"on": True, "until": 2.5}},
            {**ALL_ON, "dream": {"on": True, "until": True}},
            {**ALL_ON, "dream": {"on": True, "until": settings.POPUP_UNTIL + 1}},
            {**ALL_ON, "dream": {"on": True}},
            {**ALL_ON, "dream": {"on": True, "until": 0, "extra": 1}},
            {source: entry for source, entry in ALL_ON.items() if source != "dream"},
            {**ALL_ON, "email": {"on": True, "until": 0}},
        ]
        for wrong in wrongs:
            with self.subTest(wrong=wrong):
                self.assertEqual(self.post_json("/api/settings/sign", {**current, "popups": wrong}, self.guard(self.host))[0], 400)


if __name__ == "__main__":
    unittest.main()
