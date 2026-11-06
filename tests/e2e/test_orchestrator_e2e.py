from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from hub_case import HubCase
from hub_support import ASK, iso

OUT = Path(os.environ.get("E2E_OUT", "/tmp/orchestrator-e2e"))
WIDTHS = ((1920, 1080), (1366, 768), (390, 844))
SCREENS = ["stream", "stream/inbox", "stream/rules", *(f"{tab}/{view}" for tab in ("agents", "artifacts") for view in ("orbit", "chord", "swimlane", "tree", "3d"))]
PROBE = """(() => {
  const all = (selector) => [...document.querySelectorAll(selector)];
  const text = (node) => (node ? node.textContent.trim() : null);
  const label = (button) => text(button.firstChild);
  const badge = (button) => {
    const found = button.querySelector(".badge");
    return found && !found.hidden ? text(found) : null;
  };
  const banner = document.getElementById("mayday");
  return {
    hash: location.hash,
    title: document.title,
    h1: text(document.querySelector("h1")),
    header: all("header.top button").map((button) => button.id),
    tabs: all("#tabs > .tab-group > button").map(label),
    subs: all("#tabs .subtabs button").map(label),
    badges: Object.fromEntries(all("#tabs button").map((button) => [button.id, badge(button)])),
    banner: banner.hidden ? null : text(banner),
    rail: Boolean(document.getElementById("rail")),
    views: all('#main [aria-label="Ansicht"] button').map(text),
    chips: all('#main [aria-label="Kategorien"] button').map(text),
    menus: all("#main details.menu > summary").map(text),
    time: text(document.querySelector("#time > summary")),
    replay: Boolean(document.querySelector("#time .replay input[type=range]")),
    custom: Boolean(document.querySelector('#main details.menu input[type="datetime-local"]')),
    toolbar: all('#main [role="toolbar"] > *').map((node) => (node.tagName === "DETAILS" ? text(node.querySelector("summary")) : text(node))),
    toAll: all("#to-all input[type=radio]").map((input) => [input.value, input.checked]),
    inbox: all("#main .inbox-list > li").length,
    wide: document.documentElement.scrollWidth > window.innerWidth + 1,
  };
})()"""
ACTIONS = """(async () => {
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const press = async (key) => {
    document.dispatchEvent(new KeyboardEvent("keydown", {key, bubbles: true}));
    await sleep(300);
    return location.hash;
  };
  const found = {keys: [await press("2"), await press("3"), await press("1")]};
  document.getElementById("settings-open").click();
  await sleep(300);
  found.ambience = [...document.querySelectorAll(".sheet-box form > section:first-child button")].map((button) => button.id);
  found.speech = [...document.querySelectorAll('.sheet-box [aria-label="Klassen"] input')].map((input) => [input.parentElement.textContent.trim(), input.checked, input.disabled]);
  document.querySelector(".sheet-head button").click();
  document.getElementById("palette-open").click();
  await sleep(300);
  found.palette = [...document.querySelectorAll(".palette-list li > span:first-child")].map((span) => span.textContent.trim());
  document.dispatchEvent(new KeyboardEvent("keydown", {key: "Escape", bubbles: true}));
  await sleep(200);
  document.querySelector('#main [aria-label="Kategorien"] button:nth-child(2)').click();
  await sleep(900);
  const someone = document.querySelector('#main button.linkish[title$="öffnen"]');
  someone.click();
  await sleep(500);
  found.drawer = [...document.querySelectorAll("#drawer input[type=radio]")].map((input) => [input.value, input.checked]);
  return found;
})()"""


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestOrchestratorE2E(HubCase):
    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        now = time.time()
        self.claim("s1", "Skills session")
        self.write_council({
            "work/s2/claim.json": {"office": "work/s2", "session": "s2", "runtime": "claude", "name": "Stage", "since": iso(now - 7200), "beat": now - 2000, "work": "x"},
            "rasci.json": {"work/stage": {"title": "Stage line", "status": "running", "worker": "Stage (this session)", "roles": {"Stage (this session)": "RA"}}},
            "radio-silence.json": {"since": now - 60, "until": now + 3600, "by": "Docs", "text": "disk full"},
            "news.jsonl": self.jsonl([
                {"ts": now - 600, "from": "Skills", "to": ["Stage"], "text": "rebase please", "class": "post", "v": 2},
                {"ts": now - 500, "from": "Stage", "to": ["Skills"], "text": "gate red", "class": "call", "v": 2},
                {"ts": now - 400, "from": "Maintainer", "to": [], "text": "main is green", "class": "newsletter", "v": 2},
                {"ts": now - 300, "from": "Maintainer", "to": [], "text": "rotate keys", "class": "security", "v": 2},
                {"ts": now - 60, "from": "Docs", "to": [], "text": "MAYDAY disk full", "class": "mayday", "v": 2},
            ]),
        })
        self.request("feat: orchestrator", "")
        self.create_ask(ASK)
        repo = self.repos / "github.com" / "me" / "demo"
        repo.mkdir(parents=True)
        self.git(repo, "init", "--quiet", "--initial-branch=main")
        (repo / "a.txt").write_text("a\n", encoding="utf-8")
        self.git(repo, "add", "a.txt")
        self.git(repo, "commit", "--quiet", "-m", "a")
        self.git(repo, "worktree", "add", "--quiet", "-b", "feature", str(self.worktrees / "github.com" / "me" / "demo" / "feature"))
        self.base = f"http://{self.host}/"

    def drive(self, steps: list[dict]) -> dict:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump({"steps": steps}, handle)
        self.addCleanup(os.unlink, handle.name)
        done = subprocess.run(["node", str(HERE / "cdp.mjs"), os.environ.get("CHROMIUM", "chromium"), handle.name], capture_output=True, text=True, timeout=600, check=False)
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        return json.loads(done.stdout)

    def test_chromium_walks_every_screen_at_three_widths(self):
        steps = [{"width": width, "height": height, "url": f"{self.base}#{screen}", "wait": 900, "probe": PROBE, "shot": str(OUT / f"chromium-{width}-{screen.replace('/', '-')}.png")} for width, height in WIDTHS for screen in SCREENS]
        steps += [{"width": 1366, "height": 768, "url": f"{self.base}#{old}", "wait": 600, "probe": PROBE, "shot": None} for old in ("graph", "graph/chord", "tree")]
        steps.append({"width": 1366, "height": 768, "url": f"{self.base}#stream", "wait": 900, "probe": ACTIONS, "shot": None})
        data = self.drive(steps)
        self.assertEqual(data["errors"], [])
        probes = data["results"][: len(WIDTHS) * len(SCREENS)]
        for probe, step in zip(probes, steps, strict=False):
            with self.subTest(url=step["url"], width=step["width"]):
                self.assertNotIn("error", probe)
                self.assertEqual((probe["title"], probe["h1"]), ("(2) Agent Orchestrator", "Agent Orchestrator"))
                self.assertEqual(probe["header"], ["palette-open", "settings-open"])
                self.assertEqual((probe["tabs"], probe["subs"]), (["Stream", "Agents", "Artifacts"], ["Inbox", "Regeln"]))
                self.assertEqual(probe["badges"], {"tab-stream": None, "tab-inbox": "2", "tab-rules": None, "tab-agents": "1", "tab-artifacts": None})
                self.assertEqual(probe["banner"], "MAYDAY · Docs: disk fullaufheben")
                self.assertFalse(probe["rail"])
                self.assertEqual((probe["time"], probe["replay"]), ("24 h ▾", True))
                self.assertFalse(probe["wide"], "the page scrolls sideways")
        by_hash = {probe["hash"]: probe for probe in probes}
        stream = by_hash["#stream"]
        self.assertEqual([probe["chips"] for probe in probes if probe["hash"] == "#stream"], [["Für dich", "Funk", "Arbeit", "Transkripte"]] * len(WIDTHS))
        self.assertEqual((stream["menus"], stream["custom"]), (["Filter ▾"], True))
        self.assertEqual(by_hash["#stream/inbox"]["inbox"], 2)
        for tab in ("agents", "artifacts"):
            with self.subTest(tab=tab):
                self.assertEqual(by_hash[f"#{tab}/orbit"]["views"], ["Orbit", "Chord", "Swimlane", "Tree", "3D"])
        agents = by_hash["#agents/orbit"]
        self.assertEqual(agents["toolbar"], ["Funk an alle ▾", "Mayday aufheben", "Priorität", "Tag/Nacht ▾"])
        self.assertEqual(agents["toAll"], [["newsletter", True], ["broadcast", False], ["pan-pan", False], ["security", False], ["mayday", False]])
        redirects = data["results"][len(probes) : len(probes) + 3]
        self.assertEqual([probe["hash"] for probe in redirects], ["#agents/orbit", "#agents/chord", "#artifacts/tree"])
        actions = data["results"][-1]
        self.assertNotIn("error", actions)
        self.assertEqual(actions["keys"], ["#agents/chord", "#artifacts/tree", "#stream"])
        self.assertEqual(actions["ambience"], ["sky-look", "music-toggle", "leitstand", "notify"])
        self.assertEqual([name for name, _, _ in actions["speech"]], ["Post", "Call", "Newsletter", "Broadcast", "MAYDAY", "PAN-PAN", "SECURITE"])
        self.assertEqual([entry[1:] for entry in actions["speech"] if entry[0] == "MAYDAY"], [[True, True]])
        for tool in ("Funk an alle …", "Mayday aufheben", "Priorität …", "Abend", "Regeln …", "Einstellungen …", "Himmel ansehen", "Leitstand umschalten", "Benachrichtigungen aktivieren"):
            with self.subTest(tool=tool):
                self.assertTrue(any(tool in entry for entry in actions["palette"]), actions["palette"])
        self.assertEqual(actions["drawer"], [["post", True], ["call", False]])

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_renders_every_screen_at_three_widths(self):
        profile = Path(tempfile.mkdtemp(prefix="firefox-e2e-"))
        self.addCleanup(shutil.rmtree, profile, True)
        for width, height in WIDTHS:
            for screen in SCREENS:
                shot = OUT / f"firefox-{width}-{screen.replace('/', '-')}.png"
                shot.unlink(missing_ok=True)
                with self.subTest(width=width, screen=screen):
                    command = [os.environ.get("FIREFOX", "firefox"), "--headless", "--no-remote", "--profile", str(profile), "--window-size", f"{width},{height}", "--screenshot", str(shot), f"{self.base}#{screen}"]
                    subprocess.run(command, capture_output=True, timeout=120, check=False)
                    self.assertTrue(shot.is_file() and shot.stat().st_size > 1000, shot)


if __name__ == "__main__":
    unittest.main()
