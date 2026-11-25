from __future__ import annotations

import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from hub_case import HubCase
from hub_support import HUB
from kvb_orchestrator.errors import ToolError
from kvb_orchestrator.viewstore import VIEW, ViewStore, upgraded, valid_view

TEMPLATES = HUB / "templates"
KEY = "panel:tasks/board"
PIN = {"kind": "panel", "id": "tasks/board", "w": 6, "h": 4}
STEPS = """
const P = require(process.argv[1]);
const run = (zooms, steps) => steps.reduce((now, step) => P.zoomBy(now, "panel:tasks/board", step), zooms);
console.log(JSON.stringify({
  three: run({}, [1, 1, 1]), reset: run({"panel:tasks/board": 130}, [0]), floor: run({}, Array(8).fill(-1)), ceiling: run({}, Array(14).fill(1)),
  other: run({"panel:x": 70}, [1]), back: run({}, [1, -1]), zoom: P.ZOOM,
}));
"""


def change(values: dict, expected: dict) -> bytes:
    return json.dumps({"set": values, "expect": expected}).encode()


def viewed(zoom: dict) -> dict:
    doc = copy.deepcopy(VIEW)
    doc["home"] = {"pins": [PIN], "zoom": zoom}
    return doc


class TestZoomSteps(unittest.TestCase):
    def test_keys_step_ten_percent_inside_50_to_200_and_reset_leaves_the_base_out(self):
        done = subprocess.run(["node", "-e", STEPS, str(TEMPLATES / "panels.js")], capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        out = json.loads(done.stdout)
        self.assertEqual(out["zoom"], {"min": 50, "max": 200, "step": 10, "base": 100})
        self.assertEqual((out["three"], out["reset"], out["floor"], out["ceiling"]), ({KEY: 130}, {}, {KEY: 50}, {KEY: 200}))
        self.assertEqual((out["other"], out["back"]), ({"panel:x": 70, KEY: 110}, {}))

    def test_the_tile_keys_the_wheel_and_the_menu_reach_the_same_step(self):
        home = (TEMPLATES / "page-home.js").read_text(encoding="utf-8")
        self.assertIn('const ZOOM_KEYS = {"+": 1, "=": 1, "-": -1, "0": 0};', home)
        self.assertIn("event.ctrlKey || !event.deltaY", home)
        self.assertIn('body.addEventListener("wheel", (event) => homeWheel(event, key), {passive: false});', home)
        context = (TEMPLATES / "page-context.js").read_text(encoding="utf-8")
        for label, step in (('"Zoom in"', "1"), ('"Zoom out"', "-1"), ("`Reset zoom (${homeZoom(key)} %)`", "0")):
            with self.subTest(label=label):
                self.assertIn(f"label: {label}, hint: ", context)
                self.assertIn(f"homeZoomBy(key, {step})", context)
        self.assertIn("Ctrl+wheel", (TEMPLATES / "page-constants.js").read_text(encoding="utf-8"))
        self.assertIn(".home-body > * { zoom: var(--zoom, 1); }", (TEMPLATES / "style-home.css").read_text(encoding="utf-8"))


class TestZoomStore(unittest.TestCase):
    def test_a_pinned_tile_keeps_its_zoom_and_an_unpinned_one_loses_it(self):
        self.assertEqual(valid_view(viewed({KEY: 130}))["home"]["zoom"], {KEY: 130})
        self.assertEqual(valid_view(viewed({KEY: 130, "panel:gone": 70}))["home"]["zoom"], {KEY: 130})

    def test_values_off_the_grid_or_outside_50_to_200_are_refused(self):
        for bad in ({KEY: 40}, {KEY: 210}, {KEY: 105}, {KEY: True}, {KEY: "130"}, {KEY: 130.0}, {"no key": 130}, []):
            with self.subTest(bad=bad), self.assertRaises(ToolError):
                valid_view(viewed(bad))

    def test_an_older_document_without_zoom_reads_with_none(self):
        old = copy.deepcopy(VIEW)
        old["home"] = {"pins": [PIN]}
        self.assertEqual(valid_view(upgraded(old))["home"], {"pins": [PIN], "zoom": {}})

    def test_the_zoom_survives_a_restart(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        file = Path(folder.name) / "view.json"
        ViewStore(file).patch(change({"home.pins": [PIN], "home.zoom": {KEY: 130}}, {"home.pins": [], "home.zoom": {}}))
        self.assertEqual(ViewStore(file).get()["home"], {"pins": [PIN], "zoom": {KEY: 130}})


class TestZoomOverHttp(HubCase):
    def patch(self, body: bytes) -> int:
        return self.call("PATCH", "/api/view", body, {**self.guard(self.host), "Content-Type": "application/json"})[0]

    def test_the_hub_refuses_an_off_grid_zoom_with_400_and_keeps_a_valid_one(self):
        self.assertEqual(self.patch(change({"home.pins": [PIN], "home.zoom": {KEY: 135}}, {"home.pins": [], "home.zoom": {}})), 400)
        self.assertEqual(self.patch(change({"home.pins": [PIN], "home.zoom": {KEY: 130}}, {"home.pins": [], "home.zoom": {}})), 200)
        self.assertEqual(json.loads(self.get("/api/view")[2])["home"]["zoom"], {KEY: 130})


if __name__ == "__main__":
    unittest.main()
