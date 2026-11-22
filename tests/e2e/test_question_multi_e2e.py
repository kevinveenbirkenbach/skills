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
from hub_case import HubCase
from hub_support import iso
from kvb_orchestrator import batches

OUT = Path(os.environ.get("E2E_OUT", "/tmp/hub-question-multi-shots"))
SENT_AT = 1366
GROUPS = ["Scratch (Recommended)", "Logs", "Worktrees (Recommended)"]
QUESTION = "Which groups go?"
PICKED = f"{GROUPS[0]}\n{GROUPS[2]}"
CAPTURE = """
  const posted = [];
  const send = window.fetch.bind(window);
  window.fetch = async (path, init) => {
    if (String(path) === "/api/inbox/approve") {
      posted.push(JSON.parse(init.body).items.map((item) => [item.kind, item.id, item.verb, item.label]));
    }
    return send(path, init);
  };
  const look = (options, submit) => ({pressed: options.map((option) => option.getAttribute("aria-pressed")), recommended: options.map((option) => option.classList.contains("recommended")), disabled: submit ? submit.disabled : null});
  const wide = () => document.documentElement.scrollWidth > window.innerWidth + 1;
"""
MATCH = """(async () => {@HELPERS@@CAPTURE@
  const card = await until(() => document.querySelector('#main .match-card.front[data-card="@CARD@"]'), 8000);
  if (!card) {
    return {error: text(document.getElementById("main"))};
  }
  const options = () => all(".match-options button.option", card);
  const pick = card.querySelector(".choice-send");
  const before = look(options(), pick);
  [0, 2, 1, 1].forEach((index) => options()[index].click());
  const toggled = {...look(options(), pick), front: document.querySelector("#main .match-card.front") === card, other: Boolean(card.querySelector(`.option.other input[maxlength="1000"]`))};
  pick.click();
  const overview = await until(() => document.querySelector("#main .match-overview"), 3000);
  const found = {before, toggled, rows: overview ? all("#main .match-decision").map((item) => [item.dataset.card, text(item.querySelector(".match-verdict"))]) : [], wide: wide()};
  if (@SEND@) {
    document.querySelector("#main .match-release").click();
    found.toast = await until(() => all("#toasts .toast").map(text).find((entry) => entry.startsWith("Release")), 15000);
    found.posted = posted;
  }
  return found;
})()"""
INBOX = """(async () => {@HELPERS@@CAPTURE@
  const row = await until(() => all("#main .inbox-list > li").find((li) => li.textContent.includes("@QUESTION@")), 8000);
  if (!row) {
    return {error: text(document.getElementById("main"))};
  }
  const options = all(".options button.option", row);
  const submit = row.querySelector(".choice-send");
  const before = look(options, submit);
  [0, 2].forEach((index) => options[index].click());
  const found = {before, toggled: look(options, submit), wide: wide()};
  if (@SEND@) {
    const shown = new Set(all("#toasts .toast"));
    submit.click();
    found.toast = await until(() => all("#toasts .toast").filter((box) => !shown.has(box)).map(text).find((entry) => entry.startsWith("Choice:")), 20000);
    found.gone = Boolean(await until(() => !all("#main .inbox-list > li").some((li) => li.textContent.includes("@QUESTION@")), 20000));
    found.posted = posted;
  }
  return found;
})()"""
OTHER = """(async () => {@HELPERS@@CAPTURE@
  const row = await until(() => all("#main .inbox-list > li").find((li) => li.textContent.includes("@QUESTION@")), 8000);
  if (!row) {
    return {error: text(document.getElementById("main"))};
  }
  const field = row.querySelector(".option.other input");
  const found = {field: field ? [field.maxLength, field.getAttribute("aria-label").startsWith("Other answer to ")] : null, wide: wide()};
  if (@SEND@) {
    field.value = "  @TYPED@  ";
    const shown = new Set(all("#toasts .toast"));
    row.querySelector(".option.other button[type=submit]").click();
    found.toast = await until(() => all("#toasts .toast").filter((box) => !shown.has(box)).map(text).find((entry) => entry.startsWith("Choice:")), 20000);
    found.posted = posted;
  }
  return found;
})()"""
TYPED = "Keep the old one"
UNTOUCHED = {"pressed": ["false"] * 3, "recommended": [True, False, True], "disabled": True}
TOGGLED = {"pressed": ["true", "false", "true"], "recommended": [True, False, True], "disabled": False}


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestQuestionMulti(HubCase):
    drive = base.OrchestratorE2ECase.drive
    authenticator = base.OrchestratorE2ECase.authenticator

    def setUp(self):
        super().setUp()
        now = time.time()
        self.write_council({"work/s1/claim.json": {"office": "work/s1", "session": "s1", "runtime": "claude", "name": "Skills session", "since": iso(now - 86400), "beat": now, "work": "questions"}})
        self.decision = self.question(QUESTION, GROUPS, True)
        OUT.mkdir(parents=True, exist_ok=True)

    def question(self, text: str, labels: list[str], multi: bool) -> str:
        body = {"question": text, "options": [{"label": label, "description": ""} for label in labels], "session": "s1", "timeout": 600, "multi": multi}
        status, _, answer = self.post_json("/api/decisions", body, self.local())
        self.assertEqual(status, 201, answer)
        return json.loads(answer)["id"]

    def steps(self, probe: str, view: str, fills: dict[str, str]) -> list[dict]:
        found = []
        for width, height in sorted(base.WIDTHS, key=lambda size: size[0] == SENT_AT):
            script = probe.replace("@HELPERS@", base.HELPERS).replace("@CAPTURE@", CAPTURE).replace("@SEND@", "true" if width == SENT_AT else "false")
            for name, value in fills.items():
                script = script.replace(f"@{name}@", value)
            found.append({"width": width, "height": height, "url": f"http://localhost:{self.port}/?{width}{view}", "wait": 1500, "probe": script, "shot": str(OUT / f"chromium-{width}-{view.rsplit('/', 1)[-1]}.png")})
        return found

    def run_steps(self, probe: str, view: str, decision_id: str, expected: str, question: str = QUESTION) -> list[dict]:
        """Args:
            decision_id: the decision the last step answers.
            expected: the choice it holds afterwards.
            question: the question whose row or card the probe drives.
        """
        with mock.patch.object(batches, "UNDO", 0.3):
            steps = self.steps(probe, view, {"CARD": f"decision:{decision_id}", "QUESTION": question, "TYPED": TYPED})
            data = self.drive(steps, self.authenticator(), "cdp.mjs", os.environ.get("CHROMIUM", "chromium"))
            self.settle(lambda: self.httpd.hub.decisions.get(decision_id)["status"] == "decided")
        (OUT / f"chromium-{view.rsplit('/', 1)[-1]}.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "(style-src-elem)" not in error and "/favicon.ico" not in error], [])
        self.assertEqual(self.httpd.hub.decisions.get(decision_id)["choice"], expected)
        return data["results"]

    def test_chromium_match_toggles_a_multi_question_and_releases_the_picked_labels_in_option_order(self):
        results = self.run_steps(MATCH, "#tasks/match", self.decision, PICKED)
        for found in results:
            with self.subTest(sent="posted" in found):
                self.assertNotIn("error", found, found)
                self.assertEqual((found["before"], found["toggled"]), (UNTOUCHED, {**TOGGLED, "front": True, "other": True}), found)
                self.assertEqual(found["rows"], [[f"decision:{self.decision}", f"Accept: {GROUPS[0]}, {GROUPS[2]}"]], found)
                self.assertFalse(found["wide"], found)
        self.assertTrue(results[-1]["toast"].startswith("Release: 1 decision"), results[-1])
        self.assertEqual(results[-1]["posted"], [[["decision", self.decision, "approve", PICKED]]])

    def test_chromium_inbox_toggles_a_multi_question_and_sends_the_picked_labels_with_one_signature(self):
        results = self.run_steps(INBOX, "#stream/inbox", self.decision, PICKED)
        for found in results:
            with self.subTest(sent="posted" in found):
                self.assertNotIn("error", found, found)
                self.assertEqual((found["before"], found["toggled"]), (UNTOUCHED, TOGGLED), found)
                self.assertFalse(found["wide"], found)
        self.assertTrue(results[-1]["toast"].startswith(f"Choice: {GROUPS[0]}, {GROUPS[2]}") and results[-1]["gone"], results[-1])
        self.assertEqual(results[-1]["posted"], [[["decision", self.decision, "approve", PICKED]]])

    def test_chromium_inbox_sends_one_trimmed_line_of_other_text_for_a_hook_question(self):
        branch = "Name the branch?"
        single = self.question(branch, ["main", "dev"], False)
        results = self.run_steps(OTHER, "#stream/inbox", single, TYPED, branch)
        for found in results:
            with self.subTest(sent="posted" in found):
                self.assertNotIn("error", found, found)
                self.assertEqual(found["field"], [1000, True], found)
                self.assertFalse(found["wide"], found)
        self.assertTrue(results[-1]["toast"].startswith(f"Choice: {TYPED}"), results[-1])
        self.assertEqual(results[-1]["posted"], [[["decision", single, "approve", TYPED]]])


if __name__ == "__main__":
    unittest.main()
