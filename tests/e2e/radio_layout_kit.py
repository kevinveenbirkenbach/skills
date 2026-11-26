from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest import mock

import hub_e2e_kit as base
from hub_case import HubCase
from kvb_orchestrator import receipts
from kvb_orchestrator.presence import SNAPSHOT
from kvb_orchestrator.view import RADIO_WINDOW

OUT = Path(os.environ.get("E2E_OUT", "/tmp/radio-layout-shots"))
LIVE = "f000000000000001"
SILENCE = "f000000000000002"
NEW_ALARM = "disk full again: the cleanup freed too little"
NAMES = ["Skills", "Stage", "Docs", "Atlas", "Beacon", "Comet", "Delta", "Echo", "Falcon", "Harbor"]
SESSIONS = {f"s{index}": name for index, name in enumerate(NAMES, start=1)}
LONG = "Disk at ninety percent on the build host: " + "the gate keeps the swarm waiting while the cache, the images and the logs keep growing; " * 4
FILLERS = 24
WIDTHS = (*base.WIDTHS, (960, 800))
NARROW = (390, 960)
STAGE_SHARE = 0.12
BANDS = ((1280, 720), (976, 744), (768, 976))
SHORT = ((800, 600), (1024, 600), (1280, 600), (1366, 657))
ABOVE = ((800, 976), (960, 976), (976, 744), (1024, 744), (1366, 720))
LAPTOPS = ((1280, 720), (1366, 768), (1440, 900), (1536, 864), (1920, 1080), (1024, 768), (1680, 1050), (820, 1180), (768, 1024), *ABOVE, *SHORT)
DUPS = ("dup first", "dup second")
VIEWS = ("#stream", "#agents/orbit")
STATES = ("idle", "stations", "voice", "speech", "mayday", "mayday-long")
ALARMS = {
    "mayday": "disk full",
    "mayday-long": "disk full on the build host: every agent pauses its writing steps until the operator frees space under /var/lib/docker and confirms the cleanup "
    "on the radio; the gate queue stays frozen, the deploy of the production worktree waits, and every held test run restarts after the clear of this mayday",
}
BANNER_MAX = 48
FOCUS_SIZES = ((1366, 768), (390, 844))
MAIN_SHARE = 0.54
PLAY_MIN = {"BUTTON": (24, 24), "AUDIO": (200, 30)}
POPOVER_SIZES = ((1366, 768), (1280, 720), (390, 844))
HOME_RADIO = [{"kind": "panel", "id": "radio-device", "w": 6, "h": 6}, {"kind": "panel", "id": "radio", "w": 12, "h": 7}]
STREAMS = [{"name": f"Station {index}", "url": f"https://radio.example/{index}.mp3", "from": "00:00", "to": "24:00", "days": list(range(7)), "on": False, "via": []} for index in (1, 2, 3)]
PARTS = ["radio", "radio-device", "radio-speak", "radio-log"]
DEFAULTS = {"radio": [12, 7], "radio-device": [6, 6], "radio-speak": [6, 5], "radio-log": [6, 5]}
SIZES = {"radio": [12, 9], "radio-device": [5, 7], "radio-speak": [7, 6], "radio-log": [8, 4]}
LISTED = {"radio-log"}
SCROLLER = {"radio": "radio-log", "radio-device": None, "radio-speak": None, "radio-log": "radio-log"}
PROBES = """
  const transitions = window.e2eTransitions || (window.e2eTransitions = []);
  if (document.startViewTransition && !transitions.wrapped) {
    const start = document.startViewTransition.bind(document);
    document.startViewTransition = (update) => {
      const run = start(update);
      transitions.push(run);
      return run;
    };
    transitions.wrapped = true;
  }
  const settle = () => Promise.all(transitions.map((run) => run.finished.catch(() => null)));
  const press = (node) => {
    node.dispatchEvent(new MouseEvent("mousedown", {bubbles: true, cancelable: true, view: window}));
    if (node.matches('button, input, select, textarea, summary, a[href], [tabindex]')) {
      node.focus();
    } else if (document.activeElement) {
      document.activeElement.blur();
    }
    node.dispatchEvent(new MouseEvent("mouseup", {bubbles: true, cancelable: true, view: window}));
    node.click();
  };
  const box = (node) => node.getBoundingClientRect();
  const pinByMenu = async (owner) => {
    const edge = box(owner);
    owner.dispatchEvent(new MouseEvent("contextmenu", {bubbles: true, cancelable: true, button: 2, clientX: Math.round(edge.left + 4), clientY: Math.round(edge.top + 4)}));
    const menu = await until(() => document.querySelector(".ctx-menu:not([hidden])"), 3000);
    const item = menu ? all('[role="group"][data-scope="element"] [role="menuitem"]', menu).find((node) => text(node.querySelector(".ctx-label")) === "Pin to Home") : null;
    if (item) {
      item.click();
    } else if (menu) {
      menu.dispatchEvent(new KeyboardEvent("keydown", {key: "Escape", bubbles: true, cancelable: true}));
    }
    await sleep(250);
    const target = Panels.targetOf(owner);
    return String((ViewStore.get("home.pins") || []).some((pin) => pin.kind === target.kind && pin.id === target.id));
  };
  const openSpot = async () => {
    await until(() => typeof Nav === "object" && document.getElementById("radio-spot"), 8000);
    const toggle = document.getElementById("radio-open");
    if (toggle.getAttribute("aria-expanded") !== "true") {
      toggle.click();
      await sleep(300);
    }
    return document.getElementById("radio-spot");
  };
  const closeSpot = async () => {
    const toggle = document.getElementById("radio-open");
    if (toggle.getAttribute("aria-expanded") === "true") {
      toggle.click();
      await sleep(200);
    }
  };
  const longRow = (root) => all(".radio-row", root).find((item) => text(item.querySelector(".radio-line")).startsWith("Disk at ninety"));
  const popup = () => document.getElementById("popup");
  const openRow = async (row) => {
    row.querySelector(".radio-pick").click();
    return until(() => popup().open && popup().querySelector(".radio-full") ? popup() : null, 4000);
  };
  const shown = (node) => node.getClientRects().length > 0 && !node.closest("details:not([open]) > :not(summary)");
  const scrolls = (node) => {
    const look = getComputedStyle(node);
    return (node.scrollHeight > node.clientHeight + 1 && ["auto", "scroll"].includes(look.overflowY)) || (node.scrollWidth > node.clientWidth + 1 && ["auto", "scroll"].includes(look.overflowX));
  };
  const scrollersIn = (root) => [root, ...all("*", root)].filter((node) => node instanceof HTMLElement && node.tagName !== "SELECT" && node.tagName !== "TEXTAREA" && shown(node) && scrolls(node)).map((node) => [...node.classList].at(-1) || node.tagName);
  const tile = (id) => document.querySelector(`#main .home-tile[data-pin="panel:${id}"]`);
  const pick = (root) => {
    const [channel, recipient] = all("select", root.querySelector("form.composer"));
    return {channel: channel.value, recipient: recipient.value, toShown: !recipient.closest("label").hidden, focused: document.activeElement === root.querySelector("form.composer textarea")};
  };
"""
LOADS = """
  const loads = {count: 0};
  const send = window.fetch.bind(window);
  window.fetch = async (path, init) => {
    const response = await send(path, init);
    if (String(path).startsWith("/api/state")) {
      const json = response.json.bind(response);
      response.json = () => json().then((value) => {
        loads.count += 1;
        return value;
      });
    }
    return response;
  };
  const loaded = async (more, ms) => {
    const goal = loads.count + more;
    const done = await until(() => loads.count >= goal, ms);
    await sleep(300);
    return Boolean(done);
  };
"""


