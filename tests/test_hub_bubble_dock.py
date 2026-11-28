"""Exercise requirement 098: a docked speech bubble shows its speaker's face and a close button that skips the message."""

from __future__ import annotations

import json
import subprocess
import unittest

from hub_support import HUB
from test_hub_bubble_front import rules
from test_hub_bubbles import PAGE_HEAD

BUBBLES = HUB / "templates" / "bubbles.js"
SPEECH = HUB / "templates" / "page-speech.js"
LAYER = HUB / "templates" / "page-bubbles.js"
PROBE = PAGE_HEAD + """
const settle = async () => {
  for (let round = 0; round < 8; round += 1) {
    await new Promise((resolve) => setImmediate(resolve));
  }
};
const part = () => ({gain: {value: 0, setValueAtTime: () => {}, exponentialRampToValueAtTime: () => {}}, frequency: {}, Q: {}, connect: (next) => next});
function page() {
  const layer = new Node({class: "bubbles"});
  layer.append(new Node({class: "bubble-bar"}));
  const out = {stops: 0, cleared: [], vanished: [], selectors: [], made: []};
  const timers = new Map();
  const audio = {
    sampleRate: 8000, currentTime: 0, destination: {},
    createBuffer: (channels, frames) => ({getChannelData: () => new Float32Array(frames)}), createBiquadFilter: part, createGain: part,
    createBufferSource: () => {
      const source = {...part(), ended: null, start: () => {}};
      source.addEventListener = (name, run) => {
        source.ended = run;
      };
      source.stop = (when) => {
        if (when === undefined) {
          out.stops += 1;
          setImmediate(() => source.ended && source.ended());
        }
      };
      return source;
    },
  };
  const context = {
    Bubbles, out, settings: {bubbles: true}, radioSet: {}, SPEECH_QUEUE: 9, SPEECH_QUIET: 0, SOUND_SLACK: 2, Date,
    speech: {pending: [], busy: false, current: null, loading: null, item: null, source: null, timer: 0, warned: 0},
    document: {getElementById: () => layer, querySelectorAll: (selector) => out.selectors.push(selector) && [], fonts: {add: () => null}},
    window: {
      innerWidth: 1366, innerHeight: 768, requestAnimationFrame: () => 1, cancelAnimationFrame: () => null,
      setTimeout: (run) => {
        timers.set(timers.size + 1, run);
        return timers.size;
      },
      clearTimeout: (id) => out.cleared.push(id),
    },
    performance: {now: () => 1000}, CSS: {escape: (value) => value}, g3: {tab: "stream"}, anchor3d: () => () => null,
    h: (tag, attrs, ...children) => {
      const node = new Node(attrs);
      node.append(...children);
      if (node.classes.has("speech-bubble")) {
        out.made.push(node);
      }
      return node;
    },
    face: (who) => new Node({class: "avatar", "data-face": who}),
    iconBtn: (name, label, cls, run, hint) => Object.assign(new Node({class: cls}), {icon: name, label, hint, run}),
    vanish: (node) => {
      if (node) {
        out.vanished.push(node.dataset.who);
        node.remove();
      }
    },
    nameOf: (key) => `Agent ${key}`, fixed: (value) => value.toFixed(1), FontFace: class {}, toast: () => null, context: () => audio, duck: () => null, drawSpeaker: () => null,
    Voice: {enqueue: (pending, next) => [...pending, next], loudness: () => 1},
    RadioSet: {KEYED: ["morse", "gibberlink"], FALLBACKS: ["gibberlink", "morse", "burst"], burst: (gain) => ({gain, seconds: 0.6, frequency: 1800, q: 0.9})},
  };
  vm.createContext(context);
  vm.runInContext(code, context);
  const run = (script) => vm.runInContext(script, context);
  const shown = (who) => out.made.filter((node) => node.dataset.who === who && node.parentElement);
  const skip = (who) => shown(who)[0].querySelector(".bubble-skip").run();
  const state = () => ({
    current: context.speech.current ? context.speech.current.who : null, pending: context.speech.pending.map((item) => item.who), busy: context.speech.busy,
    quiet: run("bubbles.quiet.map((item) => item.who)"), shown: run("[...bubbles.shown.keys()].map((item) => item.who)"), stops: out.stops, vanished: [...out.vanished],
  });
  return {context, out, run, shown, skip, state};
}
const sounded = (who) => ({who, line: `${who} disk almost full`, words: [who, "disk", "almost", "full"], steps: [{kind: "burst"}], tone: "direct"});
const silent = (who) => ({who, line: `${who} gate green`, words: [who, "gate", "green"], silent: true});
(async () => {
  const found = {};
  {
    const at = page();
    at.context.say(sounded("A"), sounded("B"));
    await settle();
    const node = at.shown("A")[0];
    const [head] = node.children;
    const button = node.querySelector(".bubble-skip");
    found.node = {
      head: head.children.map((child) => [...child.classes].join(" ")), face: head.children[0].dataset.face, icon: button.icon, label: button.label, hint: button.hint, wordsHidden: node.children[1].attrs["aria-hidden"], selectors: [...new Set(at.out.selectors)],
    };
    found.before = at.state();
    at.skip("A");
    await settle();
    found.current = {...at.state(), madeA: at.out.made.filter((made) => made.dataset.who === "A").length};
  }
  {
    const at = page();
    at.context.say(sounded("A"), sounded("B"), sounded("C"));
    await settle();
    at.skip("B");
    await settle();
    found.queued = at.state();
  }
  {
    const at = page();
    at.context.say(silent("A"), silent("B"));
    await settle();
    const timer = at.context.speech.timer;
    at.skip("A");
    await settle();
    found.silent = {...at.state(), clearedOwnTimer: at.out.cleared.includes(timer), timer: at.context.speech.timer !== timer && at.context.speech.timer > 0};
  }
  {
    const at = page();
    at.run('quietBubbles([{who: "Q", line: "Q docs green", words: ["Q", "docs", "green"], quiet: true}]); drawBubbles();');
    const timer = at.run("bubbles.quiet[0].timer");
    const before = at.state();
    at.skip("Q");
    at.run("quietBubbles([]); drawBubbles(); drawBubbles();");
    found.quiet = {before, after: at.state(), clearedOwnTimer: at.out.cleared.includes(timer), madeQ: at.out.made.filter((made) => made.dataset.who === "Q").length};
  }
  console.log(JSON.stringify(found));
})();
"""


