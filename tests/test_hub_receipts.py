from __future__ import annotations

import contextlib
import dataclasses
import io
import json
import os
import subprocess
import tempfile
import threading
import time
import types
import unittest
from collections.abc import Callable
from pathlib import Path
from unittest import mock

import hub_support  # noqa: F401
from hub_case import HubCase
from kvb_orchestrator import (
    choosing,
    council,
    hub,
    messaging,
    receipts,
    records,
    skill_scripts,
)
from kvb_orchestrator.names import Directory
from kvb_orchestrator.presence import SNAPSHOT, SNAPSHOT_STALE
from kvb_orchestrator.view import RADIO_WINDOW

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = REPO_ROOT / "orchestrator" / "templates"
NOW = 1_800_000_000.0
T = NOW - 1000
EARLY = T - 100
WINDOW = (T, T + 100)
PAGE_PROBE = """
const fs = require("fs");
const vm = require("vm");
const Receipts = require(process.argv[1]);
const RadioSet = require(process.argv[2]);
const code = ["page-dom.js", "page-stream.js", "page-radioview.js", "page-agent.js"].map((name) => fs.readFileSync(`${process.argv[3]}/${name}`, "utf8")).join("\\n");
const input = JSON.parse(process.argv[4]);
class Node {
  constructor(tag) {
    Object.assign(this, {tag, attrs: {}, children: []});
  }
  setAttribute(key, value) {
    this.attrs[key] = value;
  }
  addEventListener() {}
  append(child) {
    this.children.push(child);
  }
}
const text = (node) => (typeof node === "string" ? node : node.children.map(text).join(""));
const find = (node, test, out = []) => {
  if (typeof node !== "string") {
    if (test(node)) {
      out.push(node);
    }
    node.children.forEach((child) => find(child, test, out));
  }
  return out;
};
const sandbox = {
  Receipts, RadioSet, Node, NS: "svg", HUMAN: "Operator", DAY: 86400, WEEKDAYS: [], revealed: String,
  document: {createElement: (tag) => new Node(tag), createElementNS: (ns, tag) => new Node(tag)},
  relative: {format: () => "ago"}, absolute: {format: (date) => `at ${date.getTime() / 1000}`},
  Faces: {of: () => ({parts: []}), SIZE: 10}, speech: {current: null}, look: {hidden: new Set()}, PRESENCE: {}, STATUS: {},
  state: {inbox: [], messages: [], radio: [], people: input.people}, CLASSES: {call: "Call", receipt: "Read"}, PILLS: {call: "info"}, ui: {}, KINDS: [["review", "Reviews"]], KIND_TONES: {},
};
vm.runInNewContext(`${code}\\nglobalThis.probe = {eventRow, logLine, history, readerRow};`, sandbox);
const shape = (node) => ({
  route: text(find(node, (item) => item.attrs.class === "route")[0] || {children: []}),
  routes: find(node, (item) => item.attrs.class === "radio-route").map(text),
  readers: find(node, (item) => item.attrs.class === "reader").map((item) => ({
    session: item.attrs["data-session"], acked: item.attrs["data-acked"], title: item.attrs.title, label: item.attrs["aria-label"],
    badges: find(item, (part) => part.attrs.class === "ack").length, face: find(item, (part) => part.attrs["data-face"] !== undefined).map((part) => part.attrs["data-face"]),
  })),
  more: find(node, (item) => item.attrs.class === "readers-more").map((item) => ({text: text(item), title: item.attrs.title})),
  groups: find(node, (item) => item.attrs.class === "readers").map((item) => item.attrs["aria-label"]),
});
console.log(JSON.stringify({
  events: input.events.map((entry) => shape(sandbox.probe.eventRow(entry))),
  logs: input.logs.map((row) => shape(sandbox.probe.logLine(row))),
  module: {
    strip: input.strips.map((row) => Receipts.strip(row)),
    labels: input.labels.map((reader) => Receipts.label(reader, (ts) => `t${ts}`)),
    headlines: input.events.map((entry) => Receipts.headline(entry)),
    signatures: input.signatures.map((rows) => Receipts.signature(rows)),
  },
  agent: (() => {
    Object.assign(sandbox.state, input.agent.state);
    const sent = RadioSet.logRows(sandbox.state.radio, {tab: "sent", chips: {class: "", from: "", to: "", agent: ""}, q: ""}, "Operator", sandbox.state.messages);
    return {
      history: sandbox.probe.history(input.agent.key).map((row) => ({who: row.who, text: row.text, ...shape(sandbox.probe.readerRow(row) || new Node("none"))})),
      sent: sent.map((row) => ({text: row.text, ...shape(sandbox.probe.logLine(row))})),
    };
  })(),
}));
"""


def message(cls: str, ts: float, to: list[str], sender: str = "One") -> dict:
    return {"ts": ts, "from": sender, "to": to, "text": cls, "class": cls, "v": 2}


def receipt(reader: str, ts: float, call: object) -> dict:
    return {"ts": ts, "from": reader, "to": ["One"], "text": "c", "class": "receipt", "v": 2, "call": call}


def directory(*held: tuple[str, str, float]) -> Directory:
    return Directory([{"session": sid, "name": name, "first_seen": since, "source": "claim"} for sid, name, since in held])


def who(entry: dict) -> list[tuple[str, float | None]]:
    return [(reader["session"], reader["read"]) for reader in entry["readers"]]


NAMED = directory(("s1", "One", EARLY), ("s2", "Two", EARLY), ("s3", "Three", EARLY))


