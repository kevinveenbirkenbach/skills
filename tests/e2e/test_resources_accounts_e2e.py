from __future__ import annotations

import datetime
import json
import os
import re
import shutil
import stat
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
from kvb_orchestrator import accounts, calibration
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
BAR = """
  const bar = (id) => document.querySelector(`#main .res-accounts [data-usage="${id || "@ONE@"}"]`);
  const valueOf = (node) => Number(node.getAttribute("aria-valuenow"));
  const tenth = (value) => Math.round(value * 10) / 10;
  const settled = (value) => until(() => {
    const node = bar();
    return node && !node.hasAttribute("data-pending") && valueOf(node) === value ? node : null;
  }, 6000);
  const ratio = (node) => (100 * node.querySelector(".acc-fill").getBoundingClientRect().width) / node.getBoundingClientRect().width;
  const read = (node) => ({share: valueOf(node), ratio: ratio(node), fill: node.style.getPropertyValue("--fill"), expected: UsageBar.fillColor(valueOf(node))});
  const key = (name) => bar().dispatchEvent(new KeyboardEvent("keydown", {key: name, bubbles: true, cancelable: true}));
  const pointer = (node, type, x, y) => node.dispatchEvent(new PointerEvent(type, {bubbles: true, cancelable: true, pointerId: 1, button: 0, isPrimary: true, pointerType: "mouse", clientX: x, clientY: y}));
  const toggle = () => document.querySelector("#main .res-accounts [data-forecast-toggle]");
  const marks = () => all("#main .res-accounts [data-usage]").map((node) => [node.dataset.usage, all("[data-forecast]", node).map((mark) => [mark.dataset.forecast, mark.title])]);
  const unlimited = () => !document.querySelector('#main .res-accounts tr[data-account="@THREE@"] [data-usage]');
"""
USAGE = """(async () => {@HELPERS@@KIT@@BAR@
  if (!(await until(() => bar() && toggle(), 15000))) {
    return {error: text(box()) || text(document.getElementById("main"))};
  }
  await sleep(300);
  const first = bar();
  const shown = {...read(first), role: first.getAttribute("role"), range: [first.getAttribute("aria-valuemin"), first.getAttribute("aria-valuemax")], unlimited: unlimited()};
  bar().focus();
  key("ArrowRight");
  const right = valueOf(bar());
  key("PageUp");
  const paged = valueOf(bar());
  const keyed = await settled(tenth(Math.min(100, shown.share + 11)));
  const kept = Boolean(keyed) && document.activeElement === keyed;
  const rect = bar().getBoundingClientRect();
  const y = rect.top + rect.height / 2;
  pointer(bar(), "pointerdown", rect.left + rect.width * 0.1, y);
  pointer(document, "pointermove", rect.left + rect.width * 0.25, y);
  pointer(document, "pointermove", rect.left + rect.width * 0.4, y);
  pointer(document, "pointerup", rect.left + rect.width * 0.4, y);
  const dragged = await settled(40);
  const stored = (await (await fetch("/api/accounts", {cache: "no-store"})).json()).calibrations;
  const before = {pressed: toggle().getAttribute("aria-pressed"), marks: marks()};
  toggle().click();
  await until(() => toggle().getAttribute("aria-pressed") === "true" && marks().every(([, found]) => found.length === 1), 6000);
  const on = {pressed: toggle().getAttribute("aria-pressed"), marks: marks()};
  bar().scrollIntoView({block: "center", inline: "center"});
  return {shown, right, paged, keyed: Boolean(keyed), kept, dragged: dragged ? read(dragged) : null, stored, before, on, page: wide(), violations: window.e2eViolations || null};
})()"""
RELOAD = """(async () => {@HELPERS@@KIT@@BAR@
  if (!(await until(() => bar() && toggle() && marks().every(([, found]) => found.length === 1), 15000))) {
    return {error: text(box()) || text(document.getElementById("main"))};
  }
  bar().scrollIntoView({block: "center", inline: "center"});
  const after = {...read(bar()), pressed: toggle().getAttribute("aria-pressed"), marks: marks()};
  toggle().click();
  const off = Boolean(await until(() => toggle().getAttribute("aria-pressed") === "false" && marks().every(([, found]) => found.length === 0), 6000));
  return {after, off, page: wide(), violations: window.e2eViolations || null};
})()"""
DAY_TIME = r"(Sun|Mon|Tue|Wed|Thu|Fri|Sat) [0-2][0-9]:[0-5][0-9]"


