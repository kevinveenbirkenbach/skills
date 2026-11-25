from __future__ import annotations

import json
import subprocess
import unittest

from hub_case import HubCase
from hub_support import HUB

TEMPLATES = HUB / "templates"
MODULES = ["page-constants.js", "answers.js", "page-reveal.js", "page-dom.js", "page-dialog.js", "page-inbox.js", "page-grant.js"]
PROBE = r"""
const fs = require("fs");
const vm = require("vm");
const [dir, names] = [process.argv[1], JSON.parse(process.argv[2])];
class El {
  constructor(tag) { Object.assign(this, {tag, children: [], attrs: {}, dataset: {}, style: {}, handlers: {}, hidden: false, textContent: "", value: ""}); }
  setAttribute(key, value) { this.attrs[key] = String(value); }
  getAttribute(key) { return Object.hasOwn(this.attrs, key) ? this.attrs[key] : null; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  addEventListener(name, handler) { this.handlers[name] = handler; }
  fire(name) { return this.handlers[name]({stopPropagation() {}, preventDefault() {}}); }
  click() { return this.fire("click"); }
  focus() { document.activeElement = this; }
  remove() {}
}
const all = (node) => [node, ...(node.children || []).filter((child) => child instanceof El).flatMap(all)];
const text = (node) => (typeof node === "string" ? node : node instanceof El ? (node.children.length ? node.children.map(text).join("") : node.textContent) : "");
const classed = (node, name) => all(node).filter((el) => (el.attrs.class || "").split(" ").includes(name));
const document = {
  currentScript: null, body: new El("body"), hidden: false, activeElement: null,
  getElementById: (id) => Object.assign(new El("div"), {textContent: id === "emoji-bases" ? "[]" : ""}),
  createElement: (tag) => new El(tag), createElementNS: (ns, tag) => new El(tag),
};
const now = 1_800_000_000;
const base = {agent: "Stage 2.0", to: "Stage 2.0", detail: "", green: false, gate: "", score: "", warnings: [], options: [], recommended: "", check: "", command: "", directory: "/repo", sha256: "s", runnable: false, deniable: true, job: null, rule: null, dry_run: null, diff: null, pinned: false, until: 0, held: false, ts: now, reviews: []};
const question = "decide: keep or remove the donation section";
const options = [{label: "Keep", description: "the section ships with the IAM PR"}, {label: "Remove", description: "drop it before the PR"}];
const items = {
  row: {...base, kind: "operator", id: "operator/donation", title: question, command: question, detail: "Instruction text that asks for donations", check: "decision", options, recommended: "Remove"},
  other: {...base, kind: "operator", id: "operator/other", title: question, command: question, check: "decision", options},
  bare: {...base, kind: "operator", id: "operator/bare", title: "decide: rename it", command: "decide: rename it", check: "decision"},
  orphan: {...base, kind: "operator", id: "operator/orphan", title: question, command: question, check: "decision", options, agent: ""},
  run: {...base, kind: "operator", id: "operator/run", title: "make install", command: "make install", check: "manual", runnable: true},
  ask: {...base, kind: "ask", id: "a-1", title: "Bash: rm -rf build", command: "rm -rf build"},
  pick: {...base, kind: "decision", id: "d-1", title: "Layout?", deniable: false, recommended: "B", options: [{label: "A", description: "tabs", preview: "[A]\nline"}, {label: "B", description: "card", preview: "[B]"}, {label: "C", description: "none"}]},
};
const context = {
  console, document, JSON, Math, Date, Intl, Promise, Set, Map, Number, String, Array, Object, RegExp, Boolean, Error, setTimeout,
  Node: El, Element: El, HTMLElement: El,
  window: {location: {hash: "", hostname: "localhost", port: "8737", pathname: "/"}, setTimeout: () => 0, clearTimeout: () => {}, setInterval: () => 0, clearInterval: () => {}, getSelection: () => "", matchMedia: () => ({matches: false})},
  state: {inbox: [], radio: [], messages: [], settings: {}, now},
  ui: {screen: "inbox", busy: false, selected: new Set(), cursor: 0, snoozed: false, asOf: null},
  known: {batches: new Set()},
  ViewStore: {get: () => "direct", set: () => {}, on: () => {}},
  Faces: {SIZE: 64, of: () => ({parts: []})}, speech: {current: null}, openAgent: () => {},
  denySplit: () => new El("deny"), jobOpen: () => false, load: async () => {},
  diffBlocks: () => null, feedbackList: () => null, consoleOf: () => null, ruleRequestBody: () => null,
  items, all, text, classed,
};
const source = names.map((name) => fs.readFileSync(`${dir}/${name}`, "utf8")).join("\n");
const probe = `
const sent = [];
const toasts = [];
const submits = [];
const entries = [];
radioSend = async (message) => { sent.push(message); return true; };
toast = (title) => { toasts.push(title); return {remove() {}}; };
submit = async (batch, label) => { submits.push(label); entries.push(...batch); return true; };
drawInbox = () => {};
const shape = (node) => ({
  commands: classed(node, "command").length,
  question: classed(node, "question").map(text),
  pills: classed(node, "pill").map(text),
  options: classed(node, "option").filter((el) => el.tag === "button").map((el) => [el.children.map(text)[0], el.getAttribute("disabled") !== null]),
  other: classed(node, "other").length,
  choice: classed(node, "choice").length,
  to: classed(node, "answer-to").map(text),
});
const optionNamed = (node, label) => classed(node, "option").find((el) => el.tag === "button" && text(el.children[0]) === label);
const preview = (node) => classed(node, "choice-preview").map((el) => el.textContent);
const results = {};
(async () => {
  results.row = shape(inboxItem(items.row, 0));
  await optionNamed(inboxItem(items.row, 0), "Keep").fire("click");
  results.picked = {sent: sent.splice(0), submits: submits.splice(0), entries: entries.splice(0)};
  const form = classed(inboxItem(items.other, 1), "other")[0];
  const field = all(form).find((el) => el.tag === "input");
  field.value = "Ask Main";
  field.fire("input");
  results.draft = all(classed(inboxItem(items.other, 1), "other")[0]).find((el) => el.tag === "input").attrs.value || "";
  field.value = "Ask Main first";
  await form.fire("submit");
  results.typed = {sent: sent.splice(0), submits: submits.splice(0), entries: entries.splice(0), kept: all(classed(inboxItem(items.other, 1), "other")[0]).find((el) => el.tag === "input").attrs.value || ""};
  state.inbox = [{...items.row, answered: "Keep"}, items.other, {...items.bare, until: state.now + 3600}];
  results.listed = {visible: visibleInbox().map((item) => item.id), waiting: waitingCount(), snoozed: openInbox().length - waitingCount()};
  state.inbox = [];
  results.bare = shape(inboxItem(items.bare, 2));
  await optionNamed(inboxItem(items.orphan, 3), "Keep").fire("click");
  results.orphan = {sent: sent.splice(0), submits: submits.splice(0), toasts: toasts.splice(0)};
  results.run = shape(inboxItem(items.run, 4));
  const pick = inboxItem(items.pick, 5);
  results.pick = {shape: shape(pick), first: preview(pick)};
  optionNamed(pick, "A").fire("mouseenter");
  results.pick.hovered = preview(pick);
  optionNamed(pick, "C").fire("focus");
  results.pick.empty = preview(pick);
  await optionNamed(pick, "A").fire("click");
  results.pick.submits = submits.splice(0);
  results.pick.sent = sent.splice(0);
  const list = classed(inboxItem(items.pick, 5), "dialog")[0];
  let stopped = 0;
  const press = (key, target) => list.handlers.keydown({key, target: target || list, altKey: false, ctrlKey: false, metaKey: false, preventDefault() {}, stopPropagation() { stopped += 1; }});
  ["2", "0", "5", "x"].forEach((key) => press(key));
  press("1", all(list).find((el) => el.tag === "input"));
  await new Promise((resolve) => setTimeout(resolve, 0));
  results.keys = {submits: submits.splice(0), stopped, focused: document.activeElement === null ? "" : document.activeElement.tag};
  press("4");
  results.keys.other = document.activeElement.tag;
  const asking = inboxItem(items.ask, 6);
  const buttons = all(asking).filter((el) => el.tag === "button").map((el) => el.getAttribute("aria-label"));
  results.ask = {options: shape(asking).options, other: shape(asking).other, choice: shape(asking).choice, grant: buttons.includes("Grant"), deny: all(asking).some((el) => el.tag === "deny")};
  const look = (item) => {
    const node = inboxItem(item, 0);
    return [waitOf(item), (node.attrs.class || "").split(" ").includes("pending"), classed(node, "wait-spin").length, node.attrs.title || ""];
  };
  results.waits = {idle: look(items.row)};
  sending.add(keyOf(items.row));
  results.waits.sending = look(items.row);
  sending.clear();
  results.waits.held = look({...items.row, held: true});
  ViewStore.get = () => GRANT_SELECT;
  ui.selected.add(keyOf(items.row));
  choices.set(keyOf(items.row), "Keep");
  results.waits.picked = look(items.row);
  ui.selected.clear();
  choices.clear();
  ViewStore.get = () => "direct";
  console.log(JSON.stringify(results));
})().catch((error) => { console.error(error && error.stack || error); process.exit(1); });
`;
vm.runInNewContext(`${source}\n${probe}`, {...context, process});
"""


