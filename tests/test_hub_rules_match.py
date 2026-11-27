"""Exercise requirement 067: each hub rule and the rules form's draft count the last asks the rule matcher would grant."""

from __future__ import annotations

import json
import time
import unittest

from hub_case import HubCase
from hub_support import ASK
from kvb_orchestrator import requesting, rules
from kvb_orchestrator.errors import ToolError

COMMANDS = (("make deploy", "s1"), ("make deploy --dry", "s1"), ("make deploy", "s2"), ("make test", "s1"), ("git status", "s1"))
DRAFT = {"kind": "ask", "tool": "Bash", "pattern": "make deploy*", "scope": "/repo*"}
BAD = (
    ("empty pattern", {"pattern": ""}),
    ("unknown kind", {"kind": "grant"}),
    ("ask without tool", {"tool": ""}),
    ("past expiry", {"expires": 1}),
    ("unknown agent", {"agents": ["s9"]}),
)


def fixture_asks() -> list[dict]:
    return [rules.subject_of("ask", {"id": f"{index:016x}", "tool": "Bash", "command": command, "cwd": "/repo", "session": session}, set()) for index, (command, session) in enumerate(COMMANDS)]


class TestWindowCount(unittest.TestCase):
    def test_three_matching_asks_of_five_count_three(self):
        self.assertEqual(requesting.window_count(DRAFT, fixture_asks(), time.time()), {"matched": 3, "of": 5})

    def test_the_count_keeps_to_the_rule_agents_and_ignores_on_off_and_expiry(self):
        now = time.time()
        self.assertEqual(requesting.window_count({**DRAFT, "agents": ["s2"]}, fixture_asks(), now), {"matched": 1, "of": 5})
        self.assertEqual(requesting.window_count({**DRAFT, "enabled": False, "expires": now - 60}, fixture_asks(), now), {"matched": 3, "of": 5})

    def test_a_warned_or_chained_pattern_counts_nothing(self):
        for pattern in ("git push *", "make deploy* && *"):
            with self.subTest(pattern=pattern):
                self.assertEqual(requesting.window_count({**DRAFT, "pattern": pattern}, fixture_asks(), time.time())["matched"], 0)

    def test_a_bad_draft_raises_before_it_is_counted(self):
        now = time.time()
        for name, change in BAD[:4]:
            with self.subTest(name=name), self.assertRaises(ToolError):
                rules.rule_fields({**DRAFT, "expires": now + 3600, **change}, rules.EVERY_AGENT, now)


class TestHubRulesMatch(HubCase):
    def setUp(self):
        super().setUp()
        self.claim("s1", "Skills")
        self.claim("s2", "Stage")
        self.snapshot()

    def asked(self) -> None:
        for command, session in COMMANDS:
            self.create_ask({**ASK, "command": command, "session": session})

    def match(self, payload: object) -> tuple[int, bytes]:
        status, _, body = self.post_json("/api/rules/match", payload, self.guard(self.host))
        return status, body

    def listing(self) -> list[str]:
        return sorted(str(path.relative_to(self.state)) for path in self.state.rglob("*"))

    def test_the_match_call_answers_the_count_of_the_last_asks_and_writes_nothing(self):
        self.asked()
        before = self.listing()
        rules_file = self.httpd.hub.rules.file.exists()
        status, body = self.match({**DRAFT, "expires": time.time() + 3600})
        self.assertEqual((status, json.loads(body)), (200, {"matched": 3, "of": 5}), body)
        status, body = self.match({**DRAFT, "expires": time.time() + 3600, "agents": ["s2"]})
        self.assertEqual((status, json.loads(body)), (200, {"matched": 1, "of": 5}), body)
        self.assertEqual(self.listing(), before)
        self.assertEqual((self.httpd.hub.rules.listed(), self.httpd.hub.rules.file.exists()), ([], rules_file))

    def test_a_bad_draft_answers_400(self):
        self.asked()
        for name, change in BAD:
            with self.subTest(name=name):
                status, body = self.match({**DRAFT, "expires": time.time() + 3600, **change})
                self.assertEqual(status, 400, body)
        for name, payload in (("unknown field", {**DRAFT, "expires": time.time() + 3600, "enabled": True}), ("no object", ["ask"]), ("missing expiry", DRAFT)):
            with self.subTest(name=name):
                self.assertEqual(self.match(payload)[0], 400)

    def test_the_match_call_is_an_action_post_with_the_same_guards_as_the_rules_form(self):
        payload = json.dumps({**DRAFT, "expires": time.time() + 3600}).encode()
        for name, headers in (("no guard header", {"Host": self.host, "Origin": f"http://{self.host}"}), ("foreign origin", {**self.guard(self.host), "Origin": "http://evil.example"})):
            with self.subTest(name=name):
                self.assertEqual(self.call("POST", "/api/rules/match", payload, {**headers, "Content-Type": "application/json"})[0], 403)
        self.assertEqual(self.get("/api/rules/match")[0], 405)

    def test_the_window_holds_the_last_fifty_asks(self):
        for index in range(requesting.MATCH_WINDOW + 3):
            self.create_ask({**ASK, "command": f"make deploy {index}" if index < 3 else "make test"})
        status, body = self.match({**DRAFT, "expires": time.time() + 3600})
        self.assertEqual((status, json.loads(body)), (200, {"matched": 0, "of": requesting.MATCH_WINDOW}), body)

    def test_every_stored_rule_in_the_payload_carries_its_match_count(self):
        self.asked()
        signer = self.pin()
        later = time.time() + 3600
        deploy = self.signed_rule(signer, {**DRAFT, "expires": later})
        mine = self.signed_rule(signer, {**DRAFT, "pattern": "make *", "expires": later, "agents": ["s2"]})
        review = self.signed_rule(signer, {"kind": "review", "tool": "", "pattern": "feature/*", "scope": "/repo/*", "expires": later})
        self.assertEqual(self.call("POST", f"/api/rules/{deploy['id']}/disable", b"", self.guard(self.host))[0], 200)
        shown = {rule["id"]: (rule["matched"], rule["of"]) for rule in self.snapshot()["rules"]}
        self.assertEqual(shown, {deploy["id"]: (3, 5), mine["id"]: (1, 5), review["id"]: (0, 0)})


if __name__ == "__main__":
    unittest.main()
