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
from hub_e2e_kit import WIDTHS
from hub_support import ASK
from kvb_orchestrator import batches

OUT = Path(os.environ.get("E2E_OUT", "/tmp/bulk-grant-shots"))
FILES = ("src/app.py", "src/view.js", "docs/notes.md")
ROWS = 80
COMMON = """
  const row = (ref) => document.querySelector(`#main .inbox-list > li[data-ref="${ref}"]`);
  const split = () => document.querySelector("#grant-bar .grant-split");
  const menu = () => document.querySelector("#grant-bar details.grant-menu");
  const main = () => split() && split().firstElementChild;
  const count = () => menu() && menu().querySelector("summary").getAttribute("aria-label");
  const openMenu = async () => {
    if (!menu().open) {
      menu().querySelector("summary").click();
    }
    await until(() => menu().open, 2000);
    await sleep(100);
  };
  const grantOf = (ref) => row(ref) && (row(ref).querySelector(".item-actions button.primary") || all(".options.dialog > button.option", row(ref)).find((button) => text(button.querySelector("strong")) === "Yes"));
  const wide = () => document.documentElement.scrollWidth > innerWidth + 1;
  const switchState = () => [name(main()), count(), document.querySelector("#grant-bar #grant-direct") ? "select" : "direct"];
  const storedMode = async (mode) => {
    const end = Date.now() + 6000;
    while (Date.now() < end) {
      const view = await (await fetch("/api/view", {cache: "no-store"})).json();
      if (view.approval.mode === mode) {
        return true;
      }
      await sleep(200);
    }
    return false;
  };
  const key = (value) => document.body.dispatchEvent(new KeyboardEvent("keydown", {key: value, bubbles: true}));
"""
DIFF = """(async () => {@HELPERS@@COMMON@
  if (!(await until(() => row("@REVIEW@"), 8000))) {
    return {error: text(document.getElementById("main"))};
  }
  row("@REVIEW@").querySelector(".headline").click();
  const stack = await until(() => {
    const found = document.querySelector("#sheet .review-stack");
    return found && all(".review-file", found).length === 3 ? found : null;
  }, 8000);
  if (!stack) {
    return {error: text(document.getElementById("sheet"))};
  }
  const files = () => all(".review-file", stack);
  const state = () => ({opened: files().map((file) => file.open), marked: all("#sheet .file-entry[aria-current='true']").map((entry) => Number(entry.dataset.index))});
  const first = state();
  const [one, two] = files();
  stack.scrollTop = one.offsetTop + one.offsetHeight - stack.clientHeight + 4;
  await until(() => files()[1].open, 4000);
  await sleep(300);
  const ended = state();
  stack.scrollTop = two.offsetTop;
  await until(() => state().marked[0] === 1, 4000);
  await sleep(200);
  const second = state();
  document.querySelector('#sheet .file-entry[data-index="2"]').click();
  await sleep(400);
  const three = files()[2];
  const atTop = Math.abs(three.getBoundingClientRect().top - stack.getBoundingClientRect().top) <= 2 || stack.scrollTop >= stack.scrollHeight - stack.clientHeight - 1;
  return {first, ended, second, jumped: {...state(), atTop}, wide: wide()};
})()"""
MODE = """(async () => {@HELPERS@@COMMON@
  key("Escape");
  await until(() => document.getElementById("sheet").hidden, 4000);
  const before = switchState();
  main().click();
  const kept = await storedMode("select");
  await until(() => switchState()[2] === "select", 4000);
  return {before, kept, after: switchState(), wide: wide()};
})()"""
COLLECT = """(async () => {@HELPERS@@COMMON@
  const posted = [];
  const send = window.fetch.bind(window);
  window.fetch = (path, init) => {
    if (["/api/sign", "/api/inbox/approve"].includes(String(path))) {
      posted.push(String(path));
    }
    return send(path, init);
  };
  if (!(await until(() => row("@REVIEW@") && row("@ASK@") && row("@RUN@") && switchState()[2] === "select", 8000))) {
    return {error: text(document.getElementById("main"))};
  }
  const restored = switchState();
  const counts = [];
  const settle = async (expected) => {
    await until(() => count() === expected, 3000);
    counts.push(count());
  };
  grantOf("@REVIEW@").click();
  await settle("1 selected");
  const pale = [grantOf("@REVIEW@").disabled, grantOf("@REVIEW@").classList.contains("picked")];
  grantOf("@ASK@").click();
  await settle("2 selected");
  await openMenu();
  all("#grant-bar .grant-picked button").find((button) => name(button).startsWith("Remove feat: three files")).click();
  await settle("1 selected");
  grantOf("@REVIEW@").click();
  await settle("2 selected");
  if (document.activeElement) {
    document.activeElement.blur();
  }
  for (let step = 0; step < 40 && !row("@RUN@").classList.contains("cursor"); step += 1) {
    const cursor = document.querySelector("#main .inbox-list > li.cursor");
    key(cursor && Number(cursor.dataset.index) > Number(row("@RUN@").dataset.index) ? "k" : "j");
    await sleep(60);
  }
  key("a");
  await until(() => count() === "3 selected", 3000);
  counts.push(count());
  const pressed = ["@REVIEW@", "@ASK@", "@RUN@"].map((ref) => [grantOf(ref).getAttribute("aria-pressed"), grantOf(ref).disabled]);
  await openMenu();
  const labels = all("#grant-bar .grant-split button").map(name);
  return {restored, pale, counts, pressed, labels, posted, wide: wide()};
})()"""
SHEET = """(async () => {@HELPERS@@COMMON@
  main().click();
  await until(() => document.querySelector(".sheet-box .actions"), 4000);
  const confirm = all(".sheet-box .actions button").find((button) => text(button).startsWith("Grant "));
  return {listed: all(".sheet-box ul.mini > li strong").map(text), label: text(confirm), wide: wide()};
})()"""
CONFIRM = """(async () => {@HELPERS@@COMMON@
  navigator.credentials.get = @SIGNS@ ? navigator.credentials.get.bind(navigator.credentials) : () => Promise.reject(new DOMException("The operator canceled.", "NotAllowedError"));
  const posted = [];
  const send = window.fetch.bind(window);
  window.fetch = (path, init) => {
    if (["/api/sign", "/api/inbox/approve"].includes(String(path))) {
      posted.push([String(path), JSON.parse(init.body).items.map((item) => `${item.kind}:${item.id}:${item.verb}`).sort()]);
    }
    return send(path, init);
  };
  const shown = new Set(all("#toasts .toast"));
  all(".sheet-box .actions button").find((button) => text(button).startsWith("Grant ")).click();
  const toast = await until(() => all("#toasts .toast").filter((node) => !shown.has(node)).map(text).find((entry) => entry.startsWith("Grant selection")), 15000);
  await sleep(@SIGNS@ ? 2500 : 300);
  return {posted, toast, count: count(), wide: wide()};
})()"""
DIRECT = """(async () => {@HELPERS@@COMMON@
  const posted = [];
  const send = window.fetch.bind(window);
  window.fetch = (path, init) => {
    if (String(path) === "/api/sign") {
      posted.push(JSON.parse(init.body).items.map((item) => `${item.kind}:${item.id}`));
      return Promise.resolve(new Response("held by the e2e", {status: 503}));
    }
    return send(path, init);
  };
  await openMenu();
  document.querySelector("#grant-bar #grant-direct").click();
  const kept = await storedMode("direct");
  await until(() => switchState()[2] === "direct", 4000);
  const spare = await until(() => grantOf("@SPARE@"), 4000);
  const pressed = spare.getAttribute("aria-pressed");
  spare.click();
  await until(() => posted.length, 4000);
  return {kept, after: switchState(), pressed, posted, wide: wide()};
})()"""


