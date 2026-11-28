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

import hub_e2e_kit as base
import test_home_bookmarks_e2e as bm
import test_home_tile_open_e2e as opened
import test_workbench_w4_e2e as w4
from hub_case import HubCase

OUT = Path(os.environ.get("E2E_OUT", "/tmp/hub-044-shots"))
PANELS = [
    "stream", "radio-log", "radio", "radio-device", "radio-speak", "agents/orbit", "agents/chord", "agents/swimlane", "agents/3d", "agents/tree", "agents/hierarchy",
    "artifacts/orbit", "artifacts/chord", "artifacts/swimlane", "artifacts/3d", "artifacts/tree", "tasks/list", "tasks/board", "tasks/rasci", "tasks/gantt", "tasks/burn",
    "tasks/3d", "tasks/operator", "tasks/match", "agents/order", "resources-accounts",
]
NAMED = {"panel:radio-log": "radio-card", "panel:radio-device": "radio-card", "panel:radio-speak": "radio-card", "panel:tasks/gantt": "gantt-scroll"}
FLAT = """(async () => {@HELPERS@@HOME@@KIT@
  await go("home");
  await until(() => !all("#main .home-tile .empty h2").some((title) => text(title).endsWith("…")), 8000);
  await sleep(1200);
  const boxed = (node) => {
    const look = getComputedStyle(node);
    return parseFloat(look.borderTopWidth) > 0 || look.backgroundColor !== "rgba(0, 0, 0, 0)" || look.backgroundImage !== "none";
  };
  const area = (node) => node.offsetWidth * node.offsetHeight;
  const left = (body) => {
    for (let node = body.firstElementChild; node;) {
      if (node.classList.contains("home-flat")) {
        return null;
      }
      if (boxed(node)) {
        return node.className;
      }
      const biggest = [...node.children].reduce((best, child) => (!best || area(child) > area(best) ? child : best), null);
      node = biggest && area(biggest) >= 0.75 * area(node) ? biggest : null;
    }
    return null;
  };
  beatsAtRest();
  const found = all("#main .home-tile").map((node) => {
    const body = node.querySelector(".home-body");
    const flat = body.querySelector(".home-flat");
    const look = flat ? getComputedStyle(flat) : null;
    const pad = parseFloat(getComputedStyle(body).paddingBottom);
    const tail = [];
    for (let node = flat; node; node = node.nextElementSibling) {
      tail.push(node.getBoundingClientRect().bottom);
    }
    const gap = flat ? body.getBoundingClientRect().top + body.clientTop + body.clientHeight - pad - Math.max(...tail) : null;
    const heading = flat ? flat.querySelector(":scope > .radio-card-head > .group-title") : null;
    return {
      key: node.dataset.pin, flat: flat ? [...flat.classList].filter((name) => name !== "home-flat") : null, boxLeft: left(body),
      border: look ? look.borderTopWidth : null, background: look ? look.backgroundColor : null, gap: gap === null ? null : Math.round(gap * 10) / 10,
      heading: heading ? heading.getClientRects().length > 0 : null,
    };
  });
  return {tiles: found, wide: document.documentElement.scrollWidth > innerWidth + 1};
})()"""
FULL = """(async () => {@HELPERS@@HOME@
  await go("tasks/gantt");
  const gantt = await until(() => document.querySelector("#main .gantt-scroll"), 8000);
  const ganttBorder = gantt ? getComputedStyle(gantt).borderTopWidth : null;
  document.getElementById("radio-open").click();
  const log = await until(() => document.querySelector('#radio-spot:not([hidden]) [data-panel="radio-log"]'), 8000);
  const device = document.querySelector('#radio-spot:not([hidden]) [data-panel="radio-device"]');
  const out = {gantt: ganttBorder, log: log ? getComputedStyle(log).borderTopWidth : null, device: device ? getComputedStyle(device).borderTopWidth : null};
  document.getElementById("radio-open").click();
  return out;
})()"""
SHOW = """(async () => {@HELPERS@@HOME@
  await go("home");
  const found = await until(() => tile("@KEY@"), 8000);
  found.scrollIntoView({block: "center"});
  await sleep(400);
  return {key: found.dataset.pin};
})()"""


def probe(template: str, **names: str) -> str:
    return opened.probe(template.replace("@PANELS@", json.dumps(PANELS)), **names)


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestHomeFlatWidgets(HubCase):
    seed = base.OrchestratorE2ECase.seed
    subagents = base.OrchestratorE2ECase.subagents
    drive = base.OrchestratorE2ECase.drive
    sample = w4.TestWorkbenchResources.sample

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        self.seed()
        now = int(time.time())
        self.start = now - now % 60 - w4.ROWS * 60
        folder = self.kept / "resources"
        folder.mkdir()
        (folder / "samples.jsonl").write_text(self.jsonl([self.sample(index) for index in range(w4.ROWS)]), encoding="utf-8")

    def steps(self) -> list[dict]:
        steps = []
        for width, height in ((1920, 1080), (390, 844)):
            page = f"{self.base}?{width}"
            steps += [
                {"width": width, "height": height, "url": f"{page}-clear#stream", "wait": 600, "probe": bm.CLEAR, "shot": None},
                {"width": width, "height": height, "url": f"{page}-seed#stream", "wait": 1200, "probe": probe(opened.SEED), "shot": None},
                {"width": width, "height": height, "url": f"{page}-flat#home", "wait": 1500, "probe": probe(FLAT), "shot": str(OUT / f"chromium-{width}-home.png")},
                {"width": width, "height": height, "url": f"{page}-full#stream", "wait": 1200, "probe": probe(FULL), "shot": None},
            ]
            steps += [{"width": width, "height": height, "url": None, "wait": 0, "probe": probe(SHOW, key=key), "shot": str(OUT / f"chromium-{width}-{key.split(':')[1].replace('/', '-')}.png")} for key in NAMED]
        return steps

    def test_chromium_flattens_every_widget_whose_content_is_a_box_and_keeps_the_box_in_full_view_at_1920_and_390(self):
        data = self.drive(self.steps(), None)
        (OUT / "chromium-flat.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        per_width = len(data["results"]) // 2
        for index, width in enumerate((1920, 390)):
            flat, full = data["results"][index * per_width + 2], data["results"][index * per_width + 3]
            self.assertFalse(flat["wide"], flat)
            tiles = {tile["key"]: tile for tile in flat["tiles"]}
            self.assertEqual(len(tiles), len(PANELS) + 7, sorted(tiles))
            for key, tile in tiles.items():
                with self.subTest(width=width, key=key):
                    self.assertIsNone(tile["boxLeft"], tile)
                    if tile["flat"] is not None:
                        self.assertEqual((tile["border"], tile["background"]), ("0px", "rgba(0, 0, 0, 0)"), tile)
                        self.assertLessEqual(abs(tile["gap"]), 2, tile)
            for key, box in NAMED.items():
                with self.subTest(width=width, named=key):
                    self.assertIn(box, tiles[key]["flat"] or [], tiles[key])
            for key in ("panel:radio-log", "panel:radio-device"):
                self.assertFalse(tiles[key]["heading"], tiles[key])
            self.assertEqual(full, {"gantt": "1px", "log": "1px", "device": "1px"}, full)


if __name__ == "__main__":
    unittest.main()
