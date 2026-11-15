from __future__ import annotations

import json
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from hub_case import HubCase
from hub_support import HUB
from kvb_orchestrator import council, engines, errors, settings

TEMPLATES = HUB / "templates"
MORSE = TEMPLATES / "morse.js"
RADIOSET = TEMPLATES / "radioset.js"
VOICE = TEMPLATES / "voice.js"
PAGE_SPEECH = TEMPLATES / "page-speech.js"
PAGE_MORSE = TEMPLATES / "page-morse.js"
MARK = "[kvb-orchestrator msg 0123456789abcdef]"
TEXT = f"disk full\nsecond line {MARK}"
SIGNS = {
    "mayday": ("SOS", True), "pan-pan": ("PAN PAN", False), "security": ("SECURITE", False), "broadcast": ("CQ", False),
    "newsletter": ("CQ", False), "call": ("Skills session", False), "post": ("KA", True),
}
CODES_PROBE = """
const Morse = require(process.argv[1]);
const RadioSet = require(process.argv[2]);
const input = JSON.parse(process.argv[3]);
console.log(JSON.stringify({
  paris: [5, 20, 40].map((wpm) => ({dot: Morse.dot(wpm), ...Morse.timeline(Morse.words("PARIS"), wpm)})),
  words: input.words.map((text) => Morse.words(text)),
  joined: [Morse.joined("SOS"), Morse.joined("~ 😀")],
  sos: [Morse.timeline(Morse.joined("SOS"), 20).ms, Morse.timeline(Morse.words("SOS"), 20).ms],
  rates: [5, 20, 40].map(Morse.rate),
  plans: input.plans.map(([row, set, live]) => RadioSet.plan(row, set, live)),
  gates: [0, 10, 50, 90, 100].map(RadioSet.gateLabel),
  constants: {modes: RadioSet.MODES, gate: RadioSet.GATE, speed: Morse.SPEED, prosigns: RadioSet.PROSIGNS, kept: RadioSet.valid({mode: "morse"}).mode},
}));
"""
KEYING_PROBE = """
const fs = require("fs");
const vm = require("vm");
const RadioSet = require(process.argv[1]);
const Morse = require(process.argv[2]);
const Voice = require(process.argv[3]);
const code = [process.argv[4], process.argv[5]].map((path) => fs.readFileSync(path, "utf8")).join("\\n");
const stub = () => undefined;
const settle = async () => {
  for (let round = 0; round < 60; round += 1) {
    await new Promise((resolve) => setImmediate(resolve));
  }
};
const row = (source, pitch, cls, text) => ({class: cls, source, from: source, to: [], called: [], speaker: "E", pitch, voice: "v", word: "", rest: "x", text, ts: 1000});
function radio(plays) {
  const run = {oscillators: [], buffers: [], fetches: 0, gains: []};
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
      this.started = when;
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
  const param = () => {
    const events = [];
    run.gains.push(events);
    const log = (kind) => (value, at) => events.push([kind, value, at]);
    return {value: 0, setValueAtTime: log("set"), linearRampToValueAtTime: log("ramp"), exponentialRampToValueAtTime: log("exp")};
  };
  const made = (list) => () => {
    const node = new Source();
    list.push(node);
    return node;
  };
  const audio = {
    currentTime: 0, sampleRate: 8000, destination: {}, createOscillator: made(run.oscillators), createBufferSource: made(run.buffers),
    createGain: () => ({gain: param(), connect: (node) => node}),
    createBiquadFilter: () => ({type: "", frequency: {value: 0}, Q: {value: 0}, connect: (node) => node}),
    createBuffer: (channels, frames) => ({getChannelData: () => new Float32Array(frames)}),
  };
  const sandbox = {
    RadioSet, Morse, Voice, radioSet: RadioSet.valid({mode: "morse", classes: RadioSet.CLASSES}),
    state: {now: 1000, messages: [], speech: {tts: false, gate: {open: false}}},
    speech: {pending: [], busy: false, warned: 0, current: null, source: null, loading: null, timer: 0, item: null},
    settings: {bubbles: false, music: {on: false, volume: 0.4}, morse: {wpm: 20}}, SPEECH_QUEUE: 20, SPEECH_QUIET: 60000, SOUND_SLACK: 2, HUMAN: "Operator",
    Bubbles: {reading: () => 0.001}, wordsRead: () => 0, saidOf: (item) => item.words,
    keep: stub, drawRadioSet: stub, drawBubbles: stub, drawSpeaker: stub, duck: stub, clearBubbles: stub, silenceBeeps: stub, toast: stub,
    performance: {now: () => 0}, window: {setTimeout: () => 0, clearTimeout: stub}, context: () => audio,
    fetch: async () => {
      run.fetches += 1;
      return {ok: false, status: 503, headers: {get: () => "application/json"}, text: async () => ""};
    },
  };
  vm.runInNewContext(code, sandbox);
  run.sandbox = sandbox;
  run.say = (item) => sandbox.say({voice: item.voice, tone: "direct", cls: item.class, who: item.source, line: item.text, words: [item.text], silent: false, row: item});
  run.idle = () => !sandbox.speech.busy && !sandbox.speech.pending.length && sandbox.speech.source === null;
  return run;
}
const shape = (node) => ({type: node.type, frequency: node.frequency.value, started: node.started, stops: node.stops});
const ons = (run) => run.gains[0].filter(([kind, value]) => kind === "ramp" && value > 0).length;
(async () => {
  const whole = radio(true);
  whole.say(row("s1", 640, "mayday", "E"));
  await settle();
  const fast = radio(true);
  fast.sandbox.settings.morse.wpm = 40;
  fast.say(row("s1", 640, "mayday", "E"));
  await settle();
  const two = radio(true);
  two.say(row("s1", 600, "post", "E"));
  two.say(row("s2", 800, "post", "E"));
  await settle();
  const cut = radio(false);
  cut.say(row("s1", 640, "security", "E ".repeat(500)));
  await settle();
  const playing = [cut.oscillators.length, cut.sandbox.speech.source === cut.oscillators[0]];
  cut.sandbox.cancelSpeech();
  await settle();
  const switched = radio(false);
  switched.say(row("s1", 640, "security", "E"));
  await settle();
  switched.sandbox.keepRadio({mode: "quiet"});
  await settle();
  const urgent = radio(false);
  urgent.say(row("s1", 600, "post", "E ".repeat(200)));
  await settle();
  urgent.say(row("s2", 800, "mayday", "E"));
  await settle();
  const calm = radio(false);
  calm.say(row("s1", 600, "mayday", "E ".repeat(200)));
  await settle();
  calm.say(row("s2", 800, "pan-pan", "E"));
  calm.say(row("s3", 700, "post", "E"));
  await settle();
  const keyed = (run) => ({oscillators: run.oscillators.map((node) => [node.frequency.value, node.stops.includes("now")]), pending: run.sandbox.speech.pending.map((item) => item.cls)});
  console.log(JSON.stringify({
    urgent: keyed(urgent),
    calm: keyed(calm),
    whole: {oscillators: whole.oscillators.map(shape), buffers: whole.buffers.length, fetches: whole.fetches, ons: ons(whole), idle: whole.idle()},
    fast: fast.oscillators.map(shape),
    two: two.oscillators.map((node) => node.frequency.value),
    cut: {playing, oscillators: cut.oscillators.map(shape), idle: cut.idle()},
    switched: {oscillators: switched.oscillators.map(shape), buffers: switched.buffers.length},
  }));
})();
"""


