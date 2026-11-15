from __future__ import annotations

import json
import math
import os
import shutil
import sys
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

import hub_e2e_kit as base
from hub_e2e_kit import (
    CHOICE_CHANNELS,
    GRAPH_HOOK,
    OUT,
    SCREENS,
    SUBS,
    TABS,
    WIDTHS,
    labelled,
)
from hub_e2e_views import (
    ACTIONS,
    CAMERA,
    INBOX_CHIP,
    PICK_3D,
    POPUP_ARTIFACT,
    POPUP_ORBIT,
    PRESENCE_READ,
    PRESENCE_WALK,
    PROBE,
    RULES_OVERLAP,
    SETTINGS_OVERLAP,
)


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestOrchestratorE2E(base.OrchestratorE2ECase):
    def check_overlaps(self, browser: str, driver: str, binary: str) -> None:
        steps = []
        for width, height in WIDTHS:
            steps.append({"width": width, "height": height, "url": f"{self.base}#stream/rules", "wait": 900, "probe": RULES_OVERLAP, "shot": str(OUT / f"{browser}-{width}-rules-form.png")})
            steps.append({"width": width, "height": height, "url": None, "wait": 0, "probe": SETTINGS_OVERLAP, "shot": str(OUT / f"{browser}-{width}-settings-form.png")})
        data = self.drive(steps, None, driver, binary)
        (OUT / f"{browser}-overlap.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        hidden = {"decision": ("Tool (glob)", "Directory (glob)"), "review": ("Tool (glob)",), "ask": ()}
        for index, (width, _) in enumerate(WIDTHS):
            rules, settings = data["results"][2 * index : 2 * index + 2]
            with self.subTest(browser=browser, width=width):
                self.assertNotIn("error", rules)
                self.assertNotIn("error", settings)
                for kind, found in rules.items():
                    self.assertEqual((found["found"], found["outside"]), ([], []), kind)
                    self.assertEqual([label for label in hidden[kind] if label in found["labels"]], [], kind)
                self.assertIn("Directory (glob)", rules["review"]["labels"])
                self.assertEqual(settings, {"found": [], "outside": []})

    def popped(self, result: dict, title: str) -> None:
        before, shown, gone = result["before"], result["shown"], result["gone"]
        self.assertEqual((before["picked"], before["red"]), (False, False))
        self.assertEqual((shown["open"], shown["picked"], shown["red"], shown["fade"], shown["title"]), (True, True, True, [True, "fade"], title), shown)
        self.assertGreater(shown["size"], before["size"] * 1.4)
        self.assertLess(shown["opacity"], 1)
        self.assertIsNotNone(shown["line"], shown)
        self.assertTrue(shown["onBox"] and shown["inside"], shown)
        self.assertEqual((not shown["tall"], shown["wide"], shown["panel"]), (result["flat"], False, 0))
        self.assertEqual(gone, {"picked": False, "size": before["size"], "red": False, "open": False, "outside": True})
        self.assertTrue(result["last"])

    def check_popups(self, browser: str, driver: str, binary: str) -> None:
        steps = []
        for width, height in WIDTHS:
            steps.append({"width": width, "height": height, "url": f"{self.base}#agents/orbit", "wait": 1200, "probe": POPUP_ORBIT, "shot": str(OUT / f"{browser}-{width}-agents-orbit-popup.png")})
            steps.append({"width": width, "height": height, "url": f"{self.base}#artifacts/orbit", "wait": 1200, "probe": POPUP_ARTIFACT, "shot": str(OUT / f"{browser}-{width}-artifacts-orbit-popup.png")})
        for tab, query, prefix in (("artifacts", "feature", "branch:"), ("agents", "sta", "s2")):
            steps.append({"width": 1366, "height": 768, "url": f"{self.base}#{tab}/3d", "wait": 900, "probe": PICK_3D.replace("@QUERY@", query).replace("@PREFIX@", prefix), "shot": str(OUT / f"{browser}-1366-{tab}-3d-picked.png")})
        data = self.drive(steps, None, driver, binary)
        (OUT / f"{browser}-popups.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "(style-src-elem)" not in error and "/favicon.ico" not in error], [])
        results = data["results"]
        for index, (width, _) in enumerate(WIDTHS):
            agent, artifact = results[2 * index : 2 * index + 2]
            with self.subTest(browser=browser, width=width):
                self.assertNotIn("error", agent)
                self.assertNotIn("error", artifact)
                self.assertTrue(agent["flat"], "#agents/orbit scrolls")
                self.popped(agent, "Stage")
                self.assertEqual(agent["shown"]["face"], {"key": "s2", "svg": True, "text": ""})
                self.assertEqual(agent["shown"]["sections"], ["Tasks", "Claims", "Subagents", "History"])
                self.assertTrue(agent["shown"]["composer"])
                self.assertRegex(agent["shown"]["offices"], r"^Offices: .*identity/oidc")
                escaped = agent["escaped"]
                self.assertEqual((escaped["again"], escaped["open"], escaped["picked"], escaped["red"], escaped["size"]), (True, False, False, False, agent["before"]["size"]))
                self.popped(artifact, artifact["shown"]["label"])
        for found, tab in zip(results[-2:], ("artifacts", "agents"), strict=True):
            with self.subTest(browser=browser, tab=tab):
                self.assertNotIn("error", found)
                self.assertEqual(found["empty"], [])
                labels = [label for _, label in found["hits"]]
                self.assertEqual(len(labels), len(set(labels)), labels)
                self.assertLessEqual(len(labels), 8)
                opened = found["opened"]
                self.assertEqual((opened["open"], opened["title"], opened["picked"], opened["line"], opened["lists"], opened["flat"]), (True, opened["label"], opened["hit"], True, 0, found["flat"]), opened)
                self.assertEqual(found["closed"], {"open": False, "picked": None})
        artifacts, agents = results[-2:]
        self.assertEqual((artifacts["twins"], [label for _, label in artifacts["twin"]]), (2, ["main"]))
        self.assertTrue(artifacts["opened"]["hit"].startswith("branch:"), artifacts["opened"])
        self.assertEqual((agents["hits"], agents["opened"]["title"]), ([["s2", "Stage"]], "Stage"))

    def test_chromium_opens_agent_and_node_popups_and_finds_nodes_at_three_widths(self):
        self.check_popups("chromium", "cdp.mjs", os.environ.get("CHROMIUM", "chromium"))

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_opens_agent_and_node_popups_and_finds_nodes_at_three_widths(self):
        self.check_popups("firefox", "bidi.mjs", os.environ.get("FIREFOX", "firefox"))

    def test_chromium_form_controls_never_overlap(self):
        self.check_overlaps("chromium", "cdp.mjs", os.environ.get("CHROMIUM", "chromium"))

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_form_controls_never_overlap(self):
        self.check_overlaps("firefox", "bidi.mjs", os.environ.get("FIREFOX", "firefox"))

    def test_chromium_walks_every_screen_at_three_widths(self):
        steps = [{"width": width, "height": height, "url": f"{self.base}#{screen}", "wait": 900, "probe": PROBE, "shot": self.shot(f"{width}-{screen.replace('/', '-')}")} for width, height in WIDTHS for screen in SCREENS]
        steps += [{"width": 1366, "height": 768, "url": f"{self.base}#{old}", "wait": 600, "probe": PROBE, "shot": None} for old in ("graph", "graph/chord", "tree")]
        steps.append({"width": 1366, "height": 768, "url": f"{self.base}#stream", "wait": 900, "probe": ACTIONS, "shot": None})
        steps.append({"width": 1366, "height": 768, "url": f"{self.base}#artifacts/3d", "wait": 900, "probe": PROBE, "shot": self.shot("1366-artifacts-3d-reduced-motion"), "media": [{"name": "prefers-reduced-motion", "value": "reduce"}]})
        steps.append({"width": 1366, "height": 768, "url": f"{self.base}#tasks/list", "wait": 900, "probe": INBOX_CHIP, "shot": self.shot("1366-tasks-grant")})
        data = self.drive(steps, None)
        (OUT / "chromium-walk.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        probes = data["results"][: len(WIDTHS) * len(SCREENS)]
        for probe, step in zip(probes, steps, strict=False):
            with self.subTest(url=step["url"], width=step["width"]):
                self.assertNotIn("error", probe)
                self.assertEqual((probe["title"], probe["h1"]), ("(2) Agent Orchestrator", "Agent Orchestrator"))
                self.assertEqual(probe["header"], ["radio-open", "bubbles-toggle", "palette-open", "settings-open"])
                self.assertEqual((probe["tabs"], probe["subs"]), (TABS, SUBS))
                self.assertEqual(probe["badges"], {"tab-home": None, "tab-stream": None, "tab-rules": None, "tab-agents": "1", "tab-artifacts": None, "tab-tasks": "2", "tab-resources": None})
                self.assertEqual(probe["banner"], "MAYDAY · Docs: disk full")
                self.assertFalse(probe["rail"])
                self.assertEqual((probe["time"], probe["replay"]), ("24 h ▾", True))
                self.assertGreater(probe["icons"], 8)
                self.assertEqual(labelled(probe), {"unlabelled": [], "broken": []})
                self.assertFalse(probe["wide"], "the page scrolls sideways")
                self.assertEqual((probe["panel"], probe["nodeChips"]), (0, 0))
                self.assertEqual(probe["composers"], ["spot"])
        self.assertEqual([probe["tall"] for probe in probes if probe["hash"] == "#agents/orbit"], [False] * len(WIDTHS))
        by_hash = {probe["hash"]: probe for probe in probes}
        stream = by_hash["#stream"]
        self.assertEqual([probe["chips"] for probe in probes if probe["hash"] == "#stream"], [["For you", "Radio", "Work", "Transcripts"]] * len(WIDTHS))
        self.assertEqual((stream["menus"], stream["custom"]), (["Filter"], True))
        self.assertEqual(by_hash["#tasks/operator"]["inbox"], 2)
        for tab, own in (("agents", ["Hierarchy"]), ("artifacts", [])):
            with self.subTest(tab=tab):
                self.assertEqual(by_hash[f"#{tab}/orbit"]["views"], ["Orbit", "Chord", "Swimlane", "Tree", "3D", *own])
                self.assertEqual(by_hash[f"#{tab}/3d"]["layouts"], ["Force", "Time", "Spawn depth"])
                self.assertTrue(by_hash[f"#{tab}/3d"]["canvas"], by_hash[f"#{tab}/3d"]["note"])
                self.assertRegex(by_hash[f"#{tab}/3d"]["note"], r"^\d+ nodes · \d+ edges · Force$")
        agents = by_hash["#agents/orbit"]
        self.assertEqual(agents["toolbar"], ["Priority", "Day/Night", "Status"])
        self.assertEqual(agents["spot"], {"hidden": True, "channels": CHOICE_CHANNELS})
        hierarchy = by_hash["#agents/hierarchy"]
        self.assertEqual([office for office, _ in hierarchy["org"]], ["chair", "identity/oidc", "work/s1", "work/s2"])
        self.assertEqual(hierarchy["toggles"], [["Collapse: Operator", "true"], ["Collapse: Chair", "true"], ["Collapse: identity", "true"], ["Collapse: Presidents", "true"]])
        self.assertEqual(hierarchy["toolbar"], agents["toolbar"])
        self.assertGreaterEqual(len(hierarchy["order"]), 2)
        self.assertEqual(by_hash["#agents/tree"]["spawn"][0], ["operator", None])
        self.assertIn(["twig", "true"], by_hash["#agents/tree"]["spawn"])
        self.assertIn(["twig", "false"], by_hash["#agents/tree"]["spawn"])
        artifacts = by_hash["#artifacts/tree"]
        self.assertEqual(artifacts["deletes"], [["Delete all merged", True, "Delete all merged blocked: Secret Service locked"]])
        for state in ("merged by pr#12 into main", "upstream gone", "protected", "1 commits unpushed", "clean", "not committed: 0 staged, 0 changed, 1 new", "gc skips: ignored files beyond known caches: notes.txt"):
            with self.subTest(state=state):
                self.assertIn(state, artifacts["states"])
        for view in ("orbit", "chord"):
            with self.subTest(view=view):
                self.assertGreaterEqual(by_hash[f"#artifacts/{view}"]["marks"], 4)
        self.assertEqual((artifacts["flows"], artifacts["openWork"]), (["file", "invalid"], 5))
        for state in ("open work: not committed, task open", "open work: unpushed, task open", "open work: not merged", "3 worktrees with open work"):
            with self.subTest(state=state):
                self.assertIn(state, artifacts["states"])
        self.assertEqual(by_hash["#artifacts/chord"]["flowEdges"], ["pull", "push"])
        order = ["work/feature", "work/docs", "work/stage", "queue/gate-3", "work/old", "operator/push"]
        listed = by_hash["#tasks/list"]
        self.assertEqual(listed["views"], ["List", "Board", "RASCI", "Gantt", "Burndown and burnup", "3D"])
        self.assertEqual(by_hash["#tasks/3d"]["layouts"], ["Force", "Time"])
        self.assertTrue(by_hash["#tasks/3d"]["canvas"], by_hash["#tasks/3d"]["note"])
        self.assertRegex(by_hash["#tasks/3d"]["note"], r"^6 nodes · \d+ edges · Force$")
        self.assertEqual(listed["taskFilters"], [["all", "true", "6"], ["open", "false", "4"], ["work", "false", "4"], ["operator", "false", "2"], ["grant", "false", "1"], ["ended", "false", "2"]])
        self.assertEqual(listed["taskRows"], [[task, task not in ("work/old", "operator/push")] for task in order])
        self.assertEqual(listed["flows"], ["file", "file"])
        self.assertEqual(by_hash["#tasks/board"]["columns"], [["queued", ["work/docs", "queue/gate-3"]], ["running", ["work/feature", "work/stage"]], ["done", []]])
        self.assertEqual(by_hash["#tasks/rasci"]["matrix"], [6, 6, "CIRARASRARAR"])
        self.assertEqual([probe["taskFilters"][3][1] for probe in probes if probe["hash"] == "#tasks/operator"], ["true"] * len(WIDTHS))
        extra = data["results"][len(probes) :]
        self.assertEqual([probe["hash"] for probe in extra[:3]], ["#agents/orbit", "#agents/chord", "#artifacts/tree"])
        actions = extra[3]
        self.assertNotIn("error", actions)
        self.assertEqual(actions["keys"], ["#agents/chord", "#artifacts/tree", "#tasks/3d", "#home", "#stream"])
        self.assertEqual(actions["ambience"], ["sky-look", "music-toggle", "leitstand", "notify"])
        self.assertEqual((actions["settingsUnlabelled"], actions["popupUnlabelled"]), (0, 0))
        self.assertEqual((actions["sections"], actions["radioFields"]), (["Ambience", "Location", "Appearance", "Music", "Notifications", "Passkey"], 0))
        for tool in ("Radio …", "Cancel mayday", "Priority …", "Drain", "Suspend", "Resume", "Firewall …", "Settings …", "Look at the sky", "Toggle control room", "Enable notifications"):
            with self.subTest(tool=tool):
                self.assertTrue(any(tool in entry for entry in actions["palette"]), actions["palette"])
        self.assertEqual(actions["popup"], [["post", True], ["call", False]])
        self.assertEqual(actions["centred"], [True, "none"])
        calm, chips = extra[4:]
        self.assertRegex(calm["note"], r"Force · without motion \(prefers-reduced-motion\)$")
        self.assertEqual({key: value for key, value in chips["inbox"].items() if key != "counted"}, {"hash": "#tasks/operator", "items": chips["inbox"]["counted"], "pressed": "true", "current": ["Tasks"]})
        self.assertGreaterEqual(chips["inbox"]["items"], 1)
        self.assertEqual(chips["back"], {"hash": "#tasks/list", "rows": [["queue/gate-3", "Queue job"]]})

    def test_chromium_keeps_the_3d_camera_through_two_state_refreshes_at_three_widths(self):
        steps = [{"width": width, "height": height, "url": f"{self.base}?{width}#agents/3d", "wait": 900, "probe": CAMERA, "shot": self.shot(f"{width}-agents-3d-steady-camera")} for width, height in WIDTHS]
        data = self.drive(steps, None, init=GRAPH_HOOK)
        (OUT / "chromium-camera.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        for result, (width, _) in zip(data["results"], WIDTHS, strict=True):
            with self.subTest(width=width):
                self.assertNotIn("error", result)
                self.assertTrue(result["hooked"], result)
                self.assertGreater(math.dist(result["built"], result["moved"]), 1, result)
                for refresh in result["refreshes"]:
                    self.assertEqual((refresh["rebuilt"], refresh["settled"]), (True, True), result)
                    self.assertLess(math.dist(refresh["camera"], result["moved"]), 0.01, result)
                self.assertGreater(math.dist(result["reset"], result["moved"]), 1, result)

    def check_presence(self, browser: str, driver: str, binary: str) -> None:
        """Args:
            browser: the file name prefix of the screenshots and the result.
            driver: the browser driver script next to this file.
            binary: the browser to drive.
        """
        record = {"status": "busy", "statusUpdatedAt": int(time.time() * 1000), "name": "Skills session", "running": True}
        self.httpd.hub.agent_sessions.write_text(json.dumps({"written": time.time(), "sessions": {"s1": record}}), encoding="utf-8")
        steps = []
        for width, height in WIDTHS:
            steps += [
                {"width": width, "height": height, "url": f"{self.base}?{width}#agents/orbit", "wait": 1200, "probe": PRESENCE_WALK, "shot": str(OUT / f"{browser}-{width}-agents-presence.png")},
                {"width": width, "height": height, "url": f"{self.base}?{width}-reloaded#agents/orbit", "wait": 1200, "probe": PRESENCE_READ, "shot": str(OUT / f"{browser}-{width}-agents-presence-3d.png")},
            ]
        data = self.drive(steps, None, driver, binary)
        (OUT / f"{browser}-presence.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "(style-src-elem)" not in error and "/favicon.ico" not in error], [])
        pair = ["dead", "working"]
        order = ["working", "alive", "sleeping", "suspending", "unreachable", "dead", "faces"]
        for index, (width, _) in enumerate(WIDTHS):
            walk, read = data["results"][2 * index : 2 * index + 2]
            with self.subTest(width=width):
                self.assertNotIn("error", walk)
                self.assertNotIn("error", read)
                self.assertEqual(walk["views"], {"orbit": pair, "chord": pair, "swimlane": pair, "tree": pair, "hierarchy": ["dead", "dead", "working", "working"]})
                self.assertEqual((walk["motion"], walk["profile"]), ("presence-spin", ["working", "Working", "Working"]))
                self.assertGreaterEqual(walk["shown"][0], 3, walk["shown"])
                self.assertEqual(walk["shown"][1], 2)
                self.assertEqual(walk["before"], [[look, True] for look in order])
                self.assertEqual((walk["hidden"], walk["orbit"], walk["wide"]), ([0, 1], ["dead"], False))
                self.assertEqual(read["boxes"], [[look, look not in ("working", "faces")] for look in order])
                self.assertEqual((read["orbit"], read["back"], read["restored"]), (["dead"], pair, walk["shown"]))

    def test_chromium_shows_agent_states_and_3d_faces_switchable_through_a_reload_at_three_widths(self):
        self.check_presence("chromium", "cdp.mjs", os.environ.get("CHROMIUM", "chromium"))

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_shows_agent_states_and_3d_faces_switchable_through_a_reload_at_three_widths(self):
        self.check_presence("firefox", "bidi.mjs", os.environ.get("FIREFOX", "firefox"))

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
                self.assertEqual((probe["tabs"], probe["subs"]), (TABS, SUBS))
                self.assertEqual(labelled(probe), {"unlabelled": [], "broken": []})
                self.assertFalse(probe["wide"], "the page scrolls sideways")
                self.assertEqual((probe["panel"], probe["nodeChips"]), (0, 0))
                self.assertTrue(shot.is_file() and shot.stat().st_size > 1000, shot)
                if screen.endswith("/3d"):
                    self.assertTrue(probe["canvas"], probe["note"])


if __name__ == "__main__":
    unittest.main()
