from __future__ import annotations

import os
from pathlib import Path

import hub_e2e_kit as base
from kvb_orchestrator import phrasing

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
    requests: audio().requests.slice(at.requests).filter((url) => !/\\/api\\/(state|stream|events|tts|tree|subagents|match\\/closed|voice\\/[a-d]0)/.test(url)),
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
  const rows = () => all(".radio-row:not([data-vanishing])", spot).map((item) => ({dir: item.dataset.dir, cls: item.dataset.class, route: text(item.querySelector(".radio-route")), line: text(item.querySelector(".radio-line")), ts: Number(item.querySelector("time").dataset.ts)}));
  const chip = async (name, value) => {
    const select = spot.querySelector(`.chip-select[data-chip="${name}"] select`);
    select.value = value;
    select.dispatchEvent(new Event("change", {bubbles: true}));
    await sleep(150);
  };
  const chips = () => Object.fromEntries(all(".chip-select", spot).map((box) => [box.dataset.chip, box.querySelector("select").value]));
  const search = () => spot.querySelector('.radio-logbox input[type="search"]');
  const tab = async (id) => {
    spot.querySelector(`.radio-tabs [data-tab="${id}"]`).click();
    await sleep(150);
  };
  const modeMenu = async (mode, open) => {
    const button = spot.querySelector(`.radio-modes button[data-mode="${mode}"]`);
    if ((button.getAttribute("aria-expanded") === "true") !== open) {
      button.click();
      await sleep(200);
    }
  };
  const unlabelled = () => all(".radio-face :is(button, select, input), .radio-logbox :is(button, select, input), .radio-station button, form.composer :is(button, summary)", spot).filter((node) => node.getClientRects().length && !node.getAttribute("aria-label") && !text(node)).length;
