from __future__ import annotations

import json
import os
import shutil
import sys
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

import hub_e2e_kit as base
import test_radio_receipts_e2e as rr
from kvb_orchestrator import settings
from kvb_orchestrator.presence import SNAPSHOT

OUT = Path(os.environ.get("E2E_OUT", "/tmp/agent-settings-shots"))
WIDTH, HEIGHT = 1366, 900
SILENT = """() => {
  try {
    localStorage.setItem("kvb-orchestrator.radio", JSON.stringify({mode: "silence", classes: ["mayday", "security"]}));
  } catch (error) {
    return;
  }
}"""
KIT = """
  const SKIP = ".match-peek, .popup-head, .ctx-menu, .palette, #popup, .chip-check";
  const OPENERS = "button.agent-link, button.agent-face, button.reader, button.radio-sender, button.org-holder";
  const fresh = async () => (await (await fetch("/api/state", {cache: "no-store"})).json());
  const audit = async (root) => {
    const keys = (await fresh()).people || {};
    const faces = all(".avatar[data-face]", root).filter((node) => node.getClientRects().length && keys[node.dataset.face] && !node.closest(SKIP));
    return {count: faces.length, loose: faces.filter((node) => !node.closest(OPENERS)).map((node) => `${node.dataset.face} in ${node.parentElement.className}`)};
  };
  const closePopup = async () => {
    const close = all("#popup .popup-head button").find((node) => node.getAttribute("aria-label") === "Close");
    if (close) {
      close.click();
    }
    await until(() => !document.getElementById("popup").open, 4000);
  };
  const opens = async (button) => {
    if (!button) {
      return null;
    }
    button.click();
    const group = await until(() => document.getElementById("popup").open && document.querySelector("#popup .agent-settings[data-agent]"), 4000);
    const found = group ? {agent: group.dataset.agent, switches: all("[data-switch]", group).map((node) => [node.dataset.switch, node.getAttribute("aria-pressed"), text(node)])} : null;
    await closePopup();
    return found;
  };
  const shown = (selector) => all(selector).find((node) => node.getClientRects().length) || null;
"""
STREAM = """(async () => {@HELPERS@@KIT@
  await screenShown(8000);
  location.hash = "#stream";
  await streamShowsAll();
  await until(() => shown("#main .entry button.agent-link") && shown("#main .entry button.reader"), 10000);
  await sleep(400);
  const found = {
    audit: await audit(document.getElementById("main")),
    entry: await opens(shown("#main .entry button.agent-link")),
    reader: await opens(shown("#main .entry button.reader")),
  };
  location.hash = "#stream/inbox";
  await until(() => shown("#main .inbox-list button.agent-link"), 10000);
  return {...found, waiting: await opens(shown("#main .inbox-list button.agent-link"))};
})()"""
TASKS = """(async () => {@HELPERS@@KIT@
  location.hash = "#tasks";
  await until(() => shown("#main .who button.agent-link"), 10000);
  await sleep(400);
  return {audit: await audit(document.getElementById("main")), worker: await opens(shown("#main .who button.agent-link"))};
})()"""
RADIO = """(async () => {@HELPERS@@KIT@
  location.hash = "#stream/radio";
  const spot = await until(() => document.getElementById("radio-spot") && shown("#radio-spot .radio-row .radio-sender") && document.getElementById("radio-spot"), 10000);
  await sleep(400);
  return {audit: spot ? await audit(spot.querySelector(".radio-log")) : null, sender: await opens(shown("#radio-spot .radio-row .radio-sender"))};
})()"""
BUBBLES = """(async () => {@HELPERS@@KIT@
  const everything = document.querySelector('#radio-spot .radio-tabs [data-tab="all"]');
  if (everything && everything.getAttribute("aria-selected") !== "true") {
    everything.click();
    await sleep(400);
  }
  const row = await until(() => all("#radio-spot .radio-row").find((node) => node.querySelector(".radio-sender") && node.querySelector(".radio-route") && text(node.querySelector(".radio-route")).startsWith("Stage ")), 10000);
  if (!row) {
    return {error: "no radio row from Stage"};
  }
  row.querySelector(".radio-sender").click();
  const group = await until(() => document.getElementById("popup").open && document.querySelector("#popup .agent-settings[data-agent]"), 4000);
  if (!group) {
    return {error: "no agent settings for Stage"};
  }
  const agent = group.dataset.agent;
  const toggle = () => group.querySelector('[data-switch="bubbles"]');
  toggle().click();
  const pressed = Boolean(await until(() => toggle().getAttribute("aria-pressed") === "false", 6000));
  const end = Date.now() + 6000;
  let stored = null;
  while (Date.now() < end) {
    stored = ((await fresh()).settings.agents || {})[agent] || null;
    if (stored && stored.bubbles === false) {
      break;
    }
    await sleep(200);
  }
  await closePopup();
  const other = await until(() => document.querySelector('.speech-bubble:not([data-who="' + agent + '"])'), 15000);
  const seen = new Set();
  const watchUntil = Date.now() + 3000;
  while (Date.now() < watchUntil) {
    all(".speech-bubble").forEach((node) => seen.add(node.dataset.who));
    await sleep(100);
  }
  const quiet = await until(() => all("#radio-spot .radio-row").find((node) => text(node.querySelector(".radio-route") || node).startsWith("Stage ") && node.querySelector(".radio-sender")), 4000);
  quiet.querySelector(".radio-sender").click();
  const again = await until(() => document.getElementById("popup").open && document.querySelector("#popup .agent-settings[data-agent]"), 4000);
  again.querySelector('[data-switch="bubbles"]').click();
  await until(() => again.querySelector('[data-switch="bubbles"]').getAttribute("aria-pressed") === "true", 6000);
  await sleep(600);
  const back = ((await fresh()).settings.agents || {})[agent] || null;
  await closePopup();
  return {agent, pressed, stored, other: other ? other.dataset.who : null, seen: [...seen], back};
})()"""


