from __future__ import annotations

import importlib
import json
import socket
import subprocess
import sys
import threading
import time
import unittest
from collections.abc import Callable

from hub_case import HubCase
from hub_support import ASK, CLIENT, HOOK, OPTIONS, Key, key, signing


class TestHubAsks(HubCase):
    def first_ask(self) -> dict:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            asks = self.snapshot()["asks"]
            if asks:
                return asks[0]
            time.sleep(0.05)
        self.fail("no ask arrived")

    def hook(self, port: int, timeout: str, payload: dict) -> subprocess.Popen:
        trust = ["--approvers", str(self.approvers), "--replay", str(self.replay / "hook.json")]
        command = [sys.executable, str(CLIENT), "--port", str(port), "--timeout", timeout, *trust]
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        process.stdin.write(json.dumps(payload))
        process.stdin.close()
        self.addCleanup(process.stdout.close)
        self.addCleanup(process.stderr.close)
        return process

    def finish(self, process: subprocess.Popen) -> tuple[int, str]:
        process.wait(30)
        return process.returncode, process.stdout.read()

    def test_asks_are_created_waited_on_and_decided(self):
        self.claim("s1", "Skills session")
        bad_headers = (
            {"Host": self.host},
            {**self.local(), "X-Kvb-Orchestrator": "0"},
            {**self.local(), "Origin": "http://evil.example"},
            {**self.local(), "Origin": "null"},
            {"Host": "evil.example", "X-Kvb-Orchestrator": "1"},
        )
        for headers in bad_headers:
            with self.subTest(headers=headers):
                self.assertEqual(self.post_json("/api/asks", ASK, headers)[0], 403)
        for payload in ({**ASK, "extra": 1}, {k: v for k, v in ASK.items() if k != "cwd"}, {**ASK, "tool": "two\nlines"}, {**ASK, "timeout": -1}, [1]):
            with self.subTest(payload=payload):
                self.assertEqual(self.post_json("/api/asks", payload, self.local())[0], 400)
        self.assertEqual(self.post_json("/api/asks", ASK, {**self.local(), "Origin": f"http://{self.host}"})[0], 201)
        ask_id = self.create_ask(ASK)
        asks = [row for row in self.snapshot()["asks"] if row["id"] == ask_id]
        self.assertEqual([(row["tool"], row["command"], row["cwd"], row["agent"], row["session"]) for row in asks], [("Bash", "make deploy", "/repo", "Skills", "s1")])
        self.assertEqual(self.ask_status(ask_id, "0.1"), "pending")
        results = []
        waiter = threading.Thread(target=lambda: results.append(self.ask_status(ask_id, "20")))
        waiter.start()
        time.sleep(0.3)
        for headers in ({"Host": self.host, "X-Kvb-Orchestrator": "1"}, {"Host": self.host, "Origin": f"http://{self.host}"}, {**self.guard(self.host), "Origin": "http://evil.example"}):
            with self.subTest(headers=headers):
                self.assertEqual(self.call("POST", f"/api/asks/{ask_id}/allow", b"", headers)[0], 403)
        signer = key(-7, "main")
        stranger = self.create_ask({**ASK, "command": "make other"})
        for body in (b"", b'{"proof": null}', self.proven([self.entry("ask", stranger, "", "")], signer), b'{"proof": {"payload": {}, "assertion": {}}}'):
            with self.subTest(body=body[:60]):
                self.assertEqual(self.call("POST", f"/api/asks/{ask_id}/allow", body, self.guard(self.host))[0], 400)
        self.assertEqual(self.ask_status(ask_id, "0"), "pending")
        self.assertEqual(self.call("POST", f"/api/asks/{ask_id}/allow", self.proven([self.entry("ask", ask_id, "", "")], signer), self.guard(self.host))[0], 200)
        waiter.join(10)
        self.assertEqual(results, ["allowed"])
        self.assertEqual(self.get(f"/api/asks/{ask_id}?wait=0")[2].count(b'"assertion"'), 1)
        self.assertEqual(self.call("POST", f"/api/asks/{ask_id}/deny", b"", self.guard(self.host))[0], 409)
        other = self.create_ask(ASK)
        self.assertEqual(self.call("POST", f"/api/asks/{other}/deny", b"", self.guard(f"localhost:{self.port}"))[0], 200)
        self.assertEqual(self.ask_status(other, "0"), "denied")
        expired = self.create_ask({**ASK, "timeout": 0})
        self.assertEqual(self.ask_status(expired, "5"), "expired")
        self.assertEqual(self.call("POST", f"/api/asks/{expired}/allow", b"", self.guard(self.host))[0], 409)
        self.assertNotIn(expired, [row["id"] for row in self.snapshot()["asks"]])
        self.assertEqual(self.call("POST", "/api/asks/0123456789abcdef/allow", b"", self.guard(self.host))[0], 404)
        self.assertEqual(self.get("/api/asks/0123456789abcdef?wait=0")[0], 404)
        self.assertEqual(self.get(f"/api/asks/{ask_id}/allow")[0], 405)
        self.assertEqual(self.get(f"/api/asks/{ask_id}?wait=soon")[0], 400)

    def test_the_hook_allows_only_a_valid_signature_and_denies_unsigned(self):
        relayed = []

        def asked(decide: Callable[[str], None]) -> tuple[int, str]:
            process = self.hook(self.port, "20", HOOK)
            ask = self.first_ask()
            self.assertEqual((ask["tool"], ask["command"], ask["cwd"], ask["session"]), ("Bash", "rm -rf node_modules", "/repo", "s1"))
            decide(ask["id"])
            return self.finish(process)

        def deny(ask_id: str) -> None:
            self.assertEqual(self.call("POST", f"/api/asks/{ask_id}/deny", b"", self.guard(self.host))[0], 200)

        def allow_by(signer: Key) -> Callable[[str], None]:
            def allow(ask_id: str) -> None:
                body = self.proven([self.entry("ask", ask_id, "", "")], signer)
                relayed.append(json.loads(body)["proof"])
                self.assertEqual(self.call("POST", f"/api/asks/{ask_id}/allow", body, self.guard(self.host))[0], 200)

            return allow

        def relay(proof: dict | None) -> Callable[[str], None]:
            def compromised(ask_id: str) -> None:
                self.httpd.hub.asks.decide(ask_id, {"status": "allowed", "proof": proof})

            return compromised

        code, out = asked(deny)
        self.assertEqual((code, json.loads(out)), (0, {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {"behavior": "deny", "message": "The operator denied this in the Agent Orchestrator."}}}))
        self.assertEqual(asked(allow_by(key(-7, "main"))), (0, ""))
        self.pin()
        self.assertEqual(asked(allow_by(key(-8, "stranger"))), (0, ""))
        self.assertEqual(asked(relay(None)), (0, ""))
        code, out = asked(allow_by(key(-7, "main")))
        self.assertEqual((code, json.loads(out)), (0, {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {"behavior": "allow"}}}))
        self.assertEqual(asked(relay(relayed[-1])), (0, ""))
        self.assertEqual(self.finish(self.hook(self.port, "0.3", HOOK)), (0, ""))
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            closed = probe.getsockname()[1]
        self.assertEqual(self.finish(self.hook(closed, "5", HOOK)), (0, ""))

    def test_the_hook_posts_nothing_it_cannot_send_in_full(self):
        for name, change in (
            ("tool", {"tool_name": "T" * 201}),
            ("command", {"tool_input": {"command": "x" * 4001}}),
            ("cwd", {"cwd": "/" + "d" * 4096}),
            ("session", {"session_id": "s" * 201}),
            ("agent", {"agent_type": "a" * 201}),
        ):
            with self.subTest(name=name):
                process = self.hook(self.port, "3", {**HOOK, **change})
                self.assertEqual((self.finish(process), self.httpd.hub.asks.listed()), ((0, ""), []))
                self.assertRegex(process.stderr.read(), rf"\Akvb-orchestrator: [^\n]*\b{name}\b[^\n]*\n\Z")
        process = self.hook(self.port, "20", {**HOOK, "tool_input": {"command": "x" * 4000}})
        ask = self.first_ask()
        self.assertEqual(ask["command"], "x" * 4000)
        self.assertEqual(self.call("POST", f"/api/asks/{ask['id']}/deny", b"", self.guard(self.host))[0], 200)
        self.assertEqual(json.loads(self.finish(process)[1])["hookSpecificOutput"]["decision"]["behavior"], "deny")

    def test_a_bad_timeout_names_the_field_the_caller_sent(self):
        status, _, body = self.post_json("/api/asks", {**ASK, "timeout": -1}, self.local())
        self.assertEqual((status, body), (400, b"timeout must be a finite number of seconds, 0 or more\n"))
        for tool in ("decision_wait", "review_wait"):
            with self.subTest(tool=tool):
                result = self.tool(tool, {"id": "0123456789abcdef", "timeout_seconds": -1})
                self.assertEqual(result["content"][0]["text"], "timeout_seconds must be a finite number of seconds, 0 or more")

    def test_an_ask_with_an_invisible_format_character_is_refused_before_it_reaches_a_prompt(self):
        for name, value, code in (
            ("command", f"git status{chr(0x202E)} && rm -rf ~", "U+202E"),
            ("command", f"make{chr(0x200B)} test", "U+200B"),
            ("command", f"rm{chr(0xA0)}-rf ~", "U+00A0"),
            ("command", f"make{chr(0x3164)} test", "U+3164"),
            ("command", f"make test{chr(0xFE0F)}", "U+FE0F"),
            ("cwd", f"/repo{chr(0x2066)}", "U+2066"),
            ("session", f"s1{chr(0x200D)}", "U+200D"),
            ("tool", f"{chr(0xFEFF)}Bash", "U+FEFF"),
        ):
            with self.subTest(code=code):
                status, _, body = self.post_json("/api/asks", {**ASK, name: value}, self.local())
                self.assertEqual(status, 400)
                self.assertIn(code, body.decode("utf-8"))
        self.assertEqual(self.httpd.hub.asks.listed(), [])
        self.assertEqual([item for item in self.snapshot()["inbox"] if item["kind"] == "ask"], [])
        self.create_ask(ASK)

    def test_a_score_block_with_emoji_presentation_reaches_the_prompt_and_a_stray_selector_does_not(self):
        vs16 = chr(0xFE0F)
        score = f"🎯 Fix: 93\n💥 Break: 4\n{chr(0x23F1)}{vs16} Time: 20\n{chr(0x1F6E1)}{vs16} Security: 100\n🏆 Score: 90"
        ask_id = self.create_ask({**ASK, "command": f'git commit -m "fix: x" -m "{score}"'})
        self.assertEqual(self.post_json("/api/sign", {"items": [self.entry("ask", ask_id, "", "")]}, self.guard(self.host))[0], 200)
        result = self.tool("decision_request", {"question": f"Commit?\n{score}", "options": [{**OPTIONS[0], "description": score}, OPTIONS[1]], "agent": "Skills", "recommended": ""})
        self.assertFalse(result["isError"], result)
        for command in (f"make {chr(0x23F1)}{vs16}{vs16}", f"make{vs16}", f"{vs16}{chr(0x23F1)}"):
            with self.subTest(command=command):
                status, _, body = self.post_json("/api/asks", {**ASK, "command": command}, self.local())
                self.assertEqual(status, 400)
                self.assertIn("U+FE0F", body.decode("utf-8"))
        self.assertIn(f'id="emoji-bases" type="application/json">{json.dumps(sorted(signing.EMOJI_BASES))}</script>', self.index())

    def test_the_hook_names_the_reason_the_hub_refused_an_ask_on_one_line(self):
        process = self.hook(self.port, "3", {**HOOK, "tool_input": {"command": f"rm{chr(0xA0)}-rf node_modules"}})
        self.assertEqual(self.finish(process), (0, ""))
        self.assertRegex(process.stderr.read(), r"\Akvb-orchestrator: the hub answered 400, Claude Code asks instead: command must hold no [^\n]*U\+00A0[^\n]*\n\Z")
        self.assertEqual(self.httpd.hub.asks.listed(), [])

    def test_the_hook_prints_no_control_or_bidi_character_of_a_reason(self):
        hook = importlib.import_module("permission_hook")
        reason = f" stop{chr(0x9B)}31m{chr(0x202E)}txt\nnext{chr(0x7F)}{chr(0x2066)} {chr(0x23F1)}{chr(0xFE0F)} 20 "
        self.assertEqual(hook.clean(reason), f"stop?31m?txt?next?? {chr(0x23F1)}{chr(0xFE0F)} 20")

    def test_a_decision_with_an_invisible_format_character_is_refused_before_it_reaches_a_prompt(self):
        plain = {"question": "Merge the hub?", "options": OPTIONS, "agent": "Skills", "recommended": ""}
        for change, code in (
            ({"question": f"Merge{chr(0x202E)} the hub?"}, "U+202E"),
            ({"options": [{**OPTIONS[0], "description": f"Gate{chr(0x200B)} is green"}, OPTIONS[1]]}, "U+200B"),
            ({"options": [{**OPTIONS[0], "label": f"Merge now{chr(0x2067)}"}, OPTIONS[1]]}, "U+2067"),
        ):
            with self.subTest(code=code):
                result = self.tool("decision_request", {**plain, **change})
                self.assertTrue(result["isError"])
                self.assertIn(code, json.dumps(result, ensure_ascii=True))
        self.assertEqual(self.httpd.hub.decisions.listed(), [])
        self.assertFalse(self.tool("decision_request", plain)["isError"])

    def test_decisions_are_requested_chosen_and_waited_for(self):
        for arguments in (
            {"question": "Merge?", "options": [], "agent": "Skills"},
            {"question": "Merge?", "options": [OPTIONS[0], OPTIONS[0]], "agent": "Skills"},
            {"question": "Merge?", "options": [{"label": "x"}], "agent": "Skills"},
            {"question": "Merge?", "options": [{**OPTIONS[0], "extra": 1}], "agent": "Skills"},
            {"question": "Merge?", "options": "Merge now", "agent": "Skills"},
            {"question": "   ", "options": OPTIONS, "agent": "Skills"},
            {"question": "Merge?", "options": OPTIONS, "agent": "two\nlines"},
            {"question": "Merge?", "options": OPTIONS},
            {"question": "Merge?", "options": OPTIONS, "agent": "Skills"},
            {"question": "Merge?", "options": OPTIONS, "agent": "Skills", "recommended": "Later"},
            {"question": "Merge?", "options": OPTIONS, "agent": "Skills", "recommended": 5},
        ):
            with self.subTest(arguments=arguments):
                self.assertTrue(self.tool("decision_request", arguments)["isError"])
        result = self.tool("decision_request", {"question": "Merge the hub?", "options": OPTIONS, "agent": "Skills", "recommended": ""})["structuredContent"]
        decision_id = result["id"]
        self.assertEqual((result["status"], result["url"]), ("pending", f"http://localhost:{self.port}/"))
        listed = self.snapshot()["decisions"]
        self.assertEqual([(row["id"], row["question"], row["agent"], [o["label"] for o in row["options"]]) for row in listed], [(decision_id, "Merge the hub?", "Skills", ["Merge now", "Wait"])])
        self.assertEqual(self.tool("decision_wait", {"id": decision_id, "timeout_seconds": 0})["structuredContent"]["status"], "pending")
        self.assertEqual(self.post_json(f"/api/decisions/{decision_id}/choose", {"label": "Merge now"}, self.guard(self.host))[0], 404)
        self.assertEqual(self.tool("decision_wait", {"id": decision_id, "timeout_seconds": 0})["structuredContent"]["status"], "pending")
        self.assertTrue(self.tool("decision_wait", {"id": "0123456789abcdef", "timeout_seconds": 0})["isError"])
        for name in ("*", "* session", "* (x)", "* (x) session", "a*b"):
            with self.subTest(name=name):
                everyone = {"question": "Tell all?", "options": OPTIONS, "agent": name, "recommended": ""}
                self.assertTrue(self.tool("decision_request", everyone)["isError"])


if __name__ == "__main__":
    unittest.main()
