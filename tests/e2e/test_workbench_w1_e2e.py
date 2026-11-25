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
from hub_case import HubCase
from hub_support import ASK, PAGE
from kvb_orchestrator import batches, skill_scripts

OUT = Path(os.environ.get("E2E_OUT", "/tmp/workbench-w1-shots"))
WITHHELD = "content withheld"
DIFF = [
    {"path": "src/app.py", "status": "M", "mode": "100644", "additions": 2, "deletions": 1, "patch": "@@ -1,3 +1,4 @@\n keep = 1\n-old = 2\n+new = 3\n+more = 4\n tail = 4", "note": ""},
    {"path": "logo.png", "status": "B", "mode": "100644", "additions": 0, "deletions": 0, "patch": "", "note": ""},
    {"path": "big.txt", "status": "M", "mode": "100644", "additions": 401, "deletions": 0, "patch": "@@ -0,0 +1,401 @@\n" + "\n".join(f"+line {n}" for n in range(401)), "note": ""},
    {"path": "key.txt", "status": "A", "mode": "100755", "additions": 3, "deletions": 0, "patch": "", "note": WITHHELD},
]
OPERATOR = """(async () => {@HELPERS@@UNLABELLED@
  navigator.credentials.get = @SIGNS@ ? navigator.credentials.get.bind(navigator.credentials) : () => Promise.reject(new DOMException("The operator canceled.", "NotAllowedError"));
  window.e2ePosted = [];
  const send = window.fetch.bind(window);
  window.fetch = (path, init) => {
    if (String(path).startsWith("/api/") && init && init.method === "POST") {
      window.e2ePosted.push([String(path), JSON.parse(init.body)]);
    }
    return send(path, init);
  };
  const list = await until(() => location.hash === "#tasks/operator" && document.querySelector("#main .inbox-list") && document.querySelector("#main .diff-file"), 10000);
  if (!list) {
    return {error: text(document.getElementById("main")), hash: location.hash};
  }
  const mine = (words) => all("#main .inbox-list > li").find((li) => li.textContent.includes(words));
  const cards = ["@TAG@ review", "@TAG@ ship", "@TAG@ commit"].map(mine);
  const tasks = document.getElementById("tab-tasks");
  const badge = tasks.querySelector(".badge");
  const review = cards[0];
  const files = all(".diff-file", review).map((file) => ({
    path: file.dataset.path, status: file.dataset.status, open: file.querySelector("details") ? file.querySelector("details").open : null,
    rows: all("tr.add, tr.del", file).length, note: all(".note", file).map(text), mode: all(".mode", file).map(text),
    colours: [...new Set(all("tr.add, tr.del", file).map((row) => getComputedStyle(row).backgroundColor))].length,
  }));
  const operator = cards[1];
  const found = {
    hash: location.hash, tabs: all("#tabs > .tab-group > button").map(name), subs: all("#tabs .subtabs button").map(name),
    badge: badge && !badge.hidden ? text(badge) : null, current: all("#tabs button[aria-current=page]").map(name), streamInbox: Boolean(document.getElementById("tab-inbox")),
    kinds: cards.map((card) => (card ? card.className.split(" ").filter((name) => name.startsWith("k-")).join("") : null)),
    boxes: cards.map((card) => Boolean(card && card.querySelector('input[type="checkbox"]'))),
    operator: operator ? {command: text(operator.querySelector(".command code")), place: operator.querySelector(".command").dataset.path, text: text(operator), buttons: all("button", operator).map(name)} : null,
    files, wide: document.documentElement.scrollWidth > window.innerWidth + 1,
  };
  ["@TAG@ review", "@TAG@ ship", "@TAG@ commit"].forEach((words) => mine(words).querySelector('input[type="checkbox"]').click());
  await sleep(300);
  found.unlabelled = {main: unlabelled(document.getElementById("main"))};
  const grant = all("#grant-bar .grant-split button").find((button) => name(button).startsWith("Grant selection"));
  found.grant = name(grant);
  grant.click();
  await until(() => document.querySelector(".sheet-box .actions"), 4000);
  const granting = document.querySelector("#sheet .sheet-box");
  found.unlabelled.sheet = granting ? unlabelled(granting) : null;
  const confirm = all(".sheet-box .actions button").find((button) => text(button).startsWith("Grant "));
  found.confirm = text(confirm);
  found.listed = all(".sheet-box ul.mini > li").length;
  confirm.click();
  await until(() => window.e2ePosted.some(([path]) => path === "/api/sign"), 8000);
  await sleep(800);
  found.posted = window.e2ePosted.filter(([path]) => ["/api/sign", "/api/inbox/approve"].includes(path)).map(([path, body]) => [path, body.items.map((item) => item.kind).sort()]);
  return found;
})()"""
FEEDBACK = """(async () => {@HELPERS@@UNLABELLED@
  const mine = (words) => all("#main .inbox-list > li").find((li) => li.textContent.includes(words));
  const card = await until(() => all("#main .inbox-list > li").find((li) => li.textContent.includes("@TAG@ second") && li.querySelector(".diff-file tr.add")), 10000);
  if (!card) {
    return {error: text(document.getElementById("main"))};
  }
  const select = (from, to) => {
    const range = document.createRange();
    range.setStart(from, 0);
    range.setEnd(to, to.childNodes.length);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    return range.getBoundingClientRect();
  };
  window.e2eFeedback = [];
  const send = window.fetch.bind(window);
  window.fetch = (path, init) => {
    if (String(path).startsWith("/api/") && init && init.method === "POST" && !String(path).startsWith("/api/inbox/undo")) {
      const body = JSON.parse(init.body);
      window.e2eFeedback.push([String(path), body.text || null, (body.items || []).map((entry) => [entry.kind, entry.verb, entry.channel || "", entry.reason || ""])]);
    }
    return send(path, init);
  };
  navigator.credentials.get = @SIGNS@ ? navigator.credentials.get.bind(navigator.credentials) : () => Promise.reject(new DOMException("The operator canceled.", "NotAllowedError"));
  const rows = all(".diff-file[data-path='src/app.py'] tr[data-line]", card);
  const box = select(rows[1].querySelector("td.code"), rows[2].querySelector("td.code"));
  await sleep(300);
  const floating = document.querySelector(".feedback-float");
  const nearby = Boolean(floating && !floating.hidden);
  rows[1].querySelector("td.code").dispatchEvent(new MouseEvent("contextmenu", {bubbles: true, cancelable: true, clientX: box.left + 4, clientY: box.top + 4}));
  await sleep(200);
  const context = document.querySelector(".ctx-menu:not([hidden])");
  const menu = context && context.getAttribute("role");
  const labels = {float: floating ? unlabelled(floating) : null, menu: context ? unlabelled(context) : null};
  const first = context && context.querySelector('[role="menuitem"]');
  const item = first ? text(first.querySelector(".ctx-label")) : null;
  first.click();
  const sheet = await until(() => document.querySelector(".sheet-box textarea"), 4000);
  const writing = document.querySelector("#sheet .sheet-box");
  labels.sheet = writing ? unlabelled(writing) : null;
  const title = text(document.querySelector(".sheet-head .panel-title"));
  const range = text(document.querySelector(".sheet-box .who code"));
  sheet.value = "right-click note";
  all(".sheet-box button").find((button) => name(button) === "Save comment").click();
  const fresh = () => mine("@TAG@ second");
  await until(() => fresh() && fresh().querySelector("tr.match-mark"), 4000);
  const marked = {
    rows: all("tr.marked", fresh()).map((row) => row.dataset.line),
    notes: all("tr.match-mark", fresh()).map(text),
    list: all(".feedback-list li.line-mark", fresh()).map(text),
    open: !document.getElementById("sheet").hidden,
  };
  const ask = () => mine("@TAG@ keyed");
  const code = ask().querySelector(".command code");
  select(code, code);
  document.body.dispatchEvent(new KeyboardEvent("keydown", {key: "f", bubbles: true, cancelable: true}));
  const keyed = await until(() => document.querySelector(".sheet-box textarea"), 4000);
  const keyRange = text(document.querySelector(".sheet-box .who code"));
  keyed.value = "key f note";
  all(".sheet-box button").find((button) => name(button) === "Save comment").click();
  const askList = await until(() => ask() && all(".feedback-list li.line-mark", ask()).map(text).join("|"), 4000);
  const before = window.e2eFeedback.length;
  all(".deny-split button", ask()).find((button) => name(button) === "Deny").click();
  const reason = await until(() => document.querySelector(".sheet-box .deny-reason textarea"), 4000);
  const deny = {reason: reason ? reason.value : null, channel: (document.querySelector(".sheet-box .deny-channels input:checked") || {}).value || null, to: (document.querySelector(".sheet-box .deny-recipient select") || {}).value || null};
  all(".sheet-box .actions button").find((button) => text(button) === "Deny").click();
  await until(() => window.e2eFeedback.length > before && (!@SIGNS@ || window.e2eFeedback.some(([path]) => path === "/api/inbox/approve")), 8000);
  await sleep(1200);
  all(".item-actions button", fresh()).find((button) => name(button) === "Grant").click();
  await until(() => window.e2eFeedback.some(([path]) => path === (@SIGNS@ ? "/api/messages" : "/api/sign")) && window.e2eFeedback.filter(([path]) => path === "/api/sign").length >= 2, 10000);
  await sleep(1500);
  const kept = {review: fresh() ? all(".feedback-list li.line-mark", fresh()).map(text) : null, ask: ask() ? all(".feedback-list li.line-mark", ask()).map(text) : null};
  return {nearby, menu, item, title, range, keyRange, labels, marked, askList, deny, kept, posted: window.e2eFeedback, wide: document.documentElement.scrollWidth > window.innerWidth + 1};
})()"""


