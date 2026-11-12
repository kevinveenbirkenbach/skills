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

import test_orchestrator_e2e as base
from hub_case import HubCase
from hub_support import iso

OUT = Path(os.environ.get("E2E_OUT", "/tmp/workbench-w6-shots"))
CUE = "e2e-bubbles"
FIRST = "Disk almost full on the build host, the gate waits for space now"
SECOND = "Gate green for the merge"
VIEWS = {1920: "agents/orbit", 1366: "stream/radio", 390: "agents/hierarchy"}
SECOND_FROM = {1920: "Skills", 1366: "Skills", 390: "Docs"}
SECOND_ANCHORED = {1920: True, 1366: False, 390: False}
CALM = [{"name": "prefers-reduced-motion", "value": "reduce"}]
GUARD = """() => {
  window.e2eViolations = [];
  document.addEventListener("securitypolicyviolation", (event) => window.e2eViolations.push(`${event.violatedDirective} ${event.blockedURI}`));
}"""
READ = """
  const toggle = document.getElementById("bubbles-toggle");
  const layer = document.getElementById("bubbles");
  const live = () => all(".speech-bubble:not(.leaving)", layer);
  const speaking = () => live().find((node) => node.dataset.state === "speaking") || null;
  const waiting = () => live().find((node) => node.dataset.state === "waiting") || null;
  const read = (node) => {
    if (!node) {
      return null;
    }
    const style = getComputedStyle(node);
    const box = node.getBoundingClientRect();
    return {
      who: node.dataset.who, scale: Number(node.dataset.scale), state: node.dataset.state, words: Number(node.dataset.words), text: text(node.querySelector(".bubble-words")),
      anchored: node.parentElement === layer, rendered: Math.round(new DOMMatrix(style.transform).a * 100) / 100, transition: style.transitionProperty, font: style.fontFamily,
      box: {left: box.left, top: box.top, right: box.right, bottom: box.bottom},
    };
  };
  const cue = (word) => fetch("/api/tts", {method: "POST", headers: {"X-Kvb-Orchestrator": "1", "Content-Type": "application/json"}, body: JSON.stringify({text: word, voice: ""}), cache: "no-store"});
"""
BUBBLES_ON = """(async () => {@HELPERS@@READ@
  const before = [toggle.getAttribute("aria-pressed"), layer.hidden];
  toggle.click();
  const on = Boolean(await until(() => toggle.getAttribute("aria-pressed") === "true" && !layer.hidden, 8000));
  await cue("@CUE@");
  if (!(await until(() => speaking() && waiting(), 25000))) {
    return {before, on, error: "no pair of bubbles", bubbles: live().map(read), toasts: all("#toasts .toast").map(text)};
  }
  await sleep(400);
  return {before, on, first: read(speaking()), second: read(waiting())};
})()"""
BUBBLES_GROW = """(async () => {@HELPERS@@READ@
  const who = speaking() ? speaking().dataset.who : null;
  const seen = [];
  let [grown, faded, gone] = [null, null, null];
  const end = Date.now() + 15000;
  while (who && !grown && Date.now() < end) {
    const now = speaking();
    if (now && now.dataset.who === who) {
      seen.push(Number(now.dataset.words));
    } else if (now) {
      faded = Boolean(layer.querySelector(`.speech-bubble.leaving[data-who="${CSS.escape(who)}"]`));
      await sleep(450);
      gone = !layer.querySelector(`.speech-bubble[data-who="${CSS.escape(who)}"]`);
      grown = read(speaking());
    }
    await sleep(40);
  }
  return {who, seen: seen.filter((value, index) => value !== seen[index - 1]), faded, gone, grown};
})()"""
BUBBLES_DONE = """(async () => {@HELPERS@@READ@
  const cleared = Boolean(await until(() => !layer.querySelector(".speech-bubble"), 10000));
  const faces = [...document.fonts].filter((face) => face.family.replace(/["']/g, "") === "Comic Neue").map((face) => face.status);
  return {cleared, faces, hidden: layer.hidden, violations: window.e2eViolations || null};
})()"""
BUBBLES_3D = """(async () => {@HELPERS@@READ@
  const canvas = Boolean(await until(() => document.querySelector("#main .graph3d canvas"), 15000));
  await sleep(1500);
  await cue("@CUE@");
  if (!(await until(speaking, 25000))) {
    return {canvas, error: "no bubble in 3D", bubbles: live().map(read)};
  }
  const first = read(speaking());
  await sleep(500);
  const later = read(speaking());
  const graph = document.querySelector("#main .graph3d").getBoundingClientRect();
  return {canvas, first, later, graph: {left: graph.left, top: graph.top, right: graph.right, bottom: graph.bottom}, mode: text(document.querySelector("#main .space-note"))};
})()"""
BUBBLES_KEPT = """(async () => {@HELPERS@@READ@
  await sleep(300);
  const kept = [toggle.getAttribute("aria-pressed"), layer.hidden, toggle.title, toggle.getAttribute("aria-label")];
  toggle.click();
  const off = Boolean(await until(() => toggle.getAttribute("aria-pressed") === "false" && layer.hidden, 8000));
  return {kept, off, display: getComputedStyle(layer).display, bubbles: layer.querySelectorAll(".speech-bubble").length, violations: window.e2eViolations || null};
})()"""


