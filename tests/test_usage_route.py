"""Exercise requirement 070 through the handler: GET /api/usage on fixture token rows."""

from __future__ import annotations

import json
import time
import unittest

from hub_case import HubCase
from kvb_orchestrator import records, usage

COLUMNS = ["cache_read", "cache_write", "cost", "hit_rate", "input", "key", "output", "share", "total"]
OPUS, HAIKU = "claude-opus-5-5", "claude-haiku-5-5"


class TestUsageRoute(HubCase):
    def setUp(self):
        super().setUp()
        now = int(time.time())
        self.hour = now - now % 3600 - 3600
        self.rows = [
            {"t": self.hour, "agent": "Skills", "model": OPUS, "input": 1000, "output": 100, "cache_read": 3000, "cache_write": 0, "skill": "kvb-help", "tool": "Bash,Read"},
            {"t": self.hour, "agent": "Skills", "model": HAIKU, "input": 500, "output": 50, "cache_read": 0, "cache_write": 0, "skill": "kvb-help"},
            {"t": self.hour, "agent": "Stage", "model": OPUS, "input": 4000, "output": 1000, "cache_read": 0, "cache_write": 1000, "tool": "Edit", "account": "one@example.org"},
            {"t": self.hour, "agent": "Stage", "model": "mystery", "input": 50000, "output": 0, "cache_read": 0, "cache_write": 0, "skill": "i8-test", "tool": "Bash"},
            {"t": self.hour - 10 * 86400, "agent": "Old", "model": OPUS, "input": 7, "output": 0, "cache_read": 0, "cache_write": 0},
        ]
        folder = self.kept / "resources"
        folder.mkdir()
        (folder / usage.USAGE).write_text(self.jsonl(self.rows) + "{broken\n", encoding="utf-8")
        day = self.hour - self.hour % 86400
        (folder / "context.jsonl").write_text(self.jsonl([{"t": day, "agent": "Skills", "turns": {"12": 1, "30": 2, "99": 1}, "compactions": 2}]), encoding="utf-8")
        self.day = day

    def usage(self, query: str) -> tuple[int, dict | str]:
        status, _, body = self.get(f"/api/usage?{query}")
        return status, json.loads(body) if status == 200 else body.decode()

    def test_group_skill_answers_the_eight_columns_and_totals_equal_the_sum_of_the_token_rows(self):
        status, found = self.usage(f"group=skill&since={self.hour - 60}")
        self.assertEqual(status, 200, found)
        self.assertEqual([sorted(row) for row in found["rows"]], [COLUMNS] * 3)
        self.assertEqual([(row["key"], row["total"]) for row in found["rows"]], [("i8-test", 50000), ("", 6000), ("kvb-help", 4650)])
        kept = self.rows[:4]
        for name in ("input", "output", "cache_read", "cache_write"):
            self.assertEqual(found["total"][name], sum(row[name] for row in kept), name)
            self.assertEqual(sum(row[name] for row in found["rows"]), found["total"][name], name)
        costs = {row["key"]: row["cost"] for row in found["rows"]}
        self.assertIsNone(costs["i8-test"])
        self.assertAlmostEqual(costs[""], 0.041)
        self.assertAlmostEqual(costs["kvb-help"], 0.007275)
        self.assertIsNone(found["total"]["cost"])
        self.assertEqual(found["rows"][2]["hit_rate"], round(3000 / 4500, 4))
        self.assertFalse(found["split"])
        self.assertEqual(found["prices"]["date"], "2026-10-06")
        self.assertEqual(found["context"], [{"day": self.day, "agent": "Skills", "turns": 4, "median": 30000, "p90": 99000, "compactions": 2}])

    def test_a_filter_narrows_the_rows_and_group_tool_splits_a_message_of_several_tools(self):
        status, found = self.usage(f"group=tool&since={self.hour - 60}&skill=kvb-help")
        self.assertEqual(status, 200, found)
        self.assertTrue(found["split"])
        self.assertEqual([(row["key"], row["total"], row["share"]) for row in found["rows"]], [("Bash", 4100, 88.2), ("Read", 4100, 88.2), ("", 550, 11.8)])
        self.assertEqual(found["total"]["total"], 4650)
        status, found = self.usage(f"group=agent&since={self.hour - 60}&tool=Bash")
        self.assertEqual([(row["key"], row["total"]) for row in found["rows"]], [("Stage", 50000), ("Skills", 4100)])
        status, found = self.usage(f"group=account&since={self.hour - 60}&account=")
        self.assertEqual(found["total"]["total"], 50000 + 4100 + 550)
        status, found = self.usage(f"group=day&since={self.hour - 11 * 86400}&agent=Old")
        self.assertEqual([(row["key"], row["total"]) for row in found["rows"]], [(self.day - 10 * 86400, 7)])
        self.assertEqual(found["context"], [])

    def test_a_usage_file_larger_than_the_json_limit_streams_and_skips_an_overlong_line(self):
        path = self.kept / "resources" / usage.USAGE
        with path.open("r+b") as handle:
            handle.seek(0, 2)
            handle.seek(records.JSON_LIMIT + 1, 1)
            handle.write(b"\n" + self.jsonl([{**self.rows[0], "skill": "late"}]).encode())
        self.assertGreater(path.stat().st_size, records.JSON_LIMIT)
        status, found = self.usage(f"group=skill&since={self.hour - 60}")
        self.assertEqual(status, 200, found)
        self.assertEqual([(row["key"], row["total"]) for row in found["rows"]], [("i8-test", 50000), ("", 6000), ("kvb-help", 4650), ("late", 4100)])

    def test_an_unknown_group_or_key_and_a_missing_since_answer_400_and_a_foreign_host_403(self):
        for query in ("group=color&since=1", "group=skill&since=1&color=red", "group=skill", "group=skill&since=x", "group=skill&group=tool&since=1"):
            with self.subTest(query=query):
                self.assertEqual(self.usage(query)[0], 400)
        status, _, _ = self.call("GET", "/api/usage?group=skill&since=1", None, {"Host": "evil.example"})
        self.assertEqual(status, 403)
        status, _, _ = self.call("POST", "/api/usage?group=skill&since=1", b"{}", {"Host": self.host, "Content-Type": "application/json"})
        self.assertNotEqual(status, 200)


if __name__ == "__main__":
    unittest.main()
