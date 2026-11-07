#!/usr/bin/env python3
"""Args:
    --port: port of the Agent Orchestrator on 127.0.0.1; the signature's origin is
        http://localhost:<port>.
    --interval: seconds between two polls of the hub.
    --approvers: the pinned passkeys, e.g. ~/.config/kvb-orchestrator/approvers.json.
    --replay: the runner's replay store, outside the hub's reach, e.g.
        ~/.local/state/kvb-orchestrator-approvals/runner.json.
    --rasci: the installed register script, e.g.
        ~/.claude/skills/kvb-org-rasci/scripts/rasci.py; optional.
    --council: the council directory holding rasci.json, the agents'
        AGENTS_COUNCIL_ROOT; optional, task changes need both.
    --once: handle the queued jobs once and exit.

Returns:
    Runs as the operator, outside any sandbox, every operator command a
    pinned passkey signed in the Agent Orchestrator: exactly the signed text, with bash
    in the signed directory, each signature once and before its expiry.
    Runs every signed task change (priority pin or WSJF estimate) as
    `python3 -I -B <rasci> <argv>` from / without a shell, after checking the
    argv shape itself, and kills its process group after 30 s. Refuses task
    changes without --rasci and --council or into a council that is a
    symlink or another uid's, and every other job. Posts the last 200 output lines
    back while it runs and the exit code at its end. The exit code is 0.
"""

from __future__ import annotations

import argparse
import collections
import contextlib
import json
import os
import signal
import stat
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

import hub_api
import signing
import verifier

LINES = 200
BEAT = 2.0
SAFE_PATH = "/usr/bin:/bin"
TASK_JOB = "task"
TASK_LIMIT = 30.0
REFUSED = "refused: no valid operator signature for this command"
UNREGISTERED = "refused: this runner was started without --rasci and --council; reinstall its unit with make orchestrator-runner"


class Register(NamedTuple):
    rasci: Path
    council: Path


def call(base: str, path: str, payload: dict | None) -> dict:
    headers = dict(hub_api.GUARD)
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode()
    request = urllib.request.Request(f"{base}{path}", data=data, headers=headers, method="GET" if payload is None else "POST")
    return hub_api.call(request, hub_api.SLACK)


def collect(stream: object, tail: collections.deque, lock: threading.Lock) -> None:
    # The reader closes the pipe at EOF: a close in execute() would block on the buffer lock this read holds and SIGPIPE a command still running.
    with stream:
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


def task_refusal(job: dict, trust: verifier.Trust, now: float) -> str | None:
    """Args:
        job: the claimed task change with task, argv and proof.
        trust: the pinned keys, the runner's replay store and the origin.
        now: the current time in epoch seconds.

    Returns:
        Why the change must not run, or None when its argv has one of the
        shapes signing.task_argv() allows and a pinned key signed it.
    """
    try:
        argv = signing.task_argv(job["task"], job["argv"])
        verifier.check(job.get("proof"), signing.task_item(job["task"], argv), "", trust, now)
    except (signing.Refused, OSError) as error:
        return f"{REFUSED}: {error}"
    return None


def council_refusal(council: Path) -> str | None:
    """Args:
        council: the directory rasci.py writes the register into.

    Returns:
        Why no task change may run there, or None for a real directory of
        the runner's own uid, given by an absolute path.
    """
    if not council.is_absolute():
        return f"refused: the council {council} is no absolute path"
    try:
        found = os.lstat(council)
    except OSError as error:
        return f"refused: the council {council} cannot be read: {error}"
    if not stat.S_ISDIR(found.st_mode) or found.st_uid != os.geteuid():
        return f"refused: the council {council} is a symlink, no directory or not owned by uid {os.geteuid()}"
    return None


def execute(job: dict, report: Callable[[dict], None]) -> int:
    """Args:
        job: the claimed and verified job with command and directory.
        report: called with {"output", "code", "refused"}; code None while
            the command runs.

    Returns:
        The exit code.
    """
    return spawn(["bash", "-c", job["command"]], job["directory"], None, report)


def change(job: dict, register: Register, report: Callable[[dict], None]) -> int:
    """Args:
        job: the claimed and verified task change with task and argv.
        register: the register script and the council it writes.
        report: called with {"output", "code", "refused"}.

    Returns:
        The exit code of rasci.py, run from / on the argv task_argv() checked.

    Raises:
        signing.Refused for an argv of any other shape.
    """
    argv = signing.task_argv(job["task"], job["argv"])
    env = {"PATH": SAFE_PATH, "HOME": str(Path.home()), "AGENTS_COUNCIL_ROOT": str(register.council)}
    return spawn([sys.executable, "-I", "-B", str(register.rasci), *argv], "/", env, report, TASK_LIMIT)


def spawn(argv: list[str], cwd: str, env: dict[str, str] | None, report: Callable[[dict], None], limit: float | None = None) -> int:
    """Args:
        argv: the program and its arguments, run without a shell.
        cwd: the directory it runs in.
        env: its whole environment, or None for the runner's own.
        report: called with {"output", "code", "refused"}; code None while
            the program runs.
        limit: seconds until its whole process group is killed, or None to
            let it run.

    Returns:
        The exit code, -9 after the kill.
    """
    tail: collections.deque = collections.deque(maxlen=LINES)
    lock = threading.Lock()
    try:
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
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
    deadline = None if limit is None else time.monotonic() + limit
    while True:
        try:
            code = process.wait(BEAT if deadline is None else max(0.0, min(BEAT, deadline - time.monotonic())))
            break
        except subprocess.TimeoutExpired:
            if deadline is not None and time.monotonic() >= deadline:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                code = process.wait()
                with lock:
                    tail.append(f"killed after {limit:g} s\n")
                break
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


def cycle(base: str, trust: verifier.Trust, register: Register | None) -> None:
    for job in call(base, "/api/runner/jobs", None)["jobs"]:
        try:
            claimed = call(base, f"/api/runner/{job['id']}/claim", {})
        except urllib.error.HTTPError:
            continue
        send = sender(base, claimed["id"])
        task = claimed.get("kind") == TASK_JOB
        if not task:
            reason = refusal(claimed, trust, time.time())
        else:
            reason = UNREGISTERED if register is None else council_refusal(register.council) or task_refusal(claimed, trust, time.time())
        if reason is not None:
            send({"output": reason, "code": None, "refused": True})
        elif task:
            change(claimed, register, send)
        else:
            execute(claimed, send)


def main() -> int:
    parser = argparse.ArgumentParser(prog="runner")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--interval", type=float, required=True)
    parser.add_argument("--approvers", type=Path, required=True)
    parser.add_argument("--replay", type=Path, required=True)
    parser.add_argument("--rasci", type=Path)
    parser.add_argument("--council", type=Path)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    base = hub_api.base_url(args.port)
    trust = verifier.Trust(approvers=args.approvers, replay=args.replay, origin=signing.origin_of(args.port))
    register = Register(rasci=args.rasci, council=args.council) if args.rasci and args.council else None
    while True:
        try:
            cycle(base, trust, register)
        except (OSError, ValueError, KeyError, TypeError):
            pass
        if args.once:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
