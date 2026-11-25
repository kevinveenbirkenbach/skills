from __future__ import annotations

import json
import re
import subprocess
import time
import unittest
from typing import ClassVar

from hub_case import HubCase
from hub_support import (
    CORE_BRANCH,
    CORE_REPO,
    CORE_WORKTREE,
    HUB,
    LONG_BRANCH,
    LONG_REPO,
    LONG_TASK,
    LONG_VOLUME,
    LONG_WORKTREE,
    MERGED_BRANCH,
    NAV,
    long_repos,
    long_task,
)
from kvb_orchestrator.viewstore import SERIES_ID, SHOWN_LIMIT

TEMPLATES = HUB / "templates"
PANELS = TEMPLATES / "panels.js"
HOME = TEMPLATES / "page-home.js"
PIN = {"kind": "panel", "id": "tasks/gantt", "w": 6, "h": 4}
LAYOUT_PROBE = """
const P = require(process.argv[1]);
const pin = (id, extra) => ({kind: "task", id, w: 4, h: 3, ...extra});
const many = (count) => Array.from({length: count}, (_, index) => pin(`work/t${index}`));
const cases = {
  ok: [pin("work/a"), {kind: "panel", id: "tasks/gantt", w: 12, h: 1}],
  full: many(64),
  over: many(65),
  wide: [pin("work/a", {w: 13})],
  flat: [pin("work/a", {h: 0})],
  half: [pin("work/a", {w: 2.5})],
  text: [pin("work/a", {w: "4"})],
  space: [pin("work a")],
  long: [pin("x".repeat(201))],
  kind: [{kind: "k".repeat(33), id: "a", w: 1, h: 1}],
  empty: [{kind: "", id: "a", w: 1, h: 1}],
  extra: [pin("work/a", {x: 1})],
  twice: [pin("work/a"), pin("work/a")],
  object: {pins: []},
};
const valid = Object.fromEntries(Object.entries(cases).map(([name, value]) => [name, P.validLayout(value)]));
const cleaned = P.clean([pin("work/a"), pin("bad id"), pin("work/a"), null, pin("work/b", {extra: 1}), ...many(70)]);
console.log(JSON.stringify({valid, cleaned: [cleaned.length, cleaned[0], cleaned[1].id], notList: P.clean("x")}));
"""
REORDER_PROBE = """
const P = require(process.argv[1]);
const pins = ["a", "b", "c", "d"].map((id) => ({kind: "task", id, w: 4, h: 3}));
const ids = (list) => list.map((pin) => pin.id).join("");
const out = {
  place: [ids(P.place(pins, 0, 2)), ids(P.place(pins, 3, 0)), ids(P.place(pins, 1, 1)), ids(P.place(pins, 5, 0)), ids(P.place(pins, 0, -1))],
  move: [ids(P.move(pins, 0, -1)), ids(P.move(pins, 0, 1)), ids(P.move(pins, 3, 1)), ids(P.move(pins, 2, -1))],
  resize: [P.resize(pins, 1, 0, 13)[1], P.resize(pins, 1, 12, 1)[1], P.resize(pins, 1, 7.4, 2.6)[1]],
  stretch: [P.stretch({w: 4, h: 3}, 200, 0, 100, 80), P.stretch({w: 4, h: 3}, -1000, -1000, 100, 80), P.stretch({w: 4, h: 3}, 5000, 5000, 100, 80), P.stretch({w: 4, h: 3}, 140, 30, 100, 80)],
  untouched: ids(pins),
};
const full = Array.from({length: 64}, (_, index) => ({kind: "task", id: `t${index}`, w: 4, h: 3}));
const added = P.add(pins, "panel", "tasks/gantt");
const removed = P.remove(added.pins, "panel", "tasks/gantt");
out.add = [added.refused, added.pins.at(-1), P.add(added.pins, "panel", "tasks/gantt").pins.length, removed.length, P.remove(removed, "panel", "tasks/gantt").length,
  P.add(full, "task", "t64").refused, P.add(full, "task", "t64").pins.length, P.add(full, "task", "t3").refused, P.add(full, "task", "t3").pins.length];
out.keys = [ids(P.placeKey(pins, "task:a", "task:c")), ids(P.placeKey(pins, "task:x", "task:a")), ids(P.moveKey(pins, "task:b", 1)), ids(P.moveKey(pins, "task:x", 1)),
  P.resizeKey(pins, "task:b", 5, 2)[1], P.resizeBy(pins, "task:b", 1, -1)[1], ids(P.resizeBy(pins, "task:x", 1, 1)), ids(P.resizeKey(pins, "task:x", 1, 1))];
P.panel("agents/3d", "Agents: 3D", () => "a", "3d");
P.panel("tasks/3d", "Tasks: 3D", () => "t", "3d");
const one = P.add(pins, "panel", "agents/3d");
const second = P.add(one.pins, "panel", "tasks/3d");
const swapped = P.add(P.remove(one.pins, "panel", "agents/3d"), "panel", "tasks/3d");
const both = [...one.pins, {kind: "panel", id: "tasks/3d", w: 6, h: 4}];
out.group = [one.refused, second.refused, second.holder, second.pins.length, swapped.refused, swapped.pins.at(-1).id, P.add(one.pins, "panel", "tasks/gantt").refused,
  P.firstOfGroup(both, both[4]), P.firstOfGroup(both, both[5]), P.firstOfGroup(both, both[0])];
P.panel("radio", "Radio", () => "r", "", [12, 7]);
out.sized = [P.add(pins, "panel", "radio").pins.at(-1), P.add(pins, "panel", "tasks/gantt").pins.at(-1), P.add(pins, "task", "work/z").pins.at(-1)];
console.log(JSON.stringify(out));
"""
REGISTRY_PROBE = """
const P = require(process.argv[1]);
P.panel("tasks/gantt", "Tasks: Gantt", (size) => `gantt ${size.w}x${size.h}`);
P.item("task", (id) => `Task ${id}`, (size, id) => (id === "work/live" ? `task ${id} ${size.w}` : null));
P.item("artifact", "Artifact", (size, id) => id);
const odd = "branch:/repo\\u0000feature x";
const token = P.token(odd);
const gantt = P.lookup("panel", "tasks/gantt");
const live = P.lookup("task", "work/live");
const art = P.lookup("artifact", token);
console.log(JSON.stringify({
  gantt: [gantt.title, gantt.render({w: 6, h: 4})],
  live: [live.title, live.render({w: 3, h: 2})],
  gone: P.lookup("task", "work/deleted").render({w: 3, h: 2}),
  unknownPanel: P.lookup("panel", "nope"),
  unknownKind: P.lookup("nope", "x"),
  token: [token, P.ID.test(token), P.raw(token) === odd, art.render({w: 1, h: 1}) === odd, P.token("work/plain"), P.token("a_b"), P.raw(P.token("a_b")), P.token("y".repeat(400)), P.token("1763.5/radio:work/x:9")],
}));
"""
STORE_PROBE = """
const P = require(process.argv[1]);
const calls = [];
const listeners = [];
const pin = (id) => ({kind: "task", id, w: 1, h: 1});
const backend = {
  value: [{kind: "task", id: "work/a", w: 4, h: 3}, {kind: "task", id: "bad id", w: 1, h: 1}],
  get(path) { calls.push(["get", path]); return this.value; },
  update(path, change) { this.value = change(this.value); calls.push(["update", path, this.value.map((one) => one.id)]); return Promise.resolve(true); },
  set(path) { throw new Error(`${path} holds a list: use update()`); },
  on(path, listen) { calls.push(["on", path]); listeners.push(listen); },
};
const store = P.store(backend, "home.pins");
const seen = [];
store.watch((pins) => seen.push(pins.length));
listeners.forEach((listen) => listen([{kind: "task", id: "work/b", w: 2, h: 2}, "junk"]));
(async () => {
  const read = store.read();
  backend.value = [...backend.value, pin("work/other")];
  const wrote = await store.change((pins) => [...pins, pin("work/c")]);
  const refused = await store.change(() => Array.from({length: 65}, (_, index) => pin(`t${index}`))).then(() => "stored", (error) => error.message);
  backend.value = Array.from({length: 64}, (_, index) => pin(`t${index}`));
  backend.get = () => backend.value.slice(0, 63);
  const late = await store.change((pins) => [...pins, pin("work/late")]);
  const memory = P.memory();
  const heard = [];
  memory.on("home.pins", (value) => heard.push(value.length));
  await memory.update("home.pins", () => [1, 2]);
  const unknownPath = () => { throw new Error("unknown view path home.pins"); };
  const strict = P.store({get: unknownPath, update: unknownPath, on: unknownPath, error: () => "another browser kept changing home.pins; try again"}, "home.pins");
  const thrown = await strict.change(() => []).then(() => "stored", (error) => error.message);
  const unknown = [strict.read(), strict.watch(() => null), thrown, strict.error(), P.store(backend, "home.pins").error()];
  console.log(JSON.stringify({read: read.map((one) => one.id), wrote, refused, late: [late, backend.value.length, calls.at(-1)[2].includes("work/late")], calls: calls.slice(0, 4), seen,
    memory: [memory.get("home.pins").length, heard], unknown}));
})();
"""
START_PROBE = """
const N = require(process.argv[1]);
console.log(JSON.stringify({
  first: N.TABS[0], icon: N.ICONS.home,
  routes: [["", 0], ["", 1], ["#", 3], ["#home", 0], ["#home", 2], ["#tasks/gantt", 2], ["#stream", 5], ["#bogus", 1], ["", undefined]].map(([hash, pinned]) => N.route(hash, pinned)),
}));
"""
TAB_KIT = """
const fs = require("fs");
const vm = require("vm");
const [panelsFile, homeFile] = process.argv.slice(1);
const clone = (value) => JSON.parse(JSON.stringify(value));
const settle = () => new Promise((resolve) => setTimeout(resolve, 5));
const keys = (pins) => pins.map((pin) => `${pin.kind}:${pin.id}`);
function hub(value) {
  return {value: clone(value), hostile: false, patches: 0,
    patch(body) {
      this.patches += 1;
      if (this.hostile) {
        this.value = this.value.map((pin, at) => (at ? pin : {...pin, w: (pin.w % 12) + 1}));
      }
      if (JSON.stringify(body.expect) !== JSON.stringify(this.value)) {
        return {status: 409, view: clone(this.value)};
      }
      this.value = clone(body.set);
      return {status: 200, data: clone(this.value)};
    }};
}
function viewStore(server) {
  let saved = clone(server.value);
  let error = "";
  const pending = [];
  const fold = (changes, base) => changes.reduce((value, change) => clone(change(clone(value))), base);
  const store = {
    sent: [],
    get: (path) => clone(fold(pending, saved)),
    set(path) { throw new Error(`${path} holds a list: use update()`); },
    on() {},
    error: () => error,
    update(path, change) {
      store.sent.push(path);
      pending.push(change);
      return new Promise((resolve) => setTimeout(() => resolve(flush()), 0));
    },
  };
  function flush() {
    const changes = pending.splice(0);
    for (let attempt = 1; changes.length; attempt += 1) {
      const answer = server.patch({set: fold(changes, saved), expect: saved});
      saved = answer.status === 200 ? answer.data : answer.view;
      if (answer.status === 200) {
        error = "";
        return true;
      }
      if (attempt === 3) {
        error = "another browser kept changing home.pins; try again";
        return false;
      }
    }
    return true;
  }
  return store;
}
function page(server) {
  const store = viewStore(server);
  const toasts = [];
  const context = vm.createContext({ViewStore: store, labelOf: (key) => key, toast: (title, lines, good) => toasts.push([title, lines.join(" "), good]), tree: {data: null, model: null}, console});
  vm.runInContext(fs.readFileSync(panelsFile, "utf8"), context);
  vm.runInContext(`${fs.readFileSync(homeFile, "utf8")}
globalThis.probe = {homePress, homeUnpin, homeView, Panels};`, context);
  const probe = context.probe;
  probe.homeView.pins = probe.Panels.clean(store.get("home.pins"));
  return {...probe, store, toasts};
}
"""
PAGE_PROBE = TAB_KIT + """
const server = hub([]);
const tab = page(server);
const {homePress, homeUnpin, homeView, Panels} = tab;
const ids = Object.fromEntries(["panel", "task", "message", "artifact", "agent", "ancestry", "metric", "nope"].map((kind) => [kind, Boolean(Panels.lookup(kind, kind === "panel" ? "stream" : "x"))]));
const panels = ["stream", "radio-log", "radio", "radio-device", "radio-speak", "agents/orbit", "agents/chord", "agents/swimlane", "agents/3d", "agents/tree", "agents/hierarchy", "agents/order",
  "artifacts/orbit", "artifacts/chord", "artifacts/swimlane", "artifacts/tree", "artifacts/3d",
  "tasks/list", "tasks/board", "tasks/rasci", "tasks/gantt", "tasks/burn", "tasks/3d", "tasks/operator"].filter((id) => !Panels.lookup("panel", id));
(async () => {
  homePress("panel", "tasks/gantt", "Gantt");
  await settle();
  const one = keys(server.value);
  homePress("panel", "tasks/gantt", "Gantt");
  await settle();
  const none = server.value.length;
  homePress("panel", "agents/3d", "Agents: 3D");
  homePress("panel", "tasks/3d", "Tasks: 3D");
  await settle();
  const solid = keys(server.value);
  homeUnpin("panel:agents/3d");
  await settle();
  Array.from({length: 64}, (_, index) => homePress("task", `work/t${index}`, `t${index}`));
  await settle();
  const sent = tab.store.sent.length;
  homePress("task", "work/t64", "Task work/t64");
  await settle();
  const full = [server.value.length, tab.store.sent.length - sent];
  homeUnpin("task:work/t0");
  await settle();
  const after = server.value.length;
  server.hostile = true;
  const patches = server.patches;
  homeUnpin("task:work/t1");
  const optimistic = homeView.pins.length;
  await settle();
  console.log(JSON.stringify({ids, panels, one, none, solid, full, after, optimistic, reverted: homeView.pins.length, tries: server.patches - patches,
    fellBack: JSON.stringify(homeView.pins) === JSON.stringify(Panels.clean(server.value)), paths: [...new Set(tab.store.sent)], toasts: tab.toasts}));
})();
"""
RACE_PROBE = TAB_KIT + """
(async () => {
  const server = hub([]);
  const one = page(server);
  const other = page(server);
  one.homePress("panel", "tasks/gantt", "Gantt");
  other.homePress("task", "work/b", "Task work/b");
  await settle();
  const pinned = [keys(server.value), server.patches, keys(other.store.get("home.pins"))];
  const seed = Array.from({length: 63}, (_, index) => ({kind: "task", id: `work/s${index}`, w: 2, h: 1}));
  const crowded = hub(seed);
  const first = page(crowded);
  const late = page(crowded);
  first.homePress("task", "work/c", "Task work/c");
  late.homePress("task", "work/d", "Task work/d");
  await settle();
  const ids = keys(crowded.value);
  const stale = hub([{kind: "task", id: "work/a", w: 4, h: 3}, {kind: "task", id: "work/b", w: 4, h: 3}]);
  const mover = page(stale);
  const pinner = page(stale);
  pinner.homePress("task", "work/c", "Task work/c");
  mover.homeUnpin("task:work/a");
  await settle();
  console.log(JSON.stringify({pinned, full: [ids.length, ids.includes("task:work/c"), ids.includes("task:work/d"), late.toasts, first.toasts],
    unpinned: keys(stale.value), toasts: [...one.toasts, ...other.toasts, ...mover.toasts, ...pinner.toasts]}));
})();
"""


