from __future__ import annotations

import json
import unittest

from hub_case import HubCase
from hub_support import STREAMS
from kvb_orchestrator import settings


class TestHubSettings(HubCase):
    def settings_payload(self, streams: list[dict]) -> dict:
        colors = {"top": "#101820", "bottom": "#405060", "accent": "#ffaa00"}
        speech = {"on": True, "classes": ["call", "mayday", "pan-pan"], "muted": ["name:Docs", "s1"]}
        space = {"graph": {"axis": "time", "yaw": -45.5, "pitch": 12.25, "zoom": 1.5, "pan_x": -30.0, "pan_y": 12.0}, "sky": {"azimuth": 225.0, "altitude": 20.0, "fov": 120.0}}
        return {
            **settings.SETTINGS, "latitude": 52.52, "longitude": 13.405, "theme": "custom", "colors": colors, "music": {"on": True, "volume": 0.3}, "streams": streams, "speech": speech,
            "space": space,
        }

    def media_src(self) -> str:
        csp = self.get("/")[1]["content-security-policy"]
        return next(part.strip() for part in csp.split(";") if part.strip().startswith("media-src"))

    def test_settings_are_guarded_validated_and_persisted(self):
        self.assertEqual(self.snapshot()["settings"], settings.SETTINGS)
        payload = self.settings_payload(STREAMS)
        good = self.guard(self.host)
        for headers in ({k: v for k, v in good.items() if k != "X-Kvb-Orchestrator"}, {k: v for k, v in good.items() if k != "Origin"}, {**good, "Origin": "http://evil.example"}):
            with self.subTest(headers=headers):
                self.assertEqual(self.post_json("/api/settings", payload, headers)[0], 403)
        self.assertFalse((self.state / "settings.json").exists())
        stream = STREAMS[0]
        for broken in (
            {**payload, "latitude": 91},
            {**payload, "theme": "neon"},
            {**payload, "extra": 1},
            {**payload, "colors": {**payload["colors"], "accent": "red"}},
            {**payload, "music": {"on": "yes", "volume": 0.3}},
            {**payload, "streams": [{**stream, "url": "javascript:alert(1)"}]},
            {**payload, "streams": [{**stream, "url": "https://evil.example;script-src"}]},
            {**payload, "streams": [{**stream, "url": "https://a.example 'unsafe-inline'"}]},
            {**payload, "streams": [{**stream, "url": "https://user:pw@a.example/"}]},
            {**payload, "streams": [{**stream, "days": [7]}]},
            {**payload, "streams": [{**stream, "days": [1, 1]}]},
            {**payload, "streams": [{**stream, "from": "09:00", "to": "09:00"}]},
            {**payload, "streams": [{**stream, "to": "25:00"}]},
            *({**payload, "speech": {**payload["speech"], **change}} for change in (
                {"on": "yes"},
                {"classes": ["call", "pan-pan"]},
                {"classes": ["mayday", "shout"]},
                {"classes": ["mayday", "mayday"]},
                {"classes": "mayday"},
                {"muted": "s1"},
                {"muted": ["s1", "s1"]},
                {"muted": ["two\nlines"]},
                {"muted": [""]},
                {"muted": [7]},
                {"muted": [f"s{n}" for n in range(settings.MUTED_LIMIT + 1)]},
                {"extra": 1},
            )),
            {**payload, "speech": {"on": True, "classes": ["mayday"]}},
            {key: value for key, value in payload.items() if key != "speech"},
            *({**payload, "space": change} for change in (
                "flat",
                {"graph": payload["space"]["graph"]},
                {**payload["space"], "extra": 1},
                {**payload["space"], "sky": [180, 0, 180]},
            )),
            *({**payload, "space": {**payload["space"], "graph": {**payload["space"]["graph"], **change}}} for change in (
                {"axis": "depth"},
                {"axis": 1},
                {"yaw": 180.5},
                {"pitch": "up"},
                {"zoom": True},
                {"zoom": 0.2},
                {"pan_x": 2001},
                {"pan_y": float("nan")},
                {"roll": 0},
            )),
            {**payload, "space": {**payload["space"], "graph": {key: value for key, value in payload["space"]["graph"].items() if key != "pan_y"}}},
            *({**payload, "space": {**payload["space"], "sky": {**payload["space"]["sky"], **change}}} for change in (
                {"azimuth": -1},
                {"azimuth": 360.5},
                {"altitude": 86},
                {"fov": 10},
                {"fov": None},
                {"fov": float("inf")},
                {"zoom": 1},
            )),
            {key: value for key, value in payload.items() if key != "space"},
        ):
            with self.subTest(broken=broken):
                self.assertEqual(self.post_json("/api/settings", broken, good)[0], 400)
        status, _, body = self.post_json("/api/settings", payload, good)
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body), payload)
        self.assertEqual(json.loads((self.state / "settings.json").read_text(encoding="utf-8")), payload)
        self.assertEqual(self.snapshot()["settings"], payload)
        self.assertEqual(settings.Settings(self.state / "settings.json").get(), payload)
        self.assertEqual(self.get("/api/settings")[0], 405)
        shuffled = {**payload, "speech": {"on": False, "classes": ["mayday", "broadcast", "security"], "muted": ["s1", "Operator", "name:Docs"]}}
        status, _, body = self.post_json("/api/settings", shuffled, good)
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)["speech"], {"on": False, "classes": ["broadcast", "mayday", "security"], "muted": ["Operator", "name:Docs", "s1"]})

    def test_settings_written_before_the_radio_filter_keep_their_values(self):
        older = {key: value for key, value in self.settings_payload(STREAMS).items() if key != "speech"}
        (self.state / "settings.json").write_text(json.dumps(older), encoding="utf-8")
        loaded = settings.Settings(self.state / "settings.json").get()
        self.assertEqual(loaded, {**older, "speech": settings.SETTINGS["speech"]})
        flat = {key: value for key, value in older.items() if key != "space"}
        (self.state / "settings.json").write_text(json.dumps(flat), encoding="utf-8")
        self.assertEqual(settings.Settings(self.state / "settings.json").get(), {**flat, "speech": settings.SETTINGS["speech"], "space": settings.SETTINGS["space"]})
        (self.state / "settings.json").write_text(json.dumps({**older, "unknown": 1}), encoding="utf-8")
        self.assertEqual(settings.Settings(self.state / "settings.json").get(), settings.SETTINGS)

    def test_csp_media_src_lists_exactly_the_stream_origins(self):
        self.assertEqual(self.media_src(), "media-src 'self'")
        streams = [*STREAMS, {**STREAMS[0], "name": "Gleich", "url": "https://Radio.Example:443/zweiter?x=1"}]
        status, _, body = self.post_json("/api/settings", self.settings_payload(streams), self.guard(self.host))
        self.assertEqual(status, 200, body)
        origins = ["http://10.0.0.5:8000", "https://other.example:8443", "https://radio.example"]
        self.assertEqual(self.media_src(), " ".join(["media-src 'self'", *origins]))
        csp = self.get("/")[1]["content-security-policy"]
        self.assertIn("connect-src 'self';", csp)
        self.assertEqual(csp.count("radio.example"), 1)
        self.assertEqual(self.snapshot()["media"], origins)


if __name__ == "__main__":
    unittest.main()
