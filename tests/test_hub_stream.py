from __future__ import annotations

import json
import os
import time
import unittest
from unittest import mock

from hub_case import HubCase
from hub_support import ASK, iso
from kvb_orchestrator import events, transcripts


class TestHubStream(HubCase):
    def test_stream_reads_transcripts_with_filters_and_agent_names(self):
        now = time.time()
        self.claim("s1", "Skills session")
        main = self.projects / "-repo" / "s1.jsonl"
        sub = self.projects / "-repo" / "s1" / "subagents" / "agent-abc.jsonl"
        other = self.projects / "-other" / "s2.jsonl"
        old = self.projects / "-other" / "s3.jsonl"
        for path in (main.parent, sub.parent, other.parent):
            path.mkdir(parents=True, exist_ok=True)
        main.write_text(self.jsonl([
            {"type": "user", "sessionId": "s1", "timestamp": iso(now - 50), "message": {"role": "user", "content": "hello agent"}},
            {"type": "assistant", "sessionId": "s1", "timestamp": iso(now - 40), "message": {"role": "assistant", "content": [
                {"type": "thinking", "thinking": "hidden"}, {"type": "text", "text": "on it"}, {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}]}},
            {"type": "user", "sessionId": "s1", "timestamp": iso(now - 30), "message": {"role": "user", "content": [{"type": "tool_result", "content": "x" * 2500}]}},
            {"type": "system", "sessionId": "s1", "timestamp": iso(now - 20), "content": "compacted"},
            {"type": "attachment", "sessionId": "s1", "timestamp": iso(now - 20), "attachment": {}},
        ]) + "not json\n", encoding="utf-8")
        sub.write_text(self.jsonl([{"type": "user", "sessionId": "s1", "agentId": "abc", "timestamp": iso(now - 10), "message": {"role": "user", "content": "SUB task"}}]), encoding="utf-8")
        other.write_text(self.jsonl([{"type": "user", "sessionId": "s2", "timestamp": iso(now - 5), "message": {"role": "user", "content": "other"}}]), encoding="utf-8")
        old.write_text(self.jsonl([{"type": "user", "sessionId": "s3", "timestamp": iso(now - 9 * 86400), "message": {"role": "user", "content": "ancient"}}]), encoding="utf-8")
        os.utime(old, (now - 9 * 86400, now - 9 * 86400))

        def entries(query: str) -> list[dict]:
            status, _, body = self.get(f"/api/stream?{query}")
            self.assertEqual(status, 200, body)
            return json.loads(body)["entries"]

        with mock.patch.object(transcripts, "STREAM_SCAN", 0):
            rows = entries("")
            self.assertEqual([(row["kind"], row["agent"], row["sub"], row["text"][:11]) for row in rows], [
                ("user", "Skills", "", "hello agent"),
                ("assistant", "Skills", "", "on it"),
                ("tool_call", "Skills", "", 'Bash {"comm'),
                ("tool_result", "Skills", "", "xxxxxxxxxxx"),
                ("system", "Skills", "", "compacted"),
                ("user", "Skills", "abc", "SUB task"),
                ("user", "", "", "other"),
            ])
            result = rows[3]
            self.assertEqual((len(result["text"]), result["truncated"]), (2000, True))
            status, _, body = self.get(f"/api/stream/{result['id']}")
            self.assertEqual((status, len(json.loads(body)["text"])), (200, 2500))
            self.assertEqual(self.get("/api/stream/999999")[0], 404)
            self.assertEqual(len(entries("agent=Skills")), 6)
            self.assertEqual([row["text"] for row in entries("session=s2")], ["other"])
            self.assertEqual([row["kind"] for row in entries("kind=tool_call,system")], ["tool_call", "system"])
            self.assertEqual([row["text"] for row in entries("q=sub")], ["SUB task"])
            self.assertEqual([row["text"] for row in entries(f"from={now - 45}&to={now - 15}")][1:], ["Bash {\"command\": \"ls\"}", "x" * 2000, "compacted"])
            self.assertEqual(len(entries("limit=2")), 2)
            for query in ("kind=bogus", "from=soon", "after=-1", "limit=x"):
                with self.subTest(query=query):
                    self.assertEqual(self.get(f"/api/stream?{query}")[0], 400)
            status, _, body = self.get("/api/stream")
            last = json.loads(body)["last"]
            with main.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"type": "user", "sessionId": "s1", "timestamp": iso(now), "message": {"role": "user", "content": "fresh"}}) + "\n")
                handle.write('{"type": "user", "partial')
            self.assertEqual([row["text"] for row in entries(f"after={last}")], ["fresh"])
        self.assertNotIn("ancient", json.dumps(entries("")))

    def test_saved_views_filter_the_event_stream(self):
        now = time.time()
        self.claim("s1", "Skills session")
        register = {
            "operator/push": {"title": "git-sign-push", "workdir": "/repo", "status": "queued", "check": "manual", "roles": {}},
            "work/a": {"title": "A", "status": "queued", "roles": {}},
        }
        news = [{"ts": now - 30, "from": "Docs", "to": ["Skills"], "text": "hello"}, {"ts": now - 20, "from": "Docs", "to": [], "text": "MAYDAY disk full"}]
        self.write_council({"rasci.json": register, "news.jsonl": self.jsonl(news)})
        self.request("feat: view", "")
        self.create_ask(ASK)
        self.decision("")

        def kinds(query: str) -> list[str]:
            return [row["kind"] for row in self.events(query)["events"]]

        self.assertEqual(sorted(set(kinds("view=fuer-dich"))), ["ask", "decision", "operator", "radio", "review"])
        self.assertEqual([row["text"] for row in self.events("view=fuer-dich")["events"] if row["kind"] == "radio"], ["MAYDAY disk full"])
        self.assertEqual(kinds("kinds=review"), ["review"])
        self.assertEqual(kinds("view=funk"), ["radio", "radio"])
        self.assertEqual(sorted(set(kinds("view=arbeit"))), ["ask", "decision", "operator", "review"])
        self.assertEqual(kinds("kinds=decision"), ["decision"])
        self.assertEqual(kinds("kinds=radio&q=mayday"), ["radio"])
        self.assertEqual(kinds("kinds=ask,decision&waiting=1"), ["ask", "decision"])
        self.assertEqual(kinds("kinds=radio&agent=Docs"), ["radio", "radio"])
        self.assertEqual(kinds("kinds=register,rename"), [])
        self.write_council({"rasci.json": {**register, "work/a": {**register["work/a"], "status": "running"}}})
        self.assertEqual([(row["title"], row["text"]) for row in self.events("kinds=register,rename")["events"]], [("work/a", "status: queued → running")])
        for query in ("view=bogus", "view=reviews", "kinds=bogus", "parts=bogus", "after=x"):
            with self.subTest(query=query):
                self.assertEqual(self.get(f"/api/events?{query}")[0], 400)
        sample = events.event({"id": "x", "ts": now, "kind": "review", "title": "feat: x", "waiting": True})
        filters = events.event_filters({"kinds": ["review"]})
        self.assertTrue(events.wanted(sample, filters))
        self.assertFalse(events.wanted({**sample, "kind": "radio"}, filters))
        self.assertFalse(events.wanted({**sample, "waiting": False}, events.event_filters({"view": ["fuer-dich"]})))

    def test_crons_come_from_transcripts_timers_and_the_queue(self):
        now = time.time()
        self.claim("s1", "Skills session")
        main = self.projects / "-repo" / "s1.jsonl"
        main.parent.mkdir(parents=True)

        def use(ts: float, ident: str, name: str, data: dict) -> dict:
            return {"type": "assistant", "sessionId": "s1", "timestamp": iso(ts), "message": {"role": "assistant", "content": [{"type": "tool_use", "id": ident, "name": name, "input": data}]}}

        def result(ts: float, ident: str, text: str) -> dict:
            return {"type": "user", "sessionId": "s1", "timestamp": iso(ts), "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": ident, "content": text}]}}

        main.write_text(self.jsonl([
            use(now - 60, "t1", "CronCreate", {"cron": "*/5 * * * *", "prompt": "check deploy", "recurring": True}),
            result(now - 59, "t1", "Scheduled recurring job c0ac4c97 (Every 5 minutes). Session-only."),
            use(now - 50, "t2", "CronCreate", {"cron": "7 * * * *", "prompt": "iterate", "recurring": True}),
            result(now - 49, "t2", "Scheduled recurring job 0a929f2d (Every hour at :07)."),
            use(now - 40, "t3", "CronDelete", {"id": "c0ac4c97"}),
            use(now - 35, "t4", "ScheduleWakeup", {"delaySeconds": 60, "reason": "first", "prompt": "/loop"}),
            use(now - 30, "t5", "ScheduleWakeup", {"delaySeconds": 1200, "reason": "fallback", "prompt": "/loop"}),
            use(now - 20, "t6", "Bash", {"command": "make test", "run_in_background": True, "description": "gate"}),
            use(now - 10, "t7", "Bash", {"command": "ls"}),
        ]), encoding="utf-8")
        (self.timers / "kvb-dream-notify.timer").write_text("[Unit]\nDescription=Daily dream\n[Timer]\nOnCalendar=*-*-* 08:00:00\n", encoding="utf-8")
        (self.timers / "timers.target.wants").mkdir()
        (self.timers / "timers.target.wants" / "kvb-dream-notify.timer").write_text("", encoding="utf-8")
        (self.timers / "old.timer").write_text("[Timer]\nOnUnitActiveSec=1h\n", encoding="utf-8")
        entry = {"id": "gate-1", "kind": "gate", "task": "work/hub", "status": "active", "enqueued": now - 5, "cmd": "make test", "name": "Skills session", "session": "s1"}
        self.write_council({"queue.json": {"seq": 1, "entries": [entry, "broken"]}})

        def crons() -> dict:
            with mock.patch.object(transcripts, "STREAM_SCAN", 0):
                rows = self.events("kinds=cron")["events"]
            return {row["title"]: (row["ref"]["active"], row["agent"], row["text"]) for row in rows}

        self.assertEqual(crons(), {
            "Cron: */5 * * * *": (False, "Skills", "check deploy"),
            "Cron: 7 * * * *": (True, "Skills", "iterate"),
            "Wakeup: in 60 s": (False, "Skills", "/loop\nfirst"),
            "Wakeup: in 1200 s": (True, "Skills", "/loop\nfallback"),
            "Background: gate": (True, "Skills", "make test"),
            "Timer: *-*-* 08:00:00": (True, "", "Daily dream\nkvb-dream-notify.timer"),
            "Timer: 1h": (False, "", "old.timer"),
            "Queue: gate · running": (True, "Skills", "make test\nwork/hub"),
        })
        self.write_council({"work/s1/claim.json": {"office": "work/s1", "session": "s1", "runtime": "claude", "name": "Skills session", "since": "2026-11-05T08:00:00+00:00", "beat": now - 3600, "work": "x"}})
        self.assertEqual(crons()["Cron: 7 * * * *"][0], False)
        subagents = self.projects / "-repo" / "s1" / "subagents"
        subagents.mkdir(parents=True)
        (subagents / "agent-abc.meta.json").write_text(json.dumps({"agentType": "general-purpose", "description": "review", "spawnDepth": 1, "finished": True, "toolUseId": "t8"}), encoding="utf-8")
        (subagents / "agent-def.meta.json").write_text(json.dumps({"agentType": "Explore", "description": "find", "spawnDepth": 2, "finished": False, "toolUseId": "t9"}), encoding="utf-8")
        status, _, body = self.get("/api/subagents?session=s1")
        self.assertEqual(status, 200, body)
        self.assertEqual([(row["id"], row["type"], row["depth"], row["finished"]) for row in json.loads(body)["subagents"]], [("abc", "general-purpose", 1, True), ("def", "Explore", 2, False)])
        self.assertEqual(self.get("/api/subagents?session=../x")[0], 400)


if __name__ == "__main__":
    unittest.main()
