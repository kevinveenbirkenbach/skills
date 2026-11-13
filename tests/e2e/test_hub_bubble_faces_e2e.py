from __future__ import annotations

import json
import os
import shutil
import sys
import time
import unittest
from collections.abc import Callable
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

import test_orchestrator_e2e as base
from hub_case import HubCase
from hub_support import iso

OUT = Path(os.environ.get("E2E_OUT", "/tmp/hub-bubble-faces-shots"))
WIDTH, HEIGHT = 1366, 768
CUE = "front"
SPEAKERS = ("Skills session", "Stage", "Docs")
SAID = "disk almost full on the build host so rotate the logs and retry the gate before the next push"
SILENT = """() => {
  try {
    localStorage.setItem("kvb-orchestrator.radio", JSON.stringify({mode: "silence", classes: ["mayday", "security"], muted: []}));
  } catch (error) {
    return;
  }
}"""
SPAWN = """
  const agentChart = () => document.querySelector('#main svg.ancestry[aria-label="Ancestry: operator, chair, sessions, subagents"]');
  const agentNodes = () => all("g.ancestry-node", agentChart()).map((node) => {
    const art = node.querySelector(".face-art");
    return {agent: node.dataset.agent, kind: node.dataset.kind, face: node.dataset.face || null, r: Number(node.querySelector("circle").getAttribute("r")), art: art ? art.innerHTML : null};
  });
"""
SPAWN_ON = """(async () => {@HELPERS@@SPAWN@
  const ready = await until(() => agentChart() && agentChart().querySelector('g.ancestry-node[data-kind="twig"]'), 10000);
  if (!ready) {
    return {error: "no agent ancestry", main: (text(document.getElementById("main")) || "").slice(0, 300)};
  }
  agentChart().scrollIntoView({block: "center"});
  await sleep(300);
  return {nodes: agentNodes()};
})()"""
GRAPH = """(async () => {@HELPERS@
  await until(() => all("#main svg.chart .node[data-face] .face-art").length, 8000);
  return {faces: Object.fromEntries(all("#main svg.chart .node[data-face]").map((node) => [node.dataset.face, node.querySelector(".face-art").innerHTML]))};
})()"""
SPAWN_OFF = """(async () => {@HELPERS@@SPAWN@
  await until(() => agentChart(), 8000);
  const box = document.querySelector('#main input[data-look="faces"]');
  if (!box) {
    return {error: "no faces switch"};
  }
  box.click();
  const plain = await until(() => agentChart() && agentChart().querySelector("g.ancestry-node") && !agentChart().querySelector(".face-art"), 6000);
  agentChart().scrollIntoView({block: "center"});
  await sleep(300);
  return {switched: Boolean(plain), checked: box.checked, nodes: agentNodes()};
})()"""
FRONT = """
  const bubbles = () => all("#bubbles .speech-bubble:not(.leaving)");
  const speaker = () => bubbles().find((node) => node.dataset.state === "speaking") || null;
  const where = (node) => (node.parentElement.classList.contains("bubble-bar") ? "bar" : "layer");
  const middle = () => [Math.round(innerWidth / 2) - 13, Math.round(innerHeight / 2)];
  const pin = (key, x, y) => {
    let node = all("[data-e2e-pin]").find((item) => item.dataset.e2ePin === key);
    if (!node) {
      node = document.createElement("span");
      node.dataset.e2ePin = key;
      node.dataset.face = key;
      Object.assign(node.style, {position: "fixed", width: "26px", height: "26px", borderRadius: "50%", background: "#9aa4b1"});
      document.body.prepend(node);
    }
    Object.assign(node.style, {left: `${x}px`, top: `${y}px`});
  };
  const unpin = () => all("[data-e2e-pin]").forEach((node) => node.remove());
  const front = (x, y) => {
    const hit = document.elementFromPoint(x, y);
    const bubble = hit ? hit.closest(".speech-bubble") : null;
    return bubble ? bubble.dataset.who : null;
  };
  const inside = (box, x, y) => x > box.left && x < box.right && y > box.top && y < box.bottom;
  const stacked = (scene) => {
    const layer = document.getElementById("bubbles");
    layer.style.pointerEvents = "auto";
    const top = speaker();
    const others = bubbles().filter((node) => node !== top);
    const box = top.getBoundingClientRect();
    const overlaps = others.flatMap((node) => {
      const other = node.getBoundingClientRect();
      const [left, right, upper, lower] = [Math.max(box.left, other.left), Math.min(box.right, other.right), Math.max(box.top, other.top), Math.min(box.bottom, other.bottom)];
      return right - left > 4 && lower - upper > 4 ? [{other: node.dataset.who, where: [where(top), where(node)], front: front((left + right) / 2, (upper + lower) / 2)}] : [];
    });
    const tip = [box.left + box.width / 2 + parseFloat(getComputedStyle(top).getPropertyValue("--tail") || "0"), box.bottom + 4];
    const under = where(top) === "layer" ? others.find((node) => inside(node.getBoundingClientRect(), ...tip)) : null;
    const found = {
      scene, speaker: top.dataset.who, overlaps, tail: under ? {under: under.dataset.who, front: front(...tip)} : null,
      bubbles: bubbles().map((node) => [node.dataset.who, node.dataset.state, where(node), getComputedStyle(node).zIndex]),
    };
    layer.style.removeProperty("pointer-events");
    return found;
  };
"""
SAME = """(async () => {@HELPERS@@FRONT@
  await screenShown(8000);
  await sleep(800);
  await fetch("/api/tts", {method: "POST", headers: {"X-Kvb-Orchestrator": "1", "Content-Type": "application/json"}, body: JSON.stringify({text: "@CUE@", voice: ""}), cache: "no-store"});
  if (!(await until(() => bubbles().length === 3 && speaker(), 30000))) {
    return {error: "no bubbles", shown: bubbles().map((node) => [node.dataset.who, node.dataset.state])};
  }
  const first = speaker().dataset.who;
  window.e2eFirst = first;
  const [x, y] = middle();
  pin(first, x, y);
  bubbles().map((node) => node.dataset.who).filter((key) => key !== first).forEach((key, index) => pin(key, x + index * 34, y + 22 + index * 20));
  await sleep(1500);
  return stacked("same");
})()"""
BAR = """(async () => {@HELPERS@@FRONT@
  if (!speaker() || speaker().dataset.who !== window.e2eFirst) {
    return {error: "the first speaker ended before the bar scene"};
  }
  unpin();
  await sleep(400);
  const inBar = bubbles().filter((node) => where(node) === "bar");
  if (!inBar.length) {
    return {error: "no bubble in the bar", shown: bubbles().map((node) => [node.dataset.who, where(node)])};
  }
  const host = where(speaker()) === "bar" ? speaker() : inBar[0];
  const movers = where(speaker()) === "bar" ? bubbles().filter((node) => node !== host).map((node) => node.dataset.who) : [speaker().dataset.who];
  for (let round = 0; round < 2; round += 1) {
    const box = host.getBoundingClientRect();
    movers.forEach((key, index) => pin(key, box.left + box.width / 2 - 13 + index * 30, box.top + 14));
    await sleep(400);
  }
  return stacked("bar");
})()"""
NEXT = """(async () => {@HELPERS@@FRONT@
  const changed = await until(() => speaker() && speaker().dataset.who !== window.e2eFirst && !document.querySelector("#bubbles .speech-bubble.leaving"), 25000);
  if (!changed) {
    return {error: "the speaker did not change", shown: bubbles().map((node) => [node.dataset.who, node.dataset.state])};
  }
  const next = speaker().dataset.who;
  unpin();
  const [x, y] = middle();
  pin(next, x, y);
  bubbles().map((node) => node.dataset.who).filter((key) => key !== next).forEach((key, index) => pin(key, x + index * 34, y + 22 + index * 20));
  await sleep(1500);
  return {...stacked("next"), first: window.e2eFirst};
})()"""


