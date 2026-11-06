from __future__ import annotations

import json
import math
import os
import time
import unittest
from unittest import mock

from hub_case import HubCase
from hub_support import iso
from kvb_hub import lifetimes, names, orbits


class TestHubGraph(HubCase):
    def test_affinity_pulls_talking_agents_together(self):
        now = 1_000_000.0
        nodes = [{"id": name, "kind": kind, "parent": None} for name, kind in (("Operator", "operator"), ("Maintainer", "chair"), ("Alpha", "session"), ("Beta", "session"), ("Gamma", "session"))]
        talk = [{"ts": now - n * 60, "source": "Alpha" if n % 2 else "Beta", "targets": ["Beta" if n % 2 else "Alpha"], "class": "direct", "text": "x"} for n in range(20)]

        def spot(layout: dict, name: str) -> tuple[float, float]:
            place = layout["orbit"][name]
            return place["radius"] * math.cos(place["angle"]), place["radius"] * math.sin(place["angle"])

        layout = orbits.affinity(nodes, talk, {}, [], now, str)
        self.assertEqual(layout, orbits.affinity(nodes, talk, {}, [], now, str))
        self.assertEqual(set(layout["order"]), {"Maintainer", "Alpha", "Beta", "Gamma"})
        self.assertLess(math.dist(spot(layout, "Alpha"), spot(layout, "Beta")), math.dist(spot(layout, "Alpha"), spot(layout, "Gamma")))
        self.assertLess(math.dist(spot(layout, "Alpha"), spot(layout, "Beta")), math.dist(spot(layout, "Beta"), spot(layout, "Gamma")))
        self.assertLess(layout["orbit"]["Alpha"]["radius"], layout["orbit"]["Gamma"]["radius"])
        self.assertEqual(layout["orbit"]["Gamma"]["radius"], orbits.OUTER)
        old = [{**row, "ts": now - 86400} for row in talk]
        fresh = [{"ts": now - 60, "source": "Gamma", "targets": ["Beta"], "class": "direct", "text": "x"}] * 3
        later = orbits.affinity(nodes, old + fresh, {}, [], now, str)
        self.assertLess(math.dist(spot(later, "Beta"), spot(later, "Gamma")), math.dist(spot(later, "Alpha"), spot(later, "Beta")))
        shared = orbits.affinity(nodes, [], {"work/x": {"status": "running", "worker": "Alpha", "roles": {"Gamma": "C"}}}, [], now, str)
        self.assertLess(math.dist(spot(shared, "Alpha"), spot(shared, "Gamma")), math.dist(spot(shared, "Alpha"), spot(shared, "Beta")))
        self.assertIn("layout", self.snapshot()["graph"])

    def test_the_track_samples_the_affinity_over_the_window_on_request(self):
        now = time.time()
        news = [{"ts": now - 3000 + n * 60, "from": "Beta" if n % 2 else "Alpha", "to": ["Alpha" if n % 2 else "Beta"], "text": "x"} for n in range(30)]
        news.append({"ts": now - 100, "from": "Gamma", "to": [], "text": "here"})
        self.write_council({"news.jsonl": self.jsonl(news)})
        self.assertEqual(self.snapshot()["graph"]["track"], [])
        status, _, body = self.get(f"/api/state?from={int(now - 3600)}&track=1")
        self.assertEqual(status, 200, body)
        state = json.loads(body)
        graph, track = state["graph"], state["graph"]["track"]
        stamps = [sample["ts"] for sample in track]
        self.assertEqual(len(track), orbits.TRACK_STEPS + 1)
        self.assertEqual((stamps[0], stamps[-1]), (state["first"], state["until"]))
        self.assertEqual(stamps, sorted(stamps))
        self.assertEqual(track[-1]["orbit"], graph["layout"]["orbit"])
        for sample in track:
            self.assertEqual(set(sample["orbit"]), set(graph["layout"]["order"]))
        keys = {node["label"]: node["id"] for node in graph["nodes"]}
        self.assertEqual([sample["orbit"][keys["Gamma"]]["radius"] for sample in track[:-1]], [orbits.OUTER] * orbits.TRACK_STEPS)
        self.assertLess(track[0]["orbit"][keys["Alpha"]]["radius"], orbits.OUTER)
        self.assertLess(track[-1]["orbit"][keys["Alpha"]]["radius"], track[-1]["orbit"][keys["Gamma"]]["radius"])
        for broken in ("0", "yes", "1&track=1"):
            with self.subTest(broken=broken):
                self.assertEqual(self.get(f"/api/state?track={broken}")[0], 400)

    def test_a_rename_keeps_the_session_and_shows_the_name_of_its_moment(self):
        now = time.time()
        before = {"ts": now - 100, "from": "Skills", "to": ["Docs"], "text": "before"}
        claim = {"office": "work/s1", "session": "s1", "runtime": "claude", "name": "Skills", "since": iso(now - 200), "beat": now, "work": "x"}
        self.write_council({"work/s1/claim.json": claim, "news.jsonl": self.jsonl([before])})
        self.assertEqual([row["agent"] for row in self.events("kinds=radio")["events"]], ["Skills"])
        folder = self.projects / "-repo" / "s1"
        folder.mkdir(parents=True)
        title = folder / "custom-title.json"
        title.write_text(json.dumps({"customTitle": "IAM"}), encoding="utf-8")
        os.utime(title, (now - 50, now - 50))
        self.write_council({"news.jsonl": self.jsonl([before, {"ts": now - 20, "from": "IAM", "to": ["Docs"], "text": "after"}])})
        with mock.patch.object(names, "TITLE_SCAN", 0):
            rows = self.events("kinds=radio,rename")["events"]
        self.assertEqual([(row["kind"], row["session"], row["agent"], row["now"]) for row in rows], [
            ("radio", "s1", "Skills", "IAM"),
            ("rename", "s1", "IAM", "IAM"),
            ("radio", "s1", "IAM", "IAM"),
        ])
        self.assertEqual(rows[1]["title"], "Skills heißt jetzt IAM")
        self.assertAlmostEqual(rows[1]["ts"], now - 50, places=3)
        for name in ("Skills", "IAM"):
            with self.subTest(name=name):
                self.assertEqual([row["text"] for row in self.events(f"kinds=radio&agent={name}")["events"]], ["before", "after"])
        snapshot = self.snapshot()
        self.assertEqual([row["speech"] for row in snapshot["radio"]], ["Docs, Docs, this is Skills, before, over", "Docs, Docs, this is IAM, after, over"])
        self.assertEqual({row["voice"] for row in snapshot["radio"]}, {self.httpd.hub.speech.voice_of("s1")})
        live = {node["id"]: node for node in snapshot["graph"]["nodes"]}
        self.assertEqual((live["s1"]["label"], live["s1"]["names"]), ("IAM", ["Skills", "IAM"]))
        self.assertEqual([entry["name"] for entry in live["s1"]["timeline"]], ["Skills", "IAM"])
        for entry, since in zip(live["s1"]["timeline"], (now - 200, now - 50), strict=True):
            self.assertAlmostEqual(entry["since"], since, places=3)
        self.assertEqual(live["Operator"]["timeline"], [{"name": "Operator", "since": snapshot["until"]}])
        status, _, body = self.get(f"/api/state?from={int(now - 300)}&to={int(now - 80)}")
        self.assertEqual(status, 200, body)
        replay = {node["id"]: node for node in json.loads(body)["graph"]["nodes"]}
        self.assertEqual(replay["s1"]["label"], "Skills")
        self.assertEqual(replay["s1"]["timeline"], live["s1"]["timeline"])
        stored = json.loads((self.state / "names.json").read_text(encoding="utf-8"))["entries"]
        self.assertEqual([(entry["session"], entry["name"], entry["source"]) for entry in stored], [("s1", "Skills", "claim"), ("s1", "IAM", "title")])

    def test_birth_and_death_dates_follow_the_transcripts(self):
        self.assertEqual((lifetimes.lifetime_stamp(1_700_000_000.0), lifetimes.lifetime_stamp(None)), ("2023-11-14T22:13Z", ""))
        now = time.time()
        self.claim("s1", "Skills")
        main = self.projects / "-repo" / "s1.jsonl"
        subagents = self.projects / "-repo" / "s1" / "subagents"
        subagents.mkdir(parents=True)

        def line(ts: float) -> dict:
            return {"type": "user", "sessionId": "s1", "timestamp": iso(ts), "message": {"role": "user", "content": "x"}}

        main.write_text(self.jsonl([line(now - 3 * 86400), line(now - 2 * 86400)]), encoding="utf-8")
        for ident, finished in (("abc", True), ("def", False)):
            (subagents / f"agent-{ident}.meta.json").write_text(json.dumps({"agentType": "Explore", "description": ident, "spawnDepth": 1, "finished": finished}), encoding="utf-8")
            (subagents / f"agent-{ident}.jsonl").write_text(self.jsonl([line(now - 3 * 86400 + 60), line(now - 3 * 86400 + 120)]), encoding="utf-8")

        def life() -> dict:
            status, _, body = self.get("/api/subagents?session=s1")
            self.assertEqual(status, 200, body)
            return json.loads(body)

        born, ended = lifetimes.lifetime_stamp(now - 3 * 86400), lifetimes.lifetime_stamp(now - 2 * 86400)
        sub_born, sub_died = lifetimes.lifetime_stamp(now - 3 * 86400 + 60), lifetimes.lifetime_stamp(now - 3 * 86400 + 120)
        data = life()
        self.assertEqual((data["born"], data["died"], data["until"]), (born, "", None))
        self.assertAlmostEqual(data["since"], now - 3 * 86400, places=3)
        self.assertEqual([(row["id"], row["born"], row["died"]) for row in data["subagents"]], [("abc", sub_born, sub_died), ("def", sub_born, "")])
        self.assertAlmostEqual(data["subagents"][0]["until"], now - 3 * 86400 + 120, places=3)
        self.assertEqual(data["subagents"][1]["until"], None)
        for row in data["subagents"]:
            self.assertAlmostEqual(row["since"], now - 3 * 86400 + 60, places=3)
        os.utime(main, (now - 2 * 86400, now - 2 * 86400))
        self.assertEqual(life()["died"], "")
        self.write_council({"work/s1/claim.json": {"office": "work/s1", "session": "s1", "runtime": "claude", "name": "Skills", "since": iso(now - 4 * 86400), "beat": now - 2 * 86400, "work": "x"}})
        self.assertEqual((life()["born"], life()["died"]), (born, ended))
        self.assertAlmostEqual(life()["until"], now - 2 * 86400, places=3)


if __name__ == "__main__":
    unittest.main()
