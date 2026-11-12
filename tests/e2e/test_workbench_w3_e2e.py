from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

import test_orchestrator_e2e as base
from hub_case import HubCase
from hub_support import REPO_ROOT, iso

OUT = Path(os.environ.get("E2E_OUT", "/tmp/workbench-w3-shots"))
GATES_SPEC = importlib.util.spec_from_file_location("kvb_gates_for_e2e", REPO_ROOT / "skills" / "kvb-check-gate" / "scripts" / "gates.py")
gates = importlib.util.module_from_spec(GATES_SPEC)
GATES_SPEC.loader.exec_module(gates)
KEPT_TIP = "0c9d8e7f6a5b4c3d2e1f0a9b8c7d6e5f4a3b2c1d"
CLEAN_ALL = """(async () => {@HELPERS@
  const every = await until(() => document.querySelector('#main button[aria-label="Delete all merged"]'), 8000);
  await until(() => document.querySelector("#main svg.ancestry"), 8000);
  const token = all("#main .delete-all span.state").map(name);
  const store = document.querySelector('#main button[aria-label="Store token"]');
  const before = every ? [every.disabled, every.title] : null;
  every.click();
  const sheet = await until(() => document.querySelector("#sheet:not([hidden]) li.dry-run") && document.getElementById("sheet"), 8000);
  const rows = all("li.dry-run", sheet).map((row) => [text(row.querySelector("code")), row.dataset.token || (row.dataset.held ? "held" : null), text(row.querySelector("pre")).split("\\n")[0]]);
  const confirm = all("#sheet button").find((button) => name(button) === "Delete");
  confirm.click();
  const outcome = await until(() => sheet.querySelector("[data-cleanup]") || all("#sheet p.muted").find((node) => text(node).startsWith("Not signed")), 15000);
  const tokenClick = store ? (store.click(), await until(() => all("#toasts .toast").map(text).find((line) => line.startsWith("Token")), 8000)) : null;
  return {before, token, store: store ? [store.title, store.getAttribute("aria-label")] : null, rows, outcome: outcome ? (outcome.dataset.cleanup ? "queued" : "unsigned") : null, tokenClick,
    wide: document.documentElement.scrollWidth > document.documentElement.clientWidth};
})()"""
ANCESTRY = """(async () => {@HELPERS@
  const svg = await until(() => document.querySelector('#main svg.ancestry[aria-label="Ancestry of github.com/me/demo"]'), 8000);
  if (!svg) {
    return {error: "no ancestry"};
  }
  const nodes = all("g.ancestry-node", svg).map((node) => [node.dataset.branch, Number(node.dataset.generation)]);
  const edges = all("path.ancestry-edge", svg).map((edge) => [edge.dataset.parent, edge.dataset.child, edge.dataset.source, getComputedStyle(edge).strokeDasharray !== "none"]);
  const marks = (branch) => {
    const row = all("#main .branch-row").find((entry) => text(entry.querySelector(".branch-name strong")) === branch);
    return row ? all(".gate-mark", row).map((button) => [button.dataset.action, button.dataset.level, button.classList.contains("inherited"), button.title, Number(getComputedStyle(button).opacity) < 1]) : null;
  };
  return {nodes, edges, done: marks("feature/done"), main: marks("main"), wide: document.documentElement.scrollWidth > document.documentElement.clientWidth};
})()"""
STAGE = """(async () => {@HELPERS@
  const svg = await until(() => document.querySelector("#main svg.ancestry"), 8000);
  svg.scrollIntoView({block: "center", inline: "center"});
  await sleep(200);
  const center = (branch) => {
    const node = svg.querySelector(`g.ancestry-node[data-branch="${CSS.escape(branch)}"] circle`);
    const box = node.getBoundingClientRect();
    return {x: box.left + box.width / 2, y: box.top + box.height / 2, node};
  };
  const from = center("feature/kept");
  const onto = center("feature");
  from.node.dispatchEvent(new PointerEvent("pointerdown", {bubbles: true, button: 0, clientX: from.x, clientY: from.y, pointerType: "mouse", isPrimary: true}));
  document.dispatchEvent(new PointerEvent("pointerup", {bubbles: true, button: 0, clientX: onto.x, clientY: onto.y, pointerType: "mouse", isPrimary: true}));
  const pending = await until(() => document.querySelector('#main path.ancestry-edge.pending[data-child="feature/kept"][data-parent="feature"]'), 4000);
  const row = all("#main .branch-row").find((entry) => text(entry.querySelector(".branch-name strong")) === "feature");
  const commit = () => row.isConnected ? row.querySelector('.gate-mark[data-action="commit"]') : all("#main .branch-row").find((entry) => text(entry.querySelector(".branch-name strong")) === "feature").querySelector('.gate-mark[data-action="commit"]');
  commit().click();
  await sleep(100);
  commit().click();
  const staged = await until(() => document.querySelector('#main .gate-mark.pending[data-action="commit"][data-level="quick"]'), 4000);
  const apply = await until(() => document.querySelector('#main button[aria-label="Apply"]'), 4000);
  const count = apply ? text(apply.parentElement.querySelector(".count")) : null;
  apply.click();
  const toast = await until(() => all("#toasts .toast").map(text).find((line) => line.startsWith("Gates") || line.startsWith("Not signed") || line.includes("passkey")), 15000);
  return {pending: Boolean(pending), staged: Boolean(staged), title: staged ? staged.title : null, count, apply: apply ? [apply.title, apply.getAttribute("aria-label")] : null, toast,
    left: all("#main .gate-mark.pending").length + all("#main path.ancestry-edge.pending").length};
})()"""
TOKENLESS = """(async () => {@HELPERS@
  const every = await until(() => document.querySelector('#main button[aria-label="Delete all merged"]'), 8000);
  await until(() => document.querySelector("#main .branch-row"), 8000);
  const store = document.querySelector('#main button[aria-label="Store token"]');
  const rows = all("#main .branch-row").map((row) => [text(row.querySelector(".branch-name strong")), Boolean(row.querySelector('span.state[aria-label="token needed"]')), Boolean(row.querySelector('button[aria-label="Delete"]'))]);
  return {every: [every.disabled, every.title], token: all("#main .delete-all span.state").map(name), store: store ? store.getAttribute("aria-label") : null, rows};
})()"""
AGENTS = """(async () => {@HELPERS@
  const svg = await until(() => document.querySelector('#main svg.ancestry[aria-label="Ancestry: operator, chair, sessions, subagents"]'), 8000);
  if (!svg) {
    return {error: "no agent ancestry"};
  }
  await until(() => svg.querySelector('g.ancestry-node[data-kind="twig"]') || document.querySelector('#main svg.ancestry g[data-kind="twig"]'), 8000);
  const fresh = document.querySelector("#main svg.ancestry");
  const nodes = all("g.ancestry-node", fresh).map((node) => [node.dataset.kind, Number(node.dataset.generation), node.getBoundingClientRect().top]);
  return {nodes, edges: all("path.ancestry-edge", fresh).length, list: all("#main .spawn-tree li").length, wide: document.documentElement.scrollWidth > document.documentElement.clientWidth};
})()"""


