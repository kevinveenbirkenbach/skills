from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

from hub_case import HubCase
from hub_engines import log_rows, wav_bytes
from kvb_orchestrator import engines

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "voice"
DUTCH = wav_bytes(1, 2, engines.STT_RATE, b"\x02\x00" * engines.STT_RATE)
FRENCH = wav_bytes(1, 2, engines.STT_RATE, b"\x03\x00" * engines.STT_RATE)
HEARD = {
    "hallo-welt.wav": {"auto": ["de", "Hallo Welt."], "de": [0.9, "Hallo Welt."], "en": [0.3, "Hollow felt."]},
    "hello-world.wav": {"auto": ["en", "Hello world."], "de": [0.2, "Hello W\N{LATIN SMALL LETTER O WITH DIAERESIS}rld."], "en": [0.9, "Hello world."]},
    "dutch": {"auto": ["nl", "Hallo wereld."], "de": [0.7, "Hallo Welt."], "en": [0.4, "Hello world."]},
    "french": {"auto": ["fr", "Bonjour le monde."], "de": [0.2, "Bonschur."], "en": [0.6, "Bonjour world."]},
}
FAKE_WHISPER = """
import hashlib, json, os, sys
argv = sys.argv[1:]
data = sys.stdin.buffer.read()
home = os.environ["HOME"]
with open(os.path.join(home, "heard.json"), encoding="utf-8") as table:
    clip = json.load(table).get(hashlib.sha256(data).hexdigest(), {"auto": ["en", ""], "de": [0.0, ""], "en": [0.0, ""]})
with open(os.path.join(home, "whisper.jsonl"), "a", encoding="utf-8") as log:
    log.write(json.dumps({"argv": argv, "cwd": os.getcwd(), "tmp": os.environ["TMPDIR"]}) + "\\n")
with open(os.path.join(os.environ["TMPDIR"], "engine-spill.wav"), "wb") as spill:
    spill.write(data)
if b"FAIL" in data:
    sys.exit(4)
language = argv[argv.index("--language") + 1]
detected, text, sure = (*clip["auto"], 0.5) if language == "auto" else (language, clip[language][1], clip[language][0])
tokens = [{"text": "[_BEG_]", "p": 0.01}, *({"text": f" {word}", "p": sure} for word in text.split())]
with open(argv[argv.index("--output-file") + 1] + ".json", "w", encoding="utf-8") as out:
    json.dump({"result": {"language": detected}, "transcription": [{"text": text, "tokens": tokens}]}, out)
"""
KEPT = ("heard.json", "whisper.jsonl")


