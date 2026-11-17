from __future__ import annotations

import json
import subprocess
import unittest

from hub_support import HUB

TEMPLATES = HUB / "templates"
MODULES = ["page-constants.js", "page-reveal.js", "page-dom.js", "page-inbox.js", "page-grant.js"]
PROBE = r"""
const fs = require("fs");
const vm = require("vm");
const [dir, names] = [process.argv[1], JSON.parse(process.argv[2])];
class El {
  constructor(tag) { Object.assign(this, {tag, children: [], attrs: {}, dataset: {}, style: {}, handlers: {}, hidden: false, textContent: ""}); }
  setAttribute(key, value) {
    this.attrs[key] = String(value);
    if (key.startsWith("data-")) {
      this.dataset[key.slice(5).replace(/-([a-z])/g, (_, letter) => letter.toUpperCase())] = String(value);
    }
  }
  getAttribute(key) { return Object.hasOwn(this.attrs, key) ? this.attrs[key] : null; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  addEventListener(name, handler) { this.handlers[name] = handler; }
  click() { this.handlers.click({stopPropagation() {}, preventDefault() {}}); }
  remove() {}
}
const all = (node) => [node, ...(node.children || []).filter((child) => child instanceof El).flatMap(all)];
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));
const buttons = (node) => all(node).filter((el) => el.tag === "button");
const document = {
  currentScript: null, body: new El("body"), hidden: false, activeElement: null,
  getElementById: (id) => Object.assign(new El("div"), {textContent: id === "emoji-bases" ? "[]" : ""}),
  createElement: (tag) => new El(tag), createElementNS: (ns, tag) => new El(tag),
};
const now = 1_800_000_000;
const base = {agent: "Store", to: "Store", detail: "", green: false, gate: "", score: "", warnings: [], options: [], recommended: "", command: "", directory: "/repo", sha256: "s", runnable: false, deniable: false, job: null, rule: null, dry_run: null, diff: null, pinned: false, until: 0, held: false, ts: now};
const items = {
  green: {...base, kind: "review", id: "r-green", title: "feat: green", gate: "pass", green: true},
  red: {...base, kind: "review", id: "r-red", title: "feat: red", gate: "fail"},
  ask: {...base, kind: "ask", id: "a-1", title: "git push: ask", command: "git push"},
  run: {...base, kind: "operator", id: "operator/run", title: "make install", command: "make install", runnable: true, deniable: true},
  pick: {...base, kind: "decision", id: "d-1", title: "Which?", recommended: "A", options: [{label: "A", description: ""}]},
  rule: {...base, kind: "rule", id: "1123456789abcdef", title: "Rule ask Bash make deploy"},
};
const mode = {value: "select"};
const sets = [];
const listeners = [];
const context = {
  console, document, JSON, Math, Date, Intl, Promise, Set, Map, Number, String, Array, Object, RegExp, Boolean, Error, setTimeout,
  Node: El, Element: El, HTMLElement: El,
  window: {location: {hash: "", hostname: "localhost", port: "8737", pathname: "/"}, setTimeout: () => 0, clearTimeout: () => {}, setInterval: () => 0, clearInterval: () => {}, getSelection: () => "", matchMedia: () => ({matches: false})},
  state: {inbox: [], radio: [], messages: [], settings: {}, now},
  ui: {screen: "inbox", busy: false, selected: new Set(), cursor: 0, snoozed: false, asOf: null},
  known: {batches: new Set()},
  ViewStore: {get: (path) => (path === "approval.mode" ? mode.value : null), set: (path, value) => { sets.push([path, value]); mode.value = value; }, on: (path, callback) => listeners.push([path, callback])},
  denySplit: () => new El("deny"), jobOpen: () => false, load: async () => {}, openItem: () => {},
  items, mode, sets, listeners, all, text, buttons,
};
const source = names.map((name) => fs.readFileSync(`${dir}/${name}`, "utf8")).join("\n");
const probe = `
const proofs = [];
const accepts = [];
let renders = 0;
let streams = 0;
proofFor = async (entries) => { proofs.push(entries.map((entry) => entry.kind + ":" + entry.id)); return null; };
acceptRule = (item) => { accepts.push(item.id); };
render = () => { renders += 1; };
drawStream = () => { streams += 1; };
toast = () => ({remove() {}});
const results = {};
const take = () => ({selected: [...ui.selected].sort(), proofs: proofs.splice(0), accepts: accepts.splice(0), renders, streams});
const press = (item) => {
  const first = actionsFor(item)[0];
  return {pressed: first.getAttribute("aria-pressed"), title: first.getAttribute("title")};
};
(async () => {
  state.inbox = Object.values(items).map((item) => ({...item}));
  const of = (key) => state.inbox.find((item) => item.id === items[key].id);
  results.unpressed = press(of("green"));
  await approveOne(of("green"));
  results.added = take();
  results.pressed = press(of("green"));
  await approveOne(of("green"));
  results.removed = take();
  for (const key of ["green", "ask", "run", "pick"]) {
    await approveOne(of(key));
  }
  results.collected = take();
  await approveOne(of("red"));
  results.red = {...take(), press: press(of("red"))};
  await approveOne(of("rule"));
  results.rule = {...take(), press: press(of("rule"))};
  grantBoot();
  const bar = grantView.tray;
  const modes = grantView.modes;
  results.tray = {hidden: bar.hidden, text: text(bar), labels: buttons(bar).map((button) => button.getAttribute("aria-label")), modes: modes.map((button) => [button.dataset.mode, button.getAttribute("aria-pressed")]), listen: listeners.map(([path]) => path)};
  buttons(bar).pop().click();
  results.cleared = take();
  modes[0].click();
  results.switched = sets.splice(0);
  drawGrant();
  results.direct_tray = {hidden: bar.hidden, children: bar.children.length, modes: modes.map((button) => button.getAttribute("aria-pressed"))};
  results.direct_press = press(of("green"));
  await approveOne(of("green"));
  results.direct = take();
  console.log(JSON.stringify(results));
})().catch((error) => { console.error(error && error.stack || error); process.exit(1); });
`;
vm.runInNewContext(`${source}\n${probe}`, {...context, process});
"""


