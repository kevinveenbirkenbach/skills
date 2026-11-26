from __future__ import annotations

import json
import os
import shutil
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

import hub_e2e_kit as base
import test_match_review_e2e as matched
from hub_case import HubCase
from kvb_orchestrator import batches

OUT = Path(os.environ.get("E2E_OUT", "/tmp/hub-040-shots"))
INIT = """() => {
  window.e2eViolations = [];
  document.addEventListener("securitypolicyviolation", (event) => window.e2eViolations.push(`${event.violatedDirective} ${event.blockedURI}`));
  const real = window.fetch.bind(window);
  window.e2eSubmits = [];
  window.e2eMatch = null;
  window.fetch = (input, options) => {
    const url = String(input && input.url ? input.url : input);
    if (url.startsWith("/api/match") && window.e2eMatch) {
      return Promise.resolve(new Response(JSON.stringify({cards: window.e2eMatch}), {headers: {"Content-Type": "application/json"}}));
    }
    if (url === "/api/inbox/approve" && options && typeof options.body === "string") {
      window.e2eSubmits.push(JSON.parse(options.body).items.map((item) => [item.kind, item.id, item.verb]));
    }
    return real(input, options);
  };
}"""
STEPS = """
  const served = async () => (await (await fetch("/api/match", {cache: "no-store"})).json()).cards;
  const key = (name) => document.body.dispatchEvent(new KeyboardEvent("keydown", {key: name, bubbles: true, cancelable: true}));
  const releasing = () => Boolean(card() && card().classList.contains("match-release-card"));
  const decideAll = async () => {
    for (let tries = 0; tries < 10 && card() && !releasing(); tries += 1) {
      const front = card();
      const id = front.dataset.card;
      key(front.dataset.stale === "true" || front.hasAttribute("data-blocked") ? "ArrowUp" : "ArrowRight");
      await until(() => !card() || card().dataset.card !== id, 4000);
      await sleep(200);
    }
    return releasing();
  };
  const swipeRight = async () => {
    const head = card().querySelector(".match-head");
    const box = head.getBoundingClientRect();
    const [x, y] = [box.left + box.width / 2, box.top + 20];
    const dx = card().getBoundingClientRect().width * 0.4;
    const at = (cx) => ({bubbles: true, cancelable: true, pointerId: 12, pointerType: "touch", isPrimary: true, button: 0, clientX: cx, clientY: y});
    head.dispatchEvent(new PointerEvent("pointerdown", at(x)));
    window.dispatchEvent(new PointerEvent("pointermove", at(x + dx / 2)));
    const leaning = card().dataset.leaning || "";
    window.dispatchEvent(new PointerEvent("pointerup", at(x + dx)));
    return leaning;
  };
"""
CARD040 = """(async () => {@HELPERS@@CARD@@STEPS@
  await screenShown(8000);
  if (!(await until(card, 8000))) {
    return {error: text(document.getElementById("main")).slice(0, 300)};
  }
  await sleep(300);
  const found = {ready: await decideAll()};
  const front = card();
  found.release = Boolean(front && front.closest(".match-deck") && front.querySelector(".match-release"));
  found.layers = all("#main .match-layer").map((node) => node.dataset.card);
  found.block = Boolean(document.querySelector("#main .match-release-block"));
  found.risk = all("#main .match-accept-risk").map((node) => [node.closest(".match-decision").dataset.card, node.getAttribute("aria-pressed")]);
  found.label = text(document.querySelector("#main .match-release"));
  key("ArrowLeft");
  found.back = await until(() => !releasing() && card() && card().dataset.card, 4000);
  document.querySelector("#main .match-open-overview").click();
  found.again = Boolean(await until(releasing, 4000));
  const cards = await served();
  window.e2eMatch = [...cards, {...cards.find((one) => one.id === "@COMMIT@"), id: "review:e2e-new", ref: "e2e-new", hash: "e2e", title: "e2e: arrived meanwhile"}];
  found.arrived = Boolean(await until(() => document.querySelector('#main .match-layer[data-card="review:e2e-new"]'), 10000));
  found.stays = releasing();
  window.e2eMatch = null;
  found.wide = document.documentElement.scrollWidth > innerWidth + 1;
  return found;
})()"""
RELEASE = """(async () => {@HELPERS@@CARD@@STEPS@
  await screenShown(8000);
  if (!(await until(card, 8000))) {
    return {error: text(document.getElementById("main")).slice(0, 300)};
  }
  await sleep(300);
  if (!(await decideAll())) {
    return {error: text(document.getElementById("main")).slice(0, 300)};
  }
  const risk = () => document.querySelector('#main .match-decision[data-card="@RED@"] .match-accept-risk');
  const pressed = [];
  for (let clicks = 0; clicks < @CLICKS@; clicks += 1) {
    risk().click();
    await sleep(200);
    pressed.push(risk().getAttribute("aria-pressed"));
  }
  const label = text(document.querySelector("#main .match-release"));
  window.e2eSubmits.length = 0;
  const leaning = @SWIPE@ ? await swipeRight() : (key("ArrowRight"), "");
  await until(() => window.e2eSubmits.length >= @SUBMITS@, 20000);
  await sleep(1500);
  await until(() => card() && !releasing(), 8000);
  return {pressed, label, leaning, submits: window.e2eSubmits, front: card() ? card().dataset.card : null, peeks: all("#main .match-peek").map((node) => node.dataset.card)};
})()"""


