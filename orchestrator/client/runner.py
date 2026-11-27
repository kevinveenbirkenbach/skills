#!/usr/bin/env python3
"""Args:
    --port: port of the Agent Orchestrator on 127.0.0.1; the signature's origin is
        http://localhost:<port>.
    --interval: seconds between two polls of the hub.
    --approvers: the pinned passkeys, e.g. ~/.config/kvb-orchestrator/approvers.json.
    --replay: the runner's replay store, outside the hub's reach, e.g.
        ~/.local/state/kvb-orchestrator-approvals/runner.json.
    --state: the hub state dir, e.g. ~/.local/state/kvb-orchestrator, where
        the runner keeps runner-job.json while a job runs.
    --rasci: the installed register script, e.g.
        ~/.claude/skills/kvb-org-rasci/scripts/rasci.py; optional.
    --council: the council directory holding rasci.json, the agents'
        AGENTS_COUNCIL_ROOT; optional, task changes need both.
    --gates: the installed gates script, e.g.
        ~/.claude/skills/kvb-check-gate/scripts/gates.py; optional, gate
        changes need it.
    --queue: the installed queue script, e.g.
        ~/.agents/skills/kvb-org-queue/scripts/queue.py; optional, queue
        changes need it and --council.
    --schedules: the installed schedules script, e.g.
        ~/.claude/skills/kvb-org-organize/scripts/schedules.py; optional,
        schedule changes need it and --council.
    --radio: the installed radio script, e.g.
        ~/.claude/skills/kvb-org-radio/scripts/radio.py; optional, stale
        task prunes need it, --rasci and --council.
    --operator: the installed operator script, e.g.
        ~/.claude/skills/kvb-org-operator/scripts/operator.py; optional,
        without it no row closes done after exit 0.
    --once: handle the queued jobs once and exit.

Environment:
    SHELL: the operator's shell, else the login shell of the runner's uid.

Returns:
    Runs as the operator, outside any sandbox, every operator command a
    pinned passkey signed in the Agent Orchestrator: exactly the signed
    text, as `$SHELL -ic <text>` like `operator.py run`, in the signed
    directory, each signature once and before its expiry. After exit 0 it
    runs `operator.py checked <slug>` the same way and reports whether the
    row's check passes on this host; the hub keeps the row open unless it
    does.
    Runs every signed task change (priority pin, status, dependency or WSJF
    estimate; a board batch is one job per change) as
    `python3 -I -B <rasci> <argv>` from / without a shell, after checking the
    argv shape itself, and kills its process group after 30 s; rasci.py
    refuses a cycle or a done with an open key result, and its reason is the
    job's output. Runs every signed gate change (rule set|drop, parents
    add|drop) the same way as `python3 -I -B <gates> <argv>` with the
    operator's HOME, so gates.py writes its default gates.db. Runs every
    signed queue change (`override <id>` or `config set <key> <value>`,
    signing.queue_argv()) the same way as `python3 -I -B <queue> <argv>`
    with the operator's HOME and the council, so queue.py marks the entry
    in its queue and writes the operator's queue config. Runs every
    signed schedule change of a System timer or a Claude task
    (`timer <unit> ...` or `cron <file> <id> ...`,
    signing.schedule_argv()) the same way as
    `python3 -I -B <schedules> <argv>` with the operator's HOME and the
    council, so schedules.py writes the timer's drop-in or the task's cron
    and refreshes schedules-view.json. Runs a signed stale task prune
    (pruning.prune_argv()) as two jobs of one signature: the announce job
    as `python3 -I -B <radio> send security <text> --session Operator`,
    naming every task and the deadline, and the apply job as
    `python3 -I -B <rasci> prune --since <epoch> <task>...`; every job
    whose not_before lies ahead stays queued, unclaimed, until a later
    cycle. Refuses task
    changes without --rasci and --council or into a council that is a
    symlink or another uid's, gate changes without --gates, queue changes
    without --queue and --council or into such a council, schedule changes
    without --schedules and --council or into such a council, prunes
    without --radio, --rasci and --council or into such a council, and every
    other job. Posts the last 200 output lines
    back while it runs and the exit code at its end. Before a poll, at most
    every PREVIEW_SECONDS, it posts, for each open operator row that is a git merge of a full commit
    id (staged_diff.merge_of) whose HEAD differs from the preview the hub
    holds, staged_diff.merge_preview, which its Match card shows; such a
    merge whose job names the previewed HEAD is refused once HEAD moved.
    For each open operator row and each pending Bash ask that shipped no
    diff that is a git commit-tree with a parent (staged_diff.commit_tree_of)
    and has no preview of that parent at the hub, it posts
    staged_diff.commit_tree_preview, or the git error line that kept it.
    At start, before its first cycle, it removes a leftover runner-job.json
    and posts /api/runner/restart once, so the hub fails every job an
    earlier runner left running; a failed post is printed to stderr. While
    it runs a job it keeps runner-job.json, {pid, job, task, started} with
    its own pid, written by rename with mode 0600 and removed when the job
    ends, whatever the outcome; `orchestrator.sh idle` refuses an install
    while that pid lives, and a job whose marker cannot be written is
    refused. The exit code is 0.
"""

