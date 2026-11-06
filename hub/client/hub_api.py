from __future__ import annotations

import json
import urllib.request

SLACK = 15.0
GUARD = {"X-Kvb-Hub": "1"}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect)


def base_url(port: int) -> str:
    return f"http://127.0.0.1:{port}"


def load(request: urllib.request.Request, timeout: float) -> object:
    with OPENER.open(request, timeout=timeout) as response:
        return json.loads(response.read())


def call(request: urllib.request.Request, timeout: float) -> dict:
    data = load(request, timeout)
    if not isinstance(data, dict):
        raise TypeError("the hub answered no object")
    return data
