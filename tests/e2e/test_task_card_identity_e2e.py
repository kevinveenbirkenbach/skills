"""Exercise requirement 090 in Chromium: one card per state with its border colour, glow and owner avatar, the colour legend, light and dark, at three widths."""

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
from hub_support import iso

OUT = Path(os.environ.get("E2E_OUT", "/tmp/task-card-identity-shots"))
DAY = 86400
TONES = {"running": "ok", "operator": "warn", "queued": "info", "blocked": "bad", "stale": "faint", "ended": "line-strong"}
STATES = {
    "work/run": "running", "queue/q-1": "running", "work/ask": "operator", "work/wait": "queued", "queue/q-2": "queued",
    "work/stuck": "blocked", "queue/q-3": "blocked", "work/old": "stale", "work/done": "ended", "work/stop": "ended",
}
OWNERS = {
    "work/run": "Stage", "queue/q-1": "Stage", "work/ask": "Skills", "work/wait": "Docs", "queue/q-2": "Main",
    "work/stuck": "Main", "queue/q-3": "Docs", "work/old": "", "work/done": "Stage", "work/stop": "Docs",
}
WORKING = ["work/run", "queue/q-1"]
STATE_TONES = {"ok", "warn", "info", "bad"}
READ = """
  const card = (task) => all("#main .kanban-card").find((node) => node.dataset.task === task) || null;
  const color = (variable) => {
    const probe = document.createElement("span");
    probe.style.color = `var(${variable})`;
    document.body.append(probe);
    const found = getComputedStyle(probe).color;
    probe.remove();
    return found;
  };
  const avatarOf = (art) => (!art ? null : art.classList.contains("kanban-nobody") ? "nobody" : art.querySelector("svg.face-art") ? "face" : "other");
  const cardRead = (node) => {
    const look = getComputedStyle(node);
    const face = node.querySelector(":scope > .kanban-owner");
    const art = face ? face.querySelector(".avatar") : null;
    const box = node.getBoundingClientRect();
    const at = art ? art.getBoundingClientRect() : null;
    return {
      state: node.dataset.cardState || null,
      border: [look.borderTopWidth, look.borderTopStyle, look.borderTopColor],
      sides: new Set([look.borderTopColor, look.borderRightColor, look.borderBottomColor, look.borderLeftColor]).size,
      shadow: look.boxShadow, animation: look.animationName, working: node.classList.contains("is-working"),
      owner: face ? face.dataset.owner : null, avatar: avatarOf(art), first: face !== null && face === node.firstElementChild,
      corner: at ? [Math.round(at.left - box.left), Math.round(at.top - box.top), Math.round(at.width)] : null,
      tones: all(".pill:not(.queue-chip)", node).map((pill) => pill.dataset.tone || ""),
      title: node.getAttribute("title") || "",
    };
  };
  const sample = async (node) => {
    const seen = new Set();
    for (let at = 0; at < 26; at += 1) {
      seen.add(getComputedStyle(node).boxShadow);
      await sleep(50);
    }
    return [...seen];
  };
  const read = async () => {
    const toggle = document.querySelector("#main .kanban-legend .legend-toggle");
    return {
      cards: Object.fromEntries(all("#main .kanban-card").map((node) => [node.dataset.task, cardRead(node)])),
      tones: Object.fromEntries(@TONES@.map((tone) => [tone, color(`--${tone}`)])),
      legend: all("#main .kanban-legend .kanban-key").map((key) => {
        const look = getComputedStyle(key.querySelector(".kanban-swatch"));
        return [key.dataset.cardState, text(key), look.borderTopStyle, look.borderTopColor];
      }),
      toggle: toggle ? [name(toggle), toggle.getAttribute("aria-pressed")] : null,
      beat: await sample(card("work/run")),
      mode: document.documentElement.dataset.mode || "",
      wide: document.documentElement.scrollWidth > window.innerWidth + 1,
    };
  };
"""
BOARD = """(async () => {@HELPERS@@READ@
  const ready = () => @TASKS@.every((task) => card(task)) && document.querySelector("#main .kanban-legend .legend-toggle") && card("work/run").classList.contains("is-working");
  if (!(await until(ready, 12000))) {
    return {error: text(document.getElementById("main")).slice(0, 400), cards: all("#main .kanban-card").map((node) => node.dataset.task)};
  }
  await sleep(400);
  document.querySelector("#main .kanban-legend").scrollIntoView({block: "start"});
  return read();
})()"""


def probe() -> str:
    return (BOARD.replace("@HELPERS@", base.HELPERS).replace("@READ@", READ).replace("@TASKS@", json.dumps(sorted(STATES)))
            .replace("@TONES@", json.dumps(sorted(set(TONES.values())))))


