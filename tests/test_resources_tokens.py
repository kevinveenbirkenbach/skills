from __future__ import annotations

import ast
import datetime
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import hub_support
import resources as sampler

SCRIPT = hub_support.HUB / "client" / "resources.py"
NOW = 1_800_000_000
HOUR = 3600
SESSION, OTHER = "5d88e9aa-0000-4000-8000-000000000001", "f45bf5bb-0000-4000-8000-000000000002"
OPUS, HAIKU = "claude-opus-5-5", "claude-haiku-4-5"


def iso(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts, datetime.UTC).isoformat().replace("+00:00", "Z")


def assistant(ts: float, session: str, model: str, ident: str, counts: tuple[int, int, int, int], request: str = "") -> dict:
    usage = dict(zip(("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"), counts, strict=True))
    message = {"id": ident, "type": "message", "role": "assistant", "model": model, "content": [{"type": "text", "text": "ok"}], "usage": {**usage, "service_tier": "standard"}}
    return {"type": "assistant", "sessionId": session, "timestamp": iso(ts), "message": message, **({"requestId": request} if request else {})}


def lines(rows: list[dict]) -> str:
    return "".join(json.dumps(entry) + "\n" for entry in rows)


class TokensCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        self.projects, self.council, self.state = base / "projects", base / "council", base / "state"
        for folder in (self.projects / "-repo", self.council / "work" / "s1", self.state):
            folder.mkdir(parents=True)
        (self.council / "work" / "s1" / "claim.json").write_text(json.dumps({"office": "work/s1", "session": SESSION, "name": " Skills ", "beat": NOW}), encoding="utf-8")
        self.transcript = self.projects / "-repo" / f"{SESSION}.jsonl"

    def count(self, now: float = NOW + 120, budget: int = sampler.BUDGET) -> list[dict]:
        return sampler.count_tokens(self.projects, self.council, self.state, now, budget)

    def offsets(self) -> dict:
        return json.loads((self.state / "offsets.json").read_text(encoding="utf-8"))

    def written(self) -> list[dict]:
        path = self.state / "tokens.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []

    def totals(self) -> dict[tuple[int, str, str], tuple[int, ...]]:
        found: dict[tuple[int, str, str], tuple[int, ...]] = {}
        for entry in self.written():
            key = (entry["t"], entry["agent"], entry["model"])
            before = found.get(key, (0, 0, 0, 0))
            found[key] = tuple(a + b for a, b in zip(before, (entry["input"], entry["output"], entry["cache_read"], entry["cache_write"]), strict=True))
        return found


