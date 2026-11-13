from __future__ import annotations

import dataclasses
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from hub_case import HubCase
from hub_engines import OPERATOR_VOICE, VOICES, log_rows, write_engines
from hub_support import STREAMS, key
from kvb_orchestrator import engines, errors, phrasing, settings, speechgate

LINE = "all stations, this is Docs, disk at ninety percent, out"
VOICE = "en_US-test-high:2"
WORDS = {
    "mayday": "MAYDAY MAYDAY MAYDAY",
    "pan-pan": "PAN-PAN PAN-PAN PAN-PAN",
    "security": "say-cure-ee-tay say-cure-ee-tay say-cure-ee-tay",
}


SCRATCH = tempfile.TemporaryDirectory()


def scratch() -> Path:
    return Path(tempfile.mkdtemp(dir=SCRATCH.name))


def gate_over(rows: list[dict], threshold: int, now: float) -> speechgate.CpuGate:
    path = scratch() / "samples.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return speechgate.CpuGate(samples=path, threshold=lambda: threshold, clock=lambda: now)


class TestLatestCpu(unittest.TestCase):
    def test_the_newest_fresh_sample_counts_and_an_old_or_empty_one_does_not(self):
        now = 1_800_000_000.0
        cases = (
            ([{"t": now - 60, "cpu": 90.0}, {"t": now - 5, "cpu": 12.5}], 12.5),
            ([{"t": now - 120, "cpu": 33.0}], 33.0),
            ([{"t": now - 120.5, "cpu": 33.0}], None),
            ([{"t": now - 30, "cpu": 40.0}, {"t": now - 10, "cpu": None}], None),
            ([{"t": now - 30, "cpu": 40.0}, {"t": now - 10}], None),
            ([{"t": now - 10, "cpu": True}], None),
            ([{"t": now - 10, "cpu": "40"}], None),
            ([{"t": now - 10, "cpu": 140.0}], None),
            ([{"t": now + 600, "cpu": 10.0}], None),
            ([{"t": now - 20, "cpu": 70.0}, {"cpu": 1.0}], 70.0),
            ([], None),
        )
        for rows, expected in cases:
            with self.subTest(rows=rows):
                self.assertEqual(gate_over(rows, 50, now).state()["cpu"], expected)

    def test_a_broken_last_line_is_skipped_and_only_the_tail_is_read(self):
        now = 1_800_000_000.0
        folder = scratch()
        path = folder / "samples.jsonl"
        old = "".join(json.dumps({"t": now - 86400 + index, "cpu": 99.0, "pad": "x" * 200}) + "\n" for index in range(2000))
        path.write_text(old + json.dumps({"t": now - 3, "cpu": 21.0}) + "\n{broken\n", encoding="utf-8")
        self.assertGreater(path.stat().st_size, speechgate.TAIL)
        self.assertEqual(speechgate.latest_cpu(path, now), 21.0)
        self.assertEqual(len(speechgate.tail_lines(path, speechgate.TAIL)), len(path.read_bytes()[-speechgate.TAIL:].splitlines()) - 1)
        link = folder / "link.jsonl"
        os.symlink(path, link)
        self.assertEqual((speechgate.latest_cpu(link, now), speechgate.latest_cpu(folder / "missing.jsonl", now)), (None, None))


class TestCpuGate(unittest.TestCase):
    def test_an_uncached_line_waits_at_or_above_the_threshold_and_without_a_fresh_sample(self):
        now = 1_800_000_000.0
        for cpu, threshold, reason in ((50.0, 50, "busy"), (91.0, 90, "busy"), (49.9, 50, None), (29.0, 30, None), (None, 50, "unknown")):
            with self.subTest(cpu=cpu, threshold=threshold):
                gate = gate_over([{"t": now - 1, "cpu": cpu}], threshold, now)
                self.assertEqual(gate.state(), {"threshold": threshold, "cpu": cpu, "open": reason is None})
                if reason is None:
                    self.assertIsNone(gate.admit(LINE))
                    continue
                with self.assertRaises(errors.Held) as held:
                    gate.admit(LINE)
                self.assertEqual(held.exception.reason, reason)
        stale = gate_over([{"t": now - 121, "cpu": 5.0}], 50, now)
        with self.assertRaises(errors.Held) as held:
            stale.admit(LINE)
        self.assertEqual((held.exception.reason, stale.state()["open"]), ("unknown", False))

    def test_a_procedure_word_line_passes_under_load_and_without_a_sample(self):
        now = 1_800_000_000.0
        for rows in ([{"t": now - 1, "cpu": 99.0}], []):
            gate = gate_over(rows, 50, now)
            for line in WORDS.values():
                with self.subTest(rows=rows, line=line):
                    self.assertIsNone(gate.admit(line))
            with self.assertRaises(errors.Held):
                gate.admit(f"{WORDS['mayday']}, this is Docs Docs Docs, over")


