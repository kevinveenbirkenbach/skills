from __future__ import annotations

import importlib.util
import json
import math
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
RADIO = REPO_ROOT / "skills" / "kvb-org-radio" / "scripts" / "radio.py"
CHANNELS = {
    "mayday": "radio", "pan-pan": "radio", "security": "radio", "call": "radio", "broadcast": "radio",
    "post": "mail", "newsletter": "mail", "receipt": "mail",
}
ADDRESSED = ("call", "post", "receipt")
NEVER = 0.0


def load(root: Path):
    spec = importlib.util.spec_from_file_location("kvb_radio_seen_test", RADIO)
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(os.environ, {"AGENTS_COUNCIL_ROOT": str(root)}):
        spec.loader.exec_module(module)
    return module


def row(cls: str, ts: float, to: list[str]) -> dict:
    return {"ts": ts, "from": "One", "to": to, "text": cls, "class": cls, "v": 2}


class TestSeen(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.radio = load(self.base / "council")

    def seen(self, entry: dict, name: str, prompt: float, state: dict, since: float) -> bool:
        return self.radio.seen(entry, name, "s2", prompt, state, since)

    def test_a_row_pinned_to_the_session_is_seen_under_any_name(self):
        pinned = {**row("call", 100.0, ["Old"]), "to_sessions": ["s2"]}
        self.assertTrue(self.seen(pinned, "Two", NEVER, {"radio": 100.0}, NEVER))
        self.assertFalse(self.radio.seen(pinned, "Two", "s3", NEVER, {"radio": 100.0}, NEVER))

    def test_each_class_is_seen_by_the_mark_of_its_channel_alone(self):
        for cls, own in CHANNELS.items():
            other = "mail" if own == "radio" else "radio"
            entry = row(cls, 100.0, ["Two"] if cls in ADDRESSED else [])
            with self.subTest(cls=cls):
                self.assertTrue(self.seen(entry, "Two", NEVER, {own: 100.0}, NEVER))
                self.assertTrue(self.seen(entry, "Two", NEVER, {own: 150.0}, NEVER))
                self.assertFalse(self.seen(entry, "Two", NEVER, {own: 99.5}, NEVER))
                self.assertFalse(self.seen(entry, "Two", NEVER, {other: 500.0, "mtime": 500.0}, NEVER))
                self.assertFalse(self.seen(entry, "Two", NEVER, {}, NEVER))

    def test_the_prompt_mark_and_since_cover_every_channel(self):
        for cls in CHANNELS:
            entry = row(cls, 100.0, ["Two"] if cls in ADDRESSED else [])
            with self.subTest(cls=cls):
                self.assertTrue(self.seen(entry, "Two", 100.0, {}, NEVER))
                self.assertTrue(self.seen(entry, "Two", NEVER, {}, 100.0))
                self.assertFalse(self.seen(entry, "Two", 99.5, {}, 99.5))

    def test_a_row_the_session_sent_or_one_for_others_is_never_seen(self):
        marks = {"radio": 500.0, "mail": 500.0}
        self.assertFalse(self.seen(row("broadcast", 100.0, []), "One", 500.0, marks, 500.0))
        self.assertFalse(self.seen(row("call", 100.0, ["Three"]), "Two", 500.0, marks, 500.0))
        self.assertFalse(self.seen(row("post", 100.0, ["Three"]), "Two", 500.0, marks, 500.0))
        self.assertTrue(self.seen(row("call", 100.0, ["Three", "Two"]), "Two", NEVER, marks, NEVER))

    def test_rows_without_the_version_mark_read_their_old_channel(self):
        wake = {"ts": 100.0, "from": "One", "to": ["Two"], "class": "direct", "wake": True}
        mail = {"ts": 100.0, "from": "One", "to": ["Two"], "text": "old direct"}
        board = {"ts": 100.0, "from": "One", "to": [], "text": "old board", "class": "broadcast"}
        self.assertTrue(self.seen(wake, "Two", NEVER, {"radio": 100.0}, NEVER))
        self.assertFalse(self.seen(wake, "Two", NEVER, {"mail": 100.0}, NEVER))
        self.assertTrue(self.seen(mail, "Two", NEVER, {"mail": 100.0}, NEVER))
        self.assertFalse(self.seen(mail, "Two", NEVER, {"radio": 100.0}, NEVER))
        self.assertTrue(self.seen(board, "Two", NEVER, {"mail": 100.0}, NEVER))

    def test_a_mark_that_is_no_number_counts_as_never(self):
        for value in ("500", None, [500], {"x": 500}):
            with self.subTest(value=value):
                self.assertFalse(self.seen(row("broadcast", 100.0, []), "Two", NEVER, {"radio": value}, NEVER))

    def test_a_nan_prompt_mark_leaves_nothing_to_take_as_before(self):
        for cls, own in CHANNELS.items():
            entry = row(cls, 100.0, ["Two"] if cls in ADDRESSED else [])
            with self.subTest(cls=cls):
                self.assertTrue(self.seen(entry, "Two", math.nan, {}, NEVER))
                self.assertFalse(self.seen(entry, "Two", NEVER, {own: math.nan}, NEVER))


class TestPendingLeavesWhatSeenTook(unittest.TestCase):
    def test_show_lists_the_rows_after_every_mark_and_inside_the_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            home, root = base / "home", base / "council"
            (home / ".claude" / "sessions").mkdir(parents=True)
            (home / ".claude" / "sessions" / "s2.json").write_text(json.dumps({"sessionId": "s2", "name": "Two"}), encoding="utf-8")
            (root / "radio-seen").mkdir(parents=True)
            (root / "news-seen").mkdir()
            now = time.time()
            rows = [
                {**row("newsletter", now - 90000, []), "text": "expired"},
                {**row("newsletter", now - 46, []), "text": "under the prompt mark"},
                {**row("security", now - 44, []), "text": "under the radio mark"},
                {**row("post", now - 70, ["Two"]), "text": "under the mail mark"},
                {**row("call", now - 20, ["Three"]), "text": "for three"},
                {**row("broadcast", now - 30, []), "text": "after the radio mark"},
                {**row("newsletter", now - 35, []), "text": "after the mail mark"},
            ]
            (root / "news.jsonl").write_text("".join(json.dumps(entry) + "\n" for entry in rows), encoding="utf-8")
            (root / "news-seen" / "s2").write_text(str(now - 45), encoding="utf-8")
            (root / "radio-seen" / "s2.json").write_text(json.dumps({"radio": now - 40, "mail": now - 60}), encoding="utf-8")
            env = {"PATH": "/usr/bin:/bin", "HOME": str(home), "AGENTS_COUNCIL_ROOT": str(root), "AGENTS_COUNCIL_CONFIG": str(base / "config.json"), "CLAUDE_CODE_SESSION_ID": "s2"}
            shown = subprocess.run([sys.executable, str(RADIO), "show"], capture_output=True, text=True, env=env, check=False, timeout=30)
            self.assertEqual(shown.returncode, 0, shown.stderr)
            self.assertEqual([line.split(": ", 1)[1] for line in shown.stdout.splitlines()], ["after the radio mark", "after the mail mark"])


if __name__ == "__main__":
    unittest.main()
