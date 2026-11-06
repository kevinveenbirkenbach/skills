from __future__ import annotations

import dataclasses
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import unittest
import wave
from pathlib import PurePosixPath
from unittest import mock

from hub_case import HubCase
from hub_engines import OPERATOR_VOICE, VOICES, log_rows, wav_bytes
from hub_support import HOST_STATE, HUB, server
from kvb_orchestrator import council, engines, exchange, handler, phrasing


class TestHubSpeech(HubCase):
    def test_voices_come_from_the_models_and_stick_to_their_session(self):
        speech = self.httpd.hub.speech
        self.assertEqual(list(speech.voices), VOICES)
        self.assertEqual((speech.voices["de_DE-solo-medium:0"], speech.voices["en_US-test-high:3"]), (("de_DE-solo-medium", None), ("en_US-test-high", 3)))
        pool = [voice for voice in VOICES if voice != OPERATOR_VOICE]
        self.assertEqual((speech.pool, speech.operator), (pool, OPERATOR_VOICE))
        keys = [f"session-{n}" for n in range(40)] + ["s1", "name:Docs"]
        picked = [engines.voice_of(key, pool, OPERATOR_VOICE) for key in keys]
        self.assertEqual(picked, [pool[int(hashlib.sha256(key.encode()).hexdigest(), 16) % len(pool)] for key in keys])
        self.assertEqual(picked, [speech.voice_of(key) for key in keys])
        self.assertEqual(picked, [engines.voice_of(key, list(pool), OPERATOR_VOICE) for key in keys])
        self.assertEqual(set(picked), set(pool))
        self.assertEqual(speech.voice_of("Operator"), OPERATOR_VOICE)
        self.assertEqual(engines.voice_of("s1", [], OPERATOR_VOICE), OPERATOR_VOICE)
        self.assertEqual(engines.voice_of("s1", [], ""), "")
        with self.assertRaises(server.ToolError):
            engines.Speech(dataclasses.replace(self.engines, operator_voice="en_US-test-high:4"), self.state / "other")
        silent = engines.Speech(dataclasses.replace(self.engines, voices=self.outside, operator_voice="anything"), self.state / "silent")
        self.assertEqual((silent.voice_of("s1"), silent.describe()["operator"], silent.describe()["tts"]), ("", "", False))
        deaf = engines.Speech(dataclasses.replace(self.engines, whisper=self.outside / "missing"), self.state / "deaf")
        self.assertFalse(deaf.describe()["stt"])

    @unittest.skipIf(os.geteuid() == 0, "root searches every directory")
    def test_the_off_state_names_the_missing_part_with_its_path(self):
        self.assertEqual({key: self.httpd.hub.speech.describe()[key] for key in ("tts", "stt", "tts_off", "stt_off")}, {"tts": True, "stt": True, "tts_off": "", "stt_off": ""})
        lone = self.outside / "lone"
        lone.mkdir()
        (lone / "solo.onnx").write_bytes(b"onnx")
        cases = (
            ({"piper": self.outside / "piper"}, "tts_off", f"the Piper executable {self.outside / 'piper'} is missing or not executable"),
            ({"voices": self.outside}, "tts_off", f"the voice directory {self.outside} holds no <model>.onnx voice"),
            ({"voices": lone}, "tts_off", f"the voice config {lone / 'solo.onnx'}.json is missing, unreadable or names no 1 to {engines.SPEAKER_LIMIT} speakers"),
            ({"whisper": self.outside / "whisper-cli"}, "stt_off", f"the whisper.cpp executable {self.outside / 'whisper-cli'} is missing or not executable"),
            ({"whisper_model": self.outside / "model.bin"}, "stt_off", f"the whisper.cpp model {self.outside / 'model.bin'} is missing or not readable"),
            ({"whisper_model": self.outside}, "stt_off", f"the whisper.cpp model {self.outside} is not a file"),
        )
        for number, (change, field, message) in enumerate(cases):
            with self.subTest(change=change):
                state = engines.Speech(dataclasses.replace(self.engines, **change), self.state / f"case-{number}").describe()
                self.assertEqual((state[field[:3]], state[field]), (False, message))
        voices = self.engines.voices
        whisper = self.outside / "whisper" / "whisper-cli"
        whisper.parent.mkdir()
        whisper.write_bytes(self.engines.whisper.read_bytes())
        whisper.chmod(0o755)
        for folder in (voices, whisper.parent):
            folder.chmod(0o644)
            self.addCleanup(folder.chmod, 0o755)
        image = engines.Speech(dataclasses.replace(self.engines, whisper=whisper), self.state / "image").describe()
        self.assertEqual({key: image[key] for key in ("tts", "voices", "operator", "tts_off")}, {"tts": False, "voices": 0, "operator": "", "tts_off": f"the voice directory {voices} is missing or not searchable"})
        self.assertEqual((image["stt"], image["stt_off"]), (False, f"the whisper.cpp executable {whisper} lies under {whisper.parent}, which the hub may not search"))
        status, _, body = self.post_json("/api/tts", {"text": "radio check", "voice": OPERATOR_VOICE}, self.guard(self.host))
        self.assertEqual((status, body.decode()), (503, f"speech output is off: the voice directory {voices} is missing or not searchable\n"))

    def test_speech_output_is_guarded_whitelisted_capped_and_cached(self):
        good = self.guard(self.host)
        calls = self.engines.scratch / "piper.jsonl"
        cache = self.state / "tts"
        request = {"text": "all stations, this is Docs, board, out", "voice": "en_US-test-high:2"}
        for headers in ({k: v for k, v in good.items() if k != "X-Kvb-Orchestrator"}, {k: v for k, v in good.items() if k != "Origin"}, {**good, "Origin": "http://evil.example"}):
            with self.subTest(headers=headers):
                self.assertEqual(self.post_json("/api/tts", request, headers)[0], 403)
        for broken in (
            {**request, "voice": "en_US-test-high:4"},
            {**request, "voice": "zero:0"},
            {**request, "voice": "bad name!:0"},
            {**request, "voice": "broken:0"},
            {**request, "voice": ["en_US-test-high:2"]},
            {**request, "text": "x" * (phrasing.SPEECH_LIMIT + 1)},
            {**request, "text": " \n\t "},
            {**request, "text": "bell \x07 here"},
            {**request, "text": 7},
            {**request, "extra": 1},
            {"text": request["text"]},
        ):
            with self.subTest(broken=broken):
                self.assertEqual(self.post_json("/api/tts", broken, good)[0], 400)
        self.assertEqual(log_rows(calls), [])
        status, headers, body = self.post_json("/api/tts", request, good)
        self.assertEqual((status, headers["content-type"], headers["content-security-policy"]), (200, "audio/wav", exchange.PLAIN_CSP), body)
        with wave.open(io.BytesIO(body)) as reader:
            self.assertEqual((reader.getnchannels(), reader.getframerate(), reader.getnframes()), (1, 22050, len(request["text"]) + 1))
        key = hashlib.sha256(f"{request['voice']}\n{request['text']}".encode()).hexdigest()
        self.assertEqual(sorted(path.name for path in cache.iterdir()), [f"{key}.wav"])
        self.assertEqual(self.post_json("/api/tts", {**request, "text": "  all stations,\nthis is Docs, board, out "}, good)[2], body)
        self.assertEqual(self.post_json("/api/tts", {**request, "text": "x" * phrasing.SPEECH_LIMIT}, good)[0], 200)
        rows = log_rows(calls)
        model = self.engines.voices / "en_US-test-high.onnx"
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["argv"][:5], ["--model", str(model), "--config", f"{model}.json", "--output-file"])
        self.assertEqual(rows[0]["argv"][6:], ["--speaker", "2"])
        self.assertTrue(rows[0]["argv"][5].startswith(f"{cache}/.{key}-"))
        self.assertEqual((rows[0]["text"], rows[0]["tmp"], rows[0]["cwd"]), (f"{request['text']}\n", str(self.engines.scratch), str(self.engines.scratch)))
        self.assertEqual(self.post_json("/api/tts", {"text": "solo", "voice": "de_DE-solo-medium:0"}, good)[0], 200)
        self.assertNotIn("--speaker", log_rows(calls)[-1]["argv"])
        status, _, body = self.post_json("/api/tts", {**request, "text": "FAIL now"}, good)
        self.assertEqual(status, 502, body)
        self.assertIn(b"exit code 3", body)
        self.assertEqual([path.name for path in cache.iterdir() if path.name.startswith(".")], [])
        with mock.patch.object(engines, "TTS_KEEP", 2):
            for number in range(3):
                self.assertEqual(self.post_json("/api/tts", {**request, "text": f"line {number}"}, good)[0], 200)
        kept = {hashlib.sha256(f"{request['voice']}\nline {number}".encode()).hexdigest() + ".wav" for number in (1, 2)}
        self.assertEqual({path.name for path in cache.iterdir()}, kept)
        with mock.patch.object(self.httpd.hub.speech, "voices", {}):
            self.assertEqual(self.post_json("/api/tts", request, good)[0], 503)
        self.assertEqual(self.scripts.calls, [])

    def test_speech_input_checks_the_guard_type_size_and_format(self):
        good = self.guard(self.host)
        calls = self.engines.scratch / "whisper.jsonl"
        clip = wav_bytes(1, 2, engines.STT_RATE, b"\x01\x00" * engines.STT_RATE)

        def post(body: bytes, headers: dict[str, str]) -> tuple[int, dict, bytes]:
            return self.call("POST", "/api/stt", body, {**headers, "Content-Type": "audio/wav"})

        for headers in ({k: v for k, v in good.items() if k != "X-Kvb-Orchestrator"}, {k: v for k, v in good.items() if k != "Origin"}, {**good, "Origin": "http://evil.example"}):
            with self.subTest(headers=headers):
                self.assertEqual(post(clip, headers)[0], 403)
        for content_type in ("application/octet-stream", "audio/x-wav", "text/plain", "application/json"):
            with self.subTest(content_type=content_type):
                self.assertEqual(self.call("POST", "/api/stt", clip, {**good, "Content-Type": content_type})[0], 415)
        self.assertEqual(self.call("POST", "/api/stt", clip, good)[0], 415)
        self.assertEqual(self.call("POST", "/api/stt", b"RIFF", {**good, "Content-Type": "audio/wav", "Content-Length": str(engines.STT_LIMIT + 1)})[0], 413)
        for broken in (
            b"not a wav",
            wav_bytes(1, 2, 44100, b"\x00\x00" * 100),
            wav_bytes(2, 2, engines.STT_RATE, b"\x00\x00" * 200),
            wav_bytes(1, 1, engines.STT_RATE, b"\x00" * 100),
            wav_bytes(1, 2, engines.STT_RATE, b""),
        ):
            with self.subTest(broken=broken[:40]):
                self.assertEqual(post(broken, good)[0], 400)
        with mock.patch.object(engines, "STT_SECONDS", 1):
            self.assertEqual(post(wav_bytes(1, 2, engines.STT_RATE, b"\x00\x00" * (engines.STT_RATE + 1)), good)[0], 400)
        self.assertEqual(log_rows(calls), [])
        status, headers, body = post(clip, good)
        self.assertEqual((status, headers["content-type"]), (200, "application/json"), body)
        self.assertEqual(json.loads(body), {"text": "hello from the mic second line"})
        argv = ["--model", str(self.engines.whisper_model), "--file", "-", "--output-txt", "--language", "auto", "--no-prints", "--suppress-nst"]
        self.assertEqual(log_rows(calls), [{"argv": argv, "sha256": hashlib.sha256(clip).hexdigest()}])
        long = wav_bytes(1, 2, engines.STT_RATE, b"\x00\x00" * engines.STT_RATE * 40)
        self.assertGreater(len(long), handler.BODY_LIMIT)
        self.assertEqual(post(long, good)[0], 200)
        status, _, body = post(wav_bytes(1, 2, engines.STT_RATE, b"FAIL" * 100), good)
        self.assertEqual(status, 502, body)
        with mock.patch.object(self.httpd.hub.speech, "input_gap", return_value="the whisper.cpp model m is missing or not readable"):
            self.assertEqual(post(clip, good), (503, mock.ANY, b"speech input is off: the whisper.cpp model m is missing or not readable\n"))
        self.assertEqual(self.scripts.calls, [])
        self.assertEqual(self.get("/api/stt")[0], 405)

    def test_the_server_requires_every_engine_argument(self):
        args = {
            "--bind": "127.0.0.1", "--listen-port": "0", "--public-port": "1", "--council": str(self.council), "--pages": str(self.pages), "--state": str(self.state),
            "--host-state": str(HOST_STATE), "--skills": str(self.outside), "--transcripts": str(self.projects), "--templates": str(HUB / "templates"), "--repos": str(self.repos),
            "--worktrees": str(self.worktrees), "--timers": str(self.timers), "--llm-key-file": os.devnull, "--llm-url": "", "--llm-model": "",
            "--piper": str(self.engines.piper), "--voices": str(self.engines.voices), "--operator-voice": "en_US-test-high:9", "--whisper": str(self.engines.whisper),
            "--whisper-model": str(self.engines.whisper_model), "--scratch": str(self.engines.scratch), "--approvers": str(self.approvers),
        }

        def run(given: dict[str, str]) -> subprocess.CompletedProcess:
            argv = [part for pair in given.items() for part in pair]
            return subprocess.run([sys.executable, str(HUB / "server.py"), *argv], capture_output=True, text=True, timeout=60, check=False)

        for name in ("--piper", "--voices", "--operator-voice", "--whisper", "--whisper-model", "--scratch", "--approvers"):
            with self.subTest(name=name):
                done = run({key: value for key, value in args.items() if key != name})
                self.assertEqual(done.returncode, 2, done.stderr)
                self.assertIn(f"required: {name}", done.stderr)
        done = run(args)
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn("the operator voice 'en_US-test-high:9' is not installed", done.stderr)


