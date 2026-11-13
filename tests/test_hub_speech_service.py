from __future__ import annotations

import dataclasses
import http.client
import http.server
import json
import socket
import struct
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import hub_case
from hub_case import HubCase
from hub_engines import log_rows, wav_bytes, write_engines
from kvb_orchestrator import engines, errors, keys, speechservice, transport
from kvb_orchestrator.speechservice import Service

KEY = "sk-speech-0123456789abcdef"
VOICE = "en_US-test-high:2"
LINE = "all stations, this is Docs, disk at ninety percent, out"
MAYDAY = "MAYDAY MAYDAY MAYDAY"
SPOKEN = wav_bytes(1, 2, 22050, b"\x01\x00" * 2205)
OVERFLOW = struct.pack("<4sI", b"RIFF", len(SPOKEN) - 108) + SPOKEN[8:-100]
CLIP = wav_bytes(1, 2, engines.STT_RATE, b"\x01\x00" * engines.STT_RATE)
MALFORMED = "the speech service key must be printable ASCII without whitespace: check KVB_ORCHESTRATOR_SPEECH_KEY_FILE"
STREAMING = 0xFFFFFFFF
DATA = SPOKEN.index(b"data")


def streamed(riff: int, data: int, body: bytes = SPOKEN) -> bytes:
    at = body.index(b"data", 12)
    return body[:4] + struct.pack("<I", riff) + body[8 : at + 4] + struct.pack("<I", data) + body[at + 8 :]


class FakeService(http.server.ThreadingHTTPServer):
    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), FakeHandler)
        self.mode = "ok"
        self.requests: list[dict] = []
        self.thread = threading.Thread(target=self.serve_forever, args=(0.05,), daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}/v1"

    def stop(self) -> None:
        self.shutdown()
        self.server_close()
        self.thread.join(10)

    def handle_error(self, request, client_address):
        return None


class FakeHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return None

    def answer(self, status: int, kind: str, body: bytes, headers: dict[str, str]) -> None:
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        for name, value in headers.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def record(self, method: str, body: bytes) -> None:
        self.server.requests.append({"method": method, "path": self.path, "headers": {name.lower(): value for name, value in self.headers.items()}, "body": body})

    def do_GET(self):
        self.record("GET", b"")
        self.answer(200, "audio/wav", SPOKEN, {})

    def trickle(self, data: bytes) -> None:
        for byte in data:
            self.wfile.write(bytes([byte]))
            time.sleep(0.2)

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        self.record("POST", body)
        mode = "trickle-body" if b"trickle" in body else self.server.mode
        speech = self.path.endswith(speechservice.SPEECH_PATH)
        if mode == "trickle-body":
            self.send_response(200)
            self.send_header("Content-Length", str(len(SPOKEN)))
            self.end_headers()
            self.trickle(SPOKEN)
        elif mode == "trickle-head":
            self.trickle(b"HTTP/1.1 200 OK\r\n" * 40)
        elif mode == "short":
            self.send_response(200)
            self.send_header("Content-Length", str(len(SPOKEN)))
            self.end_headers()
            self.wfile.write(SPOKEN[:1000])
            self.close_connection = True
        elif mode == "truncated":
            self.answer(200, "audio/wav", SPOKEN[:-100], {})
        elif mode == "overflow":
            self.answer(200, "audio/wav", OVERFLOW, {})
        elif mode == "error":
            self.answer(500, "text/plain", f"upstream broke, your key {self.headers['Authorization']}".encode(), {})
        elif mode == "redirect":
            self.answer(302, "text/plain", b"", {"Location": "/elsewhere"})
        elif mode == "garbage":
            self.answer(200, "audio/wav", b"RIFF no wave here", {})
        elif mode == "notext":
            self.answer(200, "application/json", b'{"words": []}', {})
        elif mode == "slow":
            time.sleep(1.5)
            self.answer(200, "audio/wav", SPOKEN, {})
        elif mode == "big":
            self.answer(200, "audio/wav", SPOKEN + b"\x00" * 4096, {})
        elif mode == "streamed":
            self.answer(200, "audio/wav", streamed(STREAMING, STREAMING), {})
        elif mode == "streamed-short":
            self.answer(200, "audio/wav", streamed(STREAMING, len(SPOKEN) - DATA - 8)[:-100], {})
        elif speech:
            self.answer(200, "audio/wav", SPOKEN, {})
        else:
            self.answer(200, "application/json", json.dumps({"text": " hello [BLANK_AUDIO] from  the service "}).encode(), {})