DOM_KIT = """
const fs = require("fs");
const vm = require("vm");
const XHTML = "http://www.w3.org/1999/xhtml";
const parts = (selector) => selector.split(",").map((part) => {
  const found = /^\\s*([a-z]*)((?:\\[[^\\]]+\\])*)\\s*$/.exec(part);
  return {tag: found[1], attrs: [...found[2].matchAll(/\\[([\\w-]+)(?:="([^"]*)")?\\]/g)].map(([, name, value]) => [name, value])};
});
const matches = (node, selector) => parts(selector).some(({tag, attrs}) => (!tag || node.tagName === tag.toUpperCase()) && attrs.every(([name, value]) => node.attrs.has(name) && (value === undefined || node.attrs.get(name) === value)));
class El {
  constructor(tag, ns) { this.tagName = tag.toUpperCase(); this.namespaceURI = ns || XHTML; this.attrs = new Map(); this.children = []; this.parentNode = null; this.listeners = {}; }
  setAttribute(name, value) { this.attrs.set(name, String(value)); }
  getAttribute(name) { return this.attrs.has(name) ? this.attrs.get(name) : null; }
  hasAttribute(name) { return this.attrs.has(name); }
  removeAttribute(name) { this.attrs.delete(name); }
  get classList() { const list = (this.getAttribute("class") || "").split(/\\s+/); return {contains: (name) => list.includes(name)}; }
  get isConnected() { let at = this; while (at.parentNode) { at = at.parentNode; } return at === document.body; }
  focus() { document.activeElement = this; }
  detach() {
    if (this.parentNode) {
      if (this.contains(document.activeElement)) { document.activeElement = document.body; }
      this.parentNode.children = this.parentNode.children.filter((child) => child !== this); this.parentNode = null;
    }
  }
  append(...nodes) { nodes.forEach((child) => { child.detach(); child.parentNode = this; this.children.push(child); }); }
  prepend(...nodes) { nodes.reverse().forEach((child) => { child.detach(); child.parentNode = this; this.children.unshift(child); }); }
  replaceChildren(...nodes) { [...this.children].forEach((child) => child.detach()); this.append(...nodes); }
  contains(node) { for (let at = node; at; at = at.parentNode) { if (at === this) { return true; } } return false; }
  all() { return this.children.flatMap((child) => [child, ...child.all()]); }
  querySelectorAll(selector) { return this.all().filter((child) => matches(child, selector)); }
  closest(selector) { for (let at = this; at; at = at.parentNode) { if (matches(at, selector)) { return at; } } return null; }
  addEventListener(name, listen) { (this.listeners[name] = this.listeners[name] || []).push(listen); }
}
const el = (tag, attrs, ...children) => {
  const made = new El(tag);
  Object.entries(attrs).forEach(([name, value]) => made.setAttribute(name, value));
  made.append(...children);
  return made;
};
const document = {createElement: (tag) => new El(tag), createElementNS: (ns, tag) => new El(tag, ns), body: null, activeElement: null};
document.body = new El("body");
document.activeElement = document.body;
const text = (value) => {
  const made = new El("#text");
  made.textContent = String(value);
  return made;
};
const h = (tag, attrs, ...children) => {
  const made = new El(tag);
  Object.entries(attrs || {}).filter(([name, value]) => name !== "on" && value !== null && value !== undefined && value !== false).forEach(([name, value]) => made.setAttribute(name, value));
  made.append(...children.flat(Infinity).filter((child) => child !== null && child !== undefined && child !== false && child !== "").map((child) => (child instanceof El ? child : text(child))));
  return made;
};
const textOf = (node) => (node.tagName === "#TEXT" ? node.textContent : node.children.map(textOf).join(""));
const context = vm.createContext({document, MutationObserver: class { observe() {} }, console});
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), context);
const P = vm.runInContext("Panels", context);
"""
STAR_PROBE = DOM_KIT + """
P.panel("tasks/list", "Tasks: list", () => null);
P.panel("radio-log", "Radio log", () => null);
P.item("task", (id) => `Task ${id}`, () => null);
const slot = el("div", {class: "head-row", "data-star-slot": ""}, el("code", {}), el("button", {class: "priority"}));
const task = el("li", {"data-item": "task:work/a"}, slot, el("span", {}));
const bare = el("li", {"data-item": "task:work/b"}, el("span", {}));
const list = el("div", {"data-panel": "tasks/list"}, el("ol", {}, task, bare));
const svg = new El("g", "http://www.w3.org/2000/svg");
svg.setAttribute("data-item", "task:work/c");
const radio = el("section", {"aria-label": "Radio log"}, el("ul", {"aria-label": "Radio log"}));
const root = el("main", {}, list, el("div", {}, svg), radio, el("div", {"data-panel": "nope"}));
const clicked = [];
const stars = () => root.querySelectorAll("[class]").filter((node) => node.classList.contains("star"));
const own = (host) => stars().filter((node) => node.closest("[data-panel], [data-item]") === host);
const mark = P.decorate(root, {pinned: (kind, id) => kind === "task" && id === "work/a", press: (...args) => clicked.push(args), marks: [['section[aria-label="Radio log"]', "radio-log"]]});
const before = stars().length;
mark();
const [panelStar] = own(list);
const [taskStar] = own(task);
const out = {
  panel: {first: list.children[0].getAttribute("class"), stars: own(list).length, pressed: panelStar.getAttribute("aria-pressed"), title: panelStar.getAttribute("title")},
  task: {inSlot: taskStar.parentNode === slot, slotLast: slot.children.at(-1) === taskStar, rows: task.children.filter((child) => child.classList.contains("star-row")).length,
    pressed: taskStar.getAttribute("aria-pressed"), label: taskStar.getAttribute("aria-label")},
  bare: {first: bare.children[0].getAttribute("class"), stars: own(bare).length},
  svg: svg.children.length,
  radio: [radio.getAttribute("data-panel"), radio.children[0].getAttribute("class")],
  again: [before, stars().length],
};
taskStar.listeners.click[0]({preventDefault: () => null, stopPropagation: () => null});
const fresh = el("div", {"data-star-slot": ""});
task.replaceChildren(fresh, el("span", {}));
mark();
out.redrawn = [own(task)[0].parentNode === fresh, stars().length];
out.clicked = clicked;
console.log(JSON.stringify(out));
"""
MESSAGE_PROBE = """
const fs = require("fs");
const vm = require("vm");
const [panelsFile, homeFile] = process.argv.slice(1);
const urls = [];
const answers = {1762999999: {events: [{id: "radio:abc", ts: 1763000000.5}], entries: []}, 1762999899: {events: [], entries: [{id: "transcript:9", ts: 1762999900}]}};
const fetch = async (url) => {
  urls.push(url);
  return {ok: true, json: async () => answers[new URL(url, "http://hub.invalid").searchParams.get("from")]};
};
const stream = {events: [], entries: [{id: "transcript:7", ts: 5}], key: "view=fuer-dich", busy: false};
const context = vm.createContext({fetch, stream, filter: {view: "fuer-dich", waiting: true}, ui: {}, labelOf: (key) => key, toast: () => null, emptyState: () => "wait",
  eventRow: (entry) => `row ${entry.id}`, h: (tag, attrs, child) => child, URL, console});
vm.runInContext(fs.readFileSync(panelsFile, "utf8"), context);
vm.runInContext(fs.readFileSync(homeFile, "utf8"), context);
const P = vm.runInContext("Panels", context);
const tile = (raw) => P.lookup("message", P.token(raw)).render({w: 4, h: 3});
const settle = () => new Promise((resolve) => setTimeout(resolve, 0));
(async () => {
  const first = tile("1763000000.5/radio:abc");
  await settle();
  await settle();
  const found = tile("1763000000.5/radio:abc");
  tile("1762999900/radio:gone");
  await settle();
  await settle();
  const gone = tile("1762999900/radio:gone");
  const cached = tile("5/transcript:7");
  const broken = tile("nonsense");
  console.log(JSON.stringify({first, found, gone, cached, broken, urls, fetches: urls.length}));
})();
"""


