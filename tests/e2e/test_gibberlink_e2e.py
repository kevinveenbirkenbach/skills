from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

import hub_e2e_kit as base
from hub_case import HubCase
from hub_support import HUB, iso
from kvb_orchestrator import engines
from radio_set_kit import CUES, OUT, SPY, WORD, probe

GGWAVE = HUB / "vendor" / "ggwave" / "ggwave.js"
SPOKEN = "Disk at ninety percent"
GIBBER_SPY = """() => {
  (@SPY@)();
  const captured = window.e2eGibber = [];
  const pans = window.e2ePans = [];
  const encoded = (part) => {
    const raw = new Uint8Array(part.buffer, part.byteOffset, part.byteLength);
    let binary = "";
    for (let at = 0; at < raw.length; at += 0x8000) {
      binary += String.fromCharCode(...raw.subarray(at, at + 0x8000));
    }
    return btoa(binary);
  };
  window.addEventListener("message", (event) => {
    if (event.data && Array.isArray(event.data.samples)) {
      captured.push({rate: event.data.rate, frames: event.data.samples.map(encoded)});
    }
  });
  const panner = AudioContext.prototype.createStereoPanner;
  AudioContext.prototype.createStereoPanner = function panned() {
    const node = panner.call(this);
    pans.push(node);
    return node;
  };
}""".replace("@SPY@", SPY)
GIBBER_KIT = """
  const gear = () => all(".spot-head button", spot).find((button) => name(button) === "Read aloud");
  const fallbacks = () => all('#radio-gear .chips[aria-label="Fallback"] .chip', spot);
  const kept = () => JSON.parse(localStorage.getItem("kvb-orchestrator.radio") || "{}").fallback || null;
  const opened = async (open) => {
    if ((gear().getAttribute("aria-expanded") === "true") !== open) {
      gear().click();
      await sleep(200);
    }
  };
  const sent = async (count) => {
    await cue("alarm");
    refreshNow();
    return Boolean(await until(() => window.e2eGibber.length > count && lamp().dataset.lit === "true", 40000));
  };
  const stopped = async () => {
    const stop = all("button", spot.querySelector(".radio-caption")).find((button) => name(button) === "Stop speaking");
    if (stop) {
      stop.click();
    }
    return Boolean(await until(() => lamp().dataset.lit === "false", 3000));
  };
"""
GIBBER = """(async () => {@HELPERS@@RADIO@@KIT@
  press("gibberlink");
  await sleep(200);
  const button = spot.querySelector('.radio-modes button[data-mode="gibberlink"]');
  const mode = [pressed(), field("mode"), button.title, Boolean(button.querySelector("svg.bi"))];
  await opened(true);
  const before = fallbacks().map((chip) => [text(chip), chip.getAttribute("aria-pressed")]);
  fallbacks().find((chip) => text(chip) === "Morse").click();
  await sleep(150);
  const morse = [fallbacks().map((chip) => chip.getAttribute("aria-pressed")), kept()];
  fallbacks().find((chip) => text(chip) === "Gibberlink").click();
  await sleep(150);
  const back = [fallbacks().map((chip) => chip.getAttribute("aria-pressed")), kept()];
  const label = text(spot.querySelector("#radio-gear .radio-fallback .chips-label"));
  const gearFits = fits();
  await opened(false);
  const at = {captured: window.e2eGibber.length, pans: window.e2ePans.length};
  const playing = await sent(at.captured);
  await sleep(300);
  return {
    mode, before, morse, back, label, gearFits, playing, captured: window.e2eGibber.slice(at.captured), pans: window.e2ePans.slice(at.pans).map((node) => node.pan.value),
    lamp: [text(lamp()), lamp().dataset.lit], caption: text(spot.querySelector(".radio-caption strong")), fits: fits(), frames: document.querySelectorAll("iframe.gibberlink-encoder").length,
  };
})()"""
STOP = """(async () => {@HELPERS@@RADIO@@KIT@
  const lit = lamp().dataset.lit;
  return {lit, quiet: await stopped(), hidden: spot.querySelector(".radio-caption").hidden};
})()"""
QUIET = """(async () => {@HELPERS@@RADIO@@KIT@
  press("quiet");
  await sleep(200);
  const at = {captured: window.e2eGibber.length, tts: audio().tts.length};
  const played = await sent(at.captured);
  const quiet = await stopped();
  const tts = audio().tts.slice(at.tts).map((entry) => entry.body.text);
  await opened(true);
  return {played, quiet, tts, captured: window.e2eGibber.slice(at.captured), fits: fits(), violations: window.e2eViolations};
})()"""
DECODE = """
const fs = require("fs");
const factory = require(process.argv[1]);
const captures = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
factory({print: () => undefined, printErr: () => undefined}).then((ggwave) => {
  console.log(JSON.stringify(captures.map(({rate, frames}) => {
    const parameters = ggwave.getDefaultParameters();
    parameters.sampleRateInp = rate;
    const listener = ggwave.init(parameters);
    const heard = [];
    const gap = new Float32Array(Math.round(rate * 0.3));
    for (const frame of frames) {
      const raw = Buffer.from(frame, "base64");
      const parts = [new Float32Array(raw.buffer.slice(raw.byteOffset, raw.byteOffset + raw.length)), gap];
      for (const samples of parts) {
        for (let at = 0; at < samples.length; at += 1024) {
          const got = ggwave.decode(listener, new Int8Array(samples.slice(at, at + 1024).buffer));
          if (got && got.length) {
            heard.push(Buffer.from(got.buffer, got.byteOffset, got.length).toString("utf8"));
          }
        }
      }
    }
    ggwave.free(listener);
    return heard;
  })));
});
"""


