from __future__ import annotations

import json
import re
import subprocess
import time
import unittest
from unittest import mock

from hub_case import HubCase
from hub_support import HUB
from kvb_orchestrator import council, engines, exchange, settings
from kvb_orchestrator.view import ENCODER_CSP

TEMPLATES = HUB / "templates"
RADIOSET = TEMPLATES / "radioset.js"
GIBBERLINK = TEMPLATES / "gibberlink.js"
MORSE = TEMPLATES / "morse.js"
VOICE = TEMPLATES / "voice.js"
PAGE_SPEECH = TEMPLATES / "page-speech.js"
PAGE_MORSE = TEMPLATES / "page-morse.js"
PAGE_GIBBERLINK = TEMPLATES / "page-gibberlink.js"
GGWAVE = HUB / "vendor" / "ggwave" / "ggwave.js"
KEY = "4f0c2a1e-1111-2222-3333-444455556666"
MARK = "[kvb-orchestrator msg 0123456789abcdef]"
WIDE = "ä€😀"
ALARMS = ("mayday", "pan-pan", "security")
SOUND = {"protocol": "AUDIBLE_FAST", "pan": -0.4}
FRAMES_PROBE = """
const R = require(process.argv[1]);
const input = JSON.parse(process.argv[2]);
console.log(JSON.stringify({
  split: input.texts.map(([key, text]) => R.frames(key, text)),
  plans: input.plans.map(([row, set, live]) => R.plan(row, set, live)),
  kept: input.sets.map((set) => R.valid(set).fallback),
  constants: {modes: R.MODES, fallbacks: R.FALLBACKS, frame: R.FRAME, fallback: R.DEFAULTS.fallback, key: R.KEY},
}));
"""
PLAYING_PROBE = """
const fs = require("fs");
const vm = require("vm");
const RadioSet = require(process.argv[1]);
const Morse = require(process.argv[2]);
const Voice = require(process.argv[3]);
const code = process.argv.slice(4, 7).map((path) => fs.readFileSync(path, "utf8")).join("\\n");
const stub = () => undefined;
const settle = async () => {
  for (let round = 0; round < 60; round += 1) {
    await new Promise((resolve) => setImmediate(resolve));
  }
};
const row = (source, pan, cls, text) => ({class: cls, source, from: source, to: [], called: [], speaker: "E", pitch: 600, protocol: "AUDIBLE_FAST", pan, voice: "v", word: "", rest: "x", text, ts: 1000});
function radio(plays, change) {
  const run = {buffers: [], gains: [], pans: [], oscillators: [], encoded: []};
  class Source {
    constructor() {
      Object.assign(this, {type: "", frequency: {value: 0}, buffer: null, ended: null, started: null, stops: []});
    }
    connect(node) {
      return node;
    }
    addEventListener(type, ended) {
      this.ended = ended;
    }
    start(when) {
      this.started = when === undefined ? "now" : when;
      if (plays) {
        setImmediate(() => this.ended && this.ended());
      }
    }
    stop(when) {
      this.stops.push(when === undefined ? "now" : when);
      if (when === undefined) {
        setImmediate(() => this.ended && this.ended());
      }
    }
  }
  const made = (list) => () => {
    const node = new Source();
    list.push(node);
    return node;
  };
  const param = () => ({value: 0, setValueAtTime: stub, linearRampToValueAtTime: stub, exponentialRampToValueAtTime: stub});
  const audio = {
    currentTime: 0, sampleRate: 8000, destination: {}, createBufferSource: made(run.buffers), createOscillator: made(run.oscillators),
    createGain: () => {
      const gain = param();
      run.gains.push(gain);
      return {gain, connect: (node) => node};
    },
    createStereoPanner: () => {
      const pan = param();
      run.pans.push(pan);
      return {pan, connect: (node) => node};
    },
    createBuffer: (channels, frames, rate) => ({length: frames, duration: frames / rate, getChannelData: () => new Float32Array(frames)}),
  };
  const sandbox = {
    RadioSet, Morse, Voice, radioSet: RadioSet.valid({mode: "gibberlink", classes: RadioSet.CLASSES, ...change}),
    state: {now: 1000, messages: [], speech: {tts: false, gate: {open: false}}},
    speech: {pending: [], busy: false, warned: 0, current: null, source: null, loading: null, timer: 0, item: null},
    settings: {bubbles: false, music: {on: false, volume: 0.4}, morse: {wpm: 20}}, SPEECH_QUEUE: 20, SPEECH_QUIET: 60000, SOUND_SLACK: 2, HUMAN: "Operator",
    Bubbles: {reading: () => 0.001}, wordsRead: () => 0, saidOf: (item) => item.words,
    keep: stub, drawRadioSet: stub, drawBubbles: stub, drawSpeaker: stub, duck: stub, clearBubbles: stub, silenceBeeps: stub, toast: stub,
    performance: {now: () => 0}, window: {setTimeout: () => 0, clearTimeout: stub}, context: () => audio,
  };
  vm.runInNewContext(code, sandbox);
  sandbox.gibberEncode = async (step) => {
    run.encoded.push([step.pan, step.frames.length]);
    return {rate: 48000, samples: step.frames.map((frame) => new Float32Array(frame.length * 10))};
  };
  run.sandbox = sandbox;
  run.say = (item) => sandbox.say({voice: item.voice, tone: "direct", cls: item.class, who: item.source, line: item.text, words: [item.text], silent: false, row: item});
  run.idle = () => !sandbox.speech.busy && !sandbox.speech.pending.length && sandbox.speech.source === null;
  return run;
}
const long = "E ".repeat(200);
(async () => {
  const whole = radio(true, {});
  whole.say(row("s1", -0.4, "post", long));
  await settle();
  const quiet = radio(true, {squelch: 0.5});
  quiet.say(row("s1", 0.4, "post", "E"));
  await settle();
  const mute = radio(true, {squelch: 0});
  mute.say(row("s1", 0.4, "post", "E"));
  await settle();
  const stop = radio(false, {});
  stop.say(row("s1", -0.4, "post", long));
  await settle();
  const playing = [stop.buffers.length, stop.sandbox.speech.source === stop.buffers[0]];
  stop.sandbox.cancelSpeech();
  await settle();
  const urgent = radio(false, {});
  urgent.say(row("s1", -0.8, "post", long));
  await settle();
  urgent.say(row("s2", 0.8, "mayday", "E"));
  await settle();
  const during = {buffers: urgent.buffers.map((node, index) => [urgent.pans[index].value, node.stops.includes("now")]), pending: urgent.sandbox.speech.pending.map((item) => item.cls)};
  urgent.buffers[1].ended();
  await settle();
  const switched = radio(false, {});
  switched.say(row("s1", -0.4, "post", long));
  await settle();
  switched.sandbox.keepRadio({mode: "morse"});
  await settle();
  console.log(JSON.stringify({
    whole: {encoded: whole.encoded, length: whole.buffers.map((node) => node.buffer.length), pan: whole.pans.map((pan) => pan.value), gain: whole.gains.map((gain) => gain.value), idle: whole.idle()},
    quiet: quiet.gains.map((gain) => gain.value),
    mute: [mute.encoded.length, mute.buffers.length, mute.idle()],
    stop: {playing, stops: stop.buffers[0].stops, idle: stop.idle()},
    urgent: {during, encoded: urgent.encoded, after: urgent.buffers.map((node, index) => [urgent.pans[index].value, node.started])},
    switched: {stops: switched.buffers[0].stops, oscillators: switched.oscillators.length},
  }));
})();
"""
ANSWER_PROBE = """
const fs = require("fs");
const vm = require("vm");
const posted = [];
const listeners = [];
const frame = {contentWindow: {postMessage: (message) => posted.push(message)}, addEventListener: (type, loaded) => loaded()};
const sandbox = {
  h: () => frame, document: {body: {append: () => undefined}},
  window: {addEventListener: (type, heard) => listeners.push(heard), setTimeout: () => 0, clearTimeout: () => undefined},
};
vm.runInNewContext(fs.readFileSync(process.argv[1], "utf8"), sandbox);
const Floats = vm.runInContext("Float32Array", sandbox);
const settle = () => new Promise((resolve) => setImmediate(resolve));
const outcome = (promise) => promise.then((value) => ({rate: value.rate, parts: value.samples.length}), (error) => ({error: error.message}));
(async () => {
  const good = outcome(sandbox.gibberEncode({protocol: "AUDIBLE_FAST", frames: ["a", "b"]}));
  const bad = outcome(sandbox.gibberEncode({protocol: "AUDIBLE_FAST", frames: ["c"]}));
  const failed = outcome(sandbox.gibberEncode({protocol: "MT_FAST", frames: ["d"]}));
  await settle();
  const answer = (source, data) => listeners.forEach((heard) => heard({source, data}));
  answer({}, {id: 1, rate: 1, samples: []});
  answer(frame.contentWindow, {id: 1, rate: 48000, samples: [new Floats(2), new Floats(3)]});
  answer(frame.contentWindow, {id: 2, rate: "fast", samples: [[0.1]]});
  answer(frame.contentWindow, {id: 3, error: "refused"});
  console.log(JSON.stringify({posted, listeners: listeners.length, answers: await Promise.all([good, bad, failed])}));
})();
"""
DECODE_PROBE = """
const factory = require(process.argv[1]);
const Gibberlink = require(process.argv[2]);
const R = require(process.argv[3]);
const input = JSON.parse(process.argv[4]);
factory({print: () => undefined, printErr: () => undefined}).then((ggwave) => {
  const frames = R.frames(input.key, input.text);
  const heard = (parts, rate) => {
    const gap = Math.round(rate * 0.3);
    const joined = new Float32Array(parts.reduce((sum, part) => sum + part.length + gap, 0));
    parts.reduce((at, part) => {
      joined.set(part, at);
      return at + part.length + gap;
    }, 0);
    const parameters = ggwave.getDefaultParameters();
    parameters.sampleRateInp = rate;
    const listener = ggwave.init(parameters);
    const texts = [];
    for (let at = 0; at < joined.length; at += 1024) {
      const got = ggwave.decode(listener, new Int8Array(joined.slice(at, at + 1024).buffer));
      if (got && got.length) {
        texts.push(new TextDecoder().decode(new Uint8Array(got.buffer, got.byteOffset, got.length)));
      }
    }
    ggwave.free(listener);
    return texts;
  };
  const decoded = {};
  const rates = [];
  for (const protocol of input.protocols) {
    const {rate, samples} = Gibberlink.encode(ggwave, {protocol, frames});
    rates.push(rate);
    decoded[protocol] = heard(samples, rate);
  }
  const refused = input.wrong.map((request) => {
    try {
      Gibberlink.encode(ggwave, request);
      return false;
    } catch (error) {
      return true;
    }
  });
  console.log(JSON.stringify({frames, decoded, rates, refused, ids: Object.keys(ggwave.ProtocolId)}));
});
"""


