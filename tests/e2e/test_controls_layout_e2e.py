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
import hub_support
from hub_case import HubCase
from hub_support import verifier

OUT = Path(os.environ.get("E2E_OUT", "/tmp/hub-029-shots"))
TEMPLATES = hub_support.HUB / "templates"
PRESENT = [f"/srv/p{index:02d}/.claude/settings.json" for index in range(10)]
ABSENT = [f"/srv/a{index:02d}/.claude/settings.json" for index in range(30)]
BROKEN = {PRESENT[3], PRESENT[7]}
READ = """
  const box = () => document.querySelector("#main .fw-controls");
  const tab = (id) => document.getElementById(`controls-tab-${id}`);
  const flush = () => {
    const head = box().querySelector(":scope > .box-head");
    const main = document.getElementById("main");
    return Boolean(head && head.querySelector('[role="tablist"]')) && Math.abs(head.getBoundingClientRect().top - main.getBoundingClientRect().top - parseFloat(getComputedStyle(main).borderTopWidth)) <= 1;
  };
  const width = (label) => {
    const node = document.querySelector(`#main section[aria-label="${label}"]`);
    return node && node.getClientRects().length ? node.getBoundingClientRect().width : null;
  };
  const misaligned = (form) => {
    const boxes = all("label", form).filter((label) => label.querySelector(".field") && label.getClientRects().length).map((label) => label.getBoundingClientRect());
    return boxes.filter((one, index) => boxes.slice(index + 1).some((two) => Math.min(one.bottom, two.bottom) - Math.max(one.top, two.top) > 0 && Math.abs(one.top - two.top) > 1)).length;
  };
  const forms = () => all("#main form").filter((form) => form.getClientRects().length).map((form) => [form.getAttribute("aria-label") || form.className, misaligned(form)]);
  const sources = () => all("#main tbody[data-source]").map((body) => body.dataset.source).filter((source) => source !== "hub");
  const toggle = () => document.querySelector("#main .fw-missing");
  const wide = () => document.documentElement.scrollWidth > innerWidth + 1;
"""
RULES = """(async () => {@HELPERS@@READ@
  if (!(await until(() => box() && sources().length === 10 && toggle(), 15000))) {
    return {error: text(document.getElementById("main")), sources: sources()};
  }
  tab("rules").click();
  const folded = {sources: sources(), toggle: text(toggle()), pressed: toggle().getAttribute("aria-pressed")};
  toggle().click();
  await until(() => sources().length === 40, 4000);
  const opened = {count: sources().length, last: sources().slice(-1)[0], toggle: text(toggle()), pressed: toggle().getAttribute("aria-pressed")};
  toggle().click();
  await until(() => sources().length === 10, 4000);
  return {folded, opened, flush: flush(), rules: width("Firewall rules"), forms: forms(), multiple: all("#main select[multiple]").length, wide: wide()};
})()"""
GROUPS = """(async () => {@HELPERS@@READ@
  tab("groups").click();
  const form = await until(() => width("Agent groups") && document.querySelector('#main form[aria-label="New agent group"]'), 4000);
  const chips = all('[aria-label="Members"] label.check-chip', form);
  const faces = chips.filter((chip) => chip.querySelector(".avatar svg")).length;
  form.querySelector('input[aria-label="Group name"]').value = "@NAME@";
  for (const chip of chips) {
    chip.querySelector("input").checked = ["Skills", "Stage"].includes(text(chip));
  }
  const lit = chips.filter((chip) => getComputedStyle(chip).backgroundColor !== getComputedStyle(chips.find((other) => !other.querySelector("input").checked)).backgroundColor).map(text);
  form.requestSubmit();
  const row = await until(() => document.querySelector('#main [data-group="@NAME@"]'), 8000);
  return {
    flush: flush(), groups: width("Agent groups"), sets: width("Rule sets"), chips: chips.map(text), faces, lit, row: row ? text(row.querySelector(".muted")) : null,
    emptyRules: text(document.querySelector('#main form[aria-label="New rule set"] .fw-chips-field p')), forms: forms(), multiple: all("#main select[multiple]").length, wide: wide(),
  };
})()"""


