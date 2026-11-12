from __future__ import annotations

import json
import re
import time
import unittest
from urllib.parse import quote

from hub_case import HubCase
from hub_support import ASK
from kvb_orchestrator import council, events, settings, skill_scripts, view


class TestHubSurface(HubCase):
    def test_the_header_holds_only_the_title_the_radio_the_bubbles_the_palette_and_the_settings(self):
        html = self.index()
        self.assertIn("<title>Agent Orchestrator</title>", html)
        header = re.search(r'<header class="top">(.*?)</header>', html, re.DOTALL).group(1)
        self.assertIn("<h1>Agent Orchestrator</h1>", header)
        self.assertEqual(re.findall(r'<button[^>]*id="([^"]+)"', header), ["radio-open", "bubbles-toggle", "palette-open", "settings-open"])
        self.assertEqual(re.findall(r"<(?:nav|select|input|textarea)\b", header), [])
        for gone in ('id="rail"', 'id="inbox-bar"', 'id="status"', 'id="board-open"', 'id="rules-open"', 'id="timebar"'):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, html)
        self.assertIn('<nav class="tabs" id="tabs"', html)

    def test_badges_count_waiting_operator_tasks_on_tasks_active_agents_and_open_runner_jobs(self):
        now = 1000.0
        inbox = [{"until": None}, {"until": None}, {"until": now + 60}]
        claims = [{"agent": "A", "beat": now - 10}, {"agent": "A", "beat": now - 20}, {"agent": "B", "beat": now - 900}, {"agent": "C", "beat": now - 901}, {"agent": "D", "beat": None}]
        jobs = [{"status": "queued"}, {"status": "running"}, {"status": "done"}, {"status": "failed"}]
        self.assertEqual(view.badges(inbox, claims, jobs, now), {"tasks": 2, "agents": 2, "artifacts": 2})
        self.assertEqual(view.badges([], [], [], now), {"tasks": 0, "agents": 0, "artifacts": 0})
        self.claim("s1", "Skills session")
        self.create_ask(ASK)
        self.assertEqual(self.snapshot()["badges"], {"tasks": 1, "agents": 1, "artifacts": 0})
        self.assertIn("<title>(1) Agent Orchestrator</title>", self.index())

    def test_register_workers_map_to_the_agent_named_before_the_bracket(self):
        for raw, name in (("Stage (this session)", "Stage"), ("infinito-nexus-core-c8 (Production)", "infinito-nexus-core-c8"), ("Skills session", "Skills"), (" Docs ", "Docs"), ("(only)", "(only)"), (None, "")):
            with self.subTest(raw=raw):
                self.assertEqual(council.agent(raw), name)
        self.claim("s1", "Stage")
        self.write_council({"rasci.json": {"work/a": {"title": "A", "status": "running", "worker": "Stage (this session)", "roles": {"Stage (this session)": "RA"}}}})
        labels = [node["label"] for node in self.snapshot()["graph"]["nodes"]]
        self.assertEqual(labels.count("Stage"), 1)
        self.assertNotIn("Stage (this session)", labels)

    def test_radio_rows_carry_the_seven_classes_and_old_rows_keep_their_meaning(self):
        rows = [{"ts": 10.0 + n, "from": "A", "to": ["B"], "text": "x", "class": cls, "v": 2} for n, cls in enumerate(("post", "call", "receipt"))]
        rows += [{"ts": 20.0 + n, "from": "A", "to": [], "text": "x", "class": cls, "v": 2} for n, cls in enumerate(("newsletter", "broadcast", "mayday", "pan-pan", "security"))]
        rows += [
            {"ts": 30.0, "from": "A", "to": ["B"], "text": "x", "class": "direct"},
            {"ts": 31.0, "from": "A", "to": ["B"], "text": "x", "class": "direct", "wake": True},
            {"ts": 32.0, "from": "A", "to": [], "text": "x", "class": "broadcast"},
            {"ts": 33.0, "from": "A", "to": ["B"], "text": "x"},
            {"ts": 34.0, "from": "A", "to": [], "text": "MAYDAY disk full"},
            {"ts": 35.0, "from": "A", "to": [], "text": "x", "class": "shout", "v": 2},
        ]
        self.assertEqual([row["class"] for row in council.radio_rows(rows, 0, 100)], [
            "post", "call", "receipt", "newsletter", "broadcast", "mayday", "pan-pan", "security",
            "post", "call", "newsletter", "post", "mayday", "newsletter",
        ])
        self.assertEqual(council.CLASSES, ("post", "call", "newsletter", "broadcast", "mayday", "pan-pan", "security"))

    def test_read_aloud_lists_the_seven_classes_and_migrates_old_choices(self):
        self.assertEqual(settings.speech_setting({"on": True, "classes": ["security", "mayday", "post", "call", "newsletter", "broadcast", "pan-pan"], "muted": []})["classes"], list(council.CLASSES))
        for classes in (["direct", "mayday"], ["post"], ["mayday", "receipt"]):
            with self.subTest(classes=classes), self.assertRaises(settings.ToolError):
                settings.speech_setting({"on": True, "classes": classes, "muted": []})
        stored = self.state / "old-settings.json"
        stored.write_text(json.dumps({**settings.SETTINGS, "speech": {"on": True, "classes": ["direct", "pan-pan", "mayday"], "muted": []}}), encoding="utf-8")
        self.assertEqual(settings.Settings(stored).get()["speech"]["classes"], ["post", "call", "mayday", "pan-pan"])

    def test_funk_an_alle_sends_the_chosen_class_and_newsletter_goes_by_post(self):
        signer = self.pin()

        def board(payload: object) -> int:
            return self.post_json("/api/board/broadcast", payload, self.guard(self.host))[0]

        def sent() -> tuple[list[str], str]:
            script, args = self.scripts.calls[-1]
            self.assertEqual(script, skill_scripts.RADIO)
            self.assertRegex(args[-1], r"^\[kvb-orchestrator msg [0-9a-f]{16}\] ")
            return args[:-1], args[-1].split("] ", 1)[1]

        self.assertEqual(self.tell_all({"text": "main is green", "class": "newsletter"}, signer)[0], 200)
        self.assertEqual(sent(), (["post", "--session", "Operator"], "main is green"))
        for cls in ("broadcast", "pan-pan", "security", "mayday"):
            with self.subTest(cls=cls):
                self.assertEqual(self.tell_all({"text": "hear me", "class": cls}, signer)[0], 200)
                self.assertEqual(sent(), (["send", cls, "--session", "Operator"], "hear me"))
        calls = len(self.scripts.calls)
        proof = self.message_proof({"to": "*", "text": "x", "upload": "", "class": "newsletter", "voice": ""}, signer)
        for payload in ({"text": "x", "class": "post"}, {"text": "x", "class": "call"}, {"text": "x"}, {"text": "x", "class": 1}, {"text": "x", "class": "mayday"}):
            with self.subTest(payload=payload):
                self.assertEqual(board({"voice": "", "proof": proof, **payload}), 400)
        self.assertEqual(len(self.scripts.calls), calls)

    def test_the_agent_panel_sends_a_post_or_a_call(self):
        self.claim("s1", "Skills session")
        signer = self.pin()

        def send(payload: dict) -> tuple[int, dict]:
            status, _, body = self.say({"to": "Skills", "text": "rebase", **payload}, signer)
            return status, json.loads(body) if status == 201 else {}

        status, sent = send({"class": "post"})
        self.assertEqual(status, 201)
        self.assertEqual(self.scripts.calls[-1], (skill_scripts.RADIO, ["post", "--to", "Skills session", "--session", "Operator", f"[kvb-orchestrator msg {sent['id']}] rebase"]))
        status, sent = send({"class": "call"})
        self.assertEqual(status, 201)
        self.assertEqual(self.scripts.calls[-1], (skill_scripts.RADIO, ["send", "call", "--to", "Skills session", "--session", "Operator", f"[kvb-orchestrator msg {sent['id']}] rebase"]))
        proof = self.message_proof({"to": "Skills", "text": "rebase", "upload": "", "class": "post", "voice": ""}, signer)
        for payload in ({"class": "newsletter"}, {"class": "mayday"}, {}):
            with self.subTest(payload=payload):
                status, _, _ = self.post_json("/api/messages", {"to": "Skills", "text": "rebase", "upload": "", "voice": "", "proof": proof, **payload}, self.guard(self.host))
                self.assertEqual(status, 400)

    def test_the_stream_has_four_categories_and_transcripts_stay_out_by_default(self):
        self.assertEqual({key: value["label"] for key, value in events.VIEWS.items()}, {"fuer-dich": "For you", "funk": "Radio", "arbeit": "Work", "transkripte": "Transcripts"})
        self.assertEqual(events.VIEWS["transkripte"]["kinds"], ["transcript"])
        self.assertNotIn("transcript", events.VIEWS["fuer-dich"]["kinds"] + events.VIEWS["funk"]["kinds"] + events.VIEWS["arbeit"]["kinds"])
        self.assertEqual(sorted(events.VIEWS["fuer-dich"]["kinds"]), sorted(events.VIEWS["funk"]["kinds"] + events.VIEWS["arbeit"]["kinds"]))
        self.assertEqual(self.snapshot()["kinds"], dict(events.KINDS))

    def test_the_search_line_filters_by_agent_kind_and_age(self):
        now = time.time()
        news = [
            {"ts": now - 7200, "from": "Docs", "to": ["Skills"], "text": "old deploy"},
            {"ts": now - 60, "from": "Docs", "to": ["Skills"], "text": "fresh deploy"},
            {"ts": now - 30, "from": "Ops", "to": [], "text": "deploy done"},
        ]
        self.write_council({"news.jsonl": self.jsonl(news)})
        self.request("feat: deploy", "")

        def texts(q: str) -> list[str]:
            return [f"{row['kind']}:{row['agent'] or row['title']}:{row['text'] or row['title']}" for row in self.events(f"kinds={','.join(events.EVENT_KINDS)}&q={quote(q)}")["events"]]

        self.assertEqual(texts("deploy"), ["radio:Docs:old deploy", "radio:Docs:fresh deploy", "radio:Ops:deploy done", "review:feat: deploy:feat: deploy"])
        self.assertEqual(texts("agent:Docs"), ["radio:Docs:old deploy", "radio:Docs:fresh deploy"])
        self.assertEqual(texts("kind:radio deploy"), ["radio:Docs:old deploy", "radio:Docs:fresh deploy", "radio:Ops:deploy done"])
        self.assertEqual(texts("kind:review"), ["review:feat: deploy:feat: deploy"])
        self.assertEqual(texts("since:1h agent:Docs"), ["radio:Docs:fresh deploy"])
        self.assertEqual(texts("since:5m done"), ["radio:Ops:deploy done"])
        since = time.strftime("%Y-%m-%dT%H:%M", time.localtime(now - 600))
        self.assertEqual(texts(f"since:{since} kind:Radio"), ["radio:Docs:fresh deploy", "radio:Ops:deploy done"])
        for q in ("kind:bogus", "since:soon", "since:5y", "agent:"):
            with self.subTest(q=q):
                self.assertEqual(self.get(f"/api/events?q={quote(q)}")[0], 400)


if __name__ == "__main__":
    unittest.main()