class TestTokens(TokensCase):
    def test_usage_fields_add_up_per_hour_agent_and_model_and_a_message_split_over_lines_counts_once(self):
        hour = NOW
        rows = [
            {"type": "user", "sessionId": SESSION, "timestamp": iso(NOW + 5), "message": {"role": "user", "content": "x", "usage": {"input_tokens": 999}}},
            assistant(NOW + 10, SESSION, OPUS, "msg_1", (10, 20, 300, 40)),
            assistant(NOW + 10, SESSION, OPUS, "msg_1", (10, 20, 300, 40)),
            assistant(NOW + 20, SESSION, HAIKU, "msg_2", (1, 2, 3, 4)),
            assistant(NOW + 30, SESSION, OPUS, "msg_3", (5, 6, 7, 8)),
            assistant(NOW + 40, SESSION, "<synthetic>", "msg_4", (0, 0, 0, 0)),
            assistant(NOW - HOUR + 10, OTHER, OPUS, "msg_5", (100, 200, 0, 0)),
        ]
        self.transcript.write_text(lines(rows) + "{not json\n", encoding="utf-8")
        added = self.count()
        self.assertEqual(sorted((entry["t"], entry["agent"], entry["model"]) for entry in added), sorted(self.totals()))
        self.assertEqual(self.totals(), {
            (hour, "Skills", OPUS): (15, 26, 307, 48),
            (hour, "Skills", HAIKU): (1, 2, 3, 4),
            (hour - HOUR, OTHER[:8], OPUS): (100, 200, 0, 0),
        })
        self.assertEqual(sorted(self.written()[0]), ["agent", "cache_read", "cache_write", "input", "model", "output", "t"])

    def test_a_second_run_adds_only_the_bytes_after_the_last_offset(self):
        hour = NOW
        self.transcript.write_text(lines([assistant(NOW + 10, SESSION, OPUS, "msg_1", (10, 20, 30, 40))]), encoding="utf-8")
        self.count()
        self.assertEqual(self.offsets()["files"], {f"-repo/{SESSION}.jsonl": self.transcript.stat().st_size})
        self.assertEqual(self.count(), [])
        last = json.dumps(assistant(NOW + 50, SESSION, OPUS, "msg_3", (7, 7, 7, 7)))
        more = [assistant(NOW + 10, SESSION, OPUS, "msg_1", (10, 20, 30, 40)), assistant(NOW + 40, SESSION, OPUS, "msg_2", (1, 1, 1, 1))]
        with self.transcript.open("a", encoding="utf-8") as handle:
            handle.write(lines(more) + last[:40])
        self.count()
        self.assertEqual(self.totals(), {(hour, "Skills", OPUS): (11, 21, 31, 41)})
        with self.transcript.open("a", encoding="utf-8") as handle:
            handle.write(last[40:] + "\n")
        self.count()
        self.assertEqual(self.totals(), {(hour, "Skills", OPUS): (18, 28, 38, 48)})
        self.assertEqual(self.offsets()["files"][f"-repo/{SESSION}.jsonl"], self.transcript.stat().st_size)

    def test_a_byte_budget_spreads_a_long_backlog_over_runs_without_losing_tokens(self):
        rows = [assistant(NOW + index, SESSION, OPUS, f"msg_{index}", (1, 0, 0, 0)) for index in range(40)]
        self.transcript.write_text(lines(rows), encoding="utf-8")
        line = len(lines(rows[:1]))
        self.count(budget=10 * line)
        self.assertEqual(sum(entry["input"] for entry in self.written()), 10)
        for _ in range(3):
            self.count(budget=10 * line)
        self.assertEqual(sum(entry["input"] for entry in self.written()), 40)

    def test_a_shrunk_file_restarts_at_zero_a_vanished_one_leaves_the_offsets_and_an_old_one_starts_at_its_end(self):
        self.transcript.write_text(lines([assistant(NOW - 40, SESSION, OPUS, "msg_1", (5, 0, 0, 0)), assistant(NOW - 30, SESSION, OPUS, "msg_2", (5, 0, 0, 0))]), encoding="utf-8")
        old = self.projects / "-repo" / f"{OTHER}.jsonl"
        old.write_text(lines([assistant(NOW - 100 * 86400, OTHER, OPUS, "msg_9", (9, 0, 0, 0))]), encoding="utf-8")
        os.utime(old, (NOW - 100 * 86400, NOW - 100 * 86400))
        self.count()
        self.assertEqual(sum(entry["input"] for entry in self.written()), 10)
        self.transcript.write_text(lines([assistant(NOW - 20, SESSION, OPUS, "msg_7", (1, 0, 0, 0))]), encoding="utf-8")
        old.unlink()
        self.count()
        self.assertEqual(sum(entry["input"] for entry in self.written()), 11)
        self.assertEqual(sorted(self.offsets()["files"]), [f"-repo/{SESSION}.jsonl"])

    def test_a_message_that_fork_transcripts_copy_counts_once_across_files_and_runs(self):
        shared = assistant(NOW + 10, SESSION, OPUS, "msg_1", (10, 20, 30, 40), "req_1")
        subagents = self.projects / "-repo" / SESSION / "subagents"
        subagents.mkdir(parents=True)
        self.transcript.write_text(lines([shared]), encoding="utf-8")
        (subagents / "agent-a.jsonl").write_text(lines([{**shared, "timestamp": iso(NOW + 40)}, assistant(NOW + 50, SESSION, OPUS, "msg_2", (1, 1, 1, 1), "req_2")]), encoding="utf-8")
        self.count()
        self.assertEqual(self.totals(), {(NOW, "Skills", OPUS): (11, 21, 31, 41)})
        (subagents / "agent-b.jsonl").write_text(lines([shared, assistant(NOW + 60, SESSION, OPUS, "msg_1", (5, 5, 5, 5), "req_9")]), encoding="utf-8")
        self.count(now=NOW + 180)
        self.assertEqual(self.totals(), {(NOW, "Skills", OPUS): (16, 26, 36, 46)})

    def test_the_seen_messages_keep_the_hours_of_this_run_and_the_last_two_hours(self):
        self.transcript.write_text(lines([assistant(NOW - 5 * HOUR, SESSION, OPUS, "msg_1", (1, 0, 0, 0), "req_1"), assistant(NOW + 10, SESSION, OPUS, "msg_2", (1, 0, 0, 0), "req_2")]), encoding="utf-8")
        self.count()
        self.assertEqual({hour: len(keys) for hour, keys in self.offsets()["seen"].items()}, {str(NOW - 5 * HOUR): 1, str(NOW): 1})
        self.count(now=NOW + HOUR + 120)
        self.assertEqual(sorted(self.offsets()["seen"]), [str(NOW)])
        self.count(now=NOW + 2 * HOUR + 120)
        self.assertEqual(self.offsets()["seen"], {})

    def test_a_transcript_that_fails_to_read_keeps_its_offset_and_counts_nothing_twice(self):
        old = NOW - 5 * HOUR
        self.transcript.write_text(lines([assistant(old + 10, SESSION, OPUS, "msg_1", (5, 0, 0, 0), "req_1")]), encoding="utf-8")
        self.count()
        end = self.transcript.stat().st_size
        with self.transcript.open("a", encoding="utf-8") as handle:
            handle.write(lines([assistant(old + 20, SESSION, OPUS, "msg_2", (1, 0, 0, 0), "req_2")]))
        with mock.patch.object(sampler, "scan", side_effect=PermissionError("denied")):
            self.assertEqual(self.count(now=NOW + HOUR + 120), [])
        self.assertEqual(self.offsets()["files"], {f"-repo/{SESSION}.jsonl": end})
        self.count(now=NOW + 2 * HOUR + 120)
        self.assertEqual(self.totals(), {(old, "Skills", OPUS): (6, 0, 0, 0)})

    def test_a_run_without_new_bytes_leaves_offsets_json_unwritten(self):
        self.transcript.write_text(lines([assistant(NOW + 10, SESSION, OPUS, "msg_1", (1, 0, 0, 0), "req_1")]), encoding="utf-8")
        self.count()
        stored = self.offsets()
        with mock.patch.object(sampler, "replace", side_effect=AssertionError("offsets.json rewritten")):
            self.assertEqual(self.count(now=NOW + 180), [])
        self.assertEqual(self.offsets(), stored)

    def test_the_first_minute_of_an_hour_merges_rows_and_drops_those_older_than_ninety_days(self):
        hour = NOW
        stale = {"t": hour - 91 * 86400, "agent": "Old", "model": OPUS, "input": 1, "output": 1, "cache_read": 1, "cache_write": 1}
        parts = [{"t": hour - HOUR, "agent": "Skills", "model": OPUS, "input": value, "output": 0, "cache_read": 0, "cache_write": 0} for value in (1, 2, 3)]
        (self.state / "tokens.jsonl").write_text(lines([stale, *parts]), encoding="utf-8")
        self.transcript.write_text(lines([assistant(NOW + 10, SESSION, OPUS, "msg_1", (4, 0, 0, 0))]), encoding="utf-8")
        self.count(now=hour + 1800)
        self.assertEqual(len(self.written()), 5)
        self.count(now=hour + 30)
        self.assertEqual(self.written(), [{**parts[0], "input": 6}, {"t": hour, "agent": "Skills", "model": OPUS, "input": 4, "output": 0, "cache_read": 0, "cache_write": 0}])


