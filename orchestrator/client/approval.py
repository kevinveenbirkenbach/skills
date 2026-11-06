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

Returns:
    pin: exit code 0 and the pinned credential on stdout; 1 and the reason
        on stderr when the blob is no valid registration.
    verify: exit code 0 when a pinned key signed this exact commit; 1 and
        the reason on stderr otherwise. Commit only on 0.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from hub_api import GUARD, SLACK, base_url, load
from passkey import attested, b64decode
from signing import ALGORITHMS, ID, Refused, origin_of, review_item
from verifier import Trust, check, pin

GIT_TIMEOUT = 30


def git(cwd: Path, args: list[str]) -> str:
    try:
        done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=GIT_TIMEOUT, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise Refused(f"git {args[0]} did not run: {error}") from error
    if done.returncode != 0:
        raise Refused(f"git {' '.join(args)} failed: {done.stderr.strip()}")
    return done.stdout.strip()


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
    args = parser.parse_args()
    try:
        print(pin_credential(args) if args.command == "pin" else verify_commit(args))
    except (Refused, OSError) as error:
        print(f"refused: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
