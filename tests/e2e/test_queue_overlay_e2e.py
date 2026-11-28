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
from hub_case import HubCase
from test_hub_queue_overlay import (
    HUB_ORDER,
    LINE_ORDER,
    NEW_QUEUE,
    OLD_QUEUE,
    ROWS,
    board_council,
    fake_queue,
)

OUT = Path(os.environ.get("E2E_OUT", "/tmp/queue-overlay-shots"))
CHIPS = {
    "q-1": [["position", "running"], ["class", "fix"], ["prio", "P2"], ["gate", "test"], ["waited", "waited 1 min"], ["eta", "ETA 4 min"]],
    "q-2": [["position", "#1"], ["class", "hotfix"], ["prio", "P1"], ["wsjf", "WSJF 2.67"], ["gate", "quality-high"], ["waited", "waits 21 min"], ["eta", "ETA 8 min"]],
    "q-4": [["position", "#2"], ["class", "main"], ["gate", "deploy"], ["waited", "waits 1 h 6 min"], ["eta", "ETA ?"]],
    "q-3": [["position", "#3"], ["class", "feature"], ["wsjf", "WSJF 1.5"], ["gate", "test"], ["waited", "waits 30 s"], ["eta", "ETA 1 h 5 min"]],
}
READ = """
  const card = (task) => all("#main .kanban-card").find((node) => node.dataset.task === task) || null;
  const chip = (id) => all('#main .legend-chip[data-path="kanban.hidden"]').find((node) => node.dataset.chip === id) || null;
  const centre = (node, at) => {
    const box = node.getBoundingClientRect();
    return [box.left + box.width / 2 - at.left, box.top + box.height / 2 - at.top];
  };
  const read = () => {
    const at = document.querySelector("#main .kanban").getBoundingClientRect();
    const line = document.querySelector("#main svg.kanban-lines .kanban-queue");
    const points = line ? line.getAttribute("points").trim().split(/\\s+/).map((pair) => pair.split(",").map(Number)) : [];
    const badges = (line ? line.dataset.tasks.split(" ") : []).map((task) => card(task).querySelector(".queue-place")).filter(Boolean).map((node) => centre(node, at));
    const spills = (node) => {
      const own = node.getBoundingClientRect();
      const host = node.closest(".kanban-card").getBoundingClientRect();
      return own.right > host.right + 1 || own.left < host.left - 1 || node.scrollWidth > node.clientWidth + 1;
    };
    return {
      places: Object.fromEntries(all("#main .kanban-card .queue-place").map((node) => [node.closest(".kanban-card").dataset.task, [node.dataset.place, name(node)]])),
      line: line ? line.dataset.tasks : null,
      stops: points.length > 1 && points.length === badges.length && points.every(([x, y], index) => Math.abs(x - badges[index][0]) < 1.5 && Math.abs(y - badges[index][1]) < 1.5),
      jobs: Object.fromEntries(all("#main .kanban-card").filter((node) => node.querySelector(".queue-job")).map((node) => [node.dataset.task,
        all(".queue-job", node).map((job) => [job.dataset.job, all(".queue-chip", job).map((item) => [item.dataset.chip, text(item)]), text(job.querySelector(".queue-reason"))])])),
      legend: all('#main .legend-chip[data-path="kanban.hidden"]').map((node) => [node.dataset.chip, node.getAttribute("aria-pressed")]),
      order: name(document.getElementById("kanban-queue-order")),
      buttons: all("#main .queue-why").map((node) => [node.dataset.job, name(node), node.tabIndex, node.getClientRects().length > 0]),
      spill: all("#main .queue-job, #main .queue-place").filter(spills).length,
      unlabelled: all("#main .kanban-box svg.bi").map((svg) => svg.parentElement).filter((owner) => !text(owner) && !(owner.getAttribute("title") && owner.getAttribute("aria-label"))).length,
      wide: document.documentElement.scrollWidth > window.innerWidth + 1,
    };
  };
"""
BOARD = """(async () => {@HELPERS@@READ@
  if (!(await until(() => card("work/alpha") && document.querySelector("#main .queue-job") && document.querySelector("#main svg.kanban-lines .kanban-queue"), 10000))) {
    return {error: text(document.getElementById("main"))};
  }
  await sleep(400);
  const into = Date.now() % 60000;
  if (into > 45000) {
    await sleep(61000 - into);
  }
  const before = read();
  const why = card("work/alpha").querySelector(".queue-why");
  why.scrollIntoView({block: "center"});
  why.focus();
  return {before, focused: document.activeElement === why ? name(why) : null};
})()"""
POPUP = """(async () => {@HELPERS@
  const dialog = await until(() => document.getElementById("popup").open && document.getElementById("popup"), 4000);
  if (!dialog) {
    return {error: "no popup after Enter", focused: document.activeElement ? document.activeElement.outerHTML.slice(0, 200) : null};
  }
  await sleep(300);
  const box = dialog.querySelector(".popup-box").getBoundingClientRect();
  return {
    label: dialog.getAttribute("aria-label"), steps: all("#popup .queue-trace li").map(text), now: text(dialog.querySelector(".queue-reason")),
    focus: Boolean(document.activeElement && document.activeElement.closest("#popup")), inside: box.left >= 0 && box.right <= window.innerWidth + 1,
    wide: document.documentElement.scrollWidth > window.innerWidth + 1,
  };
})()"""
LAYERS = """(async () => {@HELPERS@@READ@
  document.activeElement.dispatchEvent(new KeyboardEvent("keydown", {key: "Escape", bubbles: true}));
  await sleep(300);
  const back = document.activeElement;
  const closed = [document.getElementById("popup").open, back && back.closest(".kanban-card") ? [back.closest(".kanban-card").dataset.task, back.dataset.job] : null];
  await openTaskMenu("task-filter");
  chip("jobs").click();
  await until(() => !document.querySelector("#main .queue-job"), 4000);
  chip("line").click();
  await until(() => !document.querySelector("#main .queue-place"), 4000);
  await sleep(1200);
  return {closed, off: read()};
})()"""
KEPT = """(async () => {@HELPERS@@READ@
  if (!(await until(() => card("work/alpha") && chip("line"), 10000))) {
    return {error: text(document.getElementById("main"))};
  }
  await sleep(400);
  const kept = read();
  await openTaskMenu("task-filter");
  chip("jobs").click();
  await until(() => document.querySelector("#main .queue-job"), 4000);
  chip("line").click();
  await until(() => document.querySelector("#main .queue-place"), 4000);
  await sleep(1200);
  return {kept, back: read()};
})()"""
ORDER_ONLY = """(async () => {@HELPERS@@READ@
  if (!(await until(() => card("work/alpha") && document.querySelector("#main .queue-place") && document.getElementById("kanban-queue-order"), 10000))) {
    return {error: text(document.getElementById("main"))};
  }
  await sleep(400);
  return read();
})()"""


