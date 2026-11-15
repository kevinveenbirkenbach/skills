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
from kvb_orchestrator import receipts, skill_scripts
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
SIZES = {"radio": [12, 9], "radio-device": [5, 7], "radio-speak": [7, 6], "radio-log": [8, 6]}
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
  const ownStar = (owner) => all(".star", owner).find((node) => node.closest("[data-panel], [data-item]") === owner) || null;
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
  const shown = (node) => node.getClientRects().length > 0;
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
LAYOUT = """(async () => {@HELPERS@@PROBES@
  await ViewStore.update("home.pins", () => []);
  const spot = await openSpot();
  spot.querySelector('.radio-tabs [data-tab="all"]').click();
  await until(() => all(".radio-row .reader", spot).length > 20 && longRow(spot), 20000);
  await sleep(300);
  window.scrollTo(0, 0);
  const cardOf = (node) => (node.parentElement && node.parentElement.closest(".radio-card")) || spot;
  const wider = all("*", spot).filter((node) => node.tagName !== "OPTION" && shown(node) && box(node).width > 0).filter((node) => {
    const own = box(node);
    const card = box(cardOf(node));
    return own.left < card.left - 1 || own.right > card.right + 1;
  }).map((node) => `${node.tagName}.${node.getAttribute("class")}`);
  const list = spot.querySelector(".radio-log");
  const listLook = getComputedStyle(list);
  const rows = all(".radio-row", spot);
  const lineHeight = parseFloat(getComputedStyle(rows[0].querySelector(".radio-line")).lineHeight);
  const lines = rows.map((row) => {
    const line = row.querySelector(".radio-line");
    const look = getComputedStyle(line);
    return {height: Math.round(box(row).height), nowrap: look.whiteSpace === "nowrap", ellipsis: look.textOverflow === "ellipsis", flat: line.scrollHeight <= line.clientHeight + 1 && row.scrollHeight <= row.clientHeight + 1, fits: row.scrollWidth <= row.clientWidth + 1 && box(row).right <= box(list).right + 1, width: line.clientWidth};
  });
  const long = longRow(spot).querySelector(".radio-line");
  const avatars = rows.filter((row) => row.querySelector(".reader")).map((row) => {
    const edge = box(row);
    const line = box(row.querySelector(".radio-line"));
    const faces = all(".reader .avatar", row).filter(shown).map(box);
    return {
      total: Number((row.querySelector(".readers").getAttribute("aria-label").match(/\\d+/) || ["0"])[0]),
      count: faces.length,
      more: all(".readers-more", row).filter(shown).map(text),
      inside: faces.every((face) => face.left >= edge.left - 1 && face.right <= edge.right + 1 && face.top >= edge.top - 1 && face.bottom <= edge.bottom + 1),
      after: faces.every((face) => face.left >= line.right - 1),
      stacked: faces.slice(1).every((face, index) => face.left < faces[index].right),
      sliver: faces.length ? Math.min(...faces.map((face, index) => (index + 1 < faces.length ? faces[index + 1].left : face.right) - face.left)) : null,
    };
  });
  const [device, speak, history] = ["radio-device", "radio-speak", "radio-log"].map((id) => box(spot.querySelector(`[data-panel="${id}"]`)));
  const owners = [spot, ...all("[data-panel]", spot)];
  const controls = all('button, input, select, textarea, summary, [role="tab"]', spot).filter((node) => shown(node) && !node.classList.contains("star"));
  const overlap = (a, b) => Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left)) * Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top));
  const covered = owners.map(ownStar).filter(Boolean).flatMap((star) => controls.filter((node) => !node.contains(star) && overlap(box(star), box(node)) > 1).map((node) => `${star.title} over ${node.getAttribute("aria-label") || text(node)}`));
  const knobs = all(".radio-knobs .knob-row", spot).map((row) => Math.round(box(row.querySelector(".knob-label")).left));
  return {
    page: [document.documentElement.scrollWidth, innerWidth], tall: [document.documentElement.scrollHeight, innerHeight, Math.round(box(spot).height)],
    wider, scrollers: scrollersIn(spot),
    list: {overflowY: listLook.overflowY, scrollbar: [listLook.scrollbarWidth, listLook.scrollbarColor], scrolls: list.scrollHeight > list.clientHeight + 1},
    main: getComputedStyle(document.getElementById("main")).scrollbarColor,
    heights: [...new Set(lines.map((line) => line.height))], lineHeight, rows: rows.length,
    single: lines.every((line) => line.nowrap && line.ellipsis && line.flat && line.fits),
    narrowest: Math.min(...lines.map((line) => line.width)),
    long: [long.scrollWidth > long.clientWidth, getComputedStyle(long).textOverflow],
    avatars: {rows: avatars.length, most: Math.max(...avatars.map((row) => row.count)), inside: avatars.every((row) => row.inside), after: avatars.every((row) => row.after), stacked: avatars.filter((row) => row.count > 1).every((row) => row.stacked)},
    folds: avatars.map((row) => [row.total, row.count, row.more]),
    sliver: Math.min(...avatars.map((row) => row.sliver)),
    order: {stacked: device.bottom <= speak.top + 1 && speak.bottom <= history.top + 1 && Math.abs(device.left - speak.left) < 2, beside: device.right <= speak.left && speak.bottom <= history.top + 1 && Math.abs(speak.left - history.left) < 2},
    labels: [...new Set(knobs)].length,
    stars: owners.map((owner) => [owner.dataset.panel, Boolean(ownStar(owner))]), covered,
    stations: [Boolean(spot.querySelector("details.radio-station")), spot.querySelector("details.radio-station").open],
  };
})()"""
POPUP = """(async () => {@HELPERS@@PROBES@
  const spot = document.getElementById("radio-spot");
  const copied = [];
  navigator.clipboard.writeText = (value) => {
    copied.push(value);
    return Promise.resolve();
  };
  const row = longRow(spot);
  row.scrollIntoView({block: "center"});
  await sleep(200);
  const dialog = await openRow(row);
  if (!dialog) {
    return {error: "no popup"};
  }
  const card = dialog.querySelector(".popup-box");
  const fields = Object.fromEntries(all("dl.meta > div", card).map((pair) => [text(pair.querySelector("dt")), text(pair.querySelector("dd"))]));
  const readers = all(".popup-reader", card).map((item) => ({session: item.dataset.session, name: text(item.querySelector("strong")), time: text(item.querySelector(".muted")), acked: item.dataset.acked}));
  const copy = card.querySelector(".radio-copy");
  const said = card.querySelector(".radio-said");
  const heard = () => [copy.getAttribute("aria-label"), said ? text(said) : null];
  const region = said ? [said.getAttribute("role"), said.getAttribute("aria-live"), card.contains(said), shown(said) && box(said).width <= 1] : null;
  copy.click();
  const done = await until(() => (copy.dataset.copied === "true" ? text(copy) : null), 3000);
  const success = heard();
  const buttons = all(".radio-actions button", card).map(text);
  await until(() => copy.getAttribute("aria-label") === "Copy" && copy.dataset.copied === "", 4000);
  const reset = heard();
  navigator.clipboard.writeText = () => Promise.reject(new DOMException("Denied", "NotAllowedError"));
  copy.click();
  await until(() => copy.dataset.copied === "false", 3000);
  const failure = heard();
  return {
    open: dialog.open, title: text(card.querySelector(".popup-head h2")), fields, full: dialog.querySelector(".radio-full").textContent, readers,
    heading: text(card.querySelector("h3")), buttons, copied, shown: done, region, success, reset, failure,
    stray: [...card.childNodes].filter((node) => node.nodeType === 3).map((node) => node.textContent),
    inView: (() => {
      const edge = box(card);
      return edge.left >= 0 && edge.top >= 0 && edge.right <= innerWidth + 1 && edge.bottom <= innerHeight + 1;
    })(),
  };
})()"""
CLOSE_REPLY = """(async () => {@HELPERS@@PROBES@
  const spot = document.getElementById("radio-spot");
  (document.activeElement || document.body).dispatchEvent(new KeyboardEvent("keydown", {key: "Escape", bubbles: true}));
  await sleep(200);
  const escaped = !popup().open;
  const dialog = await openRow(longRow(spot));
  const card = box(dialog.querySelector(".popup-box"));
  const x = card.left > 8 ? Math.floor(card.left / 2) : Math.ceil((card.right + document.documentElement.clientWidth) / 2);
  const hit = document.elementFromPoint(x, Math.round(innerHeight / 2));
  hit.click();
  await sleep(200);
  const outside = [hit === popup(), !popup().open];
  await openRow(longRow(spot));
  all(".radio-actions button", popup()).find((button) => text(button) === "Reply").click();
  await sleep(300);
  return {escaped, outside, reply: {open: popup().open, ...pick(spot)}};
})()"""
HOME = """(async () => {@HELPERS@@PROBES@
  const spot = await openSpot();
  const owners = Object.fromEntries(@PARTS@.map((id) => [id, id === "radio" ? spot : spot.querySelector(`[data-panel="${id}"]`)]));
  const pressed = {};
  for (const [id, owner] of Object.entries(owners)) {
    const star = ownStar(owner);
    if (star.getAttribute("aria-pressed") !== "true") {
      star.click();
      await sleep(250);
    }
    pressed[id] = star.getAttribute("aria-pressed");
  }
  await until(() => (ViewStore.get("home.pins") || []).length === 4, 5000);
  const stored = (ViewStore.get("home.pins") || []).map((pin) => [`${pin.kind}:${pin.id}`, pin.w, pin.h]);
  await closeSpot();
  location.hash = "#home";
  await screenShown(8000);
  await until(() => @PARTS@.every((id) => tile(id)) && tile("radio-log").querySelector(".radio-row") && tile("radio").querySelector(".radio-row"), 10000);
  await sleep(400);
  const measure = () => Object.fromEntries(@PARTS@.map((id) => {
    const body = tile(id).querySelector(".home-body");
    const list = tile(id).querySelector(".radio-log");
    const edge = box(body);
    const rows = list ? all(".radio-row", list).filter((row) => box(row).top >= box(list).top - 1 && box(row).bottom <= box(list).bottom + 1).length : null;
    return [id, {scrollers: scrollersIn(tile(id)), rows, inside: list ? box(list).bottom <= edge.bottom + 1 && box(list).top >= edge.top - 1 : null, filled: Math.abs(box(tile(id).querySelector(".radio-home")).height - body.clientHeight + parseFloat(getComputedStyle(body).paddingTop) + parseFloat(getComputedStyle(body).paddingBottom)) <= 2}];
  }));
  const fresh = measure();
  const whole = tile("radio");
  const bar = whole.querySelector(".spot-head");
  const gear = bar ? all("button", bar).find((button) => button.getAttribute("aria-label") === "Read aloud") : null;
  const clear = bar ? all("button", bar).find((button) => button.getAttribute("aria-label") === "Cancel mayday") : null;
  if (gear) {
    gear.click();
    await sleep(200);
  }
  const filters = whole.querySelector(".radio-gear .radio-read");
  const tools = {
    gear: gear ? [gear.getAttribute("aria-expanded"), Boolean(filters), filters ? box(filters).bottom <= box(whole).bottom + 1 : null] : null,
    clear: clear ? [clear.disabled, clear.title] : null,
  };
  if (gear) {
    gear.click();
  }
  const content = {
    tiles: all("#main .home-tile").map((node) => node.dataset.pin),
    radio: [".radio-device", ".radio-speak", ".radio-logbox"].map((selector) => Boolean(tile("radio").querySelector(selector))),
    device: [text(tile("radio-device").querySelector('[data-field="mode"]')), all(".radio-knobs input[type=range]", tile("radio-device")).length],
    speak: [Boolean(tile("radio-speak").querySelector("form.composer textarea")), tile("radio-speak").querySelectorAll("form.composer select option").length > 0],
    log: [tile("radio-log").querySelectorAll(".radio-row").length, tile("radio").querySelectorAll(".radio-row").length, document.querySelectorAll("#radio-spot .radio-row").length],
    gone: all("#main .home-tile.gone").length,
    stars: all("#main .home-tile .home-body .star").length,
    ids: all("#main .home-tile .home-body [id]").map((node) => node.id).filter((id) => !id.startsWith("mic-field-")),
  };
  const count = (id) => tile(id).querySelectorAll(".radio-row").length;
  const before = [count("radio-log"), count("radio")];
  await fetch("/api/voice/@LIVE@", {cache: "no-store"});
  window.dispatchEvent(new Event("focus"));
  const first = (id) => text(tile(id).querySelector(".radio-row .radio-line"));
  const live = await until(() => (count("radio-log") > before[0] && count("radio") > before[1] && first("radio-log").startsWith("live row") ? [first("radio-log"), first("radio")] : null), 20000);
  tile("radio-device").querySelector('.radio-modes button[data-mode="quiet"]').click();
  await sleep(200);
  const mode = [text(tile("radio").querySelector('[data-field="mode"]')), text(document.querySelector('#radio-spot [data-field="mode"]'))];
  tile("radio-device").querySelector('.radio-modes button[data-mode="auto"]').click();
  await sleep(200);
  const sizes = @SIZES@;
  await ViewStore.update("home.pins", (pins) => (pins || []).map((pin) => ({...pin, w: sizes[pin.id][0], h: sizes[pin.id][1]})));
  await until(() => @PARTS@.every((id) => tile(id).dataset.w === String(sizes[id][0]) && tile(id).dataset.h === String(sizes[id][1])), 5000);
  await sleep(400);
  const resized = measure();
  window.scrollTo(0, 0);
  return {pressed, stored, fresh, resized, tools, content, live, mode, wide: document.documentElement.scrollWidth > innerWidth + 1};
})()"""
FIT = """(async () => {@HELPERS@@PROBES@
  await ViewStore.update("home.pins", () => []);
  location.hash = "#agents/orbit";
  await screenShown(8000);
  const spot = await openSpot();
  await until(() => spot.querySelector(".radio-row"), 8000);
  await sleep(500);
  const stage = document.querySelector("#main .stage svg");
  const list = spot.querySelector(".radio-log");
  const result = {
    fit: document.body.classList.contains("fit"), tall: document.documentElement.scrollHeight > innerHeight, wide: document.documentElement.scrollWidth > innerWidth + 1,
    stage: stage ? Math.round(box(stage).height) : 0, height: innerHeight, scrollers: scrollersIn(spot),
    list: list.clientHeight, speak: (() => {
      const card = spot.querySelector(".radio-speak");
      return card.scrollHeight <= card.clientHeight + 1;
    })(),
  };
  await closeSpot();
  await sleep(300);
  const after = document.querySelector("#main .stage svg");
  result.closed = {boxes: spot.getClientRects().length, tall: document.documentElement.scrollHeight > innerHeight, stage: after ? Math.round(box(after).height) : 0};
  return result;
})()"""
SPOT = """(async () => {@HELPERS@@PROBES@@SPEAKING@
  await ViewStore.update("home.pins", () => []);
  location.hash = "@VIEW@";
  await screenShown(8000);
  const spot = await openSpot();
  await until(() => spot.querySelector(".radio-row") && spot.querySelectorAll(".radio-device .station").length === 3, 8000);
  await settle();
  await sleep(500);
  window.scrollTo(0, 0);
  const fits = (node) => node.scrollHeight <= node.clientHeight + 1;
  const list = spot.querySelector(".radio-log");
  const fold = spot.querySelector("details.radio-station");
  const form = spot.querySelector(".radio-speak form.composer");
  const note = form.querySelector(".voice-note");
  const display = spot.querySelector(".radio-caption");
  const named = (node) => node.getAttribute("aria-label") || text(node) || node.getAttribute("title") || `${node.tagName}.${node.getAttribute("class")}`;
  const blocked = () => {
    const layer = spot.querySelector(".radio-station[open] > .station-body");
    const marks = [spot.querySelector(".radio-lamp"), spot.querySelector('[data-field="cpu"]'), spot.querySelector(".radio-device .group-title")];
    const folded = (node) => Boolean(node.closest("details:not([open])")) && !node.closest("summary");
    const found = [];
    for (const node of [...all('button, input, select, textarea, summary, audio, [role="tab"]', spot), ...marks].filter((item) => shown(item) && !folded(item) && box(item).width > 0 && box(item).height > 0)) {
      window.scrollTo(0, 0);
      const seen = box(node);
      if (seen.bottom > innerHeight) {
        window.scrollBy(0, seen.top + seen.height / 2 - innerHeight / 2);
      }
      const edge = box(node);
      const [x, y] = [edge.left + edge.width / 2, edge.top + edge.height / 2];
      const hit = document.elementFromPoint(x, y);
      if (!(list.contains(node) && (y < box(list).top || y > box(list).bottom)) && !(hit === node || node.contains(hit) || (layer && hit && layer.contains(hit) && !layer.contains(node)))) {
        found.push(`${named(node)} <- ${hit ? `${hit.tagName}.${hit.getAttribute("class")}#${hit.id}` : "null"}`);
      }
    }
    window.scrollTo(0, 0);
    return found;
  };
  const stack = () => {
    const card = spot.querySelector(".radio-logbox");
    const head = [card.querySelector(".radio-tabs"), card.querySelector('input[type="search"]')].map(box);
    const chips = all(".chip-select, .radio-filters > button", card).map(box);
    return {head: Math.round(Math.max(...head.map((edge) => edge.bottom))), chips: [Math.round(Math.min(...chips.map((edge) => edge.top))), Math.round(Math.max(...chips.map((edge) => edge.bottom)))], list: Math.round(box(list).top)};
  };
  const measure = () => {
    window.scrollTo(0, 0);
    const [device, speak, history] = ["radio-device", "radio-speak", "radio-log"].map((id) => box(spot.querySelector(`[data-panel="${id}"]`)));
    const svg = document.querySelector("#main .stage svg");
    return {
      fit: document.body.classList.contains("fit"),
      page: [document.documentElement.scrollWidth, document.documentElement.scrollHeight, innerWidth, innerHeight],
      scrollers: scrollersIn(spot), cards: [fits(spot.querySelector(".radio-device")), fits(spot.querySelector(".radio-speak"))],
      main: Math.round(box(document.getElementById("main")).height), floor: Math.round(innerHeight * @MAIN@ - box(document.getElementById("spot-host")).top),
      full: Math.round(innerHeight - document.getElementById("head").offsetHeight - 16), stack: stack(), beneath: box(document.getElementById("main")).top >= box(spot).bottom - 1,
      stage: svg ? Math.round(box(svg).height) : null,
      list: list.clientHeight, rows: all(".radio-row", list).filter((row) => box(row).top >= box(list).top - 1 && box(row).bottom <= box(list).bottom + 1).length,
      order: device.right <= speak.left && device.right <= history.left && speak.bottom <= history.top + 1 && Math.abs(speak.left - history.left) < 2,
      active: {stations: fold.open ? all(".station", fold).filter(shown).length : 0, voice: !note.hidden && shown(note), speech: !display.hidden && shown(display)},
      blocked: blocked(),
      banner: (() => {
        const node = document.getElementById("mayday");
        if (node.hidden || !shown(node)) {
          return null;
        }
        const words = node.querySelector(".text");
        const cancel = node.querySelector("button");
        const edge = box(cancel);
        const hit = document.elementFromPoint(edge.left + edge.width / 2, edge.top + edge.height / 2);
        return {height: Math.round(box(node).height), title: words.title, full: words.textContent, cut: words.scrollWidth > words.clientWidth + 1, cancel: Boolean(hit && cancel.contains(hit))};
      })(),
      play: [note.querySelector(".voice-play"), note.querySelector("audio")].filter((node) => node && shown(node) && box(node).width > 0).map((node) => [node.tagName, Math.round(box(node).width), Math.round(box(node).height)]),
      line: (() => {
        const node = display.querySelector(".caption-line");
        return node && shown(node) ? [Math.round(node.clientWidth), text(node).length] : null;
      })(),
      rem: parseFloat(getComputedStyle(document.documentElement).fontSize),
    };
  };
  const wanted = @STATES@;
  const states = {};
  for (const name of wanted.filter((state) => state === "idle" || state.startsWith("mayday"))) {
    states[name] = measure();
  }
  if (wanted.includes("stations")) {
    const summary = fold.querySelector("summary");
    summary.focus();
    summary.click();
    await sleep(300);
    states.stations = measure();
    document.activeElement.dispatchEvent(new KeyboardEvent("keydown", {key: "Escape", bubbles: true}));
    await sleep(200);
    states.stations.closed = [fold.open, document.activeElement === summary];
  }
  if (wanted.includes("voice")) {
    const record = all("button", form).find((button) => button.hasAttribute("aria-pressed") && !button.classList.contains("mic"));
    record.click();
    await sleep(1300);
    record.click();
    const heard = await until(() => !note.hidden && note.querySelector("audio") && form.querySelector("textarea").value, 30000);
    await sleep(300);
    states.voice = {...measure(), heard: Boolean(heard)};
    const toggle = note.querySelector(".voice-play");
    if (toggle && shown(toggle)) {
      toggle.click();
      states.voice.played = Boolean(await until(() => !note.querySelector("audio").paused && toggle.getAttribute("aria-label") === "Pause voice message", 4000));
      toggle.click();
      states.voice.paused = Boolean(await until(() => note.querySelector("audio").paused && toggle.getAttribute("aria-label") === "Play voice message", 4000));
    }
    const trash = all("button", note).find((button) => button.getAttribute("aria-label") === "Remove recording");
    if (trash) {
      trash.click();
    }
    await sleep(200);
  }
  if (wanted.includes("speech")) {
    const found = await cue("@CUE@");
    await sleep(300);
    states.speech = {...measure(), who: found && !found.error ? found.who : found};
    const stop = display.querySelector("button");
    if (stop) {
      stop.click();
    }
    await until(() => display.hidden, 8000);
  }
  return states;
})()"""
POP = """(async () => {@HELPERS@@PROBES@
  await ViewStore.update("home.pins", () => @PINS@);
  location.hash = "@VIEW@";
  await screenShown(8000);
  if (@SPOT@) {
    await openSpot();
  } else {
    await closeSpot();
  }
  await settle();
  await sleep(500);
  const outside = (layer) => {
    const edge = box(layer);
    const clips = [["viewport", {top: 0, bottom: innerHeight, left: 0, right: innerWidth}]];
    for (let node = layer.parentElement; node && node !== document.documentElement; node = node.parentElement) {
      const look = getComputedStyle(node);
      if (look.overflowX !== "visible" || look.overflowY !== "visible") {
        clips.push([`${node.tagName}.${node.getAttribute("class")}`, box(node)]);
      }
    }
    return clips.filter(([, clip]) => edge.top < clip.top - 1 || edge.bottom > clip.bottom + 1 || edge.left < clip.left - 1 || edge.right > clip.right + 1)
      .map(([name, clip]) => `${name} [${Math.round(clip.top)},${Math.round(clip.bottom)}] vs [${Math.round(edge.top)},${Math.round(edge.bottom)}]`);
  };
  const out = [];
  for (const selector of @ROOTS@) {
    const root = document.querySelector(selector);
    if (!root || !(await until(() => root.querySelectorAll(".station").length === 3, 8000))) {
      out.push({selector, error: "no stations"});
      continue;
    }
    const fold = root.querySelector("details.radio-station");
    const summary = fold.querySelector("summary");
    const layer = fold.querySelector(".station-body");
    fold.scrollIntoView({block: "center"});
    await sleep(200);
    summary.focus();
    summary.click();
    await sleep(300);
    const whole = all(".station", layer).filter((row) => box(row).top >= box(layer).top - 1 && box(row).bottom <= box(layer).bottom + 1).length;
    const opened = {open: fold.open, side: fold.dataset.side, height: Math.round(box(layer).height), outside: outside(layer), whole};
    layer.querySelector(".station button").focus();
    document.activeElement.dispatchEvent(new KeyboardEvent("keydown", {key: "Escape", bubbles: true}));
    await sleep(200);
    const escape = [fold.open, document.activeElement === summary];
    summary.click();
    await sleep(300);
    const again = {open: fold.open, outside: outside(layer)};
    press(document.getElementById("main"));
    await sleep(200);
    out.push({selector, opened, escape, again, click: [fold.open, document.activeElement === summary, document.activeElement === document.body]});
  }
  return out;
})()"""
FOCUS = """(async () => {@HELPERS@@PROBES@
  await ViewStore.update("home.pins", () => []);
  location.hash = "#agents/orbit";
  await screenShown(8000);
  const spot = await openSpot();
  await until(() => spot.querySelectorAll(".station").length === 3 && spot.querySelector(".radio-row"), 8000);
  await settle();
  await sleep(300);
  const fold = spot.querySelector("details.radio-station");
  const night = await until(() => all("details.menu").find((menu) => menu.querySelector("summary").getAttribute("aria-label") === "Day/Night"), 8000);
  const label = (node) => (node ? `${node.tagName}.${node.getAttribute("class")}[${node.getAttribute("aria-label") || text(node).slice(0, 24)}]` : "null");
  const tab = () => spot.querySelector('.radio-tabs [role="tab"]:not([aria-selected="true"])');
  const cases = {};
  const run = async (key, menu, target) => {
    press(menu.querySelector("summary"));
    await sleep(250);
    const opened = menu.open;
    const node = target();
    press(node);
    await sleep(400);
    const active = document.activeElement;
    cases[key] = {opened, closed: !menu.open, active: label(active), summary: Boolean(active && active.matches("summary")), history: Boolean(active && active.closest(".radio-logbox")), body: active === document.body};
    menu.open = false;
    await sleep(150);
  };
  await run("night-tab", night, tab);
  await run("fold-tab", fold, tab);
  await run("night-main", night, () => document.getElementById("main"));
  await run("fold-main", fold, () => document.getElementById("main"));
  press(fold.querySelector("summary"));
  await sleep(250);
  fold.querySelector(".station button").focus();
  document.activeElement.dispatchEvent(new KeyboardEvent("keydown", {key: "Escape", bubbles: true}));
  await sleep(200);
  cases.escape = {closed: !fold.open, toggle: document.activeElement === fold.querySelector("summary")};
  return cases;
})()"""
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
ROWS = """(async () => {@HELPERS@@PROBES@@LOADS@
  await ViewStore.update("home.pins", () => []);
  location.hash = "#agents/orbit";
  await screenShown(8000);
  const spot = await openSpot();
  await until(() => spot.querySelectorAll(".radio-row").length > 2, 8000);
  await settle();
  await sleep(300);
  const rows = () => spot.querySelectorAll(".radio-row").length;
  const deliver = async () => {
    const before = rows();
    await fetch("/api/voice/@LIVE@", {cache: "no-store"});
    window.dispatchEvent(new Event("focus"));
    const done = await until(() => rows() > before, 20000);
    await sleep(300);
    return Boolean(done);
  };
  const row = spot.querySelectorAll(".radio-row")[1];
  const button = row.querySelector(".radio-pick");
  const held = () => {
    const active = document.activeElement;
    const owner = active ? active.closest(".radio-row") : null;
    return {same: active === button, key: owner ? owner.dataset.key : null, pick: Boolean(active && active.matches(".radio-pick")), body: active === document.body};
  };
  button.focus();
  const start = {...held(), want: row.dataset.key};
  const fresh = {...held(), delivered: await deliver()};
  const real = Date.now;
  Date.now = () => real.call(Date) + 60000;
  window.dispatchEvent(new Event("focus"));
  const tick = {...held(), ticked: await loaded(1, 20000)};
  Date.now = real;
  const tab = spot.querySelector('.radio-tabs [role="tab"][aria-selected="true"]');
  tab.focus();
  let focusins = 0;
  document.addEventListener("focusin", () => {
    focusins += 1;
  }, true);
  const delivered = [await deliver(), await deliver(), await deliver()];
  return {start, fresh, tick, tabs: {delivered, focusins, same: document.activeElement === tab, tab: document.activeElement.getAttribute("data-tab")}};
})()"""
KEYS = """(async () => {@HELPERS@@PROBES@
  await ViewStore.update("home.pins", () => []);
  location.hash = "#agents/orbit";
  await screenShown(8000);
  const spot = await openSpot();
  spot.querySelector('.radio-tabs [role="tab"][data-tab="all"]').click();
  const dups = () => all(".radio-row", spot).filter((node) => text(node.querySelector(".radio-line")).startsWith("dup "));
  await until(() => dups().length === 2, 8000);
  await settle();
  await sleep(300);
  const rows = () => spot.querySelectorAll(".radio-row").length;
  const deliver = async () => {
    const before = rows();
    await fetch("/api/voice/@LIVE@", {cache: "no-store"});
    window.dispatchEvent(new Event("focus"));
    const done = await until(() => rows() > before, 20000);
    await sleep(300);
    return Boolean(done);
  };
  const line = (node) => (node && node.closest(".radio-row") ? text(node.closest(".radio-row").querySelector(".radio-line")) : null);
  const out = {keys: dups().map((node) => node.dataset.key)};
  for (const word of @DUPS@) {
    const button = dups().find((node) => text(node.querySelector(".radio-line")) === word).querySelector(".radio-pick");
    button.focus();
    const delivered = await deliver();
    const active = document.activeElement;
    const result = {delivered, same: active === button, line: line(active), popup: null};
    if (active && active.matches(".radio-pick")) {
      active.click();
      result.popup = await until(() => (popup().open && popup().querySelector(".radio-full") ? popup().querySelector(".radio-full").textContent : null), 4000);
      (document.activeElement || document.body).dispatchEvent(new KeyboardEvent("keydown", {key: "Escape", bubbles: true}));
      await until(() => !popup().open, 2000);
    }
    out[word] = result;
  }
  const victim = all(".radio-row", spot).find((node) => node.dataset.class === "newsletter");
  victim.querySelector(".radio-pick").focus();
  const chip = spot.querySelector('.chip-select[data-chip="class"] select');
  chip.value = "call";
  chip.dispatchEvent(new Event("change", {bubbles: true}));
  await sleep(500);
  const near = document.activeElement;
  out.filtered = {gone: !victim.isConnected, pick: Boolean(near && near.matches(".radio-pick")), class: near && near.closest(".radio-row") ? near.closest(".radio-row").dataset.class : null};
  const search = spot.querySelector('.radio-logbox input[type="search"]');
  search.value = "no radio row says this";
  search.dispatchEvent(new Event("input", {bubbles: true}));
  await sleep(500);
  out.emptied = {gone: !spot.querySelector(".radio-row"), list: document.activeElement === spot.querySelector("ul.radio-log")};
  search.value = "";
  search.dispatchEvent(new Event("input", {bubbles: true}));
  chip.value = "";
  chip.dispatchEvent(new Event("change", {bubbles: true}));
  await sleep(300);
  return out;
})()"""
BANNER = """(async () => {@HELPERS@@PROBES@@LOADS@
  await ViewStore.update("home.pins", () => []);
  location.hash = "#agents/orbit";
  await screenShown(8000);
  const banner = document.getElementById("mayday");
  await until(() => !banner.hidden && banner.querySelector("button"), 8000);
  await settle();
  await sleep(300);
  const records = [];
  new MutationObserver((list) => records.push(...list)).observe(banner, {childList: true, subtree: true, characterData: true, attributes: true});
  const cancel = banner.querySelector("button");
  cancel.focus();
  const polled = await loaded(2, 30000);
  const steady = {polled, mutations: records.length, focus: document.activeElement === cancel, body: document.activeElement === document.body};
  records.length = 0;
  await fetch("/api/voice/@SILENCE@", {cache: "no-store"});
  const again = await loaded(3, 45000);
  const added = records.filter((record) => record.type === "childList" && record.addedNodes.length > 0).length;
  return {steady, changed: {polled: again, text: text(banner.querySelector(".text")), added, shown: !banner.hidden, cancel: Boolean(banner.querySelector("button"))}};
})()"""
COMPOSE_HOME = """(async () => {@HELPERS@@PROBES@
  const bodies = [];
  const send = window.fetch.bind(window);
  window.fetch = (path, init) => {
    if (String(path) === "/api/messages") {
      bodies.push(JSON.parse(init.body));
    }
    return send(path, init);
  };
  window.confirm = () => true;
  const spot = await openSpot();
  const spotText = spot.querySelector("form.composer textarea");
  spotText.value = "draft kept in the spot";
  spotText.dispatchEvent(new Event("input", {bubbles: true}));
  await ViewStore.update("home.pins", () => [{kind: "panel", id: "radio", w: 12, h: 7}, {kind: "panel", id: "radio-speak", w: 6, h: 5}, {kind: "panel", id: "radio-log", w: 6, h: 5}]);
  location.hash = "#home";
  await screenShown(8000);
  await until(() => tile("radio-speak") && tile("radio-log") && tile("radio") && tile("radio-log").querySelector(".radio-row"), 10000);
  await sleep(400);
  const homeSpeak = tile("radio-speak");
  const form = (root) => root.querySelector("form.composer");
  const area = (root) => form(root).querySelector("textarea");
  const record = (root) => all("button", form(root)).find((button) => button.hasAttribute("aria-pressed") && !button.classList.contains("mic"));
  const note = (root) => {
    const audio = form(root).querySelector(".voice-note audio");
    return audio ? audio.getAttribute("src").replace("/api/voice/", "").replace(".wav", "") : null;
  };
  const drafts = [area(spot).value, area(homeSpeak).value, area(tile("radio")).value];
  record(spot).click();
  await sleep(1200);
  const first = record(spot).getAttribute("aria-pressed");
  record(homeSpeak).click();
  const handed = await until(() => (record(homeSpeak).getAttribute("aria-pressed") === "true" ? [record(spot).getAttribute("aria-pressed"), "true"] : null), 5000);
  const spotHeard = await until(() => (note(spot) && area(spot).value.includes("hello from the mic") ? area(spot).value : null), 30000);
  const homeBefore = area(homeSpeak).value;
  await sleep(800);
  record(homeSpeak).click();
  const homeHeard = await until(() => (note(homeSpeak) && area(homeSpeak).value.includes("hello from the mic") ? area(homeSpeak).value : null), 30000);
  const notes = [note(spot), note(homeSpeak)];
  const sendFrom = async (root, to, words, attach) => {
    const [channel, recipient] = all("select", form(root));
    channel.value = "post";
    channel.dispatchEvent(new Event("change", {bubbles: true}));
    await until(() => [...recipient.options].some((option) => option.value === to), 8000);
    recipient.value = to;
    area(root).value = words;
    area(root).dispatchEvent(new Event("input", {bubbles: true}));
    const box = form(root).querySelector('.voice-note input[type="checkbox"]');
    if (box) {
      box.checked = attach;
    }
    const shownBefore = new Set(all("#toasts .toast"));
    form(root).querySelector('button[type="submit"]').click();
    return until(() => all("#toasts .toast").filter((node) => !shownBefore.has(node)).map(text).find((entry) => entry.startsWith("Post to")), 20000);
  };
  const spotSent = await sendFrom(spot, "Stage", "plain text from the spot", false);
  const homeAttach = Boolean(form(homeSpeak).querySelector('.voice-note input[type="checkbox"]'));
  const homeSent = await sendFrom(homeSpeak, "Docs", "voice from the Home tile", true);
  await closeSpot();
  document.getElementById("toasts").replaceChildren();
  return {drafts, first, handed, spotHeard, homeBefore, homeHeard, notes, spotSent, homeAttach, homeSent, bodies: bodies.map((body) => [body.to, body.text, body.voice])};
})()"""
REPLY_HOME = """(async () => {@HELPERS@@PROBES@
  const spotOpen = () => document.getElementById("radio-open").getAttribute("aria-expanded");
  const reply = async (root) => {
    const row = longRow(root);
    row.scrollIntoView({block: "center"});
    await sleep(200);
    await openRow(row);
    all(".radio-actions button", popup()).find((button) => text(button) === "Reply").click();
    await sleep(300);
  };
  await reply(tile("radio-log"));
  const fromLog = {spot: spotOpen(), popup: popup().open, speak: pick(tile("radio-speak")), whole: pick(tile("radio"))};
  await reply(tile("radio"));
  const fromWhole = {spot: spotOpen(), whole: pick(tile("radio"))};
  const sendFrom = async (root, words) => {
    const area = root.querySelector("form.composer textarea");
    area.value = words;
    area.dispatchEvent(new Event("input", {bubbles: true}));
    const shownBefore = new Set(all("#toasts .toast"));
    root.querySelector('form.composer button[type="submit"]').click();
    return until(() => all("#toasts .toast").filter((node) => !shownBefore.has(node)).map(text).find((entry) => entry.startsWith("Post to")), 20000);
  };
  const sent = await sendFrom(tile("radio"), "reply from the Home radio");
  const questions = [];
  window.confirm = (question) => {
    questions.push(question);
    return true;
  };
  const clear = all(".spot-head button", tile("radio")).find((button) => button.getAttribute("aria-label") === "Cancel mayday");
  const enabled = clear ? !clear.disabled : null;
  const shownBefore = new Set(all("#toasts .toast"));
  if (clear) {
    clear.click();
  }
  const lifted = await until(() => all("#toasts .toast").filter((node) => !shownBefore.has(node)).map(text).find((entry) => entry.startsWith("Cancel mayday")), 15000);
  document.getElementById("toasts").replaceChildren();
  return {fromLog, fromWhole, sent, enabled, questions, lifted, spot: spotOpen()};
})()"""


