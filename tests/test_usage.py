"""Exercise requirement 070: the sampler's usage tags and context, and the arithmetic of the usage view."""

from __future__ import annotations

import json
import unittest

import hub_support
import resources as sampler
import usage_tags as tags
from kvb_orchestrator import usage
from kvb_orchestrator.errors import ToolError
from test_resources_tokens import (
    HOUR,
    NOW,
    OPUS,
    SESSION,
    TokensCase,
    assistant,
    iso,
    lines,
)

SECRET = "SECRET-MARKER-070-never-stored"
DAY = 86400


def said(text: str) -> dict:
    return {"type": "text", "text": text}


def tool(name: str, given: dict) -> dict:
    return {"type": "tool_use", "id": "toolu_1", "name": name, "input": given}


def skill(name: str) -> dict:
    return tool("Skill", {"skill": name, "args": SECRET})


def turn(ts: float, ident: str, counts: tuple[int, int, int, int], blocks: list[dict], request: str = "", **row: object) -> dict:
    entry = assistant(ts, SESSION, OPUS, ident, counts, request)
    entry["message"]["content"] = blocks
    return {**entry, **row}


def boundary(ts: float, uuid: str) -> dict:
    return {"type": "system", "subtype": "compact_boundary", "sessionId": SESSION, "timestamp": iso(ts), "uuid": uuid, "isSidechain": False, "content": SECRET}


def summary(ts: float) -> dict:
    return {"type": "user", "sessionId": SESSION, "timestamp": iso(ts), "isCompactSummary": True, "message": {"role": "user", "content": SECRET}}


def asked(**query: str) -> dict[str, list[str]]:
    return {name: [value] for name, value in query.items()}


class UsageCase(TokensCase):
    def tagged(self) -> list[dict]:
        path = self.state / sampler.USAGE
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []

    def per(self, name: str) -> dict[str, int]:
        found: dict[str, int] = {}
        for entry in self.tagged():
            found[entry.get(name, "")] = found.get(entry.get(name, ""), 0) + entry["input"]
        return found

    def context(self) -> list[dict]:
        path = self.state / "context.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []

    def view(self, **query: str) -> dict:
        return usage.usage_view(self.state, asked(**query), NOW + HOUR)


