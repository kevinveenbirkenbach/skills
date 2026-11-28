from __future__ import annotations

import json
import re
import subprocess
import unittest

from hub_support import HUB

MATCH = HUB / "templates" / "page-match.js"
NAMES = ("toBack", "releaseLast", "matchOrder", "decisionOf")
PROBE = r"""
const vm = require("vm");
const sandbox = {RELEASE: "release", matchView: {order: [], decisions: new Map()}, out: {}};
vm.runInNewContext(process.argv[1], sandbox);
vm.runInNewContext(`
  const card = (id, ts) => ({id, hash: id, created_ts: ts, stale: false, blocked: ""});
  const ids = () => matchView.order.join(",");
  matchView.order = ["a", "b", "release"];
  matchView.decisions.set("a", {verdict: "accept", hash: "a"});
  matchOrder([card("a", 1), card("b", 2), card("c", 3)]);
  out.fresh = ids();
  toBack("b");
  out.later = ids();
  matchView.order = ["release", "b", "c"];
  matchOrder([card("a", 1), card("b", 2), card("c", 3), card("d", 4)]);
  out.shown = ids();
  toBack("release");
  out.back = ids();
`, sandbox);
console.log(JSON.stringify(sandbox.out));
"""


def extracted() -> str:
    source = MATCH.read_text(encoding="utf-8")
    parts = []
    for name in NAMES:
        found = re.search(rf"^  (?:function {name}\(|const {name} = ).*?^  }};?$", source, re.MULTILINE | re.DOTALL)
        if found is None:
            raise AssertionError(f"{name} not found in {MATCH}")
        parts.append(found.group(0).replace(f"const {name} = ", f"var {name} = "))
    return "\n".join(parts)


STAMP_PROBE = r"""
const vm = require("vm");
const sandbox = {};
vm.runInNewContext(process.argv[1], sandbox);
console.log(JSON.stringify(vm.runInNewContext(`[
  greyStamp({stale: false, blocked: ""}),
  greyStamp({stale: false, blocked: "runs", blocked_kind: "running"}),
  greyStamp({stale: false, blocked: "waits", blocked_kind: "queued"}),
  greyStamp({stale: false, blocked: "no dir", blocked_kind: "unrunnable"}),
  greyStamp({stale: true, blocked: "runs", blocked_kind: "running"}),
  greyStamp({stale: false, blocked: "ask held"}),
  greyStamp({stale: false, blocked: "too late", blocked_kind: "expired"}),
  greyStamp({stale: false, blocked: "answer it there", blocked_kind: "claude"}),
].map((key) => [key, key ? MATCH_STAMPS[key] : ""])`, sandbox)));
"""


def stamp_source() -> str:
    source = MATCH.read_text(encoding="utf-8")
    table = re.search(r"^  const MATCH_STAMPS = .*;$", source, re.MULTILINE)
    function = re.search(r"^  function greyStamp\(.*?^  }$", source, re.MULTILINE | re.DOTALL)
    if table is None or function is None:
        raise AssertionError(f"MATCH_STAMPS or greyStamp not found in {MATCH}")
    return table.group(0).replace("const ", "var ", 1) + "\n" + function.group(0)


class TestGreyedCardStamp(unittest.TestCase):
    def test_every_greyed_card_names_its_reason_and_an_active_card_has_none(self):
        done = subprocess.run(["node", "-e", STAMP_PROBE, stamp_source()], capture_output=True, text=True, timeout=60, check=True)
        self.assertEqual(json.loads(done.stdout), [
            ["", ""], ["running", "RUNNING"], ["queued", "QUEUED"], ["blocked", "BLOCKED"], ["stale", "STALE"], ["blocked", "BLOCKED"], ["expired", "EXPIRED"], ["claude", "IN CLAUDE"],
        ])


class TestReleaseCardLast(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        done = subprocess.run(["node", "-e", PROBE, extracted()], capture_output=True, text=True, timeout=60, check=False)
        if done.returncode != 0:
            raise AssertionError(done.stderr[-4000:])
        cls.data = json.loads(done.stdout)

    def test_a_new_card_queues_before_the_release_card(self):
        self.assertEqual(self.data["fresh"], "a,b,c,release")

    def test_later_puts_a_card_behind_the_release_card(self):
        self.assertEqual(self.data["later"], "a,c,release,b")

    def test_a_shown_release_card_stays_in_front_and_new_cards_queue_behind_it(self):
        self.assertEqual(self.data["shown"], "release,b,c,a,d")

    def test_sending_the_release_card_back_puts_it_last(self):
        self.assertEqual(self.data["back"], "b,c,a,d,release")


if __name__ == "__main__":
    unittest.main()
