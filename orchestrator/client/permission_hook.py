#!/usr/bin/env python3
"""Args:
    --port: port of the Agent Orchestrator on 127.0.0.1; the signature's origin is
        http://localhost:<port>.
    --timeout: seconds to wait for the operator's decision; keep it below the
        hook's timeout in settings.json.
    --approvers: the pinned passkeys, e.g. ~/.config/kvb-orchestrator/approvers.json.
    --replay: this hook's replay store, outside the hub's reach, e.g.
        ~/.local/state/kvb-orchestrator-approvals/hook.json.
    stdin: the Claude Code PermissionRequest hook input.

Returns:
    stdout: the PermissionRequest decision JSON: allow only when a pinned
        passkey signed exactly this tool, command, cwd, session and ask id;
        deny when the operator denied in the Agent Orchestrator, with the
        reason only when a pinned passkey signed it. Nothing on timeout,
        error, a missing or invalid signature, a value longer than the hub
        takes or a hub that is down, so Claude Code shows its own dialog.
        The exit code is 0.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

import hub_api
import signing
import verifier

POLL = 25.0
NAME_LIMIT = 200
COMMAND_LIMIT = 4000
PATH_LIMIT = 4096
LIMITS = {"tool": NAME_LIMIT, "command": COMMAND_LIMIT, "cwd": PATH_LIMIT, "session": NAME_LIMIT, "agent": NAME_LIMIT}
DENIED = "The operator denied this in the Agent Orchestrator."
REASON_LIMIT = 2000
CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def summary(tool_input: object) -> str:
    if isinstance(tool_input, dict):
        for key in ("command", "file_path", "url", "pattern", "path"):
            if isinstance(tool_input.get(key), str):
                return tool_input[key]
    return json.dumps(tool_input, ensure_ascii=False)


def facts(hook: dict) -> dict:
    return {
        "tool": str(hook.get("tool_name") or "?"),
        "command": summary(hook.get("tool_input")),
        "cwd": str(hook.get("cwd") or ""),
        "session": str(hook.get("session_id") or ""),
        "agent": str(hook.get("agent_type") or ""),
    }


def create(base: str, ask: dict, timeout: float) -> str:
    payload = {**ask, "timeout": timeout}
    headers = {"Content-Type": "application/json", **hub_api.GUARD}
    request = urllib.request.Request(f"{base}/api/asks", data=json.dumps(payload).encode(), headers=headers, method="POST")
    ask_id = hub_api.call(request, hub_api.SLACK)["id"]
    if not isinstance(ask_id, str) or not signing.ID.fullmatch(ask_id):
        raise ValueError("the hub answered no ask id")
    return ask_id


def status(base: str, ask_id: str, wait: float) -> dict:
    answer = hub_api.call(urllib.request.Request(f"{base}/api/asks/{ask_id}?wait={wait:.1f}"), wait + hub_api.SLACK)
    if not isinstance(answer.get("status"), str):
        raise TypeError("the hub answered no status")
    return answer


def denied(answer: dict, item: dict, trust: verifier.Trust) -> str:
    reason, channel, to = answer.get("reason"), answer.get("channel"), answer.get("to")
    if not all(isinstance(value, str) for value in (reason, channel, to)) or not reason.strip():
        return DENIED
    try:
        verifier.check(answer.get("proof"), signing.denial_item(item, channel, reason, to), "", trust, time.time())
    except (signing.Refused, OSError) as error:
        print(f"kvb-orchestrator: the reason is not signed, the agent gets the denial without it: {error}", file=sys.stderr)
        return DENIED
    return f"{DENIED} Reason: {CONTROL.sub('?', reason.strip())[:REASON_LIMIT]}"


def decision(answer: dict, item: dict, trust: verifier.Trust) -> dict | None:
    if answer["status"] == "denied":
        return {"behavior": "deny", "message": denied(answer, item, trust)}
    if answer["status"] != "allowed":
        return None
    try:
        verifier.check(answer.get("proof"), item, "", trust, time.time())
    except (signing.Refused, OSError) as error:
        print(f"kvb-orchestrator: not signed, Claude Code asks instead: {error}", file=sys.stderr)
        return None
    return {"behavior": "allow"}


def main() -> int:
    parser = argparse.ArgumentParser(prog="permission_hook")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--timeout", type=float, required=True)
    parser.add_argument("--approvers", type=Path, required=True)
    parser.add_argument("--replay", type=Path, required=True)
    args = parser.parse_args()
    base = hub_api.base_url(args.port)
    trust = verifier.Trust(approvers=args.approvers, replay=args.replay, origin=signing.origin_of(args.port))
    deadline = time.monotonic() + args.timeout
    try:
        hook = json.load(sys.stdin)
        ask = facts(hook)
        too_long = [name for name, limit in LIMITS.items() if len(ask[name]) > limit]
        if too_long:
            print(f"kvb-orchestrator: {', '.join(too_long)} too long to sign in full, Claude Code asks instead", file=sys.stderr)
            return 0
        ask_id = create(base, ask, args.timeout)
        answer = {"status": "pending"}
        while answer["status"] == "pending" and (left := deadline - time.monotonic()) > 0:
            answer = status(base, ask_id, min(left, POLL))
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return 0
    chosen = decision(answer, signing.ask_item(ask_id, ask["tool"], ask["command"], ask["cwd"], ask["session"]), trust)
    if chosen is not None:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": chosen}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
