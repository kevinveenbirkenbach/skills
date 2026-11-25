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
import test_workbench_w4_e2e as w4
from hub_case import HubCase
from kvb_orchestrator.skillindex import SKILLS_INDEX

OUT = Path(os.environ.get("E2E_OUT", "/tmp/slash-skills-shots"))
SKILLS = [
    {"name": "kvb-org-radio", "description": "Default channel to other agents", "source": "~/.claude/skills"},
    {"name": "kvb-org-rasci", "description": "Register of tasks", "source": "~/.claude/skills"},
    {"name": "kvb-org-robot", "description": "Work autonomously", "source": "~/.agents/skills"},
    {"name": "i8-alpha", "description": "Global one", "source": "~/.claude/skills"},
    {"name": "i8-zeta", "description": "Core one", "source": "/repo"},
]
KIT = """
  const shown = () => all(".slash-list .slash-option strong").map(text);
  const type = async (field, value) => {
    field.focus();
    field.value = value;
    field.setSelectionRange(value.length, value.length);
    field.dispatchEvent(new Event("input", {bubbles: true}));
    await until(() => shown().length, 2500);
    await sleep(150);
    return shown();
  };
  const key = (field, name) => field.dispatchEvent(new KeyboardEvent("keydown", {key: name, bubbles: true, cancelable: true}));
  const flow = async (field, prefix) => {
    const listed = await type(field, `/${prefix}`);
    const box = document.querySelector(".slash-list");
    const inside = box ? box.getBoundingClientRect().right <= innerWidth + 1 && box.getBoundingClientRect().left >= -1 : null;
    key(field, "Enter");
    await sleep(150);
    const picked = field.value;
    const word = await type(field, "a/b");
    const kept = await type(field, "keep /kvb");
    key(field, "Escape");
    await sleep(150);
    return {listed, inside, picked, word, kept: kept.length > 0, closed: !document.querySelector(".slash-list"), text: field.value};
  };
"""
COMPOSER = """(async () => {@HELPERS@@KIT@
  await screenShown(8000);
  const field = await until(() => document.querySelector("#radio-spot:not([hidden]) .radio-speak textarea[data-skills]"), 8000);
  if (!field) {
    return {error: text(document.getElementById("main"))};
  }
  return flow(field, "kvb-org-r");
})()"""
FEEDBACK = """(async () => {@HELPERS@@KIT@
  await screenShown(8000);
  const reject = await until(() => document.querySelector("#main .match-actions .match-reject:not([disabled])"), 8000);
  if (!reject) {
    return {error: text(document.getElementById("main"))};
  }
  reject.click();
  const field = await until(() => document.querySelector("#sheet:not([hidden]) textarea.match-feedback[data-skills]"), 4000);
  if (!field) {
    return {error: "no feedback field"};
  }
  const core = await type(field, "/i8-");
  const result = {repo: field.dataset.skills, core, ...(await flow(field, "kvb-org-r"))};
  key(field, "Escape");
  await until(() => document.getElementById("sheet").hidden, 3000);
  return result;
})()"""
INJECTED = """(async () => {@HELPERS@@KIT@
  const field = document.createElement("textarea");
  field.dataset.skills = "";
  document.getElementById("main").append(field);
  await sleep(200);
  const result = await flow(field, "kvb-org-r");
  field.remove();
  return result;
})()"""


def probe(template: str) -> str:
    return template.replace("@HELPERS@", base.HELPERS).replace("@KIT@", KIT)


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestSlashSkills(HubCase):
    drive = base.OrchestratorE2ECase.drive
    cards = matched.TestMatchReview.cards
    review = matched.TestMatchReview.review
    payload = matched.TestMatchReview.payload

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        self.cards()
        self.tree_file.with_name(SKILLS_INDEX).write_text(json.dumps({"written": 1, "skills": SKILLS}), encoding="utf-8")

    def steps(self, browser: str) -> list[dict]:
        steps = []
        for width, height in base.WIDTHS:
            at = {"width": width, "height": height}
            shot = OUT / f"{browser}-{width}"
            steps += [
                {**at, "url": f"{self.base}?{width}-composer#stream/radio", "wait": 1200, "probe": probe(COMPOSER), "shot": f"{shot}-composer.png"},
                {**at, "url": f"{self.base}?{width}-feedback#tasks/match", "wait": 1500, "probe": probe(FEEDBACK), "shot": f"{shot}-feedback.png"},
                {**at, "url": None, "wait": 0, "probe": probe(INJECTED), "shot": None},
            ]
        return steps

    def check_flow(self, found: dict) -> None:
        self.assertNotIn("error", found, found)
        self.assertEqual(found["listed"][0], "/kvb-org-radio", found)
        self.assertEqual((found["inside"], found["picked"], found["word"], found["kept"], found["closed"], found["text"]), (True, "/kvb-org-radio ", [], True, True, "keep /kvb"), found)

    def check(self, data: dict, browser: str) -> None:
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        results = iter(data["results"])
        for width, _ in base.WIDTHS:
            for field in ("composer", "feedback", "injected"):
                found = next(results)
                with self.subTest(browser=browser, width=width, field=field):
                    self.check_flow(found)
                    if field == "feedback":
                        self.assertEqual((found["repo"], found["core"]), ("/repo", ["/i8-zeta", "/i8-alpha"]), found)

    def test_chromium_suggests_skills_after_a_slash_in_every_agent_field(self):
        data = self.drive(self.steps("chromium"), None, init=w4.GUARD)
        (OUT / "chromium-slash.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.check(data, "chromium")

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_suggests_skills_after_a_slash_in_every_agent_field(self):
        data = self.drive(self.steps("firefox"), None, "bidi.mjs", os.environ.get("FIREFOX", "firefox"), init=w4.GUARD)
        (OUT / "firefox-slash.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.check(data, "firefox")


if __name__ == "__main__":
    unittest.main()
