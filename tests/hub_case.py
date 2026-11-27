from __future__ import annotations

import http.client
import itertools
import json
import os
import subprocess
import sys
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
    LOGIN_SHELL,
    OPERATOR,
    OPTIONS,
    PAGE,
    PRESENT,
    RASCI,
    RUNNER,
    SCORE,
    TREE,
    FakeScripts,
    Key,
    Redirects,
    key,
    offline_redirects,
    server,
    signing,
)
from kvb_orchestrator import batches, engines
from kvb_orchestrator.settings import Settings


class HubCase(unittest.TestCase):
    real_undo = False

    def setUp(self):
        if not self.real_undo:
            undo = mock.patch.object(Settings, "undo", lambda _settings: batches.UNDO)
            undo.start()
            self.addCleanup(undo.stop)
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
        self.kept = base / "kept"
        self.cleanup = base / "state" / "cleanup"
        self.offices = base / "state" / "offices"
        self.approvers = base / "config" / "approvers.json"
        self.replay = base / "replay"
        self.shell = base / "login-shell"
        for path in (self.pages, self.state, self.outside, self.projects, self.tree_file.parent, self.timers, self.kept):
            path.mkdir()
        self.shell.write_text(LOGIN_SHELL, encoding="utf-8")
        self.shell.chmod(0o755)
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
            places=server.Places(tree_file=self.tree_file, timers=self.timers, vendor=HUB / "vendor", cleanup=self.cleanup, offices=self.offices, kept=self.kept),
            model=server.Model(url="", model="", key=""),
            engines=self.engines,
            approvers=self.approvers,
            redirects=self.redirects(),
            live_ttl=self.live_ttl(),
        )
        self.httpd = httpd
        self.origin = signing.origin_of(self.port)
        thread = threading.Thread(target=httpd.serve_forever, args=(0.05,), daemon=True)
        thread.start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(thread.join, 10)
        self.addCleanup(httpd.shutdown)
        self.host = f"127.0.0.1:{self.port}"

    def redirects(self) -> Redirects:
        return offline_redirects()

    def live_ttl(self) -> float:
        """Returns:
            0, so a test that writes council files directly reads them in the
            next state; a case testing the live cache overrides it.
        """
        return 0.0

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

    def signed_rule(self, signer: Key, fields: dict) -> dict:
        """Args:
            signer: the pinned passkey that signs the rule.
            fields: the draft as POST /api/rules/sign takes it.

        Returns:
            The stored rule, on.
        """
        status, _, body = self.post_json("/api/rules/sign", fields, self.guard(self.host))
        self.assertEqual(status, 200, body)
        payload = json.loads(body)["payload"]
        status, _, body = self.post_json("/api/rules", {"rule": payload, "assertion": signer.assertion(payload, self.origin, "localhost", PRESENT, 0), "enabled": True}, self.guard(self.host))
        self.assertEqual(status, 201, body)
        return json.loads(body)

    def prepare(self, items: list[dict]) -> dict:
        status, _, body = self.post_json("/api/sign", {"items": items}, self.guard(self.host))
        self.assertEqual(status, 200, body)
        return json.loads(body)

    def signed(self, items: list[dict], signer: Key) -> dict:
        return signer.proof(self.prepare(items)["payload"], self.origin)

    def proven(self, items: list[dict], signer: Key) -> bytes:
        return json.dumps({"proof": self.signed(items, signer)}).encode()

    def message_proof(self, payload: dict, signer: Key) -> dict:
        status, _, body = self.post_json("/api/messages/sign", payload, self.guard(self.host))
        self.assertEqual(status, 200, body)
        return signer.proof(json.loads(body)["payload"], self.origin)

    def board_proof(self, action: str, signer: Key, agents: list[str] | None = None) -> dict:
        status, _, body = self.post_json("/api/board/sign", {"action": action, **({} if agents is None else {"agents": agents})}, self.guard(self.host))
        self.assertEqual(status, 200, body)
        return signer.proof(json.loads(body)["payload"], self.origin)

    def reveal_proof(self, kind: str, item_id: str, paths: list[str], signer: Key) -> dict:
        status, _, body = self.post_json(f"/api/diffs/{kind}/{item_id}/reveal/sign", {"paths": paths}, self.guard(self.host))
        self.assertEqual(status, 200, body)
        return signer.proof(json.loads(body)["payload"], self.origin)

    def reveal(self, kind: str, item_id: str, paths: list[str], proof: object) -> tuple[int, dict, bytes]:
        return self.post_json(f"/api/diffs/{kind}/{item_id}/reveal", {"paths": paths, "proof": proof}, self.guard(self.host))

    def say(self, payload: dict, signer: Key) -> tuple[int, dict, bytes]:
        proof = self.message_proof({"upload": "", "voice": "", **payload}, signer)
        return self.post_json("/api/messages", {"upload": "", "voice": "", **payload, "proof": proof}, self.guard(self.host))

    def tell_all(self, payload: dict, signer: Key) -> tuple[int, dict, bytes]:
        proof = self.message_proof({"to": "*", "upload": "", "voice": "", **payload}, signer)
        return self.post_json("/api/board/broadcast", {"voice": "", **payload, "proof": proof}, self.guard(self.host))

    def page(self, name: str, text: str) -> str:
        path = self.pages / name
        path.write_text(text, encoding="utf-8")
        return str(path)

    def arguments(self, title: str, notes: str, page: str) -> dict:
        return {"repo": "/repo/.git", "worktree": "/repo/.worktrees/feature/x", "branch": "feature/x", "tree": TREE, "title": title, "page": page, "notes": notes, "gate": "pass", "score": SCORE}

    def branched(self, branch: str) -> dict:
        """Args:
            branch: the review's branch, checked out in /repo/.worktrees/<branch>;
                a newer review of the same branch supersedes an older pending one.
        """
        return {"worktree": f"/repo/.worktrees/{branch}", "branch": branch}

    def events(self, query: str) -> dict:
        status, _, body = self.get(f"/api/events?{query}")
        self.assertEqual(status, 200, body)
        return json.loads(body)

    def client(self) -> dict[str, str]:
        return {"Host": self.host, "X-Kvb-Orchestrator": "1"}

    def runner_jobs(self) -> list[dict]:
        status, _, body = self.call("GET", "/api/runner/jobs", None, self.client())
        self.assertEqual(status, 200, body)
        return json.loads(body)["jobs"]

    def run_runner(self, register: bool = True, council: Path | None = None) -> None:
        trust = ["--approvers", str(self.approvers), "--replay", str(self.replay / "runner.json"), "--state", str(self.state)]
        flags = ["--rasci", str(RASCI), "--council", str(council or self.council)] if register else []
        command = [sys.executable, str(RUNNER), "--port", str(self.port), "--interval", "0.1", *trust, *flags, "--operator", str(OPERATOR), "--once"]
        done = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False, env={**os.environ, "SHELL": str(self.shell), "AGENTS_COUNCIL_ROOT": str(council or self.council)})
        self.assertEqual(done.returncode, 0, done.stderr)

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
        return self.write_fixture("branch-tree.json")

    def write_fixture(self, fixture: str) -> Path:
        """Args:
            fixture: the tree file under tests/ to write, @ROOT@ replaced.
        """
        root = self.outside / "scan"
        sample = (Path(__file__).parent / fixture).read_text(encoding="utf-8")
        self.tree_file.write_text(sample.replace("@ROOT@", str(root)), encoding="utf-8")
        self.write_local_plan(json.loads(self.tree_file.read_text(encoding="utf-8")), {})
        return root

    def write_local_plan(self, tree: dict, local: dict[str, dict]) -> None:
        """Args:
            tree: a tree file's data; each branch becomes the item `pkgmgr
                branch cleanup --local --json` plans for it as gc.py
                _local_actions does: a merged-clean local branch without
                worktree merged by ancestry gets exactly local-branch, any
                other merged-clean one the skip pkgmgr gives a tip that is no
                ancestor of the default branch.
            local: branch -> fields that replace the modelled ones, for a
                local tip that is an ancestor while the tree's merged_by,
                which covers every tip, is not.
        """
        repos = []
        for entry in tree["repos"]:
            default = f"refs/remotes/origin/{entry.get('default')}"
            items = []
            for item in entry["items"]:
                if not item["branch"]:
                    continue
                candidate = item["state"] == "merged-clean" and bool(item["local_sha"]) and not item["worktree"]
                ancestry = candidate and item["merged_by"] == "ancestor"
                planned = {
                    "branch": item["branch"], "worktree": item["worktree"], "head": item["head"], "local_sha": item["local_sha"], "remotes": item["remotes"], "upstream": item["upstream"], "state": item["state"],
                    "merged_by": item["merged_by"], "merged_into": default if item["state"] == "merged-clean" else None,
                    "skip": f"merged by {item['merged_by']}, tip is no ancestor of {default}" if candidate and not ancestry else None,
                    "actions": ["local-branch"] if ancestry else [], "result": None,
                }
                items.append({**planned, **local.get(item["branch"], {})})
            repos.append({"repo": entry["path"], "default": default, "merged_into": [], "warnings": [], "items": items})
        self.tree_file.with_name("local-plan.json").write_text(json.dumps({"repos": repos}), encoding="utf-8")

    def jsonl(self, rows: list[dict]) -> str:
        return "".join(json.dumps(row) + "\n" for row in rows)

    def host_cpu(self, cpu: float | None, age: float) -> None:
        """Args:
            cpu: the host CPU percent of the newest W4 sample, None unknown.
            age: how many seconds before now the sampler wrote it.
        """
        folder = self.kept / "resources"
        folder.mkdir(exist_ok=True)
        now = time.time()
        rows = [{"t": now - age - 60, "cpu": 5.0, "ram": 20.0}, {"t": now - age, "cpu": cpu, "ram": 20.0}]
        written = folder / f".samples-{threading.get_ident()}.jsonl"
        written.write_text(self.jsonl(rows), encoding="utf-8")
        os.replace(written, folder / "samples.jsonl")

    def hand_out(self, voice: str) -> None:
        """Args:
            voice: an installed voice the hub then hands out to a speaker, so
                /api/tts accepts it.
        """
        speech = self.httpd.hub.speech
        keys = [f"s{number}" for number in range(1000)]
        key = next((key for key in keys if engines.voice_of(key, speech.pool, speech.operator) == voice), "Operator")
        self.assertEqual(speech.voice_of(key), voice)

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
