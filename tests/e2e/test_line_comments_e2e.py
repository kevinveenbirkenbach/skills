from __future__ import annotations

import html
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
from kvb_orchestrator import batches, skill_scripts

COMMAND = "git commit -m 'line comments'"
TITLE = "feat: overlay comments"
DIFF = [{"path": "a.txt", "status": "M", "mode": "100644", "additions": 2, "deletions": 1, "patch": "@@ -1,2 +1,3 @@\n keep\n-old\n+new\n+more", "note": ""}]
FILES = ("src/app.py", "src/view.js")
CAPTURE = """
  navigator.credentials.get = @SIGNS@ ? navigator.credentials.get.bind(navigator.credentials) : () => Promise.reject(new DOMException("The operator canceled.", "NotAllowedError"));
  const posted = [];
  const send = window.fetch.bind(window);
  window.fetch = (path, init) => {
    if (["/api/sign", "/api/inbox/approve", "/api/messages/sign", "/api/messages"].includes(String(path))) {
      const body = JSON.parse(init.body);
      posted.push([String(path), body.text || null, (body.items || []).map((entry) => [entry.kind, entry.verb, entry.channel || "", entry.reason || ""])]);
    }
    return send(path, init);
  };
  const rightClick = async (cell) => {
    const box = cell.getBoundingClientRect();
    cell.dispatchEvent(new MouseEvent("contextmenu", {bubbles: true, cancelable: true, clientX: box.left + 4, clientY: box.top + 4}));
    await sleep(200);
    const first = document.querySelector('.ctx-menu:not([hidden]) [role="menuitem"]');
    const label = first ? text(first.querySelector(".ctx-label")) : null;
    if (first) {
      first.click();
    }
    return label;
  };
  const listed = (root) => (root ? all(".feedback-list li.line-mark", root).map(text) : null);
"""
STREAM = """(async () => {@HELPERS@@UNLABELLED@@CAPTURE@
  const rowOf = () => all("#main .feed > li.k-ask").find((li) => li.textContent.includes(@COMMAND@) && li.querySelector("tr[data-line]"));
  if (!(await until(rowOf, 10000))) {
    return {error: text(document.getElementById("main"))};
  }
  const item = await rightClick(all("tr[data-line]", rowOf())[1].querySelector("td.code"));
  const field = await until(() => document.querySelector(".sheet-box textarea"), 4000);
  if (!field) {
    return {error: "no comment sheet", item};
  }
  const sheet = {title: text(document.querySelector(".sheet-head .panel-title")), range: text(document.querySelector(".sheet-box .who code")), unlabelled: unlabelled(document.querySelector("#sheet .sheet-box"))};
  field.value = "stream note";
  all(".sheet-box button").find((button) => name(button) === "Save comment").click();
  await until(() => rowOf() && rowOf().querySelector("tr.match-mark"), 4000);
  const marked = {rows: all("tr.marked", rowOf()).map((row) => row.dataset.line), notes: all("tr.match-mark", rowOf()).map(text), list: listed(rowOf()), open: !document.getElementById("sheet").hidden};
  all(".deny-split button", rowOf()).find((button) => name(button) === "Deny").click();
  const reason = await until(() => document.querySelector(".sheet-box .deny-reason textarea"), 4000);
  const deny = {reason: reason ? reason.value : null, channel: (document.querySelector(".sheet-box .deny-channels input:checked") || {}).value || null, to: (document.querySelector(".sheet-box .deny-recipient select") || {}).value || null};
  all(".sheet-box .actions button").find((button) => text(button) === "Deny").click();
  await until(() => posted.some(([path]) => path === (@SIGNS@ ? "/api/inbox/approve" : "/api/sign")), 8000);
  await sleep(1200);
  return {item, sheet, marked, deny, posted, kept: listed(rowOf()), wide: document.documentElement.scrollWidth > innerWidth + 1};
})()"""
OVERLAY = """(async () => {@HELPERS@@UNLABELLED@@CAPTURE@
  const row = () => document.querySelector('#main .inbox-list > li[data-ref="@REVIEW@"]');
  if (!(await until(row, 8000))) {
    return {error: text(document.getElementById("main"))};
  }
  row().querySelector(".headline").click();
  const lines = () => all("#sheet .review-file[data-path='src/app.py'] tr[data-line]");
  if (!(await until(() => lines().length, 8000))) {
    return {error: text(document.getElementById("sheet"))};
  }
  const target = lines()[2];
  const item = await rightClick(target.querySelector("td.code"));
  const field = await until(() => document.querySelector("#sheet tr.match-comment textarea"), 4000);
  if (!field) {
    return {error: "no inline comment field", item};
  }
  const inline = {after: field.closest("tr").previousElementSibling === target, unlabelled: unlabelled(field.closest("tr"))};
  field.value = "overlay note";
  all("#sheet tr.match-comment button").find((button) => name(button) === "Save comment").click();
  await until(() => document.querySelector("#sheet tr.match-mark"), 4000);
  const marked = {rows: all("#sheet tr.marked").map((tr) => tr.dataset.line), notes: all("#sheet tr.match-mark").map(text), list: all("#sheet .review-notes li.line-mark").map(text), field: Boolean(document.querySelector("#sheet tr.match-comment")), open: !document.getElementById("sheet").hidden};
  document.body.dispatchEvent(new KeyboardEvent("keydown", {key: "Escape", bubbles: true}));
  await until(() => document.getElementById("sheet").hidden, 4000);
  const card = listed(row());
  row().querySelector(".item-actions button.primary").click();
  await until(() => posted.some(([path]) => path === (@SIGNS@ ? "/api/messages" : "/api/sign")), 10000);
  await sleep(1200);
  return {item, inline, marked, card, posted, kept: listed(row()), wide: document.documentElement.scrollWidth > innerWidth + 1};
})()"""