class TestServiceUrl(unittest.TestCase):
    def test_only_a_plain_http_or_https_base_is_accepted_and_empty_keeps_the_engines(self):
        self.assertFalse(Service(url="", key="").enabled())
        for url in ("http://127.0.0.1:8000/v1", "https://speech.example/v1", "http://svc-ai-speech/v1", "https://[::1]:8443/v1"):
            with self.subTest(url=url):
                self.assertTrue(Service(url=url, key="").enabled())
        for url in (
            "ftp://speech.example/v1", "speech.example/v1", "https:///v1", "https://user:pass@speech.example/v1", "https://speech.example/v1?key=1",
            "https://speech.example/v1#top", "https://speech.example:0/v1", "https://speech.example:99999/v1", "https://speech.example/v 1",
            "https://speech.example/%761", "https://speech.example/v1\n", "https://spéech.example/v1", "file:///etc/passwd",
        ):
            with self.subTest(url=url), self.assertRaises(errors.ToolError) as refused:
                Service(url=url, key=KEY)
            self.assertNotIn("pass", str(refused.exception))

    def test_a_key_travels_only_over_https_or_to_the_loopback_host(self):
        for url in ("https://speech.example/v1", "https://10.0.0.5:8443/v1", "http://127.0.0.1:8000/v1", "http://localhost/v1", "http://LOCALHOST:9000/v1", "http://[::1]:8000/v1"):
            with self.subTest(url=url):
                self.assertTrue(Service(url=url, key=KEY).enabled())
        for url in ("http://svc-ai-speech/v1", "http://10.0.0.5:8000/v1", "http://127.0.0.2/v1", "http://localhost.example/v1", "http://[::2]/v1", "http://speech.example/v1"):
            with self.subTest(url=url):
                self.assertTrue(Service(url=url, key="").enabled())
                with self.assertRaises(errors.ToolError) as refused:
                    Service(url=url, key=KEY)
                self.assertEqual(str(refused.exception), "the speech service key travels only over https or to 127.0.0.1, localhost or ::1: set an https KVB_ORCHESTRATOR_SPEECH_URL or empty KVB_ORCHESTRATOR_SPEECH_KEY_FILE")
                self.assertNotIn(KEY, str(refused.exception))


