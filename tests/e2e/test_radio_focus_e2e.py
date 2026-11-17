from __future__ import annotations

import json
import os
import shutil
import sys
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

import radio_layout_kit as kit
from kvb_orchestrator import skill_scripts
from radio_layout_focus_probes import (
    BANNER,
    COMPOSE_HOME,
    FOCUS,
    KEYS,
    POP,
    REPLY_HOME,
    ROWS,
)
from radio_layout_kit import (
    ALARMS,
    DUPS,
    FOCUS_SIZES,
    HOME_RADIO,
    NEW_ALARM,
    OUT,
    POPOVER_SIZES,
    probe,
)


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestRadioFocus(kit.RadioLayoutCase):
    def popover_steps(self, browser: str) -> list[dict]:
        self.stations()
        tiles = json.dumps([f'#main .home-tile[data-pin="panel:{part}"]' for part in ("radio-device", "radio")])
        places = (("spot", "#stream", "[]", '["#radio-spot"]', "true"), ("home", "#home", json.dumps(HOME_RADIO), tiles, "false"), ("home-spot", "#home", json.dumps(HOME_RADIO), tiles, "true"))
        return [{"width": width, "height": height, "url": f"http://localhost:{self.port}/?{width}-pop#stream" if name == "spot" else None, "wait": 1500 if name == "spot" else 0,
                 "probe": probe(POP.replace("@VIEW@", view).replace("@PINS@", pins).replace("@ROOTS@", roots).replace("@SPOT@", spot)), "shot": str(OUT / f"{browser}-{width}-pop-{name}.png")}
                for width, height in POPOVER_SIZES for name, view, pins, roots, spot in places]

    def check_side(self, opened: dict) -> None:
        self.assertLessEqual(opened["height"], opened["cap"], opened)
        above, below, need = opened["above"], opened["below"], opened["need"]
        if above >= need:
            self.assertEqual(opened["side"], "up", opened)
        elif below >= need:
            self.assertEqual(opened["side"], "down", opened)
        else:
            self.assertEqual(opened["side"], "up" if above >= below else "down", opened)

    def check_popover(self, data: dict, browser: str) -> None:
        results = iter(data["results"])
        for width, _ in POPOVER_SIZES:
            for place in ("spot", "home", "home-spot"):
                found = next(results)
                self.assertEqual(len(found), 1 if place == "spot" else 2, found)
                for fold in found:
                    with self.subTest(browser=browser, width=width, place=place, root=fold["selector"]):
                        self.assertNotIn("error", fold, fold)
                        self.assertEqual((fold["opened"]["open"], fold["opened"]["outside"]), (True, []), fold)
                        self.assertGreaterEqual(fold["opened"]["whole"], 1, fold)
                        self.check_side(fold["opened"])
                        self.assertEqual(fold["escape"], [False, True], fold)
                        self.assertEqual(fold["again"], {"open": True, "outside": []}, fold)
                        self.assertEqual(fold["click"], [False, False, True], fold)

    def focus_steps(self, browser: str) -> list[dict]:
        self.stations()
        return [{"width": width, "height": height, "url": f"http://localhost:{self.port}/?{width}-focus#stream", "wait": 1500, "probe": probe(FOCUS), "shot": str(OUT / f"{browser}-{width}-focus.png")}
                for width, height in FOCUS_SIZES]

    def check_focus(self, data: dict, browser: str) -> None:
        for (width, _), cases in zip(FOCUS_SIZES, data["results"], strict=True):
            for key, found in cases.items():
                with self.subTest(browser=browser, width=width, case=key):
                    if key == "escape":
                        self.assertEqual(found, {"closed": True, "toggle": True}, found)
                        continue
                    self.assertEqual((found["opened"], found["closed"], found["summary"]), (True, True, False), found)
                    self.assertTrue(found["history"] if key.endswith("tab") else found["body"], found)

    def watch(self, browser: str, kind: str, template: str) -> dict:
        width, height = FOCUS_SIZES[0]
        step = {"width": width, "height": height, "url": f"http://localhost:{self.port}/?{width}-{kind}#stream", "wait": 1500, "probe": probe(template), "shot": str(OUT / f"{browser}-{width}-{kind}.png")}
        driver = ("bidi.mjs", os.environ.get("FIREFOX", "firefox")) if browser == "firefox" else ()
        data = self.drive([step], None, *driver)
        (OUT / f"{browser}-radio-{kind}.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        return data["results"][0]

    def check_rows(self, found: dict, browser: str) -> None:
        want = {"same": True, "key": found["start"].pop("want"), "pick": True, "body": False}
        for moment, done in (("start", None), ("fresh", "delivered"), ("tick", "ticked")):
            with self.subTest(browser=browser, moment=moment):
                if done:
                    self.assertTrue(found[moment].pop(done), found)
                self.assertEqual(found[moment], want, found)
        with self.subTest(browser=browser, moment="tabs"):
            self.assertIsNotNone(found["tabs"].pop("tab"), found)
            self.assertEqual(found["tabs"], {"delivered": [True, True, True], "focusins": 0, "same": True}, found)

    def twins(self) -> None:
        now = time.time()
        with (self.council / "news.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(self.jsonl([{"ts": now - 50, "from": "Docs", "to": [], "text": words, "class": "broadcast", "v": 2} for words in DUPS]))

    def check_keys(self, found: dict, browser: str) -> None:
        with self.subTest(browser=browser, case="keys"):
            self.assertEqual(len(set(found["keys"])), len(DUPS), found)
        for words in DUPS:
            with self.subTest(browser=browser, case=words):
                self.assertEqual(found[words], {"delivered": True, "same": True, "line": words, "popup": words}, found)
        with self.subTest(browser=browser, case="filtered"):
            self.assertEqual(found["filtered"], {"gone": True, "pick": True, "class": "call"}, found)
        with self.subTest(browser=browser, case="emptied"):
            self.assertEqual(found["emptied"], {"gone": True, "list": True}, found)

    def check_banner(self, found: dict, browser: str) -> None:
        with self.subTest(browser=browser, moment="steady"):
            self.assertEqual(found["steady"], {"polled": True, "mutations": 0, "focus": True, "body": False}, found)
        with self.subTest(browser=browser, moment="changed"):
            self.assertTrue(found["changed"].pop("text").endswith(NEW_ALARM), found)
            self.assertEqual(found["changed"], {"polled": True, "added": 1, "shown": True, "cancel": True}, found)

    def test_chromium_leaves_the_focus_where_a_click_lands_and_returns_it_to_the_toggle_only_on_escape(self):
        data = self.drive(self.focus_steps("chromium"), None)
        (OUT / "chromium-radio-focus.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        self.check_focus(data, "chromium")

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_leaves_the_focus_where_a_click_lands_and_returns_it_to_the_toggle_only_on_escape(self):
        data = self.drive(self.focus_steps("firefox"), None, "bidi.mjs", os.environ.get("FIREFOX", "firefox"))
        (OUT / "firefox-radio-focus.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        self.check_focus(data, "firefox")

    def test_chromium_holds_the_focus_on_a_history_row_and_its_tab_across_new_rows_and_the_minute_tick(self):
        self.check_rows(self.watch("chromium", "rows", ROWS), "chromium")

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_holds_the_focus_on_a_history_row_and_its_tab_across_new_rows_and_the_minute_tick(self):
        self.check_rows(self.watch("firefox", "rows", ROWS), "firefox")

    def test_chromium_keys_twin_rows_apart_and_moves_the_focus_of_a_filtered_out_row_to_the_nearest_row_or_the_list(self):
        self.twins()
        self.check_keys(self.watch("chromium", "keys", KEYS), "chromium")

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_keys_twin_rows_apart_and_moves_the_focus_of_a_filtered_out_row_to_the_nearest_row_or_the_list(self):
        self.twins()
        self.check_keys(self.watch("firefox", "keys", KEYS), "firefox")

    def test_chromium_redraws_the_mayday_banner_only_when_the_silence_changes(self):
        self.silence(ALARMS["mayday"])
        self.check_banner(self.watch("chromium", "banner", BANNER), "chromium")

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_redraws_the_mayday_banner_only_when_the_silence_changes(self):
        self.silence(ALARMS["mayday"])
        self.check_banner(self.watch("firefox", "banner", BANNER), "firefox")

    def test_chromium_places_the_station_popover_inside_every_clip_and_closes_it_on_escape_and_outside_clicks_in_the_spot_and_on_home(self):
        data = self.drive(self.popover_steps("chromium"), None)
        (OUT / "chromium-radio-popover.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        self.check_popover(data, "chromium")

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_places_the_station_popover_inside_every_clip_and_closes_it_on_escape_and_outside_clicks_in_the_spot_and_on_home(self):
        data = self.drive(self.popover_steps("firefox"), None, "bidi.mjs", os.environ.get("FIREFOX", "firefox"))
        (OUT / "firefox-radio-popover.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        self.check_popover(data, "firefox")

    def test_chromium_home_copies_keep_their_own_composer_record_reply_and_cancel_the_mayday(self):
        now = time.time()
        self.write_council({"radio-silence.json": {"since": now - 60, "until": now + 3600, "by": "Docs", "text": "disk full"}})
        steps = []
        for width, height in ((1366, 768), (390, 844)):
            shot = str(OUT / f"chromium-{width}")
            steps += [
                {"width": width, "height": height, "url": f"http://localhost:{self.port}/?{width}-copies#stream", "wait": 1500, "probe": probe(COMPOSE_HOME), "shot": f"{shot}-home-composers.png", "gesture": True},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(REPLY_HOME), "shot": f"{shot}-home-reply.png"},
            ]
        data = self.drive(steps, self.authenticator())
        (OUT / "chromium-radio-home-copies.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        results = iter(data["results"])
        question = "Lift the radio silence of the active mayday?"
        for width in (1366, 390):
            composed, replied = next(results), next(results)
            with self.subTest(width=width, part="own composer state"):
                self.assertEqual(composed["drafts"], ["draft kept in the spot", "", ""], composed)
                self.assertEqual((composed["first"], composed["handed"]), ("true", ["false", "true"]), composed)
                self.assertIn("hello from the mic", composed["spotHeard"] or "", composed)
                self.assertNotIn("hello from the mic", composed["homeBefore"], composed)
                self.assertIn("hello from the mic", composed["homeHeard"] or "", composed)
                self.assertTrue(all(composed["notes"]) and composed["notes"][0] != composed["notes"][1], composed)
                self.assertTrue((composed["spotSent"] or "").startswith("Post to Stage: sent"), composed)
                self.assertTrue(composed["homeAttach"], composed)
                self.assertTrue((composed["homeSent"] or "").startswith("Post to Docs: sent"), composed)
                self.assertEqual(composed["bodies"], [["Stage", "plain text from the spot", ""], ["Docs", "voice from the Home tile", composed["notes"][1]]], composed)
            with self.subTest(width=width, part="reply and mayday from Home"):
                self.assertEqual(replied["fromLog"], {"spot": "false", "popup": False, "speak": {"channel": "post", "recipient": "Stage", "toShown": True, "focused": True},
                                                      "whole": {"channel": "post", "recipient": replied["fromLog"]["whole"]["recipient"], "toShown": True, "focused": False}}, replied)
                self.assertEqual(replied["fromWhole"], {"spot": "false", "whole": {"channel": "post", "recipient": "Stage", "toShown": True, "focused": True}}, replied)
                self.assertTrue((replied["sent"] or "").startswith("Post to Stage: sent"), replied)
                self.assertEqual((replied["enabled"], replied["questions"]), (True, [question]), replied)
                self.assertTrue((replied["lifted"] or "").startswith("Cancel mayday: done"), replied)
                self.assertEqual(replied["spot"], "false", replied)
        radio = [args for script, args in self.scripts.calls if script == skill_scripts.RADIO]
        self.assertEqual([args[:3] for args in radio if args[0] == "post"], [["post", "--to", "Stage"], ["post", "--to", "Docs"], ["post", "--to", "Stage"]] * 2, radio)
        self.assertEqual([args for args in radio if args[0] == "clear"], [["clear", "--force", "--session", "Operator"]] * 2, radio)


if __name__ == "__main__":
    unittest.main()