VIEW_PROBE = """
const P = require(process.argv[1]);
const view = {chart: "hardware", tokens: "interval", shown: ["host:CPU"]};
const pin = {kind: "metric", id: "hardware/x", w: 4, h: 3, view};
P.item("metric", (id, seen) => `Metric ${id} ${seen ? seen.shown.join() : "none"}`, (size, id, seen) => (seen ? `${id} ${size.w} ${seen.chart}` : null));
const added = P.add([], "metric", "hardware/x", view);
const looked = P.lookup("metric", "hardware/x", view);
const bare = P.lookup("metric", "hardware/x");
console.log(JSON.stringify({
  valid: [P.validLayout([pin]), P.validLayout([{...pin, view: []}]), P.validLayout([{...pin, view: "x"}]), P.validLayout([{...pin, view: null}]), P.validLayout([{...pin, extra: 1}])],
  cleaned: P.clean([pin, {...pin, id: "hardware/y", view: [1]}]),
  added: [added.pins, P.add([], "task", "work/a").pins, P.add([], "task", "work/a", "x").pins],
  resized: P.resizeKey(added.pins, "metric:hardware/x", 6, 5),
  lookup: [looked.title, looked.render({w: 4, h: 3}), bare.title, bare.render({w: 1, h: 1})],
  digest: [P.digest("host:CPU") === P.digest("host:CPU"), P.digest("host:CPU") === P.digest("host:RAM"), /^[0-9a-f]{16}$/.test(P.digest("")), P.ID.test(`hardware/${P.digest("x")}`)],
}));
"""
CAPTURE_PROBE = DOM_KIT + """
P.item("metric", (id, view) => `Metric ${view.shown === null ? "all" : view.shown.join()}`, () => null);
let selection = null;
P.capture("resources-hardware", () => ({kind: "metric", id: selection === null ? "hardware/all" : "hardware/cpu", view: {chart: "hardware", tokens: "interval", shown: selection}}));
const head = el("div", {class: "res-head", "data-star-slot": ""}, el("span", {class: "res-title"}));
const chart = el("section", {"data-panel": "resources-hardware"}, head, el("div", {class: "res-plot"}));
const loose = el("section", {"data-panel": "resources-unknown"});
const root = el("main", {}, chart, loose);
const clicked = [];
const mark = P.decorate(root, {pinned: (kind, id) => `${kind}:${id}` === "metric:hardware/cpu", press: (...args) => clicked.push(args)});
const star = () => head.children.find((child) => child.classList.contains("star"));
const before = [star().getAttribute("aria-pressed"), star().getAttribute("title"), loose.children.length, chart.children[0] === head];
selection = ["host:CPU"];
mark();
const after = [star().getAttribute("aria-pressed"), star().getAttribute("title"), head.children.filter((child) => child.classList.contains("star")).length];
star().listeners.click[0]({preventDefault: () => null, stopPropagation: () => null});
console.log(JSON.stringify({before, after, clicked, target: P.targetOf(chart)}));
"""
METRIC_PROBE = """
const fs = require("fs");
const vm = require("vm");
const [panelsFile, resourcesFile, homeFile] = process.argv.slice(1);
const Resources = require(require("path").join(require("path").dirname(resourcesFile), "resources.js"));
const context = vm.createContext({ViewStore: {get: () => ({tokens: "accumulated"}), update: () => Promise.resolve(true), on: () => null}, labelOf: (key) => key, toast: () => null, Resources, console});
vm.runInContext(fs.readFileSync(panelsFile, "utf8"), context);
vm.runInContext(`${fs.readFileSync(resourcesFile, "utf8")}\\n${fs.readFileSync(homeFile, "utf8")}\\nglobalThis.probe = {resourcePin, resourceView, Panels};`, context);
const {resourcePin, resourceView, Panels} = context.probe;
const empty = resourcePin("tokens");
resourceView.series.hardware = {ids: ["host:RAM", "host:CPU", "disk:/"], shown: ["host:CPU"], tokens: "accumulated"};
resourceView.series.tokens = {ids: ["agent:Skills", "agent:Stage"], shown: ["agent:Stage", "agent:Skills"], tokens: "accumulated"};
resourceView.series.combined = {ids: ["host:CPU", "agent:Skills", "burn:done"], shown: ["host:CPU", "burn:done"], tokens: "interval"};
const pins = ["hardware", "tokens", "combined"].map(resourcePin);
resourceView.series.hardware = {ids: ["host:RAM", "host:CPU", "disk:/"], shown: ["host:RAM", "host:CPU", "disk:/"], tokens: "interval"};
const all = resourcePin("hardware");
const titles = [...pins, all, empty].map((pin) => Panels.lookup(pin.kind, pin.id, pin.view).title);
const four = Panels.lookup("metric", "x", {chart: "tokens", tokens: "interval", shown: ["agent:a", "agent:b", "agent:c", "agent:d"]}).title;
const broken = [Panels.lookup("metric", "x").title, Panels.lookup("metric", "x", {chart: "disks", shown: null}).render({w: 1, h: 1})];
const limit = Number(process.argv[4]);
const agents = (count) => Array.from({length: count}, (_, index) => `agent:a${String(index).padStart(3, "0")}`);
const selected = (count, off) => {
  resourceView.series.tokens = {ids: agents(count), shown: agents(count).slice(off), tokens: "interval"};
  const pin = resourcePin("tokens");
  return [pin.view.shown === null ? null : pin.view.shown.length, pin.refused || null, pin.id.split("/").length];
};
const limits = [selected(limit + 1, 1), selected(limit + 2, 1), selected(limit + 2, 0), selected(limit + 2, limit + 2)];
console.log(JSON.stringify({empty, pins, all, titles, four, broken, limits, digests: [Panels.digest("host:CPU"), Panels.digest("burn:done\\nhost:CPU")]}));
"""
PRESS_PROBE = TAB_KIT + """
const server = hub([]);
const tab = page(server);
const view = {chart: "hardware", tokens: "interval", shown: ["host:CPU"]};
(async () => {
  tab.homePress("metric", "hardware/abc", "Hardware: CPU", view);
  await settle();
  const stored = clone(server.value);
  tab.homePress("metric", "hardware/abc", "Hardware: CPU", view);
  await settle();
  console.log(JSON.stringify({stored, after: server.value, pins: tab.homeView.pins}));
})();
"""
REFUSED_PROBE = DOM_KIT + """
P.item("metric", (id) => `Metric ${id}`, () => null);
P.item("artifact", (id) => `Artifact ${id}`, () => null);
let over = true;
P.capture("resources-tokens", () => (over ? {kind: "metric", id: "tokens/interval/x", view: {chart: "tokens"}, refused: "too many series"} : {kind: "metric", id: "tokens/interval/y", view: {chart: "tokens"}}));
const chart = el("section", {"data-panel": "resources-tokens"}, el("div", {"data-star-slot": ""}));
const long = el("li", {"data-item": `artifact:wt:/${"p".repeat(300)}`});
const root = el("main", {}, chart, long);
const clicked = [];
const mark = P.decorate(root, {pinned: () => false, press: (...args) => clicked.push(args)});
const star = (host) => host.all().find((node) => node.classList.contains("star"));
const read = (host) => [star(host).hasAttribute("disabled"), star(host).getAttribute("title"), star(host).getAttribute("aria-pressed")];
const fire = (host) => (star(host).listeners.click || []).forEach((listen) => listen({preventDefault: () => null, stopPropagation: () => null}));
const refused = read(chart);
const first = star(chart);
fire(chart);
over = false;
mark();
const freed = [...read(chart), star(chart) === first];
fire(chart);
over = true;
mark();
const again = read(chart);
fire(chart);
fire(long);
console.log(JSON.stringify({refused, freed, again, long: read(long), clicked}));
"""
ORDER_PROBE = DOM_KIT + """
Object.assign(context, {h, state: {agent_order: ["Skills", "Stage"]}, ui: {order: null}, counter: (value) => text(value), face: () => text("face"), person: (name) => text(name),
  icon: () => text("icon"), officeBtn: (name, label) => h("button", {"aria-label": label}), focusKey: () => null, refocus: () => null, act: async () => true, go: () => null});
vm.runInContext(`${fs.readFileSync(process.argv[2], "utf8")}\\nglobalThis.probe = {orderDom, drawAgentOrder};`, context);
const {orderDom, drawAgentOrder} = context.probe;
P.panel("agents/order", "Agents: priority", () => null);
orderDom.box = el("section", {"data-panel": "agents/order"});
orderDom.slot = el("span", {"data-star-slot": ""});
document.body.append(orderDom.box);
const mark = P.decorate(document.body, {pinned: () => false, press: () => null});
const stars = () => orderDom.box.all().filter((node) => node.classList.contains("star"));
drawAgentOrder();
mark();
const first = stars()[0];
first.focus();
drawAgentOrder();
mark();
context.state.agent_order = ["Stage", "Skills", "Docs"];
drawAgentOrder();
mark();
console.log(JSON.stringify({count: stars().length, same: stars()[0] === first, focused: document.activeElement === first, head: first.parentNode.parentNode === orderDom.box.children[0],
  ranks: orderDom.box.all().filter((node) => node.tagName === "LI").map((node) => node.getAttribute("data-name"))}));
"""
TREE_PROBE = DOM_KIT + """
const [, artifactsFile, treeFile, homeFile, dataFile] = process.argv.slice(1);
Object.assign(context, {
  h, icon: () => text(""), named: (label, hint) => ({title: hint || label, "aria-label": label}), iconBtn: (name, label, cls, run, hint) => h("button", {"aria-label": label, title: hint}),
  counter: (value) => text(value), emptyState: (title, words) => h("div", {class: "empty", "data-title": title}, words), branchAncestry: () => null, gateChips: () => h("span", {class: "gates"}), gateExplain: () => null,
  flowLine: () => null, flowDetails: () => null, flowEdges: () => [], copyButton: () => null, face: () => null, person: (name) => text(name), status: (value) => text(value), pill: (words) => text(words),
  workChips: () => null, popupHead: (glyph, label) => h("h2", {class: "panel-title"}, label), meta: (rows) => h("dl", {}, rows.map(([key, value]) => h("div", {"data-key": key}, value === null || value === undefined ? "" : value))),
  WORK_CHIPS: {}, clock: {format: () => "c"}, stampOf: (t) => t, nowSeconds: () => 1763000000, labelOf: (key) => key, toast: () => null,
  tree: {data: JSON.parse(fs.readFileSync(dataFile, "utf8")), model: null, busy: false, q: "", open: new Set(), dom: null},
});
vm.runInContext(`${[artifactsFile, treeFile, homeFile].map((file) => fs.readFileSync(file, "utf8")).join("\\n")}
tree.model = artifactModel(tree.data);
homeView.fetched.tree = Date.now();
globalThis.probe = {treeCards};`, context);
const {treeCards} = context.probe;
const tree = context.tree;
const flat = (nodes) => nodes.filter((node) => node instanceof El).flatMap((node) => [node, ...node.all()]);
const deletes = (nodes) => flat(nodes).filter((node) => node.getAttribute("aria-label") === "Delete").length;
const rows = flat(treeCards("", false).nodes).filter((node) => node.hasAttribute("data-item"));
const pinned = rows.map((row) => {
  const target = P.targetOf(row);
  const entry = target.id ? P.lookup(target.kind, target.id) : null;
  const shown = entry ? entry.render({w: 4, h: 3}) : null;
  const head = shown ? shown.all().find((node) => node.classList.contains("panel-title")) : null;
  const path = shown ? shown.all().find((node) => node.getAttribute("data-key") === "Path" || node.getAttribute("data-key") === "Ref") : null;
  return {id: target.id, refused: target.refused || null, title: entry ? entry.title : null, label: head ? textOf(head) : null, path: path ? textOf(path) : null, deletes: shown ? deletes([shown]) : null};
});
const home = P.lookup("panel", "artifacts/tree").render({w: 6, h: 4});
const glance = [deletes(treeCards("", false).nodes), deletes(treeCards("", true).nodes), deletes([home])];
const digested = pinned.map((entry) => entry.id).filter((id) => /_23_/.test(id || ""));
const kept = tree.data;
tree.data = {...kept, repos: [], tasks: [], cleanups: []};
const empty = [treeCards("", true).nodes[0].getAttribute("data-title"), treeCards("zz", false).nodes[0].getAttribute("data-title"), textOf(P.lookup("panel", "artifacts/tree").render({w: 6, h: 4}).children[0])];
tree.data = kept;
tree.model = context.artifactModel({...kept, repos: [], tasks: []});
const gone = digested.map((id) => [P.lookup("artifact", id).render({w: 4, h: 3}), P.lookup("artifact", id).title]);
console.log(JSON.stringify({pinned, glance, empty, gone}));
"""


