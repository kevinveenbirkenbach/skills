from __future__ import annotations

import json
import os
import shutil
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

import hub_e2e_kit as base
import test_resources_accounts_e2e as acc
import test_resources_view_e2e as res
import test_workbench_w4_e2e as w4
from hub_case import HubCase

OUT = acc.OUT
EMAIL = acc.EMAIL
ADDED = "two@example.org"
STORED = {"provider": "Anthropic", "email": EMAIL, "renewal": {"day": 1, "time": "09:00"}, "reset": {"day": 4, "time": "18:30"}, "resubscribe": "", "autorenew": True, "limit": None, "note": "old"}
FILE = f"provider,Contact,renewal,reset,note\nAnthropic,{EMAIL},Mon 09:00,Thu 18:30,new note\nOpenAI,{ADDED},Tue 10:00,Fri 12:00,fresh\n"
IMPORT = """(async () => {@HELPERS@@READ@@KIT@
  const apply = () => sheet().querySelector("[data-import-apply]");
  const choice = () => sheet().querySelector('[data-choice="@EMAIL@"]');
  const changed = (node, value) => {
    node.value = value;
    node.dispatchEvent(new Event("change", {bubbles: true}));
  };
  if (!(await until(() => box() && rows().length === 2, 15000))) {
    return {error: text(box()) || text(document.getElementById("main"))};
  }
  const links = all("#main .res-accounts a[data-export]").map((link) => [link.dataset.export, link.getAttribute("href"), link.hasAttribute("download")]);
  const exported = await (await fetch(links[0][1], {cache: "no-store"})).text();
  const picker = box().querySelector("[data-import-file]");
  const data = new DataTransfer();
  data.items.add(new File([@FILE@], "accounts.csv", {type: "text/csv"}));
  picker.files = data.files;
  picker.dispatchEvent(new Event("change", {bubbles: true}));
  await until(() => !sheet().hidden && apply(), 5000);
  const blocked = {disabled: apply().disabled, missing: text(sheet().querySelector("[data-import-missing]"))};
  changed(sheet().querySelector('[data-map="email"]'), "1");
  await until(() => choice(), 5000);
  const statuses = all("[data-import-row]", sheet()).map((row) => row.dataset.importRow);
  changed(choice(), "keep");
  await until(() => choice() && choice().value === "keep", 5000);
  const ready = !apply().disabled;
  let applied = null;
  if (@APPLY@) {
    apply().click();
    applied = Boolean(await until(() => sheet().hidden && rows().length === 3, 5000));
  }
  return {links, exported, blocked, statuses, ready, applied, page: wide(), violations: window.e2eViolations || null};
})()"""


def probe(apply: bool) -> str:
    names = {"@HELPERS@": base.HELPERS, "@READ@": res.READ, "@KIT@": acc.KIT, "@EMAIL@": EMAIL, "@FILE@": json.dumps(FILE), "@APPLY@": "true" if apply else "false"}
    template = IMPORT
    for key, value in names.items():
        template = template.replace(key, value)
    return template


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestAccountsImport(HubCase):
    drive = base.OrchestratorE2ECase.drive
    sample = w4.TestWorkbenchResources.sample

    def setUp(self):
        acc.TestResourcesAccounts.setUp(self)
        status, _, answer = self.post_json("/api/accounts", {"id": "", "account": STORED}, self.guard(self.host))
        self.assertEqual(status, 200, answer)

    def steps(self, browser: str) -> list[dict]:
        last = len(base.WIDTHS) - 1
        return [
            {"width": width, "height": height, "url": f"{self.base}?{width}#resources", "wait": 1200, "probe": probe(index == last), "shot": f"{OUT / f'{browser}-{width}'}-accounts-import.png"}
            for index, (width, height) in enumerate(base.WIDTHS)
        ]

    def check(self, data: dict, browser: str) -> None:
        last = len(base.WIDTHS) - 1
        for index, ((width, _), found) in enumerate(zip(base.WIDTHS, data["results"], strict=True)):
            with self.subTest(browser=browser, width=width):
                self.assertNotIn("error", found, found)
                self.assertEqual(found["links"], [["csv", "/api/accounts/export?format=csv", True], ["tsv", "/api/accounts/export?format=tsv", True]])
                self.assertTrue(found["exported"].startswith("provider,email,"), found["exported"])
                self.assertIn(EMAIL, found["exported"])
                self.assertEqual(found["blocked"], {"disabled": True, "missing": "Missing: email"})
                self.assertEqual(found["statuses"], ["update", "new"])
                self.assertTrue(found["ready"])
                self.assertEqual(found["applied"], True if index == last else None)
                self.assertEqual(found["page"], {"wide": False})
                self.assertEqual(w4.quiet(found["violations"]), [])
        stored = {account["email"]: account for account in self.httpd.hub.accounts.ledger.listed()}
        self.assertEqual(sorted(stored), [EMAIL, ADDED])
        self.assertEqual(stored[EMAIL]["note"], "old")
        self.assertEqual((stored[ADDED]["provider"], stored[ADDED]["note"]), ("OpenAI", "fresh"))

    def test_chromium_exports_and_imports_with_one_mapped_column_and_one_kept_conflict(self):
        data = self.drive(self.steps("chromium"), None, init=w4.GUARD)
        (OUT / "chromium-accounts-import.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        self.check(data, "chromium")

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_exports_and_imports_with_one_mapped_column_and_one_kept_conflict(self):
        data = self.drive(self.steps("firefox"), None, "bidi.mjs", os.environ.get("FIREFOX", "firefox"), init=w4.GUARD)
        (OUT / "firefox-accounts-import.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        self.check(data, "firefox")


if __name__ == "__main__":
    unittest.main()
