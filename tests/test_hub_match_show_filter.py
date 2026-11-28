"""Exercise requirement 097: the Show filter of Match's context menu over card kinds and states."""

from __future__ import annotations

import json
import re
import subprocess
import unittest
from pathlib import Path

from hub_support import HUB

MATCH = HUB / "templates" / "page-match.js"
CONTEXT = HUB / "templates" / "page-context.js"
MATCH_NAMES = (
    "MATCH_KINDS", "MATCH_STAMPS", "lapsedCard", "greyStamp", "MATCH_SHOWS", "SHOW_STATES", "showState", "shownCard", "hiddenWords", "allHiddenWords",
    "matchHidden", "decisionOf", "showSplit", "showCounts", "toggleShow", "showAll", "matchShowItems", "decided", "unreleasable", "risky", "releasePlan",
)
CONTEXT_NAMES = ("CTX_MATCH", "ctxOwn", "ctxSections", "ctxItem", "ctxRun")
PROBE = r"""
const vm = require("vm");
const sandbox = {
  RELEASE: "release",
  STORE: {show: "kvb-orchestrator.match-show"},
  storage: {},
  matchView: {cards: null, order: [], decisions: new Map(), history: []},
  refusedIds: new Map(),
  expiredWords: () => "expired 20:41, 3 minutes ago",
  draws: 0,
  closes: 0,
  out: {},
  ctxMenu: {checks: []},
  ctxFound: () => [],
  paletteItems: () => [],
  Nav: {TABS: [], tabOf: () => ""},
  ui: {screen: "match"},
  revealed: (text) => text,
  icon: () => null,
  face: () => null,
};
sandbox.stored = (key, fallback) => (Object.hasOwn(sandbox.storage, key) ? JSON.parse(sandbox.storage[key]) : fallback);
sandbox.keep = (key, value) => {
  sandbox.storage[key] = JSON.stringify(value);
  return true;
};
sandbox.drawMatch = () => {
  sandbox.draws += 1;
};
sandbox.ctxClose = () => {
  sandbox.closes += 1;
};
sandbox.h = (tag, attrs, ...children) => ({tag, attrs: {...attrs}, children, setAttribute(name, value) { this.attrs[name] = value; }});
vm.runInNewContext(process.argv[1], sandbox);
vm.runInNewContext(`
  const card = (id, kind, extra) => ({id: kind + ":" + id, ref: id, kind, entry: kind === "commit" ? "review" : kind, title: id, hash: "h-" + id, blocked: "", stale: false, ...extra});
  const deck = [
    card("c1", "commit"),
    card("c2", "commit", {stale: true, stale_reason: "tree moved"}),
    card("m1", "command", {blocked: "runs", blocked_kind: "running"}),
    card("a1", "ask"),
    card("a2", "ask", {blocked: "expired", blocked_kind: "expired"}),
    card("a3", "ask", {blocked: "answer it there", blocked_kind: "claude"}),
    card("d1", "decision", {blocked: "waits", blocked_kind: "queued"}),
    card("r1", "rule", {blocked: "held", blocked_kind: "other"}),
  ];
  const ids = (cards) => cards.map((one) => one.id);
  const key = STORE.show;
  out.before = matchShowItems();
  matchView.cards = deck;
  out.counts = showCounts(deck);
  out.states = deck.map(showState);
  const items = matchShowItems();
  out.items = items.map((item) => [item.label, item.hint, typeof item.checked === "function" ? item.checked() : null]);
  items.find((item) => item.label === "Ask").run();
  out.askOff = {stored: JSON.parse(storage[key]), draws, checked: items.map((item) => (item.checked ? item.checked() : null))};
  const split = showSplit(deck, matchHidden());
  out.askSplit = {shown: ids(split.shown), hidden: split.hidden, words: hiddenWords(split.hidden)};
  storage[key] = JSON.stringify(["stale", "greyed"]);
  out.stateSplit = ids(showSplit(deck, matchHidden()).shown);
  storage[key] = JSON.stringify(["ask", "bogus", 5, null]);
  out.cleaned = [...matchHidden()];
  storage[key] = JSON.stringify({ask: true});
  out.notList = [...matchHidden()];
  storage[key] = JSON.stringify(["commit", "command", "ask", "decision", "rule"]);
  const none = showSplit(deck, matchHidden());
  out.allHidden = {shown: none.shown.length, hidden: none.hidden, words: allHiddenWords(none.hidden), one: allHiddenWords(1)};
  const drawn = draws;
  matchShowItems().find((item) => item.label === "Show all").run();
  out.showAll = {stored: JSON.parse(storage[key]), hidden: [...matchHidden()], drew: draws - drawn};
  storage[key] = JSON.stringify(["ask"]);
  matchView.decisions.set("ask:a1", {verdict: "accept", feedback: "", label: "", hash: "h-a1", card: deck[3], risk: false});
  const kept = showSplit(deck, matchHidden());
  const picked = decided(deck);
  const plan = releasePlan(picked);
  out.decidedHidden = {open: ids(kept.open).includes("ask:a1"), hidden: kept.hidden, onRelease: picked.map(([one]) => one.id), rest: plan.rest.map(([one]) => one.id)};
  out.counted = showCounts(kept.open).ask;
  const inside = {closest: (selector) => (selector === CTX_MATCH ? {} : null)};
  const outside = {closest: () => null};
  out.sections = {inside: ctxSections(inside).map((section) => [section.scope, section.title, section.items.length]), outside: ctxSections(outside).map((section) => section.scope)};
  const show = ctxSections(inside)[0].items;
  const nodes = show.map(ctxItem);
  out.nodes = nodes.map((node) => [node.attrs.role, node.attrs["aria-checked"] === undefined ? null : node.attrs["aria-checked"]]);
  const closed = closes;
  ctxRun(show.find((item) => item.label === "Commit"));
  out.ticked = {closes: closes - closed, commit: nodes[0].attrs["aria-checked"], ask: nodes[2].attrs["aria-checked"], stored: JSON.parse(storage[key])};
  ctxRun(show.find((item) => item.label === "Show all"));
  out.closedOnShowAll = closes - closed;
`, sandbox);
console.log(JSON.stringify(sandbox.out));
"""


