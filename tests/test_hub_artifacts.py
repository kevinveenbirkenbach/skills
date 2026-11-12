from __future__ import annotations

import hashlib
import json
import re
import tempfile
import unittest
from pathlib import Path

from hub_case import HubCase
from hub_support import HUB, PAGE
from kvb_orchestrator import artifacts, exchange, icons
from kvb_orchestrator.errors import ToolError

VENDOR = HUB / "vendor"
TEMPLATES = HUB / "templates"
VENDORED = {
    "bootstrap-icons/bootstrap-icons.svg": ("fe7b61303ee8b160aa2d596dabbb70f4ffeaf8ea24891004e9b1d0d2877638b1", "Copyright (c) 2019-2024 The Bootstrap Authors"),
    "3d-force-graph/3d-force-graph.min.js": ("13088340aad408156064fd120c3bc3a47c93a3cc45b8f132d6284b20e2223be9", "Copyright (c) 2017 Vasco Asturiano"),
    "three/three.module.js": ("9052042d676cb0fdc1ddfefe193053f34b7ac0513a616fdac4535d49987812ea", "Copyright © 2010-2026 three.js authors"),
    "three/three.core.js": ("9edde002b066a9a05676a6127f67735b62baf399bdea529f2f7e31657da769e6", "Copyright © 2010-2026 three.js authors"),
}
VERSIONS = {"3d-force-graph/3d-force-graph.min.js": "Version 1.80.1", "three/three.core.js": "REVISION = '186'"}


class TestHubIcons(HubCase):
    def test_the_page_inlines_exactly_the_icons_it_uses_from_the_vendored_sprite(self):
        html = self.index()
        sprite = re.search(r'<svg xmlns="http://www.w3.org/2000/svg" class="sprite" aria-hidden="true" focusable="false">(.*?)</svg>', html, re.DOTALL)
        self.assertIsNotNone(sprite)
        inlined = re.findall(r'<symbol id="bi-([a-z0-9-]+)" viewBox="0 0 16 16">', sprite.group(1))
        used = icons.used(TEMPLATES)
        self.assertGreater(len(used), 40)
        self.assertEqual(inlined, used)
        known = icons.symbols(VENDOR / icons.SPRITE)
        self.assertLessEqual(set(used), set(known))
        for name in ("command", "gear"):
            with self.subTest(header=name):
                self.assertIn(f'<use href="#bi-{name}"></use>', html)
        self.assertIsNone(re.search(r'(?:src|href)="(?:https?:)?//', html))
        self.assertNotIn("cdn.", html)

    def test_an_icon_missing_from_the_sprite_stops_the_start(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "page.js").write_text('const x = icon("bi-not-an-icon-ever");', encoding="utf-8")
            with self.assertRaisesRegex(ToolError, "not-an-icon-ever"):
                icons.sheet(VENDOR, Path(folder))

    def test_vendored_files_are_pinned_and_carry_their_mit_licence(self):
        for name, (digest, holder) in VENDORED.items():
            with self.subTest(file=name):
                path = VENDOR / name
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)
                licence = (path.parent / "LICENSE").read_text(encoding="utf-8")
                self.assertIn("MIT License", licence)
                self.assertIn(holder, licence)
        for name, marker in VERSIONS.items():
            with self.subTest(version=name):
                self.assertIn(marker, (VENDOR / name).read_text(encoding="utf-8"))

    def test_the_vendor_route_serves_only_its_allowlist_under_the_plain_csp(self):
        status, headers, body = self.get("/vendor/3d-force-graph.min.js")
        self.assertEqual((status, headers["content-type"]), (200, "text/javascript; charset=utf-8"))
        self.assertEqual(body, (VENDOR / "3d-force-graph" / "3d-force-graph.min.js").read_bytes())
        self.assertEqual(headers["content-security-policy"], exchange.PLAIN_CSP)
        for path in ("/vendor/bootstrap-icons.svg", "/vendor/LICENSE", "/vendor/..%2Fserver.py", "/vendor/three"):
            with self.subTest(path=path):
                self.assertEqual(self.get(path)[0], 404)


