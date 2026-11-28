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
import test_home_dashboard_e2e as dash
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
  const swipe = async (sign) => {
    const head = card().querySelector(".match-head");
    const box = head.getBoundingClientRect();
    const [x, y] = [box.left + box.width / 2, box.top + 20];
    const dx = sign * card().getBoundingClientRect().width * 0.4;
    const at = (cx) => ({bubbles: true, cancelable: true, pointerId: 12, pointerType: "touch", isPrimary: true, button: 0, clientX: cx, clientY: y});
    head.dispatchEvent(new PointerEvent("pointerdown", at(x)));
    window.dispatchEvent(new PointerEvent("pointermove", at(x + dx / 2)));
    const leaning = card().dataset.leaning || "";
    window.dispatchEvent(new PointerEvent("pointerup", at(x + dx)));
    return leaning;
  };
  const swipeRight = () => swipe(1);
  const unreleased = () => !releasing() && card() && card().dataset.card;
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
  found.labelled = all("button", front).map(name).filter((words) => /^Release \\d+ decisions?$/.test(words || ""));
  const acts = all("#main .match-stack > .match-actions .match-act");
  found.row = acts.map((node) => [node.classList[1], text(node.querySelector(".match-act-label")), node.disabled]);
  found.sides = acts.map((node) => Math.round(node.getBoundingClientRect().left));
  found.held = document.querySelector("#main .match-release") ? document.querySelector("#main .match-release").title : null;
  found.verdicts = all("#main .match-decision").filter((node) => node.querySelector(".match-verdict")).map((node) => node.dataset.card);
  found.layers = all("#main .match-layer").map((node) => node.dataset.card);
  found.block = Boolean(document.querySelector("#main .match-release-block"));
  found.risk = all("#main .match-accept-risk").map((node) => [node.closest(".match-decision").dataset.card, node.getAttribute("aria-pressed")]);
  found.label = text(document.querySelector("#main .match-release"));
  key("ArrowLeft");
  found.back = await until(unreleased, 4000);
  key("s");
  found.undone = Boolean(await until(releasing, 4000));
  key("a");
  found.skipped = await until(unreleased, 4000);
  key("s");
  await until(releasing, 4000);
  found.swiped = [await swipe(-1), await until(unreleased, 4000)];
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
  const disabled = document.querySelector("#main .match-release").disabled;
  window.e2eSubmits.length = 0;
  const corner = [];
  const watch = new MutationObserver(() => {
    const box = document.querySelector("#toasts .toast.wait");
    if (!box || corner.length) {
      return;
    }
    const mark = box.querySelector(".undo-row > .undo-glass:last-child");
    const undo = box.querySelector(".undo-row > .btn");
    if (!mark || !mark.querySelector(".match-glass-face") || !undo) {
      corner.push({glass: false});
      return;
    }
    const [outer, glass, button] = [box, mark, undo].map((node) => node.getBoundingClientRect());
    corner.push({glass: true, right: Math.round(outer.right - glass.right), bottom: Math.round(outer.bottom - glass.bottom), after: glass.left >= button.right});
  });
  watch.observe(document.getElementById("toasts"), {childList: true});
  const leaning = @SWIPE@ ? await swipeRight() : (key("@KEY@"), "");
  await until(() => window.e2eSubmits.length >= @SUBMITS@, 20000);
  await sleep(1500);
  watch.disconnect();
  if (@SUBMITS@) {
    await until(() => card() && !releasing(), 8000);
  }
  return {pressed, label, disabled, leaning, corner, submits: window.e2eSubmits, front: card() ? card().dataset.card : null, peeks: all("#main .match-peek").map((node) => node.dataset.card)};
})()"""
HEIGHTS = """(async () => {@HELPERS@@HOME_KIT@@CARD@@STEPS@
  if (@WIDGET@) {
    await ViewStore.update("home.pins", () => [{kind: "panel", id: "tasks/match", w: 12, h: 8}]);
    await go("#home");
  } else {
    await screenShown(8000);
  }
  if (!(await until(card, 8000))) {
    return {error: text(document.getElementById("main")).slice(0, 300)};
  }
  await sleep(700);
  const box = (node) => {
    const rect = node.getBoundingClientRect();
    return [rect.left, rect.top, rect.width, rect.height];
  };
  const row = (selector) => all(`:scope > .match-actions ${selector}`, card().closest(".match-stack"));
  const measure = () => {
    const front = card();
    const inner = front.querySelector(".match-body");
    return {id: front.dataset.card, card: box(front), deck: box(front.closest(".match-deck")), scrolls: inner.scrollHeight > inner.clientHeight + 1,
      acts: row(".match-act").map((node) => [node.classList[1], ...box(node)])};
  };
  const seen = [];
  for (const id of @IDS@) {
    if (card().dataset.card !== id) {
      await pick(id);
      await sleep(700);
    }
    seen.push(measure());
  }
  for (let tries = 0; tries < 10 && card() && !releasing(); tries += 1) {
    const id = card().dataset.card;
    const greyed = card().dataset.stale === "true" || card().hasAttribute("data-blocked");
    row(greyed ? ".match-later" : ".match-accept")[0].click();
    await until(() => !card() || card().dataset.card !== id, 4000);
    await sleep(200);
  }
  await sleep(700);
  seen.push(releasing() ? measure() : {id: null});
  return {seen, wide: document.documentElement.scrollWidth > innerWidth + 1};
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
    def release(self, name: str, clicks: int, swipe: bool, submits: int, key: str = "ArrowRight") -> dict:
        step = {"width": 1920, "height": 1080, "url": f"{self.base}?{name}#tasks/match", "wait": 1500, "shot": str(OUT / f"chromium-{name}.png"),
                "probe": probe(RELEASE, red=f"review:{self.red}", clicks=str(clicks), swipe="true" if swipe else "false", submits=str(submits), key=key)}
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
                self.assertEqual((found["ready"], found["release"], found["block"], found["wide"]), (True, False, False, False), found)
                self.assertIn(f"review:{self.stale}", found["layers"], found)
                self.assertEqual(found["risk"], [[f"review:{self.red}", "false"]], found)
                self.assertNotIn(f"review:{self.red}", found["verdicts"], found)
                self.assertEqual(found["labelled"], [], found)
                self.assertEqual(found["row"], [["match-drop", "Cancel", True], ["match-skip", "Skip", False], ["match-release", "Release", True]], found)
                self.assertEqual(found["sides"], sorted(found["sides"]), found)
                self.assertEqual(found["label"], "Release", found)
                self.assertIn("one red-gate commit waits for your risk accept or its way back to the stack.", found["held"], found)
                self.assertIn("feat: red gate", found["held"], found)
                self.assertEqual(found["back"], f"review:{self.stale}", found)
                self.assertEqual((found["undone"], found["skipped"], found["swiped"]), (True, f"review:{self.stale}", ["reject", f"review:{self.stale}"]), found)
                self.assertEqual((found["again"], found["arrived"], found["stays"]), (True, True, True), found)

    def test_chromium_every_card_keeps_the_deck_height_and_its_three_buttons_in_place(self):
        ids = [f"review:{self.commit}", "operator:operator/issue", f"review:{self.stale}", f"review:{self.red}"]
        sizes = (("page", 1366, 768, "tasks/match"), ("widget", 390, 900, "stream"))
        steps = [{"width": width, "height": height, "url": f"{self.base}?{view}-{width}-heights#{route}", "wait": 1500, "shot": str(OUT / f"chromium-{view}-{width}-heights.png"),
                  "probe": probe(HEIGHTS, ids=json.dumps(ids), widget="true" if view == "widget" else "false", home_kit=dash.HOME)} for view, width, height, route in sizes]
        data = self.drive(steps, None, init=INIT)
        (OUT / "chromium-heights.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        for (view, width, _, _), found in zip(sizes, data["results"], strict=True):
            with self.subTest(view=view, width=width):
                self.assertNotIn("error", found, found)
                seen = found["seen"]
                self.assertEqual([one["id"] for one in seen], [*ids, "release"], found)
                first = seen[0]
                self.assertTrue(first["scrolls"], first)
                self.assertEqual([act[0] for act in first["acts"]], ["match-reject", "match-later", "match-accept"], first)
                for one in seen[1:]:
                    self.assertAlmostEqual(one["card"][3], first["card"][3], delta=1, msg=one)
                    self.assertAlmostEqual(one["card"][3], one["deck"][3] - (one["card"][1] - one["deck"][1]), delta=1, msg=one)
                    self.assertEqual(len(one["acts"]), 3, one)
                    for act, kept in zip(one["acts"], first["acts"], strict=True):
                        for at, was in zip(act[1:], kept[1:], strict=True):
                            self.assertAlmostEqual(at, was, delta=1, msg=(one, first))
                self.assertEqual([act[0] for act in seen[-1]["acts"]], ["match-drop", "match-skip", "match-release"], found)
                self.assertFalse(found["wide"], found)

    def test_chromium_an_open_risk_greys_the_release_and_the_arrow_releases_nothing(self):
        found = self.release("no-risk", 0, False, 0)
        self.assertEqual((found["submits"], found["label"], found["disabled"], found["front"], found["corner"]), ([], "Release", True, "release", []), found)

    def test_chromium_release_by_swipe_signs_a_risk_accepted_red_gate_commit_on_its_own_first(self):
        found = self.release("risk", 1, True, 2)
        self.assertEqual((found["pressed"], found["leaning"], found["label"], found["disabled"]), (["true"], "accept", "Release", False), found)
        self.assertEqual(self.sorted_submits(found), [[["review", self.red, "approve"]], sorted([["review", self.commit, "approve"], ["operator", "operator/issue", "approve"]])], found)
        self.settle(lambda: self.status(self.red) == "approved" and self.status(self.commit) == "approved")

    def test_chromium_d_releases_and_the_undo_countdown_shows_the_hourglass_bottom_right(self):
        found = self.release("risk-d", 1, False, 2, "d")
        self.assertEqual((found["pressed"], found["disabled"]), (["true"], False), found)
        self.assertEqual(len(found["submits"]), 2, found)
        self.assertEqual(len(found["corner"]), 1, found)
        corner = found["corner"][0]
        self.assertEqual((corner["glass"], corner["after"]), (True, True), found)
        self.assertTrue(0 <= corner["right"] <= 40 and 0 <= corner["bottom"] <= 40, found)
        self.settle(lambda: self.status(self.red) == "approved" and self.status(self.commit) == "approved")

    def test_chromium_a_withdrawn_risk_greys_the_release_again(self):
        found = self.release("withdrawn", 2, False, 0)
        self.assertEqual((found["pressed"], found["label"], found["disabled"], found["submits"], found["front"]), (["true", "false"], "Release", True, [], "release"), found)


if __name__ == "__main__":
    unittest.main()
