from __future__ import annotations

import array
import base64
import json
import math
import os
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from hub_case import HubCase
from hub_engines import wav_bytes
from hub_support import ASK, iso

OUT = Path(os.environ.get("E2E_OUT", "/tmp/orchestrator-phase4-shots"))
WIDTHS = ((1920, 1080), (1366, 768), (390, 844))
VIEWS = ("orbit", "chord", "swimlane", "tree", "3d")
TASK_VIEWS = ("list", "board", "rasci", "gantt", "burn", "3d")
SCREENS = ["home", "stream", "tasks/operator", "tasks/match", "stream/rules", *(f"{tab}/{view}" for tab in ("agents", "artifacts") for view in VIEWS), "agents/hierarchy", *(f"tasks/{view}" for view in TASK_VIEWS), "resources"]
SUBS = ["Firewall"]
TABS = ["Home", "Stream", "Agents", "Artifacts", "Tasks", "Resources"]
HELPERS = """
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const until = async (check, ms) => {
    const end = Date.now() + ms;
    while (Date.now() < end) {
      const found = check();
      if (found) {
        return found;
      }
      await sleep(200);
    }
    return null;
  };
  const all = (selector, root) => [...(root || document).querySelectorAll(selector)];
  const text = (node) => (node ? node.textContent.trim() : null);
  const name = (node) => (node ? node.getAttribute("aria-label") || text(node) : null);
  const toolbarRows = () => {
    const bar = document.querySelector('#main [role="toolbar"][aria-label="Tasks"]');
    const boxes = bar ? [...bar.children].filter((node) => node.getClientRects().length).map((node) => node.getBoundingClientRect()).sort((a, b) => a.top - b.top) : [];
    let [rows, bottom] = [0, -Infinity];
    for (const box of boxes) {
      if (box.top >= bottom - 1) {
        rows += 1;
        bottom = box.bottom;
      } else {
        bottom = Math.max(bottom, box.bottom);
      }
    }
    return rows;
  };
  const taskLayout = () => all("#main .graph.tasks > *").map((node) => (node.matches('[role="toolbar"]') ? "toolbar" : node.matches('[aria-label="Task filters"]') ? "chips" : "body"));
  const screenShown = async (ms) => {
    const shown = await until(() => {
      if (typeof Nav !== "object") {
        return false;
      }
      const route = Nav.route(location.hash);
      const view = route.view ? Nav.viewsOf(route.screen).find(([id]) => id === route.view)[1] : null;
      const pressed = name(document.querySelector('#main [aria-label="View"] button[aria-pressed="true"]'));
      return document.getElementById("main").getAttribute("aria-labelledby") === `tab-${route.screen}` && (!view || pressed === view);
    }, ms);
    await sleep(0);
    return Boolean(shown);
  };
"""
OVERLAP = """
  const shown = (node) => node.getClientRects().length > 0 && node.getBoundingClientRect().width > 0;
  const words = (label) => [...label.childNodes].filter((node) => node.nodeType === 3).map((node) => node.textContent).join("").trim();
  const called = (node) => node.getAttribute("aria-label") || (node.closest("label") ? words(node.closest("label")) : "") || text(node) || node.type;
  const clashes = (root) => {
    const boxes = all("input, select, textarea, button", root).filter(shown).map((node) => ({node, box: node.getBoundingClientRect()}));
    const found = [];
    boxes.forEach((a, index) => boxes.slice(index + 1).forEach((b) => {
      const x = Math.min(a.box.right, b.box.right) - Math.max(a.box.left, b.box.left);
      const y = Math.min(a.box.bottom, b.box.bottom) - Math.max(a.box.top, b.box.top);
      if (x > 0.5 && y > 0.5) {
        found.push(`${called(a.node)} × ${called(b.node)}`);
      }
    }));
    const framed = (node) => (getComputedStyle(node).display === "contents" ? framed(node.parentElement) : node);
    const outside = boxes.filter(({box}) => box.right > framed(root).getBoundingClientRect().right + 0.5).map(({node}) => called(node));
    return {found, outside};
  };
"""
SPEAKING = """
  const caption = () => {
    const node = document.querySelector("#radio-spot:not([hidden]) .radio-caption");
    return node && !node.hidden ? node : null;
  };
  const ring = (box) => getComputedStyle(box.querySelector(".speaker-face"), "::after").animationName;
  const mouth = (art) => (art ? [art.classList.contains("speaking"), getComputedStyle(art.querySelector(".mouth")).animationName] : null);
  const faces = () => ({
    speaking: mouth(document.querySelector('#radio-spot .radio-caption .avatar[data-face="s2"]')),
    silent: mouth(document.querySelector('.avatar[data-face]:not([data-face="s2"])')),
    keys: [...new Set(all(".avatar.speaking").map((art) => art.dataset.face))],
  });
  const cue = async (word) => {
    await until(() => document.querySelector("#radio-spot:not([hidden])"), 8000);
    await fetch("/api/tts", {method: "POST", headers: {"X-Kvb-Orchestrator": "1", "Content-Type": "application/json"}, body: JSON.stringify({text: word, voice: ""}), cache: "no-store"});
    const found = await until(caption, 25000);
    return found ? {who: text(found.querySelector("strong")), line: text(found.querySelector(".caption-line")), chip: found.querySelector(".avatar").dataset.face, ring: ring(found), faces: faces()} : {error: "no caption", toasts: all("#toasts .toast").map(text)};
  };
"""
FITS = "tall: document.documentElement.scrollHeight > window.innerHeight, wide: document.documentElement.scrollWidth > window.innerWidth + 1"
GRAPH_HOOK = """() => {
  let made = null;
  Object.defineProperty(window, "ForceGraph3D", {
    configurable: true,
    get: () => made && ((options) => {
      const graph = made(options);
      window.e2eGraphs = [...(window.e2eGraphs || []), graph];
      return graph;
    }),
    set: (value) => {
      made = value;
    },
  });
}"""