def probe(template: str, cue: str = CUE) -> str:
    return template.replace("@HELPERS@", base.HELPERS).replace("@READ@", READ).replace("@CUE@", cue)


def quiet(found: dict) -> dict:
    violations = found["violations"]
    return {**found, "violations": None if violations is None else [seen for seen in violations if not seen.endswith("/favicon.ico")]}


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestWorkbenchBubbles(HubCase):
    drive = base.TestOrchestratorE2E.drive

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        now = time.time()
        self.write_council({
            "work/s2/claim.json": {"office": "work/s2", "session": "s2", "runtime": "claude", "name": "Stage", "since": iso(now - 7200), "beat": now - 60, "work": "x"},
            "chair/claim.json": {"office": "chair", "session": "s1", "runtime": "claude", "name": "Skills session", "since": iso(now - 7200), "beat": now, "work": "allocate"},
            "news.jsonl": self.jsonl([
                {"ts": now - 600, "from": "Skills session", "to": ["Stage"], "text": "rebase please", "class": "post", "v": 2},
                {"ts": now - 500, "from": "Stage", "to": ["Skills session"], "text": "gate red", "class": "call", "v": 2},
                {"ts": now - 400, "from": "Docs", "to": [], "text": "docs are green", "class": "newsletter", "v": 2},
            ]),
        })
        self.keys = {row["from"]: row["source"] for row in self.snapshot()["radio"]}
        hub = self.httpd.hub
        spoken = base.tone(1, 8000)

        def synthesize(body: bytes) -> bytes:
            word = json.loads(body)["text"]
            if word.startswith(CUE):
                now = time.time()
                rows = [
                    {"ts": now - 0.01, "from": "Stage", "to": [], "text": FIRST, "class": "security", "v": 2},
                    {"ts": now, "from": "Docs" if word.endswith("-docs") else "Skills session", "to": [], "text": SECOND, "class": "security", "v": 2},
                ]
                with (self.council / "news.jsonl").open("a", encoding="utf-8") as handle:
                    handle.write(self.jsonl(rows))
            return spoken

        patch = mock.patch.object(hub.speech, "synthesize", synthesize)
        patch.start()
        self.addCleanup(patch.stop)
        self.base = f"http://{self.host}/"

    def steps(self, browser: str, calm: bool, three: bool) -> list[dict]:
        steps = []
        for width, height in base.WIDTHS:
            view = VIEWS[width]
            media = CALM if calm and width == 390 else []
            cue = f"{CUE}-docs" if SECOND_FROM[width] == "Docs" else CUE
            shot = str(OUT / f"{browser}-{width}-bubbles")
            steps += [
                {"width": width, "height": height, "url": f"{self.base}?{width}#{view}", "wait": 1200, "probe": probe(BUBBLES_ON, cue), "shot": f"{shot}-pair.png", "media": media},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(BUBBLES_GROW), "shot": f"{shot}-grown.png", "media": media},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(BUBBLES_DONE), "shot": None, "media": media},
            ]
            if three and width == 1366:
                steps.append({"width": width, "height": height, "url": f"{self.base}?3d#agents/3d", "wait": 1500, "probe": probe(BUBBLES_3D), "shot": f"{shot}-3d.png"})
            steps.append({"width": width, "height": height, "url": f"{self.base}?{width}-reloaded#{view}", "wait": 1200, "probe": probe(BUBBLES_KEPT), "shot": f"{shot}-off.png", "media": media})
        return steps

    def check(self, data: dict, browser: str, calm: bool, three: bool) -> None:
        results = iter(data["results"])
        for width, _ in base.WIDTHS:
            on, grow, done = next(results), next(results), next(results)
            solid = next(results) if three and width == 1366 else None
            kept = next(results)
            first_key, second_key = self.keys["Stage"], self.keys[SECOND_FROM[width]]
            with self.subTest(browser=browser, width=width):
                self.assertNotIn("error", on, on)
                self.assertEqual((on["before"], on["on"]), (["false", True], True))
                first, second = on["first"], on["second"]
                self.assertEqual((first["who"], first["scale"], first["rendered"], first["state"], first["anchored"]), (first_key, 1, 1, "speaking", True), first)
                self.assertTrue(0 < first["words"] < len(FIRST.split()), first)
                self.assertEqual(first["text"], " ".join(FIRST.split()[: first["words"]]))
                self.assertEqual(first["font"].replace('"', "").split(",")[0], "Comic Neue", first["font"])
                self.assertEqual((second["who"], second["scale"], second["rendered"], second["state"], second["text"], second["words"]), (second_key, 0.8, 0.8, "waiting", "…", 0), second)
                self.assertEqual(second["anchored"], SECOND_ANCHORED[width], second)
                motion = "opacity" if calm and width == 390 else "transform, opacity"
                self.assertEqual((first["transition"], second["transition"]), (motion, motion))
                self.assertEqual(grow["who"], first_key)
                self.assertGreaterEqual(len(grow["seen"]), 3, grow)
                self.assertEqual(grow["seen"], sorted(grow["seen"]), grow)
                self.assertEqual(grow["seen"][-1], len(FIRST.split()), grow)
                self.assertEqual((grow["faded"], grow["gone"]), (True, True), grow)
                grown = grow["grown"]
                self.assertEqual((grown["who"], grown["scale"], grown["rendered"], grown["state"]), (second_key, 1, 1, "speaking"), grown)
                self.assertEqual(grown["text"], " ".join(SECOND.split()[: grown["words"]]))
                self.assertEqual(quiet(done), {"cleared": True, "faces": ["loaded"], "hidden": False, "violations": []})
                self.assertEqual(quiet(kept), {"kept": ["true", False, "Speech bubbles", "Speech bubbles"], "off": True, "display": "none", "bubbles": 0, "violations": []})
            if solid is not None:
                with self.subTest(browser=browser, view="3d"):
                    self.assertNotIn("error", solid, solid)
                    graph = solid["graph"]
                    for read in (solid["first"], solid["later"]):
                        self.assertEqual((read["who"], read["anchored"]), (first_key, True), solid)
                        middle = (read["box"]["left"] + read["box"]["right"]) / 2
                        self.assertTrue(graph["left"] <= middle <= graph["right"] and graph["top"] - 16 <= read["box"]["bottom"] <= graph["bottom"], solid)
        self.assertFalse(self.httpd.hub.settings.get()["bubbles"])

    def test_chromium_reads_two_rows_without_tts_as_growing_bubbles_keeps_the_switch_and_hides_the_layer_at_three_widths(self):
        data = self.drive(self.steps("chromium", True, True), None, init=GUARD)
        (OUT / "chromium-bubbles.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        self.check(data, "chromium", True, True)

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_reads_two_rows_without_tts_as_growing_bubbles_keeps_the_switch_and_hides_the_layer_at_three_widths(self):
        data = self.drive(self.steps("firefox", False, False), None, "bidi.mjs", os.environ.get("FIREFOX", "firefox"), init=GUARD)
        (OUT / "firefox-bubbles.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        self.check(data, "firefox", False, False)


if __name__ == "__main__":
    unittest.main()
