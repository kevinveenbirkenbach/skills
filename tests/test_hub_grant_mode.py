from __future__ import annotations

import json
import subprocess
import unittest

from hub_support import HUB

TEMPLATES = HUB / "templates"
MODULES = ["page-constants.js", "page-reveal.js", "page-dom.js", "page-dialog.js", "page-inbox.js", "page-grant.js"]
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
  click() { return this.handlers.click({stopPropagation() {}, preventDefault() {}}); }
  focus() {}
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
const base = {agent: "Store", to: "Store", detail: "", green: false, gate: "", score: "", warnings: [], options: [], recommended: "", command: "", directory: "/repo", sha256: "s", runnable: false, deniable: false, job: null, rule: null, dry_run: null, diff: null, pinned: false, until: 0, held: false, ts: now, reviews: []};
const items = {
  green: {...base, kind: "review", id: "r-green", title: "feat: green", gate: "pass", green: true},
  red: {...base, kind: "review", id: "r-red", title: "feat: red", gate: "fail"},
  ask: {...base, kind: "ask", id: "a-1", title: "git push: ask", command: "git push"},
  run: {...base, kind: "operator", id: "operator/run", title: "make install", command: "make install", runnable: true, deniable: true},
  pick: {...base, kind: "decision", id: "d-1", title: "Which?", recommended: "A", options: [{label: "A", description: ""}, {label: "B", description: ""}]},
  rule: {...base, kind: "rule", id: "1123456789abcdef", title: "Rule ask Bash make deploy"},
  open: {...base, kind: "decision", id: "d-2", title: "Open?", options: [{label: "A", description: ""}, {label: "B", description: ""}]},
  row: {...base, kind: "operator", id: "operator/ask", title: "Ship it?", command: "Ship it?", check: "decision", deniable: true, options: [{label: "Yes", description: ""}]},
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
  base, items, mode, sets, listeners, all, text, buttons,
};
const source = names.map((name) => fs.readFileSync(`${dir}/${name}`, "utf8")).join("\n");
const probe = `
const proofs = [];
const sent = [];
const accepts = [];
const sheets = [];
let renders = 0;
let streams = 0;
let signing = false;
proofFor = async (entries) => { proofs.push(entries.map((entry) => entry.kind + ":" + entry.id)); sent.push(entries.map((entry) => entry.label)); return signing ? {proof: "p"} : null; };
sendJson = async () => ({ok: true, data: {id: \`b\${proofs.length}\`, due: 0}});
undoToast = () => {};
acceptRule = async (item) => { accepts.push(item.id); return true; };
openSheet = (title, body) => { sheets.push(body); };
closeSheet = () => {};
render = () => { renders += 1; };
drawStream = () => { streams += 1; };
toast = () => ({remove() {}});
const results = {};
const take = () => ({selected: [...ui.selected].sort(), proofs: proofs.splice(0), labels: sent.splice(0), accepts: accepts.splice(0), renders, streams});
const dialogOf = (item) => { const made = choiceOf(item, () => {}); return Array.isArray(made) ? made[1] : made; };
const option = (item, label) => buttons(dialogOf(item)).find((button) => (button.getAttribute("title") || "").startsWith(\`\${label}: \`));
const pressedOptions = (item) => buttons(dialogOf(item)).filter((button) => button.getAttribute("aria-pressed") === "true").map((button) => button.getAttribute("title").split(": ")[0]);
const press = (item) => {
  const first = actionsFor(item)[0];
  return {pressed: first.getAttribute("aria-pressed"), title: first.getAttribute("title"), disabled: Boolean(first.disabled), picked: (first.getAttribute("class") || "").split(" ").includes("picked")};
};
const labels = (node) => buttons(node).map((button) => button.getAttribute("aria-label"));
const byName = (node, label) => buttons(node).find((button) => button.getAttribute("aria-label") === label);
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
  results.solo_titles = [press(of("red")).title, press(of("rule")).title];
  await approveOne(of("red"));
  results.red = {...take(), press: press(of("red"))};
  await approveOne(of("rule"));
  results.rule = {...take(), press: press(of("rule"))};
  await approveOne(of("red"));
  await approveOne(of("rule"));
  results.solo_out = take();
  grantBoot();
  const bar = grantView.tray;
  const summary = () => all(bar).find((node) => node.tag === "summary").getAttribute("aria-label");
  results.tray = {summary: summary(), labels: labels(bar), main: buttons(bar)[0].getAttribute("aria-label"), listen: listeners.map(([path]) => path)};
  byName(bar, "Remove make install").click();
  results.unpicked = take();
  byName(bar, "Clear").click();
  results.cleared = take();
  byName(bar, "Direct").click();
  results.switched = sets.splice(0);
  drawGrant();
  results.direct_tray = {summary: summary(), labels: labels(bar), main: buttons(bar)[0].getAttribute("id")};
  results.direct_press = press(of("green"));
  await approveOne(of("green"));
  results.direct = take();
  ui.selected.add(keyOf(of("run")));
  results.direct_picked = press(of("run"));
  drawGrant();
  results.direct_selection = {main: buttons(bar)[0].getAttribute("aria-label"), labels: labels(bar)};
  ui.selected.clear();
  results.direct_pick = {before: take()};
  await option(of("open"), "B").click();
  results.direct_pick.after = take();
  mode.value = "select";
  await option(of("open"), "B").click();
  results.option_added = {...take(), pressed: pressedOptions(of("open"))};
  await option(of("open"), "B").click();
  results.option_removed = {...take(), pressed: pressedOptions(of("open"))};
  await option(of("open"), "B").click();
  await option(of("pick"), "B").click();
  await option(of("row"), "Yes").click();
  results.option_row = {pressed: pressedOptions(of("row")), batchable: batchable(of("row"))};
  await approveOne(of("green"));
  await approveOne(of("red"));
  await approveOne(of("rule"));
  results.all = take();
  const actions = selectionActions(state.inbox);
  results.all_grant = actions.grant.getAttribute("aria-label");
  await actions.grant.click();
  const sheet = sheets.splice(0)[0];
  results.all_note = text(sheet[0]);
  signing = true;
  await buttons(sheet[2]).find((button) => text(button).startsWith("Grant ")).click();
  results.all_granted = take();
  const commit = {...base, kind: "operator", id: "operator/commit", title: "git commit", command: "git commit", runnable: true, deniable: true, reviews: [{id: "r-green", status: "pending", gate: "pass"}, {id: "r-red", status: "pending", gate: "fail"}, {id: "r-old", status: "approved", gate: "pass"}]};
  state.inbox = [...Object.values(items).map((item) => ({...item})), commit];
  const runOf = (row) => actionsFor(row)[0];
  results.run_label = runOf(commit).getAttribute("aria-label");
  await runOf(commit).click();
  results.run_collected = {...take(), sheets: sheets.splice(0).length};
  ui.selected.clear();
  mode.value = "direct";
  await runOf(commit).click();
  const runSheet = sheets.splice(0)[0];
  results.run_note = text(runSheet[0]);
  await buttons(runSheet[2]).find((button) => text(button).startsWith("Grant ")).click();
  results.run_granted = take();
  results.run_stuck = runOf({...commit, reviews: [{id: "r-gone", status: "rejected", gate: "pass"}]}).getAttribute("disabled");
  results.run_plain = runOf({...commit, reviews: [{id: "r-old", status: "approved", gate: "pass"}]}).getAttribute("aria-label");
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

    def test_a_picked_item_shows_a_pale_green_disabled_grant_button(self):
        self.assertEqual(self.data["unpressed"]["pressed"], "false")
        self.assertTrue(self.data["unpressed"]["title"].startswith("Select: "), self.data["unpressed"])
        self.assertEqual((self.data["unpressed"]["disabled"], self.data["unpressed"]["picked"]), (False, False))
        pressed = self.data["pressed"]
        self.assertEqual((pressed["pressed"], pressed["disabled"], pressed["picked"]), ("true", True, True))
        self.assertEqual(pressed["title"], "In the selection: take it out with ✕ in the Grant menu")

    def test_a_checkbox_pick_in_direct_also_turns_the_button_pale_and_opens_the_grant_split(self):
        picked = self.data["direct_picked"]
        self.assertEqual((picked["pressed"], picked["disabled"], picked["picked"]), (None, True, True))
        self.assertEqual(self.data["direct_selection"]["main"], "Grant selection (1)")
        self.assertEqual(self.data["direct_selection"]["labels"][-1], "Select")

    def test_a_red_gate_and_a_rule_collect_in_select_and_say_they_sign_alone(self):
        self.assertEqual(self.data["solo_titles"], ["Select: press to add it to the selection; Grant asks its own passkey signature for it"] * 2)
        self.assertIn("review:r-red", self.data["red"]["selected"])
        self.assertEqual((self.data["red"]["proofs"], self.data["red"]["press"]["pressed"]), ([], "true"))
        self.assertIn("rule:1123456789abcdef", self.data["rule"]["selected"])
        self.assertEqual((self.data["rule"]["proofs"], self.data["rule"]["accepts"], self.data["rule"]["press"]["pressed"]), ([], [], "true"))
        self.assertEqual(self.data["solo_out"]["selected"], ["ask:a-1", "decision:d-1", "operator:operator/run", "review:r-green"])

    def test_an_option_pick_posts_at_once_in_direct(self):
        self.assertEqual((self.data["direct_pick"]["after"]["proofs"], self.data["direct_pick"]["after"]["labels"]), ([["decision:d-2"]], [["B"]]))
        self.assertEqual(self.data["direct_pick"]["after"]["selected"], [])

    def test_an_option_pick_collects_with_its_label_in_select_and_the_same_pick_takes_it_out(self):
        self.assertEqual(self.data["option_added"]["selected"], ["decision:d-2"])
        self.assertEqual((self.data["option_added"]["proofs"], self.data["option_added"]["pressed"]), ([], ["B"]))
        self.assertEqual((self.data["option_removed"]["selected"], self.data["option_removed"]["pressed"]), ([], []))
        self.assertEqual(self.data["option_row"], {"pressed": ["Yes"], "batchable": True})

    def test_grant_n_signs_each_rule_and_red_gate_alone_first_then_the_batch_once(self):
        self.assertEqual(self.data["all"]["selected"], ["decision:d-1", "decision:d-2", "operator:operator/ask", "review:r-green", "review:r-red", "rule:1123456789abcdef"])
        self.assertEqual((self.data["all"]["proofs"], self.data["all"]["accepts"]), ([], []))
        self.assertEqual(self.data["all_grant"], "Grant selection (6)")
        self.assertIn("Each rule and each red-gate review first asks its own signature, one after the other (2). Then the passkey signs the rest once", self.data["all_note"])
        granted = self.data["all_granted"]
        self.assertEqual(granted["proofs"], [["review:r-red"], ["review:r-green", "decision:d-1", "decision:d-2", "operator:operator/ask"]])
        self.assertEqual(granted["labels"], [[""], ["", "B", "B", "Yes"]])
        self.assertEqual((granted["accepts"], granted["selected"]), (["1123456789abcdef"], []))

    def test_a_commit_row_approves_the_reviews_it_verifies_before_it_runs(self):
        self.assertEqual(self.data["run_label"], "Approve 2 and run")
        self.assertEqual(self.data["run_collected"]["selected"], ["operator:operator/commit"])
        self.assertEqual((self.data["run_collected"]["proofs"], self.data["run_collected"]["sheets"]), ([], 0))
        self.assertIn("first asks its own signature, one after the other (1). Then the passkey signs the rest once, commit rows settling after the reviews they verify.", self.data["run_note"])
        self.assertEqual(self.data["run_granted"]["proofs"], [["review:r-red"], ["review:r-green", "operator:operator/commit"]])
        self.assertEqual((self.data["run_stuck"], self.data["run_plain"]), ("", "Run"))

    def test_one_split_grants_the_selection_and_its_menu_holds_the_rest(self):
        tray = self.data["tray"]
        self.assertEqual(tray["main"], "Grant selection (4)")
        self.assertEqual(tray["summary"], "4 selected")
        self.assertEqual(tray["labels"], [
            "Grant selection (4)", "Deny selection (2)", "Grant all green (1)",
            "Remove feat: green", "Remove git push: ask", "Remove make install", "Remove Which?",
            "Clear", "Direct",
        ])
        self.assertEqual(tray["listen"], ["approval"])

    def test_a_picked_item_leaves_the_selection_through_its_menu_entry(self):
        self.assertEqual(self.data["unpicked"]["selected"], ["ask:a-1", "decision:d-1", "review:r-green"])
        self.assertEqual(self.data["unpicked"]["proofs"], [])

    def test_clear_empties_the_selection(self):
        self.assertEqual(self.data["cleared"]["selected"], [])

    def test_the_switch_stores_the_mode_in_the_view_store(self):
        self.assertEqual(self.data["switched"], [["approval.mode", "direct"]])

    def test_direct_without_a_pick_shows_select_and_grants_at_once(self):
        self.assertEqual(self.data["direct_tray"], {"summary": "0 selected", "labels": ["Select", "Deny selection (0)", "Grant all green (1)", "Clear"], "main": "grant-select"})
        self.assertEqual(self.data["direct_press"]["pressed"], None)
        self.assertEqual(self.data["direct_press"]["title"], "Grant")
        self.assertEqual(self.data["direct"]["proofs"], [["review:r-green"]])
        self.assertEqual(self.data["direct"]["selected"], [])


if __name__ == "__main__":
    unittest.main()
