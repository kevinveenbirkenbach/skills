"""Exercise requirements 075 and 088: the stale list, its prefix groups and filter and the dial of the page, the uncapped signed prune through the hub and the runner's argv, not_before and replay rules."""

from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from hub_case import HubCase
from hub_support import HUB, RASCI, RUNNER, runner, signing, verifier

pruning = runner.pruning
TEMPLATES = HUB / "templates"
NOW = 2_000_000_000
OLD = "2026-01-01T00:00:00+00:00"
FAKE_RADIO = """import json
import pathlib
import sys

here = pathlib.Path(__file__)
with here.with_suffix(".calls").open("a", encoding="utf-8") as calls:
    calls.write(json.dumps(sys.argv[1:]) + "\\n")
print("ts: 1.0")
"""
PROBE = """
const P = require(process.argv[1]);
const D = require(process.argv[2]);
const now = Number(process.argv[3]);
const DAY = 86400;
const row = (task, age, fields) => ({task, kind: "task", status: "queued", worker: "-", roles: {}, editable: true, ended: false, updated: now - age * DAY, ...fields});
const rows = [row("work/two", 2), row("work/four", 4), row("work/old", 9), row("work/ended", 9, {ended: true, editable: false}),
  row("operator/x", 9, {kind: "command", editable: false}), row("work/busy", 9, {worker: "Docs"}), row("work/none", 9, {updated: null})];
const sources = {now, tasks: rows, beats: {Docs: now - 30}, runner: null};
const ids = (days) => P.stale(rows, sources, days).map((found) => found.task);
const apply = (id, status, at) => ({id, kind: "prune", status, argv: ["prune", "--since", "1000", "work/old"], not_before: at});
const range = {min: 1, max: 60, page: 5};
console.log(JSON.stringify({
  three: ids(3), five: ids(5), one: ids(1), defaults: P.STALE_DAYS, minutes: P.MINUTES,
  items: P.items(["work/old", "work/four"], 3, 1000, 10),
  pending: P.pending([apply("j2", "queued", now + 900), {id: "j0", kind: "prune", status: "queued", argv: ["announce"]}, apply("j1", "queued", now + 125), apply("j3", "done", now + 5)], now),
  late: P.pending([apply("j1", "queued", now - 5)], now),
  none: P.pending([], now),
  clocks: [D.countdown(0), D.countdown(65), D.countdown(600)],
  days: ["3", " 12 ", "0", "1000", "x", "2.5"].map(P.daysOf),
  points: [D.point(0, 60, 58), D.point(15, 60, 58), D.point(30, 60, 58)].map((point) => point.map(Math.round)),
  keys: ["ArrowRight", "PageUp", "End", "Home", "ArrowLeft", "PageDown", "Tab"].map((key) => D.stepped(key, 10, range)),
  ends: [D.stepped("ArrowRight", 60, {min: 0, max: 60, page: 5}), D.stepped("ArrowLeft", 1, range), D.stepped("PageDown", 3, range)],
  angles: [D.fromAngle(90, 60), D.fromAngle(-90, 60), D.fromAngle(180, 60)],
  ticks: [D.ticks(5).length, D.ticks(5).filter((tick) => tick.long).length],
  clamp: [D.clamp(61.4, {min: 0, max: 60}), D.clamp(-3, range), D.clamp(7.6, {min: 0, max: 60})],
  groups: P.groups([row("work/b", 4), row("solo", 5), row("ci/x", 6), row("work/a", 7), row("other/y", 3)]).map((group) => [group.prefix, group.rows.map((found) => found.task)]),
  owners: [P.owner(row("a", 1, {worker: "Docs"})), P.owner(row("a", 1, {responsible: "Main, Docs"})), P.owner(row("a", 1, {responsible: "-"})), P.owner(row("a", 1))],
  matches: [P.matches(row("ci/x", 1, {title: "Fix the Build"}), " build "), P.matches(row("ci/x", 1, {worker: "Docs"}), "DOC"), P.matches(row("ci/x", 1), "CI/"), P.matches(row("ci/x", 1), "work"), P.matches(row("ci/x", 1), "  ")],
}));
"""
PREFIXES = ("ci", "cluster", "work", "fix")


