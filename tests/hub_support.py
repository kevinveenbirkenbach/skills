from __future__ import annotations

import base64
import concurrent.futures
import datetime
import functools
import hashlib
import importlib.util
import json
import os
import secrets
import socket
import ssl
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HUB = REPO_ROOT / "orchestrator"
sys.path[:0] = [str(HUB), str(HUB / "client")]
CLIENT = HUB / "client" / "permission_hook.py"
RUNNER = HUB / "client" / "runner.py"
APPROVAL = HUB / "client" / "approval.py"
RASCI = REPO_ROOT / "skills" / "kvb-org-rasci" / "scripts" / "rasci.py"
OPERATOR = REPO_ROOT / "skills" / "kvb-org-operator" / "scripts" / "operator.py"
LOGIN_SHELL = '#!/bin/sh\n[ "$1" = -ic ] || exit 97\nexec /bin/sh -c "$2"\n'
SPEC = importlib.util.spec_from_file_location("kvb_orchestrator_server", HUB / "server.py")
server = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = server
SPEC.loader.exec_module(server)
RUNNER_SPEC = importlib.util.spec_from_file_location("kvb_orchestrator_runner", RUNNER)
runner = importlib.util.module_from_spec(RUNNER_SPEC)
RUNNER_SPEC.loader.exec_module(runner)
import hub_api  # noqa: F401
import passkey
import signing
import verifier
from kvb_orchestrator.redirects import Redirects

SCORE = "🎯 95 💥 3"
GIT_ENV = {
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
}
TREE = "0123456789abcdef0123456789abcdef01234567"
LONG_REPO = "/home/operator-example-01/Repositories/github.com/operator-example-01/skills"
LONG_WORKTREE = f"{LONG_REPO}/.worktrees/feature/hub-bookmarks-everywhere"
LONG_BRANCH = "feature/hub-bookmarks-everywhere"
LONG_TASK = "work/bookmarks"
LONG_VOLUME = "volume:infinito_nexus_core_mariadb_data"
CORE_REPO = "/home/operator-example-01/Repositories/github.com/infinito-nexus/core"
CORE_BRANCH = "feature/store-workspace-proxmox-cosmos-requirements-statically-into-iam-before-the-final-compose-and-swarm-roundtrip"
CORE_WORKTREE = f"/home/operator-example-01/.local/share/worktrees/github.com/infinito-nexus/core/{CORE_BRANCH}"
MERGED_BRANCH = "feature/merged-away"
PAGE ="<!doctype html><title>diff</title><script>document.title = 'page script'</script>"
HOST_STATE = Path("/home/op/.local/state/kvb-orchestrator")
ASK = {"tool": "Bash", "command": "make deploy", "cwd": "/repo", "session": "s1", "agent": "", "timeout": 60}
HOOK = {
    "session_id": "s1",
    "transcript_path": "/home/op/.claude/projects/-repo/s1.jsonl",
    "cwd": "/repo",
    "permission_mode": "default",
    "hook_event_name": "PermissionRequest",
    "tool_name": "Bash",
    "tool_input": {"command": "rm -rf node_modules", "description": "Remove node_modules"},
    "permission_suggestions": [],
}
OPTIONS = [{"label": "Merge now", "description": "Gate is green"}, {"label": "Wait", "description": ""}]
AMBIENCE = HUB / "templates" / "ambience.js"
STREAMS = [
    {"name": "Morning", "url": "https://radio.example/morning", "from": "07:00", "to": "09:00", "days": [0, 1, 2, 3, 4], "on": True, "via": []},
    {"name": "Night", "url": "http://10.0.0.5:8000/night", "from": "22:00", "to": "02:00", "days": [5], "on": True, "via": []},
    {"name": "Off", "url": "https://other.example:8443/", "from": "00:00", "to": "24:00", "days": [0, 1, 2, 3, 4, 5, 6], "on": False, "via": []},
]


def offline(host: str, port: int, timeout: float, public: bool) -> socket.socket:
    raise ConnectionRefusedError(f"no network in tests: {host}:{port}")


def offline_redirects() -> Redirects:
    return Redirects(tls=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT), dial=offline, timeout=1.0)


VOICE = HUB / "templates" / "voice.js"
SPACE = HUB / "templates" / "space.js"
NAV = HUB / "templates" / "nav.js"
POPUP = HUB / "templates" / "popup.js"
FACES = HUB / "templates" / "faces.js"
PLAN = HUB / "templates" / "plan.js"
ESTIMATE = REPO_ROOT / "skills" / "kvb-org-queue-estimate" / "scripts" / "estimate.py"


