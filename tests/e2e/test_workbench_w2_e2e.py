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

import test_orchestrator_e2e as base
from hub_case import HubCase
from hub_support import iso
from kvb_orchestrator import skill_scripts, tasking

OUT = Path(os.environ.get("E2E_OUT", "/tmp/workbench-w2-shots"))
DAY = 86400
WHY = "rasci: work/a: 1 key result(s) open; mark them met or set stopped"
STAGED = [
    ["work/c", "set work/c --status running"],
    ["work/c", "set work/c --prio 2"],
    ["work/c", "set work/c --after work/a"],
    ["work/b", "set work/b --drop-after work/a"],
    ["work/d", "set work/d --prio 4"],
    ["work/stale", "set work/stale --status stopped"],
]
EMPTY = {"queued": [], "running": [], "done": []}
BOARD_HELPERS = """
  let asked = 0;
  const get = navigator.credentials.get.bind(navigator.credentials);
  navigator.credentials.get = (options) => {
    asked += 1;
    return @SIGNS@ ? get(options) : Promise.reject(new DOMException("The operator canceled.", "NotAllowedError"));
  };
  const posted = [];
  const send = window.fetch.bind(window);
  window.fetch = (path, init) => {
    if (["/api/sign", "/api/tasks"].includes(String(path))) {
      posted.push([String(path), JSON.parse(init.body).items.map((item) => [item.id, item.argv.join(" ")])]);
    }
    return send(path, init);
  };
  const fresh = async (shown, prefix) => until(() => all("#toasts .toast").filter((box) => !shown.has(box)).map(text).find((entry) => entry.startsWith(prefix)), 20000);
  const fits = () => ({tall: document.documentElement.scrollHeight > window.innerHeight, wide: document.documentElement.scrollWidth > window.innerWidth + 1});
  const card = (task) => all("#main .kanban-card").find((node) => node.dataset.task === task) || null;
  const cell = (lane, column) => document.querySelector(`#main .kanban-cell[data-lane="${lane}"][data-column="${column}"]`);
  const drag = async (source, target) => {
    const data = new DataTransfer();
    const fire = (node, type) => node.dispatchEvent(new DragEvent(type, {bubbles: true, cancelable: true, dataTransfer: data}));
    fire(source, "dragstart");
    fire(target, "dragenter");
    fire(target, "dragover");
    fire(target, "drop");
    fire(source, "dragend");
    await sleep(400);
  };
  const read = () => ({
    columns: all("#main .kanban-head .task-column").map((node) => node.dataset.column),
    lanes: all("#main .kanban-lane").map((lane) => [lane.dataset.lane, lane.querySelector(".lane-toggle").getAttribute("aria-expanded"),
      Object.fromEntries(all(".kanban-cell", lane).map((box) => [box.dataset.column, all(".kanban-card", box).map((node) => node.dataset.task)]))]),
    labels: Object.fromEntries(all("#main .kanban-card").map((node) => [node.dataset.task, all(".pill[data-label]", node).map((pill) => pill.dataset.label)]).filter(([, found]) => found.length)),
    arrows: all("#main svg.kanban-lines .kanban-arrow").map((node) => [node.dataset.from, node.dataset.to, node.classList.contains("pending")]),
    solid: all("#main svg.kanban-lines .kanban-link").map((path) => getComputedStyle(path).strokeDasharray === "none"),
    queue: (() => {
      const line = document.querySelector("#main svg.kanban-lines .kanban-queue");
      return line ? [line.dataset.tasks, getComputedStyle(line).strokeDasharray !== "none"] : null;
    })(),
    pending: Object.fromEntries(all("#main .kanban-card.pending").map((node) => [node.dataset.task, node.dataset.pending])),
    apply: (() => {
      const button = document.getElementById("kanban-apply");
      return [button.disabled, button.getAttribute("aria-label"), text(button.querySelector(".count"))];
    })(),
    old: (() => {
      const button = document.getElementById("kanban-old");
      return [button.getAttribute("aria-pressed"), text(button.querySelector(".count"))];
    })(),
    stale: text(document.getElementById("kanban-stale")),
    why: Object.fromEntries(all("#main .kanban-card .task-why").map((node) => [node.closest(".kanban-card").dataset.task, text(node)])),
    partly: Object.fromEntries(all("#main .kanban-card .kanban-partly").map((node) => [node.closest(".kanban-card").dataset.task, node.dataset.partly])),
    listed: all("#kanban-staged li").map((item) => [item.dataset.task, text(item)]),
    unlabelled: all("#main .kanban-box svg.bi").map((svg) => svg.parentElement).filter((owner) => !text(owner) && !(owner.getAttribute("title") && owner.getAttribute("aria-label"))).length,
    ...fits(),
  });
"""
BOARD = """(async () => {@HELPERS@@BOARD_HELPERS@
  if (!(await until(() => card("work/a") && document.querySelector("#main svg.kanban-lines .kanban-arrow"), 8000))) {
    return {error: text(document.getElementById("main"))};
  }
  const before = read();
  await drag(card("work/c"), cell("p2", "running"));
  await drag(card("work/a").querySelector(".kanban-handle"), card("work/c"));
  const arrow = all("#main svg.kanban-lines .kanban-arrow").find((node) => node.dataset.from === "work/a" && node.dataset.to === "work/b");
  arrow.dispatchEvent(new MouseEvent("click", {bubbles: true}));
  await sleep(400);
  const menu = card("work/d").querySelector("details.kanban-menu");
  menu.querySelector("summary").click();
  all("button", menu).find((button) => text(button) === "P4+").click();
  await sleep(400);
  card("work/stale").querySelector(".kanban-stop").click();
  await sleep(400);
  const staged = read();
  document.getElementById("kanban-old").click();
  await sleep(300);
  const older = read().lanes.find(([lane]) => lane === "unpinned");
  document.getElementById("kanban-old").click();
  await sleep(300);
  document.querySelector('#main .kanban-lane[data-lane="p4"] .lane-toggle').click();
  await sleep(300);
  const lane = document.querySelector('#main .kanban-lane[data-lane="p4"]');
  const folded = [lane.querySelector(".lane-toggle").getAttribute("aria-expanded"), lane.querySelector(".kanban-cells").hidden, read().listed];
  lane.querySelector(".lane-toggle").click();
  await sleep(300);
  card("work/b").querySelector(".kanban-title").click();
  await sleep(400);
  const popup = document.getElementById("popup");
  const popped = [popup.open, popup.getAttribute("aria-label")];
  (document.activeElement || document.body).dispatchEvent(new KeyboardEvent("keydown", {key: "Escape", bubbles: true}));
  await sleep(300);
  const shown = new Set(all("#toasts .toast"));
  document.getElementById("kanban-apply").click();
  const toast = await fresh(shown, "Apply 6 changes");
  await sleep(600);
  return {before, staged, older, folded, popped, toast, asked, posted, after: read()};
})()"""
FORECAST = """(async () => {@HELPERS@
  const ready = () => document.querySelector("#main svg.burn") && document.querySelector('#main select[aria-label="Trend"]');
  if (!(await until(ready, 8000))) {
    return {error: text(document.getElementById("main"))};
  }
  const choose = async (label, value) => {
    const select = document.querySelector(`#main select[aria-label="${label}"]`);
    select.value = value;
    select.dispatchEvent(new Event("change", {bubbles: true}));
    await sleep(600);
  };
  const read = () => ({
    points: Object.fromEntries(["scope", "done", "remaining"].map((name) => [name, all(`#main svg.burn circle.burn-point[data-series="${name}"]`).map((dot) => [Number(dot.dataset.t), Number(dot.dataset.value)])])),
    finishes: all("#main .burn-finish").map((node) => [node.dataset.finish, node.dataset.forecast === "" ? null : Number(node.dataset.forecast), text(node), node.getAttribute("aria-label"), getComputedStyle(node, "::before").backgroundColor]),
    lines: all("#main svg.burn path.burn-finish-line").map((path) => [path.dataset.finish, Number(path.dataset.at), getComputedStyle(path).stroke, path.getAttribute("d").match(/-?\\d+(?:\\.\\d+)?/g).map(Number)]),
    stale: (() => {
      const pill = document.querySelector("#main .burn-stale");
      return [pill.dataset.stale, text(pill), pill.getAttribute("aria-label")];
    })(),
    tall: document.documentElement.scrollHeight > window.innerHeight,
    wide: document.documentElement.scrollWidth > window.innerWidth + 1,
  });
  await choose("Trend", "regression");
  const whole = read();
  await choose("Scope", "agent:Docs");
  const docs = read();
  await choose("Scope", "all");
  return {whole, docs};
})()"""


