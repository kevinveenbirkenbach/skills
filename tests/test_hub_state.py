from __future__ import annotations

import json
import time
import unittest
from unittest import mock

from hub_case import HubCase
from hub_engines import OPERATOR_VOICE, VOICES
from hub_support import ASK
from kvb_orchestrator import council, engines, exchange, phrasing, view


class TestHubState(HubCase):
    def test_state_follows_the_time_window(self):
        now = time.time()
        self.write_council({"news.jsonl": self.jsonl([
            {"ts": now - 10800, "from": "Old", "to": [], "text": "three hours"},
            {"ts": now - 3600, "from": "Skills", "to": ["Docs"], "text": "one hour"},
            {"ts": now - 60, "from": "Docs", "to": [], "text": "a minute"},
        ])})
        self.request("feat: fresh", "")
        self.create_ask(ASK)
        default = self.snapshot()
        self.assertEqual([row["text"] for row in default["radio"]], ["three hours", "one hour", "a minute"])
        self.assertAlmostEqual(default["first"], now - 10800, delta=1)
        status, _, body = self.get(f"/api/state?from={now - 7200}&to={now - 1800}")
        self.assertEqual(status, 200, body)
        past = json.loads(body)
        self.assertEqual([row["text"] for row in past["radio"]], ["one hour"])
        self.assertEqual((past["since"], past["until"]), (now - 7200, now - 1800))
        self.assertEqual((past["reviews"], past["asks"]), ([], []))
        self.assertEqual({(edge["source"], edge["target"]) for edge in past["graph"]["edges"]}, {("name:Skills", "name:Docs")})
        future = json.loads(self.get(f"/api/state?from=0&to={now + 86400}")[2])
        self.assertLessEqual(future["until"], time.time())
        self.assertEqual(len(future["radio"]), 3)
        for query in (f"from={now}&to={now - 60}", "from=soon", "to=-1", "from=1&from=2", "from=nan"):
            with self.subTest(query=query):
                self.assertEqual(self.get(f"/api/state?{query}")[0], 400)

    def test_get_never_changes_state(self):
        review_id = self.request("feat: read only", "")
        before = (self.state / "reviews.json").read_bytes()
        for path, expected in (
            ("/", 200),
            ("/?approve=1", 200),
            ("/api/state", 200),
            (f"/reviews/{review_id}/page", 200),
            (f"/reviews/{review_id}/files", 200),
            ("/reviews/0123456789abcdef/files", 404),
            (f"/reviews/{review_id}/approve", 405),
            (f"/reviews/{review_id}/reject", 405),
            (f"/api/reviews/{review_id}", 200),
            ("/api/reviews/0123456789abcdef", 404),
            ("/api/sign", 405),
            ("/api/rules/sign", 405),
            ("/mcp", 405),
            ("/api/tts", 405),
            ("/api/stt", 405),
            ("/reviews/0123456789abcdef/page", 404),
            ("/nope", 404),
        ):
            with self.subTest(path=path):
                status, _, _ = self.call("GET", path, None, self.guard(self.host))
                self.assertEqual(status, expected)
        self.assertEqual(self.call("GET", "/", None, {"Host": "evil.example"})[0], 403)
        self.assertEqual((self.state / "reviews.json").read_bytes(), before)
        self.assertEqual(self.status(review_id), "pending")

    def test_state_is_empty_without_council_files(self):
        empty = {"reviews": [], "operator": [], "register": [], "radio": [], "claims": [], "grants": []}
        state = self.snapshot()
        self.assertEqual({key: state[key] for key in empty}, empty)
        self.assertEqual([(node["id"], node["kind"]) for node in state["graph"]["nodes"]], [("Operator", "operator"), ("name:Maintainer", "chair")])
        self.assertEqual(state["graph"]["edges"], [])
        self.index()
        self.write_council({"rasci.json": "{not json", "queue-history.jsonl": "[" * 100000 + "\n", "work/x/claim.json": "[1]"})
        (self.council / "news.jsonl").write_bytes(b"\xff\xfe" + b"[" * 100000 + b"\n")
        state = self.snapshot()
        self.assertEqual({key: state[key] for key in empty}, empty)
        self.write_council({"rasci.json": "[1, 2]", "news.jsonl": "[" * 100000 + "\n"})
        self.assertEqual(self.snapshot()["radio"], [])
        self.index()

    def test_state_filters_the_register_and_bounds_the_radio(self):
        register = {
            "operator/push-skills": {"title": "git-sign-push", "workdir": "/repo", "description": "needs the key", "check": "pushed", "status": "queued", "roles": {"Operator": "R", "One": "A"}},
            "operator/old": {"title": "old command", "status": "done", "roles": {}},
            "work/hub": {"title": "Build the hub", "status": "running", "worker": "One", "objective": "Reviews in the browser", "roles": {"One": "RA", "Two": "C"}, "key_results": [{"text": "a", "met": True}, {"text": "b", "met": False}]},
            "work/finished": {"title": "Finished work", "status": "done", "roles": {}},
            "work/stopped": {"title": "Stopped work", "status": "stopped", "roles": {}},
            "work/bare": {"roles": {"Two": "R"}},
            "broken": "not a row",
        }
        now = time.time()
        rows = [{"ts": now - 100 + n, "from": "One", "to": [], "text": f"item {n:02d}"} for n in range(34)]
        rows.append({"ts": now, "from": "Two", "to": [], "text": "disk full", "class": "mayday"})
        lines = [json.dumps(row) for row in rows[:20]] + ["not json", json.dumps({"text": "no ts"})] + [json.dumps(row) for row in rows[20:]]
        self.write_council({"rasci.json": register, "news.jsonl": "\n".join(lines) + "\n"})
        with mock.patch.object(council, "RADIO_LIMIT", 30):
            state = self.snapshot()
        operator = state["operator"]
        self.assertEqual([(row["task"], row["command"], row["why"], row["status"]) for row in operator], [("operator/push-skills", "git-sign-push", "needs the key", "queued")])
        self.assertEqual([row["task"] for row in state["register"]], ["work/bare", "work/hub"])
        hub = state["register"][1]
        self.assertEqual((hub["title"], hub["responsible"], hub["accountable"], hub["met"], hub["total"]), ("Build the hub", "One", "One", 1, 2))
        self.assertEqual(state["register"][0]["status"], "queued")
        texts = [row["text"] for row in state["radio"]]
        self.assertEqual(len(texts), 30)
        self.assertEqual((texts[0], texts[-2], texts[-1]), ("item 05", "item 33", "disk full"))
        self.assertEqual(state["radio"][-1]["class"], "mayday")

    def test_state_collects_radio_claims_grants_and_the_graph(self):
        now = time.time()
        register = {
            "operator/push": {"title": "git-sign-push", "workdir": "/repo", "status": "blocked", "roles": {"Operator": "R", "Skills session": "A"}},
            "work/hub": {"title": "Build the hub", "status": "running", "worker": "Skills session", "workdir": "/repo/.worktrees/hub", "roles": {"Skills session": "R", "Maintainer": "A"}},
            "work/sub": {"title": "Helper", "status": "running", "worker": "subagent general-purpose (default)", "roles": {"Skills": "A"}},
            "work/old": {"title": "Old", "status": "done", "worker": "Ghost session", "roles": {}},
        }
        news = [
            {"ts": now - 50, "from": "Skills session", "to": ["Maintainer"], "text": "ready"},
            {"ts": now - 40, "from": "Skills", "to": ["Maintainer"], "text": "again", "class": "direct"},
            {"ts": now - 30, "from": "Maintainer", "to": [], "text": "board"},
            {"ts": now - 20, "from": "Docs", "to": [], "text": "MAYDAY disk full"},
            {"ts": now - 10, "from": "Docs", "to": ["Skills"], "text": "PAN-PAN slow"},
            {"ts": now - 5, "from": "Maintainer", "to": ["Skills", "Docs"], "text": "rotate", "class": "security"},
            {"ts": now - 2 * 86400, "from": "Old", "to": [], "text": "too old"},
        ]
        claim = {"office": "work/hub", "session": "s1", "runtime": "claude", "name": "Skills", "since": "2026-11-05T10:00:00+00:00", "beat": now, "work": "build the hub"}
        gate = {"office": "cluster/gate", "session": "s2", "runtime": "codex", "name": "Gatekeeper", "since": "2026-11-05T09:00:00+00:00", "beat": now, "work": "gate"}
        history = [
            {"id": "q1", "kind": "gate", "signature": "make test", "workdir": "/repo/.worktrees/hub/sub", "start": now - 15, "end": now - 5, "exit": 0, "minutes": 0.2},
            {"id": "q2", "kind": "deploy", "signature": "make deploy", "workdir": "/elsewhere", "start": now - 15, "end": now - 5, "exit": 0, "minutes": 0.2},
            {"id": "q3", "kind": "gate", "signature": "make test", "workdir": "/repo/.worktrees/hub", "start": now - 2 * 86400, "end": now - 2 * 86400 + 60, "exit": 0, "minutes": 1},
        ]
        self.write_council({
            "rasci.json": register,
            "news.jsonl": self.jsonl(news),
            "work/hub/claim.json": claim,
            "cluster/gate/claim.json": gate,
            "work/broken/claim.json": "not json",
            "queue-history.jsonl": self.jsonl(history),
        })
        state = self.snapshot()
        self.assertEqual(
            set(state),
            {
                "now", "since", "until", "first", "alarm_since", "reviews", "asks", "decisions", "messages", "operator",
                "register", "priority", "radio", "claims", "grants", "night", "silence", "graph",
                "inbox", "pending", "rules", "approvers", "jobs", "views", "llm", "people", "settings", "media", "speech",
                "badges", "kinds",
            },
        )
        self.assertEqual([row["speech"] for row in state["radio"]], [
            "Maintainer, Maintainer, this is Skills, ready, over",
            "Maintainer, Maintainer, this is Skills, again, over",
            "all stations, this is Maintainer, board, out",
            "MAYDAY MAYDAY MAYDAY, this is Docs Docs Docs, disk full, over",
            "PAN-PAN PAN-PAN PAN-PAN, all stations, this is Docs, slow, over",
            "SECURITE SECURITE SECURITE, all stations, this is Maintainer, rotate, over",
        ])
        speech = self.httpd.hub.speech
        self.assertEqual([row["voice"] for row in state["radio"]], [speech.voice_of(row["source"]) for row in state["radio"]])
        self.assertTrue(all(row["voice"] in VOICES and row["voice"] != OPERATOR_VOICE for row in state["radio"]))
        self.assertEqual(state["speech"], {
            "tts": True, "stt": True, "tts_off": "", "stt_off": "", "voices": len(VOICES), "operator": OPERATOR_VOICE, "sample": "all stations, this is Operator, radio check, out",
            "limit": phrasing.SPEECH_LIMIT, "rate": engines.STT_RATE, "seconds": engines.STT_SECONDS,
        })
        self.assertAlmostEqual(state["now"] - state["since"], view.RADIO_WINDOW)
        self.assertEqual((state["night"], state["silence"], state["priority"]), ("day", None, ["Skills session", "subagent general-purpose (default)"]))
        radio = [(row["from"], row["to"], row["class"], row["text"]) for row in state["radio"]]
        self.assertEqual(radio, [
            ("Skills", ["Maintainer"], "post", "ready"),
            ("Skills", ["Maintainer"], "post", "again"),
            ("Maintainer", [], "newsletter", "board"),
            ("Docs", [], "mayday", "MAYDAY disk full"),
            ("Docs", ["Skills"], "pan-pan", "PAN-PAN slow"),
            ("Maintainer", ["Skills", "Docs"], "security", "rotate"),
        ])
        self.assertEqual([(row["office"], row["agent"], row["runtime"]) for row in state["claims"]], [("cluster/gate", "Gatekeeper", "codex"), ("work/hub", "Skills", "claude")])
        self.assertEqual([(row["to"], row["kind"], row["id"]) for row in state["grants"]], [("Skills", "gate", "q1")])
        self.assertEqual([row["task"] for row in state["operator"]], ["operator/push"])
        nodes = {node["id"]: node for node in state["graph"]["nodes"]}
        moon = "subagent general-purpose (default) @ s1"
        self.assertEqual(list(nodes), ["Operator", "name:Maintainer", "name:Docs", "s2", "s1", moon])
        self.assertEqual([nodes[key]["kind"] for key in nodes], ["operator", "chair", "session", "session", "session", "subagent"])
        self.assertEqual([nodes[key]["label"] for key in nodes][:5], ["Operator", "Maintainer", "Docs", "Gatekeeper", "Skills"])
        self.assertEqual((nodes[moon]["parent"], nodes[moon]["label"]), ("s1", "subagent general-purpose (default)"))
        skills = [(task["task"], task["worker"], task["letters"]) for task in nodes["s1"]["tasks"]]
        self.assertEqual(skills, [("operator/push", False, "A"), ("work/hub", True, "R"), ("work/sub", False, "A")])
        self.assertEqual([(task["task"], task["letters"]) for task in nodes["Operator"]["tasks"]], [("operator/push", "R")])
        self.assertEqual([task["task"] for task in nodes[moon]["tasks"]], ["work/sub"])
        self.assertEqual([claim["office"] for claim in nodes["s1"]["claims"]], ["work/hub"])
        self.assertEqual((state["people"]["s1"]["now"], state["radio"][0]["source"], state["grants"][0]["target"]), ("Skills", "s1", "s1"))
        edges = {(edge["source"], edge["target"], edge["class"]): edge["count"] for edge in state["graph"]["edges"]}
        self.assertEqual(edges, {
            ("name:Docs", "*", "mayday"): 1,
            ("name:Docs", "s1", "pan-pan"): 1,
            ("name:Maintainer", "*", "newsletter"): 1,
            ("name:Maintainer", "name:Docs", "security"): 1,
            ("name:Maintainer", "s1", "grant"): 1,
            ("name:Maintainer", "s1", "security"): 1,
            ("s1", "name:Maintainer", "post"): 2,
        })

    def test_state_needs_the_host(self):
        for host in ("evil.example", f"evil.example:{self.port}", "127.0.0.1:1"):
            with self.subTest(host=host):
                self.assertEqual(self.call("GET", "/api/state", None, {"Host": host})[0], 403)
        status, headers, _ = self.get("/api/state")
        self.assertEqual(status, 200)
        self.assertEqual(headers["content-security-policy"], exchange.PLAIN_CSP)
        self.assertEqual(self.call("POST", "/api/state", b"", self.guard(self.host))[0], 404)


if __name__ == "__main__":
    unittest.main()
