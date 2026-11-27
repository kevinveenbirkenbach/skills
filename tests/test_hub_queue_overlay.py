from __future__ import annotations

import copy
import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from hub_case import HubCase
from hub_support import HUB
from kvb_orchestrator import queue_order
from kvb_orchestrator.errors import ToolError
from kvb_orchestrator.viewstore import VIEW, ViewStore, valid_view

KANBAN = HUB / "templates" / "kanban.js"
FIXTURE = Path(__file__).resolve().parent / "queue-list.json"
ROWS = json.loads(FIXTURE.read_text(encoding="utf-8"))
NEW_QUEUE = """import json
import os
import pathlib
import sys

here = pathlib.Path(__file__)
with here.with_suffix(".calls").open("a", encoding="utf-8") as calls:
    calls.write(" ".join(sys.argv[1:]) + "\\n")
here.with_suffix(".env").write_text(json.dumps(dict(os.environ)), encoding="utf-8")
if sys.argv[1:] != ["list", "--json"]:
    sys.exit(2)
sys.stdout.write(here.with_name("rows.json").read_text(encoding="utf-8"))
"""
OLD_QUEUE = """import argparse

parser = argparse.ArgumentParser(prog="queue.py")
commands = parser.add_subparsers(dest="command", required=True)
commands.add_parser("list")
parser.parse_args()
print("position\\tid\\tstatus")
"""
SLOW_QUEUE = "import time\ntime.sleep(5)\n"
FAILING_QUEUE = "import sys\nsys.exit(1)\n"
LINE_ORDER = ["work/bravo", "work/alpha", "work/delta", "work/charlie"]
HUB_ORDER = ["work/bravo", "work/alpha", "work/charlie", "work/delta"]
MODEL_PROBE = """
const K = require(process.argv[1]);
const rows = JSON.parse(process.argv[2]);
const card = (task, kind) => ({task, kind: kind || "task"});
const cards = [card("work/alpha"), card("work/bravo"), card("work/charlie"), card("work/delta"), card("work/echo"), card("queue/q-2", "queue"), card("queue/q-9", "queue")];
const line = ["work/bravo", "work/alpha", "work/delta", "work/charlie", "work/hidden"];
const marks = (jobs) => Object.fromEntries(Object.entries(K.queued(cards, line, jobs)).map(([task, mark]) => [task, [mark.place, mark.of, mark.jobs.map((job) => job.id)]]));
console.log(JSON.stringify({
  marks: marks(rows),
  degraded: marks(null),
  chips: Object.fromEntries(rows.map((job) => [job.id, K.jobChips(job).map((chip) => [chip.key, chip.text, chip.tone])])),
  hints: K.jobChips(rows[1]).map((chip) => chip.hint),
  why: rows.map(K.whyHere),
  bare: K.whyHere({...rows[2], reason: ""}),
  spans: [0, 59, 60, 3599, 3600, 3660, 86399, 86400, 90000, 172800].map(K.span),
  layers: [[], ["jobs"], ["line", "jobs"]].map(K.layers),
  legend: K.QUEUE_LAYERS,
  sig: [K.queueSig(null), K.queueSig([{...rows[0], waited_s: 119, eta_s: null}])],
}));
"""


def fake_queue(folder: Path, source: str, rows: object) -> Path:
    """Args:
        folder: an empty directory the fake owns.
        source: the fake queue.py.
        rows: what its `list --json` prints, JSON-encoded unless a string.

    Returns:
        The fake queue.py; each run appends its arguments to queue.calls
        and writes its environment to queue.env.
    """
    folder.mkdir(parents=True, exist_ok=True)
    script = folder / "queue.py"
    script.write_text(source, encoding="utf-8")
    (folder / "rows.json").write_text(rows if isinstance(rows, str) else json.dumps(rows), encoding="utf-8")
    return script


def calls(script: Path) -> list[str]:
    log = script.with_suffix(".calls")
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


