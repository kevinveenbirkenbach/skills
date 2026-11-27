from __future__ import annotations

import json
import re
import subprocess
import unittest

from hub_support import HUB

MATCH = HUB / "templates" / "page-match.js"
NAMES = ("lapsedCard", "toBack", "logStep", "backToStack", "unreleasable", "risky", "releasePlan")
PROBE = r"""
const vm = require("vm");
const sandbox = {
  RELEASE: "release",
  matchView: {order: [], decisions: new Map(), history: []},
  refusedIds: new Map(),
  expiredWords: () => "expired 20:41, 3 minutes ago",
  drawMatch: () => {},
  out: {},
};
vm.runInNewContext(process.argv[1], sandbox);
vm.runInNewContext(`
  const accept = {verdict: "accept"};
  const reject = {verdict: "reject"};
  const card = (id, extra) => ({id, ref: id, kind: "ask", title: id, blocked: "", ...extra});
  const expired = card("x", {blocked: "expired", blocked_kind: "expired"});
  out.expiredAccept = unreleasable(expired, accept);
  out.expiredReject = unreleasable(expired, reject);
  out.blocked = unreleasable(card("b", {blocked: "runs", blocked_kind: "running"}), accept);
  out.fine = unreleasable(card("f"), accept);
  refusedIds.set("r", "expired");
  out.refused = unreleasable(card("r"), accept);
  const plan = releasePlan([[expired, accept], [card("f"), accept], [card("w", {withdrawn: true}), reject]]);
  out.plan = {bad: plan.bad.map(([c]) => c.id), rest: plan.rest.map(([c]) => c.id), gone: plan.gone.map(([c]) => c.id)};
  matchView.order = ["a", "release", "c"];
  matchView.decisions.set("a", accept);
  refusedIds.set("a", "expired");
  backToStack(card("a"));
  out.order = matchView.order.join(",");
  out.undecided = !matchView.decisions.has("a") && !refusedIds.has("a");
  out.steps = matchView.history.length;
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


class TestReleaseCardRepairs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        done = subprocess.run(["node", "-e", PROBE, extracted()], capture_output=True, text=True, timeout=60, check=False)
        if done.returncode != 0:
            raise AssertionError(done.stderr[-4000:])
        cls.data = json.loads(done.stdout)

    def test_an_accepted_card_that_expired_names_its_expiry(self):
        self.assertEqual(self.data["expiredAccept"], "expired 20:41, 3 minutes ago: can no longer be granted; reject or drop it")

    def test_a_reject_of_an_expired_card_still_releases(self):
        self.assertEqual(self.data["expiredReject"], "")

    def test_a_blocked_card_names_its_block(self):
        self.assertIn("not possible now: runs", self.data["blocked"])

    def test_a_card_the_hub_refused_names_the_refusal(self):
        self.assertIn("the hub refused it: expired", self.data["refused"])

    def test_a_fine_card_releases(self):
        self.assertEqual(self.data["fine"], "")

    def test_the_plan_keeps_bad_rows_out_of_the_signed_batch(self):
        self.assertEqual(self.data["plan"], {"bad": ["x"], "rest": ["f"], "gone": ["w"]})

    def test_back_to_the_stack_puts_the_card_last_behind_the_release_card(self):
        self.assertEqual(self.data["order"], "release,c,a")
        self.assertTrue(self.data["undecided"])
        self.assertEqual(self.data["steps"], 1)


if __name__ == "__main__":
    unittest.main()
