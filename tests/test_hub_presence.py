"""Pin decision 61: each agent state from the host's session snapshot, the night state, radio receipts and claim beats."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

import hub_support  # noqa: F401
import sessions as client
from kvb_orchestrator.presence import SNAPSHOT_STALE, presence, read_snapshot

NOW = 1_800_000_000.0
FRESH = int((NOW - 60) * 1000)
OLD = int((NOW - 1800) * 1000)


def record(sid: str, status: str, updated: int, name: str) -> dict:
    return {"status": status, "statusUpdatedAt": updated, "name": name, "running": sid != "gone"}


def claim(session: str, name: str, beat: float | None) -> dict:
    return {"session": session, "agent": name, "beat": beat}


class TestPresence(unittest.TestCase):
    def states(self, sessions: dict[str, dict], parts: dict[str, str], mode: str, claims: list[dict], news: list[dict]) -> dict[str, str]:
        return presence(sessions, parts, mode, claims, news, NOW)

    def test_each_state_by_day_and_by_night(self):
        sessions = {sid: record(sid, status, updated, name) for sid, status, updated, name in (
            ("work", "busy", FRESH, "Worker"),
            ("idle", "idle", OLD, "Idler"),
            ("gone", "idle", FRESH, "Ghost"),
            ("stuck", "busy", OLD, "Stuck"),
            ("called", "idle", OLD, "Callee"),
            ("answered", "idle", OLD, "Answerer"),
            ("sleep", "idle", FRESH, "Sleeper"),
            ("park", "busy", FRESH, "Parker"),
        )}
        call = NOW - 700
        news = [
            {"ts": call, "from": "Operator", "to": ["Callee"], "class": "call"},
            {"ts": call, "from": "Operator", "to": ["Answerer"], "class": "call"},
            {"ts": call + 2, "from": "Answerer", "to": ["Operator"], "class": "receipt", "call": call},
            {"ts": NOW - 60, "from": "Operator", "to": ["Idler"], "class": "call"},
        ]
        claims = [claim("codex-on", "Codex", NOW - 60), claim("codex-off", "Codex old", NOW - 3600), claim("-", "Nobody", NOW), claim("op", "Operator", NOW)]
        day = self.states(sessions, {"sleep": "suspend", "park": "drain"}, "day", claims, news)
        self.assertEqual(day, {
            "work": "working", "idle": "alive", "gone": "dead", "stuck": "unreachable", "called": "unreachable",
            "answered": "alive", "sleep": "sleeping", "park": "suspending", "codex-on": "alive", "codex-off": "dead",
        })
        night = self.states(sessions, {"idle": "day", "work": "suspend"}, "drain", [], [])
        self.assertEqual({sid: night[sid] for sid in ("work", "idle", "called", "sleep", "park")}, {
            "work": "suspending", "idle": "alive", "called": "sleeping", "sleep": "sleeping", "park": "suspending",
        })

    def test_a_status_update_after_the_call_counts_as_reached(self):
        news = [{"ts": NOW - 900, "from": "Operator", "to": ["Alias"], "class": "call"}]
        claims = [claim("later", "Alias", NOW)]
        self.assertEqual(self.states({"later": record("later", "idle", FRESH, "Later")}, {}, "day", claims, news), {"later": "alive"})
        self.assertEqual(self.states({"later": record("later", "idle", OLD, "Later")}, {}, "day", claims, news), {"later": "unreachable"})

    def test_a_record_without_running_true_is_dead(self):
        for value in (False, None, "yes", 1):
            with self.subTest(value=value):
                entry = {**record("s", "busy", FRESH, "S"), "running": value}
                self.assertEqual(self.states({"s": entry}, {}, "day", [], []), {"s": "dead"})


class TestSnapshot(unittest.TestCase):
    def test_the_host_client_keeps_name_status_and_whether_the_process_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            proc, folder = base / "proc", base / "sessions"
            (proc / "4242").mkdir(parents=True)
            folder.mkdir()
            (proc / "4242" / "stat").write_text("4242 (claude (main)) S " + " ".join(str(n) for n in range(1, 19)) + " 777 0 0\n", encoding="utf-8")
            live = {"sessionId": "s1", "pid": 4242, "procStart": "777", "status": "busy", "statusUpdatedAt": FRESH, "name": "One", "cwd": "/secret"}
            (folder / "1.json").write_text(json.dumps(live), encoding="utf-8")
            (folder / "2.json").write_text(json.dumps({**live, "sessionId": "s2", "procStart": "778"}), encoding="utf-8")
            (folder / "3.json").write_text(json.dumps({"status": "idle"}), encoding="utf-8")
            (folder / "4.json").write_text("{broken", encoding="utf-8")
            (folder / "5.json").write_text(json.dumps(["s5"]), encoding="utf-8")
            output = base / "agent-sessions.json"
            client.write(output, client.snapshot(folder, proc, NOW))
            kept = {"status": "busy", "statusUpdatedAt": FRESH, "name": "One"}
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), {
                "written": NOW, "sessions": {"s1": {**kept, "running": True}, "s2": {**kept, "running": False}},
            })
            self.assertEqual(sorted(path.name for path in base.iterdir()), ["agent-sessions.json", "proc", "sessions"])
            self.assertEqual(client.snapshot(folder / "missing", proc, NOW), {"written": NOW, "sessions": {}})

    def test_the_host_client_skips_hostile_records_and_leaves_no_temp_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            proc, folder = base / "proc", base / "sessions"
            proc.mkdir()
            folder.mkdir()
            good = {"sessionId": "s1", "pid": 1, "procStart": "1", "status": "busy", "statusUpdatedAt": FRESH, "name": "One"}
            (base / "outside.json").write_text(json.dumps({**good, "sessionId": "s9"}), encoding="utf-8")
            (folder / "1.json").write_text(json.dumps({**good, "name": {"x": 1}, "status": "y" * 201, "statusUpdatedAt": True}), encoding="utf-8")
            (folder / "2.json").symlink_to(base / "outside.json")
            os.mkfifo(folder / "3.json")
            (folder / "4.json").write_text("[" * 30000 + "]" * 30000, encoding="utf-8")
            (folder / "5.json").write_text(json.dumps({**good, "sessionId": "s5", "name": "z" * client.RECORD_BYTES}), encoding="utf-8")
            self.assertEqual(client.snapshot(folder, proc, NOW), {"written": NOW, "sessions": {"s1": {"running": False}}})
            output = base / "agent-sessions.json"
            with self.assertRaises(TypeError):
                client.write(output, {"written": object()})
            self.assertEqual(sorted(path.name for path in base.iterdir()), ["outside.json", "proc", "sessions"])

    def test_running_needs_an_int_pid_and_the_same_process_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = Path(tmp)
            (proc / "4242").mkdir()
            (proc / "4242" / "stat").write_text("4242 (claude (main)) S " + " ".join(str(n) for n in range(1, 19)) + " 777 0 0\n", encoding="utf-8")
            entry = {"pid": 4242, "procStart": "777"}
            self.assertTrue(client.running(entry, proc))
            for bad in ({**entry, "procStart": "778"}, {**entry, "pid": 4243}, {**entry, "pid": True}, {**entry, "pid": "4242"}, {"pid": 4242}):
                with self.subTest(bad=bad):
                    self.assertFalse(client.running(bad, proc))

    def test_the_hub_reads_only_a_fresh_well_formed_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent-sessions.json"
            self.assertEqual(read_snapshot(path, NOW), {})
            entry = record("s1", "busy", FRESH, "One")
            for data, expected in (
                ({"written": NOW - SNAPSHOT_STALE, "sessions": {"s1": entry, "s2": "x"}}, {"s1": entry}),
                ({"written": NOW - SNAPSHOT_STALE - 1, "sessions": {"s1": entry}}, {}),
                ({"written": True, "sessions": {"s1": entry}}, {}),
                ({"written": NOW + 1, "sessions": {"s1": entry}}, {}),
                ({"written": float("nan"), "sessions": {"s1": entry}}, {}),
                ({"written": NOW, "sessions": ["s1"]}, {}),
                (["s1"], {}),
            ):
                with self.subTest(data=data):
                    path.write_text(json.dumps(data), encoding="utf-8")
                    self.assertEqual(read_snapshot(path, NOW), expected)


if __name__ == "__main__":
    unittest.main()
