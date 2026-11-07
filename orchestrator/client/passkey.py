from __future__ import annotations

import base64
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path

from signing import RP_ID, Refused, b64encode, challenge

try:
    from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec, ed25519, padding, rsa
except ImportError:
    serialization = None

FLAG_UP = 0x01
FLAG_AT = 0x40
EC_PREFIX = bytes.fromhex("3059301306072a8648ce3d020106082a8648ce3d030107034200")
P256_PRIME = 2**256 - 2**224 + 2**192 + 2**96 - 1
P256_B = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B
ED_PREFIX = bytes.fromhex("302a300506032b6570032100")
RSA_IDENTIFIER = bytes.fromhex("300d06092a864886f70d0101010500")
B64URL = re.compile(r"[A-Za-z0-9_-]+")
ASSERTION_KEYS = ("id", "clientDataJSON", "authenticatorData", "signature")
CBOR_DEPTH = 16
TIMEOUT = 30


def b64decode(text: object, name: str) -> bytes:
    if not isinstance(text, str) or not B64URL.fullmatch(text):
        raise Refused(f"{name} is no base64url text")
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except ValueError as error:
        raise Refused(f"{name} is no base64url text") from error


def cbor(data: bytes, offset: int, depth: int) -> tuple[object, int]:
    if depth > CBOR_DEPTH or offset >= len(data):
        raise Refused("the CBOR data is truncated or nests too deep")
    major, info = data[offset] >> 5, data[offset] & 0x1F
    offset += 1
    value = info
    if 24 <= info <= 27:
        size = 1 << (info - 24)
        if offset + size > len(data):
            raise Refused("the CBOR data is truncated")
        value = int.from_bytes(data[offset : offset + size], "big")
        offset += size
    elif info > 27:
        raise Refused("the CBOR data uses an indefinite or reserved length")
    if major == 0:
        return value, offset
    if major == 1:
        return -1 - value, offset
    if major in (2, 3):
        chunk = data[offset : offset + value]
        if len(chunk) != value:
            raise Refused("the CBOR data is truncated")
        if major == 2:
            return chunk, offset + value
        try:
            return chunk.decode("utf-8"), offset + value
        except UnicodeDecodeError as error:
            raise Refused("the CBOR text is no UTF-8") from error
    if major == 4:
        items = []
        for _ in range(value):
            item, offset = cbor(data, offset, depth + 1)
            items.append(item)
        return items, offset
    if major == 5:
        entries: dict = {}
        for _ in range(value):
            key, offset = cbor(data, offset, depth + 1)
            if isinstance(key, bool) or not isinstance(key, int | str) or key in entries:
                raise Refused("the CBOR map holds a bad or repeated key")
            entries[key], offset = cbor(data, offset, depth + 1)
        return entries, offset
    if major == 7 and info in (20, 21, 22):
        return {20: False, 21: True, 22: None}[info], offset
    raise Refused("the CBOR data holds an unsupported item")


