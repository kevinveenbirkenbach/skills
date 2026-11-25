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
import test_resources_view_e2e as res
import test_workbench_w4_e2e as w4
from hub_case import HubCase
from kvb_orchestrator import accounts
from kvb_orchestrator.viewstore import VIEW

OUT = Path(os.environ.get("E2E_OUT", "/tmp/hub-028-shots"))
EMAIL = "one@example.org"
KIT = """
  const box = () => document.querySelector("#main .res-accounts");
  const rows = () => all("#main .res-accounts tbody tr").map((row) => [row.dataset.account === "" ? "" : "account", all("td", row).map((cell) => text(cell))]);
  const sheet = () => document.getElementById("sheet");
  const field = (label) => sheet().querySelector(`[aria-label="${label}"]`);
  const button = (root, label) => all("button", root).find((node) => name(node) === label || text(node) === label);
  const wide = () => ({wide: document.documentElement.scrollWidth > innerWidth + 1});
"""
ADD = """(async () => {@HELPERS@@READ@@KIT@
  if (!(await until(() => box() && rows().length === 1, 15000))) {
    return {error: text(box()) || text(document.getElementById("main"))};
  }
  const before = rows();
  button(box(), "Add account").click();
  await until(() => !sheet().hidden && field("Provider"), 4000);
  field("Provider").value = "Anthropic";
  field("Email").value = "@EMAIL@";
  field("Renewal weekday").value = "1";
  field("Renewal time").value = "09:00";
  field("Weekly reset weekday").value = "4";
  field("Weekly reset time").value = "18:30";
  field("Autorenew").checked = true;
  field("Weekly token limit").value = "1000";
  button(sheet(), "Save").click();
  const added = Boolean(await until(() => sheet().hidden && rows().length === 2, 5000));
  const afterAdd = rows();
  button(box(), "Edit @EMAIL@").click();
  await until(() => !sheet().hidden && field("Weekly token limit"), 4000);
  const prefilled = [field("Provider").value, field("Email").value, field("Weekly token limit").value, field("Autorenew").checked];
  field("Weekly token limit").value = "";
  button(sheet(), "Save").click();
  const edited = Boolean(await until(() => sheet().hidden && rows()[0] && rows()[0][1][9] === "–", 5000));
  const afterEdit = rows();
  await pickPanel("accounts", false);
  const off = {panels: panelsShown(), picks: picks()};
  await pickPanel("accounts", true);
  await until(() => rows().length === 2, 4000);
  const on = {panels: panelsShown(), picks: picks()};
  return {before, added, afterAdd, prefilled, edited, afterEdit, off, on, page: wide(), violations: window.e2eViolations || null};
})()"""
REMOVE = """(async () => {@HELPERS@@READ@@KIT@
  button(box(), "Edit @EMAIL@").click();
  await until(() => !sheet().hidden && button(sheet(), "Remove"), 4000);
  button(sheet(), "Remove").click();
  const removed = Boolean(await until(() => sheet().hidden && rows().length === 1, 5000));
  return {removed, after: rows(), page: wide(), violations: window.e2eViolations || null};
})()"""


def probe(template: str) -> str:
    names = {"@HELPERS@": base.HELPERS, "@READ@": res.READ, "@KIT@": KIT, "@EMAIL@": EMAIL}
    for key, value in names.items():
        template = template.replace(key, value)
    return template


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestResourcesAccounts(HubCase):
    drive = base.OrchestratorE2ECase.drive
    sample = w4.TestWorkbenchResources.sample

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        now = int(time.time())
        self.start = now - now % 60 - w4.ROWS * 60
        folder = self.kept / "resources"
        folder.mkdir()
        (folder / "samples.jsonl").write_text(self.jsonl([self.sample(index) for index in range(w4.ROWS)]), encoding="utf-8")
        tokens = [
            {"t": now - 60, "agent": "Skills", "model": "claude-opus-5-5", "input": 40, "output": 2, "cache_read": 0, "cache_write": 0, "account": EMAIL},
            {"t": now - 60, "agent": "Stage", "model": "claude-haiku-4-5", "input": 3, "output": 0, "cache_read": 0, "cache_write": 0},
        ]
        (folder / "tokens.jsonl").write_text(self.jsonl(tokens), encoding="utf-8")
        self.council.mkdir(parents=True, exist_ok=True)
        (self.council / accounts.SESSION_ACCOUNTS).write_text(json.dumps({"session": "s1", "email": EMAIL}) + "\n", encoding="utf-8")
        self.base = f"http://{self.host}/"

    def steps(self, browser: str) -> list[dict]:
        steps = []
        for width, height in base.WIDTHS:
            shot = OUT / f"{browser}-{width}"
            steps += [
                {"width": width, "height": height, "url": f"{self.base}?{width}#resources", "wait": 1200, "probe": probe(ADD), "shot": f"{shot}-accounts.png"},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(REMOVE), "shot": f"{shot}-accounts-removed.png"},
            ]
        return steps

    def check(self, data: dict, browser: str) -> None:
        results = iter(data["results"])
        shown = [["resources-hardware", False], ["resources-tokens", False], ["resources-combined", True]]
        for width, _ in base.WIDTHS:
            add, remove = next(results), next(results)
            with self.subTest(browser=browser, width=width):
                self.assertNotIn("error", add, add)
                self.assertEqual([(kind, cells[-3]) for kind, cells in add["before"]], [("", "45")])
                self.assertTrue(add["added"], add)
                (kind, cells), (rest, other) = add["afterAdd"]
                self.assertEqual((kind, rest), ("account", ""))
                self.assertEqual(cells[0], "Anthropic")
                self.assertTrue(cells[1].startswith(EMAIL) and cells[1].endswith("active"), cells[1])
                self.assertEqual((cells[2], cells[5], cells[6], cells[7], cells[8], cells[9]), ("Mon 09:00", "yes", "42", "42", "42", "958"))
                self.assertEqual(other[-3], "3")
                self.assertEqual(add["prefilled"], ["Anthropic", EMAIL, "1000", True])
                self.assertTrue(add["edited"], add)
                self.assertEqual(add["afterEdit"][0][1][9], "–")
                self.assertEqual(add["off"]["panels"], [*shown, ["resources-accounts", True]])
                self.assertEqual(add["off"]["picks"][-1], ["accounts", False, False])
                self.assertEqual(add["on"]["panels"], [*shown, ["resources-accounts", False]])
                self.assertEqual(add["page"], {"wide": False})
                self.assertEqual(w4.quiet(add["violations"]), [])
                self.assertTrue(remove["removed"], remove)
                self.assertEqual([(kind, cells[-3]) for kind, cells in remove["after"]], [("", "45")])
                self.assertEqual(remove["page"], {"wide": False})
                self.assertEqual(w4.quiet(remove["violations"]), [])
        self.assertEqual(self.httpd.hub.view_store.get(), VIEW)
        self.assertEqual(self.httpd.hub.accounts.ledger.listed(), [])

    def test_chromium_adds_edits_and_removes_an_account_and_picks_the_panel_at_three_widths(self):
        data = self.drive(self.steps("chromium"), None, init=w4.GUARD)
        (OUT / "chromium-resources-accounts.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        self.check(data, "chromium")

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_adds_edits_and_removes_an_account_and_picks_the_panel_at_three_widths(self):
        data = self.drive(self.steps("firefox"), None, "bidi.mjs", os.environ.get("FIREFOX", "firefox"), init=w4.GUARD)
        (OUT / "firefox-resources-accounts.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        self.check(data, "firefox")


if __name__ == "__main__":
    unittest.main()