def probe(template: str) -> str:
    return template.replace("@HELPERS@", base.HELPERS)


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestWorkbenchArtifacts(HubCase):
    drive = base.TestOrchestratorE2E.drive
    authenticator = base.TestOrchestratorE2E.authenticator
    subagents = base.TestOrchestratorE2E.subagents

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        now = time.time()
        root = self.write_tree()
        data = json.loads(self.tree_file.read_text(encoding="utf-8"))
        next(item for item in data["repos"][0]["items"] if item["branch"] == "feature/kept")["skip"] = None
        self.tree_file.write_text(json.dumps(data), encoding="utf-8")
        self.repo = f"{root}/repos/github.com/me/demo"
        db = gates.connect(self.kept / "gates.db")
        db.executemany("INSERT INTO rules VALUES (?, ?, ?, ?, ?)", [(self.repo, "main", "commit", "test", 0.0), (self.repo, "feature/done", "pr", "e2e", 0.0)])
        db.executemany("INSERT INTO parents VALUES (?, ?, ?, ?)", [(self.repo, "feature", "main", "recorded"), (self.repo, "feature/done", "feature", "derived"), (self.repo, "feature/done", "feature/kept", "operator"), (self.repo, "feature/kept", "main", "derived")])
        db.commit()
        db.close()
        self.claim("s1", "Skills session")
        self.write_council({
            "work/s2/claim.json": {"office": "work/s2", "session": "s2", "runtime": "claude", "name": "Stage", "since": iso(now - 7200), "beat": now - 60, "work": "x"},
            "chair/claim.json": {"office": "chair", "session": "s1", "runtime": "claude", "name": "Skills session", "since": iso(now - 7200), "beat": now, "work": "allocate"},
        })
        self.subagents(now)
        self.base = f"http://{self.host}/"

    def steps(self, browser: str) -> list[dict]:
        steps = []
        for width, height in base.WIDTHS:
            shot = str(OUT / f"{browser}-{width}")
            steps += [
                {"width": width, "height": height, "url": f"{self.base}?{width}#artifacts/tree", "wait": 1200, "probe": probe(ANCESTRY), "shot": f"{shot}-ancestry.png"},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(STAGE), "shot": f"{shot}-staged.png"},
                {"width": width, "height": height, "url": f"{self.base}?{width}-clean#artifacts/tree", "wait": 1200, "probe": probe(CLEAN_ALL), "shot": f"{shot}-clean-all.png"},
                {"width": width, "height": height, "url": f"{self.base}?{width}#agents/tree", "wait": 1200, "probe": probe(AGENTS), "shot": f"{shot}-agents-ancestry.png"},
            ]
        return steps

    def check(self, data: dict, browser: str, signs: bool) -> None:
        results = iter(data["results"])
        for width, _ in base.WIDTHS:
            ancestry, staged, clean, agents = next(results), next(results), next(results), next(results)
            with self.subTest(browser=browser, width=width):
                for found in (ancestry, agents):
                    self.assertNotIn("error", found, found)
                nodes = dict(ancestry["nodes"])
                self.assertEqual(nodes, {"main": 0, "feature": 1, "feature/kept": 1, "feature/done": 2})
                self.assertEqual(sorted(ancestry["edges"]), [
                    ["feature", "feature/done", "derived", True], ["feature/kept", "feature/done", "operator", False], ["main", "feature", "recorded", False], ["main", "feature/kept", "derived", True]])
                self.assertEqual([mark[:3] for mark in ancestry["done"]], [["commit", "test", True], ["merge", "none", True], ["push", "none", True], ["pr", "e2e", False]])
                self.assertEqual([mark[3] for mark in ancestry["done"]][:1], ["commit: test · from main"])
                self.assertEqual([mark[4] for mark in ancestry["done"]], [True, True, True, False])
                self.assertEqual(ancestry["main"][0][:3], ["commit", "test", False])
                self.assertEqual((staged["pending"], staged["staged"], staged["count"]), (True, True, "2"), staged)
                self.assertEqual(staged["apply"], ["Apply 2 gate changes with one passkey signature", "Apply"])
                self.assertEqual(staged["left"], 0 if signs else 2, staged)
                self.assertEqual(clean["before"], [False, "Delete all merged: 1 branches after dry run and signature"])
                self.assertEqual(clean["token"], ["1 held by a worktree: use branch gc"])
                self.assertEqual(clean["store"], ["Store token: add the operator row that stores the GitHub token in the Secret Service", "Store token"])
                self.assertEqual([row[:2] for row in clean["rows"]], [["feature/kept", None], ["feature/done", "held"]])
                self.assertEqual(clean["outcome"], "queued" if signs else "unsigned")
                self.assertTrue(clean["tokenClick"].startswith("Token: operator row added"), clean)
                kinds = {}
                for kind, generation, _ in agents["nodes"]:
                    kinds.setdefault(kind, set()).add(generation)
                self.assertEqual((kinds["operator"], kinds["chair"]), ({0}, {1}))
                self.assertTrue(all(generation >= 2 for generation in kinds.get("session", set()) | kinds.get("subagent", set()) | kinds.get("twig", set())), agents)
                self.assertIn("twig", kinds)
                tops = {kind: min(top for k, _, top in agents["nodes"] if k == kind) for kind in kinds}
                self.assertLess(tops["operator"], tops["chair"])
                self.assertGreater(agents["list"], 0)
                self.assertFalse(any(found["wide"] for found in (ancestry, clean, agents)), (ancestry["wide"], clean["wide"], agents["wide"]))
        jobs = self.runner_jobs()
        gate_jobs = [job["argv"] for job in jobs if job.get("kind") == "gate"]
        expected = [["parents", "add", "--repo", self.repo, "--branch", "feature/kept", "--parent", "feature"], ["rule", "set", "--repo", self.repo, "--branch", "feature", "--action", "commit", "--level", "quick"]]
        self.assertEqual(sorted(gate_jobs), sorted(expected * len(base.WIDTHS)) if signs else [])
        spooled = [json.loads(path.read_text(encoding="utf-8")) for path in sorted((self.cleanup / "jobs").glob("*.json"))]
        self.assertEqual([[item["branch"] for item in job["items"]] for job in spooled], [["feature/kept"]] * len(base.WIDTHS) if signs else [])
        self.assertTrue(all(job["items"][0]["tip"] == KEPT_TIP for job in spooled))
        tokens = [args for script, args in self.scripts.calls if script.endswith("operator.py") and args[:2] == ["add", "pkgmgr-github-token"]]
        self.assertEqual(len(tokens), len(base.WIDTHS))

    def test_chromium_shows_ancestry_in_both_tabs_stages_a_parent_and_a_gate_and_signs_clean_all_merged_at_three_widths(self):
        data = self.drive(self.steps("chromium"), self.authenticator())
        (OUT / "chromium-artifacts.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        self.check(data, "chromium", True)

    def test_chromium_marks_every_forge_unavailable_branch_token_needed_and_offers_store_token_on_the_real_tokenless_tree(self):
        self.write_fixture("branch-tree-tokenless.json")
        data = json.loads(self.tree_file.read_text(encoding="utf-8"))
        data["repos"] = [repo for repo in data["repos"] if repo["forge"] != "none"]
        self.tree_file.write_text(json.dumps(data), encoding="utf-8")
        width, height = base.WIDTHS[0]
        found = self.drive([{"width": width, "height": height, "url": f"{self.base}?tokenless#artifacts/tree", "wait": 1200, "probe": probe(TOKENLESS), "shot": str(OUT / "chromium-tokenless.png")}], self.authenticator())
        self.assertEqual([error for error in found["errors"] if "/favicon.ico" not in error], [])
        shown = found["results"][0]
        self.assertEqual(shown["every"], [True, "Delete all merged blocked: no GitHub token in the Secret Service"])
        self.assertEqual((shown["token"], shown["store"]), (["2 token needed"], "Store token"))
        self.assertEqual(sorted(shown["rows"]), [["chore/ancestor-local", True, False], ["feature/open", False, False], ["fix/remote-merged", True, False], ["main", False, False]])

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_shows_ancestry_in_both_tabs_and_hands_nothing_over_unsigned_at_three_widths(self):
        data = self.drive(self.steps("firefox"), None, "bidi.mjs", os.environ.get("FIREFOX", "firefox"))
        (OUT / "firefox-artifacts.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        self.check(data, "firefox", False)


if __name__ == "__main__":
    unittest.main()
