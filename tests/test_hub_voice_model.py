from __future__ import annotations

import dataclasses
import json
import os
import unittest
from pathlib import Path
from unittest import mock

from hub_case import HubCase
from test_hub_voice_input import FIXTURES, spoken

WHISPER = Path(os.environ.get("KVB_WHISPER_CLI", "/nonexistent/whisper-cli"))
MODEL = Path(os.environ.get("KVB_WHISPER_MODEL", "/nonexistent/ggml-small-q8_0.bin"))
QUEUED = os.environ.get("KVB_VOICE_INTEGRATION") == "1"
READY = os.access(WHISPER, os.X_OK) and MODEL.is_file()
REASON = (
    "real Whisper run: needs KVB_WHISPER_CLI and KVB_WHISPER_MODEL from the operator rows of requirement 013 "
    "and KVB_VOICE_INTEGRATION=1, which only the queue.py hold command line sets"
)


@unittest.skipUnless(QUEUED and READY, REASON)
class TestVoiceModel(HubCase):
    def test_the_real_model_transcribes_the_german_and_the_english_fixture(self):
        speech = self.httpd.hub.speech
        with mock.patch.object(speech, "engines", dataclasses.replace(speech.engines, whisper=WHISPER, whisper_model=MODEL)):
            for name, words in (("hallo-welt.wav", "hallo welt"), ("hello-world.wav", "hello world")):
                with self.subTest(name=name):
                    status, _, body = self.call("POST", "/api/stt", (FIXTURES / name).read_bytes(), {**self.guard(self.host), "Content-Type": "audio/wav"})
                    self.assertEqual(status, 200, body)
                    self.assertEqual(spoken(json.loads(body)["text"]), words)


if __name__ == "__main__":
    unittest.main()
