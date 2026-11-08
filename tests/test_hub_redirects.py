from __future__ import annotations

import http.server
import json
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

from hub_case import HubCase
from hub_support import key, signing
from kvb_orchestrator import settings
from kvb_orchestrator.errors import ToolError
from kvb_orchestrator.redirects import (
    DEADLINE_HOPS,
    HOP_LIMIT,
    RETRY_SECONDS,
    Redirects,
    dial,
    global_address,
    media_source,
)

NODES = ("f111", "f121", "d111", "f131")
STATION = "https://station.radio.test/dlf/01/high/aac/stream.aac?aggregator=web"
NAMES = ("radio.test", "*.radio.test", "cdn.test", "*.cdn.test", "*.mid.test")
TIMEOUT = 0.5
STREAMED = 3.0
MUSIC_ON = {"on": True, "volume": 0.4}


class Cdn(http.server.BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return

    def answer(self, status: int, location: str | None) -> None:
        self.send_response(status)
        if location is not None:
            self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def stream(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "audio/aac")
        self.end_headers()
        deadline = time.monotonic() + STREAMED
        while time.monotonic() < deadline:
            self.wfile.write(bytes(4096))
            time.sleep(0.01)

    def drip(self) -> None:
        self.wfile.write(b"HTTP/1.1 302 Found\r\n")
        deadline = time.monotonic() + STREAMED
        while time.monotonic() < deadline:
            self.wfile.write(b"X-Drip: 1\r\n")
            time.sleep(TIMEOUT / 2)

    def do_GET(self) -> None:
        host = self.headers["Host"].split(":")[0]
        self.server.asked.append(host)
        try:
            self.route(host, len(self.server.asked))
        except OSError:
            return

    def route(self, host: str, count: int) -> None:
        if host in self.server.broken:
            self.answer(302, None)
        elif host == "station.radio.test":
            self.answer(302, f"https://{NODES[count % len(NODES)]}.cdn.test/ard/dlf/01/aac/192/stream.aac?aggregator=web&token=t{count}")
        elif host == "chain.radio.test":
            self.answer(301, "https://edge.mid.test/hop")
        elif host == "edge.mid.test":
            self.answer(307, "https://f111.cdn.test:8443/ard/live.aac")
        elif host == "moved.radio.test" and self.path == "/a":
            self.answer(302, "/b")
        elif host == "plain.radio.test":
            self.answer(302, "http://f111.cdn.test/live")
        elif host == "loop.radio.test":
            self.answer(302, f"/hop{count}")
        elif host == "short.radio.test":
            self.answer(302, "https://cdn.test/live")
        elif host == "slow.radio.test":
            time.sleep(TIMEOUT * 3)
            self.answer(200, None)
        elif host == "drip.radio.test":
            self.drip()
        elif host == "badloc.radio.test":
            self.answer(302, "https://[x")
        else:
            self.stream()


class CdnServer(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request: object, client_address: object) -> None:
        return


class FakeCdn:
    def __init__(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        key, cert = Path(self.folder.name) / "key.pem", Path(self.folder.name) / "cert.pem"
        names = ",".join(f"DNS:{name}" for name in NAMES)
        subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256", "-nodes", "-keyout", str(key), "-out", str(cert), "-days", "1", "-subj", "/CN=radio.test", "-addext", f"subjectAltName={names}"],
            capture_output=True, timeout=60, check=True,
        )
        served = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        served.load_cert_chain(cert, key)
        self.httpd = CdnServer(("127.0.0.1", 0), Cdn)
        self.httpd.socket = served.wrap_socket(self.httpd.socket, server_side=True)
        self.httpd.asked = []
        self.httpd.broken = set()
        self.dialed: list[tuple[str, int, bool]] = []
        self.trusted = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self.trusted.load_verify_locations(cert)
        self.thread = threading.Thread(target=self.httpd.serve_forever, args=(0.05,), daemon=True)
        self.thread.start()

    def dial(self, host: str, port: int, timeout: float, public: bool) -> socket.socket:
        self.dialed.append((host, port, public))
        return socket.create_connection(("127.0.0.1", self.httpd.server_address[1]), timeout)

    def redirects(self, tls: ssl.SSLContext) -> Redirects:
        return Redirects(tls=tls, dial=self.dial, timeout=TIMEOUT)

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(10)
        self.folder.cleanup()


CDN: list[FakeCdn] = []


def setUpModule() -> None:
    CDN.append(FakeCdn())


def tearDownModule() -> None:
    CDN.pop().close()


def cdn() -> FakeCdn:
    return CDN[0]


class TestRedirects(unittest.TestCase):
    def resolver(self) -> Redirects:
        return cdn().redirects(cdn().trusted)

    def test_a_rotating_cdn_signs_one_wildcard_and_no_body_is_read(self):
        before = len(cdn().dialed)
        began = time.monotonic()
        seen = [self.resolver().via(STATION) for _ in range(4)]
        self.assertLess(time.monotonic() - began, STREAMED / 2)
        self.assertEqual(seen, [["https://*.cdn.test"]] * 4)
        hops = {self.resolver().chain(STATION)[0].split("/")[2] for _ in range(4)}
        self.assertGreater(len(hops), 1, hops)
        self.assertTrue(all(host.endswith(".cdn.test") for host in hops), hops)
        self.assertEqual({port for _, port, _ in cdn().dialed[before:]}, {443})

    def test_every_hop_of_a_chain_is_signed_in_order_with_its_port(self):
        self.assertEqual(self.resolver().via("https://chain.radio.test/listen"), ["https://*.mid.test", "https://*.cdn.test:8443"])
        self.assertIn(("f111.cdn.test", 8443, True), cdn().dialed)

    def test_only_the_signed_station_may_lie_at_a_non_global_address(self):
        port = cdn().httpd.server_address[1]
        self.assertEqual([global_address(text) for text in ("8.8.8.8", "64:ff9b::808:808", "64:ff9b::7f00:1", "::127.0.0.1", "::ffff:127.0.0.1")], [True, True, False, False, False])
        for host in ("127.0.0.1", "2130706433", "::1", "10.0.0.5", "169.254.169.254", "64:ff9b::7f00:1", "::127.0.0.1"):
            with self.subTest(host=host), self.assertRaisesRegex(ToolError, f"{host} has no public address"):
                dial(host, port, TIMEOUT, True)
        dial("127.0.0.1", port, TIMEOUT, False).close()
        before = len(cdn().dialed)
        self.resolver().via("https://chain.radio.test/listen")
        self.assertEqual([public for _, _, public in cdn().dialed[before:]], [False, True, True])

    def test_a_station_answering_byte_by_byte_cannot_hold_a_resolve_past_its_deadline_or_pile_up_threads(self):
        resolver = self.resolver()
        url = "https://drip.radio.test/"
        began = time.monotonic()
        deadline = TIMEOUT * DEADLINE_HOPS
        self.assertEqual(resolver.resolve([url]), {url: (None, f"no answer within {deadline:g} s")})
        self.assertLess(time.monotonic() - began, deadline + 1)
        self.assertEqual(resolver.resolve([url]), {url: (None, "an earlier save still resolves it")})
        self.assertEqual(sum(thread.name == f"redirects {url}" for thread in threading.enumerate()), 1)

    def test_a_same_host_redirect_adds_nothing_and_a_two_label_host_stays_exact(self):
        self.assertEqual(self.resolver().via("https://moved.radio.test/a"), [])
        self.assertEqual(self.resolver().via("https://short.radio.test/"), ["https://cdn.test"])

    def test_an_unresolvable_chain_names_its_cause(self):
        resolver = self.resolver()
        self.assertEqual(resolver.outcome("https://plain.radio.test/"), (None, "redirects to http://f111.cdn.test, which is not https"))
        before = cdn().httpd.asked.count("loop.radio.test")
        self.assertEqual(resolver.outcome("https://loop.radio.test/"), (None, f"redirects more than {HOP_LIMIT} times"))
        self.assertEqual(cdn().httpd.asked.count("loop.radio.test") - before, HOP_LIMIT + 1)
        via, problem = resolver.outcome("https://slow.radio.test/")
        self.assertIsNone(via)
        self.assertIn("timed out", problem)
        cdn().httpd.broken.add("gone.radio.test")
        self.addCleanup(cdn().httpd.broken.discard, "gone.radio.test")
        self.assertEqual(resolver.outcome("https://gone.radio.test/"), (None, "answers 302 without a Location"))
        via, problem = resolver.outcome("https://other.invalid/")
        self.assertIsNone(via)
        self.assertIn("Hostname mismatch", problem)
        via, problem = cdn().redirects(ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)).outcome(STATION)
        self.assertIsNone(via)
        self.assertIn("certificate verify failed", problem)
        via, problem = resolver.outcome("https://badloc.radio.test/")
        self.assertIsNone(via)
        self.assertIn("Invalid IPv6 URL", problem)

    def test_only_https_urls_are_probed(self):
        before = len(cdn().dialed)
        self.assertEqual(self.resolver().resolve(["http://10.0.0.5:8000/nacht", STATION]), {"http://10.0.0.5:8000/nacht": ([], ""), STATION: (["https://*.cdn.test"], "")})
        self.assertEqual(len(cdn().dialed) - before, 2)

    def test_media_sources_widen_one_label_and_pass_the_settings_check(self):
        for url, origin in (
            ("https://f111.rndfnk.com/ard/dlf/01/aac/192/stream.aac?token=t", "https://*.rndfnk.com"),
            ("https://F121.RNDFNK.com:8443/", "https://*.rndfnk.com:8443"),
            ("https://a.b.c.example:443/x", "https://*.b.c.example"),
            ("https://rndfnk.com/x", "https://rndfnk.com"),
            ("https://203.0.113.5/x", "https://203.0.113.5"),
            ("https://bbc.co.uk/x", "https://bbc.co.uk"),
            ("https://a.bbc.co.uk/x", "https://*.bbc.co.uk"),
            ("https://stream.ndr.de/x", "https://*.ndr.de"),
        ):
            with self.subTest(url=url):
                self.assertEqual(media_source(url), origin)
                self.assertEqual(settings.via_origin(origin, "via"), origin)


