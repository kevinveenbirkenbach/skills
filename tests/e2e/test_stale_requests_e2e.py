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
from hub_support import ASK, signing
from kvb_orchestrator import batches, skill_scripts

OUT = Path(os.environ.get("E2E_OUT", "/tmp/hub-093-stale-shots"))
LONG = "\n".join(f"echo line {number}" for number in range(1, 41))
UNDO = 4
FLOW = """(async () => {@HELPERS@
  const posted = [];
  const send = window.fetch.bind(window);
  window.fetch = async (path, init) => {
    if (["/api/sign", "/api/requests/dismiss"].includes(String(path))) {
      posted.push([String(path), JSON.parse(init.body).items.map((item) => [item.kind, item.target, item.id, item.scope])]);
    }
    return send(path, init);
  };
  const enabled = (selector) => until(() => {
    const node = document.querySelector(selector);
    return node && !node.disabled ? node : null;
  }, 4000);
  const undoToast = () => until(() => all("#toasts .toast.wait").find((node) => text(node).startsWith("Delete")), 15000);
  const phase = "@PHASE@";
  if (phase === "stream") {
    await streamShowsAll();
    const foot = () => document.querySelector("#main details.stale-footer");
    if (!(await until(foot, 8000))) {
      return {error: text(document.getElementById("main")).slice(0, 300)};
    }
    const body = await until(() => document.querySelector('#main .feed > li[data-ref="@LONG@"] .code-body'), 8000);
    if (!body) {
      return {error: "no code box for the long ask"};
    }
    const code = body.querySelector(".command code");
    const scrolls = [body.scrollHeight > body.clientHeight + 1, getComputedStyle(body).overflowY];
    body.scrollTop = body.scrollHeight;
    await sleep(150);
    const entry = body.closest("li");
    const actions = body.closest(".code-box").querySelector(".code-foot").getBoundingClientRect();
    const long = {scrolls, bottom: body.scrollTop + body.clientHeight >= body.scrollHeight - 1, lines: code.textContent.split("\\n").length, last: code.textContent.endsWith("echo line 40"),
      clipped: entry.scrollHeight > entry.clientHeight + 1 && getComputedStyle(entry).overflowY !== "visible", foot: actions.height > 0};
    const feed = all("#main .feed > li").map((li) => li.dataset.item || "");
    const summary = text(foot().querySelector("summary"));
    const closed = !foot().open;
    foot().querySelector("summary").click();
    await until(() => foot().open && all(".stale-list > li", foot()).length, 3000);
    const rows = all(".stale-list > li", foot()).map((li) => [li.dataset.ref, li.dataset.request]).sort();
    foot().querySelector(".triage-all").click();
    const button = await enabled("#main details.stale-footer .triage-delete");
    const label = text(button);
    button.click();
    const toast = await undoToast();
    const hidden = Boolean(await until(() => !foot(), 8000));
    if (toast) {
      toast.querySelector('button[aria-label="Undo"]').click();
    }
    const back = await until(() => foot() && text(foot().querySelector("summary")) === summary, 10000);
    return {long, feed, summary, closed, rows, label, toast: Boolean(toast), hidden, back: Boolean(back), posted, wide: document.documentElement.scrollWidth > innerWidth + 1};
  }
  const chip = (id) => document.querySelector(`#main .triage-bar .chip[data-request="${id}"]`);
  if (!(await until(() => chip("all"), 8000))) {
    return {error: text(document.getElementById("main")).slice(0, 300)};
  }
  const counts = () => Object.fromEntries(all("#main .triage-bar .chip").map((node) => [node.dataset.request, text(node.querySelector(".count"))]));
  const before = counts();
  if (phase === "again") {
    return {before};
  }
  const lists = {};
  for (const id of ["open", "expired", "stale", "failed", "all"]) {
    chip(id).click();
    await until(() => chip(id).getAttribute("aria-pressed") === "true", 3000);
    await sleep(200);
    lists[id] = all("#main .inbox-list > li").map((li) => li.dataset.ref).sort();
  }
  chip("expired").click();
  await until(() => chip("expired").getAttribute("aria-pressed") === "true", 3000);
  document.querySelector("#main .triage-bar .triage-all").click();
  const button = await enabled("#main .triage-bar .triage-delete");
  const label = text(button);
  button.click();
  const toast = await undoToast();
  const gone = Boolean(await until(() => !document.querySelector('#main .inbox-list > li[data-ref="@EXPIRED@"]'), 8000));
  const settled = Boolean(await until(() => !all("#toasts .toast.wait").length, 20000));
  await sleep(1500);
  return {before, lists, label, toast: Boolean(toast), gone, settled, after: counts(), posted, wide: document.documentElement.scrollWidth > innerWidth + 1};
})()"""


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestStaleRequests(HubCase):
    drive = base.OrchestratorE2ECase.drive
    authenticator = base.OrchestratorE2ECase.authenticator

    def setUp(self):
        super().setUp()
        self.claim("s1", "Skills session")
        self.expired = self.create_ask({**ASK, "call_key": signing.call_key("Bash", {"command": ASK["command"]})})
        self.httpd.hub.asks.change(self.expired, {"expires": time.time() - 600})
        self.long = self.create_ask({**ASK, "command": LONG, "timeout": 3600})
        self.review = self.request("feat: stale", "")
        status, _, body = self.post_json("/api/match/stale", {"id": self.review, "tree": "f" * 40}, self.local())
        self.assertEqual(status, 200, body)
        greet = {"title": "echo greet", "workdir": str(self.outside), "description": "greets", "check": "manual", "status": "queued", "roles": {"Operator": "R", "Skills session": "A"}}
        self.write_council({"rasci.json": {"operator/greet": greet}})
        now = time.time()
        fields = {"task": "operator/greet", "command": "echo greet", "directory": str(self.outside), "sha256": "", "status": "failed", "proof": None}
        job = self.httpd.hub.jobs.add({**fields, "code": 2, "output": "boom\n", "created_ts": now - 20, "started": now - 19, "finished": now - 10, "dismissed": False})
        self.run_line = self.httpd.hub.log.add({"kind": "run", "title": "failed: echo greet", "text": "boom", "ref": {"job": job["id"], "task": "operator/greet", "code": 2, "status": "failed"}})["id"]

    def step(self, phase: str, width: int, height: int) -> dict:
        flow = FLOW.replace("@HELPERS@", base.HELPERS).replace("@PHASE@", phase).replace("@LONG@", f"ask:{self.long}").replace("@EXPIRED@", f"ask:{self.expired}")
        screen = "stream" if phase == "stream" else "tasks/operator"
        return {"width": width, "height": height, "url": f"http://localhost:{self.port}/?{phase}-{width}#{screen}", "wait": 1500, "probe": flow, "shot": str(OUT / f"chromium-{width}-{phase}.png")}

    def test_chromium_hides_stale_requests_behind_the_footer_and_deletes_them_by_chip_with_undo(self):
        OUT.mkdir(parents=True, exist_ok=True)
        steps = [self.step("stream", 1366, 768), self.step("tasks", 1366, 768), self.step("again", 390, 844)]
        with mock.patch.object(batches, "UNDO", UNDO):
            data = self.drive(steps, self.authenticator())
        (OUT / "chromium-stale-requests.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "(style-src-elem)" not in error and "/favicon.ico" not in error], [])
        self.assertEqual(len(data["results"]), len(steps), data)
        stream, tasks, again = data["results"]
        for found in data["results"]:
            self.assertNotIn("error", found, found)
        expired, long, review, row = f"ask:{self.expired}", f"ask:{self.long}", f"review:{self.review}", "operator:operator/greet"

        self.assertEqual(stream["long"], {"scrolls": [True, "auto"], "bottom": True, "lines": 40, "last": True, "clipped": False, "foot": True}, stream)
        self.assertEqual([item for item in stream["feed"] if item.endswith((f"/{expired}", f"/{review}"))], [], stream)
        self.assertEqual(len([item for item in stream["feed"] if item.endswith(f"/{row}")]), 1, stream)
        self.assertEqual([item for item in stream["feed"] if item.endswith(f"/{self.run_line}")], [], stream)
        self.assertEqual((stream["summary"], stream["closed"]), ("2 stale requests · 1 expired · 1 stale", True), stream)
        self.assertEqual(stream["rows"], sorted([[expired, "expired"], [review, "stale"]]), stream)
        self.assertEqual((stream["label"], stream["toast"], stream["hidden"], stream["back"], stream["wide"]), ("Delete 2", True, True, True, False), stream)
        self.assertEqual([path for path, _ in stream["posted"]], ["/api/sign", "/api/requests/dismiss"], stream)
        self.assertEqual(sorted(stream["posted"][1][1]), sorted([["dismiss", "ask", self.expired, "expired"], ["dismiss", "review", self.review, "stale"]]), stream)

        self.assertEqual(tasks["before"], {"open": "1", "expired": "1", "stale": "1", "failed": "1", "all": "4"}, tasks)
        self.assertEqual(tasks["lists"], {"open": [long], "expired": [expired], "stale": [review], "failed": [row], "all": sorted([long, expired, review, row])}, tasks)
        self.assertEqual((tasks["label"], tasks["toast"], tasks["gone"], tasks["settled"], tasks["wide"]), ("Delete 1", True, True, True, False), tasks)
        self.assertEqual(tasks["after"], {"open": "1", "expired": "0", "stale": "1", "failed": "1", "all": "3"}, tasks)
        self.assertEqual(tasks["posted"][1], ["/api/requests/dismiss", [["dismiss", "ask", self.expired, "expired"]]], tasks)

        self.assertEqual(again["before"], {"open": "1", "expired": "0", "stale": "1", "failed": "1", "all": "3"}, again)
        snapshot = self.snapshot()
        self.assertNotIn(self.expired, [item["id"] for item in snapshot["lapsed"]])
        self.assertIn(self.long, [item["id"] for item in snapshot["inbox"]])
        self.assertEqual(self.httpd.hub.asks.get(self.expired)["status"], "pending")
        self.assertEqual([args for script, args in self.scripts.calls if script == skill_scripts.RADIO], [])


if __name__ == "__main__":
    unittest.main()
