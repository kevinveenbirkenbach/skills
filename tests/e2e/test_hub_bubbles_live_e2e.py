from __future__ import annotations

import json
import os
import shutil
import sys
import time
import unittest
from collections.abc import Callable
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

import test_orchestrator_e2e as base
from hub_case import HubCase
from hub_support import iso

OUT = Path(os.environ.get("E2E_OUT", "/tmp/hub-bubbles-live-shots"))
SENDERS = ["Stage", "Docs", "Build", "Team", "Cosmos", "Store"]
CAP = 3
LATE_MS = 5000
SLACK_MS = 2000
GUARD = """() => {
  window.e2eRejections = [];
  window.addEventListener("unhandledrejection", (event) => window.e2eRejections.push(String((event.reason && event.reason.stack) || event.reason)));
  const fetched = window.fetch.bind(window);
  window.fetch = (input, init) => (window.e2eOffline && String(input).includes("/api/state") ? Promise.reject(new Error("offline")) : fetched(input, init));
  try {
    localStorage.setItem("kvb-orchestrator.radio", JSON.stringify({mode: "auto"}));
  } catch (error) {
    return;
  }
}"""
PROBE = """(async () => {@HELPERS@
  const keys = @KEYS@;
  const toggle = document.getElementById("bubbles-toggle");
  const layer = document.getElementById("bubbles");
  const live = () => all(".speech-bubble:not(.leaving)", layer);
  const log = [];
  let most = 0;
  new MutationObserver((records) => {
    for (const record of records) {
      const nodes = [...record.addedNodes].filter((node) => node instanceof Element && node.matches(".speech-bubble"));
      const changed = record.type === "attributes" && record.target.matches(".speech-bubble") ? [record.target] : [];
      [...nodes, ...changed].forEach((node) => log.push({t: performance.now(), who: node.dataset.who || null, state: node.dataset.state || null}));
    }
    most = Math.max(most, live().length);
  }).observe(layer, {subtree: true, childList: true, attributes: true, attributeFilter: ["data-state", "class"]});
  const cue = (word) => fetch("/api/tts", {method: "POST", headers: {"X-Kvb-Orchestrator": "1", "Content-Type": "application/json"}, body: JSON.stringify({text: word, voice: ""}), cache: "no-store"});
  const poll = () => window.dispatchEvent(new Event("focus"));
  const cleared = () => until(() => !layer.querySelector(".speech-bubble"), 30000);
  document.dispatchEvent(new PointerEvent("pointerdown", {bubbles: true}));
  toggle.click();
  const on = Boolean(await until(() => toggle.getAttribute("aria-pressed") === "true" && !layer.hidden, 8000));
  await sleep(1500);
  poll();
  await sleep(3000);
  const loaded = log.length;
  window.e2eOffline = true;
  poll();
  await sleep(1200);
  await cue("e2e-backlog");
  poll();
  await sleep(1200);
  const offline = text(document.getElementById("updated")).startsWith("No connection");
  window.e2eOffline = false;
  poll();
  await sleep(4000);
  const resumed = log.length - loaded;
  let from = log.length;
  await cue("e2e-live");
  poll();
  await until(() => [keys.Stage, keys.Docs, keys.Build].every((who) => log.slice(from).some((entry) => entry.who === who && entry.state === "quiet")), 20000);
  const classes = Object.fromEntries(["Stage", "Docs", "Build"].map((name) => [name, log.slice(from).some((entry) => entry.who === keys[name] && entry.state === "quiet")]));
  await cleared();
  most = 0;
  from = log.length;
  await cue("e2e-burst");
  poll();
  await sleep(12000);
  const burst = {most, agents: new Set(log.slice(from).filter((entry) => entry.state === "quiet").map((entry) => entry.who)).size};
  toggle.click();
  await until(() => toggle.getAttribute("aria-pressed") === "false", 8000);
  toggle.click();
  await until(() => toggle.getAttribute("aria-pressed") === "true", 8000);
  await cleared();
  const timed = async (word) => {
    const start = log.length;
    await cue(word);
    performance.clearResourceTimings();
    const asked = performance.now();
    poll();
    const spoke = await until(() => log.slice(start).find((entry) => entry.who === keys.Docs && entry.state === "speaking"), 20000);
    const quiet = log.slice(start).filter((entry) => entry.state === "quiet" && spoke && entry.t <= spoke.t);
    const fetches = performance.getEntriesByType("resource").filter((entry) => /\\/api\\/(state|tts)/.test(entry.name)).map((entry) => [entry.name.includes("/api/tts") ? "tts" : "state", Math.round(entry.startTime - asked), Math.round(entry.requestStart - entry.startTime), Math.round(entry.responseEnd - entry.startTime)]);
    await cleared();
    return {delay: spoke ? Math.round(spoke.t - asked) : null, firstQuiet: quiet.length ? Math.round(quiet[0].t - asked) : null, quietBefore: new Set(quiet.map((entry) => entry.who)).size, fetches};
  };
  const speech = await timed("e2e-speech");
  const alone = await timed("e2e-alone");
  return {on, loaded, offline, resumed, classes, burst, speech, alone, rejections: window.e2eRejections};
})()"""


