"""Exercise requirement 074 in Chromium: the board's running marks, their border and glow, the Running chip, at three widths."""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

import hub_e2e_kit as base
from hub_case import HubCase
from hub_support import iso

OUT = Path(os.environ.get("E2E_OUT", "/tmp/board-running-shots"))
CALM = [{"name": "prefers-reduced-motion", "value": "reduce"}]
MARKED = ["queue/q-1", "work/alpha", "work/bravo", "work/delta"]
UNMARKED = ["work/charlie", "work/echo"]
CHIPS = {
    "work/alpha": [["queue", "accent", "#bi-cpu", r"test · \d+ min", "Queue job running"]],
    "queue/q-1": [["queue", "accent", "#bi-cpu", r"test · \d+ min", "Queue job running"]],
    "work/bravo": [["agent", "ok", "#bi-person-workspace", r"Docs · [234] min", "Agent working"]],
    "work/delta": [["agent", "ok", "#bi-person-workspace", r"Skills · \d+ (s|min)", "Agent working"], ["hub", "info", "#bi-terminal", r"make deploy-hub", "Hub job running"]],
}
BORDERS = {"work/alpha": "accent", "queue/q-1": "accent", "work/bravo": "ok", "work/delta": "ok"}
READ = """
  const card = (task) => all("#main .kanban-card").find((node) => node.dataset.task === task) || null;
  const toggle = () => document.getElementById("kanban-running");
  const color = (variable) => {
    const probe = document.createElement("span");
    probe.style.color = `var(${variable})`;
    document.body.append(probe);
    const found = getComputedStyle(probe).color;
    probe.remove();
    return found;
  };
  const keyframes = (wanted) => {
    for (const sheet of document.styleSheets) {
      for (const rule of sheet.cssRules) {
        if (rule.type === CSSRule.KEYFRAMES_RULE && rule.name === wanted) {
          return [...rule.cssRules].map((frame) => [frame.keyText, [...frame.style].sort()]);
        }
      }
    }
    return null;
  };
  const spills = (node) => {
    const own = node.getBoundingClientRect();
    const host = node.closest(".kanban-card").getBoundingClientRect();
    return own.right > host.right + 1 || own.left < host.left - 1;
  };
  const read = () => {
    const cards = all("#main .kanban-card");
    const button = toggle();
    return {
      cards: cards.map((node) => node.dataset.task).sort(),
      marks: Object.fromEntries(cards.map((node) => [node.dataset.task, [node.dataset.mark || null, node.dataset.marks || null,
        all(".kanban-mark", node).map((chip) => [chip.dataset.mark, chip.dataset.tone, chip.querySelector("use").getAttribute("href"), text(chip), name(chip), chip.getAttribute("title") || ""])]])),
      borders: Object.fromEntries(cards.map((node) => [node.dataset.task, [getComputedStyle(node).borderTopWidth, getComputedStyle(node).borderTopColor]])),
      glow: Object.fromEntries(cards.filter((node) => node.dataset.mark).map((node) => {
        const after = getComputedStyle(node, "::after");
        return [node.dataset.task, [after.animationName, after.animationDuration, after.animationIterationCount]];
      })),
      tones: {accent: color("--accent"), ok: color("--ok"), info: color("--info")},
      frames: keyframes("kanban-glow"),
      toggle: button ? [name(button), button.getAttribute("aria-pressed"), text(button.querySelector(".count")), button.getAttribute("title") || ""] : null,
      spill: all("#main .kanban-mark").filter(spills).length,
      unlabelled: all("#main .kanban-box svg.bi").map((svg) => svg.parentElement).filter((owner) => !text(owner) && !(owner.getAttribute("title") && owner.getAttribute("aria-label"))).length,
      wide: document.documentElement.scrollWidth > window.innerWidth + 1,
    };
  };
"""
BOARD = """(async () => {@HELPERS@@READ@
  if (!(await until(() => card("work/delta") && card("work/delta").querySelector(".kanban-mark") && toggle(), 10000))) {
    return {error: text(document.getElementById("main"))};
  }
  await sleep(400);
  card("work/delta").scrollIntoView({block: "center"});
  return read();
})()"""
FILTER = """(async () => {@HELPERS@@READ@
  toggle().click();
  if (!(await until(() => toggle().getAttribute("aria-pressed") === "true" && all("#main .kanban-card").length === @MARKED@, 4000))) {
    return {error: `still ${all("#main .kanban-card").length} cards`};
  }
  await sleep(2500);
  const only = read();
  toggle().click();
  await until(() => toggle().getAttribute("aria-pressed") === "false" && all("#main .kanban-card").length > @MARKED@, 4000);
  return {only, back: read()};
})()"""


def probe(template: str) -> str:
    return template.replace("@HELPERS@", base.HELPERS).replace("@READ@", READ).replace("@MARKED@", str(len(MARKED)))


