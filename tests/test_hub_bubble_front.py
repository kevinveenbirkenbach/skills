from __future__ import annotations

import json
import re
import subprocess
import unittest

from hub_support import HUB

BUBBLES = HUB / "templates" / "bubbles.js"
LAYER = HUB / "templates" / "page-bubbles.js"
STYLE = HUB / "templates" / "style-bubbles.css"
RAISED = '.speech-bubble[data-state="speaking"]:not(.leaving)'
STACKING = ("z-index", "transform", "opacity", "filter", "backdrop-filter", "isolation", "will-change", "contain", "mix-blend-mode", "perspective", "clip-path", "mask")
LAYER_PROBE = """
const fs = require("fs");
const vm = require("vm");
const Bubbles = require(process.argv[1]);
const code = fs.readFileSync(process.argv[2], "utf8");
const element = (tag, attrs) => {
  const node = {tag, names: new Set(String(attrs.class || "").split(" ").filter(Boolean)), dataset: {}, parentElement: null, kids: [], offsetWidth: 120, offsetHeight: 40, textContent: "", scrollTop: 0, scrollHeight: 0,
    style: {setProperty() {}, removeProperty() {}},
    append(...kids) {
      for (const kid of kids.flat().filter((item) => typeof item === "object")) {
        if (kid.parentElement) {
          kid.parentElement.kids = kid.parentElement.kids.filter((other) => other !== kid);
        }
        kid.parentElement = node;
        node.kids.push(kid);
      }
    },
    remove() {},
  };
  node.classList = {add: (name) => node.names.add(name)};
  for (const [key, value] of Object.entries(attrs).filter(([key]) => key.startsWith("data-"))) {
    node.dataset[key.slice(5)] = value;
  }
  return node;
};
const h = (tag, attrs, ...children) => {
  const node = element(tag, attrs);
  node.append(...children);
  return node;
};
const layer = element("div", {class: "bubbles"});
const bar = element("div", {class: "bubble-bar"});
layer.append(bar);
layer.querySelector = () => bar;
const near = {A: {left: 200, top: 300, width: 26, height: 26}};
const document = {
  getElementById: () => layer,
  querySelectorAll: (selector) => {
    const key = /data-face="([^"]*)"/.exec(selector)[1];
    return near[key] ? [{getBoundingClientRect: () => near[key]}] : [];
  },
};
const item = (who) => ({who, line: `${who} says four words`, words: [who, "says", "four", "words"], started: null});
const [a, b, c] = ["A", "B", "C"].map(item);
const speech = {current: null, loading: null, pending: []};
const context = {
  Bubbles, speech, document, h, settings: {bubbles: true}, g3: {tab: "stream"}, CSS: {escape: (value) => value}, nameOf: (key) => key, fixed: (value) => value.toFixed(1),
  performance: {now: () => 5000}, window: {innerWidth: 1366, innerHeight: 768, setTimeout: () => 0, requestAnimationFrame: () => 1, cancelAnimationFrame: () => {}},
};
vm.createContext(context);
vm.runInContext(code, context);
const shown = () => [...layer.kids, ...bar.kids].filter((node) => node.names.has("speech-bubble"))
  .map((node) => [node.dataset.who, node.dataset.state, node.names.has("leaving"), node.parentElement === bar ? "bar" : "layer"])
  .sort((one, two) => one[0].localeCompare(two[0]));
a.started = 4000;
Object.assign(speech, {current: a, pending: [b, c]});
vm.runInContext("drawBubbles()", context);
const first = shown();
b.started = 4900;
Object.assign(speech, {current: b, pending: [c]});
vm.runInContext("drawBubbles()", context);
console.log(JSON.stringify({first, after: shown()}));
"""
CLIP_PROBE = """
const fs = require("fs");
const vm = require("vm");
const code = fs.readFileSync(process.argv[1], "utf8");
const body = {};
const styles = new Map();
const box = (left, top, width, height) => ({left, top, width, height, right: left + width, bottom: top + height});
const element = (rect, parent, style) => {
  const node = {parentElement: parent, getBoundingClientRect: () => rect};
  styles.set(node, {display: "block", position: "static", overflowX: "visible", overflowY: "visible", ...style});
  return node;
};
const page = element(box(0, 0, 1366, 768), body, {});
const frame = element(box(40, 100, 500, 300), page, {overflowX: "auto", overflowY: "hidden"});
const svg = element(box(40, 100, 1360, 300), frame, {overflowX: "hidden", overflowY: "hidden"});
const wrapper = element(box(0, 0, 0, 0), page, {display: "contents", overflowX: "hidden", overflowY: "hidden"});
const faces = {
  inside: [element(box(100, 200, 26, 26), svg, {})],
  scrolled: [element(box(800, 200, 26, 26), svg, {})],
  half: [element(box(527, 200, 26, 26), svg, {})],
  next: [element(box(800, 200, 26, 26), svg, {}), element(box(200, 600, 26, 26), page, {})],
  contents: [element(box(800, 200, 26, 26), wrapper, {})],
  fixed: [element(box(800, 200, 26, 26), frame, {position: "fixed"})],
  away: [element(box(1400, 200, 26, 26), page, {})],
};
const context = {
  g3: {tab: "stream"}, CSS: {escape: (value) => value}, window: {innerWidth: 1366, innerHeight: 768}, getComputedStyle: (node) => styles.get(node),
  document: {body, querySelectorAll: (selector) => faces[/data-face="([^"]*)"/.exec(selector)[1]] || []},
};
vm.createContext(context);
vm.runInContext(code, context);
const pick = (found) => (found ? [found.left, found.top, found.width, found.height] : null);
console.log(JSON.stringify(Object.fromEntries(Object.keys(faces).map((key) => [key, pick(vm.runInContext(`anchorOf(${JSON.stringify(key)})`, context))]))));
"""


