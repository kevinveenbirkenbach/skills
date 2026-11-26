from __future__ import annotations

import json
import unittest

from hub_case import HubCase
from kvb_orchestrator import fields, settings
from kvb_orchestrator.errors import ToolError

QUIET = {"sound": False, "aloud": False, "bubbles": True}
LOUD = {"sound": True, "aloud": True, "bubbles": True}


class TestAgentsSetting(unittest.TestCase):
    def test_each_agent_keeps_three_switches_and_an_all_on_entry_is_dropped(self):
        self.assertEqual(settings.agents_setting({"s1": QUIET, "s2": LOUD, "name:Docs": {**LOUD, "bubbles": False}}), {"s1": QUIET, "name:Docs": {**LOUD, "bubbles": False}})
        self.assertEqual(settings.agents_setting({}), {})

    def test_unknown_or_missing_switches_wrong_values_and_oversized_maps_are_refused(self):
        wrongs = [
            [],
            "s1",
            {"s1": {**QUIET, "volume": 1}},
            {"s1": {"sound": False, "aloud": False}},
            {"s1": {**QUIET, "sound": "off"}},
            {"s1": {**QUIET, "sound": 0}},
            {"s1": True},
            {"": QUIET},
            {"x" * (fields.NAME_LIMIT + 1): QUIET},
            {f"s{index}": QUIET for index in range(settings.AGENTS_LIMIT + 1)},
        ]
        for wrong in wrongs:
            with self.subTest(wrong=str(wrong)[:80]), self.assertRaises(ToolError):
                settings.agents_setting(wrong)


class TestHubAgentSettings(HubCase):
    def test_the_agent_switches_save_without_a_passkey_and_a_page_without_them_keeps_them(self):
        good = self.guard(self.host)
        current = self.snapshot()["settings"]
        self.assertEqual(current["agents"], {})
        quiet = {**current, "agents": {"s1": QUIET, "s2": LOUD}}
        status, _, body = self.post_json("/api/settings/sign", quiet, good)
        self.assertEqual((status, json.loads(body)["payload"]), (200, None), body)
        status, _, body = self.post_json("/api/settings", {**quiet, "proof": None}, good)
        self.assertEqual((status, json.loads(body)["settings"]["agents"]), (200, {"s1": QUIET}), body)
        older = {key: value for key, value in current.items() if key != "agents"}
        status, _, body = self.post_json("/api/settings", {**older, "bubbles": not current["bubbles"], "proof": None}, good)
        self.assertEqual((status, json.loads(body)["settings"]["agents"]), (200, {"s1": QUIET}), body)
        self.assertEqual(settings.Settings(self.state / "settings.json").get()["agents"], {"s1": QUIET})

    def test_a_save_with_an_unknown_switch_is_refused_and_changes_nothing(self):
        good = self.guard(self.host)
        current = self.snapshot()["settings"]
        for wrong in ({"s1": {**QUIET, "volume": 1}}, {"s1": {**QUIET, "aloud": "no"}}, ["s1"]):
            with self.subTest(wrong=wrong):
                self.assertEqual(self.post_json("/api/settings", {**current, "agents": wrong, "proof": None}, good)[0], 400)
        self.assertEqual(self.snapshot()["settings"]["agents"], {})


if __name__ == "__main__":
    unittest.main()
