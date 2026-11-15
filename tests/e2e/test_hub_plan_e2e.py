from __future__ import annotations

import json
import math
import os
import shutil
import sys
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

import hub_e2e_kit as base
from hub_e2e_kit import GRAPH_HOOK, OUT, WIDTHS
from hub_e2e_plan import (
    BULK,
    BURN,
    ETA_LIST,
    GANTT,
    PLAN_VALUES,
    POINTS_ON,
    REQUEST,
    STATUS_ORDER,
    STEP_TIPS,
    TASKS_3D,
    TREND_DAYS,
    TREND_RELOADED,
    TREND_SET,
)
from hub_e2e_views import CAMERA
from hub_support import iso
from kvb_orchestrator import skill_scripts


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestHubPlan(base.OrchestratorE2ECase):
    def plan_work(self, now: float) -> None:
        register = json.loads((self.council / "rasci.json").read_text(encoding="utf-8"))
        register["work/feature"]["start"] = iso(now - 1800)
        register["work/stage"]["start"] = iso(now - 900)
        register.update({
            "work/done-a": {"title": "Done A", "status": "done", "worker": "Stage", "branch": "feature/base", "start": iso(now - 36000), "end": iso(now - 28800), "roles": {"Stage": "RA"}, "estimates": {"Stage": {"value": 5, "complexity": 2}}},
            "work/done-b": {"title": "Done B", "status": "done", "worker": "Docs", "start": iso(now - 25200), "end": iso(now - 10800), "roles": {"Docs": "RA"}, "estimates": {"Docs": {"value": 3, "complexity": 2}}},
            "work/done-c": {"title": "Done C", "status": "done", "worker": "Docs", "start": iso(now - 14400), "end": iso(now - 10800), "roles": {"Docs": "RA"}},
            "work/next": {"title": "Next step", "status": "queued", "after": ["work/feature"], "roles": {"Skills": "R", "Maintainer": "A"}, "estimates": {"Skills": {"value": 8, "complexity": 3}}},
            "work/child": {"title": "Child of the base", "status": "queued", "base": "feature/base", "roles": {"Docs": "RA"}},
        })
        queue = json.loads((self.council / "queue.json").read_text(encoding="utf-8"))
        queue["entries"] += [
            {"id": "deploy-4", "seq": 4, "kind": "deploy", "task": "work/stage", "workdir": "/repo", "session": "s2", "name": "Stage", "hotfix": None, "status": "active", "enqueued": now - 400, "granted": now - 300, "cmd": "make deploy"},
            {"id": "test-5", "seq": 5, "kind": "test", "task": "work/docs", "workdir": "/repo", "session": "s2", "name": "Docs", "hotfix": None, "status": "waiting", "enqueued": now - 60, "granted": None, "cmd": "make test"},
        ]
        self.write_council({"rasci.json": register, "queue.json": queue})

    def plan_steps(self, browser: str, signs: bool) -> list[dict]:
        local = f"http://localhost:{self.port}/"
        flag = "true" if signs else "false"
        steps = []
        for width, height in WIDTHS:
            bulk = BULK.replace("@SIGNS@", flag).replace("@VALUE@", PLAN_VALUES[width])
            steps += [
                {"width": width, "height": height, "url": f"{local}?{width}#tasks/gantt", "wait": 1200, "probe": GANTT, "shot": str(OUT / f"{browser}-{width}-tasks-gantt.png")},
                {"width": width, "height": height, "url": f"{local}?{width}#tasks/burn", "wait": 900, "probe": BURN, "shot": str(OUT / f"{browser}-{width}-tasks-burn.png")},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": POINTS_ON, "shot": None},
                {"width": width, "height": height, "url": f"{local}?{width}-reloaded#tasks/burn", "wait": 1200, "probe": REQUEST, "shot": str(OUT / f"{browser}-{width}-tasks-burn-points.png")},
                {"width": width, "height": height, "url": f"{local}?{width}-points#tasks/gantt", "wait": 1200, "probe": GANTT, "shot": str(OUT / f"{browser}-{width}-tasks-gantt-points.png")},
                {"width": width, "height": height, "url": f"{local}?{width}-list#tasks/list", "wait": 1200, "probe": bulk, "shot": str(OUT / f"{browser}-{width}-tasks-business-value.png")},
            ]
        return steps

    def planned(self, probe: dict, points: bool) -> None:
        hour = 3600
        edges = [["after", "work/feature", "work/next"], ["base", "work/done-a", "work/child"], ["queue", "queue/deploy-4", "queue/gate-3"], ["queue", "queue/gate-3", "queue/test-5"]]
        self.assertEqual(probe["forecast"], ["always", [["always", "always"], ["points", "points only"], ["real", "real only"]]])
        self.assertEqual(probe["modes"], [["none", str(not points).lower()], ["points", str(points).lower()]])
        self.assertEqual((probe["request"], probe["inner"]), (points, True))
        self.assertEqual(sorted([kind, start, end] for kind, start, end, _ in probe["edges"]), sorted(edges))
        self.assertEqual({tip for *_, tip in probe["edges"]}, {"url(#gantt-tip)"})
        bars = {task: (forecast, start, end, tag) for task, forecast, start, end, tag in probe["bars"]}
        self.assertNotIn("operator/push", bars)
        self.assertEqual((bars["work/old"][0], bars["work/old"][3]), (False, "circle"))
        self.assertEqual([bars[task][0] for task in ("work/feature", "work/stage", "queue/deploy-4", "work/done-a")], [False] * 4)
        self.assertGreaterEqual(bars["work/feature"][2] - bars["work/feature"][1], 1800)
        forecasts = ("work/next", "work/docs", "work/child", "queue/gate-3", "queue/test-5")
        lengths = {task: round(bars[task][2] - bars[task][1], 3) for task in forecasts}
        self.assertEqual(lengths, {"work/next": (4.5 if points else 2) * hour, "work/docs": (3 if points else 2) * hour, "work/child": 2 * hour, "queue/gate-3": 2 * hour, "queue/test-5": 2 * hour})
        self.assertTrue(all(bars[task][0] for task in forecasts))
        self.assertEqual((bars["work/next"][1], bars["queue/test-5"][1]), (bars["work/feature"][2], bars["queue/gate-3"][2]))
        self.assertTrue(probe["hatched"] and all(probe["hatched"]), probe["hatched"])
        self.assertEqual(probe["real"], 0)
        only = {task: (round(length, 3), tag) for task, length, tag in probe["pointsOnly"]}
        dot = (0, "circle")
        self.assertEqual(only, {"work/next": (4.5 * hour, "rect") if points else dot, "work/docs": (3 * hour, "rect") if points else dot, "work/child": dot, "queue/gate-3": dot, "queue/test-5": dot})

    def check_plan(self, browser: str, driver: str, binary: str, signs: bool) -> None:
        """Args:
            signs: cdp.mjs signs the bulk business value with its virtual
                passkey; bidi.mjs has no virtual authenticator, so the probe
                answers the prompt the way a canceled passkey dialog does.
        """
        self.plan_work(time.time())
        authenticator = self.authenticator()
        data = self.drive(self.plan_steps(browser, signs), authenticator if signs else None, driver, binary)
        (OUT / f"{browser}-plan.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "(style-src-elem)" not in error and "/favicon.ico" not in error], [])
        rows = self.snapshot()["tasks"]
        ranked = list(enumerate(rows))
        status_up = [row["task"] for _, row in sorted(ranked, key=lambda pair: (STATUS_ORDER.index(pair[1]["status"]), pair[0]))]
        status_down = [row["task"] for _, row in sorted(ranked, key=lambda pair: (-STATUS_ORDER.index(pair[1]["status"]), pair[0]))]
        for index, (width, _) in enumerate(WIDTHS):
            gantt, burn, points_on, request, gantt_points, bulk = data["results"][6 * index : 6 * (index + 1)]
            value = PLAN_VALUES[width]
            items = [["work/next", f"estimate work/next Operator --value {value}"], ["work/child", f"estimate work/child Operator --value {value}"]]
            with self.subTest(browser=browser, width=width):
                for probe in (gantt, burn, points_on, request, gantt_points, bulk):
                    self.assertNotIn("error", probe)
                    self.assertEqual((probe["tall"], probe["wide"], probe["layout"]), (False, False, ["toolbar", "chips", "body"]), probe)
                    self.assertEqual(probe["rows"] == 1, width != 390, probe)
                self.planned(gantt, points=False)
                self.planned(gantt_points, points=True)
                self.assertEqual((burn["modes"], burn["request"]), ([["none", "true"], ["points", "false"]], False))
                self.assertEqual(burn["scope"][0], "all")
                self.assertEqual(burn["scope"][1][:2], ["all", "filter"])
                self.assertIn("agent:Docs", burn["scope"][1])
                self.assertIn("line:identity/oidc", burn["scope"][1])
                self.assertEqual(burn["series"], [["scope", 9], ["done", 4], ["remaining", 5]])
                self.assertEqual(burn["agent"], [["scope", 5], ["done", 2], ["remaining", 3]])
                self.assertEqual(points_on["before"], {"modes": [["none", "true"], ["points", "false"]], "request": False})
                self.assertEqual((points_on["modes"], points_on["request"]), ([["none", "false"], ["points", "true"]], True))
                self.assertEqual(request["modes"], [["none", "false"], ["points", "true"]])
                self.assertEqual(request["series"], [["scope", 12], ["done", 4], ["remaining", 8], ["unestimated", 2]])
                self.assertTrue(request["toast"].startswith(f"Request estimates: {'done' if signs else 'not signed'}"), request["toast"])
                self.assertEqual(bulk["sorts"], ["prio", "wsjf", "value", "complexity", "status", "start", "end", "agent", "title"])
                self.assertEqual((bulk["prio"], bulk["status"], bulk["statusDown"]), ([row["task"] for row in rows], status_up, [status_down, "Descending"]))
                self.assertEqual((bulk["picks"], bulk["armed"]), (["work/feature", "work/next", "work/docs", "work/child", "work/stage"], [False, "2"]))
                self.assertTrue(bulk["toast"].startswith(f"Business value {value} for 2 tasks: {'handed to the runner' if signs else 'not signed'}"), bulk["toast"])
                signed = [["/api/sign", ["items"], items]]
                self.assertEqual((bulk["asked"], bulk["posted"]), (1, [*signed, ["/api/tasks", ["items", "proof"], items]] if signs else signed))
                self.assertEqual((bulk["after"], bulk["reset"]), ([True, 0] if signs else [False, 2], True))
        self.assertEqual([args for script, args in self.scripts.calls if script == skill_scripts.ESTIMATE], [["request", "--session", "Operator"]] * (len(WIDTHS) if signs else 0))
        self.assertEqual(self.httpd.hub.settings.get()["estimation"], "none")
        jobs = self.runner_jobs()
        if not signs:
            self.assertEqual(jobs, [])
            register = json.loads((self.council / "rasci.json").read_text(encoding="utf-8"))
            self.assertEqual([task for task, row in register.items() if "Operator" in row.get("estimates", {})], [])
            return
        self.assertEqual([job["argv"][-1] for job in jobs], [PLAN_VALUES[width] for width, _ in WIDTHS for _ in range(2)])
        self.run_runner()
        register = json.loads((self.council / "rasci.json").read_text(encoding="utf-8"))
        self.assertEqual({task: register[task]["estimates"]["Operator"] for task in ("work/next", "work/child")}, {"work/next": {"value": 34, "at": register["work/next"]["estimates"]["Operator"]["at"]}, "work/child": {"value": 34, "at": register["work/child"]["estimates"]["Operator"]["at"]}})
        rows = {row["task"]: row for row in self.snapshot()["tasks"]}
        self.assertEqual((rows["work/next"]["wsjf"], rows["work/child"]["wsjf"], rows["work/child"]["value"]), ({"value": 34, "complexity": 3, "score": 11.33}, None, 34))

    def test_chromium_draws_the_gantt_and_burn_switches_the_estimation_requests_estimates_and_signs_a_bulk_business_value_at_three_widths(self):
        self.check_plan("chromium", "cdp.mjs", os.environ.get("CHROMIUM", "chromium"), signs=True)

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_draws_the_gantt_and_burn_and_asks_the_passkey_for_a_bulk_business_value_storing_nothing_unsigned(self):
        self.check_plan("firefox", "bidi.mjs", os.environ.get("FIREFOX", "firefox"), signs=False)

    def trend_work(self, now: float) -> None:
        day = 86400
        register = {
            "work/t1": {"title": "First", "status": "done", "worker": "Stage", "start": iso(now - 10 * day), "end": iso(now - 8 * day), "roles": {"Stage": "RA"}, "estimates": {"Stage": {"value": 5, "complexity": 1}}},
            "work/t2": {"title": "Second", "status": "done", "worker": "Docs", "start": iso(now - 10 * day), "end": iso(now - 6 * day), "roles": {"Docs": "RA"}, "estimates": {"Docs": {"value": 3, "complexity": 2}}},
            "work/t3": {"title": "Third", "status": "done", "worker": "Docs", "branch": "feature/t3", "start": iso(now - 10 * day), "end": iso(now - 4 * day), "roles": {"Docs": "RA"}, "estimates": {"Docs": {"value": 3, "complexity": 3}}},
            "work/t4": {"title": "Fourth", "status": "running", "worker": "Stage", "start": iso(now - day), "roles": {"Stage": "RA"}, "estimates": {"Stage": {"value": 8, "complexity": 5}}},
            "work/t5": {"title": "Fifth", "status": "queued", "after": ["work/t4"], "roles": {"Skills": "R"}, "estimates": {"Skills": {"value": 8, "complexity": 3}}},
            "work/t6": {"title": "Sixth", "status": "queued", "base": "feature/t3", "roles": {"Docs": "RA"}},
        }
        queue = {"seq": 2, "entries": [
            {"id": "deploy-1", "seq": 1, "kind": "deploy", "task": "work/t4", "workdir": "/repo", "session": "s2", "name": "Stage", "hotfix": None, "status": "active", "enqueued": now - 400, "granted": now - 300, "cmd": "make deploy"},
            {"id": "test-2", "seq": 2, "kind": "test", "task": "work/t5", "workdir": "/repo", "session": "s2", "name": "Docs", "hotfix": None, "status": "waiting", "enqueued": now - 60, "granted": None, "cmd": "make test"},
        ]}
        self.write_council({"rasci.json": register, "queue.json": queue})

    def trend_steps(self, browser: str) -> list[dict]:
        local = f"http://localhost:{self.port}/"
        steps = []
        for width, height in WIDTHS:
            days = str(TREND_DAYS[width])
            steps += [
                {"width": width, "height": height, "url": f"{local}?{width}#tasks/list", "wait": 1200, "probe": ETA_LIST, "shot": str(OUT / f"{browser}-{width}-tasks-eta.png")},
                {"width": width, "height": height, "url": f"{local}?{width}#tasks/burn", "wait": 900, "probe": TREND_SET.replace("@MODE@", "regression").replace("@DAYS@", days), "shot": str(OUT / f"{browser}-{width}-tasks-burn-regression.png")},
                {"width": width, "height": height, "url": f"{local}?{width}-regression#tasks/burn", "wait": 1200, "probe": TREND_RELOADED, "shot": None},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": TREND_SET.replace("@MODE@", "velocity").replace("@DAYS@", days), "shot": str(OUT / f"{browser}-{width}-tasks-burn-velocity.png")},
                {"width": width, "height": height, "url": f"{local}?{width}-velocity#tasks/burn", "wait": 1200, "probe": TREND_RELOADED, "shot": None},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": STEP_TIPS, "shot": str(OUT / f"{browser}-{width}-tasks-burn-steps.png")},
                {"width": width, "height": height, "url": f"{local}?{width}-3d#tasks/3d", "wait": 1200, "probe": TASKS_3D, "shot": str(OUT / f"{browser}-{width}-tasks-3d.png")},
                {"width": width, "height": height, "url": f"{local}?{width}-camera#tasks/3d", "wait": 900, "probe": CAMERA, "shot": str(OUT / f"{browser}-{width}-tasks-3d-steady-camera.png")},
            ]
        return steps

    def eta_checked(self, probe: dict, mode: str, rows: dict, edges: list[dict], window: tuple[float, float]) -> None:
        """Args:
            probe: task -> [start, eta, forecast, text, title] as the list shows it.
            mode: the estimation mode the list was drawn in.
            rows: the snapshot's task rows by task.
            edges: the snapshot's task edges.
            window: the earliest and latest time the page can have taken as now.
        """
        day = 86400
        points = {"none": {}, "points": {"work/t4": 10 * day, "work/t5": 6 * day}}[mode]
        self.assertEqual(sorted(probe), sorted(rows))
        for task, (start, eta, forecast, words, title) in probe.items():
            with self.subTest(mode=mode, task=task):
                row = rows[task]
                self.assertTrue(words.startswith("ETA ") and words != "ETA –", words)
                if row["ended"]:
                    self.assertEqual((eta, forecast, title), (row["end"], False, "ETA: the end of the ended task"))
                    continue
                self.assertTrue(forecast)
                self.assertAlmostEqual(eta - start, points.get(task, 4 * day), delta=0.01)
                ahead = [probe[edge["from"]][1] for edge in edges if edge["to"] == task and edge["from"] in probe and edge["from"] != task]
                if row["start"] is not None:
                    self.assertEqual(start, row["start"])
                elif ahead and max(ahead) > window[1]:
                    self.assertAlmostEqual(start, max(ahead), delta=0.01)
                else:
                    self.assertTrue(window[0] <= start <= window[1], (start, window))

    def trend_forecast(self, points: list[list[float]], mode: str, days: int) -> tuple[float, float | None]:
        """Args:
            points: [t, remaining] of the drawn burndown points.

        Returns:
            The trend's start and the time its remaining line reaches 0
            (None when it never falls), computed here independently of plan.js.
        """
        last_t, last_y = points[-1]
        if mode == "regression":
            mean_t = sum(t for t, _ in points) / len(points)
            mean_y = sum(y for _, y in points) / len(points)
            slope = sum((t - mean_t) * (y - mean_y) for t, y in points) / sum((t - mean_t) ** 2 for t, _ in points)
            return points[0][0], (mean_t - mean_y / slope if slope < 0 else None)
        start = max(points[0][0], last_t - days * 86400)
        before = [y for t, y in points if t <= start][-1]
        slope = (last_y - before) / (last_t - start)
        return start, (last_t - last_y / slope if slope < 0 else None)

    def trended(self, probe: dict, mode: str, days: int) -> None:
        start, forecast = self.trend_forecast(probe["points"], mode, days)
        self.assertEqual(probe["value"], mode)
        self.assertEqual(probe["days"], [days, mode == "velocity"])
        self.assertEqual(sorted(series for series, *_ in probe["lines"]), ["done", "remaining", "scope"])
        for _, begin, end in probe["lines"]:
            self.assertAlmostEqual(begin, start, delta=0.01)
            self.assertAlmostEqual(end, forecast if forecast is not None else probe["points"][-1][0], delta=0.01)
        if forecast is None:
            self.assertEqual((probe["note"], probe["marker"]), ([None, "∞"], None))
            return
        self.assertAlmostEqual(probe["note"][0], forecast, delta=0.01)
        self.assertAlmostEqual(probe["marker"], forecast, delta=0.01)
        self.assertNotEqual(probe["note"][1], "∞", probe["note"])

    def check_trend_eta_3d(self, browser: str, driver: str, binary: str) -> None:
        self.trend_work(time.time())
        begun = time.time()
        data = self.drive(self.trend_steps(browser), None, driver, binary, init=GRAPH_HOOK)
        ended = time.time()
        (OUT / f"{browser}-trend-eta-3d.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "(style-src-elem)" not in error and "/favicon.ico" not in error], [])
        snapshot = self.snapshot()
        rows = {row["task"]: row for row in snapshot["tasks"]}
        edges = snapshot["task_edges"]
        self.assertEqual(sorted([edge["kind"], edge["from"], edge["to"]] for edge in edges), [["after", "work/t4", "work/t5"], ["base", "work/t3", "work/t6"], ["queue", "queue/deploy-1", "queue/test-2"]])
        trends = [["off", "off"], ["regression", "linear regression"], ["velocity", "velocity"]]
        per = 8
        for index, (width, _) in enumerate(WIDTHS):
            eta, regression, reloaded, velocity, again, tips, shown, camera = data["results"][per * index : per * (index + 1)]
            days = TREND_DAYS[width]
            kept = TREND_DAYS[WIDTHS[index - 1][0]] if index else 7
            with self.subTest(browser=browser, width=width):
                for probe in (eta, regression, reloaded, velocity, again, tips, shown):
                    self.assertNotIn("error", probe)
                    self.assertEqual((probe["tall"], probe["wide"], probe["layout"]), (False, False, ["toolbar", "chips", "body"]), probe)
                    self.assertEqual(probe["rows"] == 1, width != 390, probe["rows"])
                for mode in ("none", "points", "back"):
                    self.eta_checked(eta[mode], "points" if mode == "points" else "none", rows, edges, (begun - 1, ended + 1))
                self.assertEqual(eta["modes"], [["none", "true"], ["points", "false"]])
                self.assertEqual((regression["before"]["value"], regression["before"]["options"], regression["before"]["note"], regression["before"]["lines"]), ("off", trends, None, []))
                self.assertEqual(regression["before"]["days"], [kept, False])
                self.assertEqual(regression["toasts"], ["Trend: linear regression"])
                self.trended(regression["after"], "regression", kept)
                self.trended(reloaded, "regression", kept)
                self.assertEqual(velocity["toasts"], [f"Trend: velocity over {kept} days", f"Trend: velocity over {days} days"])
                self.trended(velocity["after"], "velocity", days)
                self.trended(again, "velocity", days)
                self.assertEqual([step["t"] for step in tips["steps"]], [t for t, _ in again["points"]])
                listed = [[sorted(filter(None, step[key].split(" "))) for key in ("started", "ended", "joined")] for step in tips["steps"]]
                self.assertEqual(listed, [[["work/t1", "work/t2", "work/t3"], [], ["work/t5", "work/t6"]], [[], ["work/t1"], []], [[], ["work/t2"], []], [[], ["work/t3"], []], [["work/t4"], [], []], [[], [], []]])
                self.assertEqual([step["series"] for step in tips["steps"]], [["scope", "done", "remaining"]] * len(tips["steps"]))
                self.assertIn("Ended: work/t1", tips["steps"][1]["tip"])
                self.assertIn("No work package started, ended or joined the scope here", tips["steps"][-1]["tip"])
                self.assertEqual((tips["reset"], tips["note"], tips["lines"]), ("Trend: off", False, 0))
                self.tasks_3d(shown, snapshot)
                self.assertTrue(camera["hooked"], camera)
                self.assertGreater(math.dist(camera["built"], camera["moved"]), 1, camera)
                for refresh in camera["refreshes"]:
                    self.assertEqual((refresh["rebuilt"], refresh["settled"]), (True, True), camera)
                    self.assertLess(math.dist(refresh["camera"], camera["moved"]), 0.01, camera)
        self.assertEqual(self.httpd.hub.settings.get()["trend"], {"mode": "off", "days": TREND_DAYS[WIDTHS[-1][0]]})

    def tasks_3d(self, shown: dict, snapshot: dict) -> None:
        tasks = sorted(row["task"] for row in snapshot["tasks"])
        colors = {"after": shown["palette"]["violet"], "base": shown["palette"]["info"], "queue": shown["palette"]["warn"]}
        edges = sorted([edge["from"], edge["to"], edge["kind"], colors[edge["kind"]]] for edge in snapshot["task_edges"])
        self.assertEqual(len(set(colors.values())), 3, colors)
        for layout, word in (("force", "Force"), ("time", "Time")):
            drawn = shown[layout]
            with self.subTest(layout=layout):
                self.assertEqual(drawn["note"], f"{len(tasks)} nodes · {len(edges)} edges · {word}")
                self.assertEqual(drawn["layouts"], [["none", str(layout == "force").lower()], ["time", str(layout == "time").lower()]])
                self.assertEqual(sorted(node for node, *_ in drawn["nodes"]), tasks)
                self.assertEqual(sorted(drawn["links"]), edges)
                self.assertEqual(drawn["label"], "work/t5 · Fifth")
        self.assertEqual([fz for _, fz, _ in shown["force"]["nodes"]], [None] * len(tasks))
        timed = sorted(shown["time"]["nodes"], key=lambda node: node[2])
        self.assertTrue(all(fz is not None for _, fz, _ in timed), timed)
        self.assertEqual([fz for _, fz, _ in timed], sorted(fz for _, fz, _ in timed))
        self.assertLess(timed[0][1], timed[-1][1])
        popup = shown["popup"]
        self.assertEqual((popup["open"], popup["title"], popup["id"], popup["picked"], popup["open_button"], popup["line"]), (True, "Fifth", "work/t5", "work/t5", "Open task", True), popup)
        self.assertTrue(popup["eta"], popup)
        self.assertEqual((popup["closed"], shown["back"]), ([False, None], f"{len(tasks)} nodes · {len(edges)} edges · Force"))

    def test_chromium_draws_the_trend_forecast_point_tips_eta_and_tasks_3d_at_three_widths(self):
        self.check_trend_eta_3d("chromium", "cdp.mjs", os.environ.get("CHROMIUM", "chromium"))

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_draws_the_trend_forecast_point_tips_eta_and_tasks_3d_at_three_widths(self):
        self.check_trend_eta_3d("firefox", "bidi.mjs", os.environ.get("FIREFOX", "firefox"))


if __name__ == "__main__":
    unittest.main()