def columns(width: int, height: int) -> bool:
    return any(width >= low and height >= tall for low, tall in BANDS)


def probe(template: str) -> str:
    return (template.replace("@HELPERS@", base.HELPERS).replace("@PROBES@", PROBES).replace("@LOADS@", LOADS).replace("@SPEAKING@", base.SPEAKING).replace("@PARTS@", json.dumps(PARTS))
            .replace("@SIZES@", json.dumps(SIZES)).replace("@LIVE@", LIVE).replace("@SILENCE@", SILENCE).replace("@DUPS@", json.dumps(DUPS)).replace("@MAIN@", str(MAIN_SHARE)))


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestRadioLayout(HubCase):
    drive = base.TestOrchestratorE2E.drive
    beside = base.TestOrchestratorE2E.beside
    authenticator = base.TestOrchestratorE2E.authenticator
    speaks = base.TestOrchestratorE2E.speaks

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

    def steps(self, browser: str) -> list[dict]:
        steps = []
        for width, height in WIDTHS:
            shot = str(OUT / f"{browser}-{width}")
            steps += [
                {"width": width, "height": height, "url": f"http://localhost:{self.port}/?{width}#stream", "wait": 1500, "probe": probe(LAYOUT), "shot": f"{shot}-radio.png"},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(POPUP), "shot": f"{shot}-popup.png", "gesture": True},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(CLOSE_REPLY), "shot": f"{shot}-reply.png"},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(HOME), "shot": f"{shot}-home.png"},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(FIT), "shot": f"{shot}-orbit.png"},
            ]
        return steps

    def check_layout(self, layout: dict, size: tuple[int, int], index: int, browser: str) -> None:
        width = size[0]
        self.assertNotIn("error", layout, layout)
        self.assertLessEqual(layout["page"][0], layout["page"][1], layout)
        if columns(*size):
            self.assertLessEqual(layout["tall"][0], layout["tall"][1], layout)
        self.assertEqual(layout["wider"], [], layout)
        self.assertEqual(layout["scrollers"], ["radio-log"], layout)
        self.assertEqual((layout["list"]["overflowY"], layout["list"]["scrollbar"][0], layout["list"]["scrolls"]), ("auto", "thin", True), layout)
        self.assertNotIn(layout["list"]["scrollbar"][1], ("", "auto"), layout)
        if browser == "firefox":
            self.assertNotIn(layout["main"], ("", "auto"), layout)
        self.assertEqual(len(layout["heights"]), 1, layout)
        self.assertLess(layout["heights"][0], 2 * layout["lineHeight"], layout)
        self.assertTrue(layout["single"], layout)
        self.assertGreaterEqual(layout["narrowest"], 30, layout)
        self.assertEqual(layout["rows"], FILLERS + 2 + index, layout)
        self.assertEqual(layout["long"], [True, "ellipsis"], layout)
        self.assertGreaterEqual(layout["avatars"].pop("rows"), 2, layout)
        cap = 3 if width in NARROW else 8
        self.assertEqual(layout["avatars"], {"most": cap, "inside": True, "after": True, "stacked": True}, layout)
        self.assertEqual(layout["folds"], [[total, min(total, cap), [f"+{total - cap}"] if total > cap else []] for total, _, _ in layout["folds"]], layout)
        self.assertGreaterEqual(layout["sliver"], 10, layout)
        self.assertTrue(layout["order"]["stacked" if width == 390 else "beside"], layout)
        self.assertEqual(layout["labels"], 1, layout)
        self.assertEqual(layout["stars"], [[part, True] for part in PARTS], layout)
        self.assertEqual(layout["covered"], [], layout)
        self.assertEqual(layout["stations"], [True, False], layout)

    def check_popup(self, popup: dict) -> None:
        self.assertNotIn("error", popup, popup)
        self.assertTrue(popup["open"], popup)
        self.assertEqual(popup["title"], "Stage → all", popup)
        self.assertEqual(list(popup["fields"]), ["Sender", "Recipient", "Class", "Time"], popup)
        self.assertEqual((popup["fields"]["Sender"], popup["fields"]["Recipient"], popup["fields"]["Class"]), ("Stage", "all", "Broadcast"), popup)
        self.assertTrue(popup["fields"]["Time"], popup)
        self.assertEqual((popup["full"], popup["stray"]), (LONG, []), popup)
        self.assertEqual(popup["heading"], f"Read by {len(popup['readers'])}", popup)
        self.assertGreater(len(popup["readers"]), 8, popup)
        self.assertLessEqual({reader["name"] for reader in popup["readers"]}, set(NAMES), popup)
        timed = [reader for reader in popup["readers"] if reader["time"] != "read, time unknown"]
        self.assertEqual([(reader["session"], reader["name"]) for reader in timed], [("s5", "Beacon")], popup)
        self.assertRegex(timed[0]["time"], r"^read about \S.*\d", popup)
        self.assertEqual(popup["buttons"], ["Reply", "Copied"], popup)
        self.assertEqual((popup["copied"], popup["shown"]), ([LONG], "Copied"), popup)
        self.assertEqual(popup["region"], ["status", "polite", True, True], popup)
        self.assertEqual(popup["success"], ["Copied", "Copied: the full message is on the clipboard"], popup)
        self.assertEqual(popup["reset"], ["Copy", ""], popup)
        self.assertEqual(popup["failure"], ["Not copied", "Not copied: the browser refused the clipboard"], popup)
        self.assertTrue(popup["inView"], popup)

    def check_home(self, home: dict, width: int) -> None:
        self.assertEqual(home["pressed"], {part: "true" for part in PARTS}, home)
        self.assertEqual(home["stored"], [[f"panel:{part}", *DEFAULTS[part]] for part in PARTS], home)
        for moment in ("fresh", "resized"):
            for part in PARTS:
                with self.subTest(moment=moment, tile=part):
                    found = home[moment][part]
                    stacked = width == 390 and part == "radio"
                    expected = ["home-body"] if stacked else [SCROLLER[part]] if SCROLLER[part] else []
                    self.assertEqual(found["scrollers"], expected, home[moment])
                    if found["rows"] is not None and not stacked:
                        self.assertGreaterEqual(found["rows"], 2, home[moment])
                        self.assertTrue(found["inside"], home[moment])
                        self.assertTrue(found["filled"], home[moment])
        self.assertEqual(home["tools"]["gear"], ["true", True, True], home)
        self.assertEqual(home["tools"]["clear"], [True, "Cancel mayday: lift the radio silence so the agents write again; your passkey signs it"], home)
        content = home["content"]
        self.assertEqual(content["tiles"], [f"panel:{part}" for part in PARTS], home)
        self.assertEqual(content["radio"], [True, True, True], home)
        self.assertEqual(content["device"], ["Auto", 6], home)
        self.assertEqual(content["speak"], [True, True], home)
        self.assertEqual(content["log"][0], content["log"][2], home)
        self.assertEqual(content["log"][1], content["log"][2], home)
        self.assertEqual((content["gone"], content["stars"], content["ids"]), (0, 0, []), home)
        self.assertIsNotNone(home["live"], home)
        self.assertEqual(home["live"][0], home["live"][1], home)
        self.assertEqual(home["mode"], ["Quiet", "Quiet"], home)
        self.assertFalse(home["wide"], home)

    def check_fit(self, fit: dict, size: tuple[int, int]) -> None:
        self.assertTrue(fit["fit"], fit)
        self.assertFalse(fit["wide"], fit)
        self.assertTrue(fit["speak"], fit)
        self.assertEqual((fit["closed"]["boxes"], fit["closed"]["tall"]), (0, False), fit)
        self.assertGreaterEqual(fit["closed"]["stage"], 2 * STAGE_SHARE * fit["height"], fit)
        self.assertEqual(fit["scrollers"], ["radio-log"], fit)
        if not columns(*size):
            self.assertTrue(fit["tall"], fit)
            self.assertGreaterEqual(fit["stage"], 2 * STAGE_SHARE * fit["height"], fit)
        else:
            self.assertGreater(fit["closed"]["stage"], fit["stage"], fit)
            self.assertFalse(fit["tall"], fit)
            self.assertGreaterEqual(fit["stage"], STAGE_SHARE * fit["height"], fit)
            self.assertGreaterEqual(fit["list"], 60, fit)

    def silence(self, words: str) -> None:
        now = time.time()
        self.write_council({"radio-silence.json": {"since": now - 60, "until": now + 3600, "by": "Docs", "text": words}})

    def stations(self) -> None:
        hub = self.httpd.hub
        hub.settings.put({**hub.settings.get(), "streams": STREAMS}, hub.settings.get())

    def laptop_steps(self, browser: str, states: list[str]) -> list[dict]:
        places = [(width, height, view) for width, height in LAPTOPS for view in VIEWS]
        return [{"width": width, "height": height, "url": f"http://localhost:{self.port}/?{width}x{height}-{states[-1]}#stream" if view == VIEWS[0] else None, "wait": 1500 if view == VIEWS[0] else 0, "gesture": True,
                 "probe": probe(SPOT.replace("@VIEW@", view).replace("@STATES@", json.dumps(states)).replace("@CUE@", f"layout-cue-{index}")),
                 "shot": str(OUT / f"{browser}-{width}x{height}-{view[1:].replace('/', '-')}-{states[-1]}.png")} for index, (width, height, view) in enumerate(places)]

    def laptops(self, browser: str, *driver: str) -> dict:
        self.stations()
        self.speaks(tuple(f"layout-cue-{index}" for index in range(len(LAPTOPS) * len(VIEWS))))
        runs = [self.drive(self.laptop_steps(browser, [state for state in STATES if state not in ALARMS]), None, *driver)]
        for state, words in ALARMS.items():
            self.silence(words)
            runs.append(self.drive(self.laptop_steps(browser, [state]), None, *driver))
        return {"results": [{key: value for part in parts for key, value in part.items()} for parts in zip(*(run["results"] for run in runs), strict=True)], "errors": [error for run in runs for error in run["errors"]]}

    def check_laptops(self, data: dict, browser: str) -> None:
        results = iter(data["results"])
        for width, height in LAPTOPS:
            for view in VIEWS:
                states = next(results)
                for state in STATES:
                    with self.subTest(browser=browser, size=f"{width}x{height}", view=view, state=state):
                        self.check_state(states[state], state, view)
                        self.check_side(states[state], width, height)

    def check_side(self, found: dict, width: int, height: int) -> None:
        self.assertGreaterEqual(found["main"], found["floor"], found)
        self.assertLessEqual(found["page"][0], found["page"][2], found)
        self.assertLessEqual(found["stack"]["head"], found["stack"]["chips"][0] + 1, found)
        self.assertLessEqual(found["stack"]["chips"][1], found["stack"]["list"] + 1, found)
        if columns(width, height):
            self.assertLessEqual(found["page"][1], found["page"][3], found)
            self.assertEqual(found["scrollers"], ["radio-log"], found)
            self.assertTrue(found["order"], found)
            if found["fit"]:
                self.assertGreaterEqual(found["stage"], STAGE_SHARE * height, found)
            return
        self.assertGreaterEqual(found["main"], found["full"] - 1, found)
        self.assertTrue(found["beneath"], found)
        if found["fit"]:
            self.assertGreaterEqual(found["stage"], 2 * STAGE_SHARE * height, found)

    def check_state(self, found: dict, state: str, view: str) -> None:
        self.assertEqual(found["active"], {"stations": 3 if state == "stations" else 0, "voice": state == "voice", "speech": state == "speech"}, found)
        self.assertEqual(found["banner"] is not None, state in ALARMS, found)
        if state in ALARMS:
            self.assertLessEqual(found["banner"]["height"], BANNER_MAX, found)
            self.assertEqual((found["banner"]["title"], found["banner"]["cut"], found["banner"]["cancel"]), (found["banner"]["full"], state == "mayday-long", True), found)
            self.assertTrue(found["banner"]["full"].endswith(ALARMS[state]), found)
        self.assertEqual(found["blocked"], [], found)
        if state == "stations":
            self.assertEqual(found["closed"], [False, True], found)
        if state == "voice":
            self.assertTrue(found["heard"], found)
            self.assertEqual(len(found["play"]), 1, found)
            kind, width, tall = found["play"][0]
            self.assertGreaterEqual(width, PLAY_MIN[kind][0], found)
            self.assertGreaterEqual(tall, PLAY_MIN[kind][1], found)
            if kind == "BUTTON":
                self.assertEqual((found["played"], found["paused"]), (True, True), found)
        if state == "speech":
            self.assertEqual(found["who"], "Stage speaking", found)
            self.assertGreaterEqual(found["line"][0], 4 * found["rem"], found)
            self.assertGreater(found["line"][1], 0, found)
        self.assertEqual(found["fit"], view != "#stream", found)
        self.assertEqual(found["cards"], [True, True], found)
        self.assertGreaterEqual(found["list"], 60, found)
        self.assertGreaterEqual(found["rows"], 2, found)

    def popover_steps(self, browser: str) -> list[dict]:
        self.stations()
        tiles = json.dumps([f'#main .home-tile[data-pin="panel:{part}"]' for part in ("radio-device", "radio")])
        places = (("spot", "#stream", "[]", '["#radio-spot"]', "true"), ("home", "#home", json.dumps(HOME_RADIO), tiles, "false"), ("home-spot", "#home", json.dumps(HOME_RADIO), tiles, "true"))
        return [{"width": width, "height": height, "url": f"http://localhost:{self.port}/?{width}-pop#stream" if name == "spot" else None, "wait": 1500 if name == "spot" else 0,
                 "probe": probe(POP.replace("@VIEW@", view).replace("@PINS@", pins).replace("@ROOTS@", roots).replace("@SPOT@", spot)), "shot": str(OUT / f"{browser}-{width}-pop-{name}.png")}
                for width, height in POPOVER_SIZES for name, view, pins, roots, spot in places]

    def check_popover(self, data: dict, browser: str) -> None:
        results = iter(data["results"])
        for width, _ in POPOVER_SIZES:
            for place in ("spot", "home", "home-spot"):
                found = next(results)
                self.assertEqual(len(found), 1 if place == "spot" else 2, found)
                for fold in found:
                    with self.subTest(browser=browser, width=width, place=place, root=fold["selector"]):
                        self.assertNotIn("error", fold, fold)
                        self.assertEqual((fold["opened"]["open"], fold["opened"]["outside"]), (True, []), fold)
                        self.assertGreaterEqual(fold["opened"]["whole"], 1, fold)
                        self.assertEqual(fold["escape"], [False, True], fold)
                        self.assertEqual(fold["again"], {"open": True, "outside": []}, fold)
                        self.assertEqual(fold["click"], [False, False, True], fold)

    def focus_steps(self, browser: str) -> list[dict]:
        self.stations()
        return [{"width": width, "height": height, "url": f"http://localhost:{self.port}/?{width}-focus#stream", "wait": 1500, "probe": probe(FOCUS), "shot": str(OUT / f"{browser}-{width}-focus.png")}
                for width, height in FOCUS_SIZES]

    def check_focus(self, data: dict, browser: str) -> None:
        for (width, _), cases in zip(FOCUS_SIZES, data["results"], strict=True):
            for key, found in cases.items():
                with self.subTest(browser=browser, width=width, case=key):
                    if key == "escape":
                        self.assertEqual(found, {"closed": True, "toggle": True}, found)
                        continue
                    self.assertEqual((found["opened"], found["closed"], found["summary"]), (True, True, False), found)
                    self.assertTrue(found["history"] if key.endswith("tab") else found["body"], found)

    def watch(self, browser: str, kind: str, template: str) -> dict:
        width, height = FOCUS_SIZES[0]
        step = {"width": width, "height": height, "url": f"http://localhost:{self.port}/?{width}-{kind}#stream", "wait": 1500, "probe": probe(template), "shot": str(OUT / f"{browser}-{width}-{kind}.png")}
        driver = ("bidi.mjs", os.environ.get("FIREFOX", "firefox")) if browser == "firefox" else ()
        data = self.drive([step], None, *driver)
        (OUT / f"{browser}-radio-{kind}.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        return data["results"][0]

    def check_rows(self, found: dict, browser: str) -> None:
        want = {"same": True, "key": found["start"].pop("want"), "pick": True, "body": False}
        for moment, done in (("start", None), ("fresh", "delivered"), ("tick", "ticked")):
            with self.subTest(browser=browser, moment=moment):
                if done:
                    self.assertTrue(found[moment].pop(done), found)
                self.assertEqual(found[moment], want, found)
        with self.subTest(browser=browser, moment="tabs"):
            self.assertIsNotNone(found["tabs"].pop("tab"), found)
            self.assertEqual(found["tabs"], {"delivered": [True, True, True], "focusins": 0, "same": True}, found)

    def twins(self) -> None:
        now = time.time()
        with (self.council / "news.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(self.jsonl([{"ts": now - 50, "from": "Docs", "to": [], "text": words, "class": "broadcast", "v": 2} for words in DUPS]))

    def check_keys(self, found: dict, browser: str) -> None:
        with self.subTest(browser=browser, case="keys"):
            self.assertEqual(len(set(found["keys"])), len(DUPS), found)
        for words in DUPS:
            with self.subTest(browser=browser, case=words):
                self.assertEqual(found[words], {"delivered": True, "same": True, "line": words, "popup": words}, found)
        with self.subTest(browser=browser, case="filtered"):
            self.assertEqual(found["filtered"], {"gone": True, "pick": True, "class": "call"}, found)
        with self.subTest(browser=browser, case="emptied"):
            self.assertEqual(found["emptied"], {"gone": True, "list": True}, found)

    def check_banner(self, found: dict, browser: str) -> None:
        with self.subTest(browser=browser, moment="steady"):
            self.assertEqual(found["steady"], {"polled": True, "mutations": 0, "focus": True, "body": False}, found)
        with self.subTest(browser=browser, moment="changed"):
            self.assertTrue(found["changed"].pop("text").endswith(NEW_ALARM), found)
            self.assertEqual(found["changed"], {"polled": True, "added": 1, "shown": True, "cancel": True}, found)

    def check(self, data: dict, browser: str) -> None:
        results = iter(data["results"])
        for index, (width, height) in enumerate(WIDTHS):
            layout, popup, closing, home, fit = (next(results) for _ in range(5))
            with self.subTest(browser=browser, width=width, part="layout"):
                self.check_layout(layout, (width, height), index, browser)
            with self.subTest(browser=browser, width=width, part="popup"):
                self.check_popup(popup)
            with self.subTest(browser=browser, width=width, part="close and reply"):
                self.assertTrue(closing["escaped"], closing)
                self.assertEqual(closing["outside"], [True, True], closing)
                self.assertEqual(closing["reply"], {"open": False, "channel": "post", "recipient": "Stage", "toShown": True, "focused": True}, closing)
            with self.subTest(browser=browser, width=width, part="home"):
                self.check_home(home, width)
            with self.subTest(browser=browser, width=width, part="fit view"):
                self.check_fit(fit, (width, height))

    def test_chromium_lays_the_radio_out_without_overflow_one_line_rows_popup_and_four_home_stars_at_four_widths(self):
        data = self.drive(self.steps("chromium"), None)
        (OUT / "chromium-radio-layout.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        self.check(data, "chromium")

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_lays_the_radio_out_without_overflow_one_line_rows_popup_and_four_home_stars_at_four_widths(self):
        data = self.drive(self.steps("firefox"), None, "bidi.mjs", os.environ.get("FIREFOX", "firefox"))
        (OUT / "firefox-radio-layout.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        self.check(data, "firefox")

    def test_chromium_leaves_the_focus_where_a_click_lands_and_returns_it_to_the_toggle_only_on_escape(self):
        data = self.drive(self.focus_steps("chromium"), None)
        (OUT / "chromium-radio-focus.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        self.check_focus(data, "chromium")

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_leaves_the_focus_where_a_click_lands_and_returns_it_to_the_toggle_only_on_escape(self):
        data = self.drive(self.focus_steps("firefox"), None, "bidi.mjs", os.environ.get("FIREFOX", "firefox"))
        (OUT / "firefox-radio-focus.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        self.check_focus(data, "firefox")

    def test_chromium_holds_the_focus_on_a_history_row_and_its_tab_across_new_rows_and_the_minute_tick(self):
        self.check_rows(self.watch("chromium", "rows", ROWS), "chromium")

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_holds_the_focus_on_a_history_row_and_its_tab_across_new_rows_and_the_minute_tick(self):
        self.check_rows(self.watch("firefox", "rows", ROWS), "firefox")

    def test_chromium_keys_twin_rows_apart_and_moves_the_focus_of_a_filtered_out_row_to_the_nearest_row_or_the_list(self):
        self.twins()
        self.check_keys(self.watch("chromium", "keys", KEYS), "chromium")

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_keys_twin_rows_apart_and_moves_the_focus_of_a_filtered_out_row_to_the_nearest_row_or_the_list(self):
        self.twins()
        self.check_keys(self.watch("firefox", "keys", KEYS), "firefox")

    def test_chromium_redraws_the_mayday_banner_only_when_the_silence_changes(self):
        self.silence(ALARMS["mayday"])
        self.check_banner(self.watch("chromium", "banner", BANNER), "chromium")

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_redraws_the_mayday_banner_only_when_the_silence_changes(self):
        self.silence(ALARMS["mayday"])
        self.check_banner(self.watch("firefox", "banner", BANNER), "firefox")

    def test_chromium_keeps_the_main_floor_and_reachable_radio_controls_in_six_states_on_both_sides_of_the_height_threshold(self):
        data = self.laptops("chromium")
        (OUT / "chromium-radio-laptops.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        self.check_laptops(data, "chromium")

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_keeps_the_main_floor_and_reachable_radio_controls_in_six_states_on_both_sides_of_the_height_threshold(self):
        data = self.laptops("firefox", "bidi.mjs", os.environ.get("FIREFOX", "firefox"))
        (OUT / "firefox-radio-laptops.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        self.check_laptops(data, "firefox")

    def test_chromium_places_the_station_popover_inside_every_clip_and_closes_it_on_escape_and_outside_clicks_in_the_spot_and_on_home(self):
        data = self.drive(self.popover_steps("chromium"), None)
        (OUT / "chromium-radio-popover.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        self.check_popover(data, "chromium")

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_places_the_station_popover_inside_every_clip_and_closes_it_on_escape_and_outside_clicks_in_the_spot_and_on_home(self):
        data = self.drive(self.popover_steps("firefox"), None, "bidi.mjs", os.environ.get("FIREFOX", "firefox"))
        (OUT / "firefox-radio-popover.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        self.check_popover(data, "firefox")

    def test_chromium_home_copies_keep_their_own_composer_record_reply_and_cancel_the_mayday(self):
        now = time.time()
        self.write_council({"radio-silence.json": {"since": now - 60, "until": now + 3600, "by": "Docs", "text": "disk full"}})
        steps = []
        for width, height in ((1366, 768), (390, 844)):
            shot = str(OUT / f"chromium-{width}")
            steps += [
                {"width": width, "height": height, "url": f"http://localhost:{self.port}/?{width}-copies#stream", "wait": 1500, "probe": probe(COMPOSE_HOME), "shot": f"{shot}-home-composers.png", "gesture": True},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(REPLY_HOME), "shot": f"{shot}-home-reply.png"},
            ]
        data = self.drive(steps, self.authenticator())
        (OUT / "chromium-radio-home-copies.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        results = iter(data["results"])
        question = "Lift the radio silence of the active mayday?"
        for width in (1366, 390):
            composed, replied = next(results), next(results)
            with self.subTest(width=width, part="own composer state"):
                self.assertEqual(composed["drafts"], ["draft kept in the spot", "", ""], composed)
                self.assertEqual((composed["first"], composed["handed"]), ("true", ["false", "true"]), composed)
                self.assertIn("hello from the mic", composed["spotHeard"] or "", composed)
                self.assertNotIn("hello from the mic", composed["homeBefore"], composed)
                self.assertIn("hello from the mic", composed["homeHeard"] or "", composed)
                self.assertTrue(all(composed["notes"]) and composed["notes"][0] != composed["notes"][1], composed)
                self.assertTrue((composed["spotSent"] or "").startswith("Post to Stage: sent"), composed)
                self.assertTrue(composed["homeAttach"], composed)
                self.assertTrue((composed["homeSent"] or "").startswith("Post to Docs: sent"), composed)
                self.assertEqual(composed["bodies"], [["Stage", "plain text from the spot", ""], ["Docs", "voice from the Home tile", composed["notes"][1]]], composed)
            with self.subTest(width=width, part="reply and mayday from Home"):
                self.assertEqual(replied["fromLog"], {"spot": "false", "popup": False, "speak": {"channel": "post", "recipient": "Stage", "toShown": True, "focused": True},
                                                      "whole": {"channel": "post", "recipient": replied["fromLog"]["whole"]["recipient"], "toShown": True, "focused": False}}, replied)
                self.assertEqual(replied["fromWhole"], {"spot": "false", "whole": {"channel": "post", "recipient": "Stage", "toShown": True, "focused": True}}, replied)
                self.assertTrue((replied["sent"] or "").startswith("Post to Stage: sent"), replied)
                self.assertEqual((replied["enabled"], replied["questions"]), (True, [question]), replied)
                self.assertTrue((replied["lifted"] or "").startswith("Cancel mayday: done"), replied)
                self.assertEqual(replied["spot"], "false", replied)
        radio = [args for script, args in self.scripts.calls if script == skill_scripts.RADIO]
        self.assertEqual([args[:3] for args in radio if args[0] == "post"], [["post", "--to", "Stage"], ["post", "--to", "Docs"], ["post", "--to", "Stage"]] * 2, radio)
        self.assertEqual([args for args in radio if args[0] == "clear"], [["clear", "--force", "--session", "Operator"]] * 2, radio)


if __name__ == "__main__":
    unittest.main()
