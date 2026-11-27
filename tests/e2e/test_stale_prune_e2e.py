"""Exercise requirement 075: the prune dialog lists the stale tasks for N days, sets the deadline on the shared dial, signs once and the board counts down."""

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
    countdown: {now: waiting.getAttribute("aria-valuenow"), text: waiting.getAttribute("aria-valuetext"), unit: text(waiting.querySelector(".dial-readout")), listed: all(".sheet-box .prune-list li[data-task]").map((node) => node.dataset.task)},
    wide: document.documentElement.scrollWidth > innerWidth + 1};
})()"""
WAIT = """(async () => {@HELPERS@
  await screenShown(8000);
  const chip = await until(() => document.getElementById("kanban-prune"), 8000);
  if (!chip) {
    return {error: text(document.getElementById("main")).slice(0, 300)};
  }
  document.getElementById("kanban-prune-open").click();
  const waiting = await until(() => document.querySelector('.sheet-box .prune-dial[aria-readonly="true"]'), 4000);
  const box = chip.getBoundingClientRect();
  return {chip: box.width > 0 && box.right <= innerWidth + 1, waiting: Boolean(waiting), wide: document.documentElement.scrollWidth > innerWidth + 1};
})()"""


def stamp(days: float) -> str:
    return (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=days)).isoformat(timespec="seconds")


def fixture_row(status: str, days: float) -> dict:
    return {"roles": {"Docs": "RA"}, "status": status, "updated": stamp(days), "title": "fixture task", "worker": "-"}


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
                self.assertEqual(found["opened"], {"attrs": ["slider", "1", "60", "10", "10 minutes for the agents to keep a task", None], "readout": "10 min", "ticks": 60, "long": 12})
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
        self.assertEqual((signed["countdown"]["now"], signed["countdown"]["unit"], signed["countdown"]["listed"]), ("5", "5 min", ["work/old-a", "work/old-b"]))
        self.assertFalse(signed["wide"])
        jobs = sorted(self.httpd.hub.jobs.listed(), key=lambda job: job["argv"][0])
        self.assertEqual([(job["kind"], job["status"], job.get("not_before")) for job in jobs], [("prune", "queued", None), ("prune", "queued", since + 300)])
        for (other, _), found in zip(base.WIDTHS, waits, strict=True):
            with self.subTest(width=other):
                self.assertEqual(found, {"chip": True, "waiting": True, "wide": False})


if __name__ == "__main__":
    unittest.main()
