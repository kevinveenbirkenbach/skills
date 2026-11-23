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

OUT = Path(os.environ.get("E2E_OUT", "/tmp/match-swipe-shots"))
REACH = 0.4
LIFT = 120
SIDE = """
  const key = (value) => document.body.dispatchEvent(new KeyboardEvent("keydown", {key: value, bubbles: true}));
  const front = () => (card() ? card().dataset.card : null);
  const tally = () => text(document.querySelector("#main .match-tally"));
  const point = () => {
    const name = card().querySelector(".match-name").getBoundingClientRect();
    return {front: front(), x: Math.round(name.left + name.width / 2), y: Math.round(name.top + name.height / 2), width: card().getBoundingClientRect().width};
  };
  const aim = (x, y) => {
    const at = document.elementFromPoint(x, y);
    return Boolean(at && at.closest(".match-card.front .match-head") && !at.closest("button, a, input, textarea, select"));
  };
  const turned = (id) => until(() => front() === id && card(), 6000);
  const fresh = () => new Set(all("#toasts .toast"));
  const toastSince = (shown, start) => until(() => all("#toasts .toast").filter((node) => !shown.has(node)).map(text).find((entry) => entry.startsWith(start)), 4000);
"""
MEASURE = """(async () => {@HELPERS@@CARD@@SIDE@
  await screenShown(8000);
  if (!(await turned("@COMMIT@"))) {
    return {error: text(document.getElementById("main"))};
  }
  await sleep(500);
  const points = [point()];
  key("ArrowUp");
  await turned("@COMMAND@");
  await sleep(400);
  points.push(point());
  key("ArrowLeft");
  const confirm = await until(() => document.querySelector(".match-feedback-reject"), 4000);
  confirm.click();
  await turned("@STALE@");
  await sleep(400);
  points.push(point());
  key("ArrowRight");
  await sleep(400);
  key("ArrowUp");
  await turned("@COMMIT@");
  await sleep(400);
  points.push(point());
  return {points, tally: tally()};
})()"""
START = """(async () => {@HELPERS@@CARD@@SIDE@
  await screenShown(8000);
  if (!(await turned("@COMMIT@"))) {
    return {error: text(document.getElementById("main"))};
  }
  await sleep(500);
  return {front: front(), aim: aim(@X@, @Y@), tally: tally()};
})()"""
LATER = """(async () => {@HELPERS@@CARD@@SIDE@
  await turned("@COMMAND@");
  await sleep(400);
  return {front: front(), tally: tally(), aim: aim(@X@, @Y@)};
})()"""
REJECT = """(async () => {@HELPERS@@CARD@@SIDE@
  const confirm = await until(() => document.querySelector(".match-feedback-reject"), 4000);
  const title = text(document.querySelector("#sheet .sheet-head h2"));
  const field = Boolean(document.querySelector("#sheet textarea.match-feedback"));
  if (confirm) {
    confirm.click();
  }
  await turned("@STALE@");
  await sleep(400);
  return {title, field, front: front(), tally: tally(), aim: aim(@X@, @Y@)};
})()"""
REFUSED = """(async () => {@HELPERS@@CARD@@SIDE@
  const toast = await toastSince(new Set(), "Accept: refused");
  const stayed = front();
  key("ArrowUp");
  await turned("@COMMIT@");
  await sleep(400);
  return {toast: Boolean(toast), stayed, front: front(), tally: tally(), aim: aim(@X@, @Y@)};
})()"""
ACCEPT = """(async () => {@HELPERS@@CARD@@SIDE@
  await until(() => tally() === "2", 4000);
  const counted = tally();
  document.querySelector("#main .match-open-overview").click();
  await until(() => document.querySelector("#main .match-overview"), 4000);
  await sleep(300);
  const decisions = all("#main .match-decision").map((row) => [row.dataset.card, row.dataset.verdict]).sort();
  return {tally: counted, decisions, wide: document.documentElement.scrollWidth > innerWidth + 1};
})()"""


def probe(template: str, **values: object) -> str:
    found = template.replace("@HELPERS@", base.HELPERS).replace("@CARD@", matched.CARD).replace("@SIDE@", SIDE)
    for name, value in values.items():
        found = found.replace(f"@{name}@", str(value))
    return found


