"""Exercise requirements 075 and 088: the prune dialog lists the stale tasks for N days grouped by prefix with a filter, a stepper and a sticky footer, sets the deadline on the shared dial, signs 258 tasks once and the board counts down."""

from __future__ import annotations

import datetime
import json
import os
import shutil
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

import hub_e2e_kit as base
from hub_case import HubCase

OUT = Path(os.environ.get("E2E_OUT", "/tmp/hub-075-shots"))
OPEN = """(async () => {@HELPERS@
  await screenShown(8000);
  const open = await until(() => document.getElementById("kanban-prune-open"), 8000);
  if (!open) {
    return {error: text(document.getElementById("main")).slice(0, 300)};
  }
  await openTaskMenu("task-actions");
  open.click();
  const list = () => all(".sheet-box .prune-list li[data-task]").map((node) => node.dataset.task);
  await until(() => list().length, 4000);
  const field = document.getElementById("prune-days");
  const first = {tasks: list(), ticked: all(".sheet-box .prune-list input:checked").length, days: field.value, sign: name(document.getElementById("prune-sign"))};
  const days = async (value) => {
    field.value = value;
    field.dispatchEvent(new Event("change", {bubbles: true}));
    await sleep(300);
    return {tasks: list(), invalid: field.getAttribute("aria-invalid")};
  };
  const ten = await days("10");
  const one = await days("1");
  const bad = await days("0");
  const back = await days("3");
  const dial = document.querySelector(".sheet-box .prune-dial");
  const attrs = () => ["role", "aria-valuemin", "aria-valuemax", "aria-valuenow", "aria-valuetext", "aria-readonly"].map((attr) => dial.getAttribute(attr));
  const opened = {attrs: attrs(), readout: text(dial.querySelector(".dial-readout")), ticks: all(".dial-tick", dial).length, long: all(".dial-tick.long", dial).length};
  const press = (key) => {
    dial.dispatchEvent(new KeyboardEvent("keydown", {key, bubbles: true, cancelable: true}));
    return dial.getAttribute("aria-valuenow");
  };
  dial.focus();
  const keys = ["PageDown", "Home", "ArrowLeft", "End", "ArrowRight", "PageDown", "Home", "PageUp"].map((key) => [key, press(key)]);
  const box = document.querySelector(".sheet-box").getBoundingClientRect();
  return {first, ten, one, bad, back, opened, keys, inside: box.left >= 0 && box.right <= innerWidth + 1, wide: document.documentElement.scrollWidth > innerWidth + 1};
})()"""
SIGN = """(async () => {@HELPERS@
  await screenShown(8000);
  await openTaskMenu("task-actions");
  (await until(() => document.getElementById("kanban-prune-open"), 8000)).click();
  if (!(await until(() => document.getElementById("prune-sign"), 4000))) {
    return {error: text(document.getElementById("main")).slice(0, 300)};
  }
  const signs = [];
  const send = window.fetch.bind(window);
  window.fetch = (path, init) => {
    if (String(path) === "/api/sign") {
      signs.push(JSON.parse(init.body).items);
    }
    return send(path, init);
  };
  const dial = document.querySelector(".sheet-box .prune-dial");
  dial.focus();
  dial.dispatchEvent(new KeyboardEvent("keydown", {key: "PageDown", bubbles: true, cancelable: true}));
  const started = Date.now() / 1000;
  document.getElementById("prune-sign").click();
  const chip = await until(() => document.getElementById("kanban-prune"), 20000);
  const waiting = await until(() => document.querySelector('.sheet-box .prune-dial[aria-readonly="true"]'), 8000);
  if (!chip || !waiting) {
    return {signs, error: text(document.querySelector(".sheet-box") || document.getElementById("main")).slice(0, 300)};
  }
  const left = () => text(document.querySelector("#kanban-prune .prune-left"));
  const before = left();
  await sleep(2300);
  return {signs, started, before, after: left(), chip: {label: name(document.getElementById("kanban-prune")), title: document.getElementById("kanban-prune").title, role: document.getElementById("kanban-prune").getAttribute("role")},
    countdown: {now: waiting.getAttribute("aria-valuenow"), text: waiting.getAttribute("aria-valuetext"), readout: text(waiting.querySelector(".dial-face .dial-readout")), listed: all(".sheet-box .prune-list li[data-task]").map((node) => node.dataset.task)},
    wide: document.documentElement.scrollWidth > innerWidth + 1};
})()"""
WAIT = """(async () => {@HELPERS@
  await screenShown(8000);
  const chip = await until(() => document.getElementById("kanban-prune"), 8000);
  if (!chip) {
    return {error: text(document.getElementById("main")).slice(0, 300)};
  }
  await openTaskMenu("task-actions");
  document.getElementById("kanban-prune-open").click();
  const waiting = await until(() => document.querySelector('.sheet-box .prune-dial[aria-readonly="true"]'), 4000);
  const box = chip.getBoundingClientRect();
  return {chip: box.width > 0 && box.right <= innerWidth + 1, waiting: Boolean(waiting), wide: document.documentElement.scrollWidth > innerWidth + 1};
})()"""
GROUPS = """(async () => {@HELPERS@
  await screenShown(8000);
  await openTaskMenu("task-actions");
  (await until(() => document.getElementById("kanban-prune-open"), 8000)).click();
  const rows = () => all(".sheet-box .prune-list li[data-task]");
  if (!(await until(() => rows().length >= @COUNT@, 8000))) {
    return {error: text(document.querySelector(".sheet-box") || document.getElementById("main")).slice(0, 300)};
  }
  const count = () => text(document.querySelector("#prune-sign .count"));
  const group = (prefix) => document.querySelector(`.sheet-box .prune-group[data-group="${prefix}"]`);
  const check = (prefix) => group(prefix).querySelector(".prune-group-check");
  const tri = (prefix) => ({checked: check(prefix).checked, mixed: check(prefix).indeterminate, count: count()});
  const row = (task) => document.querySelector(`.sheet-box li[data-task="${task}"]`);
  const groups = all(".sheet-box .prune-group").map((node) => [node.dataset.group, text(node.querySelector(".prune-group-head .count")), all("li[data-task]", node).length]);
  const days = document.getElementById("prune-days");
  const stepper = {type: days.type, mic: days.dataset.mic || null, framed: Boolean(days.closest(".mic-frame")), mics: all('button.mic[aria-controls="prune-days"]').length, buttons: all(".sheet-box .prune-stepper button").map(name)};
  const shown = row("work/t002");
  const look = {avatar: Boolean(shown.querySelector(".prune-owner .avatar")), owner: shown.querySelector(".prune-owner").title, age: text(shown.querySelector(".prune-age"))};
  const full = tri("work");
  shown.querySelector("input[type=checkbox]").click();
  await sleep(100);
  const partial = tri("work");
  shown.querySelector("input[type=checkbox]").click();
  await sleep(100);
  const back = tri("work");
  check("ci").click();
  await sleep(100);
  const off = {...tri("ci"), ticked: all("li[data-task] input:checked", group("ci")).length};
  check("ci").click();
  await sleep(100);
  const toggle = group("fix").querySelector(".prune-group-toggle");
  toggle.click();
  await sleep(100);
  const folded = {expanded: toggle.getAttribute("aria-expanded"), hidden: group("fix").querySelector(".prune-list").hidden, count: count()};
  toggle.click();
  await sleep(100);
  const filter = document.getElementById("prune-filter");
  const typed = async (value) => {
    filter.value = value;
    filter.dispatchEvent(new Event("input", {bubbles: true}));
    await sleep(150);
    return {shown: rows().filter((node) => !node.hidden).length, groups: all(".sheet-box .prune-group").filter((node) => !node.hidden).map((node) => node.dataset.group), count: count(), none: !document.querySelector(".sheet-box .prune-none").hidden};
  };
  const narrowed = await typed("t01");
  const nothing = await typed("zzz");
  const cleared = await typed("");
  const sheet = document.getElementById("sheet");
  const foot = document.querySelector(".sheet-box .prune-foot");
  const go = document.getElementById("prune-sign");
  const visible = () => {
    const box = foot.getBoundingClientRect();
    const button = go.getBoundingClientRect();
    const hit = document.elementFromPoint(button.left + button.width / 2, button.top + button.height / 2);
    return box.top >= 0 && box.bottom <= innerHeight + 1 && Boolean(hit && hit.closest("#prune-sign")) && Boolean(foot.querySelector(".dial-readout"));
  };
  const scrolls = sheet.scrollHeight > sheet.clientHeight + 1;
  const atTop = visible();
  sheet.scrollTop = Math.floor((sheet.scrollHeight - sheet.clientHeight) / 2);
  await sleep(150);
  const midway = visible();
  rows()[rows().length - 1].scrollIntoView({block: "end"});
  sheet.scrollTop = sheet.scrollHeight;
  await sleep(150);
  const atEnd = {visible: visible(), last: rows()[rows().length - 1].getBoundingClientRect().bottom <= foot.getBoundingClientRect().top + 1};
  return {rows: rows().length, count: count(), groups, stepper, look, full, partial, back, off, folded, narrowed, nothing, cleared, scrolls, atTop, midway, atEnd, wide: document.documentElement.scrollWidth > innerWidth + 1};
})()"""
SIGN_ALL = """(async () => {@HELPERS@
  await screenShown(8000);
  await openTaskMenu("task-actions");
  (await until(() => document.getElementById("kanban-prune-open"), 8000)).click();
  if (!(await until(() => all(".sheet-box .prune-list li[data-task]").length >= @COUNT@, 8000))) {
    return {error: text(document.querySelector(".sheet-box") || document.getElementById("main")).slice(0, 300)};
  }
  const signs = [];
  const send = window.fetch.bind(window);
  window.fetch = (path, init) => {
    if (String(path) === "/api/sign") {
      signs.push(JSON.parse(init.body).items);
    }
    return send(path, init);
  };
  const count = text(document.querySelector("#prune-sign .count"));
  document.getElementById("prune-sign").click();
  const waiting = await until(() => document.querySelector('.sheet-box .prune-dial[aria-readonly="true"]'), 20000);
  return {signs, count, waiting: Boolean(waiting), listed: all(".sheet-box .prune-list li[data-task]").length, wide: document.documentElement.scrollWidth > innerWidth + 1};
})()"""
MANY = 258
PREFIXES = ("ci", "cluster", "work", "fix")