def board_council(now: float) -> dict:
    """Returns:
        A register and a queue whose grant order the hub ranks as HUB_ORDER
        and the fixture of queue.py ranks as LINE_ORDER.
    """
    entry = {"cmd": "make test", "granted": None, "hotfix": None, "status": "waiting"}
    return {
        "rasci.json": {
            "work/alpha": {"title": "Alpha", "status": "queued", "worker": "Stage", "prio": 1},
            "work/bravo": {"title": "Bravo", "status": "running", "worker": "Docs", "prio": 2},
            "work/charlie": {"title": "Charlie", "status": "queued", "worker": "Stage", "estimates": {"Stage": {"value": 3, "complexity": 2}}},
            "work/delta": {"title": "Delta", "status": "queued", "worker": "Skills"},
        },
        "queue.json": {"seq": 4, "entries": [
            {**entry, "id": "q-1", "seq": 1, "kind": "test", "task": "work/bravo", "name": "Docs", "status": "active", "enqueued": now - 200, "granted": now - 100},
            {**entry, "id": "q-2", "seq": 2, "kind": "quality-high", "task": "work/alpha", "name": "Stage", "hotfix": "alpha", "enqueued": now - 1260},
            {**entry, "id": "q-3", "seq": 3, "kind": "test", "task": "work/charlie", "name": "Stage", "enqueued": now - 30},
            {**entry, "id": "q-4", "seq": 4, "kind": "deploy", "task": "work/delta", "name": "Skills", "enqueued": now - 100},
        ]},
    }


class TestQueueRows(unittest.TestCase):
    def test_the_fixture_reads_back_field_for_field_in_grant_order(self):
        self.assertEqual(queue_order.queue_jobs(FIXTURE.read_text(encoding="utf-8")), ROWS)
        self.assertEqual([job["id"] for job in queue_order.queue_jobs(json.dumps(ROWS))], ["q-1", "q-2", "q-4", "q-3"])

    def test_a_malformed_row_is_bounded_and_one_without_an_id_or_seen_before_is_dropped(self):
        odd = {
            "id": "a", "position": True, "kind": 7, "task": "t" * 501, "name": "Docs", "class": "urgent", "prio": True,
            "wsjf": {"score": 3.5}, "waited_s": -1, "eta_s": "soon", "reason": "r" * 600, "trace": ["one", 5, None, *(f"s{n}" for n in range(30))],
        }
        found = queue_order.queue_jobs(json.dumps([{"id": ""}, "x", {"id": 5}, odd, {**odd, "kind": "again"}, {"id": "b", "position": "w" * 40, "wsjf": 2, "eta_s": 0}]))
        self.assertEqual(found, [
            {"position": None, "id": "a", "kind": "", "task": None, "session": "", "agent": "Docs", "class": None, "prio": None, "wsjf": 3.5,
             "waited_s": None, "eta_s": None, "reason": "r" * 500, "trace": ["one", *(f"s{n}" for n in range(17))], "status": None, "override": False},
            {"position": "w" * 32, "id": "b", "kind": "", "task": None, "session": "", "agent": "", "class": None, "prio": None, "wsjf": 2.0,
             "waited_s": None, "eta_s": 0.0, "reason": "", "trace": [], "status": None, "override": False},
        ])
        self.assertIsNone(queue_order.queue_jobs('[{"id": "n", "waited_s": NaN}]')[0]["waited_s"])

    def test_rows_under_entries_and_one_row_per_line_read_and_other_output_reads_as_none(self):
        self.assertEqual(queue_order.queue_jobs(json.dumps({"entries": ROWS})), ROWS)
        self.assertEqual(queue_order.queue_jobs("\n".join(json.dumps(row) for row in ROWS) + "\n"), ROWS)
        self.assertEqual(queue_order.queue_jobs("[]"), [])
        self.assertEqual([job["id"] for job in queue_order.queue_jobs('{"id": "q-9"}')], ["q-9"])
        for output in ("", "position\tid\n1\tq-1\n", "5", '{"entries": 5}', '{"error": "no config"}', '{"id": "q-1"}\nnot json\n'):
            with self.subTest(output=output):
                self.assertIsNone(queue_order.queue_jobs(output))

    def test_the_grant_order_follows_queue_py_and_keeps_the_hub_order_without_it(self):
        chain = [("q-1", False), ("q-2", True), ("q-3", True), ("q-9", True), ("q-4", True)]
        self.assertEqual(queue_order.grant_order(chain, ROWS), [("q-1", False), ("q-2", True), ("q-4", True), ("q-3", True), ("q-9", True)])
        self.assertIs(queue_order.grant_order(chain, None), chain)


