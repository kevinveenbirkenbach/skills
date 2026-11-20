from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

import hub_e2e_kit as base
from hub_case import HubCase
from hub_support import iso
from kvb_orchestrator import batches, ledger, skill_scripts

OUT = Path(os.environ.get("E2E_OUT", "/tmp/hub-012-release-shots"))
FIRST = "src/app.py"
RELEASE_AT = 1366
FLOW = """(async () => {@HELPERS@
  if (!@SIGNS@) {
    navigator.credentials.get = () => Promise.reject(new DOMException("The operator canceled.", "NotAllowedError"));
  }
  const posted = [];
  const statuses = [];
  let tamper = @SIGNS@ && @RELEASE@;
  const send = window.fetch.bind(window);
  window.fetch = async (path, init) => {
    if (!["/api/sign", "/api/inbox/approve"].includes(String(path))) {
      return send(path, init);
    }
    let body = JSON.parse(init.body);
    if (String(path) === "/api/inbox/approve" && tamper) {
      tamper = false;
      body = {...body, items: body.items.map((item) => (item.verb === "reject" ? {kind: item.kind, id: item.id, verb: "approve", label: item.label, sha256: item.sha256} : item))};
    }
    posted.push([String(path), body.items.map((item) => [item.kind, item.id, item.verb, item.channel || null, item.reason || null, item.to || null])]);
    const response = await send(path, {...init, body: JSON.stringify(body)});
    statuses.push(response.status);
    return response;
  };
  const card = () => document.querySelector("#main .match-card.front");
  const front = () => (card() ? card().dataset.card : null);
  if (!(await until(card, 8000))) {
    return {error: text(document.getElementById("main"))};
  }
  const key = (name) => document.body.dispatchEvent(new KeyboardEvent("keydown", {key: name, bubbles: true, cancelable: true}));
  const swipe = async (dx, dy) => {
    const head = card().querySelector(".match-head");
    const box = head.getBoundingClientRect();
    const [x, y] = [box.left + box.width / 2, box.top + 20];
    const at = (cx, cy) => ({bubbles: true, cancelable: true, pointerId: 11, pointerType: "touch", isPrimary: true, button: 0, clientX: cx, clientY: cy});
    head.dispatchEvent(new PointerEvent("pointerdown", at(x, y)));
    window.dispatchEvent(new PointerEvent("pointermove", at(x + dx / 2, y + dy / 2)));
    const leaning = card().dataset.leaning || "";
    window.dispatchEvent(new PointerEvent("pointerup", at(x + dx, y + dy)));
    await sleep(250);
    return leaning;
  };
  const order = [front()];
  const row = card().querySelector('.match-file[data-path="@FIRST@"] tr[data-line="3"]');
  row.scrollIntoView({block: "center"});
  const spot = row.getBoundingClientRect();
  row.dispatchEvent(new MouseEvent("contextmenu", {bubbles: true, cancelable: true, clientX: spot.left + 40, clientY: spot.top + 4, button: 2}));
  const field = await until(() => card().querySelector(".match-comment textarea"), 3000);
  field.value = "rename it";
  card().querySelector(".match-comment .match-save").click();
  await sleep(200);
  key("ArrowLeft");
  const feedback = await until(() => document.querySelector(".sheet-box .match-feedback"), 3000);
  const prefill = feedback ? feedback.value : null;
  feedback.value = `${prefill}\\nalso add a test`;
  document.querySelector(".sheet-box .match-feedback-reject").click();
  await until(() => front() !== order[0], 3000);
  order.push(front());
  key("ArrowUp");
  await until(() => front() !== order[1], 3000);
  order.push(front());
  const width = card().getBoundingClientRect().width;
  const leaned = await swipe(width * 0.4, 0);
  await until(() => front() !== order[2], 3000);
  order.push(front());
  const short = await swipe(width * 0.1, 0);
  const stayed = front() === order[3];
  await swipe(width * 0.4, 4);
  const overview = await until(() => document.querySelector("#main .match-overview"), 3000);
  const rows = overview ? all("#main .match-decision").map((item) => [item.dataset.card, item.dataset.verdict, text(item.querySelector(".match-decision-feedback"))]) : [];
  const release = document.querySelector("#main .match-release");
  const found = {order, prefill, leaned, short, stayed, rows, label: text(release), disabled: release.disabled, wide: document.documentElement.scrollWidth > window.innerWidth + 1};
  if (@RELEASE@) {
    const toastAfter = async (click) => {
      const shown = new Set(all("#toasts .toast"));
      click();
      return until(() => all("#toasts .toast").filter((node) => !shown.has(node)).map(text).find((entry) => entry.startsWith("Release")), 15000);
    };
    if (@SIGNS@) {
      found.tampered = await toastAfter(() => release.click());
      found.kept = all("#main .match-decision").length;
    }
    const flashed = new Set();
    const watch = window.setInterval(() => all("#main .match-card").forEach((node) => flashed.add(node.dataset.card)), 20);
    found.toast = await toastAfter(() => document.querySelector("#main .match-release").click());
    found.emptied = @SIGNS@ ? Boolean(await until(() => document.querySelector("#main .match-stack .empty"), 15000)) : false;
    await sleep(@SIGNS@ ? 2500 : 0);
    window.clearInterval(watch);
    found.flashed = [...flashed];
    found.posted = posted;
    found.statuses = statuses;
  }
  return found;
})()"""


