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
import test_workbench_w4_e2e as w4

OUT = Path(os.environ.get("E2E_OUT", "/tmp/agents-controls-shots"))
VIEWS = (*base.VIEWS, "hierarchy")
READ = """
  const rect = (node) => node.getBoundingClientRect();
  const card = () => document.querySelector("#main .graph > .card.controls");
  const bar = () => card() && card().querySelector(':scope > [role="toolbar"]');
  const menuOf = (label) => all("details.menu", bar()).find((node) => name(node.querySelector("summary")) === label);
  const wide = () => document.documentElement.scrollWidth > innerWidth + 1;
  const toggle = async (menu, open) => {
    if (menu.open !== open) {
      menu.querySelector("summary").click();
    }
    return Boolean(await until(() => menu.open === open && (!open || menu.querySelector(".menu-box").getClientRects().length), 3000));
  };
"""
ROW = """(async () => {@HELPERS@@READ@
  if (!(await screenShown(8000)) || !(await until(bar, 8000))) {
    return {error: text(document.getElementById("main"))};
  }
  await sleep(300);
  const graph = card().parentElement;
  const kids = [...card().children];
  const switcher = card().querySelector(':scope > [aria-label="View"]');
  const status = menuOf("Status");
  const edge = rect(card()).right - parseFloat(getComputedStyle(card()).paddingRight) - parseFloat(getComputedStyle(card()).borderRightWidth);
  const middle = (box) => (box.top + box.bottom) / 2;
  const menus = {};
  for (const label of ["Day/Night", "Status"]) {
    const menu = menuOf(label);
    const open = await toggle(menu, true);
    const box = rect(menu.querySelector(".menu-box"));
    menus[label] = {open, inside: box.left >= -1 && box.right <= innerWidth + 1, wide: wide()};
    await toggle(menu, false);
  }
  return {
    above: [...graph.children].slice(0, [...graph.children].indexOf(card())).filter((node) => node.matches('.toolbar, [role="toolbar"]')).length,
    first: kids[0] === switcher,
    last: kids[kids.length - 1] === bar(),
    controls: [...bar().children].map((node) => (node.matches("details") ? name(node.querySelector("summary")) : name(node))),
    gap: Math.round(edge - rect(status).right),
    row: Math.abs(middle(rect(bar())) - middle(rect(switcher))) < rect(switcher).height / 2,
    below: rect(bar()).top >= rect(switcher).bottom - 1,
    wide: wide(),
    menus,
    violations: window.e2eViolations || null,
  };
})()"""
BEHAVIOUR = """(async () => {@HELPERS@@READ@
  if (!(await screenShown(8000)) || !(await until(bar, 8000))) {
    return {error: text(document.getElementById("main"))};
  }
  const hidden = () => JSON.parse(localStorage.getItem("kvb-orchestrator.status") || '{"hidden": []}').hidden;
  const night = menuOf("Day/Night");
  await toggle(night, true);
  const box = night.querySelector(".menu-box");
  const nightly = {badge: all(".pill", box).length > 0, picks: all(".night-picks input", box).length, actions: all(".actions button", box).map(name)};
  await toggle(night, false);
  const look = menuOf("Status");
  await toggle(look, true);
  const first = look.querySelector('input[data-look]:not([data-look="faces"])');
  const state = first.dataset.look;
  first.click();
  const off = Boolean(await until(() => hidden().includes(state), 3000));
  look.querySelector(`input[data-look="${state}"]`).click();
  const on = Boolean(await until(() => !hidden().includes(state), 3000));
  await toggle(look, false);
  all("button", bar()).find((button) => name(button) === "Priority").click();
  const order = Boolean(await until(() => location.hash === "#agents/hierarchy" && document.activeElement && document.activeElement.id === "agent-order-title", 8000));
  return {nightly, status: {off, on}, order, wide: wide(), violations: window.e2eViolations || null};
})()"""


def probe(template: str) -> str:
    return template.replace("@HELPERS@", base.HELPERS).replace("@READ@", READ)


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestAgentsControls(base.OrchestratorE2ECase):
    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)

    def steps(self, browser: str) -> list[dict]:
        steps = []
        for width, height in base.WIDTHS:
            steps += [{"width": width, "height": height, "url": f"{self.base}?{width}-{view}#agents/{view}", "wait": 1200, "probe": probe(ROW), "shot": str(OUT / f"{browser}-{width}-{view}.png")} for view in VIEWS]
            steps.append({"width": width, "height": height, "url": f"{self.base}?{width}-behaviour#agents/orbit", "wait": 1200, "probe": probe(BEHAVIOUR), "shot": None})
        return steps

    def check(self, data: dict, browser: str) -> None:
        results = iter(data["results"])
        for width, _ in base.WIDTHS:
            for view in VIEWS:
                row = next(results)
                with self.subTest(browser=browser, width=width, view=view):
                    self.assertNotIn("error", row, row)
                    self.assertEqual((row["above"], row["first"], row["last"]), (0, True, True), row)
                    self.assertEqual(row["controls"], ["Priority", "Day/Night", "Status"])
                    self.assertEqual(row["menus"], {label: {"open": True, "inside": True, "wide": False} for label in ("Day/Night", "Status")})
                    self.assertEqual((row["wide"], w4.quiet(row["violations"])), (False, []))
                    if width == 390:
                        self.assertTrue(row["below"], row)
                    else:
                        self.assertTrue(0 <= row["gap"] <= 16, row)
                    if width == 1920:
                        self.assertTrue(row["row"], row)
            done = next(results)
            with self.subTest(browser=browser, width=width, step="behaviour"):
                self.assertNotIn("error", done, done)
                self.assertEqual(done["nightly"], {"badge": True, "picks": 3, "actions": ["Drain", "Suspend", "Resume"]})
                self.assertEqual((done["status"], done["order"]), ({"off": True, "on": True}, True), done)
                self.assertEqual((done["wide"], w4.quiet(done["violations"])), (False, []))

    def test_chromium_puts_priority_day_night_and_status_in_the_view_row_on_every_agents_view(self):
        data = self.drive(self.steps("chromium"), None, init=w4.GUARD)
        (OUT / "chromium-controls.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        self.check(data, "chromium")

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_puts_priority_day_night_and_status_in_the_view_row_on_every_agents_view(self):
        data = self.drive(self.steps("firefox"), None, "bidi.mjs", os.environ.get("FIREFOX", "firefox"), init=w4.GUARD)
        (OUT / "firefox-controls.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        self.check(data, "firefox")


if __name__ == "__main__":
    unittest.main()
