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

import test_orchestrator_e2e as base
from hub_case import HubCase
from kvb_orchestrator import receipts
from kvb_orchestrator.presence import SNAPSHOT
from kvb_orchestrator.view import RADIO_WINDOW

OUT = Path(os.environ.get("E2E_OUT", "/tmp/radio-receipts-shots"))
ADVANCE = "e000000000000001"
RESET = "e000000000000002"
SESSIONS = {"s1": "Skills", "s2": "Stage", "s3": "Docs"}
PROBE = """(async () => {@HELPERS@
  const pills = (root) => all(".pill", root).filter((pill) => text(pill) === "Read").length;
  const readers = (node) => all(".reader", node).map((reader) => ({session: reader.dataset.session, acked: reader.dataset.acked, badge: Boolean(reader.querySelector(".ack svg")), title: reader.title, label: reader.getAttribute("aria-label")}));
  const fits = () => document.documentElement.scrollWidth <= innerWidth + 1;
  const found = {};
  await fetch("/api/voice/@RESET@", {cache: "no-store"});
  const radioChip = await until(() => document.querySelector('#main [aria-label="Categories"] button[aria-label="Radio"]'), 8000);
  radioChip.click();
  const call = await until(() => all("#main .entry.k-radio").find((entry) => entry.textContent.includes("gate red on main") && entry.querySelector(".reader")), 12000);
  if (!call) {
    return {error: text(document.getElementById("main"))};
  }
  const route = text(call.querySelector(".route"));
  found.stream = {route, sender: route.split("Skills").length - 1, readers: readers(call), read: pills(document.getElementById("main")), entries: all("#main .entry.k-radio").length, fits: fits()};
  call.scrollIntoView({block: "center"});
  await sleep(200);
  document.getElementById("radio-open").click();
  const spot = await until(() => document.getElementById("radio-spot"), 4000);
  spot.querySelector('.radio-tabs [data-tab="all"]').click();
  const row = await until(() => all(".radio-row[data-class=call]", spot).find((item) => item.textContent.includes("gate red on main")), 8000);
  found.log = {
    route: row ? text(row.querySelector(".radio-route")) : null, readers: readers(row), read: pills(spot), receipts: all(".radio-row[data-class=receipt]", spot).length,
    all: Number(text(spot.querySelector('.radio-tabs [data-tab="all"] .count'))), rows: all(".radio-row", spot).length,
  };
  spot.querySelector('.radio-tabs [data-tab="sent"]').click();
  const sentRow = await until(() => all('.radio-row[data-dir="sent"]', spot).find((item) => item.textContent.includes("ping")), 8000);
  found.sent = {readers: readers(sentRow), read: pills(spot), route: sentRow ? text(sentRow.querySelector(".radio-route")) : null};
  spot.querySelector('.radio-tabs [data-tab="all"]').click();
  document.getElementById("radio-open").click();
  await sleep(200);
  all("#main button.linkish").find((button) => button.title === "Open Skills").click();
  const bubble = await until(() => all("#popup .bubble").find((item) => item.textContent.includes("gate red on main")), 8000);
  const mine = await until(() => all("#popup .bubble.mine").find((item) => item.textContent.includes("ping")), 8000);
  found.agent = {readers: readers(bubble), mine: readers(mine), read: pills(document.getElementById("popup")), bubbles: all("#popup .bubble").length};
  document.querySelector("#popup").close();
  await sleep(200);
  const later = () => all("#main .entry.k-radio").find((entry) => entry.textContent.includes("which gate"));
  window.dispatchEvent(new Event("focus"));
  found.before = await until(() => (later() && !readers(later()).length ? [] : null), 20000);
  const loads = performance.getEntriesByType("navigation").length;
  await fetch("/api/voice/@ADVANCE@", {cache: "no-store"});
  window.dispatchEvent(new Event("focus"));
  const shown = await until(() => readers(later()).length ? readers(later()) : null, 20000);
  found.after = {readers: shown, reloaded: performance.getEntriesByType("navigation").length !== loads};
  call.scrollIntoView({block: "center"});
  await sleep(300);
  return found;
})()"""


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestRadioReceipts(HubCase):
    drive = base.TestOrchestratorE2E.drive
    authenticator = base.TestOrchestratorE2E.authenticator
    beside = base.TestOrchestratorE2E.beside

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        now = time.time()
        self.call = now - 300
        self.later = now - 100
        self.claim("s1", "Skills session")
        hub = self.httpd.hub
        ping = now - 200
        sent = hub.messages.add({"to": "Skills", "address": "Skills", "text": "ping", "upload": None, "class": "call", "voice": None, "created_ts": ping, "relay_ts": ping + 0.1})
        self.write_council({
            "news.jsonl": self.jsonl([
                {"ts": self.call, "from": "Skills", "to": ["Stage", "Docs"], "text": "gate red on main", "class": "call", "v": 2},
                {"ts": self.call + 5, "from": "Stage", "to": ["Skills"], "text": "gate red on main", "class": "receipt", "v": 2, "call": self.call},
                {"ts": ping + 0.1, "from": "Operator", "to": ["Skills"], "text": f"[kvb-orchestrator msg {sent['id']}] ping", "class": "call", "v": 2},
                {"ts": ping + 3, "from": "Skills", "to": ["Operator"], "text": "ping", "class": "receipt", "v": 2, "call": ping + 0.1},
                {"ts": self.later, "from": "Skills", "to": ["Stage"], "text": "which gate", "class": "call", "v": 2},
            ]),
        })
        self.mark("s1", ping + 3)
        self.mark("s2", self.call + 5)
        self.mark("s3", self.call + 5)
        self.sessions()
        self.beside(self.sessions)
        self.sight()
        heard = hub.voice_notes.get

        def advance() -> None:
            self.sight()
            self.mark("s2", time.time())
            self.sight()

        cues = {ADVANCE: advance, RESET: lambda: self.mark("s2", self.call + 5)}

        def get(note_id: str) -> dict:
            if note_id not in cues:
                return heard(note_id)
            cues[note_id]()
            return {"id": note_id, "status": "done", "text": "", "error": "", "seconds": None, "created_ts": None}

        patch = mock.patch.object(hub.voice_notes, "get", get)
        patch.start()
        self.addCleanup(patch.stop)

    def sessions(self) -> None:
        payload = {"written": time.time(), "sessions": {sid: {"name": name, "running": True} for sid, name in SESSIONS.items()}}
        written = self.state / f".{SNAPSHOT}.e2e"
        written.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(written, self.state / SNAPSHOT)

    def sight(self) -> None:
        hub = self.httpd.hub
        receipts.sighting_pass(hub.scripts.skills, hub.council, hub.receipt_names, hub.receipt_reads, hub.agent_sessions, RADIO_WINDOW, time.time())

    def mark(self, sid: str, ts: float) -> None:
        folder = self.council / receipts.SEEN
        folder.mkdir(parents=True, exist_ok=True)
        written = folder / f".{sid}.e2e"
        written.write_text(json.dumps({"radio": ts}), encoding="utf-8")
        os.replace(written, folder / f"{sid}.json")

    def steps(self, browser: str) -> list[dict]:
        steps = []
        for width, height in base.WIDTHS:
            steps.append({
                "width": width, "height": height, "url": f"http://localhost:{self.port}/?{width}#stream", "wait": 1200,
                "probe": PROBE.replace("@HELPERS@", base.HELPERS).replace("@ADVANCE@", ADVANCE).replace("@RESET@", RESET), "shot": str(OUT / f"{browser}-{width}-receipts.png"),
            })
        return steps

    def check(self, data: dict, browser: str) -> None:
        for (width, _), found in zip(base.WIDTHS, data["results"], strict=True):
            with self.subTest(browser=browser, width=width):
                self.assertNotIn("error", found, found)
                stream, log, agent = found["stream"], found["log"], found["agent"]
                self.assertEqual((stream["sender"], stream["route"]), (1, "Skills→ Stage, Docs"), stream)
                self.assertEqual([(reader["session"], reader["acked"], reader["badge"]) for reader in stream["readers"]], [("s2", "true", True), ("s3", "false", False)], stream)
                self.assertTrue(stream["readers"][0]["title"].startswith("Stage · read ") and stream["readers"][0]["title"].endswith(" · acknowledged"), stream)
                self.assertEqual(stream["readers"][1]["title"], "Docs · read", stream)
                self.assertEqual((stream["read"], stream["entries"], stream["fits"]), (0, 3, True), stream)
                self.assertEqual((log["route"], log["read"], log["receipts"], log["all"], log["rows"]), ("Skills → Stage, Docs", 0, 0, 3, 3), log)
                self.assertEqual([(reader["session"], reader["badge"]) for reader in log["readers"]], [("s2", True), ("s3", False)], log)
                self.assertEqual((found["sent"]["route"], found["sent"]["read"]), ("Operator → Skills", 0), found["sent"])
                self.assertEqual([(reader["session"], reader["acked"], reader["badge"]) for reader in found["sent"]["readers"]], [("s1", "true", True)], found["sent"])
                self.assertEqual([(reader["session"], reader["badge"]) for reader in agent["readers"]], [("s2", True), ("s3", False)], agent)
                self.assertEqual([(reader["session"], reader["acked"], reader["badge"]) for reader in agent["mine"]], [("s1", "true", True)], agent)
                self.assertEqual(agent["read"], 0, agent)
                self.assertEqual(found["before"], [], found)
                self.assertEqual([reader["session"] for reader in found["after"]["readers"]], ["s2"], found)
                self.assertTrue(found["after"]["readers"][0]["title"].startswith("Stage · read about "), found)
                self.assertFalse(found["after"]["reloaded"], found)

    def test_chromium_shows_readers_and_acks_on_messages_and_the_operators_own_call_with_no_read_entry_and_the_sender_once_at_three_widths(self):
        data = self.drive(self.steps("chromium"), self.authenticator())
        (OUT / "chromium-radio-receipts.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        self.check(data, "chromium")

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_shows_readers_and_acks_on_messages_and_the_operators_own_call_with_no_read_entry_and_the_sender_once_at_three_widths(self):
        data = self.drive(self.steps("firefox"), None, "bidi.mjs", os.environ.get("FIREFOX", "firefox"))
        (OUT / "firefox-radio-receipts.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        self.check(data, "firefox")


if __name__ == "__main__":
    unittest.main()
