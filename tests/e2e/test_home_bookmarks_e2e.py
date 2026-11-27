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

import hub_e2e_kit as base
import test_home_dashboard_e2e as dash
import test_resources_view_e2e as res
import test_workbench_w4_e2e as w4
from hub_case import HubCase
from hub_support import (
    CORE_WORKTREE,
    LONG_REPO,
    LONG_TASK,
    LONG_VOLUME,
    LONG_WORKTREE,
    MERGED_BRANCH,
    iso,
    long_repos,
    long_task,
)

OUT = Path(os.environ.get("E2E_OUT", "/tmp/bookmarks-shots"))
CUE = "e2e-bookmarks-vanish"
GHOST = "Ghost"
KEPT = "feature/kept"
HARDWARE = ["disk:/", "disk:/boot/efi", res.CPU, "host:RAM", "host:Swap", res.UTIL, "vram:0000_3a_01_3a_00.0"]
WALKED = ["resources", "artifacts/tree", "agents/hierarchy", "tasks/operator"]
LONG_NAME = "/".join(Path(LONG_REPO).parts[-3:])
LONG_ROWS = ("repo", "worktree", "core", "leaf")
READ = res.READ.replace("const stored = async", "const storedResources = async").replace("await stored()", "await storedResources()")
KIT = """
  const pinnable = (selector) => all(selector).map((owner) => Boolean(Panels.targetOf(owner)));
  const panel = (kind) => `#main [data-panel="resources-${kind}"]`;
  const lineIds = (root) => [...new Set(all("path.res-line", root).map((path) => path.dataset.id))];
  const tileOf = (kind) => all("#main .home-tile").find((node) => node.dataset.pin.startsWith(`metric:${kind}/`)) || null;
  const pinOf = (kind) => (ViewStore.get("home.pins") || []).find((pin) => pin.kind === "metric" && pin.id.startsWith(`${kind}/`)) || null;
  const kept = () => all("#main .branch-row[data-item]").find((row) => row.dataset.item.endsWith("\\u0000@KEPT@")) || null;
  const settled = () => until(() => !all("#main .home-tile .empty h2").some((title) => text(title).endsWith("…")), 8000);
  const longRows = {
    repo: () => all("#main details.repo[data-item]").find((node) => text(node.querySelector("summary")).includes("@LONG_NAME@")) || null,
    worktree: () => all("#main .wt[data-item]").find((node) => text(node.querySelector(".wt-head > code")) === "@LONG_WORKTREE@") || null,
    core: () => all("#main .wt[data-item]").find((node) => text(node.querySelector(".wt-head > code")) === "@CORE_WORKTREE@") || null,
    leaf: () => all("#main li.leaf[data-item]").find((node) => text(node.querySelector("code")) === "@LONG_VOLUME@") || null,
  };
  const pinKey = (node) => `artifact:${Panels.token(node.dataset.item.slice(node.dataset.item.indexOf(":") + 1))}`;
  const timeOverlaps = (root) => {
    const boxes = all("text.axis", root).filter((node) => !["left", "right"].includes(node.dataset.axis)).map((node) => node.getBoundingClientRect());
    return boxes.filter((box, index) => boxes.slice(index + 1).some((other) => Math.min(box.right, other.right) - Math.max(box.left, other.left) > 0.5 && Math.min(box.bottom, other.bottom) - Math.max(box.top, other.top) > 0.5)).length;
  };
"""
CLEAR = """(async () => {
  sessionStorage.clear();
  await Promise.all([ViewStore.update("home.pins", () => []), ViewStore.update("resources.hidden", () => []), ViewStore.update("resources.combinedHidden", () => []),
    ViewStore.update("resources.panels", () => ["hardware", "tokens", "accounts"]), ViewStore.set("resources.tokens", "interval")]);
  return true;
})()"""
LOADED = """(async () => {@HELPERS@@READ@
  await screenShown(8000);
  const drawn = Boolean(await until(() => charts().length === 2 && chip("@CPU@"), 15000));
  return {drawn, charts: charts()};
})()"""
FOUND = """(async () => {@HELPERS@@HOME@@KIT@
  const found = {};
  await go("resources");
  found.charts = pinnable('#main section.res-panel[data-panel^="resources-"]');
  found.stars = all(".star, .star-row").length;
  await go("artifacts/tree");
  await until(() => kept(), 8000);
  found.tree = pinnable('#main [data-panel="artifacts/tree"]');
  found.rows = Object.fromEntries(["repo", "branch", "wt"].map((kind) => [kind, pinnable(`#main [data-item^="artifact:${kind}:"]`)]));
  await until(() => Object.values(longRows).every((find) => find()), 8000);
  found.long = Object.fromEntries(Object.entries(longRows).map(([key, find]) => [key, find() ? find().dataset.item.length : null]));
  found.disabled = all('#main [data-item^="artifact:"]').filter((node) => !Panels.targetOf(node) || Panels.targetOf(node).refused).map((node) => node.dataset.item.slice(0, 80));
  found.deletes = all('#main button[aria-label="Delete"]').length;
  await go("agents/hierarchy");
  found.order = pinnable('#main [data-panel="agents/order"]');
  await go("tasks/operator");
  found.operator = pinnable('#main [data-panel="tasks/operator"]');
  return found;
})()"""
METRIC = """(async () => {@HELPERS@@HOME@@READ@@KIT@
  await go("resources");
  if (!(await until(() => charts().length === 2 && chip("@CPU@") && lines().length === @COUNT@, 15000))) {
    return {error: text(document.getElementById("main")), charts: charts()};
  }
  const axisOverlaps = timeOverlaps(document.querySelector("#main .res-panels"));
  const others = @HARDWARE@.filter((id) => id !== "@CPU@");
  for (const id of others) {
    chip(id).click();
    await sleep(120);
  }
  const cpuOnly = Boolean(await until(() => lineIds(document.querySelector(panel("hardware"))).join() === "@CPU@", 5000));
  const hardware = await press(panel("hardware"));
  const cpuTitle = (await pinState(panel("hardware")))[1];
  const tokens = await press(panel("tokens"));
  for (const id of others) {
    chip(id).click();
    await sleep(120);
  }
  const back = Boolean(await until(() => lineIds(document.querySelector(panel("hardware"))).length === @COUNT@, 5000));
  await sleep(200);
  const allState = await pinState(panel("hardware"));
  await pickPanel("combined", true);
  await pickPanel("hardware", false);
  await pickPanel("tokens", false);
  const combinedOn = Boolean(await until(() => charts().join() === "combined" && burn().length === 2, 5000));
  const combined = await press(panel("combined"));
  return {cpuOnly, hardware, cpuTitle, tokens, back, allState, combinedOn, combined, axisOverlaps, stored: (ViewStore.get("home.pins") || []).map((pin) => [pin.kind, pin.id, pin.view || null])};
})()"""
COMBINED_OFF = """(async () => {@HELPERS@@HOME@@READ@@KIT@
  await go("resources");
  await until(() => charts().join() === "combined", 8000);
  await pickPanel("hardware", true);
  await pickPanel("tokens", true);
  await pickPanel("combined", false);
  const off = Boolean(await until(() => charts().length === 2 && lines().length === @COUNT@, 8000));
  await sleep(300);
  return {off, hardware: await pinState(panel("hardware"))};
})()"""
HOME_METRICS = """(async () => {@HELPERS@@HOME@@KIT@
  await go("home");
  await until(() => ["hardware", "tokens", "combined"].every((kind) => tileOf(kind) && tileOf(kind).querySelector("svg.res-chart")), 15000);
  await sleep(300);
  const read = (kind) => {
    const found = tileOf(kind);
    return found ? {
      title: text(found.querySelector(".home-title")), lines: lineIds(found), legend: all(".legend-chip", found).map((node) => node.dataset.series),
      chart: (found.querySelector("svg.res-chart") || {dataset: {}}).dataset.chart || null, right: all('text[data-axis="right"]', found).length,
      burn: all("path.res-burn", found).length, bars: [...new Set(all("rect.res-bar", found).map((rect) => rect.dataset.agent))].sort(),
      gone: found.classList.contains("gone"),
    } : null;
  };
  const overlaps = Object.fromEntries(["hardware", "tokens", "combined"].map((kind) => [kind, tileOf(kind) ? timeOverlaps(tileOf(kind)) : null]));
  const sized = (kind, step) => ViewStore.update("home.pins", (pins) => pins.map((pin) => (pin.kind === "metric" && pin.id.startsWith(`${kind}/`) ? {...pin, h: pin.h + step} : pin)));
  await sized("combined", -1);
  await sleep(600);
  const body = tileOf("combined").querySelector(".home-body");
  const scroll = {scrollable: body.scrollHeight > body.clientHeight + 10};
  if (scroll.scrollable) {
    body.scrollTop = body.scrollHeight;
    scroll.before = body.scrollTop;
    await sized("hardware", 1);
    await sleep(400);
    await sized("hardware", -1);
    await sleep(400);
    scroll.after = body.scrollTop;
  }
  await sized("combined", 1);
  await sleep(300);
  return {tiles: tiles(), hardware: read("hardware"), tokens: read("tokens"), combined: read("combined"), errors: all("#main .home-error").map(text), stored: pinOf("hardware"), overlaps, scroll};
})()"""
PM = """(async () => {@HELPERS@@HOME@@KIT@
  await go("artifacts/tree");
  const row = await until(() => kept(), 8000);
  row.closest("details").open = true;
  const tree = await press('#main [data-panel="artifacts/tree"]');
  const branch = row ? await pinOwner(kept() || row) : null;
  await go("agents/hierarchy");
  const order = await press('#main [data-panel="agents/order"]');
  await go("tasks/operator");
  const operator = await press('#main [data-panel="tasks/operator"]');
  await go("agents/orbit");
  const node = await until(() => all("#main svg .node[data-pick]").find((found) => (found.getAttribute("aria-label") || "").startsWith("@GHOST@,")), 8000);
  let agent = null;
  if (node) {
    node.dispatchEvent(new MouseEvent("click", {bubbles: true}));
    await until(() => document.querySelector('#popup[open] [data-item^="agent:"]'), 5000);
    agent = await press('#popup[open] [data-item^="agent:"]');
    document.getElementById("popup").close();
  }
  await go("home");
  await settled();
  await sleep(500);
  const keys = stored();
  const pick = (kind) => keys.find((key) => key.startsWith(`${kind}:`)) || null;
  const shown = (key) => {
    const found = key ? tile(key) : null;
    return found ? {gone: found.classList.contains("gone"), title: text(found.querySelector(".home-title"))} : null;
  };
  return {
    pressed: {tree, branch, order, operator, agent}, keys,
    tree: [shown("panel:artifacts/tree"), all('#main .home-tile[data-pin="panel:artifacts/tree"] details.repo').length],
    order: [shown("panel:agents/order"), all('#main .home-tile[data-pin="panel:agents/order"] .home-order li').map((item) => item.dataset.name)],
    operator: [shown("panel:tasks/operator"), all('#main .home-tile[data-pin="panel:tasks/operator"] .home-inbox > li').length],
    artifact: [shown(pick("artifact")), text(tile(pick("artifact")) && tile(pick("artifact")).querySelector(".home-body h2.panel-title"))],
    agent: [shown(pick("agent")), Boolean(tile(pick("agent")) && tile(pick("agent")).querySelector(".home-agent"))],
    errors: all("#main .home-error").map(text),
  };
})()"""
LONG = """(async () => {@HELPERS@@HOME@@KIT@
  await go("artifacts/tree");
  await until(() => Object.values(longRows).every((find) => find()), 8000);
  const pressed = {};
  const keys = {};
  for (const [key, find] of Object.entries(longRows)) {
    keys[key] = pinKey(find());
    const before = await menuPinOf(find());
    pressed[key] = before ? [before[1].startsWith("Pin to Home: Artifact "), await pinOwner(find())] : null;
  }
  await go("home");
  await settled();
  await until(() => Object.values(keys).every((key) => tile(key) && tile(key).querySelector(".home-popup")), 8000);
  await sleep(300);
  const shown = Object.fromEntries(Object.entries(keys).map(([key, pin]) => {
    const found = tile(pin);
    return [key, found ? {gone: found.classList.contains("gone"), title: text(found.querySelector(".home-title")), label: text(found.querySelector(".home-body h2.panel-title")), body: text(found.querySelector(".home-body"))} : null];
  }));
  const treeTile = tile("panel:artifacts/tree");
  const body = treeTile ? treeTile.querySelector(".home-body") : null;
  const scroll = {deletes: treeTile ? all('button[aria-label="Delete"]', treeTile).length : null, scrollable: body ? body.scrollHeight > body.clientHeight + 40 : null};
  if (scroll.scrollable) {
    body.scrollTop = 40;
    scroll.before = body.scrollTop;
    const order = (step) => ViewStore.update("home.pins", (pins) => pins.map((pin) => (pin.kind === "panel" && pin.id === "agents/order" ? {...pin, h: pin.h + step} : pin)));
    await order(1);
    await sleep(400);
    await order(-1);
    await sleep(400);
    scroll.after = body.isConnected ? body.scrollTop : null;
  }
  return {pressed, keys, stored: stored(), shown, scroll, errors: all("#main .home-error").map(text)};
})()"""
RELOADED = """(async () => {@HELPERS@@HOME@@KIT@
  await screenShown(8000);
  await until(() => tileOf("hardware") && tileOf("hardware").querySelector("svg.res-chart"), 15000);
  await sleep(300);
  return {hash: location.hash, lines: lineIds(tileOf("hardware")), title: text(tileOf("hardware").querySelector(".home-title")), stored: pinOf("hardware")};
})()"""
GONE = """(async () => {@HELPERS@@HOME@@KIT@
  await go("home");
  const keys = stored();
  const agentKey = keys.find((key) => key.startsWith("agent:"));
  const artifactKeys = keys.filter((key) => key.startsWith("artifact:"));
  const before = [agentKey, ...artifactKeys].map((key) => tile(key).classList.contains("gone"));
  await fetch("/api/tts", {method: "POST", headers: {"X-Kvb-Orchestrator": "1", "Content-Type": "application/json"}, body: JSON.stringify({text: "@CUE@", voice: ""}), cache: "no-store"});
  const started = Date.now();
  const vanished = await until(() => [agentKey, ...artifactKeys].every((key) => tile(key).classList.contains("gone")), 50000);
  const seconds = Math.round((Date.now() - started) / 1000);
  const words = (key) => (tile(key) ? [text(tile(key).querySelector(".home-gone-word")), name(tile(key).querySelector(".home-gone-unpin"))] : null);
  tile(artifactKeys[0]).scrollIntoView({block: "start"});
  await sleep(300);
  return {before, vanished: Boolean(vanished), seconds, agent: words(agentKey), artifacts: artifactKeys.map(words), agentKey, artifactKeys};
})()"""
UNPIN = """(async () => {@HELPERS@@HOME@@KIT@
  await go("home");
  const keys = stored();
  const metric = keys.find((key) => key.startsWith("metric:hardware/"));
  const artifacts = keys.filter((key) => key.startsWith("artifact:"));
  tile(metric).querySelector(".home-unpin").click();
  await sleep(300);
  for (const key of artifacts) {
    const gone = tile(key) ? tile(key).querySelector(".home-gone-unpin") : null;
    if (gone) {
      gone.click();
      await sleep(300);
    }
  }
  return {metric, artifacts, tiles: tiles(), stored: stored()};
})()"""
UNPIN_PLAIN = """(async () => {@HELPERS@@HOME@@KIT@
  await go("home");
  const metric = stored().find((key) => key.startsWith("metric:hardware/"));
  tile(metric).querySelector(".home-unpin").click();
  await sleep(300);
  return {metric, artifacts: [], tiles: tiles(), stored: stored()};
})()"""


