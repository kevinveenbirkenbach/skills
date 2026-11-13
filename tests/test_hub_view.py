from __future__ import annotations

import copy
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hub_case import HubCase
from hub_support import HOST_STATE, HUB, server
from kvb_orchestrator import records
from kvb_orchestrator.errors import Conflict, ToolError
from kvb_orchestrator.handler import BODY_LIMIT
from kvb_orchestrator.viewstore import (
    CHANGE_LIMIT,
    VIEW,
    VIEW_LIMIT,
    ViewStore,
    valid_view,
    value_at,
)

STORE = HUB / "templates" / "view-store.js"
CHIPS = HUB / "templates" / "legend-chips.js"
CHIPS_STYLE = HUB / "templates" / "style-legend-chips.css"
FULL = {
    "resources": {"hidden": ["host:CPU", "agent:Stage", "disk:/mnt_20_data"], "tokens": "accumulated", "combined": True, "combinedHidden": ["burn:scope"]},
    "burn": {"overlays": ["fix", "score"]},
    "home": {"pins": [{"kind": "panel", "id": "resources-hardware", "w": 12, "h": 4}, {"kind": "task", "id": "work/feature", "w": 1, "h": 12}]},
}
PIN = {"kind": "panel", "id": "resources-hardware", "w": 6, "h": 3}
EMBEDDED = re.compile(r'<script nonce="[^"]+" id="view" type="application/json">(.*?)</script>')
MAKE = """
const make = (tag) => {
  const node = {tag, attrs: {}, children: [], listeners: {}, textContent: "",
    set className(value) { this.attrs.class = value; }, set type(value) { this.attrs.type = value; },
    setAttribute(key, value) { this.attrs[key] = String(value); }, getAttribute(key) { return this.attrs[key]; },
    addEventListener(name, run) { this.listeners[name] = run; }, append(...items) { this.children.push(...items); }};
  return node;
};
"""
CLIENT_PROBE = """
const fs = require("fs");
const vm = require("vm");
const doc = JSON.parse(process.argv[2]);
const clone = (value) => JSON.parse(JSON.stringify(value));
const same = (one, other) => JSON.stringify(one) === JSON.stringify(other);
const server = clone(doc);
const sent = [];
const hooks = {};
let refuse = false;
let churn = 0;
let hold = null;
let gets = 0;
const at = (path) => path.split(".").reduce((node, key) => node[key], server);
const context = {
  setTimeout, clearTimeout,
  addEventListener: (name, run) => {
    hooks[name] = (hooks[name] || 0) + 1;
    hooks[`${name}:run`] = run;
  },
  document: {getElementById: (name) => (name === "view" ? {textContent: JSON.stringify(doc)} : null)},
  fetch: async (url, options) => {
    if (options.method === "GET") {
      gets += 1;
      return {ok: true, status: 200, json: async () => clone(server)};
    }
    const body = JSON.parse(options.body);
    sent.push({url, method: options.method, headers: options.headers, keepalive: options.keepalive, body});
    if (hold) {
      await hold;
    }
    if (refuse) {
      refuse = false;
      return {ok: false, status: 400, text: async () => "resources.tokens must be one of interval, accumulated\\n"};
    }
    if (churn && Object.hasOwn(body.set, "resources.hidden")) {
      server.resources.hidden = [...server.resources.hidden, `churn${churn}`];
      churn += 1;
    }
    const moved = Object.keys(body.set).filter((path) => !same(at(path), body.expect[path]));
    if (moved.length) {
      return {ok: false, status: 409, json: async () => ({view: clone(server), paths: moved})};
    }
    for (const [path, value] of Object.entries(body.set)) {
      const [section, key] = path.split(".");
      server[section][key] = value;
    }
    return {ok: true, status: 200, json: async () => clone(server)};
  },
};
vm.runInNewContext(`${fs.readFileSync(process.argv[1], "utf8")}\\nstore = ViewStore;`, context);
const V = context.store;
const heard = [];
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const caught = (run) => {
  try {
    run();
  } catch (error) {
    return error.message;
  }
  return null;
};
(async () => {
  V.on("resources.hidden", (value) => heard.push(["hidden", value]));
  V.on("home.pins", (value) => heard.push(["pins", value]));
  const unknown = caught(() => V.get("resources.nope"));
  const wide = caught(() => V.update("resources", (value) => value));
  const listSet = caught(() => V.set("resources.hidden", ["host:RAM"]));
  const first = V.update("resources.hidden", (list) => [...list, "host:CPU"]);
  const second = V.set("resources.tokens", "accumulated");
  const local = [V.get("resources.hidden"), V.get("resources.tokens"), sent.length, clone(heard)];
  const stored = await Promise.all([first, second]);
  server.home.pins = [@PIN@];
  server.burn.overlays = ["fix"];
  const combined = await V.set("resources.combined", true);
  const adopted = [V.get("home.pins"), V.get("burn.overlays"), V.get("resources.hidden"), heard.filter(([name]) => name === "pins").at(-1)];
  server.resources.hidden = ["host:CPU", "host:RAM"];
  const rebased = await V.update("resources.hidden", (list) => [...list, "disk:/"]);
  const merged = V.get("resources.hidden");
  churn = 1;
  const churned = await V.update("resources.hidden", (list) => list.filter((item) => item !== "disk:/"));
  churn = 0;
  const gaveUp = [V.get("resources.hidden"), V.error()];
  refuse = true;
  let release = null;
  hold = new Promise((resolve) => {
    release = resolve;
  });
  const refusing = V.set("resources.tokens", "interval");
  await wait(400);
  const newer = V.update("resources.combinedHidden", (list) => [...list, "burn:scope"]);
  hold = null;
  release();
  const refused = await refusing;
  const during = [V.get("resources.tokens"), V.get("resources.combinedHidden"), V.error()];
  const kept = await newer;
  hold = new Promise((resolve) => {
    release = resolve;
  });
  const flying = V.update("burn.overlays", (list) => [...list.filter((item) => item !== "fix"), "score"]);
  await wait(400);
  const leaving = V.update("home.pins", (pins) => pins.filter((pin) => pin.id !== "@PIN_ID@"));
  const beforeLeave = sent.length;
  hooks["pagehide:run"]();
  await new Promise((resolve) => setImmediate(resolve));
  const atLeave = sent.length;
  hold = null;
  release();
  const landed = await Promise.all([flying, leaving]);
  await wait(400);
  const left = clone(server);
  server.resources.combined = false;
  await hooks["pageshow:run"]({persisted: false});
  const notRestored = [gets, V.get("resources.combined")];
  await hooks["pageshow:run"]({persisted: true});
  const restored = [gets, V.get("resources.combined"), hooks.pageshow];
  const long = "x".repeat(300);
  console.log(JSON.stringify({
    unknown, wide, listSet, local, stored, combined, adopted, rebased, merged, churned, gaveUp, refused, during, kept, beforeLeave, atLeave, landed, sent, server: left, hooks: hooks.pagehide, error: V.error(), notRestored, restored,
    ids: [V.id("host", "CPU"), V.id("disk", "/"), V.id("util", "0000:01:00.0"), V.id("agent", "Stage (this session) [5d88e9]"), V.id("a:b", "c"), V.id("a", "b:c"), V.id("a_3a_b"), V.id("agent", long), V.id("agent", `${long}y`), V.id("agent", "Çelik 🦫")],
  }));
})();
""".replace("@PIN@", json.dumps(PIN)).replace("@PIN_ID@", PIN["id"])
TWO_TABS = (
    """
const fs = require("fs");
const vm = require("vm");
const code = `${fs.readFileSync(process.argv[1], "utf8")}\\n${fs.readFileSync(process.argv[2], "utf8")}`;
const base = process.argv[3];
@MAKE@
const SERIES = {
  "resources.hidden": [{id: "host:CPU", label: "CPU", tone: "res-c0"}, {id: "host:RAM", label: "RAM", tone: "res-c1"}],
  "burn.overlays": [{id: "fix", label: "Fix", tone: "k-fix"}, {id: "score", label: "Score", tone: "k-score"}],
};
const MODE = {"resources.hidden": "hidden", "burn.overlays": "shown"};
const tab = async () => {
  const doc = await (await fetch(`${base}/api/view`)).json();
  const groups = [];
  const context = {
    setTimeout, clearTimeout,
    document: {getElementById: () => ({textContent: JSON.stringify(doc)}), createElement: make, querySelectorAll: () => groups.flatMap((group) => group.children)},
    fetch: (url, options) => fetch(`${base}${url}`, {...options, headers: {...options.headers, Origin: base}}),
  };
  vm.runInNewContext(`${code}\\nstore = ViewStore;\\nchips = LegendChips;`, context);
  const draw = (path) => {
    const group = context.chips.render(SERIES[path], path, MODE[path]);
    groups.splice(0, groups.length, group);
    return group;
  };
  const press = (path, id) => {
    draw(path).children.find((chip) => chip.attrs["data-chip"] === id).listeners.click();
    return context.store.update(path, (list) => list);
  };
  const pressed = (path) => draw(path).children.map((chip) => [chip.attrs["data-chip"], chip.attrs["aria-pressed"]]);
  const pin = (id) => context.store.update("home.pins", (pins) => [...pins, {kind: "panel", id, w: 6, h: 3}]);
  const refused = (path, value) => {
    try {
      context.store.set(path, value);
    } catch (error) {
      return error.message;
    }
    return null;
  };
  return {store: context.store, press, pressed, pin, refused};
};
const SCENARIOS = {
  merge: async (a, b) => {
    const refused = [a.refused("resources.hidden", ["host:RAM"]), b.refused("home.pins", [])];
    const results = [await a.press("resources.hidden", "host:CPU"), await b.press("resources.hidden", "host:RAM"), await a.pin("p1"), await b.pin("p2")];
    return {refused, results, seen: [a.store.get("resources.hidden"), b.store.get("home.pins").map((item) => item.id)]};
  },
  same: async (a, b) => {
    const results = [];
    for (const [path, id] of [["resources.hidden", "host:CPU"], ["burn.overlays", "fix"]]) {
      results.push(await a.press(path, id), await b.press(path, id));
    }
    return {results, chips: [b.pressed("resources.hidden"), b.pressed("burn.overlays")]};
  },
};
(async () => {
  const a = await tab();
  const b = await tab();
  const found = await SCENARIOS[process.argv[4]](a, b);
  const served = await (await fetch(`${base}/api/view`)).json();
  console.log(JSON.stringify({...found, errors: [a.store.error(), b.store.error()], hidden: served.resources.hidden, overlays: served.burn.overlays, pins: served.home.pins.map((item) => item.id)}));
})();
"""
).replace("@MAKE@", MAKE)
CHIPS_PROBE = (
    """
const fs = require("fs");
const vm = require("vm");
@MAKE@
const updates = [];
const groups = [];
const lists = {"resources.hidden": ["b"], "burn.overlays": ["fix"]};
const context = {
  document: {createElement: make, querySelectorAll: (selector) => (selector === ".legend-chip" ? groups.flatMap((group) => group.children) : [])},
  ViewStore: {get: (path) => [...lists[path]], update: (path, change) => { lists[path] = change([...lists[path]]); updates.push([path, lists[path]]); return Promise.resolve(true); }},
};
vm.runInNewContext(`${fs.readFileSync(process.argv[1], "utf8")}\\nchips = LegendChips;`, context);
const L = context.chips;
const group = L.render([{id: "a", label: "CPU 10 %", tone: "res-c0 k-host"}, {id: "b", label: "RAM 20 %", tone: "res-c1 k-host"}], "resources.hidden", "hidden");
groups.push(group);
const read = (node) => node.children.map((chip) => [chip.attrs["data-chip"], chip.attrs["aria-pressed"], chip.attrs.class, chip.textContent, chip.attrs.title]);
const before = read(group);
group.children[0].listeners.click();
group.children[1].listeners.click();
const after = read(group);
lists["resources.hidden"] = [...Array.from({length: 100}, (_, index) => `old${index}`), "a"];
group.children[1].listeners.click();
const overlays = L.render([{id: "fix", label: "Fix", tone: "k-fix"}, {id: "score", label: "Score", tone: "k-score"}], "burn.overlays", "shown");
const shownBefore = read(overlays);
overlays.children[1].listeners.click();
overlays.children[0].listeners.click();
let bad = null;
try {
  L.render([], "burn.overlays", "on");
} catch (error) {
  bad = error.message;
}
const many = Array.from({length: 103}, (_, index) => `o${index}`);
console.log(JSON.stringify({
  group: [group.tag, group.attrs.class, group.attrs.role], before, after, updates, keep: L.KEEP, shownBefore, shownAfter: read(overlays), overlaysGroup: overlays.attrs["aria-label"], bad,
  placed: [L.placed(["a"], "a", false), L.placed(["a"], "b", true), L.placed([], "a", true), L.placed(["a"], "a", true), L.placed([], "a", false)],
  pruned: [L.pruned(many, new Set(["o0", "o1"])), L.pruned(["x", "y"], new Set())],
}));
"""
).replace("@MAKE@", MAKE)


