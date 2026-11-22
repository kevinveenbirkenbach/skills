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
        The exit code is 0. An ask for a Bash git commit of exactly the
        staged index (staged_diff.commit_of) carries the diff staged_diff.py
        builds of the tree its directory stages, secrets masked per the
        MEDUSA rules of the pipx install, and the sealed clear patches of
        its masked files apart; neither when it cannot be built or the body
        would pass DIFF_BODY_LIMIT. An allow of such an ask turns
        into a deny with CHANGED when what the commit records
        (staged_diff.binding) differs right before answering from the
        preview's, and with UNBOUND when either cannot be read. An ask for
        a Bash git commit-tree of full object ids (staged_diff.tree_of)
        carries the diff of its tree against its first parent the same way.
        Any other Bash command that may run git commit (-a, --all, -i, -o,
        -p, a pathspec, a chain, a wrapper) is not approvable: no ask
        reaches the hub, stderr gets WORKTREE and Claude Code shows its own
        dialog. An AskUserQuestion call becomes one hub decision per
        question; once a pinned passkey signed the pick of every question,
        the allow carries updatedInput with the questions and their
        answers, the labels of a multi-select pick joined by ", ".
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
import passkey
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
WORKTREE = "commit reads the working tree; stage the files and commit the index"
ALLOW = {"behavior": "allow"}
REASON_LIMIT = 2000
FAILURES = (OSError, ValueError, staged_diff.DiffError)
QUESTION_TOOL = "AskUserQuestion"
OPTION_KEYS = ("label", "description", "preview")


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


def commit_target(ask: dict) -> Path | None:
    return staged_diff.commit_of(ask["command"], ask["cwd"]) if ask["tool"] == "Bash" and ask["cwd"] else None


def tree_target(ask: dict) -> tuple[Path, str, list[str]] | None:
    return staged_diff.tree_of(ask["command"], ask["cwd"]) if ask["tool"] == "Bash" and ask["cwd"] else None


def unapprovable(ask: dict) -> bool:
    return ask["tool"] == "Bash" and staged_diff.names_commit(ask["command"]) and commit_target(ask) is None and tree_target(ask) is None


def tree_preview(ask: dict, rules: Path | None) -> dict:
    found = tree_target(ask)
    if found is None:
        return {}
    try:
        diff, sealed = staged_diff.commit_tree_diff(*found, rules)
        return {"diff": diff, "sealed": sealed}
    except FAILURES as error:
        print(f"kvb-orchestrator: the ask goes without its diff: {error}", file=sys.stderr)
        return {}