from __future__ import annotations

import argparse
import collections
import contextlib
import json
import os
import pwd
import shlex
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
import hub_limits
import pruning
import signing
import staged_diff
import verifier

LINES = 200
PREVIEWS = "/api/runner/previews"
RESTART = "/api/runner/restart"
MARKER = "runner-job.json"
ERROR_LIMIT = 500
PREVIEW_FAILURES = (OSError, ValueError, staged_diff.DiffError)
BEAT = 2.0
PREVIEW_SECONDS = 10.0
TREE_KIND = "commit-tree"
SAFE_PATH = "/usr/bin:/bin"
TASK_JOB = "task"
TASK_LIMIT = 30.0
GATE_JOB = "gate"
QUEUE_JOB = "queue"
SCHEDULE_JOB = "schedule"
PRUNE_JOB = signing.PRUNE_KIND
OPERATOR = "operator/"
REFUSED = "refused: no valid operator signature for this command"
UNREGISTERED = "refused: this runner was started without --rasci and --council; reinstall its unit with make orchestrator-runner"
UNGATED = "refused: this runner was started without --gates; reinstall its unit with make orchestrator-runner"
UNQUEUED = "refused: this runner was started without --queue and --council; reinstall its unit with make orchestrator-runner"
UNSCHEDULED = "refused: this runner was started without --schedules and --council; reinstall its unit with make orchestrator-runner"
UNPRUNED = "refused: this runner was started without --radio, --rasci and --council; reinstall its unit with make orchestrator-runner"


class Register(NamedTuple):
    rasci: Path
    council: Path


class Scripts(NamedTuple):
    register: Register | None
    gates: Path | None
    queue: Path | None
    schedules: Path | None
    radio: Path | None


class Host(NamedTuple):
    shell: str
    operator: Path | None
    council: Path | None
    marker: Path


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


def gate_refusal(job: dict, trust: verifier.Trust, now: float) -> str | None:
    """Args:
        job: the claimed gate change with argv and proof.
        trust: the pinned keys, the runner's replay store and the origin.
        now: the current time in epoch seconds.

    Returns:
        Why the change must not run, or None when signing.gate_argv()
        accepts its argv and a pinned key signed it.
    """
    return argv_refusal(job, trust, now, signing.gate_argv, signing.gate_item)


def argv_refusal(job: dict, trust: verifier.Trust, now: float, shape: Callable[[object], list[str]],
                 item: Callable[[list[str]], dict]) -> str | None:
    """Args:
        job: the claimed change with argv and proof.
        trust: the pinned keys, the runner's replay store and the origin.
        now: the current time in epoch seconds.
        shape: the signing check of its argv, raising signing.Refused.
        item: the signed item of that argv.

    Returns:
        Why the change must not run, or None when shape accepts its argv
        and a pinned key signed its item.
    """
    try:
        argv = shape(job["argv"])
        verifier.check(job.get("proof"), item(argv), "", trust, now)
    except (signing.Refused, OSError) as error:
        return f"{REFUSED}: {error}"
    return None


def queue_refusal(job: dict, trust: verifier.Trust, now: float) -> str | None:
    """Args:
        job: the claimed queue change with argv and proof.
        trust: the pinned keys, the runner's replay store and the origin.
        now: the current time in epoch seconds.

    Returns:
        Why the change must not run, or None when signing.queue_argv()
        accepts its argv and a pinned key signed it.
    """
    return argv_refusal(job, trust, now, signing.queue_argv, signing.queue_item)