def kit(template: str) -> str:
    return probe(template).replace("@KIT@", GIBBER_KIT)


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestGibberlink(HubCase):
    drive = base.OrchestratorE2ECase.drive
    beside = base.OrchestratorE2ECase.beside

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        now = time.time()
        self.claim("s1", "Skills session")
        self.write_council({"work/s2/claim.json": {"office": "work/s2", "session": "s2", "runtime": "claude", "name": "Stage", "since": iso(now - 7200), "beat": now - 60, "work": "x"}, "news.jsonl": ""})
        hub = self.httpd.hub
        hub.settings.put({**hub.settings.get(), "theme": "light"}, hub.settings.get())
        self.host_cpu(10.0, 0)
        self.beside(lambda: self.host_cpu(10.0, 0))
        self.sent = 0
        heard = hub.voice_notes.get

        def get(note_id: str) -> dict:
            if note_id != CUES["alarm"]:
                return heard(note_id)
            self.sent += 1
            row = {"ts": time.time(), "from": "Stage", "to": [], "text": f"{SPOKEN} {self.sent}", "class": "security", "v": 2}
            with (self.council / "news.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(self.jsonl([row]))
            return {"id": note_id, "status": "done", "text": "", "error": "", "seconds": None, "created_ts": None}

        patch = mock.patch.object(hub.voice_notes, "get", get)
        patch.start()
        self.addCleanup(patch.stop)
        self.base = f"http://localhost:{self.port}/"

    def steps(self, browser: str) -> list[dict]:
        steps = []
        for width, height in base.WIDTHS:
            shot = str(OUT / f"{browser}-{width}-radio-gibberlink")
            steps += [
                {"width": width, "height": height, "url": f"{self.base}?{width}-gibberlink#stream", "wait": 1200, "probe": kit(GIBBER), "shot": f"{shot}-playing.png", "gesture": True},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": kit(STOP), "shot": None, "gesture": True},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": kit(QUIET), "shot": f"{shot}-fallback.png", "gesture": True},
            ]
        return steps

    def decoded(self, captures: list[dict]) -> list[list[str]]:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump(captures, handle)
        self.addCleanup(os.unlink, handle.name)
        done = subprocess.run(["node", "-e", DECODE, str(GGWAVE), handle.name], capture_output=True, text=True, timeout=600, check=True)
        return json.loads(done.stdout)

    def check(self, data: dict, browser: str) -> None:
        results = iter(data["results"])
        sound = engines.sound_of("s2")
        for index, (width, _) in enumerate(base.WIDTHS):
            played, stop, quiet = next(results), next(results), next(results)
            with self.subTest(browser=browser, width=width, part="mode and fallback"):
                self.assertNotIn("error", played, played)
                self.assertEqual(played["mode"][:2], [["gibberlink"], "Gibberlink"], played["mode"])
                self.assertIn("MAYDAY", played["mode"][2])
                self.assertTrue(played["mode"][3])
                self.assertEqual(played["before"], [["Gibberlink", "true"], ["Morse", "false"], ["Hiss", "false"]])
                self.assertEqual((played["morse"], played["back"], played["label"]), ([["false", "true", "false"], "morse"], [["true", "false", "false"], "gibberlink"], "Fallback"))
                self.assertEqual((played["gearFits"], played["fits"]), ({"page": True, "panel": True}, {"page": True, "panel": True}))
            with self.subTest(browser=browser, width=width, part="frames"):
                self.assertTrue(played["playing"], {key: value for key, value in played.items() if key != "captured"})
                self.assertEqual(([capture["rate"] for capture in played["captured"]], played["frames"]), ([48000], 1))
                self.assertEqual(len(played["pans"]), 1)
                self.assertAlmostEqual(played["pans"][0], sound["pan"], places=5)
                self.assertEqual(played["lamp"], ["RX", "true"])
                self.assertEqual(played["caption"], "Stage speaking")
                self.assertEqual(self.decoded(played["captured"]), [[f"s2 1/1 {SPOKEN} {2 * index + 1}"]])
            with self.subTest(browser=browser, width=width, part="stop"):
                self.assertEqual(stop, {"lit": "true", "quiet": True, "hidden": True})
            with self.subTest(browser=browser, width=width, part="fallback in quiet"):
                self.assertNotIn("error", quiet, quiet)
                self.assertEqual((quiet["played"], quiet["quiet"], quiet["tts"]), (True, True, [WORD]))
                self.assertEqual(self.decoded(quiet["captured"]), [[f"s2 1/1 {SPOKEN} {2 * index + 2}"]])
                self.assertEqual(quiet["fits"], {"page": True, "panel": True})
                self.assertEqual([seen for seen in quiet["violations"] if not seen.endswith("/favicon.ico")], [], "the hub page itself sees no CSP violation")

    def test_chromium_sends_every_row_as_decodable_ggwave_frames_from_the_sandboxed_encoder_at_three_widths(self):
        data = self.drive(self.steps("chromium"), None, init=GIBBER_SPY)
        (OUT / "chromium-radio-gibberlink.json").write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        self.check(data, "chromium")

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_sends_every_row_as_decodable_ggwave_frames_from_the_sandboxed_encoder_at_three_widths(self):
        data = self.drive(self.steps("firefox"), None, "bidi.mjs", os.environ.get("FIREFOX", "firefox"), init=GIBBER_SPY)
        (OUT / "firefox-radio-gibberlink.json").write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        self.check(data, "firefox")


if __name__ == "__main__":
    unittest.main()
