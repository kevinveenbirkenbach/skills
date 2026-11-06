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

SCORE = "🎯 95 💥 3"
GIT_ENV = {
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
}
TREE = "0123456789abcdef0123456789abcdef01234567"
PAGE = "<!doctype html><title>diff</title><script>document.title = 'page script'</script>"
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
    {"name": "Morgen", "url": "https://radio.example/morgen", "from": "07:00", "to": "09:00", "days": [0, 1, 2, 3, 4], "on": True},
    {"name": "Nacht", "url": "http://10.0.0.5:8000/nacht", "from": "22:00", "to": "02:00", "days": [5], "on": True},
    {"name": "Aus", "url": "https://other.example:8443/", "from": "00:00", "to": "24:00", "days": [0, 1, 2, 3, 4, 5, 6], "on": False},
]
VOICE = HUB / "templates" / "voice.js"
SPACE = HUB / "templates" / "space.js"
NAV = HUB / "templates" / "nav.js"


class FakeScripts:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str]]] = []
        self.code = 0

    def run(self, script: str, args: list[str]) -> dict:
        self.calls.append((script, args))
        return {"command": " ".join([Path(script).name, *args]), "code": self.code, "stdout": "done", "stderr": ""}


def iso(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts, datetime.UTC).isoformat().replace("+00:00", "Z")


KEYS = tempfile.TemporaryDirectory()
ORIGIN = "http://localhost:8737"
PRESENT = 0x05
REGISTERED = 0x45
ZERO_LED_TRIES = 4096
KEY_SPECS = {
    -7: ["-algorithm", "EC", "-pkeyopt", "ec_paramgen_curve:P-256"],
    -8: ["-algorithm", "ED25519"],
    -257: ["-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048"],
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
    def __init__(self, alg: int, name: str) -> None:
        self.alg = alg
        self.pem = Path(KEYS.name) / f"{name}{alg}.pem"
        openssl(["genpkey", *KEY_SPECS[alg], "-out", str(self.pem)], b"")
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
    return Key(alg, name)


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
            for signer in pool.map(lambda attempt: Key(-7, f"zero{label}-{attempt}"), range(start, start + 64)):
                if signer.cose()[label][0] == 0:
                    return signer
    raise AssertionError(f"no P-256 key with a zero-led coordinate {label} in {ZERO_LED_TRIES} tries")