class TestReceipts(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.council = self.base / "council"
        (self.council / receipts.SEEN).mkdir(parents=True)
        (self.council / receipts.PROMPT).mkdir()
        with mock.patch.dict(os.environ, {"AGENTS_COUNCIL_ROOT": str(self.council)}):
            self.radio = receipts.radio_module(REPO_ROOT / "skills")
        self.assertIsNotNone(self.radio)

    def state(self, sid: str, text: str) -> None:
        (self.council / receipts.SEEN / f"{sid}.json").write_text(text, encoding="utf-8")

    def prompt(self, sid: str, text: str) -> None:
        (self.council / receipts.PROMPT / sid).write_text(text, encoding="utf-8")

    def inline(self, news: list[dict], names: Directory, window: tuple[float, float] = WINDOW, sighted: dict | None = None) -> dict[float, dict]:
        return receipts.readers_and_acks(self.radio, news, window, receipts.read_marks(self.council, NOW), names, sighted or {})

    def test_every_class_gets_its_readers_by_channel_and_its_acks_from_receipts(self):
        news = [
            message("post", T + 1, ["Two"]),
            message("call", T + 2, ["Two", "Three"]),
            message("newsletter", T + 3, []),
            message("broadcast", T + 4, []),
            message("mayday", T + 5, []),
            message("pan-pan", T + 6, []),
            message("security", T + 7, []),
            receipt("Two", T + 8, T + 2),
            receipt("Three", T + 500, T + 2),
        ]
        self.state("s1", json.dumps({"radio": T + 600, "mail": T + 600}))
        self.state("s2", json.dumps({"radio": T + 7, "mail": T + 3, "mtime": T + 900}))
        self.state("s3", json.dumps({"radio": T + 600}))
        self.prompt("s4", str(T + 4))
        found = self.inline(news, NAMED)
        self.assertEqual(sorted(found), [T + n for n in range(1, 8)])
        self.assertEqual({ts: (who(entry), entry["acks"]) for ts, entry in found.items()}, {
            T + 1: ([("s2", None)], []),
            T + 2: ([("s2", T + 8), ("s3", T + 500)], ["s2", "s3"]),
            T + 3: ([("s2", None), ("s4", None)], []),
            T + 4: ([("s3", None), ("s2", None), ("s4", None)], []),
            T + 5: ([("s3", None), ("s2", None)], []),
            T + 6: ([("s3", None), ("s2", None)], []),
            T + 7: ([("s3", None), ("s2", None)], []),
        })
        self.assertEqual(found[T + 3]["readers"], [{"session": "s2", "name": "Two", "read": None, "approximate": False}, {"session": "s4", "name": "s4", "read": None, "approximate": False}])

    def test_an_ended_session_keeps_its_read_its_ack_and_its_own_broadcast_by_its_name_history(self):
        news = [message("call", T + 10, ["Two"]), receipt("Two", T + 11, T + 10), message("broadcast", T + 20, [])]
        self.state("s1", json.dumps({"radio": T + 50}))
        self.state("s2", json.dumps({"radio": T + 50}))
        found = self.inline(news, directory(("s1", "One", EARLY), ("s2", "Two", EARLY)))
        self.assertEqual((who(found[T + 10]), found[T + 10]["acks"]), ([("s2", T + 11)], ["s2"]))
        self.assertEqual((who(found[T + 20]), found[T + 20]["acks"]), ([("s2", None)], []))

    def test_a_renamed_name_goes_to_the_session_holding_it_at_the_time(self):
        news = [
            message("call", T + 10, ["Two"]),
            receipt("Two", T + 11, T + 10),
            message("call", T + 60, ["Two"]),
            receipt("Two", T + 61, T + 60),
        ]
        self.state("s2", json.dumps({"radio": T + 70}))
        self.state("s5", json.dumps({"radio": T + 70}))
        found = self.inline(news, directory(("s2", "Two", EARLY), ("s2", "Deux", T + 50), ("s5", "Two", T + 55)))
        self.assertEqual((who(found[T + 10]), found[T + 10]["acks"]), ([("s2", T + 11), ("s5", None)], ["s2"]))
        self.assertEqual((who(found[T + 60]), found[T + 60]["acks"]), ([("s5", T + 61)], ["s5"]))
        self.assertEqual([reader["name"] for reader in found[T + 10]["readers"]], ["Two", "Two"])

    def test_receipt_names_come_from_the_host_snapshot_alone_and_outlive_the_session(self):
        file = self.base / "receipt-names.json"
        forged = [{"session": "sA", "name": "Two", "first_seen": EARLY, "source": "claim"}, {"session": "s2", "name": "Ghost", "first_seen": T + 5, "source": "claim"}]
        file.write_text(json.dumps({"entries": forged, "observed": {}}), encoding="utf-8")
        live = receipts.session_directory(receipts.ReceiptNames(file), {"s2": {"name": "Two"}, "s3": {"name": {"x": 1}}, "s4": {}}, EARLY)
        ended = receipts.session_directory(receipts.ReceiptNames(file), {}, T + 50)
        for names in (live, ended):
            with self.subTest(names=names):
                self.assertEqual((names.aliases("Two"), names.at("s2", T + 10), names.at("s3", T), names.aliases("Ghost")), ({"s2"}, "Two", "", set()))
        news = [message("call", T + 10, ["Two"]), receipt("Two", T + 11, T + 10)]
        self.state("s2", json.dumps({"radio": T + 20}))
        self.state("sA", json.dumps({"radio": T + 20}))
        found = self.inline(news, ended)
        self.assertEqual((who(found[T + 10]), found[T + 10]["acks"]), ([("s2", T + 11)], ["s2"]))

    def test_snapshot_names_match_rows_and_receipts_unnormalized_as_radio_does(self):
        names = receipts.session_directory(receipts.ReceiptNames(self.base / "raw.json"), {"s2": {"name": "Two session"}}, EARLY)
        news = [message("call", T + 10, ["Two session"]), receipt("Two session", T + 11, T + 10), message("call", T + 20, ["Two"]), receipt("Two", T + 21, T + 20)]
        self.state("s2", json.dumps({"radio": T + 30}))
        found = self.inline(news, names)
        self.assertEqual((who(found[T + 10]), found[T + 10]["acks"]), ([("s2", T + 11)], ["s2"]))
        self.assertEqual((who(found[T + 20]), found[T + 20]["acks"]), ([], []))

    def test_a_reader_reads_at_its_receipt_else_about_at_its_first_sighting_and_never_at_a_mark(self):
        news = [message("mayday", T + 10, []), message("call", T + 20, ["Two"]), receipt("Two", T + 21, T + 20), message("post", T + 30, ["Two"]), message("newsletter", T + 40, [])]
        self.state("s2", json.dumps({"radio": T + 90, "mail": T + 35}))
        self.prompt("s2", str(T + 50))
        found = self.inline(news, NAMED, sighted={("s2", T + 10): NOW - 5, ("s2", T + 20): NOW - 1, ("s2", T + 30): None, ("s3", T + 40): NOW})
        readers = [found[T + n]["readers"] for n in (10, 20, 30, 40)]
        self.assertEqual([[(entry["read"], entry["approximate"]) for entry in row] for row in readers], [[(NOW - 5, True)], [(T + 21, False)], [(None, False)], [(None, False)]])
        self.state("s2", json.dumps({"mail": T + 35}))
        self.prompt("s2", "")
        self.assertEqual([who(self.inline(news, NAMED)[T + n]) for n in (10, 30, 40)], [[], [("s2", None)], []])
        reader = receipts.reader(self.radio, message("post", T + 30, ["Two"]), "s2", "Two", (None, {"radio": T + 90}), {}, {("s2", T + 30): NOW})
        self.assertIsNone(reader)
        spy = types.SimpleNamespace(**{**vars(self.radio), "seen": lambda *args: True})
        self.assertEqual(receipts.reader(spy, message("post", T + 30, ["Two"]), "s2", "Two", (T + 99, {"mail": T + 99}), {}, {})["read"], None)

    def test_a_missing_malformed_unreadable_oversized_or_future_mark_counts_as_not_read(self):
        news = [message("broadcast", T + 4, [])]
        outside = self.base / "outside.json"
        outside.write_text(json.dumps({"radio": NOW}), encoding="utf-8")
        for sid, text in (
            ("text", json.dumps({"radio": str(NOW)})),
            ("flag", json.dumps({"radio": True})),
            ("nan", '{"radio": NaN}'),
            ("inf", '{"radio": Infinity}'),
            ("huge", json.dumps({"radio": 1e300})),
            ("negative", json.dumps({"radio": -5})),
            ("future", json.dumps({"radio": NOW + 60})),
            ("list", json.dumps([NOW])),
            ("broken", '{"radio": '),
            ("empty", ""),
            ("deep", "[" * receipts.STATE_BYTES),
            ("oversized", json.dumps({"radio": NOW}) + " " * receipts.STATE_BYTES),
            ("good", json.dumps({"radio": NOW}) + " " * (receipts.STATE_BYTES - 30)),
        ):
            self.state(sid, text)
        (self.council / receipts.SEEN / "link.json").symlink_to(outside)
        (self.council / receipts.SEEN / "folder.json").mkdir()
        os.mkfifo(self.council / receipts.SEEN / "fifo.json")
        for sid, text in (
            ("p-text", "soon"),
            ("p-future", str(NOW + 60)),
            ("p-nan", "nan"),
            ("p-large", " " * receipts.PROMPT_BYTES + str(NOW)),
            ("p-good", f" {NOW}\n"),
        ):
            self.prompt(sid, text)
        (self.council / receipts.PROMPT / "p-link").symlink_to(self.council / receipts.PROMPT / "p-good")
        marks = receipts.read_marks(self.council, NOW)
        bad = sorted(set(marks) - {"good", "p-good"})
        self.assertEqual(bad, sorted([
            "text", "flag", "nan", "inf", "huge", "negative", "future", "list", "broken", "empty", "deep", "oversized",
            "link", "folder", "fifo", "p-text", "p-future", "p-nan", "p-large", "p-link",
        ]))
        for sid in bad:
            with self.subTest(sid=sid):
                self.assertEqual(marks[sid], (None, {}))
        self.assertEqual((marks["good"], marks["p-good"]), ((None, {"radio": NOW}), (NOW, {})))
        found = receipts.readers_and_acks(self.radio, news, WINDOW, marks, directory(), {})
        self.assertEqual(who(found[T + 4]), [("good", None), ("p-good", None)])

    def test_marks_are_parsed_again_only_after_the_file_changed(self):
        self.state("s2", json.dumps({"radio": T}))
        with mock.patch.object(receipts, "read_regular", wraps=receipts.read_regular) as reads:
            first = receipts.read_marks(self.council, NOW)
            again = receipts.read_marks(self.council, NOW)
            fresh = self.council / receipts.SEEN / "s2.json.new"
            fresh.write_text(json.dumps({"radio": T + 5}), encoding="utf-8")
            os.replace(fresh, self.council / receipts.SEEN / "s2.json")
            changed = receipts.read_marks(self.council, NOW)
        self.assertEqual([marks["s2"] for marks in (first, again, changed)], [(None, {"radio": T}), (None, {"radio": T}), (None, {"radio": T + 5})])
        self.assertEqual(reads.call_count, 2)
        self.assertEqual(receipts.read_marks(self.council, T + 1), {"s2": (None, {})})

    def test_a_receipt_acks_only_the_call_whose_time_it_carries(self):
        first, second = T + 10, T + 20
        news = [
            message("call", first, ["Two"]),
            message("call", second, ["Two"]),
            receipt("Two", T + 11, first),
            receipt("Two", T + 12, first),
            receipt("Two", T + 21, second + 1e-6),
            receipt("Two", T + 22, str(second)),
            receipt("Two", T + 23, True),
            receipt("s3", T + 24, second),
            receipt("Nobody", T + 25, second),
            {**receipt("Two", T + 26, second), "from": ["Two"]},
        ]
        self.state("s2", json.dumps({"radio": T + 30}))
        self.state("s3", json.dumps({"radio": T + 10}))
        found = self.inline(news, directory(("s2", "Two", EARLY)))
        self.assertEqual((who(found[first]), found[first]["acks"]), ([("s2", T + 11)], ["s2"]))
        self.assertEqual((who(found[second]), found[second]["acks"]), ([("s2", None)], ["s3"]))

    def test_a_receipt_outside_the_window_still_acks_its_call_and_no_receipt_row_is_served(self):
        call = T + 10
        news = [message("call", call, ["Two"]), receipt("Two", T + 400, call), message("call", T + 200, ["Two"])]
        self.state("s2", json.dumps({"radio": T + 300}))
        found = self.inline(news, NAMED, (T, T + 15))
        self.assertEqual(list(found), [call])
        self.assertEqual((who(found[call]), found[call]["acks"]), ([("s2", T + 400)], ["s2"]))
        self.assertEqual(list(self.inline(news, NAMED, (T + 300, T + 500))), [])

    def test_the_hub_decides_by_radio_seen_without_a_delivery_window(self):
        calls = []

        def seen(*args):
            calls.append(args)
            return False

        spy = types.SimpleNamespace(**{**vars(self.radio), "seen": seen})
        news = [message("broadcast", T + 4, [])]
        self.state("s2", json.dumps({"radio": NOW}))
        found = receipts.readers_and_acks(spy, news, WINDOW, receipts.read_marks(self.council, NOW), NAMED, {})
        self.assertEqual(found, {T + 4: {"readers": [], "acks": []}})
        self.assertEqual(calls, [(news[0], "Two", "s2", self.radio.NEVER, {"radio": NOW}, self.radio.NEVER)])

    def test_a_row_pinned_to_a_session_reaches_it_under_any_name(self):
        news = [{**message("call", T + 10, ["Old"]), "to_sessions": ["s2"]}]
        self.state("s2", json.dumps({"radio": T + 20}))
        self.assertEqual(who(self.inline(news, NAMED)[T + 10]), [("s2", None)])

    def test_rows_without_a_usable_time_and_sessions_without_a_name(self):
        news = [{**message("broadcast", T + 4, []), "ts": "x"}, {**message("broadcast", T + 5, []), "ts": True}, message("call", T + 6, ["s9"])]
        self.state("s9", json.dumps({"radio": NOW}))
        found = self.inline(news, directory())
        self.assertEqual(list(found), [T + 6])
        self.assertEqual(found[T + 6]["readers"], [{"session": "s9", "name": "s9", "read": None, "approximate": False}])

    def test_read_marks_without_mark_folders_is_empty(self):
        self.assertEqual(receipts.read_marks(self.base / "missing", NOW), {})

    def test_the_radio_module_needs_an_installed_radio_whose_seen_takes_the_hubs_arguments(self):
        self.assertIsNone(receipts.radio_module(self.base / "none"))
        fake = self.base / "skills" / "kvb-org-radio" / "scripts"
        fake.mkdir(parents=True)
        for version, text, loads in (
            (2, "SEEN = 1\n", False),
            (3, "def seen(\n", False),
            (4, "def seen(row, name, prompt, state, since):\n    return True\n", False),
            (5, "def seen(row, name, sid, state, prompt, since):\n    return True\n", False),
            (6, "def seen(row, name, sid, prompt, state, since):\n    return True\n", True),
        ):
            (fake / "radio.py").write_text(text, encoding="utf-8")
            os.utime(fake / "radio.py", (1, version))
            with self.subTest(text=text):
                self.assertEqual(receipts.radio_module(self.base / "skills") is not None, loads)
        self.assertEqual(tuple(receipts.inspect.signature(self.radio.seen).parameters), receipts.SEEN_PARAMETERS)


class TestReceiptNames(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.file = Path(tmp.name) / receipts.NAMES

    def sessions(self, store: receipts.ReceiptNames) -> set[str]:
        return {entry["session"] for entry in store.entries}

    def test_a_session_gone_longer_than_kept_loses_its_entries_and_comes_back_when_sighted_again(self):
        store = receipts.ReceiptNames(self.file)
        receipts.session_directory(store, {"s1": {"name": "One"}, "s2": {"name": "Two"}}, NOW)
        receipts.session_directory(store, {"s1": {"name": "One"}}, NOW + receipts.KEPT)
        self.assertEqual(self.sessions(store), {"s1", "s2"})
        names = receipts.session_directory(store, {"s1": {"name": "One"}}, NOW + receipts.KEPT + 1)
        self.assertEqual((self.sessions(store), names.aliases("Two")), ({"s1"}, set()))
        again = receipts.ReceiptNames(self.file)
        self.assertEqual((self.sessions(again), set(again.observed), again.sighted), ({"s1"}, {"s1\x00session"}, {"s1": NOW + receipts.KEPT}))
        receipts.session_directory(again, {"s2": {"name": "Two"}}, NOW + receipts.KEPT + 2)
        self.assertEqual(self.sessions(again), {"s1", "s2"})

    def test_a_sighting_is_stored_at_most_every_step(self):
        store = receipts.ReceiptNames(self.file)
        receipts.session_directory(store, {"s1": {"name": "One"}}, NOW)
        with mock.patch.object(store, "save", wraps=store.save) as saves:
            receipts.session_directory(store, {"s1": {"name": "One"}}, NOW + receipts.STEP - 1)
            self.assertEqual((saves.call_count, store.sighted), (0, {"s1": NOW}))
            receipts.session_directory(store, {"s1": {"name": "One"}}, NOW + receipts.STEP)
        self.assertEqual((saves.call_count, store.sighted), (1, {"s1": NOW + receipts.STEP}))

    def test_past_the_entry_cap_the_sessions_sighted_longest_ago_go_first_and_the_file_stays_readable(self):
        with mock.patch.object(receipts, "ENTRIES", 3):
            store = receipts.ReceiptNames(self.file)
            for n in range(5):
                receipts.session_directory(store, {f"s{n}": {"name": f"N{n}"}}, NOW + n)
        self.assertEqual(self.sessions(store), {"s2", "s3", "s4"})
        crowd = {f"{n:0128d}": {"name": "N" * receipts.NAME_CHARS} for n in range(receipts.ENTRIES + 500)}
        store = receipts.ReceiptNames(self.file)
        receipts.session_directory(store, {**crowd, "long": {"name": "N" * (receipts.NAME_CHARS + 1)}}, NOW + 10)
        self.assertEqual(len(store.entries), receipts.ENTRIES)
        self.assertNotIn("long", self.sessions(store))
        self.assertLess(self.file.stat().st_size, records.JSON_LIMIT // 2)
        self.assertEqual(len(receipts.ReceiptNames(self.file).entries), receipts.ENTRIES)

    def test_a_store_with_malformed_values_keeps_only_its_valid_entries(self):
        good = {"session": "s1", "name": "One", "first_seen": EARLY, "source": "session"}
        self.file.write_text(json.dumps({
            "entries": [
                good, {**good, "session": 7}, {**good, "session": ""}, {**good, "name": ["One"]}, {**good, "first_seen": "soon"},
                {**good, "first_seen": True}, {**good, "first_seen": float("nan")}, {**good, "source": None}, {**good, "extra": 1}, "junk",
                {**good, "session": "bad id!"}, {**good, "session": "s" * 129}, {**good, "name": "N" * (receipts.NAME_CHARS + 1)},
            ],
            "observed": {"s1\x00session": "One", "s2\x00session": ["Two"], "bad id!\x00session": "X", "s4\x00session": "N" * (receipts.NAME_CHARS + 1)},
            "sighted": {"s1": T + 1e6, "s2": "x", "s3": None, "bad id!": EARLY},
        }), encoding="utf-8")
        store = receipts.ReceiptNames(self.file)
        self.assertEqual((store.entries, store.observed, store.sighted), ([good], {"s1\x00session": "One"}, {"s1": T + 1e6}))
        names = receipts.session_directory(store, {"s2": {"name": "Two"}, "bad id!": {"name": "X"}, "s3": {"name": 3}}, T)
        self.assertEqual((names.at("s1", T), names.at("s2", T), names.aliases("X"), names.at("s3", T)), ("One", "Two", set(), ""))
        self.assertEqual((store.sighted["s1"], receipts.ReceiptNames(self.file).sighted["s1"]), (T, T))
        self.file.write_text(json.dumps(["not", "a", "store"]), encoding="utf-8")
        self.assertEqual(receipts.ReceiptNames(self.file).payload(), {"entries": [], "observed": {}, "sighted": {}})


class TestReceiptReads(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.file = Path(tmp.name) / receipts.READS

    def test_rows_covered_at_the_first_pass_of_a_process_keep_no_time_and_later_ones_their_first_sighting_across_restarts(self):
        reads = receipts.ReceiptReads(self.file)
        reads.see({("s2", T + 1)}, NOW, T, True)
        reads.see({("s2", T + 1), ("s2", T + 2)}, NOW + 15, T, True)
        reads.see({("s2", T + 1), ("s2", T + 2)}, NOW + 30, T, True)
        self.assertEqual(reads.listed(NOW + 99), {("s2", T + 1): None, ("s2", T + 2): NOW + 15})
        again = receipts.ReceiptReads(self.file)
        self.assertEqual(again.listed(NOW + 99), reads.listed(NOW + 99))
        again.see({("s2", T + 2), ("s3", T + 2)}, NOW + 45, T + 2, True)
        again.see({("s4", T + 3), ("s5", T + 1)}, NOW + 60, T + 2, True)
        self.assertEqual(again.listed(NOW + 99), {("s2", T + 2): NOW + 15, ("s3", T + 2): None, ("s4", T + 3): NOW + 60})
        self.assertEqual(json.loads(self.file.read_text(encoding="utf-8")), {"reads": [["s2", T + 2, NOW + 15], ["s3", T + 2, None], ["s4", T + 3, NOW + 60]]})

    def test_the_baseline_waits_for_a_pass_with_a_fresh_snapshot_and_comes_back_after_a_stale_one(self):
        reads = receipts.ReceiptReads(self.file)
        covered: set[tuple[str, float]] = set()
        for n, fresh in enumerate((False, False, True, True, False, True, True)):
            covered.add(("s7", T + n))
            reads.see(set(covered), NOW + 15 * n, T, fresh)
        self.assertEqual(reads.listed(NOW + 999), {
            ("s7", T): None, ("s7", T + 1): None, ("s7", T + 2): None, ("s7", T + 3): NOW + 45,
            ("s7", T + 4): NOW + 60, ("s7", T + 5): None, ("s7", T + 6): NOW + 90,
        })

    def test_a_pass_after_a_gap_longer_than_two_sighting_intervals_stamps_nothing(self):
        reads = receipts.ReceiptReads(self.file)
        moments = (NOW, NOW + 2 * receipts.SIGHTING, NOW + 2 * receipts.SIGHTING + 3600, NOW + 3 * receipts.SIGHTING + 3600)
        for n, now in enumerate(moments):
            reads.see({("s7", T + k) for k in range(n + 1)}, now, T, True)
        self.assertEqual(reads.listed(NOW + 9999), {("s7", T): None, ("s7", T + 1): moments[1], ("s7", T + 2): None, ("s7", T + 3): moments[3]})

    def test_past_the_entry_cap_the_oldest_rows_go_whole_and_never_come_back_with_a_later_time(self):
        pairs = {("a", T + 1), ("b", T + 2), ("c", T + 2), ("d", T + 3), ("e", T + 4)}
        with mock.patch.object(receipts, "READ_ENTRIES", 3):
            reads = receipts.ReceiptReads(self.file)
            reads.see(set(), NOW, T, True)
            reads.see(pairs, NOW + 15, T, True)
            reads.see(pairs, NOW + 30, T, True)
        self.assertEqual(reads.listed(NOW + 99), {("d", T + 3): NOW + 15, ("e", T + 4): NOW + 15})

    def test_a_store_with_malformed_values_keeps_only_its_valid_entries_and_clamps_a_future_sighting(self):
        self.file.write_text(json.dumps({"reads": [
            ["s1", T, T + 5], ["s1", T + 1, None], ["bad id!", T, T], ["s2", "x", T], ["s3", T, "soon"], ["s4", T, 9e10],
            ["s5", T], ["s6", True, T], ["s7", T, True], [7, T, T], "junk", ["s8", T, T - 1], ["s9", T, T],
        ]}), encoding="utf-8")
        reads = receipts.ReceiptReads(self.file)
        self.assertEqual(reads.listed(NOW), {("s1", T): T + 5, ("s1", T + 1): None, ("s4", T): NOW, ("s9", T): T})
        reads.see(set(), NOW, T, True)
        self.assertEqual(receipts.ReceiptReads(self.file).listed(9e10), {("s1", T): T + 5, ("s1", T + 1): None, ("s4", T): NOW, ("s9", T): T})
        self.file.write_text(json.dumps(["not", "a", "store"]), encoding="utf-8")
        self.assertEqual(receipts.ReceiptReads(self.file).listed(NOW), {})


class TestRadioRun(unittest.TestCase):
    def test_a_run_killed_at_the_timeout_returns_the_ts_line_it_printed_before(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        script = base / "skills" / skill_scripts.RADIO
        script.parent.mkdir(parents=True)
        script.write_text("import sys, time\nprint('ts: 1800000000.5', flush=True)\ntime.sleep(30)\n", encoding="utf-8")
        with mock.patch.object(skill_scripts, "SCRIPT_TIMEOUT", 1):
            run = skill_scripts.Scripts(base / "skills", base / "council", base).run(skill_scripts.RADIO, ["send", "call"])
        self.assertEqual((run["code"], run["stdout"], messaging.stored_ts(run["stdout"])), (-1, "ts: 1800000000.5\n", 1800000000.5))


class TestServedReceipts(HubCase):
    def setUp(self):
        super().setUp()
        self.now = time.time()
        self.t = self.now - 600

    def sessions(self, records: dict[str, str], written: float | None = None) -> None:
        payload = {"written": time.time() if written is None else written, "sessions": {sid: {"name": name, "running": True} for sid, name in records.items()}}
        (self.state / SNAPSHOT).write_text(json.dumps(payload), encoding="utf-8")

    def marks(self, marks: dict[str, dict]) -> None:
        self.write_council({f"{receipts.SEEN}/{sid}.json": mark for sid, mark in marks.items()})

    def fixture(self) -> None:
        t = self.t
        self.sessions({"s1": "One", "s2": "Two", "s3": "Three"})
        self.write_council({"news.jsonl": self.jsonl([
            message("post", t + 1, ["Two"]),
            message("call", t + 2, ["Two", "Three"]),
            message("broadcast", t + 3, []),
            receipt("Two", t + 4, t + 2),
            receipt("Three", t + 5, t + 2),
        ])})
        self.marks({"s2": {"radio": t + 10, "mail": t + 10}, "s3": {"radio": t + 10}})

    def served(self, rows: list[dict]) -> dict[float, tuple]:
        return {row["ts"]: ([(reader["session"], reader["name"], reader["read"]) for reader in row["readers"]], row["acks"]) for row in rows}

    def test_the_state_carries_readers_and_acks_per_message_and_serves_no_receipt_row(self):
        self.fixture()
        t = self.t
        state = self.snapshot()
        self.assertEqual([row["class"] for row in state["radio"]], ["post", "call", "broadcast"])
        self.assertEqual(self.served(state["radio"]), {
            t + 1: ([("s2", "Two", None)], []),
            t + 2: ([("s2", "Two", t + 4), ("s3", "Three", t + 5)], ["s2", "s3"]),
            t + 3: ([("s3", "Three", None), ("s2", "Two", None)], []),
        })
        self.assertNotIn(council.RECEIPT, {edge["class"] for edge in state["graph"]["edges"]})
        self.assertIn("const Receipts = ", self.index())
        status, _, body = self.get(f"/api/state?from={t!r}&to={t + 3!r}")
        self.assertEqual(status, 200, body)
        narrowed = json.loads(body)["radio"]
        self.assertEqual(self.served(narrowed)[t + 2], ([("s2", "Two", t + 4), ("s3", "Three", t + 5)], ["s2", "s3"]))
        self.assertEqual(len(narrowed), 3)

    def test_the_stream_carries_readers_and_acks_in_the_ref_and_no_receipt_entry(self):
        self.fixture()
        t = self.t
        radio = [entry for entry in self.events("view=funk")["events"] if entry["kind"] == "radio"]
        self.assertEqual([entry["part"] for entry in radio], ["post", "call", "broadcast"])
        self.assertEqual(self.served([entry["ref"] | {"ts": entry["ts"]} for entry in radio]), {
            t + 1: ([("s2", "Two", None)], []),
            t + 2: ([("s2", "Two", t + 4), ("s3", "Three", t + 5)], ["s2", "s3"]),
            t + 3: ([("s3", "Three", None), ("s2", "Two", None)], []),
        })

    def test_an_advanced_mark_shows_its_reader_on_the_next_state_build(self):
        self.fixture()
        t = self.t
        self.marks({"s2": {"radio": t + 10}})
        self.assertEqual(self.served(self.snapshot()["radio"])[t + 1], ([], []))
        self.marks({"s2": {"radio": t + 10, "mail": t + 10}})
        self.assertEqual(self.served(self.snapshot()["radio"])[t + 1], ([("s2", "Two", None)], []))

    def test_a_session_only_the_sighting_thread_saw_keeps_its_name_after_it_left(self):
        t = self.t
        self.sessions({"s9": "Nine"})
        stop = threading.Event()
        thread = hub.sighting(self.httpd.hub, stop)
        self.settle(lambda: any(entry["session"] == "s9" for entry in self.httpd.hub.receipt_names.listed()))
        stop.set()
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertTrue(thread.daemon)
        self.sessions({})
        self.write_council({"news.jsonl": self.jsonl([message("call", t + 1, ["Nine"]), receipt("Nine", t + 2, t + 1)])})
        self.marks({"s9": {"radio": t + 10}})
        self.assertEqual(self.served(self.snapshot()["radio"]), {t + 1: ([("s9", "Nine", t + 2)], ["s9"])})
        self.assertTrue((self.state / receipts.NAMES).is_file())
        self.assertFalse((self.council / receipts.NAMES).exists())

    def test_a_malformed_receipt_store_does_not_break_the_state(self):
        self.fixture()
        damaged = self.state / "damaged.json"
        bad = [{"session": "s2", "name": "Two", "first_seen": "soon", "source": "session"}, {"session": "s3", "name": {"x": 1}, "first_seen": 1.0, "source": "session"}]
        damaged.write_text(json.dumps({"entries": bad, "observed": {"s2\x00session": 5}, "sighted": {"s2": "x"}}), encoding="utf-8")
        self.httpd.hub = dataclasses.replace(self.httpd.hub, receipt_names=receipts.ReceiptNames(damaged))
        served = self.served(self.snapshot()["radio"])
        self.assertEqual(served[self.t + 2], ([("s2", "Two", self.t + 4), ("s3", "Three", self.t + 5)], ["s2", "s3"]))
        self.assertEqual(self.events("view=funk")["events"][1]["ref"]["acks"], ["s2", "s3"])

    def test_the_sighting_thread_logs_one_line_per_failing_pass_and_survives_all_but_a_system_exit(self):
        real, calls = receipts.session_directory, []

        def flaky(store: receipts.ReceiptNames, sessions: dict[str, dict], now: float) -> Directory:
            calls.append(now)
            if len(calls) <= 3:
                raise (ValueError, TypeError, OSError)[len(calls) - 1]("broken\npass")
            return real(store, sessions, now)

        self.sessions({"s9": "Nine"})
        stop = threading.Event()
        names = self.httpd.hub.receipt_names
        with mock.patch.object(receipts, "session_directory", flaky), mock.patch.object(hub, "SIGHTING", 0.01), contextlib.redirect_stderr(io.StringIO()) as logged:
            thread = hub.sighting(self.httpd.hub, stop)
            self.settle(lambda: any(entry["session"] == "s9" for entry in names.listed()))
            alive = thread.is_alive()
            stop.set()
            thread.join(5)
        self.assertEqual((alive, len(calls) >= 4, thread.is_alive()), (True, True, False))
        self.assertEqual(logged.getvalue().splitlines(), [f"receipts: sighting pass failed: {kind}('broken\\npass')" for kind in ("ValueError", "TypeError", "OSError")])
        with self.assertRaises(SystemExit):
            receipts.sight(mock.Mock(side_effect=SystemExit(3)), self.httpd.hub.receipt_reads, threading.Event(), 0.01)

    def test_a_failed_pass_counts_as_one_that_did_not_look(self):
        reads, stop, calls = self.httpd.hub.receipt_reads, threading.Event(), []

        def step(now: float) -> None:
            calls.append(now)
            if len(calls) == 2:
                raise OSError("council unreadable")
            if len(calls) == 3:
                stop.set()
            reads.see({("s2", T + n) for n in range(len(calls))}, NOW + 15 * len(calls), T, True)

        with contextlib.redirect_stderr(io.StringIO()) as logged:
            receipts.sight(step, reads, stop, 0)
        self.assertEqual(reads.listed(NOW + 99), {("s2", T): None, ("s2", T + 1): None, ("s2", T + 2): None})
        self.assertEqual(logged.getvalue().splitlines(), ["receipts: sighting pass failed: OSError('council unreadable')"])

    def test_a_failing_receipt_store_write_leaves_the_state_and_the_stream_without_readers(self):
        self.fixture()
        with mock.patch.object(receipts.ReceiptNames, "save", side_effect=OSError(28, "No space left on device")):
            state = self.snapshot()
            radio = [entry for entry in self.events("view=funk")["events"] if entry["kind"] == "radio"]
        self.assertEqual([(row["class"], row["readers"], row["acks"]) for row in state["radio"]], [("post", [], []), ("call", [], []), ("broadcast", [], [])])
        self.assertEqual([(entry["ref"]["readers"], entry["ref"]["acks"]) for entry in radio], [([], [])] * 3)

    def test_a_reader_shows_about_the_first_sighting_that_found_its_mark_and_none_for_rows_read_before_the_hub_looked(self):
        self.fixture()
        t, hub_ = self.t, self.httpd.hub

        def sight(reads: receipts.ReceiptReads, now: float) -> None:
            receipts.sighting_pass(hub_.scripts.skills, hub_.council, hub_.receipt_names, reads, hub_.agent_sessions, RADIO_WINDOW, now)

        first = time.time() - 30
        self.sessions({"s1": "One", "s2": "Two", "s3": "Three"}, first - 1)
        sight(hub_.receipt_reads, first)
        self.write_council({"news.jsonl": self.jsonl([*records.read_jsonl(self.council / council.NEWS), message("post", t + 20, ["Three"])])})
        self.marks({"s2": {"radio": t + 10, "mail": t + 10}, "s3": {"radio": t + 10, "mail": t + 20}})
        sight(hub_.receipt_reads, first + 5)
        sight(hub_.receipt_reads, first + 10)
        served = {row["ts"]: [(entry["session"], entry["read"], entry["approximate"]) for entry in row["readers"]] for row in self.snapshot()["radio"]}
        self.assertEqual(served, {
            t + 1: [("s2", None, False)],
            t + 2: [("s2", t + 4, False), ("s3", t + 5, False)],
            t + 3: [("s3", None, False), ("s2", None, False)],
            t + 20: [("s3", first + 5, True)],
        })
        restarted = receipts.ReceiptReads(self.state / receipts.READS)
        self.write_council({"news.jsonl": self.jsonl([*records.read_jsonl(self.council / council.NEWS), message("post", t + 30, ["Three"])])})
        self.marks({"s2": {"radio": t + 10, "mail": t + 10}, "s3": {"radio": t + 10, "mail": t + 30}})
        sight(restarted, first + 15)
        self.httpd.hub = dataclasses.replace(hub_, receipt_reads=restarted)
        served = {row["ts"]: [(entry["session"], entry["read"]) for entry in row["readers"]] for row in self.snapshot()["radio"]}
        self.assertEqual((served[t + 20], served[t + 30]), ([("s3", first + 5)], [("s3", None)]))

    def ledger(self, created: float, to: str = "Two") -> dict:
        return self.httpd.hub.messages.add({"to": to, "address": to, "text": "ping  me", "upload": None, "voice": None, "voice_sha256": "", "class": "call", "created_ts": created})

    def relay(self, record: dict, ts: float, **changes: object) -> dict:
        return {"ts": ts, "from": "Operator", "to": [record["address"]], "text": f"[kvb-orchestrator msg {record['id']}] ping me", "class": "call", "v": 2, **changes}

    def sent(self) -> dict[str, tuple]:
        return {row["id"]: ([reader["session"] for reader in row["readers"]], row["acks"]) for row in self.snapshot()["messages"]}

    def append(self, rows: list[dict]) -> None:
        self.council.mkdir(parents=True, exist_ok=True)
        with (self.council / council.NEWS).open("a", encoding="utf-8") as handle:
            handle.write(self.jsonl(rows))

    def radio_runs(self, stamps: list[float], extra: Callable[[dict], list[dict]] = lambda row: [], code: int = 0, written: bool = True) -> contextlib.AbstractContextManager:
        def run(script: str, args: list[str]) -> dict:
            cls = args[1] if args[0] == "send" else ("post" if "--to" in args else "newsletter")
            stdout = ""
            if stamps:
                row = {"ts": stamps.pop(0), "from": "Operator", "to": [args[args.index("--to") + 1]] if "--to" in args else [], "text": args[-1], "class": cls, "v": 2}
                self.append([row, *extra(row)] if written else extra(row))
                stdout = f"ts: {row['ts']!r}\nsent {cls}\n"
            return {"command": script, "code": code, "stdout": stdout, "stderr": "killed"}

        return mock.patch.object(self.scripts, "run", run)

    def test_a_run_that_fails_after_storing_keeps_the_ts_it_printed_and_one_that_printed_none_keeps_nothing(self):
        t = self.t
        self.sessions({"s2": "Two"})
        written, timed_out, refused, forged, missing = (self.ledger(t + 10 * n) for n in range(1, 6))
        with self.radio_runs([t + 10.5], code=1):
            self.httpd.hub.radioed(written, ["send", "call"])
        with self.radio_runs([t + 20.5], code=-1):
            self.httpd.hub.radioed(timed_out, ["send", "call"])
        with self.radio_runs([], code=1):
            self.httpd.hub.radioed(refused, ["send", "call"])

        def held_lock(script: str, args: list[str]) -> dict:
            self.append([self.relay(forged, t + 40.5), receipt("Two", t + 40.6, t + 40.5)])
            return {"command": script, "code": -1, "stdout": "", "stderr": "timed out after 60 seconds"}

        with mock.patch.object(self.scripts, "run", held_lock):
            self.httpd.hub.radioed(forged, ["send", "call"])
        with self.radio_runs([t + 50.5], written=False):
            self.httpd.hub.radioed(missing, ["send", "call"])
        self.append([receipt("Two", t + 11, t + 10.5)])
        self.marks({"s2": {"radio": t + 60}})
        records = (written, timed_out, refused, forged, missing)
        self.assertEqual([self.httpd.hub.messages.get(record["id"]).get("relay_ts") for record in records], [t + 10.5, t + 20.5, None, None, None])
        self.assertEqual(self.sent(), {
            written["id"]: (["s2"], ["s2"]), timed_out["id"]: (["s2"], []), refused["id"]: ([], []), forged["id"]: ([], []), missing["id"]: ([], []),
        })

    def test_the_printed_ts_counts_only_as_the_whole_first_line_with_a_valid_epoch(self):
        self.assertEqual(
            [messaging.stored_ts(text) for text in (
                "ts: 1800000000.25\nsent call to Two\nts: 1800000000.75\n", "ts: 1800000000.25", "sent call to Two\nts: 1800000000.75\n",
                "...\nts: 1800000000.75\n", "ts: 2e11\n", " ts: 1800000000.25\n", "ts: 1800000000.25 \n", "ts: nan\n", "ts: 1e999\n",
            )],
            [1800000000.25, 1800000000.25, None, None, None, None, None, None, None],
        )

    def test_a_row_appended_with_the_relay_rows_ts_leaves_that_ts_without_readers_or_acks(self):
        t = self.t
        self.sessions({"s2": "Two", "s9": "Nine"})
        record = self.ledger(t + 10)
        with self.radio_runs([t + 10.5]):
            self.httpd.hub.radioed(record, ["send", "call"])
        self.append([receipt("Two", t + 11, t + 10.5)])
        self.marks({"s2": {"radio": t + 50, "mail": t + 50}, "s9": {"radio": t + 50, "mail": t + 50}})
        self.assertEqual(self.sent(), {record["id"]: (["s2"], ["s2"])})
        self.append([message("broadcast", t + 10.5, [], "Nine"), receipt("Nine", t + 12, t + 10.5)])
        self.assertEqual(self.sent(), {record["id"]: ([], [])})
        self.assertEqual([(row["readers"], row["acks"]) for row in self.snapshot()["radio"] if row["ts"] == t + 10.5], [([], [])] * 2)

    def test_a_broadcast_waking_a_hundred_sessions_keeps_the_ts_radio_py_printed_first(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        home = Path(tmp.name)
        sessions = home / ".claude" / "sessions"
        sessions.mkdir(parents=True)
        for n in range(100):
            (sessions / f"s{n}.json").write_text(json.dumps({"sessionId": f"s{n}", "name": f"Agent {n:03d} on the long wake list"}), encoding="utf-8")
        record = self.ledger(self.t + 10, "*")
        with mock.patch.object(self.scripts, "run", skill_scripts.Scripts(REPO_ROOT / "skills", self.council, home).run):
            run = self.httpd.hub.radioed(record, ["send", "broadcast"])
        lines = run["stdout"].splitlines()
        self.assertEqual(self.httpd.hub.messages.get(record["id"]).get("relay_ts"), records.read_jsonl(self.council / council.NEWS)[-1]["ts"], run["stderr"])
        self.assertEqual(
            (run["code"], lines[1], lines[-1].startswith("wake: SendMessage to Agent "), len(run["stdout"]) <= skill_scripts.OUTPUT_LIMIT + skill_scripts.FIRST_LINE_LIMIT + 8),
            (0, skill_scripts.ELIDED, True, True),
        )

    def test_a_message_shows_the_readers_and_acks_of_exactly_the_row_its_relay_run_wrote(self):
        t = self.t
        self.sessions({"s2": "Two", "s9": "Nine"})
        record = self.ledger(t + 10)
        self.write_council({"news.jsonl": self.jsonl([self.relay(record, t + 10.1), receipt("Two", t + 10.15, t + 10.1)])})
        with self.radio_runs([t + 10.5]):
            self.httpd.hub.radioed(record, ["send", "call"])
        self.assertEqual(self.httpd.hub.messages.get(record["id"])["relay_ts"], t + 10.5)
        self.append([
            self.relay(record, t + 10.3), receipt("Two", t + 10.35, t + 10.3),
            self.relay(record, t + 10.4, to_sessions=["s9"]), receipt("Nine", t + 10.45, t + 10.4),
            self.relay(record, t + 11), receipt("Two", t + 11.5, t + 11),
        ])
        self.marks({"s2": {"radio": t + 10.2}, "s9": {"radio": t + 50}})
        self.assertEqual(self.sent(), {record["id"]: ([], [])})
        self.append([receipt("Two", t + 12, t + 10.5)])
        self.marks({"s2": {"radio": t + 50}, "s9": {"radio": t + 50}})
        self.assertEqual(self.sent(), {record["id"]: (["s2"], ["s2"])})

    def test_a_copy_of_the_relay_row_landing_with_it_lends_the_message_nothing(self):
        t = self.t
        self.sessions({"s2": "Two"})
        record = self.ledger(t + 10)
        with self.radio_runs([t + 10.5], lambda row: [{**row, "ts": t + 10.4}, receipt("Two", t + 10.7, t + 10.4)]):
            self.httpd.hub.radioed(record, ["send", "call"])
        self.marks({"s2": {"radio": t + 50}})
        self.assertEqual(self.httpd.hub.messages.get(record["id"])["relay_ts"], t + 10.5)
        self.assertEqual(self.sent(), {record["id"]: (["s2"], [])})

    def test_every_one_of_forty_choice_requests_keeps_its_own_relay_row_however_late_it_lands(self):
        signer = self.pin()
        payload = {"class": "post", "to": [f"Agent {n}" for n in range(choosing.RECIPIENT_LIMIT)]}
        status, _, body = self.post_json("/api/choices/sign", payload, self.guard(self.host))
        self.assertEqual(status, 200, body)
        proof = signer.proof(json.loads(body)["payload"], self.origin)
        base = time.time() - 300
        stamps = [base + 1.6 * (n + 1) for n in range(choosing.RECIPIENT_LIMIT)]
        with mock.patch.object(messaging, "time", types.SimpleNamespace(time=lambda: base)), self.radio_runs(list(stamps)):
            status, _, body = self.post_json("/api/choices", {**payload, "proof": proof}, self.guard(self.host))
        self.assertEqual(status, 201, body)
        ids = json.loads(body)["ids"]
        self.assertEqual([self.httpd.hub.messages.get(record_id)["relay_ts"] for record_id in ids], stamps)
        self.assertGreater(stamps[-1], base + skill_scripts.SCRIPT_TIMEOUT)
        self.sessions({"s39": "Agent 39"})
        self.append([receipt("Agent 39", base + 70, stamps[-1])])
        self.marks({"s39": {"mail": base + 80}})
        served = self.sent()
        self.assertEqual((served[ids[-1]], served[ids[0]]), ((["s39"], ["s39"]), ([], [])))

    def test_a_ledger_record_from_before_voice_notes_serves_without_readers_and_relays_its_text(self):
        t = self.t
        self.fixture()
        old = self.httpd.hub.messages.add({"to": "Two", "address": "Two", "text": "hi  there", "upload": None, "created_ts": t + 10})
        self.append([self.relay(old, t + 10.1, text=f"[kvb-orchestrator msg {old['id']}] hi there"), receipt("Two", t + 10.2, t + 10.1)])
        status, _, body = self.get("/api/state")
        self.assertEqual(status, 200, body)
        served = [row for row in json.loads(body)["messages"] if row["id"] == old["id"]]
        self.assertEqual([(row["readers"], row["acks"], row["voice"], row["class"]) for row in served], [([], [], None, "")])
        self.assertEqual(self.httpd.hub.relay_text(old), f"[kvb-orchestrator msg {old['id']}] hi there")

    def test_a_session_born_while_the_snapshot_was_stale_reads_at_no_time_and_later_rows_at_their_sighting(self):
        t, hub_ = self.t, self.httpd.hub
        first = time.time() - 60

        def sight(now: float) -> None:
            receipts.sighting_pass(hub_.scripts.skills, hub_.council, hub_.receipt_names, hub_.receipt_reads, hub_.agent_sessions, RADIO_WINDOW, now)

        self.write_council({"news.jsonl": self.jsonl([message("call", t + 20, ["Seven"])])})
        self.marks({"s7": {"radio": t + 20}})
        self.sessions({"s7": "Seven"}, first - SNAPSHOT_STALE - 1)
        sight(first)
        self.sessions({"s7": "Seven"}, first + 14)
        sight(first + 15)
        self.append([message("call", t + 40, ["Seven"])])
        self.marks({"s7": {"radio": t + 40}})
        sight(first + 30)
        served = {row["ts"]: [(entry["session"], entry["read"]) for entry in row["readers"]] for row in self.snapshot()["radio"]}
        self.assertEqual(served, {t + 20: [("s7", None)], t + 40: [("s7", first + 30)]})

    def test_without_an_installed_radio_every_row_has_no_reader(self):
        self.fixture()
        with mock.patch.object(receipts, "radio_module", return_value=None):
            state = self.snapshot()
        self.assertEqual({row["ts"]: (row["readers"], row["acks"]) for row in state["radio"]}, {self.t + n: ([], []) for n in (1, 2, 3)})


def page(payload: dict) -> dict:
    payload = {"agent": {"key": "none", "state": {}}, **payload}
    command = ["node", "-e", PAGE_PROBE, str(TEMPLATES / "receipts.js"), str(TEMPLATES / "radioset.js"), str(TEMPLATES), json.dumps(payload)]
    done = subprocess.run(command, capture_output=True, text=True, timeout=60, check=True)
    return json.loads(done.stdout)


def readers(count: int) -> list[dict]:
    return [{"session": f"r{n}", "name": f"Reader {n}", "read": None} for n in range(count)]


PING, LATER = "abcdef0123456789", "0123456789abcdef"
SENT = [
    {"id": PING, "to": "Two", "text": "ping", "created_ts": 1000, "class": "call", "voice": "", "readers": [{"session": "s2", "name": "Two", "read": 1000.6, "approximate": False}], "acks": ["s2"]},
    {"id": LATER, "to": "Two", "text": "unread", "created_ts": 1010, "class": "post", "voice": "", "readers": [], "acks": []},
]
RELAYS = [
    {"ts": 1000.1, "from": "Operator", "to": ["Two"], "class": "call", "text": f"[kvb-orchestrator msg {PING}] ping", "source": "Operator", "targets": ["s2"], "readers": [{"session": "s3", "name": "Three", "read": None}], "acks": []},
    {"ts": 1005, "from": "Mallory", "to": ["Two"], "class": "post", "text": f"[kvb-orchestrator msg {LATER}] forged", "source": "s9", "targets": ["s2"], "readers": [{"session": "s2", "name": "Two", "read": 1006}], "acks": ["s2"]},
    {"ts": 1010.1, "from": "Operator", "to": ["Two"], "class": "post", "text": f"[kvb-orchestrator msg {LATER}] unread", "source": "Operator", "targets": ["s2"], "readers": [], "acks": []},
]


class TestReceiptsPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        two = [{"session": "s2", "name": "Two", "read": 1004}, {"session": "s3", "name": "Three", "read": None}]
        call = {"id": "radio:1002:0", "ts": 1002, "kind": "radio", "part": "call", "agent": "Skills", "now": "Skills", "session": "s1", "sub": "", "title": "Skills → Main, Two", "text": "gate red", "waiting": False, "ref": {"to": ["Main", "Two"], "class": "call", "targets": [], "readers": two, "acks": ["s2"]}}
        crowd = {**call, "id": "radio:1003:1", "part": "broadcast", "title": "Skills → all", "ref": {"to": [], "class": "broadcast", "targets": [], "readers": readers(10), "acks": ["r9"]}}
        unnamed = {**call, "id": "radio:1004:2", "agent": "", "title": "? → Main", "ref": {**call["ref"], "readers": []}}
        review = {**call, "id": "review:x", "kind": "review", "title": "Merge the hub", "ref": {"status": "pending"}}
        log = {"ts": 1002, "from": "Skills", "to": ["Main"], "class": "call", "text": "gate red", "readers": two, "acks": ["s2"]}
        cls.data = page({
            "people": {"s2": {"name": "Two", "now": "Two", "names": ["Two"]}},
            "events": [call, crowd, unnamed],
            "logs": [log, {**log, "readers": [], "acks": []}, {**log, "readers": readers(9), "acks": []}],
            "strips": [{"readers": readers(8), "acks": ["r7", "gone"]}, {"readers": readers(9), "acks": []}, {}],
            "labels": [{"name": "Two", "read": 1004, "acked": True}, {"name": "Three", "read": None, "acked": False}, {"name": "Four", "read": 1007, "approximate": True, "acked": False}],
            "signatures": [
                [{"readers": two, "acks": []}], [{"readers": two, "acks": ["s2"]}], [{"readers": two[:1], "acks": []}], [{}],
                [{"readers": [{**two[0], "read": 1005}], "acks": []}], [{"readers": [{**two[0], "approximate": True}], "acks": []}],
            ],
            "agent": {"key": "s2", "state": {"messages": SENT, "radio": RELAYS}},
        })
        cls.review = page({"people": {}, "events": [review], "logs": [], "strips": [], "labels": [], "signatures": []})

    def test_the_stream_header_names_the_sender_once_and_the_route_its_recipients(self):
        call, crowd, unnamed = self.data["events"]
        self.assertEqual(call["route"], "Skills→ Main, Two")
        self.assertEqual(call["route"].count("Skills"), 1)
        self.assertEqual(crowd["route"], "Skills→ all")
        self.assertEqual(unnamed["route"], "s1? → Main")
        self.assertEqual(self.data["module"]["headlines"], ["→ Main, Two", "→ all", "? → Main"])
        self.assertEqual(self.review["events"][0]["route"], "SkillsMerge the hub")

    def test_under_each_message_one_avatar_per_reader_with_the_badge_where_a_receipt_exists(self):
        call = self.data["events"][0]
        self.assertEqual([(reader["session"], reader["acked"], reader["badges"]) for reader in call["readers"]], [("s2", "true", 1), ("s3", "false", 0)])
        self.assertEqual([reader["title"] for reader in call["readers"]], ["Two · read at 1004 · acknowledged", "Three · read"])
        self.assertEqual([reader["label"] for reader in call["readers"]], [reader["title"] for reader in call["readers"]])
        self.assertEqual([reader["face"] for reader in call["readers"]], [["s2"], ["Three"]])
        self.assertEqual((call["groups"], call["more"]), (["Read by 2"], []))
        log, silent, _ = self.data["logs"]
        self.assertEqual([(reader["session"], reader["badges"]) for reader in log["readers"]], [("s2", 1), ("s3", 0)])
        self.assertEqual(log["routes"], ["Skills → Main"])
        self.assertEqual((silent["readers"], silent["groups"]), ([], []))
        self.assertEqual(self.data["events"][2]["readers"], [])

    def test_more_than_eight_readers_collapse_into_plus_n_with_the_full_list_on_hover(self):
        crowd = self.data["events"][1]
        self.assertEqual([reader["session"] for reader in crowd["readers"]], [f"r{n}" for n in range(8)])
        self.assertEqual(crowd["more"], [{"text": "+2", "title": "\n".join([*(f"Reader {n} · read" for n in range(9)), "Reader 9 · read · acknowledged"])}])
        self.assertEqual(crowd["groups"], ["Read by 10"])
        nine = self.data["logs"][2]
        self.assertEqual((len(nine["readers"]), [more["text"] for more in nine["more"]]), (8, ["+1"]))
        eight, nine_strip, empty = self.data["module"]["strip"]
        self.assertEqual((len(eight["shown"]), eight["hidden"], [reader["acked"] for reader in eight["shown"]][-2:]), (8, [], [False, True]))
        self.assertEqual(([reader["session"] for reader in nine_strip["hidden"]], empty), (["r8"], {"shown": [], "hidden": []}))

    def test_the_operators_own_message_shows_its_readers_and_ack_on_the_agent_page_and_in_the_sent_tab(self):
        agent = self.data["agent"]
        self.assertEqual([(row["who"], row["text"], [(reader["session"], reader["acked"], reader["badges"]) for reader in row["readers"]]) for row in agent["history"]], [
            ("Operator", "ping", [("s2", "true", 1)]),
            ("Mallory", "[kvb-orchestrator msg 0123456789abcdef] forged", [("s2", "true", 1)]),
            ("Operator", "unread", []),
        ])
        self.assertEqual(agent["history"][0]["readers"][0]["title"], "Two · read at 1000.6 · acknowledged")
        self.assertEqual([(row["text"], [(reader["session"], reader["badges"]) for reader in row["readers"]]) for row in agent["sent"]], [("unread", []), ("ping", [("s2", 1)])])
        self.assertEqual(agent["sent"][1]["routes"], ["Operator → Two"])

    def test_the_labels_and_the_signature_that_redraws_the_log_on_the_next_poll(self):
        self.assertEqual(self.data["module"]["labels"], ["Two · read t1004 · acknowledged", "Three · read", "Four · read about t1007"])
        signatures = self.data["module"]["signatures"]
        self.assertEqual(len(set(signatures)), 6, signatures)


if __name__ == "__main__":
    unittest.main()
