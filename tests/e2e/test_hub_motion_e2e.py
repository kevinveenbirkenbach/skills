"""Exercise requirement 086 in Chromium: toasts and cards fade out, running tasks beat, confetti lands and fades, reduced motion removes at once."""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

import hub_e2e_kit as base
import test_board_running_e2e as running
import test_match_release_card_e2e as deck
from hub_case import HubCase
from kvb_orchestrator import batches

OUT = Path(os.environ.get("E2E_OUT", "/tmp/hub-086-shots"))
CALM = [{"name": "prefers-reduced-motion", "value": "reduce"}]
WORKING = ["work/alpha", "work/bravo", "work/delta"]
STILL = ["work/charlie", "work/echo"]
FADE_MIN_MS = 100
CONFETTI_MAX_MS = 10000
WATCH = """
  const fading = (node, start, limit) => new Promise((resolve) => {
    const began = performance.now();
    const between = [];
    const step = () => {
      const at = performance.now() - began;
      if (!node.isConnected || at > limit) {
        resolve({gone: node.isConnected ? null : Math.round(at), span: between.length ? Math.round(between[between.length - 1] - between[0]) : 0, frames: between.length});
        return;
      }
      const seen = Number(getComputedStyle(node).opacity);
      if (seen > 0 && seen < 1) {
        between.push(at);
      }
      requestAnimationFrame(step);
    };
    start();
    step();
  });
  const refusedToast = async () => {
    for (let tries = 0; tries < 8 && card() && card().dataset.stale !== "true"; tries += 1) {
      const id = card().dataset.card;
      key("ArrowUp");
      await until(() => card() && card().dataset.card !== id, 4000);
      await sleep(300);
    }
    if (!card() || card().dataset.stale !== "true") {
      return null;
    }
    key("ArrowRight");
    return until(() => all("#toasts .toast").find((node) => text(node.querySelector("strong")) === "Accept: refused"), 4000);
  };
  const rain = () => document.querySelector(".confetti-rain");
  const bits = () => all(".confetti-rain i").map((node) => node.getBoundingClientRect());
"""
MOTION = """(async () => {@HELPERS@@CARD@@STEPS@@WATCH@
  await screenShown(8000);
  if (!(await until(card, 8000))) {
    return {error: text(document.getElementById("main")).slice(0, 300)};
  }
  await sleep(400);
  const box = await refusedToast();
  if (!box) {
    return {error: "no refused toast"};
  }
  await sleep(300);
  const toast = await fading(box, () => box.click(), 3000);
  if (!(await decideAll())) {
    return {toast, error: text(document.getElementById("main")).slice(0, 300)};
  }
  const appeared = performance.now();
  const layer = await until(rain, 2000);
  if (!layer) {
    return {toast, error: "no confetti"};
  }
  const bar = document.getElementById("head").getBoundingClientRect().bottom;
  const first = bits();
  const confetti = {
    pieces: first.length, below: Math.min(...first.map((rect) => rect.top)) - bar, layerTop: Math.round(layer.getBoundingClientRect().top - bar),
    spread: (Math.max(...first.map((rect) => rect.right)) - Math.min(...first.map((rect) => rect.left))) / innerWidth,
  };
  await sleep(Math.max(0, 4500 - (performance.now() - appeared)));
  confetti.landed = bits().map((rect) => Math.round(rect.bottom - innerHeight));
  confetti.resting = Number(getComputedStyle(layer).opacity);
  await until(() => !rain(), CONFETTI_MAX);
  confetti.gone = rain() ? null : Math.round(performance.now() - appeared);
  confetti.left = all(".confetti-rain, .confetti-rain i").length;
  const risk = document.querySelector('#main .match-decision[data-card="@RED@"] .match-accept-risk');
  if (risk) {
    risk.click();
    await sleep(800);
  }
  const release = card();
  if (!release || !releasing()) {
    return {toast, confetti, error: "no release card"};
  }
  const released = await fading(release, () => key("d"), 20000);
  return {toast, confetti, released};
})()"""
CALMED = """(async () => {@HELPERS@@CARD@@STEPS@@WATCH@
  await screenShown(8000);
  if (!(await until(card, 8000))) {
    return {error: text(document.getElementById("main")).slice(0, 300)};
  }
  await sleep(400);
  const box = await refusedToast();
  if (!box) {
    return {error: "no refused toast"};
  }
  const toast = await fading(box, () => box.click(), 3000);
  if (!(await decideAll())) {
    return {toast, error: text(document.getElementById("main")).slice(0, 300)};
  }
  await sleep(1000);
  const confetti = all(".confetti-rain, .confetti-rain i").length;
  const front = card();
  const back = await fading(front, () => key("ArrowLeft"), 4000);
  return {toast, confetti, back};
})()"""
BEAT = """(async () => {@HELPERS@
  const card = (task) => all("#main .kanban-card").find((node) => node.dataset.task === task) || null;
  if (!(await until(() => card("work/delta") && card("work/delta").querySelector(".kanban-mark"), 10000))) {
    return {error: text(document.getElementById("main"))};
  }
  await sleep(400);
  const keyframes = (wanted) => {
    for (const sheet of document.styleSheets) {
      for (const rule of sheet.cssRules) {
        if (rule.type === CSSRule.KEYFRAMES_RULE && rule.name === wanted) {
          return [...new Set([...rule.cssRules].flatMap((frame) => [...frame.style]))].sort();
        }
      }
    }
    return null;
  };
  const sample = async (node) => {
    const seen = {transform: new Set(), shadow: new Set()};
    for (let at = 0; at < 26; at += 1) {
      const look = getComputedStyle(node);
      seen.transform.add(look.transform);
      seen.shadow.add(look.boxShadow);
      await sleep(50);
    }
    return {transforms: [...seen.transform].filter((value) => value !== "none").length, shadows: seen.shadow.size};
  };
  const tasks = [...@WORKING@, ...@STILL@];
  const marked = Object.fromEntries(tasks.map((task) => [task, card(task) ? card(task).classList.contains("is-working") : null]));
  const animation = Object.fromEntries(tasks.map((task) => [task, card(task) ? getComputedStyle(card(task)).animationName : null]));
  return {marked, animation, beat: await sample(card("work/delta")), still: await sample(card("work/echo")), frames: {beat: keyframes("lub-dub"), glow: keyframes("lub-dub-glow")}};
})()"""