def commit_diff(ask: dict, rules: Path | None) -> tuple[str | None, dict]:
    """Returns:
        For a commit ask, what the commit records (staged_diff.binding, None
        when it cannot be read) and {"diff": the preview of exactly that,
        "sealed": the clear patches of its masked files}, {} when it cannot
        be built; for a commit-tree ask None and its tree_preview, which
        needs no binding: its object ids name content no write can change;
        None and {} for any other ask.
    """
    target = commit_target(ask)
    if target is None:
        return None, tree_preview(ask, rules)
    try:
        pinned = staged_diff.binding(target)
    except FAILURES as error:
        print(f"kvb-orchestrator: the ask goes without its diff and an allow of it turns into a deny: {error}", file=sys.stderr)
        return None, {}
    try:
        diff, sealed = staged_diff.bound_diff(target, pinned, rules)
        return pinned, {"diff": diff, "sealed": sealed}
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
        when either cannot be read; None for an allow of an unapprovable ask.
    """
    if chosen != ALLOW:
        return chosen
    if unapprovable(ask):
        return None
    target = commit_target(ask)
    if target is None:
        return chosen
    try:
        now = staged_diff.binding(target)
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


def asked_questions(hook: dict) -> list[dict] | None:
    """Returns:
        The questions of an AskUserQuestion call, None for any other tool
        call and for input of another shape.
    """
    if hook.get("tool_name") != QUESTION_TOOL or not isinstance(hook.get("tool_input"), dict):
        return None
    questions = hook["tool_input"].get("questions")
    if not isinstance(questions, list) or not questions:
        return None
    if not all(isinstance(question, dict) and isinstance(question.get("question"), str) and isinstance(question.get("options"), list) for question in questions):
        print("kvb-orchestrator: a malformed question stays in the terminal", file=sys.stderr)
        return None
    return questions


def ask_question(base: str, question: dict, session: str, timeout: float) -> str:
    options = [{key: option[key] for key in OPTION_KEYS if key in option} if isinstance(option, dict) else option for option in question["options"]]
    data = encoded({"question": question["question"], "options": options, "session": session, "timeout": timeout, "multi": question.get("multiSelect") is True})
    request = urllib.request.Request(f"{base}/api/decisions", data=data, headers={"Content-Type": "application/json", **hub_api.GUARD}, method="POST")
    decision_id = hub_api.call(request, hub_api.SLACK)["id"]
    if not isinstance(decision_id, str) or not signing.ID.fullmatch(decision_id):
        raise ValueError("the hub answered no decision id")
    return decision_id


def picked(base: str, decision_id: str, question: dict, deadline: float) -> tuple[dict, str] | None:
    """Returns:
        The hub's decided answer for the decision decision_id and the answer
        to the question it holds, its signature not yet checked: the
        option's label, for a multi-select question the picked labels in
        option order joined by ", ", or the one line of other text that
        names no option; None when the decision expires, the deadline
        passes or a multi-line pick holds a line that is no option of the
        question.
    """
    answer = {"status": "pending"}
    while answer["status"] == "pending" and (left := deadline - time.monotonic()) > 0:
        wait = min(left, POLL)
        answer = hub_api.call(urllib.request.Request(f"{base}/api/decisions/{decision_id}?wait={wait:.1f}"), wait + hub_api.SLACK)
        if not isinstance(answer.get("status"), str):
            raise TypeError("the hub answered no status")
    choice, to = answer.get("choice"), answer.get("to")
    if answer["status"] != "decided" or not isinstance(choice, str) or not isinstance(to, str):
        return None
    labels = [option["label"] for option in question["options"] if isinstance(option, dict) and isinstance(option.get("label"), str)]
    parts = choice.split(signing.PICKED) if question.get("multiSelect") is True else [choice]
    chosen = [label for label in labels if label.strip() in parts]
    other = signing.PICKED not in choice and not chosen
    if [label.strip() for label in chosen] != parts and not other:
        return None
    return answer, choice if other else ", ".join(chosen)


def counter_of(answer: dict) -> int:
    """Returns:
        The signature counter the pick's assertion claims, unchecked: it only
        orders the signature checks, so the picks of an authenticator that
        counts up pass in the order they were signed; 0 when it cannot be read.
    """
    try:
        data = passkey.b64decode(answer["proof"]["assertion"]["authenticatorData"], "authenticatorData")
    except (signing.Refused, KeyError, TypeError):
        return 0
    return int.from_bytes(data[33:37], "big")


def signed(answer: dict, decision_id: str, question: dict, trust: verifier.Trust) -> bool:
    try:
        verifier.check(answer.get("proof"), signing.choice_item(answer["to"], decision_id, question["question"], answer["choice"]), "", trust, time.time())
    except (signing.Refused, OSError) as error:
        print(f"kvb-orchestrator: the pick is not signed, Claude Code asks instead: {error}", file=sys.stderr)
        return False
    return True


def answers_of(base: str, hook: dict, questions: list[dict], timeout: float, trust: verifier.Trust, deadline: float) -> dict | None:
    """Returns:
        The PermissionRequest allow that answers every question with the
        option the operator picked and signed in the Agent Orchestrator;
        None as soon as one question goes unanswered or one signature does
        not hold.
    """
    session = str(hook.get("session_id") or "")
    asked = [(ask_question(base, question, session, timeout), question) for question in questions]
    picks = []
    for decision_id, question in asked:
        pick = picked(base, decision_id, question, deadline)
        if pick is None:
            return None
        picks.append((decision_id, question, *pick))
    for decision_id, question, answer, _ in sorted(picks, key=lambda pick: counter_of(pick[2])):
        if not signed(answer, decision_id, question, trust):
            return None
    return {"behavior": "allow", "updatedInput": {**hook["tool_input"], "answers": {question["question"]: label for _, question, _, label in picks}}}


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
        questions = asked_questions(hook)
        if questions is not None:
            chosen = answers_of(base, hook, questions, args.timeout, trust, deadline)
            if chosen is not None:
                print(json.dumps({"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": chosen}}))
            return 0
        ask = facts(hook)
        too_long = [name for name, limit in LIMITS.items() if len(ask[name]) > limit]
        if too_long:
            print(f"kvb-orchestrator: {', '.join(too_long)} too long to sign in full, Claude Code asks instead", file=sys.stderr)
            return 0
        if unapprovable(ask):
            print(f"kvb-orchestrator: {WORKTREE}", file=sys.stderr)
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
