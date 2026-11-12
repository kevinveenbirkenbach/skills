#!/usr/bin/env python3
"""Args:
    pin --port <port> --approvers <file> --credential <blob>: pins the passkey
        that the Agent Orchestrator settings panel registered (the blob it shows) in
        <file>, written with mode 0600. Run it on the host, outside every
        sandbox, e.g. --approvers ~/.config/kvb-orchestrator/approvers.json.
    verify --port <port> --approvers <file> --replay <file> --review <id>
        --gate <pass|fail>: run in the worktree right before the commit;
        fetches the review's signature from the Agent Orchestrator on 127.0.0.1:<port>
        and checks it against the repository, worktree, branch and the tree
        git write-tree prints, as this process sees them.
    request --port <port> --title <subject> --page <file> --notes <file>
        --gate <pass|fail> --score <line> --agent <name> [--rules <dir>]:
        run in the worktree; asks the operator to approve the staged tree,
        with the repository, worktree, branch and tree as git prints them
        here, the notes file's text (refused past NOTES_LIMIT characters),
        and the diff of the tree git write-tree prints against HEAD
        (staged_diff.tree_diff, content withheld per the MEDUSA rules under
        <dir>, by default those of the pipx install); without the diff when
        the body would pass DIFF_BODY_LIMIT.

Returns:
    pin: exit code 0 and the pinned credential on stdout; 1 and the reason
        on stderr when the blob is no valid registration.
    request: exit code 0 and the hub's {"id", "status", "url"} on stdout;
        1 and the reason on stderr.
    verify: exit code 0 when a pinned key signed this exact commit; 1 and
        the reason on stderr otherwise. Commit only on 0.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

import staged_diff
from hub_api import GUARD, SLACK, base_url, load
from hub_limits import DIFF_BODY_LIMIT, NOTES_LIMIT
from passkey import attested, b64decode
from signing import ALGORITHMS, ID, Refused, origin_of, review_item
from verifier import Trust, check, pin


def git(cwd: Path, args: list[str]) -> str:
    try:
        return staged_diff.git(cwd, args, None).decode("utf-8", "surrogateescape").strip()
    except staged_diff.DiffError as error:
        raise Refused(str(error)) from error


def staged(cwd: Path, review_id: str) -> dict:
    repo = git(cwd, ["rev-parse", "--path-format=absolute", "--git-common-dir"])
    worktree = git(cwd, ["rev-parse", "--show-toplevel"])
    branch = git(cwd, ["symbolic-ref", "--short", "HEAD"])
    return review_item(review_id, repo, worktree, branch, git(cwd, ["write-tree"]))


def fetch(port: int, path: str) -> dict:
    request = urllib.request.Request(f"{base_url(port)}{path}", headers=GUARD)
    try:
        data = load(request, SLACK)
    except (OSError, ValueError) as error:
        raise Refused(f"the Agent Orchestrator did not answer: {error}") from error
    if not isinstance(data, dict):
        raise Refused("the Agent Orchestrator answered no object")
    return data


def verify_commit(args: argparse.Namespace) -> str:
    review = fetch(args.port, f"/api/reviews/{args.review}")
    if review.get("status") != "approved":
        raise Refused(f"the review is {review.get('status')}, not approved")
    item = staged(Path.cwd(), args.review)
    check(review.get("proof"), item, args.gate, Trust(approvers=args.approvers, replay=args.replay, origin=origin_of(args.port)), time.time())
    return f"verified: the operator signed review {args.review}, tree {item['tree']} on {item['branch']} in {item['worktree']}"


def review_body(arguments: dict) -> bytes:
    call = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "review_request", "arguments": arguments}}
    return json.dumps(call, ensure_ascii=False).encode("utf-8")


def request_review(args: argparse.Namespace) -> str:
    cwd = Path.cwd()
    item = staged(cwd, "0" * 16)
    try:
        notes = args.notes.read_text(encoding="utf-8")
        diff = staged_diff.tree_diff(cwd, item["tree"], args.rules or staged_diff.rules_root())
    except (OSError, ValueError, staged_diff.DiffError) as error:
        raise Refused(f"the review cannot be prepared: {error}") from error
    if len(notes) > NOTES_LIMIT:
        raise Refused(f"the notes hold {len(notes)} characters, the hub takes at most {NOTES_LIMIT}")
    arguments = {key: item[key] for key in ("repo", "worktree", "branch", "tree")}
    arguments.update(title=args.title, page=str(args.page), notes=notes, gate=args.gate, score=args.score, agent=args.agent)
    body = review_body({**arguments, "diff": diff})
    if len(body) > DIFF_BODY_LIMIT:
        print(f"approval: the review goes without its diff, its {len(body)} bytes pass the hub's {DIFF_BODY_LIMIT}", file=sys.stderr)
        body = review_body(arguments)
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    try:
        answer = load(urllib.request.Request(f"{base_url(args.port)}/mcp", data=body, headers=headers, method="POST"), SLACK)
    except (OSError, ValueError) as error:
        raise Refused(f"the Agent Orchestrator gave no answer: {error}") from error
    result = answer.get("result") if isinstance(answer, dict) else None
    if not isinstance(result, dict) or result.get("isError") or not isinstance(result.get("structuredContent"), dict):
        raise Refused(f"the Agent Orchestrator refused the review: {json.dumps(answer)[:500]}")
    return json.dumps(result["structuredContent"])


def pin_credential(args: argparse.Namespace) -> str:
    try:
        credential = json.loads(b64decode(args.credential, "credential"))
    except (ValueError, RecursionError) as error:
        raise Refused("the credential blob is no JSON") from error
    entry = attested(credential, origin_of(args.port))
    entries = pin(args.approvers, entry, time.time())
    return f"pinned {entry['id']} ({ALGORITHMS[entry['alg']]}) in {args.approvers}; {len(entries)} key(s) pinned"


def review_id(text: str) -> str:
    if not ID.fullmatch(text):
        raise argparse.ArgumentTypeError("a review id is 16 hex digits")
    return text


def main() -> int:
    parser = argparse.ArgumentParser(prog="approval")
    commands = parser.add_subparsers(dest="command", required=True)
    pinning = commands.add_parser("pin")
    verifying = commands.add_parser("verify")
    for sub in (pinning, verifying):
        sub.add_argument("--port", type=int, required=True)
        sub.add_argument("--approvers", type=Path, required=True)
    pinning.add_argument("--credential", required=True)
    verifying.add_argument("--replay", type=Path, required=True)
    verifying.add_argument("--review", type=review_id, required=True)
    verifying.add_argument("--gate", choices=("pass", "fail"), required=True)
    requesting = commands.add_parser("request")
    requesting.add_argument("--port", type=int, required=True)
    for name in ("--title", "--score", "--agent"):
        requesting.add_argument(name, required=True)
    requesting.add_argument("--page", type=Path, required=True)
    requesting.add_argument("--notes", type=Path, required=True)
    requesting.add_argument("--gate", choices=("pass", "fail"), required=True)
    requesting.add_argument("--rules", type=Path)
    args = parser.parse_args()
    run = {"pin": pin_credential, "verify": verify_commit, "request": request_review}[args.command]
    try:
        print(run(args))
    except (Refused, OSError) as error:
        print(f"refused: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