class TestHubArtifacts(HubCase):
    def test_a_merge_pkgmgr_names_into_the_remote_tracking_default_points_at_the_default_branch_node(self):
        self.write_fixture("branch-tree-tokenless.json")
        status, _, body = self.get("/api/tree")
        self.assertEqual(status, 200, body)
        merges = {repo["name"]: repo["merges"] for repo in json.loads(body)["repos"]}
        self.assertEqual(merges, {
            "github.com/anon/web": [{"from": "chore/ancestor-local", "into": "main", "by": "ancestor"}, {"from": "fix/remote-merged", "into": "main", "by": "ancestor"}],
            "git.example.org/anon/notes": [{"from": "topic/ancestor-local", "into": "master", "by": "ancestor"}, {"from": "topic/patch-local", "into": "master", "by": "patch"}],
        })

    def test_the_tree_carries_artefact_leaves_overlaps_merges_and_lanes(self):
        root = self.write_tree()
        demo = f"{root}/worktrees/github.com/me/demo"
        feature, done = f"{demo}/feature", f"{demo}/feature-done"
        register = {
            "work/done": {"title": "Done", "status": "running", "worker": "Skills session", "workdir": done, "artifacts": [{"ref": "image:demo:feature-done", "added": "2026-11-06T10:00:00+00:00"}, {"ref": "volume:demo_data", "added": "2026-11-06T10:05:00+00:00"}]},
            "work/loose": {"title": "Loose", "status": "running", "artifacts": [{"ref": "log:/tmp/loose.log", "added": "2026-11-06T11:00:00+00:00"}]},
            "work/plain": {"title": "Plain", "status": "running"},
        }
        history = [{"id": "q1", "kind": "test-nostack", "workdir": done, "start": 1000.0, "end": 1010.0, "exit": 0}, {"id": "q2", "kind": "deploy", "workdir": done, "start": 1100.0, "end": 1110.0, "exit": 0}]
        self.write_council({"rasci.json": register, "queue-history.jsonl": self.jsonl(history)})
        touched = {}
        for path, branch, files in ((feature, "feature", ["a.py", "b.py"]), (done, "feature/done", ["a.py", "c.py"])):
            result = self.tool("review_request", {**self.arguments(f"feat: {branch}", "", self.page(f"{branch.replace('/', '-')}.html", PAGE)), "worktree": path, "branch": branch})
            touched[branch] = result["structuredContent"]["id"]
            self.httpd.hub.reviews.stored(touched[branch], ".json").write_text(json.dumps({"files": [{"path": name} for name in files]}), encoding="utf-8")
        self.httpd.hub.reviews.decide(touched["feature/done"], {"status": "approved", "proof": None})
        status, _, body = self.get("/api/tree")
        self.assertEqual(status, 200, body)
        data = json.loads(body)
        repo = next(entry for entry in data["repos"] if entry["name"] == "github.com/me/demo")
        branches = {entry["name"]: entry for entry in repo["branches"]}
        leaves = [(leaf["task"], leaf["kind"], leaf["name"]) for leaf in branches["feature/done"]["worktrees"][0]["artefacts"]]
        self.assertEqual(leaves, [("work/done", "image", "demo:feature-done"), ("work/done", "volume", "demo_data")])
        self.assertEqual(branches["feature"]["worktrees"][0]["artefacts"], [])
        self.assertEqual([(task["task"], [leaf["ref"] for leaf in task["artefacts"]]) for task in data["tasks"]], [("work/loose", ["log:/tmp/loose.log"])])
        self.assertEqual(repo["overlaps"], [{"a": "feature", "b": "feature/done", "count": 1, "files": ["a.py"]}])
        self.assertEqual(repo["merges"], [{"from": "feature/done", "into": "main", "by": "#12"}, {"from": "feature/kept", "into": "main", "by": "ancestor"}])
        self.assertEqual((branches["feature"]["files"], branches["feature/done"]["files"]), (2, 2))
        kinds = [(event["kind"], event["ok"]) for event in branches["feature/done"]["events"]]
        self.assertEqual(kinds, [("gate", True), ("review", None), ("gate", True), ("commit", True)])
        self.assertEqual([event["kind"] for event in branches["feature"]["events"]], ["review", "gate"])
        self.assertEqual(data["cleanups"], [])

    def test_a_lane_counts_push_commands_and_failed_gates(self):
        path = "/w/demo/feature"
        history = [{"kind": "gate", "workdir": f"{path}/sub", "start": 10.0, "end": 20.0, "exit": 2}, {"kind": "test", "workdir": "/w/other", "end": 30.0, "exit": 0}]
        jobs = [
            {"command": "gipsn", "directory": path, "status": "done", "finished": 40.0},
            {"command": "make test", "directory": path, "status": "done", "finished": 50.0},
            {"command": "git push origin feature", "directory": path, "status": "queued", "created_ts": 60.0},
            {"command": "pushd x", "directory": path, "status": "done", "finished": 70.0},
        ]
        events = artifacts.lane([path], [], history, jobs)
        self.assertEqual([(event["ts"], event["kind"], event["ok"]) for event in events], [(20.0, "gate", False), (40.0, "push", True), (60.0, "push", None)])


if __name__ == "__main__":
    unittest.main()