def der(tag: int, body: bytes) -> bytes:
    size = len(body)
    if size < 0x80:
        return bytes([tag, size]) + body
    octets = size.to_bytes((size.bit_length() + 7) // 8, "big")
    return bytes([tag, 0x80 | len(octets)]) + octets + body


def der_integer(value: bytes) -> bytes:
    digits = value.lstrip(b"\x00") or b"\x00"
    return der(0x02, b"\x00" + digits if digits[0] & 0x80 else digits)


def octets(value: object, size: int) -> bool:
    return isinstance(value, bytes) and len(value) == size


def p256_point(x: object, y: object) -> bytes | None:
    # KeePassXC 2.7.12 drops leading zero bytes of x and y (Botan BigInt as hex), against RFC 9053; pad them back to 32.
    if not all(isinstance(value, bytes) and 1 <= len(value) <= 32 for value in (x, y)):
        return None
    left, right = int.from_bytes(x, "big"), int.from_bytes(y, "big")
    if left >= P256_PRIME or right >= P256_PRIME or (right * right - left**3 + 3 * left - P256_B) % P256_PRIME:
        return None
    return b"\x04" + left.to_bytes(32, "big") + right.to_bytes(32, "big")


def cose_key(key: object) -> tuple[int, bytes]:
    if not isinstance(key, dict):
        raise Refused("the credential public key is no COSE map")
    kty, alg = key.get(1), key.get(3)
    if kty == 2 and alg == -7 and key.get(-1) == 1 and (point := p256_point(key.get(-2), key.get(-3))):
        return alg, EC_PREFIX + point
    if kty == 1 and alg == -8 and key.get(-1) == 6 and octets(key.get(-2), 32):
        return alg, ED_PREFIX + key[-2]
    if kty == 3 and alg == -257 and isinstance(key.get(-1), bytes) and isinstance(key.get(-2), bytes) and key[-1] and key[-2]:
        public = der(0x30, der_integer(key[-1]) + der_integer(key[-2]))
        return alg, der(0x30, RSA_IDENTIFIER + der(0x03, b"\x00" + public))
    raise Refused("the key is none of ES256 on P-256, EdDSA on Ed25519 or RS256")


def client_data(raw: bytes, kind: str, origin: str) -> dict:
    try:
        client = json.loads(raw)
    except (ValueError, RecursionError) as error:
        raise Refused("clientDataJSON is no JSON") from error
    if not isinstance(client, dict) or client.get("type") != kind:
        raise Refused(f"clientDataJSON is no {kind}")
    if client.get("origin") != origin or client.get("crossOrigin") is True:
        raise Refused(f"the origin is not {origin}")
    return client


def rp_flags(data: bytes, size: int) -> int:
    if len(data) < size or data[:32] != hashlib.sha256(RP_ID.encode("ascii")).digest():
        raise Refused(f"the rpIdHash is not the one of {RP_ID}")
    if not data[32] & FLAG_UP:
        raise Refused("the user presence flag is missing")
    return data[32]


def attested(credential: object, origin: str) -> dict:
    """Args:
        credential: {"id", "attestationObject", "clientDataJSON"} as the
            settings panel encodes the navigator.credentials.create answer.
        origin: the only origin the registration may come from.

    Returns:
        The entry to pin: {"id", "alg", "spki"}, the key as base64url DER.
    """
    if not isinstance(credential, dict) or set(credential) != {"id", "attestationObject", "clientDataJSON"}:
        raise Refused("the credential needs exactly id, attestationObject and clientDataJSON")
    raw_id = b64decode(credential["id"], "id")
    client_data(b64decode(credential["clientDataJSON"], "clientDataJSON"), "webauthn.create", origin)
    blob = b64decode(credential["attestationObject"], "attestationObject")
    attestation, end = cbor(blob, 0, 0)
    if end != len(blob) or not isinstance(attestation, dict) or not isinstance(attestation.get("authData"), bytes):
        raise Refused("the attestationObject holds no authData")
    data = attestation["authData"]
    if not rp_flags(data, 55) & FLAG_AT:
        raise Refused("the registration carries no attested credential")
    size = int.from_bytes(data[53:55], "big")
    if data[55 : 55 + size] != raw_id:
        raise Refused("the attested credential id differs from the id")
    key, _ = cbor(data, 55 + size, 0)
    alg, spki = cose_key(key)
    return {"id": b64encode(raw_id), "alg": alg, "spki": b64encode(spki)}


def by_library(alg: int, spki: bytes, data: bytes, signature: bytes) -> bool:
    try:
        key = serialization.load_der_public_key(spki)
        if alg == -7 and isinstance(key, ec.EllipticCurvePublicKey) and isinstance(key.curve, ec.SECP256R1):
            key.verify(signature, data, ec.ECDSA(hashes.SHA256()))
        elif alg == -8 and isinstance(key, ed25519.Ed25519PublicKey):
            key.verify(signature, data)
        elif alg == -257 and isinstance(key, rsa.RSAPublicKey):
            key.verify(signature, data, padding.PKCS1v15(), hashes.SHA256())
        else:
            return False
    except (InvalidSignature, UnsupportedAlgorithm, ValueError, TypeError):
        return False
    return True


def key_type(alg: int, spki: bytes) -> bool:
    if alg == -7:
        return len(spki) == len(EC_PREFIX) + 65 and spki.startswith(EC_PREFIX)
    if alg == -8:
        return len(spki) == len(ED_PREFIX) + 32 and spki.startswith(ED_PREFIX)
    return alg == -257 and RSA_IDENTIFIER in spki[:24]


def by_openssl(alg: int, spki: bytes, data: bytes, signature: bytes) -> bool:
    if not key_type(alg, spki):
        return False
    try:
        with tempfile.TemporaryDirectory(prefix="kvb-orchestrator-verify-") as folder:
            key, message, sealed = (Path(folder) / name for name in ("key.pem", "data.bin", "signature.bin"))
            key.write_text(f"-----BEGIN PUBLIC KEY-----\n{base64.encodebytes(spki).decode('ascii')}-----END PUBLIC KEY-----\n", encoding="ascii")
            message.write_bytes(data)
            sealed.write_bytes(signature)
            if alg == -8:
                argv = ["openssl", "pkeyutl", "-verify", "-pubin", "-inkey", str(key), "-rawin", "-in", str(message), "-sigfile", str(sealed)]
            else:
                argv = ["openssl", "dgst", "-sha256", "-verify", str(key), "-signature", str(sealed), str(message)]
            try:
                done = subprocess.run(argv, capture_output=True, timeout=TIMEOUT, check=False)
            except (OSError, subprocess.TimeoutExpired):
                return False
    except OSError as error:
        raise Refused(f"openssl found no writable temporary directory (TMPDIR): {error.strerror}") from None
    return done.returncode == 0


def verify_signature(alg: int, spki: bytes, data: bytes, signature: bytes) -> bool:
    if serialization is None:
        return by_openssl(alg, spki, data, signature)
    return by_library(alg, spki, data, signature)


def verify_assertion(assertion: object, payload: dict, credentials: list[dict], origin: str) -> int:
    """Args:
        assertion: {"id", "clientDataJSON", "authenticatorData", "signature"}
            from navigator.credentials.get, base64url.
        payload: the payload whose challenge the operator signed.
        credentials: the pinned keys.
        origin: the only origin the signature may come from.

    Returns:
        The authenticator's signature counter.
    """
    if not isinstance(assertion, dict) or not all(isinstance(assertion.get(name), str) for name in ASSERTION_KEYS):
        raise Refused("the assertion is incomplete")
    credential = next((entry for entry in credentials if entry["id"] == assertion["id"]), None)
    if credential is None:
        raise Refused("the signing key is not pinned")
    raw = b64decode(assertion["clientDataJSON"], "clientDataJSON")
    if client_data(raw, "webauthn.get", origin).get("challenge") != challenge(payload):
        raise Refused("the challenge is not the one of the payload")
    data = b64decode(assertion["authenticatorData"], "authenticatorData")
    rp_flags(data, 37)
    signed = data + hashlib.sha256(raw).digest()
    if not verify_signature(credential["alg"], b64decode(credential["spki"], "spki"), signed, b64decode(assertion["signature"], "signature")):
        raise Refused("the signature does not verify with the pinned key")
    return int.from_bytes(data[33:37], "big")
