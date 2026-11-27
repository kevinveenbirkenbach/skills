"""Exercise requirement 067: the rules page lists the hub rules grouped by kind with expiry chips and match counts, and drafts a new rule in a sheet with a live count."""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

import hub_e2e_kit as base
from hub_case import HubCase
from hub_support import ASK

OUT = Path(os.environ.get("E2E_OUT", "/tmp/hub-067-shots"))
COMMANDS = (("make deploy", "s1"), ("make deploy --dry", "s1"), ("make deploy", "s2"), ("make test", "s1"), ("git status", "s1"))
PAGE = """(async () => {@HELPERS@
  await screenShown(8000);
  (await until(() => document.getElementById("controls-tab-rules"), 8000)).click();
  if (!(await until(() => document.querySelector("#main .hub-rule-list li.hub-rule"), 8000))) {
    return {error: text(document.getElementById("main"))};
  }
  window.e2eSameDocument = true;
  const fold = (id) => document.querySelector(`#main details[data-fold="${id}"]`);
  const shown = (node) => Boolean(node && node.getClientRects().length);
  const visible = (id) => all("li.hub-rule", fold(id)).filter(shown).length;
  const rowOf = (pattern) => all("#main li.hub-rule").find((node) => text(node.querySelector(".hub-rule-pattern")) === pattern);
  const chipOf = (row) => row.querySelector("[data-expiry]");
  const found = {
    firewall: ["settings", "patterns", "groups", "sets"].map((id) => Boolean(fold(id)) && !fold(id).open),
    heads: ["ask", "review", "decision"].map((id) => [text(fold(id).querySelector("summary strong")), text(fold(id).querySelector("summary .count"))]),
  };
  const deploy = rowOf("make deploy*");
  const toggle = deploy.querySelector('input.switch[role="switch"]');
  found.row = {
    on: Boolean(toggle) && toggle.checked, tool: text(deploy.querySelector(".hub-rule-tool")), scope: text(deploy.querySelector(".hub-rule-scope")), target: text(deploy.querySelector("[data-agents]")),
    tone: chipOf(deploy).dataset.tone, chip: text(chipOf(deploy)), count: text(deploy.querySelector(".hub-rule-count")), remove: Boolean(deploy.querySelector('button[aria-label="Delete rule"]')),
  };
  found.soon = [chipOf(rowOf("make test*")).dataset.tone, text(chipOf(rowOf("make test*"))), text(rowOf("make test*").querySelector(".hub-rule-count"))];
  const before = visible("ask");
  fold("ask").querySelector("summary").click();
  await sleep(150);
  found.collapsed = {open: fold("ask").open, rows: visible("ask"), review: visible("review"), decision: visible("decision")};
  fold("ask").querySelector("summary").click();
  await sleep(150);
  found.reopened = [before, visible("ask")];
  document.querySelector("#main [data-new-rule]").click();
  const form = await until(() => document.querySelector("#sheet .rule-form"), 4000);
  if (!form) {
    return {...found, error: "no sheet"};
  }
  const live = () => document.querySelector("#sheet [data-live-count]");
  const pattern = form.querySelector('input[aria-label="Pattern"]');
  const type = async (value, matched) => {
    pattern.value = value;
    pattern.dispatchEvent(new Event("input", {bubbles: true}));
    return until(() => live().dataset.matched === matched && text(live()), 4000);
  };
  found.sheet = text(document.querySelector("#sheet .sheet-head h2"));
  found.live = [await type("make deploy*", "3"), await type("make test*", "1"), await type("", "")];
  if (@CREATE@) {
    const made = "make e2e-@WIDTH@";
    await type(made, "0");
    form.requestSubmit();
    const row = await until(() => rowOf(made), 15000);
    found.created = {row: Boolean(row), closed: document.getElementById("sheet").hidden, same: window.e2eSameDocument === true, count: row ? text(row.querySelector(".hub-rule-count")) : null, head: text(fold("ask").querySelector("summary .count"))};
  } else {
    document.querySelector("#sheet .sheet-head button").click();
  }
  found.wide = document.documentElement.scrollWidth > innerWidth + 1;
  return found;
})()"""


