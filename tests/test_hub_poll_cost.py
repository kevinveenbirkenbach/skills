from __future__ import annotations

import http.client
import json
import subprocess
import time
import unittest
from unittest import mock

from hub_case import HubCase
from hub_support import ASK, HUB
from kvb_orchestrator import register
from kvb_orchestrator.livestate import LiveState

TEMPLATES = HUB / "templates"
REGISTER = {"work/hub": {"title": "Build the hub", "status": "running", "roles": {"One": "RA"}}}
PROBE = r"""
const fs = require("fs");
const vm = require("vm");
const dir = process.argv[1];
const read = (name) => fs.readFileSync(`${dir}/${name}`, "utf8");
class El {
  constructor() { Object.assign(this, {children: [], textContent: "", replaced: 0}); }
  replaceChildren(...nodes) { this.replaced += 1; this.children = nodes; }
}
const results = {};

const timers = () => {
  const intervals = [];
  const listeners = {};
  const calls = {sky: 0, relayout: 0, radio: 0, closed: 0};
  const document = {hidden: true, addEventListener: (type, fn) => { (listeners[type] = listeners[type] || []).push(fn); }};
  const context = {
    document, window: {setInterval: (fn, ms) => intervals.push([fn, ms])}, MOVE: 1, RELAYOUT: 15000, tree: {dom: null}, CLOSED_POLL: 2000,
    poll: () => {}, follow: () => {}, fetchTree: () => {}, live: () => true, watchClosed: () => { calls.closed += 1; },
    drawSky: () => { calls.sky += 1; }, relayout: () => { calls.relayout += 1; }, syncRadio: () => { calls.radio += 1; },
  };
  vm.runInNewContext(`${read("page-timers.js")}\nstartTimers();`, context);
  const run = (ms) => intervals.forEach(([fn, every]) => { for (let n = 0; n < Math.floor(ms / every); n += 1) fn(); });
  run(60000);
  const hidden = {...calls};
  document.hidden = false;
  listeners.visibilitychange.forEach((fn) => fn());
  const shown = {...calls};
  run(10000);
  const watched = {...calls};
  document.hidden = true;
  listeners.visibilitychange.forEach((fn) => fn());
  run(30000);
  return {hidden, shown, watched, after: {...calls}};
};

const closedPolls = async () => {
  const seen = {match: 0, refresh: 0, requests: []};
  let closed = 4;
  const context = {
    STATE_TIMEOUT: 1000, state: {}, ui: {}, window: {setTimeout: () => 0, clearTimeout: () => {}, getSelection: () => ""}, document: {hidden: false},
    fetch: async (url) => { seen.requests.push(url); return {ok: true, json: async () => ({closed})}; },
    matchShown: () => true, fetchMatch: () => { seen.match += 1; },
  };
  vm.runInNewContext(`${read("page-load.js")}\nrefresh = () => { globalThis.refreshed = (globalThis.refreshed || 0) + 1; };`, context);
  const step = async (name) => { await context.watchClosed(); return [name, seen.match, context.refreshed || 0]; };
  const steps = [await step("first"), await step("same")];
  closed = 5;
  steps.push(await step("closed"));
  steps.push(await step("same again"));
  return {steps, requests: [...new Set(seen.requests)]};
};

const music = () => {
  const counts = {starts: 0, stops: 0};
  const param = () => ({value: 0, cancelScheduledValues() {}, setValueAtTime() {}, linearRampToValueAtTime(value) { this.value = value; }});
  const node = (extra) => ({connect: (next) => next, disconnect() {}, ...extra});
  class Audio {
    constructor() { Object.assign(this, {state: "running", currentTime: 0, sampleRate: 10, destination: node({})}); }
    createGain() { return node({gain: param()}); }
    createConvolver() { return node({buffer: null}); }
    createBiquadFilter() { return node({frequency: param(), Q: param(), type: ""}); }
    createOscillator() { return node({frequency: param(), detune: param(), type: "", start: () => { counts.starts += 1; }, stop: () => { counts.stops += 1; }}); }
    createBuffer(channels, length) { return {getChannelData: () => new Float32Array(length)}; }
  }
  const later = [];
  const context = {
    Math, Float32Array, audio: null, settings: {music: {on: true, volume: 1}}, radio: {playing: false},
    music: {gain: null, filter: null, drone: [], timer: 0, tension: 0, ducked: 0}, DUCK: 0.2, FADE: 3000, BASE: 110, CALM: [1], TENSE: [1],
    waitingCount: () => 0, relabel: () => {}, saveSettings: () => {},
    window: {AudioContext: Audio, setTimeout: (fn) => { later.push(fn); return later.length; }, clearTimeout: () => {}},
  };
  vm.runInNewContext(read("page-music.js"), context);
  const step = (name) => ({name, running: Boolean(context.music.gain), ...counts});
  const seen = [];
  context.syncMusic();
  seen.push(step("on"));
  context.radio.playing = true;
  context.tuneMusic(1);
  later.splice(0).forEach((fn) => fn());
  seen.push(step("radio"));
  context.radio.playing = false;
  context.tuneMusic(1);
  seen.push(step("rise"));
  context.settings.music.volume = 0;
  context.tuneMusic(1);
  seen.push(step("silent"));
  return seen;
};

const streamDraws = async () => {
  const list = new El();
  const requests = [];
  let answer = null;
  const entry = (id, text) => ({id, ts: 100, kind: "radio", waiting: false, text});
  const context = {
    El, STREAM_KEEP: 2000,
    stream: {key: null, events: [entry("radio:1", "a")], entries: [], last: 0, sessions: {}, busy: false, again: false, dom: {count: new El(), list}, error: "", tag: ""},
    state: {inbox: []}, ui: {screen: "stream", preset: 0, offline: false}, FEED_LIMIT: 400,
    live: () => true, nowSeconds: () => 200, activeWaiting: () => false, emptyState: () => new El(),
    keepTyping: (_, fn) => fn(), keepScroll: (_, fn) => fn(), h: () => new El(),
    fadeSwap: (box, nodes, around) => (around ? around(box, () => box.replaceChildren(...nodes)) : box.replaceChildren(...nodes)),
    windowKey: () => "w", windowQuery: () => "from=0", filterQuery: () => "kinds=radio",
    fetch: async (url, options) => { requests.push(options.headers["If-None-Match"] || ""); return answer; },
  };
  vm.runInNewContext(`${read("page-stream.js")}\neventRow = () => new El();`, context);
  const draws = [];
  const note = (name) => draws.push([name, list.replaced]);
  context.drawStream(true);
  note("first");
  context.drawStream(true);
  note("same");
  context.drawStream();
  note("forced");
  context.stream.events = [entry("radio:1", "changed")];
  context.drawStream(true);
  note("content");
  const body = {events: [entry("radio:1", "changed")], entries: [], last: 0, sessions: {}};
  answer = {status: 200, ok: true, headers: {get: () => '"t1"'}, json: async () => body};
  await context.fetchEvents();
  note("fetched");
  answer = {status: 304, ok: false, headers: {get: () => '"t1"'}, json: async () => { throw new Error("no body"); }};
  await context.fetchEvents();
  note("not modified");
  return {draws, requests, events: context.stream.events.length, tag: context.stream.tag, offline: context.ui.offline};
};

(async () => {
  results.timers = timers();
  results.music = music();
  results.stream = await streamDraws();
  results.closed = await closedPolls();
  console.log(JSON.stringify(results));
})().catch((error) => { console.error(error && error.stack || error); process.exit(1); });
"""