class TestNoLanguageModel(unittest.TestCase):
    def test_the_sampler_and_the_parser_import_no_network_client(self):
        tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
        imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        imported |= {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
        self.assertEqual(imported & {"urllib", "http", "socket", "ssl", "requests", "hub_api", "anthropic", "openai"}, set())


class TestTokensInScratchHome(unittest.TestCase):
    def test_the_tokens_command_reads_the_scratch_home_transcripts_and_writes_beside_the_samples(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, council = Path(tmp) / "home", Path(tmp) / "council"
            folder = home / ".claude" / "projects" / "-repo"
            folder.mkdir(parents=True)
            council.mkdir()
            ts = datetime.datetime.now(datetime.UTC).timestamp() - 60
            (folder / f"{SESSION}.jsonl").write_text(lines([assistant(ts, SESSION, OPUS, "msg_1", (3, 4, 5, 6))]), encoding="utf-8")
            state = home / ".local" / "state" / "agents-council" / "resources"
            argv = [sys.executable, str(SCRIPT), "tokens", "--state", str(state), "--council", str(council), "--transcripts", str(home / ".claude" / "projects")]
            done = subprocess.run(argv, env={**os.environ, "HOME": str(home), "PATH": "/usr/bin:/bin"}, capture_output=True, text=True, timeout=60, check=False)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(sorted(path.name for path in state.iterdir()), ["offsets.json", "tokens.jsonl"])
            written = [json.loads(line) for line in (state / "tokens.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(written, [{"t": int(ts - ts % HOUR), "agent": SESSION[:8], "model": OPUS, "input": 3, "output": 4, "cache_read": 5, "cache_write": 6}])


if __name__ == "__main__":
    unittest.main()