LINK_PROBE = """
const fs = require("fs");
const vm = require("vm");
const [navFile, panelsFile, homeFile] = process.argv.slice(1);
const context = vm.createContext({labelOf: (key) => key, toast: () => null, tree: {data: null, model: null}, URLSearchParams, console});
[navFile, panelsFile].forEach((file) => vm.runInContext(fs.readFileSync(file, "utf8"), context));
vm.runInContext(`${fs.readFileSync(homeFile, "utf8")}
globalThis.probe = {homeLink, Panels, Nav};`, context);
const {homeLink, Panels, Nav} = context.probe;
const panels = JSON.parse(process.argv[4]);
const items = [["task", "work/a"], ["message", "1763000000.5/radio:abc"], ["artifact", "branch:/repo\\u0000feature x"], ["agent", "s1"], ["ancestry", "/repo"], ["metric", "hardware/0123456789abcdef"]];
const link = (pin) => {
  const href = homeLink(pin);
  return {href, route: href === null ? null : Nav.route(href, 1)};
};
console.log(JSON.stringify({
  panels: Object.fromEntries(panels.map((id) => [id, Panels.lookup("panel", id) ? link({kind: "panel", id, w: 6, h: 4}) : null])),
  items: Object.fromEntries(items.map(([kind, raw]) => [kind, Panels.lookup(kind, Panels.token(raw)) ? link({kind, id: Panels.token(raw), w: 4, h: 3}) : null])),
  unknown: homeLink({kind: "nope", id: "x", w: 1, h: 1}),
}));
"""
OPEN_PROBE = """
const fs = require("fs");
const vm = require("vm");
const [panelsFile, homeFile] = process.argv.slice(1);
const calls = [];
const context = vm.createContext({
  labelOf: (key) => key, toast: () => null, ui: {screen: "artifacts"}, art: {repo: ""}, tree: {data: null, model: null, dom: null}, window: {setTimeout}, console,
  artSelect: (id) => calls.push(["artSelect", id]), drawArtifacts: () => calls.push(["drawArtifacts"]), taskSheet: (id) => calls.push(["taskSheet", id]),
  openAgent: (key, anchor) => calls.push(["openAgent", key, typeof anchor]), pickOf: (id) => () => id,
});
vm.runInContext(fs.readFileSync(panelsFile, "utf8"), context);
vm.runInContext(`${fs.readFileSync(homeFile, "utf8")}
globalThis.probe = {homeOpen, HOME_RETRY};`, context);
const {homeOpen, HOME_RETRY} = context.probe;
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
(async () => {
  ["nokind", ":x", "task:", "task:bad id", "nope:x", "artifact"].forEach((open) => homeOpen(open, "artifacts", 3));
  const refused = calls.splice(0);
  homeOpen("task:work/a", "tasks", 3);
  const elsewhere = calls.splice(0);
  context.ui.screen = "tasks";
  homeOpen("task:work/a", "tasks", 3);
  homeOpen("agent:name_3a_Stage", "tasks", 3);
  const direct = calls.splice(0);
  context.ui.screen = "artifacts";
  homeOpen("artifact:wt_3a_/r/w", "artifacts", 3);
  await wait(HOME_RETRY / 2);
  const waiting = calls.splice(0);
  context.tree.model = {byRef: new Map([["wt:/r/w", {id: "wt:/r/w", repo: "/r"}]])};
  await wait(HOME_RETRY * 2);
  const opened = [calls.splice(0), context.art.repo];
  context.tree.model = null;
  homeOpen("artifact:wt_3a_/r/w", "artifacts", 1);
  context.ui.screen = "stream";
  await wait(HOME_RETRY * 3);
  context.ui.screen = "artifacts";
  context.tree.model = {byRef: new Map()};
  homeOpen("artifact:wt_3a_/r/gone", "artifacts", 3);
  await wait(HOME_RETRY * 2);
  console.log(JSON.stringify({refused, elsewhere, direct, waiting, opened, left: calls}));
})();
"""


