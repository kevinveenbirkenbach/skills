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
        The exit code is 0. An ask for a Bash git commit carries the diff
        staged_diff.py builds of the tree its directory stages (of the
        working tree against HEAD with -a or --all), content withheld per
        the MEDUSA rules of the pipx install; none when it cannot be built
        or the body would pass DIFF_BODY_LIMIT. An allow of such an ask
        turns into a deny with CHANGED when what the commit records
        (staged_diff.binding) differs right before answering from the
        preview's, and with UNBOUND when either cannot be read.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import hub_api
import hub_limits
import signing
import staged_diff
import verifier

POLL = 25.0
NAME_LIMIT = 200
COMMAND_LIMIT = 4000
PATH_LIMIT = hub_limits.PATH_LIMIT
LIMITS = {"tool": NAME_LIMIT, "command": COMMAND_LIMIT, "cwd": PATH_LIMIT, "session": NAME_LIMIT, "agent": NAME_LIMIT}
DENIED = "The operator denied this in the Agent Orchestrator."
CHANGED = "staged tree changed since the preview"
UNBOUND = "the staged tree cannot be read, so the allow is not bound to it"
REASON_LIMIT = 2000
FAILURES = (OSError, ValueError, staged_diff.DiffError)


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


def commit_target(ask: dict) -> tuple[Path, bool] | None:
    return staged_diff.commit_of(ask["command"], ask["cwd"]) if ask["tool"] == "Bash" and ask["cwd"] else None


def commit_diff(ask: dict, rules: Path | None) -> tuple[str | None, dict]:
    """Returns:
        For a commit ask, what the commit records (staged_diff.binding, None
        when it cannot be read) and {"diff": the preview of exactly that},
        {} when it cannot be built; None and {} for any other ask.
    """
    target = commit_target(ask)
    if target is None:
        return None, {}
    try:
        pinned = staged_diff.binding(*target)
    except FAILURES as error:
        print(f"kvb-orchestrator: the ask goes without its diff and an allow of it turns into a deny: {error}", file=sys.stderr)
        return None, {}
    try:
        return pinned, {"diff": staged_diff.bound_diff(*target, pinned, rules)}
    except FAILURES as error:
        print(f"kvb-orchestrator: the ask goes without its diff: {error}", file=sys.stderr)
        return pinned, {}


def clean(text: str) -> str:
    """Returns:
        text on one line for the terminal and the agent: every character
        signing.unseen() names, a C0 or C1 control, a bidi or zero-width
        character among them, shown as ?, but a selector signing.presented()
        accepts; cut at REASON_LIMIT.
    """
    stripped = text.strip()
    return "".join("?" if signing.unseen(char) and not signing.presented(stripped, index) else char for index, char in enumerate(stripped))[:REASON_LIMIT]


def refusal(error: urllib.error.HTTPError) -> str:
    """Returns:
        The reason the hub sent with an error status, on one line, or the
        status text when its body cannot be read.
    """
    try:
        body = error.read().decode("utf-8", "replace")
    except OSError:
        body = ""
    return clean(body or str(error.reason))


def bound(chosen: dict | None, ask: dict, pinned: str | None) -> dict | None:
    """Args:
        pinned: what the commit recorded when the ask was made, None when
            that could not be read.

    Returns:
        chosen, or for an allow of a commit ask a deny with CHANGED when
        what it records now differs from pinned, with UNBOUND and the error
        when either cannot be read.
    """
    if chosen != {"behavior": "allow"} or commit_target(ask) is None:
        return chosen
    try:
        now = staged_diff.binding(*commit_target(ask))
    except FAILURES as error:
        return {"behavior": "deny", "message": f"{UNBOUND}: {clean(str(error))}"}
    if pinned is None:
        return {"behavior": "deny", "message": UNBOUND}
    return chosen if now == pinned else {"behavior": "deny", "message": CHANGED}


def encoded(payload: dict) -> bytes:
    return json.dumps(payload).encode()


def create(base: str, ask: dict, timeout: float, shown: dict) -> str:
    data = encoded({**ask, "timeout": timeout, **shown})
    if len(data) > hub_limits.DIFF_BODY_LIMIT:
        print(f"kvb-orchestrator: the ask goes without its diff, its {len(data)} bytes pass the hub's {hub_limits.DIFF_BODY_LIMIT}", file=sys.stderr)
        data = encoded({**ask, "timeout": timeout})
    headers = {"Content-Type": "application/json", **hub_api.GUARD}
    request = urllib.request.Request(f"{base}/api/asks", data=data, headers=headers, method="POST")
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
    return f"{DENIED} Reason: {clean(reason)}"


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
        pinned, shown = commit_diff(ask, staged_diff.rules_root())
        ask_id = create(base, ask, args.timeout, shown)
        answer = {"status": "pending"}
        while answer["status"] == "pending" and (left := deadline - time.monotonic()) > 0:
            answer = status(base, ask_id, min(left, POLL))
    except urllib.error.HTTPError as error:
        print(f"kvb-orchestrator: the hub answered {error.code}, Claude Code asks instead: {refusal(error)}", file=sys.stderr)
        return 0
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return 0
    chosen = bound(decision(answer, signing.ask_item(ask_id, ask["tool"], ask["command"], ask["cwd"], ask["session"]), trust), ask, pinned)
    if chosen is not None:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": chosen}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
