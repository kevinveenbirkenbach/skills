from __future__ import annotations

import base64
import io
import json
import struct
import subprocess
import unittest
import wave

from hub_support import VOICE
from kvb_orchestrator import engines, settings

VOICE_PROBE = """
const V = require(process.argv[1]);
const settings = JSON.parse(process.argv[2]);
const rows = [
  {class: "mayday", to: [], source: "s1", speech: "m", voice: "v"},
  {class: "pan-pan", to: ["Operator"], source: "s1", speech: "p", voice: "v"},
  {class: "security", to: [], source: "s2", speech: "s", voice: "v"},
  {class: "direct", to: ["Operator"], source: "s2", speech: "d", voice: "v"},
  {class: "direct", to: ["Docs"], source: "s3", speech: "o", voice: "v"},
  {class: "broadcast", to: [], source: "s3", speech: "b", voice: "v"},
  {class: "broadcast", to: [], source: "s3", speech: "", voice: "v"},
];
const filters = [
  {on: false, classes: ["broadcast", "direct", "security", "pan-pan", "mayday"], muted: []},
  {on: true, classes: ["mayday"], muted: ["s1"]},
  {on: true, classes: ["direct", "mayday"], muted: ["s2"]},
  {on: true, classes: ["broadcast", "direct", "security", "pan-pan", "mayday"], muted: []},
];
let pending = [];
for (const cls of ["broadcast", "direct", "security", "mayday", "broadcast", "pan-pan", "mayday", "direct"]) {
  pending = V.enqueue(pending, {cls, text: `${cls}-${pending.length}`}, 6);
}
console.log(JSON.stringify({
  tones: rows.map((row) => V.toneOf(row, "Operator")),
  spoken: filters.map((filter) => rows.map((row) => V.speakable(row, filter))),
  queue: pending.map((item) => item.cls),
  loud: settings.map((one) => Object.fromEntries(["mayday", "review", "direct", "radio"].map((tone) => [tone, V.loudness(tone, one)]))),
  beeps: settings.map((one) => V.beep({mayday: true, review: true, direct: true, radio: true}, one, ["mayday", "review", "direct", "radio"])),
  frames: [V.frames(1.5, 16000, 120), V.frames(130, 16000, 120), V.frames(0, 16000, 120)],
  wav: Buffer.from(V.wav(Float32Array.from([0, 0.5, -0.5, 1, -1, 2, -2]), 16000)).toString("base64"),
}));
"""


class TestVoiceModule(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        quiet = {name: {"on": False, "volume": 0.1} for name in settings.TONES}
        cls.settings = [
            settings.SETTINGS,
            {**settings.SETTINGS, "music": {"on": True, "volume": 1.0}, "sounds": quiet},
            {**settings.SETTINGS, "sounds": {**settings.SETTINGS["sounds"], "mayday": {"on": True, "volume": 0.0}, "radio": {"on": True, "volume": 0.8}}},
            *({**settings.SETTINGS, "squelch": 0.0, "music": {"on": music, "volume": 1.0}, "sounds": {name: {"on": True, "volume": 1.0} for name in settings.TONES}} for music in (True, False)),
        ]
        command = ["node", "-e", VOICE_PROBE, str(VOICE), json.dumps(cls.settings)]
        done = subprocess.run(command, capture_output=True, text=True, timeout=60, check=True)
        cls.data = json.loads(done.stdout)

    def test_urgency_picks_the_tone_and_mayday_is_never_quieter(self):
        self.assertEqual(self.data["tones"], ["mayday", "mayday", "direct", "direct", "radio", "radio", "radio"])
        self.assertEqual(len(self.data["loud"]), len(self.settings))
        for loud in self.data["loud"]:
            with self.subTest(loud=loud):
                self.assertEqual(loud["mayday"], max(loud.values()))
        self.assertEqual([loud["mayday"] for loud in self.data["loud"]], [0.9, 1.0, 0.8, 0.0, 0.0])

    def test_squelch_at_zero_plays_no_tone_with_music_on_or_off(self):
        self.assertEqual(self.data["beeps"], ["mayday", None, "mayday", None, None])
        self.assertEqual([set(loud.values()) for loud in self.data["loud"][3:]], [{0.0}, {0.0}])

    def test_the_radio_filter_picks_classes_and_stations(self):
        self.assertEqual(self.data["spoken"], [
            [False] * 7,
            [True, False, False, False, False, False, False],
            [True, False, False, False, True, False, False],
            [True, True, True, True, True, True, False],
        ])

    def test_the_queue_puts_alarms_first_and_drops_routine_traffic(self):
        self.assertEqual(self.data["queue"], ["mayday", "mayday", "pan-pan", "security", "broadcast", "direct"])

    def test_the_recording_is_encoded_as_16_khz_mono_pcm(self):
        body = base64.b64decode(self.data["wav"])
        self.assertEqual(engines.wav_seconds(body), 7 / engines.STT_RATE)
        with wave.open(io.BytesIO(body)) as reader:
            self.assertEqual((reader.getnchannels(), reader.getsampwidth(), reader.getframerate(), reader.getnframes()), (1, 2, 16000, 7))
            self.assertEqual(struct.unpack("<7h", reader.readframes(7)), (0, 16383, -16384, 32767, -32768, 32767, -32768))
        self.assertEqual(self.data["frames"], [24000, 16000 * 120, 0])


if __name__ == "__main__":
    unittest.main()