class TestTagging(UsageCase):
    def test_a_skill_call_tags_the_later_messages_of_the_session_and_the_earlier_ones_carry_none(self):
        self.transcript.write_text(lines([
            turn(NOW + 10, "msg_0", (1, 0, 0, 0), [said(SECRET)]),
            turn(NOW + 20, "msg_1", (2, 0, 0, 0), [skill("kvb-help")]),
            turn(NOW + 30, "msg_2", (4, 0, 0, 0), [said("a")]),
            turn(NOW + 40, "msg_3", (8, 0, 0, 0), [said("b")]),
        ]), encoding="utf-8")
        self.count()
        self.assertEqual(self.per("skill"), {"": 3, "kvb-help": 12})
        self.assertEqual(self.offsets()["skills"], {SESSION: [[NOW + 20, "kvb-help"]]})
        with self.transcript.open("a", encoding="utf-8") as handle:
            handle.write(lines([turn(NOW + 50, "msg_4", (16, 0, 0, 0), [said("c")])]))
        self.count(now=NOW + 180)
        self.assertEqual(self.per("skill"), {"": 3, "kvb-help": 28})

    def test_a_message_over_three_lines_with_two_tool_uses_counts_once_and_under_each_tool_once(self):
        parts = [[{"type": "thinking", "thinking": SECRET}], [tool("Bash", {"command": SECRET})], [tool("Read", {"file_path": "/x"})]]
        self.transcript.write_text(lines([turn(NOW + 10 + index, "msg_1", (10, 20, 30, 40), blocks, "req_1") for index, blocks in enumerate(parts)]), encoding="utf-8")
        self.count()
        self.assertEqual([(entry["tool"], entry["input"]) for entry in self.tagged()], [("Bash,Read", 10)])
        found = self.view(group="tool", since=str(NOW - HOUR))
        self.assertTrue(found["split"])
        self.assertEqual([(row["key"], row["total"], row["share"]) for row in found["rows"]], [("Bash", 100, 100.0), ("Read", 100, 100.0)])
        self.assertEqual(found["total"]["total"], 100)
        self.assertEqual(self.view(group="skill", since=str(NOW - HOUR))["total"]["total"], 100)

    def test_a_sidechain_transcript_carries_its_agent_type_and_the_main_thread_none(self):
        subagents = self.projects / "-repo" / SESSION / "subagents"
        subagents.mkdir(parents=True)
        self.transcript.write_text(lines([turn(NOW + 10, "msg_1", (1, 0, 0, 0), [said("x")])]), encoding="utf-8")
        (subagents / "agent-a1.jsonl").write_text(lines([turn(NOW + 20, "msg_2", (2000, 0, 0, 0), [tool("Grep", {"pattern": SECRET})], isSidechain=True)]), encoding="utf-8")
        (subagents / "agent-a1.meta.json").write_text(json.dumps({"agentType": "Explore", "description": SECRET}), encoding="utf-8")
        (subagents / "agent-b2.jsonl").write_text(lines([turn(NOW + 30, "msg_3", (4, 0, 0, 0), [said("y")], isSidechain=True)]), encoding="utf-8")
        self.count()
        self.assertEqual(self.per("subagent"), {"": 1, "Explore": 2000, tags.UNTYPED: 4})
        self.assertEqual([sum(row["turns"].values()) for row in self.context()], [1])

    def test_a_51st_skill_within_one_hour_lands_in_other(self):
        rows = []
        for index in range(51):
            rows += [turn(NOW + 10 * index, f"call_{index}", (0, 0, 0, 0), [skill(f"skill-{index:02d}")]), turn(NOW + 10 * index + 5, f"msg_{index}", (1000 - index, 0, 0, 0), [said("z")])]
        self.transcript.write_text(lines(rows), encoding="utf-8")
        self.count()
        found = self.per("skill")
        self.assertEqual(set(found), {*(f"skill-{index:02d}" for index in range(50)), tags.OTHER})
        self.assertEqual(found[tags.OTHER], 950)

    def test_the_repo_is_the_base_name_of_the_git_top_level_of_the_cwd(self):
        top = self.state.parent / "work" / "demo"
        (top / ".git").mkdir(parents=True)
        (top / "sub").mkdir()
        self.transcript.write_text(lines([
            turn(NOW + 10, "msg_1", (1, 0, 0, 0), [said("a")], cwd=str(top / "sub")),
            turn(NOW + 20, "msg_2", (2, 0, 0, 0), [said("b")], cwd="relative/dir"),
        ]), encoding="utf-8")
        self.count()
        self.assertEqual(self.per("repo"), {"demo": 1, "": 2})

    def test_context_per_turn_and_compactions_count_per_day_and_agent_and_a_copied_boundary_once(self):
        self.transcript.write_text(lines([
            turn(NOW + 10, "msg_1", (2000, 0, 10000, 0), [said("a")]),
            turn(NOW + 20, "msg_2", (500, 0, 30000, 0), [said("b")]),
            turn(NOW + 30, "msg_3", (1000, 0, 30000, 5000), [said("c")]),
            boundary(NOW + 40, "u-1"),
            summary(NOW + 41),
            turn(NOW + 50, "msg_4", (99999, 7, 0, 0), [said("d")]),
        ]), encoding="utf-8")
        self.count()
        fork = self.projects / "-repo" / "fork.jsonl"
        fork.write_text(lines([boundary(NOW + 40, "u-1")]), encoding="utf-8")
        self.count(now=NOW + 180)
        day = NOW - NOW % DAY
        self.assertEqual(sampler.CONTEXT, "context.jsonl")
        merged = tags.compact_context(self.context(), NOW)
        self.assertEqual(merged, [{"t": day, "agent": "Skills", "turns": {"12": 1, "30": 1, "31": 1, "99": 1}, "compactions": 1}])
        found = self.view(group="agent", since=str(day))["context"]
        self.assertEqual(found, [{"day": day, "agent": "Skills", "turns": 4, "median": 30000, "p90": 99000, "compactions": 1}])

    def test_no_output_file_and_no_view_holds_prompt_text_tool_input_or_output(self):
        subagents = self.projects / "-repo" / SESSION / "subagents"
        subagents.mkdir(parents=True)
        self.transcript.write_text(lines([
            {"type": "user", "sessionId": SESSION, "timestamp": iso(NOW + 5), "message": {"role": "user", "content": SECRET}},
            turn(NOW + 10, "msg_1", (5, 1, 0, 0), [said(SECRET), skill("kvb-help"), tool("Bash", {"command": SECRET})]),
            {"type": "user", "sessionId": SESSION, "timestamp": iso(NOW + 12), "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": SECRET}]}},
            boundary(NOW + 20, "u-9"),
            summary(NOW + 21),
        ]), encoding="utf-8")
        (subagents / "agent-a1.jsonl").write_text(lines([turn(NOW + 30, "msg_3", (1, 0, 0, 0), [said(SECRET)], isSidechain=True)]), encoding="utf-8")
        (subagents / "agent-a1.meta.json").write_text(json.dumps({"agentType": SECRET + " with spaces", "description": SECRET}), encoding="utf-8")
        self.count(now=NOW + 30)
        files = sorted(path for path in self.state.rglob("*") if path.is_file())
        self.assertEqual([path.name for path in files], ["context.jsonl", "offsets.json", "tokens.jsonl", "usage.jsonl"])
        for path in files:
            self.assertNotIn(SECRET, path.read_text(encoding="utf-8"), path.name)
        for group in usage.GROUPS:
            self.assertNotIn(SECRET, json.dumps(self.view(group=group, since=str(NOW - HOUR))), group)
        self.assertEqual(self.per("skill"), {"": 5, "kvb-help": 1})