def change(values: dict, expected: dict) -> bytes:
    return json.dumps({"set": values, "expect": expected}).encode()


class TestViewDocument(unittest.TestCase):
    def test_the_defaults_and_a_full_document_pass_unchanged(self):
        self.assertEqual(valid_view(copy.deepcopy(VIEW)), VIEW)
        self.assertEqual(valid_view(copy.deepcopy(FULL)), FULL)
        self.assertEqual(VIEW, {"resources": {"hidden": [], "tokens": "interval", "combined": False, "combinedHidden": []}, "burn": {"overlays": []}, "home": {"pins": []}})

    def test_unknown_or_missing_keys_and_malformed_values_are_refused(self):
        def changed(section: str | None, key: str | None, value: object) -> dict:
            doc = copy.deepcopy(FULL)
            if section is None:
                doc[key] = value
            elif key is None:
                doc[section] = value
            elif value is KeyError:
                del doc[section][key]
            else:
                doc[section][key] = value
            return doc

        pin = FULL["home"]["pins"][0]
        cases = {
            "not an object": [],
            "unknown top key": changed(None, "theme", "dark"),
            "unknown nested key": changed("resources", "extra", 1),
            "missing key": changed("resources", "combinedHidden", KeyError),
            "section not an object": changed("burn", None, ["fix"]),
            "tokens mode": changed("resources", "tokens", "sum"),
            "combined not a flag": changed("resources", "combined", 1),
            "hidden not a list": changed("resources", "hidden", "host:CPU"),
            "id with a space": changed("resources", "hidden", ["host CPU"]),
            "empty id": changed("resources", "combinedHidden", [""]),
            "id too long": changed("resources", "hidden", ["x" * 201]),
            "repeated id": changed("resources", "hidden", ["a", "a"]),
            "too many ids": changed("resources", "hidden", [f"id{index}" for index in range(501)]),
            "unknown overlay": changed("burn", "overlays", ["cost"]),
            "repeated overlay": changed("burn", "overlays", ["fix", "fix"]),
            "null overlay": changed("burn", "overlays", [None]),
            "65 pins": changed("home", "pins", [{**pin, "id": f"p{index}"} for index in range(65)]),
            "pin width 0": changed("home", "pins", [{**pin, "w": 0}]),
            "pin height 13": changed("home", "pins", [{**pin, "h": 13}]),
            "pin width true": changed("home", "pins", [{**pin, "w": True}]),
            "pin width 1.5": changed("home", "pins", [{**pin, "w": 1.5}]),
            "pin kind too long": changed("home", "pins", [{**pin, "kind": "k" * 33}]),
            "pin id too long": changed("home", "pins", [{**pin, "id": "i" * 201}]),
            "pin unknown key": changed("home", "pins", [{**pin, "x": 1}]),
            "pin twice": changed("home", "pins", [pin, dict(pin)]),
        }
        for name, doc in cases.items():
            with self.subTest(case=name), self.assertRaises(ToolError):
                valid_view(doc)

    def test_sixty_four_pins_of_one_by_one_to_twelve_by_twelve_pass(self):
        doc = copy.deepcopy(VIEW)
        doc["home"]["pins"] = [{"kind": "panel", "id": f"p{index}", "w": 1 + index % 12, "h": 12 - index % 12} for index in range(64)]
        self.assertEqual(valid_view(doc), doc)

    def store(self) -> ViewStore:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        return ViewStore(Path(folder.name) / "view.json")

    def test_two_tabs_changing_other_paths_both_land_in_the_store(self):
        store = self.store()
        store.patch(change({"home.pins": [PIN], "burn.overlays": ["fix"]}, {"home.pins": [], "burn.overlays": []}))
        found = store.patch(change({"resources.hidden": ["host:CPU"]}, {"resources.hidden": []}))
        expected = {**VIEW, "resources": {**VIEW["resources"], "hidden": ["host:CPU"]}, "burn": {"overlays": ["fix"]}, "home": {"pins": [PIN]}}
        self.assertEqual((found, ViewStore(store.file).get()), (expected, expected))

    def test_a_stale_tab_on_the_same_path_gets_a_conflict_and_its_retry_keeps_both_changes(self):
        store = self.store()
        store.patch(change({"resources.hidden": ["host:CPU"], "home.pins": [PIN]}, {"resources.hidden": [], "home.pins": []}))
        before = store.file.read_bytes()
        second = {**PIN, "id": "p2"}
        with self.assertRaises(Conflict) as caught:
            store.patch(change({"resources.hidden": ["host:RAM"], "home.pins": [second]}, {"resources.hidden": [], "home.pins": []}))
        self.assertEqual(caught.exception.payload["paths"], ["resources.hidden", "home.pins"])
        self.assertEqual(value_at(caught.exception.payload["view"], "home.pins"), [PIN])
        self.assertEqual((store.file.read_bytes(), store.get()["resources"]["hidden"]), (before, ["host:CPU"]))
        found = store.patch(change({"resources.hidden": ["host:CPU", "host:RAM"], "home.pins": [PIN, second]}, {"resources.hidden": ["host:CPU"], "home.pins": [PIN]}))
        self.assertEqual((found["resources"]["hidden"], found["home"]["pins"]), (["host:CPU", "host:RAM"], [PIN, second]))