class TestRegisterCache(HubCase):
    def parses(self, calls: list) -> int:
        return sum(1 for call in calls if call.args[0].name == register.REGISTER)

    def test_two_states_on_an_unchanged_register_parse_it_once(self):
        self.write_council({"rasci.json": REGISTER})
        with mock.patch.object(register, "read_json", wraps=register.read_json) as reader:
            self.snapshot()
            self.snapshot()
            self.assertEqual(self.parses(reader.call_args_list), 1)
            self.write_council({"rasci.json": {**REGISTER, "work/next": {"title": "Next", "status": "queued", "roles": {}}}})
            self.assertIn("work/next", {row["task"] for row in self.snapshot()["tasks"]})
            self.assertEqual(self.parses(reader.call_args_list), 2)

    def test_each_call_gets_its_own_top_level_dict_over_shared_rows(self):
        self.write_council({"rasci.json": REGISTER})
        path = self.council / register.REGISTER
        first, second = register.read_register(path), register.read_register(path)
        self.assertIsNot(first, second)
        self.assertIs(first["work/hub"], second["work/hub"])
        self.assertEqual(register.read_register(self.council / "missing.json"), {})


class TestLiveStateSlots(unittest.TestCase):
    def test_polls_within_the_ttl_share_one_build_and_one_encoding(self):
        live = LiveState(60.0)
        calls: list[int] = []

        def build() -> dict:
            calls.append(1)
            return {"build": len(calls)}

        first = live.encoded("live", build)
        self.assertIs(live.encoded("live", build), first)
        self.assertEqual((len(calls), json.loads(first)), (1, {"build": 1}))
        self.assertEqual(live.shared("live", build), {"build": 1})

    def test_a_slot_rounds_the_window_start_down_to_the_ttl(self):
        self.assertEqual([LiveState(2.0).slot(moment) for moment in (100.0, 101.9, 102.0)], [100.0, 100.0, 102.0])
        self.assertEqual(LiveState(0.0).slot(101.5), 101.5)

    def test_stale_slots_leave_the_cache(self):
        live = LiveState(0.05)
        live.shared(1, dict)
        time.sleep(0.1)
        live.shared(2, dict)
        self.assertEqual((set(live.built), set(live.locks)), ({2}, {2}))


