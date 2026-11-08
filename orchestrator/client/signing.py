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
OFFICE = re.compile(r"chair|[a-z0-9][a-z0-9._-]{0,63}/[a-z0-9][a-z0-9._-]{0,63}")
SESSION = re.compile(r"(?!-)[A-Za-z0-9_-]{1,128}")
WORK = re.compile(r"(?=[^\x00-\x1f\x7f]*\S)[^\x00-\x1f\x7f]{1,300}")
HOLDER = re.compile(r"[^\x00-\x1f\x7f]{0,200}")
OFFICE_ACTIONS = ("appoint", "takeover", "recall")
OFFICE_KEYS = ("action", "office", "holder", "session", "work")
TASK = re.compile(r"[a-z0-9][a-z0-9._-]{0,99}(?:/[a-z0-9][a-z0-9._-]{0,99}){0,7}")
PRIO = re.compile(r"[1-9][0-9]{0,2}")
FIBONACCI = ("1", "2", "3", "5", "8", "13", "21", "34", "55", "89")
ESTIMATOR = "Operator"
COMMANDS = "operator/"
APPROVAL_KEYS = {"v", "kind", "items", "nonce", "expires"}
RULE_KEYS = {"v", "kind", "id", "kinds", "tool", "pattern", "scope", "expires"}
WARNINGS = (
    ("deletes recursively", re.compile(r"\brm\s+(?:-\S+\s+)*-\S*[rR]")),
    ("forces", re.compile(r"--force\b|\bpush\b.*\s-f\b")),
    ("pushes", re.compile(r"\bgit\b.*\bpush\b")),
    ("root", re.compile(r"\bsudo\b|\bdoas\b")),
    ("pipes into a shell", re.compile(r"\|\s*(?:sudo\s+)?(?:ba|z|k|da)?sh\b")),
    ("discards changes", re.compile(r"\bgit\b.*\b(?:reset\s+--hard|clean\s+-\S*f)")),
    ("Docker deletes", re.compile(r"\bdocker\s+(?:system\s+prune|volume\s+(?:rm|prune)|rmi?\b)")),
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


def office_item(action: str, office: str, holder: str, session: str, work: str) -> dict:
    return {"kind": "office", "action": action, "office": office, "holder": holder, "session": session, "work": work}


def office_problem(order: object) -> str | None:
    """Args:
        order: {"action", "office", "holder", "session", "work"}: appoint
            gives a vacant office to the session, takeover hands the
            holder's office to the session, recall takes it from the
            holder; work is the claim's one-line --work.

    Returns:
        Why the order is malformed, or None.
    """
    if not isinstance(order, dict) or set(order) != set(OFFICE_KEYS) or not all(isinstance(order[name], str) for name in OFFICE_KEYS):
        return "an office order holds exactly action, office, holder, session and work as text"
    action, office, holder, session, work = (order[name] for name in OFFICE_KEYS)
    if action not in OFFICE_ACTIONS:
        return f"action must be one of {', '.join(OFFICE_ACTIONS)}"
    if not OFFICE.fullmatch(office):
        return "office must be chair, <dimension>/<line>, cluster/<slug> or work/<slug>"
    if not HOLDER.fullmatch(holder) or (action == "appoint") != (holder == ""):
        return "appoint names no holder, takeover and recall the current one"
    if action == "recall":
        return None if session == work == "" else "a recall names no successor and no work"
    if not SESSION.fullmatch(session) or session == holder:
        return "session must be the successor's session id, not the holder's"
    if not WORK.fullmatch(work):
        return "work must be one line of 1 to 300 characters"
    return None


def rule_request_item(request_id: str, kind: str, tool: str, pattern: str, scope: str, expires: int) -> dict:
    return {"kind": "rule-request", "id": request_id, "rule": kind, "tool": tool, "pattern": pattern, "scope": scope, "expires": expires}


def denial_item(subject: dict, channel: str, reason: str, to: str) -> dict:
    """Args:
        subject: the item an approval of it would sign.
        channel: the radio class that tells the requesting agent.
        reason: the operator's reason, possibly empty.
        to: the requesting agent's name for a direct channel, "*" for a
            class to all.

    Returns:
        The item a denial signs: its hash never equals the subject's, so no
        denial signature approves anything.
    """
    return {"kind": "deny", "subject": item_hash(subject), "channel": channel, "reason": reason, "to": to}


def message_item(to: str, cls: str, text: str, upload: str, voice: str, voice_sha256: str) -> dict:
    return {"kind": "message", "to": to, "class": cls, "text": text, "upload": upload, "voice": voice, "voice_sha256": voice_sha256}


def board_item(action: str) -> dict:
    return {"kind": "board", "action": action}


def stream_item(origins: list[str], urls: list[str]) -> dict:
    return {"kind": "streams", "origins": origins, "urls": urls}


def task_item(task: str, argv: list[str]) -> dict:
    return {"kind": "task", "id": task, "argv": argv}


def task_argv(task: object, argv: object) -> list[str]:
    """Args:
        task: the register task the change is for, a rasci.py slug outside
            operator/.
        argv: the rasci.py arguments, one of `set <task> --prio <1-999>`,
            `estimate <task> Operator --value <fib> --complexity <fib>` or
            `estimate <task> Operator --drop`.

    Returns:
        argv, the hub and the runner check it the same way.

    Raises:
        Refused for every other task or argv.
    """
    if not isinstance(task, str) or not TASK.fullmatch(task) or task.startswith(COMMANDS):
        raise Refused("the task is no register task slug outside operator/")
    if not isinstance(argv, list) or not all(isinstance(part, str) for part in argv):
        raise Refused("the argv is no list of texts")
    rest = argv[3:]
    pinned = argv[:3] == ["set", task, "--prio"] and len(argv) == 4 and bool(PRIO.fullmatch(argv[3]))
    estimated = len(rest) == 4 and rest[0] == "--value" and rest[1] in FIBONACCI and rest[2] == "--complexity" and rest[3] in FIBONACCI
    if pinned or (argv[:3] == ["estimate", task, ESTIMATOR] and (estimated or rest == ["--drop"])):
        return argv
    raise Refused("the argv is no task priority or WSJF estimate change of this task")


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
