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
ALERTS = HUB / "templates" / "page-alerts.js"
CONSTANTS = HUB / "templates" / "page-constants.js"
VOICE = HUB / "templates" / "voice.js"
STYLE = HUB / "templates" / "style-bubbles.css"
FONT = HUB / "vendor" / "comic-neue" / "comic-neue-latin-400-normal.woff2"
FONT_SHA256 = "b7753f30f8bd4925cf48a2ffe936c52ff1f16fe441f8c0245acf046296ac590f"
HOLDER = "Copyright 2014 The Comic Neue Project Authors (https://github.com/crozynski/comicneue)"
BUBBLES_PROBE = """
const B = require(process.argv[1]);
const item = (who, n) => ({who, n});
const [a1, b1, c1, a2, b2, d1] = [item("A", 1), item("B", 1), item("C", 1), item("A", 2), item("B", 2), item("D", 1)];
const planOf = (head, pending, quiet) => B.plan(head, pending, quiet).map((entry) => [entry.who, entry.item.n, entry.scale]);
const speech = {classes: ["security", "post"]};
console.log(JSON.stringify({
  scales: [0, 1, 2, 3, 4, 9].map(B.scale),
  reveals: [B.reveals(4, 2), B.reveals(5, 1), B.reveals(0, 3)],
  shown: [0, 0.49, 0.5, 1.49, 1.5, 9].map((at) => B.shown(4, 2, at)),
  reading: [0, 4, 5, 9, 180].map(B.reading),
  words: [B.words("  Disk almost\\nfull\\t now  "), B.words(""), B.words(null)],
  plans: [planOf(a1, [b1, c1, a2, b2, d1]), planOf(null, [b1, a1, b2]), planOf(a1, []), planOf(null, [])],
  picked: [{class: "mayday"}, {class: "security"}, {class: "post"}, {class: "broadcast"}].map((row) => B.picked(row, speech)),
  quiet: planOf(a1, [b1], [item("B", 9), item("E", 1), item("F", 1)]),
  admitted: (() => {
    const burst = Array.from({length: 30}, (_, index) => item("ABCDEF"[index % 6], index));
    const first = B.admit([], burst, new Set(["A"]));
    const later = B.admit(first.start.slice(1), first.waiting, new Set());
    return {first: first.start.map((entry) => [entry.who, entry.n]), left: first.waiting.length, later: later.start.map((entry) => [entry.who, entry.n])};
  })(),
  queued: (() => {
    let waiting = [];
    for (let n = 0; n < 35; n += 1) {
      waiting = B.queued(waiting, item("A", n));
    }
    return [waiting.length, waiting[0].n, waiting[waiting.length - 1].n];
  })(),
}));
"""
ROWS_PROBE = """
const fs = require("fs");
const vm = require("vm");
const real = require(process.argv[1]);
const Voice = require(process.argv[2]);
const code = process.argv.slice(3).map((path) => fs.readFileSync(path, "utf8")).join("\\n");
function page(fault) {
  const out = {draws: 0, pumped: [], toasts: []};
  const sandbox = {
    out,
    Bubbles: {
      ...real,
      plan: () => [],
      admit: (...args) => {
        out.draws += 1;
        if (fault && out.draws === 1) {
          throw new Error("draw failed");
        }
        return real.admit(...args);
      },
    },
    Voice: {...Voice, beep: () => null},
    RadioSet: {plan: (row) => (["mayday", "security"].includes(row.class) ? [{kind: "burst"}] : []), ledgerOf: () => null},
    settings: {bubbles: true, notify: false, music: {}},
    radioSet: {mode: "auto", classes: ["mayday", "pan-pan", "security"], sounds: {}, squelch: 1},
    state: {now: 1000, radio: [], inbox: [], pending: [], messages: [], speech: {tts: false, gate: {open: false}}},
    known: {inbox: null, alarms: null, radio: null, batches: new Set(), now: null},
    speech: {pending: [], busy: false, current: null, loading: null, item: null, source: null, timer: 0, warned: 0},
    alarmRows: () => [], live: () => true, keyOf: (item) => item.id, short: (text) => text, dash: (text) => text, undoToast: () => null,
    toast: (title, lines) => out.toasts.push(`${title}: ${lines.join(" ")}`),
    document: {currentScript: null}, performance: {now: () => 0},
    window: {matchMedia: () => ({matches: false}), setTimeout: (run, ms) => (ms ? 0 : run()), clearTimeout: () => null, requestAnimationFrame: () => 0, cancelAnimationFrame: () => null},
  };
  vm.createContext(sandbox);
  vm.runInContext(`${code}
pump = () => out.pumped.push(speech.pending.map((item) => item.cls));
function quietLines() {
  return [...bubbles.quiet, ...bubbles.waiting].map((item) => item.line);
}`, sandbox);
  return sandbox;
}
const row = (line, cls, age) => ({ts: -age, from: line, source: line, to: [], text: line, class: cls});
function batch(rows, fault) {
  const at = page(fault);
  at.state.now = 2000;
  let thrown = null;
  try {
    at.speakRows(rows.map((entry) => ({...entry, ts: 2000 + entry.ts})), true);
  } catch (error) {
    thrown = String(error.message);
  }
  return {thrown, pumped: at.out.pumped, draws: at.out.draws, toasts: at.out.toasts, bubbles: at.quietLines().length};
}
function gap() {
  const at = page(false);
  const poll = (now, rows, resumed) => {
    at.state.now = now;
    at.state.radio = [...at.state.radio, ...rows.map((entry) => ({...entry, ts: now + entry.ts}))];
    at.announce(resumed);
  };
  poll(1000, [], false);
  poll(1010, [row("live", "post", 1)], false);
  poll(1041, [row("late", "post", 1)], false);
  poll(1050, [row("back", "post", 1)], true);
  poll(1060, [row("again", "post", 1)], false);
  poll(1070, [row("fresh", "post", 29), row("stale", "post", 31)], false);
  return at.quietLines();
}
const posts = (count) => Array.from({length: count}, (_, index) => row(`post ${index % 6}`, "post", 2));
console.log(JSON.stringify({
  fault: batch([row("post", "post", 2), row("Sec", "mayday", 1)], true),
  burst: batch([...posts(1000), row("Sec", "mayday", 1)], false),
  speech: batch([...posts(10), row("Docs", "security", 1)], false),
  gap: gap(),
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
  const draw = () => null;
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
    context: () => ({}), drawBubbles: draw, drawSpeaker: draw, wordsRead: () => 0,
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
STUCK_PROBE = """
const fs = require("fs");
const vm = require("vm");
const Bubbles = require(process.argv[1]);
const code = fs.readFileSync(process.argv[2], "utf8");
const rejected = [];
process.on("unhandledRejection", (error) => rejected.push(String(error && error.message)));
const settle = async () => {
  for (let round = 0; round < 5; round += 1) {
    await new Promise((resolve) => setImmediate(resolve));
  }
};
const part = () => ({gain: {value: 0, setValueAtTime: () => null, exponentialRampToValueAtTime: () => null}, frequency: {}, Q: {}, connect: (next) => next});
const audio = {
  sampleRate: 8000, currentTime: 0, destination: {}, createBuffer: (channels, frames) => ({getChannelData: () => new Float32Array(frames)}),
  createBiquadFilter: part, createGain: part, createBufferSource: () => ({...part(), addEventListener: () => null, start: () => null, stop: () => null}),
};
async function run(rule, items) {
  const speech = {pending: [], busy: false, current: null, loading: null, item: null, source: null, timer: 0, warned: 0};
  const timers = new Map();
  const heard = [];
  let [fired, ducked, ids] = [false, false, 0];
  const breaks = {
    reading: () => speech.busy && !speech.current && !speech.timer,
    ended: () => speech.busy && !speech.current && !speech.source && speech.item !== null,
    tail: () => speech.busy && speech.item === null,
  };
  const sandbox = {
    Bubbles, speech, Date, settings: {bubbles: true}, radioSet: {}, SPEECH_QUEUE: 9, SPEECH_QUIET: 0, SOUND_SLACK: 2,
    Voice: {enqueue: (pending, next) => [...pending, next], loudness: () => 1}, RadioSet: {burst: (gain) => ({gain, seconds: 0.6, frequency: 1800, q: 0.9})},
    toast: () => null, context: () => audio, drawBubbles: () => null, performance: {now: () => 1000},
    duck: () => {
      if (rule === "transmit" && !ducked) {
        ducked = true;
        throw new Error("no gain node");
      }
    },
    drawSpeaker: () => {
      if (speech.current && speech.current.who !== heard[heard.length - 1]) {
        heard.push(speech.current.who);
      }
      if (!fired && breaks[rule] && breaks[rule]()) {
        fired = true;
        throw new Error("draw failed");
      }
    },
    window: {
      setTimeout: (next) => {
        ids += 1;
        timers.set(ids, next);
        return ids;
      },
      clearTimeout: (id) => timers.delete(id),
    },
  };
  vm.runInNewContext(code, sandbox);
  items.forEach((item) => sandbox.say(item));
  for (let round = 0; round < 12; round += 1) {
    await settle();
    const due = [...timers.values()];
    timers.clear();
    for (const next of due) {
      try {
        next();
      } catch (error) {
        rejected.push(String(error.message));
      }
    }
  }
  await settle();
  return {faulted: fired || ducked, heard, busy: speech.busy, pending: speech.pending.map((item) => item.who)};
}
(async () => {
  const silent = (who) => ({who, line: "Disk almost full", words: ["Disk", "almost", "full"], silent: true});
  const sounded = (who) => ({who, line: "radio check", steps: [{kind: "burst"}], tone: "direct"});
  console.log(JSON.stringify({
    reading: await run("reading", [silent("A"), silent("B")]),
    ended: await run("ended", [sounded("A"), sounded("B")]),
    tail: await run("tail", [sounded("A"), sounded("B")]),
    transmit: await run("transmit", [sounded("A"), sounded("B")]),
  }));
})();
"""
PAGE_HEAD = """
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
"""
SOUND_PROBE = PAGE_HEAD + """
const settle = async () => {
  for (let round = 0; round < 5; round += 1) {
    await new Promise((resolve) => setImmediate(resolve));
  }
};
const part = () => ({gain: {value: 0, setValueAtTime: () => {}, exponentialRampToValueAtTime: () => {}}, frequency: {}, Q: {}, connect: (next) => next});
const ROW = {who: "A", line: "Disk almost full", words: ["Disk", "almost", "full"]};
async function transmitted(steps, cut, row = ROW, broken = "") {
  const layer = new Node({class: "bubbles"});
  layer.append(new Node({class: "bubble-bar"}));
  const clock = {now: 1000};
  const [ends, made, counts, states] = [[], [], [], []];
  const timers = new Map();
  const item = {...row, steps};
  const audio = {
    sampleRate: 8000, currentTime: 0, destination: {}, createBuffer: (channels, frames) => ({getChannelData: () => new Float32Array(frames)}),
    createBiquadFilter: part, createGain: part, decodeAudioData: async () => ({duration: 1}),
    createBufferSource: () => ({...part(), addEventListener: (name, run) => ends.push(run), start: () => {}, stop: () => {}}),
  };
  const context = {
    Bubbles, item, counts, states, made, broken, thrown: [], settings: {bubbles: true}, radioSet: {}, SPEECH_QUEUE: 9, SPEECH_QUIET: 0, SOUND_SLACK: 2,
    speech: {pending: [], busy: false, current: null, loading: null, item: null, source: null, timer: 0, warned: 0},
    document: {getElementById: () => layer, querySelectorAll: () => [], fonts: {add: () => null}},
    window: {
      innerWidth: 1366, innerHeight: 768, requestAnimationFrame: () => 1, cancelAnimationFrame: () => null, clearTimeout: () => null,
      setTimeout: (run) => {
        timers.set(timers.size + 1, run);
        return timers.size;
      },
    },
    performance: {now: () => clock.now}, CSS: {escape: (value) => value}, g3: {tab: "stream"}, anchor3d: () => () => null,
    h: (tag, attrs, ...children) => {
      const node = new Node(attrs);
      node.append(...children);
      if (node.classes.has("speech-bubble")) {
        made.push(node);
      }
      return node;
    },
    nameOf: (key) => key, fixed: (value) => value.toFixed(1), FontFace: class {}, toast: () => null, context: () => audio,
    duck: () => {
      if (broken === "duck") {
        throw new Error("no gain node");
      }
    },
    fetch: async (url, options) => (JSON.parse(options.body).text === "fails"
      ? {ok: false, status: 500, headers: {get: () => "text/plain"}, text: async () => "tts down"}
      : {ok: true, status: 200, headers: {get: () => "audio/wav"}, arrayBuffer: async () => ({})}),
    Voice: {enqueue: (pending, next) => [...pending, next], loudness: () => 1}, RadioSet: {burst: (gain) => ({gain, seconds: 0.6, frequency: 1800, q: 0.9})},
  };
  vm.runInNewContext(`${code}
function drawSpeaker() {
  if (broken === "ended" && !speech.source && !speech.current && !thrown.length) {
    thrown.push("draw failed");
    throw new Error("draw failed");
  }
  drawBubbles();
  counts.push(wordsRead(item));
  const node = made.find((entry) => entry.dataset.who === item.who);
  states.push(node ? node.dataset.state : null);
}
say(item);`, context);
  await settle();
  while (ends.length) {
    clock.now += 500;
    context.drawSpeaker();
    if (cut && item.playing === "speech") {
      Object.assign(item, {cut: true, steps: [...item.steps.slice(0, item.at), {kind: "burst"}]});
    }
    ends.splice(0).forEach((run) => {
      try {
        run();
      } catch (error) {
        context.thrown.push(String(error.message));
      }
    });
    await settle();
  }
  clock.now += 2000;
  context.drawSpeaker();
  const mine = made.filter((node) => node.dataset.who === item.who);
  const text = mine.length ? mine[0].querySelector(".bubble-words").textContent : null;
  const found = {nodes: mine.length, leaving: mine.some((node) => node.classes.has("leaving")), counts: [...counts], states: [...states], text, reading: context.speech.current === item && Boolean(context.speech.timer)};
  if (context.speech.timer) {
    timers.get(context.speech.timer)();
    await settle();
  }
  context.drawBubbles();
  return {...found, after: {cleared: context.speech.item === null && context.speech.current === null, busy: context.speech.busy, left: mine.every((node) => node.classes.has("leaving"))}};
}
(async () => {
  const [word, speech] = [{kind: "word", text: "W"}, {kind: "speech", text: "t"}];
  console.log(JSON.stringify({
    quiet: await transmitted([word, {kind: "burst"}], false),
    burst: await transmitted([{kind: "burst"}], false),
    fallback: await transmitted([word, {kind: "speech", text: "fails"}], false),
    cut: await transmitted([word, speech], true),
    auto: await transmitted([word, speech], false),
    check: await transmitted([{kind: "speech", text: "fails"}], false, {who: "Operator", line: "radio check"}),
    silent: await transmitted([], false, {...ROW, silent: true}),
    rejected: await transmitted([{kind: "burst"}], false, ROW, "duck"),
    faulty: await transmitted([{kind: "burst"}], false, ROW, "ended"),
  }));
})();
"""
STOP_PROBE = PAGE_HEAD + """
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
const playing = {who: "A", line: "Disk almost full", words: ["Disk", "almost", "full"], started: 1000, duration: 3, floor: 0};
const next = {who: "B", line: "Gate green", words: ["Gate", "green"]};
const quiet = {who: "C", line: "Docs green", words: ["Docs", "green"], silent: true};
Object.assign(speech, {current: playing, item: playing, busy: true, source: {stop: () => { stops += 1; }}, pending: [next, quiet]});
drawBubbles();
const before = layer.querySelectorAll(".speech-bubble").length;
${scenario}
frames.splice(0).forEach((frame) => frame());
out = {before, after: layer.querySelectorAll(".speech-bubble").length, shown: bubbles.shown.size, stops, current: speech.current === playing, busy: speech.busy,
  pending: speech.pending.map((item) => item.who), hidden: layer.hidden, pressed: toggle.attrs["aria-pressed"] || null};`, context);
  return context.out;
}
console.log(JSON.stringify({
  stop: run("cancelSpeech();"),
  off: run("settings.bubbles = false;\\nsyncBubbles();"),
  dropped: run("Object.assign(speech, {current: quiet, item: quiet, timer: 5, pending: []});\\nsettings.bubbles = false;\\nsyncBubbles();\\nsettings.bubbles = true;\\nsyncBubbles();"),
}));
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

    def test_a_silent_bubble_shows_beside_the_speech_queue_only_for_an_agent_the_queue_leaves_free(
        self,
    ):
        self.assertEqual(
            self.data["quiet"],
            [["A", 1, 1], ["B", 1, 0.8], ["E", 1, 0.8], ["F", 1, 0.8]],
        )

    def test_a_burst_of_thirty_silent_bubbles_shows_at_most_three_at_once_one_per_agent_and_the_rest_wait_in_order(
        self,
    ):
        self.assertEqual(
            self.data["admitted"],
            {"first": [["B", 1], ["C", 2], ["D", 3]], "left": 27, "later": [["A", 0]]},
        )

    def test_at_most_thirty_silent_bubbles_wait_and_the_oldest_go_first(self):
        self.assertEqual(self.data["queued"], [30, 5, 34])


class TestRowsReachSpeechBeforeAnyDraw(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        done = subprocess.run(
            [
                "node",
                "-e",
                ROWS_PROBE,
                str(BUBBLES),
                str(VOICE),
                str(CONSTANTS),
                str(LAYER),
                str(SPEECH),
                str(ALERTS),
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        cls.data = json.loads(done.stdout)

    def test_a_throwing_redraw_never_costs_the_mayday_of_the_same_batch_its_speech(
        self,
    ):
        self.assertEqual(
            self.data["fault"],
            {
                "thrown": None,
                "pumped": [["mayday"]],
                "draws": 1,
                "toasts": ["Drawing speech bubbles failed: draw failed"],
                "bubbles": 1,
            },
        )

    def test_a_batch_of_a_thousand_silent_rows_queues_the_mayday_and_draws_once(
        self,
    ):
        self.assertEqual(
            self.data["burst"],
            {
                "thrown": None,
                "pumped": [["mayday"]],
                "draws": 1,
                "toasts": [],
                "bubbles": 30,
            },
        )

    def test_silent_rows_never_enter_the_speech_queue(self):
        self.assertEqual(self.data["speech"]["pumped"], [["security"]])

    def test_no_silent_bubble_after_a_poll_gap_over_30_s_a_reconnect_or_for_a_row_older_than_30_s(
        self,
    ):
        self.assertEqual(self.data["gap"], ["live", "again", "fresh"])


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


class TestTransmission(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        done = subprocess.run(["node", "-e", SOUND_PROBE, str(BUBBLES), str(SPEECH), str(LAYER)], capture_output=True, text=True, timeout=60, check=True)
        cls.data = json.loads(done.stdout)

    def test_one_bubble_node_carries_a_row_through_every_sound_into_its_silent_reading(self):
        for case in ("quiet", "burst", "fallback", "cut", "silent", "rejected", "faulty"):
            with self.subTest(case=case):
                found = self.data[case]
                self.assertEqual((found["nodes"], found["leaving"], found["reading"]), (1, False, True), found)

    def test_a_spoken_row_keeps_its_one_node_until_the_speech_ends_and_then_fades(self):
        found = self.data["auto"]
        self.assertEqual((found["nodes"], found["leaving"], found["reading"]), (1, True, False), found)

    def test_the_speech_reveals_the_line_a_procedure_word_none_of_it_and_a_burst_or_the_silent_reading_the_rest_at_reading_pace(self):
        expected = {
            "quiet": [0, 0, 0, 1, 2, 2, 2, 3],
            "burst": [1, 2, 2, 2, 3],
            "fallback": [0, 0, 0, 1, 2, 2, 2, 3],
            "cut": [0, 0, 0, 1, 2, 2, 3, 3, 3, 3, 3],
            "auto": [0, 0, 0, 1, 2, 2, 2, 3],
            "check": [1, 2, 2, 2, 2],
            "silent": [1, 3],
            "rejected": [1, 2, 3],
            "faulty": [1, 2, 2, 3],
        }
        self.assertEqual({case: found["counts"] for case, found in self.data.items()}, expected)

    def test_the_words_shown_never_go_back(self):
        for case, found in self.data.items():
            with self.subTest(case=case):
                self.assertEqual(found["counts"], sorted(found["counts"]), found)

    def test_every_row_ends_cleared_with_its_bubble_leaving_once_its_reading_time_is_over(self):
        for case, found in self.data.items():
            with self.subTest(case=case):
                self.assertEqual(found["after"], {"cleared": True, "busy": False, "left": True}, found)

    def test_the_bubble_of_the_sounding_row_speaks_throughout(self):
        for case, found in self.data.items():
            with self.subTest(case=case):
                self.assertEqual(set(found["states"]), {"speaking"}, found)

    def test_a_radio_check_without_words_shows_its_line_during_the_burst_that_stands_in_for_it(self):
        found = self.data["check"]
        self.assertEqual((found["nodes"], found["text"], found["leaving"], found["reading"]), (1, "radio check", True, False), found)


class TestQueueSurvivesAFault(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        done = subprocess.run(
            ["node", "-e", STUCK_PROBE, str(BUBBLES), str(SPEECH)],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        cls.data = json.loads(done.stdout)

    def test_a_fault_while_a_row_sounds_or_is_read_still_hands_the_queue_to_the_next_row(
        self,
    ):
        for case, heard in (
            ("reading", ["A", "B"]),
            ("ended", ["A", "B"]),
            ("tail", ["A", "B"]),
            ("transmit", ["B"]),
        ):
            with self.subTest(case=case):
                self.assertEqual(
                    self.data[case],
                    {"faulted": True, "heard": heard, "busy": False, "pending": []},
                    self.data[case],
                )


class TestBubbleStop(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        done = subprocess.run(["node", "-e", STOP_PROBE, str(BUBBLES), str(SPEECH), str(LAYER)], capture_output=True, text=True, timeout=60, check=True)
        cls.data = json.loads(done.stdout)

    def test_stop_speaking_clears_every_bubble_at_once_and_stops_the_audio(self):
        self.assertEqual(self.data["stop"], {"before": 3, "after": 0, "shown": 0, "stops": 1, "current": False, "busy": True, "pending": [], "hidden": False, "pressed": None})

    def test_switching_the_bubbles_off_clears_the_layer_and_leaves_the_audible_item_playing(self):
        self.assertEqual(self.data["off"], {"before": 3, "after": 0, "shown": 0, "stops": 0, "current": True, "busy": True, "pending": ["B"], "hidden": True, "pressed": "false"})

    def test_switching_the_bubbles_off_during_a_silent_reading_leaves_no_bubble_when_they_come_back(self):
        self.assertEqual(self.data["dropped"], {"before": 3, "after": 0, "shown": 0, "stops": 0, "current": False, "busy": False, "pending": [], "hidden": False, "pressed": "true"})


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
