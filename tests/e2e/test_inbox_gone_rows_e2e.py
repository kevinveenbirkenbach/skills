from __future__ import annotations

import os
import shutil
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

import test_orchestrator_e2e as base
from hub_case import HubCase

OUT = Path(os.environ.get("E2E_OUT", "/tmp/inbox-gone-rows-shots"))
WIDTHS = ((1920, 1080), (390, 844))
GONE = "git merge --no-ff --no-verify -F msg"
NOTICE = "already done or removed elsewhere"
FILL = {"workdir": "/repo", "check": "manual", "status": "queued", "roles": {"Operator": "R", "Store": "A"}}
SHOWN = {
    "operator/gui-agentbox-merge-push": {**FILL, "title": GONE, "description": "merge the agentbox", "seq": 1},
    "operator/later": {**FILL, "title": "echo later", "description": "removed while the page shows it", "seq": 2},
    "operator/kept": {**FILL, "title": "echo kept", "description": "changed while the page shows it", "seq": 3},
}
LEFT = {"operator/kept": {**SHOWN["operator/kept"], "title": "echo kept changed"}}
HOLD = """() => {
  const send = window.fetch.bind(window);
  const held = [];
  let holding = true;
  window.__release = () => {
    holding = false;
    held.splice(0).forEach((go) => go());
  };
  window.fetch = (path, init) => (holding && String(path).startsWith("/api/state") ? new Promise((resolve, reject) => held.push(() => send(path, init).then(resolve, reject))) : send(path, init));
}"""
CLICK = """
  const click = async (words) => {
    const row = rowOf(words);
    if (!row) {
      return {error: text(document.getElementById("main"))};
    }
    const shown = new Set(all("#toasts .toast"));
    press(row, "Run");
    const toast = await until(() => all("#toasts .toast").find((box) => !shown.has(box)), 8000);
    await sleep(300);
    return {toast: text(toast && toast.querySelector("strong")), lines: text(toast && toast.querySelector("pre")), bad: toast ? toast.classList.contains("bad") : null, open: Boolean(rowOf(words)), wide: wide()};
  };
"""
BEFORE = """(async () => {@HELPERS@@LABELS@
  window.__page = "same page";
  await until(() => all("#main .inbox-list > li").length === 3, 8000);
  return {rows: all("#main .inbox-list > li .command code").map(text), wide: wide()};
})()"""
RUN_GONE = """(async () => {@HELPERS@@LABELS@@CLICK@
  return click("git merge");
})()"""
RUN_KEPT = """(async () => {@HELPERS@@LABELS@@CLICK@
  return click("echo kept");
})()"""
REFRESH = """(async () => {@HELPERS@@LABELS@
  window.__release();
  window.dispatchEvent(new Event("focus"));
  const settled = await until(() => !rowOf("echo later") && rowOf("echo kept changed"), 15000);
  return {settled: Boolean(settled), samePage: window.__page === "same page", rows: all("#main .inbox-list > li .command code").map(text)};
})()"""


def probe(template: str) -> str:
    return template.replace("@CLICK@", CLICK).replace("@HELPERS@", base.HELPERS).replace("@LABELS@", base.LABELS)


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestInboxGoneRows(HubCase):
    drive = base.TestOrchestratorE2E.drive

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        self.write_tree()
        hub = self.httpd.hub
        real = hub.render

        def render(nonce: str) -> tuple[str, str]:
            self.write_council({"rasci.json": SHOWN})
            page = real(nonce)
            self.write_council({"rasci.json": LEFT})
            return page

        patch = mock.patch.object(hub, "render", render)
        patch.start()
        self.addCleanup(patch.stop)

    def steps(self, browser: str) -> list[dict]:
        steps = []
        for width, height in WIDTHS:
            shot = OUT / f"{browser}-{width}"
            url = f"http://localhost:{self.port}/?{width}#stream/inbox"
            steps += [
                {"width": width, "height": height, "url": url, "wait": 1200, "probe": probe(BEFORE), "shot": f"{shot}-1-stale-row.png"},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(RUN_GONE), "shot": f"{shot}-2-run-removed-row.png"},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(RUN_KEPT), "shot": f"{shot}-3-run-changed-row.png"},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(REFRESH), "shot": f"{shot}-4-refreshed.png"},
            ]
        return steps

    def check(self, browser: str, driver: str, binary: str) -> None:
        data = self.drive(self.steps(browser), None, driver, binary, HOLD)
        self.assertEqual([error for error in data["errors"] if "(style-src-elem)" not in error and "/favicon.ico" not in error], [])
        results = iter(data["results"])
        for width, _ in WIDTHS:
            before, gone, kept, refreshed = next(results), next(results), next(results), next(results)
            with self.subTest(browser=browser, width=width, part="the page draws the rows it was rendered with"):
                self.assertEqual((sorted(before["rows"]), before["wide"]), (sorted([GONE, "echo later", "echo kept"]), False), before)
            with self.subTest(browser=browser, width=width, part="a run the hub answers 404 for closes the card at once with a notice"):
                self.assertNotIn("error", gone, gone)
                self.assertEqual((gone["toast"], gone["lines"], gone["bad"]), (f"Run: {GONE}: {NOTICE}", None, False), gone)
                self.assertEqual((gone["open"], gone["wide"]), (False, False), gone)
            with self.subTest(browser=browser, width=width, part="a present row whose run fails otherwise stays with its error"):
                self.assertNotIn("error", kept, kept)
                self.assertEqual((kept["toast"], kept["lines"], kept["bad"], kept["open"]), ("Run: echo kept: not possible", '409 {"id": "operator/kept", "status": "changed"}', True, True), kept)
            with self.subTest(browser=browser, width=width, part="the next refresh drops every row the hub no longer returns, without a reload"):
                self.assertEqual((refreshed["settled"], refreshed["samePage"], refreshed["rows"]), (True, True, ["echo kept changed"]), refreshed)

    def test_chromium_closes_removed_rows_and_keeps_failed_ones_at_1920_and_390(self):
        self.check("chromium", "cdp.mjs", os.environ.get("CHROMIUM", "chromium"))

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_closes_removed_rows_and_keeps_failed_ones_at_1920_and_390(self):
        self.check("firefox", "bidi.mjs", os.environ.get("FIREFOX", "firefox"))


if __name__ == "__main__":
    unittest.main()