class TestQueueOrderRuns(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)

    def order(self, source: str, rows: object) -> queue_order.QueueOrder:
        return queue_order.QueueOrder(script=fake_queue(self.base / "skills", source, rows), council=self.base / "council", home=self.base / "home")

    def test_it_runs_once_per_window_again_when_the_live_jobs_change_and_never_while_none_is_live(self):
        order = self.order(NEW_QUEUE, ROWS)
        one, two = frozenset({"q-1"}), frozenset({"q-1", "q-2"})
        self.assertEqual(order.get(one, 1000.0), ROWS)
        self.assertEqual(order.get(one, 1000.0 + queue_order.ORDER_SECONDS - 1), ROWS)
        self.assertEqual(calls(order.script), ["list --json"])
        order.get(two, 1010.0)
        order.get(two, 1010.0 + queue_order.ORDER_SECONDS)
        self.assertEqual(order.get(frozenset(), 5000.0), [])
        self.assertEqual(calls(order.script), ["list --json"] * 3)

    def test_a_request_meeting_a_running_read_gets_the_rows_read_before(self):
        order = self.order(NEW_QUEUE, ROWS)
        self.assertEqual(order.get(frozenset({"q-1"}), 1000.0), ROWS)
        with order.lock:
            self.assertEqual(order.get(frozenset({"q-1", "q-2"}), 2000.0), ROWS)
        self.assertEqual(calls(order.script), ["list --json"])

    def test_an_old_queue_py_a_failure_text_output_a_missing_script_and_an_overrun_read_as_none(self):
        cases = {"old": (OLD_QUEUE, ROWS), "failing": (FAILING_QUEUE, ROWS), "text": (NEW_QUEUE, "position\tid\n1\tq-1\n"), "slow": (SLOW_QUEUE, ROWS)}
        for name, (source, rows) in cases.items():
            with self.subTest(case=name), mock.patch.object(queue_order, "ORDER_TIMEOUT", 0.5):
                order = queue_order.QueueOrder(script=fake_queue(self.base / name, source, rows), council=self.base, home=self.base)
                started = time.monotonic()
                self.assertIsNone(order.get(frozenset({"q-1"}), 1000.0))
                self.assertLess(time.monotonic() - started, 4)
        missing = queue_order.QueueOrder(script=self.base / "gone" / "queue.py", council=self.base, home=self.base)
        self.assertIsNone(missing.get(frozenset({"q-1"}), 1000.0))

    def test_the_run_sees_the_council_and_the_state_home_and_nothing_of_the_hub_environment(self):
        order = self.order(NEW_QUEUE, ROWS)
        with mock.patch.dict(os.environ, {"KVB_ORCHESTRATOR_SECRET": "x"}):
            order.get(frozenset({"q-1"}), 1000.0)
        seen = json.loads(order.script.with_suffix(".env").read_text(encoding="utf-8"))
        self.assertEqual((seen["HOME"], seen["AGENTS_COUNCIL_ROOT"], seen["PATH"]), (str(self.base / "home"), str(self.base / "council"), "/usr/local/bin:/usr/bin:/bin"))
        self.assertNotIn("KVB_ORCHESTRATOR_SECRET", seen)


