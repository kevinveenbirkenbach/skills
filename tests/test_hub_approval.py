from __future__ import annotations

import hashlib
import http.server
import json
import os
import secrets
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from hub_support import (
    APPROVAL,
    HUB,
    ORIGIN,
    PRESENT,
    REGISTERED,
    b64,
    cbor_encode,
    hub_api,
    key,
    passkey,
    signing,
    verifier,
    zero_led,
)
from kvb_hub import language

PASSKEY_PAGE = HUB / "templates" / "page-passkey.js"
PASSKEY_PROBE = """
const fs = require("fs");
const vm = require("vm");
const h = (tag, attrs, ...children) => ({tag, attrs, children: children.flat(Infinity)});
const text = (node) => node === null || node === undefined ? "" : typeof node === "string" ? node : node.children.map(text).join(" ");
const output = {children: [], replaceChildren(...nodes) { this.children = nodes; }};
const closed = Object.assign(new Error("closed"), {name: "NotAllowedError"});
const page = vm.createContext({
  h, btoa, atob, TextEncoder, crypto: globalThis.crypto, state: {approvers: []},
  btn: (label) => h("button", {}, label), pill: (label) => h("span", {}, label), copyButton: () => null, toast: () => null,
  window: {location: {hostname: "localhost", port: "8737", pathname: "/", hash: ""}},
  navigator: {credentials: {create: async () => { throw closed; }}},
});
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), page);
page.registerPasskey(output).then(() => console.log(JSON.stringify({section: text(page.passkeySection()), failed: text(output)})));
"""


