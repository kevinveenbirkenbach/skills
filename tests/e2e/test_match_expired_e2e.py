from __future__ import annotations

import json
import os
import re
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
from hub_support import ASK, signing
from kvb_orchestrator import batches, skill_scripts

OUT = Path(os.environ.get("E2E_OUT", "/tmp/hub-096-expired-shots"))
AGO = 690
GONE_MS = 300
TIP = re.compile(r"^expired \d{2}:\d{2}, 12 minutes ago$")
FLOW = """(async () => {@HELPERS@
  const posted = [];
  const send = window.fetch.bind(window);
  window.fetch = async (path, init) => {
    if (["/api/sign", "/api/inbox/approve", "/api/requests/dismiss"].includes(String(path))) {
      posted.push([String(path), JSON.parse(init.body).items.map((item) => [item.kind, item.target || null, item.id, item.verb || null, item.scope || null, item.channel || null])]);
    }
    return send(path, init);
  };
  const sheet = document.getElementById("sheet");
  let opened = false;
  new MutationObserver(() => {
    opened = opened || !sheet.hidden;
  }).observe(sheet, {attributes: true, attributeFilter: ["hidden"]});
  const card = () => document.querySelector("#main .match-card.front");
  const front = () => (card() ? card().dataset.card : null);
  if (!(await until(card, 8000))) {
    return {error: text(document.getElementById("main"))};
  }
  const key = (name) => document.body.dispatchEvent(new KeyboardEvent("keydown", {key: name, bubbles: true, cancelable: true}));
  const id = front();
  const stamp = card().querySelector(".match-stamp");
  if (!stamp) {
    return {id, stamp: null};
  }
  stamp.dispatchEvent(new MouseEvent("mouseenter"));
  const style = getComputedStyle(stamp);
  const found = {id, stamp: text(stamp), kind: stamp.dataset.stamp, tip: stamp.title, color: style.color, opacity: style.opacity, pointer: style.pointerEvents,
    accept: document.querySelector("#main .match-accept").disabled, reject: document.querySelector("#main .match-reject").disabled};
  const swipe = async (share) => {
    const head = card().querySelector(".match-head");
    const box = head.getBoundingClientRect();
    const at = (x) => ({bubbles: true, cancelable: true, pointerId: 9, pointerType: "touch", isPrimary: true, button: 0, clientX: x, clientY: box.top + 20});
    head.dispatchEvent(new PointerEvent("pointerdown", at(box.left + box.width / 2)));
    window.dispatchEvent(new PointerEvent("pointermove", at(box.left + box.width * (0.5 + share / 2))));
    const leaned = card().dataset.leaning || "";
    const start = performance.now();
    window.dispatchEvent(new PointerEvent("pointerup", at(box.left + box.width * (0.5 + share))));
    return {leaned, start};
  };
  const right = await swipe(0.45);
  await sleep(500);
  found.leaned = right.leaned;
  found.kept = front() === id;
  found.tally = text(document.querySelector("#main .match-tally"));
  found.wide = document.documentElement.scrollWidth > window.innerWidth + 1;
  if (@RELEASE@) {
    const left = await swipe(-0.45);
    found.leftLeaned = left.leaned;
    while (front() === id && performance.now() - left.start < 2000) {
      await sleep(10);
    }
    found.goneMs = performance.now() - left.start;
    await sleep(400);
    found.sheetAfterSwipe = opened;
    found.dropRows = all("#main .match-decision").map((row) => [row.dataset.card, row.dataset.verdict, text(row.querySelector(".match-verdict")), Boolean(row.querySelector(".match-decision-feedback"))]);
    key("s");
    found.undone = Boolean(await until(() => front() === id, 3000));
    key("ArrowLeft");
    const overview = await until(() => document.querySelector("#main .match-overview"), 4000);
    found.sheetAfterKey = opened;
    found.rows = overview ? all("#main .match-decision").map((row) => [row.dataset.card, row.dataset.verdict, text(row.querySelector(".match-verdict")), Boolean(row.querySelector(".match-decision-feedback"))]) : [];
    const shown = new Set(all("#toasts .toast"));
    document.querySelector("#main .match-release").click();
    found.toast = await until(() => all("#toasts .toast").filter((node) => !shown.has(node)).map(text).find((entry) => entry.startsWith("Release")), 15000);
    found.emptied = Boolean(await until(() => document.querySelector("#main .match-stack .empty"), 15000));
    found.posted = posted;
  }
  return found;
})()"""
AGAIN = """(async () => {@HELPERS@
  await until(() => document.querySelector("#main .match-stack .empty, #main .match-card.front"), 8000);
  const response = await fetch("/api/match", {cache: "no-store"});
  const cards = (await response.json()).cards.map((card) => card.id);
  const front = document.querySelector("#main .match-card.front");
  return {again: true, cards, front: front ? front.dataset.card : null, empty: Boolean(document.querySelector("#main .match-stack .empty"))};
})()"""


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestMatchExpired(HubCase):
    drive = base.OrchestratorE2ECase.drive
    authenticator = base.OrchestratorE2ECase.authenticator

    def setUp(self):
        super().setUp()
        self.claim("s1", "Skills session")
        self.ask = self.create_ask({**ASK, "call_key": signing.call_key("Bash", {"command": ASK["command"]})})
        self.httpd.hub.asks.change(self.ask, {"expires": time.time() - AGO})

    def radio(self) -> list[list[str]]:
        return [args for script, args in self.scripts.calls if script == skill_scripts.RADIO]

    def step(self, width: int, height: int, release: bool) -> dict:
        flow = FLOW.replace("@HELPERS@", base.HELPERS).replace("@RELEASE@", "true" if release else "false")
        shot = OUT / f"chromium-{width}-{'released' if release else 'expired'}.png"
        return {"width": width, "height": height, "url": f"http://localhost:{self.port}/?{width}-{release}#tasks/match", "wait": 1500, "probe": flow, "shot": str(shot)}

    def again(self) -> dict:
        return {"width": 1366, "height": 768, "url": f"http://localhost:{self.port}/?again#tasks/match", "wait": 1500, "probe": AGAIN.replace("@HELPERS@", base.HELPERS), "shot": str(OUT / "chromium-1366-again.png")}

    def test_chromium_drops_an_expired_ask_silently_and_the_release_dismisses_it_for_every_page(self):
        OUT.mkdir(parents=True, exist_ok=True)
        steps = [self.step(width, height, False) for width, height in base.WIDTHS] + [self.step(1366, 768, True)]
        with mock.patch.object(batches, "UNDO", 0.3):
            data = self.drive(steps, self.authenticator())
            self.settle(lambda: self.httpd.hub.dismissals.listed() != [])
        again = self.drive([self.again()], None)
        (OUT / "chromium-expired.json").write_text(json.dumps({"release": data, "again": again}, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "(style-src-elem)" not in error and "/favicon.ico" not in error], [])
        self.assertEqual(len(data["results"]), len(steps), data)
        card = f"ask:{self.ask}"
        for found in data["results"]:
            with self.subTest(step=found.get("toast") is not None):
                self.assertNotIn("error", found, found)
                self.assertEqual((found["id"], found["stamp"], found["kind"]), (card, "EXPIRED", "expired"), found)
                self.assertRegex(found["tip"], TIP)
                self.assertEqual((found["opacity"], found["pointer"]), ("1", "auto"), found)
                channels = [int(part) for part in found["color"].removeprefix("rgb(").removesuffix(")").split(",")[:3]]
                self.assertGreater(max(channels) - min(channels), 20, found)
                self.assertEqual((found["accept"], found["reject"]), (True, False), found)
                self.assertEqual((found["leaned"], found["kept"], found["tally"]), ("", True, "0"), found)
                self.assertFalse(found["wide"], found)
        released = data["results"][-1]
        self.assertEqual(released["leftLeaned"], "reject", released)
        self.assertLess(released["goneMs"], GONE_MS, released)
        self.assertFalse(released["sheetAfterSwipe"], released)
        self.assertEqual(released["dropRows"], [[card, "drop", "Drop (expired)", False]], released)
        self.assertTrue(released["undone"], released)
        self.assertFalse(released["sheetAfterKey"], released)
        self.assertEqual(released["rows"], [[card, "drop", "Drop (expired)", False]], released)
        self.assertNotIn("not possible", released["toast"], released)
        self.assertTrue(released["emptied"], released)
        self.assertEqual([path for path, _ in released["posted"]], ["/api/sign", "/api/inbox/approve"], released)
        self.assertEqual(released["posted"][1][1], [["dismiss", "ask", self.ask, None, "expired", None]], released)
        self.assertEqual(len(again["results"]), 1, again)
        shown = again["results"][0]
        self.assertNotIn(card, shown["cards"], shown)
        self.assertEqual((shown["front"], shown["empty"]), (None, True), shown)
        self.assertEqual(self.httpd.hub.asks.get(self.ask)["status"], "pending")
        self.assertEqual(self.radio(), [])
        status, _, body = self.get("/api/match")
        self.assertEqual(status, 200, body)
        self.assertNotIn(card, [entry["id"] for entry in json.loads(body)["cards"]])


if __name__ == "__main__":
    unittest.main()