def tone(seconds: int, rate: int) -> bytes:
    frames = array.array("h", (int(6000 * math.sin(2 * math.pi * 440 * n / rate)) for n in range(seconds * rate)))
    return wav_bytes(1, 2, rate, frames.tobytes())


UNLABELLED = """
  const unlabelled = (root, skip) => all("svg.bi", root).filter((svg) => !svg.closest(".sprite") && !(skip && skip.contains(svg))).map((svg) => svg.parentElement).filter((owner) => !text(owner) && !(owner.getAttribute("title") && owner.getAttribute("aria-label"))).map((owner) => owner.outerHTML.slice(0, 160));
"""
LABELS = UNLABELLED + """
  const wide = () => document.documentElement.scrollWidth > window.innerWidth + 1;
  const rowOf = (words) => all("#main .inbox-list > li").find((li) => li.textContent.includes(words));
  const askOf = (command) => all("#main .inbox-list > li.k-ask").find((li) => text(li.querySelector(".command code")) === command);
  const press = (root, label) => all("button", root).find((button) => name(button) === label).click();
  const out = () => document.querySelector("#main .console .console-out");
  const atEnd = () => out().scrollTop + out().clientHeight >= out().scrollHeight - 12;
  const line = () => text(document.querySelector("#main .console .console-status"));
"""
CHOICE_CHANNELS = ["post", "call", "newsletter", "broadcast", "pan-pan", "security", "mayday"]


def labelled(probe: dict) -> dict:
    return {key: probe[key] for key in ("unlabelled", "broken")}


