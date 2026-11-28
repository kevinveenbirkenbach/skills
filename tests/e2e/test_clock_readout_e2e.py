"""Exercise requirement 087: the match clock, the undo dial and the prune dial print their time inside the face below the pivot, update it and keep the hand moving."""

from __future__ import annotations

import datetime
import itertools
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

OUT = Path(os.environ.get("E2E_OUT", "/tmp/hub-087-clock-shots"))
KIT = r"""@HELPERS@
  const frame = () => new Promise((resolve) => window.requestAnimationFrame(() => resolve()));
  const angle = (dial) => {
    const found = /rotate\(([-0-9.]+) /.exec(dial.querySelector(".dial-hand").getAttribute("transform") || "");
    return found ? Number(found[1]) : null;
  };
  const readout = (dial) => text(dial.querySelector(".dial-face .dial-readout"));
  const placed = (dial) => {
    const words = dial.querySelector(".dial-face .dial-readout");
    const pin = dial.querySelector(".dial-face .dial-pin");
    if (!words || !pin) {
      return null;
    }
    const [box, pivot, face] = [words.getBoundingClientRect(), pin.getBoundingClientRect(), dial.querySelector(".dial-face").getBoundingClientRect()];
    return {centred: Math.abs(box.left + box.right - pivot.left - pivot.right) / 2 < 2, below: box.top >= pivot.bottom - 1 && box.bottom <= face.bottom, inside: box.left >= face.left && box.right <= face.right};
  };
  const sweep = async (dial) => {
    await frame();
    const first = angle(dial);
    await sleep(100);
    return [first, angle(dial)];
  };
  const turned = async (dial) => {
    const before = {now: dial.getAttribute("aria-valuenow"), readout: readout(dial)};
    dial.focus();
    dial.dispatchEvent(new KeyboardEvent("keydown", {key: "ArrowRight", bubbles: true, cancelable: true}));
    const after = {now: dial.getAttribute("aria-valuenow"), readout: readout(dial)};
    const frames = await sweep(dial);
    await sleep(300);
    return {placed: placed(dial), before, after, frames, rest: angle(dial), max: dial.getAttribute("aria-valuemax")};
  };"""
MATCH = """(async () => {@KIT@
  const glass = await until(() => document.querySelector("#main .match-glass.large"), 8000);
  if (!glass) {
    return {error: text(document.getElementById("main")).slice(0, 300)};
  }
  const box = glass.getBoundingClientRect();
  glass.dispatchEvent(new MouseEvent("contextmenu", {bubbles: true, cancelable: true, button: 2, clientX: box.left + 4, clientY: box.top + 4}));
  const dial = await until(() => document.querySelector("#sheet .match-refresh-dial"), 3000);
  return dial ? await turned(dial) : {error: "no match clock"};
})()"""
UNDO = """(async () => {@KIT@
  await screenShown(8000);
  document.getElementById("settings-open").click();
  const dial = await until(() => document.querySelector(".sheet-box form.settings .undo-dial"), 8000);
  if (!dial) {
    return {error: "no undo dial"};
  }
  dial.scrollIntoView({block: "center"});
  await sleep(300);
  return await turned(dial);
})()"""
PRUNE = """(async () => {@KIT@
  await screenShown(8000);
  await openTaskMenu("task-actions");
  (await until(() => document.getElementById("kanban-prune-open"), 8000)).click();
  if (!(await until(() => document.getElementById("prune-sign"), 4000))) {
    return {error: text(document.getElementById("main")).slice(0, 300)};
  }
  const setup = document.querySelector(".sheet-box .prune-dial");
  const opened = {placed: placed(setup), readout: readout(setup)};
  document.getElementById("prune-sign").click();
  const dial = await until(() => document.querySelector('.sheet-box .prune-dial[aria-readonly="true"]'), 20000);
  if (!dial) {
    return {opened, error: text(document.querySelector(".sheet-box") || document.getElementById("main")).slice(0, 300)};
  }
  const running = placed(dial);
  const seen = [];
  const end = performance.now() + 3600;
  while (performance.now() < end) {
    const words = readout(dial);
    if (!seen.length || seen[seen.length - 1].text !== words) {
      seen.push({text: words, at: Math.round(performance.now())});
    }
    await sleep(50);
  }
  const frames = await sweep(dial);
  document.dispatchEvent(new KeyboardEvent("keydown", {key: "Escape", bubbles: true}));
  await until(() => !dial.isConnected, 4000);
  await sleep(100);
  const gone = angle(dial);
  await sleep(300);
  return {opened, placed: running, seen, frames, stopped: {connected: dial.isConnected, still: gone === angle(dial)}};
})()"""