def probe(template: str, name: str) -> str:
    for key, value in {"@HELPERS@": base.HELPERS, "@READ@": READ, "@NAME@": name}.items():
        template = template.replace(key, value)
    return template


def view_files() -> list[dict]:
    present = [{"path": path, "exists": True, "folder": True, "sha256": "", "error": "unreadable: ValueError" if path in BROKEN else "", "settings": {}} for path in PRESENT]
    absent = [{"path": path, "exists": False, "folder": False, "sha256": "", "error": "no directory: create it first", "settings": {}} for path in ABSENT]
    return [*absent[:15], *reversed(present), *absent[15:]]


class TestControlsSource(unittest.TestCase):
    def test_no_controls_form_uses_a_multi_select(self):
        for name in ("page-rules.js", "page-firewall.js"):
            with self.subTest(name=name):
                self.assertNotIn("multiple", (TEMPLATES / name).read_text(encoding="utf-8"))


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestControlsLayout(HubCase):
    drive = base.OrchestratorE2ECase.drive

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        self.claim("s1", "Skills")
        self.claim("s2", "Stage")
        self.claim("s3", "Store")
        self.snapshot()
        verifier.write_private(self.state / "firewall" / "view.json", {"written": 0, "files": view_files()})
        self.page_url = f"http://localhost:{self.port}/"

    def test_chromium_lays_out_rules_and_groups_folds_missing_files_and_names_a_group_by_chips_at_three_widths(self):
        steps = []
        for width, height in base.WIDTHS:
            shot = OUT / f"chromium-{width}"
            steps += [
                {"width": width, "height": height, "url": f"{self.page_url}?{width}#stream/rules", "wait": 1500, "probe": probe(RULES, ""), "shot": f"{shot}-rules.png"},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(GROUPS, f"pair{width}"), "shot": f"{shot}-groups.png"},
            ]
        data = self.drive(steps, None)
        (OUT / "chromium-controls-layout.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        results = iter(data["results"])
        errors_first = [PRESENT[3], PRESENT[7], *[path for path in PRESENT if path not in BROKEN]]
        for width, _ in base.WIDTHS:
            rules, groups = next(results), next(results)
            with self.subTest(width=width):
                self.assertNotIn("error", rules, rules)
                self.assertEqual(rules["folded"], {"sources": errors_first, "toggle": "show 30 missing", "pressed": "false"})
                self.assertEqual(rules["opened"], {"count": 40, "last": ABSENT[-1], "toggle": "hide 30 missing", "pressed": "true"})
                self.assertTrue(rules["flush"], rules)
                self.assertTrue(groups["flush"], groups)
                self.assertAlmostEqual(groups["groups"], rules["rules"], delta=1)
                self.assertAlmostEqual(groups["sets"], rules["rules"], delta=1)
                self.assertEqual([count for _, count in rules["forms"] + groups["forms"]], [0] * (len(rules["forms"]) + len(groups["forms"])), (rules["forms"], groups["forms"]))
                self.assertEqual((rules["multiple"], groups["multiple"], rules["wide"], groups["wide"]), (0, 0, False, False))
                self.assertEqual((groups["chips"], groups["faces"], sorted(groups["lit"])), (["Skills", "Stage", "Store"], 3, ["Skills", "Stage"]))
                self.assertEqual(groups["row"], "Skills, Stage")
                self.assertTrue(groups["emptyRules"].startswith("No rule yet: create one under Rules"), groups["emptyRules"])
        self.assertEqual(sorted((group["name"], group["members"]) for group in self.httpd.hub.groups.listed()), sorted((f"pair{width}", ["s1", "s2"]) for width, _ in base.WIDTHS))


if __name__ == "__main__":
    unittest.main()
