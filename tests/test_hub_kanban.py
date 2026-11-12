from __future__ import annotations

import json
import re
import subprocess
import time
import unittest

from hub_case import HubCase
from hub_support import HUB, PLAN, iso, runner, signing
from kvb_orchestrator import skill_scripts, tasking

KANBAN = HUB / "templates" / "kanban.js"
DAY = 86400
KANBAN_PROBE = """
const K = require(process.argv[1]);
const H = 3600, D = 86400, now = 100 * D;
const row = (task, fields) => ({task, kind: "task", status: "queued", ended: false, start: null, end: null, prio: null, wsjf: null, after: [], movable: true, editable: true, ...fields});
const rows = [
  row("work/p1", {prio: 1, status: "running", start: now - H}),
  row("work/p2", {prio: 2, status: "blocked"}),
  row("work/p3", {prio: 3, status: "blocked", start: now - H}),
  row("work/p4", {prio: 4}),
  row("work/p7", {prio: 7, status: "stopped", ended: true, end: now - H}),
  row("work/low", {wsjf: {score: 1.5}}),
  row("work/high", {wsjf: {score: 4}}),
  row("work/none", {}),
  row("work/also", {wsjf: {score: 4}}),
  row("work/old", {status: "done", ended: true, end: now - D - 1}),
  row("work/fresh", {status: "done", ended: true, end: now - D + 1}),
  row("operator/push", {kind: "command"}),
  row("queue/gate-1", {kind: "queue", status: "running"}),
];
const hub = (task) => rows.find((entry) => entry.task === task);
const place = (old) => {
  const found = K.board(rows, {now, old});
  return {hidden: found.hidden, lanes: found.lanes.map((lane) => [lane.id, lane.label, lane.count, Object.fromEntries(Object.entries(lane.cells).map(([column, cards]) => [column, cards.map((entry) => entry.task)]))])};
};
const shown = (staged) => staged.map((change) => [change.task, change.argv.join(" ")]);
let staged = [];
staged = K.stage(staged, hub("work/none"), {column: "running"}, rows);
staged = K.stage(staged, hub("work/none"), {lane: "p2"}, rows);
staged = K.stage(staged, hub("work/low"), {lane: "p4"}, K.pending(rows, staged));
staged = K.stage(staged, hub("work/high"), {lane: "p4"}, K.pending(rows, staged));
staged = K.stage(staged, hub("work/p1"), {lane: "unpinned"}, rows);
staged = K.stage(staged, hub("work/none"), {after: "work/p1"}, rows);
const first = shown(staged);
staged = K.stage(staged, hub("work/none"), {column: "done"}, rows);
const replaced = shown(staged);
staged = K.stage(staged, hub("work/none"), {lane: "unpinned"}, rows);
staged = K.stage(staged, hub("work/none"), {drop: "work/p1"}, rows);
const back = shown(staged);
const applied = Object.fromEntries(K.pending(rows, staged).filter((entry) => entry.pending).map((entry) => [entry.task, [entry.status, entry.ended, entry.prio, entry.after, entry.pending.length]]));
const dep = row("work/dep", {after: ["work/p1", "work/p2"]});
const linked = [row("a", {}), row("b", {after: ["a"]}), row("c", {after: ["a", "b", "gone", "c"]})];
const job = (id, task, batch, status, created_ts, output) => ({id, kind: "task", task, batch, status, created_ts, output: output || "", command: id});
const jobs = [
  job("pin", "work/x", "b2", "done", 21),
  job("old", "work/x", "b1", "failed", 10, "rasci: old"),
  job("status", "work/x", "b2", "failed", 20, "x\\nrasci: work/x: 1 key result(s) open"),
  job("lone", "work/y", undefined, "refused", 5, "refused: expired"),
  job("cmd", "work/z", "b3", "failed", 30),
  job("fixed", "work/w", "b4", "failed", 1),
  job("later", "work/w", "b5", "done", 2),
  {id: "run", task: "work/v", status: "failed", created_ts: 3, output: ""},
];
const reasons = (found) => found && {...found, failed: found.failed.map((entry) => entry.id)};
console.log(JSON.stringify({
  columns: K.COLUMNS, lanes: K.LANES, freeFrom: K.FREE_FROM,
  sorted: [["running", null], ["blocked", null], ["blocked", 5], ["queued", null], ["done", 1], ["stopped", 1], ["awaiting", null]].map(([status, start]) => K.columnOf(row("x", {status, start}))),
  labels: rows.slice(0, 5).map(K.labelOf),
  lanesOf: [null, 0, -1, 1, 2, 3, 4, 9].map(K.laneOf),
  belowOne: K.board([row("work/zero", {prio: 0}), row("work/minus", {prio: -3})], {now, old: false}).lanes.map((lane) => [lane.id, lane.count]),
  why: Object.fromEntries(["work/x", "work/y", "work/z", "work/w", "work/v", "work/none"].map((task) => [task, reasons(K.why(jobs, task))])),
  onBoard: rows.filter(K.onBoard).length,
  hidden: place(false), shown: place(true),
  pins: [K.freePin(rows, "work/none"), K.freePin([...rows, row("work/five", {prio: 5})], "work/none"), K.freePin(rows, "work/p4")],
  first, replaced, back, applied,
  untouched: K.pending(rows, staged).filter((entry, index) => entry === rows[index]).length,
  noops: [K.move(hub("work/p1"), {column: "running"}, rows), K.move(hub("work/p3"), {column: "running"}, rows), K.move(hub("work/p2"), {lane: "p2"}, rows), K.move(hub("work/p7"), {lane: "p4"}, rows),
    K.move(hub("work/p3"), {after: "work/p3"}, rows), K.move(dep, {after: "work/p1"}, rows), K.move(dep, {drop: "work/p3"}, rows), K.move(hub("work/p7"), {status: "stopped"}, rows)],
  moves: [K.move(hub("work/none"), {status: "stopped"}, rows), K.move(dep, {drop: "work/p1"}, rows), K.move(hub("work/fresh"), {column: "running"}, rows)],
  pendingAfter: K.pending([dep], [{task: "work/dep", argv: ["set", "work/dep", "--after", "work/p3"]}, {task: "work/dep", argv: ["set", "work/dep", "--drop-after", "work/p1"]}])[0].after,
  lines: K.lines(linked, ["gone", "c", "a"]),
}));
"""
FORECAST_PROBE = """
const P = require(process.argv[1]);
const D = 86400, now = 100 * D;
const points = (scope, done) => scope.map((value, index) => ({t: index * D, scope: value, done: done[index], remaining: value - done[index], unestimated: 0}));
const days = (t) => (t === null ? null : t / D);
const finish = (found, mode) => {
  const reached = P.finishes(found, P.trend(found, {mode, days: 7}));
  return [days(reached.fixed), days(reached.growing)];
};
const row = (task, fields) => ({task, kind: "task", status: "queued", ended: false, start: null, end: null, points: null, worker: "-", roles: {}, updated: null, ...fields});
const rows = [
  row("work/a", {status: "running", start: now - 5 * D, updated: now - 4 * D}),
  row("work/b", {status: "running", start: now - 2 * D, updated: now - D}),
  row("work/c", {status: "done", ended: true, start: now - 6 * D, end: now - 5 * D, updated: now - 5 * D}),
  row("operator/push", {kind: "command", updated: now - 9 * D}),
  row("queue/x", {kind: "queue", status: "awaiting"}),
];
const scope = (choice) => {
  const found = P.scoped(rows, choice, {filtered: rows, since: now - D, until: now, now, holders: {}});
  return {rows: found.rows.map((entry) => entry.task), stale: found.stale.map((entry) => entry.task), from: found.from / D, to: found.to / D};
};
console.log(JSON.stringify({
  fixedScope: finish(points([4, 4, 4], [0, 1, 2]), "regression"),
  growing: finish(points([4, 5, 6], [0, 2, 4]), "regression"),
  growingNever: finish(points([4, 5, 6], [0, 1, 2]), "regression"),
  never: finish(points([4, 4, 4], [1, 1, 1]), "regression"),
  finished: finish(points([2, 3, 3], [0, 2, 3]), "regression"),
  velocity: finish(points([4, 5, 6], [0, 2, 4]), "velocity"),
  noTrend: P.finishes(points([1], [0]), null),
  beyond: P.finishes([{t: 0, scope: 1, done: 0, remaining: 1}, {t: 1, scope: 1, done: 1e-13, remaining: 1 - 1e-13}], P.trend([{t: 0, scope: 1, done: 0, remaining: 1}, {t: 1, scope: 1, done: 1e-13, remaining: 1 - 1e-13}], {mode: "regression", days: 7})),
  staleDays: P.STALE_DAYS,
  stale: [row("t", {updated: now - 3 * D}), row("t", {updated: now - 3 * D + 1}), row("t", {updated: now - 10 * D, ended: true}), row("t", {}), row("t", {updated: undefined})].map((entry) => P.stale(entry, now)),
  all: scope("all"), filter: scope("filter"),
  burn: P.burn(P.scoped(rows, "all", {filtered: rows, since: now - D, until: now, now, holders: {}}).rows, {estimation: "none", from: now - 6 * D, to: now}).points.pop(),
}));
"""