def board_council(now: float) -> dict:
    """Returns:
        A register whose work/alpha holds an active queue job, work/bravo
        a worker and work/delta an R with a fresh beat, work/charlie a
        worker whose beat is 10 minutes old, and work/echo nothing.
    """
    return {
        "rasci.json": {
            "work/alpha": {"title": "Alpha", "status": "running", "worker": "Stage", "prio": 1},
            "work/bravo": {"title": "Bravo", "status": "running", "worker": "Docs", "prio": 2},
            "work/charlie": {"title": "Charlie", "status": "queued", "worker": "Late"},
            "work/delta": {"title": "Delta", "status": "running", "worker": "Main", "roles": {"Skills": "R", "Main": "A"}},
            "work/echo": {"title": "Echo", "status": "queued", "worker": "-"},
        },
        "queue.json": {"seq": 1, "entries": [
            {"id": "q-1", "seq": 1, "cmd": "make test", "kind": "test", "task": "work/alpha", "name": "Stage", "hotfix": None, "status": "active", "enqueued": now - 200, "granted": now - 100},
        ]},
        "work/delta/claim.json": {"session": "c-skills", "runtime": "claude", "name": "Skills", "since": iso(now - 600), "beat": now - 60, "work": "delta"},
    }


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestBoardRunning(HubCase):
    drive = base.OrchestratorE2ECase.drive

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        now = time.time()
        self.write_council(board_council(now))
        sessions = {
            "s-docs": {"name": "Docs session", "status": "busy", "statusUpdatedAt": int((now - 120) * 1000), "running": True},
            "s-late": {"name": "Late session", "status": "busy", "statusUpdatedAt": int((now - 600) * 1000), "running": True},
        }
        self.httpd.hub.agent_sessions.write_text(json.dumps({"written": now, "sessions": sessions}), encoding="utf-8")
        job = self.httpd.hub.jobs.add({"task": "work/delta", "command": "make deploy-hub\nsecond line", "directory": "/", "sha256": "", "status": "running", "proof": None, "head": "",
                                       "code": None, "output": "", "created_ts": now, "started": now - 45, "finished": None, "dismissed": False})
        self.httpd.hub.runner_marker.write_text(json.dumps({"pid": os.getpid(), "job": job["id"], "task": "work/delta", "started": now - 45}), encoding="utf-8")

    def steps(self) -> list[dict]:
        local = f"http://localhost:{self.port}/"
        steps = []
        for width, height in base.WIDTHS:
            steps += [
                {"width": width, "height": height, "url": f"{local}?{width}#tasks/board", "wait": 1500, "probe": probe(BOARD), "shot": str(OUT / f"chromium-{width}-running-board.png")},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(FILTER), "shot": str(OUT / f"chromium-{width}-running-filter.png")},
                {"width": width, "height": height, "url": f"{local}?{width}-calm#tasks/board", "wait": 1500, "probe": probe(BOARD), "shot": str(OUT / f"chromium-{width}-running-reduced-motion.png"), "media": CALM},
            ]
        return steps

    def check_marks(self, read: dict, shown: list[str]) -> None:
        for task in shown:
            with self.subTest(task=task):
                first, keys, chips = read["marks"][task]
                if task not in CHIPS:
                    self.assertEqual((first, keys, chips), (None, None, []))
                    self.assertEqual(read["borders"][task][0], "1px")
                    continue
                wanted = CHIPS[task]
                self.assertEqual((first, keys), (wanted[0][0], " ".join(chip[0] for chip in wanted)))
                self.assertEqual([chip[:3] for chip in chips], [chip[:3] for chip in wanted])
                for (_, _, _, shown_text, label, title), (_, _, _, pattern, word) in zip(chips, wanted, strict=True):
                    self.assertRegex(shown_text, f"^{pattern}")
                    self.assertEqual(label, f"{word}: {shown_text}")
                    self.assertRegex(title, rf"(?s)^{re.escape(task)}: .+, since ")
                self.assertEqual(read["borders"][task], ["2px", read["tones"][BORDERS[task]]])

    def check_board(self, read: dict, moving: bool) -> None:
        self.assertNotIn("error", read, read)
        self.assertEqual(read["cards"], sorted(MARKED + UNMARKED))
        self.check_marks(read, MARKED + UNMARKED)
        self.assertEqual(read["frames"], [["0%, 100%", ["opacity"]], ["50%", ["opacity"]]])
        glow = ["kanban-glow", "3s", "infinite"] if moving else ["none", "0s", "1"]
        self.assertEqual(read["glow"], {task: glow for task in MARKED})
        self.assertEqual(read["toggle"][:3], ["Running", "false", str(len(MARKED))], read["toggle"])
        self.assertIn("every card shown", read["toggle"][3])
        self.assertEqual((read["spill"], read["unlabelled"], read["wide"]), (0, 0, False), read)

    def test_chromium_marks_running_cards_glows_by_opacity_only_and_filters_them_at_three_widths(self):
        data = self.drive(self.steps(), None)
        (OUT / "chromium-board-running.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        results = iter(data["results"])
        for width, _ in base.WIDTHS:
            with self.subTest(width=width):
                board, filtered, calm = next(results), next(results), next(results)
                self.check_board(board, True)
                self.assertNotIn("error", filtered, filtered)
                only = filtered["only"]
                self.assertEqual(only["cards"], MARKED)
                self.check_marks(only, MARKED)
                self.assertEqual(only["toggle"][:3], ["Running", "true", str(len(MARKED))])
                self.assertIn("only these shown", only["toggle"][3])
                self.assertEqual(filtered["back"]["cards"], sorted(MARKED + UNMARKED))
                self.check_board(calm, False)


if __name__ == "__main__":
    unittest.main()
