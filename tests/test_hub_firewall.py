from __future__ import annotations

import functools
import json
import time
from unittest import mock

from hub_case import HubCase
from hub_support import ASK, PRESENT, key, signing, verifier
from kvb_orchestrator import batches, rules

HOME_FILE = "/home/op/.claude/settings.json"
PROJECT_FILE = "/home/op/Repositories/demo/.claude/settings.json"
SHA = "ab" * 32
PERMISSIONS = {
    "allow": ["Bash(make test:*)", "Bash(make lint:*)", "Bash(git status:*)", "WebFetch(domain:example.org)", "mcp__memory__search"],
    "ask": ["Bash(git push:*)"],
    "deny": ["Read(~/.ssh/**)", 7],
}
SANDBOX = {"enabled": True, "filesystem": {"allowWrite": ["/tmp", "~/Repositories"]}, "network": {"allowLocalBinding": False}}
ADD = {"list": "permissions.allow", "op": "add", "entry": "Bash(make build:*)"}


class TestHubFirewall(HubCase):
    def setUp(self):
        super().setUp()
        self.claim("s1", "Skills")
        self.claim("s2", "Stage")
        self.snapshot()

    def view(self, files: list[dict]) -> None:
        (self.state / "firewall" / "view.json").write_text(json.dumps({"written": time.time(), "files": files}), encoding="utf-8")

    def home_view(self) -> dict:
        return {"path": HOME_FILE, "exists": True, "sha256": SHA, "error": "", "settings": {"permissions": PERMISSIONS, "sandbox": SANDBOX, "env": {"EXAMPLE_FLAG": "fixture-value-not-a-secret"}}}

    def firewall(self) -> dict:
        status, _, body = self.get("/api/firewall")
        self.assertEqual(status, 200, body)
        return json.loads(body)

    def post(self, path: str, payload: object) -> tuple[int, bytes]:
        status, _, body = self.post_json(path, payload, self.guard(self.host))
        return status, body

    def test_the_firewall_groups_the_settings_by_tool_and_prefix_and_lists_the_deny_patterns(self):
        self.assertEqual(self.firewall()["files"], [])
        self.assertIn("kvb-orchestrator-firewall", self.firewall()["error"])
        self.view([self.home_view(), {"path": PROJECT_FILE, "exists": False, "sha256": "", "error": "", "settings": {}}, {"path": "/x", "exists": "yes", "sha256": "", "settings": {}}])
        found = self.firewall()
        self.assertEqual([entry["path"] for entry in found["files"]], [HOME_FILE, PROJECT_FILE])
        groups = [(group["tool"], group["prefix"], [(entry["list"], entry["entry"]) for entry in group["entries"]]) for group in found["files"][0]["groups"]]
        self.assertEqual(groups, [
            ("Bash", "git", [("allow", "Bash(git status:*)"), ("ask", "Bash(git push:*)")]),
            ("Bash", "make", [("allow", "Bash(make test:*)"), ("allow", "Bash(make lint:*)")]),
            ("Read", "~/.ssh/**", [("deny", "Read(~/.ssh/**)")]),
            ("WebFetch", "domain", [("allow", "WebFetch(domain:example.org)")]),
            ("mcp__memory__search", "", [("allow", "mcp__memory__search")]),
        ])
        self.assertEqual(found["files"][0]["sandbox"], [{"key": "sandbox.enabled", "value": True}, {"key": "sandbox.filesystem.allowWrite", "values": ["/tmp", "~/Repositories"]}, {"key": "sandbox.network.allowLocalBinding", "value": False}])
        self.assertEqual(found["lists"], list(signing.SETTINGS_LISTS))
        self.assertEqual([pattern["label"] for pattern in found["patterns"]][:len(signing.WARNINGS)], [label for label, _ in signing.WARNINGS])
        self.assertNotIn("fixture-value-not-a-secret", json.dumps(found))
        for path in ("/api/firewall/preview", "/api/firewall/settings", "/api/firewall/groups", "/api/firewall/sets", "/api/firewall/groups/0123456789abcdef/delete"):
            with self.subTest(path=path):
                self.assertEqual(self.get(path)[0], 405)
        self.assertEqual(self.get("/api/firewall/settings/0123456789abcdef")[0], 404)

    def test_a_settings_change_is_previewed_signed_and_queued_for_the_host(self):
        self.view([self.home_view()])
        item = {"kind": "settings", "file": HOME_FILE, "base": SHA, "changes": [ADD, {"list": "permissions.ask", "op": "remove", "entry": "Bash(git push:*)"}]}
        status, body = self.post("/api/firewall/preview", {"items": [item]})
        self.assertEqual(status, 200, body)
        diff = json.loads(body)["diffs"][0]["diff"]
        changed = [line for line in diff.splitlines() if line[:1] in "+-" and line[:3] not in ("+++", "---")]
        self.assertEqual([line[0] + line[1:].strip() for line in changed], ['-"mcp__memory__search"', '+"mcp__memory__search",', '+"Bash(make build:*)"', '-"ask": [', '-"Bash(git push:*)"', '-],', '+"ask": [],'])
        self.assertNotIn("EXAMPLE_FLAG", diff)
        signed = signing.settings_item(HOME_FILE, SHA, item["changes"])
        self.assertEqual(self.prepare([item])["payload"]["items"], [signing.item_hash(signed)])
        signer = self.pin()
        proof = signer.proof(self.prepare([item])["payload"], self.origin)
        for name, items, proven, expected in (
            ("no proof", [item], None, 400),
            ("forged", [item], key(-7, "intruder").proof(self.prepare([item])["payload"], self.origin), 400),
            ("stale base", [{**item, "base": "cd" * 32}], proof, 409),
            ("unlisted file", [{**item, "file": PROJECT_FILE}], proof, 400),
            ("hooks list", [{**item, "changes": [{**ADD, "list": "hooks.Stop"}]}], proof, 400),
            ("added twice", [{**item, "changes": [{**ADD, "entry": "Bash(make test:*)"}]}], proof, 400),
            ("two items for one file", [item, item], proof, 400),
            ("other item signed", [{**item, "changes": [ADD]}], proof, 400),
        ):
            with self.subTest(name=name):
                self.assertEqual(self.post("/api/firewall/settings", {"items": items, "proof": proven})[0], expected)
        self.assertEqual(self.post_json("/api/firewall/settings", {"items": [item], "proof": proof}, {"Host": self.host})[0], 403)
        self.assertEqual(list((self.state / "firewall" / "jobs").iterdir()), [])
        status, body = self.post("/api/firewall/settings", {"items": [item], "proof": proof})
        self.assertEqual(status, 202, body)
        job_id = json.loads(body)["id"]
        written = self.state / "firewall" / "jobs" / f"{job_id}.json"
        job = json.loads(written.read_text(encoding="utf-8"))
        self.assertEqual((sorted(job), job["items"], job["proof"]), (["created", "id", "items", "proof", "v"], [{name: signed[name] for name in signing.SETTINGS_KEYS}], proof))
        self.assertEqual(written.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.post("/api/firewall/settings", {"items": [item], "proof": proof})[0], 400)
        self.assertEqual(json.loads(self.get(f"/api/firewall/settings/{job_id}")[2])["status"], "queued")
        result = {"id": job_id, "finished": time.time(), "items": [{**job["items"][0], "status": "done", "reason": ""}]}
        (self.state / "firewall" / "results" / f"{job_id}.json").write_text(json.dumps(result), encoding="utf-8")
        self.assertEqual(json.loads(self.get(f"/api/firewall/settings/{job_id}")[2])["status"], "done")

    def test_a_settings_entry_or_path_with_an_invisible_format_character_is_refused_before_it_reaches_a_prompt(self):
        self.view([self.home_view()])
        for name, item, code in (
            ("bidi override in an entry", {"kind": "settings", "file": HOME_FILE, "base": SHA, "changes": [{**ADD, "entry": f"Bash(make build{chr(0x202E)}:*)"}]}, "U+202E"),
            ("zero-width space in an entry", {"kind": "settings", "file": HOME_FILE, "base": SHA, "changes": [{**ADD, "entry": f"Bash(make{chr(0x200B)} build:*)"}]}, "U+200B"),
            ("no-break space in a deny entry", {"kind": "settings", "file": HOME_FILE, "base": SHA, "changes": [{"list": "permissions.deny", "op": "add", "entry": f"Bash(rm{chr(0xA0)}-r:*)"}]}, "U+00A0"),
            ("ideographic space in a deny entry", {"kind": "settings", "file": HOME_FILE, "base": SHA, "changes": [{"list": "permissions.deny", "op": "add", "entry": f"Bash(rm{chr(0x3000)}-r:*)"}]}, "U+3000"),
            ("Hangul filler in an entry", {"kind": "settings", "file": HOME_FILE, "base": SHA, "changes": [{**ADD, "entry": f"Bash(make{chr(0x3164)} build:*)"}]}, "U+3164"),
            ("grapheme joiner in an entry", {"kind": "settings", "file": HOME_FILE, "base": SHA, "changes": [{**ADD, "entry": f"Bash(make{chr(0x34F)} build:*)"}]}, "U+034F"),
            ("variation selector in an entry", {"kind": "settings", "file": HOME_FILE, "base": SHA, "changes": [{**ADD, "entry": f"Bash(make build{chr(0xE0100)}:*)"}]}, "U+E0100"),
            ("Hangul filler in a path", {"kind": "settings", "file": f"/home/op{chr(0xFFA0)}/.claude/settings.json", "base": SHA, "changes": [ADD]}, "U+FFA0"),
        ):
            with self.subTest(name=name):
                for path in ("/api/firewall/preview", "/api/sign"):
                    status, body = self.post(path, {"items": [item]})
                    self.assertEqual(status, 400)
                    self.assertIn(code, body.decode("utf-8"))
        self.assertIn("U+2067", signing.settings_problem({"file": f"/home/op{chr(0x2067)}/.claude/settings.json", "base": SHA, "changes": [ADD]}))
        self.assertIn("U+FEFF", signing.settings_problem({"file": HOME_FILE, "base": SHA, "changes": [{**ADD, "entry": f"{chr(0xFEFF)}Bash(make build:*)"}]}))
        self.assertIsNone(signing.settings_problem({"file": HOME_FILE, "base": SHA, "changes": [ADD]}))
        self.assertEqual(self.post("/api/firewall/preview", {"items": [{"kind": "settings", "file": HOME_FILE, "base": SHA, "changes": [ADD]}]})[0], 200)

    def test_removing_a_settings_entry_with_a_hidden_character_is_offered_and_adding_one_is_not(self):
        hidden = f"Bash(make{chr(0x202E)} build:*)"
        self.view([{**self.home_view(), "settings": {"permissions": {**PERMISSIONS, "allow": [*PERMISSIONS["allow"], hidden]}, "sandbox": SANDBOX}}])
        removal = {"kind": "settings", "file": HOME_FILE, "base": SHA, "changes": [{"list": "permissions.allow", "op": "remove", "entry": hidden}]}
        addition = {**removal, "changes": [{"list": "permissions.ask", "op": "add", "entry": hidden}]}
        for path in ("/api/firewall/preview", "/api/sign"):
            with self.subTest(path=path):
                self.assertEqual(self.post(path, {"items": [removal]})[0], 200)
                status, body = self.post(path, {"items": [addition]})
                self.assertEqual(status, 400)
                self.assertIn("U+202E", body.decode("utf-8"))
        self.assertIsNone(signing.hidden_problem(removal["changes"][0], "change"))
        for name, value in (
            ("no list", {"op": "remove", "entry": hidden}),
            ("extra key", {**removal["changes"][0], "note": "x"}),
            ("unknown list", {**removal["changes"][0], "list": "permissions.other"}),
            ("an ask with op remove", {"kind": "ask", "op": "remove", "entry": hidden}),
            ("nested in an item", {"kind": "review", "branch": {"op": "remove", "entry": hidden}}),
        ):
            with self.subTest(name=name):
                self.assertIn("U+202E", signing.hidden_problem(value, "item"))

    def test_a_group_set_addressee_legacy_rule_or_pattern_with_a_hidden_character_is_never_offered_for_a_signature(self):
        rlo = chr(0x202E)
        signer = self.pin()
        rule = self.signed_rule(signer, {"kind": "ask", "tool": "Bash", "pattern": "make *", "scope": "/repo*", "expires": time.time() + 3600, "agents": ["s1"]})
        for path, payload in (("/api/firewall/groups", {"name": f"ci{rlo}", "members": ["s1"]}), ("/api/firewall/sets", {"name": f"ci{rlo}", "days": 7, "rules": [rule["id"]]})):
            with self.subTest(path=path):
                status, body = self.post(path, payload)
                self.assertEqual(status, 400)
                self.assertIn("U+202E", body.decode("utf-8"))
        for code in (0x2028, 0x2029, 0x85, 0x0B, 0x0D, 0x34F, 0xFE0F, 0xE0100, 0x3164, 0x1160, 0xA0, 0x3000):
            with self.subTest(code=code):
                status, body = self.post("/api/rules/sign", {"kind": "ask", "tool": "Bash", "pattern": f"make test{chr(code)}in /safe", "scope": "/repo*", "expires": time.time() + 3600})
                self.assertEqual(status, 400)
                self.assertIn(f"U+{code:04X}", body.decode("utf-8"))
        stored = self.httpd.hub.rules.get(rule["id"])
        legacy = {key: value for key, value in stored["proof"]["payload"].items() if key != signing.TARGET}
        self.httpd.hub.rules.change(rule["id"], {"enabled": False, "proof": {**stored["proof"], "payload": {**legacy, "pattern": f"make test{rlo}*"}}})
        status, body = self.post("/api/sign", {"items": [{"kind": "enable", "rule": rule["id"]}]})
        self.assertEqual(status, 400)
        self.assertIn("U+202E", body.decode("utf-8"))
        self.claim("s1", f"Skills{rlo}")
        ask_id = self.create_ask(ASK)
        shown = next(item for item in self.snapshot()["inbox"] if item["id"] == ask_id)
        self.assertIn(rlo, shown["to"])
        status, body = self.post("/api/sign", {"items": [{**self.entry("ask", ask_id, "", ""), "verb": "reject", "channel": "post", "reason": "no", "to": shown["to"]}]})
        self.assertEqual(status, 400)
        self.assertIn("U+202E", body.decode("utf-8"))
        self.assertEqual(self.post("/api/sign", {"items": [self.entry("ask", ask_id, "", "")]})[0], 200)

    def test_the_hub_keeps_only_permissions_and_sandbox_and_refuses_a_view_unsafe_to_copy(self):
        self.view([self.home_view()])
        files, _ = self.httpd.hub.settings_files()
        self.assertEqual(sorted(files[0]["settings"]), ["permissions", "sandbox"])
        domain = {"kind": "settings", "file": HOME_FILE, "base": SHA, "changes": [{"list": "sandbox.network.allowedDomains", "op": "add", "entry": "example.org"}]}
        status, body = self.post("/api/firewall/preview", {"items": [domain]})
        self.assertEqual(status, 200, body)
        self.assertNotIn('"env"', json.loads(body)["diffs"][0]["diff"])
        deep = functools.reduce(lambda inner, _: {"x": inner}, range(600), {})
        for name, extra, reason in (("600 levels", deep, "nests deeper than 64"), ("lone surrogate", "\ud800", "lone surrogate")):
            with self.subTest(name=name):
                self.view([{**self.home_view(), "settings": {"permissions": {**PERMISSIONS, "extra": extra}, "sandbox": SANDBOX}}])
                status, body = self.post("/api/firewall/preview", {"items": [{**domain, "changes": [ADD]}]})
                self.assertEqual(status, 400, body)
                self.assertIn(reason, body.decode("utf-8"))

    def test_groups_and_rule_sets_hold_known_agents_and_stored_rules(self):
        for name, payload, expected in (
            ("unknown session", {"name": "builders", "members": ["s1", "s9"]}, 400),
            ("every agent", {"name": "builders", "members": ["*"]}, 400),
            ("unsorted", {"name": "builders", "members": ["s2", "s1"]}, 400),
            ("empty name", {"name": " ", "members": ["s1"]}, 400),
            ("extra key", {"name": "builders", "members": ["s1"], "rule": "x"}, 400),
        ):
            with self.subTest(name=name):
                self.assertEqual(self.post("/api/firewall/groups", payload)[0], expected)
        status, body = self.post("/api/firewall/groups", {"name": "builders", "members": ["s1", "s2"]})
        self.assertEqual(status, 201, body)
        group = json.loads(body)
        self.assertEqual(self.post("/api/firewall/groups", {"name": "builders", "members": ["s1"]})[0], 409)
        self.assertEqual([(entry["name"], entry["members"]) for entry in self.firewall()["groups"]], [("builders", ["s1", "s2"])])
        signer = self.pin()
        rule = self.signed_rule(signer, {"kind": "ask", "tool": "Bash", "pattern": "make *", "scope": "/repo*", "expires": time.time() + 3600, "agents": ["s1"]})
        for name, payload in (("no days", {"name": "ci", "days": 0, "rules": [rule["id"]]}), ("unknown rule", {"name": "ci", "days": 7, "rules": ["0123456789abcdef"]}), ("no rules", {"name": "ci", "days": 7, "rules": []})):
            with self.subTest(name=name):
                self.assertEqual(self.post("/api/firewall/sets", payload)[0], 400)
        status, body = self.post("/api/firewall/sets", {"name": "ci", "days": 7, "rules": [rule["id"]]})
        self.assertEqual(status, 201, body)
        stored = json.loads(body)
        self.assertEqual((stored["days"], stored["rules"]), (7, [{"kind": "ask", "tool": "Bash", "pattern": "make *", "scope": "/repo*"}]))
        for path, ident in (("groups", group["id"]), ("sets", stored["id"])):
            with self.subTest(path=path):
                self.assertEqual(self.call("POST", f"/api/firewall/{path}/{ident}/delete", b"", self.guard(self.host))[0], 200)
                self.assertEqual(self.call("POST", f"/api/firewall/{path}/{ident}/delete", b"", self.guard(self.host))[0], 404)

    def signed_rule(self, signer, fields: dict) -> dict:
        status, _, body = self.post_json("/api/rules/sign", fields, self.guard(self.host))
        self.assertEqual(status, 200, body)
        payload = json.loads(body)["payload"]
        status, _, body = self.post_json("/api/rules", {"rule": payload, "assertion": signer.assertion(payload, self.origin, "localhost", PRESENT, 0), "enabled": True}, self.guard(self.host))
        self.assertEqual(status, 201, body)
        return json.loads(body)

    def test_a_rule_applies_to_one_agent_a_group_or_every_agent(self):
        signer = self.pin()
        now = time.time()
        base = {"kind": "ask", "tool": "Bash", "scope": "/repo*", "expires": now + 3600}
        for name, agents in (("unknown agent", ["s9"]), ("unsorted group", ["s2", "s1"]), ("pseudo agent", ["name:Docs"]), ("empty", [])):
            with self.subTest(name=name):
                self.assertEqual(self.post_json("/api/rules/sign", {**base, "pattern": "make *", "agents": agents}, self.guard(self.host))[0], 400)
        self.assertEqual(self.post_json("/api/rules/sign", {"kind": "review", "tool": "", "pattern": "feature/*", "scope": "/repo/*", "expires": now + 3600, "agents": ["s1"]}, self.guard(self.host))[0], 400)
        one = self.signed_rule(signer, {**base, "pattern": "make one", "agents": ["s1"]})
        group = self.signed_rule(signer, {**base, "pattern": "make group", "agents": ["s1", "s2"]})
        every = self.signed_rule(signer, {**base, "pattern": "make every"})
        self.assertEqual((one["agents"], group["agents"], every["agents"]), (["s1"], ["s1", "s2"], ["*"]))
        self.assertEqual(one["proof"]["payload"]["agents"], ["s1"])
        with mock.patch.object(batches, "UNDO", 0.05):
            asks = {(command, session): self.create_ask({**ASK, "command": command, "session": session}) for command in ("make one", "make group", "make every") for session in ("s1", "s2", "s3")}
            time.sleep(0.6)
        statuses = {pair: self.ask_status(ask_id, "0") for pair, ask_id in asks.items()}
        self.assertEqual(statuses, {
            ("make one", "s1"): "allowed", ("make one", "s2"): "pending", ("make one", "s3"): "pending",
            ("make group", "s1"): "allowed", ("make group", "s2"): "allowed", ("make group", "s3"): "pending",
            ("make every", "s1"): "allowed", ("make every", "s2"): "allowed", ("make every", "s3"): "allowed",
        })
        hook = verifier.Trust(approvers=self.approvers, replay=self.replay / "hook.json", origin=self.origin)
        relayed = json.loads(self.get(f"/api/asks/{asks[('make one', 's1')]}?wait=0")[2])["proof"]
        verifier.check(relayed, signing.ask_item(asks[("make one", "s1")], "Bash", "make one", "/repo", "s1"), "", hook, time.time())
        with self.assertRaisesRegex(signing.Refused, "does not match"):
            verifier.check(relayed, signing.ask_item(asks[("make one", "s2")], "Bash", "make one", "/repo", "s2"), "", hook, time.time())

    def test_a_decision_rule_scoped_to_an_agent_decides_only_decisions_under_the_name_it_holds_now(self):
        for session, name in (("s1", "Docs"), ("s1", "Main"), ("s1", "Skills"), ("s2", "Main")):
            time.sleep(1.1)
            self.claim(session, name)
            self.snapshot()
        held = {(entry["session"], entry["name"]) for entry in self.httpd.hub.names.listed()}
        self.assertLessEqual({("s1", "Docs"), ("s1", "Main"), ("s1", "Skills"), ("s2", "Main")}, held)
        signer = self.pin()
        self.signed_rule(signer, {"kind": "decision", "tool": "", "pattern": "*", "scope": "*", "expires": time.time() + 3600, "agents": ["s1"]})
        options = [{"label": "Yes", "description": ""}, {"label": "No", "description": ""}]
        with mock.patch.object(batches, "UNDO", 0.05):
            asked = {name: self.tool("decision_request", {"question": "Merge?", "options": options, "agent": name, "recommended": "Yes"})["structuredContent"]["id"] for name in ("Skills", "Main", "Docs", "Stage")}
            self.settle(lambda: self.choice(asked["Skills"]) == "Yes")
            time.sleep(0.3)
        self.assertEqual({name: self.choice(decision) for name, decision in asked.items()}, {"Skills": "Yes", "Main": None, "Docs": None, "Stage": None})
        self.claim("s3", "Skills")
        self.snapshot()
        with mock.patch.object(batches, "UNDO", 0.05):
            shared = self.tool("decision_request", {"question": "Merge?", "options": options, "agent": "Skills", "recommended": "Yes"})["structuredContent"]["id"]
            time.sleep(0.6)
        self.assertIsNone(self.choice(shared))

    def test_turning_a_rule_on_needs_a_fresh_passkey_signature_and_turning_it_off_none(self):
        signer = self.pin()
        rule = self.signed_rule(signer, {"kind": "ask", "tool": "Bash", "pattern": "make *", "scope": "/repo*", "expires": time.time() + 3600})
        other = self.signed_rule(signer, {"kind": "ask", "tool": "Bash", "pattern": "make other", "scope": "/repo*", "expires": time.time() + 3600})
        enable = f"/api/rules/{rule['id']}/enable"
        self.assertEqual(self.call("POST", f"/api/rules/{rule['id']}/disable", b"", self.guard(self.host))[0], 200)
        unsigned = (("no body", b""), ("no proof", b'{"proof": null}'), ("the rule's own signature", json.dumps({"proof": rule["proof"]}).encode()))
        for name, body in unsigned:
            with self.subTest(name=name):
                self.assertEqual(self.call("POST", enable, body, self.guard(self.host))[0], 400)
                self.assertFalse(self.httpd.hub.rules.get(rule["id"])["enabled"])
        offer = self.prepare([{"kind": "enable", "rule": rule["id"]}])
        self.assertEqual((offer["enables"], offer["payload"]["items"]), (rule["proof"]["payload"], [signing.item_hash(signing.enable_item(rule["proof"]["payload"]))]))
        self.assertEqual(self.post("/api/sign", {"items": [{"kind": "enable", "rule": "0123456789abcdef"}]})[0], 404)
        proof = signer.proof(offer["payload"], self.origin)
        foreign = signer.proof(self.prepare([{"kind": "enable", "rule": other["id"]}])["payload"], self.origin)
        for name, body in (("forged", {"proof": key(-7, "intruder").proof(offer["payload"], self.origin)}), ("another rule's approval", {"proof": foreign})):
            with self.subTest(name=name):
                self.assertEqual(self.post(enable, body)[0], 400)
                self.assertFalse(self.httpd.hub.rules.get(rule["id"])["enabled"])
        with mock.patch.object(batches, "UNDO", 0.05):
            waiting = self.create_ask({**ASK, "command": "make x", "session": "s1"})
            time.sleep(0.6)
        self.assertEqual(self.ask_status(waiting, "0"), "pending")
        status, body = self.post(enable, {"proof": proof})
        self.assertEqual((status, json.loads(body)["enabled"]), (200, True), body)
        self.assertEqual(self.call("POST", f"/api/rules/{rule['id']}/disable", b"", self.guard(self.host))[0], 200)
        self.assertEqual(self.post(enable, {"proof": proof})[0], 400)
        self.assertFalse(self.httpd.hub.rules.get(rule["id"])["enabled"])

    def test_a_deleted_rule_never_comes_back_with_its_old_proof_and_a_fresh_signature_does(self):
        signer = self.pin()
        fields = {"kind": "ask", "tool": "Bash", "pattern": "make *", "scope": "/repo*", "expires": time.time() + 3600}
        rule = self.signed_rule(signer, fields)
        old = {"rule": rule["proof"]["payload"], "assertion": rule["proof"]["assertion"], "enabled": True}
        self.assertEqual(self.post("/api/rules", old)[0], 409)
        self.assertEqual(self.call("POST", f"/api/rules/{rule['id']}/delete", b"", self.guard(self.host))[0], 200)
        self.assertEqual(self.post("/api/rules", old)[0], 409)
        self.assertIsNone(self.httpd.hub.rules.get(rule["id"]))
        unsigned = json.loads(self.post("/api/rules/sign", fields)[1])["payload"]
        object.__setattr__(self.httpd.hub, "offers", rules.Offers())
        self.assertEqual(self.post("/api/rules", {"rule": unsigned, "assertion": signer.assertion(unsigned, self.origin, "localhost", PRESENT, 0), "enabled": True})[0], 409)
        fresh = self.signed_rule(signer, fields)
        self.assertEqual([stored["id"] for stored in self.httpd.hub.rules.listed()], [fresh["id"]])
        with mock.patch.object(batches, "UNDO", 0.05):
            asked = self.create_ask({**ASK, "command": "make x", "session": "s1"})
            time.sleep(0.6)
        self.assertEqual(self.ask_status(asked, "0"), "allowed")

    def test_a_group_changed_after_signing_grants_nothing_beyond_the_signed_members(self):
        self.claim("s3", "Evil")
        self.snapshot()
        signer = self.pin()
        group = json.loads(self.post("/api/firewall/groups", {"name": "builders", "members": ["s1", "s2"]})[1])
        self.signed_rule(signer, {"kind": "ask", "tool": "Bash", "pattern": "make *", "scope": "/repo*", "expires": time.time() + 3600, "agents": group["members"]})
        self.assertEqual(self.call("POST", f"/api/firewall/groups/{group['id']}/delete", b"", self.guard(self.host))[0], 200)
        self.assertEqual(self.post("/api/firewall/groups", {"name": "builders", "members": ["s1", "s2", "s3"]})[0], 201)
        with mock.patch.object(batches, "UNDO", 0.05):
            asks = {session: self.create_ask({**ASK, "command": "make x", "session": session}) for session in ("s1", "s3")}
            time.sleep(0.6)
        self.assertEqual({session: self.ask_status(ask_id, "0") for session, ask_id in asks.items()}, {"s1": "allowed", "s3": "pending"})

    def test_the_signed_target_decides_and_an_untargeted_rule_reaches_every_agent(self):
        now = time.time()
        plain = signing.rule_payload("0123456789abcdef", ["ask"], "Bash", "make *", "*", int(now) + 600)
        item = signing.ask_item("fedcba9876543210", "Bash", "make x", "/repo", "s2")
        self.assertTrue(signing.rule_allows(plain, item, "", now))
        self.assertTrue(signing.rule_allows(signing.targeted(plain, ["*"]), item, "", now))
        self.assertTrue(signing.rule_allows(signing.targeted(plain, ["s1", "s2"]), item, "", now))
        self.assertFalse(signing.rule_allows(signing.targeted(plain, ["s1"]), item, "", now))
        review = signing.rule_payload("0123456789abcdef", ["review"], "", "*", "*", int(now) + 600)
        commit = signing.review_item("fedcba9876543210", "/repo/.git", "/repo", "feature/x", "0" * 40)
        self.assertTrue(signing.rule_allows(review, commit, "pass", now))
        self.assertFalse(signing.rule_allows(signing.targeted(review, ["s1"]), commit, "pass", now))
        for agents in ([], ["s2", "s1"], ["s1", "s1"], ["*", "s1"], "s1", [3]):
            with self.subTest(agents=agents), self.assertRaises(signing.Refused):
                signing.checked_rule(signing.targeted(plain, agents), now)
        subject = {"recommended": "Yes", "agent": "Skills", "sessions": {"s1"}}
        stored = {"kind": "decision", "pattern": "*", "enabled": True, "expires": now + 600}
        targeted = {**stored, "proof": {"payload": signing.targeted(review, ["s2"])}}
        self.assertFalse(rules.rule_matches(targeted, "decision", subject, now))
        self.assertTrue(rules.rule_matches({**stored, "proof": {"payload": signing.targeted(review, ["s1"])}}, "decision", subject, now))