def probe(template: str, signs: bool) -> str:
    helpers = BOARD_HELPERS.replace("@SIGNS@", "true" if signs else "false")
    return template.replace("@HELPERS@", base.HELPERS).replace("@BOARD_HELPERS@", helpers)


def regression(points: list[list[float]]) -> tuple[float, float, float] | None:
    mean_t = sum(t for t, _ in points) / len(points)
    mean_y = sum(y for _, y in points) / len(points)
    spread = sum((t - mean_t) ** 2 for t, _ in points)
    return (mean_t, mean_y, sum((t - mean_t) * (y - mean_y) for t, y in points) / spread) if spread else None


def finishes(points: dict) -> dict:
    """Returns:
        The finish at fixed and at growing scope, computed here
        independently of plan.js from the drawn burn points.
    """
    done, remaining = regression(points["done"]), regression(points["remaining"])
    last_t, last_scope = points["scope"][-1]
    t0, y0, slope = done
    fixed = last_t if points["remaining"][-1][1] <= 0 else max(last_t, t0 + (last_scope - y0) / slope) if slope > 0 else None
    r0, ry, rslope = remaining
    return {"fixed": fixed, "growing": r0 - ry / rslope if rslope < 0 else None}


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestWorkbenchKanban(HubCase):
    drive = base.TestOrchestratorE2E.drive
    authenticator = base.TestOrchestratorE2E.authenticator

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        now = time.time()
        fresh = iso(now - 3600)
        self.write_council({
            "rasci.json": {
                "work/a": {"title": "Alpha", "status": "queued", "worker": "Stage", "prio": 1, "key_results": [{"text": "shipped", "met": False}], "updated": fresh},
                "work/b": {"title": "Bravo", "status": "running", "worker": "Docs", "prio": 2, "start": iso(now - 3.9 * DAY), "after": ["work/a"], "updated": fresh},
                "work/blocked": {"title": "Blocked one", "status": "blocked", "worker": "Stage", "prio": 3, "updated": fresh},
                "work/p5": {"title": "Five", "status": "queued", "worker": "Stage", "prio": 5, "updated": fresh},
                "work/c": {"title": "Charlie", "status": "queued", "worker": "Stage", "estimates": {"Stage": {"value": 4, "complexity": 2}}, "updated": fresh},
                "work/d": {"title": "Delta", "status": "queued", "worker": "Skills", "estimates": {"Skills": {"value": 5, "complexity": 1}}, "updated": fresh},
                "work/stale": {"title": "Stale one", "status": "running", "worker": "Stage", "start": iso(now - 5 * DAY), "updated": iso(now - 4 * DAY)},
                "work/stopped": {"title": "Stopped one", "status": "stopped", "worker": "Stage", "start": iso(now - 3.7 * DAY), "end": iso(now - 3600)},
                "work/old": {"title": "Old one", "status": "done", "worker": "Stage", "start": iso(now - 4 * DAY), "end": iso(now - 2 * DAY)},
                "work/done": {"title": "Done one", "status": "done", "worker": "Stage", "start": iso(now - 3.8 * DAY), "end": iso(now - 7200)},
                "operator/push": {"title": "git push", "workdir": "/repo", "status": "queued"},
            },
            "queue.json": {"seq": 2, "entries": [
                {"id": "gate-1", "seq": 1, "kind": "gate", "task": "work/b", "name": "Docs", "hotfix": None, "status": "active", "enqueued": now - 300, "granted": now - 200, "cmd": "make test"},
                {"id": "gate-2", "seq": 2, "kind": "gate", "task": "work/c", "name": "Stage", "hotfix": None, "status": "waiting", "enqueued": now - 100, "granted": None, "cmd": "make test"},
            ]},
        })
        signer = self.pin()
        items = [{"kind": "task", "id": "work/a", "argv": ["set", "work/a", "--status", "done"]}, {"kind": "task", "id": "work/a", "argv": ["set", "work/a", "--prio", "1"]}]
        status, _, body = self.post_json("/api/tasks", {"items": items, "proof": self.signed(items, signer)}, self.guard(self.host))
        self.assertEqual((status, self.scripts.calls), (202, []), body)
        self.run_runner()
        self.assertEqual(self.scripts.calls, [(skill_scripts.RADIO, ["post", "--to", "Stage", "--session", "Operator", f"{tasking.TOLD}: rasci.py set work/a --prio 1"])])
        self.told = len(self.scripts.calls)

    def steps(self, browser: str, signs: bool) -> list[dict]:
        local = f"http://localhost:{self.port}/"
        steps = []
        for width, height in base.WIDTHS:
            steps += [
                {"width": width, "height": height, "url": f"{local}?{width}#tasks/board", "wait": 1200, "probe": probe(BOARD, signs), "shot": str(OUT / f"{browser}-{width}-kanban.png")},
                {"width": width, "height": height, "url": f"{local}?{width}-burn#tasks/burn", "wait": 1200, "probe": probe(FORECAST, signs), "shot": str(OUT / f"{browser}-{width}-forecast.png")},
            ]
        return steps

    def check_board(self, result: dict, signs: bool) -> None:
        self.assertNotIn("error", result, result)
        before, staged, after = result["before"], result["staged"], result["after"]
        self.assertEqual(before["columns"], ["queued", "running", "done"])
        self.assertEqual(before["lanes"], [
            ["p1", "true", {**EMPTY, "queued": ["work/a"]}],
            ["p2", "true", {**EMPTY, "running": ["work/b"]}],
            ["p3", "true", {**EMPTY, "queued": ["work/blocked"]}],
            ["p4", "true", {**EMPTY, "queued": ["work/p5"]}],
            ["unpinned", "true", {**EMPTY, "queued": ["work/d", "work/c", "queue/gate-2"], "running": ["queue/gate-1", "work/stale"], "done": ["work/done", "work/stopped"]}],
        ])
        self.assertEqual(before["labels"], {"work/blocked": ["blocked"], "work/stale": ["stale"], "work/stopped": ["stopped"]})
        self.assertEqual((before["arrows"], before["solid"], before["queue"]), ([["work/a", "work/b", False]], [True], ["work/b work/c", True]))
        self.assertEqual((before["old"], before["stale"], before["apply"], before["pending"]), (["false", "1"], "1", [True, "Apply 0 changes", "0"], {}))
        self.assertEqual((before["why"], before["partly"], before["listed"]), ({"work/a": WHY}, {"work/a": "1/2"}, []))
        self.assertEqual(staged["lanes"], [
            ["p1", "true", {**EMPTY, "queued": ["work/a"]}],
            ["p2", "true", {**EMPTY, "running": ["work/c", "work/b"]}],
            ["p3", "true", {**EMPTY, "queued": ["work/blocked"]}],
            ["p4", "true", {**EMPTY, "queued": ["work/d", "work/p5"]}],
            ["unpinned", "true", {**EMPTY, "queued": ["queue/gate-2"], "running": ["queue/gate-1"], "done": ["work/done", "work/stale", "work/stopped"]}],
        ])
        self.assertEqual(staged["arrows"], [["work/a", "work/c", True]])
        self.assertEqual(staged["pending"], {
            "work/c": "set work/c --status running\nset work/c --prio 2\nset work/c --after work/a",
            "work/b": "set work/b --drop-after work/a",
            "work/d": "set work/d --prio 4",
            "work/stale": "set work/stale --status stopped",
        })
        self.assertEqual((staged["apply"], staged["stale"], staged["labels"]["work/stale"]), ([False, "Apply 6 changes", "6"], "0", ["stopped"]))
        self.assertEqual(result["older"], ["unpinned", "true", {**EMPTY, "queued": ["queue/gate-2"], "running": ["queue/gate-1"], "done": ["work/done", "work/old", "work/stale", "work/stopped"]}])
        listed = [[task, f"rasci.py {argv}"] for task, argv in STAGED]
        self.assertEqual((staged["listed"], result["folded"], result["popped"]), (listed, ["false", True, listed], [True, "work/b"]))
        self.assertTrue(result["toast"].startswith(f"Apply 6 changes: {'handed to the runner' if signs else 'not signed'}"), result["toast"])
        signed = [["/api/sign", STAGED]]
        self.assertEqual((result["asked"], result["posted"]), (1, [*signed, ["/api/tasks", STAGED]] if signs else signed))
        self.assertEqual(after["apply"], [True, "Apply 0 changes", "0"] if signs else [False, "Apply 6 changes", "6"])
        for read in (before, staged, after):
            self.assertEqual((read["unlabelled"], read["tall"], read["wide"]), (0, False, False), read)

    def check_forecast(self, result: dict) -> None:
        self.assertNotIn("error", result, result)
        whole, docs = result["whole"], result["docs"]
        expected = finishes(whole["points"])
        self.assertTrue(expected["fixed"] is not None and expected["growing"] is not None and expected["growing"] > expected["fixed"], expected)
        found = {kind: (at, words, label, colour) for kind, at, words, label, colour in whole["finishes"]}
        lines = {kind: (at, stroke, path) for kind, at, stroke, path in whole["lines"]}
        self.assertEqual((sorted(found), sorted(lines), len(whole["lines"])), (["fixed", "growing"], ["fixed", "growing"], 2))
        for kind, at in expected.items():
            with self.subTest(kind=kind):
                self.assertAlmostEqual(found[kind][0], at, delta=0.01)
                self.assertAlmostEqual(lines[kind][0], at, delta=0.01)
                self.assertNotEqual(found[kind][1], "∞")
                self.assertEqual(found[kind][3], lines[kind][1])
        self.assertNotEqual(lines["fixed"][1], lines["growing"][1])
        fixed_path, growing_path = lines["fixed"][2], lines["growing"][2]
        self.assertAlmostEqual(fixed_path[1], fixed_path[3], delta=0.05, msg=f"the fixed-scope finish runs level at the last scope: {fixed_path}")
        self.assertLess(growing_path[3], growing_path[1] - 1, f"the growing-scope finish rises along the scope trend: {growing_path}")
        self.assertEqual(whole["stale"][:2], ["1", "1"])
        self.assertEqual([entry[:3] for entry in docs["finishes"]], [["fixed", None, "∞"], ["growing", None, "∞"]])
        self.assertEqual((docs["lines"], docs["stale"][:2]), ([], ["0", "0"]))
        for read in (whole, docs):
            self.assertEqual((read["tall"], read["wide"]), (False, False), read)

    def check(self, data: dict, browser: str, signs: bool) -> None:
        results = iter(data["results"])
        for width, _ in base.WIDTHS:
            with self.subTest(browser=browser, width=width):
                self.check_board(next(results), signs)
                self.check_forecast(next(results))
        self.assertEqual(self.scripts.calls[self.told:], [])
        if not signs:
            return
        self.run_runner()
        stage = f"{tasking.TOLD}: rasci.py set work/c --status running; rasci.py set work/c --prio 2; rasci.py set work/c --after work/a; rasci.py set work/stale --status stopped"
        batch = [
            (skill_scripts.RADIO, ["post", "--to", "Stage", "--session", "Operator", stage]),
            (skill_scripts.RADIO, ["post", "--to", "Docs", "--session", "Operator", f"{tasking.TOLD}: rasci.py set work/b --drop-after work/a"]),
            (skill_scripts.RADIO, ["post", "--to", "Skills", "--session", "Operator", f"{tasking.TOLD}: rasci.py set work/d --prio 4"]),
        ]
        self.assertEqual(self.scripts.calls[self.told:], batch * len(base.WIDTHS))
        stored = json.loads((self.council / "rasci.json").read_text(encoding="utf-8"))
        self.assertEqual((stored["work/c"]["status"], stored["work/c"]["prio"], stored["work/c"]["after"], "after" in stored["work/b"]), ("running", 2, ["work/a"], False))
        self.assertEqual((stored["work/d"]["prio"], stored["work/stale"]["status"], stored["work/a"]["status"]), (4, "stopped", "queued"))

    def test_chromium_stages_drags_signs_one_batch_and_draws_both_forecasts_at_three_widths(self):
        data = self.drive(self.steps("chromium", True), self.authenticator())
        (OUT / "chromium-kanban.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        self.check(data, "chromium", True)

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_stages_drags_asks_the_passkey_and_draws_both_forecasts_storing_nothing_unsigned(self):
        data = self.drive(self.steps("firefox", False), None, "bidi.mjs", os.environ.get("FIREFOX", "firefox"))
        (OUT / "firefox-kanban.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        self.check(data, "firefox", False)


if __name__ == "__main__":
    unittest.main()
