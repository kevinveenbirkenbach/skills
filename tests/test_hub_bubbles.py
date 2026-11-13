from __future__ import annotations

import hashlib
import json
import re
import subprocess
import unittest

from hub_case import HubCase
from hub_support import HUB
from kvb_orchestrator import exchange, settings, view

BUBBLES = HUB / "templates" / "bubbles.js"
LAYER = HUB / "templates" / "page-bubbles.js"
SPEECH = HUB / "templates" / "page-speech.js"
STYLE = HUB / "templates" / "style-bubbles.css"
FONT = HUB / "vendor" / "comic-neue" / "comic-neue-latin-400-normal.woff2"
FONT_SHA256 = "b7753f30f8bd4925cf48a2ffe936c52ff1f16fe441f8c0245acf046296ac590f"
HOLDER = "Copyright 2014 The Comic Neue Project Authors (https://github.com/crozynski/comicneue)"
BUBBLES_PROBE = """
const B = require(process.argv[1]);
const item = (who, n) => ({who, n});
const [a1, b1, c1, a2, b2, d1] = [item("A", 1), item("B", 1), item("C", 1), item("A", 2), item("B", 2), item("D", 1)];
const planOf = (head, pending) => B.plan(head, pending).map((entry) => [entry.who, entry.item.n, entry.scale]);
const speech = {classes: ["security", "post"]};
console.log(JSON.stringify({
  scales: [0, 1, 2, 3, 4, 9].map(B.scale),
  reveals: [B.reveals(4, 2), B.reveals(5, 1), B.reveals(0, 3)],
  shown: [0, 0.49, 0.5, 1.49, 1.5, 9].map((at) => B.shown(4, 2, at)),
  reading: [0, 4, 5, 9, 180].map(B.reading),
  words: [B.words("  Disk almost\\nfull\\t now  "), B.words(""), B.words(null)],
  plans: [planOf(a1, [b1, c1, a2, b2, d1]), planOf(null, [b1, a1, b2]), planOf(a1, []), planOf(null, [])],
  picked: [{class: "mayday"}, {class: "security"}, {class: "post"}, {class: "broadcast"}].map((row) => B.picked(row, speech)),
}));
"""
SPEECH_PROBE = """
const fs = require("fs");
const vm = require("vm");
const Bubbles = require(process.argv[1]);
const code = fs.readFileSync(process.argv[2], "utf8");
const settle = () => new Promise((resolve) => setImmediate(resolve));
async function failed(bubbles, item, cancel) {
  const shown = [];
  const speech = {pending: [], busy: false, current: null, loading: null, item: null, timer: 0, warned: 0};
  const fetch = async () => {
    if (cancel) {
      speech.item = null;
    }
    return {ok: false, status: 503, headers: {get: () => "text/plain"}, text: async () => "tts down "};
  };
  vm.runInNewContext(`${code}\\nsay(item);`, {
    Bubbles, speech, fetch, item, Date, settings: {bubbles}, SPEECH_QUEUE: 9, SPEECH_QUIET: 0, radioSet: {},
    Voice: {enqueue: (pending, next) => [...pending, next], loudness: () => 0}, RadioSet: {burst: (gain) => ({gain})},
    toast: (title, lines) => shown.push(`${title}: ${lines.join(" ")}`),
    context: () => ({}), drawBubbles: () => {}, drawSpeaker: () => {},
    performance: {now: () => 1000}, window: {setTimeout: () => 7, clearTimeout: () => {}},
  });
  for (let round = 0; round < 5; round += 1) {
    await settle();
  }
  return {current: speech.current === item, busy: speech.busy, timer: speech.timer, started: item.started ?? null, duration: item.duration ?? null, shown};
}
(async () => {
  const row = () => ({steps: [{kind: "speech", text: "t"}], who: "A", line: "Disk almost full", words: ["Disk", "almost", "full"]});
  console.log(JSON.stringify({
    fallback: await failed(true, row(), false),
    off: await failed(false, row(), false),
    sample: await failed(true, {steps: [{kind: "speech", text: "t"}], who: "Operator", line: "radio check"}, false),
    cancelled: await failed(true, row(), true),
    burst: await failed(true, {...row(), steps: [{kind: "burst"}]}, false),
    unread: await failed(false, {...row(), steps: [{kind: "burst"}]}, false),
  }));
})();
"""
STOP_PROBE = """
const fs = require("fs");
const vm = require("vm");
const Bubbles = require(process.argv[1]);
const code = process.argv.slice(2).map((path) => fs.readFileSync(path, "utf8")).join("\\n");
class Node {
  constructor(attrs) {
    Object.assign(this, {children: [], parentElement: null, dataset: {}, classes: new Set(), attrs: {}, textContent: "", hidden: false, offsetWidth: 120, offsetHeight: 40, scrollTop: 0, scrollHeight: 0});
    this.style = {setProperty: () => null, removeProperty: () => null};
    this.classList = {add: (name) => this.classes.add(name), contains: (name) => this.classes.has(name)};
    for (const [key, value] of Object.entries(attrs || {})) {
      if (key === "class") {
        value.split(" ").forEach((name) => this.classes.add(name));
      } else if (key.startsWith("data-")) {
        this.dataset[key.slice(5)] = value;
      } else {
        this.attrs[key] = value;
      }
    }
  }
  append(...nodes) {
    for (const node of nodes.filter((entry) => entry instanceof Node)) {
      node.remove();
      node.parentElement = this;
      this.children.push(node);
    }
  }
  remove() {
    if (this.parentElement) {
      this.parentElement.children = this.parentElement.children.filter((node) => node !== this);
      this.parentElement = null;
    }
  }
  setAttribute(key, value) {
    this.attrs[key] = String(value);
  }
  querySelectorAll(selector) {
    const below = (node) => node.children.flatMap((child) => [child, ...below(child)]);
    return below(this).filter((node) => node.classes.has(selector.slice(1)));
  }
  querySelector(selector) {
    return this.querySelectorAll(selector)[0] || null;
  }
}
function run(scenario) {
  const layer = new Node({class: "bubbles"});
  layer.append(new Node({class: "bubble-bar"}));
  const toggle = new Node({});
  const frames = [];
  const context = {
    Bubbles, layer, toggle, frames, out: null, stops: 0,
    speech: {pending: [], busy: false, current: null, loading: null, timer: 0, warned: 0, source: null},
    settings: {bubbles: true},
    document: {getElementById: (id) => (id === "bubbles" ? layer : toggle), querySelectorAll: () => [], fonts: {add: () => null}},
    window: {innerWidth: 1366, innerHeight: 768, requestAnimationFrame: (next) => frames.push(next), cancelAnimationFrame: () => null, setTimeout: () => 0, clearTimeout: () => null},
    performance: {now: () => 2000}, CSS: {escape: (value) => value}, g3: {tab: "stream"}, anchor3d: () => () => null,
    h: (tag, attrs, ...children) => {
      const node = new Node(attrs);
      node.append(...children);
      return node;
    },
    nameOf: (key) => key, fixed: (value) => value.toFixed(1), fetch: async () => ({ok: false, status: 404}), FontFace: class {},
    drawSpeaker: () => null, toast: () => null, saveSettings: () => null, context: () => null, Voice: {enqueue: (pending, next) => [...pending, next]}, SPEECH_QUEUE: 9, SPEECH_QUIET: 0,
  };
  vm.runInNewContext(`${code}
const playing = {who: "A", line: "Disk almost full", words: ["Disk", "almost", "full"], started: 1000, duration: 3};
const next = {who: "B", line: "Gate green", words: ["Gate", "green"]};
const quiet = {who: "C", line: "Docs green", words: ["Docs", "green"], silent: true};
Object.assign(speech, {current: playing, busy: true, source: {stop: () => { stops += 1; }}, pending: [next, quiet]});
drawBubbles();
const before = layer.querySelectorAll(".speech-bubble").length;
${scenario}
frames.splice(0).forEach((frame) => frame());
out = {before, after: layer.querySelectorAll(".speech-bubble").length, shown: bubbles.shown.size, stops, current: speech.current === playing, busy: speech.busy,
  pending: speech.pending.map((item) => item.who), hidden: layer.hidden, pressed: toggle.attrs["aria-pressed"] || null};`, context);
  return context.out;
}
console.log(JSON.stringify({stop: run("cancelSpeech();"), off: run("settings.bubbles = false;\\nsyncBubbles();")}));
"""