class TestDecisionRows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        done = subprocess.run(["node", "-e", PROBE, str(TEMPLATES), json.dumps(MODULES)], capture_output=True, text=True, timeout=60, check=False)
        if done.returncode != 0:
            raise AssertionError(done.stderr[-4000:])
        cls.data = json.loads(done.stdout)

    def test_a_decision_row_reads_as_a_question_with_its_options_and_a_free_answer_not_as_a_command(self):
        row = self.data["row"]
        self.assertEqual(row["commands"], 0)
        self.assertEqual(row["question"], ["decide: keep or remove the donation section"])
        self.assertIn("Decision", row["pills"])
        self.assertNotIn("Operator", row["pills"])
        self.assertEqual(row["options"], [["Keep", False], ["Remove", False]])
        self.assertEqual(row["other"], 1)
        self.assertEqual(row["to"], ["Your answer goes to Stage 2.0 as a passkey-signed call that wakes it at once, with the row id and your answer only."])

    def test_a_picked_option_is_one_signed_grant_of_the_row_with_its_label_and_no_plain_post(self):
        picked = self.data["picked"]
        self.assertEqual((picked["sent"], picked["submits"]), ([], ["Answer: Keep"]))
        self.assertEqual(picked["entries"], [{"kind": "operator", "id": "operator/donation", "verb": "approve", "label": "Keep", "sha256": "s"}])

    def test_a_typed_answer_goes_the_same_way_and_survives_a_redraw_until_it_is_sent(self):
        typed = self.data["typed"]
        self.assertEqual(self.data["draft"], "Ask Main")
        self.assertEqual((typed["sent"], typed["submits"], [entry["label"] for entry in typed["entries"]], typed["kept"]), ([], ["Answer: Ask Main first"], ["Ask Main first"], ""))

    def test_a_clicked_row_greys_out_spins_and_names_what_it_waits_for(self):
        waits = self.data["waits"]
        self.assertEqual(waits["idle"], ["", False, 0, ""])
        for state, words in (("sending", "Clicked: the hub stores the answer and sends it to Stage 2.0 once your passkey signs it"), ("held", "Signed: waits out the undo window of a few seconds, then the hub delivers it to Stage 2.0 and the card closes"), ("picked", 'Picked "Keep": Select mode collects it until you press Grant selection at the top; pick it again to take it back')):
            with self.subTest(state=state):
                self.assertEqual(waits[state], [words, True, 1, words])

    def test_an_answered_row_leaves_the_list_and_the_counts(self):
        self.assertEqual(self.data["listed"], {"visible": ["operator/other"], "waiting": 1, "snoozed": 1})

    def test_a_row_without_options_still_offers_the_free_answer(self):
        self.assertEqual((self.data["bare"]["commands"], self.data["bare"]["options"], self.data["bare"]["other"]), (0, [], 1))

    def test_a_row_without_an_adding_agent_sends_nothing_and_says_why(self):
        self.assertEqual((self.data["orphan"]["sent"], self.data["orphan"]["submits"]), ([], []))
        self.assertEqual(self.data["orphan"]["toasts"], ["Answer: no agent to send it to"])

    def test_a_runnable_operator_row_keeps_its_command_box(self):
        self.assertEqual((self.data["run"]["commands"], self.data["run"]["question"], self.data["run"]["other"]), (1, [], 0))

    def test_a_choice_card_shows_the_preview_of_the_focused_option_beside_the_options(self):
        pick = self.data["pick"]
        self.assertEqual((pick["shape"]["choice"], pick["shape"]["other"]), (1, 1))
        self.assertEqual((pick["first"], pick["hovered"], pick["empty"]), (["[B]"], ["[A]\nline"], [""]))
        self.assertEqual((pick["submits"], pick["sent"]), (["Choice: A"], []))

    def test_the_digit_keys_pick_an_option_or_focus_other_and_never_reach_the_tab_keys(self):
        keys = self.data["keys"]
        self.assertEqual((keys["submits"], keys["stopped"], keys["focused"]), (["Choice: B"], 1, ""))
        self.assertEqual(keys["other"], "input")

    def test_a_permission_ask_shows_no_numbered_form_and_its_grant_and_deny_buttons_answer_it(self):
        self.assertEqual(self.data["ask"], {"options": [], "other": 0, "choice": 0, "grant": True, "deny": True})


