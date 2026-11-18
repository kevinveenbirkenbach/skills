from __future__ import annotations

import http.server
import json
import os
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

import hub_e2e_kit as base
from hub_e2e_kit import CHOICE_CHANNELS, OUT, WIDTHS, tone
from hub_e2e_radio import (
    ADD_STATION,
    BELL_READ,
    BELL_SAVE,
    CALL,
    CANCELED,
    CLEAR_MAYDAY,
    COMPOSE,
    COMPOSE_SEND,
    DLF_NODE,
    DLF_PATH,
    JUMPED,
    MEDIA_LOG,
    RADIO_CLICK,
    RADIO_JUMP,
    RADIO_STOP,
    RADIO_VIEW,
    SPEAK,
    SPEAK_END,
    SPEAK_GRAPH,
    SPOT_SEND,
    STATION_NAME,
    Station,
)
from hub_support import HOST_STATE
from kvb_orchestrator import skill_scripts

SEND_GROUP = [["PTT", "PTT: push to transmit the message; your passkey signs it"], ["More send options", "More: send a test message only you hear"]]


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestHubRadio(base.OrchestratorE2ECase):
    def station(self, tls: ssl.SSLContext | None = None, moved: str | None = None) -> str:
        """Args:
            tls: serves https with this context instead of plain http.
            moved: answers every request with a 302 to this URL instead of
                the tone.
        """
        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Station)
        httpd.body, httpd.moved = tone(30, 22050), moved
        if tls:
            httpd.socket = tls.wrap_socket(httpd.socket, server_side=True)
        thread = threading.Thread(target=httpd.serve_forever, args=(0.05,), daemon=True)
        thread.start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(thread.join, 10)
        self.addCleanup(httpd.shutdown)
        return f"{'https' if tls else 'http'}://127.0.0.1:{httpd.server_address[1]}{DLF_PATH if moved else '/tone.wav'}"

    def redirected(self) -> tuple[str, list[str]]:
        """Returns:
            A station that replays the recorded Deutschlandfunk chain, a 302
            from st01.sslstream.dlf.de to an f111.rndfnk.com node, as a 302 to
            a second https origin, and that origin as its released via.
        """
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder)
        key, cert = folder / "key.pem", folder / "cert.pem"
        subprocess.run([
            "openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256", "-nodes", "-subj", "/CN=127.0.0.1",
            "-addext", "subjectAltName=IP:127.0.0.1", "-days", "1", "-keyout", str(key), "-out", str(cert),
        ], capture_output=True, timeout=60, check=True)
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(cert, key)
        node = urlsplit(self.station(tls))
        origin = f"https://{node.netloc}"
        return self.station(tls, f"{origin}{DLF_NODE}"), [origin]

    def check_radio(self, browser: str, driver: str, binary: str, redirected: bool = False) -> dict:
        """Args:
            driver: cdp.mjs saves the station through the settings form and
                signs its new origin with a virtual passkey; bidi.mjs has no
                virtual authenticator, so the station is saved before the page
                loads.
            redirected: plays the recorded Deutschlandfunk redirect chain,
                saved before the page loads with its resolved via.
        """
        station, via = self.redirected() if redirected else (self.station(), [])
        browser = f"{browser}-dlf" if redirected else browser
        signs = driver == "cdp.mjs" and not redirected
        if signs:
            first = {"width": 1366, "height": 768, "url": f"http://localhost:{self.port}/#stream", "wait": 900, "probe": ADD_STATION.replace("@STATION@", station).replace("@NAME@", STATION_NAME), "shot": None, "gesture": True}
        else:
            hub = self.httpd.hub
            hub.settings.put({**hub.settings.get(), "streams": [{"name": STATION_NAME, "url": station, "from": "00:00", "to": "24:00", "days": list(range(7)), "on": True, "via": via}]}, hub.settings.get())
            first = {"width": 1366, "height": 768, "url": f"{self.base}#stream", "wait": 900, "probe": None, "shot": None}
        steps = [
            first,
            {"width": 390, "height": 844, "url": None, "wait": 3000, "probe": RADIO_VIEW, "shot": str(OUT / f"{browser}-390-radio-station.png")},
            {"width": 1366, "height": 768, "url": None, "wait": 0, "probe": RADIO_CLICK, "shot": str(OUT / f"{browser}-1366-radio-playing.png"), "gesture": True},
            {"width": 1366, "height": 768, "url": None, "wait": 0, "probe": RADIO_STOP, "shot": str(OUT / f"{browser}-1366-radio-stopped.png")},
        ]
        data = self.drive(steps, self.authenticator() if signs else None, driver, binary, MEDIA_LOG)
        (OUT / f"{browser}-radio.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        saved, view, click, stopped = data["results"]
        if signs:
            self.assertTrue(any(toast.startswith("New station") for toast in saved["toasts"]), saved)
        self.assertNotIn("error", view)
        self.assertEqual(view["title"], STATION_NAME)
        self.assertEqual(view["line"], ["nowrap", "ellipsis", True, True])
        blocked = [entry for entry in view["log"] if entry.get("play") == "NotAllowedError"]
        if not view["media"]["playing"]:
            self.assertTrue(blocked, view)
            self.assertEqual(view["state"], "blocked", view)
            self.assertIn("Click", view["note"])
            self.assertTrue(any("blocked" in toast for toast in view["toasts"]), view["toasts"])
            self.assertTrue(click["clicked"], click)
        self.assertNotIn("error", click)
        self.assertTrue(click["media"]["playing"], click)
        self.assertEqual(click["state"], "playing", click)
        self.assertEqual([entry for entry in click["log"] if entry.get("csp") == "media-src"], [])
        with self.subTest(browser=browser, part="station stop"):
            self.assertNotIn("error", stopped, stopped)
            self.assertEqual(stopped["button"], ["Stop", f"Stop: pause {STATION_NAME}", "", True])
            self.assertTrue(stopped["paused"], stopped)
            self.assertFalse(stopped["media"]["playing"], stopped)
            self.assertEqual((stopped["media"]["second"]["paused"], stopped["media"]["second"]["src"]), (True, None), stopped)
            self.assertEqual((stopped["state"], stopped["note"], stopped["action"]), ("stopped", "stopped", ["play", "Play"]), stopped)
            self.assertGreater(stopped["tracked"], 0, stopped)
            self.assertEqual(stopped["playing"], [], "an audio element still plays after Stop")
        return data

    def test_chromium_plays_a_saved_station(self):
        self.check_radio("chromium", "cdp.mjs", os.environ.get("CHROMIUM", "chromium"))

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_plays_a_saved_station(self):
        self.check_radio("firefox", "bidi.mjs", os.environ.get("FIREFOX", "firefox"))

    def test_chromium_plays_deutschlandfunk_through_its_redirect(self):
        self.check_radio("chromium", "cdp.mjs", os.environ.get("CHROMIUM", "chromium"), redirected=True)

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_plays_deutschlandfunk_through_its_redirect(self):
        self.check_radio("firefox", "bidi.mjs", os.environ.get("FIREFOX", "firefox"), redirected=True)

    def test_chromium_sends_a_call_from_the_agent_panel_and_shows_its_receipt(self):
        handled = []

        def answer() -> None:
            for script, args in self.scripts.calls[len(handled) :]:
                handled.append(script)
                if script.endswith("radio.py") and args[:2] == ["send", "call"]:
                    to, text, now = args[args.index("--to") + 1], args[-1], time.time()
                    rows = [{"ts": now, "from": "Operator", "to": [to], "text": text, "class": "call", "v": 2}, {"ts": now + 0.5, "from": to, "to": ["Operator"], "text": text, "class": "receipt", "v": 2, "call": now}]
                    self.write_council({"radio-seen/e2e-callee.json": {"radio": now + 0.5}})
                    (self.state / "agent-sessions.json").write_text(json.dumps({"written": now, "sessions": {"e2e-callee": {"name": to, "running": True}}}), encoding="utf-8")
                    with (self.council / "news.jsonl").open("a", encoding="utf-8") as handle:
                        handle.write(self.jsonl(rows))

        self.beside(answer)
        local = f"http://localhost:{self.port}/"
        data = self.drive([{"width": 1366, "height": 768, "url": f"{local}#stream", "wait": 900, "probe": CALL, "shot": self.shot("1366-call-receipt")}], self.authenticator())
        self.assertEqual(data["errors"], [])
        result = data["results"][0]
        self.assertNotIn("error", result)
        self.assertIsNotNone(result["receipt"], result)
        self.assertTrue(" · read " in result["receipt"] and result["receipt"].endswith(" · acknowledged"), result)
        self.assertEqual(result["read"], 0, result)

    def test_chromium_shows_who_speaks_while_a_message_is_read(self):
        self.speaks(("e2e-cue-1", "e2e-cue-2"))
        steps = [
            {"width": 1366, "height": 768, "url": f"{self.base}#stream/radio", "wait": 900, "probe": SPEAK.replace("@CUE@", "e2e-cue-1"), "shot": self.shot("1366-radio-speaking"), "gesture": True},
            {"width": 1366, "height": 768, "url": None, "wait": 0, "probe": SPEAK_GRAPH, "shot": self.shot("1366-agents-speaking")},
            {"width": 1366, "height": 768, "url": None, "wait": 0, "probe": SPEAK_END, "shot": None},
            {"width": 390, "height": 844, "url": None, "wait": 0, "probe": SPEAK.replace("@CUE@", "e2e-cue-2"), "shot": self.shot("390-radio-speaking-reduced-motion"), "gesture": True, "media": [{"name": "prefers-reduced-motion", "value": "reduce"}]},
        ]
        data = self.drive(steps, None)
        (OUT / "chromium-speaking.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        speaking, graph, ended, calm = data["results"]
        self.talks(speaking, graph)
        self.assertEqual(ended, {"ended": True, "caption": False, "faces": 0})
        self.assertEqual((calm["who"], calm["line"], calm["ring"]), ("Stage speaking", "Disk almost full (e2e-cue-2)", "none"), calm)
        self.assertEqual(calm["faces"]["speaking"], [True, "none"], calm)

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_shows_who_speaks_and_moves_only_the_speakers_mouth(self):
        self.speaks(("e2e-cue-1",))
        steps = [
            {"width": 1366, "height": 768, "url": f"{self.base}#stream/radio", "wait": 900, "probe": SPEAK.replace("@CUE@", "e2e-cue-1"), "shot": str(OUT / "firefox-1366-radio-speaking.png"), "gesture": True},
            {"width": 1366, "height": 768, "url": None, "wait": 0, "probe": SPEAK_GRAPH, "shot": str(OUT / "firefox-1366-agents-speaking.png")},
        ]
        data = self.drive(steps, None, "bidi.mjs", os.environ.get("FIREFOX", "firefox"))
        (OUT / "firefox-speaking.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        self.talks(*data["results"])

    def talks(self, speaking: dict, graph: dict) -> None:
        """Args:
            speaking: the SPEAK probe while Stage (s2) is read aloud.
            graph: the SPEAK_GRAPH probe on #agents/orbit right after it.
        """
        self.assertEqual((speaking["who"], speaking["line"], speaking["chip"], speaking["ring"]), ("Stage speaking", "Disk almost full (e2e-cue-1)", "s2", "speaking"), speaking)
        self.assertEqual(speaking["faces"], {"speaking": [True, "talk"], "silent": [False, "none"], "keys": ["s2"]}, speaking)
        self.assertEqual((graph["node"] or "").split(",")[0], "Stage", graph)
        self.assertEqual((graph["ring"], graph["mouth"], graph["silent"]), ("speaking-node", "talk", "none"), graph)

    def test_chromium_records_transcribes_and_sends_a_signed_call_with_voice(self):
        local = f"http://localhost:{self.port}/"
        steps = [
            {"width": 1366, "height": 768, "url": f"{local}#agents/orbit", "wait": 1200, "probe": COMPOSE.replace("@TO@", "Stage"), "shot": self.shot("1366-radio-spot-composer"), "gesture": True},
            {"width": 1366, "height": 768, "url": None, "wait": 0, "probe": COMPOSE_SEND.replace("@ATTACH@", "false"), "shot": None},
            {"width": 1366, "height": 768, "url": None, "wait": 0, "probe": COMPOSE.replace("@TO@", "Stage"), "shot": None, "gesture": True},
            {"width": 1366, "height": 768, "url": None, "wait": 0, "probe": COMPOSE_SEND.replace("@ATTACH@", "true"), "shot": self.shot("1366-radio-spot-composer-sent")},
        ]
        data = self.drive(steps, self.authenticator())
        (OUT / "chromium-composer.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        composed, plain, again, sent = data["results"]
        self.assertNotIn("error", composed)
        self.assertEqual(composed["channels"], ["post", "call", "newsletter", "broadcast", "pan-pan", "security", "mayday"])
        self.assertIn("Stage", composed["recipients"])
        self.assertEqual(composed["recording"], "true")
        self.assertEqual(composed["text"], "hello from the mic second line", composed)
        self.assertRegex(composed["replay"] or "", r"^/api/voice/[0-9a-f]{16}\.wav$")
        self.assertEqual(composed["attach"], ["Attach recording", False])
        self.assertEqual(composed["clashes"], {"found": [], "outside": []})
        self.assertEqual(again["attach"], ["Attach recording", False])
        note = again["replay"].removeprefix("/api/voice/").removesuffix(".wav")
        for result in (plain, sent):
            self.assertEqual((result["left"], result["voice"]), ("", False), result)
            self.assertTrue(result["sent"].startswith("Call to Stage: sent"), result)
        calls = [args for script, args in self.scripts.calls if script == skill_scripts.RADIO]
        self.assertEqual(len(calls), 2, self.scripts.calls)
        self.assertEqual([call[:4] for call in calls], [["send", "call", "--to", "Stage"]] * 2)
        self.assertTrue(calls[0][-1].endswith("] hello from the mic second line please"), calls[0])
        self.assertTrue(calls[1][-1].endswith(f"] hello from the mic second line please voice: {HOST_STATE}/voice/{note}.wav"), calls[1])
        status, _, body = self.get(f"/api/voice/{note}.wav")
        self.assertEqual((status, body[:4]), (200, b"RIFF"))

    def test_chromium_clears_the_mayday_from_the_radio_spot_only_after_confirmation_and_passkey_at_three_widths(self):
        local = f"http://localhost:{self.port}/"
        steps = [{"width": width, "height": height, "url": f"{local}?{width}#agents/orbit", "wait": 1200, "probe": CLEAR_MAYDAY, "shot": self.shot(f"{width}-radio-spot-mayday-cleared")} for width, height in WIDTHS]
        data = self.drive(steps, self.authenticator())
        (OUT / "chromium-mayday.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        question = "Lift the radio silence of the active mayday?"
        for result, (width, _) in zip(data["results"], WIDTHS, strict=True):
            with self.subTest(width=width):
                self.assertNotIn("error", result)
                self.assertEqual(result["toolbar"], ["Priority", "Day/Night", "Drain", "Suspend", "Resume", "Status"])
                self.assertEqual((result["title"], result["shown"]), ("Cancel mayday: lift the radio silence so the agents write again; your passkey signs it", "Cancel mayday"))
                self.assertEqual(result["declined"], {"question": [question], "posted": [], "toasts": []})
                self.assertEqual(result["accepted"], {"question": [question], "posted": ["/api/board/sign", "/api/board/clear-mayday"]})
                self.assertTrue((result["done"] or "").startswith("Cancel mayday: done"), result)
        self.assertEqual(self.scripts.calls, [(skill_scripts.RADIO, ["clear", "--force", "--session", "Operator"])] * len(WIDTHS))

    def test_chromium_sends_every_class_from_the_radio_spot_and_keeps_its_bells_through_a_reload_at_three_widths(self):
        local = f"http://localhost:{self.port}/"
        values = {1920: ("0.35", "off", "speak"), 1366: ("0.45", "speak", "tone"), 390: ("0.55", "tone", "speak")}
        steps = [{"width": width, "height": height, "url": f"{local}?{width}-jump#stream/radio", "wait": 1200, "probe": RADIO_JUMP, "shot": self.shot(f"{width}-radio-header-spot-every-tab")} for width, height in WIDTHS]
        for width, height in WIDTHS:
            squelch, radio_bell, post = values[width]
            bells = BELL_SAVE.replace("@SQUELCH@", squelch).replace("@RADIO@", radio_bell).replace("@POST@", post)
            steps += [
                {"width": width, "height": height, "url": f"{local}?{width}#agents/orbit", "wait": 1200, "probe": SPOT_SEND.replace("@TEXT@", f"spot {width}"), "shot": self.shot(f"{width}-radio-spot-sent")},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": bells, "shot": None},
                {"width": width, "height": height, "url": f"{local}?{width}-reloaded#agents/orbit", "wait": 1200, "probe": BELL_READ, "shot": self.shot(f"{width}-radio-spot-bells")},
            ]
        data = self.drive(steps, self.authenticator())
        (OUT / "chromium-radio-spot.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        labels = dict(zip(CHOICE_CHANNELS, ["Post", "Call", "Newsletter", "Broadcast", "Pan-Pan", "Sécurité", "Mayday"], strict=True))
        mayday = "Send a mayday to all? All agents pause writing steps until you cancel it."
        jumps, walked = data["results"][: len(WIDTHS)], data["results"][len(WIDTHS) :]
        for jump, (width, _) in zip(jumps, WIDTHS, strict=True):
            with self.subTest(width=width, part="radio spot on every tab"):
                self.assertEqual(jump, JUMPED)
        for index, (width, _) in enumerate(WIDTHS):
            sent, saved, read = walked[3 * index : 3 * (index + 1)]
            squelch, radio_bell, post = values[width]
            with self.subTest(width=width):
                for probe in (sent, saved, read):
                    self.assertNotIn("error", probe)
                self.assertEqual((sent["closed"], sent["open"]), ([True, "false"], [False, "true", True]))
                self.assertEqual(sent["inline"], ["static", True, True])
                self.assertEqual((sent["toolbar"], sent["channels"], sent["record"]), (["Priority", "Day/Night", "Status"], CHOICE_CHANNELS, ["Record"]))
                self.assertEqual((sent["heads"], sent["send"], sent["cancel"]), (0, SEND_GROUP, True))
                self.assertEqual((sent["tall"], sent["wide"]), (width == 390, False))
                self.assertEqual([run["cls"] for run in sent["runs"]], CHOICE_CHANNELS)
                for run in sent["runs"]:
                    direct = run["cls"] in ("post", "call")
                    self.assertEqual((run["direct"], run["question"], run["left"]), (direct, [mayday] if run["cls"] == "mayday" else [], ""), run)
                    self.assertTrue((run["toast"] or "").startswith(f"{labels[run['cls']]} to {'Stage' if direct else 'all'}: sent"), run)
                self.assertEqual(saved["clashes"], [{"found": [], "outside": []}])
                self.assertEqual(saved["tones"], ["MAYDAY / PAN-PAN", "Reviews, asks, decisions", "Post and calls to you", "All radio", "Squelch", "speak while CPU < 50 %"])
                self.assertEqual(saved["bells"], ["MAYDAY / PAN-PAN tone", "Reviews, asks, decisions tone", "Post and calls to you tone", "All radio tone"])
                self.assertEqual((saved["kept"], saved["after"]), ([float(squelch), radio_bell != "off", post == "speak"], [radio_bell, post]))
                self.assertEqual(saved["general"], {"sections": ["Ambience", "Location", "Appearance", "Music", "Notifications", "Passkey"], "radio": 0})
                self.assertEqual((saved["tall"], saved["wide"]), (width == 390, False))
                self.assertEqual(read, {"squelch": float(squelch), "radio": radio_bell, "post": post, "tall": width == 390, "wide": False})
        heads = {"post": ["post", "--to", "Stage"], "call": ["send", "call", "--to", "Stage"], "newsletter": ["post"]}
        radio = [args for script, args in self.scripts.calls if script == skill_scripts.RADIO]
        sends = [(width, cls) for width, _ in WIDTHS for cls in CHOICE_CHANNELS]
        self.assertEqual([args[:-1] for args in radio], [[*heads.get(cls, ["send", cls]), "--session", "Operator"] for _, cls in sends])
        for args, (width, cls) in zip(radio, sends, strict=True):
            with self.subTest(width=width, cls=cls):
                self.assertTrue(args[-1].endswith(f"] spot {width} {cls}"), args)
        self.assertEqual(self.httpd.hub.settings.get()["speech"], {"threshold": 50})

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_opens_the_radio_spot_on_every_tab_and_asks_the_passkey_for_every_class_and_cancel_mayday_sending_nothing_unsigned_at_three_widths(self):
        self.pin()
        local = f"http://localhost:{self.port}/"
        steps = []
        for width, height in WIDTHS:
            shot = str(OUT / f"firefox-{width}-radio-spot")
            steps += [
                {"width": width, "height": height, "url": f"{local}?{width}-jump#stream/radio", "wait": 1200, "probe": RADIO_JUMP, "shot": f"{shot}-every-tab.png"},
                {"width": width, "height": height, "url": f"{local}?{width}#agents/orbit", "wait": 1200, "probe": SPOT_SEND.replace("@TEXT@", f"spot {width}"), "shot": f"{shot}-unsigned.png"},
                {"width": width, "height": height, "url": f"{local}?{width}-mayday#agents/orbit", "wait": 1200, "probe": CLEAR_MAYDAY, "shot": f"{shot}-mayday-kept.png"},
            ]
        data = self.drive(steps, None, "bidi.mjs", os.environ.get("FIREFOX", "firefox"), CANCELED)
        (OUT / "firefox-radio-spot.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "(style-src-elem)" not in error and "/favicon.ico" not in error], [])
        labels = dict(zip(CHOICE_CHANNELS, ["Post", "Call", "Newsletter", "Broadcast", "Pan-Pan", "Sécurité", "Mayday"], strict=True))
        mayday = "Send a mayday to all? All agents pause writing steps until you cancel it."
        question = "Lift the radio silence of the active mayday?"
        hint = "Cancel mayday: lift the radio silence so the agents write again; your passkey signs it"
        results = iter(data["results"])
        for width, _ in WIDTHS:
            jump, sent, cleared = next(results), next(results), next(results)
            with self.subTest(browser="firefox", width=width, part="radio spot on every tab"):
                self.assertEqual(jump, JUMPED)
            with self.subTest(browser="firefox", width=width, part="every class unsigned"):
                self.assertNotIn("error", sent, sent)
                self.assertEqual((sent["closed"], sent["open"], sent["inline"]), ([True, "false"], [False, "true", True], ["static", True, True]))
                self.assertEqual((sent["toolbar"], sent["channels"], sent["record"]), (["Priority", "Day/Night", "Status"], CHOICE_CHANNELS, ["Record"]))
                self.assertEqual((sent["heads"], sent["send"], sent["cancel"]), (0, SEND_GROUP, True))
                self.assertEqual((sent["tall"], sent["wide"]), (width == 390, False))
                self.assertEqual([run["cls"] for run in sent["runs"]], CHOICE_CHANNELS)
                for run in sent["runs"]:
                    direct = run["cls"] in ("post", "call")
                    self.assertEqual((run["direct"], run["question"], run["left"]), (direct, [mayday] if run["cls"] == "mayday" else [], f"spot {width} {run['cls']}"), run)
                    self.assertTrue((run["toast"] or "").startswith(f"{labels[run['cls']]} to {'Stage' if direct else 'all'}: not signed"), run)
                    self.assertIn("NotAllowedError", run["toast"], run)
            with self.subTest(browser="firefox", width=width, part="cancel mayday next to PTT unsigned"):
                self.assertNotIn("error", cleared, cleared)
                self.assertEqual(cleared["toolbar"], ["Priority", "Day/Night", "Drain", "Suspend", "Resume", "Status"])
                self.assertEqual((cleared["title"], cleared["shown"]), (hint, "Cancel mayday"))
                self.assertEqual(cleared["declined"], {"question": [question], "posted": [], "toasts": []})
                self.assertEqual(cleared["accepted"], {"question": [question], "posted": ["/api/board/sign"]})
                self.assertTrue((cleared["done"] or "").startswith("Cancel mayday: not signed"), cleared)
        self.assertEqual(self.scripts.calls, [])
        self.assertTrue((self.council / "radio-silence.json").exists())


if __name__ == "__main__":
    unittest.main()