def probe(width: int, create: bool) -> str:
    return PAGE.replace("@HELPERS@", base.HELPERS).replace("@CREATE@", "true" if create else "false").replace("@WIDTH@", str(width))


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestRulesPage(HubCase):
    drive = base.OrchestratorE2ECase.drive
    authenticator = base.OrchestratorE2ECase.authenticator

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        self.claim("s1", "Skills")
        self.claim("s2", "Stage")
        self.snapshot()
        for command, session in COMMANDS:
            self.create_ask({**ASK, "command": command, "session": session})
        self.page_url = f"http://localhost:{self.port}/"

    def stored(self, signer) -> None:
        now = time.time()
        self.signed_rule(signer, {"kind": "ask", "tool": "Bash", "pattern": "make deploy*", "scope": "/repo*", "expires": now + 30 * 86400})
        self.signed_rule(signer, {"kind": "ask", "tool": "Bash", "pattern": "make test*", "scope": "*", "expires": now + 86400 + 3600})
        self.signed_rule(signer, {"kind": "review", "tool": "", "pattern": "feature/*", "scope": "/repo/*", "expires": now + 10 * 86400})
        self.signed_rule(signer, {"kind": "decision", "tool": "", "pattern": "*", "scope": "*", "expires": now + 10 * 86400})

    def steps(self, browser: str, create: bool) -> list[dict]:
        return [{"width": width, "height": height, "url": f"{self.page_url}?{width}#stream/rules", "wait": 1500, "probe": probe(width, create), "shot": str(OUT / f"{browser}-{width}-rules-page.png")} for width, height in base.WIDTHS]

    def check(self, data: dict, create: bool) -> None:
        for index, ((width, _), found) in enumerate(zip(base.WIDTHS, data["results"], strict=True)):
            made = index if create else 0
            with self.subTest(width=width):
                self.assertNotIn("error", found, found)
                self.assertEqual(found["firewall"], [True] * 4)
                self.assertEqual(found["heads"], [["Ask", str(2 + made)], ["Review", "1"], ["Decision", "1"]])
                row = found["row"]
                self.assertEqual({key: row[key] for key in ("on", "tool", "scope", "target", "tone", "count", "remove")}, {"on": True, "tool": "Bash", "scope": "/repo*", "target": "all agents", "tone": "neutral", "count": "3 of the last 5 asks", "remove": True})
                self.assertRegex(row["chip"], r"^(29|30) days left$")
                self.assertEqual(found["soon"], ["bad", "1 day left", "1 of the last 5 asks"])
                self.assertEqual(found["collapsed"], {"open": False, "rows": 0, "review": 1, "decision": 1})
                self.assertEqual(found["reopened"], [2 + made, 2 + made])
                self.assertEqual(found["sheet"], "New rule")
                self.assertEqual(found["live"][:2], ["Would grant 3 of the last 5 asks", "Would grant 1 of the last 5 asks"])
                self.assertTrue(found["live"][2].startswith("Not counted: "), found["live"])
                if create:
                    self.assertEqual(found["created"], {"row": True, "closed": True, "same": True, "count": "0 of the last 5 asks", "head": str(3 + made)})
                self.assertFalse(found["wide"])

    def test_chromium_lists_the_rules_by_kind_and_creates_one_from_the_sheet_at_three_widths(self):
        authenticator = self.authenticator()
        self.stored(self.pin())
        data = self.drive(self.steps("chromium", True), authenticator)
        (OUT / "chromium-rules-page.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        self.check(data, True)
        self.assertEqual(sorted(rule["pattern"] for rule in self.httpd.hub.rules.listed() if rule["pattern"].startswith("make e2e-")), sorted(f"make e2e-{width}" for width, _ in base.WIDTHS))

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_lists_the_rules_by_kind_and_counts_the_draft_at_three_widths(self):
        self.stored(self.pin())
        data = self.drive(self.steps("firefox", False), None, "bidi.mjs", os.environ.get("FIREFOX", "firefox"))
        (OUT / "firefox-rules-page.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        self.check(data, False)


if __name__ == "__main__":
    unittest.main()
