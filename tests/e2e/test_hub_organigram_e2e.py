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
from hub_support import iso

OUT = Path(os.environ.get("E2E_OUT", "/tmp/organigram-shots"))
CHART = """(async () => {@HELPERS@
  await screenShown(8000);
  const canvas = await until(() => {
    const found = document.querySelector("#main .organigram");
    return found && found.querySelectorAll(".org-links path.org-dashed").length >= 3 ? found : null;
  }, 8000);
  if (!canvas) {
    return {error: text(document.getElementById("main"))};
  }
  await sleep(300);
  canvas.closest(".org-chart").scrollIntoView({block: "start"});
  const scroll = canvas.closest(".org-scroll");
  const rect = (node) => node.getBoundingClientRect();
  const chair = rect(document.querySelector('#main .org-box[data-office="chair"]'));
  const staff = all("#main .org-staff .org-box").map((node) => [node, rect(node)]);
  const units = all("#main .org-units > .org-unit");
  const side = (box) => (box.right <= chair.left ? "left" : box.left >= chair.right ? "right" : "under");
  const icons = all("#main svg.bi").map((svg) => svg.parentElement).filter((owner) => !text(owner) && !(owner.getAttribute("title") && owner.getAttribute("aria-label")));
  return {
    title: text(document.getElementById("org-title")),
    offices: all("#main .org-chart .org-row[data-office]").map((row) => [row.dataset.office, row.dataset.position, text(row.querySelector(".org-holder"))]),
    staff: staff.map(([node, box]) => [node.dataset.office, side(box)]),
    staffBelowChair: staff.every(([, box]) => box.top > chair.bottom),
    unitsBelowStaff: units.every((unit) => staff.every(([, box]) => rect(unit).top > box.bottom)),
    units: units.map((unit) => [unit.dataset.node, all(".org-positions .org-box", unit).map((node) => node.dataset.office)]),
    dashed: all("#main .org-links path.org-dashed").map((path) => [path.dataset.from, path.dataset.to, getComputedStyle(path).strokeDasharray !== "none"]),
    solid: all("#main .org-links path.org-solid").length,
    also: all("#main .org-dotted").map((node) => [node.closest(".org-box").dataset.office, text(node)]),
    toggles: all("#main .org-toggle").map(name),
    scroll: {inner: scroll.scrollWidth > scroll.clientWidth + 1, overflow: getComputedStyle(scroll).overflowX},
    chairSeen: chair.left >= rect(scroll).left - 1 && chair.right <= rect(scroll).right + 1,
    wide: document.documentElement.scrollWidth > window.innerWidth + 1,
    unlabelled: icons.map((owner) => owner.outerHTML.slice(0, 120)),
  };
})()""".replace("@HELPERS@", base.HELPERS)
FOLD = """(async () => {@HELPERS@
  const toggle = all("#main .org-toggle").find((button) => name(button) === "Collapse: identity");
  toggle.click();
  await sleep(300);
  return {label: name(toggle), dashed: all("#main .org-links path.org-dashed").map((path) => `${path.dataset.from} > ${path.dataset.to}`), seen: all("#main .org-box[data-office]").filter((node) => node.offsetParent !== null).map((node) => node.dataset.office)};
})()""".replace("@HELPERS@", base.HELPERS)
UNFOLD = """(async () => {@HELPERS@
  const toggle = all("#main .org-toggle").find((button) => name(button) === "Expand: identity");
  toggle.click();
  await sleep(300);
  return {label: name(toggle), dashed: all("#main .org-links path.org-dashed").map((path) => `${path.dataset.from} > ${path.dataset.to}`)};
})()""".replace("@HELPERS@", base.HELPERS)
UNITS = """(async () => {@HELPERS@
  const unit = document.querySelector('#main .org-unit[data-node="group:work"]');
  const scroll = unit.closest(".org-scroll");
  const before = scroll.scrollLeft;
  unit.scrollIntoView({block: "start", inline: "start"});
  await sleep(300);
  const box = unit.querySelector(".org-unit-box").getBoundingClientRect();
  const frame = scroll.getBoundingClientRect();
  return {moved: scroll.scrollLeft > before, seen: box.left >= frame.left - 1 && box.right <= frame.right + 1, wide: document.documentElement.scrollWidth > window.innerWidth + 1, page: window.scrollX};
})()""".replace("@HELPERS@", base.HELPERS)
OFFICES = [
    ["chair", "chair", "Skills"],
    ["cluster/web", "staff", "Main"],
    ["stack-architecture", "staff", "Production"],
    ["identity/ldap", "line", "Experiment"],
    ["identity/oidc", "line", "Stage"],
    ["network/dns", "line", "Stage"],
    ["work/s2", "line", "Stage"],
    ["work/s3", "line", "Experiment"],
]
DASHED = [["identity/oidc", "identity/ldap", True], ["identity/oidc", "work/s3", True], ["stack-architecture", "network/dns", True]]


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestOrganigramE2E(HubCase):
    drive = base.OrchestratorE2ECase.drive

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        now = time.time()

        def held(office: str, session: str, name: str, work: str) -> dict:
            return {"office": office, "session": session, "runtime": "claude", "name": name, "since": iso(now - 7200), "beat": now - 30, "work": work}

        self.write_council({
            "chair/claim.json": held("chair", "s1", "Skills session", "allocate"),
            "identity/oidc/claim.json": held("identity/oidc", "s2", "Stage", "oidc line"),
            "network/dns/claim.json": held("network/dns", "s2", "Stage", "work/dns"),
            "work/s2/claim.json": held("work/s2", "s2", "Stage", "x"),
            "identity/ldap/claim.json": held("identity/ldap", "s3", "Experiment", "work/ldap"),
            "work/s3/claim.json": held("work/s3", "s3", "Experiment", "x"),
            "cluster/web/claim.json": held("cluster/web", "s4", "Main", "web cluster"),
            "stack-architecture/claim.json": held("stack-architecture", "s5", "Production", "stack"),
            "rasci.json": {
                "work/ldap": {"title": "LDAP sync", "status": "running", "worker": "Experiment", "roles": {"Experiment": "R", "Stage": "A"}},
                "work/dns": {"title": "DNS zones", "status": "running", "worker": "Stage", "roles": {"Stage": "R", "Production": "C"}},
                "work/s3": {"title": "Presidency", "status": "queued", "worker": "Experiment", "roles": {"Experiment": "R", "Stage": "C", "Operator": "A"}},
                "work/web": {"title": "Web cluster", "status": "running", "worker": "Main", "roles": {"Main": "RA", "Skills session": "C"}},
                "work/old": {"title": "Old", "status": "done", "worker": "Production", "roles": {"Production": "R", "Main": "A"}},
            },
        })
        self.base = f"http://{self.host}/"

    def test_chromium_draws_the_organigram_with_staff_beside_the_chair_and_dashed_superiors_at_three_widths(self):
        steps = []
        for width, height in base.WIDTHS:
            steps.append({"width": width, "height": height, "url": f"{self.base}?{width}#agents/hierarchy", "wait": 1200, "probe": CHART, "shot": str(OUT / f"chromium-{width}-organigram.png")})
            if width == 1366:
                steps.append({"width": width, "height": height, "url": None, "wait": 0, "probe": FOLD, "shot": str(OUT / f"chromium-{width}-organigram-folded.png")})
                steps.append({"width": width, "height": height, "url": None, "wait": 0, "probe": UNFOLD, "shot": None})
            if width == 390:
                steps.append({"width": width, "height": height, "url": None, "wait": 0, "probe": UNITS, "shot": str(OUT / f"chromium-{width}-organigram-units.png")})
        data = self.drive(steps, None)
        (OUT / "chromium-organigram.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        results = iter(data["results"])
        for width, _ in base.WIDTHS:
            chart = next(results)
            with self.subTest(width=width):
                self.assertNotIn("error", chart, chart)
                self.assertTrue(chart["title"].startswith("Organigram"), chart["title"])
                self.assertEqual(chart["offices"], OFFICES)
                self.assertEqual(chart["staff"], [["cluster/web", "right"], ["stack-architecture", "left"]])
                self.assertTrue(chart["staffBelowChair"] and chart["unitsBelowStaff"], chart)
                self.assertEqual(chart["units"], [["dimension:identity", ["identity/ldap", "identity/oidc"]], ["dimension:network", ["network/dns"]], ["group:work", ["work/s2", "work/s3"]]])
                self.assertEqual(chart["dashed"], DASHED)
                self.assertEqual(chart["solid"], 16)
                self.assertEqual(chart["also"], [["identity/ldap", "Also under identity/oidc (A)"], ["network/dns", "Also under stack-architecture (C)"], ["work/s3", "Also under identity/oidc (C)"]])
                self.assertEqual(chart["toggles"], ["Collapse: Operator", "Collapse: Chair", "Collapse: identity", "Collapse: network", "Collapse: Presidents"])
                self.assertEqual((chart["unlabelled"], chart["wide"], chart["scroll"]["overflow"], chart["chairSeen"]), ([], False, "auto", True))
                if width == 390:
                    self.assertTrue(chart["scroll"]["inner"], "the organigram does not scroll inside its container")
            if width == 1366:
                folded, unfolded = next(results), next(results)
                self.assertEqual((folded["label"], folded["dashed"]), ("Expand: identity", ["stack-architecture > network/dns"]))
                self.assertNotIn("identity/oidc", folded["seen"])
                self.assertEqual((unfolded["label"], len(unfolded["dashed"])), ("Collapse: identity", 3))
            if width == 390:
                moved = next(results)
                self.assertEqual((moved["moved"], moved["seen"], moved["wide"], moved["page"]), (True, True, False, 0), moved)


if __name__ == "__main__":
    unittest.main()
