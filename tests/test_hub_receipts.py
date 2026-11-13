from __future__ import annotations

import json
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import hub_support  # noqa: F401
from kvb_orchestrator import receipts
from kvb_orchestrator.names import Directory, Names

REPO_ROOT = Path(__file__).resolve().parents[1]
NOW = 1_800_000_000.0
T = NOW - 1000
EARLY = T - 100
WINDOW = (T, T + 100)


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

    def inline(self, news: list[dict], names: Directory, window: tuple[float, float] = WINDOW) -> dict[float, dict]:
        return receipts.readers_and_acks(self.radio, news, window, receipts.read_marks(self.council, NOW), names)

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
        self.assertEqual(found[T + 3]["readers"], [{"session": "s2", "name": "Two", "read": None}, {"session": "s4", "name": "s4", "read": None}])

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
        live = receipts.session_directory(Names(file), {"s2": {"name": "Two"}, "s3": {"name": {"x": 1}}, "s4": {}}, EARLY)
        ended = receipts.session_directory(Names(file), {}, T + 50)
        for names in (live, ended):
            with self.subTest(names=names):
                self.assertEqual((names.aliases("Two"), names.at("s2", T + 10), names.at("s3", T), names.aliases("Ghost")), ({"s2"}, "Two", "", set()))
        news = [message("call", T + 10, ["Two"]), receipt("Two", T + 11, T + 10)]
        self.state("s2", json.dumps({"radio": T + 20}))
        self.state("sA", json.dumps({"radio": T + 20}))
        found = self.inline(news, ended)
        self.assertEqual((who(found[T + 10]), found[T + 10]["acks"]), ([("s2", T + 11)], ["s2"]))

    def test_snapshot_names_match_rows_and_receipts_unnormalized_as_radio_does(self):
        names = receipts.session_directory(Names(self.base / "raw.json"), {"s2": {"name": "Two session"}}, EARLY)
        news = [message("call", T + 10, ["Two session"]), receipt("Two session", T + 11, T + 10), message("call", T + 20, ["Two"]), receipt("Two", T + 21, T + 20)]
        self.state("s2", json.dumps({"radio": T + 30}))
        found = self.inline(news, names)
        self.assertEqual((who(found[T + 10]), found[T + 10]["acks"]), ([("s2", T + 11)], ["s2"]))
        self.assertEqual((who(found[T + 20]), found[T + 20]["acks"]), ([], []))

    def test_a_reader_without_a_receipt_gets_no_read_time_from_a_later_mark(self):
        news = [message("mayday", T + 10, []), message("call", T + 20, ["Two"]), receipt("Two", T + 21, T + 20)]
        self.state("s2", json.dumps({"radio": T + 90}))
        found = self.inline(news, NAMED)
        self.assertEqual((who(found[T + 10]), who(found[T + 20])), ([("s2", None)], [("s2", T + 21)]))

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
        found = receipts.readers_and_acks(self.radio, news, WINDOW, marks, directory())
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
        found = receipts.readers_and_acks(spy, news, WINDOW, receipts.read_marks(self.council, NOW), NAMED)
        self.assertEqual(found, {T + 4: {"readers": [], "acks": []}})
        self.assertEqual(calls, [(news[0], "Two", self.radio.NEVER, {"radio": NOW}, self.radio.NEVER)])

    def test_rows_without_a_usable_time_and_sessions_without_a_name(self):
        news = [{**message("broadcast", T + 4, []), "ts": "x"}, {**message("broadcast", T + 5, []), "ts": True}, message("call", T + 6, ["s9"])]
        self.state("s9", json.dumps({"radio": NOW}))
        found = self.inline(news, directory())
        self.assertEqual(list(found), [T + 6])
        self.assertEqual(found[T + 6]["readers"], [{"session": "s9", "name": "s9", "read": None}])

    def test_read_marks_without_mark_folders_is_empty(self):
        self.assertEqual(receipts.read_marks(self.base / "missing", NOW), {})

    def test_the_radio_module_needs_an_installed_radio_whose_seen_takes_the_hubs_arguments(self):
        self.assertIsNone(receipts.radio_module(self.base / "none"))
        fake = self.base / "skills" / "kvb-org-radio" / "scripts"
        fake.mkdir(parents=True)
        for version, text, loads in (
            (2, "SEEN = 1\n", False),
            (3, "def seen(\n", False),
            (4, "def seen(row, name, sid, prompt, state, since):\n    return True\n", False),
            (5, "def seen(row, name, state, prompt, since):\n    return True\n", False),
            (6, "def seen(row, name, prompt, state, since):\n    return True\n", True),
        ):
            (fake / "radio.py").write_text(text, encoding="utf-8")
            os.utime(fake / "radio.py", ns=(1, version))
            with self.subTest(text=text):
                self.assertEqual(receipts.radio_module(self.base / "skills") is not None, loads)
        self.assertEqual(tuple(receipts.inspect.signature(self.radio.seen).parameters), receipts.SEEN_PARAMETERS)


if __name__ == "__main__":
    unittest.main()