def review_page() -> str:
    sections = []
    for path in FILES:
        rows = "".join(f'<tr class="add"><td class="num"></td><td class="num">{line}</td><td class="sign">+</td><td class="code">{html.escape(path)} line {line}</td></tr>' for line in range(1, 6))
        sections.append(f'<details class="file" data-path="{path}"><summary><span class="badge added" title="added">A</span><span class="path">{path}</span>'
                        f'<span class="stat"><span class="add">+5</span><span class="del">&minus;0</span></span></summary><table class="diff"><tbody>{rows}</tbody></table></details>')
    return f'<!DOCTYPE html><html><body><section class="group" id="staged" data-files="2">{"".join(sections)}</section></body></html>'


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestLineComments(base.OrchestratorE2ECase):
    def setUp(self):
        super().setUp()
        self.ask = self.create_ask({**ASK, "command": COMMAND, "timeout": 3600, "diff": DIFF})
        arguments = {**self.arguments(TITLE, "", self.page("overlay.html", review_page())), "worktree": "/repo/.worktrees/feature/overlay", "branch": "feature/overlay", "agent": "Skills session"}
        result = self.tool("review_request", arguments)
        self.assertFalse(result["isError"], result)
        self.review = result["structuredContent"]["id"]

    def probe(self, template: str, signs: bool) -> str:
        values = {"@HELPERS@": base.HELPERS, "@UNLABELLED@": base.UNLABELLED, "@CAPTURE@": CAPTURE, "@SIGNS@": "true" if signs else "false", "@COMMAND@": json.dumps(COMMAND), "@REVIEW@": f"review:{self.review}"}
        for key, value in values.items():
            template = template.replace(key, value)
        return template

    def steps(self, browser: str, signs: bool) -> list[dict]:
        local = f"http://localhost:{self.port}/"
        return [
            {"width": 1366, "height": 768, "url": f"{local}?stream#stream", "wait": 1500, "probe": self.probe(STREAM, signs), "shot": self.shot(f"{browser}-1366-line-comments-stream")},
            {"width": 1366, "height": 768, "url": f"{local}?overlay#stream/inbox", "wait": 1200, "probe": self.probe(OVERLAY, signs), "shot": self.shot(f"{browser}-1366-line-comments-overlay")},
        ]

    def check(self, data: dict, signs: bool) -> None:
        self.assertEqual([error for error in data["errors"] if "(style-src-elem)" not in error and "/favicon.ico" not in error], [])
        stream, overlay = data["results"]
        self.assertNotIn("error", stream, stream)
        self.assertEqual((stream["item"], stream["sheet"]), ("Comment", {"title": "Comment", "range": "a.txt:2", "unlabelled": []}))
        self.assertEqual(stream["marked"], {"rows": ["2", "2"], "notes": ["stream note"], "list": ["a.txt:2stream note"], "open": False})
        self.assertEqual(stream["deny"], {"reason": "a.txt:2: stream note", "channel": "call", "to": "Skills"})
        denial = [["ask", "reject", "call", "a.txt:2: stream note"]]
        self.assertEqual(stream["posted"], [["/api/sign", None, denial], *([["/api/inbox/approve", None, denial]] if signs else [])])
        self.assertNotIn("error", overlay, overlay)
        self.assertEqual((overlay["item"], overlay["inline"]), ("Comment", {"after": True, "unlabelled": []}))
        self.assertEqual(overlay["marked"], {"rows": ["3"], "notes": ["overlay note"], "list": ["src/app.py:3overlay note"], "field": False, "open": True})
        self.assertEqual(overlay["card"], ["src/app.py:3overlay note"])
        grant = [["review", "approve", "", ""]]
        notes = f"Granted: {TITLE}. Notes:\nsrc/app.py:3: overlay note"
        self.assertEqual(overlay["posted"], [["/api/sign", None, grant], ["/api/inbox/approve", None, grant], ["/api/messages/sign", notes, []], ["/api/messages", notes, []]] if signs else [["/api/sign", None, grant]])
        if not signs:
            self.assertEqual((stream["kept"], overlay["kept"]), (["a.txt:2stream note"], ["src/app.py:3overlay note"]))
        self.assertFalse(stream["wide"] or overlay["wide"])

    def test_chromium_line_comments_reach_the_requester_in_the_deny_call_and_after_the_grant_as_one_post(self):
        with mock.patch.object(batches, "UNDO", 0.3):
            data = self.drive(self.steps("chromium", True), self.authenticator())
            self.settle(lambda: self.status(self.review) == "approved" and any(ask["status"] == "denied" for ask in self.httpd.hub.asks.listed() if ask["command"] == COMMAND))
        (base.OUT / "chromium-line-comments.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.check(data, True)
        asks = [(ask["status"], ask.get("channel", ""), ask.get("reason", "")) for ask in self.httpd.hub.asks.listed() if ask["command"] == COMMAND]
        self.assertEqual(asks, [("denied", "call", "a.txt:2: stream note")])
        radio = [" ".join(args) for script, args in self.scripts.calls if script == skill_scripts.RADIO]
        self.assertEqual(len([entry for entry in radio if entry.startswith("post --to ") and f"Granted: {TITLE}. Notes:" in entry and "src/app.py:3: overlay note" in entry]), 1, radio)

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_keeps_line_comments_when_the_deny_and_the_grant_go_unsigned(self):
        data = self.drive(self.steps("firefox", False), None, "bidi.mjs", os.environ.get("FIREFOX", "firefox"))
        (base.OUT / "firefox-line-comments.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.check(data, False)
        self.assertEqual(self.status(self.review), "pending")


if __name__ == "__main__":
    unittest.main()