def schedule_refusal(job: dict, trust: verifier.Trust, now: float) -> str | None:
    """Args:
        job: the claimed schedule change with argv and proof.
        trust: the pinned keys, the runner's replay store and the origin.
        now: the current time in epoch seconds.

    Returns:
        Why the change must not run, or None when signing.schedule_argv()
        accepts its argv and a pinned key signed it.
    """
    return argv_refusal(job, trust, now, signing.schedule_argv, signing.schedule_item)


def prune_refusal(job: dict, trust: verifier.Trust, now: float) -> str | None:
    """Args:
        job: the claimed prune job with argv, not_before and proof.
        trust: the pinned keys, the runner's replay store and the origin.
        now: the current time in epoch seconds.

    Returns:
        Why the job must not run, or None when pruning.prune_argv() accepts
        its argv with its not_before, it is due (pruning.timely()) and a
        pinned key signed its item, not_before included.
    """
    try:
        not_before = job.get("not_before")
        argv = pruning.prune_argv(job["argv"], not_before)
        pruning.timely(argv, not_before, now)
        verifier.check(job.get("proof"), pruning.prune_item(argv, not_before), "", trust, now)
    except (signing.Refused, OSError) as error:
        return f"{REFUSED}: {error}"
    return None


def not_due(job: dict, now: float) -> bool:
    """Returns:
        Whether a listed job carries a not_before after now; the cycle
        leaves it queued and unclaimed until then instead of waiting on it.
    """
    not_before = job.get("not_before")
    return pruning.whole(not_before) and not_before > now


def moved(job: dict) -> str | None:
    """Args:
        job: a claimed operator command; head, when set, is the HEAD its
            Match card previewed the merge against.

    Returns:
        Why a git merge (staged_diff.merge_of) must not run because HEAD is
        no longer that commit or cannot be read; None otherwise.
    """
    found = staged_diff.merge_of(job["command"], job["directory"]) if job.get("head") else None
    if found is None:
        return None
    try:
        head = staged_diff.head_of(found[0])
    except PREVIEW_FAILURES as error:
        return f"refused: HEAD cannot be read, so the merge is not the one previewed: {error}"
    return None if head == job["head"] else f"refused: HEAD moved from {job['head'][:12]} to {head[:12]} since the Match card previewed the merge"


def preview(row: dict, rules: Path | None) -> dict | None:
    """Args:
        row: an open operator row with task, command, directory and head,
            the HEAD of the preview the hub holds, None for none.
        rules: the MEDUSA rules directory.

    Returns:
        The preview to post for a git merge row whose HEAD differs from the
        hub's: staged_diff.merge_preview, or {head, error} when it cannot be
        built; for a git commit-tree row, with kind TREE_KIND,
        tree_preview() once head is not its parent; None for every other
        row.
    """
    found = staged_diff.merge_of(row["command"], row["directory"])
    if found is None:
        tree = staged_diff.commit_tree_of(row["command"], row["directory"])
        return None if tree is None or tree[2] == row["head"] else {"task": row["task"], "command": row["command"], "kind": TREE_KIND, **tree_preview(tree, rules)}
    try:
        head = staged_diff.head_of(found[0])
    except PREVIEW_FAILURES as error:
        head, shown = "", {"error": str(error)[:ERROR_LIMIT]}
    else:
        shown = None
    if head == row["head"]:
        return None
    if shown is None:
        try:
            shown = staged_diff.merge_preview(found[0], found[1], rules)
        except PREVIEW_FAILURES as error:
            shown = {"error": str(error)[:ERROR_LIMIT]}
    return {"task": row["task"], "command": row["command"], "head": head, **shown}


def tree_preview(found: tuple[Path, str, str], rules: Path | None) -> dict:
    """Args:
        found: the directory, tree and parent staged_diff.commit_tree_of
            read from a git commit-tree.
        rules: the MEDUSA rules directory.

    Returns:
        staged_diff.commit_tree_preview, or {head, error} with the parent
        as head and the git error line that kept it.
    """
    try:
        return staged_diff.commit_tree_preview(*found, rules)
    except PREVIEW_FAILURES as error:
        return {"head": found[2], "error": str(error)[:ERROR_LIMIT]}


