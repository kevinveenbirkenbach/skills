from __future__ import annotations

import json
import os
import shutil
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

import hub_e2e_kit as base
from hub_case import HubCase
from hub_engines import log_rows
from hub_support import iso
from kvb_orchestrator import engines, errors, phrasing, speechgate
from radio_set_kit import (
    BURST,
    BURST_DONE,
    CUES,
    FACE,
    FIXTURE,
    LIGHT,
    LOG,
    LOG_KEPT,
    MORSE,
    MORSE_SPY,
    MORSE_STOP,
    OUT,
    SOUND,
    SOUND_KEPT,
    SPY,
    THRESHOLD,
    THRESHOLDS,
    WORD,
    WPMS,
    probe,
)


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestRadioSet(HubCase):
    drive = base.OrchestratorE2ECase.drive
    authenticator = base.OrchestratorE2ECase.authenticator
    beside = base.OrchestratorE2ECase.beside

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        now = time.time()
        self.claim("s1", "Skills session")
        self.write_council({
            "work/s2/claim.json": {"office": "work/s2", "session": "s2", "runtime": "claude", "name": "Stage", "since": iso(now - 7200), "beat": now - 60, "work": "x"},
            "news.jsonl": self.jsonl([{"ts": now - row["ago"], "v": 2, **{key: value for key, value in row.items() if key != "ago"}} for row in FIXTURE]),
        })
        hub = self.httpd.hub
        for row in FIXTURE:
            if row["from"] == "Operator":
                hub.messages.add({"to": row["to"][0] if row["to"] else "*", "text": row["text"], "upload": None, "class": row["class"], "voice": None, "created_ts": now - row["ago"]})
        hub.settings.put({**hub.settings.get(), "theme": "light"}, hub.settings.get())
        self.cpu = 10.0
        self.host_cpu(self.cpu, 0)
        self.beside(lambda: self.host_cpu(self.cpu, 0))
        self.sent = 0
        self.holding = False
        self.cues()
        self.base = f"http://localhost:{self.port}/"

    def load(self, cpu: float) -> None:
        self.cpu = cpu
        self.host_cpu(cpu, 0)

    def cues(self) -> None:
        hub = self.httpd.hub
        heard, admit = hub.voice_notes.get, speechgate.CpuGate.admit
        actions = {
            CUES["low"]: lambda: self.load(10.0),
            CUES["high"]: lambda: self.load(95.0),
            CUES["hold"]: lambda: setattr(self, "holding", True),
            CUES["free"]: lambda: setattr(self, "holding", False),
            CUES["alarm"]: lambda: self.radio("security", [], "Disk at ninety percent"),
            CUES["call"]: lambda: self.radio("call", ["Operator"], "Gate is green"),
            CUES["dark"]: lambda: hub.settings.put({**hub.settings.get(), "theme": "dark"}, hub.settings.get()),
            CUES["light"]: lambda: hub.settings.put({**hub.settings.get(), "theme": "light"}, hub.settings.get()),
        }

        def get(note_id: str) -> dict:
            if note_id not in actions:
                return heard(note_id)
            actions[note_id]()
            return {"id": note_id, "status": "done", "text": "", "error": "", "seconds": None, "created_ts": None}

        def gate(gate_self: speechgate.CpuGate, line: str) -> None:
            if self.holding and line not in phrasing.PROCEDURE_LINES:
                raise errors.Held("busy")
            admit(gate_self, line)

        for patch in (mock.patch.object(hub.voice_notes, "get", get), mock.patch.object(speechgate.CpuGate, "admit", gate)):
            patch.start()
            self.addCleanup(patch.stop)

    def radio(self, cls: str, to: list[str], text: str) -> None:
        self.sent += 1
        row = {"ts": time.time(), "from": "Stage", "to": to, "text": f"{text} {self.sent}", "class": cls, "v": 2}
        with (self.council / "news.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(self.jsonl([row]))

    def steps(self, browser: str, signed: bool) -> list[dict]:
        steps = []
        for width, height in base.WIDTHS:
            shot = str(OUT / f"{browser}-{width}-radio")
            url = f"{self.base}?{width}#stream"
            value = str(THRESHOLDS[width])
            steps += [
                {"width": width, "height": height, "url": url, "wait": 1200, "probe": probe(FACE), "shot": f"{shot}-faceplate.png", "gesture": True},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(LOG), "shot": f"{shot}-log-filtered.png"},
                {"width": width, "height": height, "url": f"{url}-kept", "wait": 1200, "probe": probe(LOG_KEPT), "shot": f"{shot}-log.png"},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(SOUND), "shot": f"{shot}-silence.png", "gesture": True},
                {"width": width, "height": height, "url": f"{url}-mode", "wait": 1200, "probe": probe(SOUND_KEPT), "shot": None, "gesture": True},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(BURST), "shot": f"{shot}-burst.png", "gesture": True},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(BURST_DONE), "shot": None},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(THRESHOLD).replace("@VALUE@", value), "shot": f"{shot}-dark.png", "gesture": True},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(LIGHT), "shot": None},
            ]
        return steps

    def check(self, data: dict, browser: str, signed: bool) -> None:
        results = iter(data["results"])
        for index, (width, _) in enumerate(base.WIDTHS):
            face, log, kept, sound, mode, burst, done, threshold, light = (next(results) for _ in range(9))
            with self.subTest(browser=browser, width=width, part="faceplate"):
                self.assertNotIn("error", face, face)
                self.assertEqual(face["display"]["mode"], "Auto")
                self.assertEqual((face["display"]["cpu"], face["display"]["lamp"]), ("CPU 10 %", ["RX", "false"]), face)
                self.assertTrue(face["display"]["cls"], face)
                self.assertEqual([mode_[:2] for mode_ in face["modes"]], [["Auto", "true"], ["Quiet", "false"], ["Silence", "false"], ["Morse", "false"]])
                self.assertTrue(all(mode_[2] and mode_[3] for mode_ in face["modes"]), face["modes"])
                self.assertEqual([knob[0] for knob in face["knobs"]], ["MAYDAY / PAN-PAN", "Reviews, asks, decisions", "Post and calls to you", "All radio", "Squelch", "Threshold"])
                shown = "50" if index == 0 or not signed else str(THRESHOLDS[base.WIDTHS[index - 1][0]])
                self.assertEqual(face["knobs"][-1][1:], ["0", "100", "10", shown])
                self.assertEqual(len(face["toneToggles"]), 4)
                self.assertEqual(face["testButtons"], [*(f"Test {knob[0]}" for knob in face["knobs"][:-1]), None])
                self.assertEqual(face["squelch"], {"lit": True, "filters": ["bandpass"], "tts": []}, face)
                self.assertEqual([label["text"] for label in face["labels"]], [*(knob[0] for knob in face["knobs"][:-1]), f"speak while CPU < {shown} %"])
                for label in face["labels"]:
                    self.assertEqual((label["title"], label["row"]), (label["text"], True), label)
                    self.assertTrue(label["whole"] or width == 390, label)
                self.assertEqual(face["groups"]["Classes"][4], ["MAYDAY", "true", True])
                self.assertEqual([entry[1] for entry in face["groups"]["Classes"]], ["false", "false", "false", "false", "true", "true", "true"])
                self.assertIn(["Stage", "true", False], face["groups"]["Agents"])
                self.assertEqual(face["stationsHead"], "Internet radio")
                self.assertEqual(face["ptt"][0], "PTT")
                self.assertEqual([section for section in face["sections"] if section in ("Internet radio", "Tones", "Read radio aloud", "Radio")], [])
                self.assertEqual(face["stations"], ["Stations", ["Internet radio"]])
                self.assertEqual((face["fits"], face["unlabelled"]), ({"page": True, "panel": True}, 0))
            with self.subTest(browser=browser, width=width, part="log"):
                self.assertNotIn("error", log, log)
                every = log["every"]
                self.assertEqual(log["counts"], {"sent": len(log["sent"]), "received": len(log["received"]), "all": len(every)})
                self.assertEqual([row["ts"] for row in every], sorted((row["ts"] for row in every), reverse=True))
                self.assertTrue(all(row["dir"] == "sent" and row["route"].startswith("Operator →") for row in log["sent"]), log["sent"])
                self.assertTrue(all(row["route"].endswith("→ all") or row["route"].endswith("→ Operator") or row["cls"] in ("pan-pan", "security", "mayday") for row in log["received"]), log["received"])
                self.assertTrue(all(row["cls"] == "post" for row in log["posts"]))
                self.assertEqual([row["line"] for row in log["fromStage"]], ["rebase done"])
                self.assertEqual([row["line"] for row in log["narrowed"]], ["rebase done"])
                self.assertEqual(log["none"][0], 0)
                self.assertEqual(log["clearedChips"], [{"class": "", "from": "", "to": "", "agent": ""}, "", len(every)])
                self.assertEqual(log["opened"][0], True)
                self.assertTrue(log["opened"][1], log)
                self.assertEqual(log["fits"], {"page": True, "panel": True})
                if index == 0:
                    self.assertEqual(log["counts"], {"sent": 2, "received": 3, "all": 5})
                    self.assertEqual([row["line"] for row in log["received"]], ["deploy now", "docs are green", "gate red on main"])
                    self.assertEqual([row["line"] for row in log["sent"]], ["deploy now", "rebase please"])
            with self.subTest(browser=browser, width=width, part="log kept"):
                self.assertEqual((kept["tab"], kept["chips"]["agent"], kept["q"]), ("received", "Stage", "gate"), kept)
                self.assertEqual([row["line"] for row in kept["rows"]], [row["line"] for row in log["kept"]])
                self.assertIn("gate red on main", [row["line"] for row in kept["rows"]])
                self.assertEqual(kept["fits"], {"page": True, "panel": True})
                if width == 390:
                    self.assertGreaterEqual(kept["total"], 10, kept)
                    self.assertGreaterEqual(kept["shown"], 10, kept)
            with self.subTest(browser=browser, width=width, part="sound"):
                self.assertNotIn("error", sound, sound)
                self.assertTrue(sound["low"], sound)
                auto, held = sound["auto"], sound["held"]
                self.assertEqual([entry[1] for entry in auto["tts"]], [200, 200], auto)
                self.assertEqual(auto["tts"][0][0], WORD)
                self.assertTrue(auto["tts"][1][0].startswith("all stations, this is Stage, Disk at ninety percent"), auto)
                self.assertEqual((auto["filters"], auto["requests"]), ([], []), auto)
                self.assertEqual(len(auto["starts"]), 2, auto)
                self.assertEqual([entry[1] for entry in held["tts"]], [200, 503], held)
                self.assertEqual(held["tts"][0][0], WORD)
                self.assertEqual([kind for kind, _ in held["filters"]], ["bandpass"], held)
                self.assertEqual(held["starts"][-1], {"seconds": 0.6, "channels": 1}, held)
                self.assertEqual(sound["retries"], 0, "a held row is not requested again")
                quiet, silence = sound["quiet"], sound["silence"]
                self.assertEqual([text for text, _ in quiet["tts"]], [WORD], quiet)
                self.assertEqual([kind for kind, _ in quiet["filters"]], ["bandpass"], quiet)
                self.assertGreater(quiet["oscillators"], 0, quiet)
                self.assertEqual([text for text, _ in silence["tts"]], [WORD], silence)
                self.assertEqual((silence["filters"], silence["oscillators"], len(silence["starts"])), ([], 0, 1), silence)
                self.assertEqual((sound["pressed"], sound["mode"]), (["silence"], "Silence"))
            with self.subTest(browser=browser, width=width, part="mode kept"):
                self.assertEqual(mode, {"kept": [["silence"], "Silence"], "pressed": ["auto"]})
            with self.subTest(browser=browser, width=width, part="burst"):
                self.assertNotIn("error", burst, burst)
                self.assertEqual((burst["high"], burst["lit"], burst["open"]), (True, True, "false"), burst)
                self.assertEqual(burst["lamp"], ["RX", "RX: sound plays"])
                heard = burst["heard"]
                self.assertEqual(heard["tts"], [[WORD, 200]], heard)
                self.assertEqual([kind for kind, _ in heard["filters"]], ["bandpass"])
                self.assertTrue(300 <= heard["filters"][0][1] <= 3400, heard)
                self.assertIn({"seconds": 0.6, "channels": 1}, heard["starts"])
                self.assertIn(0.3, heard["levels"], heard)
                self.assertEqual(heard["requests"], [], heard)
                self.assertEqual((done["tts"][-1], done["low"]), ([WORD, 200], True), done)
            with self.subTest(browser=browser, width=width, part="threshold and dark"):
                self.assertNotIn("error", threshold, threshold)
                value = str(THRESHOLDS[width])
                if signed:
                    self.assertEqual(threshold["after"], [value, threshold["before"][1] + 1], threshold)
                    self.assertEqual(threshold["shown"], f"{value} %")
                    self.assertIn(f"speak while CPU < {value} %", threshold["title"])
                else:
                    self.assertEqual(threshold["after"], [threshold["before"][0], threshold["before"][1]], threshold)
                    self.assertIn("Settings: not signed", threshold["toasts"])
                self.assertTrue(threshold["dark"][1] and threshold["dark"][0] != threshold["dark"][1], threshold)
                self.assertEqual(threshold["fits"], {"page": True, "panel": True})
                self.assertEqual([seen for seen in light["violations"] if not seen.endswith("/favicon.ico")], [])
        words = [row for row in log_rows(self.engines.scratch / "piper.jsonl") if row["text"] == f"{WORD}\n"]
        self.assertEqual(len(words), 1, "the procedure word line of one voice renders once and then hits the cache")
        self.assertEqual(self.httpd.hub.settings.get()["speech"]["threshold"], THRESHOLDS[390] if signed else 50)

    def morse_steps(self, browser: str) -> list[dict]:
        steps = []
        for width, height in base.WIDTHS:
            shot = str(OUT / f"{browser}-{width}-radio-morse")
            steps += [
                {"width": width, "height": height, "url": f"{self.base}?{width}-morse#stream", "wait": 1200, "probe": probe(MORSE).replace("@WPM@", str(WPMS[width])), "shot": f"{shot}-keying.png", "gesture": True},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(MORSE_STOP), "shot": f"{shot}-stopped.png", "gesture": True},
            ]
        return steps

    def check_morse(self, data: dict, browser: str) -> None:
        results = iter(data["results"])
        before = 20
        for width, _ in base.WIDTHS:
            keying, stopped = next(results), next(results)
            wpm = WPMS[width]
            with self.subTest(browser=browser, width=width, part="morse keying"):
                self.assertNotIn("error", keying, keying)
                self.assertEqual(keying["mode"][:2], [["morse"], "Morse"], keying)
                self.assertIn("SOS", keying["mode"][2])
                self.assertEqual(keying["before"], ["5", "40", "1", str(before), f"{before} WPM ({before * 50} dots/min)"], keying)
                self.assertEqual((keying["dragged"], keying["toast"], keying["saved"]), (f"{wpm} WPM ({wpm * 50} dots/min)", True, [str(wpm), f"{wpm} WPM ({wpm * 50} dots/min)"]), keying)
                self.assertTrue(keying["playing"], keying)
                self.assertEqual([(entry["frequency"], entry["type"]) for entry in keying["keyed"]], [(engines.pitch_of("s2"), "sine")], keying)
                self.assertEqual(keying["tts"], 0, "Morse mode asks the hub for no speech line")
                self.assertEqual(keying["lamp"], ["RX", "true"])
                self.assertFalse(keying["caption"][0])
                self.assertTrue(keying["caption"][1].startswith("Stage"), keying)
                self.assertEqual((keying["gearFits"], keying["fits"]), ({"page": True, "panel": True}, {"page": True, "panel": True}), keying)
            with self.subTest(browser=browser, width=width, part="morse stop"):
                self.assertNotIn("error", stopped, stopped)
                self.assertEqual(stopped, {"before": [True, "true", False], "cut": True, "quiet": True, "hidden": True, "later": 0}, stopped)
            before = wpm
        self.assertEqual(self.httpd.hub.settings.get()["morse"], {"wpm": WPMS[390]})

    def test_chromium_keys_every_row_whole_in_morse_at_the_hub_speed_in_its_sender_pitch_and_stop_cuts_it_at_three_widths(self):
        data = self.drive(self.morse_steps("chromium"), None, init=MORSE_SPY)
        (OUT / "chromium-radio-morse.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        self.check_morse(data, "chromium")

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_keys_every_row_whole_in_morse_at_the_hub_speed_in_its_sender_pitch_and_stop_cuts_it_at_three_widths(self):
        data = self.drive(self.morse_steps("firefox"), None, "bidi.mjs", os.environ.get("FIREFOX", "firefox"), init=MORSE_SPY)
        (OUT / "firefox-radio-morse.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        self.check_morse(data, "firefox")

    def test_chromium_plays_the_radio_set_modes_burst_and_procedure_words_and_filters_the_log_at_three_widths(self):
        data = self.drive(self.steps("chromium", True), self.authenticator(), init=SPY)
        (OUT / "chromium-radio-set.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        self.check(data, "chromium", True)

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_plays_the_radio_set_modes_burst_and_procedure_words_and_keeps_the_threshold_unsigned_at_three_widths(self):
        data = self.drive(self.steps("firefox", False), None, "bidi.mjs", os.environ.get("FIREFOX", "firefox"), init=SPY)
        (OUT / "firefox-radio-set.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        self.check(data, "firefox", False)


if __name__ == "__main__":
    unittest.main()
