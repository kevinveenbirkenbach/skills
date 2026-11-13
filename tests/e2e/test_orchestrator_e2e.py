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
from hub_support import ASK, HOST_STATE, OPTIONS, RUNNER, iso, verifier
from kvb_orchestrator import batches, messaging, skill_scripts
from test_hub_cleanup import DONE_TIP, FAKE_PKGMGR, host
from test_hub_offices import COUNCIL_SCRIPT
from test_hub_offices import host as office_host

OUT = Path(os.environ.get("E2E_OUT", "/tmp/orchestrator-phase4-shots"))
WIDTHS = ((1920, 1080), (1366, 768), (390, 844))
VIEWS = ("orbit", "chord", "swimlane", "tree", "3d")
TASK_VIEWS = ("list", "board", "rasci", "gantt", "burn", "3d")
SCREENS = ["home", "stream", "tasks/operator", "stream/rules", *(f"{tab}/{view}" for tab in ("agents", "artifacts") for view in VIEWS), "agents/hierarchy", *(f"tasks/{view}" for view in TASK_VIEWS), "resources"]
SUBS = ["Firewall"]
TABS = ["Home", "Stream", "Agents", "Artifacts", "Tasks", "Resources"]
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
  const toolbarRows = () => {
    const bar = document.querySelector('#main [role="toolbar"][aria-label="Tasks"]');
    const boxes = bar ? [...bar.children].filter((node) => node.getClientRects().length).map((node) => node.getBoundingClientRect()).sort((a, b) => a.top - b.top) : [];
    let [rows, bottom] = [0, -Infinity];
    for (const box of boxes) {
      if (box.top >= bottom - 1) {
        rows += 1;
        bottom = box.bottom;
      } else {
        bottom = Math.max(bottom, box.bottom);
      }
    }
    return rows;
  };
  const taskLayout = () => all("#main .graph.tasks > *").map((node) => (node.matches('[role="toolbar"]') ? "toolbar" : node.matches('[aria-label="Task filters"]') ? "chips" : "body"));
  const screenShown = async (ms) => {
    const shown = await until(() => {
      if (typeof Nav !== "object") {
        return false;
      }
      const route = Nav.route(location.hash);
      const view = route.view ? Nav.viewsOf(route.screen).find(([id]) => id === route.view)[1] : null;
      const pressed = name(document.querySelector('#main [aria-label="View"] button[aria-pressed="true"]'));
      return document.getElementById("main").getAttribute("aria-labelledby") === `tab-${route.screen}` && (!view || pressed === view);
    }, ms);
    await sleep(0);
    return Boolean(shown);
  };
