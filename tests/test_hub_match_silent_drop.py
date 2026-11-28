"""Exercise requirement 096: Reject on an expired Match card drops it silently, and the release dismisses it hub-wide."""

from __future__ import annotations

import json
import re
import subprocess
import time
import unittest
from unittest import mock

from hub_support import ASK, HUB, signing
from kvb_orchestrator import batches, skill_scripts
from test_hub_match import MatchCase

MATCH = HUB / "templates" / "page-match.js"
NAMES = ("lapsedCard", "droppable", "toBack", "logStep", "undoStep", "decisionOf", "dropCard", "refusedHere", "pickOnly", "rejectCard", "unreleasable", "risky", "releasePlan", "matchEntry")
PROBE = r"""
const vm = require("vm");
const sandbox = {
  RELEASE: "release",
  matchView: {order: [], decisions: new Map(), history: []},
  refusedIds: new Map(),
  Answers: {pair: () => null},
  expiredWords: () => "expired 20:41, 3 minutes ago",
  FEEDBACK_LIMIT: 2000,
  h: () => ({value: "", addEventListener: () => {}, focus: () => {}}),
  icon: () => null,
  btn: () => null,
  reasonChips: () => null,
  closeSheet: () => {},
  feedbackOf: () => "",
  sheets: [],
  draws: 0,
  toasts: [],
  out: {},
};
sandbox.openSheet = (title) => sandbox.sheets.push(title);
sandbox.drawMatch = () => {
  sandbox.draws += 1;
};
sandbox.toast = (title) => sandbox.toasts.push(title);
vm.runInNewContext(process.argv[1], sandbox);
vm.runInNewContext(`
  const card = (id, extra) => ({id: "ask:" + id, ref: id, kind: "ask", entry: "ask", title: id, hash: "h-" + id, blocked: "", to: "Skills", ...extra});
  const expired = card("x", {blocked: "expired", blocked_kind: "expired"});
  const claude = card("c", {blocked: "answer it there", blocked_kind: "claude"});
  matchView.order = [expired.id, "ask:f"];
  rejectCard(expired);
  const drop = matchView.decisions.get(expired.id);
  out.drop = {verdict: drop.verdict, feedback: drop.feedback, sheets: sheets.length, draws, steps: matchView.history.length, shown: Boolean(decisionOf(expired))};
  undoStep();
  out.undone = {decided: matchView.decisions.has(expired.id), front: matchView.order[0]};
  rejectCard(expired);
  rejectCard(claude);
  out.claudeSheets = sheets.length;
  out.unreleasable = unreleasable(expired, matchView.decisions.get(expired.id));
  const reject = {verdict: "reject", feedback: "not now", label: ""};
  const plan = releasePlan([[expired, matchView.decisions.get(expired.id)], [card("f"), reject], [card("w", {withdrawn: true}), reject], [card("v", {withdrawn: true, blocked_kind: "expired"}), {verdict: "drop", feedback: "", label: ""}]]);
  const ids = (pairs) => pairs.map(([one]) => one.ref);
  out.plan = {dismissals: ids(plan.dismissals), rest: ids(plan.rest), gone: ids(plan.gone), lone: ids(plan.lone), bad: ids(plan.bad), held: ids(plan.held)};
  out.entries = [matchEntry(expired, matchView.decisions.get(expired.id)), matchEntry(card("f"), reject)];
`, sandbox);
console.log(JSON.stringify(sandbox.out));
"""


def extracted() -> str:
    source = MATCH.read_text(encoding="utf-8")
    parts = []
    for name in NAMES:
        found = re.search(rf"^  const {name} = [^\n]*;$", source, re.MULTILINE) or re.search(rf"^  (?:function {name}\(|const {name} = ).*?^  }};?$", source, re.MULTILINE | re.DOTALL)
        if found is None:
            raise AssertionError(f"{name} not found in {MATCH}")
        parts.append(found.group(0).replace(f"const {name} = ", f"var {name} = "))
    return "\n".join(parts)