def node(script: str, *args: str) -> dict:
    return json.loads(subprocess.run(["node", "-e", script, *args], check=True, capture_output=True, text=True, timeout=600).stdout)


def row(cls: str, text: str) -> dict:
    return {"class": cls, "source": KEY, "voice": "v1", "word": "W" if cls in ALARMS else "", "rest": "R", "text": text, "speaker": "Docs", "called": ["Docs"], "pitch": 600, **SOUND}


def header(index: int, count: int) -> str:
    return f"{KEY if index == 1 else KEY[:8]} {index}/{count} "


def payloads(frames: list[str]) -> list[str]:
    return [frame[len(header(index, len(frames))) :] for index, frame in enumerate(frames, start=1)]


class TestFrames(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.long = "a" * 300
        cls.edges = ["b" * offset + WIDE * 40 for offset in range(8)]
        texts = [[KEY, cls.long], [KEY, ""], *[[KEY, text] for text in cls.edges]]
        live = {"tts": True, "open": True}
        cls.cases = [(mode, fallback, gate, name) for mode in ("gibberlink", "quiet", "auto", "silence") for fallback in ("gibberlink", "morse", "burst") for gate in (True, False) for name in council.CLASSES]
        plans = [[row(name, f"hello {MARK}"), {"mode": mode, "fallback": fallback, "classes": list(council.CLASSES), "muted": []}, {**live, "open": gate}] for mode, fallback, gate, name in cls.cases]
        plans.append([row("post", "hello"), {"mode": "gibberlink", "fallback": "burst", "classes": list(council.CLASSES), "muted": []}, {"tts": False, "open": False}])
        sets = [{}, {"fallback": "morse"}, {"fallback": "burst"}, {"fallback": "hiss"}, {"fallback": 1}, {"mode": "gibberlink"}]
        cls.data = node(FRAMES_PROBE, str(RADIOSET), json.dumps({"texts": texts, "plans": plans, "sets": sets}))

    def test_a_300_byte_message_splits_into_frames_of_at_most_140_bytes_with_the_key_header_and_joins_back(self):
        frames = self.data["split"][0]
        self.assertGreaterEqual(len(frames), 3)
        for index, frame in enumerate(frames, start=1):
            with self.subTest(frame=index):
                self.assertLessEqual(len(frame.encode("utf-8")), 140)
                self.assertTrue(frame.startswith(header(index, len(frames))), frame)
        self.assertEqual("".join(payloads(frames)), self.long)
        self.assertEqual(self.data["split"][1], [f"{KEY} 1/1 "], "an empty text still sends its sender")

    def test_umlauts_euro_and_emoji_at_every_frame_edge_split_between_characters(self):
        for offset, frames in enumerate(self.data["split"][2:]):
            with self.subTest(offset=offset):
                sizes = [len(frame.encode("utf-8")) for frame in frames]
                self.assertTrue(all(size <= 140 for size in sizes), sizes)
                self.assertGreater(max(sizes), 136, "the frames fill the budget up to the last whole character")
                self.assertEqual("".join(payloads(frames)), self.edges[offset])

    def test_gibberlink_mode_gives_the_alarm_classes_their_word_then_the_whole_message_and_every_other_class_the_frames_only(self):
        gibberlink = {"kind": "gibberlink", "frames": [f"{KEY} 1/1 hello"], **SOUND}
        for case, plan in zip(self.cases, self.data["plans"], strict=False):
            mode, _, _, name = case
            if mode != "gibberlink":
                continue
            with self.subTest(case=case):
                self.assertEqual(plan, [{"kind": "word", "text": "W"}, gibberlink] if name in ALARMS else [gibberlink])
        self.assertEqual(self.data["plans"][-1], [gibberlink], "without the speech engine no procedure word is rendered")

    def test_quiet_and_auto_with_the_gate_closed_play_the_fallback_pick_after_the_word(self):
        standins = {"gibberlink": {"kind": "gibberlink", "frames": [f"{KEY} 1/1 hello"], **SOUND}, "burst": {"kind": "burst"}}
        for case, plan in zip(self.cases, self.data["plans"], strict=False):
            mode, fallback, gate, name = case
            word = [{"kind": "word", "text": "W"}] if name in ALARMS else []
            with self.subTest(case=case):
                if mode == "silence":
                    self.assertEqual(plan, word)
                elif mode == "auto" and gate:
                    self.assertEqual(plan, [*word, {"kind": "speech", "text": "R"}])
                elif mode != "gibberlink" and fallback == "morse":
                    self.assertEqual((plan[:-1], plan[-1]["kind"], plan[-1]["text"]), (word, "morse", "DE Docs hello  "))
                elif mode != "gibberlink":
                    self.assertEqual(plan, [*word, standins[fallback]])

    def test_the_fallback_pick_is_kept_per_browser_beside_the_mode_and_never_in_the_hub_settings(self):
        self.assertEqual(self.data["kept"], ["gibberlink", "morse", "burst", "gibberlink", "gibberlink", "gibberlink"])
        constants = self.data["constants"]
        self.assertEqual((constants["modes"], constants["fallbacks"], constants["fallback"]), (["auto", "quiet", "silence", "morse", "gibberlink"], ["gibberlink", "morse", "burst"], "gibberlink"))
        self.assertEqual((constants["frame"]["bytes"], constants["frame"]["prefix"], constants["key"]), (140, 8, "kvb-orchestrator.radio"))
        self.assertNotIn("fallback", settings.SETTINGS)
        self.assertNotIn("fallback", json.dumps(settings.SETTINGS))


class TestSpeakerSound(unittest.TestCase):
    def test_every_speaker_gets_one_stable_protocol_and_stereo_position_from_its_slot(self):
        keys = [f"s{number}" for number in range(200)]
        sounds = [engines.sound_of(key) for key in keys]
        self.assertEqual(sounds, [engines.sound_of(key) for key in keys])
        self.assertTrue(all(sound["protocol"] in engines.GIBBERLINK and sound["pan"] in engines.PANS for sound in sounds))
        self.assertEqual(len({(sound["protocol"], sound["pan"]) for sound in sounds}), len(engines.GIBBERLINK) * len(engines.PANS))
        with mock.patch.object(engines, "slot", lambda key, count: count - 1):
            self.assertEqual(engines.sound_of("s1"), {"protocol": engines.GIBBERLINK[-1], "pan": engines.PANS[-1]})
        self.assertEqual(engines.sound_of("s1")["protocol"], engines.GIBBERLINK[engines.slot("s1", 20) % 4])

    def test_speakers_in_distinct_slots_get_distinct_protocols_from_the_vendored_source(self):
        picks = {}
        for number in range(200):
            picks.setdefault(engines.slot(f"s{number}", 20) % len(engines.GIBBERLINK), f"s{number}")
        self.assertEqual(len({engines.sound_of(key)["protocol"] for key in picks.values()}), len(engines.GIBBERLINK))
        self.assertEqual(engines.GIBBERLINK, ("AUDIBLE_NORMAL", "AUDIBLE_FAST", "AUDIBLE_FASTEST", "DT_FASTEST"))


class TestPlaying(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = node(PLAYING_PROBE, str(RADIOSET), str(MORSE), str(VOICE), str(PAGE_SPEECH), str(PAGE_MORSE), str(PAGE_GIBBERLINK))

    def test_the_frames_play_once_in_the_sender_position_at_the_tone_volume_times_the_squelch(self):
        whole = self.data["whole"]
        self.assertEqual(whole["encoded"], [[-0.4, 3]])
        self.assertEqual((len(whole["length"]), whole["pan"], whole["gain"], whole["idle"]), (1, [-0.4], [0.5], True))
        self.assertGreater(whole["length"][0], 399 * 10 + 3 * 48000 * 0.3 - 1, "every frame with a 0.3 second gap at the encoder's 48 kHz")
        self.assertEqual(self.data["quiet"], [0.25])
        self.assertEqual(self.data["mute"], [0, 0, True], "squelch 0 encodes and plays nothing")

    def test_stop_ends_the_frames_at_once(self):
        stop = self.data["stop"]
        self.assertEqual((stop["playing"], stop["stops"], stop["idle"]), ([1, True], ["now"], True))

    def test_a_mayday_cuts_a_post_whose_frames_play_and_the_post_sends_again_whole_after_it(self):
        urgent = self.data["urgent"]
        self.assertEqual(urgent["during"], {"buffers": [[-0.8, True], [0.8, False]], "pending": ["post"]})
        self.assertEqual(urgent["encoded"], [[-0.8, 3], [0.8, 1], [-0.8, 3]])
        self.assertEqual(urgent["after"][2], [-0.8, "now"])

    def test_a_mode_change_cuts_the_frames_and_replans_the_row(self):
        self.assertEqual(self.data["switched"], {"stops": ["now"], "oscillators": 1})


class TestEncoderAnswers(unittest.TestCase):
    def test_the_page_takes_samples_only_from_its_own_encoder_frame_and_refuses_anything_else(self):
        data = node(ANSWER_PROBE, str(PAGE_GIBBERLINK))
        self.assertEqual(data["listeners"], 1, "one encoder frame, one listener, however often the radio encodes")
        self.assertEqual(data["posted"], [{"id": 1, "protocol": "AUDIBLE_FAST", "frames": ["a", "b"]}, {"id": 2, "protocol": "AUDIBLE_FAST", "frames": ["c"]}, {"id": 3, "protocol": "MT_FAST", "frames": ["d"]}])
        self.assertEqual(data["answers"], [{"rate": 48000, "parts": 2}, {"error": "the Gibberlink encoder answered no samples"}, {"error": "refused"}])


class TestEncoder(unittest.TestCase):
    def test_every_protocol_decodes_back_to_the_frame_texts_and_wrong_requests_are_refused(self):
        text = f"disk full on {WIDE} " + "rotate the keys " * 15
        wrong = [{"protocol": "MT_FAST", "frames": ["x"]}, {"protocol": "values", "frames": ["x"]}, {"protocol": "AUDIBLE_FAST", "frames": [1]}, {"protocol": "AUDIBLE_FAST", "frames": "x"}, {"frames": ["x"]}]
        data = node(DECODE_PROBE, str(GGWAVE), str(GIBBERLINK), str(RADIOSET), json.dumps({"key": KEY, "text": text, "protocols": engines.GIBBERLINK, "wrong": wrong}))
        self.assertGreaterEqual(len(data["frames"]), 3)
        self.assertEqual(list(data["decoded"]), list(engines.GIBBERLINK))
        for name, heard in data["decoded"].items():
            with self.subTest(protocol=name):
                self.assertEqual(heard, data["frames"])
        self.assertEqual((set(data["rates"]), data["refused"]), ({48000}, [True] * len(wrong)))
        for name in engines.GIBBERLINK:
            with self.subTest(protocol=name):
                self.assertIn(f"GGWAVE_PROTOCOL_{name}", data["ids"])


class TestEncoderHttp(HubCase):
    def test_the_encoder_page_carries_its_own_csp_and_the_hub_page_never_allows_eval(self):
        status, headers, body = self.get("/gibberlink")
        page = body.decode("utf-8")
        nonces = set(re.findall(r'<script nonce="([^"]+)"', page))
        self.assertEqual((status, headers["content-type"], len(nonces)), (200, "text/html; charset=utf-8", 1), page)
        csp = headers["content-security-policy"]
        self.assertEqual(csp, ENCODER_CSP.format(nonces.pop()))
        self.assertIn("'unsafe-eval' 'wasm-unsafe-eval'", csp)
        self.assertTrue(csp.startswith("sandbox allow-scripts;"), "the server keeps the encoder in an opaque origin even at top level")
        self.assertIn("connect-src 'none'", csp)
        self.assertIn('src="/vendor/ggwave.js"', page)
        self.assertIn("Gibberlink.serve(window, ggwave_factory(", page)
        self.assertLess(page.index("window.fetch = () => Promise.reject("), page.index("Gibberlink.serve("), "the frame asks for nothing before ggwave loads its wasm")
        self.assertNotEqual(self.get("/gibberlink")[1]["content-security-policy"], csp, "every load gets a fresh nonce")
        index = self.get("/")[1]["content-security-policy"]
        self.assertNotIn("unsafe-eval", index)
        self.assertIn("frame-src 'self'", index)

    def test_the_vendor_route_serves_ggwave_under_the_plain_csp(self):
        status, headers, body = self.get("/vendor/ggwave.js")
        self.assertEqual((status, headers["content-type"], headers["content-security-policy"]), (200, "text/javascript; charset=utf-8", exchange.PLAIN_CSP))
        self.assertEqual(body, GGWAVE.read_bytes())

    def test_every_radio_row_carries_the_sender_protocol_and_stereo_position(self):
        self.claim("s1", "Docs")
        self.claim("s2", "Skills")
        now = time.time()
        self.write_council({"news.jsonl": self.jsonl([
            {"ts": now - 30, "from": "Docs", "to": ["Skills"], "text": "gate red", "class": "call", "v": 2},
            {"ts": now - 20, "from": "Skills", "to": [], "text": "MAYDAY disk full", "class": "mayday", "v": 2},
        ])})
        rows = [(row["source"], row["protocol"], row["pan"]) for row in self.snapshot()["radio"]]
        self.assertEqual(rows, [(key, *engines.sound_of(key).values()) for key in ("s1", "s2")])


if __name__ == "__main__":
    unittest.main()