def stamp(days: float) -> str:
    return (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=days)).isoformat(timespec="seconds")


def fixture_row(status: str, days: float) -> dict:
    return {"roles": {"Docs": "RA"}, "status": status, "updated": stamp(days), "title": "fixture task", "worker": "-"}


def many_tasks() -> list[str]:
    return [f"{PREFIXES[index % len(PREFIXES)]}/t{index:03d}" if index % 25 else f"solo-{index:03d}" for index in range(MANY)]


def prefix_of(task: str) -> str:
    return task.split("/")[0] if "/" in task else "other"


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestStalePrune(HubCase):
    drive = base.OrchestratorE2ECase.drive
    authenticator = base.OrchestratorE2ECase.authenticator

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        self.council.mkdir(exist_ok=True)
        tasks = {"work/old-a": fixture_row("queued", 12), "work/old-b": fixture_row("blocked", 5), "work/fresh": fixture_row("queued", 1.5), "work/ended": fixture_row("done", 20)}
        (self.council / "rasci.json").write_text(json.dumps(tasks), encoding="utf-8")
        self.page_url = f"http://localhost:{self.port}/"

    def step(self, width: int, height: int, probe: str, shot: str) -> dict:
        return {"width": width, "height": height, "url": f"{self.page_url}?{width}-{shot}#tasks/board", "wait": 1500, "probe": probe.replace("@HELPERS@", base.HELPERS), "shot": str(OUT / f"chromium-{width}-prune-{shot}.png")}

    def test_the_dialog_lists_the_stale_tasks_for_n_days_and_the_deadline_sits_on_the_shared_dial(self):
        data = self.drive([self.step(width, height, OPEN, "dialog") for width, height in base.WIDTHS], None)
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        for (width, _), found in zip(base.WIDTHS, data["results"], strict=True):
            with self.subTest(width=width):
                self.assertNotIn("error", found, found)
                self.assertEqual(found["first"], {"tasks": ["work/old-a", "work/old-b"], "ticked": 2, "days": "3", "sign": "Prune"})
                self.assertEqual((found["ten"]["tasks"], found["one"]["tasks"]), (["work/old-a"], ["work/old-a", "work/old-b", "work/fresh"]))
                self.assertEqual((found["bad"], found["back"]), ({"tasks": ["work/old-a", "work/old-b", "work/fresh"], "invalid": "true"}, {"tasks": ["work/old-a", "work/old-b"], "invalid": "false"}))
                self.assertEqual(found["opened"], {"attrs": ["slider", "1", "60", "10", "10 minutes for the agents to keep a task", None], "readout": "10:00", "ticks": 60, "long": 12})
                self.assertEqual(found["keys"], [["PageDown", "5"], ["Home", "1"], ["ArrowLeft", "1"], ["End", "60"], ["ArrowRight", "60"], ["PageDown", "55"], ["Home", "1"], ["PageUp", "6"]])
                self.assertEqual((found["inside"], found["wide"]), (True, False))

    def test_prune_signs_both_jobs_once_and_the_board_counts_down_to_the_deadline(self):
        width, height = base.WIDTHS[0]
        steps = [self.step(width, height, SIGN, "signed"), *(self.step(other, tall, WAIT, "countdown") for other, tall in base.WIDTHS)]
        data = self.drive(steps, self.authenticator())
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        signed, *waits = data["results"]
        self.assertNotIn("error", signed, signed)
        self.assertEqual(len(signed["signs"]), 1, signed)
        announce, apply = signed["signs"][0]
        since = int(apply["argv"][2])
        self.assertAlmostEqual(since, signed["started"], delta=5)
        self.assertEqual(announce, {"kind": "prune", "argv": ["announce", "--days", "3", "--deadline", str(since + 300), "work/old-a", "work/old-b"]})
        self.assertEqual(apply, {"kind": "prune", "argv": ["prune", "--since", str(since), "work/old-a", "work/old-b"], "not_before": since + 300})
        self.assertEqual(signed["chip"]["role"], "timer")
        self.assertTrue(signed["chip"]["title"].endswith(": work/old-a, work/old-b"), signed["chip"])
        self.assertRegex(signed["before"], r"^[45]:[0-5][0-9]$")
        self.assertNotEqual(signed["before"], signed["after"])
        self.assertEqual((signed["countdown"]["now"], signed["countdown"]["listed"]), ("5", ["work/old-a", "work/old-b"]))
        self.assertRegex(signed["countdown"]["readout"], r"^4:[0-5][0-9]$")
        self.assertFalse(signed["wide"])
        jobs = sorted(self.httpd.hub.jobs.listed(), key=lambda job: job["argv"][0])
        self.assertEqual([(job["kind"], job["status"], job.get("not_before")) for job in jobs], [("prune", "queued", None), ("prune", "queued", since + 300)])
        for (other, _), found in zip(base.WIDTHS, waits, strict=True):
            with self.subTest(width=other):
                self.assertEqual(found, {"chip": True, "waiting": True, "wide": False})

    def many(self) -> list[str]:
        tasks = many_tasks()
        rows = {task: fixture_row("queued", 4 + index % 20) for index, task in enumerate(tasks)}
        (self.council / "rasci.json").write_text(json.dumps(rows), encoding="utf-8")
        return tasks

    def many_step(self, width: int, height: int, probe: str, shot: str) -> dict:
        return self.step(width, height, probe.replace("@COUNT@", str(MANY)), shot)

    def test_258_tasks_group_by_prefix_with_tri_state_filter_stepper_and_a_sticky_footer(self):
        tasks = self.many()
        order = sorted({prefix_of(task) for task in tasks}, key=lambda prefix: (prefix == "other", prefix))
        groups = [[prefix, str(sum(prefix_of(task) == prefix for task in tasks)), sum(prefix_of(task) == prefix for task in tasks)] for prefix in order]
        ci = sum(prefix_of(task) == "ci" for task in tasks)
        narrowed = [task for task in tasks if "t01" in task]
        data = self.drive([self.many_step(width, height, GROUPS, "groups") for width, height in base.WIDTHS], None)
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        for (width, _), found in zip(base.WIDTHS, data["results"], strict=True):
            with self.subTest(width=width):
                self.assertNotIn("error", found, found)
                self.assertEqual((found["rows"], found["count"], found["groups"]), (MANY, str(MANY), groups))
                self.assertEqual(found["stepper"], {"type": "number", "mic": None, "framed": False, "mics": 0, "buttons": ["One day less", "One day more"]})
                self.assertEqual(found["look"], {"avatar": True, "owner": "Docs", "age": "6 d"})
                self.assertEqual((found["full"], found["partial"], found["back"]), ({"checked": True, "mixed": False, "count": str(MANY)}, {"checked": False, "mixed": True, "count": str(MANY - 1)}, {"checked": True, "mixed": False, "count": str(MANY)}))
                self.assertEqual(found["off"], {"checked": False, "mixed": False, "count": str(MANY - ci), "ticked": 0})
                self.assertEqual(found["folded"], {"expanded": "false", "hidden": True, "count": str(MANY)})
                self.assertEqual(found["narrowed"], {"shown": len(narrowed), "groups": sorted({prefix_of(task) for task in narrowed}), "count": str(len(narrowed)), "none": False})
                self.assertEqual(found["nothing"], {"shown": 0, "groups": [], "count": "0", "none": True})
                self.assertEqual(found["cleared"], {"shown": MANY, "groups": order, "count": str(MANY), "none": False})
                self.assertEqual((found["scrolls"], found["atTop"], found["midway"], found["atEnd"]), (True, True, True, {"visible": True, "last": True}))
                self.assertFalse(found["wide"])

    def test_258_stale_tasks_are_pruned_under_one_signature(self):
        tasks = self.many()
        width, height = base.WIDTHS[0]
        data = self.drive([self.many_step(width, height, SIGN_ALL, "many-signed")], self.authenticator())
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        found = data["results"][0]
        self.assertNotIn("error", found, found)
        self.assertEqual((found["count"], len(found["signs"]), found["waiting"], found["listed"], found["wide"]), (str(MANY), 1, True, MANY, False))
        announce, apply = found["signs"][0]
        self.assertEqual((sorted(announce["argv"][5:]), sorted(apply["argv"][3:])), (sorted(tasks), sorted(tasks)))
        jobs = sorted(self.httpd.hub.jobs.listed(), key=lambda job: job["argv"][0])
        self.assertEqual([(job["kind"], job["status"], len(job["argv"])) for job in jobs], [("prune", "queued", 5 + MANY), ("prune", "queued", 3 + MANY)])


if __name__ == "__main__":
    unittest.main()
