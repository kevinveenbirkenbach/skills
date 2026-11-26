from __future__ import annotations

import json
import os
import shutil
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

import hub_e2e_kit as base
import test_home_dashboard_e2e as dash
from hub_case import HubCase
from hub_support import ASK, OPTIONS, iso
from kvb_orchestrator import batches, skill_scripts

OUT = Path(os.environ.get("E2E_OUT", "/tmp/hub-match-waiting-shots"))
RELEASE_AT = 1366
SCORED = "git commit -m 'feat: x' -m '🎯 Fix: 95 % · 💥 Break: 2 % · 💰 Value: 1:4 · 🏆 Score: 93'"
PICK = "operator:operator/pick"
FRONT = """(async () => {@HELPERS@
  const card = () => document.querySelector("#main .match-card.front");
  if (!(await until(card, 8000))) {
    return {error: text(document.getElementById("main"))};
  }
  const peek = document.querySelector('#main .match-peek[data-card="@PICK@"]');
  if (peek) {
    peek.click();
  }
  const node = await until(() => (card() && card().dataset.card === "@PICK@" ? card() : null), 3000);
  return {front: node ? node.dataset.card : null, options: node ? all(".match-options button.option", node).map((option) => [text(option.querySelector("strong")), option.classList.contains("recommended")]) : [],
    wide: document.documentElement.scrollWidth > window.innerWidth + 1};
})()"""
HOME = """(async () => {@HELPERS@@HOME_KIT@
  await ViewStore.update("home.pins", () => [{kind: "panel", id: "tasks/match", w: 12, h: 8}]);
  await go("#home");
  const matchTile = await until(() => document.querySelector('#main .home-tile[data-id="tasks/match"]'), 8000);
  if (!matchTile) {
    return {error: text(document.getElementById("main"))};
  }
  const slot = await until(() => matchTile.querySelector(".home-head > .home-slot"), 4000);
  await until(() => slot && /cards? wait/.test(text(slot)), 6000);
  const below = () => Boolean(matchTile.querySelector(".match-actions + .match-peeks .match-peek"));
  const toggle = slot ? slot.querySelector(".match-peeks-toggle") : null;
  const peeks = [[Boolean(await until(below, 6000)), toggle && toggle.getAttribute("aria-pressed")]];
  if (toggle) {
    toggle.click();
    await sleep(200);
    peeks.push([below() || Boolean(matchTile.querySelector(".match-peeks")), toggle.getAttribute("aria-pressed"), localStorage.getItem("kvb-orchestrator.match-peeks")]);
    toggle.click();
    await sleep(200);
    peeks.push([below(), toggle.getAttribute("aria-pressed"), localStorage.getItem("kvb-orchestrator.match-peeks")]);
  }
  return {peeks, slot: slot ? text(slot.querySelector(".muted")) : null, overview: Boolean(slot && slot.querySelector(".match-open-overview")),
    toolbar: Boolean(matchTile.querySelector(".home-body .task-toolbar")), card: Boolean(await until(() => matchTile.querySelector(".match-card.front"), 6000)),
    head: Math.round(matchTile.querySelector(".home-head").getBoundingClientRect().height), wide: document.documentElement.scrollWidth > innerWidth + 1};
})()"""
FLOW = """(async () => {@HELPERS@
  const posted = [];
  const send = window.fetch.bind(window);
  window.fetch = async (path, init) => {
    if (String(path) === "/api/inbox/approve") {
      posted.push(JSON.parse(init.body).items.map((item) => [item.kind, item.id, item.verb, item.label, item.channel || null, item.reason || null]));
    }
    return send(path, init);
  };
  const card = () => document.querySelector("#main .match-card.front:not(.match-release-card)");
  if (!(await until(card, 8000))) {
    return {error: text(document.getElementById("main"))};
  }
  const key = (name) => document.body.dispatchEvent(new KeyboardEvent("keydown", {key: name, bubbles: true, cancelable: true}));
  const seen = {};
  for (let step = 0; step < 8 && card(); step += 1) {
    const node = card();
    const id = node.dataset.card;
    const acts = Object.fromEntries(all("#main .match-actions .match-act").map((button) => [text(button.querySelector(".match-act-label")), button.disabled]));
    seen[id] = {kind: node.dataset.kind, chips: all(".match-metric", node).map((chip) => `${chip.dataset.metric}=${text(chip.querySelector("strong"))}`), acts,
      options: all(".match-options button.option", node).map((option) => text(option.querySelector("strong"))), rule: Boolean(node.querySelector(".rule-request")), command: text(node.querySelector(".match-command"))};
    if (id.startsWith("operator:")) {
      node.querySelector(".match-options button.option:not(.recommended)").click();
    } else if (id.startsWith("decision:")) {
      key("ArrowLeft");
      seen[id].refused = Boolean(await until(() => all("#toasts .toast").map(text).find((entry) => entry.startsWith("Reject: not possible")), 3000));
      node.querySelector(".match-options button.option").click();
    } else if (id.startsWith("ask:")) {
      key("ArrowRight");
    } else {
      key("ArrowRight");
      seen[id].sheet = Boolean(await until(() => document.querySelector(".sheet-box .rule-request"), 3000));
      document.querySelector(".sheet-box .sheet-head button").click();
      await sleep(200);
      seen[id].stayed = card() && card().dataset.card === id;
      key("ArrowLeft");
      const feedback = await until(() => document.querySelector(".sheet-box .match-feedback"), 3000);
      feedback.value = "too broad";
      document.querySelector(".sheet-box .match-feedback-reject").click();
    }
    await until(() => !card() || card().dataset.card !== id, 3000);
  }
  const overview = await until(() => document.querySelector("#main .match-overview"), 3000);
  const rows = overview ? all("#main .match-decision").map((item) => [item.dataset.card, item.dataset.verdict, text(item.querySelector(".match-verdict"))]) : [];
  const found = {seen, rows, wide: document.documentElement.scrollWidth > window.innerWidth + 1};
  if (@RELEASE@) {
    document.querySelector("#main .match-release").click();
    found.toast = await until(() => all("#toasts .toast").map(text).find((entry) => entry.startsWith("Release")), 15000);
    found.emptied = Boolean(await until(() => document.querySelector("#main .match-stack .empty"), 15000));
    found.posted = posted;
  }
  return found;
})()"""


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestMatchWaiting(HubCase):
    drive = base.OrchestratorE2ECase.drive
    authenticator = base.OrchestratorE2ECase.authenticator

    def setUp(self):
        super().setUp()
        now = time.time()
        self.write_council({
            "work/s1/claim.json": {"office": "work/s1", "session": "s1", "runtime": "claude", "name": "Skills session", "since": iso(now - 86400), "beat": now, "work": "match"},
            "rasci.json": {"operator/pick": {"title": "Merge the hub now?", "workdir": "/repo", "description": "the gate is green", "check": "decision", "options": OPTIONS, "recommended": "Merge now", "roles": {"Skills": "A", "Operator": "R"}}},
        })
        self.ask = self.create_ask({**ASK, "command": SCORED, "timeout": 600})
        decided = self.tool("decision_request", {"question": "Name the release?", "options": OPTIONS, "agent": "Skills", "recommended": ""})
        self.assertFalse(decided["isError"], decided)
        self.choice = decided["structuredContent"]["id"]
        rule = {"kind": "ask", "tool": "Bash", "pattern": "make test*", "scope": "/repo*", "expires": int(now) + 86400, "agent": "Skills", "why": "the gate runs make test"}
        requested = self.tool("rule_request", rule)
        self.assertFalse(requested["isError"], requested)
        self.rule = requested["structuredContent"]["id"]

    def radio(self) -> list[list[str]]:
        return [args for script, args in self.scripts.calls if script == skill_scripts.RADIO]

    def steps(self) -> list[dict]:
        OUT.mkdir(parents=True, exist_ok=True)
        steps = []
        for width, height in sorted(base.WIDTHS, key=lambda size: size[0] == RELEASE_AT):
            url = f"http://localhost:{self.port}/?{width}#tasks/match"
            front = FRONT.replace("@HELPERS@", base.HELPERS).replace("@PICK@", PICK)
            flow = FLOW.replace("@HELPERS@", base.HELPERS).replace("@RELEASE@", "true" if width == RELEASE_AT else "false")
            home = HOME.replace("@HELPERS@", base.HELPERS).replace("@HOME_KIT@", dash.HOME)
            steps.append({"width": width, "height": height, "url": f"http://localhost:{self.port}/?{width}-home#stream", "wait": 1500, "probe": home, "shot": str(OUT / f"chromium-{width}-home.png")})
            steps.append({"width": width, "height": height, "url": url, "wait": 1500, "probe": front, "shot": str(OUT / f"chromium-{width}-decision.png")})
            steps.append({"width": width, "height": height, "url": url, "wait": 1500, "probe": flow, "shot": str(OUT / f"chromium-{width}-overview.png")})
        return steps

    def check_flow(self, found: dict) -> None:
        self.assertNotIn("error", found, found)
        seen = found["seen"]
        ask, choice, rule = f"ask:{self.ask}", f"decision:{self.choice}", f"rule:{self.rule}"
        self.assertEqual(sorted(seen), sorted([PICK, ask, choice, rule]), found)
        self.assertEqual({card_id: entry["kind"] for card_id, entry in seen.items()}, {PICK: "decision", ask: "ask", choice: "decision", rule: "rule"})
        self.assertEqual(seen[ask]["chips"], ["fix=95 %", "break=2 %", "score=93", "value=1:4"], found)
        self.assertEqual((seen[ask]["command"], seen[ask]["options"]), (SCORED, []), found)
        self.assertEqual((seen[PICK]["options"], seen[PICK]["acts"]["Accept"], seen[PICK]["acts"]["Reject"]), (["Merge now", "Wait"], False, False), found)
        self.assertEqual((seen[choice]["acts"]["Accept"], seen[choice]["acts"]["Reject"], seen[choice]["refused"]), (True, True, True), found)
        self.assertEqual((seen[rule]["rule"], seen[rule]["sheet"], seen[rule]["stayed"]), (True, True, True), found)
        expected = [[PICK, "accept", "Accept: Wait"], [ask, "accept", "Accept"], [choice, "accept", "Accept: Merge now"], [rule, "reject", "Reject"]]
        self.assertEqual(sorted(found["rows"]), sorted(expected), found)
        self.assertFalse(found["wide"], found)

    def test_chromium_decides_every_waiting_kind_and_releases_them_with_one_signature(self):
        with mock.patch.object(batches, "UNDO", 0.3):
            data = self.drive(self.steps(), self.authenticator(), "cdp.mjs", os.environ.get("CHROMIUM", "chromium"))
            self.settle(lambda: self.ask_status(self.ask, "0") == "allowed")
        (OUT / "chromium-waiting.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "(style-src-elem)" not in error and "/favicon.ico" not in error], [])
        homes, fronts, flows = data["results"][0::3], data["results"][1::3], data["results"][2::3]
        for home in homes:
            with self.subTest(home=home):
                self.assertEqual((home["slot"], home["overview"], home["toolbar"], home["card"], home["wide"]), ("4 cards wait", True, False, True, False), home)
                self.assertLessEqual(home["head"], 48, home)
                self.assertEqual(home["peeks"], [[True, "true"], [False, "false", "false"], [True, "true", "true"]], home)
        for front in fronts:
            with self.subTest(front=front):
                self.assertEqual((front["front"], front["options"], front["wide"]), (PICK, [["Merge now", True], ["Wait", False]], False), front)
        for found in flows:
            with self.subTest(release="toast" in found):
                self.check_flow(found)
        released = flows[-1]
        self.assertTrue(released["toast"].startswith("Release: 4 decisions"), released)
        self.assertTrue(released["emptied"], released)
        items = sorted(released["posted"][0])
        self.assertEqual(items, sorted([["operator", "operator/pick", "approve", "Wait", None, None], ["ask", self.ask, "approve", "", None, None], ["decision", self.choice, "approve", "Merge now", None, None], ["rule", self.rule, "reject", "", "call", "too broad"]]))
        self.settle(lambda: len(self.radio()) == 3)
        told = sorted(sent[-1].split("] ", 1)[1] for sent in self.radio())
        self.assertEqual(told[1], "Decision operator/pick Answer: Wait")
        self.assertTrue(told[0].startswith(f"Choice for decision {self.choice} ") and told[2].startswith("Denied by the operator: rule request"), told)
        self.assertEqual(self.tool("decision_wait", {"id": self.choice, "timeout_seconds": 0})["structuredContent"]["choice"], "Merge now")


if __name__ == "__main__":
    unittest.main()
