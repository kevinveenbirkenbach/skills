from __future__ import annotations

import importlib.util
import json
import os
import statistics
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
QUEUE = REPO_ROOT / "skills" / "kvb-org-queue" / "scripts" / "queue.py"
FIXTURE = Path(__file__).resolve().parent / "queue-replay-20261114.json"
FP = {
    "quality-high": {"ram": 40.6, "cpu": 59.8}, "test": {"ram": 34.5, "cpu": 24.5},
    "test-nostack": {"ram": 7.2, "cpu": 9.8}, "iteration": {"ram": 10.4, "cpu": 7.9},
    "gui-dind": {"ram": 20.7, "cpu": 63.6}, "swarm": {"ram": 40.6, "cpu": 59.8}, "operator": {"ram": 10.0, "cpu": 10.0},
}
SLOTS = {"gui-dind": 1, "iteration": 3, "operator": 1, "quality-high": 1, "swarm": 1, "test": 1, "test-nostack": 4}
BUDGET = {"ram": 75, "cpu": 100}
BAND = {"low": BUDGET, "high": BUDGET}
LIMITS = {"cpu_percent": 101, "mem_percent": 85}
EXCLUSIVE = {"quality-high", "test"}
LIGHT = {"test-nostack"}
FLOOR = 15.0
STEP = 20
RAMP = 900
HOUR = 3600
HORIZON = 24 * HOUR
LINES_MEAN = 13.53
SCENARIOS = {
    "plain": {}, "ram45": {"baseline": 45.0}, "hotfix": {"hotfix": True}, "lines": {"hotfix": True, "lines": True, "agents": True},
    "real": {"free": 110.0, "ranked": True, "agents": True},
}


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def scenario(jobs: list[dict], name: str) -> list[dict]:
    """Returns:
        jobs as the scenario name replays them: `hotfix` marks every Main
        quality-high job a hotfix; `lines` adds before each such hotfix four
        light jobs that fill the test-nostack slots, then in the hotfix's
        claims an older light job and an older quality-high of Main, the
        shapes of the skeptic's probes P3 and P3b, each with a seq below
        every job enqueued after it (placed()); the older quality-high is
        held to bound() and rivals() instead of master's wait.
    """
    spec = SCENARIOS[name]
    if not spec.get("hotfix"):
        return jobs
    marked = [{**j, "hotfix": "main" if j["main"] and j["kind"] == "quality-high" else None} for j in jobs]
    if not spec.get("lines"):
        return marked
    added = []
    for h in (j for j in marked if j["hotfix"]):
        base = {"task": h["task"], "need_gb": 0, "hotfix": None, "enqueued": h["enqueued"] - 60}
        added += [{**base, "id": f"{h['id']}-fill{k}", "seq": placed(marked, h["enqueued"] - 90, 0.1 + 0.1 * k), "kind": "test-nostack",
                   "name": "other", "main": False, "workdir": f"/replay/{h['id']}/fill{k}", "claims": [f"/replay/{h['id']}/fill{k}"],
                   "enqueued": h["enqueued"] - 90, "dur": 900.0} for k in range(4)]
        added += [{**base, "id": f"{h['id']}-older-light", "seq": placed(marked, base["enqueued"], 0.5), "kind": "test-nostack",
                   "name": "Main", "main": True, "workdir": h["workdir"], "claims": h["claims"], "dur": 300.0},
                  {**base, "id": f"{h['id']}-older-gate", "seq": placed(marked, h["enqueued"] - 30, 0.6), "kind": "quality-high",
                   "name": "Main", "main": True, "workdir": h["workdir"], "claims": h["claims"], "need_gb": 15,
                   "enqueued": h["enqueued"] - 30, "dur": h["dur"]}]
    return sorted(marked + added, key=lambda j: j["seq"])


def placed(jobs: list[dict], enqueued: float, fraction: float) -> float:
    """Returns:
        A seq fraction (0 to 1) below the lowest seq of the jobs enqueued
        after enqueued, so arrival order agrees with the enqueue stamps.
    """
    return min(j["seq"] for j in jobs if j["enqueued"] > enqueued) - 1 + fraction


