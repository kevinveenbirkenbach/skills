from __future__ import annotations

import dataclasses
import http.server
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import quote

from hub_case import HubCase
from hub_support import ASK, HOST_STATE, REPO_ROOT, iso, key, server, signing
from kvb_orchestrator import handler, messaging, skill_scripts, transcripts


class TestHubBoard(HubCase):
    def test_uploads_are_sanitised_and_bounded(self):
        headers = {**self.guard(self.host), "Content-Type": "application/octet-stream"}
        status, _, body = self.call("POST", f"/api/uploads?name={quote('../../évil name.sh')}", b"data", headers)
        self.assertEqual(status, 201, body)
        upload = json.loads(body)
        self.assertEqual(upload["name"], "_vil_name.sh")
        self.assertEqual(upload["path"], str(HOST_STATE / "uploads" / upload["id"] / "_vil_name.sh"))
        self.assertEqual((self.state / "uploads" / upload["id"] / "_vil_name.sh").read_bytes(), b"data")
        for name, expected in (("..", "upload"), (".bashrc", "bashrc"), ("a\\b/c.txt", "c.txt"), ("x" * 300, "x" * 120)):
            with self.subTest(name=name):
                status, _, body = self.call("POST", f"/api/uploads?name={quote(name)}", b"1", headers)
                self.assertEqual((status, json.loads(body)["name"]), (201, expected))
        with mock.patch.object(handler, "UPLOAD_LIMIT", 8):
            self.assertEqual(self.call("POST", "/api/uploads?name=big", b"123456789", headers)[0], 413)
            self.assertEqual(self.call("POST", "/api/uploads?name=fits", b"12345678", headers)[0], 201)
        self.assertEqual(self.call("POST", "/api/uploads?name=x", b"1", {"Host": self.host, "X-Kvb-Orchestrator": "1"})[0], 403)
        self.assertEqual(self.get("/api/uploads")[0], 405)

    def test_operator_messages_go_by_radio_and_verify_over_mcp(self):
        self.claim("s1", "Skills session")
        signer = self.pin()
        headers = {**self.guard(self.host), "Content-Type": "application/octet-stream"}
        upload = json.loads(self.call("POST", "/api/uploads?name=plan.md", b"# plan", headers)[2])
        status, _, body = self.say({"to": "Skills", "text": "please\n rebase", "upload": upload["id"], "class": "post"}, signer)
        self.assertEqual(status, 201, body)
        sent = json.loads(body)
        self.assertTrue(sent["ok"])
        self.assertEqual(self.scripts.calls, [(skill_scripts.RADIO, ["post", "--to", "Skills session", "--session", "Operator", f"[kvb-orchestrator msg {sent['id']}] please rebase file: {upload['path']}"])])
        verified = self.tool("operator_message", {"id": sent["id"], "text": f"please rebase file: {upload['path']}", "to": "Skills session"})["structuredContent"]
        self.assertEqual((verified["match"], verified["to"], verified["text"], verified["upload"], verified["voice"]), (True, "Skills", "please\n rebase", upload["path"], None))
        self.assertEqual([(row["id"], row["to"], row["upload"], row["signed"]) for row in self.snapshot()["messages"]], [(sent["id"], "Skills", "plan.md", True)])
        self.assertTrue(self.tool("operator_message", {"id": "0123456789abcdef", "text": "please rebase", "to": "Skills"})["isError"])
        self.assertTrue(self.tool("operator_message", {"id": "../x", "text": "please rebase", "to": "Skills"})["isError"])
        for payload in (
            {"to": "Skills", "text": "  ", "upload": "", "class": "post", "voice": "", "proof": None},
            {"to": "Skills", "text": "hi", "upload": "0123456789abcdef", "class": "post", "voice": "", "proof": None},
            {"to": "Skills", "text": "hi", "upload": "../../etc", "class": "post", "voice": "", "proof": None},
            {"to": "two\nlines", "text": "hi", "upload": "", "class": "post", "voice": "", "proof": None},
            {"to": "Skills", "text": "hi", "class": "post", "voice": "", "proof": None},
            {"to": "Skills", "text": "hi", "upload": "", "class": "post", "voice": "", "proof": None},
        ):
            with self.subTest(payload=payload):
                self.assertEqual(self.post_json("/api/messages", payload, self.guard(self.host))[0], 400)
        self.assertEqual(self.post_json("/api/messages", {"to": "Skills", "text": "hi", "upload": "", "class": "post", "voice": "", "proof": None}, {"Host": self.host, "X-Kvb-Orchestrator": "1"})[0], 403)
        self.assertEqual(len(self.scripts.calls), 1)

    def test_board_actions_run_the_skill_scripts(self):
        self.claim("s1", "Skills session")
        self.claim("s2", "Gatekeeper")
        now = time.time()
        self.write_council({
            "radio-silence.json": {"since": now, "until": now + 60, "by": "Docs", "text": "disk full"},
            "night.json": {"mode": "drain", "active": "Operator", "resumed": []},
            "rasci.json": {"work/a": {"worker": "A", "status": "running", "prio": 2}, "work/b": {"worker": "B session", "status": "queued", "prio": 1}, "work/c": {"worker": "C", "status": "done"}},
        })
        state = self.snapshot()
        self.assertEqual((state["silence"]["by"], state["night"]), ("Docs", "drain"))
        for old, new in (("evening", "drain"), ("sunset", "suspend"), (["sunset"], "day"), ("noon", "day")):
            with self.subTest(old=old):
                self.write_council({"night.json": {"mode": old, "active": "Operator", "awake": []}})
                self.assertEqual(self.snapshot()["night"], new)
        self.assertEqual(state["agent_order"], ["B session", "A", "Gatekeeper", "Skills session"])
        self.write_council({"agent-order.json": {"agents": ["Gatekeeper", "Nobody", "A", "A"], "set": "2026-11-07T10:00:00+00:00"}})
        self.assertEqual(self.snapshot()["agent_order"], ["Gatekeeper", "A", "B session", "Skills session"])
        register = (self.council / "rasci.json").read_text(encoding="utf-8")

        signer = self.pin()

        def board(action: str, payload: object) -> tuple[int, dict | None]:
            status, _, body = self.post_json(f"/api/board/{action}", payload, self.guard(self.host))
            return status, json.loads(body) if status == 200 else None

        def signed(action: str) -> dict:
            return {"proof": self.board_proof(action, signer)}

        status, result = board("clear-mayday", signed("clear-mayday"))
        self.assertEqual((status, result["ok"], result["runs"][0]["stdout"]), (200, True, "done"))
        self.assertEqual(self.scripts.calls[-1], (skill_scripts.RADIO, ["clear", "--force", "--session", "Operator"]))
        self.assertEqual(self.tell_all({"text": "main is green", "class": "newsletter"}, signer)[0], 200)
        message_id = self.tool("operator_message", {"id": self.snapshot()["messages"][-1]["id"], "text": "main is green", "to": "*"})["structuredContent"]["id"]
        self.assertEqual(self.scripts.calls[-1], (skill_scripts.RADIO, ["post", "--session", "Operator", f"[kvb-orchestrator msg {message_id}] main is green"]))
        self.assertEqual(board("order", {"agents": ["Gatekeeper", "A", "B session"]})[0], 200)
        self.assertEqual(self.scripts.calls[-1], (skill_scripts.RASCI, ["agents", "order", "Gatekeeper,A,B session"]))
        calls = len(self.scripts.calls)
        for payload in ({"agents": ["A,B"]}, {"agents": ["A", "A"]}, {"agents": []}, {"agents": ["-x"]}, {"agents": "A"}, {"text": "x"}, {"agents": ["A", "Nobody"]}, {"agents": ["C"]}):
            with self.subTest(payload=payload):
                self.assertEqual(board("order", payload)[0], 400)
        self.assertEqual(len(self.scripts.calls), calls)
        self.assertEqual((self.council / "rasci.json").read_text(encoding="utf-8"), register)
        calls = len(self.scripts.calls)
        self.assertEqual(board("drain", signed("drain"))[0], 200)
        self.assertEqual(self.scripts.calls[calls:], [
            (skill_scripts.NIGHT, ["drain", "--session", "Operator"]),
            (skill_scripts.RADIO, ["send", "call", "--to", "Gatekeeper", "--to", "Skills session", "--session", "Operator", messaging.NIGHTS["drain"][1]]),
        ])
        self.assertIn("run kvb-agent-drain;", messaging.NIGHTS["drain"][1])
        self.assertEqual(board("resume", signed("resume"))[0], 200)
        self.assertEqual(self.scripts.calls[-2][1], ["resume", "--session", "Operator"])
        self.assertIn("run kvb-agent-resume;", self.scripts.calls[-1][1][-1])
        self.scripts.code = 1
        calls = len(self.scripts.calls)
        status, result = board("suspend", signed("suspend"))
        self.assertEqual((status, result["ok"], self.scripts.calls[calls:]), (200, False, [(skill_scripts.NIGHT, ["suspend", "--session", "Operator"])]))
        self.assertEqual(board("reboot", {})[0], 404)
        for old in ("evening", "sunset", "sunrise"):
            with self.subTest(old=old):
                self.assertEqual(board(old, {})[0], 404)
        self.assertEqual(board("broadcast", {"text": " ", "class": "newsletter", "voice": "", "proof": None})[0], 400)
        self.assertEqual(self.post_json("/api/board/suspend", {}, {"Host": self.host, "Origin": f"http://{self.host}"})[0], 403)
        self.assertEqual(self.get("/api/board/suspend")[0], 405)

    def test_board_actions_that_speak_for_the_operator_need_the_passkey(self):
        self.claim("s1", "Skills session")
        signer = self.pin()
        good = self.guard(self.host)
        self.assertEqual(messaging.SIGNED_BOARD, ("clear-mayday", "drain", "suspend", "resume", "estimates"))
        for action, other in (("clear-mayday", "resume"), ("drain", "suspend"), ("suspend", "drain"), ("resume", "clear-mayday")):
            with self.subTest(action=action):
                self.assertEqual(self.post_json(f"/api/board/{action}", {}, good)[0], 400)
                self.assertEqual(self.post_json(f"/api/board/{action}", {"proof": None}, good)[:3:2], (400, b"not signed: no signature\n"))
                stranger = key(-7, "stranger").proof(self.board_proof(action, signer)["payload"], self.origin)
                self.assertEqual(self.post_json(f"/api/board/{action}", {"proof": stranger}, good)[:3:2], (400, b"not signed: the signing key is not pinned\n"))
                proof = self.board_proof(action, signer)
                self.assertEqual(self.post_json(f"/api/board/{other}", {"proof": proof}, good)[:3:2], (400, b"not signed: the signature does not list this item\n"))
        self.assertEqual(self.scripts.calls, [])
        proof = self.board_proof("clear-mayday", signer)
        self.assertEqual(self.post_json("/api/board/clear-mayday", {"proof": proof}, good)[0], 200)
        self.assertEqual(self.scripts.calls, [(skill_scripts.RADIO, ["clear", "--force", "--session", "Operator"])])
        self.assertEqual(self.post_json("/api/board/clear-mayday", {"proof": proof}, good)[:3:2], (400, b"not signed: this signature was already used for this item\n"))
        for payload in ({"action": "order"}, {"action": "broadcast"}, {"action": "reboot"}, {"action": "sunset"}, {"action": 1}, {}, {"action": "drain", "extra": 1}):
            with self.subTest(payload=payload):
                self.assertEqual(self.post_json("/api/board/sign", payload, good)[0], 400)
        self.assertEqual(self.post_json("/api/board/sign", {"action": "drain"}, self.client())[0], 403)
        self.assertEqual(self.get("/api/board/sign")[0], 405)
        self.assertEqual(len(self.scripts.calls), 1)

    def test_a_night_action_for_chosen_agents_signs_them_and_calls_only_them(self):
        self.claim("s1", "Skills session")
        self.claim("s2", "Gatekeeper")
        signer = self.pin()
        good = self.guard(self.host)

        def board(action: str, payload: dict) -> tuple[int, bytes]:
            status, _, body = self.post_json(f"/api/board/{action}", payload, good)
            return status, body

        self.assertEqual(signing.board_item("drain", []), {"kind": "board", "action": "drain"})
        proof = self.board_proof("drain", signer, ["s2"])
        self.assertEqual(board("drain", {"proof": proof})[1], b"not signed: the signature does not list this item\n")
        self.assertEqual(board("drain", {"proof": self.board_proof("drain", signer), "agents": ["s2"]})[1], b"not signed: the signature does not list this item\n")
        self.assertEqual(board("drain", {"proof": proof, "agents": ["s2", "s1"]})[1], b"not signed: the signature does not list this item\n")
        self.assertEqual(self.scripts.calls, [])
        self.assertEqual(board("drain", {"proof": proof, "agents": ["s2"]})[0], 200)
        self.assertEqual(self.scripts.calls, [
            (skill_scripts.NIGHT, ["drain", "--session", "Operator", "--target=s2"]),
            (skill_scripts.RADIO, ["send", "call", "--to", "Gatekeeper", "--session", "Operator", messaging.ALONE["drain"]]),
        ])
        self.assertIn("run kvb-agent-drain;", messaging.ALONE["drain"])
        self.assertEqual(board("resume", {"proof": self.board_proof("resume", signer, ["s2", "s1"]), "agents": ["s1", "s2"]})[0], 200)
        self.assertEqual(self.scripts.calls[-2:], [
            (skill_scripts.NIGHT, ["resume", "--session", "Operator", "--target=s1", "--target=s2"]),
            (skill_scripts.RADIO, ["send", "call", "--to", "Gatekeeper", "--to", "Skills session", "--session", "Operator", messaging.ALONE["resume"]]),
        ])
        calls = len(self.scripts.calls)
        for action, agents in (("drain", ["s9"]), ("drain", ["s2", "s2"]), ("drain", "s2"), ("drain", [2]), ("drain", ["Operator"]), ("clear-mayday", ["s2"]), ("estimates", ["s1"])):
            with self.subTest(action=action, agents=agents):
                self.assertEqual(self.post_json("/api/board/sign", {"action": action, "agents": agents}, good)[0], 400)
                self.assertEqual(board(action, {"proof": None, "agents": agents})[0], 400)
        self.assertEqual(len(self.scripts.calls), calls)

    def test_the_state_shows_each_sessions_own_part(self):
        for night, parts in (
            ({"parts": {"s2": "drain", "s3": "noon"}}, {"s2": "drain"}),
            ({"mode": "drain", "active": "Operator", "resumed": ["s1"], "parts": {"s1": "suspend"}}, {"Operator": "day", "s1": "suspend"}),
            ({"mode": "sunset", "active": "Operator", "awake": ["s3"]}, {"Operator": "day", "s3": "day"}),
            ({"active": "Operator", "resumed": ["s1"]}, {}),
            ({"mode": "drain", "parts": ["s1"], "resumed": "s1"}, {}),
            (["drain"], {}),
        ):
            with self.subTest(night=night):
                self.write_council({"night.json": night})
                self.assertEqual(self.snapshot()["night_parts"], parts)

    def test_every_night_action_is_a_command_the_shipped_night_script_takes(self):
        with tempfile.TemporaryDirectory() as tmp:
            scripts = skill_scripts.Scripts(skills=REPO_ROOT / "skills", council=Path(tmp) / "council", home=Path(tmp))
            for action, (command, _) in messaging.NIGHTS.items():
                with self.subTest(action=action):
                    run = scripts.run(skill_scripts.NIGHT, [*command, "--session", "Operator"])
                    self.assertEqual(run["code"], 0, run["stderr"])
                    status = scripts.run(skill_scripts.NIGHT, ["status", "--session", "Operator"])["stdout"].splitlines()
                    self.assertEqual(status[0], "mode: day" if action == "resume" else f"mode: {action}")
                    run = scripts.run(skill_scripts.NIGHT, [*command, "--session", "Operator", "--target=s2"])
                    self.assertEqual(run["code"], 0, run["stderr"])
                    status = scripts.run(skill_scripts.NIGHT, ["status", "--session", "s2"])["stdout"].splitlines()
                    self.assertEqual(status[-1].startswith(f"you: {action}"), action != "resume", status)

    def test_nl_actions_are_validated_against_a_faked_endpoint(self):
        status, _, body = self.post_json("/api/nl", {"text": "approve all"}, self.guard(self.host))
        self.assertEqual(status, 400, body)
        self.assertIn(b"KVB_ORCHESTRATOR_LLM_URL", body)
        seen: list[tuple[str, str | None, dict]] = []
        replies: list[str] = []

        class Fake(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                seen.append((self.path, self.headers.get("Authorization"), data))
                answer = json.dumps({"choices": [{"message": {"content": replies[-1]}}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(answer)))
                self.end_headers()
                self.wfile.write(answer)

            def log_message(self, *args: object) -> None:
                return

        fake = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=fake.serve_forever, args=(0.05,), daemon=True).start()
        self.addCleanup(fake.server_close)
        self.addCleanup(fake.shutdown)
        self.httpd.hub = dataclasses.replace(self.httpd.hub, model=server.Model(url=f"http://127.0.0.1:{fake.server_address[1]}/v1", model="m", key="k"))
        self.claim("s1", "Skills session")
        transcript = self.projects / "-repo" / "s1.jsonl"
        transcript.parent.mkdir(parents=True)
        transcript.write_text(self.jsonl([{"type": "user", "sessionId": "s1", "timestamp": iso(time.time()), "message": {"role": "user", "content": "SECRET-TRANSCRIPT"}}]), encoding="utf-8")
        with mock.patch.object(transcripts, "STREAM_SCAN", 0):
            self.assertEqual(len(self.events("kinds=transcript")["entries"]), 1)
        review_id = self.request("feat: nl", "")
        ask_id = self.create_ask(ASK)
        decision_id = self.decision("Merge now")
        replies.append(json.dumps({"actions": [
            {"name": "approve", "arguments": {"ids": [review_id, decision_id]}},
            {"name": "choose", "arguments": {"id": decision_id, "label": "Wait"}},
            {"name": "message", "arguments": {"to": "Skills", "text": "rebase"}},
            {"name": "view", "arguments": {"name": "funk"}},
            {"name": "snooze", "arguments": {"ids": [ask_id], "hours": 2}},
            {"name": "approve", "arguments": {"ids": ["ffffffffffffffff"]}},
            {"name": "reject", "arguments": {"ids": [decision_id]}},
            {"name": "message", "arguments": {"to": "Nobody", "text": "x"}},
            {"name": "shutdown", "arguments": {}},
            {"name": "snooze", "arguments": {"ids": [ask_id], "hours": 500}},
            {"name": "view", "arguments": {"name": "funk", "extra": 1}},
        ]}))
        status, _, body = self.post_json("/api/nl", {"text": "approve everything green"}, self.guard(self.host))
        self.assertEqual(status, 200, body)
        result = json.loads(body)
        self.assertEqual([action["name"] for action in result["actions"]], ["approve", "choose", "message", "view", "snooze"])
        self.assertEqual(result["actions"][0]["args"]["items"], [self.entry("review", review_id, "", ""), self.entry("decision", decision_id, "Merge now", "")])
        self.assertEqual(result["actions"][4]["args"], {"keys": [{"kind": "ask", "id": ask_id}], "hours": 2})
        self.assertEqual(len(result["rejected"]), 6)
        path, key, sent = seen[-1]
        self.assertEqual((path, key, sent["model"]), ("/v1/chat/completions", "Bearer k", "m"))
        self.assertNotIn("SECRET-TRANSCRIPT", json.dumps(sent))
        self.assertIn(review_id, sent["messages"][1]["content"])
        self.assertIn("approve", sent["messages"][0]["content"])
        replies.append("not json")
        self.assertEqual(self.post_json("/api/nl", {"text": "x"}, self.guard(self.host))[0], 400)
        self.assertEqual(self.post_json("/api/nl", {"text": "x"}, self.client())[0], 403)


if __name__ == "__main__":
    unittest.main()