def probe(template: str, **names: str) -> str:
    fills = {"@HELPERS@": base.HELPERS, "@CARD@": matched.CARD, "@STEPS@": STEPS, **{f"@{key.upper()}@": value for key, value in names.items()}}
    for key, value in fills.items():
        template = template.replace(key, value)
    return template


class ReleaseDeck(HubCase):
    drive = base.OrchestratorE2ECase.drive
    authenticator = base.OrchestratorE2ECase.authenticator
    cards = matched.TestMatchReview.cards
    review = matched.TestMatchReview.review
    payload = matched.TestMatchReview.payload

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        self.cards()
        diff = [{"path": "src/red.py", "status": "M", "mode": "100644", "additions": 1, "deletions": 0, "patch": "@@ -1,1 +1,2 @@\n line 1\n+red line", "note": ""}]
        arguments = {**self.arguments("feat: red gate", "", self.page("feature-red.html", "<!doctype html><title>p</title>")), "worktree": "/repo/.worktrees/feature/red", "branch": "feature/red", "agent": "Stage", "diff": diff, "gate": "fail"}
        result = self.tool("review_request", arguments)
        self.assertFalse(result["isError"], result)
        self.red = result["structuredContent"]["id"]
        self.base = f"http://localhost:{self.port}/"


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestMatchReleaseCard(ReleaseDeck):
    def release(self, name: str, clicks: int, swipe: bool, submits: int) -> dict:
        step = {"width": 1920, "height": 1080, "url": f"{self.base}?{name}#tasks/match", "wait": 1500, "shot": str(OUT / f"chromium-{name}.png"),
                "probe": probe(RELEASE, red=f"review:{self.red}", clicks=str(clicks), swipe="true" if swipe else "false", submits=str(submits))}
        with mock.patch.object(batches, "UNDO", 0.3):
            data = self.drive([step], self.authenticator(), init=INIT)
        (OUT / f"chromium-{name}.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        found = data["results"][0]
        self.assertNotIn("error", found, found)
        return found

    def sorted_submits(self, found: dict) -> list[list[list[str]]]:
        return [sorted(batch) for batch in found["submits"]]

    def test_chromium_puts_the_release_card_in_front_of_greyed_and_new_cards_and_left_returns_to_the_stack(self):
        steps = [{"width": width, "height": height, "url": f"{self.base}?{width}-card#tasks/match", "wait": 1500, "shot": str(OUT / f"chromium-{width}-release-card.png"),
                  "probe": probe(CARD040, commit=f"review:{self.commit}")} for width, height in ((390, 844), (1920, 1080))]
        data = self.drive(steps, None, init=INIT)
        (OUT / "chromium-release-card.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        for (width, _), found in zip(((390, 844), (1920, 1080)), data["results"], strict=True):
            with self.subTest(width=width):
                self.assertNotIn("error", found, found)
                self.assertEqual((found["ready"], found["release"], found["block"], found["wide"]), (True, True, False, False), found)
                self.assertIn(f"review:{self.stale}", found["layers"], found)
                self.assertEqual(found["risk"], [[f"review:{self.red}", "false"]], found)
                self.assertEqual(found["label"], "Release 2 decisions", found)
                self.assertEqual(found["back"], f"review:{self.stale}", found)
                self.assertEqual((found["again"], found["arrived"], found["stays"]), (True, True, True), found)

    def test_chromium_release_by_arrow_leaves_the_red_gate_commit_in_the_stack_until_its_risk_is_accepted(self):
        found = self.release("no-risk", 0, False, 1)
        self.assertEqual(self.sorted_submits(found), [sorted([["review", self.commit, "approve"], ["operator", "operator/issue", "approve"]])], found)
        self.assertEqual(found["label"], "Release 2 decisions", found)
        self.assertIn(f"review:{self.red}", [found["front"], *found["peeks"]], found)

    def test_chromium_release_by_swipe_signs_a_risk_accepted_red_gate_commit_on_its_own_first(self):
        found = self.release("risk", 1, True, 2)
        self.assertEqual((found["pressed"], found["leaning"], found["label"]), (["true"], "accept", "Release 3 decisions"), found)
        self.assertEqual(self.sorted_submits(found), [[["review", self.red, "approve"]], sorted([["review", self.commit, "approve"], ["operator", "operator/issue", "approve"]])], found)
        self.settle(lambda: self.status(self.red) == "approved" and self.status(self.commit) == "approved")

    def test_chromium_a_withdrawn_risk_leaves_the_red_gate_commit_out_again(self):
        found = self.release("withdrawn", 2, False, 1)
        self.assertEqual((found["pressed"], found["label"]), (["true", "false"], "Release 2 decisions"), found)
        self.assertEqual(self.sorted_submits(found), [sorted([["review", self.commit, "approve"], ["operator", "operator/issue", "approve"]])], found)
        self.assertIn(f"review:{self.red}", [found["front"], *found["peeks"]], found)


if __name__ == "__main__":
    unittest.main()