def identity_council(now: float) -> dict:
    """Returns:
        A register with one card per state: work/run running with an active
        queue job (queue/q-1), work/ask queued under Skills, who has an open
        decision, work/wait queued with only an R holder and a waiting queue
        job (queue/q-2), work/stuck blocked, queue/q-3 a queue job that ended
        with exit 2, work/old untouched for four days without an owner, and
        work/done and work/stop ended ten minutes ago.
    """
    return {
        "rasci.json": {
            "work/run": {"title": "Run", "status": "running", "worker": "Stage", "prio": 1},
            "work/ask": {"title": "Ask", "status": "queued", "worker": "Skills", "prio": 1},
            "work/wait": {"title": "Wait", "status": "queued", "worker": "-", "roles": {"Docs": "R"}, "prio": 2},
            "work/stuck": {"title": "Stuck", "status": "blocked", "worker": "Main", "prio": 2},
            "work/old": {"title": "Old", "status": "queued", "updated": iso(now - 4 * DAY)},
            "work/done": {"title": "Done", "status": "done", "worker": "Stage", "end": iso(now - 600)},
            "work/stop": {"title": "Stop", "status": "stopped", "worker": "Docs", "end": iso(now - 600)},
        },
        "queue.json": {"seq": 3, "entries": [
            {"id": "q-1", "seq": 1, "cmd": "make test", "kind": "test", "task": "work/run", "name": "Stage", "hotfix": None, "status": "active", "enqueued": now - 200, "granted": now - 100},
            {"id": "q-2", "seq": 2, "cmd": "make gate", "kind": "gate", "task": "work/wait", "name": "Main", "hotfix": None, "status": "waiting", "enqueued": now - 50},
            {"id": "q-3", "seq": 3, "cmd": "make deploy", "kind": "deploy", "task": "work/done", "name": "Docs", "hotfix": None, "status": "active", "enqueued": now - 900, "granted": now - 880},
        ]},
        "queue-history.jsonl": json.dumps({"id": "q-3-1794500000000000000", "kind": "deploy", "start": now - 880, "end": now - 300, "exit": 2, "workdir": "/"}) + "\n",
    }


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestTaskCardIdentity(HubCase):
    drive = base.OrchestratorE2ECase.drive

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        self.write_council(identity_council(time.time()))
        self.decision("")

    def run_theme(self, theme: str) -> list[dict]:
        hub = self.httpd.hub
        hub.settings.put({**hub.settings.get(), "theme": theme}, hub.settings.get())
        local = f"http://localhost:{self.port}/"
        steps = [{"width": width, "height": height, "url": f"{local}?{theme}-{width}#tasks/board", "wait": 1500, "probe": probe(), "shot": str(OUT / f"chromium-{theme}-{width}-card-identity.png")}
                 for width, height in base.WIDTHS]
        data = self.drive(steps, None)
        (OUT / f"chromium-{theme}-card-identity.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        return data["results"]

    def check_cards(self, read: dict) -> None:
        cards = read["cards"]
        self.assertEqual(sorted(cards), sorted(STATES))
        for task, wanted in STATES.items():
            with self.subTest(task=task):
                found = cards[task]
                line = "dashed" if wanted == "stale" else "solid"
                self.assertEqual((found["state"], found["border"], found["sides"]), (wanted, ["2px", line, read["tones"][TONES[wanted]]], 1), found)
                self.assertNotEqual(found["shadow"], "none", found)
                self.assertEqual((found["owner"], found["avatar"], found["first"]), (OWNERS[task], "face" if OWNERS[task] else "nobody", True), found)
                left, top, size = found["corner"]
                self.assertTrue(0 <= left <= 16 and 0 <= top <= 16 and size >= 20, found)
                self.assertEqual(set(found["tones"]) & STATE_TONES, set(), found)
                self.assertTrue(found["title"].startswith(f"{task}: "), found)
                self.assertEqual((found["working"], found["animation"]), (True, "lub-dub") if task in WORKING else (False, "none"), found)

    def check_colours(self, read: dict) -> None:
        cards = read["cards"]
        colours = {state: cards[task]["border"][2] for task, state in STATES.items()}
        self.assertEqual(len(set(colours.values())), len(TONES), colours)
        still = {task: cards[task]["shadow"] for task in STATES if task not in WORKING}
        for state in set(TONES) - {"running"}:
            with self.subTest(glow=state):
                self.assertEqual(len({glow for task, glow in still.items() if STATES[task] == state}), 1, still)
        self.assertEqual(len(set(still.values())), len(TONES) - 1, still)
        self.assertGreater(len(read["beat"]), 1, read["beat"])
        self.assertNotEqual(cards["work/run"]["border"], cards["work/old"]["border"])

    def check_legend(self, read: dict) -> None:
        self.assertEqual([key for key, *_ in read["legend"]], list(TONES))
        for key, words, line, colour in read["legend"]:
            with self.subTest(legend=key):
                self.assertTrue(words, read["legend"])
                self.assertEqual((line, colour), ("dashed" if key == "stale" else "solid", read["tones"][TONES[key]]))
        self.assertEqual(read["toggle"], ["Legend", "true"], read["toggle"])

    def test_chromium_each_state_has_its_own_border_glow_and_owner_avatar_in_light_and_dark_at_three_widths(self):
        seen = {}
        for theme in ("light", "dark"):
            for (width, _), read in zip(base.WIDTHS, self.run_theme(theme), strict=True):
                with self.subTest(theme=theme, width=width):
                    self.assertNotIn("error", read, read)
                    self.assertEqual(read["mode"], theme)
                    self.check_cards(read)
                    self.check_colours(read)
                    self.check_legend(read)
                    self.assertFalse(read["wide"], read)
                    seen[theme] = read["tones"]
        self.assertNotEqual(seen["light"], seen["dark"])


if __name__ == "__main__":
    unittest.main()