class TestProcedureWords(unittest.TestCase):
    def test_alarm_rows_split_into_the_procedure_word_line_and_the_rest(self):
        self.assertEqual({cls: phrasing.procedure(cls) for cls in WORDS}, WORDS)
        self.assertEqual(phrasing.PROCEDURE_LINES, frozenset(WORDS.values()))
        for cls in ("post", "call", "newsletter", "broadcast", "receipt"):
            with self.subTest(cls=cls):
                self.assertEqual(phrasing.procedure(cls), "")
                word, rest = phrasing.phrase_parts(cls, "Docs", ["Skills"], "ready")
                self.assertEqual((word, phrasing.phrase(cls, "Docs", ["Skills"], "ready")), ("", rest))
        cases = (
            ("mayday", "MAYDAY disk full", "this is Docs Docs Docs, disk full, over"),
            ("pan-pan", "PAN-PAN slow", "all stations, this is Docs, slow, over"),
            ("security", "SECURITE rotate", "all stations, this is Docs, rotate, over"),
        )
        for cls, text, rest in cases:
            with self.subTest(cls=cls):
                self.assertEqual(phrasing.phrase_parts(cls, "Docs", [], text), (WORDS[cls], rest))
                self.assertEqual(phrasing.phrase(cls, "Docs", [], text), f"{WORDS[cls]}, {rest}")
                self.assertTrue(phrasing.SPOKEN_LINE.fullmatch(WORDS[cls]))


class TestThresholdSetting(unittest.TestCase):
    def test_only_thirty_to_ninety_in_steps_of_ten_and_fifty_by_default(self):
        self.assertEqual(settings.SETTINGS["speech"], {"threshold": 50})
        for value in (30, 40, 50, 60, 70, 80, 90):
            with self.subTest(value=value):
                self.assertEqual(settings.speech_setting({"threshold": value}), {"threshold": value})
        for value in (20, 25, 35, 95, 100, 0, 50.0, True, "50", None, [50]):
            with self.subTest(value=value), self.assertRaises(errors.ToolError):
                settings.speech_setting({"threshold": value})
        for raw in ({}, {"threshold": 50, "on": True}, "50"):
            with self.subTest(raw=raw), self.assertRaises(errors.ToolError):
                settings.speech_setting(raw)

    def test_settings_saved_before_the_radio_set_keep_every_hub_value(self):
        legacy = {
            **{key: value for key, value in settings.SETTINGS.items() if key != "speech"}, "latitude": 52.5, "streams": [{**STREAMS[0], "via": []}],
            "sounds": {"mayday": {"on": True, "volume": 0.9}}, "squelch": 0.4, "speech": {"on": True, "classes": ["mayday"], "muted": ["s1"]},
        }
        with self.assertRaises(errors.ToolError):
            settings.valid_settings(legacy)
        folder = scratch()
        (folder / "settings.json").write_text(json.dumps(legacy), encoding="utf-8")
        loaded = settings.Settings(folder / "settings.json").get()
        self.assertEqual((loaded["latitude"], loaded["streams"][0]["url"], loaded["speech"]), (52.5, STREAMS[0]["url"], {"threshold": 50}))
        self.assertNotIn("sounds", loaded)
        self.assertNotIn("squelch", loaded)
        kept = {**legacy, "speech": {"on": False, "classes": ["mayday"], "muted": [], "threshold": 70}}
        (folder / "settings.json").write_text(json.dumps(kept), encoding="utf-8")
        self.assertEqual(settings.Settings(folder / "settings.json").get()["speech"], {"threshold": 70})


