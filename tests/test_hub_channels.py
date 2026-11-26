from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

from hub_case import HubCase
from hub_support import HUB
from kvb_orchestrator import settings

TEMPLATES = HUB / "templates"
ON = {"browser": True, "sounds": True, "aloud": True, "title": True}
PROBE = """
const fs = require("fs");
const vm = require("vm");
const [alerts, speechCode] = [fs.readFileSync(process.argv[1], "utf8"), fs.readFileSync(process.argv[2], "utf8")];
const [RadioSet, Bubbles, Voice] = [require(process.argv[3]), require(process.argv[4]), require(process.argv[5])];
const ON = {browser: true, sounds: true, aloud: true, title: true};
function announced(change) {
  const heard = {shown: [], played: [], spoken: []};
  class Notification {
    constructor(title) {
      heard.shown.push(title);
    }
  }
  Notification.permission = "granted";
  const mayday = {ts: 10, from: "Docs", to: [], class: "mayday", text: "disk full"};
  const direct = {ts: 11, from: "Stage", to: ["Operator"], class: "call", text: "gate red"};
  const sandbox = {
    Notification, window: {Notification, setTimeout: (run) => run()}, settings: {channels: {...ON, ...change}, agents: {}}, RadioSet, radioSet: {mode: "auto"},
    state: {inbox: [{id: "r1", kind: "review", title: "feat: x"}], radio: [mayday, direct], pending: []},
    known: {inbox: new Set(), alarms: new Set(), radio: new Set(), batches: new Set(), now: null}, live: () => true, alarmRows: () => [mayday], keyOf: (item) => item.id,
    HUMAN: "Operator", Voice: {beep: () => "mayday"}, tones: () => ({}), loudness: () => 0.5, SOUND_KINDS: [["mayday", "MAYDAY"]], TONES: {mayday: [[880, 0, 0.2]]},
    dash: (value) => value, ITEM_LABELS: {review: "Review"},
  };
  vm.runInNewContext(alerts, sandbox);
  sandbox.play = (kind) => heard.played.push(kind);
  sandbox.speakRows = (rows) => heard.spoken.push(rows.length);
  sandbox.announce();
  return heard;
}
function synced(before, after) {
  const calls = [];
  const sandbox = {settings: {channels: {...ON, ...after}}, cancelSpeech: () => calls.push("cancel"), drawTitle: () => calls.push("title")};
  vm.runInNewContext(alerts, sandbox);
  sandbox.silenceBeeps = () => calls.push("silence");
  sandbox.syncChannels({...ON, ...before});
  return calls;
}
function spoken(aloud, bubbles, agents = {}, cls = "security") {
  const said = [];
  const sandbox = {
    RadioSet, Bubbles, Voice, radioSet: RadioSet.valid({mode: "auto"}), HUMAN: "Operator", SPEECH_FRESH: 300, short: (value) => value, quietBubbles: () => null,
    state: {now: 1000, messages: [], speech: {tts: true, gate: {open: true}}}, settings: {bubbles, channels: {...ON, aloud}, agents},
  };
  vm.runInNewContext(speechCode, sandbox);
  sandbox.say = (...items) => said.push(...items.map((item) => [item.silent, item.bubble]));
  sandbox.speakRows([{ts: 1000, from: "Stage", to: [], class: cls, source: "s2", voice: "v2", word: "W", rest: "R", text: "rotate keys now"}]);
  return said.map(([silent]) => silent);
}
function perAgent(agents, cls = "security") {
  const said = [];
  const sandbox = {
    RadioSet, Bubbles, Voice, radioSet: RadioSet.valid({mode: "quiet"}), HUMAN: "Operator", SPEECH_FRESH: 300, short: (value) => value, quietBubbles: () => null,
    state: {now: 1000, messages: [], speech: {tts: true, gate: {open: true}}}, settings: {bubbles: true, channels: ON, agents},
  };
  vm.runInNewContext(speechCode, sandbox);
  sandbox.say = (...items) => said.push(...items.map((item) => [item.silent, item.bubble]));
  sandbox.speakRows([{ts: 1000, from: "Stage", to: [], class: cls, source: "s2", voice: "v2", word: "W", rest: "R", text: "rotate keys now"}]);
  return said;
}
const OFF = (change) => ({s2: {sound: true, aloud: true, bubbles: true, ...change}});
console.log(JSON.stringify({
  announced: {on: announced({}), browser: announced({browser: false}), sounds: announced({sounds: false}), quiet: announced({browser: false, sounds: false, aloud: false, title: false})},
  synced: {
    sounds: synced({}, {sounds: false}), aloud: synced({}, {aloud: false}), both: synced({}, {sounds: false, aloud: false}),
    stays: synced({sounds: false, aloud: false}, {sounds: false, aloud: false}), back: synced({sounds: false, aloud: false}, {}), title: synced({}, {title: false}),
  },
  spoken: {on: spoken(true, false), off: spoken(false, false), bubbles: spoken(false, true), both: spoken(true, true)},
  agents: {
    all: perAgent({}), aloud: perAgent(OFF({aloud: false})), sound: perAgent(OFF({sound: false})), bubbles: perAgent(OFF({bubbles: false})),
    mute: perAgent(OFF({sound: false, aloud: false})), none: perAgent(OFF({sound: false, aloud: false, bubbles: false})), other: perAgent({s9: {sound: false, aloud: false, bubbles: false}}),
    mayday: perAgent(OFF({sound: false, aloud: false, bubbles: false}), "mayday"),
  },
}));
"""