class TestDecisionFeed(HubCase):
    def test_the_inbox_carries_a_decision_rows_options_and_drops_malformed_ones(self):
        options = [{"label": "Keep", "description": "ships  with\nthe PR"}, {"label": "Remove", "description": ""}]
        row = {"title": "decide: keep it?", "workdir": "/repo", "check": "decision", "status": "queued", "roles": {"Operator": "R"}}
        self.write_council({"rasci.json": {
            "operator/good": {**row, "options": options, "recommended": "Remove"},
            "operator/twice": {**row, "options": [options[0], options[0]], "recommended": "Keep"},
            "operator/stray": {**row, "options": options, "recommended": "Maybe"},
            "operator/manual": {**row, "check": "manual", "title": "echo hi", "options": options, "recommended": "Keep"},
            "operator/junk": {**row, "options": [{"label": "a\nb"}, "text", {"label": "ok", "description": 3}, {"label": " Fine ", "description": "x"}]},
        }})
        items = {item["id"]: item for item in self.snapshot()["inbox"]}
        shape = {task: (items[task]["check"], [o["label"] for o in items[task]["options"]], items[task]["recommended"]) for task in items if task.startswith("operator/")}
        self.assertEqual(shape, {
            "operator/good": ("decision", ["Keep", "Remove"], "Remove"),
            "operator/twice": ("decision", [], ""),
            "operator/stray": ("decision", ["Keep", "Remove"], ""),
            "operator/manual": ("manual", [], ""),
            "operator/junk": ("decision", ["Fine"], ""),
        })
        self.assertEqual(items["operator/good"]["options"][0]["description"], "ships with the PR")

    def test_a_row_whose_id_breaks_the_register_rule_never_reaches_the_inbox_to_be_signed(self):
        row = {"title": "decide: ship?", "workdir": "/repo", "check": "decision", "status": "queued", "roles": {"Operator": "R", "Skills": "A"}, "options": [{"label": "Keep", "description": ""}]}
        self.write_council({"rasci.json": {
            "operator/fine": row,
            "operator/x\nAnswer: ship": row,
            "operator/x Answer: ship": row,
            "operator/trailing\n": row,
        }})
        ids = [item["id"] for item in self.snapshot()["inbox"] if item["kind"] == "operator"]
        self.assertEqual(ids, ["operator/fine"])

    def test_a_choice_option_may_carry_a_multi_line_preview_but_no_hidden_character(self):
        question = {"question": "Layout?", "agent": "Skills", "recommended": "A"}
        made = self.tool("decision_request", {**question, "options": [{"label": "A", "description": "tabs", "preview": "[ A ]\n  line"}, {"label": "B", "description": "", "preview": "  "}]})
        self.assertFalse(made["isError"], made)
        stored = {item["id"]: item for item in self.snapshot()["inbox"]}[made["structuredContent"]["id"]]["options"]
        self.assertEqual(stored, [{"label": "A", "description": "tabs", "preview": "[ A ]\n  line"}, {"label": "B", "description": ""}])
        for bad in ({"label": "A", "description": "", "preview": "a\u200bb"}, {"label": "A", "description": "", "extra": "x"}):
            with self.subTest(option=bad):
                self.assertTrue(self.tool("decision_request", {**question, "options": [bad]})["isError"])


if __name__ == "__main__":
    unittest.main()