def probe(template: str, ids: dict[str, str] | None = None) -> str:
    names = {"@HELPERS@": base.HELPERS, "@READ@": res.READ, "@KIT@": KIT, "@BAR@": BAR, "@EMAIL@": EMAIL, **(ids or {})}
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
                self.assertEqual(add["off"]["panels"], [*shown, ["resources-accounts", True], ["resources-usage", True]])
                self.assertEqual(add["off"]["picks"][-2:], [["accounts", False, False], ["usage", False, False]])
                self.assertEqual(add["on"]["panels"], [*shown, ["resources-accounts", False], ["resources-usage", True]])
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


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestAccountUsageBar(HubCase):
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
            {"t": now - 60, "agent": "Stage", "model": "claude-opus-5-5", "input": 900, "output": 0, "cache_read": 0, "cache_write": 0, "account": "two@example.org"},
        ]
        (folder / "tokens.jsonl").write_text(self.jsonl(tokens), encoding="utf-8")
        self.council.mkdir(parents=True, exist_ok=True)
        (self.council / accounts.SESSION_ACCOUNTS).write_text(json.dumps({"session": "s1", "email": EMAIL}) + "\n", encoding="utf-8")
        reset = {"day": (datetime.datetime.now().isoweekday() % 7 + 3) % 7, "time": "12:00"}
        stored = {"provider": "Anthropic", "renewal": {"day": 1, "time": "09:00"}, "reset": reset, "resubscribe": "", "autorenew": True, "note": ""}
        ledger = self.httpd.hub.accounts.ledger
        self.ids = {
            f"@{name}@": ledger.add(accounts.valid_account({**stored, "email": email, "limit": limit}))["id"]
            for name, email, limit in (("ONE", EMAIL, 1000), ("TWO", "two@example.org", 1000), ("THREE", "three@example.org", None))
        }
        self.base = f"http://{self.host}/"

    def steps(self, browser: str) -> list[dict]:
        steps = []
        for width, height in base.WIDTHS:
            shot = OUT / f"{browser}-{width}"
            url = f"{self.base}?{width}#resources"
            steps += [
                {"width": width, "height": height, "url": url, "wait": 1200, "probe": probe(USAGE, self.ids), "shot": f"{shot}-usage.png"},
                {"width": width, "height": height, "url": f"{self.base}?{width}-reload#resources", "wait": 1200, "probe": probe(RELOAD, self.ids), "shot": f"{shot}-usage-reloaded.png"},
            ]
        return steps

    def check(self, data: dict, browser: str) -> None:
        results = iter(data["results"])
        one, two = self.ids["@ONE@"], self.ids["@TWO@"]
        for index, (width, _) in enumerate(base.WIDTHS):
            usage, reload = next(results), next(results)
            with self.subTest(browser=browser, width=width):
                self.assertNotIn("error", usage, usage)
                shown = usage["shown"]
                self.assertEqual((shown["role"], shown["range"], shown["unlimited"]), ("slider", ["0", "100"], True))
                self.assertEqual(shown["share"], 40 if index else 4.2)
                self.assertLessEqual(abs(shown["ratio"] - shown["share"]), 1, shown)
                self.assertEqual(shown["fill"], shown["expected"])
                self.assertEqual((usage["right"], usage["paged"]), (round(shown["share"] + 1, 1), round(shown["share"] + 11, 1)))
                self.assertTrue(usage["keyed"] and usage["kept"], usage)
                self.assertEqual(usage["dragged"]["share"], 40, usage)
                self.assertLessEqual(abs(usage["dragged"]["ratio"] - 40), 1, usage)
                self.assertEqual(usage["dragged"]["fill"], usage["dragged"]["expected"])
                self.assertEqual(usage["stored"][one]["share"], 40)
                self.assertEqual(usage["before"], {"pressed": "false", "marks": [[one, []], [two, []]]})
                self.assertEqual(usage["on"]["pressed"], "true")
                (first, (mine,)), (second, (full,)) = usage["on"]["marks"]
                self.assertEqual((first, mine[0], second, full[0]), (one, "reset", two, "full"))
                self.assertRegex(mine[1], rf"^[0-9]+ % expected at the reset, {DAY_TIME}$")
                self.assertRegex(full[1], rf"^100 % at {DAY_TIME}$")
                self.assertEqual(usage["page"], {"wide": False})
                self.assertEqual(w4.quiet(usage["violations"]), [])
                self.assertNotIn("error", reload, reload)
                after = reload["after"]
                self.assertEqual((after["share"], after["pressed"]), (40, "true"))
                self.assertLessEqual(abs(after["ratio"] - 40), 1, after)
                self.assertEqual([found[0][0] for _, found in after["marks"]], ["reset", "full"])
                self.assertTrue(reload["off"], reload)
                self.assertEqual(reload["page"], {"wide": False})
                self.assertEqual(w4.quiet(reload["violations"]), [])
        self.assertFalse(self.httpd.hub.settings.get()["forecast"])
        file = self.state / calibration.CALIBRATION
        self.assertEqual(stat.S_IMODE(file.stat().st_mode), 0o600)
        self.assertEqual(json.loads(file.read_text(encoding="utf-8"))[one]["share"], 40)
        self.assertIsNone(re.search(r"@[A-Z]+@", json.dumps(data["results"])))

    def test_chromium_calibrates_the_usage_bar_by_keys_and_drag_and_switches_the_forecast_at_three_widths(self):
        data = self.drive(self.steps("chromium"), None, init=w4.GUARD)
        (OUT / "chromium-account-usage.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        self.check(data, "chromium")

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_calibrates_the_usage_bar_by_keys_and_drag_and_switches_the_forecast_at_three_widths(self):
        data = self.drive(self.steps("firefox"), None, "bidi.mjs", os.environ.get("FIREFOX", "firefox"), init=w4.GUARD)
        (OUT / "firefox-account-usage.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        self.check(data, "firefox")


if __name__ == "__main__":
    unittest.main()