class TestChannelSettings(HubCase):
    def file(self) -> Path:
        return self.state / "settings.json"

    def free_save(self, payload: dict) -> tuple[int, dict]:
        good = self.guard(self.host)
        status, _, body = self.post_json("/api/settings/sign", payload, good)
        self.assertEqual((status, json.loads(body)["payload"]), (200, None), body)
        status, _, body = self.post_json("/api/settings", {**payload, "proof": None}, good)
        return status, json.loads(body) if status == 200 else {}

    def test_every_channel_is_on_by_default_and_the_hub_keeps_no_notify_flag(self):
        current = self.snapshot()["settings"]
        self.assertEqual((settings.SETTINGS["channels"], current["channels"]), (ON, ON))
        self.assertNotIn("notify", settings.SETTINGS)
        self.assertNotIn("notify", current)

    def test_a_stored_notify_flag_becomes_the_browser_channel_and_every_other_value_survives(self):
        current = self.snapshot()["settings"]
        older = {**{key: value for key, value in current.items() if key != "channels"}, "latitude": 52.5, "theme": "dark", "estimation": "points"}
        for notify in (True, False):
            with self.subTest(notify=notify):
                self.file().write_text(json.dumps({**older, "notify": notify}), encoding="utf-8")
                self.assertEqual(settings.Settings(self.file()).get(), {**older, "channels": {**ON, "browser": notify}})
        self.file().write_text(json.dumps({**older, "notify": False, "channels": {**ON, "title": False}}), encoding="utf-8")
        self.assertEqual(settings.Settings(self.file()).get()["channels"], {**ON, "title": False})
        self.file().write_text(json.dumps({**older, "notify": "yes"}), encoding="utf-8")
        self.assertEqual(settings.Settings(self.file()).get(), settings.SETTINGS)
        self.file().write_text(json.dumps({**older, "notify": False}), encoding="utf-8")
        migrated = settings.Settings(self.file())
        migrated.put({**migrated.get(), "theme": "light"}, migrated.get())
        written = json.loads(self.file().read_text(encoding="utf-8"))
        self.assertEqual((written["channels"], "notify" in written, written["latitude"], written["theme"]), ({**ON, "browser": False}, False, 52.5, "light"))

    def test_each_channel_switches_off_alone_without_a_passkey_and_survives_a_reload(self):
        for chosen in (*({**ON, name: False} for name in ON), dict.fromkeys(ON, False), ON):
            with self.subTest(chosen=chosen):
                status, saved = self.free_save({**self.snapshot()["settings"], "channels": chosen})
                self.assertEqual((status, saved["settings"]["channels"]), (200, chosen))
                self.assertEqual(json.loads(self.file().read_text(encoding="utf-8"))["channels"], chosen)
                self.assertEqual(settings.Settings(self.file()).get()["channels"], chosen)
                self.assertEqual(self.snapshot()["settings"]["channels"], chosen)

    def test_channels_are_validated_and_the_old_notify_key_is_refused(self):
        current = self.snapshot()["settings"]
        good = self.guard(self.host)
        without = {key: value for key, value in current.items() if key != "channels"}
        wrongs = [{**ON, "browser": value} for value in ("yes", 1, 0, None, [])]
        wrongs += [{key: value for key, value in ON.items() if key != "title"}, {**ON, "email": True}, {}, "all", ["browser"], None, True]
        payloads = [{**current, "channels": wrong} for wrong in wrongs] + [{**current, "notify": True}, without, {**without, "notify": False}]
        for payload in payloads:
            with self.subTest(payload=payload.get("channels"), notify=payload.get("notify")):
                self.assertEqual(self.post_json("/api/settings", payload, good)[0], 400)
        self.assertFalse(self.file().exists())
        self.assertEqual(self.snapshot()["settings"]["channels"], ON)