def node(probe: str, *args: str) -> dict:
    done = subprocess.run(["node", "-e", probe, *args], capture_output=True, text=True, timeout=60, check=False)
    if done.returncode != 0:
        raise AssertionError(done.stderr[-2000:])
    return json.loads(done.stdout)


def escaped(raw: str) -> str:
    return re.sub(r"[^A-Za-z0-9./-]", lambda found: f"_{ord(found.group()):x}_", raw)


class TestHomeLayout(unittest.TestCase):
    def test_the_layout_validation_takes_at_most_64_pins_of_kind_id_w_and_h_in_their_ranges(self):
        data = node(LAYOUT_PROBE, str(PANELS))
        self.assertEqual(data["valid"], {
            "ok": True, "full": True, "over": False, "wide": False, "flat": False, "half": False, "text": False, "space": False, "long": False,
            "kind": False, "empty": False, "extra": False, "twice": False, "object": False,
        })
        self.assertEqual(data["cleaned"], [64, {"kind": "task", "id": "work/a", "w": 4, "h": 3}, "work/t0"])
        self.assertEqual(data["notList"], [])


class TestHomeReorder(unittest.TestCase):
    def test_reorder_resize_add_and_remove_are_idempotent_and_hold_their_bounds(self):
        data = node(REORDER_PROBE, str(PANELS))
        self.assertEqual(data["place"], ["bcad", "dabc", "abcd", "abcd", "abcd"])
        self.assertEqual(data["move"], ["abcd", "bacd", "abcd", "acbd"])
        self.assertEqual([(pin["w"], pin["h"]) for pin in data["resize"]], [(1, 12), (12, 1), (7, 3)])
        self.assertEqual(data["stretch"], [{"w": 6, "h": 3}, {"w": 1, "h": 1}, {"w": 12, "h": 12}, {"w": 5, "h": 3}])
        self.assertEqual(data["untouched"], "abcd")
        self.assertEqual(data["add"], ["", PIN, 5, 4, 4, "full", 64, "", 64])

    def test_reorder_and_resize_find_their_pin_by_key_and_leave_the_list_alone_without_it(self):
        data = node(REORDER_PROBE, str(PANELS))
        resized = {"kind": "task", "id": "b", "w": 5, "h": 2}
        self.assertEqual(data["keys"], ["bcad", "abcd", "acbd", "abcd", resized, resized, "abcd", "abcd"])

    def test_home_holds_one_3d_tile_and_refuses_a_second_with_its_holder(self):
        data = node(REORDER_PROBE, str(PANELS))
        holder = {"kind": "panel", "id": "agents/3d", "w": 6, "h": 4}
        self.assertEqual(data["group"], ["", "group", holder, 5, "", "tasks/3d", "", True, False, True])

    def test_a_panel_with_its_own_size_is_pinned_at_it_and_the_rest_at_the_default(self):
        data = node(REORDER_PROBE, str(PANELS))
        self.assertEqual(data["sized"], [{"kind": "panel", "id": "radio", "w": 12, "h": 7}, PIN, {"kind": "task", "id": "work/z", "w": 4, "h": 3}])