class TestHandedVoices(unittest.TestCase):
    def test_procedure_lines_render_under_load_only_for_voices_the_hub_hands_out_and_outlive_the_trim(self):
        base = scratch()
        built = write_engines(base)
        (built.voices / "many.onnx").write_bytes(b"onnx")
        (built.voices / "many.onnx.json").write_text(json.dumps({"num_speakers": 904}), encoding="utf-8")
        speech = engines.Speech(dataclasses.replace(built, operator_voice="many:0"), base / "tts")
        now = 1_800_000_000.0

        def ask(voice: str, line: str, cpu: float) -> int:
            try:
                speech.synthesize(json.dumps({"text": line, "voice": voice}).encode(), gate_over([{"t": now, "cpu": cpu}], 50, now).admit)
            except errors.ToolError:
                return 400
            except errors.Held:
                return 503
            return 200

        def renders() -> int:
            return len(log_rows(built.scratch / "piper.jsonl"))

        allowed = {speech.voice_of(key) for key in ("s1", "s2")} | {"many:0"}
        strangers = [voice for voice in (f"many:{number}" for number in range(1, 251)) if voice not in allowed]
        for _ in range(2):
            self.assertEqual({ask(voice, WORDS["mayday"], 99.0) for voice in strangers}, {400})
            self.assertEqual(sorted(ask(voice, WORDS["mayday"], 99.0) for voice in allowed), [200] * len(allowed))
            self.assertEqual(renders(), len(allowed))
        self.assertGreaterEqual(len(strangers), 247)
        self.assertEqual(ask("many:0", LINE, 99.0), 503)
        with mock.patch.object(engines, "TTS_KEEP", 1):
            for number in range(3):
                self.assertEqual(ask("many:0", f"{LINE} {number}", 10.0), 200)
        kept = sorted(path.name.startswith(engines.WORD_CACHE) for path in (base / "tts").glob("*.wav"))
        self.assertEqual(kept, [False] + [True] * len(allowed))