class TestHubQueueOverlay(HubCase):
    def install(self, source: str) -> Path:
        script = fake_queue(self.state.parent / "fake-skills", source, ROWS)
        self.httpd.hub.queue_order.script = script
        return script

    def queue_edges(self, state: dict) -> list[tuple[str, str]]:
        return [(edge["from"], edge["to"]) for edge in state["task_edges"] if edge["kind"] == "queue"]

    def test_the_state_carries_the_queue_py_rows_and_orders_the_line_and_the_queue_edges_by_them(self):
        self.write_council(board_council(time.time()))
        script = self.install(NEW_QUEUE)
        state = self.snapshot()
        self.assertEqual(state["queue_jobs"], ROWS)
        self.assertEqual(state["queue_line"], LINE_ORDER)
        self.assertEqual(self.queue_edges(state), [("queue/q-1", "queue/q-2"), ("queue/q-2", "queue/q-4"), ("queue/q-4", "queue/q-3")])
        self.snapshot()
        self.assertEqual(calls(script), ["list --json"])

    def test_an_install_without_list_json_keeps_today_s_order_and_sends_no_rows(self):
        self.write_council(board_council(time.time()))
        self.install(OLD_QUEUE)
        state = self.snapshot()
        self.assertIsNone(state["queue_jobs"])
        self.assertEqual(state["queue_line"], HUB_ORDER)
        self.assertEqual(self.queue_edges(state), [("queue/q-1", "queue/q-2"), ("queue/q-2", "queue/q-3"), ("queue/q-3", "queue/q-4")])

    def test_a_queue_without_a_live_entry_runs_nothing(self):
        council = board_council(time.time())
        self.write_council({**council, "queue.json": {"seq": 0, "entries": []}})
        script = self.install(NEW_QUEUE)
        state = self.snapshot()
        self.assertEqual((state["queue_jobs"], state["queue_line"], calls(script)), ([], [], []))

    def test_the_page_embeds_the_layer_list_and_ships_the_overlay(self):
        html = self.index()
        self.assertIn('"kanban": {"hidden": []}', html)
        self.assertIn(KANBAN.read_text(encoding="utf-8").strip(), html)
        page = (HUB / "templates" / "page-kanban.js").read_text(encoding="utf-8")
        for needle in ('LegendChips.render(Kanban.QUEUE_LAYERS', 'KANBAN_LAYERS, "hidden")', "Kanban.queued(rows, state.queue_line, state.queue_jobs)", "openPopup(found.label"):
            with self.subTest(needle=needle):
                self.assertIn(needle, page)
        self.assertIn("Kanban.queueSig(state.queue_jobs)", (HUB / "templates" / "page-tasks.js").read_text(encoding="utf-8"))