def ask_preview(ask: dict, rules: Path | None) -> dict | None:
    """Args:
        ask: a pending Bash ask that shipped no diff, with id, command, cwd
            and head, the parent of the preview the hub holds, None for none.
        rules: the MEDUSA rules directory.

    Returns:
        {ask, ...tree_preview()} for a git commit-tree with a parent whose
        preview the hub lacks; None for every other ask.
    """
    found = staged_diff.commit_tree_of(ask["command"], ask["cwd"])
    return None if found is None or found[2] == ask["head"] else {"ask": ask["id"], **tree_preview(found, rules)}


def review_preview(row: dict, rules: Path | None) -> dict | None:
    """Args:
        row: a pending review that shipped no diff, with id, worktree, tree
            and head, the HEAD the hub last saw, None for none.
        rules: the MEDUSA rules directory.

    Returns:
        {id, head, diff}: the review's tree against its worktree's HEAD
        (staged_diff.tree_diff), or {id, head, error} when it cannot be
        built; None while HEAD is the one the hub saw.
    """
    try:
        head = staged_diff.head_of(Path(row["worktree"]))
    except PREVIEW_FAILURES as error:
        head, shown = "", {"error": str(error)[:ERROR_LIMIT]}
    else:
        shown = None
    if head == row["head"]:
        return None
    if shown is None:
        try:
            shown = {"diff": staged_diff.tree_diff(Path(row["worktree"]), row["tree"], rules)[0]}
        except PREVIEW_FAILURES as error:
            shown = {"error": str(error)[:ERROR_LIMIT]}
    return {"id": row["id"], "head": head, **shown}


def oversized(shown: dict, keys: tuple[str, ...]) -> dict:
    if len(json.dumps(shown).encode()) <= hub_limits.DIFF_BODY_LIMIT:
        return shown
    return {**{key: shown[key] for key in keys}, "error": f"the preview passes the hub's {hub_limits.DIFF_BODY_LIMIT} bytes"}


def previews(base: str, rules: Path | None) -> None:
    listed = call(base, PREVIEWS, None)
    for row in listed["rows"]:
        shown = preview(row, rules)
        if shown is not None:
            call(base, PREVIEWS, oversized(shown, tuple(key for key in ("task", "command", "kind", "head") if key in shown)))
    for row in listed["reviews"]:
        shown = review_preview(row, rules)
        if shown is not None:
            call(base, PREVIEWS, oversized(shown, ("id", "head")))
    for ask in listed["asks"]:
        shown = ask_preview(ask, rules)
        if shown is not None:
            call(base, PREVIEWS, oversized(shown, ("ask", "head")))


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


def checked(job: dict, host: Host) -> bool | None:
    """Args:
        job: an operator command that exited 0, its task operator/<slug>.
        host: the operator's shell, operator.py and council.

    Returns:
        Whether the row's check passes on this host, from `operator.py
        checked <slug>` in the operator's shell as `operator.py run` sees it;
        None without --operator, for a task whose slug signing.TASK does not
        match, or when that call cannot tell.
    """
    task = job.get("task")
    if host.operator is None or not isinstance(task, str) or not task.startswith(OPERATOR) or not signing.TASK.fullmatch(task.removeprefix(OPERATOR)):
        return None
    council = [f"AGENTS_COUNCIL_ROOT={host.council}"] if host.council else []
    command = shlex.join(["env", *council, sys.executable, "-I", "-B", str(host.operator), "checked", task.removeprefix(OPERATOR)])
    try:
        code = subprocess.run([host.shell, "-ic", command], cwd="/", stdin=subprocess.DEVNULL, capture_output=True, timeout=TASK_LIMIT, check=False, start_new_session=True).returncode
    except (OSError, subprocess.TimeoutExpired):
        return None
    return {0: True, 1: False}.get(code)


def execute(job: dict, host: Host, report: Callable[[dict], None]) -> int:
    """Args:
        job: the claimed and verified job with task, command and directory.
        host: the operator's shell, operator.py and council.
        report: called with {"output", "code", "refused"}; code None while
            the command runs; after exit 0 also "checked" from checked().

    Returns:
        The exit code of `$SHELL -ic <command>` in the signed directory.
    """

    def final(result: dict) -> None:
        report({**result, "checked": checked(job, host)} if result["code"] == 0 else result)

    return spawn([host.shell, "-ic", job["command"]], job["directory"], None, final)


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


