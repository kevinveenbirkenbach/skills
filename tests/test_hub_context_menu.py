from __future__ import annotations

import json
import subprocess
import unittest

from hub_support import HUB

TEMPLATES = HUB / "templates"
SOURCES = ["page-constants.js", "page-diff.js", "page-palette.js", "page-context.js"]
GENERAL = [
    "View: Home", "View: Stream", "View: Agents", "View: Artifacts", "View: Tasks", "View: Resources", "Radio …", "Cancel mayday", "Drain", "Suspend", "Resume",
    "Settings …", "Music on", "Look at the sky", "Toggle control room", "Enable notifications", "Keyboard shortcuts",
]
TASKS_TAB = ["Tasks: List", "Tasks: Board", "Tasks: RASCI", "Tasks: Gantt", "Tasks: Burndown and burnup", "Tasks: 3D"]
AGENTS_TAB = ["Agents: Orbit", "Agents: Chord", "Agents: Swimlane", "Agents: Tree", "Agents: 3D", "Agents: Hierarchy", "Priority …"]
TABS = ["home", "stream", "agents", "artifacts", "tasks", "resources"]
PROBE = r"""
const fs = require("fs");
const vm = require("vm");
const [dir, names] = [process.argv[1], JSON.parse(process.argv[2])];
const Nav = require(`${dir}/nav.js`);
const Panels = require(`${dir}/panels.js`);
class Element {
  constructor(tag, attrs, parent) {
    Object.assign(this, {tagName: tag.toUpperCase(), attrs: {...attrs}, parentElement: parent || null, rect: null});
  }
  getAttribute(name) { return Object.hasOwn(this.attrs, name) ? this.attrs[name] : null; }
  hasAttribute(name) { return Object.hasOwn(this.attrs, name); }
  matches(selector) {
    return selector.split(",").map((part) => /^([\w-]*)(?:\[([\w-]+)\])?$/.exec(part.trim())).some((found) => Boolean(found) && (!found[1] || this.tagName === found[1].toUpperCase()) && (!found[2] || this.hasAttribute(found[2])));
  }
  get dataset() { return Object.fromEntries(Object.entries(this.attrs).filter(([name]) => name.startsWith("data-")).map(([name, value]) => [name.slice(5), value])); }
  get classList() { return {contains: (name) => String(this.attrs.class || "").split(" ").includes(name)}; }
  closest(selector) { return this.matches(selector) ? this : this.parentElement && this.parentElement.closest(selector); }
  contains(node) { return Boolean(node) && (node === this || this.contains(node.parentElement)); }
  getBoundingClientRect() { return this.rect; }
}
Panels.item("task", (id) => `Task ${id}`, () => null);
const KEYS_OF = {Stage: "s2", Docs: "s3"};
const NAMES = {s2: "Stage", s3: "Docs"};
const calls = {tasks: [], pins: [], feedback: [], shown: [], closed: 0};
const context = {
  console, Nav, Panels, Element, JSON, Math, Object, Array, String, Number, Boolean, Promise, Map, Set, Intl,
  document: {activeElement: null, currentScript: null}, window: {innerWidth: 1366, innerHeight: 768, matchMedia: () => ({matches: false})}, navigator: {},
  state: {views: {"fuer-dich": {label: "For you"}}, tasks: [{task: "work/feature"}], inbox: [{kind: "review", id: "r1", title: "feat: x"}], graph: {nodes: []}},
  ui: {screen: "tasks"}, tree: {model: null}, settings: {music: {on: false}}, space: {look: false}, userViews: [{name: "Mine"}],
  palette: {plan: null, input: {value: ""}, index: 0, items: [], list: {replaceChildren: () => {}, children: []}},
  h: (tag, attrs, ...children) => ({tag, attrs, children}), face: () => null, revealed: (text) => text,
  agentNames: () => ["Docs", "Stage"], agentKey: (who) => KEYS_OF[who] || who, nameOf: (key) => NAMES[key] || key, labelOf: (key) => NAMES[key] || key, keyOf: (item) => `${item.kind}:${item.id}`,
  go: () => {}, useView: () => {}, useSaved: () => {}, openAgent: () => {}, openRadio: () => {}, confirmAct: () => {}, openAgentOrder: () => {}, settingsSheet: () => {},
  toggleMusic: () => {}, skyLook: () => {}, toggleLeitstand: () => {}, askNotify: () => {}, helpSheet: () => {}, micFrame: (field) => field,
  taskSheet: (id) => calls.tasks.push(id), artSelect: () => {}, select: () => {}, openItem: () => {}, openSheet: () => {}, glossarySections: () => [], toast: () => {},
  homePins: () => [], homePress: (kind, id) => calls.pins.push(`${kind}:${id}`), HOME_OPENERS: {task: (id) => calls.tasks.push(`home ${id}`)},
  closeMenus: () => { calls.closed += 1; }, calls,
};
const probe = `
ctxShow = (sections, at) => calls.shown.push({at, sections: labels(sections)});
selectionFeedback = () => null;
markLines = (picked) => calls.feedback.push(picked.path + ":" + picked.from + "-" + picked.until);
const labels = (sections) => sections.map((section) => [section.scope, section.title, section.items.map((item) => item.label)]);
const out = {};
const panel = new Element("div", {"data-panel": "tasks/list"});
const card = new Element("li", {"data-task": "work/feature", "data-item": "task:work/feature"}, panel);
const inside = new Element("span", {}, card);
const taskSections = ctxSections(inside);
out.task = labels(taskSections);
taskSections[0].items.forEach((item) => item.label !== "Copy task id" && item.run());
out.ran = {tasks: calls.tasks, pins: calls.pins};
ui.screen = "agents";
out.agent = labels(ctxSections(new Element("g", {"data-face": "s2", "data-pick": "s2"})));
out.operator = labels(ctxSections(new Element("span", {"data-face": "Operator"})))[0][0];
ui.screen = "rules";
out.rules = labels(ctxSections(new Element("main", {})));
ui.screen = "tasks";
const fire = (target, extra) => {
  let prevented = false;
  const before = calls.shown.length;
  ctxContextMenu({target, clientX: 12, clientY: 34, shiftKey: false, defaultPrevented: false, ...extra, preventDefault: () => { prevented = true; }});
  const last = calls.shown.length > before ? calls.shown[calls.shown.length - 1] : null;
  return {prevented, at: last && last.at, sections: last && last.sections};
};
out.mouse = {plain: fire(inside, {}), shift: fire(inside, {shiftKey: true}), handled: fire(inside, {defaultPrevented: true}), field: fire(new Element("textarea", {}, card), {})};
out.closed = calls.closed;
const key = (target, extra) => {
  document.activeElement = target;
  let prevented = false;
  const before = calls.shown.length;
  ctxKeydown({key: "ContextMenu", shiftKey: false, ctrlKey: false, altKey: false, metaKey: false, ...extra, preventDefault: () => { prevented = true; }});
  const last = calls.shown.length > before ? calls.shown[calls.shown.length - 1] : null;
  return {prevented, at: last && last.at, element: last && last.sections[0][1]};
};
const focused = new Element("article", {"data-task": "work/feature", tabindex: "0"});
focused.rect = {left: 30, top: 40, right: 230, bottom: 90, width: 200, height: 50};
out.keys = {menu: key(focused, {}), shiftF10: key(focused, {key: "F10", shiftKey: true}), f10: key(focused, {key: "F10"}), ctrl: key(focused, {ctrlKey: true}), field: key(new Element("input", {}), {})};
ui.screen = "inbox";
const entry = new Element("li", {"data-ref": "review:r1", "data-to": "Skills"});
const file = new Element("section", {"data-path": "src/app.py"}, entry);
const cell = new Element("td", {}, file);
out.unselected = labels(ctxSections(cell))[0];
const row = new Element("tr", {"data-line": "7"}, file);
const code = new Element("td", {}, row);
out.row = fire(code, {});
ctxSections(code)[0].items[0].run();
const note = new Element("tr", {"data-line": "7", class: "match-mark"}, file);
out.note = fire(new Element("td", {}, note), {}).sections[0][2];
selectionFeedback = () => ({ref: "review:r1", to: "Skills", path: "src/app.py", from: 2, until: 3, quote: "new"});
out.selected = fire(cell, {});
ctxSections(cell)[0].items[0].run();
out.feedback = calls.feedback;
out.palette = paletteItems().map((item) => [item.label, item.scope, item.id === undefined ? null : item.id]);
drawPalette();
out.paletteShown = palette.items.length;
out.keysHelp = KEYS.map(([name]) => name);
console.log(JSON.stringify(out));
`;
const source = names.map((name) => fs.readFileSync(`${dir}/${name}`, "utf8")).join("\n");
vm.runInNewContext(`${source}\n${probe}`, context);
"""