def probe(template: str, **values: str) -> str:
    found = template.replace("@HELPERS@", base.HELPERS).replace("@COMMON@", COMMON)
    for name, value in values.items():
        found = found.replace(f"@{name}@", value)
    return found


def review_page() -> str:
    sections = []
    for path in FILES:
        rows = "".join(f'<tr class="add"><td class="num"></td><td class="num">{line}</td><td class="sign">+</td><td class="code">{html.escape(path)} line {line}</td></tr>' for line in range(1, ROWS + 1))
        sections.append(f'<details class="file" data-path="{path}"><summary><span class="badge added" title="added">A</span><span class="path">{path}</span>'
                        f'<span class="stat"><span class="add">+{ROWS}</span><span class="del">&minus;0</span></span></summary><table class="diff"><tbody>{rows}</tbody></table></details>')
    return f'<!DOCTYPE html><html><body><section class="group" id="staged" data-files="3">{"".join(sections)}</section></body></html>'


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestBulkGrant(base.OrchestratorE2ECase):
    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        page = self.page("three-files.html", review_page())
        rows = {}
        self.sets = {}
        for width, _ in WIDTHS:
            review = self.review(f"feat: three files {width}", f"feature/bulk-{width}", page)
            ask = self.create_ask({**ASK, "command": f"make deploy-{width}", "timeout": 3600})
            task = f"operator/bulk-{width}"
            rows[task] = {"title": f"echo bulk {width}", "workdir": "/repo", "description": "bulk", "check": "manual", "status": "queued", "roles": {"Operator": "R", "Skills session": "A"}}
            self.sets[width] = {"REVIEW": f"review:{review}", "ASK": f"ask:{ask}", "RUN": f"operator:{task}"}
        self.spare = f"review:{self.review('feat: spare', 'feature/bulk-spare', page)}"
        self.write_council({"rasci.json": rows})

    def review(self, title: str, branch: str, page: str) -> str:
        arguments = {**self.arguments(title, "", page), "worktree": f"/repo/.worktrees/{branch}", "branch": branch, "agent": "Skills"}
        result = self.tool("review_request", arguments)
        self.assertFalse(result["isError"], result)
        return result["structuredContent"]["id"]

    def steps(self, browser: str, signs: bool) -> list[dict]:
        local = f"http://localhost:{self.port}/"
        flag = "true" if signs else "false"
        steps = []
        for width, height in WIDTHS:
            ids = self.sets[width]
            shot = str(OUT / f"{browser}-{width}")
            steps += [
                {"width": width, "height": height, "url": f"{local}?{width}#stream/inbox", "wait": 1200, "probe": probe(DIFF, **ids), "shot": f"{shot}-continuous-diff.png"},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(MODE), "shot": None},
                {"width": width, "height": height, "url": f"{local}?{width}-kept#stream/inbox", "wait": 1200, "probe": probe(COLLECT, **ids), "shot": f"{shot}-select-tray.png"},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(SHEET), "shot": f"{shot}-grant-sheet.png"},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(CONFIRM, SIGNS=flag), "shot": None},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(DIRECT, SPARE=self.spare), "shot": f"{shot}-direct.png"},
            ]
        return steps

    def check(self, data: dict, browser: str, signs: bool) -> None:
        self.assertEqual([error for error in data["errors"] if "(style-src-elem)" not in error and "/favicon.ico" not in error], [])
        results = iter(data["results"])
        for width, _ in WIDTHS:
            ids = self.sets[width]
            diff, mode, collect, sheet, confirm, direct = (next(results) for _ in range(6))
            with self.subTest(browser=browser, width=width):
                self.assertNotIn("error", diff, diff)
                self.assertEqual(diff["first"], {"opened": [True, False, False], "marked": [0]}, diff)
                self.assertEqual(diff["ended"]["opened"], [True, True, False], diff)
                self.assertEqual(diff["second"], {"opened": [True, True, False], "marked": [1]}, diff)
                self.assertEqual(diff["jumped"], {"opened": [True, True, True], "marked": [2], "atTop": True}, diff)
                selecting = ["Grant selection (0)", "0 selected", "select"]
                self.assertEqual((mode["before"], mode["kept"], mode["after"]), (["Select", "0 selected", "direct"], True, selecting), mode)
                self.assertNotIn("error", collect, collect)
                self.assertEqual(collect["restored"], selecting, collect)
                self.assertEqual(collect["pale"], [True, True], collect)
                self.assertEqual(collect["counts"], ["1 selected", "2 selected", "1 selected", "2 selected", "3 selected"], collect)
                self.assertEqual((collect["pressed"], collect["posted"]), ([["true", True], ["true", False], ["true", True]], []), collect)
                self.assertEqual((collect["labels"][0], collect["labels"][-1]), ("Grant selection (3)", "Direct"), collect)
                self.assertEqual(sum(label.startswith("Remove ") for label in collect["labels"]), 3, collect)
                self.assertEqual((sheet["label"], len(sheet["listed"])), ("Grant 3", 3), sheet)
                items = sorted(f"{ref}:approve" for ref in ids.values())
                self.assertEqual(confirm["posted"], [["/api/sign", items], *([["/api/inbox/approve", items]] if signs else [])], confirm)
                self.assertEqual(confirm["count"], "0 selected" if signs else "3 selected", confirm)
                self.assertEqual(direct["kept"], True, direct)
                self.assertEqual(direct["after"], ["Select", "0 selected", "direct"] if signs else ["Grant selection (3)", "3 selected", "direct"], direct)
                self.assertEqual((direct["pressed"], direct["posted"]), (None, [[self.spare]]), direct)
                self.assertFalse(any(found["wide"] for found in (diff, mode, collect, sheet, confirm, direct)), width)

    def granted(self) -> None:
        reviews = [ids["REVIEW"].split(":", 1)[1] for ids in self.sets.values()]
        asks = [ids["ASK"].split(":", 1)[1] for ids in self.sets.values()]
        self.settle(lambda: all(self.status(review) == "approved" for review in reviews))
        self.assertEqual([self.ask_status(ask, "0") for ask in asks], ["allowed"] * len(asks))
        self.assertEqual(self.status(self.spare.split(":", 1)[1]), "pending")

    def test_chromium_continuous_diff_select_tray_one_signature_and_direct_at_three_widths(self):
        with mock.patch.object(batches, "UNDO", 0.3):
            data = self.drive(self.steps("chromium", True), self.authenticator())
            (OUT / "chromium-bulk-grant.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
            self.check(data, "chromium", True)
            self.granted()

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_continuous_diff_select_tray_and_direct_at_three_widths_unsigned(self):
        data = self.drive(self.steps("firefox", False), None, "bidi.mjs", os.environ.get("FIREFOX", "firefox"))
        (OUT / "firefox-bulk-grant.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.check(data, "firefox", False)


if __name__ == "__main__":
    unittest.main()
