from __future__ import annotations

import json
import os
import shutil
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

import test_match_release_card_e2e as deck
from kvb_orchestrator import batches

OUT = Path(os.environ.get("E2E_OUT", "/tmp/hub-055-shots"))
WASD = """(async () => {@HELPERS@@CARD@@STEPS@
  await screenShown(8000);
  if (!(await until(card, 8000))) {
    return {error: text(document.getElementById("main")).slice(0, 300)};
  }
  await sleep(300);
  const front = () => (card() ? card().dataset.card : null);
  const tally = () => text(document.querySelector("#main .match-tally"));
  const press = async (name) => {
    const was = front();
    key(name);
    await until(() => front() !== was, 3000);
    await sleep(250);
    return front();
  };
  const seen = [front()];
  seen.push(await press("d"));
  seen.push(await press("w"));
  seen.push(await press("d"));
  const decided = tally();
  const undone = [await press("s"), await press("s"), await press("s")];
  const cleared = tally();
  for (let tries = 0; tries < 4 && !card().querySelector(".match-file tr[data-line]"); tries += 1) {
    await press("w");
  }
  const row = card().querySelector(".match-file tr[data-line]");
  let typed = null;
  if (row) {
    const spot = row.getBoundingClientRect();
    row.dispatchEvent(new MouseEvent("contextmenu", {bubbles: true, cancelable: true, clientX: spot.left + 40, clientY: spot.top + 4, button: 2}));
    const field = await until(() => card().querySelector(".match-comment textarea"), 3000);
    const was = front();
    field.focus();
    field.dispatchEvent(new KeyboardEvent("keydown", {key: "d", bubbles: true, cancelable: true}));
    await sleep(500);
    typed = {front: front() === was, tally: tally()};
    card().querySelector(".match-comment .btn.ghost").click();
  }
  key("a");
  const sheet = Boolean(await until(() => document.querySelector(".sheet-box .match-feedback"), 3000));
  document.querySelector(".sheet-box .btn.ghost").click();
  await sleep(300);
  for (let tries = 0; tries < 4 && (front() === "@RED@" || card().dataset.stale === "true"); tries += 1) {
    await press("w");
  }
  await press("d");
  const lap = [front()];
  for (let step = 0; step < 8; step += 1) {
    lap.push(await press("w"));
  }
  for (let tries = 0; tries < 12 && front() !== "release"; tries += 1) {
    await press("w");
  }
  if (front() !== "release") {
    return {error: "W never brought the release card", seen, lap};
  }
  const onRelease = {a: await press("a")};
  document.querySelector("#main .match-open-overview").click();
  await until(releasing, 3000);
  onRelease.w = await press("w");
  onRelease.s = await press("s");
  window.e2eSubmits.length = 0;
  key("d");
  await until(() => window.e2eSubmits.length, 20000);
  onRelease.d = window.e2eSubmits;
  return {seen, decided, undone, cleared, typed, sheet, lap, onRelease};
})()"""


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestMatchWasd(deck.ReleaseDeck):
    def test_chromium_runs_the_deck_with_wasd_undoes_step_by_step_and_brings_the_release_card_once_a_lap(self):
        OUT.mkdir(parents=True, exist_ok=True)
        step = {"width": 1920, "height": 1080, "url": f"{self.base}?wasd#tasks/match", "wait": 1500, "shot": str(OUT / "chromium-wasd.png"), "probe": deck.probe(WASD, red=f"review:{self.red}")}
        with mock.patch.object(batches, "UNDO", 0.3):
            data = self.drive([step], self.authenticator(), init=deck.INIT)
        (OUT / "chromium-wasd.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        found = data["results"][0]
        self.assertNotIn("error", found, found)
        first, second, third, _ = found["seen"]
        self.assertEqual(found["decided"], "2", found)
        self.assertEqual(found["undone"], [third, second, first], found)
        self.assertEqual(found["cleared"], "0", found)
        self.assertEqual(found["typed"], {"front": True, "tally": "0"}, found)
        self.assertTrue(found["sheet"], found)
        lap = found["lap"]
        period = lap.index(lap[0], 1)
        self.assertEqual(lap[period:], lap[: len(lap) - period], found)
        self.assertEqual(lap[:period].count("release"), 1, found)
        self.assertNotIn("release", [found["onRelease"]["a"], found["onRelease"]["w"]], found)
        self.assertEqual(found["onRelease"]["s"], "release", found)
        self.assertEqual(len(found["onRelease"]["d"]), 1, found)


if __name__ == "__main__":
    unittest.main()