def spoken(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", text).lower().split())


class TestVoiceInput(HubCase):
    def setUp(self):
        super().setUp()
        self.engines.whisper.write_text(f"#!{sys.executable}\n{FAKE_WHISPER}", encoding="utf-8")
        clips = {"dutch": DUTCH, "french": FRENCH}
        heard = {hashlib.sha256(clips[name] if name in clips else (FIXTURES / name).read_bytes()).hexdigest(): table for name, table in HEARD.items()}
        (self.engines.scratch / "heard.json").write_text(json.dumps(heard), encoding="utf-8")
        self.calls = self.engines.scratch / "whisper.jsonl"

    def post(self, body: bytes, headers: dict[str, str] | None = None, length: int | None = None) -> tuple[int, dict, bytes]:
        merged = {**(self.guard(self.host) if headers is None else headers), "Content-Type": "audio/wav"}
        if length is not None:
            merged["Content-Length"] = str(length)
        return self.call("POST", "/api/stt", body, merged)

    def leftovers(self) -> list[str]:
        return sorted(path.name for path in self.engines.scratch.iterdir() if path.name not in KEPT)

    def languages(self) -> list[str]:
        return [row["argv"][row["argv"].index("--language") + 1] for row in log_rows(self.calls)]

    def test_the_german_and_the_english_fixture_come_back_as_their_words_with_the_language_detected(self):
        for name, language, words in (("hallo-welt.wav", "de", "hallo welt"), ("hello-world.wav", "en", "hello world")):
            with self.subTest(name=name):
                status, _, body = self.post((FIXTURES / name).read_bytes())
                self.assertEqual(status, 200, body)
                answer = json.loads(body)
                self.assertEqual((answer["language"], spoken(answer["text"])), (language, words))
        self.assertEqual(self.languages(), ["auto", "auto"])
        for row in log_rows(self.calls):
            self.assertEqual(row["argv"].count("--language"), 1, row)

    def test_a_third_language_is_heard_again_in_the_surer_of_german_and_english(self):
        for clip, language, words in ((DUTCH, "de", "hallo welt"), (FRENCH, "en", "bonjour world")):
            with self.subTest(language=language):
                status, _, body = self.post(clip)
                self.assertEqual(status, 200, body)
                answer = json.loads(body)
                self.assertEqual((answer["language"], spoken(answer["text"])), (language, words))
        self.assertEqual(self.languages(), ["auto", "de", "en", "auto", "de", "en"])
        self.assertEqual(self.leftovers(), [])

    def test_the_temp_directory_is_empty_after_every_request_including_a_failed_one(self):
        self.assertEqual(self.post((FIXTURES / "hello-world.wav").read_bytes())[0], 200)
        self.assertEqual(self.leftovers(), [])
        status, _, body = self.post(wav_bytes(1, 2, engines.STT_RATE, b"FAIL" * 400))
        self.assertEqual(status, 502, body)
        self.assertEqual(self.leftovers(), [])
        rows = log_rows(self.calls)
        self.assertEqual(len(rows), 2)
        for row in rows:
            used = Path(row["tmp"])
            self.assertEqual((Path(row["cwd"]), used.parent), (used, self.engines.scratch), row)
            self.assertFalse(used.exists(), row)

    def test_a_recording_over_60_seconds_or_5_mb_is_refused_and_not_transcribed(self):
        rate = engines.STT_RATE
        self.assertEqual((engines.INPUT_SECONDS, engines.INPUT_LIMIT), (60, 5 << 20))
        self.assertEqual(self.httpd.hub.speech.describe()["input"], engines.INPUT_SECONDS)
        self.assertEqual(self.post(wav_bytes(1, 2, rate, b"\x01\x00" * rate * 60))[0], 200)
        self.assertEqual(len(log_rows(self.calls)), 1)
        status, _, body = self.post(wav_bytes(1, 2, rate, b"\x01\x00" * (rate * 60 + 1)))
        self.assertEqual((status, body), (400, b"the recording must last more than 0 and at most 60 seconds\n"))
        self.assertEqual(self.post(b"\x00" * engines.INPUT_LIMIT)[0], 400)
        self.assertEqual(self.post(b"RIFF", length=engines.INPUT_LIMIT + 1)[0], 413)
        self.assertEqual(len(log_rows(self.calls)), 1)
        self.assertEqual(self.leftovers(), [])

    def test_another_origin_host_or_a_missing_csrf_header_is_refused_and_not_transcribed(self):
        clip = (FIXTURES / "hallo-welt.wav").read_bytes()
        good = self.guard(self.host)
        refused = (
            {key: value for key, value in good.items() if key != "X-Kvb-Orchestrator"},
            {key: value for key, value in good.items() if key != "Origin"},
            {**good, "Origin": "http://evil.example"},
            {**good, "Origin": f"http://localhost:{self.port + 1}"},
            {**good, "Host": "evil.example"},
        )
        for headers in refused:
            with self.subTest(headers=headers):
                self.assertEqual(self.post(clip, headers)[0], 403)
        self.assertEqual(log_rows(self.calls), [])
        self.assertEqual(self.post(clip, good)[0], 200)

    def test_without_a_model_the_endpoint_and_the_button_state_name_the_operator_row(self):
        missing = self.outside / "ggml-missing.bin"
        speech = self.httpd.hub.speech
        with mock.patch.object(speech, "engines", dataclasses.replace(self.engines, whisper_model=missing)):
            state = speech.describe()
            status, _, body = self.post((FIXTURES / "hallo-welt.wav").read_bytes())
        self.assertFalse(state["stt"])
        self.assertEqual(state["stt_off"], f"the whisper.cpp model {missing} is missing or not readable; the operator row {engines.MODEL_ROW} installs it")
        self.assertEqual(status, 503, body)
        self.assertIn(f"the operator row {engines.MODEL_ROW} installs it".encode(), body)
        self.assertEqual(log_rows(self.calls), [])
        self.assertEqual(engines.MODEL_ROW, "make orchestrator-install")


if __name__ == "__main__":
    unittest.main()
