from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

import hub_e2e_kit as base
from hub_case import HubCase

OUT = Path(os.environ.get("E2E_OUT", "/tmp/hub-077-stamp-shots"))
FLOW = """(async () => {@HELPERS@
  const card = () => document.querySelector("#main .match-card.front");
  if (!(await until(card, 8000))) {
    return {error: text(document.getElementById("main"))};
  }
  const looked = () => {
    const stamp = card().querySelector(".match-stamp");
    if (!stamp) {
      return {card: card().dataset.card, stamp: null};
    }
    const style = getComputedStyle(stamp);
    const body = getComputedStyle(card().querySelector(".match-body"));
    return {card: card().dataset.card, stamp: text(stamp), kind: stamp.dataset.stamp, color: style.color, opacity: style.opacity, filter: style.filter, body: body.filter};
  };
  const first = looked();
  const head = card().querySelector(".match-head");
  const box = head.getBoundingClientRect();
  const at = (x) => ({bubbles: true, cancelable: true, pointerId: 7, pointerType: "touch", isPrimary: true, button: 0, clientX: x, clientY: box.top + 20});
  head.dispatchEvent(new PointerEvent("pointerdown", at(box.left + box.width / 2)));
  window.dispatchEvent(new PointerEvent("pointermove", at(box.left + box.width * 0.8)));
  const during = card().querySelector(".match-stamp") ? text(card().querySelector(".match-stamp")) : null;
  window.dispatchEvent(new PointerEvent("pointerup", at(box.left + box.width * 0.9)));
  await sleep(300);
  const swiped = looked();
  document.body.dispatchEvent(new KeyboardEvent("keydown", {key: "ArrowUp", bubbles: true, cancelable: true}));
  await until(() => card() && card().dataset.card !== first.card, 3000);
  return {first, during, swiped, second: looked(), wide: document.documentElement.scrollWidth > window.innerWidth + 1};
})()"""


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestMatchStamp(HubCase):
    drive = base.OrchestratorE2ECase.drive

    def setUp(self):
        super().setUp()
        work = tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        row = {"title": "true", "workdir": work.name, "description": "ship it", "check": "done", "roles": {"Skills": "A", "Operator": "R"}}
        self.write_council({"rasci.json": {"operator/runs": row, "operator/waits": row}})
        now = time.time()
        job = {"command": "true", "directory": work.name, "sha256": "0" * 64, "proof": None, "output": "", "finished": None, "dismissed": False, "code": None}
        self.httpd.hub.jobs.add({**job, "task": "operator/runs", "status": "running", "created_ts": now - 900, "started": now - 900})
        self.httpd.hub.jobs.add({**job, "task": "operator/waits", "status": "queued", "created_ts": now - 60, "started": None})

    def test_chromium_stamps_every_greyed_card_with_its_reason_in_colour(self):
        OUT.mkdir(parents=True, exist_ok=True)
        flow = FLOW.replace("@HELPERS@", base.HELPERS)
        steps = [{"width": width, "height": height, "url": f"http://localhost:{self.port}/?{width}#tasks/match", "wait": 1500, "probe": flow, "shot": str(OUT / f"chromium-{width}-stamp.png")} for width, height in base.WIDTHS]
        data = self.drive(steps, None, "cdp.mjs", os.environ.get("CHROMIUM", "chromium"))
        (OUT / "chromium-stamp.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "(style-src-elem)" not in error and "/favicon.ico" not in error], [])
        self.assertEqual(len(data["results"]), len(base.WIDTHS), data)
        for found in data["results"]:
            with self.subTest(width=found.get("first", {}).get("card")):
                self.assertNotIn("error", found, found)
                stamps = {found["first"]["card"]: found["first"]["kind"], found["second"]["card"]: found["second"]["kind"]}
                self.assertEqual(stamps, {"operator:operator/runs": "running", "operator:operator/waits": "queued"}, found)
                for looked in (found["first"], found["second"]):
                    self.assertIn(looked["stamp"], ("RUNNING", "QUEUED"), found)
                    self.assertEqual((looked["opacity"], looked["filter"]), ("1", "none"), found)
                    self.assertNotIn("grayscale", looked["filter"], found)
                    self.assertIn("grayscale", looked["body"], found)
                    channels = [int(part) for part in looked["color"].removeprefix("rgb(").removesuffix(")").split(",")[:3]]
                    self.assertGreater(max(channels) - min(channels), 20, found)
                self.assertEqual((found["during"], found["swiped"]["stamp"], found["swiped"]["card"]), (found["first"]["stamp"], found["first"]["stamp"], found["first"]["card"]), found)
                self.assertFalse(found["wide"], found)


if __name__ == "__main__":
    unittest.main()