def world(name: str, jobs: list[dict]) -> dict:
    """Returns:
        The host of scenario name: baseline (RAM % used outside the queue,
        None for none), free (t -> free disk in GB; `real` drops it below
        FLOOR for the hour after the middle job's enqueue), ranks (`real`:
        every task by name) and agents (`real`, `lines`: Main first, then by
        name).
    """
    spec = SCENARIOS[name]
    dip = sorted(j["enqueued"] for j in jobs)[len(jobs) // 2]
    return {
        "baseline": spec.get("baseline"),
        "free": (lambda t: 12.0 if dip <= t < dip + HOUR else spec["free"]) if "free" in spec else (lambda t: 1000.0),
        "ranks": {task: n for n, task in enumerate(sorted({j["task"] for j in jobs}))} if spec.get("ranked") else {},
        "agents": {agent: n for n, agent in enumerate(sorted({j["name"] for j in jobs}, key=lambda a: (a != "Main", a)))}
        if spec.get("agents") else {},
    }


def loaded(queue, active: list[dict], waiting: list[dict], baseline: float | None, t: float) -> dict[str, str]:
    """Returns:
        {waiting job id: load_reason()} with RAM used = baseline + the ramped
        active jobs' RAM, the young ones' RAM still to come; queue.Outside
        when the baseline alone keeps the job out (held_back()).
    """
    if baseline is None:
        return {}
    ramped = sum(FP[a["kind"]]["ram"] for a in active if t - a["granted"] >= RAMP)
    young = sum(FP[a["kind"]]["ram"] for a in active if t - a["granted"] < RAMP)
    out = {}
    for j in waiting:
        reason = queue.load_reason(LIMITS, 0.0, baseline + ramped, young + FP[j["kind"]]["ram"])
        if reason is not None:
            alone = queue.load_reason(LIMITS, 0.0, baseline, FP[j["kind"]]["ram"])
            out[j["id"]] = reason if alone is None else queue.Outside(reason)
    return out


def simulate(queue, jobs: list[dict], name: str, branch: bool, events: list | None = None) -> dict[str, float | None]:
    """Args:
        queue: the queue.py module to replay.
        jobs: the scenario's jobs, each with its claims, enqueued and dur.
        name: the scenario, whose world() the replay runs on.
        branch: whether queue has this branch's evaluate (drain, latched(),
            stalled()) or master's.
        events: when given, the branch's stall events are appended as (t,
            label, head id): each ESCALATION send, `cleanup` for each
            cleanup started, `notice` for each notice.

    Returns:
        {job id: minutes from enqueue to grant, None when it never started
        within HORIZON after the last enqueue}; every STEP seconds each
        waiting job polls and every job granted starts at once.
    """
    host = world(name, jobs)
    pending = sorted(({**j, "status": "waiting", "granted": None} for j in jobs), key=lambda j: (j["enqueued"], j["seq"]))
    t, end = pending[0]["enqueued"], max(j["enqueued"] for j in pending) + HORIZON
    waiting: list[dict] = []
    active: list[dict] = []
    data: dict = {"drain": None}
    grants: dict[str, float] = {}
    while (pending or waiting) and t <= end:
        active = [a for a in active if a["granted"] + a["dur"] > t]
        while pending and pending[0]["enqueued"] <= t:
            waiting.append(pending.pop(0))
        if not waiting:
            t = pending[0]["enqueued"]
            continue
        for j in waiting:
            j["polled"] = t
        entries = active + waiting
        load, free = loaded(queue, active, waiting, host["baseline"], t), host["free"](t)
        booked = {r: sum(FP[a["kind"]][r] for a in active) for r in BUDGET}
        args = (entries, free, FLOOR, "stop" if free < FLOOR else "ok", "ok", False, SLOTS, {j["id"]: FP[j["kind"]] for j in entries},
                BAND, booked, host["ranks"], host["agents"], load, EXCLUSIVE, LIGHT)
        if branch:
            verdicts, drain, order = queue.evaluate(*args, data["drain"], t)
            data["drain"] = queue.latched(data, drain, t)
            go = [j for j in waiting if verdicts[j["id"]] is None]
            if events is not None:
                data["entries"] = entries
                sends, clean, _ = queue.stalled(data, order, verdicts, FLOOR, free, lambda: (False, []), t)
                events += [(t, "notice" if label.startswith("noticed") else label, order[0]["id"]) for label, _ in sends]
                events += [(t, "cleanup", order[0]["id"])] if clean else []
        else:
            verdicts = queue.evaluate(*args, t)
            go = [j for j in waiting if verdicts[j["id"]] is None and j["id"] not in load]
        for j in go:
            j.update(status="active", granted=t)
            grants[j["id"]] = t
            waiting.remove(j)
            active.append(j)
        if go and branch:
            data[queue.GRANTED] = t
            data.pop(queue.STALL, None)
        t += STEP
    return {j["id"]: (grants[j["id"]] - j["enqueued"]) / 60 if j["id"] in grants else None for j in jobs}


def mean(waits: dict[str, float | None], jobs: list[dict]) -> float:
    cutoff = max(j["enqueued"] for j in jobs) + HORIZON
    return statistics.mean(w if w is not None else (cutoff - j["enqueued"]) / 60 for j, w in ((j, waits[j["id"]]) for j in jobs))


def overlaps(waits: dict[str, float | None], jobs: list[dict]) -> list[tuple[str, str]]:
    runs = [(j, j["enqueued"] + waits[j["id"]] * 60) for j in jobs if waits[j["id"]] is not None]
    return [(a["id"], b["id"]) for n, (a, ga) in enumerate(runs) for b, gb in runs[n + 1:]
            if set(a["claims"]) & set(b["claims"]) and ga < gb + b["dur"] and gb < ga + a["dur"]]


def started(waits: dict[str, float | None], job: dict) -> float:
    return job["enqueued"] + waits[job["id"]] * 60


def took(e: dict, g: float, x: dict, runs: list[tuple[dict, float]]) -> bool:
    """Returns:
        Whether e, starting at g beside runs ((job, start)), took what x
        needs: its slot (e's was the last free one), its exclusive room (one
        of the two exclusive, the other not light) or its budget (only the
        light jobs count beside an exclusive x).
    """
    running = [j for j, s in runs if j is not e and s <= g < s + j["dur"]]
    beside = [j for j in running if j["kind"] in LIGHT or x["kind"] not in EXCLUSIVE]
    slot = e["kind"] == x["kind"] and sum(j["kind"] == e["kind"] for j in running) + 1 >= SLOTS[e["kind"]]
    room = x["kind"] in EXCLUSIVE and e["kind"] not in LIGHT or e["kind"] in EXCLUSIVE and x["kind"] not in LIGHT
    return slot or room or any(sum(FP[j["kind"]][r] for j in beside) + FP[e["kind"]][r] + FP[x["kind"]][r] > BUDGET[r] for r in BUDGET)


def bound(waits: dict[str, float | None], jobs: list[dict], x: dict) -> float:
    """Returns:
        The latest grant the rule allows x: one STEP after the later of its
        enqueue and the end of every job started before it that is older and
        shares one of its claims or is a hotfix.
    """
    ends = [started(waits, j) + j["dur"] for j in jobs if j is not x and waits[j["id"]] is not None and started(waits, j) < started(waits, x)
            and (j["enqueued"] < x["enqueued"] and set(j["claims"]) & set(x["claims"]) or j["hotfix"])]
    return max([x["enqueued"], *ends]) + STEP


def rivals(waits: dict[str, float | None], jobs: list[dict], x: dict) -> list[str]:
    """Returns:
        The jobs after x in arrival (seq), of other claims and no hotfix,
        that started while x waited and took what it needs (took()).
    """
    runs = [(j, started(waits, j)) for j in jobs if waits[j["id"]] is not None]
    return [e["id"] for e, g in runs if not e["hotfix"] and e["seq"] > x["seq"] and not set(e["claims"]) & set(x["claims"])
            and x["enqueued"] <= g < started(waits, x) and took(e, g, x, runs)]


class TestReplay(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        with mock.patch.dict(os.environ, {"AGENTS_COUNCIL_ROOT": str(Path(tmp.name).resolve() / "council")}):
            cls.queue = load(QUEUE, "queue_replay_under_test")
        cls.fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cls.jobs = cls.fixture["jobs"]
        cls.scenes = {name: scenario(cls.jobs, name) for name in SCENARIOS}
        cls.events: list = []
        cls.waits = {name: simulate(cls.queue, cls.scenes[name], name, True, cls.events if name == "real" else None) for name in SCENARIOS}

    def test_the_fixture_is_todays_140_finished_jobs_with_frozen_claims_and_masters_waits(self):
        self.assertEqual(len(self.jobs), 140)
        self.assertTrue(all("claims" in j and j["dur"] > 0 for j in self.jobs))
        self.assertEqual(set(self.fixture["master"]), set(SCENARIOS))
        self.assertEqual(Counter(j["id"].rsplit("-", 1)[-1] for j in self.scenes["lines"] if j["id"].startswith("quality-high-1930-")),
                         Counter({"fill0": 1, "fill1": 1, "fill2": 1, "fill3": 1, "light": 1, "gate": 1}))

    def test_the_mean_wait_stays_within_a_minute_of_master_and_lines_within_a_minute_of_its_main_first_mean(self):
        for name in ("plain", "ram45", "hotfix", "real"):
            jobs = self.scenes[name]
            with self.subTest(scenario=name):
                self.assertLessEqual(mean(self.waits[name], jobs), mean(self.fixture["master"][name], jobs) + 1)
        with self.subTest(scenario="lines"):
            self.assertLessEqual(mean(self.waits["lines"], self.scenes["lines"]), LINES_MEAN + 1,
                                 "lines trades mean wait for Main's bound, capped a minute above the accepted cost")

    def test_no_scenario_starves_a_job_master_runs(self):
        for name in SCENARIOS:
            with self.subTest(scenario=name):
                starved = {i for i, w in self.waits[name].items() if w is None}
                self.assertEqual(starved - {i for i, w in self.fixture["master"][name].items() if w is None}, set())

    def test_no_hotfix_and_no_main_job_waits_longer_than_on_master(self):
        for name in ("plain", "hotfix", "lines", "real"):
            master, branch = self.fixture["master"][name], self.waits[name]
            jobs = [j for j in self.scenes[name] if (j["main"] or j["hotfix"]) and not j["id"].endswith("-older-gate")]
            with self.subTest(scenario=name):
                self.assertEqual([(j["id"], master[j["id"]], branch[j["id"]]) for j in jobs if branch[j["id"]] is None or (
                    master[j["id"]] is not None and branch[j["id"]] > master[j["id"]] + STEP / 60)], [])

    def test_an_older_main_gate_starts_by_its_bound_and_no_younger_rival_takes_its_room(self):
        waits, jobs = self.waits["lines"], self.scenes["lines"]
        gates = [j for j in jobs if j["id"].endswith("-older-gate")]
        self.assertEqual(len(gates), 2)
        self.assertEqual({x["id"]: round((bound(waits, jobs, x) - x["enqueued"]) / 60, 1) for x in gates},
                         {"quality-high-16-older-gate": 19.5, "quality-high-1930-older-gate": 33.5})
        self.assertEqual([(x["id"], waits[x["id"]]) for x in gates if waits[x["id"]] is None or started(waits, x) > bound(waits, jobs, x)], [])
        self.assertEqual({x["id"]: rivals(waits, jobs, x) for x in gates if rivals(waits, jobs, x)}, {})

    def test_no_two_jobs_of_one_claim_run_at_once(self):
        for name, jobs in self.scenes.items():
            with self.subTest(scenario=name):
                self.assertEqual(overlaps(self.waits[name], jobs), [])

    def test_the_disk_dip_starts_one_cleanup_and_one_notice_per_head_and_escalates(self):
        per_head = Counter((label, head) for _, label, head in self.events if label in ("cleanup", "notice"))
        self.assertTrue(per_head)
        self.assertEqual({count for count in per_head.values()}, {1})
        self.assertIn("escalated post", {label for _, label, _ in self.events})


if __name__ == "__main__":
    unittest.main()
