from __future__ import annotations

import array
import base64
import contextlib
import http.server
import json
import math
import os
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from collections.abc import Callable
from pathlib import Path
from unittest import mock
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from hub_case import HubCase
from hub_engines import wav_bytes
from hub_support import ASK, HOST_STATE, RUNNER, iso, verifier
from kvb_orchestrator import skill_scripts
from test_hub_cleanup import DONE_TIP, FAKE_PKGMGR, host
from test_hub_offices import COUNCIL_SCRIPT
from test_hub_offices import host as office_host

OUT = Path(os.environ.get("E2E_OUT", "/tmp/orchestrator-phase4-shots"))
WIDTHS = ((1920, 1080), (1366, 768), (390, 844))
VIEWS = ("orbit", "chord", "swimlane", "tree", "3d")
TASK_VIEWS = ("list", "board", "rasci")
SCREENS = ["stream", "stream/inbox", "stream/rules", "stream/radio", *(f"{tab}/{view}" for tab in ("agents", "artifacts") for view in VIEWS), "agents/hierarchy", *(f"tasks/{view}" for view in TASK_VIEWS)]
SUBS = ["Inbox", "Firewall", "Radio"]
TABS = ["Stream", "Agents", "Artifacts", "Tasks"]
HELPERS = """
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const until = async (check, ms) => {
    const end = Date.now() + ms;
    while (Date.now() < end) {
      const found = check();
      if (found) {
        return found;
      }
      await sleep(200);
    }
    return null;
  };
  const all = (selector, root) => [...(root || document).querySelectorAll(selector)];
  const text = (node) => (node ? node.textContent.trim() : null);
  const name = (node) => (node ? node.getAttribute("aria-label") || text(node) : null);
"""
PROBE = """(async () => {@HELPERS@
  await until(() => !document.querySelector("#main .space-note") || !text(document.querySelector("#main .space-note")).startsWith("Loading"), 8000);
  const badge = (button) => {
    const found = button.querySelector(".badge");
    return found && !found.hidden ? text(found) : null;
  };
  const icons = all("svg.bi").filter((svg) => !svg.closest(".sprite"));
  const banner = document.getElementById("mayday");
  return {
    hash: location.hash,
    title: document.title,
    h1: text(document.querySelector("h1")),
    header: all("header.top button").map((button) => button.id),
    tabs: all("#tabs > .tab-group > button").map(name),
    subs: all("#tabs .subtabs button").map(name),
    badges: Object.fromEntries(all("#tabs button").map((button) => [button.id, badge(button)])),
    banner: banner.hidden ? null : text(banner),
    rail: Boolean(document.getElementById("rail")),
    views: all('#main [aria-label="View"] button').map(name),
    layouts: all('#main [aria-label="Layout"] button').map(name),
    chips: all('#main [aria-label="Categories"] button').map(name),
    menus: all("#main details.menu > summary").map(name),
    time: text(document.querySelector("#time > summary")),
    replay: Boolean(document.querySelector("#time .replay input[type=range]")),
    custom: Boolean(document.querySelector('#main details.menu input[type="datetime-local"]')),
    toolbar: all('#main [role="toolbar"] > *').map((node) => name(node.tagName === "DETAILS" ? node.querySelector("summary") : node.querySelector("button") || node)),
    toAll: all("#to-all input[type=radio]").map((input) => [input.value, input.checked]),
    inbox: all("#main .inbox-list > li").length,
    icons: icons.length,
    unlabelled: icons.map((svg) => svg.parentElement).filter((owner) => !text(owner) && !(owner.getAttribute("title") && owner.getAttribute("aria-label"))).map((owner) => owner.outerHTML.slice(0, 160)),
    broken: all("svg.bi use").filter((use) => !document.getElementById(use.getAttribute("href").slice(1))).map((use) => use.getAttribute("href")),
    states: all("#main span.state").map(name),
    deletes: all('#main button[aria-label="Delete"], #main button[aria-label="Delete all merged"]').map((button) => [name(button), button.disabled, button.title]),
    spawn: all("#main .spawn-tree li").map((item) => [item.dataset.kind, item.dataset.running || null]),
    marks: all("#main svg.chart .node").length,
    note: text(document.querySelector("#main .space-note")),
    canvas: Boolean(document.querySelector("#main .graph3d canvas")),
    org: all("#main .org-chart .org-row[data-office]").map((row) => [row.dataset.office, text(row.querySelector(".org-holder"))]),
    toggles: all("#main .org-toggle").map((button) => [name(button), button.getAttribute("aria-expanded")]),
    order: all("#main .agent-order li").map((item) => item.dataset.name),
    taskFilters: all('#main [aria-label="Task filters"] button').map((button) => [button.dataset.filter, button.getAttribute("aria-pressed"), text(button.querySelector(".count"))]),
    taskRows: all("#main .task-row").map((row) => [row.dataset.task, row.classList.contains("open-work")]),
    columns: all("#main .task-column").map((column) => [column.dataset.column, all(".task-card", column).map((card) => card.dataset.task)]),
    matrix: [all("#main table.matrix thead th").length, all("#main table.matrix tbody tr").length, all("#main table.matrix td .letter").map(text).join("")],
    flows: all("#main .flow").map((flow) => flow.dataset.flow),
    flowEdges: all("#main svg.chart path.flow").map((path) => path.dataset.side),
    openWork: all("#main .open-work").length,
    panel: all("#drawer, .drawer, #main aside, #main .panel, #main .graph-body").length,
    nodeChips: all("#main .space-list, #main .chip[data-node]").length,
    wide: document.documentElement.scrollWidth > window.innerWidth + 1,
    tall: document.documentElement.scrollHeight > window.innerHeight,
  };
})()""".replace("@HELPERS@", HELPERS)
ORG_OPEN = """(async () => {@HELPERS@
  const row = await until(() => document.querySelector('#main .org-row[data-office="identity/oidc"]'), 8000);
  if (!row) {
    return {error: text(document.getElementById("main"))};
  }
  const toggle = all("#main .org-toggle").find((button) => name(button) === "Collapse: identity");
  toggle.focus();
  return {focused: document.activeElement.dataset.focus, offices: all("#main .org-row[data-office]").map((entry) => entry.dataset.office)};
})()""".replace("@HELPERS@", HELPERS)
ORG_FOLDED = """(async () => {@HELPERS@
  const toggle = document.activeElement;
  const folded = {focused: toggle.dataset.focus, expanded: toggle.getAttribute("aria-expanded"), label: name(toggle), hidden: document.getElementById(toggle.getAttribute("aria-controls")).hidden, seen: all("#main .org-row[data-office]").filter((entry) => entry.offsetParent !== null).map((entry) => entry.dataset.office)};
  toggle.click();
  await sleep(200);
  const before = all("#main .agent-order li").map((item) => item.dataset.name);
  all("#main .agent-order li")[1].querySelector('[data-focus^="up:"]').focus();
  return {...folded, again: toggle.getAttribute("aria-expanded"), before};
})()""".replace("@HELPERS@", HELPERS)
ORDER_MOVED = """(async () => {@HELPERS@
  const after = all("#main .agent-order li").map((item) => item.dataset.name);
  const focused = document.activeElement.dataset.focus || null;
  const save = all("#main .agent-order button").find((button) => text(button) === "Save order");
  const disabled = save.disabled;
  save.click();
  const toast = await until(() => all("#toasts .toast").find((box) => text(box).startsWith("Priority")), 8000);
  return {after, focused, disabled, toast: text(toast)};
})()""".replace("@HELPERS@", HELPERS)
OPEN_TAKEOVER = """(async () => {@HELPERS@
  document.querySelector('#main [data-focus="takeover:identity/oidc"]').click();
  await sleep(400);
  return {title: text(document.querySelector(".sheet-head .panel-title")), options: all(".sheet-box select option").map((option) => option.value), work: document.querySelector('.sheet-box input[aria-label="Work"]').value, focused: document.activeElement.tagName};
})()""".replace("@HELPERS@", HELPERS)
CONFIRM_TAKEOVER = """(async () => {@HELPERS@
  all(".sheet-box button").find((button) => name(button) === "Hand over").click();
  const done = await until(() => document.querySelector(".sheet-box [data-result]"), 30000);
  return {result: done ? done.dataset.result : null, text: text(done), toasts: all("#toasts .toast").map(text)};
})()""".replace("@HELPERS@", HELPERS)
AFTER_TAKEOVER = """(async () => {@HELPERS@
  document.querySelector(".sheet-head button").click();
  const row = await until(() => {
    const found = document.querySelector('#main .org-row[data-office="identity/oidc"] .org-holder');
    return found && !text(found).endsWith("Stage") ? found : null;
  }, 15000);
  return {holder: text(row)};
})()""".replace("@HELPERS@", HELPERS)
INBOX_CHIP = """(async () => {@HELPERS@
  const chip = (id) => document.querySelector(`#main [aria-label="Task filters"] button[data-filter="${id}"]`);
  chip("operator").click();
  await until(() => location.hash === "#stream/inbox" && document.querySelector("#main .inbox-list"), 4000);
  const inbox = {hash: location.hash, items: all("#main .inbox-list > li").length, counted: Number(text(chip("operator").querySelector(".count"))), pressed: chip("operator").getAttribute("aria-pressed"), current: all("#tabs button[aria-current=page]").map(name)};
  chip("grant").click();
  await until(() => location.hash.startsWith("#tasks/"), 4000);
  await sleep(300);
  return {inbox, back: {hash: location.hash, rows: all("#main .task-row").map((row) => [row.dataset.task, text(row.querySelector(".pill"))])}};
})()""".replace("@HELPERS@", HELPERS)
PIN = """(async () => {@HELPERS@
  const row = await until(() => all("#main .task-row").find((item) => item.dataset.task === "work/docs"), 8000);
  if (!row) {
    return {error: text(document.getElementById("main"))};
  }
  row.querySelector('button[aria-label="Priority"]').click();
  await sleep(400);
  const field = document.querySelector('.sheet-box input[aria-label="Priority"]');
  field.value = "2";
  field.dispatchEvent(new Event("input", {bubbles: true}));
  const preview = all(".sheet-box .task-edit .command code").map(text);
  all(".sheet-box button").find((button) => name(button) === "Pin").click();
  const done = await until(() => document.querySelector(".sheet-box [data-jobs]"), 20000);
  return {title: text(document.querySelector(".sheet-head .panel-title")), preview, jobs: done ? done.dataset.jobs : null, toasts: all("#toasts .toast").map(text)};
})()""".replace("@HELPERS@", HELPERS)
ACTIONS = """(async () => {@HELPERS@
  const press = async (key) => {
    document.dispatchEvent(new KeyboardEvent("keydown", {key, bubbles: true}));
    await sleep(300);
    return location.hash;
  };
  const found = {keys: [await press("2"), await press("3"), await press("4"), await press("1")]};
  document.getElementById("settings-open").click();
  await sleep(300);
  found.ambience = all(".sheet-box form > section:first-child button").map((button) => button.id);
  found.speech = all('.sheet-box [aria-label="Classes"] input').map((input) => [input.parentElement.textContent.trim(), input.checked, input.disabled]);
  found.settingsUnlabelled = all(".sheet-box svg.bi").map((svg) => svg.parentElement).filter((owner) => !text(owner) && !(owner.getAttribute("title") && owner.getAttribute("aria-label"))).length;
  document.querySelector(".sheet-head button").click();
  document.getElementById("palette-open").click();
  await sleep(300);
  found.palette = all(".palette-list li > span:first-child").map(text);
  document.dispatchEvent(new KeyboardEvent("keydown", {key: "Escape", bubbles: true}));
  await sleep(200);
  document.querySelector('#main [aria-label="Categories"] button:nth-child(2)').click();
  await sleep(900);
  document.querySelector('#main button.linkish[title^="Open "]').click();
  await sleep(500);
  found.popup = all("#popup input[type=radio]").map((input) => [input.value, input.checked]);
  found.popupUnlabelled = all("#popup svg.bi").map((svg) => svg.parentElement).filter((owner) => !text(owner) && !(owner.getAttribute("title") && owner.getAttribute("aria-label"))).length;
  found.centred = [document.getElementById("popup").open, document.querySelector("#popup .leader line").getAttribute("display")];
  return found;
})()""".replace("@HELPERS@", HELPERS)
POPUPS = """
  const dialog = document.getElementById("popup");
  const box = dialog.querySelector(".popup-box");
  const line = dialog.querySelector(".leader line");
  const click = (target) => target.dispatchEvent(new MouseEvent("click", {bubbles: true, cancelable: true}));
  const tint = document.createElement("i");
  tint.style.color = "var(--alarm)";
  document.body.append(tint);
  const red = getComputedStyle(tint).color;
  tint.remove();
  const tall = () => document.documentElement.scrollHeight > innerHeight;
  const look = (node) => ({picked: node.classList.contains("picked"), size: Math.round(node.querySelector("circle").getBoundingClientRect().width), red: getComputedStyle(node.querySelector("circle")).fill === red});
  const opened = () => {
    const rect = box.getBoundingClientRect();
    const ends = line.getAttribute("display") === "none" ? null : ["x1", "y1", "x2", "y2"].map((key) => Number(line.getAttribute(key)));
    return {
      open: dialog.open, fade: [dialog.classList.contains("fade"), getComputedStyle(dialog).animationName], title: text(box.querySelector(".panel-title")), opacity: Number(getComputedStyle(box).opacity), line: ends,
      onBox: Boolean(ends) && (Math.abs(ends[2] - rect.left) < 1 || Math.abs(ends[2] - rect.right) < 1 || Math.abs(ends[3] - rect.top) < 1 || Math.abs(ends[3] - rect.bottom) < 1),
      inside: rect.left >= 0 && rect.top >= 0 && rect.right <= innerWidth && rect.bottom <= innerHeight,
      tall: tall(), wide: document.documentElement.scrollWidth > innerWidth + 1, panel: all("#drawer, .drawer, #main aside, #main .panel, #main .graph-body").length,
    };
  };
  const away = async (pick) => {
    const outside = document.elementFromPoint(2, innerHeight - 2);
    click(outside);
    await sleep(250);
    return {...look(pick()), open: dialog.open, outside: outside === dialog};
  };
"""
POPUP_ORBIT = """(async () => {@HELPERS@@POPUPS@
  const pick = () => document.querySelector('#main svg .node[data-pick="s2"]');
  if (!(await until(pick, 8000))) {
    return {error: text(document.getElementById("main"))};
  }
  const before = look(pick());
  const flat = !tall();
  click(pick());
  await sleep(400);
  const shown = {...opened(), ...look(pick()), sections: all("h3", box).map((head) => head.firstChild.textContent), composer: Boolean(box.querySelector("form textarea")), offices: text(box.querySelector(".popup-body p"))};
  const gone = await away(pick);
  click(pick());
  await sleep(300);
  const again = dialog.open;
  (document.activeElement || document.body).dispatchEvent(new KeyboardEvent("keydown", {key: "Escape", bubbles: true}));
  await sleep(250);
  const escaped = {...look(pick()), open: dialog.open, again};
  click(pick());
  await sleep(500);
  return {before, flat, shown, gone, escaped, last: dialog.open};
})()""".replace("@HELPERS@", HELPERS).replace("@POPUPS@", POPUPS)
POPUP_ARTIFACT = """(async () => {@HELPERS@@POPUPS@
  const first = await until(() => document.querySelector('#main svg .node[data-pick^="branch:"]'), 8000);
  if (!first) {
    return {error: text(document.getElementById("main"))};
  }
  const id = first.dataset.pick;
  const pick = () => all("#main svg .node[data-pick]").find((node) => node.dataset.pick === id);
  const before = look(pick());
  const flat = !tall();
  click(pick());
  await sleep(400);
  const shown = {...opened(), ...look(pick()), label: first.getAttribute("aria-label").split(",")[0]};
  const gone = await away(pick);
  click(pick());
  await sleep(400);
  return {before, flat, shown, gone, last: dialog.open};
})()""".replace("@HELPERS@", HELPERS).replace("@POPUPS@", POPUPS)
PICK_3D = """(async () => {@HELPERS@
  const field = await until(() => document.querySelector('#main input[aria-label="Find a node"]'), 8000);
  const ready = await until(() => document.querySelector("#main .graph3d canvas") && !text(document.querySelector("#main .space-note")).startsWith("Loading"), 8000);
  if (!field || !ready) {
    return {error: text(document.querySelector("#main .graph"))};
  }
  const type = async (value) => {
    field.value = value;
    field.dispatchEvent(new Event("input", {bubbles: true}));
    await sleep(150);
    return all("#main .hits .chip").map((chip) => [chip.dataset.hit, text(chip)]);
  };
  const tree = await (await fetch("/api/tree", {cache: "no-store"})).json();
  const found = {empty: await type(""), twins: tree.repos.flatMap((repo) => repo.branches).filter((branch) => branch.name === "main").length, twin: await type("main"), hits: await type("@QUERY@")};
  found.flat = document.documentElement.scrollHeight <= innerHeight;
  const chip = all("#main .hits .chip").find((node) => node.dataset.hit.startsWith("@PREFIX@"));
  if (!chip) {
    return {error: found};
  }
  chip.click();
  await sleep(600);
  const dialog = document.getElementById("popup");
  const line = dialog.querySelector(".leader line");
  const host = () => document.querySelector("#main .graph3d");
  found.opened = {
    open: dialog.open, title: text(dialog.querySelector(".popup-box .panel-title")), label: text(chip), hit: chip.dataset.hit, picked: host().dataset.picked || null,
    line: line.getAttribute("display") !== "none", lists: all("#main .space-list, #main .chip[data-node]").length, flat: document.documentElement.scrollHeight <= innerHeight,
  };
  dialog.dispatchEvent(new MouseEvent("click", {bubbles: true}));
  await sleep(300);
  found.closed = {open: dialog.open, picked: host().dataset.picked || null};
  chip.click();
  await sleep(600);
  return found;
})()""".replace("@HELPERS@", HELPERS)
CALL = """(async () => {@HELPERS@
  document.querySelector('#main [aria-label="Categories"] button[aria-label="Radio"]').click();
  const someone = await until(() => document.querySelector('#main button.linkish[title^="Open "]'), 8000);
  someone.click();
  await sleep(500);
  document.querySelector('#popup input[type=radio][value="call"]').click();
  const field = document.querySelector("#popup textarea");
  field.value = "E2E call ping";
  field.dispatchEvent(new Event("input", {bubbles: true}));
  document.querySelector('#popup button[type="submit"]').click();
  const entry = await until(() => all("#main .entry").find((row) => row.textContent.includes("Read") && row.textContent.includes("E2E call ping")), 20000);
  return {to: text(someone), receipt: entry ? text(entry) : null, sent: all("#main .entry").filter((row) => row.textContent.includes("E2E call ping")).length};
})()""".replace("@HELPERS@", HELPERS)
OPEN_DELETE = """(async () => {@HELPERS@
  const card = await until(() => all("#main details.repo").find((details) => details.textContent.includes("github.com/me/demo")), 8000);
  if (!card) {
    return {error: text(document.getElementById("main"))};
  }
  card.open = true;
  await sleep(300);
  const every = document.querySelector('#main button[aria-label="Delete all merged"]');
  const buttons = all('button[aria-label="Delete"]', card);
  const states = all("span.state", card).map(name);
  buttons.find((button) => !button.disabled).click();
  await sleep(500);
  return {states, every: [every.disabled, every.title], buttons: buttons.map((button) => [button.disabled, button.title]), title: text(document.querySelector(".sheet-head .panel-title")), dry: all('.sheet-box [aria-label="Dry run"] pre').map(text)};
})()""".replace("@HELPERS@", HELPERS)
CONFIRM = """(async () => {@HELPERS@
  all(".sheet-box button").find((button) => name(button) === "Delete").click();
  const done = await until(() => document.querySelector(".sheet-box [data-result]"), 30000);
  const job = document.querySelector(".sheet-box [data-cleanup]");
  return {job: job ? job.dataset.cleanup : null, result: done ? done.dataset.result : null, text: text(done), toasts: all("#toasts .toast").map(text)};
})()""".replace("@HELPERS@", HELPERS)
AFTER = """(async () => {@HELPERS@
  document.querySelector(".sheet-head button").click();
  const past = await until(() => all("#main details.repo").find((details) => details.textContent.includes("Recently deleted")), 15000);
  return {past: past ? [past.querySelector("[data-result]").dataset.result, name(past.querySelector("span.state"))] : null, branches: all("#main details.repo").filter((details) => details !== past).flatMap((details) => all(".branch-name strong", details)).map(text)};
})()""".replace("@HELPERS@", HELPERS)
OVERLAP = """
  const shown = (node) => node.getClientRects().length > 0 && node.getBoundingClientRect().width > 0;
  const words = (label) => [...label.childNodes].filter((node) => node.nodeType === 3).map((node) => node.textContent).join("").trim();
  const called = (node) => node.getAttribute("aria-label") || (node.closest("label") ? words(node.closest("label")) : "") || text(node) || node.type;
  const clashes = (root) => {
    const boxes = all("input, select, textarea, button", root).filter(shown).map((node) => ({node, box: node.getBoundingClientRect()}));
    const found = [];
    boxes.forEach((a, index) => boxes.slice(index + 1).forEach((b) => {
      const x = Math.min(a.box.right, b.box.right) - Math.max(a.box.left, b.box.left);
      const y = Math.min(a.box.bottom, b.box.bottom) - Math.max(a.box.top, b.box.top);
      if (x > 0.5 && y > 0.5) {
        found.push(`${called(a.node)} × ${called(b.node)}`);
      }
    }));
    const outside = boxes.filter(({box}) => box.right > root.getBoundingClientRect().right + 0.5).map(({node}) => called(node));
    return {found, outside};
  };
"""
RULES_OVERLAP = """(async () => {@HELPERS@@CLASHES@
  const open = document.querySelector(".sheet-head button");
  if (open) {
    open.click();
  }
  const rules = await until(() => document.querySelector("#main .rule-form"), 8000);
  const kind = rules.querySelector("select");
  const found = {};
  for (const value of ["decision", "review", "ask"]) {
    kind.value = value;
    kind.dispatchEvent(new Event("change", {bubbles: true}));
    await sleep(150);
    found[value] = {...clashes(rules), labels: all("label", rules).filter(shown).map(words)};
  }
  return found;
})()""".replace("@HELPERS@", HELPERS).replace("@CLASHES@", OVERLAP)
SETTINGS_OVERLAP = """(async () => {@HELPERS@@CLASHES@
  document.getElementById("settings-open").click();
  const settings = await until(() => document.querySelector(".sheet-box form.settings"), 8000);
  all("button", settings).find((button) => text(button) === "+ Station").click();
  const theme = all("select", settings).find((select) => [...select.options].some((option) => option.value === "custom"));
  theme.value = "custom";
  theme.dispatchEvent(new Event("change", {bubbles: true}));
  await sleep(250);
  const place = all("section", settings).find((section) => text(section.querySelector("h3")) === "Location");
  place.scrollIntoView({block: "start"});
  return clashes(settings);
})()""".replace("@HELPERS@", HELPERS).replace("@CLASHES@", OVERLAP)
MEDIA_LOG = """() => {
  const keep = (entry) => {
    try {
      const list = JSON.parse(sessionStorage.getItem("e2e-media") || "[]");
      list.push({...entry, page: Math.round(performance.timeOrigin)});
      sessionStorage.setItem("e2e-media", JSON.stringify(list));
    } catch (error) {
      return;
    }
  };
  const play = HTMLMediaElement.prototype.play;
  HTMLMediaElement.prototype.play = function () {
    window.e2eAudio = this;
    const src = this.getAttribute("src") || "";
    const result = play.call(this);
    result.then(() => keep({play: "ok", src}), (error) => keep({play: error.name, src}));
    return result;
  };
  document.addEventListener("securitypolicyviolation", (event) => keep({csp: event.effectiveDirective, blocked: event.blockedURI}));
}"""
MEDIA = """
  const log = () => JSON.parse(sessionStorage.getItem("e2e-media") || "[]");
  const sample = () => (window.e2eAudio ? {paused: window.e2eAudio.paused, time: window.e2eAudio.currentTime, error: window.e2eAudio.error ? window.e2eAudio.error.code : null, src: window.e2eAudio.getAttribute("src")} : null);
  const advancing = async () => {
    const first = sample();
    await sleep(1500);
    const second = sample();
    return {first, second, playing: Boolean(first && second && !second.paused && second.time - first.time > 0.5)};
  };
"""
ADD_STATION = """(async () => {@HELPERS@
  const clock = (date) => `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
  document.getElementById("settings-open").click();
  const form = await until(() => document.querySelector(".sheet-box form.settings"), 8000);
  all("button", form).find((button) => text(button) === "+ Station").click();
  await sleep(200);
  const row = all(".stream-row", form).pop();
  const [label, address, start, end] = all("input.field", row);
  const set = (input, value) => {
    input.value = value;
    input.dispatchEvent(new Event("input", {bubbles: true}));
  };
  set(label, "@NAME@");
  set(address, "@STATION@");
  set(start, clock(new Date(Date.now() - 3600000)));
  set(end, clock(new Date(Date.now() + 3600000)));
  all('.days input[type="checkbox"]', row).forEach((box) => {
    box.checked = true;
  });
  all("button", form).find((button) => button.type === "submit").click();
  await until(() => all("#toasts .toast").map(text).find((toast) => toast.startsWith("New station")), 8000);
  return {toasts: all("#toasts .toast").map(text)};
})()""".replace("@HELPERS@", HELPERS)
STATION_NAME = "E2E tone with a very long station name that fits on no single line"
DLF_PATH = "/dlf/01/high/aac/stream.aac?aggregator=web"
DLF_NODE = "/ard/dlf/01/aac/192/stream.aac?aggregator=web"
RADIO_STATE = """(async () => {@HELPERS@@MEDIA@
  await until(() => log().some((entry) => entry.play), 8000);
  return {log: log(), media: await advancing(), toasts: all("#toasts .toast").map(text)};
})()""".replace("@HELPERS@", HELPERS).replace("@MEDIA@", MEDIA)
RADIO_VIEW = """(async () => {@HELPERS@@MEDIA@
  location.hash = "#stream/radio";
  const row = await until(() => document.querySelector('#main [data-station="0"]'), 8000);
  if (!row) {
    const initial = JSON.parse(document.getElementById("state").textContent);
    return {error: "no station row", log: log(), wrapped: !String(HTMLMediaElement.prototype.play).includes("[native code]"), streams: initial.settings.streams, media: initial.media, now: new Date().toString()};
  }
  const label = row.querySelector(".station-name");
  const style = getComputedStyle(label);
  return {
    state: row.dataset.state,
    note: text(row.querySelector(".station-note")),
    title: label.title,
    line: [style.whiteSpace, style.textOverflow, label.scrollWidth > label.clientWidth, label.getBoundingClientRect().height < 2 * parseFloat(style.lineHeight)],
    media: await advancing(),
    log: log(),
    toasts: all("#toasts .toast").map(text),
  };
})()""".replace("@HELPERS@", HELPERS).replace("@MEDIA@", MEDIA)
RADIO_CLICK = """(async () => {@HELPERS@@MEDIA@
  const row = document.querySelector('#main [data-station="0"]');
  if (!row) {
    return {error: "no station row", log: log(), media: await advancing()};
  }
  const play = row.querySelector('button[data-action="play"]');
  const clicked = Boolean(sample() && sample().paused && play);
  if (clicked) {
    play.click();
  }
  await until(() => sample() && !sample().paused, 6000);
  const media = await advancing();
  const now = document.querySelector('#main [data-station="0"]');
  return {clicked, state: now.dataset.state, note: text(now.querySelector(".station-note")), media, log: log()};
})()""".replace("@HELPERS@", HELPERS).replace("@MEDIA@", MEDIA)
SPEAKING = """
  const caption = () => {
    const node = document.querySelector("#main .radio-caption");
    return node && !node.hidden ? node : null;
  };
  const ring = (chip) => (chip ? getComputedStyle(chip.querySelector(".speaker-face"), "::after").animationName : null);
  const cue = async (word) => {
    await until(() => document.querySelector("#main .speakers .speaker"), 8000);
    await fetch("/api/tts", {method: "POST", headers: {"X-Kvb-Orchestrator": "1", "Content-Type": "application/json"}, body: JSON.stringify({text: word, voice: ""}), cache: "no-store"});
    const found = await until(caption, 25000);
    const chip = document.querySelector("#main .speaker.speaking");
    return found ? {who: text(found.querySelector("strong")), line: text(found.querySelector(".caption-line")), chip: chip ? chip.dataset.key : null, ring: ring(chip)} : {error: "no caption", toasts: all("#toasts .toast").map(text)};
  };
"""
SPEAK = """(async () => {@HELPERS@@SPEAKING@
  return cue("@CUE@");
})()""".replace("@HELPERS@", HELPERS).replace("@SPEAKING@", SPEAKING)
SPEAK_GRAPH = """(async () => {@HELPERS@@SPEAKING@
  location.hash = "#agents/orbit";
  const node = await until(() => document.querySelector("#main svg .node.speaking"), 6000);
  return {node: node ? node.getAttribute("aria-label") : null, ring: node ? getComputedStyle(node.querySelector("circle")).animationName : null};
})()""".replace("@HELPERS@", HELPERS).replace("@SPEAKING@", SPEAKING)
SPEAK_END = """(async () => {@HELPERS@@SPEAKING@
  const ended = Boolean(await until(() => !document.querySelector("#main svg .node") || !document.querySelector("#main svg .node.speaking"), 20000));
  location.hash = "#stream/radio";
  await until(() => document.querySelector("#main .radio-caption"), 6000);
  await sleep(300);
  return {ended, caption: Boolean(caption()), chips: all("#main .speaker.speaking").length};
})()""".replace("@HELPERS@", HELPERS).replace("@SPEAKING@", SPEAKING)
COMPOSE = """(async () => {@HELPERS@
  const form = await until(() => document.querySelector("#main form.composer"), 8000);
  if (!form) {
    return {error: "no composer"};
  }
  const [channel, recipient] = all("select", form);
  await until(() => [...recipient.options].some((option) => option.value === "@TO@"), 8000);
  channel.value = "call";
  channel.dispatchEvent(new Event("change", {bubbles: true}));
  recipient.value = "@TO@";
  const record = all("button", form).find((button) => button.hasAttribute("aria-pressed"));
  record.click();
  await sleep(1500);
  const recording = record.getAttribute("aria-pressed");
  record.click();
  const field = form.querySelector("textarea");
  await until(() => field.value && form.querySelector('.voice-note input[type="checkbox"]'), 60000);
  const replay = form.querySelector(".voice-note audio");
  const attach = form.querySelector('.voice-note input[type="checkbox"]');
  return {
    channels: all("option", channel).map((option) => option.value),
    recipients: all("option", recipient).map((option) => option.value),
    recording,
    text: field.value,
    replay: replay ? replay.getAttribute("src") : null,
    attach: attach ? [text(attach.closest("label")), attach.checked] : null,
    status: text(form.querySelector(".composer-status")),
    toasts: all("#toasts .toast").map(text),
    clashes: (() => {@CLASHES@
      return clashes(form);
    })(),
  };
})()""".replace("@HELPERS@", HELPERS).replace("@CLASHES@", OVERLAP)
COMPOSE_SEND = """(async () => {@HELPERS@
  const form = document.querySelector("#main form.composer");
  const field = form.querySelector("textarea");
  field.value = `${field.value} please`;
  field.dispatchEvent(new Event("input", {bubbles: true}));
  form.querySelector('.voice-note input[type="checkbox"]').checked = @ATTACH@;
  const before = all("#toasts .toast").length;
  form.querySelector('button[type="submit"]').click();
  const sent = await until(() => all("#toasts .toast").slice(before).map(text).find((toast) => toast.startsWith("Call to")), 20000);
  return {sent, left: field.value, voice: Boolean(form.querySelector(".voice-note audio"))};
})()""".replace("@HELPERS@", HELPERS)
CLEAR_MAYDAY = """(async () => {@HELPERS@
  window.confirm = () => true;
  const button = await until(() => all('#main [role="toolbar"] button').find((node) => name(node) === "Cancel mayday" && !node.disabled), 8000);
  if (!button) {
    return {error: "no enabled Cancel mayday button"};
  }
  button.click();
  const done = await until(() => all("#toasts .toast").map(text).find((toast) => toast.startsWith("Cancel mayday")), 15000);
  return {done, toasts: all("#toasts .toast").map(text)};
})()""".replace("@HELPERS@", HELPERS)


