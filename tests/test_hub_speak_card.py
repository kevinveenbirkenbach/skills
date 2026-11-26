from __future__ import annotations

import json
import re
import subprocess
import unittest

from hub_support import HUB

TEMPLATES = HUB / "templates"
MODULES = ["page-constants.js", "page-reveal.js", "page-dom.js", "page-board.js", "page-composer.js"]
PROBE = r"""
const fs = require("fs");
const vm = require("vm");
const [dir, names] = [process.argv[1], JSON.parse(process.argv[2])];
class El {
  constructor(tag) { Object.assign(this, {tag, children: [], attrs: {}, dataset: {}, style: {}}); }
  setAttribute(key, value) { this.attrs[key] = String(value); }
  getAttribute(key) { return Object.hasOwn(this.attrs, key) ? this.attrs[key] : null; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  addEventListener() {}
}
const document = {
  currentScript: null, body: new El("body"),
  getElementById: () => Object.assign(new El("div"), {textContent: "[]"}),
  createElement: (tag) => new El(tag), createElementNS: (ns, tag) => new El(tag),
};
const context = {
  console, document, JSON, Math, Date, Intl, Promise, Set, Map, Number, String, Array, Object, RegExp, Boolean, Error,
  El, Node: El, Element: El, HTMLElement: El,
  window: {location: {hash: ""}, setTimeout: () => 0, matchMedia: () => ({matches: false})},
  state: {inbox: [], radio: [], silence: null}, ui: {}, settings: {},
};
const source = names.map((name) => fs.readFileSync(`${dir}/${name}`, "utf8")).join("\n");
const probe = `
const toggle = new El("button");
state.silence = null;
drawMayday(toggle);
const idle = [toggle.attrs["aria-pressed"], toggle.children[1], toggle.title];
state.silence = {since: 1, by: "Docs", text: "disk full"};
drawMayday(toggle);
const active = [toggle.attrs["aria-pressed"], toggle.children[1], toggle.title];
JSON.stringify({idle, active, channels: CHANNELS.map(([id]) => id), titled: CHANNELS.every(([id]) => typeof CHANNEL_HINTS[id] === "string" && CHANNEL_HINTS[id].length > 0)});
`;
console.log(vm.runInNewContext(`${source}\n${probe}`, context));
"""


class TestSpeakCard(unittest.TestCase):
    def probe(self) -> dict:
        done = subprocess.run(["node", "-e", PROBE, str(TEMPLATES), json.dumps(MODULES)], capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def test_the_toggle_reads_mayday_until_one_holds_the_radio_silent_then_cancel_mayday(self):
        out = self.probe()
        self.assertEqual(out["idle"][:2], ["false", "MAYDAY"])
        self.assertTrue(out["idle"][2].startswith("MAYDAY: "), out)
        self.assertEqual(out["active"], ["true", "Cancel mayday", "Cancel mayday: lift the radio silence so the agents write again; your passkey signs it"])

    def test_the_channel_select_holds_no_mayday_and_every_channel_keeps_its_hint_for_the_choice_buttons(self):
        out = self.probe()
        self.assertEqual(out["channels"], ["post", "call", "newsletter", "broadcast", "pan-pan", "security"])
        self.assertTrue(out["titled"], out)

    def test_the_card_has_no_hint_sentence_no_hint_tooltip_and_no_browser_confirm(self):
        composer = (TEMPLATES / "page-composer.js").read_text(encoding="utf-8")
        self.assertNotIn("window.confirm", composer)
        self.assertNotIn("Your passkey signs every message", composer)
        self.assertNotIn("composer-hint", composer)
        self.assertNotIn("CHANNEL_HINTS[", composer)

    def test_channel_row_textarea_and_footer_share_one_frame_with_ptt_and_mayday_after_the_mic(self):
        composer = (TEMPLATES / "page-composer.js").read_text(encoding="utf-8")
        self.assertIn("const frame = micFrame(text, [record, status]);", composer)
        self.assertIn('frame.prepend(h("div", {class: "composer-grid"}', composer)
        self.assertRegex(composer, r'frame\.querySelector\("\.mic-foot"\)\.append\(h\("div", \{class: "ptt-split".*\), mayday\);')
        self.assertIn('h("form", {class: "composer"}, frame, replay)', composer)

    def test_the_card_is_one_rounded_surface(self):
        css = (TEMPLATES / "style-ui.css").read_text(encoding="utf-8")
        self.assertRegex(css, r"\.radio-card\.radio-speak \{ border-radius: 14px; \}")
        self.assertRegex(css, r"\.composer-grid \{ display: flex; min-width: 0; border-bottom: 1px solid var\(--line\); \}")
        self.assertNotRegex(css, r"\.composer textarea \{[^}]*border-radius")
        self.assertNotIn(".radio-cancel", css)
        self.assertIsNone(re.search(r'class: "[^"]*\bcard\b', (TEMPLATES / "page-composer.js").read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