def fill(probe: str) -> str:
    return probe.replace("@HELPERS@", base.HELPERS).replace("@KIT@", KIT)


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestAgentSettings(base.OrchestratorE2ECase):
    mark = rr.TestRadioReceipts.mark
    sight = rr.TestRadioReceipts.sight

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        file =self.state / "settings.json"
        file.write_text(json.dumps({**settings.SETTINGS, "bubbles": True}), encoding="utf-8")
        held = self.httpd.hub.settings
        with held.lock:
            held.current = settings.Settings(file).get()
        self.sent = False
        self.present()
        self.mark("s2", time.time())
        self.sight()
        self.beside(self.live_rows)

    def present(self) -> None:
        payload = {"written": time.time(), "sessions": {"s1": {"name": "Skills session", "running": True}, "s2": {"name": "Stage", "running": True}}}
        written = self.state / f".{SNAPSHOT}.e2e"
        written.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(written, self.state / SNAPSHOT)

    def live_rows(self) -> None:
        self.present()
        if self.sent or self.httpd.hub.settings.get()["agents"].get("s2", {}).get("bubbles") is not False:
            return
        self.sent = True
        now = time.time()
        rows = [
            {"ts": now, "from": "Stage", "to": [], "text": "stage rotates the keys quietly", "class": "security", "v": 2},
            {"ts": now + 0.001, "from": "Skills session", "to": [], "text": "skills rotates the keys aloud", "class": "security", "v": 2},
        ]
        with (self.council / "news.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(self.jsonl(rows))

    def test_chromium_opens_every_agent_from_its_face_or_name_and_switches_its_own_bubbles(self):
        steps = [
            {"width": WIDTH, "height": HEIGHT, "url": f"{self.base}?agents#stream", "wait": 1200, "probe": fill(STREAM), "shot": str(OUT / "chromium-stream.png")},
            {"width": WIDTH, "height": HEIGHT, "url": None, "wait": 0, "probe": fill(TASKS), "shot": str(OUT / "chromium-tasks.png")},
            {"width": WIDTH, "height": HEIGHT, "url": None, "wait": 0, "probe": fill(RADIO), "shot": str(OUT / "chromium-radio.png")},
            {"width": WIDTH, "height": HEIGHT, "url": None, "wait": 0, "probe": fill(BUBBLES), "shot": str(OUT / "chromium-bubbles.png")},
        ]
        data = self.drive(steps, self.authenticator(), init=SILENT)
        (OUT / "chromium-agent-settings.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        stream, tasks, radio, bubbles = data["results"]
        switches = [["sound", "true", "Sound"], ["aloud", "true", "Read aloud"], ["bubbles", "true", "Bubbles"]]
        for name, found in (("stream", stream), ("tasks", tasks), ("radio", radio)):
            with self.subTest(screen=name):
                self.assertNotIn("error", found, found)
                self.assertGreater(found["audit"]["count"], 0, found)
                self.assertEqual(found["audit"]["loose"], [], found)
        for found in (stream["entry"], stream["waiting"], stream["reader"], tasks["worker"], radio["sender"]):
            self.assertIsNotNone(found, data["results"])
            self.assertEqual(found["switches"], switches, found)
        self.assertNotIn("error", bubbles, bubbles)
        self.assertEqual((bubbles["agent"], bubbles["pressed"], bubbles["stored"]), ("s2", True, {"sound": True, "aloud": True, "bubbles": False}), bubbles)
        self.assertEqual(bubbles["other"], "s1", bubbles)
        self.assertNotIn("s2", bubbles["seen"], bubbles)
        self.assertIsNone(bubbles["back"], bubbles)
        self.assertEqual(self.httpd.hub.settings.get()["agents"], {})


if __name__ == "__main__":
    unittest.main()