def columns(width: int, height: int) -> bool:
    return any(width >= low and height >= tall for low, tall in BANDS)


def probe(template: str) -> str:
    return (template.replace("@HELPERS@", base.HELPERS).replace("@PROBES@", PROBES).replace("@LOADS@", LOADS).replace("@SPEAKING@", base.SPEAKING).replace("@PARTS@", json.dumps(PARTS))
            .replace("@SIZES@", json.dumps(SIZES)).replace("@LIVE@", LIVE).replace("@SILENCE@", SILENCE).replace("@DUPS@", json.dumps(DUPS)).replace("@MAIN@", str(MAIN_SHARE)))


class RadioLayoutCase(HubCase):
    drive = base.OrchestratorE2ECase.drive
    beside = base.OrchestratorE2ECase.beside
    authenticator = base.OrchestratorE2ECase.authenticator
    speaks = base.OrchestratorE2ECase.speaks

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        now = time.time()
        self.claim("s1", "Skills session")
        rows = [{"ts": now - 1200 + index * 30, "from": NAMES[index % len(NAMES)], "to": [], "text": f"status line {index}: build {index} green", "class": "newsletter", "v": 2} for index in range(FILLERS)]
        self.call = now - 400
        self.long = now - 300
        rows += [
            {"ts": self.call, "from": "Skills", "to": ["Stage", "Docs"], "text": "gate red on main", "class": "call", "v": 2},
            {"ts": self.call + 5, "from": "Stage", "to": ["Skills"], "text": "gate red on main", "class": "receipt", "v": 2, "call": self.call},
            {"ts": self.long, "from": "Stage", "to": [], "text": LONG, "class": "broadcast", "v": 2},
        ]
        self.write_council({"news.jsonl": self.jsonl(rows)})
        for sid in SESSIONS:
            self.mark(sid, now - 100)
        self.sessions()
        self.beside(self.sessions)
        self.httpd.hub.receipt_reads.times[("s5", self.long)] = self.long + 40
        self.sight()
        self.live = 0
        hub = self.httpd.hub
        heard = hub.voice_notes.get

        def get(note_id: str) -> dict:
            if note_id == SILENCE:
                self.silence(NEW_ALARM)
                return {"id": note_id, "status": "done", "text": "", "error": "", "seconds": None, "created_ts": None}
            if note_id != LIVE:
                return heard(note_id)
            self.live += 1
            row = {"ts": time.time(), "from": "Docs", "to": [], "text": f"live row {self.live} for Home", "class": "broadcast", "v": 2}
            with (self.council / "news.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(self.jsonl([row]))
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

    def silence(self, words: str) -> None:
        now = time.time()
        self.write_council({"radio-silence.json": {"since": now - 60, "until": now + 3600, "by": "Docs", "text": words}})

    def stations(self) -> None:
        hub = self.httpd.hub
        hub.settings.put({**hub.settings.get(), "streams": STREAMS}, hub.settings.get())