def gate(job: dict, gates: Path, report: Callable[[dict], None]) -> int:
    """Args:
        job: the claimed and verified gate change with argv.
        gates: the gates script.
        report: called with {"output", "code", "refused"}.

    Returns:
        The exit code of gates.py, run from / on the argv gate_argv() checked.

    Raises:
        signing.Refused for an argv of any other shape.
    """
    argv = signing.gate_argv(job["argv"])
    env = {"PATH": SAFE_PATH, "HOME": str(Path.home())}
    return spawn([sys.executable, "-I", "-B", str(gates), *argv], "/", env, report, TASK_LIMIT)


def queue(job: dict, scripts: Scripts, report: Callable[[dict], None]) -> int:
    """Args:
        job: the claimed and verified queue change with argv.
        scripts: the runner's scripts; queue and the register's council set.
        report: called with {"output", "code", "refused"}.

    Returns:
        The exit code of queue.py, run from / on the argv queue_argv()
        checked, with the operator's HOME and the council as its
        AGENTS_COUNCIL_ROOT.

    Raises:
        signing.Refused for an argv of any other shape.
    """
    return council_script(scripts.queue, signing.queue_argv(job["argv"]), scripts, report)


def schedule(job: dict, scripts: Scripts, report: Callable[[dict], None]) -> int:
    """Args:
        job: the claimed and verified schedule change with argv.
        scripts: the runner's scripts; schedules and the register's council
            set.
        report: called with {"output", "code", "refused"}.

    Returns:
        The exit code of schedules.py, run from / on the argv
        schedule_argv() checked, with the operator's HOME and the council as
        its AGENTS_COUNCIL_ROOT.

    Raises:
        signing.Refused for an argv of any other shape.
    """
    return council_script(scripts.schedules, signing.schedule_argv(job["argv"]), scripts, report)


def prune(job: dict, scripts: Scripts, report: Callable[[dict], None]) -> int:
    """Args:
        job: the claimed and verified prune job with argv and not_before.
        scripts: the runner's scripts; radio and the register set.
        report: called with {"output", "code", "refused"}.

    Returns:
        The exit code of radio.py sending the announcement for the announce
        job, else of rasci.py prune on the apply job's argv.

    Raises:
        signing.Refused for an argv of any other shape.
    """
    not_before = job.get("not_before")
    argv = pruning.prune_argv(job["argv"], not_before)
    if not_before is None:
        return council_script(scripts.radio, pruning.radio_argv(argv), scripts, report)
    return council_script(scripts.register.rasci, argv, scripts, report)


def council_script(script: Path, argv: list[str], scripts: Scripts, report: Callable[[dict], None]) -> int:
    """Args:
        script: the skill script to run.
        argv: its arguments, already checked against their signing shape.
        scripts: the runner's scripts; the register's council set.
        report: called with {"output", "code", "refused"}.

    Returns:
        The exit code of `python3 -I -B <script> <argv>`, run from / without
        a shell with the operator's HOME and the council as its
        AGENTS_COUNCIL_ROOT, killed after TASK_LIMIT seconds.
    """
    env = {"PATH": SAFE_PATH, "HOME": str(Path.home()), "AGENTS_COUNCIL_ROOT": str(scripts.register.council)}
    return spawn([sys.executable, "-I", "-B", str(script), *argv], "/", env, report, TASK_LIMIT)


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


def mark(marker: Path, job: dict) -> str | None:
    """Args:
        marker: runner-job.json in the hub state dir.
        job: the claimed job about to run, with id and task.

    Returns:
        Why the job must not run: the marker that makes `orchestrator.sh
        idle` refuse an install, which would stop the runner under the job,
        cannot be written; None once it is written.
    """
    try:
        verifier.write_private(marker, {"pid": os.getpid(), "job": job["id"], "task": job["task"], "started": time.time()})
    except OSError as error:
        return f"refused: the runner cannot write {marker}, which keeps an install from stopping it under this job: {error}"
    return None