class TestViewClient(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        done = subprocess.run(["node", "-e", CLIENT_PROBE, str(STORE), json.dumps(VIEW)], capture_output=True, text=True, timeout=60, check=True)
        cls.data = json.loads(done.stdout)
        chips = subprocess.run(["node", "-e", CHIPS_PROBE, str(CHIPS)], capture_output=True, text=True, timeout=60, check=True)
        cls.chips = json.loads(chips.stdout)

    def bodies(self) -> list[dict]:
        return [entry["body"] for entry in self.data["sent"]]

    def test_set_changes_the_value_at_once_and_sends_one_debounced_patch_against_the_stored_values(self):
        data = self.data
        self.assertEqual(data["unknown"], "unknown view path resources.nope")
        self.assertEqual(data["wide"], "a view path to change must be section.key, not resources")
        self.assertEqual(data["local"], [["host:CPU"], "accumulated", 0, [["hidden", ["host:CPU"]]]])
        self.assertEqual(data["stored"], [True, True])
        first = data["sent"][0]
        self.assertEqual((first["url"], first["method"], first["headers"], first["keepalive"]), ("/api/view", "PATCH", {"X-Kvb-Orchestrator": "1", "Content-Type": "application/json"}, False))
        self.assertEqual(self.bodies()[:2], [
            {"set": {"resources.hidden": ["host:CPU"], "resources.tokens": "accumulated"}, "expect": {"resources.hidden": [], "resources.tokens": "interval"}},
            {"set": {"resources.combined": True}, "expect": {"resources.combined": False}},
        ])

    def test_an_older_tab_adopts_what_another_browser_stored_on_other_paths(self):
        self.assertTrue(self.data["combined"])
        self.assertEqual(self.data["adopted"], [[PIN], ["fix"], ["host:CPU"], ["pins", [PIN]]])

    def test_a_conflict_on_the_same_path_reruns_the_change_on_the_stored_value_and_keeps_both(self):
        self.assertTrue(self.data["rebased"])
        self.assertEqual(self.data["merged"], ["host:CPU", "host:RAM", "disk:/"])
        self.assertEqual(self.bodies()[2:4], [
            {"set": {"resources.hidden": ["host:CPU", "disk:/"]}, "expect": {"resources.hidden": ["host:CPU"]}},
            {"set": {"resources.hidden": ["host:CPU", "host:RAM", "disk:/"]}, "expect": {"resources.hidden": ["host:CPU", "host:RAM"]}},
        ])

    def test_three_conflicts_in_a_row_give_up_with_the_stored_value_and_a_reason(self):
        self.assertFalse(self.data["churned"])
        self.assertEqual(len([body for body in self.bodies()[4:7] if "resources.hidden" in body["set"]]), 3)
        self.assertEqual(self.data["gaveUp"], [["host:CPU", "host:RAM", "disk:/", "churn1", "churn2", "churn3"], "another browser kept changing resources.hidden; try again"])

    def test_a_refused_change_falls_back_to_the_stored_value_and_keeps_a_newer_change(self):
        self.assertFalse(self.data["refused"])
        self.assertEqual(self.data["during"], ["accumulated", ["burn:scope"], "resources.tokens must be one of interval, accumulated"])
        self.assertTrue(self.data["kept"])

    def test_leaving_the_page_while_a_patch_is_in_flight_sends_the_pending_change_at_once_with_keepalive(self):
        data = self.data
        self.assertEqual(data["hooks"], 1)
        self.assertEqual((data["beforeLeave"], data["atLeave"]), (10, 11))
        last = data["sent"][-1]
        self.assertEqual((last["keepalive"], last["body"]), (True, {"set": {"home.pins": []}, "expect": {"home.pins": [PIN]}}))
        self.assertEqual(data["landed"], [True, True])
        self.assertEqual((data["server"]["burn"]["overlays"], data["server"]["home"]["pins"], data["error"]), (["score"], [], ""))

    def test_set_refuses_a_list_path_so_a_retry_cannot_overwrite_what_another_browser_stored(self):
        self.assertEqual(self.data["listSet"], "a list view path changes through update(), not set(): resources.hidden")
        self.assertEqual(self.data["local"][0], ["host:CPU"])

    def test_a_page_restored_from_the_back_forward_cache_refetches_the_stored_view(self):
        self.assertEqual(self.data["notRestored"], [0, True])
        self.assertEqual(self.data["restored"], [1, False, 1])

    def test_ids_follow_the_view_grammar_and_stay_distinct(self):
        ids = self.data["ids"]
        self.assertEqual(ids[:4], ["host:CPU", "disk:/", "util:0000_3a_01_3a_00.0", "agent:Stage_20__28_this_20_session_29__20__5b_5d88e9_5d_"])
        self.assertEqual(len(set(ids)), len(ids))
        for value in ids:
            with self.subTest(id=value):
                self.assertRegex(value, r"\A[A-Za-z0-9:_./-]{1,200}\Z")
        self.assertEqual(len(ids[7]), 200)

    def test_hidden_mode_chips_are_pressed_while_shown_and_toggle_through_update(self):
        chips = self.chips
        self.assertEqual(chips["group"], ["div", "legend-chips", "group"])
        self.assertEqual(chips["before"], [
            ["a", "true", "legend-chip res-c0 k-host", "CPU 10 %", "CPU 10 %: shown, press to hide"],
            ["b", "false", "legend-chip res-c1 k-host", "RAM 20 %", "RAM 20 %: hidden, press to show"],
        ])
        self.assertEqual([chip[1] for chip in chips["after"]], ["false", "true"])
        self.assertEqual(chips["updates"][:2], [["resources.hidden", ["b", "a"]], ["resources.hidden", ["a"]]])
        self.assertEqual(chips["placed"], [[], ["a", "b"], ["a"], ["a"], []])

    def test_shown_mode_chips_are_pressed_while_switched_on_and_store_the_on_list(self):
        chips = self.chips
        self.assertEqual([chip[:2] for chip in chips["shownBefore"]], [["fix", "true"], ["score", "false"]])
        self.assertEqual(chips["shownBefore"][1][4], "Score: off, press to switch it on")
        self.assertEqual(chips["updates"][3:], [["burn.overlays", ["fix", "score"]], ["burn.overlays", ["score"]]])
        self.assertEqual([chip[1] for chip in chips["shownAfter"]], ["false", "true"])
        self.assertEqual(chips["overlaysGroup"], "Overlays: press a chip to switch it on or off")
        self.assertEqual(chips["bad"], "a legend chip mode must be hidden or shown, not on")

    def test_hidden_ids_of_series_gone_from_the_page_are_dropped_oldest_first_beyond_the_cap(self):
        chips = self.chips
        self.assertEqual(chips["keep"], 100)
        many, short = chips["pruned"]
        self.assertEqual((len(many), many[:3]), (100, ["o0", "o1", "o5"]))
        self.assertEqual(short, ["x", "y"])
        path, last = chips["updates"][2]
        self.assertEqual((path, len(last), last[:2], last[-2:]), ("resources.hidden", 100, ["old2", "old3"], ["a", "b"]))


class TestHubView(HubCase):
    def patch(self, body: bytes, headers: dict[str, str]) -> tuple[int, bytes]:
        status, _, answer = self.call("PATCH", "/api/view", body, {**headers, "Content-Type": "application/json"})
        return status, answer

    def view(self) -> dict:
        status, _, body = self.get("/api/view")
        self.assertEqual(status, 200, body)
        return json.loads(body)

    def write(self, values: dict) -> tuple[int, bytes]:
        stored = self.view()
        return self.patch(change(values, {path: value_at(stored, path) for path in values}), self.guard(self.host))

    def reopen(self) -> None:
        self.httpd.hub = server.open_hub(
            council=self.council, pages=self.pages, public_port=self.port, state=self.state, host_state=HOST_STATE, transcripts=self.projects, scripts=self.scripts,
            templates=HUB / "templates",
            places=server.Places(tree_file=self.tree_file, timers=self.timers, vendor=HUB / "vendor", cleanup=self.cleanup, offices=self.offices, kept=self.kept),
            model=server.Model(url="", model="", key=""), engines=self.engines, approvers=self.approvers, redirects=self.redirects(),
        )

    def test_a_get_and_a_patch_round_trip_and_the_file_is_private(self):
        self.assertEqual(self.view(), VIEW)
        status, body = self.write(FULL)
        self.assertEqual((status, json.loads(body)), (200, FULL))
        self.assertEqual(self.view(), FULL)
        stored = self.state / "view.json"
        self.assertEqual(json.loads(stored.read_text(encoding="utf-8")), FULL)
        self.assertEqual(stored.stat().st_mode & 0o777, 0o600)

    def test_two_tabs_changing_other_paths_keep_both_changes(self):
        self.assertEqual(self.patch(change({"home.pins": [PIN], "burn.overlays": ["fix"]}, {"home.pins": [], "burn.overlays": []}), self.guard(self.host))[0], 200)
        status, body = self.patch(change({"resources.hidden": ["host:CPU"]}, {"resources.hidden": []}), self.guard(self.host))
        expected = {**VIEW, "resources": {**VIEW["resources"], "hidden": ["host:CPU"]}, "burn": {"overlays": ["fix"]}, "home": {"pins": [PIN]}}
        self.assertEqual((status, json.loads(body), self.view()), (200, expected, expected))

    def test_a_stale_expect_answers_409_with_the_stored_view_and_stores_nothing(self):
        self.assertEqual(self.write({"resources.hidden": ["host:CPU"]})[0], 200)
        before = (self.state / "view.json").read_bytes()
        status, body = self.patch(change({"resources.hidden": ["host:RAM"], "burn.overlays": ["fix"]}, {"resources.hidden": [], "burn.overlays": []}), self.guard(self.host))
        found = json.loads(body)
        self.assertEqual((status, found["paths"], found["view"]["resources"]["hidden"]), (409, ["resources.hidden"], ["host:CPU"]))
        self.assertEqual(((self.state / "view.json").read_bytes(), self.view()["burn"]["overlays"]), (before, []))

    def tabs(self, scenario: str) -> dict:
        done = subprocess.run(["node", "-e", TWO_TABS, str(STORE), str(CHIPS), self.origin, scenario], capture_output=True, text=True, timeout=60, check=True)
        return json.loads(done.stdout)

    def test_two_stale_tabs_of_the_page_scripts_keep_both_hidden_series_and_both_pins(self):
        found = self.tabs("merge")
        refusal = "a list view path changes through update(), not set(): "
        self.assertEqual(found["refused"], [f"{refusal}resources.hidden", f"{refusal}home.pins"])
        self.assertEqual((found["results"], found["errors"]), ([True, True, True, True], ["", ""]))
        self.assertEqual((found["hidden"], found["pins"]), (["host:CPU", "host:RAM"], ["p1", "p2"]))
        self.assertEqual(found["seen"], [["host:CPU", "host:RAM"], ["p1", "p2"]])
        self.assertEqual((self.view()["resources"]["hidden"], [pin["id"] for pin in self.view()["home"]["pins"]]), (["host:CPU", "host:RAM"], ["p1", "p2"]))

    def test_a_stale_tab_pressing_a_chip_another_tab_already_pressed_keeps_that_choice_in_both_modes(self):
        found = self.tabs("same")
        self.assertEqual((found["results"], found["errors"]), ([True, True, True, True], ["", ""]))
        self.assertEqual((found["hidden"], found["overlays"]), (["host:CPU"], ["fix"]))
        self.assertEqual(found["chips"], [[["host:CPU", "false"], ["host:RAM", "true"]], [["fix", "true"], ["score", "false"]]])
        self.assertEqual((self.view()["resources"]["hidden"], self.view()["burn"]["overlays"]), (["host:CPU"], ["fix"]))

    def test_a_malformed_change_an_unknown_path_or_a_body_past_the_change_limit_answers_400_and_stores_nothing(self):
        self.assertEqual(self.write(FULL)[0], 200)
        stored = self.state / "view.json"
        before = stored.read_bytes()
        padded = change({"resources.tokens": "interval"}, {"resources.tokens": "accumulated"})
        bodies = {
            "not json": b"{resources",
            "not utf-8": b"\xff\xfe{}",
            "a list": b"[]",
            "no expect": json.dumps({"set": {"resources.tokens": "interval"}}).encode(),
            "expect other paths": change({"resources.tokens": "interval"}, {"resources.combined": True}),
            "set and more": json.dumps({"set": {"resources.tokens": "interval"}, "expect": {"resources.tokens": "accumulated"}, "theme": "dark"}).encode(),
            "empty set": change({}, {}),
            "set a list": json.dumps({"set": [["resources.tokens", "interval"]], "expect": {}}).encode(),
            "unknown section": change({"theme": "dark"}, {"theme": "sky"}),
            "unknown key": change({"resources.extra": 1}, {"resources.extra": 0}),
            "too deep": change({"home.pins.0": PIN}, {"home.pins.0": PIN}),
            "a section missing a key": change({"resources": {"hidden": []}}, {"resources": FULL["resources"]}),
            "malformed value": change({"resources.combined": "yes"}, {"resources.combined": True}),
            "null overlay": change({"burn.overlays": [None]}, {"burn.overlays": ["fix", "score"]}),
            "one bad of two": change({"resources.tokens": "interval", "home.pins": [{**PIN, "w": 13}]}, {"resources.tokens": "accumulated", "home.pins": FULL["home"]["pins"]}),
            "the change limit and one byte": padded + b" " * (CHANGE_LIMIT + 1 - len(padded)),
            "512 KiB": padded + b" " * (512 << 10),
        }
        self.assertEqual((CHANGE_LIMIT, len(bodies["the change limit and one byte"])), (129 << 10, CHANGE_LIMIT + 1))
        for name, body in bodies.items():
            with self.subTest(case=name):
                status, answer = self.patch(body, self.guard(self.host))
                self.assertEqual(status, 400, answer)
                self.assertEqual(stored.read_bytes(), before)
                self.assertEqual(self.view(), FULL)
        exact = padded + b" " * (CHANGE_LIMIT - len(padded))
        self.assertEqual(self.patch(exact, self.guard(self.host))[0], 200)

    def test_a_list_near_the_document_cap_can_still_shrink_but_never_grow(self):
        ids = [f"agent:{'a' * 190}{index:04d}" for index in range(320)]
        status, answer = self.write({"resources.hidden": ids})
        self.assertEqual(status, 200, answer)
        stored = self.state / "view.json"
        self.assertGreater(len(stored.read_bytes()), VIEW_LIMIT - (1 << 10))
        before = stored.read_bytes()
        status, answer = self.write({"resources.hidden": [*ids, *(f"agent:{'b' * 190}{index:04d}" for index in range(3))]})
        self.assertEqual(status, 400, answer)
        self.assertIn(b"the view document must not exceed", answer)
        self.assertEqual((stored.read_bytes(), self.view()["resources"]["hidden"]), (before, ids))
        shrink = change({"resources.hidden": ids[:-1]}, {"resources.hidden": ids})
        self.assertGreater(len(shrink), VIEW_LIMIT)
        status, answer = self.patch(shrink, self.guard(self.host))
        self.assertEqual(status, 200, answer)
        self.assertEqual(self.view()["resources"]["hidden"], ids[:-1])

    def test_changes_that_grow_the_document_past_64_kib_are_refused(self):
        ids = [f"agent:{'a' * 180}{index:04d}" for index in range(300)]
        self.assertEqual(self.write({"resources.hidden": ids})[0], 200)
        before = (self.state / "view.json").read_bytes()
        status, answer = self.write({"resources.combinedHidden": [f"burn:{'b' * 180}{index:04d}" for index in range(100)]})
        self.assertEqual(status, 400, answer)
        self.assertEqual((self.state / "view.json").read_bytes(), before)
        self.assertEqual(self.view()["resources"]["combinedHidden"], [])

    def test_a_body_beyond_the_hub_wide_limit_answers_413_and_stores_nothing(self):
        status, _, answer = self.call("PATCH", "/api/view", b" " * (BODY_LIMIT + 1), {**self.guard(self.host), "Content-Type": "application/json"})
        self.assertEqual(status, 413, answer)
        self.assertFalse((self.state / "view.json").exists())

    def test_a_whole_document_put_no_longer_exists(self):
        status, _, _ = self.call("PUT", "/api/view", json.dumps(FULL).encode(), {**self.guard(self.host), "Content-Type": "application/json"})
        self.assertEqual(status, 501)
        self.assertEqual(self.view(), VIEW)

    def test_a_patch_needs_no_passkey_and_leaves_the_signed_settings_file_byte_identical(self):
        saved = {**self.snapshot()["settings"], "theme": "dark"}
        status, _, body = self.post_json("/api/settings", saved, self.guard(self.host))
        self.assertEqual(status, 200, body)
        settings = self.state / "settings.json"
        before, stamp = settings.read_bytes(), settings.stat().st_mtime_ns
        self.assertFalse(self.approvers.exists())
        status, body = self.write(FULL)
        self.assertEqual(status, 200, body)
        self.assertEqual((settings.read_bytes(), settings.stat().st_mtime_ns), (before, stamp))
        self.assertEqual(self.snapshot()["settings"], saved)

    def test_a_patch_without_the_header_from_a_foreign_origin_or_host_is_refused(self):
        body = change(FULL, VIEW)
        cases = {
            "no header": {"Host": self.host, "Origin": f"http://{self.host}"},
            "foreign origin": {"Host": self.host, "Origin": "http://evil.example", "X-Kvb-Orchestrator": "1"},
            "no origin": {"Host": self.host, "X-Kvb-Orchestrator": "1"},
        }
        for name, headers in cases.items():
            with self.subTest(case=name):
                self.assertEqual(self.patch(body, headers)[0], 403)
        self.assertEqual(self.patch(body, {**self.guard(self.host), "Host": "evil.example"})[0], 403)
        self.assertEqual(self.call("PATCH", "/api/settings", body, self.guard(self.host))[0], 404)
        self.assertFalse((self.state / "view.json").exists())
        self.assertEqual(self.view(), VIEW)

    def test_a_failed_write_keeps_the_stored_file_and_the_served_document(self):
        self.assertEqual(self.write(VIEW)[0], 200)
        stored = self.state / "view.json"
        before = stored.read_bytes()
        with mock.patch.object(records.os, "replace", side_effect=OSError(28, "No space left on device")):
            status, body = self.write(FULL)
        self.assertEqual(status, 500, body)
        self.assertEqual(stored.read_bytes(), before)
        self.assertEqual(self.view(), VIEW)

    def test_the_store_survives_a_hub_restart_and_the_page_carries_it(self):
        self.assertEqual(self.write(FULL)[0], 200)
        self.reopen()
        self.assertEqual(self.view(), FULL)
        embedded = EMBEDDED.search(self.index())
        self.assertIsNotNone(embedded)
        self.assertEqual(json.loads(embedded.group(1)), FULL)

    def test_a_broken_stored_file_falls_back_to_the_defaults(self):
        (self.state / "view.json").write_text('{"resources": {"hidden": ["bad id"]}}', encoding="utf-8")
        self.reopen()
        self.assertEqual(self.view(), VIEW)

    def test_the_page_carries_the_store_the_chips_and_their_style(self):
        html = self.index()
        for path in (STORE, CHIPS, CHIPS_STYLE):
            with self.subTest(file=path.name):
                self.assertIn(path.read_text(encoding="utf-8").strip(), html)


if __name__ == "__main__":
    unittest.main()