def node(probe: str, *args: str) -> dict:
    done = subprocess.run(["node", "-e", probe, *args], capture_output=True, text=True, timeout=60, check=True)
    return json.loads(done.stdout)


def radio_row(cls: str, text: str) -> dict:
    return {"class": cls, "source": "s1", "from": "Docs", "to": ["Skills session"], "called": ["Skills session"], "speaker": "Docs", "pitch": 612, "voice": "", "word": "", "rest": "", "text": text}


def radio_set(mode: str, muted: list[str]) -> dict:
    return {"mode": mode, "classes": list(council.CLASSES), "muted": muted, "sounds": {}, "squelch": 1, "log": {}}


class TestMorseCode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        offline, online = {"tts": False, "open": False}, {"tts": True, "open": True}
        plans = [[radio_row(name, TEXT), radio_set("morse", []), offline] for name in council.CLASSES]
        plans += [
            [radio_row("security", TEXT), radio_set("morse", []), online],
            [radio_row("security", TEXT), radio_set("morse", ["s1"]), offline],
            [radio_row("mayday", TEXT), radio_set("morse", ["s1"]), offline],
            [radio_row("broadcast", "word " * 600), radio_set("morse", []), offline],
        ]
        words = ["PARIS", "paris", "Grüße, Ëva! 😀 ~ À ÿ"]
        cls.data = node(CODES_PROBE, str(MORSE), str(RADIOSET), json.dumps({"words": words, "plans": plans}))

    def test_paris_at_20_wpm_lasts_exactly_50_dot_units_of_60_ms(self):
        slow, normal, fast = self.data["paris"]
        self.assertEqual((normal["dot"], normal["ms"]), (60, 50 * 60))
        self.assertEqual((slow["dot"], slow["ms"], fast["dot"], fast["ms"]), (240, 50 * 240, 30, 50 * 30))
        self.assertEqual(len(normal["tones"]), 14)
        self.assertEqual(normal["tones"][:4], [[0, 60], [120, 180], [360, 180], [600, 60]])
        self.assertEqual(normal["tones"][4], [(11 + 3) * 60, 60])
        self.assertEqual(normal["tones"][-1], [42 * 60, 60])
        self.assertEqual(normal["ms"] - sum(normal["tones"][-1]), 7 * 60, "the closing word gap is 7 dot units")

    def test_letters_case_fold_umlauts_key_their_code_or_base_letter_and_the_rest_is_skipped(self):
        upper, lower, mixed = self.data["words"]
        self.assertEqual(upper, [[".--.", ".-", ".-.", "..", "..."]])
        self.assertEqual(lower, upper)
        self.assertEqual(mixed, [["--.", ".-.", "..--", "...--..", ".", "--..--"], [".", "...-", ".-", "-.-.--"], [".--.-"], ["-.--"]])

    def test_a_prosign_keys_its_letters_without_the_letter_gap(self):
        self.assertEqual(self.data["joined"], [[["...---..."]], []])
        self.assertEqual(self.data["sos"], [30 * 60, 34 * 60])

    def test_the_speed_label_names_words_and_dot_units_per_minute(self):
        self.assertEqual(self.data["rates"], ["5 WPM (250 dots/min)", "20 WPM (1000 dots/min)", "40 WPM (2000 dots/min)"])
        self.assertEqual(self.data["constants"]["speed"], {"min": settings.WPM[0], "max": settings.WPM[1], "step": 1})

    def test_every_class_keys_its_prosign_then_de_with_the_clear_name_and_the_whole_text_in_the_sender_pitch(self):
        plans = self.data["plans"]
        for index, name in enumerate(council.CLASSES):
            sign, joined = SIGNS[name]
            with self.subTest(name=name):
                self.assertEqual(plans[index], [{"kind": "morse", "sign": sign, "joined": joined, "text": f"DE Docs {TEXT.replace(MARK, ' ')}", "pitch": 612}])
                self.assertNotIn("s1", plans[index][0]["text"])
                self.assertNotIn("kvb-orchestrator", plans[index][0]["text"])
        online, muted, mayday, long = plans[len(council.CLASSES):]
        self.assertEqual(online, plans[list(council.CLASSES).index("security")], "Morse needs neither the speech engine nor an open CPU gate")
        self.assertEqual((muted, mayday[0]["sign"]), ([], "SOS"), "the read-aloud filters hold in Morse, a MAYDAY always keys")
        self.assertEqual(long[0]["text"].count("word"), 600, "Morse keys the whole text, with no cap")
        self.assertEqual(self.data["constants"]["prosigns"], {name: {"sign": "" if name == "call" else sign, "joined": joined, "called": name == "call"} for name, (sign, joined) in SIGNS.items()})

    def test_morse_is_a_fourth_mode_and_the_threshold_labels_read_never_and_always_at_the_ends(self):
        constants = self.data["constants"]
        self.assertEqual((constants["modes"], constants["kept"]), (["auto", "quiet", "silence", "morse"], "morse"))
        self.assertEqual(constants["gate"], {"min": settings.THRESHOLDS[0], "max": settings.THRESHOLDS[-1], "step": settings.THRESHOLDS[1] - settings.THRESHOLDS[0]})
        self.assertEqual(self.data["gates"], ["never", "speak while CPU < 10 %", "speak while CPU < 50 %", "speak while CPU < 90 %", "always"])