class OrchestratorE2ECase(HubCase):
    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        self.seed()

    def seed(self) -> None:
        now = time.time()
        self.root = self.write_tree()
        feature = f"{self.root}/worktrees/github.com/me/demo/feature"
        self.claim("s1", "Skills session")
        self.write_council({
            "work/s2/claim.json": {"office": "work/s2", "session": "s2", "runtime": "claude", "name": "Stage", "since": iso(now - 7200), "beat": now - 2000, "work": "x"},
            "chair/claim.json": {"office": "chair", "session": "s1", "runtime": "claude", "name": "Skills session", "since": iso(now - 7200), "beat": now, "work": "allocate"},
            "identity/oidc/claim.json": {"office": "identity/oidc", "session": "s2", "runtime": "claude", "name": "Stage", "since": iso(now - 7200), "beat": now - 2000, "work": "oidc line"},
            "rasci.json": {
                "work/stage": {"title": "Stage line", "status": "running", "worker": "Stage (this session)", "roles": {"Stage (this session)": "RA"}},
                "work/feature": {
                    "title": "Show the merge flow in the hub", "status": "running", "worker": "Skills session", "objective": "The operator sees where a branch flows", "workdir": feature, "prio": 1,
                    "roles": {"Skills session": "RA", "Operator": "C", "Docs": "I"}, "key_results": [{"text": "Flow in the tree", "met": True}, {"text": "Flow in Tasks", "met": False}],
                    "estimates": {"Skills": {"value": 8, "complexity": 3, "at": iso(now - 600)}},
                },
                "work/docs": {"title": "Update the README", "status": "blocked", "worker": "Docs", "branch": "main", "roles": {"Docs": "R", "Maintainer": "A", "Skills": "S"}, "estimates": {"Docs": {"value": 3, "complexity": 2}}},
                "work/old": {"title": "Old line", "status": "done", "worker": "Stage", "end": iso(now - 86400), "roles": {"Stage": "RA"}},
                "operator/push": {"title": "git push", "workdir": "/repo", "status": "done", "roles": {"Operator": "R"}},
            },
            "queue.json": {"seq": 3, "entries": [{"id": "gate-3", "kind": "gate", "task": "work/feature", "workdir": feature, "session": "s1", "name": "Skills", "status": "waiting", "enqueued": now - 120, "cmd": "make test"}]},
            "radio-silence.json": {"since": now - 60, "until": now + 3600, "by": "Docs", "text": "disk full"},
            "news.jsonl": self.jsonl([
                {"ts": now - 600, "from": "Skills", "to": ["Stage"], "text": "rebase please", "class": "post", "v": 2},
                {"ts": now - 500, "from": "Stage", "to": ["Skills"], "text": "gate red", "class": "call", "v": 2},
                {"ts": now - 400, "from": "Maintainer", "to": [], "text": "main is green", "class": "newsletter", "v": 2},
                {"ts": now - 300, "from": "Maintainer", "to": [], "text": "rotate keys", "class": "security", "v": 2},
                {"ts": now - 60, "from": "Docs", "to": [], "text": "MAYDAY disk full", "class": "mayday", "v": 2},
            ]),
        })
        self.subagents(now)
        self.request("feat: orchestrator", "")
        self.create_ask({**ASK, "timeout": 3600})
        self.base = f"http://{self.host}/"

    def subagents(self, now: float) -> None:
        def line(ts: float) -> dict:
            return {"type": "user", "sessionId": "s1", "timestamp": iso(ts), "message": {"role": "user", "content": "x"}}

        folder = self.projects / "-repo" / "s1" / "subagents"
        folder.mkdir(parents=True)
        (self.projects / "-repo" / "s1.jsonl").write_text(self.jsonl([line(now - 3600), line(now - 30)]), encoding="utf-8")
        for ident, finished in (("abc", True), ("def", False)):
            (folder / f"agent-{ident}.meta.json").write_text(json.dumps({"agentType": "Explore", "description": f"look {ident}", "spawnDepth": 1, "finished": finished}), encoding="utf-8")
            (folder / f"agent-{ident}.jsonl").write_text(self.jsonl([line(now - 1800), line(now - 60)]), encoding="utf-8")

    def drive(self, steps: list[dict], authenticator: dict | None, driver: str = "cdp.mjs", binary: str = os.environ.get("CHROMIUM", "chromium"), init: str | None = None) -> dict:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump({"steps": steps, "authenticator": authenticator, "init": init}, handle)
        self.addCleanup(os.unlink, handle.name)
        done = subprocess.run(["node", str(HERE / driver), binary, handle.name], capture_output=True, text=True, timeout=900, check=False)
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        return json.loads(done.stdout)

    def beside(self, work: Callable[[], None]) -> None:
        stop = threading.Event()

        def loop() -> None:
            while not stop.wait(0.2):
                work()

        thread = threading.Thread(target=loop, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 10)
        self.addCleanup(stop.set)

    def shot(self, name: str) -> str:
        return str(OUT / f"chromium-{name}.png")

    def authenticator(self) -> dict:
        signer = self.pin()
        private = "".join(line for line in signer.pem.read_text(encoding="utf-8").splitlines() if not line.startswith("-----"))
        return {"credentialId": base64.b64encode(signer.raw_id).decode(), "privateKey": private, "rpId": "localhost"}

    def speaks(self, cues: tuple[str, ...]) -> None:
        hub = self.httpd.hub
        spoken = tone(6, 8000)

        def synthesize(body: bytes, admit: Callable[[str], None]) -> bytes:
            word = json.loads(body)["text"]
            if word in cues:
                row = {"ts": time.time(), "from": "Stage", "to": [], "text": f"Disk almost full ({word})\nsecond line", "class": "security", "v": 2}
                with (self.council / "news.jsonl").open("a", encoding="utf-8") as handle:
                    handle.write(self.jsonl([row]))
            return spoken

        patch = mock.patch.object(hub.speech, "synthesize", synthesize)
        patch.start()
        self.addCleanup(patch.stop)