class TestHomeRegistry(unittest.TestCase):
    def test_the_registry_finds_panels_and_item_kinds_and_a_missing_item_renders_none(self):
        data = node(REGISTRY_PROBE, str(PANELS))
        self.assertEqual(data["gantt"], ["Tasks: Gantt", "gantt 6x4"])
        self.assertEqual(data["live"], ["Task work/live", "task work/live 3"])
        self.assertIsNone(data["gone"])
        self.assertIsNone(data["unknownPanel"])
        self.assertIsNone(data["unknownKind"])
        self.assertEqual(data["token"], ["branch_3a_/repo_0_feature_20_x", True, True, True, "work/plain", "a_5f_b", "a_b", None, "1763.5/radio_3a_work/x_3a_9"])

    @unittest.skipUnless((TEMPLATES / "view-store.js").exists(), "waits on 007: view-store.js is not on this branch yet")
    def test_pin_ids_follow_the_view_store_id_grammar(self):
        probe = 'const P = require(process.argv[1]); const V = require(process.argv[2]); const ids = ["work/a", "branch:/r\\u0000x y", "a_b", "1763.5/radio:w:9"]; console.log(JSON.stringify(ids.map((id) => [P.token(id), V.id(id)])));'
        done = subprocess.run(["node", "-e", probe, str(PANELS), str(TEMPLATES / "view-store.js")], capture_output=True, text=True, timeout=60, check=True)
        for mine, theirs in json.loads(done.stdout):
            self.assertEqual(mine, theirs)

    def test_the_store_changes_the_stored_pins_through_update_and_refuses_an_invalid_layout_before_the_backend(self):
        data = node(STORE_PROBE, str(PANELS))
        self.assertEqual(data["read"], ["work/a"])
        self.assertTrue(data["wrote"])
        self.assertEqual(data["calls"], [["on", "home.pins"], ["get", "home.pins"], ["get", "home.pins"], ["update", "home.pins", ["work/a", "work/other", "work/c"]]])
        self.assertEqual(data["refused"], "invalid layout")
        self.assertEqual(data["late"], [True, 64, False])
        self.assertEqual(data["unknown"], [[], False, "unknown view path home.pins", "another browser kept changing home.pins; try again", ""])
        self.assertEqual(data["seen"], [1])
        self.assertEqual(data["memory"], [2, [2]])


class TestHomeStart(unittest.TestCase):
    def test_home_is_the_first_tab_and_the_start_once_a_pin_exists_while_an_explicit_hash_wins(self):
        data = node(START_PROBE, str(NAV))
        self.assertEqual((data["first"], data["icon"]), (["home", "Home"], "bi-house-door"))
        stream = {"screen": "stream", "view": None, "redirect": None}
        home = {"screen": "home", "view": None, "redirect": None}
        self.assertEqual(data["routes"], [
            stream, {"screen": "home", "view": None, "redirect": "#home"}, {"screen": "home", "view": None, "redirect": "#home"}, home, home,
            {"screen": "tasks", "view": "gantt", "redirect": None}, stream, stream, stream,
        ])


class TestHomePage(unittest.TestCase):
    def test_the_page_registers_every_panel_and_item_kind_and_refuses_the_65th_pin_before_any_update(self):
        data = node(PAGE_PROBE, str(PANELS), str(HOME))
        self.assertEqual(data["ids"], {"panel": True, "task": True, "message": True, "artifact": True, "agent": True, "ancestry": True, "metric": True, "nope": False})
        self.assertEqual(data["panels"], [])
        self.assertEqual((data["one"], data["none"], data["solid"], data["full"], data["after"]), (["panel:tasks/gantt"], 0, ["panel:agents/3d"], [64, 0], 63))
        self.assertEqual(data["paths"], ["home.pins"])
        self.assertEqual(data["toasts"][:2], [
            ["One 3D tile at a time", "Home already holds Agents: 3D: unpin it before you pin Tasks: 3D.", False],
            ["Home is full", "At most 64 pins: unpin one before you pin Task work/t64.", False],
        ])

    def test_a_refused_update_falls_back_to_the_stored_pins_and_shows_the_store_error(self):
        data = node(PAGE_PROBE, str(PANELS), str(HOME))
        self.assertEqual((data["optimistic"], data["tries"], data["reverted"], data["fellBack"]), (62, 3, 63, True))
        self.assertEqual(data["toasts"][2:], [["Home not saved", "another browser kept changing home.pins; try again", False]])

    def test_two_stale_tabs_keep_both_pins_and_a_late_65th_pin_is_refused_visibly(self):
        data = node(RACE_PROBE, str(PANELS), str(HOME))
        both = ["panel:tasks/gantt", "task:work/b"]
        self.assertEqual(data["pinned"], [both, 3, both])
        self.assertEqual(data["full"], [64, True, False, [["Home is full", "At most 64 pins: unpin one before you pin Task work/d.", False]], []])
        self.assertEqual(data["unpinned"], ["task:work/b", "task:work/c"])
        self.assertEqual(data["toasts"], [])

    def test_every_data_panel_and_data_item_kind_in_the_templates_is_registered(self):
        home = HOME.read_text(encoding="utf-8")
        registered = set(re.findall(r'Panels\.panel\("([^"]+)"', home))
        kinds = set(re.findall(r'Panels\.item\("([^"]+)"', home))
        sources = "\n".join(path.read_text(encoding="utf-8") for path in TEMPLATES.glob("page-*.js"))
        literal = set(re.findall(r'"data-panel": "([^"]+)"', sources))
        views = {"agents": ["orbit", "chord", "swimlane", "3d"], "artifacts": ["orbit", "chord", "swimlane", "3d"], "tasks": ["list", "board", "rasci", "gantt", "burn"]}
        dynamic = {f"{tab}/{view}" for tab in re.findall(r'"data-panel": `(\w+)/\$\{view\}`', sources) for view in views[tab]}
        used = set(re.findall(r'(?:"data-item"|item): `(\w+):', sources))
        marked = set(re.findall(r"\['[^']+', \"([^\"]+)\"\]", home))
        captured = set(re.findall(r'Panels\.capture\("([^"]+)"', home))
        made = set(re.findall(r'\{kind: "(\w+)", id, view[,}]', sources))
        self.assertEqual((len(literal), marked), (13, {"radio-log"}))
        literal |= marked
        self.assertEqual(len(dynamic), 13)
        self.assertEqual(sorted(literal | dynamic), sorted(registered))
        self.assertIn('"data-panel": `resources-${kind}`', sources)
        self.assertEqual(captured, {"resources-hardware", "resources-tokens", "resources-combined"})
        self.assertFalse(captured & registered)
        self.assertEqual((made, sorted(used | made)), ({"metric"}, sorted(kinds)))


