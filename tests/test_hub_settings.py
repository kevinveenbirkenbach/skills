from __future__ import annotations

import json
import unittest

from hub_case import HubCase
from hub_support import STREAMS, Key, key
from kvb_orchestrator import settings


class TestHubSettings(HubCase):
    def settings_payload(self, streams: list[dict]) -> dict:
        colors = {"top": "#101820", "bottom": "#405060", "accent": "#ffaa00"}
        space = {"graph": {"axis": "time", "yaw": -45.5, "pitch": 12.25, "zoom": 1.5, "pan_x": -30.0, "pan_y": 12.0}, "sky": {"azimuth": 225.0, "altitude": 20.0, "fov": 120.0}}
        return {
            **settings.SETTINGS, "latitude": 52.52, "longitude": 13.405, "theme": "custom", "colors": colors, "music": {"on": True, "volume": 0.3}, "streams": streams,
            "space": space,
        }

    def media_src(self) -> str:
        csp = self.get("/")[1]["content-security-policy"]
        return next(part.strip() for part in csp.split(";") if part.strip().startswith("media-src"))

    def prepared(self, payload: dict) -> dict:
        status, _, body = self.post_json("/api/settings/sign", payload, self.guard(self.host))
        self.assertEqual(status, 200, body)
        return json.loads(body)

    def save(self, payload: dict, signer: Key) -> tuple[int, dict, bytes]:
        request = self.prepared(payload)["payload"]
        proof = None if request is None else signer.proof(request, self.origin)
        return self.post_json("/api/settings", {**payload, "proof": proof}, self.guard(self.host))

    def test_a_new_stream_url_needs_the_passkey(self):
        good = self.guard(self.host)
        payload = self.settings_payload(STREAMS)
        self.assertEqual(self.post_json("/api/settings", payload, good)[:3:2], (400, b"not signed: no signature\n"))
        self.assertFalse((self.state / "settings.json").exists())
        signer = self.pin()
        request = self.prepared(payload)["payload"]
        stranger = key(-7, "stranger").proof(request, self.origin)
        self.assertEqual(self.post_json("/api/settings", {**payload, "proof": stranger}, good)[:3:2], (400, b"not signed: the signing key is not pinned\n"))
        self.assertEqual(self.media_src(), "media-src 'self'")
        proof = signer.proof(request, self.origin)
        status, _, body = self.post_json("/api/settings", {**payload, "proof": proof}, good)
        self.assertEqual(status, 200, body)
        self.assertEqual(self.media_src(), "media-src 'self' http://10.0.0.5:8000 https://other.example:8443 https://radio.example")
        moved = self.settings_payload([{**STREAMS[0], "url": "https://radio.example/evening"}, STREAMS[1]])
        self.assertEqual(self.post_json("/api/settings", moved, good)[:3:2], (400, b"not signed: no signature\n"))
        status, _, body = self.save(moved, signer)
        self.assertEqual(status, 200, body)
        self.assertEqual(self.media_src(), "media-src 'self' http://10.0.0.5:8000 https://radio.example")
        self.assertEqual(self.post_json("/api/settings", self.settings_payload([]), good)[0], 200)
        self.assertEqual(self.post_json("/api/settings", {**payload, "proof": proof}, good)[:3:2], (400, b"not signed: this signature was already used for this item\n"))
        self.assertEqual(self.save(moved, signer)[0], 200)
        evil = self.settings_payload([*moved["streams"], {**STREAMS[0], "url": "https://evil.example/listen"}])
        self.assertEqual(self.post_json("/api/settings", {**evil, "proof": signer.proof(self.prepared(payload)["payload"], self.origin)}, good)[:3:2], (400, b"not signed: the signature does not list this item\n"))
        self.assertEqual(self.post_json("/api/settings", evil, good)[0], 400)
        self.assertEqual(self.media_src(), "media-src 'self' http://10.0.0.5:8000 https://radio.example")
        status, _, body = self.save(evil, signer)
        self.assertEqual(status, 200, body)
        self.assertIn("https://evil.example", self.media_src())
        for broken in ({**payload, "theme": "neon"}, {**payload, "proof": None}):
            with self.subTest(broken=list(broken)):
                self.assertEqual(self.post_json("/api/settings/sign", broken, good)[0], 400)
        self.assertEqual(self.post_json("/api/settings/sign", payload, self.client())[0], 403)
        self.assertEqual(self.get("/api/settings/sign")[0], 405)

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
                {"threshold": 55},
                {"threshold": "50"},
                {"threshold": None},
                {"on": True},
                {"extra": 1},
            )),
            {**payload, "speech": {}},
            {name: value for name, value in payload.items() if name != "speech"},
            {**payload, "squelch": 1.0},
            {**payload, "sounds": {}},
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
            {**payload, "space": {**payload["space"], "graph": {name: value for name, value in payload["space"]["graph"].items() if name != "pan_y"}}},
            *({**payload, "space": {**payload["space"], "sky": {**payload["space"]["sky"], **change}}} for change in (
                {"azimuth": -1},
                {"azimuth": 360.5},
                {"altitude": 86},
                {"fov": 10},
                {"fov": None},
                {"fov": float("inf")},
                {"zoom": 1},
            )),
            {name: value for name, value in payload.items() if name != "space"},
        ):
            with self.subTest(broken=broken):
                self.assertEqual(self.post_json("/api/settings", broken, good)[0], 400)
        status, _, body = self.save(payload, self.pin())
        self.assertEqual(status, 200, body)
        unresolved = {**payload, "streams": [{**stream, "via": None if stream["url"].startswith("https:") else []} for stream in payload["streams"]]}
        self.assertEqual(json.loads(body)["settings"], unresolved)
        self.assertEqual(json.loads((self.state / "settings.json").read_text(encoding="utf-8")), unresolved)
        self.assertEqual(self.snapshot()["settings"], unresolved)
        self.assertEqual(settings.Settings(self.state / "settings.json").get(), unresolved)
        self.assertEqual(self.get("/api/settings")[0], 405)

    def test_the_hub_keeps_no_tones_squelch_or_read_aloud_filters_since_each_browser_keeps_its_radio_set(self):
        current = self.snapshot()["settings"]
        self.assertFalse({"sounds", "squelch"} & set(current))
        self.assertEqual(current["speech"], {"threshold": 50})
        legacy = (
            {**current, "squelch": 0.35},
            {**current, "sounds": {"radio": {"on": False, "volume": 0.4}}},
            {**current, "speech": {"threshold": 50, "on": True, "classes": ["post", "mayday"], "muted": ["s1"]}},
        )
        for broken in legacy:
            with self.subTest(broken=sorted(broken)):
                self.assertEqual(self.post_json("/api/settings", broken, self.guard(self.host))[0], 400)
        self.assertFalse((self.state / "settings.json").exists())
        self.assertIsNone(self.prepared({**current, "music": {"on": True, "volume": 0.2}})["payload"])

    def test_the_estimation_mode_defaults_to_no_estimate_is_stored_and_survives_a_reload(self):
        self.assertEqual((settings.SETTINGS["estimation"], self.snapshot()["settings"]["estimation"]), ("none", "none"))
        good = self.guard(self.host)
        for wrong in ("Story points", "", None, 1, ["points"]):
            with self.subTest(wrong=wrong):
                self.assertEqual(self.post_json("/api/settings", {**settings.SETTINGS, "estimation": wrong}, good)[0], 400)
        self.assertEqual(self.post_json("/api/settings", {key: value for key, value in settings.SETTINGS.items() if key != "estimation"}, good)[0], 400)
        status, _, body = self.save({**self.snapshot()["settings"], "estimation": "points"}, self.pin())
        self.assertEqual((status, json.loads(body)["settings"]["estimation"]), (200, "points"))
        self.assertEqual(json.loads((self.state / "settings.json").read_text(encoding="utf-8"))["estimation"], "points")
        self.assertEqual(settings.Settings(self.state / "settings.json").get()["estimation"], "points")
        self.assertEqual(self.snapshot()["settings"]["estimation"], "points")
        older = {key: value for key, value in self.settings_payload(STREAMS).items() if key != "estimation"}
        (self.state / "settings.json").write_text(json.dumps(older), encoding="utf-8")
        self.assertEqual(settings.Settings(self.state / "settings.json").get()["estimation"], "none")

    def test_the_trend_defaults_to_off_over_seven_days_is_validated_stored_and_survives_a_reload(self):
        self.assertEqual((settings.SETTINGS["trend"], self.snapshot()["settings"]["trend"]), ({"mode": "off", "days": 7}, {"mode": "off", "days": 7}))
        good = self.guard(self.host)
        wrongs = [{"mode": mode, "days": 7} for mode in ("linear", "Regression", "", None, 1)]
        wrongs += [{"mode": "velocity", "days": days} for days in (0, 366, 1.5, True, "7", None, -3)]
        wrongs += [{"mode": "velocity"}, {"days": 7}, {"mode": "velocity", "days": 7, "extra": 1}, "velocity", ["velocity", 7]]
        for wrong in wrongs:
            with self.subTest(wrong=wrong):
                self.assertEqual(self.post_json("/api/settings", {**settings.SETTINGS, "trend": wrong}, good)[0], 400)
        self.assertEqual(self.post_json("/api/settings", {key: value for key, value in settings.SETTINGS.items() if key != "trend"}, good)[0], 400)
        self.assertEqual(self.snapshot()["settings"]["trend"], {"mode": "off", "days": 7})
        for chosen in ({"mode": "regression", "days": 7}, {"mode": "velocity", "days": 1}, {"mode": "velocity", "days": 365}, {"mode": "velocity", "days": 14}):
            with self.subTest(chosen=chosen):
                self.assertIsNone(self.prepared({**self.snapshot()["settings"], "trend": chosen})["payload"])
                status, _, body = self.post_json("/api/settings", {**self.snapshot()["settings"], "trend": chosen, "proof": None}, good)
                self.assertEqual((status, json.loads(body)["settings"]["trend"]), (200, chosen))
        self.assertEqual(json.loads((self.state / "settings.json").read_text(encoding="utf-8"))["trend"], {"mode": "velocity", "days": 14})
        self.assertEqual(settings.Settings(self.state / "settings.json").get()["trend"], {"mode": "velocity", "days": 14})
        self.assertEqual(self.snapshot()["settings"]["trend"], {"mode": "velocity", "days": 14})
        older = {key: value for key, value in self.settings_payload(STREAMS).items() if key != "trend"}
        (self.state / "settings.json").write_text(json.dumps(older), encoding="utf-8")
        self.assertEqual(settings.Settings(self.state / "settings.json").get()["trend"], {"mode": "off", "days": 7})

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
        streams = [*STREAMS, {**STREAMS[0], "name": "Same", "url": "https://Radio.Example:443/second?x=1"}]
        status, _, body = self.save(self.settings_payload(streams), self.pin())
        self.assertEqual(status, 200, body)
        origins = ["http://10.0.0.5:8000", "https://other.example:8443", "https://radio.example"]
        self.assertEqual(self.media_src(), " ".join(["media-src 'self'", *origins]))
        csp = self.get("/")[1]["content-security-policy"]
        self.assertIn("connect-src 'self';", csp)
        self.assertEqual(csp.count("radio.example"), 1)
        self.assertEqual(self.snapshot()["media"], origins)


if __name__ == "__main__":
    unittest.main()