class TestDockedBubbleSkip(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        done = subprocess.run(["node", "-e", PROBE, str(BUBBLES), str(SPEECH), str(LAYER)], capture_output=True, text=True, timeout=60, check=False)
        if done.returncode != 0:
            raise AssertionError(done.stderr[-4000:])
        cls.data = json.loads(done.stdout)

    def test_a_bubble_carries_the_speakers_face_left_of_the_name_and_a_labelled_close_button(self):
        node = self.data["node"]
        self.assertEqual(node["head"], ["avatar", "bubble-who", "bubble-skip"])
        self.assertEqual((node["face"], node["icon"]), ("A", "bi-x-lg"))
        self.assertEqual(node["label"], "Skip message from Agent A")
        self.assertIn("Agent A", node["hint"])
        self.assertEqual(node["wordsHidden"], "true")

    def test_the_face_inside_a_bubble_is_never_an_anchor(self):
        self.assertEqual(self.data["node"]["selectors"], ['[data-face="A"]:not(#bubbles *)', '[data-face="B"]:not(#bubbles *)'])

    def test_closing_the_message_read_aloud_stops_its_audio_and_the_next_one_starts(self):
        self.assertEqual((self.data["before"]["current"], self.data["before"]["pending"]), ("A", ["B"]))
        current = self.data["current"]
        self.assertEqual((current["stops"], current["current"], current["pending"], current["busy"]), (1, "B", [], True), current)
        self.assertEqual((current["vanished"], current["shown"], current["madeA"]), (["A"], ["B"], 1), current)

    def test_closing_a_queued_message_takes_it_off_the_queue_and_leaves_the_voice_playing(self):
        queued = self.data["queued"]
        self.assertEqual((queued["stops"], queued["current"], queued["pending"], queued["vanished"]), (0, "A", ["C"], ["B"]), queued)
        self.assertNotIn("B", queued["shown"])

    def test_closing_a_silent_reading_ends_it_and_the_next_one_reads(self):
        silent = self.data["silent"]
        self.assertEqual((silent["current"], silent["pending"], silent["vanished"], silent["stops"]), ("B", [], ["A"], 0), silent)
        self.assertEqual((silent["clearedOwnTimer"], silent["timer"]), (True, True), silent)

    def test_closing_a_quiet_bubble_drops_it_and_the_next_poll_does_not_bring_it_back(self):
        quiet = self.data["quiet"]
        self.assertEqual((quiet["before"]["quiet"], quiet["before"]["shown"]), (["Q"], ["Q"]), quiet)
        self.assertEqual((quiet["after"]["quiet"], quiet["after"]["shown"], quiet["after"]["vanished"]), ([], [], ["Q"]), quiet)
        self.assertEqual((quiet["clearedOwnTimer"], quiet["madeQ"]), (True, 1), quiet)


class TestDockedBubbleStyle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rules = rules()

    def test_face_name_and_close_show_only_in_the_bar_with_the_face_first(self):
        self.assertEqual(self.rules[".bubble-head"]["display"], "none")
        self.assertEqual(self.rules[".bubble-bar .bubble-head"]["display"], "flex")
        self.assertNotIn("display", self.rules[".bubble-who"])

    def test_the_close_button_takes_clicks_through_the_layer_that_ignores_the_pointer(self):
        self.assertEqual(self.rules[".bubbles"]["pointer-events"], "none")
        self.assertEqual(self.rules[".bubble-skip"]["pointer-events"], "auto")
        self.assertEqual(self.rules[".speech-bubble.leaving .bubble-skip"]["pointer-events"], "none")


if __name__ == "__main__":
    unittest.main()