@unittest.skipUnless(
    shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium"
)
class TestLiveBubbles(HubCase):
    drive = base.TestOrchestratorE2E.drive
    beside = base.TestOrchestratorE2E.beside

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        now = time.time()
        claims = {
            f"work/s{index}/claim.json": {
                "office": f"work/s{index}",
                "session": f"s{index}",
                "runtime": "claude",
                "name": name,
                "since": iso(now - 7200),
                "beat": now - 60,
                "work": "x",
            }
            for index, name in enumerate(SENDERS[:2], start=2)
        }
        backlog = [
            {
                "ts": now - 5,
                "from": name,
                "to": [],
                "text": f"backlog from {name}",
                "class": "broadcast",
                "v": 2,
            }
            for name in SENDERS
        ]
        self.write_council({**claims, "news.jsonl": self.jsonl(backlog)})
        self.keys = {row["from"]: row["source"] for row in self.snapshot()["radio"]}
        self.host_cpu(95.0, 0)
        self.beside(lambda: self.host_cpu(95.0, 0))
        hub = self.httpd.hub
        spoken = base.tone(1, 8000)
        cues = {
            "e2e-backlog": [
                ("post", "Stage", ["Docs"], "posted while the page was offline"),
                ("broadcast", "Docs", [], "broadcast while the page was offline"),
            ],
            "e2e-live": [
                ("post", "Stage", ["Docs"], "rebase please, the gate is red"),
                ("broadcast", "Docs", [], "docs are green for everyone"),
                ("newsletter", "Build", [], "build cache trimmed"),
            ],
            "e2e-burst": [
                ("post", SENDERS[index % len(SENDERS)], ["Stage"], f"burst row {index}")
                for index in range(30)
            ],
            "e2e-speech": [
                *(
                    ("post", SENDERS[at], ["Docs"], f"silent row {index}")
                    for index, at in enumerate((0, 2, 3, 4, 5) * 2)
                ),
                ("security", "Docs", [], "Disk almost full on the build host"),
            ],
            "e2e-alone": [
                ("security", "Docs", [], "Disk almost full on the backup host"),
            ],
        }

        def synthesize(body: bytes, admit: Callable[[str], None]) -> bytes:
            word = json.loads(body)["text"]
            if word in cues:
                stamp = time.time()
                rows = [
                    {
                        "ts": stamp - (len(cues[word]) - 1 - index) / 1000,
                        "from": sender,
                        "to": to,
                        "text": text,
                        "class": cls,
                        "v": 2,
                    }
                    for index, (cls, sender, to, text) in enumerate(cues[word])
                ]
                with (self.council / "news.jsonl").open(
                    "a", encoding="utf-8"
                ) as handle:
                    handle.write(self.jsonl(rows))
            else:
                admit(word)
            return spoken

        patch = mock.patch.object(hub.speech, "synthesize", synthesize)
        patch.start()
        self.addCleanup(patch.stop)
        self.base = f"http://localhost:{self.port}/"

    def steps(self, browser: str) -> list[dict]:
        probe = PROBE.replace("@HELPERS@", base.HELPERS).replace(
            "@KEYS@", json.dumps(self.keys)
        )
        return [
            {
                "width": 1366,
                "height": 768,
                "url": f"{self.base}#stream",
                "wait": 1200,
                "probe": probe,
                "shot": str(OUT / f"{browser}-1366-live-bubbles.png"),
                "gesture": True,
            }
        ]

    def check(self, data: dict) -> None:
        found = data["results"][0]
        self.assertNotIn("error", found, found)
        self.assertTrue(found["on"], found)
        self.assertEqual(
            (found["loaded"], found["offline"], found["resumed"]), (0, True, 0), found
        )
        self.assertEqual(
            found["classes"], {"Stage": True, "Docs": True, "Build": True}, found
        )
        self.assertTrue(
            found["burst"]["most"] <= CAP and found["burst"]["agents"] >= CAP, found
        )
        speech, alone = found["speech"], found["alone"]
        self.assertGreaterEqual(speech["quietBefore"], CAP, found)
        self.assertEqual(alone["quietBefore"], 0, found)
        self.assertLess(speech["delay"], LATE_MS, found)
        self.assertLess(alone["delay"], LATE_MS, found)
        self.assertLess(speech["delay"] - alone["delay"], SLACK_MS, found)
        self.assertEqual(found["rejections"], [], found)

    def test_chromium_bubbles_every_live_row_but_no_backlog_caps_a_burst_and_never_delays_speech(
        self,
    ):
        data = self.drive(self.steps("chromium"), None, init=GUARD)
        (OUT / "chromium-live-bubbles.json").write_text(
            json.dumps(data, indent=1), encoding="utf-8"
        )
        self.assertEqual(data["errors"], [])
        self.check(data)

    @unittest.skipUnless(
        shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox"
    )
    def test_firefox_bubbles_every_live_row_but_no_backlog_caps_a_burst_and_never_delays_speech(
        self,
    ):
        data = self.drive(
            self.steps("firefox"),
            None,
            "bidi.mjs",
            os.environ.get("FIREFOX", "firefox"),
            init=GUARD,
        )
        (OUT / "firefox-live-bubbles.json").write_text(
            json.dumps(data, indent=1), encoding="utf-8"
        )
        self.assertEqual(
            [error for error in data["errors"] if "/favicon.ico" not in error], []
        )
        self.check(data)


if __name__ == "__main__":
    unittest.main()
