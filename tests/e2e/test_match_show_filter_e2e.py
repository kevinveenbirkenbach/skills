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
from hub_support import ASK

OUT = Path(os.environ.get("E2E_OUT", "/tmp/hub-097-show-shots"))
KEY = "kvb-orchestrator.match-show"
MENU = """
  const shownMenu = () => document.querySelector(".ctx-menu:not([hidden])");
  const showItems = () => all('[data-scope="match-show"] .ctx-item', shownMenu() || document.createElement("div"));
  const showRead = () => showItems().map((node) => [text(node.querySelector(".ctx-label")), text(node.querySelector(".muted")), node.getAttribute("role"), node.getAttribute("aria-checked")]);
  const showItem = (label) => showItems().find((node) => text(node.querySelector(".ctx-label")) === label);
  const rightClick = (node) => {
    const box = node.getBoundingClientRect();
    return !node.dispatchEvent(new MouseEvent("contextmenu", {bubbles: true, cancelable: true, button: 2, clientX: box.left + 8, clientY: box.top + 4}));
  };
  const closeMenu = async () => {
    if (shownMenu()) {
      shownMenu().dispatchEvent(new KeyboardEvent("keydown", {key: "Escape", bubbles: true, cancelable: true}));
    }
    await until(() => !shownMenu(), 3000);
  };
  const deckIds = () => [...new Set(all("#main .match-stack [data-card]").map((node) => node.dataset.card))];
  const hiddenHead = () => {
    const button = document.querySelector("#main .match-hidden");
    return button ? [button.hidden, text(button)] : null;
  };
"""
FIRST = """(async () => {@HELPERS@@CARD@@STEPS@@MENU@
  await screenShown(8000);
  if (!(await until(card, 8000))) {
    return {error: text(document.getElementById("main")).slice(0, 300)};
  }
  await sleep(400);
  const found = {head: hiddenHead(), asks: deckIds().filter((id) => id.startsWith("ask:")).length};
  found.prevented = rightClick(card().querySelector(".match-title"));
  await until(shownMenu, 3000);
  found.menu = showRead();
  showItem("Ask").click();
  await sleep(400);
  found.open = Boolean(shownMenu());
  found.ask = showItem("Ask") ? showItem("Ask").getAttribute("aria-checked") : null;
  await closeMenu();
  await until(() => !deckIds().some((id) => id.startsWith("ask:")), 4000);
  await sleep(400);
  found.after = {asks: deckIds().filter((id) => id.startsWith("ask:")).length, head: hiddenHead(), stored: localStorage.getItem("@KEY@")};
  for (let tries = 0; tries < 6 && !card().querySelector(".match-file tr[data-line]"); tries += 1) {
    const id = card().dataset.card;
    key("w");
    await until(() => card() && card().dataset.card !== id, 3000);
    await sleep(250);
  }
  const row = card().querySelector(".match-file tr[data-line]");
  if (row) {
    rightClick(row);
    found.comment = {field: Boolean(await until(() => card().querySelector(".match-comment textarea"), 3000)), menu: Boolean(shownMenu())};
    card().querySelector(".match-comment .btn.ghost").click();
    await sleep(300);
  }
  return found;
})()"""
SECOND = """(async () => {@HELPERS@@CARD@@STEPS@@MENU@
  await screenShown(8000);
  if (!(await until(card, 8000))) {
    return {error: text(document.getElementById("main")).slice(0, 300)};
  }
  await sleep(400);
  const found = {reloaded: {asks: deckIds().filter((id) => id.startsWith("ask:")).length, head: hiddenHead(), stored: localStorage.getItem("@KEY@")}};
  const decidedId = card().dataset.card;
  key("d");
  await until(() => !card() || card().dataset.card !== decidedId, 4000);
  await sleep(300);
  document.querySelector("#main .match-hidden").click();
  found.opened = Boolean(await until(shownMenu, 3000));
  for (const label of ["Commit", "Command"]) {
    showItem(label).click();
    await sleep(300);
  }
  await closeMenu();
  await until(releasing, 4000);
  await sleep(400);
  found.release = {front: releasing(), listed: all("#main .match-decision").map((node) => node.dataset.card), decided: decidedId, head: hiddenHead()};
  key("s");
  const empty = await until(() => document.querySelector("#main .match-deck > .match-all-hidden"), 4000);
  await sleep(300);
  found.empty = empty ? {words: text(empty.querySelector("h2")), glass: Boolean(empty.querySelector(".match-glass")), button: text(empty.querySelector(".match-show-all")), head: hiddenHead()} : null;
  if (empty) {
    empty.querySelector(".match-show-all").click();
  }
  await until(card, 4000);
  await sleep(400);
  found.restored = {cards: deckIds().filter((id) => id !== "release").length, asks: deckIds().filter((id) => id.startsWith("ask:")).length, head: hiddenHead(), stored: localStorage.getItem("@KEY@")};
  found.wide = document.documentElement.scrollWidth > innerWidth + 1;
  return found;
})()"""


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestMatchShowFilter(deck.ReleaseDeck):
    def setUp(self):
        super().setUp()
        self.ask = self.create_ask({**ASK, "command": "make show", "timeout": 3600})

    def step(self, name: str, template: str) -> dict:
        probe = deck.probe(template.replace("@MENU@", MENU), key=KEY)
        return {"width": 1366, "height": 900, "url": f"{self.base}?{name}#tasks/match", "wait": 1500, "probe": probe, "shot": str(OUT / f"chromium-{name}.png")}

    def test_chromium_hides_a_kind_remembers_it_across_a_reload_names_all_hidden_and_show_all_restores_the_deck(self):
        OUT.mkdir(parents=True, exist_ok=True)
        data = self.drive([self.step("show-first", FIRST), self.step("show-reload", SECOND)], None, init=deck.INIT)
        (OUT / "chromium-show.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        first, second = data["results"]
        self.assertNotIn("error", first, first)
        self.assertNotIn("error", second, second)
        self.assertEqual((first["head"], first["asks"], first["prevented"]), ([True, "0 hidden"], 1, True), first)
        menu = first["menu"]
        self.assertEqual([row[0] for row in menu], ["Commit", "Command", "Ask", "Decision", "Rule", "Expired", "Stale", "Greyed", "Show all"], first)
        self.assertEqual([row[2] for row in menu], ["menuitemcheckbox"] * 8 + ["menuitem"], first)
        self.assertEqual([row[3] for row in menu[:8]], ["true"] * 8, first)
        counts = {row[0]: row[1] for row in menu[:8]}
        self.assertEqual({label: counts[label] for label in ("Commit", "Command", "Ask", "Decision", "Rule", "Stale")}, {"Commit": "3", "Command": "1", "Ask": "1", "Decision": "0", "Rule": "0", "Stale": "1"}, first)
        self.assertTrue(all(counts[label].isdigit() for label in ("Expired", "Greyed")), first)
        self.assertEqual((first["open"], first["ask"]), (True, "false"), first)
        self.assertEqual(first["after"], {"asks": 0, "head": [False, "1 hidden"], "stored": '["ask"]'}, first)
        self.assertEqual(first["comment"], {"field": True, "menu": False}, first)
        self.assertEqual(second["reloaded"], {"asks": 0, "head": [False, "1 hidden"], "stored": '["ask"]'}, second)
        self.assertTrue(second["opened"], second)
        release = second["release"]
        self.assertTrue(release["front"], second)
        self.assertIn(release["decided"], release["listed"], second)
        self.assertEqual(release["head"], [False, "4 hidden"], second)
        self.assertEqual(second["empty"], {"words": "All 5 cards hidden by the Show filter", "glass": False, "button": "Show all", "head": [False, "5 hidden"]}, second)
        self.assertEqual(second["restored"]["asks"], 1, second)
        self.assertEqual((second["restored"]["head"], second["restored"]["stored"]), ([True, "0 hidden"], "[]"), second)
        self.assertGreaterEqual(second["restored"]["cards"], 5, second)
        self.assertFalse(second["wide"], second)


if __name__ == "__main__":
    unittest.main()