class TestTokenRowsUnchanged(UsageCase):
    def test_tokens_jsonl_keeps_the_old_key_set_and_one_row_per_hour_agent_and_model_after_a_tagged_run(self):
        self.transcript.write_text(lines([
            turn(NOW + 10, "msg_1", (1, 0, 0, 0), [skill("kvb-help")], cwd="/nowhere"),
            turn(NOW + 20, "msg_2", (2, 0, 0, 0), [tool("Bash", {"command": "ls"})]),
            turn(NOW + 30, "msg_3", (4, 0, 0, 0), [tool("Read", {"file_path": "/x"})]),
        ]), encoding="utf-8")
        self.count(now=NOW + 30)
        self.assertEqual(self.written(), [{"t": NOW, "agent": "Skills", "model": OPUS, "input": 7, "output": 0, "cache_read": 0, "cache_write": 0}])
        self.assertEqual(sorted((row.get("skill", ""), row.get("tool", "")) for row in self.tagged()), [("", "Skill"), ("kvb-help", "Bash"), ("kvb-help", "Read")])
        self.assertEqual(sum(row["input"] for row in self.tagged()), 7)


class TestUsageArithmetic(unittest.TestCase):
    def test_the_estimate_equals_the_hand_computed_price_and_an_unknown_model_gives_null(self):
        self.assertEqual(usage.PRICES, hub_support.HUB / "kvb_orchestrator" / "prices.json")
        families = usage.prices()["families"]
        row = {"model": "claude-opus-5-5", "input": 1_000_000, "output": 100_000, "cache_read": 2_000_000, "cache_write": 400_000}
        self.assertAlmostEqual(usage.cost(row, families), 4 + 2 + 0.8 + 2)
        self.assertAlmostEqual(usage.cost({**row, "model": "claude-fable-5-1", "output": 0, "cache_read": 0, "cache_write": 0}, families), 10)
        self.assertIsNone(usage.cost({**row, "model": "gpt-x"}, families))
        total = usage.blank()
        usage.added(total, usage.entry({"t": NOW, "model": "claude-haiku-5-5", "input": 1000}), families)
        self.assertAlmostEqual(total["cost"], 0.0001)
        usage.added(total, usage.entry({"t": NOW, "model": "gpt-x", "input": 1}), families)
        self.assertIsNone(usage.finished("k", total, 1001)["cost"])

    def test_every_family_prices_cache_read_at_a_tenth_and_cache_write_at_one_and_a_quarter_of_input(self):
        table = usage.prices()
        self.assertEqual((table["date"], sorted(table["families"])), ("2026-10-06", ["fable", "haiku", "opus", "sonnet"]))
        for name, found in table["families"].items():
            self.assertAlmostEqual(found["cache_read"], found["input"] * 0.1, msg=name)
            self.assertAlmostEqual(found["cache_write"], found["input"] * 1.25, msg=name)

    def test_the_cache_hit_rate_is_cache_read_over_input_plus_cache_read(self):
        total = {"input": 100, "output": 7, "cache_read": 300, "cache_write": 9, "cost": 0.0}
        found = usage.finished("k", total, 832)
        self.assertEqual((found["hit_rate"], found["total"], found["share"]), (0.75, 416, 50.0))
        self.assertIsNone(usage.finished("k", {**total, "input": 0, "cache_read": 0}, 0)["hit_rate"])

    def test_the_quantiles_take_the_nearest_rank_without_a_float_round_up(self):
        turns = dict.fromkeys(range(1, 11), 1)
        self.assertEqual((usage.quantile(turns, 1, 2), usage.quantile(turns, 9, 10)), (5000, 9000))
        self.assertIsNone(usage.quantile({}, 1, 2))

    def test_folding_keeps_the_fifty_largest_values_and_breaks_ties_by_name(self):
        sums = {(NOW, "A", "m", HOUR, "", f"v{index:02d}", "", "", ""): [1, 0, 0, 0] for index in range(51)}
        folded = tags.fold(sums)
        self.assertEqual(sorted(key[5] for key in folded), sorted([*(f"v{index:02d}" for index in range(50)), tags.OTHER]))
        self.assertEqual(sum(sum(counts) for counts in folded.values()), 51)

    def test_an_old_row_without_tags_reads_as_empty_tags(self):
        old = {"t": NOW, "agent": "A", "model": OPUS, "input": 1, "output": 2, "cache_read": 3, "cache_write": 4}
        self.assertEqual(tags.row_tags(old), ("", "", "", ""))
        self.assertEqual(usage.entry(old), {**old, "skill": "", "tool": "", "subagent": "", "repo": "", "account": ""})

    def test_the_trim_merges_the_open_window_folds_old_days_and_streams_settled_rows_through(self):
        now = NOW + 30
        settled = {"t": NOW - 5 * DAY, "agent": "A", "model": OPUS, "input": 1, "output": 0, "cache_read": 0, "cache_write": 0, "skill": "s"}
        daily = {**settled, "t": NOW - NOW % DAY - 200 * DAY, "width": DAY}
        stale = {**settled, "t": NOW - 95 * DAY, "tool": "Bash"}
        fresh = {**settled, "t": NOW - HOUR, "tool": "Read"}
        raw = [json.dumps(row).encode() + b"\n" for row in (settled, daily, stale, stale, fresh, fresh)] + [b"{broken\n"]
        found = [json.loads(line) for line in tags.trimmed(iter(raw), now, now - 90 * DAY)]
        day = stale["t"] - stale["t"] % DAY
        self.assertEqual(found, [settled, daily, {**stale, "t": day, "width": DAY, "input": 2}, {**fresh, "input": 2}])
        self.assertEqual(next(iter(tags.trimmed(iter(raw[:1]), now, now - 90 * DAY))), raw[0].decode())

    def test_the_query_rejects_an_unknown_group_or_key_and_a_missing_since(self):
        for query in (asked(group="color", since="1"), asked(group="skill", since="1", color="red"), asked(group="skill"), asked(group="skill", since="9", until="5"), {"group": ["skill", "tool"], "since": ["1"]}):
            with self.subTest(query=query), self.assertRaises(ToolError):
                usage.parsed(query, NOW)
        self.assertEqual(usage.parsed(asked(group="hour", since="1", tool=""), NOW), ("hour", 1.0, NOW, {"tool": ""}))


if __name__ == "__main__":
    unittest.main()
