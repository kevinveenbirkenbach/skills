from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
import threading
import time
from collections.abc import Callable
from urllib.parse import urljoin, urlsplit

from . import NAME
from .errors import ToolError
from .settings import stream_origin

HOP_LIMIT = 5
TIMEOUT = 4.0
DEADLINE_HOPS = 3
RETRY_SECONDS = 600
MOVED = frozenset({301, 302, 303, 307, 308})
HEADERS = {"User-Agent": NAME, "Accept": "*/*"}
EMBEDDING = (ipaddress.ip_network("64:ff9b::/96"), ipaddress.ip_network("::/96"))
SECOND_LEVELS = frozenset({"ac", "co", "com", "edu", "go", "gov", "ne", "net", "or", "org"})

Dial = Callable[[str, int, float, bool], socket.socket]


def global_address(text: str) -> bool:
    """Returns:
        Whether the address is global; a NAT64 or IPv4-compatible IPv6
        address counts by the IPv4 address it embeds.
    """
    address = ipaddress.ip_address(text)
    if address.version == 6 and any(address in network for network in EMBEDDING):
        return ipaddress.IPv4Address(int(address) & 0xFFFFFFFF).is_global
    return address.is_global


def dial(host: str, port: int, timeout: float, public: bool) -> socket.socket:
    """Args:
        public: connect only to a global address, as for a redirect target
            the operator never signed; the address checked is the one
            dialed, so a second lookup cannot swap it. Each allowed address
            is tried in turn.
    """
    failure: Exception = ToolError(f"{host} has no public address")
    for _, _, _, _, address in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM):
        if public and not global_address(address[0]):
            continue
        try:
            return socket.create_connection(address[:2], timeout)
        except OSError as error:
            failure = error
    raise failure


def media_source(url: str) -> str:
    """Returns:
        The media-src source a redirect hop to the url needs. A host of three
        or more labels widens to its siblings (https://*.cdn.example): a CDN
        such as the ARD's rndfnk.com picks another node per request, so the
        exact host the server saw is not the one the browser gets. An IP
        address, a two-label host and a name right under a country code's
        generic second level (bbc.co.uk, SECOND_LEVELS) stay exact; a
        private multi-tenant suffix such as github.io is not known and
        widens.
    """
    origin = stream_origin(url)
    parts = urlsplit(origin)
    host = parts.hostname or ""
    labels = host.split(".")
    try:
        ipaddress.ip_address(host)
        exact = True
    except ValueError:
        exact = len(labels) < 3 or (len(labels) == 3 and len(labels[2]) == 2 and labels[1] in SECOND_LEVELS)
    shown = host if exact else "*." + ".".join(labels[1:])
    return f"https://{shown}" if parts.port is None else f"https://{shown}:{parts.port}"


class Hop(http.client.HTTPConnection):
    default_port = 443

    def __init__(self, host: str, port: int, tls: ssl.SSLContext, opener: Dial, timeout: float, public: bool) -> None:
        super().__init__(host, port, timeout=timeout)
        self.tls = tls
        self.opener = opener
        self.public = public

    def connect(self) -> None:
        self.sock = self.tls.wrap_socket(self.opener(self.host, self.port, self.timeout, self.public), server_hostname=self.host)


class Redirects:
    """Args:
        tls: the context every hop's certificate is verified against.
        dial: opens the TCP connection to a host and port within a timeout,
            to a global address only when told so.
        timeout: seconds each socket operation of a hop may take; a whole
            resolve answers within DEADLINE_HOPS times that.
    """

    def __init__(self, tls: ssl.SSLContext, dial: Dial, timeout: float) -> None:
        self.tls = tls
        self.dial = dial
        self.timeout = timeout
        self.tried: dict[str, float] = {}
        self.running: set[str] = set()
        self.lock = threading.Lock()

    def due(self, url: str) -> bool:
        return time.monotonic() - self.tried.get(url, -RETRY_SECONDS) >= RETRY_SECONDS

    def hop(self, url: str, public: bool) -> str | None:
        """Returns:
            The absolute URL the url redirects to, or None when it answers
            without a redirect. A GET that reads no byte of the body, since a
            live stream never ends and some stream servers refuse HEAD.
        """
        parts = urlsplit(url)
        connection = Hop(parts.hostname or "", parts.port or Hop.default_port, self.tls, self.dial, self.timeout, public)
        try:
            connection.request("GET", (parts.path or "/") + (f"?{parts.query}" if parts.query else ""), headers=HEADERS)
            with connection.getresponse() as response:
                status, location = response.status, response.getheader("Location")
        finally:
            connection.close()
        if status not in MOVED:
            return None
        if not location:
            raise ToolError(f"answers {status} without a Location")
        return urljoin(url, location)

    def chain(self, url: str) -> list[str]:
        """Returns:
            Every URL the url redirects through, in order, after the url.

        Raises:
            ToolError when a hop leaves https, the chain is longer than
            HOP_LIMIT, or a hop names no valid URL. Only the url itself, which
            the operator signed, may lie at a non-global address.
        """
        hops: list[str] = []
        target = self.hop(url, False)
        while target is not None:
            origin = stream_origin(target)
            if urlsplit(origin).scheme != "https":
                raise ToolError(f"redirects to {origin}, which is not https")
            if len(hops) == HOP_LIMIT:
                raise ToolError(f"redirects more than {HOP_LIMIT} times")
            hops.append(target)
            target = self.hop(target, True)
        return hops

    def via(self, url: str) -> list[str]:
        own = stream_origin(url)
        return list(dict.fromkeys(media_source(hop) for hop in self.chain(url) if stream_origin(hop) != own))

    def outcome(self, url: str) -> tuple[list[str] | None, str]:
        try:
            return self.via(url), ""
        except (OSError, http.client.HTTPException, ToolError, ValueError) as error:
            return None, str(error) or type(error).__name__

    def probe(self, url: str, outcomes: dict[str, tuple[list[str] | None, str]]) -> None:
        try:
            outcomes[url] = self.outcome(url)
        finally:
            with self.lock:
                self.running.discard(url)

    def claim(self, urls: list[str]) -> tuple[list[str], list[str]]:
        """Returns:
            The https urls among urls, and those of them no earlier probe
            still resolves, now marked running and tried.
        """
        wanted = sorted({url for url in urls if urlsplit(url).scheme == "https"})
        with self.lock:
            probed = [url for url in wanted if url not in self.running]
            self.running.update(probed)
        self.tried.update(dict.fromkeys(probed, time.monotonic()))
        return wanted, probed

    def resolve(self, urls: list[str]) -> dict[str, tuple[list[str] | None, str]]:
        """Returns:
            Per url the origins its redirect chain needs besides its own, or
            None and why the chain could not be resolved, within the deadline
            even when a station answers byte by byte. A late chain goes on in
            its daemon thread until its socket timeouts end it, and a url
            whose earlier probe still runs is not probed again, so at most one
            thread per url lingers. Only https urls are probed; any other maps
            to no origins. Records each probe for due().
        """
        wanted, probed = self.claim(urls)
        limit = self.timeout * DEADLINE_HOPS
        deadline = time.monotonic() + limit
        found: dict[str, tuple[list[str] | None, str]] = {}
        threads = [threading.Thread(target=self.probe, args=(url, found), name=f"redirects {url}", daemon=True) for url in probed]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(max(0.0, deadline - time.monotonic()))
        outcomes = {url: (None, "an earlier save still resolves it") for url in wanted} | {url: (None, f"no answer within {limit:g} s") for url in probed} | dict(found)
        return {url: outcomes.get(url, ([], "")) for url in urls}