def refused(claimed: dict, trust: verifier.Trust, scripts: Scripts) -> str | None:
    kind, register = claimed.get("kind"), scripts.register
    if kind == TASK_JOB:
        return UNREGISTERED if register is None else council_refusal(register.council) or task_refusal(claimed, trust, time.time())
    if kind == GATE_JOB:
        return UNGATED if scripts.gates is None else gate_refusal(claimed, trust, time.time())
    if kind == QUEUE_JOB:
        return UNQUEUED if scripts.queue is None or register is None else council_refusal(register.council) or queue_refusal(claimed, trust, time.time())
    if kind == SCHEDULE_JOB:
        return UNSCHEDULED if scripts.schedules is None or register is None else council_refusal(register.council) or schedule_refusal(claimed, trust, time.time())
    if kind == PRUNE_JOB:
        return UNPRUNED if scripts.radio is None or register is None else council_refusal(register.council) or prune_refusal(claimed, trust, time.time())
    return refusal(claimed, trust, time.time()) or moved(claimed)


def run(claimed: dict, scripts: Scripts, host: Host, send: Callable[[dict], None]) -> None:
    kind = claimed.get("kind")
    if kind == TASK_JOB:
        change(claimed, scripts.register, send)
    elif kind == GATE_JOB:
        gate(claimed, scripts.gates, send)
    elif kind == QUEUE_JOB:
        queue(claimed, scripts, send)
    elif kind == SCHEDULE_JOB:
        schedule(claimed, scripts, send)
    elif kind == PRUNE_JOB:
        prune(claimed, scripts, send)
    else:
        execute(claimed, host, send)


def cycle(base: str, trust: verifier.Trust, scripts: Scripts, host: Host) -> None:
    for job in call(base, "/api/runner/jobs", None)["jobs"]:
        if not_due(job, time.time()):
            continue
        try:
            claimed = call(base, f"/api/runner/{job['id']}/claim", {})
        except urllib.error.HTTPError:
            continue
        send = sender(base, claimed["id"])
        reason = refused(claimed, trust, scripts) or mark(host.marker, claimed)
        if reason is not None:
            send({"output": reason, "code": None, "refused": True})
            continue
        try:
            run(claimed, scripts, host, send)
        finally:
            host.marker.unlink(missing_ok=True)


def restart(base: str, marker: Path) -> None:
    marker.unlink(missing_ok=True)
    try:
        call(base, RESTART, {})
    except (OSError, ValueError, TypeError) as error:
        print(f"runner: the hub keeps the jobs an earlier runner left running: {error}", file=sys.stderr)


def post_previews(base: str, rules: Path | None, told: str) -> str:
    """Returns:
        The error this post failed with, printed unless it equals told, the
        one printed last; "" once a post succeeds.
    """
    try:
        previews(base, rules)
    except (OSError, ValueError, KeyError, TypeError) as error:
        if str(error) != told:
            print(f"runner: no merge previews: {error}", file=sys.stderr)
        return str(error)
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(prog="runner")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--interval", type=float, required=True)
    parser.add_argument("--approvers", type=Path, required=True)
    parser.add_argument("--replay", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--rasci", type=Path)
    parser.add_argument("--council", type=Path)
    parser.add_argument("--gates", type=Path)
    parser.add_argument("--queue", type=Path)
    parser.add_argument("--schedules", type=Path)
    parser.add_argument("--radio", type=Path)
    parser.add_argument("--operator", type=Path)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    base = hub_api.base_url(args.port)
    trust = verifier.Trust(approvers=args.approvers, replay=args.replay, origin=signing.origin_of(args.port))
    scripts = Scripts(register=Register(rasci=args.rasci, council=args.council) if args.rasci and args.council else None, gates=args.gates, queue=args.queue, schedules=args.schedules, radio=args.radio)
    host = Host(shell=os.environ.get("SHELL") or pwd.getpwuid(os.geteuid()).pw_shell, operator=args.operator, council=args.council, marker=args.state / MARKER)
    rules, told, previewed = staged_diff.rules_root(), "", None
    restart(base, host.marker)
    while True:
        if previewed is None or time.monotonic() - previewed >= PREVIEW_SECONDS:
            previewed = time.monotonic()
            told = post_previews(base, rules, told)
        try:
            cycle(base, trust, scripts, host)
        except (OSError, ValueError, KeyError, TypeError):
            pass
        if args.once:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