class TestLivePollsRoute(HubCase):
    def live_ttl(self) -> float:
        return 60.0

    def test_polls_whose_start_shares_a_slot_share_one_state(self):
        start = int(time.time()) // 60 * 60 - 3600
        first = self.state_at(f"from={start}")
        self.assertEqual(self.state_at(f"from={start + 30}")["now"], first["now"])
        self.assertGreater(self.state_at(f"from={start - 60}")["now"], first["now"])
        self.assertGreater(self.state_at(f"from={start}&to={int(first['now'])}")["now"], first["now"])

    def test_a_window_start_after_now_is_refused(self):
        self.assertEqual(self.get(f"/api/state?from={int(time.time()) + 3600}")[0], 400)

    def state_at(self, query: str) -> dict:
        status, headers, body = self.get(f"/api/state?{query}")
        self.assertEqual((status, headers["content-type"]), (200, "application/json"), body)
        return json.loads(body)


class TestClosedCount(HubCase):
    def closed(self) -> tuple[int, int]:
        status, _, body = self.get("/api/match/closed")
        self.assertEqual(status, 200, body)
        return json.loads(body)["closed"], len(body)

    def test_the_closed_count_moves_once_per_closed_card_and_builds_neither_the_state_nor_a_card(self):
        closer = {"closer": "a" * 43}
        self.create_ask({**ASK, **closer})
        self.create_ask({**ASK, "session": "s2", **closer})
        hub = type(self.httpd.hub)
        with mock.patch.object(hub, "built", side_effect=AssertionError("state built")), mock.patch.object(hub, "match_cards", side_effect=AssertionError("cards built")):
            before, size = self.closed()
            self.assertLess(size, 64)
            self.assertEqual(self.closed()[0], before)
            status, _, body = self.post_json("/api/asks/ran", {"event": "SessionEnd", "session": "s1", **closer}, self.local())
            self.assertEqual(status, 200, body)
            self.assertEqual(self.closed()[0], before + 1)
        self.assertEqual(self.post_json("/api/match/closed", {}, self.local())[0], 404)


