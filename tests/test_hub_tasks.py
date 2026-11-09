from __future__ import annotations

import importlib.util
import json
import os
import signal
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

from hub_case import HubCase
from hub_support import REPO_ROOT, iso, key, runner, signing, verifier
from kvb_orchestrator import settings, skill_scripts, tasks, tree

BROKEN = {"pull": [], "push": [], "source": "invalid"}
FLOW = {"pull": ["origin/main", "store-i18n"], "push": ["main", "production"], "source": "file"}
PRIO = ["set", "work/feature", "--prio", "3"]
ESTIMATE = ["estimate", "work/feature", "Operator", "--value", "8", "--complexity", "3"]
QUEUE_SCRIPT = REPO_ROOT / "skills" / "kvb-org-queue" / "scripts" / "queue.py"


def change(argv: list, task: str = "work/feature") -> dict:
    return {"kind": "task", "id": task, "argv": argv}


def valued(task: str, value: str) -> dict:
    return change(["estimate", task, "Operator", "--value", value], task)


def load_queue():
    spec = importlib.util.spec_from_file_location("queue_for_the_hub_chain", QUEUE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestHubTasks(HubCase):
    def places(self) -> tuple[str, str, str]:
        root = self.write_tree()
        return str(root), f"{root}/repos/github.com/me/demo", f"{root}/worktrees/github.com/me/demo"

    def worktrees(self) -> dict[str, dict]:
        data = json.loads(self.get("/api/tree")[2])
        found = {wt["path"]: wt for repo in data["repos"] for entry in repo["branches"] for wt in entry["worktrees"]}
        return {**found, **{wt["path"]: wt for repo in data["repos"] for wt in repo["detached"]}}

    def test_the_tree_maps_each_worktree_flow_and_a_missing_one_is_none(self):
        root, demo, trees = self.places()
        flows = {path: wt["flow"] for path, wt in self.worktrees().items()}
        self.assertEqual(flows, {
            f"{trees}/feature": FLOW,
            f"{trees}/feature-done": None,
            demo: None,
            f"{trees}/detached": BROKEN,
            f"{root}/worktrees/x/y/lone": None,
            f"{root}/outside/elsewhere": None,
        })

    def test_a_flow_of_the_wrong_shape_reads_as_invalid_and_long_lists_are_capped(self):
        for raw in (
            "x",
            ["main"],
            {"pull": ["a"], "push": ["b"]},
            {"pull": "a", "push": [], "source": "file"},
            {"pull": [1], "push": [], "source": "file"},
            {"pull": ["a b"], "push": [], "source": "file"},
            {"pull": ["a\nb"], "push": [], "source": "file"},
            {"pull": ["x" * 256], "push": [], "source": "file"},
            {"pull": ["a"], "push": ["b"], "source": "File!"},
            {"pull": ["a"], "push": ["b"], "source": 3},
            {"pull": ["a"], "push": ["b"], "source": "invalid"},
        ):
            with self.subTest(raw=raw):
                self.assertEqual(tree.flow({"flow": raw}), BROKEN)
        self.assertIsNone(tree.flow({}))
        self.assertIsNone(tree.flow({"flow": None}))
        many = tree.flow({"flow": {"pull": [f"b{n}" for n in range(40)], "push": ["main"], "source": "config", "extra": 1}})
        self.assertEqual(many, {"pull": [f"b{n}" for n in range(tree.FLOW_LIMIT)], "push": ["main"], "source": "config"})

    def test_worktrees_carry_their_open_work_and_the_open_tasks_on_them(self):
        root, demo, trees = self.places()
        self.write_council({"rasci.json": {
            "work/feature": {"status": "running", "workdir": f"{trees}/feature"},
            "work/old": {"status": "done", "workdir": f"{trees}/feature-done"},
        }})
        found = self.worktrees()
        self.assertEqual({path: wt["open_work"] for path, wt in found.items()}, {
            f"{trees}/feature": ["dirty", "task"],
            f"{trees}/feature-done": [],
            demo: ["unpushed"],
            f"{trees}/detached": ["unmerged"],
            f"{root}/worktrees/x/y/lone": ["unmerged"],
            f"{root}/outside/elsewhere": [],
        })
        self.assertEqual((found[f"{trees}/feature"]["tasks"], found[f"{trees}/feature-done"]["tasks"]), (["work/feature"], []))

    def test_the_state_lists_every_task_ranked_with_roles_wsjf_flow_and_open_work(self):
        _, _, trees = self.places()
        now = time.time()
        register = {
            "work/feature": {
                "title": "Feature", "status": "running", "worker": "Skills session", "objective": "Ship it", "workdir": f"{trees}/feature",
                "roles": {"Skills session": "RA", "Operator": "C", "Docs": "I"}, "key_results": [{"text": "a", "met": True}, {"text": "b", "met": False}],
                "estimates": {"Skills": {"value": 8, "complexity": 2, "at": "2026-11-07T08:00:00+00:00"}, "Docs": {"value": 5, "complexity": 3}},
            },
            "work/pinned": {"title": "Pinned", "status": "blocked", "prio": 1, "branch": "feature/done", "roles": {"Stage": "R"}},
            "work/scored": {"title": "Scored", "status": "queued", "estimates": {"Docs": {"value": 3, "complexity": 1}}},
            "work/done": {"title": "Done", "status": "done", "end": "2026-11-07T09:00:00+00:00", "workdir": "/nowhere"},
            "operator/push": {"title": "git push", "workdir": "/repo", "status": "queued", "roles": {"Operator": "R"}},
            "work/bad": {"title": ["x"], "status": "running", "prio": True, "estimates": {"X": {"value": 4, "complexity": 2}, "Y": "no", "Z": {"value": True, "complexity": 1}}, "roles": {"Z": "RQ", "W": 5}, "key_results": "no"},
            "broken": "not a row",
        }
        queue = {"seq": 9, "entries": [
            {"id": "gate-7", "kind": "gate", "task": "work/feature", "workdir": f"{trees}/feature", "session": "s1", "name": "Stage", "status": "waiting", "enqueued": now - 60, "cmd": "make test"},
            {"id": "deploy-8", "kind": "deploy", "task": "work/pinned", "workdir": "/elsewhere", "session": "s2", "name": "Docs", "status": "active", "enqueued": now - 30, "cmd": "make deploy"},
            {"id": "bad-9", "enqueued": "yesterday"},
            "not an entry",
        ]}
        self.write_council({"rasci.json": register, "queue.json": queue})
        rows = {row["task"]: row for row in self.snapshot()["tasks"]}
        self.assertEqual(list(rows), ["work/pinned", "work/scored", "work/feature", "operator/push", "work/bad", "queue/gate-7", "queue/deploy-8", "work/done"])
        feature = rows["work/feature"]
        self.assertEqual((feature["kind"], feature["status"], feature["met"], feature["total"], feature["prio"], feature["editable"], feature["ended"]), ("task", "running", 1, 2, None, True, False))
        self.assertEqual(feature["roles"], {"Skills": "RA", "Operator": "C", "Docs": "I"})
        self.assertEqual(feature["estimates"], {"Skills": {"value": 8, "complexity": 2}, "Docs": {"value": 5, "complexity": 3}})
        self.assertEqual(feature["wsjf"], {"value": 6.5, "complexity": 2.5, "score": 2.6})
        self.assertEqual((feature["worktree"], feature["worktree_branch"], feature["repo"], feature["flow"], feature["open_work"]), (f"{trees}/feature", "feature", "github.com/me/demo", FLOW, ["task", "dirty"]))
        pinned = rows["work/pinned"]
        self.assertEqual((pinned["prio"], pinned["worktree"], pinned["worktree_branch"], pinned["flow"], pinned["open_work"]), (1, f"{trees}/feature-done", "feature/done", None, ["task"]))
        self.assertEqual(rows["work/scored"]["wsjf"], {"value": 3, "complexity": 1, "score": 3.0})
        bad = rows["work/bad"]
        self.assertEqual((bad["title"], bad["prio"], bad["estimates"], bad["wsjf"], bad["roles"], bad["total"]), ("['x']", None, {}, None, {"Z": "R"}, 0))
        command = rows["operator/push"]
        self.assertEqual((command["kind"], command["title"], command["editable"], command["open_work"]), ("command", "git push", False, ["task"]))
        gate, deploy = rows["queue/gate-7"], rows["queue/deploy-8"]
        self.assertEqual((gate["kind"], gate["status"], gate["title"], gate["worker"], gate["editable"], gate["flow"]), ("queue", "awaiting", "make test", "Stage", False, FLOW))
        self.assertEqual(gate["queue"], {"kind": "gate", "parent": "work/feature", "enqueued": now - 60})
        self.assertEqual((deploy["status"], deploy["flow"], deploy["queue"]["parent"]), ("running", None, "work/pinned"))
        done = rows["work/done"]
        self.assertEqual((done["ended"], done["editable"], done["open_work"], done["worktree"]), (True, False, [], ""))

    def test_only_the_newest_ended_tasks_are_listed(self):
        register = {f"work/old-{n:03d}": {"status": "done", "end": f"2026-11-{1 + n // 24:02d}T{n % 24:02d}:00:00+00:00"} for n in range(30)}
        self.write_council({"rasci.json": {**register, "work/open": {"status": "queued"}}})
        with mock.patch.object(tasks, "ENDED_SHOWN", 5):
            listed = [row["task"] for row in self.snapshot()["tasks"]]
        self.assertEqual(listed, ["work/open", "work/old-029", "work/old-028", "work/old-027", "work/old-026", "work/old-025"])

    def test_a_task_change_needs_a_known_open_task_and_one_of_three_argv_shapes(self):
        self.write_council({"rasci.json": {
            "work/feature": {"title": "F", "status": "running"},
            "work/done": {"status": "done"},
            "operator/push": {"title": "git push", "workdir": "/repo", "status": "queued"},
        }})
        for argv in (
            ["set", "work/feature", "--prio", "0"],
            ["set", "work/feature", "--prio", "1000"],
            ["set", "work/feature", "--prio", "03"],
            ["set", "work/feature", "--prio", 3],
            ["set", "work/feature", "--prio", "3", "--status", "done"],
            ["set", "work/other", "--prio", "3"],
            ["estimate", "work/feature", "Skills", "--value", "8", "--complexity", "3"],
            ["estimate", "work/feature", "Operator", "--value", "4", "--complexity", "3"],
            ["estimate", "work/feature", "Operator", "--complexity", "3", "--value", "8"],
            ["estimate", "work/feature", "Operator", "--drop", "--value", "8"],
            ["rm", "work/feature"],
            "set work/feature --prio 3",
        ):
            with self.subTest(argv=argv):
                status, _, body = self.post_json("/api/sign", {"items": [change(argv)]}, self.guard(self.host))
                self.assertEqual(status, 400, body)
        refused = (
            ([change(["set", "operator/push", "--prio", "3"], "operator/push")], 400),
            ([change(["set", "work/x;rm", "--prio", "3"], "work/x;rm")], 400),
            ([{**change(PRIO), "extra": 1}], 400),
            ([change(PRIO), change(PRIO)], 400),
            ([change(PRIO, "x")], 400),
            ([change(["set", "work/nope", "--prio", "3"], "work/nope")], 404),
            ([change(["set", "work/done", "--prio", "3"], "work/done")], 409),
        )
        for items, code in refused:
            with self.subTest(items=items):
                self.assertEqual(self.post_json("/api/sign", {"items": items}, self.guard(self.host))[0], code)
        prepared = self.prepare([change(PRIO), change(ESTIMATE), change(["estimate", "work/feature", "Operator", "--drop"])])
        self.assertEqual(len(prepared["payload"]["items"]), 3)
        self.assertIn(signing.item_hash(signing.task_item("work/feature", PRIO)), prepared["payload"]["items"])
        self.assertEqual(self.get("/api/tasks")[0], 405)
        self.assertEqual(self.post_json("/api/tasks", {"items": [change(PRIO)], "proof": None}, self.client())[0], 403)
        self.assertEqual(self.post_json("/api/tasks", {"items": [change(PRIO)], "proof": None}, self.guard(self.host))[0], 400)
        forged = {**self.signed([change(PRIO)], self.pin()), "assertion": {}}
        status, _, body = self.post_json("/api/tasks", {"items": [change(PRIO)], "proof": forged}, self.guard(self.host))
        self.assertEqual(status, 400, body)
        self.assertIn("not signed", body.decode() if isinstance(body, bytes) else body)
        snapshot = self.snapshot()
        self.assertEqual([job for job in snapshot["jobs"] if job["kind"] == "task"], [])
        self.assertNotIn("Task change signed", json.dumps(snapshot, ensure_ascii=False))

    def test_a_task_the_hub_cannot_sign_whole_is_not_editable(self):
        long_slug = "work/" + "x" * 600
        self.write_council({"rasci.json": {long_slug: {"status": "running"}, "work/a b": {"status": "running"}}})
        self.assertEqual([task["editable"] for task in self.snapshot()["tasks"]], [False, False])

    def test_a_signed_priority_and_estimate_reach_the_register_through_the_runner(self):
        self.write_council({"rasci.json": {"work/feature": {"title": "F", "status": "running", "roles": {"Skills": "RA"}}}})
        signer = self.pin()
        items = [change(PRIO), change(ESTIMATE)]
        status, _, body = self.post_json("/api/tasks", {"items": items, "proof": self.signed(items, signer)}, self.guard(self.host))
        self.assertEqual(status, 202, body)
        self.assertEqual((len(json.loads(body)["jobs"]), json.loads(body)["status"]), (2, "queued"))
        queued = sorted(self.runner_jobs(), key=lambda job: job["argv"][0], reverse=True)
        self.assertEqual([(job["kind"], job["task"], job["argv"], job["command"], job["directory"]) for job in queued], [
            ("task", "work/feature", PRIO, "rasci.py set work/feature --prio 3", ""),
            ("task", "work/feature", ESTIMATE, "rasci.py estimate work/feature Operator --value 8 --complexity 3", ""),
        ])
        trust = verifier.Trust(approvers=self.approvers, replay=self.replay / "old.json", origin=self.origin)
        self.assertIn("does not list this item", runner.refusal(queued[0], trust, time.time()))
        self.run_runner()
        stored = json.loads((self.council / "rasci.json").read_text(encoding="utf-8"))["work/feature"]
        self.assertEqual((stored["prio"], stored["estimates"]["Operator"]["value"], stored["estimates"]["Operator"]["complexity"], stored["roles"]), (3, 8, 3, {"Skills": "RA"}))
        jobs = {job["command"]: job for job in self.snapshot()["jobs"]}
        self.assertEqual([(job["status"], job["code"]) for job in jobs.values()], [("done", 0), ("done", 0)])
        self.assertEqual(self.snapshot()["tasks"][0]["prio"], 3)
        self.assertNotIn(skill_scripts.OPERATOR_SCRIPT, [script for script, _ in self.scripts.calls])
        proof = queued[0]["proof"]
        forged = (
            (["set", "work/feature", "--prio", "9"], proof, "does not list this item"),
            (["rm", "work/feature"], proof, "no task priority"),
            (PRIO, proof, "already used"),
            (PRIO, None, "no signature"),
        )
        for argv, relayed, reason in forged:
            with self.subTest(argv=argv, reason=reason):
                fields = {"kind": "task", "task": "work/feature", "argv": argv, "command": "x", "directory": "", "sha256": "", "status": "queued", "proof": relayed}
                tampered = self.httpd.hub.jobs.add({**fields, "code": None, "output": "", "created_ts": time.time(), "started": None, "finished": None})
                self.run_runner()
                record = self.httpd.hub.jobs.get(tampered["id"])
                self.assertEqual(record["status"], "refused")
                self.assertTrue(record["output"].startswith(runner.REFUSED), record["output"])
                self.assertIn(reason, record["output"])
        self.assertEqual(json.loads((self.council / "rasci.json").read_text(encoding="utf-8"))["work/feature"]["prio"], 3)

    def test_a_runner_without_the_register_flags_refuses_task_changes(self):
        self.write_council({"rasci.json": {"work/feature": {"title": "F", "status": "running"}}})
        signer = self.pin()
        items = [change(PRIO)]
        self.assertEqual(self.post_json("/api/tasks", {"items": items, "proof": self.signed(items, signer)}, self.guard(self.host))[0], 202)
        self.run_runner(register=False)
        job = next(job for job in self.snapshot()["jobs"] if job["kind"] == "task")
        self.assertEqual(job["status"], "refused")
        self.assertIn(runner.UNREGISTERED, job["output"])
        self.assertNotIn("prio", json.loads((self.council / "rasci.json").read_text(encoding="utf-8"))["work/feature"])

    def test_a_runner_refuses_task_changes_into_a_symlinked_or_foreign_council(self):
        self.write_council({"rasci.json": {"work/feature": {"title": "F", "status": "running"}}})
        linked = self.council.with_name("linked-council")
        linked.symlink_to(self.council)
        signer = self.pin()
        items = [change(PRIO)]
        self.assertEqual(self.post_json("/api/tasks", {"items": items, "proof": self.signed(items, signer)}, self.guard(self.host))[0], 202)
        self.run_runner(council=linked)
        job = next(job for job in self.snapshot()["jobs"] if job["kind"] == "task")
        self.assertEqual(job["status"], "refused")
        self.assertIn(f"{linked} is a symlink, no directory or not owned by uid", job["output"])
        self.assertNotIn("prio", json.loads((self.council / "rasci.json").read_text(encoding="utf-8"))["work/feature"])
        self.assertIsNone(runner.council_refusal(self.council))
        for path in (self.council / "rasci.json", self.council / "missing", Path(""), Path("council")):
            with self.subTest(path=path):
                self.assertTrue(runner.council_refusal(path).startswith("refused: "))
        with mock.patch("os.geteuid", return_value=os.geteuid() + 1):
            self.assertIn("not owned by uid", runner.council_refusal(self.council))

    def test_a_signed_task_change_never_writes_through_a_register_swapped_for_a_link(self):
        register = {"work/feature": {"title": "F", "status": "running"}}
        self.write_council({"rasci.json": register})
        signer = self.pin()
        items = [change(PRIO)]
        self.assertEqual(self.post_json("/api/tasks", {"items": items, "proof": self.signed(items, signer)}, self.guard(self.host))[0], 202)
        target = self.outside / "elsewhere.json"
        target.write_text(json.dumps(register), encoding="utf-8")
        before = target.read_bytes()
        linked = self.council / "rasci.json"
        linked.unlink()
        linked.symlink_to(target)
        self.run_runner()
        job = next(job for job in self.snapshot()["jobs"] if job["kind"] == "task")
        self.assertEqual(job["status"], "failed", job["output"])
        self.assertIn("is no regular file below", job["output"])
        self.assertEqual((linked.is_symlink(), target.read_bytes()), (True, before))

    def test_a_task_change_runs_only_its_checked_argv_from_the_root_within_its_limit(self):
        register = runner.Register(rasci=Path("/x/rasci.py"), council=Path("/c"))
        with mock.patch.object(runner, "spawn", return_value=0) as spawn:
            runner.change({"task": "work/feature", "argv": PRIO}, register, print)
            with self.assertRaises(signing.Refused):
                runner.change({"task": "work/feature", "argv": ["rm", "work/feature"]}, register, print)
        argv, cwd, env, _, limit = spawn.call_args.args
        self.assertEqual((spawn.call_count, argv[1:], cwd, env["AGENTS_COUNCIL_ROOT"], limit), (1, ["-I", "-B", "/x/rasci.py", *PRIO], "/", "/c", runner.TASK_LIMIT))

    def test_a_program_past_its_limit_is_killed_with_its_whole_process_group(self):
        reports = []
        child = "import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); time.sleep(60)"
        started = time.monotonic()
        code = runner.spawn([sys.executable, "-c", child], "/", None, reports.append, 0.5)
        self.assertLess(time.monotonic() - started, 10)
        self.assertEqual((code, reports[-1]["code"]), (-signal.SIGKILL, -signal.SIGKILL))
        self.assertIn("killed after 0.5 s", reports[-1]["output"])

    def test_open_tasks_queue_rows_parties_and_task_keys_are_capped(self):
        many = {f"P{n}": {"value": 3, "complexity": 1} for n in range(9)}
        register = {f"work/t{n}": {"status": "queued", "prio": n + 1, "estimates": many, "roles": {party: "R" for party in many}} for n in range(6)}
        register["work/" + "x" * 900] = {"status": "queued"}
        now = time.time()
        queue = {"seq": 7, "entries": [{"id": f"gate-{n}", "kind": "gate", "task": "work/t0", "status": "waiting", "enqueued": now - 100 + n, "cmd": "make test"} for n in range(7)]}
        self.write_council({"rasci.json": register, "queue.json": queue})
        with mock.patch.multiple(tasks, OPEN_SHOWN=4, QUEUE_SHOWN=3, PARTIES_SHOWN=2):
            rows = self.snapshot()["tasks"]
        self.assertEqual([row["task"] for row in rows], ["work/t0", "work/t1", "work/t2", "work/t3", "queue/gate-0", "queue/gate-1", "queue/gate-2"])
        self.assertEqual((len(rows[0]["estimates"]), len(rows[0]["roles"])), (2, 2))
        self.assertEqual(max(len(row["task"]) for row in self.snapshot()["tasks"]), tasks.TEXT_SHOWN)

    def plan_register(self, now: float) -> tuple[dict, dict]:
        register = {
            "work/base": {"status": "done", "branch": "feature/base", "start": iso(now - 7200), "end": iso(now - 3600)},
            "work/child": {"status": "queued", "base": "feature/base"},
            "work/next": {"status": "queued", "after": ["work/child", "work/gone", "work/next", 7]},
            "work/side": {"status": "running", "branch": "side", "base": "feature/base", "start": iso(now - 600)},
            "work/pinned": {"status": "queued", "prio": 1},
        }
        entries = [
            {"id": "deploy-1", "seq": 1, "kind": "deploy", "task": "work/side", "name": "Stage", "hotfix": None, "status": "active", "enqueued": now - 200, "granted": now - 100, "cmd": "make deploy"},
            {"id": "gate-2", "seq": 2, "kind": "gate", "task": "work/next", "name": "Docs", "hotfix": None, "status": "waiting", "enqueued": now - 50, "granted": None, "cmd": "make test"},
            {"id": "gate-3", "seq": 3, "kind": "gate", "task": "work/pinned", "name": "Docs", "hotfix": None, "status": "waiting", "enqueued": now - 40, "granted": None, "cmd": "make test"},
            {"id": "hot-4", "seq": 4, "kind": "gate", "task": "work/next", "name": "Docs", "hotfix": "db", "status": "waiting", "enqueued": now - 30, "granted": None, "cmd": "make test"},
            {"id": "old-5", "seq": 5, "kind": "gate", "task": "work/next", "name": "Stage", "hotfix": None, "status": "waiting", "enqueued": now - 7210, "granted": None, "cmd": "make test"},
        ]
        return register, {"seq": 5, "entries": entries}

    def test_edges_come_from_explicit_dependencies_branch_bases_and_the_queue_order(self):
        now = time.time()
        register, queue = self.plan_register(now)
        self.write_council({"rasci.json": register, "queue.json": queue})
        state = self.snapshot()
        self.assertEqual(state["task_edges"], [
            {"from": "work/child", "to": "work/next", "kind": "after"},
            {"from": "work/base", "to": "work/child", "kind": "base"},
            {"from": "work/base", "to": "work/side", "kind": "base"},
            {"from": "queue/deploy-1", "to": "queue/hot-4", "kind": "queue"},
            {"from": "queue/hot-4", "to": "queue/gate-3", "kind": "queue"},
            {"from": "queue/gate-3", "to": "queue/old-5", "kind": "queue"},
            {"from": "queue/old-5", "to": "queue/gate-2", "kind": "queue"},
        ])
        rows = {row["task"]: row for row in state["tasks"]}
        self.assertEqual((rows["work/next"]["after"], rows["work/child"]["base"], rows["work/pinned"]["base"]), (["work/child", "work/gone", "work/next"], "feature/base", "-"))
        self.assertAlmostEqual(rows["work/base"]["start"], now - 7200, places=3)
        self.assertAlmostEqual(rows["work/base"]["end"], now - 3600, places=3)
        self.assertIsNone(rows["work/side"]["end"])
        self.assertEqual((rows["queue/deploy-1"]["start"], rows["queue/gate-2"]["start"]), (now - 100, None))

    def test_the_queue_chain_follows_the_grant_order_of_queue_py(self):
        now = time.time()
        register, queue = self.plan_register(now)
        entries = [(entry, entry["enqueued"]) for entry in queue["entries"]]
        chain = tasks.queue_chain(entries, register, [], now)
        self.assertEqual(chain, [("deploy-1", False), ("hot-4", True), ("gate-3", True), ("old-5", True), ("gate-2", True)])
        self.assertEqual(tasks.register_ranks(register, []), {"work/pinned": 0, "work/child": 1, "work/next": 2, "work/side": 3})
        waiting = [entry for entry in queue["entries"] if entry["status"] == "waiting"]
        queue_py = load_queue()
        for agents, first in (([], "gate-3"), (["Stage", "Docs"], "old-5")):
            with self.subTest(agents=agents):
                ranks = tasks.register_ranks(register, agents)
                expected = [entry["id"] for entry in queue_py.ordered(waiting, ranks, {name: index for index, name in enumerate(agents)}, now)]
                found = [job for job, waits in tasks.queue_chain(entries, register, agents, now) if waits]
                self.assertEqual(found, expected)
                self.assertEqual(found[:2], ["hot-4", first])

    def test_a_bulk_business_value_is_stored_only_with_one_verified_assertion_over_the_exact_ids_and_values(self):
        register = {
            "work/a": {"status": "running", "estimates": {"Skills": {"value": 3, "complexity": 2}, "Docs": {"value": 5, "complexity": 2}}},
            "work/b": {"status": "queued", "estimates": {"Docs": {"value": 2, "complexity": 1}}},
        }
        self.write_council({"rasci.json": register})
        before = (self.council / "rasci.json").read_bytes()
        signer = self.pin()
        batch = [valued("work/a", "21"), valued("work/b", "21")]
        proof = self.signed(batch, signer)
        good = self.guard(self.host)
        for items, relayed, reason in (
            ([batch[0], valued("work/b", "34")], proof, "list every approved item"),
            ([valued("work/b", "21"), valued("work/a", "34")], proof, "list every approved item"),
            ([*batch, valued("work/c", "21")], proof, "not found"),
            (batch, key(-7, "stranger").proof(proof["payload"], self.origin), "not signed"),
            (batch, {**proof, "assertion": {**proof["assertion"], "signature": proof["assertion"]["signature"][::-1]}}, "not signed"),
            (batch, None, "not signed"),
        ):
            with self.subTest(items=items, reason=reason):
                status, _, body = self.post_json("/api/tasks", {"items": items, "proof": relayed}, good)
                self.assertIn(status, (400, 404), body)
                self.assertIn(reason, body.decode())
        self.assertEqual([job for job in self.snapshot()["jobs"] if job["kind"] == "task"], [])
        status, _, body = self.post_json("/api/tasks", {"items": batch, "proof": proof}, good)
        self.assertEqual(status, 202, body)
        self.assertEqual(len(json.loads(body)["jobs"]), 2)
        for items in (batch, batch[:1], batch[::-1]):
            with self.subTest(replayed=items):
                status, _, body = self.post_json("/api/tasks", {"items": items, "proof": proof}, good)
                self.assertEqual(status, 400, body)
                self.assertIn("already used", body.decode())
        self.assertEqual((self.council / "rasci.json").read_bytes(), before)
        self.run_runner()
        stored = json.loads((self.council / "rasci.json").read_text(encoding="utf-8"))
        self.assertEqual({task: row["estimates"]["Operator"]["value"] for task, row in stored.items()}, {"work/a": 21, "work/b": 21})
        self.assertFalse(any("complexity" in row["estimates"]["Operator"] for row in stored.values()))
        rows = {row["task"]: row for row in self.snapshot()["tasks"]}
        self.assertEqual(rows["work/a"]["wsjf"], {"value": 21, "complexity": 2, "score": 10.5})
        self.assertEqual(rows["work/b"]["wsjf"], {"value": 21, "complexity": 1, "score": 21.0})
        self.assertEqual((rows["work/a"]["value"], rows["work/a"]["points"], rows["work/a"]["estimates"]["Operator"]), (21, 2, {"value": 21, "complexity": None}))
        self.assertEqual(self.runner_jobs(), [])
        tampered_fields = {"kind": "task", "task": "work/a", "argv": ["estimate", "work/a", "Operator", "--value", "34"], "command": "x", "directory": "", "sha256": "", "status": "queued", "proof": proof}
        tampered = self.httpd.hub.jobs.add({**tampered_fields, "code": None, "output": "", "created_ts": time.time(), "started": None, "finished": None})
        replayed = self.httpd.hub.jobs.add({**tampered_fields, "argv": batch[0]["argv"], "code": None, "output": "", "created_ts": time.time(), "started": None, "finished": None})
        self.run_runner()
        self.assertIn("does not list this item", self.httpd.hub.jobs.get(tampered["id"])["output"])
        self.assertIn("already used", self.httpd.hub.jobs.get(replayed["id"])["output"])
        self.assertEqual(json.loads((self.council / "rasci.json").read_text(encoding="utf-8")), stored)

    def test_estimates_go_out_only_on_an_explicit_request_in_story_points_mode_once_per_request(self):
        self.write_council({"rasci.json": {"work/a": {"status": "queued", "roles": {"Skills": "RA"}}}})
        good = self.guard(self.host)
        signer = self.pin()
        self.snapshot()
        self.index()
        status, _, body = self.post_json("/api/board/estimates", {"proof": self.board_proof("estimates", signer)}, good)
        self.assertEqual(status, 409, body)
        self.assertEqual(self.post_json("/api/board/estimates", {}, self.client())[0], 403)
        status, _, body = self.post_json("/api/settings", {**self.snapshot()["settings"], "estimation": "points", "proof": None}, good)
        self.assertEqual((status, json.loads(body)["settings"]["estimation"]), (200, "points"))
        self.snapshot()
        self.index()
        self.assertEqual(self.post_json("/api/board/estimates", {}, good)[0], 400)
        self.assertEqual(self.post_json("/api/board/estimates", {"proof": None}, good)[0], 400)
        self.assertEqual(self.scripts.calls, [])
        proof = self.board_proof("estimates", signer)
        status, _, body = self.post_json("/api/board/estimates", {"proof": proof}, good)
        self.assertEqual(status, 200, body)
        self.assertTrue(json.loads(body)["ok"])
        self.assertEqual(self.post_json("/api/board/estimates", {"proof": proof}, good)[0], 400)
        self.assertEqual(self.scripts.calls, [(skill_scripts.ESTIMATE, ["request", "--session", "Operator"])])
        self.snapshot()
        self.assertEqual(self.post_json("/api/settings", {**self.snapshot()["settings"], "estimation": "none", "proof": None}, good)[0], 200)
        self.assertEqual(len(self.scripts.calls), 1)
        self.assertEqual(settings.Settings(self.state / "settings.json").get()["estimation"], "none")


if __name__ == "__main__":
    unittest.main()
