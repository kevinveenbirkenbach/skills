#!/usr/bin/env python3
"""Args:
    --port: port of the kvb-hub on 127.0.0.1; the signature's origin is
        http://localhost:<port>.
    --interval: seconds between two polls of the hub.
    --approvers: the pinned passkeys, e.g. ~/.config/kvb-hub/approvers.json.
    --replay: the runner's replay store, outside the hub's reach, e.g.
        ~/.local/state/kvb-hub-approvals/runner.json.
    --once: handle the queued jobs once and exit.

Returns:
    Runs as the operator, outside any sandbox, every operator command a
    pinned passkey signed in the kvb-hub: exactly the signed text, with bash
    in the signed directory, each signature once and before its expiry.
    Refuses every other job. Posts the last 200 output lines back while it
    runs and the exit code at its end. The exit code is 0.
"""

from __future__ import annotations

import argparse
import collections
import json
import subprocess
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

import hub_api
import signing
import verifier

LINES = 200
BEAT = 2.0
REFUSED = "refused: no valid operator signature for this command"


def call(base: str, path: str, payload: dict | None) -> dict:
    headers = dict(hub_api.GUARD)
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode()
    request = urllib.request.Request(f"{base}{path}", data=data, headers=headers, method="GET" if payload is None else "POST")
    return hub_api.call(request, hub_api.SLACK)


def collect(stream: object, tail: collections.deque, lock: threading.Lock) -> None:
    for line in stream:
        with lock:
            tail.append(line)


def refusal(job: dict, trust: verifier.Trust, now: float) -> str | None:
    """Args:
        job: the claimed job with task, command, directory and proof.
        trust: the pinned keys, the runner's replay store and the origin.
        now: the current time in epoch seconds.

    Returns:
        Why the job must not run, or None when a pinned key signed it.
    """
    try:
        verifier.check(job.get("proof"), signing.operator_item(job["task"], job["command"], job["directory"]), "", trust, now)
    except (signing.Refused, OSError) as error:
        return f"{REFUSED}: {error}"
    return None


def execute(job: dict, report: Callable[[dict], None]) -> int:
    """Args:
        job: the claimed and verified job with command and directory.
        report: called with {"output", "code", "refused"}; code None while
            the command runs.

    Returns:
        The exit code.
    """
    tail: collections.deque = collections.deque(maxlen=LINES)
    lock = threading.Lock()
    try:
        process = subprocess.Popen(
            ["bash", "-c", job["command"]],
            cwd=job["directory"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            start_new_session=True,
        )
    except OSError as error:
        report({"output": f"could not start: {error}", "code": 127, "refused": False})
        return 127
    reader = threading.Thread(target=collect, args=(process.stdout, tail, lock), daemon=True)
    reader.start()
    while True:
        try:
            code = process.wait(BEAT)
            break
        except subprocess.TimeoutExpired:
            with lock:
                output = "".join(tail)
            report({"output": output, "code": None, "refused": False})
    reader.join()
    report({"output": "".join(tail), "code": code, "refused": False})
    return code


def sender(base: str, job_id: str) -> Callable[[dict], None]:
    def send(result: dict) -> None:
        try:
            call(base, f"/api/runner/{job_id}/report", result)
        except (OSError, ValueError, TypeError):
            return

    return send


def cycle(base: str, trust: verifier.Trust) -> None:
    for job in call(base, "/api/runner/jobs", None)["jobs"]:
        try:
            claimed = call(base, f"/api/runner/{job['id']}/claim", {})
        except urllib.error.HTTPError:
            continue
        send = sender(base, claimed["id"])
        reason = refusal(claimed, trust, time.time())
        if reason is None:
            execute(claimed, send)
        else:
            send({"output": reason, "code": None, "refused": True})


def main() -> int:
    parser = argparse.ArgumentParser(prog="runner")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--interval", type=float, required=True)
    parser.add_argument("--approvers", type=Path, required=True)
    parser.add_argument("--replay", type=Path, required=True)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    base = hub_api.base_url(args.port)
    trust = verifier.Trust(approvers=args.approvers, replay=args.replay, origin=signing.origin_of(args.port))
    while True:
        try:
            cycle(base, trust)
        except (OSError, ValueError, KeyError, TypeError):
            pass
        if args.once:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
