from __future__ import annotations

import json
import os
import shutil
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

import hub_e2e_kit as base
import test_match_review_e2e as matched
import test_workbench_w4_e2e as w4
from hub_case import HubCase

OUT = Path(os.environ.get("E2E_OUT", "/tmp/hub-035-036-shots"))
DECK = """
  const widen = () => card() && card().querySelector(".match-widen");
  const shown = (node) => Boolean(node && node.getClientRects().length);
  const area = () => {
    const box = document.querySelector("#main .graph.match");
    const look = getComputedStyle(box);
    return box.clientWidth - parseFloat(look.paddingLeft) - parseFloat(look.paddingRight);
  };
  const width = () => card().offsetWidth;
  const later = async () => {
    const before = card().dataset.card;
    document.body.dispatchEvent(new KeyboardEvent("keydown", {key: "ArrowUp", bubbles: true}));
    return Boolean(await until(() => card() && card().dataset.card !== before, 4000));
  };
  const flip = async (wide) => {
    widen().click();
    await until(() => document.querySelector("#main .match-stack").dataset.wide === String(wide), 4000);
    await sleep(200);
  };
"""
WIDE = """(async () => {@HELPERS@@CARD@@DECK@
  await screenShown(8000);
  if (!(await until(card, 8000))) {
    return {error: text(document.getElementById("main")).slice(0, 300)};
  }
  await sleep(300);
  if (document.querySelector("#main .match-stack").dataset.wide === "true") {
    await flip(false);
  }
  const before = {button: shown(widen()), width: width(), area: Math.round(area())};
  if (!before.button) {
    return {before};
  }
  await flip(true);
  const wide = {width: width(), area: Math.round(area()), label: widen().getAttribute("aria-label"), keys: await later()};
  wide.after = width();
  return {before, wide};
})()"""
KEPT = """(async () => {@HELPERS@@CARD@@DECK@
  await screenShown(8000);
  if (!(await until(card, 8000))) {
    return {error: text(document.getElementById("main")).slice(0, 300)};
  }
  await sleep(300);
  const kept = {wide: document.querySelector("#main .match-stack").dataset.wide, width: width(), area: Math.round(area())};
  await flip(false);
  const narrow = {width: width(), label: widen().getAttribute("aria-label"), keys: await later()};
  narrow.after = width();
  return {kept, narrow};
})()"""
PILE = """(async () => {@HELPERS@@CARD@@DECK@
  await screenShown(8000);
  if (!(await until(card, 8000))) {
    return {error: text(document.getElementById("main")).slice(0, 300)};
  }
  await sleep(300);
  const open = () => Number((text(document.querySelector("#main .task-toolbar .muted")) || "").split(" ")[0]);
  const pile = () => {
    const front = card();
    const edge = front.getBoundingClientRect();
    return {open: open(), release: front.classList.contains("match-release-card"), layers: all("#main .match-layer").map((layer) => ({
      size: Math.abs(layer.offsetWidth - front.offsetWidth) <= 2 && Math.abs(layer.offsetHeight - front.offsetHeight) <= 2,
      above: layer.getBoundingClientRect().top < edge.top - 1,
      lower: Number(getComputedStyle(layer).zIndex) < Number(getComputedStyle(front).zIndex),
      inert: getComputedStyle(layer).pointerEvents === "none" && layer.getAttribute("aria-hidden") === "true",
    }))};
  };
  const seen = [pile()];
  for (let tries = 0; open() > 1 && tries < 8; tries += 1) {
    const count = open();
    document.body.dispatchEvent(new KeyboardEvent("keydown", {key: "ArrowLeft", bubbles: true}));
    const confirm = await until(() => document.querySelector(".match-feedback-reject"), 2000);
    if (!confirm) {
      await later();
      continue;
    }
    confirm.click();
    if (await until(() => open() === count - 1 && card(), 4000)) {
      await sleep(500);
      seen.push(pile());
    }
  }
  return {seen};
})()"""


def probe(template: str) -> str:
    return template.replace("@HELPERS@", base.HELPERS).replace("@CARD@", matched.CARD).replace("@DECK@", DECK)


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestMatchPile(HubCase):
    drive = base.OrchestratorE2ECase.drive
    cards = matched.TestMatchReview.cards
    review = matched.TestMatchReview.review
    payload = matched.TestMatchReview.payload

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        self.cards()

    def steps(self) -> list[dict]:
        steps = []
        for width, height in base.WIDTHS:
            at = {"width": width, "height": height}
            shot = OUT / f"chromium-{width}"
            steps.append({**at, "url": f"{self.base}?{width}-wide#tasks/match", "wait": 1500, "probe": probe(WIDE), "shot": f"{shot}-match-wide.png"})
            if width > 640:
                steps.append({**at, "url": f"{self.base}?{width}-kept#tasks/match", "wait": 1500, "probe": probe(KEPT), "shot": f"{shot}-match-narrow.png"})
            steps.append({**at, "url": f"{self.base}?{width}-pile#tasks/match", "wait": 1500, "probe": probe(PILE), "shot": f"{shot}-match-pile.png"})
        return steps

    def test_chromium_widens_a_match_card_keeps_the_choice_and_piles_the_waiting_cards_behind_it(self):
        data = self.drive(self.steps(), None, init=w4.GUARD)
        (OUT / "chromium-match-pile.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        results = iter(data["results"])
        for width, _ in base.WIDTHS:
            wide = next(results)
            kept = next(results) if width > 640 else None
            pile = next(results)
            with self.subTest(width=width, step="wide"):
                self.assertNotIn("error", wide, wide)
                self.assertEqual(wide["before"]["button"], width > 640, wide)
                self.assertLessEqual(wide["before"]["width"], 960, wide)
                if width > 640:
                    self.assertLessEqual(abs(wide["wide"]["width"] - wide["wide"]["area"]), 2, wide)
                    self.assertEqual((wide["wide"]["label"], wide["wide"]["keys"], wide["wide"]["after"]), ("Normal width", True, wide["wide"]["width"]), wide)
            if kept:
                with self.subTest(width=width, step="kept"):
                    self.assertNotIn("error", kept, kept)
                    self.assertEqual(kept["kept"]["wide"], "true", kept)
                    self.assertLessEqual(abs(kept["kept"]["width"] - kept["kept"]["area"]), 2, kept)
                    self.assertLessEqual(kept["narrow"]["width"], 960, kept)
                    self.assertEqual((kept["narrow"]["label"], kept["narrow"]["keys"], kept["narrow"]["after"]), ("Full width", True, kept["narrow"]["width"]), kept)
            with self.subTest(width=width, step="pile"):
                self.assertNotIn("error", pile, pile)
                seen = pile["seen"]
                self.assertGreaterEqual(seen[0]["open"], 3, seen)
                self.assertEqual(seen[-1]["open"], 1, seen)
                for state in seen:
                    self.assertEqual(len(state["layers"]), min(2, state["open"] - (0 if state["release"] else 1)), state)
                    for layer in state["layers"]:
                        self.assertEqual(layer, {"size": True, "above": True, "lower": True, "inert": True}, state)


if __name__ == "__main__":
    unittest.main()