class TestServiceKey(unittest.TestCase):
    def test_a_key_that_is_no_printable_ascii_token_is_refused_and_never_shown(self):
        for key in ("sk-SECRET\n# rotated 2026-11-13", "sk SECRET", "sk-\tSECRET", "sk-SECRET\r", "sk-SÉCRET", "sk-\x7fSECRET", "sk-\x00SECRET"):
            with self.subTest(key=key), self.assertRaises(errors.ToolError) as refused:
                Service(url="https://speech.example/v1", key=key)
            self.assertEqual(str(refused.exception), MALFORMED)
        service = Service(url="https://speech.example/v1", key=KEY)
        built = engines.Engines(piper=Path("p"), voices=Path("v"), operator_voice="", whisper=Path("w"), whisper_model=Path("m"), scratch=Path("s"), service=service)
        for shown in (repr(service), str(service), repr(built)):
            with self.subTest(shown=shown[:40]):
                self.assertNotIn(KEY, shown)

    def test_the_key_file_is_read_strictly_and_an_unreadable_one_stops_the_start(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        base = Path(folder.name)
        (base / "key").write_text(f"  {KEY}\n", encoding="utf-8")
        (base / "binary").write_bytes(b"\xffsk-SECRET")
        self.assertEqual((keys.key_from(Path("/dev/null"), "speech service"), keys.key_from(base / "key", "speech service")), ("", KEY))
        for path in (base, base / "missing", base / "binary"):
            with self.subTest(path=path), self.assertRaises(errors.ToolError) as refused:
                keys.key_from(path, "speech service")
            self.assertEqual(str(refused.exception), f"the speech service key file {path} is unreadable")
            self.assertIsNone(refused.exception.__cause__)

    def test_a_key_file_over_the_limit_stops_the_start_without_reading_on(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        base = Path(folder.name)
        (base / "full").write_text("k" * keys.KEY_LIMIT, encoding="utf-8")
        (base / "huge").write_text("k" * (keys.KEY_LIMIT + 1), encoding="utf-8")
        self.assertEqual(keys.key_from(base / "full", "speech service"), "k" * keys.KEY_LIMIT)
        for path in (base / "huge", Path("/dev/zero")):
            with self.subTest(path=path):
                with self.assertRaises(errors.ToolError) as refused:
                    keys.key_from(path, "speech service")
                self.assertEqual(str(refused.exception), f"the speech service key file {path} holds more than {keys.KEY_LIMIT} bytes")

    def test_every_failure_of_the_request_becomes_its_type_name_only(self):
        service = Service(url="http://127.0.0.1:9/v1", key=KEY)
        for error in (ValueError(f"Invalid header value b'Bearer {KEY}'"), RuntimeError(KEY), http.client.InvalidURL(KEY), OSError(KEY)):
            with self.subTest(error=type(error).__name__), mock.patch.object(http.client.HTTPConnection, "request", side_effect=error):
                with self.assertRaises(errors.EngineError) as failed:
                    service.speak(VOICE, LINE)
                self.assertEqual(str(failed.exception), f"the speech service failed: {type(error).__name__}")
                self.assertTrue(failed.exception.__suppress_context__)


class TestTransportDeadline(unittest.TestCase):
    def speak(self, url: str) -> tuple[str, float]:
        started = time.monotonic()
        with mock.patch.object(speechservice, "SERVICE_TIMEOUT", 0.5), self.assertRaises(errors.EngineError) as failed:
            Service(url=url, key="").speak(VOICE, LINE)
        return str(failed.exception), time.monotonic() - started

    def test_a_stalled_name_lookup_ends_at_the_deadline(self):
        with mock.patch.object(transport.socket, "getaddrinfo", side_effect=lambda *args, **kwargs: time.sleep(3)):
            message, took = self.speak("http://speech.example/v1")
        self.assertEqual(message, "the speech service took longer than 0.5 seconds")
        self.assertLess(took, 1.5)

    def test_a_stalled_connect_gets_only_the_time_left_across_every_address(self):
        timeouts: list[float] = []

        def stall(sock: socket.socket, address: tuple) -> None:
            timeouts.append(sock.gettimeout())
            time.sleep(sock.gettimeout())
            raise TimeoutError

        addresses = [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", 9))] * 3
        with mock.patch.object(transport.Call, "resolve", return_value=addresses), mock.patch.object(socket.socket, "connect", stall):
            message, took = self.speak("http://speech.example/v1")
        self.assertEqual(message, "the speech service took longer than 0.5 seconds")
        self.assertLess(took, 1.5)
        self.assertTrue(timeouts and sum(timeouts) <= 0.5, timeouts)

    def test_a_stalled_tls_handshake_ends_at_the_deadline(self):
        listener = socket.create_server(("127.0.0.1", 0))
        self.addCleanup(listener.close)
        message, took = self.speak(f"https://127.0.0.1:{listener.getsockname()[1]}/v1")
        self.assertEqual(message, "the speech service took longer than 0.5 seconds")
        self.assertLess(took, 1.5)

    def test_a_watchdog_that_cannot_start_fails_with_its_type_name(self):
        with mock.patch.object(transport.threading.Timer, "start", side_effect=RuntimeError(KEY)):
            message, _ = self.speak("http://127.0.0.1:9/v1")
        self.assertEqual(message, "the speech service failed: RuntimeError")


class TestWholeWav(unittest.TestCase):
    def test_only_a_wav_whose_sizes_match_the_bytes_received_counts(self):
        chunks = struct.pack("<4sI", b"LIST", 1) + b"x\x00" + SPOKEN[12:]
        odd = struct.pack("<4sI4s", b"RIFF", len(chunks) + 4, b"WAVE") + chunks
        self.assertEqual([engines.whole_wav(body) for body in (SPOKEN, odd)], [SPOKEN, odd])
        empty = wav_bytes(1, 2, 22050, b"")
        for body in (SPOKEN[:-100], OVERFLOW, SPOKEN + b"\x00", SPOKEN[:-1], b"", b"RIFF", empty, SPOKEN.replace(b"WAVE", b"AVI ", 1)):
            with self.subTest(size=len(body)):
                self.assertIsNone(engines.whole_wav(body))

    def test_a_streamed_wav_counts_only_if_its_data_chunk_is_last_and_runs_to_the_end(self):
        real = len(SPOKEN) - DATA - 8
        chunks = struct.pack("<4sI", b"LIST", 1) + b"x\x00" + SPOKEN[12:]
        odd = struct.pack("<4sI4s", b"RIFF", len(chunks) + 4, b"WAVE") + chunks
        for riff, data in ((STREAMING, STREAMING), (0, 0), (STREAMING, 0), (0, STREAMING), (STREAMING, real), (0, real)):
            with self.subTest(riff=riff, data=data):
                self.assertEqual(engines.whole_wav(streamed(riff, data)), SPOKEN)
        self.assertEqual(engines.whole_wav(streamed(STREAMING, STREAMING, odd)), odd)
        trailer = struct.pack("<4sI", b"LIST", 2) + b"xy"
        for name, body in (
            ("data not last", streamed(STREAMING, real) + trailer),
            ("truncated with a real size", streamed(STREAMING, real)[:-100]),
            ("real size short of the end", streamed(STREAMING, real - 2)),
            ("no audio", streamed(STREAMING, STREAMING)[: DATA + 8]),
            ("no data chunk", streamed(STREAMING, STREAMING)[:DATA]),
            ("real RIFF, placeholder data", streamed(len(SPOKEN) - 8, STREAMING)),
            ("real RIFF, zero data", streamed(len(SPOKEN) - 8, 0)),
            ("mismatched RIFF, placeholder data", streamed(len(SPOKEN), STREAMING)),
            ("placeholder RIFF, truncated fmt", streamed(STREAMING, STREAMING)[:30]),
        ):
            with self.subTest(name=name):
                self.assertIsNone(engines.whole_wav(body))


class TestServiceEngines(unittest.TestCase):
    def test_with_the_service_no_local_piper_or_whisper_is_needed_but_the_voices_are(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        base = Path(folder.name)
        built = write_engines(base)
        gone = {"piper": base / "missing-piper", "whisper": base / "missing-whisper", "whisper_model": base / "missing.bin"}
        remote = engines.Speech(dataclasses.replace(built, service=Service(url="http://127.0.0.1:9/v1", key=""), **gone), base / "remote")
        local = engines.Speech(dataclasses.replace(built, **gone), base / "local")
        self.assertEqual([remote.describe()[key] for key in ("tts", "stt", "tts_off", "stt_off")], [True, True, "", ""])
        self.assertEqual([local.describe()[key] for key in ("tts", "stt")], [False, False])
        voiceless = engines.Speech(dataclasses.replace(built, service=Service(url="http://127.0.0.1:9/v1", key=""), voices=base / "none"), base / "voiceless")
        self.assertEqual((voiceless.describe()["tts"], voiceless.describe()["stt"]), (False, True))


class TestSpeechServiceHttp(HubCase):
    def setUp(self):
        self.service = FakeService()
        self.addCleanup(self.service.stop)
        original = hub_case.write_engines

        def remote(base: Path) -> engines.Engines:
            return dataclasses.replace(original(base), service=Service(url=self.service.url, key=KEY))

        with mock.patch.object(hub_case, "write_engines", remote):
            super().setUp()
        self.hand_out(VOICE)

    def tts(self, text: str) -> tuple[int, dict, bytes]:
        return self.post_json("/api/tts", {"text": text, "voice": VOICE}, self.guard(self.host))

    def stt(self, clip: bytes) -> tuple[int, dict, bytes]:
        return self.call("POST", "/api/stt", clip, {**self.guard(self.host), "Content-Type": "audio/wav"})

    def local_calls(self) -> list[dict]:
        return log_rows(self.engines.scratch / "piper.jsonl") + log_rows(self.engines.scratch / "whisper.jsonl")

    def test_speech_output_renders_at_the_service_behind_the_cpu_gate_and_the_cache(self):
        self.host_cpu(10.0, 5)
        status, headers, body = self.tts(LINE)
        self.assertEqual((status, headers["content-type"], body), (200, "audio/wav", SPOKEN))
        [sent] = self.service.requests
        self.assertEqual((sent["method"], sent["path"], sent["headers"]["authorization"], sent["headers"]["content-type"]), ("POST", "/v1/audio/speech", f"Bearer {KEY}", "application/json"))
        self.assertEqual(json.loads(sent["body"]), {"model": speechservice.SPEECH_MODEL, "input": LINE, "voice": VOICE, "response_format": "wav"})
        self.assertEqual(self.tts(LINE)[::2], (200, SPOKEN))
        self.assertEqual(len(self.service.requests), 1)
        for cpu, age, reason in ((99.0, 5, "busy"), (None, 5, "unknown"), (10.0, 900, "unknown")):
            with self.subTest(cpu=cpu, age=age):
                self.host_cpu(cpu, age)
                status, _, body = self.tts(f"{LINE} again")
                self.assertEqual((status, json.loads(body)), (503, {"reason": reason}))
                self.assertEqual(self.tts(LINE)[::2], (200, SPOKEN))
        self.assertEqual(len(self.service.requests), 1)
        self.host_cpu(99.0, 5)
        self.assertEqual(self.tts(MAYDAY)[0], 200)
        self.assertEqual(json.loads(self.service.requests[-1]["body"])["input"], MAYDAY)
        self.assertEqual(self.local_calls(), [])

    def test_a_streamed_wav_with_placeholder_sizes_is_served_and_cached_with_the_real_sizes(self):
        self.host_cpu(10.0, 5)
        self.service.mode = "streamed"
        self.assertEqual(self.tts(LINE)[::2], (200, SPOKEN))
        self.assertEqual(self.tts(LINE)[::2], (200, SPOKEN))
        self.assertEqual(len(self.service.requests), 1)

    def test_speech_input_transcribes_at_the_service_within_the_hub_limits(self):
        status, headers, body = self.stt(CLIP)
        self.assertEqual((status, headers["content-type"], json.loads(body)), (200, "application/json", {"text": "hello from the service"}))
        [sent] = self.service.requests
        kind = sent["headers"]["content-type"]
        boundary = kind.removeprefix("multipart/form-data; boundary=")
        self.assertEqual((sent["path"], sent["headers"]["authorization"]), ("/v1/audio/transcriptions", f"Bearer {KEY}"))
        self.assertNotEqual(boundary, kind)
        parts = sent["body"].split(f"--{boundary}".encode())
        self.assertEqual(parts[-1], b"--\r\n")
        self.assertIn(f'name="model"\r\n\r\n{speechservice.HEARING_MODEL}\r\n'.encode(), parts[1])
        self.assertIn(b'name="file"; filename="recording.wav"\r\nContent-Type: audio/wav\r\n\r\n' + CLIP + b"\r\n", sent["body"])
        self.assertEqual(self.stt(b"not a wav")[0], 400)
        with mock.patch.object(engines, "HEARING_RATE", 1):
            self.assertEqual(self.stt(CLIP)[0], 503)
        self.assertEqual(len(self.service.requests), 1)
        self.assertEqual(self.local_calls(), [])

    def test_a_failing_service_answers_502_without_the_key_and_leaves_no_partial_file(self):
        self.host_cpu(10.0, 5)
        cases = (
            ("error", "tts", "the speech service answered HTTP 500"),
            ("redirect", "tts", "the speech service answered HTTP 302"),
            ("garbage", "tts", "the speech service answered no complete WAV"),
            ("truncated", "tts", "the speech service answered no complete WAV"),
            ("overflow", "tts", "the speech service answered no complete WAV"),
            ("streamed-short", "tts", "the speech service answered no complete WAV"),
            ("short", "tts", "the speech service answered a truncated reply"),
            ("big", "tts", f"the speech service answered more than {len(SPOKEN)} bytes"),
            ("slow", "tts", "the speech service took longer than 0.5 seconds"),
            ("error", "stt", "the speech service answered HTTP 500"),
            ("notext", "stt", "the speech service answered no transcript"),
            ("short", "stt", "the speech service answered a truncated reply"),
        )
        for number, (mode, route, message) in enumerate(cases):
            with self.subTest(mode=mode, route=route), mock.patch.object(speechservice, "SPOKEN_REPLY", len(SPOKEN)), mock.patch.object(speechservice, "SERVICE_TIMEOUT", 0.5):
                self.service.mode = mode
                status, _, body = self.tts(f"{LINE} {number}") if route == "tts" else self.stt(CLIP)
                self.assertEqual((status, body.decode()), (502, f"{message}\n"))
                self.assertNotIn(KEY, body.decode())
        self.assertNotIn("GET", [sent["method"] for sent in self.service.requests])
        self.assertEqual([path.name for path in (self.state / "tts").iterdir()], [])
        self.service.stop()
        self.service.mode = "ok"
        self.assertEqual(self.tts(f"{LINE} refused")[::2], (502, b"the speech service failed: ConnectionRefusedError\n"))
        self.assertEqual(self.local_calls(), [])

    def test_a_trickling_service_hits_the_wall_clock_deadline_and_frees_the_speech_lock(self):
        self.host_cpu(10.0, 5)
        late = b"the speech service took longer than 1 seconds\n"
        with mock.patch.object(speechservice, "SERVICE_TIMEOUT", 1.0):
            started = time.monotonic()
            outcome: list[tuple[int, bytes]] = []
            stuck = threading.Thread(target=lambda: outcome.append(self.tts(f"{LINE} trickle")[::2]))
            stuck.start()
            time.sleep(0.3)
            self.assertEqual(self.tts(MAYDAY)[::2], (200, SPOKEN))
            stuck.join(10)
            self.assertEqual(outcome, [(502, late)])
            self.assertLess(time.monotonic() - started, 3.0)
            self.service.mode = "trickle-head"
            started = time.monotonic()
            self.assertEqual(self.stt(CLIP)[::2], (502, late))
            self.assertLess(time.monotonic() - started, 3.0)
        self.assertEqual(sorted(path.name.startswith(engines.WORD_CACHE) for path in (self.state / "tts").iterdir()), [True])


if __name__ == "__main__":
    unittest.main()
