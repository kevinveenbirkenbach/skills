from __future__ import annotations

import json
import os
import shutil
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

import hub_e2e_kit as base
import test_match_review_e2e as matched
from hub_case import HubCase

OUT = Path(os.environ.get("E2E_OUT", "/tmp/hub-039-shots"))
INIT = """() => {
  window.e2eViolations = [];
  document.addEventListener("securitypolicyviolation", (event) => window.e2eViolations.push(`${event.violatedDirective} ${event.blockedURI}`));
  const real = window.fetch.bind(window);
  window.e2eSent = [];
  window.fetch = (input, options) => {
    const url = String(input && input.url ? input.url : input);
    if (url.startsWith("/api/match") && window.e2eMatch) {
      return Promise.resolve(new Response(JSON.stringify({cards: window.e2eMatch}), {headers: {"Content-Type": "application/json"}}));
    }
    if (url === "/api/messages" && options && options.method === "POST") {
      window.e2eSent.push(JSON.parse(options.body));
    }
    return real(input, options);
  };
}"""
STEPS = """
  const served = async () => (await (await fetch("/api/match", {cache: "no-store"})).json()).cards;
  const key = (name) => document.body.dispatchEvent(new KeyboardEvent("keydown", {key: name, bubbles: true}));
  const actionable = async () => {
    for (let tries = 0; tries < 6 && card() && card().querySelector(".match-stale-note, [data-stale='true']"); tries += 1) {
      key("ArrowUp");
      await sleep(600);
    }
    return card() && card().dataset.card;
  };
  const reject = async (words) => {
    const id = await actionable();
    key("ArrowLeft");
    const field = await until(() => document.querySelector(".match-feedback"), 4000);
    if (!field) {
      return null;
    }
    field.value = words;
    document.querySelector(".match-feedback-reject").click();
    await until(() => !card() || card().dataset.card !== id, 4000);
    return id;
  };
  const release = async () => {
    const open = document.querySelector("#main .match-open-overview");
    if (open && !open.hidden) {
      open.click();
    }
    return until(() => document.querySelector("#main .match-overview"), 8000);
  };
  const serve = async (cards) => {
    window.e2eMatch = cards;
    await sleep(2600);
    window.dispatchEvent(new Event("focus"));
  };
"""
CHANGED = """(async () => {@HELPERS@@CARD@@STEPS@
  await screenShown(8000);
  if (!(await until(card, 8000))) {
    return {error: text(document.getElementById("main")).slice(0, 300)};
  }
  await sleep(300);
  const cards = await served();
  const id = await reject("fix the probe");
  await serve(cards.map((one) => (one.id === id ? {...one, hash: `${one.hash}0`} : one)));
  await release();
  const note = await until(() => document.querySelector(`#main .match-decision[data-card="${id}"] .match-decision-note`), 8000);
  const row = document.querySelector(`#main .match-decision[data-card="${id}"]`);
  return {id, verdict: row && row.dataset.verdict, note: note ? text(note) : null};
})()"""
ACCEPTED = """(async () => {@HELPERS@@CARD@@STEPS@
  await screenShown(8000);
  if (!(await until(card, 8000))) {
    return {error: text(document.getElementById("main")).slice(0, 300)};
  }
  await sleep(300);
  const cards = await served();
  const id = await actionable();
  const title = (cards.find((one) => one.id === id) || {}).title;
  key("ArrowRight");
  await until(() => !card() || card().dataset.card !== id, 4000);
  const tally = () => text(document.querySelector("#main .match-tally"));
  const before = tally();
  const shown = new Set(all("#toasts .toast"));
  await serve(cards.map((one) => (one.id === id ? {...one, hash: `${one.hash}0`} : one)));
  const toast = await until(() => all("#toasts .toast").filter((node) => !shown.has(node)).map(text).find((entry) => entry.startsWith("Accept dropped")), 8000);
  return {id, title, before, after: tally(), toast: toast || null};
})()"""
WITHDRAWN = """(async () => {@HELPERS@@CARD@@STEPS@
  await screenShown(8000);
  if (!(await until(card, 8000))) {
    return {error: text(document.getElementById("main")).slice(0, 300)};
  }
  await sleep(300);
  const cards = await served();
  const id = await reject("withdrawn probe");
  const title = (cards.find((one) => one.id === id) || {}).title;
  await serve(cards.filter((one) => one.id !== id));
  await release();
  const row = await until(() => document.querySelector(`#main .match-decision[data-card="${id}"][data-withdrawn="true"]`), 8000);
  const button = document.querySelector("#main .match-release");
  if (!row || !button) {
    return {id, row: Boolean(row), button: Boolean(button)};
  }
  button.click();
  await until(() => window.e2eSent.length, 15000);
  return {id, title, row: true, sent: window.e2eSent.map((message) => ({cls: message.class, text: message.text}))};
})()"""


def probe(template: str) -> str:
    return template.replace("@HELPERS@", base.HELPERS).replace("@CARD@", matched.CARD).replace("@STEPS@", STEPS)


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestMatchRejects(HubCase):
    drive = base.OrchestratorE2ECase.drive
    authenticator = base.OrchestratorE2ECase.authenticator
    cards = matched.TestMatchReview.cards
    review = matched.TestMatchReview.review
    payload = matched.TestMatchReview.payload

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        self.cards()
        self.base = f"http://localhost:{self.port}/"

    def test_chromium_keeps_a_reject_across_a_changed_or_withdrawn_card_and_drops_a_changed_accept_with_a_toast(self):
        at = {"width": 1366, "height": 900}
        steps = [
            {**at, "url": f"{self.base}?changed#tasks/match", "wait": 1500, "probe": probe(CHANGED), "shot": str(OUT / "chromium-changed.png")},
            {**at, "url": f"{self.base}?accepted#tasks/match", "wait": 1500, "probe": probe(ACCEPTED), "shot": str(OUT / "chromium-accepted.png")},
            {**at, "url": f"{self.base}?withdrawn#tasks/match", "wait": 1500, "probe": probe(WITHDRAWN), "shot": str(OUT / "chromium-withdrawn.png")},
        ]
        data = self.drive(steps, self.authenticator(), init=INIT)
        (OUT / "chromium-match-rejects.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        changed, accepted, withdrawn = data["results"]
        with self.subTest(case="changed reject"):
            self.assertNotIn("error", changed, changed)
            self.assertEqual(changed["verdict"], "reject", changed)
            self.assertIn("changed since your reject", changed["note"], changed)
        with self.subTest(case="changed accept"):
            self.assertNotIn("error", accepted, accepted)
            self.assertEqual((accepted["before"], accepted["after"]), ("1", "0"), accepted)
            self.assertIn(accepted["title"], accepted["toast"] or "", accepted)
        with self.subTest(case="withdrawn reject"):
            self.assertNotIn("error", withdrawn, withdrawn)
            self.assertTrue(withdrawn["row"], withdrawn)
            calls = [message for message in withdrawn["sent"] if message["cls"] == "call"]
            self.assertEqual(len(calls), 1, withdrawn)
            self.assertIn(withdrawn["title"], calls[0]["text"], withdrawn)
            self.assertIn("withdrawn probe", calls[0]["text"], withdrawn)


if __name__ == "__main__":
    unittest.main()