class FakeScripts:
    skills = REPO_ROOT / "skills"

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str]]] = []
        self.code = 0

    def run(self, script: str, args: list[str]) -> dict:
        self.calls.append((script, args))
        return {"command": " ".join([Path(script).name, *args]), "code": self.code, "stdout": "done", "stderr": ""}


def iso(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts, datetime.UTC).isoformat().replace("+00:00", "Z")


def scan_item(branch: str, worktree: str | None, state: str, sha: str) -> dict:
    """Args:
        branch: the branch name.
        worktree: its worktree path, None for a branch without one.
        state: the gc state, such as unmerged or merged-clean.
        sha: the local tip.

    Returns:
        One pkgmgr branch tree item; a merged-clean one without a worktree
        is a branch the tree offers to delete.
    """
    merged = state == "merged-clean"
    counts = 0 if worktree else None
    return dict({
        "branch": branch, "worktree": worktree, "head": sha, "detached": False, "locked": None, "worktree_state": "clean" if worktree else "none",
        "staged": counts, "unstaged": counts, "untracked": counts, "upstream": None, "ahead": None, "behind": None, "gone": False, "local_sha": sha, "remotes": {},
        "compose_projects": [], "images": [], "state": state, "merged_by": "#7" if merged else None, "merged_into": "main" if merged else None, "size_bytes": None,
        "skip": None, "reason": state, "result": None, "flow": None,
    }, actions=["local-branch"])


def long_repos() -> list[dict]:
    """Returns:
        pkgmgr scan repositories on paths of real length: the skills
        repository with the worktree of LONG_BRANCH and the merged
        MERGED_BRANCH, and infinito-nexus/core with a worktree path of 196
        characters.
    """
    def entry(path: str, items: list[dict]) -> dict:
        return {"path": path, "remote": f"{path}.git", "default": "main", "missing": False, "known": True, "forge": "none", "scanned_at": "2026-11-14T12:00:00+00:00", "warnings": [], "items": items}

    return [
        entry(LONG_REPO, [scan_item(LONG_BRANCH, LONG_WORKTREE, "unmerged", "1" * 40), scan_item(MERGED_BRANCH, None, "merged-clean", "2" * 40)]),
        entry(CORE_REPO, [scan_item(CORE_BRANCH, CORE_WORKTREE, "unmerged", "3" * 40)]),
    ]


def long_task(now: float) -> dict:
    """Returns:
        The register row of LONG_TASK, working in LONG_WORKTREE and holding
        the volume LONG_VOLUME.
    """
    return {"title": "Bookmarks everywhere", "status": "running", "worker": "Skills session", "workdir": LONG_WORKTREE, "roles": {"Skills session": "RA"}, "artifacts": [{"ref": LONG_VOLUME, "added": iso(now - 600)}]}


KEYS = tempfile.TemporaryDirectory()
ORIGIN = "http://localhost:8737"
PRESENT = 0x05
REGISTERED = 0x45
ZERO_LED_TRIES = 4096


def rsa_spec(bits: int) -> list[str]:
    return ["-algorithm", "RSA", "-pkeyopt", f"rsa_keygen_bits:{bits}"]


KEY_SPECS = {
    -7: ["-algorithm", "EC", "-pkeyopt", "ec_paramgen_curve:P-256"],
    -8: ["-algorithm", "ED25519"],
    -257: rsa_spec(2048),
}


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def openssl(argv: list[str], data: bytes) -> bytes:
    return subprocess.run(["openssl", *argv], input=data, capture_output=True, timeout=60, check=True).stdout


def cbor_encode(value: object) -> bytes:
    def head(major: int, size: int) -> bytes:
        if size < 24:
            return bytes([major << 5 | size])
        width = next(width for width in (1, 2, 4, 8) if size < 1 << (8 * width))
        return bytes([major << 5 | {1: 24, 2: 25, 4: 26, 8: 27}[width]]) + size.to_bytes(width, "big")

    if isinstance(value, bool) or value is None:
        return bytes([0xE0 | {False: 20, True: 21, None: 22}[value]])
    if isinstance(value, int):
        return head(0, value) if value >= 0 else head(1, -1 - value)
    if isinstance(value, bytes):
        return head(2, len(value)) + value
    if isinstance(value, str):
        return head(3, len(value.encode())) + value.encode()
    if isinstance(value, list):
        return head(4, len(value)) + b"".join(cbor_encode(entry) for entry in value)
    return head(5, len(value)) + b"".join(cbor_encode(name) + cbor_encode(entry) for name, entry in value.items())