def sideways(point: dict, width: int, sign: int) -> list[list[int]]:
    """Args:
        point: a measured {x, y, width} of a front card's name.
        width: the viewport width the drag stays inside.
        sign: 1 drags to the right, -1 to the left.

    Returns:
        The drag from the name REACH card widths sideways, kept 2 px inside the viewport.
    """
    end = min(max(point["x"] + sign * round(REACH * point["width"]), 2), width - 2)
    return [[point["x"], point["y"]], [end, point["y"]]]


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestMatchSwipe(HubCase):
    drive = base.OrchestratorE2ECase.drive
    cards = matched.TestMatchReview.cards
    review = matched.TestMatchReview.review
    payload = matched.TestMatchReview.payload

    def setUp(self):
        super().setUp()
        self.cards()

    def card_ids(self) -> dict[str, str]:
        return {"COMMIT": f"review:{self.commit}", "COMMAND": "operator:operator/issue", "STALE": f"review:{self.stale}"}

    def measured(self, driver: str, binary: str) -> dict[int, list[dict]]:
        steps = [{"width": width, "height": height, "url": f"{self.base}?{width}-measure#tasks/match", "wait": 1500, "probe": probe(MEASURE, **self.card_ids()), "shot": None} for width, height in base.WIDTHS]
        data = self.drive(steps, None, driver, binary)
        found = {}
        for result, (width, _) in zip(data["results"], base.WIDTHS, strict=True):
            self.assertNotIn("error", result, result)
            self.assertEqual([point["front"] for point in result["points"]], [self.card_ids()[name] for name in ("COMMIT", "COMMAND", "STALE", "COMMIT")], result)
            self.assertEqual(result["tally"], "1", result)
            found[width] = result["points"]
        return found

    def steps(self, browser: str, points: dict[int, list[dict]]) -> list[dict]:
        OUT.mkdir(parents=True, exist_ok=True)
        steps = []
        for width, height in base.WIDTHS:
            commit, command, stale, again = points[width]
            self.assertGreaterEqual(commit["y"] - max(commit["y"] - LIFT, 2), 90, commit)
            shot = str(OUT / f"{browser}-{width}")
            at = {"width": width, "height": height}
            steps += [
                {**at, "url": f"{self.base}?{width}-swipe#tasks/match", "wait": 1500, "probe": probe(START, X=commit["x"], Y=commit["y"], **self.card_ids()), "shot": None},
                {**at, "url": None, "wait": 0, "drag": [[commit["x"], commit["y"]], [commit["x"], max(commit["y"] - LIFT, 2)]], "probe": probe(LATER, X=command["x"], Y=command["y"], **self.card_ids()), "shot": None},
                {**at, "url": None, "wait": 0, "drag": sideways(command, width, -1), "probe": probe(REJECT, X=stale["x"], Y=stale["y"], **self.card_ids()), "shot": None},
                {**at, "url": None, "wait": 0, "drag": sideways(stale, width, 1), "probe": probe(REFUSED, X=again["x"], Y=again["y"], **self.card_ids()), "shot": None},
                {**at, "url": None, "wait": 0, "drag": sideways(again, width, 1), "probe": probe(ACCEPT), "shot": f"{shot}-swiped-decisions.png"},
            ]
        return steps

    def check(self, data: dict) -> None:
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        ids = self.card_ids()
        results = iter(data["results"])
        for width, _ in base.WIDTHS:
            start, later, reject, refused, accept = (next(results) for _ in range(5))
            with self.subTest(width=width):
                self.assertNotIn("error", start, start)
                self.assertEqual(start, {"front": ids["COMMIT"], "aim": True, "tally": "0"})
                self.assertEqual(later, {"front": ids["COMMAND"], "tally": "0", "aim": True})
                self.assertTrue(reject["title"] and reject["title"].startswith("Reject: "), reject)
                self.assertEqual({key: reject[key] for key in ("field", "front", "tally", "aim")}, {"field": True, "front": ids["STALE"], "tally": "1", "aim": True}, reject)
                self.assertEqual(refused, {"toast": True, "stayed": ids["STALE"], "front": ids["COMMIT"], "tally": "1", "aim": True})
                self.assertEqual(accept, {"tally": "2", "decisions": sorted([[ids["COMMIT"], "accept"], [ids["COMMAND"], "reject"]]), "wide": False})

    def test_chromium_real_mouse_swipes_send_later_reject_refuse_stale_and_accept_at_three_widths(self):
        binary = os.environ.get("CHROMIUM", "chromium")
        data = self.drive(self.steps("chromium", self.measured("cdp.mjs", binary)), None)
        (OUT / "chromium-match-swipe.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.check(data)

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_real_mouse_swipes_send_later_reject_refuse_stale_and_accept_at_three_widths(self):
        binary = os.environ.get("FIREFOX", "firefox")
        data = self.drive(self.steps("firefox", self.measured("bidi.mjs", binary)), None, "bidi.mjs", binary)
        (OUT / "firefox-match-swipe.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.check(data)


if __name__ == "__main__":
    unittest.main()
