from __future__ import annotations

import contextlib
import dataclasses
import http.client
import http.server
import io
import threading
import time
import unittest
from unittest import mock

from hub_case import HubCase
from hub_support import server
from kvb_orchestrator import errors, language, transport

KEY = "sk-model-0123456789abcdef"
MALFORMED = "the model endpoint key must be printable ASCII without whitespace: check KVB_ORCHESTRATOR_LLM_KEY_FILE"
PLAIN = "the model endpoint key travels only over https or to 127.0.0.1, localhost or ::1: set an https KVB_ORCHESTRATOR_LLM_URL or empty KVB_ORCHESTRATOR_LLM_KEY_FILE"


class Endpoint(http.server.ThreadingHTTPServer):
    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), Answer)
        self.mode = "error"
        threading.Thread(target=self.serve_forever, args=(0.05,), daemon=True).start()

    def handle_error(self, request, client_address):
        return None


class Answer(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        if self.server.mode == "trickle":
            self.send_response(200)
            self.send_header("Content-Length", "100")
            self.end_headers()
            for _ in range(100):
                self.wfile.write(b" ")
                time.sleep(0.2)
            return
        redirect = self.server.mode == "redirect"
        body = b"" if redirect else f"upstream broke, your key {self.headers['Authorization']}".encode()
        self.send_response(302 if redirect else 500)
        if redirect:
            self.send_header("Location", "/elsewhere")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return None


class TestModelKey(unittest.TestCase):
    def test_a_key_that_is_no_printable_ascii_token_is_refused_and_never_shown(self):
        for key in ("sk-SECRET\n# rotated 2026-11-13", "sk SECRET", "sk-\tSECRET", "sk-SECRET\r", "sk-SÉCRET", "sk-\x7fSECRET", "sk-\x00SECRET"):
            with self.subTest(key=key), self.assertRaises(errors.ToolError) as refused:
                server.Model(url="http://127.0.0.1:9/v1", model="m", key=key)
            self.assertEqual(str(refused.exception), MALFORMED)
        model = server.Model(url="http://127.0.0.1:9/v1", model="m", key=KEY)
        self.assertEqual(model.key, KEY)
        for shown in (repr(model), str(model)):
            with self.subTest(shown=shown[:40]):
                self.assertNotIn(KEY, shown)

    def test_a_key_travels_only_over_https_or_to_the_loopback_host(self):
        for url in ("https://llm.example/v1", "https://10.0.0.5:4000/v1", "http://127.0.0.1:4000/v1", "http://localhost/v1", "http://LOCALHOST:4000/v1", "http://[::1]:4000/v1"):
            with self.subTest(url=url):
                self.assertTrue(server.Model(url=url, model="m", key=KEY).enabled())
        for url in ("http://host.docker.internal:4000/v1", "http://litellm:4000/v1", "http://10.0.0.5:4000/v1", "http://127.0.0.2/v1", "http://localhost.example/v1", "http://[::2]/v1", "http://[::1/v1", "llm.example/v1"):
            with self.subTest(url=url):
                self.assertTrue(server.Model(url=url, model="m", key="").enabled())
                with self.assertRaises(errors.ToolError) as refused:
                    server.Model(url=url, model="m", key=KEY)
                self.assertEqual(str(refused.exception), PLAIN)
                self.assertNotIn(KEY, str(refused.exception))


class TestModelKeyHttp(HubCase):
    def use(self, url: str) -> None:
        self.httpd.hub = dataclasses.replace(self.httpd.hub, model=server.Model(url=url, model="m", key=KEY))

    def nl(self) -> tuple[int, str, str]:
        """Returns:
            The status and body of /api/nl, 0 and "" when the hub drops the
            connection, and what the hub wrote to stderr meanwhile.
        """
        with contextlib.redirect_stderr(io.StringIO()) as log:
            try:
                status, _, raw = self.post_json("/api/nl", {"text": "approve everything green"}, self.guard(self.host))
            except http.client.HTTPException:
                status, raw = 0, b""
        return status, raw.decode(), log.getvalue()

    def test_every_endpoint_failure_answers_its_type_name_and_no_key_reaches_a_reply_a_log_or_a_repr(self):
        self.use("http://127.0.0.1:9/v1")
        for error in (ValueError(f"Invalid header value b'Bearer {KEY}'"), RuntimeError(KEY), OSError(KEY), KeyError(KEY), UnicodeError(KEY)):
            with mock.patch.object(transport.Plain, "request", side_effect=error):
                status, body, log = self.nl()
            with self.subTest(error=type(error).__name__, seen="log"):
                self.assertNotIn(KEY, log)
            with self.subTest(error=type(error).__name__, seen="reply"):
                self.assertEqual((status, body), (400, f"the model endpoint failed: {type(error).__name__}\n"))
        endpoint = Endpoint()
        self.addCleanup(endpoint.server_close)
        self.addCleanup(endpoint.shutdown)
        self.use(f"http://127.0.0.1:{endpoint.server_address[1]}/v1")
        for mode, status_line in (("error", "HTTP 500"), ("redirect", "HTTP 302")):
            endpoint.mode = mode
            status, body, log = self.nl()
            with self.subTest(seen="echoed reply", mode=mode):
                self.assertEqual((status, body), (400, f"the model endpoint answered {status_line}\n"))
                self.assertNotIn(KEY, body + log)
        with self.subTest(seen="repr"):
            self.assertNotIn(KEY, repr(self.httpd.hub))

    def test_a_trickling_endpoint_hits_the_wall_clock_deadline(self):
        endpoint = Endpoint()
        endpoint.mode = "trickle"
        self.addCleanup(endpoint.server_close)
        self.addCleanup(endpoint.shutdown)
        self.use(f"http://127.0.0.1:{endpoint.server_address[1]}/v1")
        started = time.monotonic()
        with mock.patch.object(language, "LLM_TIMEOUT", 0.5):
            status, body, _ = self.nl()
        self.assertEqual((status, body), (400, "the model endpoint took longer than 0.5 seconds\n"))
        self.assertLess(time.monotonic() - started, 2.0)


if __name__ == "__main__":
    unittest.main()