class TestBubbleSchedule(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        done = subprocess.run(["node", "-e", BUBBLES_PROBE, str(BUBBLES)], capture_output=True, text=True, timeout=60, check=True)
        cls.data = json.loads(done.stdout)

    def test_the_scale_falls_with_the_queue_position_to_at_least_a_half(self):
        self.assertEqual(self.data["scales"], [1, 0.8, 0.65, 0.5, 0.5, 0.5])

    def test_word_i_of_n_appears_at_i_over_n_of_the_duration(self):
        self.assertEqual(self.data["reveals"], [[0, 0.5, 1, 1.5], [0, 0.2, 0.4, 0.6, 0.8], []])
        self.assertEqual(self.data["shown"], [1, 1, 2, 3, 4, 4])

    def test_without_audio_a_row_lasts_its_reading_time_at_180_words_a_minute_and_at_least_one_and_a_half_seconds(self):
        self.assertEqual(self.data["reading"], [1.5, 1.5, 5 / 3, 3, 60])
        self.assertEqual(self.data["words"], [["Disk", "almost", "full", "now"], [], []])

    def test_each_agent_gets_one_bubble_sized_by_its_earliest_item(self):
        self.assertEqual(self.data["plans"], [
            [["A", 1, 1], ["B", 1, 0.8], ["C", 1, 0.65], ["D", 1, 0.5]],
            [["B", 1, 0.8], ["A", 1, 0.65]],
            [["A", 1, 1]],
            [],
        ])

    def test_bubbles_follow_the_read_aloud_classes_and_mayday_always(self):
        self.assertEqual(self.data["picked"], [True, True, True, False])


class TestSpeechFallback(unittest.TestCase):
    def test_a_failed_tts_request_reads_the_row_at_reading_pace_only_while_bubbles_are_on(self):
        done = subprocess.run(["node", "-e", SPEECH_PROBE, str(BUBBLES), str(SPEECH)], capture_output=True, text=True, timeout=60, check=True)
        data = json.loads(done.stdout)
        failed = ["Reading radio aloud failed: 503 tts down"]
        self.assertEqual(data["fallback"], {"current": True, "busy": True, "timer": 7, "started": 1000, "duration": 1.5, "shown": failed})
        for case in ("off", "sample", "cancelled"):
            with self.subTest(case=case):
                self.assertEqual(data[case], {"current": False, "busy": False, "timer": 0, "started": None, "duration": None, "shown": failed})

    def test_a_row_the_burst_stands_in_for_reads_at_reading_pace_only_while_bubbles_are_on(self):
        done = subprocess.run(["node", "-e", SPEECH_PROBE, str(BUBBLES), str(SPEECH)], capture_output=True, text=True, timeout=60, check=True)
        data = json.loads(done.stdout)
        self.assertEqual(data["burst"], {"current": True, "busy": True, "timer": 7, "started": 1000, "duration": 1.5, "shown": []})
        self.assertEqual(data["unread"], {"current": False, "busy": False, "timer": 0, "started": None, "duration": None, "shown": []})


class TestBubbleStop(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        done = subprocess.run(["node", "-e", STOP_PROBE, str(BUBBLES), str(SPEECH), str(LAYER)], capture_output=True, text=True, timeout=60, check=True)
        cls.data = json.loads(done.stdout)

    def test_stop_speaking_clears_every_bubble_at_once_and_stops_the_audio(self):
        self.assertEqual(self.data["stop"], {"before": 3, "after": 0, "shown": 0, "stops": 1, "current": False, "busy": True, "pending": [], "hidden": False, "pressed": None})

    def test_switching_the_bubbles_off_clears_the_layer_and_leaves_the_audible_item_playing(self):
        self.assertEqual(self.data["off"], {"before": 3, "after": 0, "shown": 0, "stops": 0, "current": True, "busy": True, "pending": ["B"], "hidden": True, "pressed": "false"})


class TestBubbleAssets(unittest.TestCase):
    def test_the_font_is_pinned_and_carries_the_ofl_without_a_reserved_name(self):
        data = FONT.read_bytes()
        self.assertEqual((data[:4], hashlib.sha256(data).hexdigest()), (b"wOF2", FONT_SHA256))
        licence = (FONT.parent / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("SIL OPEN FONT LICENSE Version 1.1 - 26 February 2007", licence)
        self.assertIn(HOLDER, licence)
        self.assertNotIn("with Reserved Font Name", licence)

    def test_bubble_text_is_set_as_text_only_in_the_comic_neue_stack_and_reduced_motion_drops_the_motion(self):
        layer = LAYER.read_text(encoding="utf-8")
        for markup in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "DOMParser"):
            with self.subTest(markup=markup):
                self.assertNotIn(markup, layer)
        self.assertIn("view.words.textContent = text;", layer)
        style = STYLE.read_text(encoding="utf-8")
        self.assertIn('"Comic Neue", "Comic Sans MS", cursive', style)
        self.assertIn("pointer-events: none", style)
        calm = re.search(r"@media \(prefers-reduced-motion: reduce\) \{(.*?)\n\}", style, re.DOTALL).group(1)
        self.assertIn(".speech-bubble { transition: opacity .4s var(--ease); }", calm)
        self.assertIn(".bubble-words { scroll-behavior: auto; }", calm)

    def test_the_schedule_module_parses_on_its_own(self):
        done = subprocess.run(["node", "--check", str(BUBBLES)], capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(done.returncode, 0, done.stderr)


class TestHubBubbles(HubCase):
    def test_the_toolbar_icon_and_the_layer_ship_in_the_page_under_the_unchanged_csp(self):
        status, headers, body = self.get("/")
        self.assertEqual(status, 200)
        html = body.decode("utf-8")
        header = re.search(r'<header class="top">(.*?)</header>', html, re.DOTALL).group(1)
        toggle = re.search(r'<button [^>]*id="bubbles-toggle"[^>]*>(.*?)</button>', header).group(0)
        for part in ('title="Speech bubbles"', 'aria-label="Speech bubbles"', 'aria-pressed="false"', '<use href="#bi-chat-quote"></use>'):
            with self.subTest(part=part):
                self.assertIn(part, toggle)
        self.assertIn('<symbol id="bi-chat-quote"', html)
        self.assertIn('<div class="bubbles" id="bubbles" aria-hidden="true" hidden><div class="bubble-bar"></div></div>', html)
        self.assertIn(BUBBLES.read_text(encoding="utf-8").strip(), html)
        nonce = re.search(r"script-src 'nonce-([^']+)'", headers["content-security-policy"]).group(1)
        self.assertEqual(headers["content-security-policy"], view.INDEX_CSP.format(nonce, "'self'"))
        self.assertNotIn("font-src", headers["content-security-policy"])
        self.assertNotIn("@font-face", html)

    def test_the_vendor_route_serves_the_font_as_woff2_under_the_plain_csp(self):
        status, headers, body = self.get("/vendor/comic-neue.woff2")
        self.assertEqual((status, headers["content-type"], headers["content-security-policy"]), (200, "font/woff2", exchange.PLAIN_CSP))
        self.assertEqual(body, FONT.read_bytes())
        for path in ("/vendor/comic-neue-latin-400-normal.woff2", "/vendor/comic-neue", "/vendor/LICENSE"):
            with self.subTest(path=path):
                self.assertEqual(self.get(path)[0], 404)

    def test_the_bubble_switch_is_a_hub_setting_saved_without_a_passkey_that_survives_a_reload(self):
        self.assertEqual((settings.SETTINGS["bubbles"], self.snapshot()["settings"]["bubbles"]), (False, False))
        good = self.guard(self.host)
        current = self.snapshot()["settings"]
        for wrong in ("true", 1, None, [True]):
            with self.subTest(wrong=wrong):
                self.assertEqual(self.post_json("/api/settings", {**current, "bubbles": wrong}, good)[0], 400)
        self.assertEqual(self.post_json("/api/settings", {key: value for key, value in current.items() if key != "bubbles"}, good)[0], 400)
        status, _, body = self.post_json("/api/settings/sign", {**current, "bubbles": True}, good)
        self.assertEqual((status, json.loads(body)["payload"]), (200, None))
        status, _, body = self.post_json("/api/settings", {**current, "bubbles": True, "proof": None}, good)
        self.assertEqual((status, json.loads(body)["settings"]), (200, {**current, "bubbles": True}), body)
        self.assertTrue(settings.Settings(self.state / "settings.json").get()["bubbles"])
        self.assertTrue(self.snapshot()["settings"]["bubbles"])
        older = {key: value for key, value in current.items() if key != "bubbles"}
        (self.state / "settings.json").write_text(json.dumps(older), encoding="utf-8")
        self.assertFalse(settings.Settings(self.state / "settings.json").get()["bubbles"])


if __name__ == "__main__":
    unittest.main()