def probe(template: str) -> str:
    return template.replace("@HELPERS@", base.HELPERS).replace("@SPAWN@", SPAWN).replace("@FRONT@", FRONT).replace("@CUE@", CUE)


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestHubBubbleFrontAndSpawnFaces(HubCase):
    drive = base.TestOrchestratorE2E.drive
    subagents = base.TestOrchestratorE2E.subagents

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        now = time.time()
        self.claim("s1", "Skills session")
        self.write_council({
            "work/s2/claim.json": {"office": "work/s2", "session": "s2", "runtime": "claude", "name": "Stage", "since": iso(now - 7200), "beat": now - 60, "work": "x"},
            "chair/claim.json": {"office": "chair", "session": "s1", "runtime": "claude", "name": "Skills session", "since": iso(now - 7200), "beat": now, "work": "allocate"},
        })
        self.subagents(now)
        hub = self.httpd.hub
        hub.settings.put({**hub.settings.get(), "bubbles": True}, hub.settings.get())

        def synthesize(body: bytes, admit: Callable[[str], None]) -> bytes:
            if json.loads(body)["text"] == CUE:
                rows = [{"ts": time.time(), "from": name, "to": [], "text": f"{name}: {SAID}, {SAID}", "class": "security", "v": 2} for name in SPEAKERS]
                with (self.council / "news.jsonl").open("a", encoding="utf-8") as handle:
                    handle.write(self.jsonl(rows))
            return base.tone(1, 8000)

        patch = mock.patch.object(hub.speech, "synthesize", synthesize)
        patch.start()
        self.addCleanup(patch.stop)
        self.base = f"http://{self.host}/"

    def steps(self) -> list[dict]:
        shot = str(OUT / f"chromium-{WIDTH}")
        page = {"width": WIDTH, "height": HEIGHT}
        return [
            {**page, "url": f"{self.base}?faces#agents/tree", "wait": 1200, "probe": probe(SPAWN_ON), "shot": f"{shot}-spawn-faces-on.png"},
            {**page, "url": f"{self.base}?graph#agents/orbit", "wait": 1200, "probe": probe(GRAPH), "shot": None},
            {**page, "url": f"{self.base}?plain#agents/tree", "wait": 1200, "probe": probe(SPAWN_OFF), "shot": f"{shot}-spawn-faces-off.png"},
            {**page, "url": f"{self.base}?bubbles#stream", "wait": 1200, "probe": probe(SAME), "shot": f"{shot}-bubbles-same-layer.png"},
            {**page, "url": None, "wait": 0, "probe": probe(BAR), "shot": f"{shot}-bubbles-bar.png"},
            {**page, "url": None, "wait": 0, "probe": probe(NEXT), "shot": f"{shot}-bubbles-next-speaker.png"},
        ]

    def check(self, data: dict) -> None:
        faces_on, graph, faces_off, same, bar, following = data["results"]
        for found in data["results"]:
            self.assertNotIn("error", found, found)
        nodes = {node["agent"]: node for node in faces_on["nodes"]}
        faced = {agent for agent, node in nodes.items() if node["art"]}
        self.assertEqual({nodes[agent]["kind"] for agent in faced}, {"operator", "chair", "session"}, faces_on)
        self.assertTrue({"s1", "s2"} <= faced, faces_on)
        for agent, node in nodes.items():
            with self.subTest(agent=agent):
                self.assertEqual((node["face"], node["r"]), (agent, 13) if agent in faced else (None, 9))
        shared = faced & set(graph["faces"])
        self.assertTrue({"s1", "s2"} <= shared, graph)
        for agent in shared:
            with self.subTest(agent=agent):
                self.assertEqual(nodes[agent]["art"], graph["faces"][agent])
        self.assertEqual((faces_off["switched"], faces_off["checked"]), (True, False), faces_off)
        self.assertEqual({(node["art"], node["face"], node["r"]) for node in faces_off["nodes"]}, {(None, None, 9)})
        self.assertEqual(len(faces_off["nodes"]), len(faces_on["nodes"]))
        for scene in (same, bar, following):
            with self.subTest(scene=scene["scene"]):
                self.assertTrue(scene["overlaps"], scene)
                self.assertEqual({overlap["front"] for overlap in scene["overlaps"]}, {scene["speaker"]}, scene)
                if scene["tail"]:
                    self.assertEqual(scene["tail"]["front"], scene["speaker"], scene)
        self.assertIsNotNone(same["tail"], same)
        self.assertTrue(any(overlap["where"][0] != overlap["where"][1] for overlap in bar["overlaps"]), bar)
        self.assertNotEqual(following["speaker"], following["first"])

    def test_chromium_keeps_the_speaking_bubble_in_front_and_draws_faces_in_the_spawn_ancestry(self):
        data = self.drive(self.steps(), None, init=SILENT)
        (OUT / "chromium-bubble-faces.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        self.check(data)


if __name__ == "__main__":
    unittest.main()