def extracted(path: Path, names: tuple[str, ...]) -> str:
    source = path.read_text(encoding="utf-8")
    parts = []
    for name in names:
        found = re.search(rf"^  const {name} = [^\n]*;$", source, re.MULTILINE) or re.search(rf"^  (?:function {name}\(|const {name} = ).*?^  }};?$", source, re.MULTILINE | re.DOTALL)
        if found is None:
            raise AssertionError(f"{name} not found in {path}")
        parts.append(found.group(0).replace(f"const {name} = ", f"var {name} = "))
    return "\n".join(parts)


class TestMatchShowFilter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        script = f"{extracted(MATCH, MATCH_NAMES)}\n{extracted(CONTEXT, CONTEXT_NAMES)}"
        done = subprocess.run(["node", "-e", PROBE, script], capture_output=True, text=True, timeout=60, check=False)
        if done.returncode != 0:
            raise AssertionError(done.stderr[-4000:])
        cls.data = json.loads(done.stdout)

    def test_no_show_items_before_the_first_fetch(self):
        self.assertEqual(self.data["before"], [])

    def test_every_card_counts_once_for_its_kind_and_once_for_its_state(self):
        self.assertEqual(self.data["counts"], {"commit": 2, "command": 1, "ask": 3, "decision": 1, "rule": 1, "expired": 2, "stale": 1, "greyed": 3})
        self.assertEqual(self.data["states"], ["", "stale", "greyed", "", "expired", "expired", "greyed", "greyed"])

    def test_the_menu_lists_eight_ticked_checkboxes_with_their_counts_then_show_all(self):
        self.assertEqual(self.data["items"], [
            ["Commit", "2", True], ["Command", "1", True], ["Ask", "3", True], ["Decision", "1", True], ["Rule", "1", True],
            ["Expired", "2", True], ["Stale", "1", True], ["Greyed", "3", True], ["Show all", "every kind and state", None],
        ])

    def test_unticking_ask_is_remembered_and_redraws(self):
        found = self.data["askOff"]
        self.assertEqual(found["stored"], ["ask"])
        self.assertEqual(found["draws"], 1)
        self.assertEqual(found["checked"], [True, True, False, True, True, True, True, True, None])

    def test_a_hidden_kind_leaves_the_deck_and_the_head_counts_it(self):
        self.assertEqual(self.data["askSplit"], {"shown": ["commit:c1", "commit:c2", "command:m1", "decision:d1", "rule:r1"], "hidden": 3, "words": "3 hidden"})

    def test_a_hidden_state_leaves_the_deck_whatever_the_kind(self):
        self.assertEqual(self.data["stateSplit"], ["commit:c1", "ask:a1", "ask:a2", "ask:a3"])

    def test_unknown_or_malformed_stored_values_are_ignored(self):
        self.assertEqual(self.data["cleaned"], ["ask"])
        self.assertEqual(self.data["notList"], [])

    def test_with_every_card_hidden_the_empty_state_names_the_count(self):
        self.assertEqual(self.data["allHidden"], {"shown": 0, "hidden": 8, "words": "All 8 cards hidden by the Show filter", "one": "All 1 card hidden by the Show filter"})

    def test_show_all_clears_the_filter_and_redraws(self):
        self.assertEqual(self.data["showAll"], {"stored": [], "hidden": [], "drew": 1})

    def test_a_decided_card_that_gets_hidden_stays_on_the_release_card_and_releases(self):
        found = self.data["decidedHidden"]
        self.assertFalse(found["open"])
        self.assertEqual(found["hidden"], 2)
        self.assertIn("ask:a1", found["onRelease"])
        self.assertIn("ask:a1", found["rest"])
        self.assertEqual(self.data["counted"], 2)

    def test_the_show_section_follows_the_element_items_only_inside_match(self):
        self.assertEqual(self.data["sections"]["inside"], [["match-show", "Show", 9]])
        self.assertEqual(self.data["sections"]["outside"], [])

    def test_a_show_checkbox_is_a_menuitemcheckbox_and_keeps_the_menu_open(self):
        self.assertEqual(self.data["nodes"][:8], [["menuitemcheckbox", "true"]] * 2 + [["menuitemcheckbox", "false"]] + [["menuitemcheckbox", "true"]] * 5)
        self.assertEqual(self.data["nodes"][8], ["menuitem", None])
        self.assertEqual(self.data["ticked"], {"closes": 0, "commit": "false", "ask": "false", "stored": ["ask", "commit"]})
        self.assertEqual(self.data["closedOnShowAll"], 1)


if __name__ == "__main__":
    unittest.main()
