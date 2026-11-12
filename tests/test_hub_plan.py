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
const kept = P.scoped(rows, "all", context).rows;
const stepsOf = (from, to) => P.steps(kept, P.burn(kept, {estimation: "none", from, to}).points, from);
const eta = (estimation) => Object.fromEntries([...P.etas(rows, edges, {now, estimation}).entries()].map(([task, found]) => [task, [found.start === null ? null : found.start / H, found.eta === null ? null : found.eta / H, found.forecast]]));
const D = 86400;
const burnt = [
  row("t/a", {status: "done", ended: true, start: 0, end: 2 * D}),
  row("t/b", {status: "done", ended: true, start: 0, end: 4 * D}),
  row("t/c", {status: "done", ended: true, start: 0, end: 6 * D}),
  row("t/d", {status: "running", start: 9 * D}),
  row("t/e", {}),
];
const burnPoints = P.burn(burnt, {estimation: "none", from: 0, to: 10 * D}).points;
const rising = P.burn([row("t/x", {}), row("t/y", {status: "running", start: 5 * D})], {estimation: "none", from: 0, to: 10 * D}).points;
const trendOf = (points, mode, days) => {
  const found = P.trend(points, {mode, days});
  return found && {start: found.start / D, forecast: found.forecast === null ? null : found.forecast / D, meets: found.forecast === null ? null : P.lineAt(found.lines.done, found.forecast) - P.lineAt(found.lines.scope, found.forecast), slope: found.lines.remaining.slope * D};
};
console.log(JSON.stringify({
  options: [P.FORECASTS, P.ESTIMATIONS, P.TRENDS, P.SORTS.map(([id]) => id), P.SERIES, P.TRENDED],
  burnt: burnPoints.map((point) => [point.t / D, point.remaining]),
  trends: {
    off: trendOf(burnPoints, "off", 7), regression: trendOf(burnPoints, "regression", 7), velocity7: trendOf(burnPoints, "velocity", 7), velocity30: trendOf(burnPoints, "velocity", 30),
    velocity3: trendOf(burnPoints, "velocity", 3), rising: trendOf(rising, "regression", 7), risingVelocity: trendOf(rising, "velocity", 7), single: trendOf(burnPoints.slice(-1), "regression", 7),
    beyondDates: P.trend([{t: 0, scope: 1, done: 0, remaining: 1}, {t: 1, scope: 1, done: 1e-13, remaining: 1 - 1e-13}], {mode: "regression", days: 7}).forecast,
  },
  steps: {whole: stepsOf(70 * H, now), window: stepsOf(90 * H, 99 * H), burnt: P.steps(burnt, burnPoints, 0)},
  etas: {none: eta("none"), points: eta("points"), loop: [...P.etas(loop, looped, {now, estimation: "none"}).keys()].sort()},
  medians: P.medians(rows),
  queueMedians: P.medians([...rows, row("queue/done", {kind: "queue", status: "done", ended: true, start: 0, end: 50 * H, points: 1})]),
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

    def test_the_selectors_offer_the_forecasts_estimations_trends_sort_modes_and_series(self):
        forecasts, estimations, trends, sorts, series, trended = self.data["options"]
        self.assertEqual(forecasts, [["always", "always"], ["points", "points only"], ["real", "real only"]])
        self.assertEqual(estimations, [["none", "No estimate"], ["points", "Story points"]])
        self.assertEqual(trends, [["off", "off"], ["regression", "linear regression"], ["velocity", "velocity"]])
        self.assertEqual(sorts, ["prio", "wsjf", "value", "complexity", "status", "start", "end", "agent", "title"])
        self.assertEqual((series, trended), (["scope", "done", "remaining", "unestimated"], ["scope", "done", "remaining"]))

    def test_the_regression_forecast_is_where_the_least_squares_line_of_remaining_reaches_zero_and_done_meets_scope(self):
        self.assertEqual(self.data["burnt"], [[0, 4], [2, 3], [4, 2], [6, 1], [9, 2], [10, 2]])
        found = self.data["trends"]["regression"]
        self.assertEqual(found["start"], 0)
        self.assertAlmostEqual(found["slope"], -86 / 461, places=9)
        self.assertAlmostEqual(found["forecast"], 760 / 43, places=9)
        self.assertAlmostEqual(found["meets"], 0, places=9)

    def test_the_velocity_forecast_runs_the_mean_rate_of_the_last_n_days_from_the_last_point(self):
        trends = self.data["trends"]
        self.assertEqual({key: trends[key]["start"] for key in ("velocity7", "velocity30")}, {"velocity7": 3, "velocity30": 0})
        self.assertAlmostEqual(trends["velocity7"]["forecast"], 24, places=9)
        self.assertAlmostEqual(trends["velocity30"]["forecast"], 20, places=9)
        self.assertAlmostEqual(trends["velocity7"]["slope"], -1 / 7, places=9)
        self.assertAlmostEqual(trends["velocity7"]["meets"], 0, places=9)

    def test_a_trend_that_never_falls_has_no_forecast_and_off_or_a_single_point_no_trend(self):
        trends = self.data["trends"]
        self.assertEqual((trends["velocity3"]["start"], trends["velocity3"]["forecast"]), (7, None))
        self.assertGreater(trends["velocity3"]["slope"], 0)
        self.assertEqual((trends["rising"]["forecast"], trends["risingVelocity"]["forecast"]), (None, None))
        self.assertEqual((trends["off"], trends["single"]), (None, None))

    def test_a_falling_trend_that_reaches_zero_only_after_the_last_date_has_no_forecast(self):
        self.assertIsNone(self.data["trends"]["beyondDates"])

    def test_each_point_lists_the_tasks_that_started_ended_or_joined_the_scope_at_its_step(self):
        steps = self.data["steps"]
        empty = {"started": [], "ended": [], "joined": []}
        self.assertEqual(steps["burnt"], [
            {"started": ["t/a", "t/b", "t/c"], "ended": [], "joined": ["t/e"]},
            {**empty, "ended": ["t/a"]}, {**empty, "ended": ["t/b"]}, {**empty, "ended": ["t/c"]}, {**empty, "started": ["t/d"]}, empty,
        ])
        self.assertEqual(steps["whole"], [
            {**empty, "joined": ["work/next", "work/tail"]}, {**empty, "started": ["work/a"]}, {**empty, "ended": ["work/a"]}, {**empty, "started": ["work/b"]},
            {**empty, "started": ["work/stop"]}, {**empty, "ended": ["work/stop"]}, {**empty, "ended": ["work/b"]}, {**empty, "started": ["work/c"]},
            {**empty, "ended": ["work/c"]}, {**empty, "started": ["work/run"]}, empty,
        ])
        self.assertEqual(steps["window"], [
            {"started": ["work/a", "work/b", "work/c", "work/stop"], "ended": ["work/a", "work/b", "work/stop"], "joined": ["work/next", "work/tail"]},
            {**empty, "ended": ["work/c"]}, {**empty, "started": ["work/run"]}, empty,
        ])

    def test_the_eta_is_the_end_when_ended_else_start_or_now_behind_the_predecessors_plus_the_forecast_length(self):
        ended = {"work/a": [80, 82, False], "work/b": [84, 88, False], "work/c": [90, 91, False], "work/stop": [85, 86, False], "operator/push": [None, 70, False]}
        self.assertEqual(self.data["etas"]["none"], {
            **ended, "work/run": [95, 97, True], "work/next": [100, 102, True], "work/tail": [102, 104, True], "queue/x": [100, 102, True],
        })
        self.assertEqual(self.data["etas"]["points"], {
            **ended, "work/run": [95, 102.5, True], "work/next": [102.5, 107, True], "work/tail": [107, 109, True], "queue/x": [102.5, 104.5, True],
        })
        self.assertEqual(self.data["etas"]["loop"], ["loop/a", "loop/b"])

    def test_medians_take_done_tasks_only_and_the_points_of_those_with_points(self):
        self.assertEqual(self.data["medians"], {"duration": 2 * HOUR, "perPoint": 1.5 * HOUR})
        self.assertEqual(self.data["median"], [None, 2, 2.5])

    def test_a_done_queue_job_never_moves_the_medians(self):
        self.assertEqual(self.data["queueMedians"], self.data["medians"])

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