def many_tasks(count: int) -> list[str]:
    return [f"{PREFIXES[index % len(PREFIXES)]}/t{index:03d}" if index % 25 else f"solo-{index:03d}" for index in range(count)]


def prune_items(tasks: list[str], since: int, deadline: int, days: str = "3") -> list[dict]:
    return [
        {"kind": "prune", "argv": ["announce", "--days", days, "--deadline", str(deadline), *tasks]},
        {"kind": "prune", "argv": ["prune", "--since", str(since), *tasks], "not_before": deadline},
    ]


def register_row(status: str) -> dict:
    return {"roles": {"Docs": "RA"}, "status": status, "updated": OLD, "title": "t"}


class TestPagePrune(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        done = subprocess.run(["node", "-e", PROBE, str(TEMPLATES / "prune.js"), str(TEMPLATES / "dial.js"), str(NOW)], capture_output=True, text=True, timeout=60, check=True)
        cls.data = json.loads(done.stdout)

    def test_the_stale_list_holds_the_open_unmarked_tasks_without_a_change_for_n_days_oldest_first(self):
        self.assertEqual((self.data["three"], self.data["five"], self.data["one"]), (["work/old", "work/four"], ["work/old"], ["work/old", "work/four", "work/two"]))
        self.assertEqual((self.data["defaults"], self.data["minutes"]), (3, {"value": 10, "min": 1, "max": 60, "page": 5}))

    def test_one_list_becomes_the_announce_and_the_apply_item_with_the_deadline_as_not_before(self):
        self.assertEqual(self.data["items"], prune_items(["work/old", "work/four"], 1000, 1600))

    def test_the_countdown_reads_the_nearest_queued_apply_job_and_never_goes_below_zero(self):
        self.assertEqual(self.data["pending"], {"job": "j1", "deadline": NOW + 125, "tasks": ["work/old"], "left": 125})
        self.assertEqual((self.data["late"]["left"], self.data["none"]), (0, None))
        self.assertEqual(self.data["clocks"], ["0:00", "1:05", "10:00"])
        self.assertEqual(self.data["days"], [3, 12, None, None, None, None])

    def test_the_generic_dial_maps_values_keys_angles_and_ticks_like_the_undo_dial(self):
        self.assertEqual(self.data["points"], [[70, 12], [128, 70], [70, 128]])
        self.assertEqual(self.data["keys"], [11, 15, 60, 1, 9, 5, None])
        self.assertEqual(self.data["ends"], [60, 1, 1])
        self.assertEqual(self.data["angles"], [15, 45, 30])
        self.assertEqual(self.data["ticks"], [60, 12])
        self.assertEqual(self.data["clamp"], [60, 1, 8])

    def test_the_dialog_groups_by_prefix_with_other_last_and_filters_on_slug_title_and_owner(self):
        self.assertEqual(self.data["groups"], [["ci", ["ci/x"]], ["work", ["work/b", "work/a"]], ["other", ["solo", "other/y"]]])
        self.assertEqual(self.data["owners"], ["Docs", "Main", "-", "-"])
        self.assertEqual(self.data["matches"], [True, True, True, False, True])


class TestPruneArgv(unittest.TestCase):
    def test_exactly_the_announce_and_the_apply_shapes_pass(self):
        announce, apply = prune_items(["work/a", "work/b-1.x"], NOW - 60, NOW + 600)
        self.assertEqual(pruning.prune_argv(announce["argv"], None), announce["argv"])
        self.assertEqual(pruning.prune_argv(apply["argv"], apply["not_before"]), apply["argv"])
        self.assertEqual(pruning.prune_item(apply["argv"], NOW + 600), apply)
        self.assertEqual(pruning.prune_item(announce["argv"], None), announce)

    def test_checked_tasks_takes_300_distinct_slugs_and_still_refuses_duplicates_invalid_slugs_and_records(self):
        tasks = many_tasks(300)
        self.assertEqual(pruning.checked_tasks(tasks), tasks)
        announce, apply = prune_items(tasks, NOW - 60, NOW + 600)
        self.assertEqual(pruning.prune_argv(announce["argv"], None), announce["argv"])
        self.assertEqual(pruning.prune_argv(apply["argv"], apply["not_before"]), apply["argv"])
        refused = {
            "none": [], "duplicate": [*tasks, tasks[150]], "upper case": [*tasks, "Work/x"], "empty segment": ["work//x"],
            "leading dash": ["-x"], "too long": ["a" * 101], "space": ["work/a b"], "operator row": [*tasks, "operator/x"], "hotfix row": [*tasks, "hotfix/x"],
        }
        for name, listed in refused.items():
            with self.subTest(name=name):
                self.assertRaises(signing.Refused, pruning.checked_tasks, listed)

    def test_every_other_argv_or_not_before_is_refused(self):
        cases = {
            "text": ("prune --since 1 work/a", NOW), "no texts": (["prune", "--since", 1, "work/a"], NOW),
            "announce with not_before": (["announce", "--days", "3", "--deadline", str(NOW), "work/a"], NOW),
            "apply without not_before": (["prune", "--since", str(NOW - 600), "work/a"], None),
            "apply bool not_before": (["prune", "--since", str(NOW - 600), "work/a"], True),
            "window too short": (["prune", "--since", str(NOW - 59), "work/a"], NOW),
            "window too long": (["prune", "--since", str(NOW - 3601), "work/a"], NOW),
            "no tasks": (["prune", "--since", str(NOW - 600)], NOW), "twice": (["prune", "--since", str(NOW - 600), "work/a", "work/a"], NOW),
            "operator row": (["prune", "--since", str(NOW - 600), "operator/x"], NOW),
            "hotfix row": (["prune", "--since", str(NOW - 600), "hotfix/x"], NOW), "option task": (["prune", "--since", str(NOW - 600), "--status"], NOW),
            "zero days": (["announce", "--days", "0", "--deadline", str(NOW), "work/a"], None), "short epoch": (["announce", "--days", "3", "--deadline", "99", "work/a"], None),
            "set": (["set", "work/a", "--status", "stopped"], None), "rm": (["rm", "work/a"], None),
        }
        for name, (argv, not_before) in cases.items():
            with self.subTest(name=name):
                self.assertRaises(signing.Refused, pruning.prune_argv, argv, not_before)

    def test_an_announce_must_lie_ahead_and_an_apply_job_must_be_due(self):
        announce, apply = prune_items(["work/a"], NOW - 60, NOW + 600)
        pruning.timely(announce["argv"], None, NOW)
        pruning.timely(apply["argv"], NOW + 600, NOW + 600)
        self.assertRaises(signing.Refused, pruning.timely, announce["argv"], None, NOW + 600)
        self.assertRaises(signing.Refused, pruning.timely, apply["argv"], NOW + 600, NOW + 599)
        late = prune_items(["work/a"], NOW, NOW + signing.PRUNE_WINDOW + pruning.SKEW + 1)[0]
        self.assertRaises(signing.Refused, pruning.timely, late["argv"], None, NOW)

    def test_the_announcement_names_every_task_and_the_deadline_in_local_time_and_iso(self):
        deadline = NOW + 600
        local = datetime.datetime.fromtimestamp(deadline).astimezone()
        argv = pruning.radio_argv(prune_items(["work/a", "work/b"], NOW, deadline)[0]["argv"])
        self.assertEqual((argv[:2], argv[3:]), (["send", "security"], ["--session", "Operator"]))
        for part in (f"at {local:%H:%M}", local.isoformat(timespec="seconds"), "work/a, work/b", "3 days", "rasci.py keep <task>"):
            with self.subTest(part=part):
                self.assertIn(part, argv[2])

    def test_a_prune_approval_lives_through_its_window_and_other_mixes_keep_theirs(self):
        announce, apply = prune_items(["work/a"], NOW, NOW + 600)
        self.assertEqual(signing.lifetime([pruning.prune_item(announce["argv"], None), pruning.prune_item(apply["argv"], NOW + 600)]), signing.LIFETIME + signing.PRUNE_WINDOW)
        self.assertEqual(signing.lifetime([pruning.prune_item(announce["argv"], None), signing.queue_item(["override", "test-1"])]), signing.LIFETIME)


class TestReplaySeen(unittest.TestCase):
    def test_an_accepted_assertion_passes_the_counter_again_for_its_other_items_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "runner.json"
            nonce, other = "a" * 32, "b" * 32
            verifier.consume(store, f"{nonce}:announce", NOW + 900, "key", 5, nonce, NOW)
            verifier.consume(store, f"{other}:later", NOW + 900, "key", 6, other, NOW + 10)
            verifier.consume(store, f"{nonce}:apply", NOW + 900, "key", 5, nonce, NOW + 600)
            self.assertEqual(json.loads(store.read_text(encoding="utf-8"))["counts"]["key"], {"count": 6, "nonce": other})
            with self.assertRaises(signing.Refused):
                verifier.consume(store, f"{nonce}:apply", NOW + 900, "key", 5, nonce, NOW + 601)
            with self.assertRaises(signing.Refused):
                verifier.consume(store, f"{'c' * 32}:forged", NOW + 900, "key", 5, "c" * 32, NOW + 602)
            with self.assertRaises(signing.Refused):
                verifier.consume(store, f"{nonce}:after", NOW + 900, "key", 5, nonce, NOW + 901)


class PruneCase(HubCase):
    def setUp(self):
        super().setUp()
        self.council.mkdir(exist_ok=True)
        tasks = {"work/a": register_row("queued"), "work/b": register_row("running"), "work/c": register_row("queued"), "work/done": register_row("done")}
        (self.council / "rasci.json").write_text(json.dumps(tasks), encoding="utf-8")

    def queue_prune(self, tasks: list[str], since: int, deadline: int) -> dict:
        items = prune_items(tasks, since, deadline)
        status, _, body = self.post_json("/api/prune", {"items": items, "proof": self.signed(items, self.pin())}, self.guard(self.host))
        self.assertEqual(status, 202, body)
        return json.loads(body)


class TestHubPrune(PruneCase):
    def test_one_signature_queues_exactly_the_announce_and_the_held_apply_job(self):
        now = int(time.time())
        items = prune_items(["work/a", "work/b"], now - 30, now + 600)
        payload = self.prepare(items)["payload"]
        self.assertEqual(sorted(payload["items"]), sorted(signing.item_hash(pruning.prune_item(item["argv"], item.get("not_before"))) for item in items))
        self.assertAlmostEqual(payload["expires"] - now, signing.LIFETIME + signing.PRUNE_WINDOW, delta=5)
        proof = self.pin().proof(payload, self.origin)
        self.assertEqual(self.post_json("/api/prune", {"items": items, "proof": proof}, {"Host": self.host})[0], 403)
        status, _, body = self.post_json("/api/prune", {"items": items, "proof": proof}, self.guard(self.host))
        self.assertEqual(status, 202, body)
        self.assertEqual(len(json.loads(body)["jobs"]), 2)
        jobs = sorted(self.runner_jobs(), key=lambda job: job["argv"][0])
        self.assertEqual([(job["kind"], job["task"], job["argv"], job.get("not_before")) for job in jobs], [("prune", "prune", items[0]["argv"], None), ("prune", "prune", items[1]["argv"], now + 600)])
        self.assertTrue(jobs[0]["command"].startswith("radio.py send security Stale task prune at "), jobs[0]["command"])
        self.assertEqual(jobs[1]["command"], f"rasci.py prune --since {now - 30} work/a work/b")

    def test_the_hub_refuses_a_prune_whose_two_jobs_disagree_or_name_no_open_task(self):
        now = int(time.time())
        good = prune_items(["work/a"], now - 30, now + 600)
        cases = {
            "one item": good[:1], "swapped": good[::-1], "other tasks": [good[0], prune_items(["work/c"], now - 30, now + 600)[1]],
            "other deadline": [good[0], {**good[1], "not_before": now + 660}], "deadline passed": prune_items(["work/a"], now - 700, now - 1),
            "old since": prune_items(["work/a"], now - signing.LIFETIME - 60, now + 30), "future since": prune_items(["work/a"], now + pruning.SKEW + 60, now + pruning.SKEW + 600),
            "done task": prune_items(["work/done"], now - 30, now + 600), "unknown task": prune_items(["work/zz"], now - 30, now + 600),
            "extra key": [{**good[0], "not_before": None}, good[1]],
        }
        for name, items in cases.items():
            with self.subTest(name=name):
                status, _, body = self.post_json("/api/sign", {"items": items}, self.guard(self.host))
                self.assertEqual(status, 400, body)
        proof = self.signed(good, self.pin())
        status, _, body = self.post_json("/api/prune", {"items": prune_items(["work/c"], now - 30, now + 600), "proof": proof}, self.guard(self.host))
        self.assertEqual(status, 400, body)
        self.assertEqual(self.runner_jobs(), [])

    def test_the_page_ships_the_prune_dialog_and_the_shared_dial(self):
        html = self.index()
        for marker in ("const Dial = ", "const Prune = ", "pruneControls(stale)", '"/api/prune"', 'name: "undo-dial"', 'name: "prune-dial"', 'id: "kanban-prune"'):
            with self.subTest(marker=marker):
                self.assertIn(marker, html)


class TestRunnerPrune(PruneCase):
    def setUp(self):
        super().setUp()
        self.home = self.outside / "home"
        self.home.mkdir(parents=True)
        self.radio = self.outside / "radio" / "radio.py"
        self.radio.parent.mkdir(parents=True)
        self.radio.write_text(FAKE_RADIO, encoding="utf-8")

    def flags(self) -> list[str]:
        return ["--radio", str(self.radio), "--rasci", str(RASCI), "--council", str(self.council)]

    def run_prune_runner(self, flags: list[str]) -> None:
        trust = ["--approvers", str(self.approvers), "--replay", str(self.replay / "runner.json"), "--state", str(self.state)]
        command = [sys.executable, str(RUNNER), "--port", str(self.port), "--interval", "0.1", *trust, *flags, "--once"]
        done = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False, env={**os.environ, "HOME": str(self.home)})
        self.assertEqual(done.returncode, 0, done.stderr)

    def jobs(self) -> list[tuple[str, str, int | None]]:
        return [(job["argv"][0], job["status"], job["code"]) for job in sorted(self.httpd.hub.jobs.listed(), key=lambda job: job["argv"][0])]

    def statuses(self) -> dict[str, str]:
        return {task: row["status"] for task, row in json.loads((self.council / "rasci.json").read_text(encoding="utf-8")).items()}

    def keep(self, task: str) -> None:
        env = {"PATH": "/usr/bin:/bin", "HOME": str(self.home), "AGENTS_COUNCIL_ROOT": str(self.council)}
        done = subprocess.run([sys.executable, str(RASCI), "keep", task], capture_output=True, text=True, env=env, check=False, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_the_announce_runs_at_once_the_apply_job_waits_unclaimed_and_stops_only_the_unkept_tasks(self):
        now = int(time.time())
        deadline = now + 4
        self.queue_prune(["work/a", "work/b"], now - 100, deadline)
        self.run_prune_runner(self.flags())
        self.assertEqual(self.jobs(), [("announce", "done", 0), ("prune", "queued", None)])
        sent = [json.loads(line) for line in self.radio.with_suffix(".calls").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0], pruning.radio_argv(prune_items(["work/a", "work/b"], now - 100, deadline)[0]["argv"]))
        self.assertEqual(self.statuses(), {"work/a": "queued", "work/b": "running", "work/c": "queued", "work/done": "done"})
        self.keep("work/b")
        time.sleep(max(0.0, deadline - time.time()) + 1)
        self.run_prune_runner(self.flags())
        self.assertEqual(self.jobs(), [("announce", "done", 0), ("prune", "done", 0)])
        self.assertEqual(self.statuses(), {"work/a": "stopped", "work/b": "running", "work/c": "queued", "work/done": "done"})
        output = next(job["output"] for job in self.httpd.hub.jobs.listed() if job["argv"][0] == "prune")
        self.assertIn("stopped work/a", output)
        self.assertIn("kept work/b: changed at ", output)

    def test_one_signature_prunes_300_tasks_through_the_hub_and_the_runner(self):
        tasks = many_tasks(300)
        (self.council / "rasci.json").write_text(json.dumps({task: register_row("queued") for task in tasks}), encoding="utf-8")
        now = int(time.time())
        deadline = now + 4
        self.assertEqual(len(self.queue_prune(tasks, now - 100, deadline)["jobs"]), 2)
        self.run_prune_runner(self.flags())
        self.assertEqual(self.jobs(), [("announce", "done", 0), ("prune", "queued", None)])
        sent = [json.loads(line) for line in self.radio.with_suffix(".calls").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(sent, [pruning.radio_argv(prune_items(tasks, now - 100, deadline)[0]["argv"])])
        time.sleep(max(0.0, deadline - time.time()) + 1)
        self.run_prune_runner(self.flags())
        self.assertEqual(self.jobs(), [("announce", "done", 0), ("prune", "done", 0)])
        self.assertEqual(self.statuses(), dict.fromkeys(tasks, "stopped"))

    def test_without_radio_the_runner_refuses_the_announce_and_leaves_the_apply_job_unclaimed(self):
        now = int(time.time())
        self.queue_prune(["work/a"], now - 100, now + 600)
        self.run_prune_runner(["--rasci", str(RASCI), "--council", str(self.council)])
        jobs = sorted(self.httpd.hub.jobs.listed(), key=lambda job: job["argv"][0])
        self.assertEqual([(job["status"], job["output"]) for job in jobs], [("refused", runner.UNPRUNED), ("queued", "")])
        self.assertFalse(self.radio.with_suffix(".calls").exists())

    def test_the_runner_refuses_an_apply_job_whose_not_before_or_tasks_differ_from_the_signed_ones(self):
        now = int(time.time())
        self.queue_prune(["work/a"], now - 100, now + 600)
        apply = next(job for job in self.httpd.hub.jobs.listed() if job["argv"][0] == "prune")
        self.httpd.hub.jobs.change(apply["id"], {"not_before": now - 40})
        self.run_prune_runner(self.flags())
        refused = self.httpd.hub.jobs.get(apply["id"])
        self.assertEqual(refused["status"], "refused")
        self.assertIn("does not list this item", refused["output"])
        self.assertEqual(self.statuses()["work/a"], "queued")

    def test_prune_refusal_checks_the_shape_and_the_due_time_before_any_signature(self):
        now = int(time.time())
        trust = mock.Mock()
        self.assertIn("no prune announce", runner.prune_refusal({"argv": ["set", "work/a", "--status", "stopped"], "proof": None}, trust, now))
        announce, apply = prune_items(["work/a"], now - 100, now + 600)
        self.assertIn("not due before", runner.prune_refusal({**apply, "proof": None}, trust, now))
        self.assertIn("passed", runner.prune_refusal({**announce, "proof": None}, trust, now + 601))
        self.assertTrue(runner.not_due(apply, now))
        self.assertFalse(runner.not_due(apply, now + 600))
        self.assertFalse(runner.not_due(announce, now))
        scripts = runner.Scripts(register=None, gates=None, queue=None, schedules=None, radio=Path("/x/radio.py"))
        with self.assertRaises(signing.Refused):
            runner.prune({"argv": ["rm", "work/a"]}, scripts, print)


if __name__ == "__main__":
    unittest.main()