class TestSilentDrop(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        done = subprocess.run(["node", "-e", PROBE, extracted()], capture_output=True, text=True, timeout=60, check=False)
        if done.returncode != 0:
            raise AssertionError(done.stderr[-4000:])
        cls.data = json.loads(done.stdout)

    def test_reject_on_an_expired_card_drops_it_without_a_sheet(self):
        self.assertEqual(self.data["drop"], {"verdict": "drop", "feedback": "", "sheets": 0, "draws": 1, "steps": 1, "shown": True})

    def test_s_puts_the_dropped_card_back_in_front(self):
        self.assertEqual(self.data["undone"], {"decided": False, "front": "ask:x"})

    def test_a_card_open_in_claude_keeps_its_feedback_sheet(self):
        self.assertEqual(self.data["claudeSheets"], 1)

    def test_a_drop_releases(self):
        self.assertEqual(self.data["unreleasable"], "")

    def test_the_plan_puts_a_dropped_expired_card_into_the_dismissals_not_the_radio_rejects(self):
        self.assertEqual(self.data["plan"], {"dismissals": ["x"], "rest": ["f"], "gone": ["w"], "lone": [], "bad": [], "held": []})

    def test_a_drop_is_released_as_a_dismissal_of_the_expired_request(self):
        dismissal, rejection = self.data["entries"]
        self.assertEqual(dismissal, {"kind": "dismiss", "target": "ask", "id": "x", "scope": "expired"})
        self.assertEqual((rejection["verb"], rejection["channel"], rejection["reason"]), ("reject", "call", "not now"))


class TestReleasedDismissal(MatchCase):
    def setUp(self):
        super().setUp()
        self.claim("s1", "Skills session")
        self.expired = self.create_ask({**ASK, "call_key": signing.call_key("Bash", {"command": ASK["command"]})})
        self.httpd.hub.asks.change(self.expired, {"expires": time.time() - 600})
        self.open = self.create_ask({**ASK, "command": "make open", "timeout": 3600})

    def radio(self) -> list[list[str]]:
        return [args for script, args in self.scripts.calls if script == skill_scripts.RADIO]

    def release(self) -> list[dict]:
        return [self.entry("ask", self.open, "", ""), {"kind": "dismiss", "target": "ask", "id": self.expired, "scope": "expired"}]

    def shown(self) -> list[str]:
        return [card["id"] for card in self.cards()]

    def test_one_signature_releases_a_grant_and_a_dismissal_and_no_agent_hears_of_the_drop(self):
        entries = self.release()
        self.assertIn(f"ask:{self.expired}", self.shown())
        with mock.patch.object(batches, "UNDO", 0.05):
            status, _, body = self.approve(entries, self.signed(entries, self.pin()))
            self.assertEqual(status, 202, body)
            self.assertEqual(sorted((item["id"], item["verb"]) for item in json.loads(body)["items"]), sorted([(self.open, "approve"), (self.expired, "dismiss")]))
            self.settle(lambda: self.httpd.hub.dismissals.listed() != [] and self.httpd.hub.asks.get(self.open)["status"] == "allowed")
        self.assertNotIn(f"ask:{self.expired}", self.shown())
        self.assertNotIn(f"ask:{self.expired}", [item["id"] for item in self.snapshot()["lapsed"]])
        self.assertEqual(self.httpd.hub.asks.get(self.expired)["status"], "pending")
        self.assertEqual(self.radio(), [])

    def test_the_undo_brings_the_dropped_card_back(self):
        entries = self.release()
        with mock.patch.object(batches, "UNDO", 60):
            status, _, body = self.approve(entries, self.signed(entries, self.pin()))
            self.assertEqual(status, 202, body)
            self.assertNotIn(f"ask:{self.expired}", self.shown())
            status, _, body = self.post_json(f"/api/inbox/undo/{json.loads(body)['id']}", {}, self.guard(self.host))
            self.assertEqual(status, 200, body)
        self.assertEqual(self.card(f"ask:{self.expired}")["blocked_kind"], "expired")
        self.assertEqual(self.httpd.hub.dismissals.listed(), [])
        self.assertEqual(self.radio(), [])

    def test_an_unsigned_partly_signed_or_doubled_dismissal_is_refused(self):
        entries = self.release()
        status, _, body = self.approve(entries, None)
        self.assertEqual(status, 400, body)
        self.assertIn("not signed", body.decode())
        signer = self.pin()
        status, _, body = self.approve(entries, self.signed(entries[:1], signer))
        self.assertEqual(status, 400, body)
        doubled = [self.entry("ask", self.open, "", ""), {"kind": "dismiss", "target": "ask", "id": self.open, "scope": "all"}]
        self.assertEqual(self.post_json("/api/sign", {"items": doubled}, self.guard(self.host))[0], 400)
        self.assertEqual(self.httpd.hub.dismissals.listed(), [])
        self.assertIn(f"ask:{self.expired}", self.shown())


if __name__ == "__main__":
    unittest.main()
