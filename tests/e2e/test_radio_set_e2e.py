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
from hub_engines import log_rows
from hub_support import iso
from kvb_orchestrator import errors, phrasing, speechgate

OUT = Path(os.environ.get("E2E_OUT", "/tmp/radio-set-shots"))
WORD = phrasing.procedure("security")
CUES = {"low": "c000000000000001", "high": "c000000000000002", "hold": "c000000000000003", "free": "c000000000000004", "alarm": "a000000000000001", "call": "a000000000000002", "dark": "d000000000000001", "light": "d000000000000002"}
THRESHOLDS = {1920: 60, 1366: 70, 390: 80}
FIXTURE = [
    {"ago": 600, "from": "Operator", "to": ["Stage"], "class": "post", "text": "rebase please"},
    {"ago": 500, "from": "Stage", "to": ["Operator"], "class": "call", "text": "gate red on main"},
    {"ago": 400, "from": "Docs", "to": [], "class": "newsletter", "text": "docs are green"},
    {"ago": 350, "from": "Stage", "to": ["Skills session"], "class": "post", "text": "rebase done\nsecond line of the full message"},
    {"ago": 320, "from": "Operator", "to": [], "class": "broadcast", "text": "deploy now"},
]
SPY = """() => {
  window.e2eViolations = [];
  document.addEventListener("securitypolicyviolation", (event) => window.e2eViolations.push(`${event.violatedDirective} ${event.blockedURI}`));
  const log = window.e2eAudio = {tts: [], requests: [], filters: [], starts: [], oscillators: 0, levels: [], passkeys: 0};
  const fetched = window.fetch.bind(window);
  window.fetch = (input, init) => {
    const url = String(input && input.url ? input.url : input);
    const entry = url.includes("/api/tts") ? {body: JSON.parse(init.body), status: 0} : null;
    log.requests.push(url);
    if (entry) {
      log.tts.push(entry);
    }
    return fetched(input, init).then((response) => {
      if (entry) {
        entry.status = response.status;
      }
      return response;
    });
  };
  const filter = AudioContext.prototype.createBiquadFilter;
  AudioContext.prototype.createBiquadFilter = function created() {
    const node = filter.call(this);
    log.filters.push(node);
    return node;
  };
  const start = AudioBufferSourceNode.prototype.start;
  AudioBufferSourceNode.prototype.start = function started(...args) {
    log.starts.push({seconds: this.buffer ? Math.round(this.buffer.duration * 1000) / 1000 : null, channels: this.buffer ? this.buffer.numberOfChannels : null});
    return start.apply(this, args);
  };
  const tone = OscillatorNode.prototype.start;
  OscillatorNode.prototype.start = function toned(...args) {
    log.oscillators += 1;
    return tone.apply(this, args);
  };
  const level = AudioParam.prototype.setValueAtTime;
  AudioParam.prototype.setValueAtTime = function levelled(value, at) {
    log.levels.push(Math.round(value * 1000) / 1000);
    return level.call(this, value, at);
  };
  if (navigator.credentials) {
    const get = navigator.credentials.get.bind(navigator.credentials);
    navigator.credentials.get = (options) => {
      log.passkeys += 1;
      return get(options);
    };
  }
}"""
RADIO = """
  const spotToggle = document.getElementById("radio-open");
  await until(() => typeof Nav === "object" && document.getElementById("radio-spot"), 8000);
  if (spotToggle.getAttribute("aria-expanded") !== "true") {
    spotToggle.click();
    await sleep(300);
  }
  const spot = document.getElementById("radio-spot");
  const audio = () => window.e2eAudio;
  const cue = (name) => fetch(`/api/voice/${{@CUES@}[name]}`, {cache: "no-store"});
  const refreshNow = () => window.dispatchEvent(new Event("focus"));
  const field = (name) => text(spot.querySelector(`.radio-display [data-field="${name}"]`));
  const lamp = () => spot.querySelector(".radio-lamp");
  const fits = () => ({page: document.documentElement.scrollWidth <= innerWidth + 1, panel: spot.scrollWidth <= spot.clientWidth + 1});
  const press = (mode) => spot.querySelector(`.radio-modes button[data-mode="${mode}"]`).click();
  const pressed = () => all(".radio-modes button", spot).filter((button) => button.getAttribute("aria-pressed") === "true").map((button) => button.dataset.mode);
  const mark = () => ({tts: audio().tts.length, starts: audio().starts.length, filters: audio().filters.length, oscillators: audio().oscillators, levels: audio().levels.length, requests: audio().requests.length});
  const since = (at) => ({
    tts: audio().tts.slice(at.tts).map((entry) => [entry.body.text, entry.status]),
    starts: audio().starts.slice(at.starts),
    filters: audio().filters.slice(at.filters).map((node) => [node.type, node.frequency.value]),
    oscillators: audio().oscillators - at.oscillators,
    levels: audio().levels.slice(at.levels),
    requests: audio().requests.slice(at.requests).filter((url) => !/\\/api\\/(state|stream|events|tts|tree|subagents|voice\\/[a-d]0)/.test(url)),
  });
  const cpuShown = async (label) => {
    refreshNow();
    return Boolean(await until(() => field("cpu") === label, 12000));
  };
  const transmit = async (names, count) => {
    const at = mark();
    for (const name of names) {
      await cue(name);
    }
    refreshNow();
    await until(() => audio().tts.length >= at.tts + count && audio().tts.slice(at.tts).every((entry) => entry.status), 20000);
    await sleep(1500);
    await until(() => lamp().dataset.lit === "false", 4000);
    return since(at);
  };
  const tabs = () => Object.fromEntries(all('.radio-tabs [role="tab"]', spot).map((tab) => [tab.dataset.tab, Number(text(tab.querySelector(".count")))]));
  const selected = () => (spot.querySelector('.radio-tabs [aria-selected="true"]') || {dataset: {}}).dataset.tab || null;
  const rows = () => all(".radio-row", spot).map((item) => ({dir: item.dataset.dir, cls: item.dataset.class, route: text(item.querySelector(".radio-route")), line: text(item.querySelector(".radio-line")), ts: Number(item.querySelector("time").dataset.ts)}));
  const chip = async (name, value) => {
    const select = spot.querySelector(`.chip-select[data-chip="${name}"] select`);
    select.value = value;
    select.dispatchEvent(new Event("change", {bubbles: true}));
    await sleep(150);
  };
  const chips = () => Object.fromEntries(all(".chip-select", spot).map((box) => [box.dataset.chip, box.querySelector("select").value]));
  const search = () => spot.querySelector('.radio-filters input[type="search"]');
  const tab = async (id) => {
    spot.querySelector(`.radio-tabs [data-tab="${id}"]`).click();
    await sleep(150);
  };
  const unlabelled = () => all(".radio-face :is(button, select, input), #radio-gear :is(button, select, input), .radio-logbox :is(button, select, input), .radio-station button", spot).filter((node) => node.getClientRects().length && !node.getAttribute("aria-label") && !text(node)).length;
""".replace("@CUES@", ", ".join(f'"{name}": "{ident}"' for name, ident in CUES.items()))
FACE = """(async () => {@HELPERS@@RADIO@
  await cpuShown("CPU 10 %");
  const display = {lamp: [text(lamp()), lamp().dataset.lit], cls: field("class"), mode: field("mode"), cpu: field("cpu"), title: spot.querySelector('[data-field="cpu"]').title};
  const modes = all(".radio-modes button", spot).map((button) => [text(button), button.getAttribute("aria-pressed"), Boolean(button.title && button.getAttribute("aria-label")), Boolean(button.querySelector("svg.bi"))]);
  const knobs = all(".radio-knobs input[type=range]", spot).map((input) => [input.getAttribute("aria-label"), input.min, input.max, input.step, input.value]);
  const toneToggles = all(".radio-knobs button[aria-pressed]", spot).map((button) => [button.getAttribute("aria-label"), button.getAttribute("aria-pressed")]);
  const labels = all(".radio-knobs .knob-row", spot).filter((row) => row.querySelector(".knob-label")).map((row) => {
    const label = row.querySelector(".knob-label");
    return {text: text(label), title: label.title, whole: label.scrollWidth <= label.clientWidth + 1, row: row.scrollWidth <= row.clientWidth + 1};
  });
  const gear = all(".spot-head button", spot).find((button) => name(button) === "Read aloud");
  gear.click();
  await sleep(200);
  const groups = Object.fromEntries(all("#radio-gear .chips", spot).map((group) => [group.getAttribute("aria-label"), all(".chip", group).map((chipNode) => [text(chipNode), chipNode.getAttribute("aria-pressed"), chipNode.disabled])]));
  const stationsHead = text(spot.querySelector(".radio-station .group-title"));
  const ptt = spot.querySelector('form.composer button[type="submit"]');
  const pageFits = fits();
  document.getElementById("settings-open").click();
  await until(() => document.querySelector("#sheet .sheet-box"), 4000);
  const sections = all("#sheet .settings h3").map(text);
  all("#sheet .sheet-head button").find((button) => name(button) === "Close").click();
  await sleep(200);
  all(".radio-station button", spot).find((button) => text(button) === "Edit stations").click();
  await until(() => document.querySelector("#sheet .sheet-box"), 4000);
  const stations = [document.querySelector("#sheet .sheet-box").getAttribute("aria-label"), all("#sheet .settings h3").map(text)];
  all("#sheet .sheet-head button").find((button) => name(button) === "Close").click();
  await sleep(200);
  return {display, modes, knobs, toneToggles, labels, groups, stationsHead, ptt: [text(ptt), ptt.title], sections, stations, fits: pageFits, unlabelled: unlabelled(), palette: getComputedStyle(document.documentElement).getPropertyValue("--panel").trim(), violations: window.e2eViolations};
})()"""
LOG = """(async () => {@HELPERS@@RADIO@
  await until(() => rows().length, 8000);
  const counts = tabs();
  await tab("sent");
  const sent = rows();
  await tab("received");
  const received = rows();
  await tab("all");
  const every = rows();
  await chip("class", "post");
  const posts = rows();
  await chip("from", "Stage");
  const fromStage = rows();
  search().value = "second";
  search().dispatchEvent(new Event("input", {bubbles: true}));
  await sleep(150);
  const narrowed = rows();
  search().value = "please";
  search().dispatchEvent(new Event("input", {bubbles: true}));
  await sleep(150);
  const none = [rows().length, text(spot.querySelector(".radio-log li.muted"))];
  all(".radio-filters button", spot).find((button) => name(button) === "Clear filters").click();
  await sleep(150);
  const clearedChips = [chips(), search().value, rows().length];
  const summary = spot.querySelector(".radio-row summary");
  summary.click();
  await sleep(150);
  const opened = [summary.parentElement.open, text(summary.parentElement.querySelector(".radio-full"))];
  await tab("received");
  await chip("agent", "Stage");
  search().value = "gate";
  search().dispatchEvent(new Event("input", {bubbles: true}));
  await sleep(200);
  spot.querySelector(".radio-logbox").scrollIntoView({block: "start"});
  await sleep(200);
  return {counts, sent, received, every, posts, fromStage, narrowed, none, clearedChips, opened, kept: rows(), fits: fits()};
})()"""
LOG_KEPT = """(async () => {@HELPERS@@RADIO@
  await until(() => spot.querySelector(".radio-tabs [role=tab]"), 8000);
  await sleep(300);
  const kept = {tab: selected(), chips: chips(), q: search().value, rows: rows()};
  all(".radio-filters button", spot).find((button) => name(button) === "Clear filters").click();
  await tab("all");
  const list = spot.querySelector(".radio-log");
  list.scrollIntoView({block: "start"});
  await sleep(300);
  const top = Math.max(list.getBoundingClientRect().top, spot.getBoundingClientRect().top, document.querySelector(".head").getBoundingClientRect().bottom);
  const bottom = Math.min(list.getBoundingClientRect().bottom, spot.getBoundingClientRect().bottom, innerHeight);
  const shown = all(".radio-row", list).filter((item) => item.getBoundingClientRect().top >= top - 1 && item.getBoundingClientRect().bottom <= bottom + 1).length;
  return {...kept, shown, total: all(".radio-row", list).length, fits: fits()};
})()"""
SOUND = """(async () => {@HELPERS@@RADIO@
  const found = {};
  press("auto");
  await cue("free");
  await cue("low");
  found.low = await cpuShown("CPU 10 %");
  found.auto = await transmit(["alarm"], 2);
  await cue("hold");
  found.held = await transmit(["alarm"], 2);
  const heldCount = audio().tts.length;
  await sleep(2500);
  found.retries = audio().tts.length - heldCount;
  await cue("free");
  press("quiet");
  found.quiet = await transmit(["alarm", "call"], 1);
  press("silence");
  found.silence = await transmit(["alarm", "call"], 1);
  found.pressed = pressed();
  found.mode = field("mode");
  return found;
})()"""
SOUND_KEPT = """(async () => {@HELPERS@@RADIO@
  await sleep(300);
  const kept = [pressed(), field("mode")];
  press("auto");
  return {kept, pressed: pressed()};
})()"""
BURST = """(async () => {@HELPERS@@RADIO@
  const squelch = all(".radio-knobs input[type=range]", spot).find((input) => input.getAttribute("aria-label") === "Squelch");
  squelch.value = "0.6";
  squelch.dispatchEvent(new Event("input", {bubbles: true}));
  await cue("high");
  const high = await cpuShown("CPU 95 %");
  const at = mark();
  await cue("alarm");
  refreshNow();
  const lit = Boolean(await until(() => lamp().dataset.lit === "true" && audio().filters.length > at.filters, 20000));
  return {high, lit, lamp: [text(lamp()), lamp().getAttribute("aria-label")], open: spot.querySelector('[data-field="cpu"]').dataset.open, heard: since(at)};
})()"""
BURST_DONE = """(async () => {@HELPERS@@RADIO@
  await until(() => lamp().dataset.lit === "false", 6000);
  await sleep(800);
  const squelch = all(".radio-knobs input[type=range]", spot).find((input) => input.getAttribute("aria-label") === "Squelch");
  squelch.value = "1";
  squelch.dispatchEvent(new Event("input", {bubbles: true}));
  await cue("low");
  return {tts: audio().tts.slice(-2).map((entry) => [entry.body.text, entry.status]), low: await cpuShown("CPU 10 %")};
})()"""
THRESHOLD = """(async () => {@HELPERS@@RADIO@
  const knob = all(".radio-knobs input[type=range]", spot).find((input) => input.getAttribute("aria-label") === "Threshold");
  const before = [knob.value, audio().passkeys];
  knob.value = "@VALUE@";
  knob.dispatchEvent(new Event("input", {bubbles: true}));
  knob.dispatchEvent(new Event("change", {bubbles: true}));
  await until(() => all("#toasts .toast").length, 15000);
  await sleep(600);
  refreshNow();
  await sleep(800);
  await cue("dark");
  refreshNow();
  const light = getComputedStyle(document.documentElement).getPropertyValue("--panel").trim();
  const dark = await until(() => {
    const now = getComputedStyle(document.documentElement).getPropertyValue("--panel").trim();
    return now !== light ? now : null;
  }, 12000);
  await sleep(400);
  return {before, after: [knob.value, audio().passkeys], shown: text(knob.parentElement.querySelector(".knob-value")), title: spot.querySelector('[data-field="cpu"]').title, toasts: all("#toasts .toast strong").map(text), dark: [light, dark], fits: fits()};
})()"""
LIGHT = """(async () => {@HELPERS@@RADIO@
  await cue("light");
  refreshNow();
  await sleep(1500);
  return {violations: window.e2eViolations};
})()"""


