from __future__ import annotations

import json
import subprocess
import unittest

from hub_support import PLAN

HOUR = 3600
NOW = 100 * HOUR
PLAN_PROBE = """
const P = require(process.argv[1]);
const H = 3600;
const now = 100 * H;
const row = (task, fields) => ({task, kind: "task", status: "queued", ended: false, start: null, end: null, points: null, wsjf: null, value: null, worker: "-", title: "-", roles: {}, ...fields});
const rows = [
  row("work/a", {status: "done", ended: true, start: 80 * H, end: 82 * H, points: 2, worker: "Skills"}),
  row("work/b", {status: "done", ended: true, start: 84 * H, end: 88 * H, points: 2, roles: {Stage: "R"}}),
  row("work/c", {status: "done", ended: true, start: 90 * H, end: 91 * H}),
  row("work/run", {status: "running", start: 95 * H, points: 5, worker: "Stage"}),
  row("work/next", {points: 3}),
  row("work/tail", {}),
  row("work/stop", {status: "stopped", ended: true, start: 85 * H, end: 86 * H, points: 1}),
  row("queue/x", {kind: "queue", status: "awaiting"}),
  row("operator/push", {kind: "command", status: "done", ended: true, end: 70 * H}),
];
const edges = [
  {from: "work/run", to: "work/next", kind: "after"},
  {from: "work/next", to: "work/tail", kind: "after"},
  {from: "work/c", to: "work/tail", kind: "base"},
  {from: "work/run", to: "queue/x", kind: "queue"},
  {from: "work/gone", to: "work/tail", kind: "base"},
];
const loop = [row("loop/a", {}), row("loop/b", {})];
const looped = [{from: "loop/a", to: "loop/b", kind: "base"}, {from: "loop/b", to: "loop/a", kind: "queue"}];
const lay = (estimation, forecast) => P.bars(rows, edges, {now, estimation, forecast}).map((bar) => [bar.task, bar.start / H, bar.end / H, bar.forecast, bar.dot]);
const sorts = [
  row("t1", {wsjf: {score: 2}, value: 8, points: 3, status: "running", start: 5, worker: "Bravo", title: "Zulu"}),
  row("t2", {status: "done", start: 3, end: 9}),
  row("t3", {wsjf: {score: 5}, value: 3, points: 1, worker: "alpha", title: "Alpha"}),
  row("t4", {wsjf: {score: 2}, value: 13, points: 8, status: "blocked", start: 1, end: 4, worker: "Charlie", title: "mike"}),
];
const context = {filtered: [rows[0], rows[7]], since: 90 * H, until: 99 * H, now, holders: {"identity/oidc": "Stage"}};
const scope = (choice) => {
  const found = P.scoped(rows, choice, context);
  return {tasks: found.rows.map((entry) => entry.task), from: found.from / H, to: found.to / H};
};
const series = (estimation) => P.burn(P.scoped(rows, "all", context).rows, {estimation, from: 70 * H, to: now}).points.map((point) => [point.t / H, point.scope, point.done, point.remaining, point.unestimated]);
console.log(JSON.stringify({
  options: [P.FORECASTS, P.ESTIMATIONS, P.SORTS.map(([id]) => id), P.SERIES],
  medians: P.medians(rows),
  median: [P.median([]), P.median([3, 1, 2]), P.median([4, 1, 3, 2])],
  bars: {noneAlways: lay("none", "always"), pointsAlways: lay("points", "always"), pointsOnly: lay("points", "points"), noneOnly: lay("none", "points"), real: lay("points", "real")},
  loop: P.bars(loop, looped, {now, estimation: "none", forecast: "always"}).map((bar) => bar.task),
  empty: P.bars([row("work/new", {}), row("work/gone", {status: "done", ended: true})], [], {now, estimation: "none", forecast: "always"}),
  scopes: {all: scope("all"), filter: scope("filter"), agent: scope("agent:Stage"), line: scope("line:identity/oidc"), none: scope("agent:Nobody")},
  burn: {none: series("none"), points: series("points")},
  sorted: Object.fromEntries(P.SORTS.map(([id]) => [id, [P.sortRows(sorts, id, false).map((entry) => entry.task), P.sortRows(sorts, id, true).map((entry) => entry.task)]])),
  unknown: P.sortRows(sorts, "nope", false).map((entry) => entry.task),
}));
"""