class TestMorseKeying(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = node(KEYING_PROBE, str(RADIOSET), str(MORSE), str(VOICE), str(PAGE_SPEECH), str(PAGE_MORSE))

    def test_one_sine_oscillator_keys_the_whole_row_at_the_hub_speed_in_the_row_pitch_without_speech(self):
        whole = self.data["whole"]
        self.assertEqual(whole["oscillators"], [{"type": "sine", "frequency": 640, "started": 0, "stops": [64 * 60 / 1000]}])
        self.assertEqual((whole["buffers"], whole["fetches"], whole["ons"], whole["idle"]), (0, 0, 15, True))
        self.assertEqual(self.data["fast"][0]["stops"], [64 * 30 / 1000])
        self.assertEqual(self.data["two"], [600, 800])

    def test_stop_cuts_a_long_message_at_once(self):
        cut = self.data["cut"]
        self.assertEqual(cut["playing"], [1, True])
        self.assertEqual(cut["oscillators"][0]["stops"], [4092 * 60 / 1000, "now"], "a 1000 character text keys whole for minutes until Stop cuts it")
        self.assertEqual((len(cut["oscillators"]), cut["idle"]), (1, True))

    def test_a_higher_class_cuts_the_keying_row_which_keys_again_whole_after_it(self):
        self.assertEqual(self.data["urgent"], {"oscillators": [[600, True], [800, False]], "pending": ["post"]})
        self.assertEqual(self.data["calm"], {"oscillators": [[600, False]], "pending": ["pan-pan", "post"]}, "a lower or equal class waits for the whole row")

    def test_a_mode_change_cuts_the_keying_and_replans_the_row(self):
        switched = self.data["switched"]
        self.assertEqual(switched["oscillators"][0]["stops"], [100 * 60 / 1000, "now"])
        self.assertEqual((len(switched["oscillators"]), switched["buffers"]), (1, 1))


class TestMorsePitch(unittest.TestCase):
    def test_every_speaker_keys_one_stable_pitch_inside_550_to_850_hz_and_speakers_spread_over_it(self):
        keys = [f"s{number}" for number in range(200)]
        pitches = [engines.pitch_of(key) for key in keys]
        self.assertEqual(pitches, [engines.pitch_of(key) for key in keys])
        self.assertTrue(all(550 <= pitch <= 850 for pitch in pitches), pitches)
        self.assertGreaterEqual(len(set(pitches)), 120)
        self.assertLess(min(pitches), 575)
        self.assertGreater(max(pitches), 825)

    def test_pitch_and_voice_come_from_the_one_speaker_slot(self):
        pool = ["a:0", "b:0", "c:0"]
        with mock.patch.object(engines, "slot", lambda key, count: count - 1):
            self.assertEqual((engines.voice_of("s1", pool, "op"), engines.pitch_of("s1")), ("c:0", 850))
        with mock.patch.object(engines, "slot", lambda key, count: 0):
            self.assertEqual((engines.voice_of("s1", pool, "op"), engines.pitch_of("s1")), ("a:0", 550))
        self.assertEqual(engines.pitch_of("s1") - 550, engines.slot("s1", 301))
        self.assertEqual(engines.voice_of("s1", pool, "op"), pool[engines.slot("s1", len(pool))])


class TestMorseSetting(unittest.TestCase):
    def test_the_speed_is_a_whole_number_from_5_to_40_words_per_minute_and_20_by_default(self):
        self.assertEqual((settings.SETTINGS["morse"], settings.WPM), ({"wpm": 20}, (5, 40)))
        for value in (5, 6, 20, 39, 40):
            with self.subTest(value=value):
                self.assertEqual(settings.morse_setting({"wpm": value}), {"wpm": value})
        for value in (4, 41, 0, -20, 20.0, True, False, "20", None, [20]):
            with self.subTest(value=value), self.assertRaises(errors.ToolError):
                settings.morse_setting({"wpm": value})
        for raw in ({}, {"wpm": 20, "extra": 1}, "20", None):
            with self.subTest(raw=raw), self.assertRaises(errors.ToolError):
                settings.morse_setting(raw)

    def test_a_page_or_a_file_from_before_the_speed_keeps_the_saved_or_the_default_speed(self):
        saved = {**settings.SETTINGS, "morse": {"wpm": 33}, "rates": {"period": "day", "metrics": ["tasks", "cpu"]}}
        older = {key: value for key, value in saved.items() if key not in ("morse", "rates")}
        self.assertEqual(settings.completed(older, saved), saved)
        self.assertEqual(settings.completed({**older, "morse": {"wpm": 7}}, saved)["morse"], {"wpm": 7})
        self.assertEqual(settings.completed("flat", saved), "flat")
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / "settings.json"
            file.write_text(json.dumps({**older, "latitude": 52.5}), encoding="utf-8")
            loaded = settings.Settings(file).get()
        self.assertEqual((loaded["morse"], loaded["latitude"]), ({"wpm": 20}, 52.5))


class TestMorseHttp(HubCase):
    def save(self, payload: dict) -> tuple[int, dict, bytes]:
        return self.post_json("/api/settings", {**payload, "proof": None}, self.guard(self.host))

    def test_the_speed_is_validated_saved_without_a_passkey_and_survives_a_reload(self):
        current = self.snapshot()["settings"]
        self.assertEqual(current["morse"], {"wpm": 20})
        for wrong in ({"wpm": 4}, {"wpm": 41}, {"wpm": "20"}, {"wpm": True}, {"wpm": 20.5}, {}, {"wpm": 20, "dots": 1000}, 20):
            with self.subTest(wrong=wrong):
                self.assertEqual(self.save({**current, "morse": wrong})[0], 400)
        status, _, body = self.post_json("/api/settings/sign", {**current, "morse": {"wpm": 33}}, self.guard(self.host))
        self.assertEqual((status, json.loads(body)["payload"]), (200, None))
        status, _, body = self.save({**current, "morse": {"wpm": 33}})
        self.assertEqual((status, json.loads(body)["settings"]["morse"]), (200, {"wpm": 33}), body)
        self.assertEqual(settings.Settings(self.state / "settings.json").get()["morse"], {"wpm": 33})
        sheet = {key: value for key, value in self.snapshot()["settings"].items() if key != "morse"}
        status, _, body = self.save({**sheet, "bubbles": True})
        self.assertEqual((status, json.loads(body)["settings"]["morse"]), (200, {"wpm": 33}), body)
        self.assertEqual(self.snapshot()["settings"]["morse"], {"wpm": 33})

    def test_every_radio_row_carries_the_sender_pitch_its_clear_name_and_the_called_names(self):
        self.claim("s1", "Docs")
        self.claim("s2", "Skills")
        now = time.time()
        self.write_council({"news.jsonl": self.jsonl([
            {"ts": now - 30, "from": "Docs", "to": ["Skills"], "text": "gate red", "class": "call", "v": 2},
            {"ts": now - 20, "from": "Skills", "to": [], "text": "MAYDAY disk full", "class": "mayday", "v": 2},
        ])})
        rows = [(row["source"], row["speaker"], row["called"], row["pitch"]) for row in self.snapshot()["radio"]]
        self.assertEqual(rows, [("s1", "Docs", ["Skills"], engines.pitch_of("s1")), ("s2", "Skills", [], engines.pitch_of("s2"))])
        self.assertNotEqual(engines.pitch_of("s1"), engines.pitch_of("s2"))


if __name__ == "__main__":
    unittest.main()
