from __future__ import annotations

import json
import re
import subprocess
import unittest

from hub_support import HUB

TEMPLATES = HUB / "templates"
MODULES = ["page-constants.js", "page-reveal.js", "page-dom.js"]
VIEWS = {
    "page-match.js": "Match",
    "page-tasks.js": "Tasks",
    "page-resources.js": "Resources",
    "page-artifacts.js": "Artifacts",
    "page-graph-charts.js": "Agents",
    "page-firewall.js": "Controls",
}
PROBE = r"""
const fs = require("fs");
const vm = require("vm");
const [dir, names] = [process.argv[1], JSON.parse(process.argv[2])];
class El {
  constructor(tag) { Object.assign(this, {tag, children: [], attrs: {}, dataset: {}, style: {}}); }
  setAttribute(key, value) { this.attrs[key] = String(value); }
  getAttribute(key) { return Object.hasOwn(this.attrs, key) ? this.attrs[key] : null; }
  append(...nodes) { this.children.push(...nodes); }
  addEventListener() {}
}
const document = {
  currentScript: null, body: new El("body"),
  getElementById: () => Object.assign(new El("div"), {textContent: "[]"}),
  createElement: (tag) => new El(tag), createElementNS: (ns, tag) => new El(tag),
};
const context = {
  console, document, JSON, Math, Date, Intl, Promise, Set, Map, Number, String, Array, Object, RegExp, Boolean, Error,
  Node: El, Element: El, HTMLElement: El,
  window: {location: {hash: ""}, setTimeout: () => 0, matchMedia: () => ({matches: false})},
  state: {inbox: [], radio: []}, ui: {}, settings: {},
};
const source = names.map((name) => fs.readFileSync(`${dir}/${name}`, "utf8")).join("\n");
const probe = `
const title = h("strong", {class: "box-title"}, "Match");
const count = h("span", {}, "2 cards wait");
const button = h("button", {type: "button"}, "Tasks");
const band = boxHead("Match", "task-toolbar", title, count, null, button);
const plain = boxHead("Resources", "", button);
const holding = boxHead("Agents", "", h("div", {role: "toolbar", "aria-label": "Agents tools"}, button));
JSON.stringify({
  band: {tag: band.tag, attrs: band.attrs, order: band.children.map((child) => child.tag + ":" + (child.children[0] || ""))},
  plain: plain.attrs.class, holding: holding.attrs.role,
});
`;
console.log(vm.runInNewContext(`${source}\n${probe}`, context));
"""


class TestBoxHeads(unittest.TestCase):
    def test_the_band_helper_renders_its_label_classes_and_children_in_order_and_never_nests_a_toolbar(self):
        done = subprocess.run(["node", "-e", PROBE, str(TEMPLATES), json.dumps(MODULES)], capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        out = json.loads(done.stdout)
        self.assertEqual(out["band"]["tag"], "div")
        self.assertEqual(out["band"]["attrs"], {"class": "box-head task-toolbar", "role": "toolbar", "aria-label": "Match"})
        self.assertEqual(out["band"]["order"], ["strong:Match", "span:2 cards wait", "button:Tasks"])
        self.assertEqual((out["plain"], out["holding"]), ("box-head", "group"))

    def test_every_view_builds_its_controls_with_the_one_band_helper(self):
        helpers = [name for name in sorted(path.name for path in TEMPLATES.glob("*.js")) if re.search(r"\bconst boxHead\b|\bfunction boxHead\b", (TEMPLATES / name).read_text(encoding="utf-8"))]
        self.assertEqual(helpers, ["page-dom.js"])
        for name, label in VIEWS.items():
            with self.subTest(view=name):
                self.assertIn(f'boxHead("{label}"', (TEMPLATES / name).read_text(encoding="utf-8"))

    def test_no_template_keeps_a_separate_controls_card(self):
        for path in sorted(TEMPLATES.glob("*.js")):
            with self.subTest(file=path.name):
                self.assertNotIn("card controls", path.read_text(encoding="utf-8"))

    def test_the_band_sits_on_the_box_edge_through_the_main_padding_variables(self):
        page = (TEMPLATES / "index.html.j2").read_text(encoding="utf-8")
        self.assertRegex(page, r"main \{ --main-pad: var\(--sp-5\); --main-top: var\(--main-pad\);[^}]*padding: var\(--main-top\) var\(--main-pad\)")
        self.assertRegex(page, r"\.box-head \{[^}]*margin: calc\(-1 \* var\(--main-top\)\) calc\(-1 \* var\(--main-pad\)\) 0;")
        self.assertIn("--main-top: var(--sp-3)", (TEMPLATES / "style-ui.css").read_text(encoding="utf-8"))

    def test_the_match_card_bar_is_its_own_background_on_the_outer_edge(self):
        css = (TEMPLATES / "style-match.css").read_text(encoding="utf-8")
        self.assertNotIn(".match-card.front::before", css)
        self.assertRegex(css, r"\.match-card\.front \{[^}]*border-top-width: 0;[^}]*background: var\(--bar\) top / 100% 6px no-repeat")
        self.assertIn("mask-image: linear-gradient(180deg, transparent 6px, #000 6px", css)


if __name__ == "__main__":
    unittest.main()