class TestChannelGates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        files = [TEMPLATES / name for name in ("page-alerts.js", "page-speech.js", "radioset.js", "bubbles.js", "voice.js")]
        done = subprocess.run(["node", "-e", PROBE, *map(str, files)], capture_output=True, text=True, timeout=60, check=True)
        cls.data = json.loads(done.stdout)

    def test_the_browser_channel_alone_gates_the_desktop_notifications(self):
        announced = self.data["announced"]
        self.assertEqual(announced["on"]["shown"], ["Mayday from Docs", "Review waiting", "Radio from Stage"])
        self.assertEqual(announced["browser"], {"shown": [], "played": ["mayday"], "spoken": [2]})

    def test_the_sound_channel_alone_gates_the_alert_tones(self):
        announced = self.data["announced"]
        self.assertEqual(announced["on"]["played"], ["mayday"])
        self.assertEqual(announced["sounds"], {"shown": announced["on"]["shown"], "played": [], "spoken": [2]})

    def test_with_every_channel_off_the_rows_still_reach_the_reader_which_drops_their_audio_itself(self):
        self.assertEqual(self.data["announced"]["quiet"], {"shown": [], "played": [], "spoken": [2]})

    def test_the_read_aloud_channel_plans_no_audible_step_and_keeps_the_silent_bubble(self):
        self.assertEqual(self.data["spoken"], {"on": [False], "off": [], "bubbles": [True], "both": [False]})

    def test_an_agents_own_switches_silence_its_speech_its_sounds_or_its_bubble_and_spare_other_agents_and_a_mayday(self):
        agents = self.data["agents"]
        self.assertEqual((agents["all"], agents["other"], agents["mayday"]), ([[False, True]], [[False, True]], [[False, True]]))
        self.assertEqual((agents["aloud"], agents["sound"], agents["bubbles"]), ([[False, True]], [[False, True]], [[False, False]]))
        self.assertEqual((agents["mute"], agents["none"]), ([[True, True]], []))

    def test_switching_a_channel_off_stops_what_it_already_queued_and_every_switch_redraws_the_title(self):
        synced = self.data["synced"]
        self.assertEqual(synced["sounds"], ["silence", "title"])
        self.assertEqual(synced["aloud"], ["cancel", "title"])
        self.assertEqual(synced["both"], ["silence", "cancel", "title"])
        self.assertEqual((synced["stays"], synced["back"], synced["title"]), (["title"], ["title"], ["title"]))


if __name__ == "__main__":
    unittest.main()