class TestHubContextMenu(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        done = subprocess.run(["node", "-e", PROBE, str(TEMPLATES), json.dumps(SOURCES)], capture_output=True, text=True, timeout=60, check=False)
        if done.returncode != 0:
            raise AssertionError(done.stderr.strip()[:1200])
        cls.data = json.loads(done.stdout)

    def test_the_element_items_come_first_then_the_tab_then_the_general_ones(self):
        self.assertEqual(self.data["task"], [
            ["element", "Task work/feature", ["Open task", "Copy task id", "Pin to Home"]],
            ["tasks", "Tasks", TASKS_TAB],
            ["general", "General", GENERAL],
        ])

    def test_the_element_items_act_on_the_clicked_element(self):
        self.assertEqual(self.data["ran"], {"tasks": ["work/feature"], "pins": ["task:work/feature"]})

    def test_an_agent_scoped_palette_item_shows_only_on_its_own_agent(self):
        self.assertEqual(self.data["agent"], [["element", "Stage", ["Stage", "Copy name"]], ["agents", "Agents", AGENTS_TAB], ["general", "General", GENERAL]])
        self.assertEqual(self.data["operator"], "agents")

    def test_a_sub_screen_takes_the_items_of_its_tab(self):
        self.assertEqual(self.data["rules"], [["stream", "Stream", ["View: Stream › Controls", "Stream: For you", "Stream: Mine", "Controls …"]], ["general", "General", GENERAL]])

    def test_every_palette_item_has_a_scope_and_the_palette_still_lists_them_all(self):
        palette = self.data["palette"]
        self.assertLessEqual({scope for _, scope, _ in palette}, {"general", "agent", *TABS})
        self.assertEqual([[label, key] for label, scope, key in palette if scope == "agent"], [["Docs", "s3"], ["Stage", "s2"]])
        self.assertEqual([key for _, scope, key in palette if scope != "agent"], [None] * (len(palette) - 2))
        self.assertEqual([label for label, scope, _ in palette if scope == "general"], GENERAL)
        self.assertEqual(self.data["paletteShown"], len(palette))

    def test_a_right_click_opens_the_menu_at_the_pointer_and_shift_or_a_handled_event_or_a_text_field_keep_the_native_one(self):
        mouse = self.data["mouse"]
        self.assertEqual((mouse["plain"]["prevented"], mouse["plain"]["at"]), (True, {"x": 12, "y": 34}))
        self.assertEqual(mouse["plain"]["sections"], self.data["task"])
        for case in ("shift", "handled", "field"):
            with self.subTest(case=case):
                self.assertEqual(mouse[case], {"prevented": False, "at": None, "sections": None})
        self.assertEqual(self.data["closed"], 1)

    def test_the_menu_key_and_shift_f10_open_the_menu_of_the_focused_element_at_its_rect(self):
        keys = self.data["keys"]
        opened = {"prevented": True, "at": {"x": 30, "y": 90}, "element": "Task work/feature"}
        self.assertEqual((keys["menu"], keys["shiftF10"]), (opened, opened))
        for case in ("f10", "ctrl", "field"):
            with self.subTest(case=case):
                self.assertEqual(keys[case], {"prevented": False, "at": None, "element": None})

    def test_a_selection_or_a_right_clicked_code_row_in_a_diff_makes_comment_the_first_item_of_the_menu(self):
        self.assertEqual(self.data["unselected"], ["element", "src/app.py", ["Copy path", "Open entry", "Copy id"]])
        self.assertEqual(self.data["row"]["sections"][0], ["element", "src/app.py", ["Comment", "Copy path", "Open entry", "Copy id"]])
        self.assertEqual(self.data["note"], ["Copy path", "Open entry", "Copy id"])
        selected = self.data["selected"]
        self.assertTrue(selected["prevented"])
        self.assertEqual(selected["sections"][0], ["element", "src/app.py", ["Comment", "Copy path", "Open entry", "Copy id"]])
        self.assertEqual(self.data["feedback"], ["src/app.py:7-7", "src/app.py:2-3"])

    def test_the_shortcuts_sheet_names_the_context_menu_keys(self):
        keys = self.data["keysHelp"]
        self.assertEqual(keys[:4], ["Ctrl+K", "Right-click", "Shift+right-click", "Menu key · Shift+F10"])


if __name__ == "__main__":
    unittest.main()
