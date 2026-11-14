from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ORGANIGRAM = Path(__file__).resolve().parent.parent / "orchestrator" / "templates" / "organigram.js"
PROBE = """
const O = require(process.argv[1]);
const claim = (office, kind, agent, fields) => {
  const [dimension, line] = kind === "line" ? office.split("/") : ["", ""];
  return {office, kind, dimension, line, agent, session: agent ? `s-${agent}` : "s9", work: "-", beat: null, ...fields};
};
const claims = [
  claim("work/s3", "work", "Experiment"),
  claim("stack-architecture", "other", "Production"),
  claim("identity/oidc", "line", "Stage"),
  claim("chair", "chair", "Skills"),
  claim("cluster/web", "cluster", "Main"),
  claim("network/dns", "line", "Stage"),
  claim("identity/ldap", "line", "Experiment", {work: "work/ldap"}),
  claim("work/s2", "work", "Stage"),
  claim("work/s9", "work", ""),
];
const task = (name, roles, fields) => ({task: name, ended: false, worker: "-", roles, ...fields});
const tasks = [
  task("work/ldap", {Experiment: "R", Stage: "A"}),
  task("work/dns", {Stage: "R", Production: "C", Experiment: "I"}),
  task("work/web", {Main: "RA", Skills: "C"}),
  task("work/old", {Production: "R", Main: "A"}, {ended: true}),
  task("work/s3", {Experiment: "R", Stage: "C", Operator: "A"}),
  task("work/ldap2", {Experiment: "R", Stage: "AC"}),
  task("work/worker", {Main: "C"}, {worker: "Production"}),
  task("work/support", {Stage: "R", Main: "S", Production: "I"}),
  task("queue/gate-1", {}),
];
const chart = O.chart(claims);
const box = (left, top, width, height) => ({left, top, right: left + width, bottom: top + height});
const unit = (left) => ({box: box(left, 300, 200, 40), positions: [box(left + 30, 360, 200, 60), box(left + 30, 440, 200, 60)]});
console.log(JSON.stringify({
  positions: Object.fromEntries(claims.map((entry) => [entry.office, O.position(entry)])),
  unknown: O.position(claim("odd", "mystery", "X")),
  chart: {
    chair: chart.chair && chart.chair.office,
    staff: chart.staff.map((entry) => entry.office),
    units: chart.units.map((entry) => [entry.id, entry.kind, entry.label, entry.positions.map((position) => position.office)]),
  },
  vacant: O.chart(claims.filter((entry) => entry.kind !== "chair")).chair,
  edges: O.dotted(claims, tasks),
  quiet: O.dotted(claims, tasks.map((entry) => ({...entry, ended: true}))),
  solid: O.solid({root: box(400, 0, 200, 50), chair: box(400, 90, 200, 80), staff: [box(560, 200, 200, 60), box(240, 200, 200, 60)], units: [unit(100), unit(700)]}),
  lonely: O.solid({root: box(400, 0, 200, 50), chair: box(400, 90, 200, 80), staff: [], units: []}),
  below: O.dashed(box(0, 0, 100, 40), box(300, 200, 100, 40)),
  column: O.dashed(box(0, 0, 100, 40), box(0, 200, 100, 40)),
  beside: O.dashed(box(300, 0, 100, 40), box(0, 20, 100, 40)),
}));
"""


@unittest.skipUnless(shutil.which("node"), "no node")
class TestOrganigram(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        done = subprocess.run(["node", "-e", PROBE, str(ORGANIGRAM)], capture_output=True, text=True, timeout=60, check=True)
        cls.data = json.loads(done.stdout)

    def test_domain_chairs_and_presidents_stand_in_line_and_organizers_and_single_offices_are_staff(self):
        self.assertEqual(self.data["positions"], {
            "work/s3": "line", "stack-architecture": "staff", "identity/oidc": "line", "chair": "chair", "cluster/web": "staff",
            "network/dns": "line", "identity/ldap": "line", "work/s2": "line", "work/s9": "line",
        })
        self.assertEqual(self.data["unknown"], "staff")

    def test_the_chart_puts_the_dimensions_by_name_then_the_presidents_under_the_chair_and_the_staff_beside_it(self):
        self.assertEqual(self.data["chart"], {
            "chair": "chair",
            "staff": ["cluster/web", "stack-architecture"],
            "units": [
                ["dimension:identity", "dimension", "identity", ["identity/ldap", "identity/oidc"]],
                ["dimension:network", "dimension", "network", ["network/dns"]],
                ["group:work", "work", "Presidents", ["work/s2", "work/s3", "work/s9"]],
            ],
        })
        self.assertIsNone(self.data["vacant"])

    def test_an_office_holder_named_a_or_c_on_an_open_task_becomes_a_dashed_superior(self):
        self.assertEqual(self.data["edges"], [
            {"from": "cluster/web", "to": "stack-architecture", "letters": "C", "tasks": ["work/worker"]},
            {"from": "identity/oidc", "to": "identity/ldap", "letters": "AC", "tasks": ["work/ldap", "work/ldap2"]},
            {"from": "identity/oidc", "to": "work/s3", "letters": "C", "tasks": ["work/s3"]},
            {"from": "stack-architecture", "to": "identity/oidc", "letters": "C", "tasks": ["work/dns"]},
        ])

    def test_ended_tasks_the_chair_s_own_line_and_parties_without_an_office_draw_no_dashed_line(self):
        self.assertEqual(self.data["quiet"], [])
        drawn = {(edge["from"], edge["to"]) for edge in self.data["edges"]}
        self.assertFalse({edge for edge in drawn if edge[0] == "chair" or "Operator" in edge})
        self.assertNotIn(("cluster/web", "identity/oidc"), drawn)

    def test_the_solid_lines_join_root_chair_staff_rail_and_combs(self):
        self.assertEqual(self.data["solid"], [
            "M 500 50 V 70 H 500 V 90",
            "M 500 170 L 500 282",
            "M 500 230 L 560 230",
            "M 500 230 L 440 230",
            "M 200 282 L 800 282",
            "M 200 282 L 200 300",
            "M 800 282 L 800 300",
            "M 118 340 L 118 470",
            "M 118 390 L 130 390",
            "M 118 470 L 130 470",
            "M 718 340 L 718 470",
            "M 718 390 L 730 390",
            "M 718 470 L 730 470",
        ])
        self.assertEqual(self.data["lonely"], ["M 500 50 V 70 H 500 V 90"])

    def test_a_dashed_line_leaves_the_facing_edges_and_rounds_a_shared_column_on_the_right(self):
        self.assertEqual(self.data["below"], "M 50 40 C 50 120 350 120 350 200")
        self.assertEqual(self.data["column"], "M 100 20 C 136 20 136 220 100 220")
        self.assertEqual(self.data["beside"], "M 300 20 C 200 20 200 40 100 40")


if __name__ == "__main__":
    unittest.main()