"""
PROBE = """(async () => {@HELPERS@
  await screenShown(8000);
  await until(() => !(text(document.querySelector("#main .space-note")) || "").startsWith("Loading") && !all("#main .empty h2").some((title) => text(title).endsWith("…")), 8000);
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
    spot: (() => {
      const box = document.getElementById("radio-spot");
      return box ? {hidden: box.hidden, channels: [...box.querySelector("form.composer select").options].map((option) => option.value)} : null;
    })(),
    composers: all("form.composer").map((form) => (form.closest("#radio-spot") ? "spot" : "other")),
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
    columns: all("#main .task-column").map((column) => [column.dataset.column, all(`#main .kanban-cell[data-column="${column.dataset.column}"] .task-card`).map((card) => card.dataset.task)]),
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
  await until(() => location.hash === "#tasks/operator" && document.querySelector("#main .inbox-list"), 4000);
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
  const found = {keys: [await press("3"), await press("4"), await press("5"), await press("1"), await press("2")]};
  document.getElementById("settings-open").click();
  await sleep(300);
  found.ambience = all(".sheet-box form > section:first-child button").map((button) => button.id);
  found.sections = all(".sheet-box form.settings > section > h3").map(text);
  found.radioFields = all('.sheet-box [aria-label="Squelch"], .sheet-box [aria-label="Classes"], .sheet-box [aria-label="Speakers"], .sheet-box [aria-label="Mode"], .sheet-box .sound-row, .sheet-box .stream-row').length;
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
    const rect = box.getBoundingClientRect();
    const [, x, y] = [[rect.left, rect.left / 2, innerHeight / 2], [innerWidth - rect.right, (rect.right + innerWidth) / 2, innerHeight / 2], [rect.top, innerWidth / 2, rect.top / 2], [innerHeight - rect.bottom, innerWidth / 2, (rect.bottom + innerHeight) / 2]].sort((a, b) => b[0] - a[0])[0];
    const outside = (await until(() => document.elementFromPoint(x, y) === dialog && dialog, 3000)) || document.elementFromPoint(x, y);
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
  const art = box.querySelector(".popup-head .avatar.big");
  const face = art ? {key: art.dataset.face, svg: Boolean(art.querySelector("svg.face-art .mouth")), text: art.textContent} : null;
  const shown = {...opened(), ...look(pick()), sections: all("h3", box).map((head) => head.firstChild.textContent), composer: Boolean(box.querySelector("form textarea")), offices: text(box.querySelector(".popup-body p")), face};
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
  const entry = await until(() => all("#main .entry").find((row) => row.textContent.includes("E2E call ping") && row.querySelector('.reader[data-acked="true"] .ack')), 20000);
  const read = all("#main .entry .pill").filter((pill) => text(pill) === "Read").length;
  return {to: text(someone), receipt: entry ? entry.querySelector('.reader[data-acked="true"]').title : null, read, sent: all("#main .entry").filter((row) => row.textContent.includes("E2E call ping")).length};
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
  window.e2eMedia = new Set();
  HTMLMediaElement.prototype.play = function () {
    window.e2eAudio = this;
    window.e2eMedia.add(this);
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
  location.hash = "#stream/radio";
  const edit = await until(() => all("#radio-spot button").find((button) => text(button) === "Edit stations" && button.getClientRects().length), 8000);
  edit.click();
  const form = await until(() => document.querySelector('.sheet-box form[aria-label="Stations"]'), 8000);
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
  const row = await until(() => all('#radio-spot [data-station="0"]').find((item) => item.getClientRects().length), 8000);
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
  const row = document.querySelector('#radio-spot [data-station="0"]');
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
  const now = document.querySelector('#radio-spot [data-station="0"]');
  return {clicked, state: now.dataset.state, note: text(now.querySelector(".station-note")), media, log: log()};
})()""".replace("@HELPERS@", HELPERS).replace("@MEDIA@", MEDIA)
RADIO_STOP = """(async () => {@HELPERS@@MEDIA@
  const row = () => document.querySelector('#radio-spot [data-station="0"]');
  const stop = row() ? row().querySelector('button[data-action="stop"]') : null;
  if (!stop) {
    return {error: "no Stop button on the playing station", state: row() ? row().dataset.state : null, media: sample(), log: log()};
  }
  const button = [stop.getAttribute("aria-label"), stop.title, text(stop), Boolean(stop.querySelector('svg.bi use[href="#bi-stop-fill"]'))];
  stop.click();
  const paused = Boolean(await until(() => sample() && sample().paused && sample().src === null, 8000));
  const media = await advancing();
  const now = row();
  const action = now ? now.querySelector("button[data-action]") : null;
  const elements = [...new Set([...(window.e2eMedia || []), ...all("audio, video")])];
  return {
    button, paused, media, tracked: (window.e2eMedia || new Set()).size,
    state: now ? now.dataset.state : null, note: now ? text(now.querySelector(".station-note")) : null,
    action: action ? [action.dataset.action, action.getAttribute("aria-label")] : null,
    playing: elements.filter((element) => !element.paused).map((element) => element.getAttribute("src") || element.currentSrc || element.tagName),
  };
})()""".replace("@HELPERS@", HELPERS).replace("@MEDIA@", MEDIA)
SPEAKING = """
  const caption = () => {
    const node = document.querySelector("#radio-spot:not([hidden]) .radio-caption");
    return node && !node.hidden ? node : null;
  };
  const ring = (box) => getComputedStyle(box.querySelector(".speaker-face"), "::after").animationName;
  const mouth = (art) => (art ? [art.classList.contains("speaking"), getComputedStyle(art.querySelector(".mouth")).animationName] : null);
  const faces = () => ({
    speaking: mouth(document.querySelector('#radio-spot .radio-caption .avatar[data-face="s2"]')),
    silent: mouth(document.querySelector('.avatar[data-face]:not([data-face="s2"])')),
    keys: [...new Set(all(".avatar.speaking").map((art) => art.dataset.face))],
  });
  const cue = async (word) => {
    await until(() => document.querySelector("#radio-spot:not([hidden])"), 8000);
    await fetch("/api/tts", {method: "POST", headers: {"X-Kvb-Orchestrator": "1", "Content-Type": "application/json"}, body: JSON.stringify({text: word, voice: ""}), cache: "no-store"});
    const found = await until(caption, 25000);
    return found ? {who: text(found.querySelector("strong")), line: text(found.querySelector(".caption-line")), chip: found.querySelector(".avatar").dataset.face, ring: ring(found), faces: faces()} : {error: "no caption", toasts: all("#toasts .toast").map(text)};
  };
"""
SPEAK = """(async () => {@HELPERS@@SPEAKING@
  return cue("@CUE@");
})()""".replace("@HELPERS@", HELPERS).replace("@SPEAKING@", SPEAKING)
SPEAK_GRAPH = """(async () => {@HELPERS@@SPEAKING@
  location.hash = "#agents/orbit";
  const node = await until(() => document.querySelector("#main svg .node.speaking"), 6000);
  const silent = document.querySelector('#main svg .node[data-pick="s1"] .mouth');
  return {
    node: node ? node.getAttribute("aria-label") : null, ring: node ? getComputedStyle(node.querySelector("circle")).animationName : null,
    mouth: node ? getComputedStyle(node.querySelector(".mouth")).animationName : null, silent: silent ? getComputedStyle(silent).animationName : null,
  };
})()""".replace("@HELPERS@", HELPERS).replace("@SPEAKING@", SPEAKING)
SPEAK_END = """(async () => {@HELPERS@@SPEAKING@
  const ended = Boolean(await until(() => !document.querySelector("#main svg .node") || !document.querySelector("#main svg .node.speaking"), 20000));
  location.hash = "#stream/radio";
  await until(() => document.querySelector("#radio-spot:not([hidden]) .radio-caption"), 6000);
  await sleep(300);
  return {ended, caption: Boolean(caption()), faces: all(".avatar.speaking").length};
})()""".replace("@HELPERS@", HELPERS).replace("@SPEAKING@", SPEAKING)
SPOT_OPEN = """
  const spotToggle = document.getElementById("radio-open");
  if (spotToggle && spotToggle.getAttribute("aria-expanded") !== "true") {
    spotToggle.click();
    await sleep(300);
  }
  const spot = document.getElementById("radio-spot");
"""
COMPOSE = """(async () => {@HELPERS@@SPOT_OPEN@
  const form = spot ? spot.querySelector("form.composer") : null;
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
})()""".replace("@HELPERS@", HELPERS).replace("@SPOT_OPEN@", SPOT_OPEN).replace("@CLASHES@", OVERLAP)
COMPOSE_SEND = """(async () => {@HELPERS@
  const form = document.querySelector("#radio-spot form.composer");
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
  const questions = [];
  let accept = false;
  window.confirm = (question) => {
    questions.push(question);
    return accept;
  };
  const posted = [];
  const send = window.fetch.bind(window);
  window.fetch = (path, init) => {
    if (String(path).startsWith("/api/board/")) {
      posted.push(String(path));
    }
    return send(path, init);
  };
  await until(() => document.querySelector('#main [role="toolbar"]'), 8000);
  const toolbar = all('#main [role="toolbar"] button, #main [role="toolbar"] summary').map(name);@SPOT_OPEN@
  const button = await until(() => spot && all(".spot-head button", spot).find((node) => name(node) === "Cancel mayday" && !node.disabled), 8000);
  if (!button) {
    return {error: "no enabled Cancel mayday button in the radio spot", toolbar};
  }
  const shown = new Set(all("#toasts .toast"));
  const fresh = () => all("#toasts .toast").filter((node) => !shown.has(node)).map(text);
  button.click();
  await sleep(800);
  const declined = {question: questions.slice(), posted: posted.slice(), toasts: fresh()};
  accept = true;
  button.click();
  const done = await until(() => fresh().find((toast) => toast.startsWith("Cancel mayday")), 15000);
  return {toolbar, title: button.title, shown: text(button), declined, accepted: {question: questions.slice(declined.question.length), posted: posted.slice(declined.posted.length)}, done};
})()""".replace("@HELPERS@", HELPERS).replace("@SPOT_OPEN@", SPOT_OPEN)
NIGHT_MENU = """(async () => {@HELPERS@
  const questions = [];
  window.confirm = (question) => {
    questions.push(question);
    return true;
  };
  let asked = 0;
  const get = navigator.credentials.get.bind(navigator.credentials);
  navigator.credentials.get = (options) => {
    asked += 1;
    return @SIGNS@ ? get(options) : Promise.reject(new DOMException("The operator canceled.", "NotAllowedError"));
  };
  const posted = [];
  const send = window.fetch.bind(window);
  window.fetch = (path, init) => {
    if (String(path).startsWith("/api/board/")) {
      const body = JSON.parse(init.body);
      posted.push([String(path), Object.keys(body), body.action || null]);
    }
    return send(path, init);
  };
  const menu = await until(() => all('#main [role="toolbar"] details.menu').find((node) => name(node.querySelector("summary")) === "Day/Night"), 8000);
  if (!menu) {
    return {error: text(document.getElementById("main"))};
  }
  menu.open = true;
  const buttons = all(".actions button", menu);
  const runs = [];
  for (const button of buttons) {
    const label = name(button);
    const [before, prompts, sent] = [asked, questions.length, posted.length];
    const shown = new Set(all("#toasts .toast"));
    button.click();
    const toast = await until(() => all("#toasts .toast").filter((box) => !shown.has(box)).map(text).find((entry) => entry.startsWith(`${label}:`)), 15000);
    runs.push({label, question: questions.slice(prompts), asked: asked - before, posted: posted.slice(sent), toast});
  }
  return {labels: buttons.map(name), runs};
})()""".replace("@HELPERS@", HELPERS)
NIGHT_LOOK = """(async () => {@HELPERS@
  const menu = await until(() => all('#main [role="toolbar"] details.menu').find((node) => name(node.querySelector("summary")) === "Day/Night"), 8000);
  if (!menu) {
    return {error: text(document.getElementById("main"))};
  }
  menu.open = true;
  await sleep(200);
  const box = menu.querySelector(".menu-box");
  return {
    children: [...box.children].map((node) => [node.tagName.toLowerCase(), node.className]),
    badge: all(".pill", box).map(text),
    picks: all(".night-picks label", box).map((label) => [text(label), label.querySelector("input").checked]),
    buttons: all("button", box).map((button) => [name(button), button.title]),
    paragraphs: all("p", box).length,
    wide: document.documentElement.scrollWidth > window.innerWidth + 1,
  };
})()""".replace("@HELPERS@", HELPERS)
NIGHT_PICK = """(async () => {@HELPERS@
  const questions = [];
  window.confirm = (question) => {
    questions.push(question);
    return true;
  };
  navigator.credentials.get = @SIGNS@ ? navigator.credentials.get.bind(navigator.credentials) : () => Promise.reject(new DOMException("The operator canceled.", "NotAllowedError"));
  const posted = [];
  const send = window.fetch.bind(window);
  window.fetch = (path, init) => {
    if (String(path).startsWith("/api/board/")) {
      const body = JSON.parse(init.body);
      posted.push([String(path), Object.keys(body), body.action || null, body.agents || null]);
    }
    return send(path, init);
  };
  const menu = await until(() => all('#main [role="toolbar"] details.menu').find((node) => name(node.querySelector("summary")) === "Day/Night"), 8000);
  if (!menu) {
    return {error: text(document.getElementById("main"))};
  }
  menu.open = true;
  await sleep(200);
  const box = menu.querySelector(".menu-box");
  const picks = () => all(".night-picks label", box).map((label) => [text(label), label.querySelector("input").checked]);
  const enabled = () => all(".actions button", box).map((button) => !button.disabled);
  const tick = (label) => all(".night-picks label", box).find((node) => text(node) === label).querySelector("input").click();
  const fresh = async (label, click) => {
    const shown = new Set(all("#toasts .toast"));
    click();
    return until(() => all("#toasts .toast").filter((node) => !shown.has(node)).map(text).find((entry) => entry.startsWith(`${label}:`)), 15000);
  };
  const found = {badge: all(".pill", box).map(text), start: picks()};
  tick("Skills");
  found.one = [picks(), enabled()];
  found.drain = await fresh("Drain", () => all(".actions button", box).find((button) => name(button) === "Drain").click());
  found.kept = picks();
  tick("Stage");
  found.none = [picks(), enabled()];
  tick("All");
  found.all = [picks(), enabled()];
  menu.open = false;
  document.getElementById("palette-open").click();
  const item = await until(() => all(".palette-list li").find((li) => text(li.querySelector("span")) === "Stage"), 4000);
  item.click();
  const row = await until(() => document.querySelector("#popup .agent-night"), 4000);
  found.popup = {badge: all(".pill", row).map(text), buttons: all("button", row).map(name)};
  found.suspend = await fresh("Suspend", () => all("button", row).find((button) => name(button) === "Suspend").click());
  return {...found, questions, posted, wide: document.documentElement.scrollWidth > window.innerWidth + 1};
})()""".replace("@HELPERS@", HELPERS)
FITS = "tall: document.documentElement.scrollHeight > window.innerHeight, wide: document.documentElement.scrollWidth > window.innerWidth + 1"
SPOT_SEND = """(async () => {@HELPERS@
  const questions = [];
  window.confirm = (question) => {
    questions.push(question);
    return true;
  };
  await until(() => document.querySelector('#main [role="toolbar"]'), 8000);
  const toggle = document.getElementById("radio-open");
  const main = document.getElementById("main");
  const spot = document.getElementById("radio-spot");
  const closed = [spot.hidden, toggle.getAttribute("aria-expanded")];
  toggle.click();
  await sleep(400);
  const form = spot.querySelector("form.composer");
  const [channel, recipient] = all("select", form);
  const field = form.querySelector("textarea");
  const found = {
    closed,
    open: [spot.hidden, toggle.getAttribute("aria-expanded"), document.activeElement === field],
    inline: [getComputedStyle(spot).position, spot.getBoundingClientRect().bottom <= main.getBoundingClientRect().top, spot.parentElement.nextElementSibling === main],
    toolbar: all('#main [role="toolbar"] > *').map((node) => name(node.tagName === "DETAILS" ? node.querySelector("summary") : node)),
    channels: all("option", channel).map((option) => option.value),
    record: all("button", form).filter((button) => button.hasAttribute("aria-pressed")).map(text),
    heads: all(".spot-head button", spot).map((button) => [name(button), button.title]),
    @FITS@,
  };
  await until(() => [...recipient.options].some((option) => option.value === "Stage"), 8000);
  found.runs = [];
  for (const cls of found.channels) {
    channel.value = cls;
    channel.dispatchEvent(new Event("change", {bubbles: true}));
    const direct = !recipient.closest("label").hidden;
    if (direct) {
      recipient.value = "Stage";
    }
    field.value = `@TEXT@ ${cls}`;
    field.dispatchEvent(new Event("input", {bubbles: true}));
    const shown = new Set(all("#toasts .toast"));
    const prompts = questions.length;
    const submit = form.querySelector('button[type="submit"]');
    submit.click();
    const toast = await until(() => all("#toasts .toast").filter((node) => !shown.has(node)).map(text).find((entry) => entry.includes(" to ")), 20000);
    await until(() => !submit.disabled, 20000);
    found.runs.push({cls, direct, toast, question: questions.slice(prompts), left: field.value});
  }
  document.getElementById("toasts").replaceChildren();
  return found;
})()""".replace("@HELPERS@", HELPERS).replace("@FITS@", FITS)
RADIO_JUMP = """(async () => {@HELPERS@
  const spot = await until(() => location.hash === "#stream" && document.querySelector("#radio-spot:not([hidden])"), 8000);
  if (!spot) {
    return {error: text(document.getElementById("main"))};
  }
  await sleep(200);
  const focused = document.activeElement === spot.querySelector("textarea");
  const tabs = [];
  for (const hash of ["#home", "#stream/inbox", "#agents/orbit", "#artifacts/tree", "#tasks/list", "#resources"]) {
    location.hash = hash;
    await sleep(500);
    const main = document.getElementById("main");
    tabs.push([hash, !spot.hidden, spot.getBoundingClientRect().bottom <= main.getBoundingClientRect().top]);
  }
  const toggle = document.getElementById("radio-open");
  toggle.click();
  await sleep(200);
  return {
    hash: "#stream", focused, tabs, closed: [spot.hidden, toggle.getAttribute("aria-expanded")],
    header: all("header.top button").map((button) => [button.id, name(button), text(button)]), radioTab: Boolean(document.getElementById("tab-radio")),
  };
})()""".replace("@HELPERS@", HELPERS)
CANCELED = """() => {
  window.e2ePasskeys = 0;
  if (navigator.credentials) {
    navigator.credentials.get = () => {
      window.e2ePasskeys += 1;
      return Promise.reject(new DOMException("The operator canceled.", "NotAllowedError"));
    };
  }
}"""
JUMPED = {
    "hash": "#stream", "focused": True, "tabs": [[tab, True, True] for tab in ("#home", "#stream/inbox", "#agents/orbit", "#artifacts/tree", "#tasks/list", "#resources")], "closed": [True, "false"],
    "header": [["radio-open", "Radio", ""], ["bubbles-toggle", "Speech bubbles", ""], ["palette-open", "Commands", ""], ["settings-open", "Settings", ""]], "radioTab": False,
}
PRESENCE_HELPERS = """
  const states = () => all("#main .presence:not(label)").map((node) => node.dataset.state).sort();
  const statusMenu = () => {
    const menu = all('#main [role="toolbar"] details.menu').find((node) => name(node.querySelector("summary")) === "Status");
    menu.open = true;
    return menu;
  };
  const looks = (menu) => all("input[data-look]", menu).map((input) => [input.dataset.look, input.checked]);
  const graph3d = async (faces) => {
    const box = await until(() => {
      const found = document.querySelector("#main .graph3d");
      return found && found.dataset.faces !== undefined && (faces === null || found.dataset.faces === faces) ? found : null;
    }, 15000);
    return box ? [Number(box.dataset.faces), Number(box.dataset.badges)] : null;
  };
"""
PRESENCE_WALK = """(async () => {@HELPERS@@PRESENCE@
  const views = {};
  for (const view of ["orbit", "chord", "swimlane", "tree", "hierarchy"]) {
    location.hash = `#agents/${view}`;
    await screenShown(6000);
    await until(() => all("#main .presence:not(label)").length, 6000);
    views[view] = states();
  }
  location.hash = "#agents/orbit";
  await screenShown(6000);
  const node = await until(() => document.querySelector('#main svg .node[data-pick="s1"]'), 6000);
  const motion = getComputedStyle(node.querySelector(".presence .glyph")).animationName;
  node.dispatchEvent(new MouseEvent("click", {bubbles: true}));
  const mark = await until(() => document.querySelector("#popup .presence"), 4000);
  const profile = mark ? [mark.dataset.state, text(mark), mark.getAttribute("aria-label")] : null;
  (document.activeElement || document.body).dispatchEvent(new KeyboardEvent("keydown", {key: "Escape", bubbles: true}));
  await sleep(300);
  location.hash = "#agents/3d";
  const shown = await graph3d(null);
  const menu = statusMenu();
  const before = looks(menu);
  menu.querySelector('input[data-look="working"]').click();
  menu.querySelector('input[data-look="faces"]').click();
  const hidden = await graph3d("0");
  location.hash = "#agents/orbit";
  await screenShown(6000);
  await until(() => document.querySelector('#main svg .node[data-pick="s2"]'), 6000);
  return {views, motion, profile, shown, before, hidden, orbit: states(), @FITS@};
})()""".replace("@HELPERS@", HELPERS).replace("@PRESENCE@", PRESENCE_HELPERS).replace("@FITS@", FITS)
PRESENCE_READ = """(async () => {@HELPERS@@PRESENCE@
  await until(() => document.querySelector('#main svg .node[data-pick="s2"]'), 8000);
  await sleep(300);
  const menu = statusMenu();
  const kept = {boxes: looks(menu), orbit: states()};
  menu.querySelector('input[data-look="working"]').click();
  menu.querySelector('input[data-look="faces"]').click();
  await sleep(300);
  const back = states();
  location.hash = "#agents/3d";
  return {...kept, back, restored: await graph3d(null)};
})()""".replace("@HELPERS@", HELPERS).replace("@PRESENCE@", PRESENCE_HELPERS)
GEAR_SAVE = """(async () => {@HELPERS@@CLASHES@
  const spot = document.getElementById("radio-spot");
  const face = spot.querySelector(".radio-face");
  const gear = all(".spot-head button", spot).find((button) => name(button) === "Read aloud");
  gear.click();
  const box = await until(() => spot.querySelector("#radio-gear .radio-read"), 4000);
  if (!box) {
    return {error: "no read-aloud filters behind the gear"};
  }
  const chips = () => all('#radio-gear [aria-label="Classes"] button', spot);
  const post = () => chips().find((chip) => text(chip) === "Post");
  const found = {
    expanded: gear.getAttribute("aria-expanded"),
    tones: all(".radio-knobs .knob-label", face).map(text),
    classes: chips().map((chip) => [text(chip), chip.getAttribute("aria-pressed"), chip.disabled]),
    clashes: [clashes(face), clashes(spot.querySelector("#radio-gear"))],
    @FITS@,
  };
  const squelch = face.querySelector('input[aria-label="Squelch"]');
  squelch.value = "@SQUELCH@";
  squelch.dispatchEvent(new Event("input", {bubbles: true}));
  const tone = face.querySelector('button[aria-label="All radio tone"]');
  if (tone.getAttribute("aria-pressed") !== "@TONE@") {
    tone.click();
  }
  if (post().getAttribute("aria-pressed") !== "@POST@") {
    post().click();
  }
  await sleep(200);
  const kept = JSON.parse(localStorage.getItem("kvb-orchestrator.radio"));
  found.kept = [kept.squelch, kept.sounds.radio.on, kept.classes.includes("post")];
  gear.click();
  await sleep(200);
  found.after = [gear.getAttribute("aria-expanded"), Boolean(spot.querySelector("#radio-gear .radio-read"))];
  document.getElementById("settings-open").click();
  const sheet = await until(() => document.querySelector(".sheet-box form.settings"), 4000);
  found.general = {sections: all("section > h3", sheet).map(text), radio: all('[aria-label="Squelch"], [aria-label="Classes"], [aria-label="Speakers"], [aria-label="Mode"], .sound-row, .stream-row', sheet).length};
  document.querySelector(".sheet-head button").click();
  return found;
})()""".replace("@HELPERS@", HELPERS).replace("@CLASHES@", OVERLAP).replace("@FITS@", FITS)
GEAR_READ = """(async () => {@HELPERS@@SPOT_OPEN@
  const gear = spot ? all(".spot-head button", spot).find((button) => name(button) === "Read aloud") : null;
  if (!gear) {
    return {error: text(document.getElementById("main"))};
  }
  gear.click();
  await until(() => spot.querySelector("#radio-gear .radio-read"), 4000);
  const face = spot.querySelector(".radio-face");
  return {
    squelch: Number(face.querySelector('input[aria-label="Squelch"]').value),
    tone: face.querySelector('button[aria-label="All radio tone"]').getAttribute("aria-pressed") === "true",
    post: all('#radio-gear [aria-label="Classes"] button', spot).find((chip) => text(chip) === "Post").getAttribute("aria-pressed") === "true",
    @FITS@,
  };
})()""".replace("@HELPERS@", HELPERS).replace("@SPOT_OPEN@", SPOT_OPEN).replace("@FITS@", FITS)
GRAPH_HOOK = """() => {
  let made = null;
  Object.defineProperty(window, "ForceGraph3D", {
    configurable: true,
    get: () => made && ((options) => {
      const graph = made(options);
      window.e2eGraphs = [...(window.e2eGraphs || []), graph];
      return graph;
    }),
    set: (value) => {
      made = value;
    },
  });
}"""
CAMERA = """(async () => {@HELPERS@
  const ready = await until(() => window.e2eGraphs && document.querySelector("#main .graph3d canvas") && !text(document.querySelector("#main .space-note")).startsWith("Loading"), 15000);
  if (!ready) {
    return {error: text(document.querySelector("#main .graph"))};
  }
  const graph = window.e2eGraphs[window.e2eGraphs.length - 1];
  const position = () => {
    const at = graph.cameraPosition();
    return [at.x, at.y, at.z];
  };
  await sleep(5500);
  let [fed, stops] = [0, 0];
  const stopped = graph.onEngineStop();
  graph.onEngineStop(() => {
    stops += 1;
    stopped();
  });
  const feed = graph.graphData;
  graph.graphData = function (...args) {
    fed += args.length;
    return feed.apply(graph, args);
  };
  const built = position();
  const canvas = document.querySelector("#main .graph3d canvas");
  const rect = canvas.getBoundingClientRect();
  for (let turn = 0; turn < 4; turn += 1) {
    canvas.dispatchEvent(new WheelEvent("wheel", {deltaY: -120, clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2, bubbles: true, cancelable: true}));
    await sleep(60);
  }
  await sleep(900);
  const moved = position();
  const refreshes = [];
  for (let round = 0; round < 2; round += 1) {
    const [feeds, ends] = [fed, stops];
    document.dispatchEvent(new Event("visibilitychange"));
    const rebuilt = Boolean(await until(() => fed > feeds, 8000));
    const settled = Boolean(await until(() => stops > ends, 10000));
    await sleep(900);
    refreshes.push({rebuilt, settled, camera: position()});
  }
  all("#main button").find((button) => name(button) === "Reset view").click();
  await sleep(1500);
  return {hooked: typeof stopped === "function", built, moved, refreshes, reset: position()};
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


UNLABELLED = """
  const unlabelled = (root, skip) => all("svg.bi", root).filter((svg) => !svg.closest(".sprite") && !(skip && skip.contains(svg))).map((svg) => svg.parentElement).filter((owner) => !text(owner) && !(owner.getAttribute("title") && owner.getAttribute("aria-label"))).map((owner) => owner.outerHTML.slice(0, 160));
"""
LABELS = UNLABELLED + """
  const wide = () => document.documentElement.scrollWidth > window.innerWidth + 1;
  const rowOf = (words) => all("#main .inbox-list > li").find((li) => li.textContent.includes(words));
  const askOf = (command) => all("#main .inbox-list > li.k-ask").find((li) => text(li.querySelector(".command code")) === command);
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
INBOX_PICK = """(async () => {@HELPERS@
  navigator.credentials.get = @SIGNS@ ? navigator.credentials.get.bind(navigator.credentials) : () => Promise.reject(new DOMException("The operator canceled.", "NotAllowedError"));
  const posted = [];
  const send = window.fetch.bind(window);
  window.fetch = (path, init) => {
    if (["/api/sign", "/api/inbox/approve"].includes(String(path))) {
      posted.push([String(path), JSON.parse(init.body).items.map((item) => [item.id, item.verb, item.channel || null])]);
    }
    return send(path, init);
  };
  const list = await until(() => document.querySelector("#main .inbox-list"), 8000);
  if (!list) {
    return {error: text(document.getElementById("main"))};
  }
  let scroller = list;
  while (scroller && !(scroller.scrollHeight > scroller.clientHeight + 4 && getComputedStyle(scroller).overflowY !== "visible")) {
    scroller = scroller.parentElement;
  }
  scroller = scroller || document.scrollingElement;
  const last = all("#main .inbox-list > li").filter((li) => li.textContent.includes("echo row")).pop();
  last.scrollIntoView({block: "center"});
  await sleep(300);
  const title = text(last.querySelector(".command code"));
  const before = scroller.scrollTop;
  last.querySelector("input").click();
  await sleep(300);
  const after = scroller.scrollTop;
  const holder = document.activeElement && document.activeElement.closest("li");
  const focused = Boolean(holder && text(holder.querySelector(".command code")) === title && document.activeElement.checked);
  all("#main .inbox-list > li").find((li) => li.textContent.includes("pick a name")).querySelector("input").click();
  await sleep(300);
  const buttons = all("#main .inbox-actions button").map(name);
  all("#main .inbox-actions button").find((button) => name(button).startsWith("Deny selection")).click();
  await until(() => document.querySelector(".sheet-box .actions"), 4000);
  const listed = all(".sheet-box ul.mini > li strong").map(text);
  const confirm = all(".sheet-box .actions button").find((button) => text(button).startsWith("Deny "));
  const label = text(confirm);
  const shown = new Set(all("#toasts .toast"));
  confirm.click();
  const toast = await until(() => all("#toasts .toast").filter((node) => !shown.has(node)).map(text).find((entry) => entry.startsWith("Deny selection")), 15000);
  return {title, before, moved: Math.abs(after - before), focused, buttons, listed, label, toast, posted, wide: document.documentElement.scrollWidth > window.innerWidth + 1};
})()""".replace("@HELPERS@", HELPERS)
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
  const row = await until(() => askOf("make deploy"), 8000);
  if (!row) {
    return {error: text(document.getElementById("main"))};
  }
  press(row, "Deny via …");
  const box = await until(() => document.querySelector(".sheet-box"), 4000);
  box.querySelector('input[value="call"]').click();
  box.querySelector("textarea").value = "make the gate green first";
  press(box.querySelector(".actions"), "Deny");
  const undo = await until(() => all("#toasts .toast.wait").find((toast) => toast.textContent.includes("Denial")), 8000);
  return {undo: text(undo), sheet: !document.getElementById("sheet").hidden};
})()""".replace("@HELPERS@", HELPERS).replace("@LABELS@", LABELS)
DENIED = """(async () => {@HELPERS@@LABELS@
  return {gone: Boolean(await until(() => !askOf("make deploy"), 20000))};
})()""".replace("@HELPERS@", HELPERS).replace("@LABELS@", LABELS)
ACCEPT = """(async () => {@HELPERS@@LABELS@
  press(rowOf("Rule request"), "Accept");
  const toast = await until(() => all("#toasts .toast").find((box) => box.textContent.includes("Created: Rule")), 15000);
  await until(() => !rowOf("Rule request"), 8000);
  return {toast: text(toast), left: Boolean(rowOf("Rule request"))};
})()""".replace("@HELPERS@", HELPERS).replace("@LABELS@", LABELS)
WATCH = """
  const questions = [];
  window.confirm = (question) => {
    questions.push(question);
    return true;
  };
  let asked = 0;
  const get = navigator.credentials.get.bind(navigator.credentials);
  navigator.credentials.get = (options) => {
    asked += 1;
    return @SIGNS@ ? get(options) : Promise.reject(new DOMException("The operator canceled.", "NotAllowedError"));
  };
  const posted = [];
  const send = window.fetch.bind(window);
  window.fetch = (path, init) => {
    if (["/api/choices/sign", "/api/choices", "/api/sign", "/api/inbox/approve"].includes(String(path))) {
      const body = JSON.parse(init.body);
      posted.push([String(path), Object.keys(body).sort(), body.class || null, body.to || null]);
    }
    return send(path, init);
  };
  const bar = () => document.getElementById("choice-request");
  const fresh = async (shown, prefix) => until(() => all("#toasts .toast").filter((box) => !shown.has(box)).map(text).find((entry) => entry.startsWith(prefix)), 20000);
  const fits = () => ({tall: document.documentElement.scrollHeight > window.innerHeight, wide: document.documentElement.scrollWidth > window.innerWidth + 1});
"""
CHOICE_VIEW = """(async () => {@HELPERS@@LABELS@
  const found = await until(() => document.getElementById("choice-request") && all("#main .inbox-list > li .options").length === @CARDS@ && document.querySelector('#choice-request input[type="checkbox"]'), 8000);
  if (!found) {
    return {error: text(document.getElementById("main"))};
  }
  const box = document.getElementById("choice-request");
  const chip = document.querySelector('#main [aria-label="Task filters"] button[data-filter="operator"]');
  const closed = all("button[data-channel]", box).filter((button) => button.checkVisibility()).length;
  return {
    kinds: [...new Set(all("#main .inbox-list > li").map((li) => text(li.querySelector(".pill"))))].sort(),
    filter: [text(chip).replace(/[0-9]+$/, ""), chip.getAttribute("aria-pressed")],
    channels: all("button[data-channel]", box).map((button) => [button.dataset.channel, name(button), button.disabled]),
    fields: all("textarea, input:not([type=checkbox])", box).length,
    agents: all('input[type="checkbox"]', box).map((input) => input.value),
    multi: [name(box.querySelector("summary")), box.open, closed, text(box.querySelector(".menu-box h3 .count")), all('input[type="checkbox"]', box).filter((input) => input.checked).length],
    bar: [box.parentElement.getAttribute("aria-label"), toolbarRows(), taskLayout()],
    cards: all("#main .inbox-list > li").filter((li) => li.querySelector(".options")).map((li) => [text(li.querySelector(".pill")), all(".option strong", li).map(text)]),
    choices: all("#main [data-column], #main .group-title, #main h2, #main h3").filter((node) => node.dataset.column === "choices" || text(node) === "Choices").length,
    unlabelled: unlabelled(document),
    tall: document.documentElement.scrollHeight > window.innerHeight,
    wide: wide(),
  };
})()""".replace("@HELPERS@", HELPERS).replace("@LABELS@", LABELS)
CHOICE_SEND = """(async () => {@HELPERS@@WATCH@
  const menu = bar();
  menu.querySelector("summary").click();
  await sleep(200);
  const boxes = all('input[type="checkbox"]', menu).slice(0, 2);
  boxes.forEach((box) => box.click());
  const counted = text(menu.querySelector(".menu-box h3 .count"));
  const opened = [menu.open, all("button[data-channel]", menu).filter((button) => button.checkVisibility()).length];
  const picked = boxes.map((box) => box.value).sort((a, b) => a.localeCompare(b));
  const runs = [];
  for (const button of all("button[data-channel]", bar())) {
    const [before, prompts, sent] = [asked, questions.length, posted.length];
    const shown = new Set(all("#toasts .toast"));
    const disabled = button.disabled;
    button.click();
    const toast = await fresh(shown, "Choice request");
    runs.push({channel: button.dataset.channel, disabled, asked: asked - before, question: questions.slice(prompts), posted: posted.slice(sent), toast});
  }
  return {picked, counted, opened, runs, fields: all("textarea, input:not([type=checkbox])", bar()).length, ...fits()};
})()""".replace("@HELPERS@", HELPERS).replace("@WATCH@", WATCH)
CHOICE_ANSWER = """(async () => {@HELPERS@@WATCH@
  bar().querySelector("summary").click();
  await sleep(200);
  const closed = [bar().open, all("button[data-channel]", bar()).filter((button) => button.checkVisibility()).length];
  const card = await until(() => all("#main .inbox-list > li").find((li) => li.textContent.includes("@QUESTION@")), 8000);
  if (!card) {
    return {error: text(document.getElementById("main"))};
  }
  const option = all(".option", card).find((button) => text(button.querySelector("strong")) === "Wait");
  const title = option.title;
  const shown = new Set(all("#toasts .toast"));
  option.click();
  const toast = await fresh(shown, "Choice: Wait");
  const gone = @SIGNS@ ? Boolean(await until(() => !all("#main .inbox-list > li").some((li) => li.textContent.includes("@QUESTION@")), 20000)) : null;
  return {title, asked, posted, toast, gone, closed, ...fits()};
})()""".replace("@HELPERS@", HELPERS).replace("@WATCH@", WATCH)
TASKS_FIT = """(async () => {@HELPERS@
  await until(() => document.getElementById("choice-request") && document.querySelector("#main .tasks-body > *"), 8000);
  document.getElementById("toasts").replaceChildren();
  await sleep(300);
  return {
    hash: location.hash,
    bar: all("#choice-request button[data-channel]").map((button) => button.dataset.channel),
    rows: toolbarRows(),
    layout: taskLayout(),
    columns: all("#main .task-column").map((column) => column.dataset.column),
    choices: all("#main [data-column], #main .group-title, #main h2, #main h3").filter((node) => node.dataset.column === "choices" || text(node) === "Choices").length,
    tall: document.documentElement.scrollHeight > window.innerHeight,
    wide: document.documentElement.scrollWidth > window.innerWidth + 1,
  };
})()""".replace("@HELPERS@", HELPERS)
PLAN_HELPERS = """
  const fits = () => ({tall: document.documentElement.scrollHeight > window.innerHeight, wide: document.documentElement.scrollWidth > window.innerWidth + 1, rows: toolbarRows(), layout: taskLayout()});
  const modes = () => all('#main [aria-label="Estimation"] button').map((button) => [button.dataset.estimation, button.getAttribute("aria-pressed")]);
  const requestShown = () => {
    const button = document.getElementById("request-estimates");
    return button ? !button.hidden && button.getClientRects().length > 0 : null;
  };
  const choose = async (select, value) => {
    select.value = value;
    select.dispatchEvent(new Event("change", {bubbles: true}));
    await sleep(300);
  };
  const fresh = async (shown, prefix) => until(() => all("#toasts .toast").filter((box) => !shown.has(box)).map(text).find((entry) => entry.startsWith(prefix)), 20000);
"""
GANTT = """(async () => {@HELPERS@@PLAN_HELPERS@
  const svg = await until(() => document.querySelector("#main svg.gantt"), 8000);
  if (!svg) {
    return {error: text(document.getElementById("main"))};
  }
  const forecast = document.querySelector('#main select[aria-label="Forecast"]');
  const scroll = document.querySelector("#main .gantt-scroll");
  const marks = () => all("#main svg.gantt [data-forecast]").map((mark) => [mark.dataset.task, mark.dataset.forecast === "true", Number(mark.dataset.start), Number(mark.dataset.end), mark.tagName.toLowerCase()]);
  const found = {
    hash: location.hash,
    forecast: [forecast.value, all("option", forecast).map((option) => [option.value, text(option)])],
    modes: modes(),
    request: requestShown(),
    bars: marks(),
    edges: all("#main svg.gantt path.gantt-edge").map((path) => [path.dataset.kind, path.dataset.from, path.dataset.to, path.getAttribute("marker-end")]),
    hatched: all("#main svg.gantt .gantt-bar.forecast").map((bar) => getComputedStyle(bar).fill.includes("gantt-hatch")),
    inner: Boolean(scroll && scroll.closest(".tasks-body")),
    ...fits(),
  };
  await choose(forecast, "real");
  found.real = marks().filter(([, hatched]) => hatched).length;
  await choose(forecast, "points");
  found.pointsOnly = marks().filter(([, hatched]) => hatched).map(([task, , start, end, tag]) => [task, end - start, tag]);
  await choose(forecast, "always");
  return found;
})()""".replace("@HELPERS@", HELPERS).replace("@PLAN_HELPERS@", PLAN_HELPERS)
BURN = """(async () => {@HELPERS@@PLAN_HELPERS@
  const svg = await until(() => document.querySelector("#main svg.burn"), 8000);
  if (!svg) {
    return {error: text(document.getElementById("main"))};
  }
  const scope = document.querySelector('#main select[aria-label="Scope"]');
  const series = () => all("#main svg.burn path.burn-line").map((path) => [path.dataset.series, Number(path.dataset.last)]);
  const found = {hash: location.hash, modes: modes(), request: requestShown(), scope: [scope.value, all("option", scope).map((option) => option.value)], series: series(), ...fits()};
  await choose(scope, "agent:Docs");
  found.agent = series();
  await choose(scope, "all");
  return found;
})()""".replace("@HELPERS@", HELPERS).replace("@PLAN_HELPERS@", PLAN_HELPERS)
POINTS_ON = """(async () => {@HELPERS@@PLAN_HELPERS@
  const before = {modes: modes(), request: requestShown()};
  all('#main [aria-label="Estimation"] button').find((button) => button.dataset.estimation === "points").click();
  const shown = await until(() => requestShown(), 8000);
  return {before, modes: modes(), request: Boolean(shown), ...fits()};
})()""".replace("@HELPERS@", HELPERS).replace("@PLAN_HELPERS@", PLAN_HELPERS)
REQUEST = """(async () => {@HELPERS@@PLAN_HELPERS@
  const svg = await until(() => document.querySelector("#main svg.burn") && requestShown(), 8000);
  if (!svg) {
    return {error: text(document.getElementById("main")), modes: modes()};
  }
  const series = all("#main svg.burn path.burn-line").map((path) => [path.dataset.series, Number(path.dataset.last)]);
  const shown = new Set(all("#toasts .toast"));
  document.getElementById("request-estimates").click();
  const toast = await fresh(shown, "Request estimates");
  return {modes: modes(), series, toast, ...fits()};
})()""".replace("@HELPERS@", HELPERS).replace("@PLAN_HELPERS@", PLAN_HELPERS)
BULK = """(async () => {@HELPERS@@PLAN_HELPERS@
  const list = await until(() => all("#main .task-row").length && document.getElementById("bulk-value"), 8000);
  if (!list) {
    return {error: text(document.getElementById("main"))};
  }
  let asked = 0;
  const get = navigator.credentials.get.bind(navigator.credentials);
  navigator.credentials.get = (options) => {
    asked += 1;
    return @SIGNS@ ? get(options) : Promise.reject(new DOMException("The operator canceled.", "NotAllowedError"));
  };
  const posted = [];
  const send = window.fetch.bind(window);
  window.fetch = (path, init) => {
    if (["/api/sign", "/api/tasks"].includes(String(path))) {
      const body = JSON.parse(init.body);
      posted.push([String(path), Object.keys(body).sort(), body.items.map((item) => [item.id, item.argv.join(" ")])]);
    }
    return send(path, init);
  };
  const rows = () => all("#main .task-row").map((row) => row.dataset.task);
  const sort = document.querySelector('#main select[aria-label="Sort"]');
  const direction = document.querySelector("#main button[data-direction]");
  const found = {sorts: all("option", sort).map((option) => option.value), prio: rows()};
  await choose(sort, "status");
  found.status = rows();
  direction.click();
  await sleep(300);
  found.statusDown = [rows(), name(direction)];
  direction.click();
  await choose(sort, "prio");
  found.picks = all("#main .task-row input.task-pick").map((box) => box.closest(".task-row").dataset.task);
  for (const task of ["work/next", "work/child"]) {
    all("#main .task-row").find((row) => row.dataset.task === task).querySelector("input.task-pick").click();
  }
  const button = document.getElementById("bulk-value");
  found.armed = [button.disabled, text(button.querySelector(".count"))];
  await choose(document.querySelector('#main select[aria-label="Business value of the selection"]'), "@VALUE@");
  const shown = new Set(all("#toasts .toast"));
  button.click();
  found.toast = await fresh(shown, "Business value @VALUE@ for 2 tasks");
  found.asked = asked;
  found.posted = posted;
  found.after = [button.disabled, all("#main .task-row input.task-pick:checked").length];
  Object.assign(found, fits());
  all('#main [aria-label="Estimation"] button').find((entry) => entry.dataset.estimation === "none").click();
  found.reset = Boolean(await until(() => requestShown() === false, 8000));
  return found;
})()""".replace("@HELPERS@", HELPERS).replace("@PLAN_HELPERS@", PLAN_HELPERS)
ETA_LIST = """(async () => {@HELPERS@@PLAN_HELPERS@
  const list = await until(() => all("#main .task-row .task-eta").length >= 8, 8000);
  if (!list) {
    return {error: text(document.getElementById("main"))};
  }
  const number = (value) => (value === "" ? null : Number(value));
  const read = () => Object.fromEntries(all("#main .task-row").map((row) => {
    const eta = row.querySelector(".task-eta");
    return [row.dataset.task, [number(eta.dataset.start), number(eta.dataset.eta), eta.dataset.forecast === "true", text(eta), eta.title]];
  }));
  const toggle = async (mode) => {
    const before = JSON.stringify(read());
    all('#main [aria-label="Estimation"] button').find((button) => button.dataset.estimation === mode).click();
    await until(() => JSON.stringify(read()) !== before, 8000);
    await sleep(300);
    return read();
  };
  const found = {none: read(), modes: modes(), ...fits()};
  found.points = await toggle("points");
  found.back = await toggle("none");
  return found;
})()""".replace("@HELPERS@", HELPERS).replace("@PLAN_HELPERS@", PLAN_HELPERS)
TREND_READ = """
  const trendOf = () => {
    const select = document.querySelector('#main select[aria-label="Trend"]');
    const days = document.querySelector('#main input[aria-label="Velocity days"]');
    const note = document.querySelector("#main .burn-forecast");
    const marker = document.querySelector("#main svg.burn .forecast-line");
    return {
      value: select.value, options: all("option", select).map((option) => [option.value, text(option)]), days: [Number(days.value), days.getClientRects().length > 0],
      note: note ? [note.dataset.forecast === "" ? null : Number(note.dataset.forecast), text(note)] : null, marker: marker ? Number(marker.dataset.forecast) : null,
      lines: all("#main svg.burn path.burn-trend").map((path) => [path.dataset.series, Number(path.dataset.from), Number(path.dataset.to)]),
      points: all('#main svg.burn circle.burn-point[data-series="remaining"]').map((circle) => [Number(circle.dataset.t), Number(circle.dataset.value)]),
    };
  };
  const chart = async () => until(() => document.querySelector("#main svg.burn") && document.querySelector('#main select[aria-label="Trend"]'), 8000);
"""
TREND_SET = """(async () => {@HELPERS@@PLAN_HELPERS@@TREND_READ@
  if (!(await chart())) {
    return {error: text(document.getElementById("main"))};
  }
  const before = trendOf();
  const shown = new Set(all("#toasts .toast"));
  await choose(document.querySelector('#main select[aria-label="Trend"]'), "@MODE@");
  const toasts = [await fresh(shown, "Trend: ")];
  if ("@MODE@" === "velocity") {
    const days = document.querySelector('#main input[aria-label="Velocity days"]');
    const again = new Set(all("#toasts .toast"));
    days.value = "@DAYS@";
    days.dispatchEvent(new Event("change", {bubbles: true}));
    toasts.push(await fresh(again, "Trend: velocity over @DAYS@ days"));
  }
  await sleep(400);
  return {before, after: trendOf(), toasts, ...fits()};
})()""".replace("@HELPERS@", HELPERS).replace("@PLAN_HELPERS@", PLAN_HELPERS).replace("@TREND_READ@", TREND_READ)
TREND_RELOADED = """(async () => {@HELPERS@@PLAN_HELPERS@@TREND_READ@
  if (!(await chart())) {
    return {error: text(document.getElementById("main"))};
  }
  await sleep(300);
  return {...trendOf(), ...fits()};
})()""".replace("@HELPERS@", HELPERS).replace("@PLAN_HELPERS@", PLAN_HELPERS).replace("@TREND_READ@", TREND_READ)
STEP_TIPS = """(async () => {@HELPERS@@PLAN_HELPERS@@TREND_READ@
  if (!(await chart())) {
    return {error: text(document.getElementById("main"))};
  }
  const steps = all('#main svg.burn circle.burn-point[data-series="remaining"]').map((circle) => ({
    t: Number(circle.dataset.t), started: circle.dataset.started, ended: circle.dataset.ended, joined: circle.dataset.joined, tip: text(circle.querySelector("title")),
    series: all(`#main svg.burn circle.burn-point[data-step="${circle.dataset.step}"]`).map((mark) => mark.dataset.series),
  }));
  const shown = new Set(all("#toasts .toast"));
  await choose(document.querySelector('#main select[aria-label="Trend"]'), "off");
  const reset = await fresh(shown, "Trend: off");
  await sleep(300);
  return {steps, reset, note: Boolean(document.querySelector("#main .burn-forecast")), lines: all("#main svg.burn path.burn-trend").length, ...fits()};
})()""".replace("@HELPERS@", HELPERS).replace("@PLAN_HELPERS@", PLAN_HELPERS).replace("@TREND_READ@", TREND_READ)
TASKS_3D = """(async () => {@HELPERS@@PLAN_HELPERS@
  const note = () => text(document.querySelector("#main .space-note")) || "";
  const ready = await until(() => window.e2eGraphs && document.querySelector("#main .graph3d canvas") && !note().startsWith("Loading"), 15000);
  if (!ready) {
    return {error: text(document.querySelector("#main .graph"))};
  }
  const graph = () => window.e2eGraphs[window.e2eGraphs.length - 1];
  const id = (end) => (typeof end === "object" ? end.id : end);
  const look = () => {
    const data = graph().graphData();
    const color = graph().linkColor();
    return {
      note: note(), layouts: all('#main [aria-label="Layout"] button').map((button) => [button.dataset.layout, button.getAttribute("aria-pressed")]),
      nodes: data.nodes.map((node) => [node.id, Number.isFinite(node.fz) ? node.fz : null, Number.isFinite(node.ts) ? node.ts : null]),
      links: data.links.map((link) => [id(link.source), id(link.target), link.kind, color(link)]),
      label: (() => {
        const shown = graph().nodeLabel()(data.nodes.find((node) => node.id === "work/t5"));
        return shown instanceof Element ? shown.textContent : String(shown);
      })(),
    };
  };
  const layout = async (mode, word) => {
    all('#main [aria-label="Layout"] button').find((button) => button.dataset.layout === mode).click();
    await until(() => note().endsWith(word), 8000);
    await sleep(400);
    return look();
  };
  const css = getComputedStyle(document.documentElement);
  const palette = Object.fromEntries(["violet", "info", "warn"].map((role) => [role, css.getPropertyValue(`--${role}`).trim()]));
  const force = look();
  const time = await layout("time", "Time");
  const field = document.querySelector('#main input[aria-label="Find a node"]');
  field.value = "work/t5";
  field.dispatchEvent(new Event("input", {bubbles: true}));
  await sleep(200);
  const chip = all("#main .hits .chip").find((node) => node.dataset.hit === "work/t5");
  if (!chip) {
    return {error: "no search hit", force, time};
  }
  chip.click();
  await sleep(600);
  const dialog = document.getElementById("popup");
  const eta = dialog.querySelector(".task-eta");
  const popup = {
    open: dialog.open, title: text(dialog.querySelector(".popup-box .panel-title")), id: text(dialog.querySelector(".popup-head .task-id")), picked: document.querySelector("#main .graph3d").dataset.picked || null,
    eta: eta ? eta.dataset.eta : null, open_button: name(dialog.querySelector(".popup-body .actions button")), line: dialog.querySelector(".leader line").getAttribute("display") !== "none",
  };
  (document.activeElement || document.body).dispatchEvent(new KeyboardEvent("keydown", {key: "Escape", bubbles: true}));
  await sleep(300);
  popup.closed = [dialog.open, document.querySelector("#main .graph3d").dataset.picked || null];
  const back = await layout("none", "Force");
  await sleep(1200);
  return {palette, force, time, popup, back: back.note, ...fits()};
})()""".replace("@HELPERS@", HELPERS).replace("@PLAN_HELPERS@", PLAN_HELPERS)
PLAN_VALUES = {1920: "13", 1366: "21", 390: "34"}
TREND_DAYS = {1920: 7, 1366: 3, 390: 14}
STATUS_ORDER = ["queued", "awaiting", "claimed", "running", "blocked", "stale", "done", "stopped"]
CHOICE_REQUEST = "send me your open decisions as choices"
CHOICE_CHANNELS = ["post", "call", "newsletter", "broadcast", "pan-pan", "security", "mayday"]
NIGHT_HINTS = [
    ("Drain", "Drain: the agents finish their task and take nothing new; your passkey signs it"),
    ("Suspend", "Suspend: the agents park their work, write the handover and idle; your passkey signs it"),
    ("Resume", "Resume: all agents continue from their handover; your passkey signs it"),
]
SLOW ="seq -f 'Row %g' 1 60; sleep 4; seq -f 'Row %g' 61 80; sleep 4; echo finished"


def labelled(probe: dict) -> dict:
    return {key: probe[key] for key in ("unlabelled", "broken")}


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestOrchestratorE2E(HubCase):
    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        self.seed()

    def seed(self) -> None:
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
        self.create_ask({**ASK, "timeout": 3600})
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
        spoken = tone(6, 8000)

        def synthesize(body: bytes, admit: Callable[[str], None]) -> bytes:
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
            {"width": 1366, "height": 768, "url": None, "wait": 0, "probe": RADIO_STOP, "shot": str(OUT / f"{browser}-1366-radio-stopped.png")},
        ]
        data = self.drive(steps, self.authenticator() if signs else None, driver, binary, MEDIA_LOG)
        (OUT / f"{browser}-radio.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        saved, view, click, stopped = data["results"]
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
        with self.subTest(browser=browser, part="station stop"):
            self.assertNotIn("error", stopped, stopped)
            self.assertEqual(stopped["button"], ["Stop", f"Stop: pause {STATION_NAME}", "", True])
            self.assertTrue(stopped["paused"], stopped)
            self.assertFalse(stopped["media"]["playing"], stopped)
            self.assertEqual((stopped["media"]["second"]["paused"], stopped["media"]["second"]["src"]), (True, None), stopped)
            self.assertEqual((stopped["state"], stopped["note"], stopped["action"]), ("stopped", "stopped", ["play", "Play"]), stopped)
            self.assertGreater(stopped["tracked"], 0, stopped)
            self.assertEqual(stopped["playing"], [], "an audio element still plays after Stop")
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
                self.assertEqual(agent["shown"]["face"], {"key": "s2", "svg": True, "text": ""})
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
                self.assertEqual(probe["header"], ["radio-open", "bubbles-toggle", "palette-open", "settings-open"])
                self.assertEqual((probe["tabs"], probe["subs"]), (TABS, SUBS))
                self.assertEqual(probe["badges"], {"tab-home": None, "tab-stream": None, "tab-rules": None, "tab-agents": "1", "tab-artifacts": None, "tab-tasks": "2", "tab-resources": None})
                self.assertEqual(probe["banner"], "MAYDAY · Docs: disk full")
                self.assertFalse(probe["rail"])
                self.assertEqual((probe["time"], probe["replay"]), ("24 h ▾", True))
                self.assertGreater(probe["icons"], 8)
                self.assertEqual(labelled(probe), {"unlabelled": [], "broken": []})
                self.assertFalse(probe["wide"], "the page scrolls sideways")
                self.assertEqual((probe["panel"], probe["nodeChips"]), (0, 0))
                self.assertEqual(probe["composers"], ["spot"])
        self.assertEqual([probe["tall"] for probe in probes if probe["hash"] == "#agents/orbit"], [False] * len(WIDTHS))
        by_hash = {probe["hash"]: probe for probe in probes}
        stream = by_hash["#stream"]
        self.assertEqual([probe["chips"] for probe in probes if probe["hash"] == "#stream"], [["For you", "Radio", "Work", "Transcripts"]] * len(WIDTHS))
        self.assertEqual((stream["menus"], stream["custom"]), (["Filter"], True))
        self.assertEqual(by_hash["#tasks/operator"]["inbox"], 2)
        for tab, own in (("agents", ["Hierarchy"]), ("artifacts", [])):
            with self.subTest(tab=tab):
                self.assertEqual(by_hash[f"#{tab}/orbit"]["views"], ["Orbit", "Chord", "Swimlane", "Tree", "3D", *own])
                self.assertEqual(by_hash[f"#{tab}/3d"]["layouts"], ["Force", "Time", "Spawn depth"])
                self.assertTrue(by_hash[f"#{tab}/3d"]["canvas"], by_hash[f"#{tab}/3d"]["note"])
                self.assertRegex(by_hash[f"#{tab}/3d"]["note"], r"^\d+ nodes · \d+ edges · Force$")
        agents = by_hash["#agents/orbit"]
        self.assertEqual(agents["toolbar"], ["Priority", "Day/Night", "Status"])
        self.assertEqual(agents["spot"], {"hidden": True, "channels": CHOICE_CHANNELS})
        hierarchy = by_hash["#agents/hierarchy"]
        self.assertEqual([office for office, _ in hierarchy["org"]], ["chair", "identity/oidc", "work/s1", "work/s2"])
        self.assertEqual(hierarchy["toggles"], [["Collapse: Operator", "true"], ["Collapse: Chair", "true"], ["Collapse: identity", "true"], ["Collapse: Presidents", "true"]])
        self.assertEqual(hierarchy["toolbar"], agents["toolbar"])
        self.assertGreaterEqual(len(hierarchy["order"]), 2)
        self.assertEqual(by_hash["#agents/tree"]["spawn"][0], ["operator", None])
        self.assertIn(["twig", "true"], by_hash["#agents/tree"]["spawn"])
        self.assertIn(["twig", "false"], by_hash["#agents/tree"]["spawn"])
        artifacts = by_hash["#artifacts/tree"]
        self.assertEqual(artifacts["deletes"], [["Delete all merged", True, "Delete all merged blocked: Secret Service locked"]])
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
        self.assertEqual(listed["views"], ["List", "Board", "RASCI", "Gantt", "Burndown and burnup", "3D"])
        self.assertEqual(by_hash["#tasks/3d"]["layouts"], ["Force", "Time"])
        self.assertTrue(by_hash["#tasks/3d"]["canvas"], by_hash["#tasks/3d"]["note"])
        self.assertRegex(by_hash["#tasks/3d"]["note"], r"^6 nodes · \d+ edges · Force$")
        self.assertEqual(listed["taskFilters"], [["all", "true", "6"], ["open", "false", "4"], ["work", "false", "4"], ["operator", "false", "2"], ["grant", "false", "1"], ["ended", "false", "2"]])
        self.assertEqual(listed["taskRows"], [[task, task not in ("work/old", "operator/push")] for task in order])
        self.assertEqual(listed["flows"], ["file", "file"])
        self.assertEqual(by_hash["#tasks/board"]["columns"], [["queued", ["work/docs", "queue/gate-3"]], ["running", ["work/feature", "work/stage"]], ["done", []]])
        self.assertEqual(by_hash["#tasks/rasci"]["matrix"], [6, 6, "CIRARASRARAR"])
        self.assertEqual([probe["taskFilters"][3][1] for probe in probes if probe["hash"] == "#tasks/operator"], ["true"] * len(WIDTHS))
        extra = data["results"][len(probes) :]
        self.assertEqual([probe["hash"] for probe in extra[:3]], ["#agents/orbit", "#agents/chord", "#artifacts/tree"])
        actions = extra[3]
        self.assertNotIn("error", actions)
        self.assertEqual(actions["keys"], ["#agents/chord", "#artifacts/tree", "#tasks/3d", "#home", "#stream"])
        self.assertEqual(actions["ambience"], ["sky-look", "music-toggle", "leitstand", "notify"])
        self.assertEqual((actions["settingsUnlabelled"], actions["popupUnlabelled"]), (0, 0))
        self.assertEqual((actions["sections"], actions["radioFields"]), (["Ambience", "Location", "Appearance", "Music", "Notifications", "Passkey"], 0))
        for tool in ("Radio …", "Cancel mayday", "Priority …", "Drain", "Suspend", "Resume", "Firewall …", "Settings …", "Look at the sky", "Toggle control room", "Enable notifications"):
            with self.subTest(tool=tool):
                self.assertTrue(any(tool in entry for entry in actions["palette"]), actions["palette"])
        self.assertEqual(actions["popup"], [["post", True], ["call", False]])
        self.assertEqual(actions["centred"], [True, "none"])
        calm, chips = extra[4:]
        self.assertRegex(calm["note"], r"Force · without motion \(prefers-reduced-motion\)$")
        self.assertEqual({key: value for key, value in chips["inbox"].items() if key != "counted"}, {"hash": "#tasks/operator", "items": chips["inbox"]["counted"], "pressed": "true", "current": ["Tasks"]})
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
                    self.write_council({"radio-seen/e2e-callee.json": {"radio": now + 0.5}})
                    (self.state / "agent-sessions.json").write_text(json.dumps({"written": now, "sessions": {"e2e-callee": {"name": to, "running": True}}}), encoding="utf-8")
                    with (self.council / "news.jsonl").open("a", encoding="utf-8") as handle:
                        handle.write(self.jsonl(rows))

        self.beside(answer)
        local = f"http://localhost:{self.port}/"
        data = self.drive([{"width": 1366, "height": 768, "url": f"{local}#stream", "wait": 900, "probe": CALL, "shot": self.shot("1366-call-receipt")}], self.authenticator())
        self.assertEqual(data["errors"], [])
        result = data["results"][0]
        self.assertNotIn("error", result)
        self.assertIsNotNone(result["receipt"], result)
        self.assertTrue(" · read " in result["receipt"] and result["receipt"].endswith(" · acknowledged"), result)
        self.assertEqual(result["read"], 0, result)

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
        self.talks(speaking, graph)
        self.assertEqual(ended, {"ended": True, "caption": False, "faces": 0})
        self.assertEqual((calm["who"], calm["line"], calm["ring"]), ("Stage speaking", "Disk almost full (e2e-cue-2)", "none"), calm)
        self.assertEqual(calm["faces"]["speaking"], [True, "none"], calm)

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_shows_who_speaks_and_moves_only_the_speakers_mouth(self):
        self.speaks(("e2e-cue-1",))
        steps = [
            {"width": 1366, "height": 768, "url": f"{self.base}#stream/radio", "wait": 900, "probe": SPEAK.replace("@CUE@", "e2e-cue-1"), "shot": str(OUT / "firefox-1366-radio-speaking.png"), "gesture": True},
            {"width": 1366, "height": 768, "url": None, "wait": 0, "probe": SPEAK_GRAPH, "shot": str(OUT / "firefox-1366-agents-speaking.png")},
        ]
        data = self.drive(steps, None, "bidi.mjs", os.environ.get("FIREFOX", "firefox"))
        (OUT / "firefox-speaking.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        self.talks(*data["results"])

    def talks(self, speaking: dict, graph: dict) -> None:
        """Args:
            speaking: the SPEAK probe while Stage (s2) is read aloud.
            graph: the SPEAK_GRAPH probe on #agents/orbit right after it.
        """
        self.assertEqual((speaking["who"], speaking["line"], speaking["chip"], speaking["ring"]), ("Stage speaking", "Disk almost full (e2e-cue-1)", "s2", "speaking"), speaking)
        self.assertEqual(speaking["faces"], {"speaking": [True, "talk"], "silent": [False, "none"], "keys": ["s2"]}, speaking)
        self.assertEqual((graph["node"] or "").split(",")[0], "Stage", graph)
        self.assertEqual((graph["ring"], graph["mouth"], graph["silent"]), ("speaking-node", "talk", "none"), graph)

    def test_chromium_records_transcribes_and_sends_a_signed_call_with_voice(self):
        local = f"http://localhost:{self.port}/"
        steps = [
            {"width": 1366, "height": 768, "url": f"{local}#agents/orbit", "wait": 1200, "probe": COMPOSE.replace("@TO@", "Stage"), "shot": self.shot("1366-radio-spot-composer"), "gesture": True},
            {"width": 1366, "height": 768, "url": None, "wait": 0, "probe": COMPOSE_SEND.replace("@ATTACH@", "false"), "shot": None},
            {"width": 1366, "height": 768, "url": None, "wait": 0, "probe": COMPOSE.replace("@TO@", "Stage"), "shot": None, "gesture": True},
            {"width": 1366, "height": 768, "url": None, "wait": 0, "probe": COMPOSE_SEND.replace("@ATTACH@", "true"), "shot": self.shot("1366-radio-spot-composer-sent")},
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

    def test_chromium_clears_the_mayday_from_the_radio_spot_only_after_confirmation_and_passkey_at_three_widths(self):
        local = f"http://localhost:{self.port}/"
        steps = [{"width": width, "height": height, "url": f"{local}?{width}#agents/orbit", "wait": 1200, "probe": CLEAR_MAYDAY, "shot": self.shot(f"{width}-radio-spot-mayday-cleared")} for width, height in WIDTHS]
        data = self.drive(steps, self.authenticator())
        (OUT / "chromium-mayday.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        question = "Lift the radio silence of the active mayday?"
        for result, (width, _) in zip(data["results"], WIDTHS, strict=True):
            with self.subTest(width=width):
                self.assertNotIn("error", result)
                self.assertEqual(result["toolbar"], ["Priority", "Day/Night", "Drain", "Suspend", "Resume", "Status"])
                self.assertEqual((result["title"], result["shown"]), ("Cancel mayday: lift the radio silence so the agents write again; your passkey signs it", ""))
                self.assertEqual(result["declined"], {"question": [question], "posted": [], "toasts": []})
                self.assertEqual(result["accepted"], {"question": [question], "posted": ["/api/board/sign", "/api/board/clear-mayday"]})
                self.assertTrue((result["done"] or "").startswith("Cancel mayday: done"), result)
        self.assertEqual(self.scripts.calls, [(skill_scripts.RADIO, ["clear", "--force", "--session", "Operator"])] * len(WIDTHS))

    def test_chromium_sends_every_class_from_the_radio_spot_and_keeps_its_gear_settings_through_a_reload_at_three_widths(self):
        local = f"http://localhost:{self.port}/"
        values = {1920: ("0.35", "false", "true"), 1366: ("0.45", "true", "false"), 390: ("0.55", "false", "true")}
        steps = [{"width": width, "height": height, "url": f"{local}?{width}-jump#stream/radio", "wait": 1200, "probe": RADIO_JUMP, "shot": self.shot(f"{width}-radio-header-spot-every-tab")} for width, height in WIDTHS]
        for width, height in WIDTHS:
            squelch, tone, post = values[width]
            gear = GEAR_SAVE.replace("@SQUELCH@", squelch).replace("@TONE@", tone).replace("@POST@", post)
            steps += [
                {"width": width, "height": height, "url": f"{local}?{width}#agents/orbit", "wait": 1200, "probe": SPOT_SEND.replace("@TEXT@", f"spot {width}"), "shot": self.shot(f"{width}-radio-spot-sent")},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": gear, "shot": None},
                {"width": width, "height": height, "url": f"{local}?{width}-reloaded#agents/orbit", "wait": 1200, "probe": GEAR_READ, "shot": self.shot(f"{width}-radio-spot-gear")},
            ]
        data = self.drive(steps, self.authenticator())
        (OUT / "chromium-radio-spot.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        labels = dict(zip(CHOICE_CHANNELS, ["Post", "Call", "Newsletter", "Broadcast", "Pan-Pan", "Sécurité", "Mayday"], strict=True))
        mayday = "Send a mayday to all? All agents pause writing steps until you cancel it."
        jumps, walked = data["results"][: len(WIDTHS)], data["results"][len(WIDTHS) :]
        for jump, (width, _) in zip(jumps, WIDTHS, strict=True):
            with self.subTest(width=width, part="radio spot on every tab"):
                self.assertEqual(jump, JUMPED)
        for index, (width, _) in enumerate(WIDTHS):
            sent, saved, read = walked[3 * index : 3 * (index + 1)]
            squelch, tone, post = values[width]
            with self.subTest(width=width):
                for probe in (sent, saved, read):
                    self.assertNotIn("error", probe)
                self.assertEqual((sent["closed"], sent["open"]), ([True, "false"], [False, "true", True]))
                self.assertEqual(sent["inline"], ["static", True, True])
                self.assertEqual((sent["toolbar"], sent["channels"], sent["record"]), (["Priority", "Day/Night", "Status"], CHOICE_CHANNELS, ["Record"]))
                self.assertEqual(sent["heads"], [["Read aloud", "Read aloud: the classes and agents the radio sounds for"], ["Cancel mayday", "Cancel mayday: lift the radio silence so the agents write again; your passkey signs it"]])
                self.assertEqual((sent["tall"], sent["wide"]), (False, False))
                self.assertEqual([run["cls"] for run in sent["runs"]], CHOICE_CHANNELS)
                for run in sent["runs"]:
                    direct = run["cls"] in ("post", "call")
                    self.assertEqual((run["direct"], run["question"], run["left"]), (direct, [mayday] if run["cls"] == "mayday" else [], ""), run)
                    self.assertTrue((run["toast"] or "").startswith(f"{labels[run['cls']]} to {'Stage' if direct else 'all'}: sent"), run)
                self.assertEqual((saved["expanded"], saved["clashes"]), ("true", [{"found": [], "outside": []}] * 2))
                self.assertEqual(saved["tones"], ["MAYDAY / PAN-PAN", "Reviews, asks, decisions", "Post and calls to you", "All radio", "Squelch", "Threshold"])
                self.assertEqual([entry[0] for entry in saved["classes"]], ["Post", "Call", "Newsletter", "Broadcast", "MAYDAY", "PAN-PAN", "Sécurité"])
                self.assertEqual([entry[1:] for entry in saved["classes"] if entry[0] == "MAYDAY"], [["true", True]])
                self.assertEqual((saved["kept"], saved["after"]), ([float(squelch), tone == "true", post == "true"], ["false", False]))
                self.assertEqual(saved["general"], {"sections": ["Ambience", "Location", "Appearance", "Music", "Notifications", "Passkey"], "radio": 0})
                self.assertEqual((saved["tall"], saved["wide"]), (False, False))
                self.assertEqual(read, {"squelch": float(squelch), "tone": tone == "true", "post": post == "true", "tall": False, "wide": False})
        heads = {"post": ["post", "--to", "Stage"], "call": ["send", "call", "--to", "Stage"], "newsletter": ["post"]}
        radio = [args for script, args in self.scripts.calls if script == skill_scripts.RADIO]
        sends = [(width, cls) for width, _ in WIDTHS for cls in CHOICE_CHANNELS]
        self.assertEqual([args[:-1] for args in radio], [[*heads.get(cls, ["send", cls]), "--session", "Operator"] for _, cls in sends])
        for args, (width, cls) in zip(radio, sends, strict=True):
            with self.subTest(width=width, cls=cls):
                self.assertTrue(args[-1].endswith(f"] spot {width} {cls}"), args)
        self.assertEqual(self.httpd.hub.settings.get()["speech"], {"threshold": 50})

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_opens_the_radio_spot_on_every_tab_and_asks_the_passkey_for_every_class_and_cancel_mayday_sending_nothing_unsigned_at_three_widths(self):
        self.pin()
        local = f"http://localhost:{self.port}/"
        steps = []
        for width, height in WIDTHS:
            shot = str(OUT / f"firefox-{width}-radio-spot")
            steps += [
                {"width": width, "height": height, "url": f"{local}?{width}-jump#stream/radio", "wait": 1200, "probe": RADIO_JUMP, "shot": f"{shot}-every-tab.png"},
                {"width": width, "height": height, "url": f"{local}?{width}#agents/orbit", "wait": 1200, "probe": SPOT_SEND.replace("@TEXT@", f"spot {width}"), "shot": f"{shot}-unsigned.png"},
                {"width": width, "height": height, "url": f"{local}?{width}-mayday#agents/orbit", "wait": 1200, "probe": CLEAR_MAYDAY, "shot": f"{shot}-mayday-kept.png"},
            ]
        data = self.drive(steps, None, "bidi.mjs", os.environ.get("FIREFOX", "firefox"), CANCELED)
        (OUT / "firefox-radio-spot.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "(style-src-elem)" not in error and "/favicon.ico" not in error], [])
        labels = dict(zip(CHOICE_CHANNELS, ["Post", "Call", "Newsletter", "Broadcast", "Pan-Pan", "Sécurité", "Mayday"], strict=True))
        mayday = "Send a mayday to all? All agents pause writing steps until you cancel it."
        question = "Lift the radio silence of the active mayday?"
        hint = "Cancel mayday: lift the radio silence so the agents write again; your passkey signs it"
        results = iter(data["results"])
        for width, _ in WIDTHS:
            jump, sent, cleared = next(results), next(results), next(results)
            with self.subTest(browser="firefox", width=width, part="radio spot on every tab"):
                self.assertEqual(jump, JUMPED)
            with self.subTest(browser="firefox", width=width, part="every class unsigned"):
                self.assertNotIn("error", sent, sent)
                self.assertEqual((sent["closed"], sent["open"], sent["inline"]), ([True, "false"], [False, "true", True], ["static", True, True]))
                self.assertEqual((sent["toolbar"], sent["channels"], sent["record"]), (["Priority", "Day/Night", "Status"], CHOICE_CHANNELS, ["Record"]))
                self.assertEqual(sent["heads"], [["Read aloud", "Read aloud: the classes and agents the radio sounds for"], ["Cancel mayday", hint]])
                self.assertEqual((sent["tall"], sent["wide"]), (False, False))
                self.assertEqual([run["cls"] for run in sent["runs"]], CHOICE_CHANNELS)
                for run in sent["runs"]:
                    direct = run["cls"] in ("post", "call")
                    self.assertEqual((run["direct"], run["question"], run["left"]), (direct, [mayday] if run["cls"] == "mayday" else [], f"spot {width} {run['cls']}"), run)
                    self.assertTrue((run["toast"] or "").startswith(f"{labels[run['cls']]} to {'Stage' if direct else 'all'}: not signed"), run)
                    self.assertIn("NotAllowedError", run["toast"], run)
            with self.subTest(browser="firefox", width=width, part="icon-only cancel mayday unsigned"):
                self.assertNotIn("error", cleared, cleared)
                self.assertEqual(cleared["toolbar"], ["Priority", "Day/Night", "Drain", "Suspend", "Resume", "Status"])
                self.assertEqual((cleared["title"], cleared["shown"]), (hint, ""))
                self.assertEqual(cleared["declined"], {"question": [question], "posted": [], "toasts": []})
                self.assertEqual(cleared["accepted"], {"question": [question], "posted": ["/api/board/sign"]})
                self.assertTrue((cleared["done"] or "").startswith("Cancel mayday: not signed"), cleared)
        self.assertEqual(self.scripts.calls, [])
        self.assertTrue((self.council / "radio-silence.json").exists())

    def test_chromium_keeps_the_3d_camera_through_two_state_refreshes_at_three_widths(self):
        steps = [{"width": width, "height": height, "url": f"{self.base}?{width}#agents/3d", "wait": 900, "probe": CAMERA, "shot": self.shot(f"{width}-agents-3d-steady-camera")} for width, height in WIDTHS]
        data = self.drive(steps, None, init=GRAPH_HOOK)
        (OUT / "chromium-camera.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        for result, (width, _) in zip(data["results"], WIDTHS, strict=True):
            with self.subTest(width=width):
                self.assertNotIn("error", result)
                self.assertTrue(result["hooked"], result)
                self.assertGreater(math.dist(result["built"], result["moved"]), 1, result)
                for refresh in result["refreshes"]:
                    self.assertEqual((refresh["rebuilt"], refresh["settled"]), (True, True), result)
                    self.assertLess(math.dist(refresh["camera"], result["moved"]), 0.01, result)
                self.assertGreater(math.dist(result["reset"], result["moved"]), 1, result)

    def check_night_menu(self, browser: str, driver: str, binary: str, signs: bool) -> None:
        """Args:
            signs: cdp.mjs signs every prompt with its virtual passkey; bidi.mjs
                has no virtual authenticator, so the probe answers each prompt
                the way a canceled passkey dialog does.
        """
        authenticator = self.authenticator()
        probe = NIGHT_MENU.replace("@SIGNS@", "true" if signs else "false")
        looks = [{"width": width, "height": height, "url": f"http://localhost:{self.port}/?{width}#agents/orbit", "wait": 1200, "probe": NIGHT_LOOK, "shot": str(OUT / f"{browser}-{width}-night-menu-tooltips.png")} for width, height in WIDTHS]
        step = {"width": 1366, "height": 768, "url": f"http://localhost:{self.port}/#agents/orbit", "wait": 1200, "probe": probe, "shot": str(OUT / f"{browser}-1366-night-menu.png")}
        data = self.drive([*looks, step], authenticator if signs else None, driver, binary)
        (OUT / f"{browser}-night-menu.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "(style-src-elem)" not in error and "/favicon.ico" not in error], [])
        *seen, found = data["results"]
        for look, (width, _) in zip(seen, WIDTHS, strict=True):
            with self.subTest(browser=browser, width=width):
                self.assertNotIn("error", look)
                self.assertEqual(look["children"], [["span", ""], ["div", "night-picks"], ["div", "actions"]])
                self.assertEqual((look["badge"], look["paragraphs"], look["wide"]), (["Day"], 0, False))
                self.assertEqual(look["picks"], [["All", True], ["Skills", True], ["Stage", True]])
                self.assertEqual(look["buttons"], [list(entry) for entry in NIGHT_HINTS])
        self.assertNotIn("error", found)
        self.assertEqual(found["labels"], ["Drain", "Suspend", "Resume"])
        for run, action in zip(found["runs"], ("drain", "suspend", "resume"), strict=True):
            with self.subTest(browser=browser, action=action):
                self.assertEqual(run["asked"], 1, run)
                self.assertEqual(len(run["question"]), 1, run)
                self.assertIn(f"kvb-agent-{action}", run["question"][0])
                signed = [["/api/board/sign", ["action"], action]]
                if signs:
                    self.assertEqual(run["posted"], [*signed, [f"/api/board/{action}", ["proof"], None]])
                    self.assertTrue((run["toast"] or "").startswith(f"{run['label']}: done"), run)
                else:
                    self.assertEqual(run["posted"], signed)
                    self.assertTrue((run["toast"] or "").startswith(f"{run['label']}: not signed"), run)
        nights = [args for script, args in self.scripts.calls if script == skill_scripts.NIGHT]
        self.assertEqual(nights, [[action, "--session", "Operator"] for action in ("drain", "suspend", "resume")] if signs else [])
        if not signs:
            self.assertEqual(self.scripts.calls, [])

    def test_chromium_runs_drain_suspend_and_resume_only_after_the_passkey_signs(self):
        self.check_night_menu("chromium", "cdp.mjs", os.environ.get("CHROMIUM", "chromium"), signs=True)

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_asks_the_passkey_for_drain_suspend_and_resume_and_runs_nothing_unsigned(self):
        self.check_night_menu("firefox", "bidi.mjs", os.environ.get("FIREFOX", "firefox"), signs=False)

    def check_night_picks(self, browser: str, driver: str, binary: str, signs: bool) -> None:
        """Args:
            signs: as in check_night_menu.
        """
        self.write_council({"night.json": {"parts": {"s2": "drain"}}})
        probe = NIGHT_PICK.replace("@SIGNS@", "true" if signs else "false")
        steps = [{"width": width, "height": height, "url": f"http://localhost:{self.port}/?{width}#agents/orbit", "wait": 1200, "probe": probe, "shot": str(OUT / f"{browser}-{width}-night-picks.png")} for width, height in WIDTHS]
        data = self.drive(steps, self.authenticator() if signs else None, driver, binary)
        (OUT / f"{browser}-night-picks.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "(style-src-elem)" not in error and "/favicon.ico" not in error], [])
        everyone, one, nobody = [["All", True], ["Skills", True], ["Stage", True]], [["All", False], ["Skills", False], ["Stage", True]], [["All", False], ["Skills", False], ["Stage", False]]
        for found, (width, _) in zip(data["results"], WIDTHS, strict=True):
            with self.subTest(browser=browser, width=width):
                self.assertNotIn("error", found)
                self.assertEqual((found["badge"], found["start"], found["wide"]), (["Day", "1 alone"], everyone, False))
                self.assertEqual((found["one"], found["kept"], found["none"], found["all"]), ([one, [True] * 3], one, [nobody, [False] * 3], [everyone, [True] * 3]))
                self.assertEqual(found["popup"], {"badge": ["Draining"], "buttons": ["Drain", "Suspend", "Resume"]})
                self.assertEqual([question.split(":")[0] for question in found["questions"]], ["Drain Stage", "Suspend Stage"])
                sent = [["/api/board/sign", ["action", "agents"], "drain", ["s2"]], ["/api/board/drain", ["proof", "agents"], None, ["s2"]], ["/api/board/sign", ["action", "agents"], "suspend", ["s2"]], ["/api/board/suspend", ["proof", "agents"], None, ["s2"]]]
                self.assertEqual(found["posted"], sent if signs else sent[::2])
                self.assertEqual([found["drain"].split("$")[0].split()[1], found["suspend"].split("$")[0].split()[1]], ["done", "done"] if signs else ["not", "not"])
        nights = [args for script, args in self.scripts.calls if script == skill_scripts.NIGHT]
        self.assertEqual(nights, [[action, "--session", "Operator", "--target=s2"] for _ in WIDTHS for action in ("drain", "suspend")] if signs else [])
        calls = [args for script, args in self.scripts.calls if script == skill_scripts.RADIO]
        self.assertEqual(calls, [["send", "call", "--to", "Stage", "--session", "Operator", messaging.ALONE[action]] for _ in WIDTHS for action in ("drain", "suspend")] if signs else [])

    def test_chromium_drains_and_suspends_chosen_agents_from_the_menu_and_the_agent_panel_at_three_widths(self):
        self.check_night_picks("chromium", "cdp.mjs", os.environ.get("CHROMIUM", "chromium"), signs=True)

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_asks_the_passkey_for_chosen_agents_and_runs_nothing_unsigned_at_three_widths(self):
        self.check_night_picks("firefox", "bidi.mjs", os.environ.get("FIREFOX", "firefox"), signs=False)

    def test_chromium_deletes_a_merged_branch_after_dry_run_and_signature(self):
        tree = json.loads(self.tree_file.read_text(encoding="utf-8"))
        tree["delete_ready"], tree["delete_reason"] = True, ""
        next(item for item in tree["repos"][0]["items"] if item["branch"] == "feature/done").update(worktree=None, worktree_state=None, actions=["local-branch", "remote-branch"], compose_projects=[], images=[])
        self.tree_file.write_text(json.dumps(tree), encoding="utf-8")
        demo = f"{self.root}/repos/github.com/me/demo"
        Path(demo).mkdir(parents=True)
        fake = self.outside / "bin" / "pkgmgr"
        fake.parent.mkdir()
        fake.write_text(FAKE_PKGMGR.format(python=sys.executable), encoding="utf-8")
        fake.chmod(0o755)
        (fake.parent / "plan.json").write_text(json.dumps([{"branch": "feature/done", "worktree": None, "local_sha": DONE_TIP, "head": DONE_TIP, "state": "merged-clean", "skip": None, "actions": ["local-branch"]}]), encoding="utf-8")
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
        self.assertIn("stays: remote-branch (local only; the host refuses a plan that deletes it)", opened["dry"][0])
        self.assertEqual((confirmed["result"], confirmed["text"]), ("done", "feature/donedeleted"), confirmed)
        self.assertEqual(confirmed["toasts"], ["Delete: donefeature/done: deleted"])
        self.assertEqual(after["past"], ["done", "deleted"])
        self.assertNotIn("feature/done", after["branches"])
        written = [json.loads(path.read_text(encoding="utf-8")) for path in results.glob("*.json")]
        self.assertEqual([[(item["branch"], item["status"]) for item in result["items"]] for result in written], [[("feature/done", "done")]])
        calls = [json.loads(line)["argv"] for line in (fake.parent / "calls.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(calls, [
            ["branch", "cleanup", "--json", "--branch", "feature/done"],
            ["branch", "cleanup", "--apply", "--json", "--branch", "feature/done"],
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
        self.assertNotIn("error", denied, denied)
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

    def check_inbox_picks(self, browser: str, driver: str, binary: str, signs: bool) -> None:
        """Args:
            signs: as in check_night_menu.
        """
        fill = {"description": "fill", "workdir": "/repo", "status": "queued", "roles": {"Operator": "R", "Skills session": "A"}}
        rows = {f"operator/row-{n:02}": {**fill, "title": f"echo row {n:02}", "check": "manual", "seq": n} for n in range(1, 15)}
        rows["operator/name"] = {**fill, "title": "pick a name", "check": "decision", "seq": 15}
        self.write_council({"rasci.json": rows})
        probe = INBOX_PICK.replace("@SIGNS@", "true" if signs else "false")
        steps = [{"width": width, "height": height, "url": f"http://localhost:{self.port}/?{width}#stream/inbox", "wait": 1200, "probe": probe, "shot": str(OUT / f"{browser}-{width}-inbox-deny-selection.png")} for width, height in WIDTHS]
        stops = []
        with mock.patch.object(batches, "UNDO", 0.3):
            data = self.drive(steps, self.authenticator() if signs else None, driver, binary)
            if signs:
                self.settle(lambda: len([call for call in self.scripts.calls if call[0] == skill_scripts.RASCI]) >= 2 * len(WIDTHS))
            stops = [args for script, args in self.scripts.calls if script == skill_scripts.RASCI]
        (OUT / f"{browser}-inbox-deny-selection.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "(style-src-elem)" not in error and "/favicon.ico" not in error], [])
        denied = []
        for found, (width, _) in zip(data["results"], WIDTHS, strict=True):
            with self.subTest(browser=browser, width=width):
                self.assertNotIn("error", found)
                self.assertGreater(found["before"], 0, found)
                self.assertEqual((found["moved"], found["focused"], found["wide"]), (0, True, False), found)
                self.assertTrue({"Grant selection (1)", "Deny selection (2)"} <= set(found["buttons"]), found["buttons"])
                self.assertEqual((sorted(found["listed"]), found["label"]), (sorted([found["title"], "pick a name"]), "Deny 2"))
                task = f"operator/row-{found['title'][-2:]}"
                items = sorted([[task, "reject", "post"], ["operator/name", "reject", "post"]])
                self.assertEqual([[path, sorted(entries)] for path, entries in found["posted"]], [["/api/sign", items], *([["/api/inbox/approve", items]] if signs else [])])
                self.assertIn("takes effect" if signs else "not signed", found["toast"])
                denied += [task, "operator/name"]
        self.assertEqual(sorted(stops), sorted([["set", task, "--status", "stopped"] for task in denied]) if signs else [])

    def test_chromium_keeps_the_inbox_scroll_on_a_tick_and_denies_a_selection_with_one_signature_at_three_widths(self):
        self.check_inbox_picks("chromium", "cdp.mjs", os.environ.get("CHROMIUM", "chromium"), signs=True)

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_keeps_the_inbox_scroll_on_a_tick_and_denies_nothing_unsigned_at_three_widths(self):
        self.check_inbox_picks("firefox", "bidi.mjs", os.environ.get("FIREFOX", "firefox"), signs=False)

    def choice_steps(self, browser: str, signs: bool, questions: dict[int, str]) -> list[dict]:
        flag = "true" if signs else "false"
        local = f"http://localhost:{self.port}/"
        steps = []
        for index, (width, height) in enumerate(WIDTHS):
            cards = len(WIDTHS) - index if signs else len(WIDTHS)
            steps += [
                {"width": width, "height": height, "url": f"{local}?{width}#stream/inbox", "wait": 1200, "probe": CHOICE_VIEW.replace("@CARDS@", str(cards)), "shot": str(OUT / f"{browser}-{width}-tasks-choices.png")},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": CHOICE_SEND.replace("@SIGNS@", flag), "shot": str(OUT / f"{browser}-{width}-choice-request.png")},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": CHOICE_ANSWER.replace("@SIGNS@", flag).replace("@QUESTION@", questions[width]), "shot": str(OUT / f"{browser}-{width}-choice-answer.png")},
                *({"width": width, "height": height, "url": f"{local}?{width}#tasks/{view}", "wait": 900, "probe": TASKS_FIT, "shot": str(OUT / f"{browser}-{width}-tasks-{view}-fit.png")} for view in TASK_VIEWS),
            ]
        return steps

    def requested(self, sent: dict, signs: bool) -> None:
        """Args:
            sent: the CHOICE_SEND probe: two agents ticked, then every channel
                button pressed once.
        """
        labels = dict(zip(CHOICE_CHANNELS, ["Post", "Call", "Newsletter", "Broadcast", "Pan-Pan", "Sécurité", "Mayday"], strict=True))
        self.assertEqual(len(sent["picked"]), 2, sent)
        self.assertEqual((sent["counted"], sent["fields"], sent["tall"], sent["wide"]), ("2", 0, False, False))
        self.assertEqual(sent["opened"], [True, len(CHOICE_CHANNELS)])
        self.assertEqual([run["channel"] for run in sent["runs"]], CHOICE_CHANNELS)
        for run in sent["runs"]:
            with self.subTest(channel=run["channel"]):
                to = sent["picked"] if run["channel"] in ("post", "call") else ["*"]
                signed = [["/api/choices/sign", ["class", "to"], run["channel"], to]]
                self.assertEqual((run["disabled"], run["asked"], len(run["question"])), (False, 1, int(run["channel"] == "mayday")), run)
                title = f"Choice request ({labels[run['channel']]}) to {', '.join(to) if to != ['*'] else 'all'}"
                self.assertEqual(run["posted"], [*signed, ["/api/choices", ["class", "proof", "to"], run["channel"], to]] if signs else signed)
                self.assertTrue((run["toast"] or "").startswith(f"{title}: {'sent' if signs else 'not signed'}"), run)

    def answered(self, result: dict, signs: bool) -> None:
        self.assertNotIn("error", result)
        self.assertEqual((result["title"], result["asked"], result["closed"], result["tall"], result["wide"]), ("Wait: your passkey signs this answer, a post to Stage", 1, [False, 0], False, False))
        signed = [["/api/sign", ["items"], None, None]]
        self.assertEqual(result["posted"], [*signed, ["/api/inbox/approve", ["items", "proof"], None, None]] if signs else signed)
        self.assertTrue((result["toast"] or "").startswith("Choice: Wait" + ("" if signs else ": not signed")), result)
        self.assertEqual(result["gone"], True if signs else None)

    def check_choices(self, browser: str, driver: str, binary: str, signs: bool) -> None:
        """Args:
            signs: cdp.mjs signs every prompt with its virtual passkey; bidi.mjs
                has no virtual authenticator, so the probes answer each prompt
                the way a canceled passkey dialog does.
        """
        self.inbox_work()
        self.create_ask({**ASK, "command": "make choices", "timeout": 3600})
        authenticator = self.authenticator()
        questions = {width: f"Pick a name at {width} px?" for width, _ in WIDTHS}
        decisions = {width: self.tool("decision_request", {"question": question, "options": OPTIONS, "agent": "Stage", "recommended": ""})["structuredContent"]["id"] for width, question in questions.items()}
        data = self.drive(self.choice_steps(browser, signs, questions), authenticator if signs else None, driver, binary)
        (OUT / f"{browser}-choices.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "(style-src-elem)" not in error and "/favicon.ico" not in error], [])
        per = 3 + len(TASK_VIEWS)
        for index, (width, _) in enumerate(WIDTHS):
            view, sent, answer, *fitted = data["results"][per * index : per * (index + 1)]
            with self.subTest(browser=browser, width=width):
                self.assertNotIn("error", view)
                self.assertEqual(view["kinds"], ["Ask", "Choice", "Operator", "Review", "Rule request"])
                self.assertEqual(view["filter"], ["Waits on Operator", "true"])
                self.assertEqual(view["channels"], [[channel, label, channel in ("post", "call")] for channel, label in zip(CHOICE_CHANNELS, ["Post", "Call", "Newsletter", "Broadcast", "Pan-Pan", "Sécurité", "Mayday"], strict=True)])
                self.assertEqual((view["fields"], view["choices"], view["multi"], view["unlabelled"], view["tall"], view["wide"]), (0, 0, ["Request choices", False, 0, "0", 0], [], False, False))
                self.assertEqual(view["bar"], ["Tasks", view["bar"][1], ["toolbar", "chips", "body"]])
                self.assertEqual(view["bar"][1] == 1, width != 390, view["bar"])
                self.assertGreaterEqual(len(view["agents"]), 2, view)
                self.assertIn(["Choice", ["Merge now", "Wait"]], view["cards"])
                self.requested(sent, signs)
                self.answered(answer, signs)
                for fit, name in zip(fitted, TASK_VIEWS, strict=True):
                    self.assertEqual((fit["hash"], fit["bar"], fit["choices"], fit["tall"], fit["wide"]), (f"#tasks/{name}", CHOICE_CHANNELS, 0, False, False), fit)
                    self.assertEqual((fit["rows"] == 1, fit["layout"]), (width != 390, ["toolbar", "chips", "body"]), fit)
                    if name == "board":
                        self.assertEqual(fit["columns"], ["queued", "running", "done"])
        hub = self.httpd.hub
        if not signs:
            self.assertEqual((self.scripts.calls, hub.messages.listed()), ([], []))
            self.assertEqual([hub.decisions.get(decision)["status"] for decision in decisions.values()], ["pending"] * len(WIDTHS))
            return
        requests = [record for record in hub.messages.listed() if record["text"] == CHOICE_REQUEST]
        self.assertEqual((len(requests), sorted({record["class"] for record in requests})), (len(WIDTHS) * 9, sorted(CHOICE_CHANNELS)))
        for record in requests:
            self.assertTrue(self.tool("operator_message", {"id": record["id"], "text": CHOICE_REQUEST, "to": record["to"]})["structuredContent"]["match"], record["id"])
        radio = [args for script, args in self.scripts.calls if script == skill_scripts.RADIO]
        self.assertEqual(len(radio), len(requests) + len(WIDTHS))
        for width, decision in decisions.items():
            with self.subTest(width=width):
                state = self.tool("decision_wait", {"id": decision, "timeout_seconds": 0})["structuredContent"]
                self.assertEqual((state["status"], state["choice"], state["answer"]), ("decided", "Wait", f"Choice for decision {decision} ({questions[width]}): Wait"))
                found = self.tool("operator_message", {"id": state["message"], "text": state["answer"], "to": "Stage"})["structuredContent"]
                self.assertEqual((found["match"], found["class"], found["to"]), (True, "post", "Stage"))
                self.assertIn(["post", "--to", "Stage", "--session", "Operator", f"[kvb-orchestrator msg {state['message']}] {state['answer']}"], radio)

    def test_chromium_requests_choices_on_every_channel_and_signs_a_choice_at_three_widths(self):
        self.check_choices("chromium", "cdp.mjs", os.environ.get("CHROMIUM", "chromium"), signs=True)

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_asks_the_passkey_for_every_choice_request_and_answer_and_sends_nothing_unsigned(self):
        self.check_choices("firefox", "bidi.mjs", os.environ.get("FIREFOX", "firefox"), signs=False)

    def plan_work(self, now: float) -> None:
        register = json.loads((self.council / "rasci.json").read_text(encoding="utf-8"))
        register["work/feature"]["start"] = iso(now - 1800)
        register["work/stage"]["start"] = iso(now - 900)
        register.update({
            "work/done-a": {"title": "Done A", "status": "done", "worker": "Stage", "branch": "feature/base", "start": iso(now - 36000), "end": iso(now - 28800), "roles": {"Stage": "RA"}, "estimates": {"Stage": {"value": 5, "complexity": 2}}},
            "work/done-b": {"title": "Done B", "status": "done", "worker": "Docs", "start": iso(now - 25200), "end": iso(now - 10800), "roles": {"Docs": "RA"}, "estimates": {"Docs": {"value": 3, "complexity": 2}}},
            "work/done-c": {"title": "Done C", "status": "done", "worker": "Docs", "start": iso(now - 14400), "end": iso(now - 10800), "roles": {"Docs": "RA"}},
            "work/next": {"title": "Next step", "status": "queued", "after": ["work/feature"], "roles": {"Skills": "R", "Maintainer": "A"}, "estimates": {"Skills": {"value": 8, "complexity": 3}}},
            "work/child": {"title": "Child of the base", "status": "queued", "base": "feature/base", "roles": {"Docs": "RA"}},
        })
        queue = json.loads((self.council / "queue.json").read_text(encoding="utf-8"))
        queue["entries"] += [
            {"id": "deploy-4", "seq": 4, "kind": "deploy", "task": "work/stage", "workdir": "/repo", "session": "s2", "name": "Stage", "hotfix": None, "status": "active", "enqueued": now - 400, "granted": now - 300, "cmd": "make deploy"},
            {"id": "test-5", "seq": 5, "kind": "test", "task": "work/docs", "workdir": "/repo", "session": "s2", "name": "Docs", "hotfix": None, "status": "waiting", "enqueued": now - 60, "granted": None, "cmd": "make test"},
        ]
        self.write_council({"rasci.json": register, "queue.json": queue})

    def plan_steps(self, browser: str, signs: bool) -> list[dict]:
        local = f"http://localhost:{self.port}/"
        flag = "true" if signs else "false"
        steps = []
        for width, height in WIDTHS:
            bulk = BULK.replace("@SIGNS@", flag).replace("@VALUE@", PLAN_VALUES[width])
            steps += [
                {"width": width, "height": height, "url": f"{local}?{width}#tasks/gantt", "wait": 1200, "probe": GANTT, "shot": str(OUT / f"{browser}-{width}-tasks-gantt.png")},
                {"width": width, "height": height, "url": f"{local}?{width}#tasks/burn", "wait": 900, "probe": BURN, "shot": str(OUT / f"{browser}-{width}-tasks-burn.png")},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": POINTS_ON, "shot": None},
                {"width": width, "height": height, "url": f"{local}?{width}-reloaded#tasks/burn", "wait": 1200, "probe": REQUEST, "shot": str(OUT / f"{browser}-{width}-tasks-burn-points.png")},
                {"width": width, "height": height, "url": f"{local}?{width}-points#tasks/gantt", "wait": 1200, "probe": GANTT, "shot": str(OUT / f"{browser}-{width}-tasks-gantt-points.png")},
                {"width": width, "height": height, "url": f"{local}?{width}-list#tasks/list", "wait": 1200, "probe": bulk, "shot": str(OUT / f"{browser}-{width}-tasks-business-value.png")},
            ]
        return steps

    def planned(self, probe: dict, points: bool) -> None:
        hour = 3600
        edges = [["after", "work/feature", "work/next"], ["base", "work/done-a", "work/child"], ["queue", "queue/deploy-4", "queue/gate-3"], ["queue", "queue/gate-3", "queue/test-5"]]
        self.assertEqual(probe["forecast"], ["always", [["always", "always"], ["points", "points only"], ["real", "real only"]]])
        self.assertEqual(probe["modes"], [["none", str(not points).lower()], ["points", str(points).lower()]])
        self.assertEqual((probe["request"], probe["inner"]), (points, True))
        self.assertEqual(sorted([kind, start, end] for kind, start, end, _ in probe["edges"]), sorted(edges))
        self.assertEqual({tip for *_, tip in probe["edges"]}, {"url(#gantt-tip)"})
        bars = {task: (forecast, start, end, tag) for task, forecast, start, end, tag in probe["bars"]}
        self.assertNotIn("operator/push", bars)
        self.assertEqual((bars["work/old"][0], bars["work/old"][3]), (False, "circle"))
        self.assertEqual([bars[task][0] for task in ("work/feature", "work/stage", "queue/deploy-4", "work/done-a")], [False] * 4)
        self.assertGreaterEqual(bars["work/feature"][2] - bars["work/feature"][1], 1800)
        forecasts = ("work/next", "work/docs", "work/child", "queue/gate-3", "queue/test-5")
        lengths = {task: round(bars[task][2] - bars[task][1], 3) for task in forecasts}
        self.assertEqual(lengths, {"work/next": (4.5 if points else 2) * hour, "work/docs": (3 if points else 2) * hour, "work/child": 2 * hour, "queue/gate-3": 2 * hour, "queue/test-5": 2 * hour})
        self.assertTrue(all(bars[task][0] for task in forecasts))
        self.assertEqual((bars["work/next"][1], bars["queue/test-5"][1]), (bars["work/feature"][2], bars["queue/gate-3"][2]))
        self.assertTrue(probe["hatched"] and all(probe["hatched"]), probe["hatched"])
        self.assertEqual(probe["real"], 0)
        only = {task: (round(length, 3), tag) for task, length, tag in probe["pointsOnly"]}
        dot = (0, "circle")
        self.assertEqual(only, {"work/next": (4.5 * hour, "rect") if points else dot, "work/docs": (3 * hour, "rect") if points else dot, "work/child": dot, "queue/gate-3": dot, "queue/test-5": dot})

    def check_plan(self, browser: str, driver: str, binary: str, signs: bool) -> None:
        """Args:
            signs: cdp.mjs signs the bulk business value with its virtual
                passkey; bidi.mjs has no virtual authenticator, so the probe
                answers the prompt the way a canceled passkey dialog does.
        """
        self.plan_work(time.time())
        authenticator = self.authenticator()
        data = self.drive(self.plan_steps(browser, signs), authenticator if signs else None, driver, binary)
        (OUT / f"{browser}-plan.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "(style-src-elem)" not in error and "/favicon.ico" not in error], [])
        rows = self.snapshot()["tasks"]
        ranked = list(enumerate(rows))
        status_up = [row["task"] for _, row in sorted(ranked, key=lambda pair: (STATUS_ORDER.index(pair[1]["status"]), pair[0]))]
        status_down = [row["task"] for _, row in sorted(ranked, key=lambda pair: (-STATUS_ORDER.index(pair[1]["status"]), pair[0]))]
        for index, (width, _) in enumerate(WIDTHS):
            gantt, burn, points_on, request, gantt_points, bulk = data["results"][6 * index : 6 * (index + 1)]
            value = PLAN_VALUES[width]
            items = [["work/next", f"estimate work/next Operator --value {value}"], ["work/child", f"estimate work/child Operator --value {value}"]]
            with self.subTest(browser=browser, width=width):
                for probe in (gantt, burn, points_on, request, gantt_points, bulk):
                    self.assertNotIn("error", probe)
                    self.assertEqual((probe["tall"], probe["wide"], probe["layout"]), (False, False, ["toolbar", "chips", "body"]), probe)
                    self.assertEqual(probe["rows"] == 1, width != 390, probe)
                self.planned(gantt, points=False)
                self.planned(gantt_points, points=True)
                self.assertEqual((burn["modes"], burn["request"]), ([["none", "true"], ["points", "false"]], False))
                self.assertEqual(burn["scope"][0], "all")
                self.assertEqual(burn["scope"][1][:2], ["all", "filter"])
                self.assertIn("agent:Docs", burn["scope"][1])
                self.assertIn("line:identity/oidc", burn["scope"][1])
                self.assertEqual(burn["series"], [["scope", 9], ["done", 4], ["remaining", 5]])
                self.assertEqual(burn["agent"], [["scope", 5], ["done", 2], ["remaining", 3]])
                self.assertEqual(points_on["before"], {"modes": [["none", "true"], ["points", "false"]], "request": False})
                self.assertEqual((points_on["modes"], points_on["request"]), ([["none", "false"], ["points", "true"]], True))
                self.assertEqual(request["modes"], [["none", "false"], ["points", "true"]])
                self.assertEqual(request["series"], [["scope", 12], ["done", 4], ["remaining", 8], ["unestimated", 2]])
                self.assertTrue(request["toast"].startswith(f"Request estimates: {'done' if signs else 'not signed'}"), request["toast"])
                self.assertEqual(bulk["sorts"], ["prio", "wsjf", "value", "complexity", "status", "start", "end", "agent", "title"])
                self.assertEqual((bulk["prio"], bulk["status"], bulk["statusDown"]), ([row["task"] for row in rows], status_up, [status_down, "Descending"]))
                self.assertEqual((bulk["picks"], bulk["armed"]), (["work/feature", "work/next", "work/docs", "work/child", "work/stage"], [False, "2"]))
                self.assertTrue(bulk["toast"].startswith(f"Business value {value} for 2 tasks: {'handed to the runner' if signs else 'not signed'}"), bulk["toast"])
                signed = [["/api/sign", ["items"], items]]
                self.assertEqual((bulk["asked"], bulk["posted"]), (1, [*signed, ["/api/tasks", ["items", "proof"], items]] if signs else signed))
                self.assertEqual((bulk["after"], bulk["reset"]), ([True, 0] if signs else [False, 2], True))
        self.assertEqual([args for script, args in self.scripts.calls if script == skill_scripts.ESTIMATE], [["request", "--session", "Operator"]] * (len(WIDTHS) if signs else 0))
        self.assertEqual(self.httpd.hub.settings.get()["estimation"], "none")
        jobs = self.runner_jobs()
        if not signs:
            self.assertEqual(jobs, [])
            register = json.loads((self.council / "rasci.json").read_text(encoding="utf-8"))
            self.assertEqual([task for task, row in register.items() if "Operator" in row.get("estimates", {})], [])
            return
        self.assertEqual([job["argv"][-1] for job in jobs], [PLAN_VALUES[width] for width, _ in WIDTHS for _ in range(2)])
        self.run_runner()
        register = json.loads((self.council / "rasci.json").read_text(encoding="utf-8"))
        self.assertEqual({task: register[task]["estimates"]["Operator"] for task in ("work/next", "work/child")}, {"work/next": {"value": 34, "at": register["work/next"]["estimates"]["Operator"]["at"]}, "work/child": {"value": 34, "at": register["work/child"]["estimates"]["Operator"]["at"]}})
        rows = {row["task"]: row for row in self.snapshot()["tasks"]}
        self.assertEqual((rows["work/next"]["wsjf"], rows["work/child"]["wsjf"], rows["work/child"]["value"]), ({"value": 34, "complexity": 3, "score": 11.33}, None, 34))

    def test_chromium_draws_the_gantt_and_burn_switches_the_estimation_requests_estimates_and_signs_a_bulk_business_value_at_three_widths(self):
        self.check_plan("chromium", "cdp.mjs", os.environ.get("CHROMIUM", "chromium"), signs=True)

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_draws_the_gantt_and_burn_and_asks_the_passkey_for_a_bulk_business_value_storing_nothing_unsigned(self):
        self.check_plan("firefox", "bidi.mjs", os.environ.get("FIREFOX", "firefox"), signs=False)

    def trend_work(self, now: float) -> None:
        day = 86400
        register = {
            "work/t1": {"title": "First", "status": "done", "worker": "Stage", "start": iso(now - 10 * day), "end": iso(now - 8 * day), "roles": {"Stage": "RA"}, "estimates": {"Stage": {"value": 5, "complexity": 1}}},
            "work/t2": {"title": "Second", "status": "done", "worker": "Docs", "start": iso(now - 10 * day), "end": iso(now - 6 * day), "roles": {"Docs": "RA"}, "estimates": {"Docs": {"value": 3, "complexity": 2}}},
            "work/t3": {"title": "Third", "status": "done", "worker": "Docs", "branch": "feature/t3", "start": iso(now - 10 * day), "end": iso(now - 4 * day), "roles": {"Docs": "RA"}, "estimates": {"Docs": {"value": 3, "complexity": 3}}},
            "work/t4": {"title": "Fourth", "status": "running", "worker": "Stage", "start": iso(now - day), "roles": {"Stage": "RA"}, "estimates": {"Stage": {"value": 8, "complexity": 5}}},
            "work/t5": {"title": "Fifth", "status": "queued", "after": ["work/t4"], "roles": {"Skills": "R"}, "estimates": {"Skills": {"value": 8, "complexity": 3}}},
            "work/t6": {"title": "Sixth", "status": "queued", "base": "feature/t3", "roles": {"Docs": "RA"}},
        }
        queue = {"seq": 2, "entries": [
            {"id": "deploy-1", "seq": 1, "kind": "deploy", "task": "work/t4", "workdir": "/repo", "session": "s2", "name": "Stage", "hotfix": None, "status": "active", "enqueued": now - 400, "granted": now - 300, "cmd": "make deploy"},
            {"id": "test-2", "seq": 2, "kind": "test", "task": "work/t5", "workdir": "/repo", "session": "s2", "name": "Docs", "hotfix": None, "status": "waiting", "enqueued": now - 60, "granted": None, "cmd": "make test"},
        ]}
        self.write_council({"rasci.json": register, "queue.json": queue})

    def trend_steps(self, browser: str) -> list[dict]:
        local = f"http://localhost:{self.port}/"
        steps = []
        for width, height in WIDTHS:
            days = str(TREND_DAYS[width])
            steps += [
                {"width": width, "height": height, "url": f"{local}?{width}#tasks/list", "wait": 1200, "probe": ETA_LIST, "shot": str(OUT / f"{browser}-{width}-tasks-eta.png")},
                {"width": width, "height": height, "url": f"{local}?{width}#tasks/burn", "wait": 900, "probe": TREND_SET.replace("@MODE@", "regression").replace("@DAYS@", days), "shot": str(OUT / f"{browser}-{width}-tasks-burn-regression.png")},
                {"width": width, "height": height, "url": f"{local}?{width}-regression#tasks/burn", "wait": 1200, "probe": TREND_RELOADED, "shot": None},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": TREND_SET.replace("@MODE@", "velocity").replace("@DAYS@", days), "shot": str(OUT / f"{browser}-{width}-tasks-burn-velocity.png")},
                {"width": width, "height": height, "url": f"{local}?{width}-velocity#tasks/burn", "wait": 1200, "probe": TREND_RELOADED, "shot": None},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": STEP_TIPS, "shot": str(OUT / f"{browser}-{width}-tasks-burn-steps.png")},
                {"width": width, "height": height, "url": f"{local}?{width}-3d#tasks/3d", "wait": 1200, "probe": TASKS_3D, "shot": str(OUT / f"{browser}-{width}-tasks-3d.png")},
                {"width": width, "height": height, "url": f"{local}?{width}-camera#tasks/3d", "wait": 900, "probe": CAMERA, "shot": str(OUT / f"{browser}-{width}-tasks-3d-steady-camera.png")},
            ]
        return steps

    def eta_checked(self, probe: dict, mode: str, rows: dict, edges: list[dict], window: tuple[float, float]) -> None:
        """Args:
            probe: task -> [start, eta, forecast, text, title] as the list shows it.
            mode: the estimation mode the list was drawn in.
            rows: the snapshot's task rows by task.
            edges: the snapshot's task edges.
            window: the earliest and latest time the page can have taken as now.
        """
        day = 86400
        points = {"none": {}, "points": {"work/t4": 10 * day, "work/t5": 6 * day}}[mode]
        self.assertEqual(sorted(probe), sorted(rows))
        for task, (start, eta, forecast, words, title) in probe.items():
            with self.subTest(mode=mode, task=task):
                row = rows[task]
                self.assertTrue(words.startswith("ETA ") and words != "ETA –", words)
                if row["ended"]:
                    self.assertEqual((eta, forecast, title), (row["end"], False, "ETA: the end of the ended task"))
                    continue
                self.assertTrue(forecast)
                self.assertAlmostEqual(eta - start, points.get(task, 4 * day), delta=0.01)
                ahead = [probe[edge["from"]][1] for edge in edges if edge["to"] == task and edge["from"] in probe and edge["from"] != task]
                if row["start"] is not None:
                    self.assertEqual(start, row["start"])
                elif ahead and max(ahead) > window[1]:
                    self.assertAlmostEqual(start, max(ahead), delta=0.01)
                else:
                    self.assertTrue(window[0] <= start <= window[1], (start, window))

    def trend_forecast(self, points: list[list[float]], mode: str, days: int) -> tuple[float, float | None]:
        """Args:
            points: [t, remaining] of the drawn burndown points.

        Returns:
            The trend's start and the time its remaining line reaches 0
            (None when it never falls), computed here independently of plan.js.
        """
        last_t, last_y = points[-1]
        if mode == "regression":
            mean_t = sum(t for t, _ in points) / len(points)
            mean_y = sum(y for _, y in points) / len(points)
            slope = sum((t - mean_t) * (y - mean_y) for t, y in points) / sum((t - mean_t) ** 2 for t, _ in points)
            return points[0][0], (mean_t - mean_y / slope if slope < 0 else None)
        start = max(points[0][0], last_t - days * 86400)
        before = [y for t, y in points if t <= start][-1]
        slope = (last_y - before) / (last_t - start)
        return start, (last_t - last_y / slope if slope < 0 else None)

    def trended(self, probe: dict, mode: str, days: int) -> None:
        start, forecast = self.trend_forecast(probe["points"], mode, days)
        self.assertEqual(probe["value"], mode)
        self.assertEqual(probe["days"], [days, mode == "velocity"])
        self.assertEqual(sorted(series for series, *_ in probe["lines"]), ["done", "remaining", "scope"])
        for _, begin, end in probe["lines"]:
            self.assertAlmostEqual(begin, start, delta=0.01)
            self.assertAlmostEqual(end, forecast if forecast is not None else probe["points"][-1][0], delta=0.01)
        if forecast is None:
            self.assertEqual((probe["note"], probe["marker"]), ([None, "∞"], None))
            return
        self.assertAlmostEqual(probe["note"][0], forecast, delta=0.01)
        self.assertAlmostEqual(probe["marker"], forecast, delta=0.01)
        self.assertNotEqual(probe["note"][1], "∞", probe["note"])

    def check_trend_eta_3d(self, browser: str, driver: str, binary: str) -> None:
        self.trend_work(time.time())
        begun = time.time()
        data = self.drive(self.trend_steps(browser), None, driver, binary, init=GRAPH_HOOK)
        ended = time.time()
        (OUT / f"{browser}-trend-eta-3d.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "(style-src-elem)" not in error and "/favicon.ico" not in error], [])
        snapshot = self.snapshot()
        rows = {row["task"]: row for row in snapshot["tasks"]}
        edges = snapshot["task_edges"]
        self.assertEqual(sorted([edge["kind"], edge["from"], edge["to"]] for edge in edges), [["after", "work/t4", "work/t5"], ["base", "work/t3", "work/t6"], ["queue", "queue/deploy-1", "queue/test-2"]])
        trends = [["off", "off"], ["regression", "linear regression"], ["velocity", "velocity"]]
        per = 8
        for index, (width, _) in enumerate(WIDTHS):
            eta, regression, reloaded, velocity, again, tips, shown, camera = data["results"][per * index : per * (index + 1)]
            days = TREND_DAYS[width]
            kept = TREND_DAYS[WIDTHS[index - 1][0]] if index else 7
            with self.subTest(browser=browser, width=width):
                for probe in (eta, regression, reloaded, velocity, again, tips, shown):
                    self.assertNotIn("error", probe)
                    self.assertEqual((probe["tall"], probe["wide"], probe["layout"]), (False, False, ["toolbar", "chips", "body"]), probe)
                    self.assertEqual(probe["rows"] == 1, width != 390, probe["rows"])
                for mode in ("none", "points", "back"):
                    self.eta_checked(eta[mode], "points" if mode == "points" else "none", rows, edges, (begun - 1, ended + 1))
                self.assertEqual(eta["modes"], [["none", "true"], ["points", "false"]])
                self.assertEqual((regression["before"]["value"], regression["before"]["options"], regression["before"]["note"], regression["before"]["lines"]), ("off", trends, None, []))
                self.assertEqual(regression["before"]["days"], [kept, False])
                self.assertEqual(regression["toasts"], ["Trend: linear regression"])
                self.trended(regression["after"], "regression", kept)
                self.trended(reloaded, "regression", kept)
                self.assertEqual(velocity["toasts"], [f"Trend: velocity over {kept} days", f"Trend: velocity over {days} days"])
                self.trended(velocity["after"], "velocity", days)
                self.trended(again, "velocity", days)
                self.assertEqual([step["t"] for step in tips["steps"]], [t for t, _ in again["points"]])
                listed = [[sorted(filter(None, step[key].split(" "))) for key in ("started", "ended", "joined")] for step in tips["steps"]]
                self.assertEqual(listed, [[["work/t1", "work/t2", "work/t3"], [], ["work/t5", "work/t6"]], [[], ["work/t1"], []], [[], ["work/t2"], []], [[], ["work/t3"], []], [["work/t4"], [], []], [[], [], []]])
                self.assertEqual([step["series"] for step in tips["steps"]], [["scope", "done", "remaining"]] * len(tips["steps"]))
                self.assertIn("Ended: work/t1", tips["steps"][1]["tip"])
                self.assertIn("No work package started, ended or joined the scope here", tips["steps"][-1]["tip"])
                self.assertEqual((tips["reset"], tips["note"], tips["lines"]), ("Trend: off", False, 0))
                self.tasks_3d(shown, snapshot)
                self.assertTrue(camera["hooked"], camera)
                self.assertGreater(math.dist(camera["built"], camera["moved"]), 1, camera)
                for refresh in camera["refreshes"]:
                    self.assertEqual((refresh["rebuilt"], refresh["settled"]), (True, True), camera)
                    self.assertLess(math.dist(refresh["camera"], camera["moved"]), 0.01, camera)
        self.assertEqual(self.httpd.hub.settings.get()["trend"], {"mode": "off", "days": TREND_DAYS[WIDTHS[-1][0]]})

    def tasks_3d(self, shown: dict, snapshot: dict) -> None:
        tasks = sorted(row["task"] for row in snapshot["tasks"])
        colors = {"after": shown["palette"]["violet"], "base": shown["palette"]["info"], "queue": shown["palette"]["warn"]}
        edges = sorted([edge["from"], edge["to"], edge["kind"], colors[edge["kind"]]] for edge in snapshot["task_edges"])
        self.assertEqual(len(set(colors.values())), 3, colors)
        for layout, word in (("force", "Force"), ("time", "Time")):
            drawn = shown[layout]
            with self.subTest(layout=layout):
                self.assertEqual(drawn["note"], f"{len(tasks)} nodes · {len(edges)} edges · {word}")
                self.assertEqual(drawn["layouts"], [["none", str(layout == "force").lower()], ["time", str(layout == "time").lower()]])
                self.assertEqual(sorted(node for node, *_ in drawn["nodes"]), tasks)
                self.assertEqual(sorted(drawn["links"]), edges)
                self.assertEqual(drawn["label"], "work/t5 · Fifth")
        self.assertEqual([fz for _, fz, _ in shown["force"]["nodes"]], [None] * len(tasks))
        timed = sorted(shown["time"]["nodes"], key=lambda node: node[2])
        self.assertTrue(all(fz is not None for _, fz, _ in timed), timed)
        self.assertEqual([fz for _, fz, _ in timed], sorted(fz for _, fz, _ in timed))
        self.assertLess(timed[0][1], timed[-1][1])
        popup = shown["popup"]
        self.assertEqual((popup["open"], popup["title"], popup["id"], popup["picked"], popup["open_button"], popup["line"]), (True, "Fifth", "work/t5", "work/t5", "Open task", True), popup)
        self.assertTrue(popup["eta"], popup)
        self.assertEqual((popup["closed"], shown["back"]), ([False, None], f"{len(tasks)} nodes · {len(edges)} edges · Force"))

    def test_chromium_draws_the_trend_forecast_point_tips_eta_and_tasks_3d_at_three_widths(self):
        self.check_trend_eta_3d("chromium", "cdp.mjs", os.environ.get("CHROMIUM", "chromium"))

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_draws_the_trend_forecast_point_tips_eta_and_tasks_3d_at_three_widths(self):
        self.check_trend_eta_3d("firefox", "bidi.mjs", os.environ.get("FIREFOX", "firefox"))

    def check_presence(self, browser: str, driver: str, binary: str) -> None:
        """Args:
            browser: the file name prefix of the screenshots and the result.
            driver: the browser driver script next to this file.
            binary: the browser to drive.
        """
        record = {"status": "busy", "statusUpdatedAt": int(time.time() * 1000), "name": "Skills session", "running": True}
        self.httpd.hub.agent_sessions.write_text(json.dumps({"written": time.time(), "sessions": {"s1": record}}), encoding="utf-8")
        steps = []
        for width, height in WIDTHS:
            steps += [
                {"width": width, "height": height, "url": f"{self.base}?{width}#agents/orbit", "wait": 1200, "probe": PRESENCE_WALK, "shot": str(OUT / f"{browser}-{width}-agents-presence.png")},
                {"width": width, "height": height, "url": f"{self.base}?{width}-reloaded#agents/orbit", "wait": 1200, "probe": PRESENCE_READ, "shot": str(OUT / f"{browser}-{width}-agents-presence-3d.png")},
            ]
        data = self.drive(steps, None, driver, binary)
        (OUT / f"{browser}-presence.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "(style-src-elem)" not in error and "/favicon.ico" not in error], [])
        pair = ["dead", "working"]
        order = ["working", "alive", "sleeping", "suspending", "unreachable", "dead", "faces"]
        for index, (width, _) in enumerate(WIDTHS):
            walk, read = data["results"][2 * index : 2 * index + 2]
            with self.subTest(width=width):
                self.assertNotIn("error", walk)
                self.assertNotIn("error", read)
                self.assertEqual(walk["views"], {"orbit": pair, "chord": pair, "swimlane": pair, "tree": pair, "hierarchy": ["dead", "dead", "working", "working"]})
                self.assertEqual((walk["motion"], walk["profile"]), ("presence-spin", ["working", "Working", "Working"]))
                self.assertGreaterEqual(walk["shown"][0], 3, walk["shown"])
                self.assertEqual(walk["shown"][1], 2)
                self.assertEqual(walk["before"], [[look, True] for look in order])
                self.assertEqual((walk["hidden"], walk["orbit"], walk["wide"]), ([0, 1], ["dead"], False))
                self.assertEqual(read["boxes"], [[look, look not in ("working", "faces")] for look in order])
                self.assertEqual((read["orbit"], read["back"], read["restored"]), (["dead"], pair, walk["shown"]))

    def test_chromium_shows_agent_states_and_3d_faces_switchable_through_a_reload_at_three_widths(self):
        self.check_presence("chromium", "cdp.mjs", os.environ.get("CHROMIUM", "chromium"))

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_shows_agent_states_and_3d_faces_switchable_through_a_reload_at_three_widths(self):
        self.check_presence("firefox", "bidi.mjs", os.environ.get("FIREFOX", "firefox"))

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