class Key:
    def __init__(self, alg: int, name: str, spec: list[str]) -> None:
        self.alg = alg
        self.pem = Path(KEYS.name) / f"{name}{alg}.pem"
        openssl(["genpkey", *spec, "-out", str(self.pem)], b"")
        self.spki = openssl(["pkey", "-in", str(self.pem), "-pubout", "-outform", "DER"], b"")
        self.raw_id = os.urandom(16)
        self.id = b64(self.raw_id)

    def cose(self) -> dict:
        if self.alg == -7:
            return {1: 2, 3: -7, -1: 1, -2: self.spki[-64:-32], -3: self.spki[-32:]}
        if self.alg == -8:
            return {1: 1, 3: -8, -1: 6, -2: self.spki[-32:]}
        modulus = openssl(["rsa", "-pubin", "-inform", "DER", "-modulus", "-noout"], self.spki).decode("ascii").strip().split("=", 1)[1]
        return {1: 3, 3: -257, -1: bytes.fromhex(modulus), -2: (65537).to_bytes(3, "big")}

    def sign(self, data: bytes) -> bytes:
        message = Path(KEYS.name) / f"message-{secrets.token_hex(8)}"
        message.write_bytes(data)
        if self.alg == -8:
            return openssl(["pkeyutl", "-sign", "-inkey", str(self.pem), "-rawin", "-in", str(message)], b"")
        return openssl(["dgst", "-sha256", "-sign", str(self.pem), str(message)], b"")

    def credential(self, origin: str, rp: str, flags: int) -> dict:
        return self.registration(self.cose(), origin, rp, flags)

    def registration(self, cose: dict, origin: str, rp: str, flags: int) -> dict:
        data = hashlib.sha256(rp.encode()).digest() + bytes([flags]) + bytes(4) + bytes(16) + len(self.raw_id).to_bytes(2, "big") + self.raw_id + cbor_encode(cose)
        client = json.dumps({"type": "webauthn.create", "challenge": b64(os.urandom(32)), "origin": origin}).encode()
        return {"id": self.id, "attestationObject": b64(cbor_encode({"fmt": "none", "attStmt": {}, "authData": data})), "clientDataJSON": b64(client)}

    def blob(self, origin: str) -> str:
        return b64(json.dumps(self.credential(origin, "localhost", REGISTERED)).encode())

    def assertion(self, payload: dict, origin: str, rp: str, flags: int, count: int) -> dict:
        client = json.dumps({"type": "webauthn.get", "challenge": signing.challenge(payload), "origin": origin, "crossOrigin": False}).encode()
        data = hashlib.sha256(rp.encode()).digest() + bytes([flags]) + count.to_bytes(4, "big")
        signature = self.sign(data + hashlib.sha256(client).digest())
        return {"id": self.id, "clientDataJSON": b64(client), "authenticatorData": b64(data), "signature": b64(signature), "userHandle": None}

    def proof(self, payload: dict, origin: str) -> dict:
        return {"payload": payload, "assertion": self.assertion(payload, origin, "localhost", PRESENT, 0)}

    def pin(self, path: Path, origin: str) -> None:
        verifier.pin(path, passkey.attested(self.credential(origin, "localhost", REGISTERED), origin), time.time())


@functools.cache
def key(alg: int, name: str) -> Key:
    return Key(alg, name, KEY_SPECS[alg])


@functools.cache
def rsa_key(bits: int) -> Key:
    return Key(-257, f"rsa{bits}", rsa_spec(bits))


@functools.cache
def zero_led(label: int) -> Key:
    """Args:
        label: the COSE label of the coordinate, -2 for x or -3 for y.

    Returns:
        A fresh P-256 key whose coordinate starts with a zero byte, as
        about one key in 256 does.
    """
    with concurrent.futures.ThreadPoolExecutor() as pool:
        for start in range(0, ZERO_LED_TRIES, 64):
            for signer in pool.map(lambda attempt: Key(-7, f"zero{label}-{attempt}", KEY_SPECS[-7]), range(start, start + 64)):
                if signer.cose()[label][0] == 0:
                    return signer
    raise AssertionError(f"no P-256 key with a zero-led coordinate {label} in {ZERO_LED_TRIES} tries")
