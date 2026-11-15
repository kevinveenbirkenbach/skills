from __future__ import annotations

import base64
import dataclasses
import json
import os
import shutil
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

import hub_e2e_kit as base
from hub_case import HubCase
from kvb_orchestrator import engines

OUT = Path(os.environ.get("E2E_OUT", "/tmp/voice-input-shots"))
WIDTHS = ((1920, 1080), (390, 844))
FIXTURE = HERE.parent / "fixtures" / "voice" / "hello-world.wav"
HEARD = "hello from the mic second line"
FAKE_MIC = """() => {
  const wav = Uint8Array.from(atob("@WAV@"), (char) => char.charCodeAt(0));
  const posted = [];
  window.__voice = {posted, opened: 0};
  const fetched = window.fetch.bind(window);
  window.fetch = (path, init) => {
    if (String(path) === "/api/stt") {
      posted.push(Date.now());
    }
    return fetched(path, init);
  };
  if (navigator.mediaDevices) {
    navigator.mediaDevices.getUserMedia = async () => {
      window.__voice.opened += 1;
      const sound = new AudioContext();
      sound.resume();
      const source = sound.createBufferSource();
      source.buffer = await sound.decodeAudioData(wav.slice().buffer);
      source.loop = true;
      const sink = sound.createMediaStreamDestination();
      source.connect(sink);
      source.start();
      return sink.stream;
    };
  }
}"""
MIC = """
  const FIELDS = 'textarea, input:not([type]), input[type="text"], input[type="search"]';
  const micOf = (field) => (field && field.id ? document.querySelector(`button.mic[aria-controls="${CSS.escape(field.id)}"]`) : null);
  const bare = () => all(FIELDS).filter((field) => !field.readOnly && !micOf(field)).map((field) => field.getAttribute("aria-label") || field.placeholder || field.outerHTML.slice(0, 80));
  const composer = () => document.querySelector('#radio-spot textarea[aria-label="Message"]');
  const live = () => {
    const found = document.getElementById("mic-live");
    return found && !found.hidden ? text(found) : null;
  };
  const look = (button) => {
    const box = button.getBoundingClientRect();
    return {pressed: button.getAttribute("aria-pressed"), disabled: button.disabled, title: button.title, width: box.width, height: box.height, live: live()};
  };
  const escape = () => document.dispatchEvent(new KeyboardEvent("keydown", {key: "Escape", bubbles: true, cancelable: true}));
  const openComposer = async () => {
    const spot = document.getElementById("radio-spot");
    if (spot.hidden) {
      document.getElementById("radio-open").click();
    }
    const field = await until(() => composer(), 4000);
    field.scrollIntoView({block: "center"});
    return field;
  };
"""
SCAN = """(async () => {@HELPERS@@MIC@
  const missing = {};
  let scanned = 0;
  for (const screen of @SCREENS@) {
    location.hash = `#${screen}`;
    await screenShown(8000);
    await sleep(250);
    scanned += all(FIELDS).length;
    const found = bare();
    if (found.length) {
      missing[screen] = found;
    }
  }
  for (const [name, opener] of [["settings", "settings-open"], ["palette", "palette-open"]]) {
    document.getElementById(opener).click();
    await sleep(500);
    scanned += all(FIELDS).length;
    const found = bare();
    if (found.length) {
      missing[name] = found;
    }
    escape();
    await sleep(300);
  }
  location.hash = "#stream";
  await screenShown(8000);
  const field = await openComposer();
  field.value = "start end";
  field.focus();
  field.setSelectionRange(6, 6);
  await sleep(400);
  return {missing, scanned, idle: look(micOf(field))};
})()"""
RECORD = """(async () => {@HELPERS@@MIC@
  const button = micOf(composer());
  button.click();
  await until(() => button.getAttribute("aria-pressed") === "true" && live(), 8000);
  await sleep(300);
  return {...look(button), opened: window.__voice.opened};
})()"""
STOP = """(async () => {@HELPERS@@MIC@
  const field = composer();
  const button = micOf(field);
  button.click();
  await until(() => field.value.includes("@HEARD@"), 20000);
  await sleep(200);
  return {value: field.value, caret: field.selectionStart, focused: document.activeElement === field, posts: window.__voice.posted.length, ...look(button)};
})()"""
CANCEL = """(async () => {@HELPERS@@MIC@
  const field = composer();
  const button = micOf(field);
  const before = [field.value, window.__voice.posted.length];
  button.click();
  const recording = Boolean(await until(() => button.getAttribute("aria-pressed") === "true" && live(), 8000));
  await sleep(800);
  escape();
  await until(() => button.getAttribute("aria-pressed") === "false" && !live(), 8000);
  await sleep(1500);
  return {recording, same: field.value === before[0], posts: window.__voice.posted.length - before[1], ...look(button)};
})()"""
DEAF = """(async () => {@HELPERS@@MIC@
  await screenShown(8000);
  const field = await openComposer();
  const button = micOf(field);
  button.click();
  await sleep(800);
  return {...look(button), opened: window.__voice.opened, posts: window.__voice.posted.length};
})()"""


