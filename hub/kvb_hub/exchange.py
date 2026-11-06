from __future__ import annotations

import json
import re
from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from . import NAME
from .errors import Conflict, EngineError, Missing, ToolError, Unavailable
from .hub import Hub

GUARD = "X-Kvb-Hub"
PLAIN_CSP = "default-src 'none'; frame-ancestors 'none'"
LENGTH = re.compile(r"[0-9]{1,9}")
QUERY_FIELDS = 32


class HubServer(ThreadingHTTPServer):
    daemon_threads = True
    hub: Hub


class Exchange(BaseHTTPRequestHandler):
    server: HubServer
    server_version = NAME
    sys_version = ""
    timeout = 60

    def send(self, status: HTTPStatus, content_type: str, body: bytes, headers: dict[str, str]) -> None:
        self.send_response(status)
        common = {
            "Content-Type": content_type,
            "Content-Length": str(len(body)),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        }
        for name, value in {**common, **headers}.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def send_text(self, status: HTTPStatus, message: str) -> None:
        self.send(status, "text/plain; charset=utf-8", f"{message}\n".encode(), {"Content-Security-Policy": PLAIN_CSP})

    def send_json(self, status: HTTPStatus, payload: dict) -> None:
        self.send(status, "application/json", json.dumps(payload).encode(), {"Content-Security-Policy": PLAIN_CSP})

    def not_allowed(self) -> None:
        self.send_response(HTTPStatus.METHOD_NOT_ALLOWED)
        self.send_header("Allow", "POST")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def answer(self, produce: Callable[[], dict], status: HTTPStatus) -> None:
        self.attempt(produce, lambda payload: self.send_json(status, payload))

    def attempt(self, produce: Callable[[], object], deliver: Callable[[object], None]) -> None:
        try:
            result = produce()
        except ToolError as error:
            self.send_text(HTTPStatus.BAD_REQUEST, str(error))
        except Missing:
            self.send_text(HTTPStatus.NOT_FOUND, "not found")
        except Conflict as error:
            self.send_json(HTTPStatus.CONFLICT, error.payload)
        except Unavailable as error:
            self.send_text(HTTPStatus.SERVICE_UNAVAILABLE, str(error))
        except EngineError as error:
            self.send_text(HTTPStatus.BAD_GATEWAY, str(error))
        except OSError as error:
            self.send_text(HTTPStatus.INTERNAL_SERVER_ERROR, f"storage failed: {error.strerror}")
        else:
            deliver(result)

    def query(self) -> dict[str, list[str]]:
        try:
            return parse_qs(urlsplit(self.path).query, keep_blank_values=True, max_num_fields=QUERY_FIELDS)
        except ValueError as error:
            raise ToolError(str(error)) from error

    def host(self) -> str | None:
        hosts = self.headers.get_all("Host")
        if hosts is None or len(hosts) != 1 or hosts[0] not in self.server.hub.hosts():
            return None
        return hosts[0]

    def guarded(self, host: str) -> bool:
        return self.headers.get_all(GUARD) == ["1"] and self.headers.get_all("Origin") == [f"http://{host}"]

    def local(self, host: str) -> bool:
        origins = self.headers.get_all("Origin")
        return self.headers.get_all(GUARD) == ["1"] and (origins is None or origins == [f"http://{host}"])

    def client(self) -> bool:
        return self.headers.get_all(GUARD) == ["1"] and self.headers.get_all("Origin") is None

    def body(self, limit: int) -> bytes | None:
        length = self.headers.get("Content-Length")
        if length is None or not LENGTH.fullmatch(length):
            self.send_text(HTTPStatus.LENGTH_REQUIRED, "Content-Length required")
            return None
        if int(length) > limit:
            self.send_text(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "body too large")
            return None
        return self.rfile.read(int(length))