def probe(template: str, **names: str) -> str:
    """Args:
        template: a probe with @WATCH@, @WORKING@, @STILL@, CONFETTI_MAX and
            the placeholders deck.probe() fills.
        names: further @NAME@ placeholders and their values.

    Returns:
        The probe with every placeholder filled.
    """
    filled = template.replace("@WATCH@", WATCH).replace("@WORKING@", json.dumps(WORKING)).replace("@STILL@", json.dumps(STILL)).replace("CONFETTI_MAX", str(CONFETTI_MAX_MS))
    return deck.probe(filled, **names)


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestHubMotion(deck.ReleaseDeck):
    def run_deck(self, name: str, template: str, media: list[dict] | None) -> dict:
        step = {"width": 1366, "height": 768, "url": f"{self.base}?{name}#tasks/match", "wait": 1500, "shot": str(OUT / f"chromium-{name}.png"),
                "probe": probe(template, red=f"review:{self.red}"), "media": media or []}
        with mock.patch.object(batches, "UNDO", 0.3):
            data = self.drive([step], self.authenticator(), init=deck.INIT)
        (OUT / f"chromium-{name}.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        found = data["results"][0]
        self.assertNotIn("error", found, found)
        return found

    def test_chromium_a_dismissed_toast_and_a_released_card_fade_and_confetti_lands_and_fades(self):
        found = self.run_deck("motion", MOTION, None)
        for part in ("toast", "released"):
            with self.subTest(part=part):
                self.assertIsNotNone(found[part]["gone"], found)
                self.assertGreaterEqual(found[part]["span"], FADE_MIN_MS, found)
        confetti = found["confetti"]
        self.assertEqual(confetti["pieces"], 28, confetti)
        self.assertGreaterEqual(confetti["below"], -1, confetti)
        self.assertGreaterEqual(confetti["layerTop"], -1, confetti)
        self.assertGreaterEqual(confetti["spread"], 0.9, confetti)
        self.assertTrue(all(abs(gap) <= 2 for gap in confetti["landed"]), confetti)
        self.assertEqual(confetti["resting"], 1, confetti)
        self.assertIsNotNone(confetti["gone"], confetti)
        self.assertLessEqual(confetti["gone"], CONFETTI_MAX_MS, confetti)
        self.assertEqual(confetti["left"], 0, confetti)

    def test_chromium_under_reduced_motion_a_toast_and_a_card_leave_at_once_and_no_confetti_falls(self):
        found = self.run_deck("calm", CALMED, CALM)
        for part in ("toast", "back"):
            with self.subTest(part=part):
                self.assertIsNotNone(found[part]["gone"], found)
                self.assertEqual(found[part]["frames"], 0, found)
        self.assertEqual(found["confetti"], 0, found)


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestHubHeartbeat(HubCase):
    drive = base.OrchestratorE2ECase.drive

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        now = time.time()
        self.write_council(running.board_council(now))
        sessions = {
            "s-docs": {"name": "Docs session", "status": "busy", "statusUpdatedAt": int((now - 120) * 1000), "running": True},
            "s-late": {"name": "Late session", "status": "busy", "statusUpdatedAt": int((now - 600) * 1000), "running": True},
        }
        self.httpd.hub.agent_sessions.write_text(json.dumps({"written": now, "sessions": sessions}), encoding="utf-8")
        job = self.httpd.hub.jobs.add({"task": "work/delta", "command": "make deploy-hub", "directory": "/", "sha256": "", "status": "running", "proof": None, "head": "",
                                       "code": None, "output": "", "created_ts": now, "started": now - 45, "finished": None, "dismissed": False})
        self.httpd.hub.runner_marker.write_text(json.dumps({"pid": os.getpid(), "job": job["id"], "task": "work/delta", "started": now - 45}), encoding="utf-8")

    def test_chromium_running_tasks_beat_with_scale_and_glow_and_keep_only_the_glow_under_reduced_motion(self):
        local = f"http://localhost:{self.port}/"
        steps = [{"width": 1366, "height": 768, "url": f"{local}?{name}#tasks/board", "wait": 1500, "probe": probe(BEAT), "shot": str(OUT / f"chromium-beat-{name}.png"), "media": media}
                 for name, media in (("motion", []), ("calm", CALM))]
        data = self.drive(steps, None)
        (OUT / "chromium-beat.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        moving, calm = data["results"]
        for found, name in ((moving, "lub-dub"), (calm, "lub-dub-glow")):
            with self.subTest(animation=name):
                self.assertNotIn("error", found, found)
                self.assertEqual(found["marked"], {**dict.fromkeys(WORKING, True), **dict.fromkeys(STILL, False)}, found)
                self.assertEqual(found["animation"], {**dict.fromkeys(WORKING, name), **dict.fromkeys(STILL, "none")}, found)
                self.assertGreater(found["beat"]["shadows"], 1, found)
                self.assertEqual(found["still"], {"transforms": 0, "shadows": 1}, found)
        self.assertGreater(moving["beat"]["transforms"], 0, moving)
        self.assertEqual(calm["beat"]["transforms"], 0, calm)
        self.assertEqual(moving["frames"], {"beat": ["box-shadow", "transform"], "glow": ["box-shadow"]}, moving)


if __name__ == "__main__":
    unittest.main()