class TestEventsTag(HubCase):
    def tagged(self, tag: str) -> tuple[int, dict, bytes]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        try:
            connection.request("GET", "/api/events?kinds=radio", headers={"Host": self.host, "If-None-Match": tag})
            response = connection.getresponse()
            return response.status, {name.lower(): value for name, value in response.getheaders()}, response.read()
        finally:
            connection.close()

    def test_the_current_tag_answers_304_without_a_body_and_a_change_answers_200(self):
        now = time.time()
        self.write_council({"news.jsonl": self.jsonl([{"ts": now - 10, "from": "One", "to": [], "text": "first"}])})
        status, headers, body = self.get("/api/events?kinds=radio")
        self.assertEqual(status, 200, body)
        tag = headers["etag"]
        self.assertRegex(tag, r'^"[0-9a-f]{32}"$')
        status, headers, body = self.tagged(tag)
        self.assertEqual((status, body, headers["etag"]), (304, b"", tag))
        self.assertEqual(self.tagged('"other"')[0], 200)
        self.write_council({"news.jsonl": self.jsonl([{"ts": now - 10, "from": "One", "to": [], "text": "first"}, {"ts": now - 5, "from": "Two", "to": [], "text": "second"}])})
        status, headers, body = self.tagged(tag)
        self.assertEqual(status, 200, body)
        self.assertNotEqual(headers["etag"], tag)
        self.assertEqual([row["text"] for row in json.loads(body)["events"]], ["first", "second"])


class TestPagePolls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        done = subprocess.run(["node", "-e", PROBE, str(TEMPLATES)], capture_output=True, text=True, timeout=60, check=False)
        if done.returncode != 0:
            raise AssertionError(done.stderr[-4000:])
        cls.data = json.loads(done.stdout)

    def test_a_hidden_tab_draws_no_sky_and_no_relayout_and_showing_it_lays_out_once(self):
        found = self.data["timers"]
        self.assertEqual((found["hidden"]["sky"], found["hidden"]["relayout"]), (0, 0), found)
        self.assertEqual(found["hidden"]["radio"], 3, found)
        self.assertEqual((found["shown"]["sky"], found["shown"]["relayout"], found["shown"]["radio"]), (0, 1, 4), found)
        self.assertEqual((found["after"]["sky"], found["after"]["relayout"], found["after"]["radio"]), (0, 1, 5), found)

    def test_the_closed_card_poll_runs_every_2_s_only_while_the_tab_is_shown(self):
        found = self.data["timers"]
        self.assertEqual((found["hidden"]["closed"], found["shown"]["closed"], found["watched"]["closed"], found["after"]["closed"]), (0, 0, 5, 5), found)

    def test_a_moved_closed_count_fetches_match_and_the_state_once_and_the_first_read_or_an_unchanged_one_nothing(self):
        found = self.data["closed"]
        self.assertEqual(found["steps"], [["first", 0, 0], ["same", 0, 0], ["closed", 1, 1], ["same again", 1, 1]], found)
        self.assertEqual(found["requests"], ["/api/match/closed"], found)

    def test_music_level_zero_stops_the_graph_and_a_rise_restarts_it(self):
        steps = {step["name"]: step for step in self.data["music"]}
        self.assertTrue(steps["on"]["running"], steps)
        self.assertEqual((steps["radio"]["running"], steps["radio"]["stops"]), (False, steps["on"]["starts"]), steps)
        self.assertTrue(steps["rise"]["running"], steps)
        self.assertGreater(steps["rise"]["starts"], steps["on"]["starts"], steps)
        self.assertFalse(steps["silent"]["running"], steps)

    def test_a_poll_with_unchanged_rows_replaces_none(self):
        found = self.data["stream"]
        self.assertEqual(found["draws"], [["first", 1], ["same", 1], ["forced", 2], ["content", 3], ["fetched", 3], ["not modified", 3]], found)
        self.assertEqual(found["requests"], ["", '"t1"'], found)
        self.assertEqual((found["events"], found["tag"], found["offline"]), (1, '"t1"', False), found)


if __name__ == "__main__":
    unittest.main()
