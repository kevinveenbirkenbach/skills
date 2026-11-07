from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from collections.abc import Callable
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from hub_case import HubCase
from hub_support import ASK, iso, verifier
from test_hub_cleanup import DONE_TIP, FAKE_PKGMGR, host

OUT = Path(os.environ.get("E2E_OUT", "/tmp/orchestrator-phase4-shots"))
WIDTHS = ((1920, 1080), (1366, 768), (390, 844))
VIEWS = ("orbit", "chord", "swimlane", "tree", "3d")
SCREENS = ["stream", "stream/inbox", "stream/rules", *(f"{tab}/{view}" for tab in ("agents", "artifacts") for view in VIEWS)]
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
"""
PROBE = """(async () => {@HELPERS@
  await until(() => !document.querySelector("#main .space-note") || !text(document.querySelector("#main .space-note")).startsWith("Lade"), 8000);
  const badge = (button) => {
    const found = button.querySelector(".badge");
    return found && !found.hidden ? text(found) : null;
  };
  const icons = all("svg.bi").filter((svg) => !svg.closest(".sprite"));
  const banner = document.getElementById("mayday");
  return {
    hash: location.hash,
    title: document.title,
    h1: text(document.querySelector("h1")),
    header: all("header.top button").map((button) => button.id),
    tabs: all("#tabs > .tab-group > button").map(name),
    subs: all("#tabs .subtabs button").map(name),
    badges: Object.fromEntries(all("#tabs button").map((button) => [button.id, badge(button)])),
    banner: banner.hidden ? null : text(banner),
    rail: Boolean(document.getElementById("rail")),
    views: all('#main [aria-label="Ansicht"] button').map(name),
    layouts: all('#main [aria-label="Anordnung"] button').map(name),
    chips: all('#main [aria-label="Kategorien"] button').map(name),
    menus: all("#main details.menu > summary").map(name),
    time: text(document.querySelector("#time > summary")),
    replay: Boolean(document.querySelector("#time .replay input[type=range]")),
    custom: Boolean(document.querySelector('#main details.menu input[type="datetime-local"]')),
    toolbar: all('#main [role="toolbar"] > *').map((node) => name(node.tagName === "DETAILS" ? node.querySelector("summary") : node.querySelector("button") || node)),
    toAll: all("#to-all input[type=radio]").map((input) => [input.value, input.checked]),
    inbox: all("#main .inbox-list > li").length,
    icons: icons.length,
    unlabelled: icons.map((svg) => svg.parentElement).filter((owner) => !text(owner) && !(owner.getAttribute("title") && owner.getAttribute("aria-label"))).map((owner) => owner.outerHTML.slice(0, 160)),
    broken: all("svg.bi use").filter((use) => !document.getElementById(use.getAttribute("href").slice(1))).map((use) => use.getAttribute("href")),
    states: all("#main span.state").map(name),
    deletes: all('#main button[aria-label="Löschen"], #main button[aria-label="Alle gemergten löschen"]').map((button) => [name(button), button.disabled, button.title]),
    spawn: all("#main .spawn-tree li").map((item) => [item.dataset.kind, item.dataset.running || null]),
    marks: all("#main svg.chart .node").length,
    note: text(document.querySelector("#main .space-note")),
    canvas: Boolean(document.querySelector("#main .graph3d canvas")),
    wide: document.documentElement.scrollWidth > window.innerWidth + 1,
  };
})()""".replace("@HELPERS@", HELPERS)
ACTIONS = """(async () => {@HELPERS@
  const press = async (key) => {
    document.dispatchEvent(new KeyboardEvent("keydown", {key, bubbles: true}));
    await sleep(300);
    return location.hash;
  };
  const found = {keys: [await press("2"), await press("3"), await press("1")]};
  document.getElementById("settings-open").click();
  await sleep(300);
  found.ambience = all(".sheet-box form > section:first-child button").map((button) => button.id);
  found.speech = all('.sheet-box [aria-label="Klassen"] input').map((input) => [input.parentElement.textContent.trim(), input.checked, input.disabled]);
  found.settingsUnlabelled = all(".sheet-box svg.bi").map((svg) => svg.parentElement).filter((owner) => !text(owner) && !(owner.getAttribute("title") && owner.getAttribute("aria-label"))).length;
  document.querySelector(".sheet-head button").click();
  document.getElementById("palette-open").click();
  await sleep(300);
  found.palette = all(".palette-list li > span:first-child").map(text);
  document.dispatchEvent(new KeyboardEvent("keydown", {key: "Escape", bubbles: true}));
  await sleep(200);
  document.querySelector('#main [aria-label="Kategorien"] button:nth-child(2)').click();
  await sleep(900);
  document.querySelector('#main button.linkish[title$="öffnen"]').click();
  await sleep(500);
  found.drawer = all("#drawer input[type=radio]").map((input) => [input.value, input.checked]);
  found.drawerUnlabelled = all("#drawer svg.bi").map((svg) => svg.parentElement).filter((owner) => !text(owner) && !(owner.getAttribute("title") && owner.getAttribute("aria-label"))).length;
  return found;
})()""".replace("@HELPERS@", HELPERS)
PICK_3D = """(async () => {@HELPERS@
  const list = await until(() => document.querySelector("#main .space-list"), 8000);
  if (!list) {
    return {error: text(document.querySelector("#main .graph"))};
  }
  list.open = true;
  const chip = all("#main .space-list [data-node]").find((node) => node.dataset.node.startsWith("@PREFIX@"));
  if (!chip) {
    return {error: all("#main .space-list [data-node]").map((node) => node.dataset.node)};
  }
  chip.click();
  await sleep(600);
  return {panel: text(document.querySelector("#main aside .panel-title")), label: chip.textContent};
})()""".replace("@HELPERS@", HELPERS)
CALL = """(async () => {@HELPERS@
  document.querySelector('#main [aria-label="Kategorien"] button[aria-label="Funk"]').click();
  const someone = await until(() => document.querySelector('#main button.linkish[title$="öffnen"]'), 8000);
  someone.click();
  await sleep(500);
  document.querySelector('#drawer input[type=radio][value="call"]').click();
  const field = document.querySelector("#drawer textarea");
  field.value = "E2E call ping";
  field.dispatchEvent(new Event("input", {bubbles: true}));
  document.querySelector('#drawer button[type="submit"]').click();
  const entry = await until(() => all("#main .entry").find((row) => row.textContent.includes("Gelesen") && row.textContent.includes("E2E call ping")), 20000);
  return {to: text(someone), receipt: entry ? text(entry) : null, sent: all("#main .entry").filter((row) => row.textContent.includes("E2E call ping")).length};
})()""".replace("@HELPERS@", HELPERS)
OPEN_DELETE = """(async () => {@HELPERS@
  const card = await until(() => all("#main details.repo").find((details) => details.textContent.includes("github.com/me/demo")), 8000);
  if (!card) {
    return {error: text(document.getElementById("main"))};
  }
  card.open = true;
  await sleep(300);
  const every = document.querySelector('#main button[aria-label="Alle gemergten löschen"]');
  const buttons = all('button[aria-label="Löschen"]', card);
  const states = all("span.state", card).map(name);
  buttons.find((button) => !button.disabled).click();
  await sleep(500);
  return {states, every: [every.disabled, every.title], buttons: buttons.map((button) => [button.disabled, button.title]), title: text(document.querySelector(".sheet-head .panel-title")), dry: all('.sheet-box [aria-label="Trockenlauf"] pre').map(text)};
})()""".replace("@HELPERS@", HELPERS)
CONFIRM = """(async () => {@HELPERS@
  all(".sheet-box button").find((button) => name(button) === "Löschen").click();
  const done = await until(() => document.querySelector(".sheet-box [data-result]"), 30000);
  const job = document.querySelector(".sheet-box [data-cleanup]");
  return {job: job ? job.dataset.cleanup : null, result: done ? done.dataset.result : null, text: text(done), toasts: all("#toasts .toast").map(text)};
})()""".replace("@HELPERS@", HELPERS)
AFTER = """(async () => {@HELPERS@
  document.querySelector(".sheet-head button").click();
  const past = await until(() => all("#main details.repo").find((details) => details.textContent.includes("Zuletzt gelöscht")), 15000);
  return {past: past ? [past.querySelector("[data-result]").dataset.result, name(past.querySelector("span.state"))] : null, branches: all("#main details.repo").filter((details) => details !== past).flatMap((details) => all(".branch-name strong", details)).map(text)};
})()""".replace("@HELPERS@", HELPERS)


def labelled(probe: dict) -> dict:
    return {key: probe[key] for key in ("unlabelled", "broken")}


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
        self.subagents(now)
        self.request("feat: orchestrator", "")
        self.create_ask(ASK)
        self.root = self.write_tree()
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

    def drive(self, steps: list[dict], authenticator: dict | None, driver: str = "cdp.mjs", binary: str = os.environ.get("CHROMIUM", "chromium")) -> dict:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump({"steps": steps, "authenticator": authenticator}, handle)
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

    def test_chromium_walks_every_screen_at_three_widths(self):
        steps = [{"width": width, "height": height, "url": f"{self.base}#{screen}", "wait": 900, "probe": PROBE, "shot": self.shot(f"{width}-{screen.replace('/', '-')}")} for width, height in WIDTHS for screen in SCREENS]
        steps += [{"width": 1366, "height": 768, "url": f"{self.base}#{old}", "wait": 600, "probe": PROBE, "shot": None} for old in ("graph", "graph/chord", "tree")]
        steps.append({"width": 1366, "height": 768, "url": f"{self.base}#stream", "wait": 900, "probe": ACTIONS, "shot": None})
        steps.append({"width": 1366, "height": 768, "url": f"{self.base}#artifacts/3d", "wait": 900, "probe": PICK_3D.replace("@PREFIX@", "branch:"), "shot": self.shot("1366-artifacts-3d-picked")})
        steps.append({"width": 1366, "height": 768, "url": f"{self.base}#agents/3d", "wait": 900, "probe": PICK_3D.replace("@PREFIX@", "s2"), "shot": self.shot("1366-agents-3d-picked")})
        steps.append({"width": 1366, "height": 768, "url": f"{self.base}#artifacts/3d", "wait": 900, "probe": PROBE, "shot": self.shot("1366-artifacts-3d-reduced-motion"), "media": [{"name": "prefers-reduced-motion", "value": "reduce"}]})
        data = self.drive(steps, None)
        (OUT / "chromium-walk.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        probes = data["results"][: len(WIDTHS) * len(SCREENS)]
        for probe, step in zip(probes, steps, strict=False):
            with self.subTest(url=step["url"], width=step["width"]):
                self.assertNotIn("error", probe)
                self.assertEqual((probe["title"], probe["h1"]), ("(2) Agent Orchestrator", "Agent Orchestrator"))
                self.assertEqual(probe["header"], ["palette-open", "settings-open"])
                self.assertEqual((probe["tabs"], probe["subs"]), (["Stream", "Agents", "Artifacts"], ["Inbox", "Regeln"]))
                self.assertEqual(probe["badges"], {"tab-stream": None, "tab-inbox": "2", "tab-rules": None, "tab-agents": "1", "tab-artifacts": None})
                self.assertEqual(probe["banner"], "MAYDAY · Docs: disk full")
                self.assertFalse(probe["rail"])
                self.assertEqual((probe["time"], probe["replay"]), ("24 h ▾", True))
                self.assertGreater(probe["icons"], 8)
                self.assertEqual(labelled(probe), {"unlabelled": [], "broken": []})
                self.assertFalse(probe["wide"], "the page scrolls sideways")
        by_hash = {probe["hash"]: probe for probe in probes}
        stream = by_hash["#stream"]
        self.assertEqual([probe["chips"] for probe in probes if probe["hash"] == "#stream"], [["Für dich", "Funk", "Arbeit", "Transkripte"]] * len(WIDTHS))
        self.assertEqual((stream["menus"], stream["custom"]), (["Filter"], True))
        self.assertEqual(by_hash["#stream/inbox"]["inbox"], 2)
        for tab in ("agents", "artifacts"):
            with self.subTest(tab=tab):
                self.assertEqual(by_hash[f"#{tab}/orbit"]["views"], ["Orbit", "Chord", "Swimlane", "Tree", "3D"])
                self.assertEqual(by_hash[f"#{tab}/3d"]["layouts"], ["Kraft", "Zeit", "Spawn-Tiefe"])
                self.assertTrue(by_hash[f"#{tab}/3d"]["canvas"], by_hash[f"#{tab}/3d"]["note"])
                self.assertRegex(by_hash[f"#{tab}/3d"]["note"], r"^\d+ Knoten · \d+ Kanten · Kraft$")
        agents = by_hash["#agents/orbit"]
        self.assertEqual(agents["toolbar"], ["Funk an alle", "Mayday aufheben", "Priorität", "Tag/Nacht"])
        self.assertEqual(agents["toAll"], [["newsletter", True], ["broadcast", False], ["pan-pan", False], ["security", False], ["mayday", False]])
        self.assertEqual(by_hash["#agents/tree"]["spawn"][0], ["operator", None])
        self.assertIn(["twig", "true"], by_hash["#agents/tree"]["spawn"])
        self.assertIn(["twig", "false"], by_hash["#agents/tree"]["spawn"])
        artifacts = by_hash["#artifacts/tree"]
        self.assertEqual(artifacts["deletes"], [["Alle gemergten löschen", True, "Alle gemergten löschen gesperrt: Secret Service locked"], ["Löschen", True, "Löschen gesperrt: Secret Service locked"]])
        for state in ("gemergt durch #12 in main", "Upstream weg", "geschützt", "1 Commits ungepusht", "sauber", "nicht committet: 0 gestaged, 0 geändert, 1 neu", "gc überspringt: ignored files beyond known caches: notes.txt"):
            with self.subTest(state=state):
                self.assertIn(state, artifacts["states"])
        for view in ("orbit", "chord"):
            with self.subTest(view=view):
                self.assertGreaterEqual(by_hash[f"#artifacts/{view}"]["marks"], 4)
        extra = data["results"][len(probes) :]
        self.assertEqual([probe["hash"] for probe in extra[:3]], ["#agents/orbit", "#agents/chord", "#artifacts/tree"])
        actions = extra[3]
        self.assertNotIn("error", actions)
        self.assertEqual(actions["keys"], ["#agents/chord", "#artifacts/tree", "#stream"])
        self.assertEqual(actions["ambience"], ["sky-look", "music-toggle", "leitstand", "notify"])
        self.assertEqual((actions["settingsUnlabelled"], actions["drawerUnlabelled"]), (0, 0))
        self.assertEqual([name for name, _, _ in actions["speech"]], ["Post", "Call", "Newsletter", "Broadcast", "MAYDAY", "PAN-PAN", "SECURITE"])
        self.assertEqual([entry[1:] for entry in actions["speech"] if entry[0] == "MAYDAY"], [[True, True]])
        for tool in ("Funk an alle …", "Mayday aufheben", "Priorität …", "Abend", "Regeln …", "Einstellungen …", "Himmel ansehen", "Leitstand umschalten", "Benachrichtigungen aktivieren"):
            with self.subTest(tool=tool):
                self.assertTrue(any(tool in entry for entry in actions["palette"]), actions["palette"])
        self.assertEqual(actions["drawer"], [["post", True], ["call", False]])
        artifact_pick, agent_pick, calm = extra[4:]
        self.assertEqual(artifact_pick["panel"], artifact_pick["label"])
        self.assertEqual(agent_pick["panel"], agent_pick["label"])
        self.assertRegex(calm["note"], r"Kraft · ohne Bewegung \(prefers-reduced-motion\)$")

    def test_chromium_sends_a_call_from_the_agent_panel_and_shows_its_receipt(self):
        handled = []

        def answer() -> None:
            for script, args in self.scripts.calls[len(handled) :]:
                handled.append(script)
                if script.endswith("radio.py") and args[:2] == ["send", "call"]:
                    to, text, now = args[args.index("--to") + 1], args[-1], time.time()
                    rows = [{"ts": now, "from": "Operator", "to": [to], "text": text, "class": "call", "v": 2}, {"ts": now + 0.5, "from": to, "to": ["Operator"], "text": text, "class": "receipt", "v": 2, "call": now}]
                    with (self.council / "news.jsonl").open("a", encoding="utf-8") as handle:
                        handle.write(self.jsonl(rows))

        self.beside(answer)
        data = self.drive([{"width": 1366, "height": 768, "url": f"{self.base}#stream", "wait": 900, "probe": CALL, "shot": self.shot("1366-call-receipt")}], None)
        self.assertEqual(data["errors"], [])
        result = data["results"][0]
        self.assertNotIn("error", result)
        self.assertIsNotNone(result["receipt"], result)
        self.assertIn("Gelesen", result["receipt"])

    def test_chromium_deletes_a_merged_branch_after_dry_run_and_signature(self):
        tree = json.loads(self.tree_file.read_text(encoding="utf-8"))
        tree["delete_ready"], tree["delete_reason"] = True, ""
        self.tree_file.write_text(json.dumps(tree), encoding="utf-8")
        demo = f"{self.root}/repos/github.com/me/demo"
        Path(demo).mkdir(parents=True)
        fake = self.outside / "bin" / "pkgmgr"
        fake.parent.mkdir()
        fake.write_text(FAKE_PKGMGR.format(python=sys.executable), encoding="utf-8")
        fake.chmod(0o755)
        worktree = f"{self.root}/worktrees/github.com/me/demo/feature-done"
        (fake.parent / "plan.json").write_text(json.dumps([{"branch": "feature/done", "worktree": worktree, "local_sha": DONE_TIP, "head": DONE_TIP, "state": "merged-clean", "skip": None}]), encoding="utf-8")
        following = json.loads(json.dumps(tree))
        following["repos"][0]["items"] = [item for item in following["repos"][0]["items"] if item["branch"] != "feature/done"]
        (fake.parent / "next-tree.json").write_text(json.dumps(following), encoding="utf-8")
        signer = self.pin()
        trust = verifier.Trust(approvers=self.approvers, replay=self.replay / "cleanup.json", origin=self.origin)
        runner = host.Cleanup(trust, self.tree_file, fake)
        jobs, results = self.cleanup / "jobs", self.cleanup / "results"
        self.beside(lambda: any(jobs.iterdir()) and host.cycle(jobs, results, runner))
        private = "".join(line for line in signer.pem.read_text(encoding="utf-8").splitlines() if not line.startswith("-----"))
        authenticator = {"credentialId": base64.b64encode(signer.raw_id).decode(), "privateKey": private, "rpId": "localhost"}
        local = f"http://localhost:{self.port}/"
        steps = [
            {"width": 1366, "height": 768, "url": f"{local}#artifacts/tree", "wait": 1200, "probe": OPEN_DELETE, "shot": self.shot("1366-delete-dry-run")},
            {"width": 1366, "height": 768, "url": None, "wait": 0, "probe": CONFIRM, "shot": self.shot("1366-delete-result")},
            {"width": 1366, "height": 768, "url": None, "wait": 0, "probe": AFTER, "shot": self.shot("1366-delete-tree-after")},
        ]
        data = self.drive(steps, authenticator)
        (OUT / "chromium-delete.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        opened, confirmed, after = data["results"]
        self.assertNotIn("error", opened)
        self.assertEqual(opened["every"], [False, "Alle gemergten löschen: 1 Branches nach Trockenlauf und Signatur"])
        self.assertEqual(opened["buttons"], [[False, "Löschen: feature/done lokal entfernen, nach Trockenlauf und Signatur"]])
        self.assertEqual(opened["title"], "feature/done löschen")
        self.assertEqual(len(opened["dry"]), 1)
        self.assertTrue(opened["dry"][0].startswith("feature/done @ 5b1e6fd3a7c0: merged-clean, gemergt durch #12"), opened["dry"])
        self.assertIn("bleibt: remote-branch (nur lokal)", opened["dry"][0])
        self.assertEqual((confirmed["result"], confirmed["text"]), ("done", "feature/donegelöscht"), confirmed)
        self.assertEqual(confirmed["toasts"], ["Löschen: erledigtfeature/done: gelöscht"])
        self.assertEqual(after["past"], ["done", "gelöscht"])
        self.assertNotIn("feature/done", after["branches"])
        written = [json.loads(path.read_text(encoding="utf-8")) for path in results.glob("*.json")]
        self.assertEqual([[(item["branch"], item["status"]) for item in result["items"]] for result in written], [[("feature/done", "done")]])
        calls = [json.loads(line)["argv"] for line in (fake.parent / "calls.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(calls, [
            ["branch", "cleanup", "--json", "--local", "--branch", "feature/done"],
            ["branch", "cleanup", "--apply", "--json", "--local", "--branch", "feature/done"],
            ["branch", "tree", "--format", "json", "--output", str(self.tree_file)],
        ])

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_walks_every_screen_at_three_widths(self):
        shots = [(width, height, screen, OUT / f"firefox-{width}-{screen.replace('/', '-')}.png") for width, height in WIDTHS for screen in SCREENS]
        for *_, shot in shots:
            shot.unlink(missing_ok=True)
        steps = [{"width": width, "height": height, "url": f"{self.base}#{screen}", "wait": 900, "probe": PROBE, "shot": str(shot)} for width, height, screen, shot in shots]
        data = self.drive(steps, None, "bidi.mjs", os.environ.get("FIREFOX", "firefox"))
        (OUT / "firefox-walk.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        blocked = [error for error in data["errors"] if error.startswith("Content-Security-Policy")]
        self.assertEqual([error for error in data["errors"] if error not in blocked], [])
        # 3d-force-graph injects its own <style>, which the unchanged CSP blocks; the page carries those rules itself.
        self.assertEqual([error for error in blocked if "(style-src-elem)" not in error and "/favicon.ico" not in error], [])
        for probe, (width, _, screen, shot) in zip(data["results"], shots, strict=True):
            with self.subTest(width=width, screen=screen):
                self.assertNotIn("error", probe)
                self.assertEqual(probe["hash"], f"#{screen}")
                self.assertEqual((probe["tabs"], probe["subs"]), (["Stream", "Agents", "Artifacts"], ["Inbox", "Regeln"]))
                self.assertEqual(labelled(probe), {"unlabelled": [], "broken": []})
                self.assertFalse(probe["wide"], "the page scrolls sideways")
                self.assertTrue(shot.is_file() and shot.stat().st_size > 1000, shot)
                if screen.endswith("/3d"):
                    self.assertTrue(probe["canvas"], probe["note"])


if __name__ == "__main__":
    unittest.main()
