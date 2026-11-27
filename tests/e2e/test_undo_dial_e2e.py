from __future__ import annotations

import json
import os
import shutil
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

import test_match_release_card_e2e as deck

OUT = Path(os.environ.get("E2E_OUT", "/tmp/hub-043-shots"))
WORDS = "10 s remain to undo"
TEXTS = """(async () => {@HELPERS@@CARD@@STEPS@
  const row = () => document.querySelector('#main .inbox-list > li[data-ref="@RED@"]');
  if (!(await until(row, 8000))) {
    return {error: text(document.getElementById("main")).slice(0, 300)};
  }
  all(".deny-split button", row()).find((button) => name(button).startsWith("Deny via")).click();
  const sheet = await until(() => document.querySelector(".sheet-box .deny-channels"), 4000);
  const deny = sheet ? all(".sheet-box p.muted").map(text).find((line) => line.startsWith("The passkey signs the denial")) : null;
  document.dispatchEvent(new KeyboardEvent("keydown", {key: "Escape", bubbles: true}));
  await until(() => !document.querySelector(".sheet-box .deny-channels"), 4000);
  document.getElementById("settings-open").click();
  const dial = await until(() => document.querySelector(".sheet-box form.settings .undo-dial"), 8000);
  if (!dial) {
    return {deny, error: "no dial"};
  }
  dial.scrollIntoView({block: "center"});
  await sleep(300);
  const attrs = () => ["role", "aria-valuemin", "aria-valuemax", "aria-valuenow", "aria-valuetext"].map((attr) => dial.getAttribute(attr));
  const dialed = {attrs: attrs(), label: dial.getAttribute("aria-label"), readout: text(dial.querySelector(".dial-readout")), ticks: all(".dial-tick", dial).length, long: all(".dial-tick.long", dial).length};
  const press = (key) => {
    dial.dispatchEvent(new KeyboardEvent("keydown", {key, bubbles: true, cancelable: true}));
    return dial.getAttribute("aria-valuenow");
  };
  dial.focus();
  const keys = [["ArrowRight", press("ArrowRight")], ["PageUp", press("PageUp")], ["End", press("End")], ["ArrowRight", press("ArrowRight")], ["PageDown", press("PageDown")], ["Home", press("Home")], ["ArrowLeft", press("ArrowLeft")]];
  const zero = {text: dial.getAttribute("aria-valuetext"), readout: text(dial.querySelector(".dial-readout"))};
  const box = dial.getBoundingClientRect();
  return {deny, opened: dialed, keys, zero, focused: document.activeElement === dial, inside: box.left >= 0 && box.right <= innerWidth, wide: document.documentElement.scrollWidth > innerWidth + 1};
})()"""
RELEASED = """(async () => {@HELPERS@@CARD@@STEPS@
  await screenShown(8000);
  if (!(await until(card, 8000)) || !(await decideAll())) {
    return {error: text(document.getElementById("main")).slice(0, 300)};
  }
  const risk = document.querySelector('#main .match-decision[data-card="@RED@"] .match-accept-risk');
  if (risk) {
    risk.click();
  }
  const release = await until(() => document.querySelector("#main .match-release"), 4000);
  return release ? {title: release.title} : {error: text(document.getElementById("main")).slice(0, 300)};
})()"""


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestUndoDial(deck.ReleaseDeck):
    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        payload = {**self.snapshot()["settings"], "undo": 10, "proof": None}
        self.assertEqual(self.post_json("/api/settings", payload, self.guard(self.host))[0], 200)

    def test_chromium_sets_the_undo_window_on_a_dial_and_every_undo_text_names_the_saved_seconds(self):
        steps = [
            {"width": 1366, "height": 768, "url": f"{self.base}?dial#stream/inbox", "wait": 1500, "shot": str(OUT / "chromium-1366-undo-dial.png"), "probe": deck.probe(TEXTS, red=f"review:{self.red}")},
            {"width": 1920, "height": 1080, "url": f"{self.base}?dial-release#tasks/match", "wait": 1500, "shot": str(OUT / "chromium-1920-undo-release.png"), "probe": deck.probe(RELEASED, red=f"review:{self.red}")},
        ]
        data = self.drive(steps, None, init=deck.INIT)
        (OUT / "chromium-undo-dial.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        texts, released = data["results"]
        for found in (texts, released):
            self.assertNotIn("error", found, found)
        self.assertIn(f"then {WORDS}.", texts["deny"], texts)
        self.assertEqual(texts["opened"], {"attrs": ["slider", "0", "60", "10", "10 seconds to undo"], "label": "Undo window in seconds", "readout": "10 s", "ticks": 60, "long": 12}, texts)
        self.assertEqual(texts["keys"], [["ArrowRight", "11"], ["PageUp", "16"], ["End", "60"], ["ArrowRight", "60"], ["PageDown", "55"], ["Home", "0"], ["ArrowLeft", "0"]], texts)
        self.assertEqual(texts["zero"], {"text": "0 seconds: takes effect at once", "readout": "0 s"}, texts)
        self.assertEqual((texts["focused"], texts["inside"], texts["wide"]), (True, True, False), texts)
        self.assertTrue(released["title"].endswith(f"after each signature {WORDS}."), released)


if __name__ == "__main__":
    unittest.main()
