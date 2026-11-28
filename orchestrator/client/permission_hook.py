#!/usr/bin/env python3
"""Args:
    --port: port of the Agent Orchestrator on 127.0.0.1; the signature's origin is
        http://localhost:<port>.
    --timeout: seconds to wait for the operator's decision; keep it below the
        hook's timeout in settings.json.
    --approvers: the pinned passkeys, e.g. ~/.config/kvb-orchestrator/approvers.json.
    --replay: this hook's replay store, outside the hub's reach, e.g.
        ~/.local/state/kvb-orchestrator-approvals/hook.json; the closer
        tokens live beside it (closer_path()).
    --bound: set when the same registration runs this client on CLOSING
        too (scripts/orchestrator.sh hook), so the hub keeps a card whose
        wait ran out as open in Claude until a closing event ends it; each
        registration then carries the session's closer_token(), the only
        token a closing report closes its cards with.
    stdin: the Claude Code PermissionRequest hook input, or the input of a
        CLOSING event: the PostToolUse input of a call that ran, a Stop,
        UserPromptSubmit or SessionEnd input, which report_ran() tells the
        hub and which prints nothing.

Returns:
    stdout: the PermissionRequest decision JSON: allow only when a pinned
        passkey signed exactly this tool, command (summary()), cwd, session
        and ask id;
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
import os
import re
import secrets
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
SHELL = "Bash"
SHELL_KEYS = frozenset({"command", "description", "timeout", "run_in_background"})
OPTION_KEYS = ("label", "description", "preview")
RAN_EVENT = "PostToolUse"
SESSION_END = "SessionEnd"
CLOSING = (RAN_EVENT, "Stop", "UserPromptSubmit", SESSION_END)
RAN_TIMEOUT = 2.0
ANSWERS_LIMIT = 8
QUESTION_LIMIT = 20_000
ANSWER_LIMIT = 4000
CLOSERS = "closers"
CLOSER = re.compile(r"[A-Za-z0-9_-]{32,128}")
CLOSER_BYTES = 32


def summary(tool: str, tool_input: object) -> str:
    """Returns:
        What the hub shows and the passkey signs: a Bash call's command when
        it sets nothing beyond SHELL_KEYS, else the whole input as sorted
        JSON, so an allow never covers a value the operator did not see.
    """
    if tool == SHELL and isinstance(tool_input, dict) and isinstance(tool_input.get("command"), str) and set(tool_input) <= SHELL_KEYS:
        return tool_input["command"]
    return json.dumps(tool_input, ensure_ascii=False, indent=1, sort_keys=True)


def facts(hook: dict) -> dict:
    tool = str(hook.get("tool_name") or "?")
    return {
        "tool": tool,
        "command": summary(tool, hook.get("tool_input")),
        "cwd": str(hook.get("cwd") or ""),
        "session": str(hook.get("session_id") or ""),
        "agent": str(hook.get("agent_type") or ""),
    }


def commit_target(ask: dict) -> Path | None:
    return staged_diff.commit_of(ask["command"], ask["cwd"]) if ask["tool"] == SHELL and ask["cwd"] else None


def tree_target(ask: dict) -> tuple[Path, str, list[str]] | None:
    return staged_diff.tree_of(ask["command"], ask["cwd"]) if ask["tool"] == SHELL and ask["cwd"] else None


def unapprovable(ask: dict) -> bool:
    return ask["tool"] == SHELL and staged_diff.names_commit(ask["command"]) and commit_target(ask) is None and tree_target(ask) is None


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


def call_key_of(hook: dict) -> str:
    """Returns:
        signing.call_key() of the hook input's tool_name and tool_input, the
        same for the PermissionRequest and the PostToolUse input of one call,
        an AskUserQuestion input keyed without the answers its PostToolUse
        input may carry; empty when they cannot be encoded, so the ask goes
        without it and never becomes an expired Match card.
    """
    tool_input = hook.get("tool_input")
    if hook.get("tool_name") == QUESTION_TOOL and isinstance(tool_input, dict):
        tool_input = {name: value for name, value in tool_input.items() if name != "answers"}
    try:
        return signing.call_key(hook.get("tool_name"), tool_input)
    except (TypeError, ValueError):
        return ""


def ran_answers(hook: dict) -> dict[str, str] | None:
    """Returns:
        The {question: answer} an AskUserQuestion call that ran carries in
        its tool_response, else in its tool_input; None for another tool or
        no such map of texts within the hub's ANSWERS_LIMIT, QUESTION_LIMIT
        and ANSWER_LIMIT, so the report still closes the decisions.
    """
    if hook.get("tool_name") != QUESTION_TOOL:
        return None
    for source in (hook.get("tool_response"), hook.get("tool_input")):
        answers = source.get("answers") if isinstance(source, dict) else None
        if isinstance(answers, dict) and 0 < len(answers) <= ANSWERS_LIMIT and all(isinstance(question, str) and isinstance(answer, str) and len(question) <= QUESTION_LIMIT and len(answer) <= ANSWER_LIMIT for question, answer in answers.items()):
            return answers
    return None


def closer_path(replay: Path, session: str) -> Path | None:
    """Args:
        replay: --replay, this hook's replay store; the closer tokens live
            beside it in CLOSERS, outside the hub's reach.
        session: the hook input's session_id.

    Returns:
        The file of the session's closer token, one per session id; None for
        a session id signing.SESSION refuses, so no id names a path outside
        CLOSERS.
    """
    return replay.parent / CLOSERS / f"{session}.token" if signing.SESSION.fullmatch(session) else None


def read_closer(path: Path) -> str | None:
    """Returns:
        The closer token the file at path holds, None when there is none.

    Raises:
        OSError when path is a link, ValueError when it holds no CLOSER.
    """
    try:
        handle = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return None
    with os.fdopen(handle, encoding="ascii", errors="replace") as file:
        token = file.read(256)
    if not CLOSER.fullmatch(token):
        raise ValueError(f"{path} holds no closer token")
    return token


def closer_token(replay: Path, session: str) -> str:
    """Args:
        replay: --replay (closer_path()).
        session: the hook input's session_id.

    Returns:
        The session's closer token, which every registration and every
        CLOSING report of the session sends as closer: on first use
        secrets.token_urlsafe(CLOSER_BYTES) written to a mode 0600 file and
        linked into place, so a file a concurrent hook linked first wins and
        no reader sees it half written; empty for a session id closer_path()
        refuses, whose cards only a PostToolUse closes.
    """
    path = closer_path(replay, session)
    if path is None:
        return ""
    found = read_closer(path)
    if found is not None:
        return found
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}")
    handle = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(handle, "w", encoding="ascii") as file:
            file.write(secrets.token_urlsafe(CLOSER_BYTES))
        os.link(temporary, path)
    except FileExistsError:
        pass
    finally:
        temporary.unlink(missing_ok=True)
    token = read_closer(path)
    if token is None:
        raise ValueError(f"{path} went away while it was made")
    return token


def report_ran(base: str, hook: dict, replay: Path) -> None:
    """Args:
        hook: the input of a CLOSING event; the hub closes, of exactly that
            session_id, for a PostToolUse the oldest still pending ask and
            per question the oldest decision of call_key_of() as answered in
            Claude, the decisions with ran_answers(); for Stop and
            UserPromptSubmit every still open card of the main agent; for
            SessionEnd every one as ended. Every report carries the
            session's closer token when its file exists (closer_token()),
            and the hub closes a card registered with a closer only for that
            token; Stop, UserPromptSubmit and SessionEnd send nothing
            without one. SessionEnd deletes the token file after its report,
            even a failed one. One POST, no read; the report approves and
            denies nothing.
        replay: --replay (closer_path()).
    """
    event, session = hook.get("hook_event_name"), str(hook.get("session_id") or "")
    if event not in CLOSING or not session or len(session) > NAME_LIMIT:
        return
    path = closer_path(replay, session)
    try:
        token = None if path is None else read_closer(path)
        closer = {} if token is None else {"closer": token}
        if event == RAN_EVENT:
            key, answers = call_key_of(hook), ran_answers(hook)
            if not key:
                return
            body = {"event": event, "call_key": key, "session": session, **({"answers": answers} if answers else {}), **closer}
        elif token is None:
            return
        else:
            body = {"event": event, "session": session, **closer}
        request = urllib.request.Request(f"{base}/api/asks/ran", data=encoded(body), headers={"Content-Type": "application/json", **hub_api.GUARD}, method="POST")
        hub_api.call(request, RAN_TIMEOUT)
    finally:
        if event == SESSION_END and path is not None:
            path.unlink(missing_ok=True)


def create(base: str, ask: dict, timeout: float, shown: dict, key: str, closers: bool, closer: str) -> str:
    """Args:
        key: the call's call_key_of(), sent only when not empty.
        closers: --bound, sent as bound only when set.
        closer: the session's closer_token(), sent only when not empty.
    """
    called = {**({"call_key": key} if key else {}), **({"bound": True} if closers else {}), **({"closer": closer} if closer else {})}
    data = encoded({**ask, "timeout": timeout, **called, **shown})
    if len(data) > hub_limits.DIFF_BODY_LIMIT:
        print(f"kvb-orchestrator: the ask goes without its diff, its {len(data)} bytes pass the hub's {hub_limits.DIFF_BODY_LIMIT}", file=sys.stderr)
        data = encoded({**ask, "timeout": timeout, **called})
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


def ask_question(base: str, question: dict, hook: dict, timeout: float, closers: bool, closer: str) -> str:
    """Args:
        hook: the PermissionRequest input of the AskUserQuestion call; its
            session_id, call_key_of() and agent_type (a subagent's) go with
            the decision, so the CLOSING events close it.
        closers: --bound, sent as bound only when set.
        closer: the session's closer_token(), sent only when not empty.
    """
    options = [{key: option[key] for key in OPTION_KEYS if key in option} if isinstance(option, dict) else option for option in question["options"]]
    key, subagent = call_key_of(hook), str(hook.get("agent_type") or "")
    tied = {**({"call_key": key} if key else {}), **({"subagent": subagent} if subagent else {}), **({"bound": True} if closers else {}), **({"closer": closer} if closer else {})}
    data = encoded({"question": question["question"], "options": options, "session": str(hook.get("session_id") or ""), "timeout": timeout, "multi": question.get("multiSelect") is True, **tied})
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


def answers_of(base: str, hook: dict, questions: list[dict], timeout: float, trust: verifier.Trust, deadline: float, closers: bool, closer: str) -> dict | None:
    """Returns:
        The PermissionRequest allow that answers every question with the
        option the operator picked and signed in the Agent Orchestrator;
        None as soon as one question goes unanswered or one signature does
        not hold.
    """
    asked = [(ask_question(base, question, hook, timeout, closers, closer), question) for question in questions]
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
    parser.add_argument("--bound", action="store_true")
    args = parser.parse_args()
    base = hub_api.base_url(args.port)
    trust = verifier.Trust(approvers=args.approvers, replay=args.replay, origin=signing.origin_of(args.port))
    deadline = time.monotonic() + args.timeout
    try:
        hook = json.load(sys.stdin)
        if hook.get("hook_event_name") in CLOSING:
            report_ran(base, hook, args.replay)
            return 0
        questions = asked_questions(hook)
        if questions is not None:
            closer = closer_token(args.replay, str(hook.get("session_id") or "")) if args.bound else ""
            chosen = answers_of(base, hook, questions, args.timeout, trust, deadline, args.bound, closer)
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
        ask_id = create(base, ask, args.timeout, shown, call_key_of(hook), args.bound, closer_token(args.replay, ask["session"]) if args.bound else "")
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