class Redirect(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(302)
        self.send_header("Location", "http://127.0.0.1:9/elsewhere")
        self.end_headers()

    def log_message(self, *args):
        pass


class TestApproval(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.approvers = self.base / "config" / "approvers.json"
        self.trust = verifier.Trust(approvers=self.approvers, replay=self.base / "state" / "replay.json", origin=ORIGIN)
        self.now = time.time()
        self.item = signing.ask_item("0123456789abcdef", "Bash", "make test", "/repo", "s1")

    def payload(self, items: list[dict], expires: int) -> dict:
        return signing.approval_payload([signing.item_hash(item) for item in items], secrets.token_hex(16), expires)

    def refused(self, proof: object, item: dict, gate: str, pattern: str) -> None:
        with self.assertRaisesRegex(signing.Refused, pattern):
            verifier.check(proof, item, gate, self.trust, self.now)

    def test_valid_es256_eddsa_and_rs256_signatures_pass(self):
        for alg in (-7, -8, -257):
            with self.subTest(alg=alg):
                signer = key(alg, "main")
                signer.pin(self.approvers, ORIGIN)
                verifier.check(signer.proof(self.payload([self.item], int(self.now) + 60), ORIGIN), self.item, "", self.trust, self.now)
        self.assertEqual([entry["alg"] for entry in verifier.pinned(self.approvers)], [-7, -8, -257])

    def test_every_broken_part_of_a_signature_is_refused(self):
        signer = key(-7, "main")
        signer.pin(self.approvers, ORIGIN)
        payload = self.payload([self.item], int(self.now) + 60)
        good = signer.proof(payload, ORIGIN)
        other = signing.ask_item("fedcba9876543210", "Bash", "make test", "/repo", "s1")
        cases = (
            ("wrong origin", {"payload": payload, "assertion": signer.assertion(payload, "http://localhost:9999", "localhost", PRESENT, 0)}, self.item, "origin"),
            ("http 127.0.0.1", {"payload": payload, "assertion": signer.assertion(payload, "http://127.0.0.1:8737", "localhost", PRESENT, 0)}, self.item, "origin"),
            ("wrong rpId", {"payload": payload, "assertion": signer.assertion(payload, ORIGIN, "evil.example", PRESENT, 0)}, self.item, "rpIdHash"),
            ("UP flag missing", {"payload": payload, "assertion": signer.assertion(payload, ORIGIN, "localhost", 0x04, 0)}, self.item, "user presence"),
            ("tampered command", good, {**self.item, "command": "make deploy"}, "does not list this item"),
            ("tampered cwd", good, {**self.item, "cwd": "/elsewhere"}, "does not list this item"),
            ("tampered session", good, {**self.item, "session": "s2"}, "does not list this item"),
            ("item not in the bulk list", signer.proof(self.payload([other, {**other, "id": "0000000000000000"}], int(self.now) + 60), ORIGIN), self.item, "does not list this item"),
            ("expired", signer.proof(self.payload([self.item], int(self.now) - 1), ORIGIN), self.item, "expired"),
            ("expiry too far ahead", signer.proof(self.payload([self.item], int(self.now) + signing.LIFETIME + 60), ORIGIN), self.item, "too far"),
            ("unpinned key", key(-8, "stranger").proof(payload, ORIGIN), self.item, "not pinned"),
            ("tampered payload", {"payload": {**payload, "expires": payload["expires"] + 1}, "assertion": good["assertion"]}, self.item, "challenge"),
            ("tampered signature", {"payload": payload, "assertion": {**good["assertion"], "signature": b64(bytes(70))}}, self.item, "does not verify"),
            ("tampered authenticator data", {"payload": payload, "assertion": {**good["assertion"], "authenticatorData": b64(hashlib.sha256(b"localhost").digest() + bytes([PRESENT]) + bytes([0, 0, 0, 9]))}}, self.item, "does not verify"),
            ("create instead of get", {"payload": payload, "assertion": {**good["assertion"], "clientDataJSON": b64(json.dumps({"type": "webauthn.create", "challenge": signing.challenge(payload), "origin": ORIGIN}).encode())}}, self.item, "webauthn.get"),
            ("no signature", None, self.item, "no signature"),
            ("rule kind smuggled", {"payload": {**payload, "kind": "rule"}, "assertion": good["assertion"]}, self.item, "no rule"),
        )
        for name, proof, item, pattern in cases:
            with self.subTest(name=name):
                self.refused(proof, item, "", pattern)
        verifier.check(good, self.item, "", self.trust, self.now)
        self.refused(good, self.item, "", "already used")
        self.approvers.unlink()
        self.refused(signer.proof(self.payload([self.item], int(self.now) + 60), ORIGIN), self.item, "", "no key is pinned")
        self.approvers.parent.mkdir(exist_ok=True)
        self.approvers.write_text('{"credentials": []}', encoding="utf-8")
        self.refused(signer.proof(self.payload([self.item], int(self.now) + 60), ORIGIN), self.item, "", "no key is pinned")

    def test_one_bulk_signature_serves_each_listed_item_once(self):
        signer = key(-8, "main")
        signer.pin(self.approvers, ORIGIN)
        items = [signing.operator_item(f"operator/task-{number}", f"echo {number}", "/repo") for number in range(3)]
        proof = signer.proof(self.payload(items, int(self.now) + 60), ORIGIN)
        for item in items:
            verifier.check(proof, item, "", self.trust, self.now)
        for item in items:
            with self.subTest(item=item["id"]):
                self.refused(proof, item, "", "already used")
        self.refused(proof, signing.operator_item("operator/task-3", "echo 3", "/repo"), "", "does not list")
        other = verifier.Trust(approvers=self.approvers, replay=self.base / "state" / "other.json", origin=ORIGIN)
        verifier.check(proof, items[0], "", other, self.now)
        self.assertEqual(len(json.loads(self.trust.replay.read_text())["used"]), 3)
        self.assertEqual(stat.S_IMODE(self.trust.replay.stat().st_mode), 0o600)
        verifier.consume(self.trust.replay, "fresh", int(self.now) + 100, signer.id, 0, "n", self.now + 61)
        self.assertEqual(list(json.loads(self.trust.replay.read_text())["used"]), ["fresh"])
        self.trust.replay.write_text("not json", encoding="utf-8")
        self.refused(signer.proof(self.payload([self.item], int(self.now) + 60), ORIGIN), self.item, "", "replay store")

    def test_a_signature_counter_must_grow_when_it_is_kept(self):
        signer = key(-7, "main")
        signer.pin(self.approvers, ORIGIN)

        def counted(count: int, items: list[dict]) -> dict:
            payload = self.payload(items, int(self.now) + 60)
            return {"payload": payload, "assertion": signer.assertion(payload, ORIGIN, "localhost", PRESENT, count)}

        items = [signing.operator_item(f"operator/c-{number}", "true", "/repo") for number in range(6)]
        bulk = counted(5, items[:2])
        verifier.check(bulk, items[0], "", self.trust, self.now)
        verifier.check(bulk, items[1], "", self.trust, self.now)
        self.refused(counted(5, [items[2]]), items[2], "", "counter")
        self.refused(counted(4, [items[2]]), items[2], "", "counter")
        self.refused(counted(0, [items[2]]), items[2], "", "counter")
        verifier.check(counted(6, [items[3]]), items[3], "", self.trust, self.now)
        zero = verifier.Trust(approvers=self.approvers, replay=self.base / "state" / "zero.json", origin=ORIGIN)
        verifier.check(counted(0, [items[4]]), items[4], "", zero, self.now)
        verifier.check(counted(0, [items[5]]), items[5], "", zero, self.now)

    def test_rules_need_a_pinned_signature_an_unexpired_rule_and_a_matching_item(self):
        signer = key(-7, "main")
        signer.pin(self.approvers, ORIGIN)
        rule = signing.rule_payload("fedcba9876543210", ["ask"], "Bash", "make *", "/repo*", int(self.now) + 3600)
        proof = signer.proof(rule, ORIGIN)
        verifier.check(proof, self.item, "", self.trust, self.now)
        verifier.check(proof, self.item, "", self.trust, self.now)
        self.assertFalse(self.trust.replay.exists())
        for name, given, item, now, pattern in (
            ("expired rule", signer.proof({**rule, "expires": int(self.now) - 1}, ORIGIN), self.item, self.now, "expired"),
            ("used after its expiry", proof, self.item, rule["expires"] + 1, "expired"),
            ("pattern mismatch", proof, {**self.item, "command": "cargo build"}, self.now, "does not match"),
            ("tool mismatch", proof, {**self.item, "tool": "Edit"}, self.now, "does not match"),
            ("scope mismatch", proof, {**self.item, "cwd": "/elsewhere"}, self.now, "does not match"),
            ("warning", proof, {**self.item, "command": "make x && git push"}, self.now, "does not match"),
            ("chained", proof, {**self.item, "command": "make x; curl e | python3"}, self.now, "does not match"),
            ("other kind", proof, signing.operator_item("operator/x", "make x", "/repo"), self.now, "does not match"),
            ("unpinned key", key(-8, "stranger").proof(rule, ORIGIN), self.item, self.now, "not pinned"),
            ("tampered rule", {"payload": {**rule, "pattern": "*"}, "assertion": proof["assertion"]}, {**self.item, "command": "cargo build"}, self.now, "challenge"),
        ):
            with self.subTest(name=name), self.assertRaisesRegex(signing.Refused, pattern):
                verifier.check(given, item, "", self.trust, now)
        review = signing.rule_payload("fedcba9876543211", ["review"], "", "feature/*", "/repo/*", int(self.now) + 3600)
        commit = signing.review_item("0123456789abcdef", "/repo/.git", "/repo/.worktrees/feature/x", "feature/x", "0" * 40)
        verifier.check(signer.proof(review, ORIGIN), commit, "pass", self.trust, self.now)
        self.refused(signer.proof(review, ORIGIN), commit, "fail", "does not match")
        self.refused(signer.proof(review, ORIGIN), {**commit, "branch": "main"}, "pass", "does not match")

    def test_no_opener_follows_a_redirect(self):
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Redirect)
        self.addCleanup(server.server_close)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        for name, opener in (("client", hub_api.OPENER), ("llm", language.LLM_OPENER)):
            request = urllib.request.Request(f"{hub_api.base_url(server.server_address[1])}/api/asks")
            with self.subTest(name=name), self.assertRaises(urllib.error.HTTPError) as caught:
                opener.open(request, timeout=5)
            self.assertEqual(caught.exception.code, 302)

    def test_attestation_parsing_yields_the_pinned_key_of_each_algorithm(self):
        for alg in (-7, -8, -257):
            with self.subTest(alg=alg):
                signer = key(alg, "main")
                self.assertEqual(passkey.attested(signer.credential(ORIGIN, "localhost", REGISTERED), ORIGIN), {"id": signer.id, "alg": alg, "spki": b64(signer.spki)})
        signer = key(-7, "main")
        good = signer.credential(ORIGIN, "localhost", REGISTERED)
        attestation, _ = passkey.cbor(passkey.b64decode(good["attestationObject"], "attestationObject"), 0, 0)
        data = attestation["authData"]
        p384 = {1: 2, 3: -35, -1: 2, -2: bytes(48), -3: bytes(48)}
        swapped = data[:55] + key(-8, "stranger").raw_id + data[71:]
        for name, credential, pattern in (
            ("wrong origin", signer.credential("http://localhost:1", "localhost", REGISTERED), "origin"),
            ("wrong rpId", signer.credential(ORIGIN, "evil.example", REGISTERED), "rpIdHash"),
            ("no attested credential", signer.credential(ORIGIN, "localhost", PRESENT), "attested"),
            ("no user presence", signer.credential(ORIGIN, "localhost", 0x44), "user presence"),
            ("get instead of create", {**good, "clientDataJSON": b64(json.dumps({"type": "webauthn.get", "origin": ORIGIN}).encode())}, "webauthn.create"),
            ("other id", {**good, "id": key(-8, "stranger").id}, "differs"),
            ("swapped id", {**good, "attestationObject": b64(cbor_encode({"fmt": "none", "attStmt": {}, "authData": swapped}))}, "differs"),
            ("truncated", {**good, "attestationObject": good["attestationObject"][:40]}, "CBOR|authData"),
            ("P-384", {**good, "attestationObject": b64(cbor_encode({"fmt": "none", "attStmt": {}, "authData": data[:71] + cbor_encode(p384)}))}, "none of"),
            ("extra field", {**good, "type": "public-key"}, "exactly"),
        ):
            with self.subTest(name=name), self.assertRaisesRegex(signing.Refused, pattern):
                passkey.attested(credential, ORIGIN)

    def test_a_coordinate_keepassxc_sent_without_its_leading_zero_bytes_pins_and_verifies(self):
        for label, name in ((-2, "x"), (-3, "y")):
            with self.subTest(coordinate=name):
                signer = zero_led(label)
                cose = signer.cose()
                short = {**cose, label: cose[label].lstrip(b"\x00")}
                self.assertLess(len(short[label]), 32)
                blob = b64(json.dumps(signer.registration(short, ORIGIN, "localhost", REGISTERED)).encode())
                argv = [sys.executable, str(APPROVAL), "pin", "--port", "8737", "--approvers", str(self.approvers), "--credential", blob]
                done = subprocess.run(argv, capture_output=True, text=True, timeout=60, check=False)
                self.assertEqual(done.returncode, 0, done.stderr)
                pinned = verifier.pinned(self.approvers)[-1]
                self.assertEqual((pinned["id"], pinned["alg"], pinned["spki"]), (signer.id, -7, b64(signer.spki)))
                verifier.check(signer.proof(self.payload([self.item], int(self.now) + 60), ORIGIN), self.item, "", self.trust, self.now)

    def test_a_coordinate_must_be_1_to_32_bytes_below_p_and_on_the_curve(self):
        signer = key(-7, "main")
        cose = signer.cose()
        prime = 2**256 - 2**224 + 2**192 + 2**96 - 1
        x, y = (int.from_bytes(cose[label], "big") for label in (-2, -3))
        root = pow((y * y - x**3 + 3 * x) % prime, (prime + 1) // 4, prime).to_bytes(32, "big")
        cases = [("x of p", {**cose, -2: prime.to_bytes(32, "big"), -3: root}), ("one-byte x off the curve", {**cose, -2: b"\x01"})]
        for label, name in ((-2, "x"), (-3, "y")):
            flipped = cose[label][:-1] + bytes([cose[label][-1] ^ 1])
            cases += [(f"empty {name}", {**cose, label: b""}), (f"33-byte {name}", {**cose, label: b"\x00" + cose[label]}), (f"{name} off the curve", {**cose, label: flipped})]
        for name, given in cases:
            with self.subTest(name=name), self.assertRaisesRegex(signing.Refused, "none of ES256"):
                passkey.attested(signer.registration(given, ORIGIN, "localhost", REGISTERED), ORIGIN)
        with self.subTest(name="one-byte x of 0 on the curve"):
            zero_x = passkey.attested(signer.registration({**cose, -2: b"\x00", -3: root}, ORIGIN, "localhost", REGISTERED), ORIGIN)
            self.assertEqual(zero_x["spki"], b64(passkey.EC_PREFIX + b"\x04" + bytes(32) + root))

    def test_the_cbor_decoder_reads_what_webauthn_sends_and_nothing_else(self):
        value = {"fmt": "none", 1: -7, -2: b"\x00\xff", "list": [0, 23, 24, 255, 256, 65536, 2**32, True, False, None], "text": "ä"}
        encoded = cbor_encode(value)
        self.assertEqual(passkey.cbor(encoded, 0, 0), (value, len(encoded)))
        for name, data in (
            ("indefinite array", b"\x9f\x01\xff"),
            ("float", b"\xfa\x00\x00\x00\x00"),
            ("tag", b"\xc0\x01"),
            ("truncated bytes", b"\x44\x00"),
            ("truncated length", b"\x19\x01"),
            ("repeated key", b"\xa2\x01\x01\x01\x02"),
            ("bad utf-8", b"\x61\xff"),
            ("too deep", b"\x81" * 40 + b"\x01"),
            ("empty", b""),
        ):
            with self.subTest(name=name), self.assertRaises(signing.Refused):
                passkey.cbor(data, 0, 0)

    def test_both_backends_verify_and_reject_the_same(self):
        backends = [passkey.by_openssl] if passkey.serialization is None else [passkey.by_openssl, passkey.by_library]
        for alg in (-7, -8, -257):
            signer = key(alg, "main")
            data = os.urandom(64)
            signature = signer.sign(data)
            for backend in backends:
                with self.subTest(alg=alg, backend=backend.__name__):
                    self.assertTrue(backend(alg, signer.spki, data, signature))
                    self.assertFalse(backend(alg, signer.spki, data + b"x", signature))
                    self.assertFalse(backend(alg, signer.spki, data, bytes(len(signature))))
                    self.assertFalse(backend({-7: -257, -8: -7, -257: -7}[alg], signer.spki, data, signature))
                    self.assertFalse(backend(-36, signer.spki, data, signature))
        signer = key(-8, "main")
        signer.pin(self.approvers, ORIGIN)
        with mock.patch.object(passkey, "serialization", None):
            verifier.check(signer.proof(self.payload([self.item], int(self.now) + 60), ORIGIN), self.item, "", self.trust, self.now)

    def test_the_pin_cli_writes_the_pinned_keys_with_mode_0600(self):
        approvers = self.base / "fresh" / "kvb-hub" / "approvers.json"

        def pin(blob: str, port: str) -> subprocess.CompletedProcess:
            argv = [sys.executable, str(APPROVAL), "pin", "--port", port, "--approvers", str(approvers), "--credential", blob]
            return subprocess.run(argv, capture_output=True, text=True, timeout=60, check=False)

        done = pin(key(-7, "main").blob(ORIGIN), "8737")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn(f"pinned {key(-7, 'main').id} (ES256)", done.stdout)
        self.assertEqual((stat.S_IMODE(approvers.stat().st_mode), stat.S_IMODE(approvers.parent.stat().st_mode)), (0o600, 0o700))
        self.assertEqual(pin(key(-7, "main").blob(ORIGIN), "8737").returncode, 0)
        self.assertEqual(pin(key(-8, "main").blob(ORIGIN), "8737").returncode, 0)
        self.assertEqual([(entry["id"], entry["alg"]) for entry in verifier.pinned(approvers)], [(key(-7, "main").id, -7), (key(-8, "main").id, -8)])
        self.assertEqual(stat.S_IMODE(approvers.stat().st_mode), 0o600)
        before = approvers.read_bytes()
        for blob, port, reason in ((key(-257, "main").blob(ORIGIN), "9999", "origin"), ("not-a-blob!", "8737", "base64url"), (b64(b"[1]"), "8737", "exactly")):
            with self.subTest(reason=reason):
                done = pin(blob, port)
                self.assertEqual(done.returncode, 1, done.stdout)
                self.assertIn(reason, done.stderr)
        self.assertEqual(approvers.read_bytes(), before)
        self.assertEqual(sorted(path.name for path in approvers.parent.iterdir()), ["approvers.json"])
        approvers.chmod(0o664)
        with self.assertRaisesRegex(signing.Refused, "writable by others"):
            verifier.pinned(approvers)


class TestPasskeyPage(unittest.TestCase):
    def test_the_section_and_a_failed_registration_name_the_keepassxc_localhost_setting(self):
        done = subprocess.run(["node", "-e", PASSKEY_PROBE, str(PASSKEY_PAGE)], capture_output=True, text=True, timeout=60, check=True)
        shown = json.loads(done.stdout)
        self.assertIn("nicht registriert: NotAllowedError", shown["failed"])
        for where in ("section", "failed"):
            for text in ("Nutzung von localhost mit Passkeys zulassen", "Allow using localhost with passkeys", "Passkeys request canceled.", "entsperrt"):
                with self.subTest(where=where, text=text):
                    self.assertIn(text, shown[where])


if __name__ == "__main__":
    unittest.main()
