"""Exercise requirement 094 in Chromium: Claude's answer closes a card within 5 s, and a card whose hook stopped waiting reads open in Claude."""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

import hub_e2e_kit as base
from hub_case import HubCase
from hub_support import ASK, signing
from kvb_orchestrator.asking import ENDED, TERMINAL

OUT = Path(os.environ.get("E2E_OUT", "/tmp/hub-094-dialog-shots"))
AGO = 690
CLOSE_MS = 5000
TIP = re.compile(r"^open in Claude since \d{2}:\d{2}, 1[2-4] minutes ago$")
QUESTION = "Push the branch?"
ANSWER = "Later"
OPTIONS = [{"label": "Now", "description": ""}, {"label": ANSWER, "description": ""}]
QUESTIONS = {"questions": [{"question": QUESTION, "options": [{"label": "Now"}, {"label": ANSWER}]}]}
ASKED = signing.call_key("AskUserQuestion", QUESTIONS)
CLOSER = "a" * 43
REPORT = """
  const report = (body) => fetch("/api/asks/ran", {method: "POST", headers: {"Content-Type": "application/json", "X-Kvb-Orchestrator": "1"}, body: JSON.stringify(body)}).then((response) => response.status);
  const timed = async (body, check) => {
    const start = Date.now();
    const status = await report(body);
    const done = await until(check, @CLOSE_MS@ + 1000);
    return {status, ms: done ? Date.now() - start : null};
  };
"""
BINDING = """(async () => {@HELPERS@@REPORT@
  const count = () => all("#main .muted").map(text).find((words) => /^[0-9]+ cards? waits?$/.test(words)) || "";
  if (!(await until(() => count() === "5 cards wait", 8000))) {
    return {error: `deck shows ${count() || text(document.getElementById("main"))}`};
  }
  await sleep(2500);
  const found = {};
  found.ran = await timed({event: "PostToolUse", call_key: "@KEY@", session: "s1", closer: "@CLOSER@"}, () => count() === "4 cards wait");
  found.answered = await timed({event: "PostToolUse", call_key: "@ASKED@", session: "s4", answers: {"@QUESTION@": "@ANSWER@"}, closer: "@CLOSER@"}, () => count() === "3 cards wait");
  found.stop = await timed({event: "Stop", session: "s2", closer: "@CLOSER@"}, () => count() === "2 cards wait");
  found.ended = await timed({event: "SessionEnd", session: "s3", closer: "@CLOSER@"}, () => count() === "1 card waits");
  found.front = document.querySelector("#main .match-card.front") ? document.querySelector("#main .match-card.front").dataset.card : null;
  return found;
})()"""
STAMP = """(async () => {@HELPERS@
  const card = await until(() => document.querySelector("#main .match-card.front"), 8000);
  if (!card) {
    return {error: text(document.getElementById("main"))};
  }
  const stamp = card.querySelector(".match-stamp");
  if (stamp) {
    stamp.dispatchEvent(new MouseEvent("mouseenter"));
  }
  return {
    id: card.dataset.card, stamp: stamp ? text(stamp) : null, kind: stamp ? stamp.dataset.stamp : null, tip: stamp ? stamp.title : null,
    blocked: text(card.querySelector(".match-blocked")), words: text(card), stale: card.dataset.stale,
    accept: document.querySelector("#main .match-accept").disabled, reject: document.querySelector("#main .match-reject").disabled,
    wide: document.documentElement.scrollWidth > window.innerWidth + 1,
  };
})()"""
STREAM = """(async () => {@HELPERS@
  await streamShowsAll();
  const entry = (words) => all("#main .feed > li").find((row) => text(row).includes(words));
  const decision = await until(() => entry("@QUESTION@"), 8000);
  const ask = await until(() => entry("make deploy"), 8000);
  const pills = (row) => (row ? all(".msg-meta .pill", row).map(text) : null);
  return {decision: pills(decision), ask: pills(ask), blocked: ask ? ask.getAttribute("title") : null};
})()"""
INBOX = """(async () => {@HELPERS@@REPORT@
  const row = () => document.querySelector('#main .inbox-list > li[data-ref="ask:@LAPSED@"]');
  if (!(await until(row, 8000))) {
    return {error: text(document.getElementById("main"))};
  }
  const pills = all(".msg-meta .pill", row()).map(text);
  const actions = all(".item-actions .btn, .code-box .btn.primary", row()).map(text).filter((words) => /^(Grant|Deny|Allow)/.test(words));
  await sleep(2500);
  const closed = await timed({event: "UserPromptSubmit", session: "s1", closer: "@CLOSER@"}, () => !row());
  return {pills, actions, closed};
})()"""


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestDialogBoundCards(HubCase):
    drive = base.OrchestratorE2ECase.drive

    def setUp(self):
        super().setUp()
        for session, name in (("s1", "Skills session"), ("s2", "Store session"), ("s3", "Main session"), ("s4", "Stage session")):
            self.claim(session, name)
        saved = self.httpd.hub.settings.get()
        self.httpd.hub.settings.put({**saved, "match": {"refresh": 60}}, saved)
        self.key = signing.call_key("Bash", {"command": "make build"})
        self.lapsed = self.create_ask({**ASK, "call_key": signing.call_key("Bash", {"command": ASK["command"]}), "bound": True, "closer": CLOSER})
        self.httpd.hub.asks.change(self.lapsed, {"expires": time.time() - AGO})
        self.ran = self.create_ask({**ASK, "command": "make build", "call_key": self.key, "bound": True, "closer": CLOSER, "timeout": 600})
        self.stopped = self.create_ask({**ASK, "command": "make lint", "session": "s2", "bound": True, "closer": CLOSER, "timeout": 600})
        self.ended = self.create_ask({**ASK, "command": "make docs", "session": "s3", "bound": True, "closer": CLOSER, "timeout": 600})
        status, _, body = self.post_json("/api/decisions", {"question": QUESTION, "options": OPTIONS, "session": "s4", "timeout": 600, "multi": False, "call_key": ASKED, "bound": True, "closer": CLOSER}, self.local())
        self.assertEqual(status, 201, body)
        self.answered = json.loads(body)["id"]

    def step(self, name: str, width: int, height: int, screen: str, probe: str) -> dict:
        flow = probe.replace("@HELPERS@", base.HELPERS).replace("@REPORT@", REPORT).replace("@CLOSE_MS@", str(CLOSE_MS))
        for marker, value in (("@KEY@", self.key), ("@ASKED@", ASKED), ("@QUESTION@", QUESTION), ("@ANSWER@", ANSWER), ("@LAPSED@", self.lapsed), ("@CLOSER@", CLOSER)):
            flow = flow.replace(marker, value)
        return {"width": width, "height": height, "url": f"http://localhost:{self.port}/?{name}-{width}#{screen}", "wait": 1500, "probe": flow, "shot": str(OUT / f"chromium-{name}-{width}.png")}

    def test_chromium_drops_cards_claude_answered_within_5_s_and_shows_the_timed_out_one_open_in_claude(self):
        OUT.mkdir(parents=True, exist_ok=True)
        steps = [self.step("binding", 1366, 768, "tasks/match", BINDING)]
        steps += [self.step("open-in-claude", width, height, "tasks/match", STAMP) for width, height in base.WIDTHS]
        steps += [self.step("stream", 1366, 768, "stream", STREAM), self.step("inbox", 1366, 768, "tasks/operator", INBOX)]
        data = self.drive(steps, None)
        (OUT / "chromium-dialog-bound.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "(style-src-elem)" not in error and "/favicon.ico" not in error], [])
        self.assertEqual(len(data["results"]), len(steps), data)
        binding, *stamps, stream, inbox = data["results"]
        self.assertNotIn("error", binding, binding)
        for name in ("ran", "answered", "stop", "ended"):
            with self.subTest(event=name):
                self.assertEqual(binding[name]["status"], 200, binding)
                self.assertIsNotNone(binding[name]["ms"], binding)
                self.assertLess(binding[name]["ms"], CLOSE_MS, binding)
        self.assertEqual(binding["front"], f"ask:{self.lapsed}", binding)
        for found in stamps:
            with self.subTest(width=found.get("id")):
                self.assertNotIn("error", found, found)
                self.assertEqual((found["id"], found["stamp"], found["kind"], found["stale"]), (f"ask:{self.lapsed}", "IN CLAUDE", "claude", "false"), found)
                self.assertRegex(found["tip"], TIP)
                self.assertTrue(found["blocked"].startswith("Open in Claude: answer it there"), found)
                self.assertNotIn("EXPIRED", found["words"])
                self.assertNotIn("STALE", found["words"])
                self.assertEqual((found["accept"], found["reject"], found["wide"]), (True, False, False), found)
        self.assertIn("answered in Claude", stream["decision"], stream)
        self.assertIn(ANSWER, stream["decision"], stream)
        self.assertIn("open in Claude", stream["ask"], stream)
        self.assertNotIn("expired", stream["ask"], stream)
        self.assertEqual(stream["blocked"], "Open in Claude: answer it there", stream)
        self.assertNotIn("error", inbox, inbox)
        self.assertIn("open in Claude", inbox["pills"], inbox)
        self.assertEqual(inbox["actions"], [], inbox)
        self.assertEqual(inbox["closed"]["status"], 200, inbox)
        self.assertIsNotNone(inbox["closed"]["ms"], inbox)
        self.assertLess(inbox["closed"]["ms"], CLOSE_MS, inbox)
        statuses = {ident: self.httpd.hub.asks.get(ident)["status"] for ident in (self.lapsed, self.ran, self.stopped, self.ended)}
        self.assertEqual(statuses, {self.lapsed: TERMINAL, self.ran: TERMINAL, self.stopped: TERMINAL, self.ended: ENDED})
        decision = self.httpd.hub.decisions.get(self.answered)
        self.assertEqual((decision["status"], decision["choice"]), (TERMINAL, ANSWER))


if __name__ == "__main__":
    unittest.main()