def stamp(days: float) -> str:
    return (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=days)).isoformat(timespec="seconds")


def seconds(readout: str) -> int:
    minutes, rest = readout.split(":")
    return int(minutes) * 60 + int(rest)


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestClockReadout(HubCase):
    drive = base.OrchestratorE2ECase.drive
    authenticator = base.OrchestratorE2ECase.authenticator

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        self.council.mkdir(exist_ok=True)
        row = {"roles": {"Docs": "RA"}, "status": "queued", "updated": stamp(12), "title": "fixture task", "worker": "-"}
        (self.council / "rasci.json").write_text(json.dumps({"work/old-a": row}), encoding="utf-8")

    def step(self, width: int, height: int, screen: str, probe: str, shot: str) -> dict:
        return {"width": width, "height": height, "url": f"http://localhost:{self.port}/?{width}-{shot}#{screen}", "wait": 1500,
                "probe": probe.replace("@KIT@", KIT).replace("@HELPERS@", base.HELPERS), "shot": str(OUT / f"chromium-{width}-{shot}.png")}

    def assert_turned(self, found: dict) -> None:
        self.assertNotIn("error", found, found)
        self.assertEqual(found["placed"], {"centred": True, "below": True, "inside": True}, found)
        for moment in ("before", "after"):
            now = int(found[moment]["now"])
            self.assertEqual(found[moment]["readout"], f"{now // 60}:{now % 60:02d}", found)
        self.assertEqual(int(found["after"]["now"]), int(found["before"]["now"]) + 1, found)
        first, later = found["frames"]
        self.assertNotEqual(first, later, found)
        self.assertAlmostEqual(found["rest"], int(found["after"]["now"]) * 360 / int(found["max"]), delta=0.01, msg=found)

    def test_the_match_clock_and_the_undo_dial_print_their_time_below_the_pivot_and_sweep_to_each_new_value(self):
        steps = [step for width, height in base.WIDTHS for step in (self.step(width, height, "tasks/match", MATCH, "match-clock"), self.step(width, height, "stream", UNDO, "undo-clock"))]
        data = self.drive(steps, None)
        (OUT / "chromium-clocks.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "(style-src-elem)" not in error and "/favicon.ico" not in error], [])
        self.assertEqual(len(data["results"]), 2 * len(base.WIDTHS), data)
        for index, (width, _) in enumerate(base.WIDTHS):
            for found in data["results"][2 * index : 2 * index + 2]:
                with self.subTest(width=width):
                    self.assert_turned(found)

    def test_the_prune_dialog_clock_reads_m_ss_drops_one_second_each_second_and_stops_once_closed(self):
        width, height = base.WIDTHS[1]
        data = self.drive([self.step(width, height, "tasks/board", PRUNE, "prune-clock")], self.authenticator())
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        found = data["results"][0]
        self.assertNotIn("error", found, found)
        self.assertEqual(found["opened"], {"placed": {"centred": True, "below": True, "inside": True}, "readout": "10:00"}, found)
        self.assertEqual(found["placed"], {"centred": True, "below": True, "inside": True}, found)
        texts = [seconds(seen["text"]) for seen in found["seen"]]
        self.assertGreaterEqual(len(texts), 3, found)
        self.assertEqual([earlier - later for earlier, later in itertools.pairwise(texts)], [1] * (len(texts) - 1), found)
        gaps = [later["at"] - earlier["at"] for earlier, later in itertools.pairwise(found["seen"][1:])]
        for gap in gaps:
            self.assertAlmostEqual(gap, 1000, delta=250, msg=found)
        first, later = found["frames"]
        self.assertLess(later, first, found)
        self.assertEqual(found["stopped"], {"connected": False, "still": True}, found)


if __name__ == "__main__":
    unittest.main()