def probe(template: str, screens: list[str] | None = None) -> str:
    names = {
        "@HELPERS@": base.HELPERS, "@HOME@": dash.HOME, "@READ@": READ, "@KIT@": KIT, "@KEPT@": KEPT, "@GHOST@": GHOST, "@CUE@": CUE, "@CPU@": res.CPU,
        "@HARDWARE@": json.dumps(HARDWARE), "@COUNT@": str(len(HARDWARE)), "@SCREENS@": json.dumps(screens or WALKED),
        "@LONG_NAME@": LONG_NAME, "@LONG_WORKTREE@": LONG_WORKTREE, "@CORE_WORKTREE@": CORE_WORKTREE, "@LONG_VOLUME@": LONG_VOLUME,
    }
    for key, value in names.items():
        template = template.replace(key, value)
    return template


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestHomeBookmarks(HubCase):
    seed = base.OrchestratorE2ECase.seed
    subagents = base.OrchestratorE2ECase.subagents
    drive = base.OrchestratorE2ECase.drive
    sample = w4.TestWorkbenchResources.sample

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        self.seed()
        now = int(time.time())
        self.start = now - now % 60 - w4.ROWS * 60
        hour = self.start - self.start % 3600
        tokens = [{"t": hour + step * 3600, "agent": "Skills", "model": "claude-opus-5-5", "input": 1000 * (step + 1), "output": 500, "cache_read": 20000, "cache_write": 1000} for step in range(7)]
        tokens += [{"t": hour + step * 3600, "agent": "Stage", "model": "claude-haiku-4-5", "input": 200, "output": 100, "cache_read": 3000, "cache_write": 0} for step in range(0, 7, 2)]
        folder = self.kept / "resources"
        folder.mkdir()
        (folder / "samples.jsonl").write_text(self.jsonl([self.sample(index) for index in range(w4.ROWS)]), encoding="utf-8")
        (folder / "tokens.jsonl").write_text(self.jsonl([row for row in tokens if row["t"] <= now]), encoding="utf-8")
        register = self.council / "rasci.json"
        rows = json.loads(register.read_text(encoding="utf-8"))
        rows["work/ghost"] = {"title": "Ghost line", "status": "running", "worker": GHOST, "start": iso(now - 1800), "roles": {GHOST: "RA"}}
        rows[LONG_TASK] = long_task(now)
        register.write_text(json.dumps(rows), encoding="utf-8")
        scan = json.loads(self.tree_file.read_text(encoding="utf-8"))
        scan["repos"] += long_repos()
        self.tree_file.write_text(json.dumps(scan), encoding="utf-8")
        self.write_local_plan(scan, {MERGED_BRANCH: {"skip": None, "actions": ["local-branch"]}})

    def vanish(self) -> None:
        register = self.council / "rasci.json"
        rows = json.loads(register.read_text(encoding="utf-8"))
        rows.pop("work/ghost", None)
        rows.pop(LONG_TASK, None)
        register.write_text(json.dumps(rows), encoding="utf-8")
        scan = json.loads(self.tree_file.read_text(encoding="utf-8"))
        long = {repo["path"] for repo in long_repos()}
        scan["repos"] = [repo for repo in scan["repos"] if repo["path"] not in long]
        for repo in scan["repos"]:
            repo["items"] = [item for item in repo["items"] if item.get("branch") != KEPT]
        self.tree_file.write_text(json.dumps(scan), encoding="utf-8")

    def cue(self) -> None:
        spoken = base.tone(1, 8000)

        def synthesize(body: bytes, admit: Callable[[str], None]) -> bytes:
            if json.loads(body)["text"] == CUE:
                self.vanish()
            return spoken

        patch = mock.patch.object(self.httpd.hub.speech, "synthesize", synthesize)
        patch.start()
        self.addCleanup(patch.stop)

    def steps(self, browser: str) -> list[dict]:
        self.cue()
        steps = []
        for index, (width, height) in enumerate(base.WIDTHS):
            shot = str(OUT / f"{browser}-{width}")
            page = f"{self.base}?{width}"
            last = index == len(base.WIDTHS) - 1
            steps += [
                {"width": width, "height": height, "url": f"{page}-clear#stream", "wait": 600, "probe": CLEAR, "shot": None},
                {"width": width, "height": height, "url": f"{page}-loaded#resources", "wait": 1200, "probe": probe(LOADED), "shot": None},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(FOUND), "shot": None},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(dash.OWNERS), "shot": None},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(METRIC), "shot": f"{shot}-combined-pin.png"},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(dash.OWNERS, ["resources"]), "shot": None},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(COMBINED_OFF), "shot": f"{shot}-metric-pin.png"},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(HOME_METRICS), "shot": f"{shot}-home-metrics.png"},
                {"width": width, "height": height, "url": f"{page}-reloaded#home", "wait": 1500, "probe": probe(RELOADED), "shot": None},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(PM), "shot": f"{shot}-home-bookmarks.png"},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(LONG), "shot": f"{shot}-home-long-paths.png"},
            ]
            if last:
                steps.append({"width": width, "height": height, "url": None, "wait": 0, "probe": probe(GONE), "shot": f"{shot}-gone.png"})
            steps.append({"width": width, "height": height, "url": None, "wait": 0, "probe": probe(UNPIN if last else UNPIN_PLAIN), "shot": None})
        return steps

    def check(self, data: dict, browser: str) -> None:
        results = iter(data["results"])
        for index, (width, _) in enumerate(base.WIDTHS):
            last = index == len(base.WIDTHS) - 1
            with self.subTest(browser=browser, width=width):
                next(results)
                loaded = next(results)
                self.assertTrue(loaded["drawn"], loaded)
                found = next(results)
                self.assertEqual((found["charts"], found["stars"]), ([True] * 5, 0), found)
                self.assertEqual(found["tree"], [True], found)
                self.assertTrue(found["rows"]["repo"] and all(found["rows"]["repo"]), found)
                self.assertTrue(found["rows"]["branch"] and all(found["rows"]["branch"]), found)
                self.assertTrue(found["rows"]["wt"] and all(found["rows"]["wt"]), found)
                self.assertEqual((found["order"], found["operator"]), ([True], [True]), found)
                self.assertTrue(all(found["long"].values()), found)
                self.assertGreater(found["long"]["leaf"], 0, found)
                self.assertEqual(found["disabled"], [], found)
                self.assertGreaterEqual(found["deletes"], 1, found)
                walked = next(results)
                self.assertEqual((walked["missing"], walked["stars"]), ([], []), walked)
                metric = next(results)
                self.assertNotIn("error", metric, metric)
                self.assertEqual((metric["cpuOnly"], metric["hardware"], metric["tokens"], metric["back"], metric["combinedOn"], metric["combined"]), (True, "true", "true", True, True, "true"), metric)
                self.assertEqual(metric["cpuTitle"], "Unpin from Home: Hardware: CPU")
                self.assertEqual(metric["axisOverlaps"], 0, metric)
                self.assertEqual(metric["allState"], ["false", "Pin to Home: Hardware: all series"])
                kinds = [[kind, key.split("/")[0], view] for kind, key, view in metric["stored"]]
                self.assertEqual(kinds, [
                    ["metric", "hardware", {"chart": "hardware", "tokens": "interval", "shown": [res.CPU]}],
                    ["metric", "tokens", {"chart": "tokens", "tokens": "interval", "shown": None}],
                    ["metric", "combined", {"chart": "combined", "tokens": "interval", "shown": None}],
                ])
                self.assertRegex(metric["stored"][0][1], r"^hardware/[0-9a-f]{16}$")
                self.assertEqual([key for _, key, _ in metric["stored"][1:]], ["tokens/interval/all", "combined/interval/all"])
                combined_walk = next(results)
                self.assertEqual((combined_walk["missing"], combined_walk["stars"]), ([], []), combined_walk)
                self.assertEqual(next(results), {"off": True, "hardware": ["false", "Pin to Home: Hardware: all series"]})
                home = next(results)
                self.assertEqual(home["errors"], [], home)
                self.assertEqual((home["hardware"]["title"], home["hardware"]["lines"], home["hardware"]["legend"], home["hardware"]["chart"]), ("Hardware: CPU", [res.CPU], [res.CPU], "hardware"), home)
                self.assertEqual((home["tokens"]["title"], home["tokens"]["bars"]), ("Tokens: all series", ["Skills", "Stage"]), home)
                self.assertEqual((home["combined"]["title"], home["combined"]["chart"], home["combined"]["lines"]), ("Combined: all series", "combined", HARDWARE), home)
                self.assertGreater(home["combined"]["right"], 0, home)
                self.assertEqual(home["combined"]["burn"], 2, home)
                self.assertEqual(home["overlaps"], {"hardware": 0, "tokens": 0, "combined": 0}, home)
                if home["scroll"]["scrollable"]:
                    self.assertEqual(home["scroll"]["after"], home["scroll"]["before"], home)
                reloaded = next(results)
                self.assertEqual((reloaded["hash"], reloaded["lines"], reloaded["title"]), ("#home", [res.CPU], "Hardware: CPU"), reloaded)
                self.assertEqual(reloaded["stored"]["view"], {"chart": "hardware", "tokens": "interval", "shown": [res.CPU]})
                pm = next(results)
                self.assertEqual(pm["pressed"], {"tree": "true", "branch": "true", "order": "true", "operator": "true", "agent": "true"}, pm)
                self.assertEqual(pm["errors"], [], pm)
                self.assertEqual((pm["tree"][0], pm["order"][0]["gone"], pm["operator"]), ({"gone": False, "title": "Artifacts: tree"}, False, [{"gone": False, "title": "Tasks: Waits on Operator"}, 2]), pm)
                self.assertGreaterEqual(pm["tree"][1], 2, pm)
                self.assertGreaterEqual(len(pm["order"][1]), 2, pm)
                self.assertEqual((pm["artifact"][0]["gone"], pm["artifact"][1]), (False, KEPT), pm)
                self.assertEqual((pm["agent"][0], pm["agent"][1]), ({"gone": False, "title": f"Agent {GHOST}"}, True), pm)
                self.check_long(next(results))
                if last:
                    gone = next(results)
                    self.assertEqual(gone["before"], [False] * 6, gone)
                    self.assertTrue(gone["vanished"], gone)
                    self.assertEqual((gone["agent"], gone["artifacts"]), (["gone", "Unpin"], [["gone", "Unpin"]] * 5), gone)
                unpinned = next(results)
                self.assertNotIn(unpinned["metric"], unpinned["tiles"])
                self.assertNotIn(unpinned["metric"], unpinned["stored"])
                if last:
                    self.assertEqual(len(unpinned["artifacts"]), 5, unpinned)
                    self.assertFalse(set(unpinned["artifacts"]) & set(unpinned["tiles"] + unpinned["stored"]), unpinned)

    def check_long(self, long: dict) -> None:
        self.assertEqual(long["errors"], [], long)
        self.assertEqual(long["pressed"], {key: [True, "true"] for key in LONG_ROWS}, long)
        self.assertEqual([key for key in long["stored"] if key in long["keys"].values()], list(long["keys"].values()), long)
        for key in ("core", "leaf"):
            self.assertRegex(long["keys"][key], r"^artifact:(wt|artefact)_23_[0-9a-f]{16}$", long)
        labels = {"repo": LONG_REPO, "worktree": LONG_WORKTREE, "core": CORE_WORKTREE, "leaf": LONG_VOLUME}
        names = {"repo": LONG_NAME, "worktree": "/".join(Path(LONG_WORKTREE).parts[-2:]), "core": "/".join(Path(CORE_WORKTREE).parts[-2:]), "leaf": LONG_VOLUME.split(":", 1)[1]}
        for key in LONG_ROWS:
            shown = long["shown"][key]
            self.assertIsNotNone(shown, (key, long))
            self.assertFalse(shown["gone"], (key, shown))
            self.assertEqual(shown["label"], names[key], (key, shown))
            self.assertIn(labels[key], shown["body"], (key, shown))
            self.assertTrue(shown["title"].startswith("Artifact "), (key, shown))
        self.assertIn(LONG_WORKTREE, long["shown"]["worktree"]["title"])
        self.assertIn(CORE_WORKTREE, long["shown"]["core"]["title"])
        self.assertIn(LONG_VOLUME, long["shown"]["leaf"]["title"])
        self.assertEqual(long["scroll"]["deletes"], 0, long)
        if long["scroll"]["scrollable"]:
            self.assertEqual(long["scroll"]["after"], long["scroll"]["before"], long)

    def test_chromium_pins_metrics_with_their_selection_views_and_single_elements_at_three_widths(self):
        data = self.drive(self.steps("chromium"), None, init=w4.GUARD)
        (OUT / "chromium-bookmarks.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        self.check(data, "chromium")

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_pins_metrics_with_their_selection_views_and_single_elements_at_three_widths(self):
        data = self.drive(self.steps("firefox"), None, "bidi.mjs", os.environ.get("FIREFOX", "firefox"), init=w4.GUARD)
        (OUT / "firefox-bookmarks.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        self.check(data, "firefox")


if __name__ == "__main__":
    unittest.main()