def probe(source: str) -> str:
    return source.replace("@HELPERS@", base.HELPERS).replace("@MIC@", MIC).replace("@SCREENS@", json.dumps(base.SCREENS)).replace("@HEARD@", HEARD)


def fake_mic() -> str:
    return FAKE_MIC.replace("@WAV@", base64.b64encode(FIXTURE.read_bytes()).decode())


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestVoiceInputE2E(HubCase):
    drive = base.OrchestratorE2ECase.drive

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)

    def steps(self, browser: str) -> list[dict]:
        steps = []
        for width, height in WIDTHS:
            url = f"http://localhost:{self.port}/?{width}#stream"
            steps += [
                {"width": width, "height": height, "url": url, "wait": 1500, "probe": probe(SCAN), "shot": str(OUT / f"{browser}-{width}-idle.png"), "gesture": True},
                {"width": width, "height": height, "wait": 200, "probe": probe(RECORD), "shot": str(OUT / f"{browser}-{width}-recording.png"), "gesture": True},
                {"width": width, "height": height, "wait": 1200, "probe": probe(STOP), "gesture": True},
                {"width": width, "height": height, "wait": 200, "probe": probe(CANCEL), "gesture": True},
            ]
        return steps

    def deaf_steps(self) -> list[dict]:
        return [{"width": width, "height": height, "url": f"http://localhost:{self.port}/?{width}#stream", "wait": 1500, "probe": probe(DEAF), "gesture": True} for width, height in WIDTHS]

    def deafen(self) -> None:
        speech = self.httpd.hub.speech
        patch = mock.patch.object(speech, "engines", dataclasses.replace(speech.engines, whisper_model=self.outside / "ggml-missing.bin"))
        patch.start()
        self.addCleanup(patch.stop)

    def errors(self, data: dict) -> list[str]:
        return [error for error in data["errors"] if "/favicon.ico" not in error]

    def check(self, data: dict, browser: str) -> None:
        self.assertEqual(self.errors(data), [])
        for index, (width, _) in enumerate(WIDTHS):
            scan, recording, stopped, cancelled = data["results"][index * 4 : index * 4 + 4]
            with self.subTest(browser=browser, width=width):
                for found in (scan, recording, stopped, cancelled):
                    self.assertNotIn("error", found, found)
                self.assertEqual(scan["missing"], {}, scan)
                self.assertGreater(scan["scanned"], 0, scan)
                idle = scan["idle"]
                self.assertEqual((idle["pressed"], idle["disabled"], idle["live"]), ("false", False, None), idle)
                self.assertEqual((recording["pressed"], recording["opened"]), ("true", 1), recording)
                self.assertIn("Recording", recording["live"] or "", recording)
                self.assertEqual(stopped["value"], f"start {HEARD} end", stopped)
                self.assertEqual((stopped["caret"], stopped["focused"], stopped["posts"], stopped["pressed"], stopped["live"]), (len(f"start {HEARD}"), True, 1, "false", None), stopped)
                self.assertEqual((cancelled["recording"], cancelled["same"], cancelled["posts"], cancelled["pressed"], cancelled["live"]), (True, True, 0, "false", None), cancelled)
                if width < 640:
                    for shown in (idle, recording):
                        self.assertGreaterEqual(min(shown["width"], shown["height"]), 44, shown)

    def check_deaf(self, data: dict, browser: str) -> None:
        self.assertEqual(self.errors(data), [])
        for (width, _), found in zip(WIDTHS, data["results"], strict=True):
            with self.subTest(browser=browser, width=width):
                self.assertNotIn("error", found, found)
                self.assertEqual((found["disabled"], found["pressed"], found["opened"], found["posts"], found["live"]), (True, "false", 0, 0, None), found)
                self.assertIn(f"the operator row {engines.MODEL_ROW} installs it", found["title"], found)

    def test_chromium_records_from_a_fake_microphone_and_inserts_the_transcript_at_the_cursor_at_1920_and_390(self):
        data = self.drive(self.steps("chromium"), None, init=fake_mic())
        (OUT / "chromium-voice-input.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.check(data, "chromium")

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_records_from_a_fake_microphone_and_inserts_the_transcript_at_the_cursor_at_1920_and_390(self):
        data = self.drive(self.steps("firefox"), None, "bidi.mjs", os.environ.get("FIREFOX", "firefox"), init=fake_mic())
        (OUT / "firefox-voice-input.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.check(data, "firefox")

    def test_chromium_disables_the_microphone_and_names_the_operator_row_without_a_model(self):
        self.deafen()
        data = self.drive(self.deaf_steps(), None, init=fake_mic())
        (OUT / "chromium-voice-input-deaf.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.check_deaf(data, "chromium")

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_disables_the_microphone_and_names_the_operator_row_without_a_model(self):
        self.deafen()
        data = self.drive(self.deaf_steps(), None, "bidi.mjs", os.environ.get("FIREFOX", "firefox"), init=fake_mic())
        (OUT / "firefox-voice-input-deaf.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.check_deaf(data, "firefox")


if __name__ == "__main__":
    unittest.main()