""".replace("@CUES@", ", ".join(f'"{name}": "{ident}"' for name, ident in CUES.items()))
FACE = """(async () => {@HELPERS@@RADIO@
  await cpuShown("CPU 10 %");
  const display = {lamp: [text(lamp()), lamp().dataset.lit], cls: field("class"), mode: field("mode"), cpu: field("cpu"), title: spot.querySelector('[data-field="cpu"]').title};
  const modes = all(".radio-modes button", spot).map((button) => [text(button).replace("▾", ""), button.getAttribute("aria-pressed"), Boolean(button.title && button.getAttribute("aria-label")), Boolean(button.querySelector("svg.bi"))]);
  const knobs = all(".radio-knobs input[type=range]", spot).map((input) => [input.getAttribute("aria-label"), input.min, input.max, input.step, input.value]);
  const toneToggles = all(".radio-knobs button[aria-pressed]", spot).map((button) => [button.getAttribute("aria-label"), button.getAttribute("aria-pressed")]);
  const labels = all(".radio-knobs .knob-row", spot).filter((row) => row.querySelector(".knob-label")).map((row) => {
    const label = row.querySelector(".knob-label");
    return {text: text(label), title: label.title, whole: label.scrollWidth <= label.clientWidth + 1, row: row.scrollWidth <= row.clientWidth + 1};
  });
  const testButtons = all(".radio-knobs .knob-row", spot).map((row) => (row.querySelector(".knob-test") ? name(row.querySelector(".knob-test")) : null));
  const atTest = mark();
  all(".radio-knobs .knob-test", spot).find((button) => name(button) === "Test Squelch").click();
  const squelchLit = Boolean(await until(() => lamp().dataset.lit === "true" && audio().filters.length > atTest.filters, 6000));
  const squelch = {lit: squelchLit, filters: since(atTest).filters.map(([type]) => type), tts: since(atTest).tts};
  await until(() => lamp().dataset.lit === "false", 6000);
  const bells = all(".radio-knobs .knob-toggle", spot).map((button) => [name(button), button.dataset.bell]);
  await modeMenu("auto", true);
  const caret = all(".radio-modes .mode-caret", spot).filter((node) => node.getClientRects().length).map((node) => node.closest("button").dataset.mode);
  const groups = Object.fromEntries(all(".radio-mode-menu .chips", spot).map((group) => [group.getAttribute("aria-label"), all(".chip", group).map((chipNode) => [text(chipNode), chipNode.getAttribute("aria-pressed"), chipNode.disabled])]));
  all('.radio-mode-menu .chips[aria-label="Fallback"] .chip', spot).find((chipNode) => text(chipNode) === "Hiss").click();
  await sleep(150);
  const menuFits = fits();
  await modeMenu("auto", false);
  const send = [name(spot.querySelector("form.composer .ptt-more")), spot.querySelector("form.composer .mayday-toggle").getAttribute("aria-pressed")];
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
  return {display, modes, knobs, toneToggles, testButtons, squelch, labels, bells, caret, groups, menuFits, send, stationsHead, ptt: [text(ptt), ptt.title], sections, stations, fits: pageFits, unlabelled: unlabelled(), palette: getComputedStyle(document.documentElement).getPropertyValue("--panel").trim(), violations: window.e2eViolations};
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
  const faceOf = () => spot.querySelector(".radio-row:not([data-vanishing]) .radio-sender");
  const sender = name(faceOf());
  faceOf().click();
  const switches = await until(() => document.getElementById("popup").open && document.querySelector("#popup .agent-settings"), 4000);
  const key = switches ? switches.dataset.agent : "";
  const stored = async () => ((await (await fetch("/api/state", {cache: "no-store"})).json()).settings.agents || {})[key] || null;
  const flip = async (what, want) => {
    switches.querySelector(`[data-switch="${what}"]`).click();
    await until(() => switches.querySelector(`[data-switch="${what}"]`).getAttribute("aria-pressed") === want, 4000);
  };
  await flip("sound", "false");
  await flip("aloud", "false");
  await until(() => faceOf().dataset.quiet === "true", 4000);
  const muted = [sender, faceOf().dataset.quiet, await stored(), Boolean(switches)];
  await flip("sound", "true");
  await flip("aloud", "true");
  await until(() => faceOf().dataset.quiet === "false", 4000);
  const unmuted = [faceOf().dataset.quiet, await stored()];
  all("#popup .popup-head button").find((button) => name(button) === "Close").click();
  await sleep(150);
  spot.querySelector(".radio-row:not([data-vanishing]) .radio-pick").click();
  const full = await until(() => document.getElementById("popup").open && document.querySelector("#popup .radio-full"), 4000);
  const opened = [document.getElementById("popup").open, text(full)];
  all("#popup .popup-head button").find((button) => name(button) === "Close").click();
  await sleep(150);
  await tab("received");
  await chip("agent", "Stage");
  search().value = "gate";
  search().dispatchEvent(new Event("input", {bubbles: true}));
  await sleep(200);
  spot.querySelector(".radio-logbox").scrollIntoView({block: "start"});
  await sleep(200);
  return {counts, sent, received, every, posts, fromStage, narrowed, none, clearedChips, muted, unmuted, opened, kept: rows(), fits: fits()};
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
  const shown = all(".radio-row:not([data-vanishing])", list).filter((item) => item.getBoundingClientRect().top >= top - 1 && item.getBoundingClientRect().bottom <= bottom + 1).length;
  return {...kept, shown, total: all(".radio-row:not([data-vanishing])", list).length, fits: fits()};
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
WPMS = {1920: 12, 1366: 25, 390: 40}
MORSE_SPY = """() => {
  (@SPY@)();
  const keyed = window.e2eMorse = [];
  const start = OscillatorNode.prototype.start;
  OscillatorNode.prototype.start = function keying(...args) {
    this.e2e = {frequency: this.frequency.value, type: this.type, start: args[0], stop: null, cut: false};
    keyed.push(this.e2e);
    return start.apply(this, args);
  };
  const stop = OscillatorNode.prototype.stop;
  OscillatorNode.prototype.stop = function unkeying(...args) {
    if (this.e2e && args[0] === undefined) {
      this.e2e.cut = true;
    } else if (this.e2e) {
      this.e2e.stop = args[0];
    }
    return stop.apply(this, args);
  };
}""".replace("@SPY@", SPY)
MORSE_KEYED = """
  const keyed = () => window.e2eMorse.filter((entry) => entry.stop !== null && entry.stop - entry.start > 1);
  const speed = () => spot.querySelector('.radio-mode-menu input[aria-label="Morse speed"]');
  const rate = () => text(spot.querySelector(".radio-mode-menu .morse-rate"));
"""
MORSE = """(async () => {@HELPERS@@RADIO@@KEYED@
  press("morse");
  await sleep(200);
  const mode = [pressed(), field("mode"), spot.querySelector('.radio-modes button[data-mode="morse"]').title];
  await modeMenu("morse", true);
  const before = [speed().min, speed().max, speed().step, speed().value, rate()];
  speed().value = "@WPM@";
  speed().dispatchEvent(new Event("input", {bubbles: true}));
  const dragged = rate();
  speed().dispatchEvent(new Event("change", {bubbles: true}));
  const toast = await until(() => all("#toasts .toast strong").map(text).includes("Morse speed saved"), 15000);
  await sleep(300);
  const saved = [speed().value, rate()];
  const menuFits = fits();
  await modeMenu("morse", false);
  const at = {tts: audio().tts.length, keyed: keyed().length};
  await cue("alarm");
  refreshNow();
  const playing = await until(() => keyed().length > at.keyed && lamp().dataset.lit === "true", 20000);
  const caption = spot.querySelector(".radio-caption");
  return {
    mode, before, dragged, toast: Boolean(toast), saved, menuFits, playing: Boolean(playing), keyed: keyed().slice(at.keyed), tts: audio().tts.length - at.tts,
    lamp: [text(lamp()), lamp().dataset.lit], caption: [caption.hidden, text(caption.querySelector("strong"))], fits: fits(),
  };
})()""".replace("@KEYED@", MORSE_KEYED)
MORSE_STOP = """(async () => {@HELPERS@@RADIO@@KEYED@
  const last = keyed()[keyed().length - 1];
  const caption = spot.querySelector(".radio-caption");
  const stop = all("button", caption).find((button) => name(button) === "Stop speaking");
  const before = [Boolean(stop), lamp().dataset.lit, last.cut];
  stop.click();
  const quiet = Boolean(await until(() => lamp().dataset.lit === "false", 2000));
  await sleep(500);
  return {before, cut: last.cut, quiet, hidden: caption.hidden, later: keyed().filter((entry) => !entry.cut).length};
})()""".replace("@KEYED@", MORSE_KEYED)


def probe(template: str) -> str:
    return template.replace("@HELPERS@", base.HELPERS).replace("@RADIO@", RADIO)