def probe(template: str, tag: str, signs: bool) -> str:
    return template.replace("@HELPERS@", base.HELPERS).replace("@UNLABELLED@", base.UNLABELLED).replace("@TAG@", tag).replace("@SIGNS@", "true" if signs else "false")


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestWorkbenchOperatorTasks(HubCase):
    drive = base.OrchestratorE2ECase.drive
    authenticator = base.OrchestratorE2ECase.authenticator

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        self.claim("s2", "Skills")
        rows = {}
        self.reviews = {}
        for width, _ in base.WIDTHS:
            tag = f"w{width}"
            for word in ("review", "second"):
                arguments = {**self.arguments(f"feat: {tag} {word}", "", self.page(f"{tag}-{word}.html", PAGE)), **self.branched(f"feature/{tag}-{word}"), "agent": "Skills", "diff": DIFF}
                result = self.tool("review_request", arguments)
                self.assertFalse(result["isError"], result)
                self.reviews[(tag, word)] = result["structuredContent"]["id"]
            for word in ("commit", "keyed"):
                status, _, body = self.post_json("/api/asks", {**ASK, "command": f"git commit -m '{tag} {word}'", "session": "s2", "diff": DIFF}, self.local())
                self.assertEqual(status, 201, body)
            rows[f"operator/{tag}"] = {"title": f"make {tag} ship", "workdir": "/repo", "description": f"{tag} ship the build", "check": "manual", "status": "queued", "roles": {"Skills": "A"}}
        self.write_council({"rasci.json": rows})
        self.base = f"http://localhost:{self.port}/"

    def steps(self, browser: str, signs: bool) -> list[dict]:
        steps = []
        for width, height in base.WIDTHS:
            tag = f"w{width}"
            shot = str(OUT / f"{browser}-{width}-operator")
            steps.append({"width": width, "height": height, "url": f"{self.base}?{width}#stream/inbox", "wait": 1200, "probe": probe(OPERATOR, tag, signs), "shot": f"{shot}-tasks.png"})
            steps.append({"width": width, "height": height, "url": None, "wait": 0, "probe": probe(FEEDBACK, tag, signs), "shot": f"{shot}-feedback.png"})
        return steps

    def check(self, data: dict, browser: str, signs: bool) -> None:
        results = iter(data["results"])
        for width, _ in base.WIDTHS:
            tag = f"w{width}"
            tasks, feedback = next(results), next(results)
            with self.subTest(browser=browser, width=width, part="unlabelled controls"):
                self.assertNotIn("error", tasks, tasks)
                self.assertNotIn("error", feedback, feedback)
                self.assertEqual(tasks["unlabelled"], {"main": [], "sheet": []})
                self.assertEqual(feedback["labels"], {"float": [], "menu": [], "sheet": []})
            with self.subTest(browser=browser, width=width):
                self.assertNotIn("error", tasks, tasks)
                self.assertEqual((tasks["hash"], tasks["tabs"], tasks["subs"], tasks["streamInbox"], tasks["current"]), ("#tasks/operator", base.TABS, ["Controls"], False, ["Tasks"]))
                self.assertRegex(tasks["badge"] or "", r"^[1-9][0-9]*$")
                self.assertEqual((tasks["kinds"], tasks["boxes"]), (["k-review", "k-operator", "k-ask"], [True, True, True]))
                operator = tasks["operator"]
                self.assertEqual((operator["command"], operator["place"]), (f"make {tag} ship", "/repo"))
                self.assertIn(f"{tag} ship the build", operator["text"])
                for label in ("Run", "Deny", "Copy", "1 h", "tomorrow", "pin"):
                    self.assertIn(label, operator["buttons"])
                self.assertEqual([(entry["path"], entry["status"], entry["open"]) for entry in tasks["files"]], [("src/app.py", "M", True), ("logo.png", "B", None), ("big.txt", "M", False), ("key.txt", "A", None)])
                self.assertEqual((tasks["files"][0]["rows"], tasks["files"][0]["note"], tasks["files"][0]["colours"]), (3, [], 2))
                self.assertEqual((tasks["files"][3]["note"], tasks["files"][3]["mode"]), ([WITHHELD], ["100755"]))
                self.assertEqual((tasks["grant"], tasks["confirm"], tasks["listed"]), ("Grant selection (3)", "Grant 3", 3))
                kinds = ["ask", "operator", "review"]
                self.assertEqual(tasks["posted"], [["/api/sign", kinds], *([["/api/inbox/approve", kinds]] if signs else [])])
                self.assertFalse(tasks["wide"])
                self.assertNotIn("error", feedback, feedback)
                self.assertEqual((feedback["nearby"], feedback["menu"], feedback["item"], feedback["title"]), (True, "menu", "Comment", "Comment"))
                self.assertEqual((feedback["range"], feedback["keyRange"]), ("src/app.py:2", "/repo:1"))
                self.assertEqual(feedback["marked"], {"rows": ["2", "2"], "notes": ["right-click note"], "list": ["src/app.py:2right-click note"], "open": False})
                self.assertEqual(feedback["askList"], "/repo:1key f note")
                self.assertEqual(feedback["deny"], {"reason": "/repo:1: key f note", "channel": "call", "to": "Skills"})
                denial = [["ask", "reject", "call", "/repo:1: key f note"]]
                grant = [["review", "approve", "", ""]]
                notes = f"Granted: feat: {tag} second. Notes:\nsrc/app.py:2: right-click note"
                expected = [["/api/sign", None, denial], ["/api/inbox/approve", None, denial], ["/api/sign", None, grant], ["/api/inbox/approve", None, grant], ["/api/messages/sign", notes, []], ["/api/messages", notes, []]]
                self.assertEqual(feedback["posted"], expected if signs else [["/api/sign", None, denial], ["/api/sign", None, grant]])
                if not signs:
                    self.assertEqual(feedback["kept"], {"review": ["src/app.py:2right-click note"], "ask": ["/repo:1key f note"]})
                self.assertFalse(feedback["wide"])
        radio = [" ".join(args) for script, args in self.scripts.calls if script == skill_scripts.RADIO]
        granted = [entry for entry in radio if entry.startswith("send post --to Skills ") and "Granted: feat: w" in entry and "Notes:" in entry and "right-click note" in entry]
        self.assertEqual(len(granted), len(base.WIDTHS) if signs else 0, radio)
        asks = {ask["command"]: (ask["status"], ask.get("channel", ""), ask.get("reason", "")) for ask in self.httpd.hub.asks.listed() if "keyed" in ask["command"]}
        self.assertEqual(asks, {f"git commit -m 'w{width} keyed'": ("denied", "call", "/repo:1: key f note") if signs else ("pending", "", "") for width, _ in base.WIDTHS})

    def test_chromium_shows_operator_tasks_with_a_badge_diffs_bulk_grants_and_line_comments_in_the_deny_call_and_grant_post_at_three_widths(self):
        with mock.patch.object(batches, "UNDO", 0.3):
            data = self.drive(self.steps("chromium", True), self.authenticator())
            self.settle(lambda: all(ask["status"] == "denied" for ask in self.httpd.hub.asks.listed() if "keyed" in ask["command"]))
        (OUT / "chromium-operator.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        self.check(data, "chromium", True)

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_shows_operator_tasks_with_a_badge_diffs_and_keeps_line_comments_without_signing_at_three_widths(self):
        data = self.drive(self.steps("firefox", False), None, "bidi.mjs", os.environ.get("FIREFOX", "firefox"))
        (OUT / "firefox-operator.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        self.check(data, "firefox", False)


if __name__ == "__main__":
    unittest.main()