class TestHomeStars(unittest.TestCase):
    def test_a_star_sits_in_flow_in_its_own_hosts_slot_or_a_star_row_and_never_twice(self):
        data = node(STAR_PROBE, str(PANELS))
        self.assertEqual(data["panel"], {"first": "star-row", "stars": 1, "pressed": "false", "title": "Pin to Home: Tasks: list"})
        self.assertEqual(data["task"], {"inSlot": True, "slotLast": True, "rows": 0, "pressed": "true", "label": "Unpin from Home"})
        self.assertEqual(data["bare"], {"first": "star-row", "stars": 1})
        self.assertEqual((data["svg"], data["radio"], data["again"], data["redrawn"]), (0, ["radio-log", "star-row"], [4, 4], [True, 4]))
        self.assertEqual(data["clicked"], [["task", "work/a", "Task work/a", None]])

    def test_the_star_css_positions_nothing_and_leaves_the_starred_elements_alone(self):
        css = (TEMPLATES / "style-home.css").read_text(encoding="utf-8")
        star = re.findall(r"^\.star(?:-row)?(?:\[[^\]]+\])? \{([^}]*)\}", css, re.MULTILINE)
        self.assertEqual(len(star), 3)
        self.assertFalse(any("position" in rule for rule in star), star)
        self.assertNotIn("[data-panel]", css)
        self.assertNotIn("[data-item]", css)


class TestHomeBookmarks(unittest.TestCase):
    VIEW: ClassVar[dict] = {"chart": "hardware", "tokens": "interval", "shown": ["host:CPU"]}

    def test_a_pin_may_carry_a_plain_view_that_cleaning_adding_resizing_and_the_registry_keep(self):
        data = node(VIEW_PROBE, str(PANELS))
        pin = {"kind": "metric", "id": "hardware/x", "w": 4, "h": 3, "view": self.VIEW}
        self.assertEqual(data["valid"], [True, False, False, False, False])
        self.assertEqual(data["cleaned"], [pin])
        self.assertEqual(data["added"], [[pin], [{"kind": "task", "id": "work/a", "w": 4, "h": 3}], [{"kind": "task", "id": "work/a", "w": 4, "h": 3}]])
        self.assertEqual(data["resized"], [{**pin, "w": 6, "h": 5}])
        self.assertEqual(data["lookup"], ["Metric hardware/x host:CPU", "hardware/x 4 hardware", "Metric hardware/x none", None])
        self.assertEqual(data["digest"], [True, False, True, True])

    def test_a_captured_panel_stars_the_pin_its_capture_makes_now_and_presses_it_with_its_view(self):
        data = node(CAPTURE_PROBE, str(PANELS))
        self.assertEqual(data["before"], ["false", "Pin to Home: Metric all", 0, True])
        self.assertEqual(data["after"], ["true", "Unpin from Home: Metric host:CPU", 1])
        self.assertEqual(data["clicked"], [["metric", "hardware/cpu", "Metric host:CPU", self.VIEW]])
        self.assertEqual(data["target"], {"kind": "metric", "id": "hardware/cpu", "view": self.VIEW})

    def test_a_chart_star_pins_the_series_switched_on_now_so_another_selection_is_another_pin(self):
        data = node(METRIC_PROBE, str(PANELS), str(TEMPLATES / "page-resources.js"), str(HOME))
        cpu, mixed = data["digests"]
        self.assertEqual(data["empty"], {"kind": "metric", "id": "tokens/accumulated/all", "view": {"chart": "tokens", "tokens": "accumulated", "shown": None}})
        self.assertEqual(data["pins"], [
            {"kind": "metric", "id": f"hardware/{cpu}", "view": self.VIEW},
            {"kind": "metric", "id": "tokens/accumulated/all", "view": {"chart": "tokens", "tokens": "accumulated", "shown": None}},
            {"kind": "metric", "id": f"combined/interval/{mixed}", "view": {"chart": "combined", "tokens": "interval", "shown": ["burn:done", "host:CPU"]}},
        ])
        self.assertEqual(data["all"], {"kind": "metric", "id": "hardware/all", "view": {"chart": "hardware", "tokens": "interval", "shown": None}})
        self.assertEqual(data["titles"], ["Hardware: CPU", "Tokens (accumulated): all series", "Combined: done, CPU", "Hardware: all series", "Tokens (accumulated): all series"])
        self.assertEqual((data["four"], data["broken"]), ("Tokens: 4 series", ["Metric", None]))

    def test_pressing_a_metric_star_stores_its_view_with_the_pin_and_pressing_again_unpins_it(self):
        data = node(PRESS_PROBE, str(PANELS), str(HOME))
        pin = {"kind": "metric", "id": "hardware/abc", "w": 4, "h": 3, "view": self.VIEW}
        self.assertEqual((data["stored"], data["after"], data["pins"]), ([pin], [], []))

    def test_a_chart_star_refuses_a_selection_past_the_view_stores_series_limit_and_names_why(self):
        data = node(METRIC_PROBE, str(PANELS), str(TEMPLATES / "page-resources.js"), str(HOME), str(SHOWN_LIMIT))
        why = f"more than {SHOWN_LIMIT} series are switched on: switch some off, or all of them on"
        self.assertEqual(data["limits"], [[SHOWN_LIMIT, None, 3], [SHOWN_LIMIT + 1, why, 3], [None, None, 3], [0, None, 3]])

    def test_a_refused_capture_or_an_overlong_id_disables_the_star_with_its_reason_and_a_press_pins_nothing(self):
        data = node(REFUSED_PROBE, str(PANELS))
        refused = [True, "Pin to Home: not possible, too many series", "false"]
        self.assertEqual((data["refused"], data["again"]), (refused, refused))
        self.assertEqual(data["freed"], [False, "Pin to Home: Metric tokens/interval/y", "false", True])
        self.assertEqual(data["long"], [True, "Pin to Home: not possible, the id runs past 200 characters", "false"])
        self.assertEqual(data["clicked"], [["metric", "tokens/interval/y", "Metric tokens/interval/y", {"chart": "tokens"}]])

    def test_the_agent_priority_star_stays_the_same_button_and_keeps_its_focus_through_a_redraw(self):
        data = node(ORDER_PROBE, str(PANELS), str(TEMPLATES / "page-agent-order.js"))
        self.assertEqual(data, {"count": 1, "same": True, "focused": True, "head": True, "ranks": ["Stage", "Skills", "Docs"]})

    def test_the_client_pin_id_grammar_is_the_hubs(self):
        done = subprocess.run(["node", "-e", "console.log(JSON.stringify(require(process.argv[1]).ID.source))", str(PANELS)], capture_output=True, text=True, timeout=60, check=True)
        self.assertEqual(json.loads(done.stdout), f"^{SERIES_ID.pattern}$")


