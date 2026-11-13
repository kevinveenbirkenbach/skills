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

import test_orchestrator_e2e as base
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
OPERATOR = """(async () => {@HELPERS@
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
  const grant = all("#main .inbox-actions button").find((button) => name(button).startsWith("Grant selection"));
  found.grant = name(grant);
  grant.click();
  await until(() => document.querySelector(".sheet-box .actions"), 4000);
  const confirm = all(".sheet-box .actions button").find((button) => text(button).startsWith("Grant "));
  found.confirm = text(confirm);
  found.listed = all(".sheet-box ul.mini > li").length;
  confirm.click();
  await until(() => window.e2ePosted.some(([path]) => path === "/api/sign"), 8000);
  await sleep(800);
  found.posted = window.e2ePosted.filter(([path]) => ["/api/sign", "/api/inbox/approve"].includes(path)).map(([path, body]) => [path, body.items.map((item) => item.kind).sort()]);
  return found;
})()"""
FEEDBACK = """(async () => {@HELPERS@
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
    if (String(path).startsWith("/api/messages")) {
      window.e2eFeedback.push([String(path), JSON.parse(init.body).text]);
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
  const menu = floating && floating.getAttribute("role");
  floating.querySelector("button").click();
  const sheet = await until(() => document.querySelector(".sheet-box textarea"), 4000);
  const title = text(document.querySelector(".sheet-head .panel-title"));
  const range = text(document.querySelector(".sheet-box .who code"));
  sheet.value = "right-click note";
  all(".sheet-box button").find((button) => name(button) === "Send feedback").click();
  await until(() => window.e2eFeedback.length >= (@SIGNS@ ? 2 : 1), 8000);
  await sleep(600);
  const fresh = () => all("#main .inbox-list > li").find((li) => li.textContent.includes("@TAG@ second"));
  const shown = @SIGNS@ ? await until(() => fresh() && all(".feedback-list li", fresh()).map(text).find((entry) => entry.includes("right-click note")), 15000) : null;
  const close = document.querySelector(".sheet-head button");
  if (close) {
    close.click();
  }
  const ask = all("#main .inbox-list > li").find((li) => li.textContent.includes("@TAG@ keyed"));
  const code = ask.querySelector(".command code");
  select(code, code);
  document.body.dispatchEvent(new KeyboardEvent("keydown", {key: "f", bubbles: true, cancelable: true}));
  const keyed = await until(() => document.querySelector(".sheet-box textarea"), 4000);
  const keyRange = text(document.querySelector(".sheet-box .who code"));
  keyed.value = "key f note";
  all(".sheet-box button").find((button) => name(button) === "Send feedback").click();
  await sleep(1500);
  return {nearby, menu, title, range, keyRange, shown: shown || "", posted: window.e2eFeedback, wide: document.documentElement.scrollWidth > window.innerWidth + 1};
})()"""


def probe(template: str, tag: str, signs: bool) -> str:
    return template.replace("@HELPERS@", base.HELPERS).replace("@TAG@", tag).replace("@SIGNS@", "true" if signs else "false")


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestWorkbenchOperatorTasks(HubCase):
    drive = base.TestOrchestratorE2E.drive
    authenticator = base.TestOrchestratorE2E.authenticator

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        self.claim("s2", "Skills")
        rows = {}
        self.reviews = {}
        for width, _ in base.WIDTHS:
            tag = f"w{width}"
            for word in ("review", "second"):
                arguments = {**self.arguments(f"feat: {tag} {word}", "", self.page(f"{tag}-{word}.html", PAGE)), "agent": "Skills", "diff": DIFF}
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
            with self.subTest(browser=browser, width=width):
                self.assertNotIn("error", tasks, tasks)
                self.assertEqual((tasks["hash"], tasks["tabs"], tasks["subs"], tasks["streamInbox"], tasks["current"]), ("#tasks/operator", base.TABS, ["Firewall"], False, ["Tasks"]))
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
                self.assertEqual((feedback["nearby"], feedback["menu"], feedback["title"]), (True, "menu", "Feedback"))
                self.assertEqual((feedback["range"], feedback["keyRange"]), ("src/app.py:2-2", "/repo:1-1"))
                ref = f"review:{self.reviews[(tag, 'second')]}"
                texts = [text for path, text in feedback["posted"] if path == "/api/messages/sign"]
                self.assertEqual(texts[0].split(": ", 1)[0], f"Feedback on {ref} src/app.py:2-2")
                self.assertTrue(texts[0].endswith(" right-click note"), texts)
                if signs:
                    self.assertIn("right-click note", feedback["shown"])
                    self.assertTrue(any(text and text.endswith(" key f note") for _, text in feedback["posted"]), feedback["posted"])
                self.assertFalse(feedback["wide"])
        radio = [" ".join(args) for script, args in self.scripts.calls if script == skill_scripts.RADIO]
        reached = [entry for entry in radio if "] Feedback on review:" in entry or "] Feedback on ask:" in entry]
        self.assertEqual(len(reached), 2 * len(base.WIDTHS) if signs else 0, radio)

    def test_chromium_shows_operator_tasks_with_a_badge_diffs_bulk_grants_and_sends_feedback_at_three_widths(self):
        with mock.patch.object(batches, "UNDO", 0.3):
            data = self.drive(self.steps("chromium", True), self.authenticator())
        (OUT / "chromium-operator.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        self.check(data, "chromium", True)

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_shows_operator_tasks_with_a_badge_diffs_and_feedback_without_signing_at_three_widths(self):
        data = self.drive(self.steps("firefox", False), None, "bidi.mjs", os.environ.get("FIREFOX", "firefox"))
        (OUT / "firefox-operator.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        self.check(data, "firefox", False)


if __name__ == "__main__":
    unittest.main()