class TestOverlayModel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        done = subprocess.run(["node", "-e", MODEL_PROBE, str(KANBAN), json.dumps(ROWS)], capture_output=True, text=True, timeout=60, check=True)
        cls.data = json.loads(done.stdout)

    def test_each_card_on_the_line_gets_its_stop_and_its_jobs_and_a_queue_card_its_own_job(self):
        self.assertEqual(self.data["marks"], {
            "work/alpha": [2, 5, ["q-2"]], "work/bravo": [1, 5, ["q-1"]], "work/charlie": [4, 5, ["q-3"]], "work/delta": [3, 5, ["q-4"]], "queue/q-2": [None, 5, ["q-2"]],
        })

    def test_without_queue_py_rows_the_line_stays_numbered_and_no_card_shows_jobs(self):
        self.assertEqual(self.data["degraded"], {"work/alpha": [2, 5, []], "work/bravo": [1, 5, []], "work/charlie": [4, 5, []], "work/delta": [3, 5, []]})

    def test_the_chips_show_position_class_pin_wsjf_gate_wait_and_eta(self):
        self.assertEqual(self.data["chips"], {
            "q-1": [["position", "running", "neutral"], ["class", "fix", "warn"], ["prio", "P2", "neutral"], ["gate", "test", "teal"], ["waited", "waited 1 min", "neutral"], ["eta", "ETA 4 min", "neutral"]],
            "q-2": [["position", "#1", "neutral"], ["class", "hotfix", "bad"], ["prio", "P1", "neutral"], ["wsjf", "WSJF 2.67", "neutral"], ["gate", "quality-high", "teal"],
                    ["waited", "waits 21 min", "neutral"], ["eta", "ETA 8 min", "neutral"]],
            "q-4": [["position", "#2", "neutral"], ["class", "main", "violet"], ["gate", "deploy", "teal"], ["waited", "waits 1 h 6 min", "neutral"], ["eta", "ETA ?", "neutral"]],
            "q-3": [["position", "#3", "neutral"], ["class", "feature", "info"], ["wsjf", "WSJF 1.5", "neutral"], ["gate", "test", "teal"], ["waited", "waits 30 s", "neutral"], ["eta", "ETA 1 h 5 min", "neutral"]],
        })
        self.assertEqual(self.data["hints"], [
            "q-2: grant position #1", "q-2: class hotfix", "q-2: its task is pinned P1", "q-2: WSJF 2.6667 of its task", "q-2: runs the gate quality-high",
            "q-2: waits 21 min in the queue", "q-2: starts in about 8 min",
        ])

    def test_why_here_lists_the_trace_in_order_and_falls_back_to_the_reason(self):
        self.assertEqual(self.data["why"], [
            {"label": "Why here: q-1 at running", "place": "running", "steps": ["granted at its last poll", "slot test:1 of 2"]},
            {"label": "Why here: q-2 at #1", "place": "#1", "steps": ["hotfix first", "rank 0", "line slot:2 behind q-1", "RAM 61 % + 15 % reaches 75 %"]},
            {"label": "Why here: q-4 at #2", "place": "#2", "steps": ["waits behind q-2"]},
            {"label": "Why here: q-3 at #3", "place": "#3", "steps": ["rank 7", "waited 0 h", "line slot:2 behind q-2", "RAM 52 % + 15 GB fits"]},
        ])
        self.assertEqual(self.data["bare"]["steps"], ["queue.py gave no trace and no reason for this job"])

    def test_spans_read_in_their_two_largest_units(self):
        self.assertEqual(self.data["spans"], ["0 s", "59 s", "1 min", "59 min", "1 h", "1 h 1 min", "23 h 59 min", "1 d", "1 d 1 h", "2 d"])

    def test_the_legend_switches_each_layer_and_the_redraw_signature_ignores_seconds(self):
        self.assertEqual(self.data["legend"], [["line", "Queue line", "k-queue-line"], ["jobs", "Queue jobs", "k-queue-jobs"]])
        self.assertEqual(self.data["layers"], [{"line": True, "jobs": True}, {"line": True, "jobs": False}, {"line": False, "jobs": False}])
        self.assertEqual(self.data["sig"], [None, [{**ROWS[0], "waited_s": 1, "eta_s": None}]])


class TestKanbanView(unittest.TestCase):
    def test_the_layer_list_starts_empty_takes_each_known_layer_once_and_refuses_others(self):
        self.assertEqual(VIEW["kanban"], {"hidden": []})
        doc = copy.deepcopy(VIEW)
        doc["kanban"]["hidden"] = ["jobs", "line"]
        self.assertEqual(valid_view(doc), doc)
        for hidden in (["grid"], ["line", "line"], "line", [None]):
            with self.subTest(hidden=hidden), self.assertRaises(ToolError):
                valid_view({**doc, "kanban": {"hidden": hidden}})
        with self.assertRaises(ToolError):
            valid_view({key: value for key, value in doc.items() if key != "kanban"})

    def test_a_view_stored_by_an_older_hub_keeps_its_sections_and_gains_the_layers(self):
        with tempfile.TemporaryDirectory() as folder:
            stored = Path(folder) / "view.json"
            old = {key: value for key, value in copy.deepcopy(VIEW).items() if key != "kanban"}
            old["home"]["pins"] = [{"kind": "panel", "id": "resources-hardware", "w": 6, "h": 3}]
            old["burn"]["overlays"] = ["fix"]
            stored.write_text(json.dumps(old), encoding="utf-8")
            self.assertEqual(ViewStore(stored).get(), {**old, "kanban": {"hidden": []}})


if __name__ == "__main__":
    unittest.main()
