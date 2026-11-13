from __future__ import annotations

import json
import subprocess
import unittest

from hub_support import HUB
from kvb_orchestrator import council

RADIOSET = HUB / "templates" / "radioset.js"
PROBE = """
const R = require(process.argv[1]);
const input = JSON.parse(process.argv[2]);
const out = {};
for (const [name, args] of Object.entries(input)) {
  out[name] = args.map((call) => R[call[0]](...call.slice(1)));
}
out.constants = {key: R.KEY, modes: R.MODES, tones: R.TONES, classes: R.CLASSES, tabs: R.TABS, chips: R.CHIPS, defaults: R.DEFAULTS};
console.log(JSON.stringify(out));
"""
PAGE_LOAD = HUB / "templates" / "page-load.js"
STALE_PROBE = """
const fs = require("fs");
const vm = require("vm");
const code = fs.readFileSync(process.argv[1], "utf8");
const stub = () => undefined;
const settle = async () => {
  for (let round = 0; round < 8; round += 1) {
    await new Promise((resolve) => setImmediate(resolve));
  }
};
function page() {
  const pending = [];
  const announced = [];
  const timers = [];
  const fetch = (url, options) => new Promise((resolve, reject) => {
    pending.push({resolve, reject});
    if (options && options.signal) {
      options.signal.addEventListener("abort", () => reject(new Error("aborted")));
    }
  });
  const context = {
    fetch, AbortController, STATE_TIMEOUT: 15000, windowQuery: () => "", FADE: 0, MOVE: 0,
    state: {now: 0, radio: []}, ui: {offline: false}, settingsSig: "", motion: {current: new Map([[1, 1]]), asOf: null},
    window: {getSelection: () => "", setTimeout: (run, ms) => timers.push({run, ms}), clearTimeout: stub}, document: {hidden: false},
    adoptSettings: stub, tuneMusic: stub, drawSky: stub, render: stub, drawTime: stub, drawAgent: stub, drawStream: stub, relayout: stub, pulses: stub, tick: stub,
  };
  context.announce = () => announced.push(context.state.now);
  vm.runInNewContext(code, context);
  return {context, pending, announced, timers};
}
const answer = (now) => ({ok: true, json: async () => ({now, radio: []})});
(async () => {
  const slow = page();
  slow.context.load();
  for (let ticket = 1; ticket <= 6; ticket += 1) {
    slow.context.load();
    slow.pending[ticket - 1].resolve(answer(ticket));
    await settle();
  }
  slow.pending[6].resolve(answer(7));
  await settle();
  const stale = page();
  stale.context.load();
  stale.context.load();
  stale.pending[1].resolve(answer(3));
  await settle();
  stale.pending[0].resolve(answer(2));
  await settle();
  const failing = page();
  failing.context.load();
  failing.context.load();
  failing.pending[1].resolve(answer(5));
  await settle();
  failing.pending[0].reject(new Error("503"));
  await settle();
  const lateError = failing.context.ui.offline;
  failing.context.load();
  failing.pending[2].reject(new Error("503"));
  await settle();
  const polling = page();
  polling.context.load();
  polling.context.poll();
  const busy = polling.pending.length;
  polling.pending[0].resolve(answer(1));
  await settle();
  polling.context.poll();
  const hung = page();
  for (let tick = 0; tick < 60; tick += 1) {
    hung.context.poll();
    await settle();
  }
  const stuck = [hung.pending.length, hung.context.ui.offline];
  hung.timers.forEach((timer) => timer.run());
  await settle();
  hung.context.poll();
  console.log(JSON.stringify({
    slow: slow.announced, stale: [stale.context.state.now, stale.announced], errors: [lateError, failing.context.ui.offline], polls: [busy, polling.pending.length],
    hung: {stuck, freed: [hung.pending.length, hung.context.ui.offline], waits: hung.timers.map((timer) => timer.ms)},
  }));
})();
"""
PAGE_SPEECH = HUB / "templates" / "page-speech.js"
PAGE_RADIOVIEW = HUB / "templates" / "page-radioview.js"
TRANSMIT_PROBE = """
const fs = require("fs");
const vm = require("vm");
const RadioSet = require(process.argv[1]);
const speechCode = fs.readFileSync(process.argv[2], "utf8");
const viewCode = fs.readFileSync(process.argv[3], "utf8");
const stub = () => undefined;
const settle = async () => {
  for (let round = 0; round < 40; round += 1) {
    await new Promise((resolve) => setImmediate(resolve));
  }
};
const row = {class: "security", source: "s1", voice: "v1", word: "W", rest: "R", text: "t"};
async function queued(flip) {
  const heard = [];
  const sandbox = {
    RadioSet, radioSet: RadioSet.valid({mode: "auto"}), state: {speech: {tts: true, gate: {open: true}}},
    speech: {pending: [], busy: false, current: null, source: null, item: null, timer: 0}, settings: {bubbles: false}, SPEECH_QUEUE: 9,
    Voice: {enqueue: (pending, next) => [...pending, next]}, drawBubbles: stub, drawSpeaker: stub,
  };
  vm.runInNewContext(speechCode, sandbox);
  sandbox.context = () => ({});
  sandbox.spoken = async (audio, item, step) => {
    heard.push(step.text);
    if (heard.length === 1 && flip) {
      sandbox.radioSet = RadioSet.valid({mode: flip});
    }
    return "";
  };
  sandbox.burst = async () => {
    heard.push("burst");
  };
  sandbox.say({row});
  sandbox.say({row});
  await settle();
  return heard;
}
async function stalled() {
  const waits = [];
  const sandbox = {
    speech: {current: null, source: null}, SOUND_SLACK: 2, performance: {now: () => 0}, duck: stub, drawSpeaker: stub,
    window: {setTimeout: (run, ms) => waits.push({run, ms}), clearTimeout: stub},
  };
  vm.runInNewContext(speechCode, sandbox);
  let done = false;
  let stops = 0;
  const source = {addEventListener: stub, stop: () => {
    stops += 1;
  }};
  sandbox.sounded({}, source, 0.5).then(() => {
    done = true;
  });
  await settle();
  const before = [done, sandbox.speech.source === source];
  waits.forEach((wait) => wait.run());
  await settle();
  return {before, after: [done, sandbox.speech.source], waits: waits.map((wait) => wait.ms), stops};
}
function pressed() {
  const calls = [];
  const sandbox = {RadioSet, h: (tag, attrs, ...children) => ({tag, attrs: attrs || {}, children: children.flat()}), icon: (name) => name, named: (label, hint) => ({"aria-label": label, title: hint})};
  vm.runInNewContext(`${viewCode}\\nradioDom = {};`, sandbox);
  sandbox.knobs = () => [];
  sandbox.context = () => calls.push("context");
  sandbox.keepRadio = (change) => calls.push(change);
  const modes = sandbox.faceplate().children.find((child) => child.attrs["aria-label"] === "Mode");
  modes.children.forEach((button) => button.attrs.on.click());
  return calls;
}
(async () => {
  console.log(JSON.stringify({
    auto: await queued(""), silence: await queued("silence"), quiet: await queued("quiet"), stalled: await stalled(), pressed: pressed(),
  }));
})();
"""
VOICE_JS = HUB / "templates" / "voice.js"
MODES_PROBE = """
const fs = require("fs");
const vm = require("vm");
const RadioSet = require(process.argv[1]);
const Voice = require(process.argv[2]);
const code = fs.readFileSync(process.argv[3], "utf8");
const stub = () => undefined;
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const until = async (check) => {
  for (let round = 0; round < 500 && !check(); round += 1) {
    await wait(1);
  }
};
const WORD = "MAYDAY MAYDAY MAYDAY";
const rest = (id) => `this is ${id}, over`;
function radio({running = true, hold = "", long = "", fail = 0, scale = 1000, bubbles = false} = {}) {
  const run = {log: [], releases: [], gesture: running, sources: [], beeps: 0, reads: 0};
  class Source {
    constructor() {
      Object.assign(this, {buffer: null, ended: null, stopped: false, audible: false});
    }
    connect(node) {
      return node;
    }
    addEventListener(type, ended) {
      this.ended = ended;
    }
    label() {
      return this.buffer && this.buffer.text ? this.buffer.text : "burst";
    }
    start() {
      run.sources.push(this);
      if (audio.state === "running") {
        audio.play(this);
      }
    }
    stop(when) {
      if (when === undefined && !this.stopped) {
        this.stopped = true;
        run.log.push(["stop", this.label()]);
        setImmediate(() => this.ended && this.ended());
      }
    }
  }
  const audio = {
    state: running ? "running" : "suspended", currentTime: 0, sampleRate: 8000, destination: {},
    play(source) {
      if (!source.audible && !source.stopped) {
        source.audible = true;
        run.log.push(["audible", source.label(), sandbox.radioSet.mode]);
        if (source.label() !== long) {
          setImmediate(() => source.ended && source.ended());
        }
      }
    },
    resume() {
      if (run.gesture) {
        audio.state = "running";
        run.sources.forEach((source) => audio.play(source));
      }
      return Promise.resolve();
    },
    createBufferSource: () => new Source(),
    createGain: () => ({gain: {value: 0, setValueAtTime: stub, exponentialRampToValueAtTime: stub}, connect: (node) => node}),
    createBiquadFilter: () => ({type: "", frequency: {value: 0}, Q: {value: 0}, connect: (node) => node}),
    createBuffer: (channels, frames) => ({getChannelData: () => new Float32Array(frames)}),
    decodeAudioData: async (data) => ({duration: data.text === long ? 60 : 1, text: data.text}),
  };
  const sandbox = {
    RadioSet, Voice, radioSet: RadioSet.valid(null), state: {now: 1000, messages: [], speech: {tts: true, gate: {open: true}}},
    speech: {pending: [], busy: false, warned: 0, current: null, source: null, loading: null, timer: 0, item: null},
    settings: {bubbles, music: {on: false, volume: 0.4}}, SPEECH_QUEUE: 20, SPEECH_QUIET: 60000, SOUND_SLACK: 2, HUMAN: "Operator", Bubbles: {reading: () => 0.001},
    keep: stub, drawRadioSet: stub, drawBubbles: stub, drawSpeaker: stub, duck: stub, clearBubbles: stub, toast: (title) => run.log.push(["toast", title]),
    silenceBeeps: () => {
      run.beeps += 1;
    },
    performance: {now: () => 0}, window: {setTimeout: (next, ms) => setTimeout(next, ms / scale), clearTimeout: (id) => clearTimeout(id)},
    context: () => {
      if (audio.state === "suspended") {
        audio.resume();
      }
      return audio;
    },
    fetch: async (url, options) => {
      const text = JSON.parse(options.body).text;
      run.log.push(["tts", text]);
      if (text === hold) {
        await new Promise((resolve) => run.releases.push(resolve));
      }
      if (fail && text !== WORD) {
        return {ok: false, status: fail, headers: {get: () => (fail === 503 ? "application/json" : "text/plain")}, text: async () => (fail === 503 ? "{\\"reason\\": \\"busy\\"}" : "piper failed")};
      }
      return {ok: true, status: 200, headers: {get: () => "audio/wav"}, arrayBuffer: async () => ({text}), text: async () => ""};
    },
  };
  vm.runInNewContext(code, sandbox);
  const read = sandbox.readSilently;
  sandbox.readSilently = (item, next) => {
    run.reads += 1;
    read(item, next);
  };
  run.state = sandbox.state;
  run.finish = () => run.sources.filter((source) => source.audible && !source.stopped).forEach((source) => source.ended && source.ended());
  run.say = (id) => sandbox.say({row: {class: "mayday", word: WORD, rest: rest(id), voice: "v", source: id, from: id, to: [], text: "help", ts: 1000}, voice: "v", tone: "mayday", cls: "mayday", who: id, line: "help", words: [], silent: false});
  run.press = (mode) => {
    sandbox.keepRadio({mode});
    sandbox.context();
  };
  run.keep = (change) => sandbox.keepRadio(change);
  run.heard = () => run.log.filter(([event]) => event === "audible").map(([, text, mode]) => [text, mode]);
  run.stops = () => run.log.filter(([event]) => event === "stop").map(([, text]) => text);
  run.idle = () => !sandbox.speech.busy && !sandbox.speech.pending.length;
  return run;
}
async function pressedWhilePlaying(long, count, mode) {
  const run = radio({long});
  run.say("A");
  await until(() => run.heard().length === count);
  run.press(mode);
  await wait(20);
  return {heard: run.heard(), stops: run.stops()};
}
async function failedWhileRendering(fail, mode) {
  const run = radio({hold: rest("A"), fail});
  run.say("A");
  await until(() => run.releases.length);
  run.press(mode);
  run.releases.forEach((release) => release());
  await until(run.idle);
  await wait(10);
  return run.heard();
}
(async () => {
  const inflight = radio({hold: rest("A")});
  inflight.say("A");
  await until(() => inflight.releases.length);
  inflight.press("silence");
  inflight.releases.forEach((release) => release());
  await until(inflight.idle);
  const playing = await pressedWhilePlaying(rest("A"), 2, "silence");
  const word = await pressedWhilePlaying(WORD, 1, "silence");
  const quiet = await pressedWhilePlaying(rest("A"), 2, "quiet");
  const failed = {
    silence503: await failedWhileRendering(503, "silence"), silence500: await failedWhileRendering(500, "silence"), quiet503: await failedWhileRendering(503, "quiet"),
  };
  const kept = radio({fail: 500, long: "burst", scale: 10});
  kept.say("A");
  await until(() => kept.heard().length === 2);
  kept.keep({squelch: 0.5});
  kept.keep({log: {tab: "all", chips: {}, q: "gate"}});
  await wait(20);
  const fallback = {heard: kept.heard(), stops: kept.stops()};
  const beeper = radio({});
  beeper.press("quiet");
  const quietBeeps = beeper.beeps;
  beeper.press("silence");
  const silenceBeeps = beeper.beeps;
  beeper.keep({squelch: 0.5});
  beeper.press("silence");
  const beeps = [quietBeeps, silenceBeeps, beeper.beeps];
  const natural = {};
  for (const flag of ["open", "tts"]) {
    const run = radio({long: rest("A"), bubbles: true});
    run.say("A");
    await until(() => run.heard().length === 2);
    if (flag === "open") {
      run.state.speech.gate = {open: false};
    } else {
      run.state.speech.tts = false;
    }
    run.finish();
    await until(run.idle);
    await wait(10);
    natural[flag] = {heard: run.heard(), reads: run.reads};
  }
  const renderedRun = radio({hold: rest("A")});
  renderedRun.say("A");
  await until(() => renderedRun.releases.length);
  renderedRun.state.speech.gate = {open: false};
  renderedRun.releases.forEach((release) => release());
  await until(renderedRun.idle);
  await wait(10);
  const renderedLine = renderedRun.heard();
  const suspended = radio({running: false});
  suspended.say("B");
  suspended.say("C");
  await until(suspended.idle);
  const started = suspended.sources.length;
  suspended.gesture = true;
  suspended.press("silence");
  await wait(20);
  console.log(JSON.stringify({
    inflight: {tts: inflight.log.filter(([event]) => event === "tts").map(([, text]) => text), heard: inflight.heard()},
    playing, word, quiet, failed, fallback, beeps, natural, renderedLine, suspended: {started, heard: suspended.heard(), stopped: suspended.sources.filter((source) => source.stopped).length},
  }));
})();
"""
PAGE_ALERTS = HUB / "templates" / "page-alerts.js"
BEEPS_PROBE = """
const fs = require("fs");
const vm = require("vm");
const code = fs.readFileSync(process.argv[1], "utf8");
const stub = () => undefined;
const stops = [];
let made = 0;
const audio = {
  currentTime: 0, destination: {},
  createOscillator: () => {
    made += 1;
    return {type: "", frequency: {value: 0}, connect: (node) => node, addEventListener: stub, start: stub, stop: (when) => stops.push(when === undefined ? "now" : "scheduled")};
  },
  createGain: () => ({gain: {setValueAtTime: stub, exponentialRampToValueAtTime: stub}, connect: (node) => node}),
};
const sandbox = {TONES: {mayday: [[880, 0, 0.2], [660, 0.25, 0.2]], radio: [[440, 0, 0.1]]}, duck: stub, context: () => audio};
vm.runInNewContext(code, sandbox);
sandbox.play("mayday", 0.8);
sandbox.play("radio", 0.5);
const now = () => stops.filter((kind) => kind === "now").length;
const queued = [made, now()];
sandbox.silenceBeeps();
const silenced = now();
sandbox.silenceBeeps();
console.log(JSON.stringify({queued, silenced, again: now()}));
"""
HUMAN = "Operator"
WORD = "MAYDAY MAYDAY MAYDAY"
ROWS = {
    "mayday": {"class": "mayday", "source": "s1", "voice": "v1", "word": WORD, "rest": "this is Docs Docs Docs, disk full, over"},
    "security": {"class": "security", "source": "s2", "voice": "v2", "word": "say-cure-ee-tay say-cure-ee-tay say-cure-ee-tay", "rest": "all stations, this is Stage, rotate, over"},
    "post": {"class": "post", "source": "s2", "voice": "v2", "word": "", "rest": "Operator, Operator, this is Stage, ready, over"},
    "muted": {"class": "security", "source": "s9", "voice": "v9", "word": "say-cure-ee-tay say-cure-ee-tay say-cure-ee-tay", "rest": "all stations, this is Muted, x, over"},
    "voiceless": {"class": "post", "source": "s3", "voice": "", "word": "", "rest": "x"},
}
LOG = [
    {"ts": 10, "from": "Operator", "to": ["Stage"], "class": "post", "text": "rebase please"},
    {"ts": 20, "from": "Stage", "to": ["Operator"], "class": "call", "text": "gate red on main"},
    {"ts": 30, "from": "Docs", "to": [], "class": "newsletter", "text": "docs are green"},
    {"ts": 40, "from": "Stage", "to": ["Skills"], "class": "post", "text": "rebase done"},
    {"ts": 50, "from": "Operator", "to": [], "class": "broadcast", "text": "deploy now"},
    {"ts": 60, "from": "Docs", "to": ["Skills"], "class": "pan-pan", "text": "Gate slow"},
    {"ts": 70, "from": "Skills", "to": ["Docs"], "class": "call", "text": "which gate"},
    {"ts": 80, "from": "Operator", "to": [], "class": "broadcast", "text": "spoofed order"},
]
MESSAGES = [
    {"id": "a" * 16, "to": "Stage", "text": "rebase please", "created_ts": 10, "class": "post", "voice": "v0"},
    {"id": "b" * 16, "to": "*", "text": "deploy now", "created_ts": 50, "class": "broadcast", "voice": "v0"},
]