class TestPlanModule(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        done = subprocess.run(["node", "-e", PLAN_PROBE, str(PLAN)], capture_output=True, text=True, timeout=60, check=True)
        cls.data = json.loads(done.stdout)

    def test_the_selectors_offer_the_forecasts_estimations_sort_modes_and_series(self):
        forecasts, estimations, sorts, series = self.data["options"]
        self.assertEqual(forecasts, [["always", "always"], ["points", "points only"], ["real", "real only"]])
        self.assertEqual(estimations, [["none", "No estimate"], ["points", "Story points"]])
        self.assertEqual(sorts, ["prio", "wsjf", "value", "complexity", "status", "start", "end", "agent", "title"])
        self.assertEqual(series, ["scope", "done", "remaining", "unestimated"])

    def test_medians_take_done_tasks_only_and_the_points_of_those_with_points(self):
        self.assertEqual(self.data["medians"], {"duration": 2 * HOUR, "perPoint": 1.5 * HOUR})
        self.assertEqual(self.data["median"], [None, 2, 2.5])

    def test_without_estimate_a_forecast_is_as_long_as_the_median_duration_behind_its_predecessors(self):
        self.assertEqual(self.data["bars"]["noneAlways"], [
            ["work/a", 80, 82, False, False],
            ["work/b", 84, 88, False, False],
            ["work/c", 90, 91, False, False],
            ["work/run", 95, 100, False, False],
            ["work/next", 100, 102, True, False],
            ["work/tail", 102, 104, True, False],
            ["work/stop", 85, 86, False, False],
            ["queue/x", 100, 102, True, False],
            ["operator/push", 70, 70, False, True],
        ])

    def test_with_story_points_a_forecast_is_points_times_the_median_hours_per_point(self):
        bars = {task: rest for task, *rest in self.data["bars"]["pointsAlways"]}
        self.assertEqual(bars["work/next"], [100, 104.5, True, False])
        self.assertEqual(bars["work/tail"], [104.5, 106.5, True, False])

    def test_points_only_draws_a_dot_behind_the_predecessors_of_a_task_without_estimate(self):
        only = {task: rest for task, *rest in self.data["bars"]["pointsOnly"]}
        self.assertEqual((only["work/next"], only["work/tail"], only["queue/x"]), ([100, 104.5, True, False], [104.5, 104.5, True, True], [100, 100, True, True]))
        none = {task: rest for task, *rest in self.data["bars"]["noneOnly"]}
        self.assertEqual((none["work/next"], none["work/tail"]), ([100, 100, True, True], [100, 100, True, True]))

    def test_real_only_draws_no_forecast(self):
        self.assertEqual([task for task, *_ in self.data["bars"]["real"]], ["work/a", "work/b", "work/c", "work/run", "work/stop", "operator/push"])
        self.assertFalse(any(bar[3] for bar in self.data["bars"]["real"]))

    def test_a_cycle_still_draws_every_task_no_done_task_means_a_dot_and_an_ended_task_without_times_no_bar(self):
        self.assertEqual(self.data["loop"], ["loop/a", "loop/b"])
        self.assertEqual(self.data["empty"], [{"task": "work/new", "start": NOW, "end": NOW, "forecast": True, "dot": True}])

    def test_the_scopes_are_the_whole_register_the_filter_in_its_window_and_one_agent_or_line(self):
        work = ["work/a", "work/b", "work/c", "work/run", "work/next", "work/tail", "work/stop"]
        scopes = self.data["scopes"]
        self.assertEqual(scopes["all"], {"tasks": work, "from": 80, "to": 100})
        self.assertEqual(scopes["filter"], {"tasks": ["work/a"], "from": 90, "to": 99})
        self.assertEqual(scopes["agent"], {"tasks": ["work/b", "work/run"], "from": 84, "to": 100})
        self.assertEqual(scopes["line"], scopes["agent"])
        self.assertEqual(scopes["none"], {"tasks": [], "from": 76, "to": 100})

    def test_without_estimate_the_burn_counts_tasks(self):
        self.assertEqual(self.data["burn"]["none"], [
            [70, 2, 0, 2, 0], [80, 3, 0, 3, 0], [82, 3, 1, 2, 0], [84, 4, 1, 3, 0], [85, 5, 1, 4, 0], [86, 4, 1, 3, 0],
            [88, 4, 2, 2, 0], [90, 5, 2, 3, 0], [91, 5, 3, 2, 0], [95, 6, 3, 3, 0], [100, 6, 3, 3, 0],
        ])

    def test_with_story_points_the_burn_sums_complexity_and_counts_the_unestimated_apart(self):
        burn = self.data["burn"]["points"]
        self.assertEqual(burn[0], [70, 3, 0, 3, 1])
        self.assertEqual(burn[-1], [100, 12, 4, 8, 1])
        self.assertEqual([point[4] for point in burn], [1, 1, 1, 1, 1, 1, 1, 2, 1, 1, 1])

    def test_the_list_sorts_by_every_mode_in_both_directions_with_missing_keys_last(self):
        self.assertEqual(self.data["sorted"], {
            "prio": [["t1", "t2", "t3", "t4"], ["t4", "t3", "t2", "t1"]],
            "wsjf": [["t1", "t4", "t3", "t2"], ["t3", "t1", "t4", "t2"]],
            "value": [["t3", "t1", "t4", "t2"], ["t4", "t1", "t3", "t2"]],
            "complexity": [["t3", "t1", "t4", "t2"], ["t4", "t1", "t3", "t2"]],
            "status": [["t3", "t1", "t4", "t2"], ["t2", "t4", "t1", "t3"]],
            "start": [["t4", "t2", "t1", "t3"], ["t1", "t2", "t4", "t3"]],
            "end": [["t4", "t2", "t1", "t3"], ["t2", "t4", "t1", "t3"]],
            "agent": [["t3", "t1", "t4", "t2"], ["t4", "t1", "t3", "t2"]],
            "title": [["t3", "t4", "t2", "t1"], ["t1", "t2", "t4", "t3"]],
        })
        self.assertEqual(self.data["unknown"], ["t1", "t2", "t3", "t4"])


if __name__ == "__main__":
    unittest.main()