def change(argv: list, task: str) -> dict:
    return {"kind": "task", "id": task, "argv": argv}


class TestKanbanModule(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        done = subprocess.run(["node", "-e", KANBAN_PROBE, str(KANBAN)], capture_output=True, text=True, timeout=60, check=True)
        cls.data = json.loads(done.stdout)

    def test_the_board_has_waiting_running_and_done_and_blocked_and_stopped_are_labels(self):
        self.assertEqual(self.data["columns"], [["queued", "Waiting"], ["running", "Running"], ["done", "Done"]])
        self.assertEqual(self.data["sorted"], ["running", "queued", "running", "queued", "done", "done", "queued"])
        self.assertEqual(self.data["labels"], [None, "blocked", "blocked", None, "stopped"])

    def test_operator_commands_stay_off_the_board_and_queue_jobs_stay_on_it(self):
        self.assertEqual(self.data["onBoard"], 12)
        placed = [task for lane in self.data["shown"]["lanes"] for cells in lane[3].values() for task in cells]
        self.assertEqual(len(placed), 12)
        self.assertEqual([task for task in placed if task.startswith(("operator/", "queue/"))], ["queue/gate-1"])

    def test_lanes_are_p1_to_p3_p4_plus_and_unpinned_by_wsjf_rank_and_old_done_cards_hide(self):
        self.assertEqual((self.data["lanes"], self.data["freeFrom"]), ([["p1", "P1"], ["p2", "P2"], ["p3", "P3"], ["p4", "P4+"], ["unpinned", "Unpinned"]], 4))
        self.assertEqual(self.data["lanesOf"], ["unpinned", "p1", "p1", "p1", "p2", "p3", "p4", "p4"])
        self.assertEqual(self.data["belowOne"], [["p1", 2], ["p2", 0], ["p3", 0], ["p4", 0], ["unpinned", 0]])
        empty = {"queued": [], "running": [], "done": []}
        self.assertEqual(self.data["hidden"], {"hidden": 1, "lanes": [
            ["p1", "P1", 1, {**empty, "running": ["work/p1"]}],
            ["p2", "P2", 1, {**empty, "queued": ["work/p2"]}],
            ["p3", "P3", 1, {**empty, "running": ["work/p3"]}],
            ["p4", "P4+", 2, {**empty, "queued": ["work/p4"], "done": ["work/p7"]}],
            ["unpinned", "Unpinned", 6, {**empty, "queued": ["work/also", "work/high", "work/low", "work/none"], "running": ["queue/gate-1"], "done": ["work/fresh"]}],
        ]})
        self.assertEqual(self.data["shown"]["hidden"], 0)
        self.assertEqual(self.data["shown"]["lanes"][4][3]["done"], ["work/fresh", "work/old"])

    def test_a_card_shows_every_refusal_of_its_newest_batch_and_how_much_of_it_applied(self):
        self.assertEqual(self.data["why"], {
            "work/x": {"failed": ["status"], "applied": 1, "total": 2},
            "work/y": {"failed": ["lone"], "applied": 0, "total": 1},
            "work/z": {"failed": ["cmd"], "applied": 0, "total": 1},
            "work/w": None,
            "work/v": None,
            "work/none": None,
        })

    def test_p4_plus_takes_the_lowest_pin_from_4_no_other_open_task_holds(self):
        self.assertEqual(self.data["pins"], [5, 6, 4])

    def test_moves_stage_one_change_each_and_a_later_move_of_the_same_kind_replaces_it(self):
        self.assertEqual(self.data["first"], [
            ["work/none", "set work/none --status running"],
            ["work/none", "set work/none --prio 2"],
            ["work/low", "set work/low --prio 5"],
            ["work/high", "set work/high --prio 6"],
            ["work/p1", "set work/p1 --unpin"],
            ["work/none", "set work/none --after work/p1"],
        ])
        self.assertEqual(self.data["replaced"], [*self.data["first"][1:], ["work/none", "set work/none --status done"]])
        self.assertEqual(self.data["back"], [
            ["work/low", "set work/low --prio 5"], ["work/high", "set work/high --prio 6"], ["work/p1", "set work/p1 --unpin"], ["work/none", "set work/none --status done"],
        ])

    def test_staged_moves_show_at_once_as_pending_rows(self):
        self.assertEqual(self.data["applied"], {
            "work/p1": ["running", False, None, [], 1],
            "work/low": ["queued", False, 5, [], 1],
            "work/high": ["queued", False, 6, [], 1],
            "work/none": ["done", True, None, [], 1],
        })
        self.assertEqual(self.data["untouched"], 9)
        self.assertEqual(self.data["pendingAfter"], ["work/p2", "work/p3"])

    def test_a_move_to_where_the_card_already_is_stages_nothing(self):
        self.assertEqual(self.data["noops"], [None] * 8)
        self.assertEqual(self.data["moves"], [["set", "work/none", "--status", "stopped"], ["set", "work/dep", "--drop-after", "work/p1"], ["set", "work/fresh", "--status", "running"]])

    def test_arrows_run_into_the_dependent_card_several_per_card_and_the_queue_line_keeps_queue_order(self):
        self.assertEqual(self.data["lines"], {"arrows": [{"from": "a", "to": "b"}, {"from": "a", "to": "c"}, {"from": "b", "to": "c"}], "queue": ["c", "a"]})


class TestForecast(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        done = subprocess.run(["node", "-e", FORECAST_PROBE, str(PLAN)], capture_output=True, text=True, timeout=60, check=True)
        cls.data = json.loads(done.stdout)

    def assertDays(self, found: list, expected: list) -> None:
        for got, want in zip(found, expected, strict=True):
            if want is None:
                self.assertIsNone(got)
            else:
                self.assertAlmostEqual(got, want, places=9)

    def test_at_fixed_scope_both_finishes_meet(self):
        self.assertDays(self.data["fixedScope"], [4, 4])

    def test_a_growing_scope_finishes_later_than_the_fixed_one(self):
        self.assertDays(self.data["growing"], [3, 4])
        self.assertDays(self.data["velocity"], [3, 4])

    def test_a_finish_that_is_never_reached_is_none_and_shown_as_infinity(self):
        self.assertDays(self.data["growingNever"], [6, None])
        self.assertDays(self.data["never"], [None, None])
        self.assertEqual(self.data["noTrend"], {"fixed": None, "growing": None})
        self.assertIsNone(self.data["beyond"]["growing"])
        self.assertIsNone(self.data["beyond"]["fixed"])

    def test_nothing_remaining_finishes_at_the_last_point(self):
        self.assertDays(self.data["finished"], [2, 2])

    def test_a_task_without_a_register_change_for_three_days_is_stale(self):
        self.assertEqual((self.data["staleDays"], self.data["stale"]), (3, [True, False, False, False, False]))

    def test_the_scope_leaves_out_operator_commands_and_queue_jobs_and_counts_stale_tasks_apart(self):
        self.assertEqual(self.data["all"], {"rows": ["work/b", "work/c"], "stale": ["work/a"], "from": 94, "to": 100})
        self.assertEqual(self.data["filter"], {"rows": ["work/b", "work/c"], "stale": ["work/a"], "from": 99, "to": 100})
        self.assertEqual((self.data["burn"]["scope"], self.data["burn"]["done"]), (2, 1))


class TestBoardArgv(unittest.TestCase):
    def test_the_signed_register_contract_takes_exactly_one_board_change(self):
        for flags in (["--status", "running"], ["--status", "stopped"], ["--after", "work/b"], ["--drop-after", "work/b"], ["--prio", "4"], ["--unpin"]):
            with self.subTest(flags=flags):
                argv = ["set", "work/a", *flags]
                self.assertEqual(signing.task_argv("work/a", argv), argv)
        for flags in (["--status", "paused"], ["--status"], ["--after", "work/a"], ["--after", "operator/push"], ["--after", "Work/B"], ["--unpin", "--prio", "4"], ["--status", "done", "--prio", "2"], ["--drop-after"], ["--title", "x"], []):
            with self.subTest(flags=flags), self.assertRaises(signing.Refused):
                signing.task_argv("work/a", ["set", "work/a", *flags])


class TestHubKanban(HubCase):
    def board_register(self) -> dict:
        return {
            "work/a": {"title": "A", "status": "queued", "worker": "Stage", "roles": {"Stage": "RA"}, "key_results": [{"text": "shipped", "met": False}], "updated": iso(time.time() - 4 * DAY)},
            "work/b": {"title": "B", "status": "running", "worker": "Docs", "after": ["work/a"], "updated": iso(time.time() - DAY)},
            "work/c": {"title": "C", "status": "queued", "worker": "Stage"},
            "work/d": {"title": "D", "status": "done", "worker": "Docs", "end": iso(time.time() - 2 * DAY)},
            "work/e": {"title": "E", "status": "queued", "worker": "-"},
            "operator/push": {"title": "git push", "workdir": "/repo", "status": "queued"},
        }

    def test_the_state_carries_the_change_time_the_movable_rows_and_the_queue_line(self):
        now = time.time()
        register = self.board_register()
        entries = [
            {"id": "gate-1", "seq": 1, "kind": "gate", "task": "work/c", "name": "Stage", "hotfix": None, "status": "active", "enqueued": now - 300, "granted": now - 200, "cmd": "make test"},
            {"id": "gate-2", "seq": 2, "kind": "gate", "task": "work/a", "name": "Stage", "hotfix": None, "status": "waiting", "enqueued": now - 100, "granted": None, "cmd": "make test"},
            {"id": "gate-3", "seq": 3, "kind": "gate", "task": "work/c", "name": "Stage", "hotfix": None, "status": "waiting", "enqueued": now - 50, "granted": None, "cmd": "make test"},
            {"id": "gate-4", "seq": 4, "kind": "gate", "task": None, "name": "Stage", "hotfix": None, "status": "waiting", "enqueued": now - 40, "granted": None, "cmd": "make test"},
        ]
        self.write_council({"rasci.json": register, "queue.json": {"seq": 4, "entries": entries}})
        state = self.snapshot()
        rows = {row["task"]: row for row in state["tasks"]}
        self.assertAlmostEqual(rows["work/a"]["updated"], now - 4 * DAY, delta=2)
        self.assertIsNone(rows["work/c"]["updated"])
        self.assertEqual({task: (row["movable"], row["editable"]) for task, row in rows.items() if not task.startswith("queue/")}, {
            "work/a": (True, True), "work/b": (True, True), "work/c": (True, True), "work/d": (True, False), "work/e": (True, True), "operator/push": (False, False),
        })
        self.assertEqual((rows["queue/gate-1"]["movable"], rows["queue/gate-1"]["updated"]), (False, None))
        self.assertEqual(state["queue_line"], ["work/c", "work/a"])

    def test_a_signed_board_batch_reaches_the_register_through_the_runner_and_tells_each_worker_once(self):
        self.write_council({"rasci.json": self.board_register()})
        self.claim("s1", "Stage session")
        signer = self.pin()
        items = [
            change(["set", "work/c", "--status", "running"], "work/c"),
            change(["set", "work/c", "--prio", "4"], "work/c"),
            change(["set", "work/a", "--after", "work/c"], "work/a"),
            change(["set", "work/b", "--drop-after", "work/a"], "work/b"),
            change(["set", "work/d", "--status", "running"], "work/d"),
            change(["set", "work/e", "--unpin"], "work/e"),
        ]
        status, _, body = self.post_json("/api/tasks", {"items": items, "proof": self.signed(items, signer)}, self.guard(self.host))
        self.assertEqual(status, 202, body)
        self.assertEqual((len(json.loads(body)["jobs"]), self.scripts.calls), (6, []))
        self.run_runner()
        self.assertEqual(self.scripts.calls, [
            (skill_scripts.RADIO, ["post", "--to", "Stage session", "--session", "Operator", f"{tasking.TOLD}: rasci.py set work/c --status running; rasci.py set work/c --prio 4; rasci.py set work/a --after work/c"]),
            (skill_scripts.RADIO, ["post", "--to", "Docs", "--session", "Operator", f"{tasking.TOLD}: rasci.py set work/b --drop-after work/a; rasci.py set work/d --status running"]),
        ])
        stored = json.loads((self.council / "rasci.json").read_text(encoding="utf-8"))
        self.assertEqual((stored["work/c"]["status"], stored["work/c"]["prio"], stored["work/a"]["after"], "after" in stored["work/b"]), ("running", 4, ["work/c"], False))
        self.assertEqual((stored["work/d"]["status"], "end" in stored["work/d"], "prio" in stored["work/e"]), ("running", False, False))
        self.assertTrue(all("updated" in stored[task] for task in ("work/a", "work/b", "work/c", "work/d")))
        self.assertEqual([job["status"] for job in self.snapshot()["jobs"] if job["kind"] == "task"], ["done"] * 6)

    def test_the_executor_refuses_a_cycle_a_done_with_an_open_key_result_and_a_forged_change_and_says_why(self):
        self.write_council({"rasci.json": self.board_register()})
        before = (self.council / "rasci.json").read_bytes()
        signer = self.pin()
        items = [change(["set", "work/a", "--after", "work/b"], "work/a"), change(["set", "work/a", "--status", "done"], "work/a")]
        proof = self.signed(items, signer)
        status, _, body = self.post_json("/api/tasks", {"items": items, "proof": proof}, self.guard(self.host))
        self.assertEqual(status, 202, body)
        fields = {"kind": "task", "task": "work/a", "argv": ["set", "work/a", "--status", "stopped"], "command": "x", "directory": "", "sha256": "", "status": "queued", "proof": proof}
        forged = self.httpd.hub.jobs.add({**fields, "code": None, "output": "", "created_ts": time.time(), "started": None, "finished": None})
        self.run_runner()
        jobs = {job["command"]: job for job in self.snapshot()["jobs"] if job["kind"] == "task"}
        cycle, done = jobs["rasci.py set work/a --after work/b"], jobs["rasci.py set work/a --status done"]
        self.assertEqual((cycle["status"], cycle["code"]), ("failed", 2))
        self.assertIn("rasci: work/a: --after work/b closes a cycle", cycle["output"])
        self.assertEqual((done["status"], done["code"]), ("failed", 2))
        self.assertIn("rasci: work/a: 1 key result(s) open", done["output"])
        record = self.httpd.hub.jobs.get(forged["id"])
        self.assertEqual(record["status"], "refused")
        self.assertTrue(record["output"].startswith(runner.REFUSED), record["output"])
        self.assertIn("does not list this item", record["output"])
        self.assertEqual((self.council / "rasci.json").read_bytes(), before)
        self.assertEqual(self.scripts.calls, [])

    def test_only_the_changes_rasci_applied_are_told_once_their_whole_batch_ended(self):
        self.write_council({"rasci.json": self.board_register()})
        signer = self.pin()
        items = [change(["set", "work/a", "--status", "done"], "work/a"), change(["set", "work/a", "--prio", "2"], "work/a")]
        status, _, body = self.post_json("/api/tasks", {"items": items, "proof": self.signed(items, signer)}, self.guard(self.host))
        self.assertEqual((status, self.scripts.calls), (202, []), body)
        self.run_runner()
        self.assertEqual(self.scripts.calls, [(skill_scripts.RADIO, ["post", "--to", "Stage", "--session", "Operator", f"{tasking.TOLD}: rasci.py set work/a --prio 2"])])
        jobs = [job for job in self.snapshot()["jobs"] if job["kind"] == "task"]
        self.assertEqual(sorted(job["status"] for job in jobs), ["done", "failed"])
        self.assertEqual(len({job["batch"] for job in jobs}), 1)
        self.assertEqual(self.httpd.hub.tell_applied(jobs[0]), [])
        self.assertEqual(len(self.scripts.calls), 1)

    def test_the_hub_signs_a_status_move_of_an_ended_task_but_no_other_change_of_it_and_no_operator_row(self):
        self.write_council({"rasci.json": self.board_register()})
        good = self.guard(self.host)
        self.assertEqual(self.post_json("/api/sign", {"items": [change(["set", "work/d", "--status", "queued"], "work/d")]}, good)[0], 200)
        for items, code in (
            ([change(["set", "work/d", "--prio", "2"], "work/d")], 409),
            ([change(["set", "work/d", "--after", "work/a"], "work/d")], 409),
            ([change(["set", "operator/push", "--status", "done"], "operator/push")], 400),
            ([change(["set", "work/a", "--after", "operator/push"], "work/a")], 400),
            ([change(["set", "work/a", "--status", "done", "--prio", "1"], "work/a")], 400),
        ):
            with self.subTest(items=items):
                self.assertEqual(self.post_json("/api/sign", {"items": items}, good)[0], code)
        self.assertEqual(self.scripts.calls, [])

    def test_the_page_ships_the_board_modules_and_every_board_control_is_a_labelled_icon(self):
        html = self.index()
        self.assertIn(KANBAN.read_text(encoding="utf-8").strip(), html)
        self.assertIn("function kanbanBoard(shown)", html)
        self.assertIn(".kanban-lines", html)
        self.assertIn("const TASK_COLUMNS = Kanban.COLUMNS;", html)
        page = (HUB / "templates" / "page-kanban.js").read_text(encoding="utf-8")
        controls = [line for line in page.splitlines() if re.search(r'h\("(?:button|summary|span)", (?:\{|named)', line) and "icon(" in line or 'h("button"' in line]
        self.assertGreaterEqual(len(controls), 6)
        for line in controls:
            with self.subTest(line=line.strip()[:90]):
                self.assertTrue("named(" in line or "title:" in line, line)
        self.assertNotIn("innerHTML", page)


if __name__ == "__main__":
    unittest.main()
