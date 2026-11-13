from __future__ import annotations

import contextlib
import http.client
import socket
import ssl
import threading
import time
from urllib.parse import urlsplit

CHUNK = 1 << 16
TLS = ssl.create_default_context()


class Failure(Exception):
    """Args:
        reason: what went wrong as a status, a limit or an exception type,
            never a header or a body of the exchange.
    """


class Call:
    """Args:
        seconds: the wall-clock time one call may take, from the name lookup
            to the last byte of the answer.
    """

    def __init__(self, seconds: float) -> None:
        self.seconds = seconds
        self.deadline = time.monotonic() + seconds
        self.lock = threading.Lock()
        self.sock: socket.socket | None = None
        self.over = False

    def late(self) -> Failure:
        return Failure(f"took longer than {self.seconds:g} seconds")

    def remaining(self) -> float:
        left = self.deadline - time.monotonic()
        if left <= 0:
            raise self.late()
        return left

    def attach(self, sock: socket.socket | None) -> None:
        with self.lock:
            if self.over and sock is not None:
                raise self.late()
            self.sock = sock

    def cut(self) -> None:
        with self.lock:
            self.over = True
            if self.sock is not None:
                with contextlib.suppress(OSError):
                    socket.socket.shutdown(self.sock, socket.SHUT_RDWR)

    def finish(self) -> None:
        with self.lock:
            self.over = True
            self.sock = None

    def resolve(self, host: str, port: int) -> list[tuple]:
        """Returns:
            The addresses of host, looked up in a daemon thread that the call
            waits for only until its deadline.
        """
        outcome: list[object] = []

        def lookup() -> None:
            try:
                outcome.append(socket.getaddrinfo(host, port, type=socket.SOCK_STREAM))
            except OSError as error:
                outcome.append(error)

        worker = threading.Thread(target=lookup, name="bounded lookup", daemon=True)
        worker.start()
        worker.join(self.remaining())
        if not outcome:
            raise self.late()
        if isinstance(outcome[0], OSError):
            raise outcome[0]
        return outcome[0]

    def dial(self, host: str, port: int) -> socket.socket:
        """Returns:
            A socket connected to the first address of host that answers,
            each attempt within the time left, the watchdog able to cut it.
        """
        failure: OSError = OSError("no address")
        for family, kind, proto, _, address in self.resolve(host, port):
            sock = socket.socket(family, kind, proto)
            try:
                self.attach(sock)
                sock.settimeout(self.remaining())
                sock.connect(address)
                sock.settimeout(self.remaining())
                return sock
            except OSError as error:
                self.attach(None)
                sock.close()
                failure = error
            except Failure:
                self.attach(None)
                sock.close()
                raise
        raise failure


class Plain(http.client.HTTPConnection):
    def __init__(self, host: str, port: int, call: Call) -> None:
        super().__init__(host, port, timeout=call.seconds)
        self.call = call

    def connect(self) -> None:
        self.sock = self.call.dial(self.host, self.port)


class Sealed(Plain):
    def connect(self) -> None:
        raw = self.call.dial(self.host, self.port)
        try:
            tls = TLS.wrap_socket(raw, server_hostname=self.host, do_handshake_on_connect=False)
        except BaseException:
            raw.close()
            raise
        self.sock = tls
        self.call.attach(tls)
        tls.do_handshake()


CONNECTIONS = {"http": (Plain, 80), "https": (Sealed, 443)}


def drain(response: http.client.HTTPResponse, limit: int, call: Call) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while chunk := response.read1(CHUNK):
        size += len(chunk)
        if size > limit:
            raise Failure(f"answered more than {limit} bytes")
        call.remaining()
        chunks.append(chunk)
    call.remaining()
    if response.length:
        raise Failure("answered a truncated reply")
    return b"".join(chunks)


def post(url: str, body: bytes, headers: dict[str, str], limit: int, seconds: float) -> bytes:
    """Args:
        url: the http or https URL to POST to; no proxy and no redirect.
        body: the request body.
        headers: the request headers.
        limit: the most bytes the answer may carry.
        seconds: the wall-clock time the whole call may take: name lookup,
            connect, TLS handshake, request and answer.

    Returns:
        The body of a 200 answer.

    Raises:
        Failure for every other outcome, naming a status, a limit or an
        exception type only.
    """
    call = Call(seconds)
    watchdog = threading.Timer(seconds, call.cut)
    watchdog.daemon = True
    connection: Plain | None = None
    try:
        watchdog.start()
        parts = urlsplit(url)
        kind, port = CONNECTIONS[parts.scheme]
        connection = kind(parts.hostname or "", parts.port or port, call)
        connection.request("POST", (parts.path or "/") + (f"?{parts.query}" if parts.query else ""), body=body, headers=headers)
        call.remaining()
        with connection.getresponse() as response:
            if response.status != 200:
                raise Failure(f"answered HTTP {response.status}")
            return drain(response, limit, call)
    except Failure:
        raise
    except Exception as error:  # noqa: BLE001
        if isinstance(error, TimeoutError) or time.monotonic() >= call.deadline:
            raise call.late() from None
        raise Failure(f"failed: {type(error).__name__}") from None
    finally:
        watchdog.cancel()
        call.finish()
        if connection is not None:
            connection.close()