class TestSpeechGateHttp(HubCase):
    def setUp(self):
        super().setUp()
        self.hand_out(VOICE)

    def tts(self, text: str) -> tuple[int, dict, bytes]:
        return self.post_json("/api/tts", {"text": text, "voice": VOICE}, self.guard(self.host))

    def piper_calls(self) -> list[dict]:
        return log_rows(self.engines.scratch / "piper.jsonl")

    def test_an_uncached_line_answers_busy_or_unknown_and_piper_records_no_call(self):
        for cpu, age, reason in ((50.0, 5, "busy"), (97.5, 0, "busy"), (None, 5, "unknown"), (10.0, 125, "unknown")):
            with self.subTest(cpu=cpu, age=age):
                self.host_cpu(cpu, age)
                status, headers, body = self.tts(LINE)
                self.assertEqual((status, headers["content-type"], json.loads(body)), (503, "application/json", {"reason": reason}))
        (self.kept / "resources" / "samples.jsonl").unlink()
        self.assertEqual(json.loads(self.tts(LINE)[2]), {"reason": "unknown"})
        self.assertEqual(self.piper_calls(), [])
        self.host_cpu(49.0, 5)
        status, headers, _ = self.tts(LINE)
        self.assertEqual((status, headers["content-type"]), (200, "audio/wav"))
        self.assertEqual([row["text"] for row in self.piper_calls()], [f"{LINE}\n"])

    def test_a_cached_line_answers_whatever_the_cpu(self):
        self.host_cpu(12.0, 5)
        first = self.tts(LINE)
        self.assertEqual(first[0], 200)
        for cpu, age in ((99.0, 5), (None, 5), (10.0, 900)):
            with self.subTest(cpu=cpu, age=age):
                self.host_cpu(cpu, age)
                self.assertEqual(self.tts(LINE)[::2], (200, first[2]))
        self.assertEqual(len(self.piper_calls()), 1)
        self.assertEqual(self.tts(f"{LINE} again")[0], 503)

    def test_a_procedure_word_line_renders_under_load_once_and_then_hits_the_cache(self):
        self.host_cpu(99.0, 5)
        for line in WORDS.values():
            with self.subTest(line=line):
                self.assertEqual(self.tts(line)[0], 200)
                self.assertEqual(self.tts(line)[0], 200)
        self.assertEqual([row["text"] for row in self.piper_calls()], [f"{line}\n" for line in WORDS.values()])
        for voice, status in ((OPERATOR_VOICE, 200), (OPERATOR_VOICE, 200), *((voice, 400) for voice in VOICES if voice not in (VOICE, OPERATOR_VOICE))):
            with self.subTest(voice=voice):
                self.assertEqual(self.post_json("/api/tts", {"text": WORDS["mayday"], "voice": voice}, self.guard(self.host))[0], status)
        self.assertEqual(len(self.piper_calls()), len(WORDS) + 1)

    def test_the_state_carries_the_gate_and_the_rows_their_procedure_word(self):
        self.write_council({"news.jsonl": self.jsonl([
            {"ts": time.time() - 30, "from": "Docs", "to": [], "text": "MAYDAY disk full", "class": "mayday", "v": 2},
            {"ts": time.time() - 20, "from": "Docs", "to": ["Skills"], "text": "ready", "class": "call", "v": 2},
        ])})
        self.assertEqual(self.snapshot()["speech"]["gate"], {"threshold": 50, "cpu": None, "open": False})
        self.host_cpu(42.0, 5)
        self.assertEqual(self.snapshot()["speech"]["gate"], {"threshold": 50, "cpu": 42.0, "open": True})
        self.host_cpu(50.0, 5)
        state = self.snapshot()
        self.assertEqual(state["speech"]["gate"], {"threshold": 50, "cpu": 50.0, "open": False})
        rows = [(row["word"], row["rest"], row["speech"]) for row in state["radio"]]
        self.assertEqual(rows, [
            (WORDS["mayday"], "this is Docs Docs Docs, disk full, over", f"{WORDS['mayday']}, this is Docs Docs Docs, disk full, over"),
            ("", "Skills, Skills, this is Docs, ready, over", "Skills, Skills, this is Docs, ready, over"),
        ])

    def test_the_threshold_changes_only_with_a_valid_passkey_signature(self):
        good = self.guard(self.host)
        current = self.snapshot()["settings"]
        raised = {**current, "speech": {"threshold": 70}}
        self.assertIsNone(json.loads(self.post_json("/api/settings/sign", current, good)[2])["payload"])
        self.assertEqual(self.post_json("/api/settings", {**raised, "proof": None}, good)[:3:2], (400, b"not signed: no signature\n"))
        signer = self.pin()
        status, _, body = self.post_json("/api/settings/sign", raised, good)
        self.assertEqual(status, 200, body)
        request = json.loads(body)["payload"]
        self.assertEqual(len(request["items"]), 1)
        stranger = self.post_json("/api/settings", {**raised, "proof": key(-7, "stranger").proof(request, self.origin)}, good)
        self.assertEqual(stranger[:3:2], (400, b"not signed: the signing key is not pinned\n"))
        self.assertEqual(self.snapshot()["speech"]["gate"]["threshold"], 50)
        lowered = {**current, "speech": {"threshold": 30}}
        self.assertEqual(self.post_json("/api/settings", {**lowered, "proof": signer.proof(request, self.origin)}, good)[:3:2], (400, b"not signed: the signature does not list this item\n"))
        status, _, body = self.post_json("/api/settings", {**raised, "proof": signer.proof(request, self.origin)}, good)
        self.assertEqual((status, json.loads(body)["settings"]["speech"]), (200, {"threshold": 70}), body)
        self.assertEqual(self.snapshot()["speech"]["gate"]["threshold"], 70)
        self.assertEqual(settings.Settings(self.state / "settings.json").get()["speech"], {"threshold": 70})
        for wrong in (35, 100, 20, "70", 70.0):
            with self.subTest(wrong=wrong):
                self.assertEqual(self.post_json("/api/settings/sign", {**current, "speech": {"threshold": wrong}}, good)[0], 400)
        self.host_cpu(60.0, 5)
        self.assertEqual(self.tts(LINE)[0], 200)


if __name__ == "__main__":
    unittest.main()
