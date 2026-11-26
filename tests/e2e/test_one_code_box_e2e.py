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
from hub_support import ASK
from kvb_orchestrator import batches

OUT = Path(os.environ.get("E2E_OUT", "/tmp/hub-047-shots"))
LONG = "\n".join(f"echo line {number}" for number in range(1, 201))
SHIP = "make ship " + " ".join(f"ARG{number}=value" for number in range(40))
KIT = """
  const press = async (button) => {
    button.click();
    await sleep(250);
    return button.getAttribute("aria-expanded");
  };
  const look = (box) => {
    const body = box.querySelector(".code-body");
    const foot = box.querySelector(".code-foot");
    return {
      last: box.lastElementChild === foot, foot: all("button", foot).map(name), expanded: foot.querySelector(".code-eye").getAttribute("aria-expanded"),
      clipped: body.scrollHeight > body.clientHeight + 1,
    };
  };
  const toggle = async (box) => {
    const eye = box.querySelector(".code-eye");
    const first = {...look(box)};
    const opened = await press(eye);
    const full = {expanded: opened, clipped: look(box).clipped};
    const closed = await press(eye);
    return {first, full, closed: {expanded: closed, clipped: look(box).clipped}};
  };
  const loose = (selector) => all(selector).filter((node) => !node.closest(".code-box")).length;
"""
STREAM = """(async () => {@HELPERS@@KIT@
  await streamShowsAll();
  const rowOf = () => document.querySelector('#main .feed > li[data-ref="@ASK@"]');
  const reviewOf = () => all("#main .feed > li.k-review").find((li) => !li.classList.contains("waiting") && text(li).includes("@REVIEW_TITLE@"));
  await until(() => rowOf() && reviewOf(), 8000);
  await sleep(1500);
  const [row, review] = [rowOf(), reviewOf()];
  if (!row || !review) {
    return {error: text(document.getElementById("main")).slice(0, 300)};
  }
  const ask = await toggle(row.querySelector(".code-box"));
  const box = review.querySelector(".code-box");
  const before = box ? box.querySelectorAll(".diff-file").length : null;
  box.querySelector(".code-eye").click();
  const loaded = Boolean(await until(() => all("#main .feed > li.k-review").find((li) => text(li).includes("@REVIEW_TITLE@") && li.querySelector(".code-box .diff-file")), 8000));
  return {ask, before, loaded, sheet: Boolean(document.querySelector("#sheet:not([hidden])")), loose: loose("#main .command, #main .diff-file"), wide: document.documentElement.scrollWidth > innerWidth + 1};
})()"""
OPERATOR = """(async () => {@HELPERS@@KIT@
  const row = await until(() => document.querySelector('#main .inbox-list > li[data-ref="@ASK@"]'), 8000);
  if (!row) {
    return {error: text(document.getElementById("main")).slice(0, 300)};
  }
  return {ask: await toggle(row.querySelector(".code-box")), loose: loose("#main .command, #main .diff-file"), wide: document.documentElement.scrollWidth > innerWidth + 1};
})()"""
MATCH = """(async () => {@HELPERS@@KIT@
  const front = () => document.querySelector("#main .match-card.front");
  await until(front, 8000);
  for (let tries = 0; tries < 12 && front() && front().dataset.card !== "@ASK@"; tries += 1) {
    const id = front().dataset.card;
    document.body.dispatchEvent(new KeyboardEvent("keydown", {key: "w", bubbles: true, cancelable: true}));
    await until(() => front() && front().dataset.card !== id, 3000);
    await sleep(200);
  }
  const card = front();
  if (!card || card.dataset.card !== "@ASK@") {
    return {error: card ? card.dataset.card : "no card"};
  }
  const box = card.querySelector(".code-box");
  const body = card.querySelector(".match-body");
  return {box: look(box), place: box.dataset.place, scrolls: body.scrollHeight > body.clientHeight + 1, overflowY: getComputedStyle(body).overflowY,
    page: document.documentElement.scrollHeight > innerHeight + 1, loose: loose("#main .match-command, #main .match-file")};
})()"""
TASKS = """(async () => {@HELPERS@@KIT@
  const row = await until(() => document.querySelector('#main li[data-task="operator/ship"]'), 8000);
  if (!row) {
    return {error: text(document.getElementById("main")).slice(0, 300)};
  }
  const box = row.querySelector(".code-box");
  const first = look(box);
  box.querySelector(".code-eye").click();
  const sheet = await until(() => document.querySelector('#sheet:not([hidden]) .code-box[data-place="sheet"]'), 4000);
  const full = sheet ? text(sheet) : null;
  document.dispatchEvent(new KeyboardEvent("keydown", {key: "Escape", bubbles: true}));
  const closed = Boolean(await until(() => !document.querySelector("#sheet:not([hidden])"), 4000));
  return {place: box.dataset.place, first, full, closed, loose: loose("#main .command, #main .diff-file")};
})()"""


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestOneCodeBox(base.OrchestratorE2ECase):
    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        self.ask =f"ask:{self.create_ask({**ASK, 'command': LONG, 'timeout': 3600})}"
        register = json.loads((self.council / "rasci.json").read_text(encoding="utf-8"))
        register["operator/ship"] = {"title": SHIP, "workdir": "/repo", "status": "running", "roles": {"Operator": "R"}}
        self.write_council({"rasci.json": register})
        diff = [{"path": "src/box.py", "status": "M", "mode": "100644", "additions": 1, "deletions": 0, "patch": "@@ -1,1 +1,2 @@\n line 1\n+box line", "note": ""}]
        self.review_title = "feat: decided box"
        arguments = {**self.arguments(self.review_title, "", self.page("box.html", "<!doctype html><title>p</title>")), "worktree": "/repo/.worktrees/feature/box", "branch": "feature/box", "agent": "Stage", "diff": diff}
        review = self.tool("review_request", arguments)["structuredContent"]["id"]
        entries = [self.entry("review", review, "", "")]
        with mock.patch.object(batches, "UNDO", 0.05):
            self.assertEqual(self.approve(entries, self.signed(entries, self.pin()))[0], 202)
            self.settle(lambda: self.status(review) == "approved")

    def fill(self, probe: str) -> str:
        return probe.replace("@HELPERS@", base.HELPERS).replace("@KIT@", KIT).replace("@ASK@", self.ask).replace("@REVIEW_TITLE@", self.review_title)

    def test_chromium_puts_every_command_and_diff_in_one_code_box_whose_eye_toggles_in_place_at_1920_and_390(self):
        steps = []
        for width, height in ((1920, 1080), (390, 844)):
            page = f"{self.base}?{width}"
            steps += [
                {"width": width, "height": height, "url": f"{page}-stream#stream", "wait": 1500, "probe": self.fill(STREAM), "shot": str(OUT / f"chromium-{width}-stream.png")},
                {"width": width, "height": height, "url": f"{page}-operator#tasks/operator", "wait": 1500, "probe": self.fill(OPERATOR), "shot": str(OUT / f"chromium-{width}-operator.png")},
                {"width": width, "height": height, "url": f"{page}-match#tasks/match", "wait": 1500, "probe": self.fill(MATCH), "shot": str(OUT / f"chromium-{width}-match.png")},
                {"width": width, "height": height, "url": f"{page}-tasks#tasks/list", "wait": 1500, "probe": self.fill(TASKS), "shot": str(OUT / f"chromium-{width}-tasks.png")},
            ]
        data = self.drive(steps, None)
        (OUT / "chromium-code-box.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        for index, width in enumerate((1920, 390)):
            stream, operator, match, tasks = data["results"][index * 4:index * 4 + 4]
            with self.subTest(width=width):
                for found in (stream, operator, match, tasks):
                    self.assertNotIn("error", found, found)
                    self.assertEqual(found["loose"], 0, found)
                for found in (stream["ask"], operator["ask"]):
                    self.assertEqual((found["first"]["last"], found["first"]["expanded"], found["first"]["clipped"]), (True, "false", True), found)
                    self.assertEqual(found["first"]["foot"][:2], ["Copy", "Show all"], found)
                    self.assertTrue({"Grant", "Deny"} <= set(found["first"]["foot"]), found)
                    self.assertEqual(found["full"], {"expanded": "true", "clipped": False}, found)
                    self.assertEqual(found["closed"], {"expanded": "false", "clipped": True}, found)
                self.assertEqual((stream["before"], stream["loaded"], stream["sheet"], stream["wide"], operator["wide"]), (0, True, False, False, False), stream)
                self.assertEqual((match["place"], match["box"]["expanded"], match["box"]["last"], match["box"]["foot"]), ("open", "true", True, ["Copy", "Show less"]), match)
                self.assertEqual((match["scrolls"], match["overflowY"], match["page"]), (True, "auto", False), match)
                self.assertEqual((tasks["place"], tasks["first"]["expanded"], tasks["closed"]), ("closed", "false", True), tasks)
                self.assertIn(SHIP, tasks["full"], tasks)


if __name__ == "__main__":
    unittest.main()