class TestHomeTree(HubCase):
    def served_tree(self) -> str:
        scanned = {"generated_at": "2026-11-14T12:00:00+00:00", "delete_ready": False, "delete_reason": "Secret Service locked", "repos": long_repos()}
        self.tree_file.write_text(json.dumps(scanned), encoding="utf-8")
        self.write_local_plan(scanned, {MERGED_BRANCH: {"skip": None, "actions": ["local-branch"]}})
        self.write_council({"rasci.json": {LONG_TASK: long_task(time.time())}})
        status, _, body = self.get("/api/tree")
        self.assertEqual(status, 200, body[:300])
        served = self.outside / "served-tree.json"
        served.write_bytes(body)
        return str(served)

    def test_every_tree_row_on_paths_of_real_length_pins_shows_that_one_element_on_home_and_turns_gone(self):
        data = node(TREE_PROBE, str(PANELS), str(TEMPLATES / "page-artifacts.js"), str(TEMPLATES / "page-tree.js"), str(HOME), self.served_tree())
        rows = [
            (f"repo:{CORE_REPO}", "github.com/infinito-nexus/core", CORE_REPO),
            (f"branch:{CORE_REPO}\0{CORE_BRANCH}", CORE_BRANCH, None),
            (f"wt:{CORE_WORKTREE}", CORE_BRANCH, CORE_WORKTREE),
            (f"repo:{LONG_REPO}", "github.com/operator-example-01/skills", LONG_REPO),
            (f"branch:{LONG_REPO}\0{LONG_BRANCH}", LONG_BRANCH, None),
            (f"wt:{LONG_WORKTREE}", LONG_BRANCH, LONG_WORKTREE),
            (f"artefact:wt:{LONG_WORKTREE}\0{LONG_TASK}\0{LONG_VOLUME}", LONG_VOLUME.split(":", 1)[1], LONG_VOLUME),
            (f"branch:{LONG_REPO}\0{MERGED_BRANCH}", MERGED_BRANCH, None),
        ]
        self.assertEqual(len(data["pinned"]), len(rows), data["pinned"])
        digested = []
        for found, (raw, label, path) in zip(data["pinned"], rows, strict=True):
            with self.subTest(row=raw):
                self.assertEqual((found["refused"], found["title"], found["label"], found["path"], found["deletes"]), (None, f"Artifact {raw.replace(chr(0), ' ')}", label, path, 0), found)
                self.assertTrue(SERIES_ID.fullmatch(found["id"]), found)
                if len(escaped(raw)) <= 200:
                    self.assertEqual(found["id"], escaped(raw))
                else:
                    self.assertRegex(found["id"], rf"^{raw.split(':', 1)[0]}_23_[0-9a-f]{{16}}$")
                    digested.append(found["id"].split("_23_")[0])
        self.assertEqual(digested, ["wt", "artefact"])
        self.assertEqual(data["glance"], [1, 0, 0])
        self.assertEqual(data["empty"], ["No repository", "Nothing found", "pkgmgr names no repository."])
        self.assertEqual([gone[0] for gone in data["gone"]], [None, None])
        for gone, kind in zip(data["gone"], digested, strict=True):
            self.assertRegex(gone[1], rf"^Artifact {kind}#[0-9a-f]{{16}}$")


class TestHomeMessage(unittest.TestCase):
    def test_a_pinned_message_resolves_by_its_own_id_and_time_whatever_the_stream_shows(self):
        data = node(MESSAGE_PROBE, str(PANELS), str(HOME))
        self.assertEqual(data["first"], "wait")
        self.assertEqual(data["urls"], ["/api/events?from=1762999999&to=1763000002&after=0", "/api/events?from=1762999899&to=1762999901&after=0"])
        self.assertEqual((data["found"], data["gone"], data["cached"], data["broken"]), ("row radio:abc", None, "row transcript:7", None))
        self.assertEqual(len(data["urls"]), data["fetches"])


class TestHomeOpen(unittest.TestCase):
    PANEL_IDS = (
        "stream", "radio-log", "agents/orbit", "agents/chord", "agents/swimlane", "agents/3d", "agents/tree", "agents/hierarchy", "agents/order",
        "artifacts/orbit", "artifacts/chord", "artifacts/swimlane", "artifacts/tree", "artifacts/3d",
        "tasks/list", "tasks/board", "tasks/rasci", "tasks/gantt", "tasks/burn", "tasks/3d", "tasks/operator",
    )
    ITEMS: ClassVar[dict] = {
        "task": ("#tasks/list", "task:work/a", "tasks", "list"),
        "message": ("#stream", "message:1763000000.5/radio_3a_abc", "stream", None),
        "artifact": ("#artifacts/orbit", "artifact:branch_3a_/repo_0_feature_20_x", "artifacts", "orbit"),
        "agent": ("#agents/orbit", "agent:s1", "agents", "orbit"),
        "ancestry": ("#artifacts/tree", "ancestry:/repo", "artifacts", "tree"),
        "metric": ("#resources", "metric:hardware/0123456789abcdef", "resources", None),
    }

    def test_a_hash_may_name_a_pin_to_open_and_then_redirects_to_its_screen_without_it(self):
        hashes = ["#agents/orbit?open=agent:s1", "#stream/radio?open=x:y", "#tasks/operator?open=panel:tasks/operator", "#agents/orbit?other=1", "#resources?open=metric:hardware/x", "#?open=task:a"]
        probe = "const N = require(process.argv[1]); console.log(JSON.stringify(JSON.parse(process.argv[2]).map((hash) => N.route(hash, 1))));"
        done = subprocess.run(["node", "-e", probe, str(NAV), json.dumps(hashes)], capture_output=True, text=True, timeout=60, check=True)
        self.assertEqual(json.loads(done.stdout), [
            {"screen": "agents", "view": "orbit", "redirect": "#agents/orbit", "open": "agent:s1"},
            {"screen": "stream", "view": None, "redirect": "#stream", "spot": True, "open": "x:y"},
            {"screen": "inbox", "view": None, "redirect": "#tasks/operator", "open": "panel:tasks/operator"},
            {"screen": "agents", "view": "orbit", "redirect": None},
            {"screen": "resources", "view": None, "redirect": "#resources", "open": "metric:hardware/x"},
            {"screen": "home", "view": None, "redirect": "#home", "open": "task:a"},
        ])

    def test_every_panel_and_item_kind_links_to_its_own_tab_and_view_and_an_item_names_itself_to_open(self):
        data = node(LINK_PROBE, str(NAV), str(PANELS), str(HOME), json.dumps(self.PANEL_IDS))
        special = {"stream": ("stream", None), "radio-log": ("stream", None), "agents/order": ("agents", "hierarchy"), "tasks/operator": ("inbox", None)}
        for panel in self.PANEL_IDS:
            with self.subTest(panel=panel):
                found = data["panels"][panel]
                self.assertIsNotNone(found)
                screen, view = special.get(panel, tuple(panel.split("/")))
                self.assertEqual((found["route"]["screen"], found["route"]["view"]), (screen, view), found)
        self.assertEqual(data["panels"]["radio-log"], {"href": "#stream/radio", "route": {"screen": "stream", "view": None, "redirect": "#stream", "spot": True}})
        self.assertEqual(data["panels"]["agents/order"]["href"], "#agents/hierarchy?open=panel:agents/order")
        self.assertEqual(data["panels"]["agents/order"]["route"]["open"], "panel:agents/order")
        self.assertEqual({panel: found["href"] for panel, found in data["panels"].items() if panel not in ("radio-log", "agents/order")}, {panel: f"#{panel}" for panel in self.PANEL_IDS if panel not in ("radio-log", "agents/order")})
        for kind, (hash_, key, screen, view) in self.ITEMS.items():
            with self.subTest(kind=kind):
                self.assertEqual(data["items"][kind], {"href": f"{hash_}?open={key}", "route": {"screen": screen, "view": view, "redirect": hash_, "open": key}})
        self.assertIsNone(data["unknown"])

    def test_an_opened_item_waits_for_its_data_gives_up_on_a_gone_one_and_stops_once_another_screen_shows(self):
        data = node(OPEN_PROBE, str(PANELS), str(HOME))
        self.assertEqual((data["refused"], data["elsewhere"], data["waiting"], data["left"]), ([], [], [], []), data)
        self.assertEqual(data["direct"], [["taskSheet", "work/a"], ["openAgent", "name:Stage", "function"]])
        self.assertEqual(data["opened"], [[["drawArtifacts"], ["artSelect", "wt:/r/w"]], "/r"])


class TestHomeIndex(HubCase):
    def test_the_index_embeds_the_registry_the_home_page_and_its_styles(self):
        html = self.index()
        for name in ("panels.js", "page-home.js", "style-home.css"):
            with self.subTest(name=name):
                self.assertIn((TEMPLATES / name).read_text(encoding="utf-8").strip(), html)
        for glyph in ("bi-star", "bi-star-fill", "bi-house-door", "bi-grip-vertical", "bi-arrow-down-right", "bi-arrows-angle-expand"):
            with self.subTest(glyph=glyph):
                self.assertIn(f'<symbol id="{glyph}"', html)


if __name__ == "__main__":
    unittest.main()
