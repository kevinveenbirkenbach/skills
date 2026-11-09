from __future__ import annotations

import hashlib
import json
import secrets
import tempfile
import threading
import time
import unittest
from unittest import mock

from hub_case import HubCase
from hub_engines import log_rows, wav_bytes
from hub_support import HOST_STATE, key, signing
from kvb_orchestrator import engines, exchange, signed, skill_scripts, voicenotes


class TestHubComposer(HubCase):
    def clip(self, sample: bytes) -> bytes:
        return wav_bytes(1, 2, engines.STT_RATE, sample * engines.STT_RATE)

    def record(self, body: bytes, headers: dict[str, str]) -> tuple[int, dict, bytes]:
        return self.call("POST", "/api/voice", body, {"Content-Type": "audio/wav", **headers})

    def note(self, body: bytes) -> str:
        status, _, answer = self.record(body, self.guard(self.host))
        self.assertEqual(status, 202, answer)
        note = json.loads(answer)
        self.settle(lambda: self.heard(note["id"])["status"] != "pending")
        return note["id"]

    def heard(self, note_id: str) -> dict:
        status, _, body = self.get(f"/api/voice/{note_id}")
        self.assertEqual(status, 200, body)
        return json.loads(body)

    def submit(self, body: bytes) -> tuple[int, bytes]:
        status, _, answer = self.record(body, self.guard(self.host))
        if status == 202:
            note = json.loads(answer)["id"]
            self.settle(lambda: self.heard(note)["status"] != "pending")
        return status, answer

    def hear(self, body: bytes) -> tuple[int, bytes]:
        status, _, answer = self.call("POST", "/api/stt", body, {**self.guard(self.host), "Content-Type": "audio/wav"})
        return status, answer

    def check(self, message_id: str, text: str, to: str) -> dict:
        return self.tool("operator_message", {"id": message_id, "text": text, "to": to})

    def test_a_recording_is_transcribed_off_the_request_and_kept_for_replay(self):
        good = self.guard(self.host)
        clip = self.clip(b"\x01\x00")
        release = threading.Event()
        whisper = self.httpd.hub.speech.whisper

        def slow(body: bytes) -> dict:
            release.wait(10)
            return whisper(body)

        with mock.patch.object(self.httpd.hub.speech, "whisper", side_effect=slow):
            status, _, body = self.record(clip, good)
            self.assertEqual(status, 202, body)
            note = json.loads(body)
            self.assertEqual((note["status"], note["text"], note["seconds"]), ("pending", "", 1.0))
            self.assertEqual(self.heard(note["id"])["status"], "pending")
            release.set()
            self.settle(lambda: self.heard(note["id"])["status"] == "done")
        self.assertEqual(self.heard(note["id"])["text"], "hello from the mic second line")
        status, headers, body = self.get(f"/api/voice/{note['id']}.wav")
        self.assertEqual((status, headers["content-type"], headers["content-security-policy"], body), (200, "audio/wav", exchange.PLAIN_CSP, clip))
        self.assertEqual((self.state / "voice" / f"{note['id']}.wav").read_bytes(), clip)
        failed = self.note(wav_bytes(1, 2, engines.STT_RATE, b"FAIL" * 100))
        self.assertEqual(self.heard(failed)["status"], "failed")
        self.assertIn("exit code 4", self.heard(failed)["error"])
        self.assertEqual(self.get(f"/api/voice/{failed}.wav")[0], 200)
        for path in ("/api/voice/0123456789abcdef", "/api/voice/0123456789abcdef.wav", "/api/voice/../tts", "/api/voice/x.wav"):
            with self.subTest(path=path):
                self.assertEqual(self.get(path)[0], 404)
        self.assertEqual(self.get("/api/voice")[0], 405)
        self.assertEqual(len(log_rows(self.engines.scratch / "whisper.jsonl")), 2)
        self.assertEqual(self.scripts.calls, [])

    def test_a_recording_is_checked_for_guard_type_size_length_and_load(self):
        good = self.guard(self.host)
        clip = self.clip(b"\x01\x00")
        for headers in ({k: v for k, v in good.items() if k != "X-Kvb-Orchestrator"}, {k: v for k, v in good.items() if k != "Origin"}, {**good, "Origin": "http://evil.example"}):
            with self.subTest(headers=headers):
                self.assertEqual(self.record(clip, headers)[0], 403)
        self.assertEqual(self.call("POST", "/api/voice", clip, {**good, "Content-Type": "audio/webm"})[0], 415)
        self.assertEqual(self.record(b"RIFF", {**good, "Content-Length": str(engines.STT_LIMIT + 1)})[0], 413)
        for broken in (b"not a wav", wav_bytes(1, 2, 44100, b"\x00\x00" * 100), wav_bytes(1, 2, engines.STT_RATE, b"")):
            with self.subTest(broken=broken[:20]):
                self.assertEqual(self.record(broken, good)[0], 400)
        with mock.patch.object(engines, "STT_SECONDS", 1):
            self.assertEqual(self.record(wav_bytes(1, 2, engines.STT_RATE, b"\x00\x00" * (engines.STT_RATE + 1)), good)[0], 400)
        with mock.patch.object(self.httpd.hub.speech, "input_gap", return_value="the whisper.cpp model m is not a file"):
            self.assertEqual(self.record(clip, good)[:3:2], (503, b"speech input is off: the whisper.cpp model m is not a file\n"))
        release = threading.Event()
        self.addCleanup(release.set)
        with mock.patch.object(self.httpd.hub.speech, "whisper", side_effect=lambda body: release.wait(10) and {"text": ""}):
            for _ in range(voicenotes.HEARING_LIMIT):
                self.assertEqual(self.record(clip, good)[0], 202)
            self.assertEqual(self.record(clip, good)[0], 503)
            release.set()
        self.assertEqual(list((self.state / "voice").glob(".*")), [])

    def test_only_the_newest_recordings_are_kept(self):
        with mock.patch.object(voicenotes, "VOICE_KEEP", 2):
            first, second, third = (self.note(self.clip(bytes([n, 0]))) for n in (1, 2, 3))
        self.assertEqual(self.get(f"/api/voice/{first}.wav")[0], 404)
        self.assertEqual([self.get(f"/api/voice/{note}.wav")[0] for note in (second, third)], [200, 200])
        self.assertEqual(sorted(path.stem for path in (self.state / "voice").iterdir()), sorted([second, third]))

    def test_an_operator_message_needs_the_passkey_and_carries_its_recording(self):
        self.claim("s1", "Skills session")
        voice = self.note(self.clip(b"\x01\x00"))
        payload = {"to": "Skills", "text": " please rebase ", "upload": "", "class": "call", "voice": voice}
        status, _, body = self.post_json("/api/messages/sign", payload, self.guard(self.host))
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)["credentials"], [])
        unpinned = key(-7, "stranger").proof(json.loads(body)["payload"], self.origin)
        self.assertEqual(self.post_json("/api/messages", {**payload, "proof": unpinned}, self.guard(self.host))[:3:2], (400, b"not signed: no key is pinned\n"))
        signer = self.pin()
        proof = self.message_proof(payload, signer)
        for changed, reason in (
            ({"proof": None}, b"not signed: no signature\n"),
            ({"proof": key(-7, "stranger").proof(proof["payload"], self.origin)}, b"not signed: the signing key is not pinned\n"),
            ({"proof": signer.proof(proof["payload"], "http://127.0.0.1:1")}, None),
            ({"text": "please merge", "proof": proof}, b"not signed: the signature does not list this item\n"),
            ({"class": "post", "proof": proof}, b"not signed: the signature does not list this item\n"),
            ({"voice": "", "proof": proof}, b"not signed: the signature does not list this item\n"),
        ):
            with self.subTest(changed=list(changed)):
                status, _, answer = self.post_json("/api/messages", {**payload, **changed}, self.guard(self.host))
                self.assertEqual(status, 400, answer)
                if reason is not None:
                    self.assertEqual(answer, reason)
        self.assertEqual(self.scripts.calls, [])
        status, _, body = self.post_json("/api/messages", {**payload, "proof": proof}, self.guard(self.host))
        self.assertEqual(status, 201, body)
        sent = json.loads(body)
        recording = f"{HOST_STATE}/voice/{voice}.wav"
        self.assertEqual(self.scripts.calls, [(skill_scripts.RADIO, ["send", "call", "--to", "Skills session", "--session", "Operator", f"[kvb-orchestrator msg {sent['id']}] please rebase voice: {recording}"])])
        self.assertEqual(self.post_json("/api/messages", {**payload, "proof": proof}, self.guard(self.host))[:3:2], (400, b"not signed: this signature was already used for this item\n"))
        verified = self.check(sent["id"], "please rebase", "Skills session")["structuredContent"]
        self.assertEqual((verified["match"], verified["text"], verified["class"], verified["voice"]), (True, "please rebase", "call", recording))
        row = self.snapshot()["messages"][-1]
        self.assertEqual((row["id"], row["class"], row["voice"], row["signed"]), (sent["id"], "call", voice, True))
        self.assertEqual(len(self.scripts.calls), 1)

    def test_a_signed_message_to_all_names_everyone_and_keeps_its_class(self):
        signer = self.pin()
        voice = self.note(self.clip(b"\x01\x00"))
        status, _, body = self.tell_all({"text": "disk full", "class": "mayday", "voice": voice}, signer)
        self.assertEqual(status, 200, body)
        script, args = self.scripts.calls[-1]
        self.assertEqual((script, args[:4]), (skill_scripts.RADIO, ["send", "mayday", "--session", "Operator"]))
        self.assertTrue(args[-1].endswith(f"] disk full voice: {HOST_STATE}/voice/{voice}.wav"), args[-1])
        self.assertEqual(self.snapshot()["messages"][-1]["to"], "*")
        for payload in (
            {"to": "Skills", "text": "x", "upload": "", "class": "mayday", "voice": ""},
            {"to": "*", "text": "x", "upload": "0123456789abcdef", "class": "newsletter", "voice": ""},
            {"to": "*", "text": "x", "upload": "", "class": "receipt", "voice": ""},
            {"to": "*", "text": " ", "upload": "", "class": "broadcast", "voice": ""},
            {"to": "*", "text": "x", "upload": "", "class": "broadcast", "voice": "0123456789abcdef"},
            {"to": "*", "text": "x", "upload": "", "class": "broadcast", "voice": 7},
            {"to": "*", "text": "x", "upload": "", "class": "broadcast"},
        ):
            with self.subTest(payload=payload):
                self.assertEqual(self.post_json("/api/messages/sign", payload, self.guard(self.host))[0], 400)
        self.assertEqual(self.post_json("/api/messages/sign", {"to": "*", "text": "x", "upload": "", "class": "broadcast", "voice": ""}, self.client())[0], 403)
        self.assertEqual(self.get("/api/messages/sign")[0], 405)

    def test_operator_message_matches_only_the_signed_text_and_recipient(self):
        self.claim("s1", "Skills session")
        signer = self.pin()
        voice = self.note(self.clip(b"\x01\x00"))
        status, _, body = self.say({"to": "Skills", "text": "please\n rebase", "class": "call", "voice": voice}, signer)
        self.assertEqual(status, 201, body)
        sent = json.loads(body)["id"]
        row = self.scripts.calls[-1][1][-1].split("] ", 1)[1]
        for text, to in (("please rebase", "Skills"), ("please  rebase", "Skills session"), (row, "Skills")):
            with self.subTest(text=text, to=to):
                result = self.check(sent, text, to)
                self.assertFalse(result["isError"], result)
                found = result["structuredContent"]
                self.assertEqual((found["match"], found["text"], found["to"], found["class"]), (True, "please\n rebase", "Skills", "call"))
                self.assertEqual(found["voice"], f"{HOST_STATE}/voice/{voice}.wav")
        for text, to in (("please merge", "Skills"), ("please rebase", "Stage"), ("please rebase", "*"), ("please", "Skills")):
            with self.subTest(text=text, to=to):
                result = self.check(sent, text, to)
                self.assertTrue(result["isError"], result)
                self.assertNotIn("structuredContent", result)
        self.assertEqual(self.tell_all({"text": "main is green", "class": "newsletter"}, signer)[0], 200)
        everyone = next(message["id"] for message in self.snapshot()["messages"] if message["to"] == "*")
        self.assertTrue(self.check(everyone, "main is green", "*")["structuredContent"]["match"])
        self.assertTrue(self.check(everyone, "main is green", "Skills")["isError"])
        legacy = self.httpd.hub.messages.add({"to": "Skills", "address": "Skills session", "text": "deploy", "upload": None, "created_ts": time.time()})
        self.assertTrue(self.check(legacy["id"], "deploy", "Skills")["isError"])
        self.httpd.hub.messages.change(sent, {"text": "rm -rf"})
        self.assertTrue(self.check(sent, "rm -rf", "Skills")["isError"])
        self.assertTrue(self.tool("operator_message", {"id": everyone})["isError"])

    def test_a_post_or_a_call_never_goes_to_everyone(self):
        signer = self.pin()
        for cls in ("post", "call"):
            with self.subTest(cls=cls):
                payload = {"to": " * ", "text": "x", "upload": "", "class": cls, "voice": ""}
                self.assertEqual(self.post_json("/api/messages/sign", payload, self.guard(self.host))[:3:2], (400, b"a post or a call names one agent, never *\n"))
                item = signing.message_item("*", cls, "x", "", "", "")
                request = signing.approval_payload([signing.item_hash(item)], secrets.token_hex(16), int(time.time()) + 60)
                proof = signer.proof(request, self.origin)
                self.assertEqual(self.post_json("/api/messages", {**payload, "proof": proof}, self.guard(self.host))[0], 400)
        self.assertEqual(self.scripts.calls, [])

    def test_the_hub_transcribes_a_bounded_number_of_recordings_per_minute(self):
        answers = [self.submit(self.clip(b"\x01\x00")) for _ in range(12)]
        statuses = [status for status, _ in answers]
        self.assertIn(503, statuses)
        self.assertEqual(statuses, [202] * engines.HEARING_RATE + [503] * (12 - engines.HEARING_RATE))
        self.assertIn(f"at most {engines.HEARING_RATE} recordings per {engines.HEARING_WINDOW} s".encode(), answers[-1][1])
        self.assertEqual(self.hear(self.clip(b"\x01\x00"))[0], 503)
        self.assertEqual(len(log_rows(self.engines.scratch / "whisper.jsonl")), engines.HEARING_RATE)

    def test_the_hub_transcribes_at_most_its_hourly_audio_budget(self):
        full = wav_bytes(1, 2, engines.STT_RATE, b"\x01\x00" * engines.STT_RATE * engines.STT_SECONDS)
        statuses = [self.submit(full)[0] for _ in range(5)]
        status, answer = self.submit(self.clip(b"\x01\x00"))
        self.assertEqual((statuses, status), ([202] * 5, 503), answer)
        self.assertEqual(engines.HEARING_BUDGET, 5 * engines.STT_SECONDS)
        self.assertIn(f"{engines.HEARING_BUDGET} s of audio per hour".encode(), answer)
        self.assertEqual(self.hear(self.clip(b"\x01\x00"))[0], 503)

    def test_a_recording_a_stored_message_refers_to_is_never_trimmed(self):
        self.claim("s1", "Skills session")
        signer = self.pin()
        with mock.patch.object(voicenotes, "VOICE_KEEP", 1):
            kept = self.note(self.clip(b"\x01\x00"))
            self.assertEqual(self.say({"to": "Skills", "text": "hear this", "class": "post", "voice": kept}, signer)[0], 201)
            newer = [self.note(self.clip(bytes([n, 0]))) for n in (2, 3)]
            self.assertEqual(self.get(f"/api/voice/{kept}.wav")[0], 200)
            self.assertEqual([self.get(f"/api/voice/{note}.wav")[0] for note in newer], [404, 200])
            sending = self.note(self.clip(b"\x04\x00"))
            with self.httpd.hub.voice_notes.held(sending):
                self.note(self.clip(b"\x05\x00"))
                self.assertEqual(self.get(f"/api/voice/{sending}.wav")[0], 200)
        self.assertEqual(self.get(f"/api/voice/{kept}.wav")[0], 200)

    def test_the_signature_binds_the_bytes_of_the_recording(self):
        self.claim("s1", "Skills session")
        signer = self.pin()
        voice = self.note(self.clip(b"\x01\x00"))
        wav = self.state / "voice" / f"{voice}.wav"
        original = wav.read_bytes()
        payload = {"to": "Skills", "text": "hear this", "upload": "", "class": "call", "voice": voice}
        proof = self.message_proof(payload, signer)
        wav.write_bytes(self.clip(b"\x02\x00"))
        self.assertEqual(self.post_json("/api/messages", {**payload, "proof": proof}, self.guard(self.host))[:3:2], (400, b"not signed: the signature does not list this item\n"))
        self.assertEqual(self.scripts.calls, [])
        wav.write_bytes(original)
        status, _, body = self.post_json("/api/messages", {**payload, "proof": proof}, self.guard(self.host))
        self.assertEqual(status, 201, body)
        found = self.check(json.loads(body)["id"], "hear this", "Skills")["structuredContent"]
        self.assertEqual(found["voice_sha256"], hashlib.sha256(original).hexdigest())

    def test_a_signature_check_without_a_temporary_directory_answers_400(self):
        self.claim("s1", "Skills session")
        signer = self.pin()
        payload = {"to": "Skills", "text": "x", "upload": "", "class": "post", "voice": ""}
        proof = self.message_proof(payload, signer)
        missing = self.state / "no-such-tmp"
        with mock.patch.object(signed.passkey, "serialization", None), mock.patch.object(tempfile, "tempdir", str(missing)):
            status, _, body = self.post_json("/api/messages", {**payload, "proof": proof}, self.guard(self.host))
        self.assertEqual(status, 400, body)
        self.assertTrue(body.startswith(b"not signed: "), body)
        self.assertEqual(self.scripts.calls, [])


if __name__ == "__main__":
    unittest.main()