def tone(seconds: int, rate: int) -> bytes:
    frames = array.array("h", (int(6000 * math.sin(2 * math.pi * 440 * n / rate)) for n in range(seconds * rate)))
    return wav_bytes(1, 2, rate, frames.tobytes())


class Station(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.server.moved:
            self.send_response(302)
            self.send_header("Location", self.server.moved)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = self.server.body
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        with contextlib.suppress(OSError):
            self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        return


LABELS = """
  const unlabelled = (root) => all("svg.bi", root).filter((svg) => !svg.closest(".sprite")).map((svg) => svg.parentElement).filter((owner) => !text(owner) && !(owner.getAttribute("title") && owner.getAttribute("aria-label"))).map((owner) => owner.outerHTML.slice(0, 160));
  const wide = () => document.documentElement.scrollWidth > window.innerWidth + 1;
  const rowOf = (words) => all("#main .inbox-list > li").find((li) => li.textContent.includes(words));
  const press = (root, label) => all("button", root).find((button) => name(button) === label).click();
  const out = () => document.querySelector("#main .console .console-out");
  const atEnd = () => out().scrollTop + out().clientHeight >= out().scrollHeight - 12;
  const line = () => text(document.querySelector("#main .console .console-status"));
"""
RUN_START = """(async () => {@HELPERS@@LABELS@
  const row = await until(() => rowOf("Row"), 8000);
  if (!row) {
    return {error: text(document.getElementById("main"))};
  }
  press(row, "Run");
  const toast = await until(() => all("#toasts .toast.wait").find((box) => box.textContent.includes("Run")), 8000);
  const queued = await until(() => out() && line(), 15000);
  await until(() => out().textContent.includes("Row 60"), 20000);
  return {toast: text(toast), queued, running: line(), overflows: out().scrollHeight > out().clientHeight, followed: atEnd()};
})()""".replace("@HELPERS@", HELPERS).replace("@LABELS@", LABELS)
RUN_HELD = """(async () => {@HELPERS@@LABELS@
  out().scrollTop = 0;
  await sleep(300);
  await until(() => out().textContent.includes("Row 80"), 20000);
  await sleep(300);
  return {held: out().scrollTop, running: line()};
})()""".replace("@HELPERS@", HELPERS).replace("@LABELS@", LABELS)
RUN_DONE = """(async () => {@HELPERS@@LABELS@
  out().scrollTop = out().scrollHeight;
  await until(() => document.querySelector("#main .console").dataset.status === "done", 20000);
  await sleep(500);
  const lines = out().textContent.trim().split("\\n");
  return {done: line(), last: lines[lines.length - 1], lines: lines.length, followed: atEnd(), actions: all(".item-actions button", out().closest("li")).map(name)};
})()""".replace("@HELPERS@", HELPERS).replace("@LABELS@", LABELS)
LAYOUT = """(async () => {@HELPERS@@LABELS@
  await until(() => document.querySelector("#main .console") && rowOf("Rule request"), 8000);
  const rule = rowOf("Rule request");
  return {
    kinds: all("#main .inbox-list > li").map((li) => text(li.querySelector(".pill"))),
    splits: all("#main .deny-split").map((group) => all("button", group).map(name)),
    console: line(),
    followed: atEnd(),
    fits: out().getBoundingClientRect().right <= window.innerWidth,
    dry: text(rule.querySelector(".dry-run-count")),
    fields: all(".rule-request dt", rule).map(text),
    accept: all("button", rule).filter((button) => name(button) === "Accept").length,
    unlabelled: unlabelled(document),
    wide: wide(),
  };
})()""".replace("@HELPERS@", HELPERS).replace("@LABELS@", LABELS)
DENY_SHEET = """(async () => {@HELPERS@@LABELS@
  const row = await until(() => rowOf("git push"), 8000);
  press(row, "Deny via …");
  const box = await until(() => document.querySelector(".sheet-box"), 4000);
  return {
    title: text(box.querySelector(".panel-title")),
    channels: all(".deny-channels input[type=radio]", box).map((input) => [input.value, input.checked]),
    hints: all(".deny-channel small", box).map(text),
    reason: Boolean(box.querySelector("textarea")),
    unlabelled: unlabelled(box),
    wide: wide(),
  };
})()""".replace("@HELPERS@", HELPERS).replace("@LABELS@", LABELS)
DENY = """(async () => {@HELPERS@@LABELS@
  const row = await until(() => rowOf("Bash: make deploy"), 8000);
  press(row, "Deny via …");
  const box = await until(() => document.querySelector(".sheet-box"), 4000);
  box.querySelector('input[value="call"]').click();
  box.querySelector("textarea").value = "make the gate green first";
  press(box.querySelector(".actions"), "Deny");
  const undo = await until(() => all("#toasts .toast.wait").find((toast) => toast.textContent.includes("Denial")), 8000);
  return {undo: text(undo), sheet: !document.getElementById("sheet").hidden};
})()""".replace("@HELPERS@", HELPERS).replace("@LABELS@", LABELS)
DENIED = """(async () => {@HELPERS@@LABELS@
  return {gone: Boolean(await until(() => !rowOf("Bash: make deploy"), 20000))};
})()""".replace("@HELPERS@", HELPERS).replace("@LABELS@", LABELS)
ACCEPT = """(async () => {@HELPERS@@LABELS@
  press(rowOf("Rule request"), "Accept");
  const toast = await until(() => all("#toasts .toast").find((box) => box.textContent.includes("Created: Rule")), 15000);
  await until(() => !rowOf("Rule request"), 8000);
  return {toast: text(toast), left: Boolean(rowOf("Rule request"))};
})()""".replace("@HELPERS@", HELPERS).replace("@LABELS@", LABELS)
SLOW = "seq -f 'Row %g' 1 60; sleep 4; seq -f 'Row %g' 61 80; sleep 4; echo finished"


def labelled(probe: dict) -> dict:
    return {key: probe[key] for key in ("unlabelled", "broken")}


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestOrchestratorE2E(HubCase):
    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        now = time.time()
        self.root = self.write_tree()
        feature = f"{self.root}/worktrees/github.com/me/demo/feature"
        self.claim("s1", "Skills session")
        self.write_council({
            "work/s2/claim.json": {"office": "work/s2", "session": "s2", "runtime": "claude", "name": "Stage", "since": iso(now - 7200), "beat": now - 2000, "work": "x"},
            "chair/claim.json": {"office": "chair", "session": "s1", "runtime": "claude", "name": "Skills session", "since": iso(now - 7200), "beat": now, "work": "allocate"},
            "identity/oidc/claim.json": {"office": "identity/oidc", "session": "s2", "runtime": "claude", "name": "Stage", "since": iso(now - 7200), "beat": now - 2000, "work": "oidc line"},
            "rasci.json": {
                "work/stage": {"title": "Stage line", "status": "running", "worker": "Stage (this session)", "roles": {"Stage (this session)": "RA"}},
                "work/feature": {
                    "title": "Show the merge flow in the hub", "status": "running", "worker": "Skills session", "objective": "The operator sees where a branch flows", "workdir": feature, "prio": 1,
                    "roles": {"Skills session": "RA", "Operator": "C", "Docs": "I"}, "key_results": [{"text": "Flow in the tree", "met": True}, {"text": "Flow in Tasks", "met": False}],
                    "estimates": {"Skills": {"value": 8, "complexity": 3, "at": iso(now - 600)}},
                },
                "work/docs": {"title": "Update the README", "status": "blocked", "worker": "Docs", "branch": "main", "roles": {"Docs": "R", "Maintainer": "A", "Skills": "S"}, "estimates": {"Docs": {"value": 3, "complexity": 2}}},
                "work/old": {"title": "Old line", "status": "done", "worker": "Stage", "end": iso(now - 86400), "roles": {"Stage": "RA"}},
                "operator/push": {"title": "git push", "workdir": "/repo", "status": "done", "roles": {"Operator": "R"}},
            },
            "queue.json": {"seq": 3, "entries": [{"id": "gate-3", "kind": "gate", "task": "work/feature", "workdir": feature, "session": "s1", "name": "Skills", "status": "waiting", "enqueued": now - 120, "cmd": "make test"}]},
            "radio-silence.json": {"since": now - 60, "until": now + 3600, "by": "Docs", "text": "disk full"},
            "news.jsonl": self.jsonl([
                {"ts": now - 600, "from": "Skills", "to": ["Stage"], "text": "rebase please", "class": "post", "v": 2},
                {"ts": now - 500, "from": "Stage", "to": ["Skills"], "text": "gate red", "class": "call", "v": 2},
                {"ts": now - 400, "from": "Maintainer", "to": [], "text": "main is green", "class": "newsletter", "v": 2},
                {"ts": now - 300, "from": "Maintainer", "to": [], "text": "rotate keys", "class": "security", "v": 2},
                {"ts": now - 60, "from": "Docs", "to": [], "text": "MAYDAY disk full", "class": "mayday", "v": 2},
            ]),
        })
        self.subagents(now)
        self.request("feat: orchestrator", "")
        self.create_ask(ASK)
        self.base = f"http://{self.host}/"

    def subagents(self, now: float) -> None:
        def line(ts: float) -> dict:
            return {"type": "user", "sessionId": "s1", "timestamp": iso(ts), "message": {"role": "user", "content": "x"}}

        folder = self.projects / "-repo" / "s1" / "subagents"
        folder.mkdir(parents=True)
        (self.projects / "-repo" / "s1.jsonl").write_text(self.jsonl([line(now - 3600), line(now - 30)]), encoding="utf-8")
        for ident, finished in (("abc", True), ("def", False)):
            (folder / f"agent-{ident}.meta.json").write_text(json.dumps({"agentType": "Explore", "description": f"look {ident}", "spawnDepth": 1, "finished": finished}), encoding="utf-8")
            (folder / f"agent-{ident}.jsonl").write_text(self.jsonl([line(now - 1800), line(now - 60)]), encoding="utf-8")

    def drive(self, steps: list[dict], authenticator: dict | None, driver: str = "cdp.mjs", binary: str = os.environ.get("CHROMIUM", "chromium"), init: str | None = None) -> dict:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump({"steps": steps, "authenticator": authenticator, "init": init}, handle)
        self.addCleanup(os.unlink, handle.name)
        done = subprocess.run(["node", str(HERE / driver), binary, handle.name], capture_output=True, text=True, timeout=900, check=False)
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        return json.loads(done.stdout)

    def beside(self, work: Callable[[], None]) -> None:
        stop = threading.Event()

        def loop() -> None:
            while not stop.wait(0.2):
                work()

        thread = threading.Thread(target=loop, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 10)
        self.addCleanup(stop.set)

    def shot(self, name: str) -> str:
        return str(OUT / f"chromium-{name}.png")

    def authenticator(self) -> dict:
        signer = self.pin()
        private = "".join(line for line in signer.pem.read_text(encoding="utf-8").splitlines() if not line.startswith("-----"))
        return {"credentialId": base64.b64encode(signer.raw_id).decode(), "privateKey": private, "rpId": "localhost"}

    def speaks(self, cues: tuple[str, ...]) -> None:
        hub = self.httpd.hub
        hub.settings.put({**hub.settings.get(), "speech": {"on": True, "classes": ["mayday", "pan-pan", "security"], "muted": []}}, hub.settings.get())
        spoken = tone(6, 8000)

        def synthesize(body: bytes) -> bytes:
            word = json.loads(body)["text"]
            if word in cues:
                row = {"ts": time.time(), "from": "Stage", "to": [], "text": f"Disk almost full ({word})\nsecond line", "class": "security", "v": 2}
                with (self.council / "news.jsonl").open("a", encoding="utf-8") as handle:
                    handle.write(self.jsonl([row]))
            return spoken

        patch = mock.patch.object(hub.speech, "synthesize", synthesize)
        patch.start()
        self.addCleanup(patch.stop)

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

    def check_overlaps(self, browser: str, driver: str, binary: str) -> None:
        steps = []
        for width, height in WIDTHS:
            steps.append({"width": width, "height": height, "url": f"{self.base}#stream/rules", "wait": 900, "probe": RULES_OVERLAP, "shot": str(OUT / f"{browser}-{width}-rules-form.png")})
            steps.append({"width": width, "height": height, "url": None, "wait": 0, "probe": SETTINGS_OVERLAP, "shot": str(OUT / f"{browser}-{width}-settings-form.png")})
        data = self.drive(steps, None, driver, binary)
        (OUT / f"{browser}-overlap.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        hidden = {"decision": ("Tool (glob)", "Directory (glob)"), "review": ("Tool (glob)",), "ask": ()}
        for index, (width, _) in enumerate(WIDTHS):
            rules, settings = data["results"][2 * index : 2 * index + 2]
            with self.subTest(browser=browser, width=width):
                self.assertNotIn("error", rules)
                self.assertNotIn("error", settings)
                for kind, found in rules.items():
                    self.assertEqual((found["found"], found["outside"]), ([], []), kind)
                    self.assertEqual([label for label in hidden[kind] if label in found["labels"]], [], kind)
                self.assertIn("Directory (glob)", rules["review"]["labels"])
                self.assertEqual(settings, {"found": [], "outside": []})

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
        ]
        data = self.drive(steps, self.authenticator() if signs else None, driver, binary, MEDIA_LOG)
        (OUT / f"{browser}-radio.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        saved, view, click = data["results"]
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
        return data

    def popped(self, result: dict, title: str) -> None:
        before, shown, gone = result["before"], result["shown"], result["gone"]
        self.assertEqual((before["picked"], before["red"]), (False, False))
        self.assertEqual((shown["open"], shown["picked"], shown["red"], shown["fade"], shown["title"]), (True, True, True, [True, "fade"], title), shown)
        self.assertGreater(shown["size"], before["size"] * 1.4)
        self.assertLess(shown["opacity"], 1)
        self.assertIsNotNone(shown["line"], shown)
        self.assertTrue(shown["onBox"] and shown["inside"], shown)
        self.assertEqual((not shown["tall"], shown["wide"], shown["panel"]), (result["flat"], False, 0))
        self.assertEqual(gone, {"picked": False, "size": before["size"], "red": False, "open": False, "outside": True})
        self.assertTrue(result["last"])

    def check_popups(self, browser: str, driver: str, binary: str) -> None:
        steps = []
        for width, height in WIDTHS:
            steps.append({"width": width, "height": height, "url": f"{self.base}#agents/orbit", "wait": 1200, "probe": POPUP_ORBIT, "shot": str(OUT / f"{browser}-{width}-agents-orbit-popup.png")})
            steps.append({"width": width, "height": height, "url": f"{self.base}#artifacts/orbit", "wait": 1200, "probe": POPUP_ARTIFACT, "shot": str(OUT / f"{browser}-{width}-artifacts-orbit-popup.png")})
        for tab, query, prefix in (("artifacts", "feature", "branch:"), ("agents", "sta", "s2")):
            steps.append({"width": 1366, "height": 768, "url": f"{self.base}#{tab}/3d", "wait": 900, "probe": PICK_3D.replace("@QUERY@", query).replace("@PREFIX@", prefix), "shot": str(OUT / f"{browser}-1366-{tab}-3d-picked.png")})
        data = self.drive(steps, None, driver, binary)
        (OUT / f"{browser}-popups.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "(style-src-elem)" not in error and "/favicon.ico" not in error], [])
        results = data["results"]
        for index, (width, _) in enumerate(WIDTHS):
            agent, artifact = results[2 * index : 2 * index + 2]
            with self.subTest(browser=browser, width=width):
                self.assertNotIn("error", agent)
                self.assertNotIn("error", artifact)
                self.assertTrue(agent["flat"], "#agents/orbit scrolls")
                self.popped(agent, "Stage")
                self.assertEqual(agent["shown"]["sections"], ["Tasks", "Claims", "Subagents", "History"])
                self.assertTrue(agent["shown"]["composer"])
                self.assertRegex(agent["shown"]["offices"], r"^Offices: .*identity/oidc")
                escaped = agent["escaped"]
                self.assertEqual((escaped["again"], escaped["open"], escaped["picked"], escaped["red"], escaped["size"]), (True, False, False, False, agent["before"]["size"]))
                self.popped(artifact, artifact["shown"]["label"])
        for found, tab in zip(results[-2:], ("artifacts", "agents"), strict=True):
            with self.subTest(browser=browser, tab=tab):
                self.assertNotIn("error", found)
                self.assertEqual(found["empty"], [])
                labels = [label for _, label in found["hits"]]
                self.assertEqual(len(labels), len(set(labels)), labels)
                self.assertLessEqual(len(labels), 8)
                opened = found["opened"]
                self.assertEqual((opened["open"], opened["title"], opened["picked"], opened["line"], opened["lists"], opened["flat"]), (True, opened["label"], opened["hit"], True, 0, found["flat"]), opened)
                self.assertEqual(found["closed"], {"open": False, "picked": None})
        artifacts, agents = results[-2:]
        self.assertEqual((artifacts["twins"], [label for _, label in artifacts["twin"]]), (2, ["main"]))
        self.assertTrue(artifacts["opened"]["hit"].startswith("branch:"), artifacts["opened"])
        self.assertEqual((agents["hits"], agents["opened"]["title"]), ([["s2", "Stage"]], "Stage"))

    def test_chromium_opens_agent_and_node_popups_and_finds_nodes_at_three_widths(self):
        self.check_popups("chromium", "cdp.mjs", os.environ.get("CHROMIUM", "chromium"))

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_opens_agent_and_node_popups_and_finds_nodes_at_three_widths(self):
        self.check_popups("firefox", "bidi.mjs", os.environ.get("FIREFOX", "firefox"))

    def test_chromium_form_controls_never_overlap(self):
        self.check_overlaps("chromium", "cdp.mjs", os.environ.get("CHROMIUM", "chromium"))

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_form_controls_never_overlap(self):
        self.check_overlaps("firefox", "bidi.mjs", os.environ.get("FIREFOX", "firefox"))

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

    def test_chromium_walks_every_screen_at_three_widths(self):
        steps = [{"width": width, "height": height, "url": f"{self.base}#{screen}", "wait": 900, "probe": PROBE, "shot": self.shot(f"{width}-{screen.replace('/', '-')}")} for width, height in WIDTHS for screen in SCREENS]
        steps += [{"width": 1366, "height": 768, "url": f"{self.base}#{old}", "wait": 600, "probe": PROBE, "shot": None} for old in ("graph", "graph/chord", "tree")]
        steps.append({"width": 1366, "height": 768, "url": f"{self.base}#stream", "wait": 900, "probe": ACTIONS, "shot": None})
        steps.append({"width": 1366, "height": 768, "url": f"{self.base}#artifacts/3d", "wait": 900, "probe": PROBE, "shot": self.shot("1366-artifacts-3d-reduced-motion"), "media": [{"name": "prefers-reduced-motion", "value": "reduce"}]})
        steps.append({"width": 1366, "height": 768, "url": f"{self.base}#tasks/list", "wait": 900, "probe": INBOX_CHIP, "shot": self.shot("1366-tasks-grant")})
        data = self.drive(steps, None)
        (OUT / "chromium-walk.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        probes = data["results"][: len(WIDTHS) * len(SCREENS)]
        for probe, step in zip(probes, steps, strict=False):
            with self.subTest(url=step["url"], width=step["width"]):
                self.assertNotIn("error", probe)
                self.assertEqual((probe["title"], probe["h1"]), ("(2) Agent Orchestrator", "Agent Orchestrator"))
                self.assertEqual(probe["header"], ["palette-open", "settings-open"])
                self.assertEqual((probe["tabs"], probe["subs"]), (TABS, SUBS))
                self.assertEqual(probe["badges"], {"tab-stream": None, "tab-inbox": "2", "tab-rules": None, "tab-radio": None, "tab-agents": "1", "tab-artifacts": None, "tab-tasks": None})
                self.assertEqual(probe["banner"], "MAYDAY · Docs: disk full")
                self.assertFalse(probe["rail"])
                self.assertEqual((probe["time"], probe["replay"]), ("24 h ▾", True))
                self.assertGreater(probe["icons"], 8)
                self.assertEqual(labelled(probe), {"unlabelled": [], "broken": []})
                self.assertFalse(probe["wide"], "the page scrolls sideways")
                self.assertEqual((probe["panel"], probe["nodeChips"]), (0, 0))
        self.assertEqual([probe["tall"] for probe in probes if probe["hash"] == "#agents/orbit"], [False] * len(WIDTHS))
        by_hash = {probe["hash"]: probe for probe in probes}
        stream = by_hash["#stream"]
        self.assertEqual([probe["chips"] for probe in probes if probe["hash"] == "#stream"], [["For you", "Radio", "Work", "Transcripts"]] * len(WIDTHS))
        self.assertEqual((stream["menus"], stream["custom"]), (["Filter"], True))
        self.assertEqual(by_hash["#stream/inbox"]["inbox"], 2)
        for tab, own in (("agents", ["Hierarchy"]), ("artifacts", [])):
            with self.subTest(tab=tab):
                self.assertEqual(by_hash[f"#{tab}/orbit"]["views"], ["Orbit", "Chord", "Swimlane", "Tree", "3D", *own])
                self.assertEqual(by_hash[f"#{tab}/3d"]["layouts"], ["Force", "Time", "Spawn depth"])
                self.assertTrue(by_hash[f"#{tab}/3d"]["canvas"], by_hash[f"#{tab}/3d"]["note"])
                self.assertRegex(by_hash[f"#{tab}/3d"]["note"], r"^\d+ nodes · \d+ edges · Force$")
        agents = by_hash["#agents/orbit"]
        self.assertEqual(agents["toolbar"], ["Radio to all", "Cancel mayday", "Priority", "Day/Night"])
        self.assertEqual(agents["toAll"], [["newsletter", True], ["broadcast", False], ["pan-pan", False], ["security", False], ["mayday", False]])
        hierarchy = by_hash["#agents/hierarchy"]
        self.assertEqual([office for office, _ in hierarchy["org"]], ["chair", "identity/oidc", "work/s1", "work/s2"])
        self.assertEqual(hierarchy["toggles"], [["Collapse: Operator", "true"], ["Collapse: Chair", "true"], ["Collapse: identity", "true"], ["Collapse: Presidents", "true"]])
        self.assertEqual(hierarchy["toolbar"], agents["toolbar"])
        self.assertGreaterEqual(len(hierarchy["order"]), 2)
        self.assertEqual(by_hash["#agents/tree"]["spawn"][0], ["operator", None])
        self.assertIn(["twig", "true"], by_hash["#agents/tree"]["spawn"])
        self.assertIn(["twig", "false"], by_hash["#agents/tree"]["spawn"])
        artifacts = by_hash["#artifacts/tree"]
        self.assertEqual(artifacts["deletes"], [["Delete all merged", True, "Delete all merged blocked: Secret Service locked"], ["Delete", True, "Delete blocked: Secret Service locked"]])
        for state in ("merged by #12 into main", "upstream gone", "protected", "1 commits unpushed", "clean", "not committed: 0 staged, 0 changed, 1 new", "gc skips: ignored files beyond known caches: notes.txt"):
            with self.subTest(state=state):
                self.assertIn(state, artifacts["states"])
        for view in ("orbit", "chord"):
            with self.subTest(view=view):
                self.assertGreaterEqual(by_hash[f"#artifacts/{view}"]["marks"], 4)
        self.assertEqual((artifacts["flows"], artifacts["openWork"]), (["file", "invalid"], 5))
        for state in ("open work: not committed, task open", "open work: unpushed, task open", "open work: not merged", "3 worktrees with open work"):
            with self.subTest(state=state):
                self.assertIn(state, artifacts["states"])
        self.assertEqual(by_hash["#artifacts/chord"]["flowEdges"], ["pull", "push"])
        order = ["work/feature", "work/docs", "work/stage", "queue/gate-3", "work/old", "operator/push"]
        listed = by_hash["#tasks/list"]
        self.assertEqual(listed["views"], ["List", "Board", "RASCI"])
        self.assertEqual(listed["taskFilters"], [["all", "true", "6"], ["open", "false", "4"], ["work", "false", "4"], ["operator", "false", "2"], ["grant", "false", "1"], ["ended", "false", "2"]])
        self.assertEqual(listed["taskRows"], [[task, task not in ("work/old", "operator/push")] for task in order])
        self.assertEqual(listed["flows"], ["file", "file"])
        self.assertEqual(by_hash["#tasks/board"]["columns"], [["queued", ["queue/gate-3"]], ["running", ["work/feature", "work/stage"]], ["blocked", ["work/docs"]], ["done", ["work/old", "operator/push"]], ["stopped", []]])
        self.assertEqual(by_hash["#tasks/rasci"]["matrix"], [6, 6, "CIRARASRARAR"])
        self.assertEqual([probe["taskFilters"][3][1] for probe in probes if probe["hash"] == "#stream/inbox"], ["true"] * len(WIDTHS))
        extra = data["results"][len(probes) :]
        self.assertEqual([probe["hash"] for probe in extra[:3]], ["#agents/orbit", "#agents/chord", "#artifacts/tree"])
        actions = extra[3]
        self.assertNotIn("error", actions)
        self.assertEqual(actions["keys"], ["#agents/chord", "#artifacts/tree", "#tasks/rasci", "#stream"])
        self.assertEqual(actions["ambience"], ["sky-look", "music-toggle", "leitstand", "notify"])
        self.assertEqual((actions["settingsUnlabelled"], actions["popupUnlabelled"]), (0, 0))
        self.assertEqual([name for name, _, _ in actions["speech"]], ["Post", "Call", "Newsletter", "Broadcast", "MAYDAY", "PAN-PAN", "Sécurité"])
        self.assertEqual([entry[1:] for entry in actions["speech"] if entry[0] == "MAYDAY"], [[True, True]])
        for tool in ("Radio to all …", "Cancel mayday", "Priority …", "Evening", "Firewall …", "Settings …", "Look at the sky", "Toggle control room", "Enable notifications"):
            with self.subTest(tool=tool):
                self.assertTrue(any(tool in entry for entry in actions["palette"]), actions["palette"])
        self.assertEqual(actions["popup"], [["post", True], ["call", False]])
        self.assertEqual(actions["centred"], [True, "none"])
        calm, chips = extra[4:]
        self.assertRegex(calm["note"], r"Force · without motion \(prefers-reduced-motion\)$")
        self.assertEqual({key: value for key, value in chips["inbox"].items() if key != "counted"}, {"hash": "#stream/inbox", "items": chips["inbox"]["counted"], "pressed": "true", "current": ["Inbox"]})
        self.assertGreaterEqual(chips["inbox"]["items"], 1)
        self.assertEqual(chips["back"], {"hash": "#tasks/list", "rows": [["queue/gate-3", "Queue job"]]})

    def test_chromium_sends_a_call_from_the_agent_panel_and_shows_its_receipt(self):
        handled = []

        def answer() -> None:
            for script, args in self.scripts.calls[len(handled) :]:
                handled.append(script)
                if script.endswith("radio.py") and args[:2] == ["send", "call"]:
                    to, text, now = args[args.index("--to") + 1], args[-1], time.time()
                    rows = [{"ts": now, "from": "Operator", "to": [to], "text": text, "class": "call", "v": 2}, {"ts": now + 0.5, "from": to, "to": ["Operator"], "text": text, "class": "receipt", "v": 2, "call": now}]
                    with (self.council / "news.jsonl").open("a", encoding="utf-8") as handle:
                        handle.write(self.jsonl(rows))

        self.beside(answer)
        local = f"http://localhost:{self.port}/"
        data = self.drive([{"width": 1366, "height": 768, "url": f"{local}#stream", "wait": 900, "probe": CALL, "shot": self.shot("1366-call-receipt")}], self.authenticator())
        self.assertEqual(data["errors"], [])
        result = data["results"][0]
        self.assertNotIn("error", result)
        self.assertIsNotNone(result["receipt"], result)
        self.assertIn("Read", result["receipt"])

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
        self.assertEqual((speaking["who"], speaking["line"], speaking["chip"], speaking["ring"]), ("Stage speaking", "Disk almost full (e2e-cue-1)", "s2", "speaking"), speaking)
        self.assertEqual((graph["node"] or "").split(",")[0], "Stage", graph)
        self.assertEqual(graph["ring"], "speaking-node")
        self.assertEqual(ended, {"ended": True, "caption": False, "chips": 0})
        self.assertEqual((calm["who"], calm["line"], calm["ring"]), ("Stage speaking", "Disk almost full (e2e-cue-2)", "none"), calm)

    def test_chromium_records_transcribes_and_sends_a_signed_call_with_voice(self):
        local = f"http://localhost:{self.port}/"
        steps = [
            {"width": 1366, "height": 768, "url": f"{local}#stream/radio", "wait": 1200, "probe": COMPOSE.replace("@TO@", "Stage"), "shot": self.shot("1366-radio-composer"), "gesture": True},
            {"width": 1366, "height": 768, "url": None, "wait": 0, "probe": COMPOSE_SEND.replace("@ATTACH@", "false"), "shot": None},
            {"width": 1366, "height": 768, "url": None, "wait": 0, "probe": COMPOSE.replace("@TO@", "Stage"), "shot": None, "gesture": True},
            {"width": 1366, "height": 768, "url": None, "wait": 0, "probe": COMPOSE_SEND.replace("@ATTACH@", "true"), "shot": self.shot("1366-radio-composer-sent")},
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

    def test_chromium_clears_the_mayday_only_after_the_passkey_signs(self):
        local = f"http://localhost:{self.port}/"
        data = self.drive([{"width": 1366, "height": 768, "url": f"{local}#agents/orbit", "wait": 1200, "probe": CLEAR_MAYDAY, "shot": self.shot("1366-mayday-cleared")}], self.authenticator())
        self.assertEqual(data["errors"], [])
        result = data["results"][0]
        self.assertNotIn("error", result)
        self.assertTrue((result["done"] or "").startswith("Cancel mayday: done"), result)
        self.assertEqual(self.scripts.calls, [(skill_scripts.RADIO, ["clear", "--force", "--session", "Operator"])])

    def test_chromium_deletes_a_merged_branch_after_dry_run_and_signature(self):
        tree = json.loads(self.tree_file.read_text(encoding="utf-8"))
        tree["delete_ready"], tree["delete_reason"] = True, ""
        self.tree_file.write_text(json.dumps(tree), encoding="utf-8")
        demo = f"{self.root}/repos/github.com/me/demo"
        Path(demo).mkdir(parents=True)
        fake = self.outside / "bin" / "pkgmgr"
        fake.parent.mkdir()
        fake.write_text(FAKE_PKGMGR.format(python=sys.executable), encoding="utf-8")
        fake.chmod(0o755)
        worktree = f"{self.root}/worktrees/github.com/me/demo/feature-done"
        (fake.parent / "plan.json").write_text(json.dumps([{"branch": "feature/done", "worktree": worktree, "local_sha": DONE_TIP, "head": DONE_TIP, "state": "merged-clean", "skip": None}]), encoding="utf-8")
        following = json.loads(json.dumps(tree))
        following["repos"][0]["items"] = [item for item in following["repos"][0]["items"] if item["branch"] != "feature/done"]
        (fake.parent / "next-tree.json").write_text(json.dumps(following), encoding="utf-8")
        authenticator = self.authenticator()
        trust = verifier.Trust(approvers=self.approvers, replay=self.replay / "cleanup.json", origin=self.origin)
        runner = host.Cleanup(trust, self.tree_file, fake)
        jobs, results = self.cleanup / "jobs", self.cleanup / "results"
        self.beside(lambda: any(jobs.iterdir()) and host.cycle(jobs, results, runner))
        local = f"http://localhost:{self.port}/"
        steps = [
            {"width": 1366, "height": 768, "url": f"{local}#artifacts/tree", "wait": 1200, "probe": OPEN_DELETE, "shot": self.shot("1366-delete-dry-run")},
            {"width": 1366, "height": 768, "url": None, "wait": 0, "probe": CONFIRM, "shot": self.shot("1366-delete-result")},
            {"width": 1366, "height": 768, "url": None, "wait": 0, "probe": AFTER, "shot": self.shot("1366-delete-tree-after")},
        ]
        data = self.drive(steps, authenticator)
        (OUT / "chromium-delete.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        opened, confirmed, after = data["results"]
        self.assertNotIn("error", opened)
        self.assertEqual(opened["every"], [False, "Delete all merged: 1 branches after dry run and signature"])
        self.assertEqual(opened["buttons"], [[False, "Delete: remove feature/done locally, after dry run and signature"]])
        self.assertEqual(opened["title"], "Delete feature/done")
        self.assertEqual(len(opened["dry"]), 1)
        self.assertTrue(opened["dry"][0].startswith("feature/done @ 5b1e6fd3a7c0: merged-clean, merged by #12"), opened["dry"])
        self.assertIn("stays: remote-branch (local only)", opened["dry"][0])
        self.assertEqual((confirmed["result"], confirmed["text"]), ("done", "feature/donedeleted"), confirmed)
        self.assertEqual(confirmed["toasts"], ["Delete: donefeature/done: deleted"])
        self.assertEqual(after["past"], ["done", "deleted"])
        self.assertNotIn("feature/done", after["branches"])
        written = [json.loads(path.read_text(encoding="utf-8")) for path in results.glob("*.json")]
        self.assertEqual([[(item["branch"], item["status"]) for item in result["items"]] for result in written], [[("feature/done", "done")]])
        calls = [json.loads(line)["argv"] for line in (fake.parent / "calls.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(calls, [
            ["branch", "cleanup", "--json", "--local", "--branch", "feature/done"],
            ["branch", "cleanup", "--apply", "--json", "--local", "--branch", "feature/done"],
            ["branch", "tree", "--format", "json", "--output", str(self.tree_file)],
        ])

    def test_chromium_folds_the_hierarchy_by_keyboard_reorders_agents_and_hands_an_office_over_with_a_signature(self):
        signer = self.pin()
        trust = verifier.Trust(approvers=self.approvers, replay=self.replay / "offices.json", origin=self.origin)
        runner = office_host.Offices(trust, self.council, COUNCIL_SCRIPT, self.outside / "home")
        jobs, results = self.offices / "jobs", self.offices / "results"
        self.beside(lambda: any(jobs.iterdir()) and office_host.cycle(jobs, results, runner))
        private = "".join(line for line in signer.pem.read_text(encoding="utf-8").splitlines() if not line.startswith("-----"))
        authenticator = {"credentialId": base64.b64encode(signer.raw_id).decode(), "privateKey": private, "rpId": "localhost"}
        local = f"http://localhost:{self.port}/"
        steps = [
            {"width": 1366, "height": 768, "url": f"{local}#agents/hierarchy", "wait": 1200, "probe": ORG_OPEN, "shot": self.shot("1366-hierarchy-open")},
            {"width": 1366, "height": 768, "url": None, "wait": 0, "keys": ["Enter"], "probe": ORG_FOLDED, "shot": None},
            {"width": 1366, "height": 768, "url": None, "wait": 0, "keys": ["Enter"], "probe": ORDER_MOVED, "shot": self.shot("1366-hierarchy-order")},
            {"width": 1366, "height": 768, "url": None, "wait": 0, "probe": OPEN_TAKEOVER, "shot": self.shot("1366-hierarchy-takeover")},
            {"width": 1366, "height": 768, "url": None, "wait": 0, "probe": CONFIRM_TAKEOVER, "shot": self.shot("1366-hierarchy-takeover-result")},
            {"width": 1366, "height": 768, "url": None, "wait": 0, "probe": AFTER_TAKEOVER, "shot": self.shot("1366-hierarchy-after")},
        ]
        data = self.drive(steps, authenticator)
        (OUT / "chromium-hierarchy.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        opened, folded, moved, sheet, confirmed, after = data["results"]
        self.assertNotIn("error", opened)
        self.assertEqual(opened["focused"], "toggle:dimension:identity")
        self.assertEqual((folded["focused"], folded["expanded"], folded["label"], folded["hidden"], folded["again"]), ("toggle:dimension:identity", "false", "Expand: identity", True, "true"))
        self.assertNotIn("identity/oidc", folded["seen"])
        before = folded["before"]
        self.assertEqual(moved["after"], [before[1], before[0], *before[2:]])
        self.assertEqual((moved["focused"], moved["disabled"]), (f"down:{before[1]}", False))
        self.assertTrue(moved["toast"].startswith("Priority"), moved)
        self.assertIn(("rasci.py", ["agents", "order", ",".join(moved["after"])]), [(Path(script).name, args) for script, args in self.scripts.calls])
        self.assertEqual((sheet["title"], sheet["options"], sheet["work"], sheet["focused"]), ("identity/oidc: Hand over", ["s1"], "oidc line", "SELECT"))
        self.assertEqual((confirmed["result"], confirmed["text"]), ("done", "identity/oidcdone"), confirmed)
        self.assertIn("Hand over: doneidentity/oidc: done", confirmed["toasts"])
        self.assertNotIn("error", after)
        claim = json.loads((self.council / "identity" / "oidc" / "claim.json").read_text(encoding="utf-8"))
        self.assertEqual((claim["session"], claim["work"]), ("s1", "oidc line"))
        written = [json.loads(path.read_text(encoding="utf-8")) for path in results.glob("*.json")]
        self.assertEqual([[(item["office"], item["action"], item["status"]) for item in result["items"]] for result in written], [[("identity/oidc", "takeover", "done")]])

    def inbox_work(self) -> None:
        stage = {"title": "Stage line", "status": "running", "worker": "Stage (this session)", "roles": {"Stage (this session)": "RA"}}
        greet = {"title": SLOW, "workdir": str(self.outside), "description": "counts", "check": "manual", "status": "queued", "roles": {"Operator": "R", "Skills session": "A"}}
        push = {"title": "git push", "workdir": "/repo", "description": "ship", "check": "manual", "status": "queued", "roles": {"Operator": "R", "Skills session": "A"}}
        self.write_council({"rasci.json": {"work/stage": stage, "operator/greet": greet, "operator/push": push}})
        arguments = {"kind": "ask", "tool": "Bash", "pattern": "make deploy", "scope": "/repo*", "expires": int(time.time()) + 7 * 86400, "agent": "Skills", "why": "deploy runs after every green gate"}
        self.assertFalse(self.tool("rule_request", arguments)["isError"])

    def layout(self, probe: dict) -> None:
        self.assertNotIn("error", probe)
        self.assertEqual(sorted(probe["kinds"]), ["Ask", "Operator", "Operator", "Review", "Rule request"])
        self.assertIn(["Deny", "Deny via …"], probe["splits"])
        self.assertEqual(len(probe["splits"]), 4)
        self.assertEqual(probe["fields"], ["Kind", "Tool (glob)", "Pattern (glob)", "Directory (glob)", "Expires on"])
        self.assertEqual(probe["dry"], "Dry run: the rule would have granted 1 of 1 asks from the last 7 days.")
        self.assertEqual(probe["accept"], 1)
        self.assertTrue(probe["fits"] and probe["followed"], probe)
        self.assertEqual((probe["unlabelled"], probe["wide"]), ([], False))

    def test_chromium_runs_a_command_into_its_console_denies_by_call_and_accepts_a_rule(self):
        self.inbox_work()
        signer = self.pin()
        trust = ["--approvers", str(self.approvers), "--replay", str(self.replay / "runner.json")]

        def run_jobs() -> None:
            if any(job["status"] == "queued" for job in self.httpd.hub.jobs.listed()):
                subprocess.run([sys.executable, str(RUNNER), "--port", str(self.port), "--interval", "0.1", *trust, "--once"], capture_output=True, timeout=120, check=False)

        self.beside(run_jobs)
        private = "".join(line for line in signer.pem.read_text(encoding="utf-8").splitlines() if not line.startswith("-----"))
        authenticator = {"credentialId": base64.b64encode(signer.raw_id).decode(), "privateKey": private, "rpId": "localhost"}
        inbox = f"http://localhost:{self.port}/#stream/inbox"
        steps = [
            {"width": 1366, "height": 768, "url": inbox, "wait": 1200, "probe": RUN_START, "shot": self.shot("1366-inbox-console-running")},
            {"width": 1366, "height": 768, "url": None, "wait": 0, "probe": RUN_HELD, "shot": self.shot("1366-inbox-console-scrolled-up")},
            {"width": 1366, "height": 768, "url": None, "wait": 0, "probe": RUN_DONE, "shot": self.shot("1366-inbox-console-done")},
        ]
        for width, height in WIDTHS:
            fresh = f"http://localhost:{self.port}/?{width}#stream/inbox"
            steps.append({"width": width, "height": height, "url": fresh, "wait": 1200, "probe": LAYOUT, "shot": self.shot(f"{width}-inbox-console")})
            steps.append({"width": width, "height": height, "url": None, "wait": 0, "probe": DENY_SHEET, "shot": self.shot(f"{width}-inbox-deny-sheet")})
        steps += [
            {"width": 1366, "height": 768, "url": inbox, "wait": 1200, "probe": DENY, "shot": self.shot("1366-inbox-deny-undo")},
            {"width": 1366, "height": 768, "url": None, "wait": 0, "probe": DENIED, "shot": None},
            {"width": 1366, "height": 768, "url": None, "wait": 0, "probe": ACCEPT, "shot": self.shot("1366-inbox-rule-accepted")},
        ]
        data = self.drive(steps, authenticator)
        (OUT / "chromium-inbox.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        started, held, done, *rest = data["results"]
        self.assertNotIn("error", started)
        self.assertIn("takes effect in", started["toast"])
        self.assertTrue(started["running"].startswith("running"), started)
        self.assertTrue(started["overflows"] and started["followed"], started)
        self.assertLess(held["held"], 50, held)
        self.assertEqual((done["last"], done["lines"], done["followed"]), ("finished", 81, True))
        self.assertRegex(done["done"], r"^doneExit code 0 after \d+ s$")
        self.assertIn("Close", done["actions"])
        layouts, sheets = rest[0:6:2], rest[1:6:2]
        for probe, sheet, (width, _) in zip(layouts, sheets, WIDTHS, strict=True):
            with self.subTest(width=width):
                self.layout(probe)
                self.assertTrue(probe["console"].startswith("doneExit code 0"), probe)
                self.assertEqual(sheet["title"], "Deny")
                self.assertEqual(sheet["channels"], [["post", True], ["call", False], ["newsletter", False], ["broadcast", False], ["pan-pan", False], ["security", False]])
                self.assertEqual(sheet["hints"][:3], ["to Skills, when its turn ends", "to Skills, at once, wakes it", "to all, when their turn ends"])
                self.assertEqual((sheet["reason"], sheet["unlabelled"], sheet["wide"]), (True, [], False))
        denied, gone, accepted = rest[6:]
        self.assertTrue(denied["undo"].startswith("Denial (Call): Bash: make deploy"), denied)
        self.assertFalse(denied["sheet"])
        self.assertTrue(gone["gone"])
        self.assertEqual((accepted["toast"], accepted["left"]), ("Created: Rule: ask Bash make deploy in /repo*", False))
        ask = self.httpd.hub.asks.listed()[0]
        self.assertEqual((ask["status"], ask["reason"], ask["channel"]), ("denied", "make the gate green first", "call"))
        calls = [args for script, args in self.scripts.calls if script.endswith("radio.py")]
        self.assertEqual(calls[-1][:4], ["send", "call", "--to", "Skills session"])
        self.assertTrue(calls[-1][-1].endswith("Reason: make the gate green first"), calls[-1])
        self.assertEqual([(rule["kind"], rule["pattern"], rule["proof"] is not None) for rule in self.httpd.hub.rules.listed()], [("ask", "make deploy", True)])
        self.assertEqual([(job["status"], job["code"]) for job in self.httpd.hub.jobs.listed()], [("done", 0)])

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_draws_the_inbox_console_and_the_rule_request_at_three_widths(self):
        self.inbox_work()
        now = time.time()
        fields = {"task": "operator/greet", "command": SLOW, "directory": str(self.outside), "sha256": "", "status": "done", "proof": None}
        output = "".join(f"Row {number}\n" for number in range(1, 81)) + "finished\n"
        self.httpd.hub.jobs.add({**fields, "code": 0, "output": output, "created_ts": now - 20, "started": now - 19, "finished": now - 10, "dismissed": False})
        shots = [(width, height, OUT / f"firefox-{width}-inbox-console.png") for width, height in WIDTHS]
        steps = [{"width": width, "height": height, "url": f"{self.base}#stream/inbox", "wait": 1200, "probe": LAYOUT, "shot": str(shot)} for width, height, shot in shots]
        data = self.drive(steps, None, "bidi.mjs", os.environ.get("FIREFOX", "firefox"))
        (OUT / "firefox-inbox.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "(style-src-elem)" not in error and "/favicon.ico" not in error], [])
        for probe, (width, _, shot) in zip(data["results"], shots, strict=True):
            with self.subTest(width=width):
                self.layout(probe)
                self.assertEqual(probe["console"], "doneExit code 0 after 9 s")
                self.assertTrue(shot.is_file() and shot.stat().st_size > 1000, shot)

    def test_chromium_pins_a_task_priority_after_signature_and_the_runner_applies_it(self):
        signer = self.pin()
        private = "".join(line for line in signer.pem.read_text(encoding="utf-8").splitlines() if not line.startswith("-----"))
        authenticator = {"credentialId": base64.b64encode(signer.raw_id).decode(), "privateKey": private, "rpId": "localhost"}
        local = f"http://localhost:{self.port}/"
        data = self.drive([{"width": 1366, "height": 768, "url": f"{local}#tasks/list", "wait": 1200, "probe": PIN, "shot": self.shot("1366-tasks-priority-signed")}], authenticator)
        (OUT / "chromium-task-priority.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        pinned = data["results"][0]
        self.assertNotIn("error", pinned)
        self.assertEqual((pinned["title"], pinned["preview"][0]), ("work/docs", "rasci.py set work/docs --prio 2"))
        self.assertEqual(pinned["toasts"], ["Priority work/docs: handed to the runnerrasci.py set work/docs --prio 2"])
        jobs = self.runner_jobs()
        self.assertEqual([(job["id"], job["kind"], job["argv"]) for job in jobs], [(pinned["jobs"], "task", ["set", "work/docs", "--prio", "2"])])
        self.run_runner()
        register = json.loads((self.council / "rasci.json").read_text(encoding="utf-8"))
        self.assertEqual((register["work/docs"]["prio"], register["work/feature"]["prio"]), (2, 1))
        self.assertEqual([(row["task"], row["prio"]) for row in self.snapshot()["tasks"][:2]], [("work/feature", 1), ("work/docs", 2)])

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_walks_every_screen_at_three_widths(self):
        shots = [(width, height, screen, OUT / f"firefox-{width}-{screen.replace('/', '-')}.png") for width, height in WIDTHS for screen in SCREENS]
        for *_, shot in shots:
            shot.unlink(missing_ok=True)
        steps = [{"width": width, "height": height, "url": f"{self.base}#{screen}", "wait": 900, "probe": PROBE, "shot": str(shot)} for width, height, screen, shot in shots]
        data = self.drive(steps, None, "bidi.mjs", os.environ.get("FIREFOX", "firefox"))
        (OUT / "firefox-walk.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        blocked = [error for error in data["errors"] if error.startswith("Content-Security-Policy")]
        self.assertEqual([error for error in data["errors"] if error not in blocked], [])
        # 3d-force-graph injects its own <style>, which the unchanged CSP blocks; the page carries those rules itself.
        self.assertEqual([error for error in blocked if "(style-src-elem)" not in error and "/favicon.ico" not in error], [])
        for probe, (width, _, screen, shot) in zip(data["results"], shots, strict=True):
            with self.subTest(width=width, screen=screen):
                self.assertNotIn("error", probe)
                self.assertEqual(probe["hash"], f"#{screen}")
                self.assertEqual((probe["tabs"], probe["subs"]), (TABS, SUBS))
                self.assertEqual(labelled(probe), {"unlabelled": [], "broken": []})
                self.assertFalse(probe["wide"], "the page scrolls sideways")
                self.assertEqual((probe["panel"], probe["nodeChips"]), (0, 0))
                self.assertTrue(shot.is_file() and shot.stat().st_size > 1000, shot)
                if screen.endswith("/3d"):
                    self.assertTrue(probe["canvas"], probe["note"])


if __name__ == "__main__":
    unittest.main()