def probe(template: str) -> str:
    return template.replace("@HELPERS@", base.HELPERS).replace("@READ@", READ)


def jobs_shown() -> dict:
    """Returns:
        The overlay each card must carry: every task card its job, each
        queue card its own, chips as CHIPS and the reason of the fixture.
    """
    shown = {}
    for row in ROWS:
        entry = [[row["id"], CHIPS[row["id"]], row["reason"]]]
        shown[row["task"]] = entry
        shown[f"queue/{row['id']}"] = entry
    return shown


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestQueueOverlay(HubCase):
    drive = base.OrchestratorE2ECase.drive

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        self.write_council(board_council(time.time()))
        self.fakes = self.state.parent / "fake-skills"
        self.httpd.hub.queue_order.script = fake_queue(self.fakes / "new", NEW_QUEUE, ROWS)

    def steps(self) -> list[dict]:
        local = f"http://localhost:{self.port}/"
        steps = []
        for width, height in base.WIDTHS:
            steps += [
                {"width": width, "height": height, "url": f"{local}?{width}#tasks/board", "wait": 1500, "probe": probe(BOARD), "shot": str(OUT / f"chromium-{width}-queue-board.png")},
                {"width": width, "height": height, "url": None, "wait": 0, "keys": ["Enter"], "probe": probe(POPUP), "shot": str(OUT / f"chromium-{width}-queue-why.png")},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(LAYERS), "shot": str(OUT / f"chromium-{width}-queue-layers-off.png")},
                {"width": width, "height": height, "url": f"{local}?{width}-reloaded#tasks/board", "wait": 1500, "probe": probe(KEPT), "shot": str(OUT / f"chromium-{width}-queue-layers-back.png")},
            ]
        return steps

    def check_fit(self, read: dict) -> None:
        self.assertEqual((read["unlabelled"], read["spill"], read["wide"]), (0, 0, False), read)

    def check_full(self, read: dict) -> None:
        self.assertEqual(read["places"], {task: [str(place), f"Queue stop {place} of 4"] for place, task in enumerate(LINE_ORDER, 1)})
        self.assertEqual((read["line"], read["stops"]), (" ".join(LINE_ORDER), True), read)
        self.assertEqual(read["jobs"], jobs_shown())
        self.assertEqual((read["legend"], read["order"]), ([["line", "true"], ["jobs", "true"]], None))
        self.assertEqual(sorted(read["buttons"]), sorted([job, f"Why here: {job}", 0, True] for job in [row["id"] for row in ROWS] * 2))
        self.check_fit(read)

    def check_off(self, read: dict) -> None:
        self.assertEqual((read["places"], read["line"], read["jobs"], read["buttons"]), ({}, None, {}, []), read)
        self.assertEqual(read["legend"], [["line", "false"], ["jobs", "false"]])
        self.check_fit(read)

    def test_chromium_numbers_the_line_shows_each_job_explains_it_by_keyboard_and_keeps_the_switched_layers_at_three_widths(self):
        data = self.drive(self.steps(), None)
        (OUT / "chromium-queue-overlay.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        results = iter(data["results"])
        for width, _ in base.WIDTHS:
            with self.subTest(width=width):
                board, popup, layers, kept = next(results), next(results), next(results), next(results)
                self.assertNotIn("error", board, board)
                self.check_full(board["before"])
                self.assertEqual(board["focused"], "Why here: q-2")
                self.assertEqual((popup.get("label"), popup.get("steps"), popup.get("now")), ("Why here: q-2 at #1", ROWS[1]["trace"], f"Now: {ROWS[1]['reason']}"), popup)
                self.assertEqual((popup["focus"], popup["inside"], popup["wide"]), (True, True, False), popup)
                self.assertEqual(layers["closed"], [False, ["work/alpha", "q-2"]])
                self.check_off(layers["off"])
                self.assertNotIn("error", kept, kept)
                self.check_off(kept["kept"])
                self.check_full(kept["back"])
        self.assertEqual(self.httpd.hub.view_store.get()["kanban"], {"hidden": []})

    def test_chromium_keeps_the_numbered_hub_order_and_says_why_without_list_json_at_three_widths(self):
        order = self.httpd.hub.queue_order
        order.script, order.live = fake_queue(self.fakes / "old", OLD_QUEUE, ROWS), None
        local = f"http://localhost:{self.port}/"
        steps = [{"width": width, "height": height, "url": f"{local}?{width}-old#tasks/board", "wait": 1500, "probe": probe(ORDER_ONLY), "shot": str(OUT / f"chromium-{width}-queue-order-only.png")} for width, height in base.WIDTHS]
        data = self.drive(steps, None)
        (OUT / "chromium-queue-order-only.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        for (width, _), read in zip(base.WIDTHS, data["results"], strict=True):
            with self.subTest(width=width):
                self.assertNotIn("error", read, read)
                self.assertEqual(read["places"], {task: [str(place), f"Queue stop {place} of 4"] for place, task in enumerate(HUB_ORDER, 1)})
                self.assertEqual((read["line"], read["stops"], read["jobs"], read["buttons"]), (" ".join(HUB_ORDER), True, {}, []), read)
                self.assertEqual((read["legend"], read["order"]), ([["line", "true"], ["jobs", "true"]], "Queue order only"))
                self.check_fit(read)


if __name__ == "__main__":
    unittest.main()
