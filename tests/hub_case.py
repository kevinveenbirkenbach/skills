from __future__ import annotations

import http.client
import itertools
import json
import os
import subprocess
import tempfile
import threading
import time
import unittest
from collections.abc import Callable
from pathlib import Path
from unittest import mock

from hub_engines import write_engines
from hub_support import (
    GIT_ENV,
    HOST_STATE,
    HUB,
    OPTIONS,
    PAGE,
    SCORE,
    TREE,
    FakeScripts,
    Key,
    key,
    server,
    signing,
)


class HubCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        self.council = base / "council"
        self.pages = base / "pages"
        self.state = base / "state"
        self.outside = base / "outside"
        self.projects = base / "projects"
        self.tree_file = base / "tree" / "branch-tree.json"
        self.timers = base / "timers"
        self.cleanup = base / "state" / "cleanup"
        self.offices = base / "state" / "offices"
        self.approvers = base / "config" / "approvers.json"
        self.replay = base / "replay"
        for path in (self.pages, self.state, self.outside, self.projects, self.tree_file.parent, self.timers):
            path.mkdir()
        silence = mock.patch.object(server.Handler, "log_message")
        silence.start()
        self.addCleanup(silence.stop)
        self.ids = itertools.count(1)
        self.scripts = FakeScripts()
        self.engines = write_engines(base)
        httpd = server.HubServer(("127.0.0.1", 0), server.Handler)
        self.port = httpd.server_address[1]
        httpd.hub = server.open_hub(
            council=self.council,
            pages=self.pages,
            public_port=self.port,
            state=self.state,
            host_state=HOST_STATE,
            transcripts=self.projects,
            scripts=self.scripts,
            templates=HUB / "templates",
            places=server.Places(tree_file=self.tree_file, timers=self.timers, vendor=HUB / "vendor", cleanup=self.cleanup, offices=self.offices),
            model=server.Model(url="", model="", key=""),
            engines=self.engines,
            approvers=self.approvers,
        )
        self.httpd = httpd
        self.origin = signing.origin_of(self.port)
        thread = threading.Thread(target=httpd.serve_forever, args=(0.05,), daemon=True)
        thread.start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(thread.join, 10)
        self.addCleanup(httpd.shutdown)
        self.host = f"127.0.0.1:{self.port}"

    def call(self, method: str, path: str, body: bytes | None, headers: dict[str, str]) -> tuple[int, dict, bytes]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        try:
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            return response.status, {k.lower(): v for k, v in response.getheaders()}, response.read()
        finally:
            connection.close()

    def get(self, path: str) -> tuple[int, dict, bytes]:
        return self.call("GET", path, None, {"Host": self.host})

    def post_mcp(self, payload: object, headers: dict[str, str]) -> tuple[int, dict, bytes]:
        merged = {"Host": self.host, "Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        return self.call("POST", "/mcp", json.dumps(payload).encode(), {**merged, **headers})

    def rpc(self, method: str, params: dict) -> dict:
        status, _, body = self.post_mcp({"jsonrpc": "2.0", "id": next(self.ids), "method": method, "params": params}, {})
        self.assertEqual(status, 200, body)
        return json.loads(body)

    def tool(self, name: str, arguments: dict) -> dict:
        return self.rpc("tools/call", {"name": name, "arguments": arguments})["result"]

    def guard(self, host: str) -> dict[str, str]:
        return {"Host": host, "Origin": f"http://{host}", "X-Kvb-Orchestrator": "1"}

    def pin(self) -> Key:
        signer = key(-7, "main")
        signer.pin(self.approvers, self.origin)
        return signer

    def prepare(self, items: list[dict]) -> dict:
        status, _, body = self.post_json("/api/sign", {"items": items}, self.guard(self.host))
        self.assertEqual(status, 200, body)
        return json.loads(body)

    def signed(self, items: list[dict], signer: Key) -> dict:
        return signer.proof(self.prepare(items)["payload"], self.origin)

    def proven(self, items: list[dict], signer: Key) -> bytes:
        return json.dumps({"proof": self.signed(items, signer)}).encode()

    def page(self, name: str, text: str) -> str:
        path = self.pages / name
        path.write_text(text, encoding="utf-8")
        return str(path)

    def arguments(self, title: str, notes: str, page: str) -> dict:
        return {"repo": "/repo/.git", "worktree": "/repo/.worktrees/feature/x", "branch": "feature/x", "tree": TREE, "title": title, "page": page, "notes": notes, "gate": "pass", "score": SCORE}

    def events(self, query: str) -> dict:
        status, _, body = self.get(f"/api/events?{query}")
        self.assertEqual(status, 200, body)
        return json.loads(body)

    def client(self) -> dict[str, str]:
        return {"Host": self.host, "X-Kvb-Orchestrator": "1"}

    def settle(self, check: Callable[[], bool]) -> None:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if check():
                return
            time.sleep(0.05)
        self.fail("the condition did not settle")

    def approve(self, items: list[dict], proof: dict | None) -> tuple[int, dict, bytes]:
        return self.post_json("/api/inbox/approve", {"items": items, "proof": proof}, self.guard(self.host))

    def entry(self, kind: str, ident: str, label: str, digest: str) -> dict:
        return {"kind": kind, "id": ident, "verb": "approve", "label": label, "sha256": digest}

    def decision(self, recommended: str) -> str:
        result = self.tool("decision_request", {"question": "Merge the hub?", "options": OPTIONS, "agent": "Skills", "recommended": recommended})
        self.assertFalse(result["isError"], result)
        return result["structuredContent"]["id"]

    def choice(self, decision_id: str) -> str | None:
        return self.tool("decision_wait", {"id": decision_id, "timeout_seconds": 0})["structuredContent"]["choice"]

    def git(self, cwd: Path, *args: str) -> str:
        done = subprocess.run(["git", *args], cwd=cwd, env={**os.environ, **GIT_ENV}, check=True, capture_output=True, text=True)
        return done.stdout

    def request(self, title: str, notes: str) -> str:
        result = self.tool("review_request", self.arguments(title, notes, self.page("bundle.html", PAGE)))
        self.assertFalse(result["isError"], result)
        return result["structuredContent"]["id"]

    def status(self, review_id: str) -> str:
        return self.tool("review_status", {"id": review_id})["structuredContent"]["status"]

    def index(self) -> str:
        status, headers, body = self.get("/")
        self.assertEqual(status, 200, body)
        self.assertTrue(headers["content-type"].startswith("text/html"))
        return body.decode("utf-8")

    def snapshot(self) -> dict:
        status, headers, body = self.get("/api/state")
        self.assertEqual(status, 200, body)
        self.assertEqual(headers["content-type"], "application/json")
        return json.loads(body)

    def write_council(self, files: dict[str, object]) -> None:
        for name, content in files.items():
            path = self.council / name
            path.parent.mkdir(parents=True, exist_ok=True)
            text = content if isinstance(content, str) else json.dumps(content)
            path.write_text(text, encoding="utf-8")

    def write_tree(self) -> Path:
        root = self.outside / "scan"
        sample = (Path(__file__).parent / "branch-tree.json").read_text(encoding="utf-8")
        self.tree_file.write_text(sample.replace("@ROOT@", str(root)), encoding="utf-8")
        return root

    def jsonl(self, rows: list[dict]) -> str:
        return "".join(json.dumps(row) + "\n" for row in rows)

    def post_json(self, path: str, payload: object, headers: dict[str, str]) -> tuple[int, dict, bytes]:
        return self.call("POST", path, json.dumps(payload).encode(), {**headers, "Content-Type": "application/json"})

    def local(self) -> dict[str, str]:
        return {"Host": self.host, "X-Kvb-Orchestrator": "1"}

    def create_ask(self, payload: dict) -> str:
        status, _, body = self.post_json("/api/asks", payload, self.local())
        self.assertEqual(status, 201, body)
        return json.loads(body)["id"]

    def ask_status(self, ask_id: str, wait: str) -> str:
        status, _, body = self.get(f"/api/asks/{ask_id}?wait={wait}")
        self.assertEqual(status, 200, body)
        return json.loads(body)["status"]

    def claim(self, session: str, name: str) -> None:
        self.write_council({f"work/{session}/claim.json": {"office": f"work/{session}", "session": session, "runtime": "claude", "name": name, "since": "2026-11-05T08:00:00+00:00", "beat": time.time(), "work": "x"}})