def rules() -> dict[str, dict[str, str]]:
    css = STYLE.read_text(encoding="utf-8")
    top = re.sub(r"@media[^{]*\{.*?\n\}", "", css, flags=re.DOTALL)
    found: dict[str, dict[str, str]] = {}
    for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", top):
        declarations = dict(tuple(part.strip() for part in line.split(":", 1)) for line in body.split(";") if ":" in line)
        for selector in selectors.split(","):
            found.setdefault(selector.strip(), {}).update(declarations)
    return found


class TestSpeakingBubbleInFront(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rules = rules()

    def test_only_the_speaking_bubble_that_is_not_leaving_rises_above_the_others(self):
        raised = {selector: declared["z-index"] for selector, declared in self.rules.items() if ".speech-bubble" in selector and "z-index" in declared}
        self.assertEqual(raised, {RAISED: "1"})

    def test_bubbles_in_the_layer_and_in_the_bar_are_positioned_so_the_z_index_takes_effect(self):
        self.assertEqual(self.rules[".speech-bubble"]["position"], "absolute")
        self.assertEqual(self.rules[".bubble-bar .speech-bubble"]["position"], "relative")

    def test_the_tail_is_drawn_by_the_bubble_itself_inside_its_own_stacking_context(self):
        self.assertIn("transform", self.rules[".speech-bubble"])
        self.assertIn("transform", self.rules[".bubble-bar .speech-bubble"])
        for tail in (".speech-bubble::before", ".speech-bubble::after"):
            with self.subTest(tail=tail):
                self.assertEqual(self.rules[tail]["content"], '""')
                self.assertNotIn("z-index", self.rules[tail])

    def test_floating_and_bar_bubbles_share_the_one_stacking_context_of_the_layer(self):
        self.assertEqual((self.rules[".bubbles"]["position"], self.rules[".bubbles"]["z-index"]), ("fixed", "20"))
        self.assertEqual([name for name in STACKING if name in self.rules[".bubble-bar"]], [])


class TestSpeakingMark(unittest.TestCase):
    def test_the_speaking_mark_follows_the_speaker_across_containers_and_a_leaving_bubble_keeps_its_old_mark(self):
        done = subprocess.run(["node", "-e", LAYER_PROBE, str(BUBBLES), str(LAYER)], capture_output=True, text=True, timeout=60, check=True)
        data = json.loads(done.stdout)
        self.assertEqual(data["first"], [["A", "speaking", False, "layer"], ["B", "waiting", False, "bar"], ["C", "waiting", False, "bar"]])
        self.assertEqual(data["after"], [["A", "speaking", True, "layer"], ["B", "speaking", False, "bar"], ["C", "waiting", False, "bar"]])
        for step, bubbles in data.items():
            with self.subTest(step=step):
                self.assertEqual([who for who, state, leaving, _ in bubbles if state == "speaking" and not leaving], ["A" if step == "first" else "B"])


class TestClippedAnchor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        done = subprocess.run(["node", "-e", CLIP_PROBE, str(LAYER)], capture_output=True, text=True, timeout=60, check=True)
        cls.data = json.loads(done.stdout)

    def test_a_face_inside_its_scrolling_frame_anchors_with_its_full_box(self):
        self.assertEqual(self.data["inside"], [100, 200, 26, 26])

    def test_a_face_scrolled_out_of_its_frame_is_no_anchor_so_the_bubble_falls_back_to_the_bar(self):
        self.assertIsNone(self.data["scrolled"])
        self.assertIsNone(self.data["away"])

    def test_a_half_clipped_face_anchors_on_its_visible_part(self):
        self.assertEqual(self.data["half"], [527, 200, 13, 26])

    def test_the_next_face_of_the_same_agent_anchors_when_the_first_is_clipped(self):
        self.assertEqual(self.data["next"], [200, 600, 26, 26])

    def test_boxless_wrappers_and_ancestors_of_a_fixed_face_do_not_clip(self):
        self.assertEqual((self.data["contents"], self.data["fixed"]), ([800, 200, 26, 26], [800, 200, 26, 26]))


if __name__ == "__main__":
    unittest.main()
