from __future__ import annotations

import base64
import fnmatch
import hashlib
import json
import re
from pathlib import Path

RP_ID = "localhost"
VERSION = 1
LIFETIME = 900
RULE_LIFETIME = 366 * 86400
ALGORITHMS = {-7: "ES256", -8: "EdDSA", -257: "RS256"}
HASH = re.compile(r"[0-9a-f]{64}")
NONCE = re.compile(r"[0-9a-f]{32}")
ID = re.compile(r"[0-9a-f]{16}")
CHAINED = re.compile(r"[;&|`$<>()\n\r]")
APPROVAL_KEYS = {"v", "kind", "items", "nonce", "expires"}
RULE_KEYS = {"v", "kind", "id", "kinds", "tool", "pattern", "scope", "expires"}
WARNINGS = (
    ("löscht rekursiv", re.compile(r"\brm\s+(?:-\S+\s+)*-\S*[rR]")),
    ("erzwingt", re.compile(r"--force\b|\bpush\b.*\s-f\b")),
    ("pusht", re.compile(r"\bgit\b.*\bpush\b")),
    ("root", re.compile(r"\bsudo\b|\bdoas\b")),
    ("Pipe in eine Shell", re.compile(r"\|\s*(?:sudo\s+)?(?:ba|z|k|da)?sh\b")),
    ("verwirft Änderungen", re.compile(r"\bgit\b.*\b(?:reset\s+--hard|clean\s+-\S*f)")),
    ("Docker löscht", re.compile(r"\bdocker\s+(?:system\s+prune|volume\s+(?:rm|prune)|rmi?\b)")),
)


class Refused(Exception):
    pass


def origin_of(port: int) -> str:
    return f"http://{RP_ID}:{port}"


def b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")


def challenge(payload: dict) -> str:
    return b64encode(hashlib.sha256(canonical(payload)).digest())


def item_hash(item: dict) -> str:
    return hashlib.sha256(canonical(item)).hexdigest()


def ask_item(ask_id: str, tool: str, command: str, cwd: str, session: str) -> dict:
    return {"kind": "ask", "id": ask_id, "tool": tool, "command": command, "cwd": cwd, "session": session}


def review_item(review_id: str, repo: str, worktree: str, branch: str, tree: str) -> dict:
    return {"kind": "review", "id": review_id, "repo": repo, "worktree": worktree, "branch": branch, "tree": tree}


def operator_item(task: str, command: str, directory: str) -> dict:
    return {"kind": "operator", "id": task, "command": command, "directory": directory}


def cleanup_item(repository: str, branch: str, worktree: str, tip: str) -> dict:
    return {"kind": "cleanup", "repository": repository, "branch": branch, "worktree": worktree, "tip": tip}


def approval_payload(hashes: list[str], nonce: str, expires: int) -> dict:
    return {"v": VERSION, "kind": "approve", "items": sorted(set(hashes)), "nonce": nonce, "expires": expires}


def rule_payload(rule_id: str, kinds: list[str], tool: str, pattern: str, scope: str, expires: int) -> dict:
    return {"v": VERSION, "kind": "rule", "id": rule_id, "kinds": kinds, "tool": tool, "pattern": pattern, "scope": scope, "expires": expires}


def warnings(command: str) -> list[str]:
    return [label for label, pattern in WARNINGS if pattern.search(command)]


def expiry(value: object, now: float, cap: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise Refused("the expiry is no whole number of epoch seconds")
    if value <= now:
        raise Refused("the signature has expired")
    if value > now + cap:
        raise Refused("the expiry lies too far ahead")
    return value


def checked_approval(payload: object, now: float) -> dict:
    if not isinstance(payload, dict) or set(payload) != APPROVAL_KEYS or payload["v"] != VERSION or payload["kind"] != "approve":
        raise Refused("the payload is no approval")
    items = payload["items"]
    if not isinstance(items, list) or not items or not all(isinstance(entry, str) and HASH.fullmatch(entry) for entry in items):
        raise Refused("the approval lists no item hashes")
    if not isinstance(payload["nonce"], str) or not NONCE.fullmatch(payload["nonce"]):
        raise Refused("the approval holds no nonce")
    expiry(payload["expires"], now, LIFETIME)
    return payload


def checked_rule(payload: object, now: float) -> dict:
    if not isinstance(payload, dict) or set(payload) != RULE_KEYS or payload["v"] != VERSION or payload["kind"] != "rule":
        raise Refused("the payload is no rule")
    if not isinstance(payload["id"], str) or not ID.fullmatch(payload["id"]):
        raise Refused("the rule holds no id")
    kinds = payload["kinds"]
    if not isinstance(kinds, list) or not kinds or not all(isinstance(kind, str) for kind in kinds):
        raise Refused("the rule names no kinds")
    if not isinstance(payload["tool"], str) or not all(isinstance(payload[name], str) and payload[name] for name in ("pattern", "scope")):
        raise Refused("the rule needs a tool text, a pattern and a scope")
    expiry(payload["expires"], now, RULE_LIFETIME)
    return payload


def rule_allows(rule: dict, item: dict, gate: str, now: float) -> bool:
    if rule["expires"] <= now or item["kind"] not in rule["kinds"]:
        return False
    if item["kind"] == "ask":
        named = fnmatch.fnmatchcase(item["tool"], rule["tool"]) and fnmatch.fnmatchcase(item["cwd"], rule["scope"])
        plain = not CHAINED.search(item["command"]) and not warnings(item["command"])
        return named and plain and fnmatch.fnmatchcase(item["command"], rule["pattern"])
    if item["kind"] == "review":
        return gate == "pass" and fnmatch.fnmatchcase(item["branch"], rule["pattern"]) and fnmatch.fnmatchcase(item["worktree"], rule["scope"])
    return False


def load_pinned(path: Path) -> list[dict]:
    try:
        mode = path.stat().st_mode
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError, RecursionError) as error:
        raise Refused(f"the pinned keys in {path} are unreadable") from error
    if mode & 0o022:
        raise Refused(f"{path} is writable by others")
    entries = data.get("credentials") if isinstance(data, dict) else None
    shaped = isinstance(entries, list) and all(isinstance(entry, dict) and isinstance(entry.get("id"), str) and entry.get("alg") in ALGORITHMS and isinstance(entry.get("spki"), str) for entry in entries)
    if not shaped:
        raise Refused(f"the pinned keys in {path} are malformed")
    return entries