class TestGrantMode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        done = subprocess.run(["node", "-e", PROBE, str(TEMPLATES), json.dumps(MODULES)], capture_output=True, text=True, timeout=60, check=False)
        if done.returncode != 0:
            raise AssertionError(done.stderr[-4000:])
        cls.data = json.loads(done.stdout)

    def test_a_grant_in_select_toggles_the_selection_without_a_signature(self):
        self.assertEqual(self.data["added"]["selected"], ["review:r-green"])
        self.assertEqual(self.data["added"]["proofs"], [])
        self.assertEqual((self.data["added"]["renders"], self.data["added"]["streams"]), (1, 1))
        self.assertEqual(self.data["removed"]["selected"], [])
        self.assertEqual(self.data["removed"]["proofs"], [])

    def test_every_selectable_kind_collects_in_select(self):
        self.assertEqual(self.data["collected"]["selected"], ["ask:a-1", "decision:d-1", "operator:operator/run", "review:r-green"])
        self.assertEqual(self.data["collected"]["proofs"], [])

    def test_the_grant_button_shows_whether_its_item_is_selected(self):
        self.assertEqual(self.data["unpressed"]["pressed"], "false")
        self.assertTrue(self.data["unpressed"]["title"].startswith("Select: "), self.data["unpressed"])
        self.assertEqual(self.data["pressed"]["pressed"], "true")

    def test_a_red_gate_and_a_rule_stay_direct_in_select_and_say_why(self):
        self.assertEqual(self.data["red"]["proofs"], [["review:r-red"]])
        self.assertEqual(self.data["red"]["press"]["pressed"], None)
        self.assertEqual(self.data["red"]["press"]["title"], "Grant: acts at once, a red gate is never granted in a selection")
        self.assertEqual(self.data["rule"]["accepts"], ["1123456789abcdef"])
        self.assertEqual(self.data["rule"]["proofs"], [])
        self.assertTrue(self.data["rule"]["press"]["title"].endswith(": acts at once, a rule is accepted one at a time"), self.data["rule"])

    def test_the_tray_counts_the_selection_and_holds_its_actions(self):
        tray = self.data["tray"]
        self.assertFalse(tray["hidden"])
        self.assertTrue(tray["text"].startswith("4 selected"), tray)
        self.assertEqual(tray["labels"], ["Grant selection (4)", "Deny selection (2)", "Grant all green (1)", "Clear"])
        self.assertEqual(tray["modes"], [["direct", "false"], ["select", "true"]])
        self.assertEqual(tray["listen"], ["approval"])

    def test_clear_empties_the_selection(self):
        self.assertEqual(self.data["cleared"]["selected"], [])

    def test_the_switch_stores_the_mode_in_the_view_store(self):
        self.assertEqual(self.data["switched"], [["approval.mode", "direct"]])

    def test_direct_hides_the_tray_and_grants_at_once(self):
        self.assertEqual(self.data["direct_tray"], {"hidden": True, "children": 0, "modes": ["true", "false"]})
        self.assertEqual(self.data["direct_press"]["pressed"], None)
        self.assertEqual(self.data["direct_press"]["title"], "Grant")
        self.assertEqual(self.data["direct"]["proofs"], [["review:r-green"]])
        self.assertEqual(self.data["direct"]["selected"], [])


if __name__ == "__main__":
    unittest.main()