class TestRedirectSettings(HubCase):
    def redirects(self) -> Redirects:
        return cdn().redirects(cdn().trusted)

    def station(self, url: str, via: list[str]) -> dict:
        return {"name": "DLF", "url": url, "from": "00:00", "to": "24:00", "days": list(range(7)), "on": True, "via": via}

    def payload(self, streams: list[dict]) -> dict:
        return {**settings.SETTINGS, "streams": streams}

    def media_src(self) -> str:
        csp = self.get("/")[1]["content-security-policy"]
        return next(part.strip() for part in csp.split(";") if part.strip().startswith("media-src"))

    def dials(self) -> int:
        return len(cdn().dialed)

    def prepared(self, streams: list[dict]) -> dict:
        status, _, body = self.post_json("/api/settings/sign", self.payload(streams), self.guard(self.host))
        self.assertEqual(status, 200, body)
        return json.loads(body)

    def saved(self, streams: list[dict], proof: dict | None) -> dict:
        status, _, body = self.post_json("/api/settings", {**self.payload(streams), "proof": proof}, self.guard(self.host))
        self.assertEqual(status, 200, body)
        return json.loads(body)

    def signed_and_saved(self, streams: list[dict]) -> dict:
        prepared = self.prepared(streams)
        return self.saved(streams, None if prepared["payload"] is None else self.pin().proof(prepared["payload"], self.origin))

    def music_toggled(self, streams: list[dict]) -> dict:
        status, _, body = self.post_json("/api/settings", {**self.payload(streams), "music": MUSIC_ON, "proof": None}, self.guard(self.host))
        self.assertEqual(status, 200, body)
        return json.loads(body)

    def test_an_agent_cannot_make_the_hub_contact_an_unsigned_origin(self):
        self.pin()
        before = self.dials()
        streams = [self.station("https://attacker.radio.test/exfil?secret=s3cr3t", [])]
        prepared = self.prepared(streams)
        self.assertEqual(set(prepared), {"payload", "challenge", "credentials"})
        self.assertEqual(prepared["payload"]["items"], [signing.item_hash(signing.stream_item(["https://attacker.radio.test"], [streams[0]["url"]]))])
        unsigned = self.post_json("/api/settings", {**self.payload(streams), "proof": None}, self.guard(self.host))
        self.assertEqual(unsigned[:3:2], (400, b"nicht signiert: no signature\n"))
        stranger = {**self.payload(streams), "proof": key(-7, "stranger").proof(prepared["payload"], self.origin)}
        self.assertEqual(self.post_json("/api/settings", stranger, self.guard(self.host))[:3:2], (400, b"nicht signiert: the signing key is not pinned\n"))
        self.assertEqual(self.dials(), before)
        self.assertNotIn("attacker.radio.test", cdn().httpd.asked)
        self.assertFalse((self.state / "settings.json").exists())

    def test_a_signed_save_resolves_and_stores_the_redirect_target(self):
        streams = [self.station(STATION, [])]
        self.assertEqual(self.prepared(streams)["payload"]["items"], [signing.item_hash(signing.stream_item(["https://station.radio.test"], [STATION]))])
        result = self.signed_and_saved(streams)
        self.assertEqual(result["problems"], [])
        self.assertEqual(result["settings"]["streams"][0]["via"], ["https://*.cdn.test"])
        self.assertEqual(settings.Settings(self.state / "settings.json").get(), result["settings"])
        self.assertEqual(self.media_src(), "media-src 'self' https://*.cdn.test https://station.radio.test")
        self.assertEqual(self.snapshot()["media"], ["https://*.cdn.test", "https://station.radio.test"])
        before = self.dials()
        self.assertIsNone(self.prepared(result["settings"]["streams"])["payload"])
        self.assertEqual(self.saved(result["settings"]["streams"], None), result)
        self.assertEqual(self.dials(), before)

    def test_a_music_toggle_with_a_resolved_station_makes_no_dial_even_in_an_outage(self):
        saved = self.signed_and_saved([self.station(STATION, [])])["settings"]
        cdn().httpd.broken.add("station.radio.test")
        self.addCleanup(cdn().httpd.broken.discard, "station.radio.test")
        before = self.dials()
        self.assertEqual(self.music_toggled(saved["streams"]), {"settings": {**saved, "music": MUSIC_ON}, "problems": []})
        self.assertEqual(self.dials(), before)

    def test_a_page_sent_via_is_overwritten(self):
        saved = self.signed_and_saved([self.station(STATION, [])])["settings"]
        result = self.saved([{**saved["streams"][0], "via": ["https://*.evil.test"]}], None)
        self.assertEqual(result["settings"]["streams"][0]["via"], ["https://*.cdn.test"])
        self.assertNotIn("evil", self.media_src())

    def test_a_new_url_at_a_signed_origin_takes_the_passkey_before_any_dial(self):
        saved = self.signed_and_saved([self.station(STATION, [])])["settings"]
        other = self.station("https://station.radio.test/go", [])
        streams = [*saved["streams"], other]
        self.assertEqual(self.prepared(streams)["payload"]["items"], [signing.item_hash(signing.stream_item(["https://station.radio.test"], [other["url"]]))])
        before = self.dials()
        unsigned = self.post_json("/api/settings", {**self.payload(streams), "proof": None}, self.guard(self.host))
        self.assertEqual(unsigned[:3:2], (400, b"nicht signiert: no signature\n"))
        self.assertEqual(self.dials(), before)
        self.assertEqual(self.httpd.hub.settings.get(), saved)

    def test_a_failed_resolution_stays_unresolved_names_the_station_and_retries_once_due(self):
        saved = self.signed_and_saved([self.station(STATION, [])])["settings"]
        cdn().httpd.broken.add("station.radio.test")
        self.addCleanup(cdn().httpd.broken.discard, "station.radio.test")
        crafted = ["https://*.evil.test"]
        other = "https://station.radio.test/other"
        before = self.dials()
        result = self.signed_and_saved([{**saved["streams"][0], "via": crafted}, self.station(other, crafted)])
        self.assertEqual(self.dials() - before, 1)
        self.assertEqual(result["problems"], ["DLF: answers 302 without a Location"])
        self.assertEqual([stream["via"] for stream in result["settings"]["streams"]], [["https://*.cdn.test"], None])
        self.assertEqual(self.media_src(), "media-src 'self' https://*.cdn.test https://station.radio.test")
        cdn().httpd.broken.discard("station.radio.test")
        before = self.dials()
        early = self.music_toggled(result["settings"]["streams"])
        self.assertEqual((self.dials() - before, early["problems"], early["settings"]["streams"][1]["via"]), (0, [], None))
        self.httpd.hub.redirects.tried[other] -= RETRY_SECONDS
        retried = self.music_toggled(early["settings"]["streams"])
        self.assertEqual([stream["via"] for stream in retried["settings"]["streams"]], [["https://*.cdn.test"], ["https://*.cdn.test"]])
        self.assertEqual(retried["problems"], [])

    def test_a_save_that_lands_while_another_resolves_makes_that_one_fail(self):
        saved = self.signed_and_saved([self.station(STATION, [])])["settings"]
        slow = [*saved["streams"], self.station("https://drip.radio.test/", [])]
        proof = self.pin().proof(self.prepared(slow)["payload"], self.origin)
        answers: list[tuple] = []
        racing = threading.Thread(target=lambda: answers.append(self.post_json("/api/settings", {**self.payload(slow), "proof": proof}, self.guard(self.host))))
        racing.start()
        time.sleep(TIMEOUT)
        self.assertEqual(self.music_toggled(saved["streams"])["settings"]["music"], MUSIC_ON)
        racing.join(TIMEOUT * DEADLINE_HOPS + 5)
        self.assertEqual(answers[0][:3:2], (400, b"the settings changed while this save was checked; save again\n"))
        self.assertEqual([stream["url"] for stream in self.httpd.hub.settings.get()["streams"]], [STATION])

    def test_settings_saved_before_redirect_resolution_are_never_dialed_unsigned_and_heal_when_re_added(self):
        legacy = {name: value for name, value in self.station(STATION, []).items() if name != "via"}
        (self.state / "settings.json").write_text(json.dumps(self.payload([legacy])), encoding="utf-8")
        loaded = settings.Settings(self.state / "settings.json").get()
        self.assertEqual(loaded["streams"], [{**legacy, "via": []}])
        self.assertEqual(settings.media_origins(loaded), ["https://station.radio.test"])
        self.httpd.hub.settings.put(loaded, self.httpd.hub.settings.get())
        self.assertIsNone(self.prepared([legacy])["payload"])
        self.assertEqual(self.media_src(), "media-src 'self' https://station.radio.test")
        before = self.dials()
        self.assertEqual(self.music_toggled([legacy])["settings"]["streams"][0]["via"], [])
        self.assertEqual(self.dials(), before)
        self.assertEqual(self.post_json("/api/settings", {**self.payload([]), "proof": None}, self.guard(self.host))[0], 200)
        result = self.signed_and_saved([legacy])
        self.assertGreater(self.dials(), before)
        self.assertEqual(result["settings"]["streams"][0]["via"], ["https://*.cdn.test"])
        self.assertEqual(self.media_src(), "media-src 'self' https://*.cdn.test https://station.radio.test")

    def test_via_holds_only_canonical_https_origins(self):
        for via in (
            "https://cdn.example",
            ["https://*.com"],
            ["https://*.*.cdn.example"],
            ["http://cdn.example"],
            ["https://cdn.example:443"],
            ["https://cdn.example:70000"],
            ["https://cdn.example/path"],
            ["https://user@cdn.example"],
            ["https://cdn.example 'unsafe-inline'"],
            ["https://cdn.example;script-src"],
            ["https://Cdn.example"],
            [7],
            ["https://a.example", "https://a.example"],
            [f"https://n{index}.example" for index in range(settings.VIA_LIMIT + 1)],
        ):
            with self.subTest(via=via):
                self.assertEqual(self.post_json("/api/settings/sign", {**settings.SETTINGS, "streams": [self.station(STATION, via)]}, self.guard(self.host))[0], 400)


if __name__ == "__main__":
    unittest.main()