class TestSpeechImage(unittest.TestCase):
    def test_every_directory_a_chmod_without_search_bit_creates_is_opened_again(self):
        text = (HUB / "Dockerfile").read_text(encoding="utf-8").replace("\\\n", " ")
        steps = [" ".join(step.split()) for step in text.splitlines() if step.strip() and not step.lstrip().startswith("#")]
        closed: dict[str, int] = {}
        for number, step in enumerate(steps):
            found = re.fullmatch(r"(?:ADD|COPY) .*--chmod=([0-7]{3,4}) .* (/\S+)", step)
            if found and not int(found[1], 8) & 0o111:
                closed[str(PurePosixPath(found[2]).parent)] = number
        self.assertEqual(sorted(closed), ["/opt/voices", "/opt/whisper"])
        for folder, number in closed.items():
            with self.subTest(folder=folder):
                self.assertTrue(any(step.startswith("RUN chmod 0755 ") and folder in step.split()[3:] for step in steps[number + 1 :]), steps[number])


class TestPhraseology(unittest.TestCase):
    def test_every_class_speaks_in_maritime_phraseology(self):
        cases = (
            (("mayday", "Docs", [], "MAYDAY disk full"), "MAYDAY MAYDAY MAYDAY, this is Docs Docs Docs, disk full, over"),
            (("mayday", "Docs", ["Skills"], "mayday, mayday: disk full"), "MAYDAY MAYDAY MAYDAY, this is Docs Docs Docs, disk full, over"),
            (("pan-pan", "Docs", ["Skills"], "PAN-PAN: slow"), "PAN-PAN PAN-PAN PAN-PAN, all stations, this is Docs, slow, over"),
            (("security", "Maintainer", ["Skills", "Docs"], "SECURITE rotate"), "SECURITE SECURITE SECURITE, all stations, this is Maintainer, rotate, over"),
            (("call", "Skills", ["Maintainer"], "ready"), "Maintainer, Maintainer, this is Skills, ready, over"),
            (("post", "Skills", ["Alpha", "Beta"], "ready"), "Alpha and Beta, Alpha and Beta, this is Skills, ready, over"),
            (("call", "Docs", ["Ops"], "MAYDAY is only a word here"), "Ops, Ops, this is Docs, MAYDAY is only a word here, over"),
            (("post", "Skills", [], "lost target"), "all stations, this is Skills, lost target, out"),
            (("newsletter", "Maintainer", [], "board"), "all stations, this is Maintainer, board, out"),
            (("broadcast", "Operator", [], "[kvb-orchestrator msg 0123456789abcdef] deploy now file: /home/op/x.txt"), "all stations, this is Operator, deploy now, out"),
            (("broadcast", "Docs", [], "  two\n lines\t here "), "all stations, this is Docs, two lines here, out"),
            (("broadcast", "", [], "-"), "all stations, this is unknown station, out"),
        )
        for arguments, expected in cases:
            with self.subTest(arguments=arguments):
                self.assertEqual(phrasing.phrase(*arguments), expected)

    def test_a_phrase_fits_the_speech_limit_on_one_line(self):
        for cls in council.CLASSES:
            with self.subTest(cls=cls):
                spoken = phrasing.phrase(cls, "n" * 900, ["a\nb " * 300] * 9, "word\n" * 9000)
                self.assertLessEqual(len(spoken), phrasing.SPEECH_LIMIT)
                self.assertTrue(phrasing.SPOKEN_LINE.fullmatch(spoken))
        self.assertTrue(phrasing.phrase("broadcast", "Docs", [], "word " * 300).endswith("word, out"))


if __name__ == "__main__":
    unittest.main()