def run(calls: dict[str, list[list]]) -> dict:
    done = subprocess.run(["node", "-e", PROBE, str(RADIOSET), json.dumps(calls)], capture_output=True, text=True, timeout=60, check=True)
    return json.loads(done.stdout)


class TestRadioSetModule(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        defaults = {"mode": "auto", "classes": ["mayday", "pan-pan", "security"], "muted": ["s9"], "sounds": {}, "squelch": 1, "log": {}}
        modes = ("auto", "quiet", "silence")
        lives = ({"tts": True, "open": True}, {"tts": True, "open": False}, {"tts": False, "open": True})
        plans = [["plan", ROWS[name], {**defaults, "mode": mode}, live] for mode in modes for live in lives for name in ROWS]
        plans += [["plan", ROWS["post"], {**defaults, "classes": ["mayday", "post"]}, lives[0]], ["plan", ROWS["post"], {**defaults, "classes": ["mayday", "post"], "mode": "quiet"}, lives[0]]]
        stored = [
            None, "broken", [], {"mode": "loud", "squelch": 2, "classes": ["post"], "muted": ["s2", "s2", "", 7, "s1"], "sounds": {"radio": {"on": "yes", "volume": 0.4}, "review": {"on": False, "volume": -1}}},
            {"mode": "quiet", "squelch": 0, "classes": ["security", "shout", "post", "call", "newsletter", "broadcast", "pan-pan"], "log": {"tab": "sent", "chips": {"class": "post", "from": 7, "to": "x" * 201}, "q": "gate"}},
        ]
        entries = [
            {"tab": "all", "chips": {"class": "", "from": "", "to": "", "agent": ""}, "q": ""},
            {"tab": "sent", "chips": {"class": "", "from": "", "to": "", "agent": ""}, "q": ""},
            {"tab": "received", "chips": {"class": "", "from": "", "to": "", "agent": ""}, "q": ""},
            {"tab": "all", "chips": {"class": "post", "from": "", "to": "", "agent": ""}, "q": ""},
            {"tab": "all", "chips": {"class": "", "from": "Stage", "to": "", "agent": ""}, "q": ""},
            {"tab": "all", "chips": {"class": "", "from": "", "to": "Skills", "agent": ""}, "q": ""},
            {"tab": "all", "chips": {"class": "", "from": "", "to": "", "agent": "Docs"}, "q": ""},
            {"tab": "all", "chips": {"class": "", "from": "", "to": "", "agent": ""}, "q": "GATE"},
            {"tab": "all", "chips": {"class": "call", "from": "", "to": "", "agent": "Skills"}, "q": "gate"},
            {"tab": "received", "chips": {"class": "", "from": "", "to": "", "agent": "Stage"}, "q": "rebase"},
        ]
        cls.data = run({
            "plans": plans,
            "stored": [["valid", value] for value in stored],
            "logs": [["logRows", LOG, entry, HUMAN, MESSAGES] for entry in entries],
            "counts": [["counts", LOG, HUMAN, MESSAGES]],
            "ledger": [["ledgerOf", {"text": f"deploy now [kvb-orchestrator msg {'b' * 16}]"}, MESSAGES], ["ledgerOf", {"text": f"forged [kvb-orchestrator msg {'c' * 16}]"}, MESSAGES], ["ledgerOf", LOG[-1], MESSAGES]],
            "choices": [["choices", LOG]],
            "cleared": [["cleared", entries[8]]],
            "bursts": [["burst", 0.45], ["burst", 0]],
        })
        cls.modes, cls.lives = modes, lives

    def plan(self, mode: str, live: int, name: str) -> list[dict]:
        index = (self.modes.index(mode) * len(self.lives) + live) * len(ROWS) + list(ROWS).index(name)
        return self.data["plans"][index]

    def test_auto_speaks_below_the_threshold_and_bursts_above_it_or_without_tts(self):
        word = {"kind": "word", "text": WORD}
        self.assertEqual(self.plan("auto", 0, "mayday"), [word, {"kind": "speech", "text": ROWS["mayday"]["rest"]}])
        self.assertEqual(self.plan("auto", 1, "mayday"), [word, {"kind": "burst"}])
        self.assertEqual(self.plan("auto", 2, "mayday"), [{"kind": "burst"}])
        self.assertEqual(self.plan("auto", 0, "security")[0]["kind"], "word")
        self.assertEqual(self.data["plans"][-2], [{"kind": "speech", "text": ROWS["post"]["rest"]}])

    def test_quiet_never_asks_for_speech_except_the_procedure_word(self):
        for live in range(len(self.lives)):
            for name in ("mayday", "security"):
                with self.subTest(live=live, name=name):
                    plan = self.plan("quiet", live, name)
                    self.assertEqual(plan[-1], {"kind": "burst"})
                    self.assertEqual([step["kind"] for step in plan[:-1]], ["word"] if self.lives[live]["tts"] else [])
        self.assertEqual(self.data["plans"][-1], [{"kind": "burst"}])

    def test_silence_plays_only_the_procedure_word(self):
        for live in range(len(self.lives)):
            with self.subTest(live=live):
                self.assertEqual(self.plan("silence", live, "mayday"), [{"kind": "word", "text": WORD}] if self.lives[live]["tts"] else [])
                self.assertEqual(self.plan("silence", live, "post"), [])

    def test_the_read_aloud_filters_skip_classes_and_muted_agents_but_never_a_mayday(self):
        for mode in self.modes:
            for live in range(len(self.lives)):
                with self.subTest(mode=mode, live=live):
                    self.assertEqual(self.plan(mode, live, "post"), [])
                    self.assertEqual(self.plan(mode, live, "muted"), [])
                    self.assertEqual(self.plan(mode, live, "voiceless"), [])
        self.assertNotEqual(self.plan("auto", 0, "security"), [])

    def test_the_burst_is_band_passed_noise_of_about_0_6_seconds_at_the_given_loudness(self):
        loud, silent = self.data["bursts"]
        self.assertTrue(0.4 <= loud["seconds"] <= 0.8, loud)
        self.assertEqual((loud["gain"], silent["gain"]), (0.45, 0))
        self.assertTrue(300 <= loud["frequency"] <= 3400 and loud["q"] > 0, loud)

    def test_the_stored_radio_set_is_normalised_and_mayday_stays_read_aloud(self):
        defaults = self.data["constants"]["defaults"]
        empty, broken, listed, wrong, chosen = self.data["stored"]
        self.assertEqual((empty, broken, listed), (defaults, defaults, defaults))
        self.assertEqual(defaults["mode"], "auto")
        self.assertEqual(self.data["constants"]["key"], "kvb-orchestrator.radio")
        self.assertEqual((wrong["mode"], wrong["squelch"], wrong["classes"], wrong["muted"]), ("auto", 1, ["post", "mayday"], ["s1", "s2"]))
        self.assertEqual(wrong["sounds"]["radio"], {"on": False, "volume": 0.4})
        self.assertEqual(wrong["sounds"]["review"], {"on": False, "volume": 0.6})
        self.assertEqual((chosen["mode"], chosen["squelch"], chosen["classes"]), ("quiet", 0, list(council.CLASSES)))
        self.assertEqual(chosen["log"], {"tab": "sent", "chips": {"class": "post", "from": "", "to": "", "agent": ""}, "q": "gate"})
        self.assertEqual(self.data["constants"]["classes"], list(council.CLASSES))
        self.assertEqual(self.data["constants"]["tones"], ["mayday", "review", "direct", "radio"])

    def test_the_log_tabs_chips_and_search_combine_with_and_newest_first(self):
        texts = [[row["text"] for row in rows] for rows in self.data["logs"]]
        self.assertEqual(texts[0], [row["text"] for row in reversed(LOG)])
        self.assertEqual(texts[1], ["deploy now", "rebase please"])
        self.assertEqual(texts[2], ["spoofed order", "Gate slow", "deploy now", "docs are green", "gate red on main"])
        self.assertEqual(texts[3], ["rebase done", "rebase please"])
        self.assertEqual(texts[4], ["rebase done", "gate red on main"])
        self.assertEqual(texts[5], ["Gate slow", "rebase done"])
        self.assertEqual(texts[6], ["which gate", "Gate slow", "docs are green"])
        self.assertEqual(texts[7], ["which gate", "Gate slow", "gate red on main"])
        self.assertEqual(texts[8], ["which gate"])
        self.assertEqual(texts[9], [])
        self.assertEqual(self.data["counts"], [{"sent": 2, "received": 5, "all": 8}])
        self.assertEqual(self.data["choices"][0]["class"], ["post", "call", "newsletter", "broadcast", "pan-pan"])
        self.assertEqual(self.data["choices"][0]["agent"], ["Docs", "Operator", "Skills", "Stage"])
        self.assertEqual(self.data["cleared"], [{"tab": "all", "chips": {"class": "", "from": "", "to": "", "agent": ""}, "q": ""}])

    def test_sent_comes_from_the_hub_ledger_and_a_row_only_named_operator_is_not_sent(self):
        sent = self.data["logs"][1]
        self.assertEqual([(row["to"], row["class"], row["sent"]) for row in sent], [([], "broadcast", True), (["Stage"], "post", True)])
        self.assertNotIn("spoofed order", [row["text"] for row in sent])
        self.assertEqual(self.data["ledger"], [MESSAGES[1], None, None])


class TestStaleState(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        done = subprocess.run(["node", "-e", STALE_PROBE, str(PAGE_LOAD)], capture_output=True, text=True, timeout=60, check=True)
        cls.data = json.loads(done.stdout)

    def test_every_answer_newer_than_the_applied_one_applies_even_while_slower_requests_overlap(self):
        self.assertEqual(self.data["slow"], [1, 2, 3, 4, 5, 6, 7])

    def test_an_answer_older_than_the_applied_one_is_dropped_so_no_radio_row_is_announced_twice(self):
        self.assertEqual(self.data["stale"], [3, [3]])

    def test_only_a_failure_newer_than_the_applied_answer_marks_the_page_offline(self):
        self.assertEqual(self.data["errors"], [False, True])

    def test_the_poller_skips_its_tick_while_a_request_is_in_flight(self):
        self.assertEqual(self.data["polls"], [1, 2])

    def test_a_hung_state_request_is_aborted_after_its_timeout_marks_the_page_offline_and_frees_the_poller(self):
        self.assertEqual(self.data["hung"], {"stuck": [1, False], "freed": [2, True], "waits": [15000, 15000]})


class TestTransmit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        done = subprocess.run(["node", "-e", TRANSMIT_PROBE, str(RADIOSET), str(PAGE_SPEECH), str(PAGE_RADIOVIEW)], capture_output=True, text=True, timeout=60, check=True)
        cls.data = json.loads(done.stdout)

    def test_a_mode_change_replans_the_playing_and_the_queued_rows_at_play_time(self):
        self.assertEqual(self.data["auto"], ["W", "R", "W", "R"])
        self.assertEqual(self.data["silence"], ["W", "W"])
        self.assertEqual(self.data["quiet"], ["W", "burst", "W", "burst"])

    def test_a_sound_that_never_ends_frees_the_speaker_after_its_duration_plus_two_seconds(self):
        self.assertEqual(self.data["stalled"], {"before": [False, True], "after": [True, None], "waits": [2500], "stops": 1})

    def test_every_mode_button_keeps_the_mode_before_it_resumes_the_audio_context(self):
        self.assertEqual(self.data["pressed"], [{"mode": "auto"}, "context", {"mode": "quiet"}, "context", {"mode": "silence"}, "context"])


class TestSpeechModes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        done = subprocess.run(["node", "-e", MODES_PROBE, str(RADIOSET), str(VOICE_JS), str(PAGE_SPEECH)], capture_output=True, text=True, timeout=60, check=True)
        cls.data = json.loads(done.stdout)

    def test_silence_pressed_while_the_rest_line_renders_starts_no_sound_once_it_arrives(self):
        self.assertEqual(self.data["inflight"], {"tts": [WORD, "this is A, over"], "heard": [[WORD, "auto"]]})

    def test_silence_pressed_while_the_rest_line_plays_stops_it_and_keeps_a_playing_procedure_word(self):
        self.assertEqual(self.data["playing"], {"heard": [[WORD, "auto"], ["this is A, over", "auto"]], "stops": ["this is A, over"]})
        self.assertEqual(self.data["word"], {"heard": [[WORD, "auto"]], "stops": []})

    def test_sounds_started_on_a_suspended_context_are_stopped_so_a_later_resume_plays_none_of_them(self):
        self.assertEqual(self.data["suspended"], {"started": 4, "heard": [], "stopped": 4})

    def test_a_rest_line_the_hub_holds_or_fails_after_silence_was_pressed_plays_no_fallback_burst(self):
        word = [WORD, "auto"]
        self.assertEqual(self.data["failed"], {"silence503": [word], "silence500": [word], "quiet503": [word, ["burst", "quiet"]]})

    def test_quiet_pressed_while_the_rest_line_plays_stops_it_and_plays_the_burst_instead(self):
        self.assertEqual(self.data["quiet"], {"heard": [[WORD, "auto"], ["this is A, over", "auto"], ["burst", "quiet"]], "stops": ["this is A, over"]})

    def test_a_volume_or_log_change_keeps_the_fallback_burst_of_a_failed_rest_line_playing(self):
        self.assertEqual(self.data["fallback"], {"heard": [[WORD, "auto"], ["burst", "auto"]], "stops": []})

    def test_only_the_switch_to_silence_stops_the_queued_alert_beeps_and_a_later_knob_drag_does_not(self):
        self.assertEqual(self.data["beeps"], [0, 1, 1])

    def test_a_gate_or_tts_change_after_a_line_ends_by_itself_voices_the_row_once_with_no_burst_and_no_bubble(self):
        voiced = {"heard": [[WORD, "auto"], ["this is A, over", "auto"]], "reads": 0}
        self.assertEqual(self.data["natural"], {"open": voiced, "tts": voiced})

    def test_a_gate_that_closes_while_the_rest_line_renders_still_plays_the_rendered_line(self):
        self.assertEqual(self.data["renderedLine"], [[WORD, "auto"], ["this is A, over", "auto"]])


class TestAlertBeeps(unittest.TestCase):
    def test_silencing_stops_every_beep_play_scheduled_and_forgets_it(self):
        done = subprocess.run(["node", "-e", BEEPS_PROBE, str(PAGE_ALERTS)], capture_output=True, text=True, timeout=60, check=True)
        self.assertEqual(json.loads(done.stdout), {"queued": [3, 0], "silenced": 3, "again": 3})


if __name__ == "__main__":
    unittest.main()
