from __future__ import annotations

import json
import os
import shutil
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

import radio_layout_kit as kit
from radio_layout_kit import (
    ALARMS,
    BANNER_MAX,
    DEFAULTS,
    FILLERS,
    LAPTOPS,
    LONG,
    NAMES,
    NARROW,
    OUT,
    PARTS,
    PLAY_MIN,
    SCROLLER,
    STAGE_SHARE,
    STATES,
    VIEWS,
    WIDTHS,
    columns,
    probe,
)
from radio_layout_probes import CLOSE_REPLY, FIT, HOME, LAYOUT, POPUP, SPOT


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestRadioLayout(kit.RadioLayoutCase):
    def steps(self, browser: str) -> list[dict]:
        steps = []
        for width, height in WIDTHS:
            shot = str(OUT / f"{browser}-{width}")
            steps += [
                {"width": width, "height": height, "url": f"http://localhost:{self.port}/?{width}#stream", "wait": 1500, "probe": probe(LAYOUT), "shot": f"{shot}-radio.png"},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(POPUP), "shot": f"{shot}-popup.png", "gesture": True},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(CLOSE_REPLY), "shot": f"{shot}-reply.png"},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(HOME), "shot": f"{shot}-home.png"},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(FIT), "shot": f"{shot}-orbit.png"},
            ]
        return steps

    def check_layout(self, layout: dict, size: tuple[int, int], index: int, browser: str) -> None:
        width = size[0]
        self.assertNotIn("error", layout, layout)
        self.assertLessEqual(layout["page"][0], layout["page"][1], layout)
        if columns(*size):
            self.assertLessEqual(layout["tall"][0], layout["tall"][1], layout)
        self.assertEqual(layout["wider"], [], layout)
        self.assertEqual(layout["scrollers"], ["radio-log"], layout)
        self.assertEqual((layout["list"]["overflowY"], layout["list"]["scrollbar"][0], layout["list"]["scrolls"]), ("auto", "thin", True), layout)
        self.assertNotIn(layout["list"]["scrollbar"][1], ("", "auto"), layout)
        if browser == "firefox":
            self.assertNotIn(layout["main"], ("", "auto"), layout)
        self.assertEqual(len(layout["heights"]), 1, layout)
        self.assertLess(layout["heights"][0], 2 * layout["lineHeight"], layout)
        self.assertTrue(layout["single"], layout)
        self.assertGreaterEqual(layout["narrowest"], 30, layout)
        self.assertEqual(layout["rows"], FILLERS + 2 + index, layout)
        self.assertEqual(layout["long"], [True, "ellipsis"], layout)
        self.assertGreaterEqual(layout["avatars"].pop("rows"), 2, layout)
        cap = 3 if width in NARROW else 8
        self.assertEqual(layout["avatars"], {"most": cap, "inside": True, "after": True, "stacked": True}, layout)
        self.assertEqual(layout["folds"], [[total, min(total, cap), [f"+{total - cap}"] if total > cap else []] for total, _, _ in layout["folds"]], layout)
        self.assertGreaterEqual(layout["sliver"], 10, layout)
        self.assertTrue(layout["order"]["stacked" if width == 390 else "beside"], layout)
        self.assertEqual(layout["labels"], 1, layout)
        self.assertEqual(layout["stars"], [[part, True] for part in PARTS], layout)
        self.assertEqual(layout["covered"], [], layout)
        self.assertEqual(layout["stations"], [True, False], layout)

    def check_popup(self, popup: dict) -> None:
        self.assertNotIn("error", popup, popup)
        self.assertTrue(popup["open"], popup)
        self.assertEqual(popup["title"], "Stage → all", popup)
        self.assertEqual(list(popup["fields"]), ["Sender", "Recipient", "Class", "Time"], popup)
        self.assertEqual((popup["fields"]["Sender"], popup["fields"]["Recipient"], popup["fields"]["Class"]), ("Stage", "all", "Broadcast"), popup)
        self.assertTrue(popup["fields"]["Time"], popup)
        self.assertEqual((popup["full"], popup["stray"]), (LONG, []), popup)
        self.assertEqual(popup["heading"], f"Read by {len(popup['readers'])}", popup)
        self.assertGreater(len(popup["readers"]), 8, popup)
        self.assertLessEqual({reader["name"] for reader in popup["readers"]}, set(NAMES), popup)
        timed = [reader for reader in popup["readers"] if reader["time"] != "read, time unknown"]
        self.assertEqual([(reader["session"], reader["name"]) for reader in timed], [("s5", "Beacon")], popup)
        self.assertRegex(timed[0]["time"], r"^read about \S.*\d", popup)
        self.assertEqual(popup["buttons"], ["Reply", "Copied"], popup)
        self.assertEqual((popup["copied"], popup["shown"]), ([LONG], "Copied"), popup)
        self.assertEqual(popup["region"], ["status", "polite", True, True], popup)
        self.assertEqual(popup["success"], ["Copied", "Copied: the full message is on the clipboard"], popup)
        self.assertEqual(popup["reset"], ["Copy", ""], popup)
        self.assertEqual(popup["failure"], ["Not copied", "Not copied: the browser refused the clipboard"], popup)
        self.assertTrue(popup["inView"], popup)

    def check_home(self, home: dict, width: int) -> None:
        self.assertEqual(home["pressed"], {part: "true" for part in PARTS}, home)
        self.assertEqual(home["stored"], [[f"panel:{part}", *DEFAULTS[part]] for part in PARTS], home)
        for moment in ("fresh", "resized"):
            for part in PARTS:
                with self.subTest(moment=moment, tile=part):
                    found = home[moment][part]
                    stacked = width == 390 and part == "radio"
                    expected = ["home-body"] if stacked else [SCROLLER[part]] if SCROLLER[part] else []
                    self.assertEqual(found["scrollers"], expected, home[moment])
                    if found["rows"] is not None and not stacked:
                        self.assertGreaterEqual(found["rows"], 2, home[moment])
                        self.assertTrue(found["inside"], home[moment])
                        self.assertTrue(found["filled"], home[moment])
        self.assertEqual(home["tools"]["gear"], ["true", True, True], home)
        self.assertEqual(home["tools"]["clear"], [True, "Cancel mayday: lift the radio silence so the agents write again; your passkey signs it"], home)
        content = home["content"]
        self.assertEqual(content["tiles"], [f"panel:{part}" for part in PARTS], home)
        self.assertEqual(content["radio"], [True, True, True], home)
        self.assertEqual(content["device"], ["Auto", 6], home)
        self.assertEqual(content["speak"], [True, True], home)
        self.assertEqual(content["log"][0], content["log"][2], home)
        self.assertEqual(content["log"][1], content["log"][2], home)
        self.assertEqual((content["gone"], content["stars"], content["ids"]), (0, 0, []), home)
        self.assertIsNotNone(home["live"], home)
        self.assertEqual(home["live"][0], home["live"][1], home)
        self.assertEqual(home["mode"], ["Quiet", "Quiet"], home)
        self.assertFalse(home["wide"], home)

    def check_fit(self, fit: dict, size: tuple[int, int]) -> None:
        self.assertTrue(fit["fit"], fit)
        self.assertFalse(fit["wide"], fit)
        self.assertTrue(fit["speak"], fit)
        self.assertEqual((fit["closed"]["boxes"], fit["closed"]["tall"]), (0, False), fit)
        self.assertGreaterEqual(fit["closed"]["stage"], 2 * STAGE_SHARE * fit["height"], fit)
        self.assertEqual(fit["scrollers"], ["radio-log"], fit)
        if not columns(*size):
            self.assertTrue(fit["tall"], fit)
            self.assertGreaterEqual(fit["stage"], 2 * STAGE_SHARE * fit["height"], fit)
        else:
            self.assertGreater(fit["closed"]["stage"], fit["stage"], fit)
            self.assertFalse(fit["tall"], fit)
            self.assertGreaterEqual(fit["stage"], STAGE_SHARE * fit["height"], fit)
            self.assertGreaterEqual(fit["list"], 60, fit)

    def laptop_steps(self, browser: str, states: list[str]) -> list[dict]:
        places = [(width, height, view) for width, height in LAPTOPS for view in VIEWS]
        return [{"width": width, "height": height, "url": f"http://localhost:{self.port}/?{width}x{height}-{states[-1]}#stream" if view == VIEWS[0] else None, "wait": 1500 if view == VIEWS[0] else 0, "gesture": True,
                 "probe": probe(SPOT.replace("@VIEW@", view).replace("@STATES@", json.dumps(states)).replace("@CUE@", f"layout-cue-{index}")),
                 "shot": str(OUT / f"{browser}-{width}x{height}-{view[1:].replace('/', '-')}-{states[-1]}.png")} for index, (width, height, view) in enumerate(places)]

    def laptops(self, browser: str, *driver: str) -> dict:
        self.stations()
        self.speaks(tuple(f"layout-cue-{index}" for index in range(len(LAPTOPS) * len(VIEWS))))
        runs = [self.drive(self.laptop_steps(browser, [state for state in STATES if state not in ALARMS]), None, *driver)]
        for state, words in ALARMS.items():
            self.silence(words)
            runs.append(self.drive(self.laptop_steps(browser, [state]), None, *driver))
        return {"results": [{key: value for part in parts for key, value in part.items()} for parts in zip(*(run["results"] for run in runs), strict=True)], "errors": [error for run in runs for error in run["errors"]]}

    def check_laptops(self, data: dict, browser: str) -> None:
        results = iter(data["results"])
        for width, height in LAPTOPS:
            for view in VIEWS:
                states = next(results)
                for state in STATES:
                    with self.subTest(browser=browser, size=f"{width}x{height}", view=view, state=state):
                        self.check_state(states[state], state, view)
                        self.check_side(states[state], width, height)

    def check_side(self, found: dict, width: int, height: int) -> None:
        self.assertGreaterEqual(found["main"], found["floor"], found)
        self.assertLessEqual(found["page"][0], found["page"][2], found)
        self.assertLessEqual(found["stack"]["head"], found["stack"]["chips"][0] + 1, found)
        self.assertLessEqual(found["stack"]["chips"][1], found["stack"]["list"] + 1, found)
        if columns(width, height):
            self.assertLessEqual(found["page"][1], found["page"][3], found)
            self.assertEqual(found["scrollers"], ["radio-log"], found)
            self.assertTrue(found["order"], found)
            if found["fit"]:
                self.assertGreaterEqual(found["stage"], STAGE_SHARE * height, found)
            return
        self.assertGreaterEqual(found["main"], found["full"] - 1, found)
        self.assertTrue(found["beneath"], found)
        if found["fit"]:
            self.assertGreaterEqual(found["stage"], 2 * STAGE_SHARE * height, found)

    def check_state(self, found: dict, state: str, view: str) -> None:
        self.assertEqual(found["active"], {"stations": 3 if state == "stations" else 0, "voice": state == "voice", "speech": state == "speech"}, found)
        self.assertEqual(found["banner"] is not None, state in ALARMS, found)
        if state in ALARMS:
            self.assertLessEqual(found["banner"]["height"], BANNER_MAX, found)
            self.assertEqual((found["banner"]["title"], found["banner"]["cut"], found["banner"]["cancel"]), (found["banner"]["full"], state == "mayday-long", True), found)
            self.assertTrue(found["banner"]["full"].endswith(ALARMS[state]), found)
        self.assertEqual(found["blocked"], [], found)
        if state == "stations":
            self.assertEqual(found["closed"], [False, True], found)
        if state == "voice":
            self.assertTrue(found["heard"], found)
            self.assertEqual(len(found["play"]), 1, found)
            kind, width, tall = found["play"][0]
            self.assertGreaterEqual(width, PLAY_MIN[kind][0], found)
            self.assertGreaterEqual(tall, PLAY_MIN[kind][1], found)
            if kind == "BUTTON":
                self.assertEqual((found["played"], found["paused"]), (True, True), found)
        if state == "speech":
            self.assertEqual(found["who"], "Stage speaking", found)
            self.assertGreaterEqual(found["line"][0], 4 * found["rem"], found)
            self.assertGreater(found["line"][1], 0, found)
        self.assertEqual(found["fit"], view != "#stream", found)
        self.assertEqual(found["cards"], [True, True], found)
        self.assertGreaterEqual(found["list"], 60, found)
        self.assertGreaterEqual(found["rows"], 2, found)

    def check(self, data: dict, browser: str) -> None:
        results = iter(data["results"])
        for index, (width, height) in enumerate(WIDTHS):
            layout, popup, closing, home, fit = (next(results) for _ in range(5))
            with self.subTest(browser=browser, width=width, part="layout"):
                self.check_layout(layout, (width, height), index, browser)
            with self.subTest(browser=browser, width=width, part="popup"):
                self.check_popup(popup)
            with self.subTest(browser=browser, width=width, part="close and reply"):
                self.assertTrue(closing["escaped"], closing)
                self.assertEqual(closing["outside"], [True, True], closing)
                self.assertEqual(closing["reply"], {"open": False, "channel": "post", "recipient": "Stage", "toShown": True, "focused": True}, closing)
            with self.subTest(browser=browser, width=width, part="home"):
                self.check_home(home, width)
            with self.subTest(browser=browser, width=width, part="fit view"):
                self.check_fit(fit, (width, height))

    def test_chromium_lays_the_radio_out_without_overflow_one_line_rows_popup_and_four_home_stars_at_four_widths(self):
        data = self.drive(self.steps("chromium"), None)
        (OUT / "chromium-radio-layout.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        self.check(data, "chromium")

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_lays_the_radio_out_without_overflow_one_line_rows_popup_and_four_home_stars_at_four_widths(self):
        data = self.drive(self.steps("firefox"), None, "bidi.mjs", os.environ.get("FIREFOX", "firefox"))
        (OUT / "firefox-radio-layout.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        self.check(data, "firefox")

    def test_chromium_keeps_the_main_floor_and_reachable_radio_controls_in_six_states_on_both_sides_of_the_height_threshold(self):
        data = self.laptops("chromium")
        (OUT / "chromium-radio-laptops.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        self.check_laptops(data, "chromium")

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_keeps_the_main_floor_and_reachable_radio_controls_in_six_states_on_both_sides_of_the_height_threshold(self):
        data = self.laptops("firefox", "bidi.mjs", os.environ.get("FIREFOX", "firefox"))
        (OUT / "firefox-radio-laptops.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        self.check_laptops(data, "firefox")


if __name__ == "__main__":
    unittest.main()