def patch(lines: int) -> str:
    rows = [f"@@ -1,{lines} +1,{lines + 1} @@"] + [f" line {number}" for number in range(1, lines + 1)]
    rows.insert(4, "+added line")
    return "\n".join(rows)


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestMatchRelease(HubCase):
    drive = base.OrchestratorE2ECase.drive
    authenticator = base.OrchestratorE2ECase.authenticator

    def setUp(self):
        super().setUp()
        work = tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.work = Path(work.name)
        now = time.time()
        self.write_council({
            "work/s1/claim.json": {"office": "work/s1", "session": "s1", "runtime": "claude", "name": "Skills session", "since": iso(now - 86400), "beat": now, "work": "match"},
            "work/s2/claim.json": {"office": "work/s2", "session": "s2", "runtime": "claude", "name": "Stage session", "since": iso(now - 86400), "beat": now, "work": "i18n"},
        })
        self.rejected = self.review("feat: rejected stage", "feature/one", "Skills", [(FIRST, 20), ("docs/notes.md", 8)], now - 120)
        self.accepted = self.review("feat: accepted stage", "feature/two", "Stage", [("src/two.py", 12)], now - 60)
        folder = self.state / "firewall"
        folder.mkdir(parents=True, exist_ok=True)
        files = [{"path": "/home/op/.claude/settings.json", "exists": True, "sha256": "", "settings": {"sandbox": {"filesystem": {"denyRead": []}}}}]
        (folder / "view.json").write_text(json.dumps({"written": "2026-11-14T12:00:00+00:00", "files": files}), encoding="utf-8")
        self.write_council({"rasci.json": {"operator/ship": {"title": "make ship", "workdir": str(self.work), "description": "ship it", "check": "done", "roles": {"Skills": "A", "Operator": "R"}}}})
        self.cards = [f"review:{self.rejected}", f"review:{self.accepted}", "operator:operator/ship"]

    def review(self, title: str, branch: str, agent: str, files: list[tuple[str, int]], created: float) -> str:
        """Args:
            created: when the review was requested; the stamp has second
                resolution, so reviews requested in one second tie and their
                random ids would decide the card order.
        """
        diff = [{"path": path, "status": "M", "mode": "100644", "additions": 1, "deletions": 0, "patch": patch(lines), "note": ""} for path, lines in files]
        page = self.page(f"{branch.replace('/', '-')}.html", "<!doctype html><title>p</title>")
        arguments = {**self.arguments(title, "", page), "worktree": f"/repo/.worktrees/{branch}", "branch": branch, "agent": agent, "diff": diff}
        with mock.patch.object(ledger, "stamp", return_value=iso(created)):
            result = self.tool("review_request", arguments)
        self.assertFalse(result["isError"], result)
        return result["structuredContent"]["id"]

    def radio(self) -> list[list[str]]:
        return [args for script, args in self.scripts.calls if script == skill_scripts.RADIO]

    def steps(self, browser: str, signs: bool) -> list[dict]:
        OUT.mkdir(parents=True, exist_ok=True)
        widths = sorted(base.WIDTHS, key=lambda size: size[0] == RELEASE_AT)
        steps = []
        for width, height in widths:
            flow = FLOW.replace("@HELPERS@", base.HELPERS).replace("@FIRST@", FIRST).replace("@SIGNS@", "true" if signs else "false")
            flow = flow.replace("@RELEASE@", "true" if width == RELEASE_AT else "false")
            steps.append({"width": width, "height": height, "url": f"http://localhost:{self.port}/?{width}#tasks/match", "wait": 1500, "probe": flow, "shot": str(OUT / f"{browser}-{width}-overview.png")})
        return steps

    def check_flow(self, found: dict) -> None:
        reason = f"{FIRST}:3: rename it"
        self.assertNotIn("error", found, found)
        self.assertEqual(found["order"], [self.cards[0], self.cards[1], self.cards[2], self.cards[1]], found)
        self.assertEqual((found["prefill"], found["leaned"], found["short"], found["stayed"]), (reason, "accept", "accept", True), found)
        expected = [[self.cards[0], "reject", f"{reason}\nalso add a test"], [self.cards[1], "accept", None], [self.cards[2], "accept", None]]
        self.assertEqual(sorted(found["rows"]), sorted(expected), found)
        self.assertEqual((found["label"], found["disabled"], found["wide"]), ("Release 3 decisions", False, False), found)

    def run_flow(self, browser: str, driver: str, binary: str, signs: bool) -> dict:
        with mock.patch.object(batches, "UNDO", 0.3):
            data = self.drive(self.steps(browser, signs), self.authenticator() if signs else None, driver, binary)
            if signs:
                self.settle(lambda: self.status(self.rejected) == "rejected" and self.status(self.accepted) == "approved")
        (OUT / f"{browser}-release.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "(style-src-elem)" not in error and "/favicon.ico" not in error], [])
        self.assertEqual(len(data["results"]), len(base.WIDTHS), data)
        for found in data["results"]:
            with self.subTest(browser=browser, release="toast" in found):
                self.check_flow(found)
        return data["results"][-1]

    def test_chromium_swipes_three_cards_rejects_with_feedback_and_releases_with_one_signature(self):
        released = self.run_flow("chromium", "cdp.mjs", os.environ.get("CHROMIUM", "chromium"), signs=True)
        self.assertTrue(released["tampered"].startswith("Release: 3 decisions: not possible"), released)
        self.assertIn("list every approved item", released["tampered"], released)
        self.assertEqual(released["kept"], 3, released)
        self.assertTrue(released["toast"].startswith("Release: 3 decisions"), released)
        self.assertNotIn("not possible", released["toast"], released)
        self.assertTrue(released["emptied"], released)
        self.assertEqual(released["flashed"], [], released)
        posted = [path for path, _ in released["posted"]]
        self.assertEqual(posted, ["/api/sign", "/api/inbox/approve"] * 2)
        self.assertEqual(released["statuses"], [200, 400, 200, 202], released)
        self.assertIn(["review", self.rejected, "approve", None, None, None], released["posted"][1][1])
        items = sorted(released["posted"][3][1])
        told = f"{FIRST}:3: rename it\nalso add a test"
        self.assertEqual(items, sorted([["review", self.rejected, "reject", "call", told, "Skills"], ["review", self.accepted, "approve", None, None, None], ["operator", "operator/ship", "approve", None, None, None]]))
        stored = self.httpd.hub.reviews.get(self.rejected)
        self.assertEqual((stored["channel"], stored["reason"], stored["to"]), ("call", f"{FIRST}:3: rename it also add a test", "Skills"))
        self.assertIsNotNone(self.httpd.hub.reviews.get(self.accepted)["proof"])
        self.assertEqual([(job["task"], job["status"]) for job in self.httpd.hub.jobs.listed()], [("operator/ship", "queued")])
        self.settle(lambda: self.radio() != [])
        self.assertEqual(self.radio()[-1][:4], ["send", "call", "--to", "Skills session"])
        self.assertTrue(self.radio()[-1][-1].endswith(f"Reason: {FIRST}:3: rename it also add a test"), self.radio()[-1])

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_swipes_three_cards_and_releases_nothing_unsigned(self):
        refused = self.run_flow("firefox", "bidi.mjs", os.environ.get("FIREFOX", "firefox"), signs=False)
        self.assertIn("not signed", refused["toast"], refused)
        self.assertEqual([path for path, _ in refused["posted"]], ["/api/sign"])
        time.sleep(0.5)
        self.assertEqual((self.status(self.rejected), self.status(self.accepted)), ("pending", "pending"))
        self.assertEqual((self.httpd.hub.jobs.listed(), self.radio()), ([], []))


if __name__ == "__main__":
    unittest.main()