def probe(template: str) -> str:
    return template.replace("@HELPERS@", base.HELPERS).replace("@RADIO@", RADIO)


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestRadioSet(HubCase):
    drive = base.TestOrchestratorE2E.drive
    authenticator = base.TestOrchestratorE2E.authenticator
    beside = base.TestOrchestratorE2E.beside

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
                self.assertEqual([mode_[:2] for mode_ in face["modes"]], [["Auto", "true"], ["Quiet", "false"], ["Silence", "false"]])
                self.assertTrue(all(mode_[2] and mode_[3] for mode_ in face["modes"]), face["modes"])
                self.assertEqual([knob[0] for knob in face["knobs"]], ["MAYDAY / PAN-PAN", "Reviews, asks, decisions", "Post and calls to you", "All radio", "Squelch", "Threshold"])
                self.assertEqual(face["knobs"][-1][1:], ["30", "90", "10", "50" if index == 0 or not signed else str(THRESHOLDS[base.WIDTHS[index - 1][0]])])
                self.assertEqual(len(face["toneToggles"]), 4)
                self.assertEqual([label["text"] for label in face["labels"]], [knob[0] for knob in face["knobs"]])
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
                    self.assertIn(f"below {value} %", threshold["title"])
                else:
                    self.assertEqual(threshold["after"], [threshold["before"][0], threshold["before"][1]], threshold)
                    self.assertIn("Settings: not signed", threshold["toasts"])
                self.assertTrue(threshold["dark"][1] and threshold["dark"][0] != threshold["dark"][1], threshold)
                self.assertEqual(threshold["fits"], {"page": True, "panel": True})
                self.assertEqual([seen for seen in light["violations"] if not seen.endswith("/favicon.ico")], [])
        words = [row for row in log_rows(self.engines.scratch / "piper.jsonl") if row["text"] == f"{WORD}\n"]
        self.assertEqual(len(words), 1, "the procedure word line of one voice renders once and then hits the cache")
        self.assertEqual(self.httpd.hub.settings.get()["speech"]["threshold"], THRESHOLDS[390] if signed else 50)

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
