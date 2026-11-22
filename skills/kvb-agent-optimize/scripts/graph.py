#!/usr/bin/env python3
"""Environment:
    CBM_CACHE_DIR: graph cache of codebase-memory-mcp; default
        ~/.cache/codebase-memory-mcp. A root counts as indexed when its
        <project>.db file exists there.
    KVB_CODE_GRAPH_STATE: state directory (per-session files, rows.json,
        inflight.json, index.lock, logs/<project>.log with one line per hook
        decision, logs/<project>.index.log with the output of the queue job
        and the helper); default $XDG_STATE_HOME/kvb-code-graph, else
        ~/.local/state/kvb-code-graph.
    KVB_CODE_GRAPH_CONFIG: JSON config; default
        $XDG_CONFIG_HOME/kvb-code-graph/config.json, else
        ~/.config/kvb-code-graph/config.json. Both keys are required and have
        no default; while one is missing nothing is indexed:
            queue_file_threshold: a root with more files (tracked plus
                untracked, not ignored), with a .gitmodules file, with a
                nested repository (gitlink or untracked clone) or whose file
                count git cannot tell within GIT_TIMEOUT is enqueued, never
                started from the hook.
            queue_task: the open kvb-org-rasci task the queue job runs under.
    KVB_CODE_GRAPH_SKILLS: skills root holding kvb-org-queue,
        kvb-org-organize and kvb-org-operator; default ~/.agents/skills.
    KVB_CODE_GRAPH_BIN: the codebase-memory-mcp binary; default the one on
        PATH.

Args:
    hook: PreToolUse adapter. Reads the hook JSON (session_id, cwd,
        tool_input) on stdin; without a session_id it does nothing. For each
        git root of cwd and of the file_path, path or notebook_path the call
        touches that has no graph and that no live helper, queue job or
        deciding hook holds, and whose last index did not fail within
        BACKOFF_SECONDS: a large root is enqueued by a detached `enqueue`, a
        small root starts the `index` helper only while no other helper runs
        and `watch.py status` reports memory=ok, else it is retried after
        DEFER_SECONDS. Git runs only below a `.git` entry, with repository
        hooks and fsmonitor off and at most GIT_TIMEOUT per call, never under
        the session lock; a root whose rev-parse timed out STALL_TIMEOUTS
        times in a row (stalled.json, rewritten only on change) is skipped
        for BACKOFF_SECONDS. The first call of a session prints a
        systemMessage when the config is incomplete or no permanent daemon
        runs, and records a missing config or an inactive
        kvb-code-graph.service as one kvb-org-operator row (--check
        decision) once per host. A step starts only while HOOK_BUDGET leaves
        room for its worst case; a root that does not fit is deferred, the
        notices move to the next call. Never blocks the tool call.
    enqueue --root <dir> --task <task> --session <id>: run `queue.py hold
        --kind test --task <task> --session <id> -- graph.py index`; when the
        hold exits non-zero and the helper recorded no failure of its own, it
        records failed_at, so a refused hold (task not open) backs off too.
    index --root <dir> [--mode M] [--call-timeout S] [--deadline S]: wait for
        the host-wide index slot, hold one MCP stdio session rooted at dir,
        call index_repository with async true and the mode, poll its status
        while the job is queued, running or cancelling. Every reply waits at
        most the call timeout, the whole run at most the deadline; then it
        exits 1. A reply without one of these states ends the run as
        refused. The daemon keeps running an index it accepted.
    supervise [--rounds N] [--pause S]: keep a permanent daemon: run
        `daemon start` when `daemon status` reports no daemon or an unknown
        one, never while a session-managed daemon runs (upstream refuses it
        until the last session ends). The check repeats every S seconds
        (default SUPERVISE_SECONDS), so a permanent daemon follows the last
        session within one round; only consecutive starts that leave no
        permanent daemon wait longer, doubling from S up to
        SUPERVISE_CEILING. Prints one line per change of the daemon state.
        N rounds, 0 (default) for ever.

Exit codes:
    hook and supervise 0; index 0 when the job succeeded, 1 otherwise;
    enqueue the exit code of the hold.
"""

from __future__ import annotations

import argparse
import fcntl
import itertools
import json
import os
import re
import select
import shutil
import signal
import subprocess
import sys
import time
from contextlib import contextmanager, suppress
from pathlib import Path

SERVICE = "kvb-code-graph.service"
ENABLE = f"systemctl --user enable --now {SERVICE}"
NOTICE = f"codebase-memory-mcp: no permanent daemon; run: {ENABLE}"
SUPERVISE_SECONDS = 30
NOTICE_PENDING = f"codebase-memory-mcp: {SERVICE} starts the permanent daemon within {SUPERVISE_SECONDS} s after the last session ends; nothing to do"
NOTICE_STUCK = f"codebase-memory-mcp: no daemon although {SERVICE} is active; check: journalctl --user -u {SERVICE}"
NOTICE_NO_UNIT = f"codebase-memory-mcp: no permanent daemon; run make install in the skills repository, it installs {SERVICE}"
DAEMON_ROW = "kvb-code-graph-daemon"
CONFIG_ROW = "kvb-code-graph-config"
PATH_KEYS = ("file_path", "path", "notebook_path")
MODE = "full"
GIT_TIMEOUT = 2
GIT_SAFE = ("-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", "--no-optional-locks")
STATUS_TIMEOUT = 3
ROW_TIMEOUT = 5
HOOK_BUDGET = 20
LAUNCH_SECONDS = GIT_TIMEOUT + STATUS_TIMEOUT
NOTICE_SECONDS = 2 * ROW_TIMEOUT + 2 * STATUS_TIMEOUT
DEFER_SECONDS = 300
BACKOFF_SECONDS = 6 * 3600
STALL_TIMEOUTS = 2
SUPERVISE_CEILING = 3600
POLL_SECONDS = 2
CALL_TIMEOUT = 120
INDEX_DEADLINE = 3 * 3600
RUNNING = ("queued", "running", "cancelling")
TERMINAL = ("succeeded", "failed", "cancelled")
SAFE = re.compile(r"[^A-Za-z0-9._-]")
MEMORY = re.compile(r"memory=(\w+)")
SELF = str(Path(__file__).resolve())
STARTED = time.monotonic()


def cache_dir() -> Path:
    return Path(os.environ.get("CBM_CACHE_DIR") or Path.home() / ".cache" / "codebase-memory-mcp")


def state_dir() -> Path:
    explicit = os.environ.get("KVB_CODE_GRAPH_STATE")
    if explicit:
        return Path(explicit)
    base = os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state"
    return Path(base) / "kvb-code-graph"


def config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


def config_path() -> Path:
    explicit = os.environ.get("KVB_CODE_GRAPH_CONFIG")
    return Path(explicit) if explicit else config_home() / "kvb-code-graph" / "config.json"


def config() -> dict | None:
    """Returns:
        The config with a non-negative integer queue_file_threshold and a
        non-empty queue_task, or None when the file or either key is missing
        or invalid.
    """
    try:
        data = json.loads(config_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    threshold, task = data.get("queue_file_threshold"), data.get("queue_task")
    valid = type(threshold) is int and threshold >= 0 and isinstance(task, str) and task
    return data if valid else None


def unit_installed() -> bool:
    return (config_home() / "systemd" / "user" / SERVICE).is_file()


def skill_script(skill: str, name: str) -> Path:
    root = os.environ.get("KVB_CODE_GRAPH_SKILLS") or Path.home() / ".agents" / "skills"
    return Path(root) / skill / "scripts" / name


def binary() -> str | None:
    return os.environ.get("KVB_CODE_GRAPH_BIN") or shutil.which("codebase-memory-mcp")


def project_name(root: str) -> str:
    """Args:
        root: absolute path of a repository root.

    Returns:
        The project name codebase-memory-mcp derives for it
        (cbm_project_name_sanitize of the canonical path, upstream 0.12.1).
    """
    mapped = "".join(
        f"{byte:02x}" if byte >= 0x80 else ("-" if SAFE.match(chr(byte)) else chr(byte))
        for byte in os.path.realpath(root).encode("utf-8")
    )
    collapsed = re.sub(r"\.{2,}", ".", re.sub(r"-{2,}", "-", mapped))
    return collapsed.lstrip("-.").rstrip("-") or "root"


def indexed(root: str) -> bool:
    return (cache_dir() / f"{project_name(root)}.db").is_file()


def run(command: list[str], timeout: float = STATUS_TIMEOUT, **options) -> subprocess.CompletedProcess | None:
    """Args:
        command: argv, run in its own process group.
        timeout: seconds; past it the whole group is killed.
        options: further Popen keywords (cwd, env).

    Returns:
        The finished process with text output, one with returncode None and
        no output when it ran past the timeout, or None when it did not
        start.
    """
    try:
        process = subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, errors="surrogateescape", start_new_session=True, **options,
        )
    except OSError:
        return None
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.wait()
        return subprocess.CompletedProcess(command, None, "", "")
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def remaining() -> float:
    return HOOK_BUDGET - (time.monotonic() - STARTED)


def git_env() -> dict[str, str]:
    kept = {key: value for key, value in os.environ.items() if not key.startswith("GIT_") or key == "GIT_CEILING_DIRECTORIES"}
    return {**kept, "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0"}


def git(cwd: Path | str, *args: str) -> subprocess.CompletedProcess | None:
    executable = shutil.which("git")
    return run([executable, *GIT_SAFE, *args], GIT_TIMEOUT, cwd=cwd, env=git_env()) if executable else None


def git_probe(path: str) -> tuple[Path, str] | None:
    """Returns:
        The nearest existing folder of path and the nearest folder at or
        above it holding a `.git` entry, or None when there is none.
    """
    probe = Path(path)
    while not probe.is_dir():
        if probe.parent == probe:
            return None
        probe = probe.parent
    holder = next((str(folder) for folder in (probe, *probe.parents) if os.path.lexists(folder / ".git")), None)
    return (probe, holder) if holder else None


def git_root(path: str) -> str | None:
    """Args:
        path: any absolute path, existing or not.

    Returns:
        The top level of the work tree holding it (a submodule and a linked
        worktree are their own roots); None outside git, below a root whose
        rev-parse stalled within BACKOFF_SECONDS, or when the hook budget
        has no room for git.
    """
    found = git_probe(path)
    if found is None or remaining() < GIT_TIMEOUT or stalled(found[1]):
        return None
    probe, holder = found
    result = git(probe, "rev-parse", "--show-toplevel")
    if result is not None:
        record_stall(holder, result.returncode is None)
    top = result.stdout.strip() if result and result.returncode == 0 else ""
    return os.path.realpath(top) if top else None


def fresh_stall(entry: object, now: float) -> bool:
    if not isinstance(entry, dict):
        return False
    at, timeouts = entry.get("at"), entry.get("timeouts")
    return isinstance(at, (int, float)) and type(timeouts) is int and now - at < BACKOFF_SECONDS


def stalled(holder: str) -> bool:
    """Args:
        holder: the nearest folder holding a `.git` entry.

    Returns:
        Whether rev-parse below it timed out STALL_TIMEOUTS times in a row,
        the last within BACKOFF_SECONDS. Drops every older entry.
    """
    now = time.time()
    with locked_json(state_dir() / "stalled.json") as stalls:
        for gone in [key for key, entry in stalls.items() if not fresh_stall(entry, now)]:
            del stalls[gone]
        return stalls.get(holder, {}).get("timeouts", 0) >= STALL_TIMEOUTS


def record_stall(holder: str, timed_out: bool) -> None:
    """Args:
        holder: the nearest folder holding a `.git` entry.
        timed_out: whether rev-parse below it just timed out; a reply
            clears its count.
    """
    with locked_json(state_dir() / "stalled.json") as stalls:
        if timed_out:
            stalls[holder] = {"timeouts": stalls.get(holder, {}).get("timeouts", 0) + 1, "at": time.time()}
        else:
            stalls.pop(holder, None)


def file_count(root: str) -> int:
    """Returns:
        The tracked plus untracked, not ignored files of the root, as the
        upstream walk sees them; -1 when git cannot tell within GIT_TIMEOUT
        or a nested repository (gitlink, untracked clone) hides its files.
    """
    result = git(root, "ls-files", "-z", "--stage", "--cached", "--others", "--exclude-standard")
    if not result or result.returncode != 0:
        return -1
    entries = result.stdout.split("\0")[:-1]
    nested = any(entry.startswith("160000 ") or entry.endswith("/") for entry in entries)
    return -1 if nested else len(entries)


def large(root: str, threshold: int) -> tuple[bool, int]:
    count = file_count(root)
    return count < 0 or count > threshold or (Path(root) / ".gitmodules").exists(), count


def touched(event: dict) -> list[str]:
    cwd = event.get("cwd") or ""
    tool_input = event.get("tool_input") or {}
    paths = [cwd] if cwd else []
    for key in PATH_KEYS:
        value = tool_input.get(key) if isinstance(tool_input, dict) else None
        if isinstance(value, str) and value:
            paths.append(value if os.path.isabs(value) else os.path.join(cwd or os.getcwd(), value))
    return paths


def session_key(session_id: str) -> str:
    return SAFE.sub("_", session_id)[:128] or "unknown"


@contextmanager
def locked_json(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        handle.seek(0)
        raw = handle.read()
        try:
            data = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            data = {}
        data = data if isinstance(data, dict) else {}
        yield data
        if json.dumps(data) != raw:
            handle.seek(0)
            handle.truncate()
            json.dump(data, handle)


def alive(pid: object) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def note(root: str, text: str) -> Path:
    logs = state_dir() / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    log = logs / f"{project_name(root)}.log"
    with open(log, "a", encoding="utf-8") as handle:
        handle.write(f"graph: {text} {root} {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n")
    return log


def detach(root: str, kind: str, command: list[str]) -> int:
    with open(note(root, kind).with_suffix(".index.log"), "ab") as log:
        return subprocess.Popen(
            command,
            cwd=root,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
        ).pid


def memory_stage() -> str:
    """Returns:
        The memory stage `watch.py status` reports from its stored samples
        (no CPU sampling), "unknown" when it cannot be read.
    """
    script = skill_script("kvb-org-organize", "watch.py")
    status = run([sys.executable, "-I", str(script), "status"]) if script.is_file() else None
    stage = MEMORY.search(status.stdout) if status and status.returncode == 0 else None
    return stage.group(1) if stage else "unknown"


def reserve(root: str) -> str:
    """Returns:
        "held" when a live helper, queue job or deciding hook holds the root,
        "backoff" when its last index failed within BACKOFF_SECONDS, else
        "reserved" with this hook recorded as its holder.
    """
    with locked_json(state_dir() / "inflight.json") as inflight:
        entry = inflight.get(root) or {}
        if alive(entry.get("pid")):
            return "held"
        failed_at = entry.get("failed_at")
        if isinstance(failed_at, (int, float)) and time.time() - failed_at < BACKOFF_SECONDS:
            return "backoff"
        inflight[root] = {"pid": os.getpid(), "via": "deciding"}
        return "reserved"


def settle(root: str, entry: dict | None) -> None:
    """Args:
        root: a git root.
        entry: its new in-flight record, None to drop it.
    """
    with locked_json(state_dir() / "inflight.json") as inflight:
        if entry:
            inflight[root] = entry
        else:
            inflight.pop(root, None)


def helper_running() -> bool:
    with locked_json(state_dir() / "inflight.json") as inflight:
        return any(isinstance(entry, dict) and entry.get("via") == "helper" and alive(entry.get("pid")) for entry in inflight.values())


def index_command(root: str) -> list[str]:
    return [sys.executable, "-I", SELF, "index", "--root", root, "--mode", MODE]


def decide(root: str, session: str, settings: dict) -> tuple[str, dict | None]:
    big, count = large(root, settings["queue_file_threshold"])
    if big:
        enqueue = [sys.executable, "-I", SELF, "enqueue", "--root", root, "--task", settings["queue_task"], "--session", session]
        return "queued", {"pid": detach(root, "queue", enqueue), "via": "queue", "files": count}
    if helper_running():
        note(root, "defer (index helper busy)")
        return "deferred", None
    stage = memory_stage()
    if stage != "ok":
        note(root, f"defer (memory stage {stage})")
        return "deferred", None
    return "started", {"pid": detach(root, "spawn", index_command(root)), "via": "helper", "files": count}


def cmd_enqueue(root: str, task: str, session: str) -> int:
    started = time.time()
    queue = str(skill_script("kvb-org-queue", "queue.py"))
    hold = [sys.executable, "-I", queue, "hold", "--kind", "test", "--task", task, "--session", session, "--", *index_command(root)]
    try:
        code = subprocess.run(hold, check=False).returncode
    except OSError as error:
        print(f"graph: {root} queue hold did not start: {error}", flush=True)
        code = 127
    if code != 0:
        with locked_json(state_dir() / "inflight.json") as inflight:
            failed_at = (inflight.get(root) or {}).get("failed_at")
            if not (isinstance(failed_at, (int, float)) and failed_at >= started):
                inflight[root] = {"failed_at": time.time(), "state": f"queue exit {code}"}
    return code


def launch(root: str, session: str, settings: dict) -> str:
    """Args:
        root: an unindexed git root.
        session: the hook payload's session id.
        settings: the complete config.

    Returns:
        "held", "deferred", "queued" or "started".
    """
    reserved = reserve(root)
    if reserved != "reserved":
        return "held" if reserved == "held" else "deferred"
    outcome, entry = "deferred", None
    try:
        outcome, entry = decide(root, session, settings)
    finally:
        settle(root, entry)
    return outcome


def daemon_kind(executable: str | None) -> str:
    """Returns:
        "permanent" or "session-managed" as `daemon status` reports it,
        "other" for a running daemon it reports otherwise, "none" else.
    """
    status = run([executable, "daemon", "status"]) if executable else None
    if status is None or status.returncode != 0:
        return "none"
    if "active (permanent)" in status.stdout:
        return "permanent"
    return "session-managed" if "session-managed" in status.stdout else "other"


def unit_active() -> bool:
    systemctl = shutil.which("systemctl")
    unit = run([systemctl, "--user", "is-active", "--quiet", SERVICE]) if systemctl else None
    return unit is not None and unit.returncode == 0


def add_row_once(slug: str, session: str, command: str, reason: str, options: list[str]) -> None:
    """Args:
        slug: the kvb-org-operator row; added at most once per host, so a row
            the operator cancelled is never reopened.
        session: the hook payload's session id, forwarded as --session.
        command: the row's command, shown only (--check decision).
        reason: why the row exists.
        options: the row's answers as "<label>=<consequence>", the
            recommended one first.
    """
    rows = state_dir() / "rows.json"
    with locked_json(rows) as added:
        if slug in added:
            return
    script = skill_script("kvb-org-operator", "operator.py")
    if not script.is_file():
        return
    result = run([
        sys.executable, "-I", str(script), "add", slug, "--session", session,
        "--dir", str(Path.home()), "--command", command, "--reason", reason, "--check", "decision",
        *[part for option in options for part in ("--option", option)], "--recommended", options[0].partition("=")[0],
    ], timeout=ROW_TIMEOUT)
    if result is not None and result.returncode == 0:
        with locked_json(rows) as added:
            added[slug] = time.time()


def notices(session: str, settings: dict | None) -> list[str]:
    messages = []
    if settings is None:
        path = config_path()
        messages.append(f"kvb-code-graph: nothing is indexed until {path} sets queue_file_threshold and queue_task (operator row {CONFIG_ROW})")
        add_row_once(CONFIG_ROW, session, f"code {path}", "set queue_file_threshold and queue_task; the code graph hook indexes nothing until both are set",
                     [f"Configure=set queue_file_threshold and queue_task in {path}; indexing starts", "Leave off=nothing is indexed"])
    kind = daemon_kind(binary())
    if kind == "permanent":
        return messages
    active = unit_active()
    if active and kind == "other":
        return messages
    if active:
        messages.append(NOTICE_PENDING if kind == "session-managed" else NOTICE_STUCK)
    elif unit_installed():
        messages.append(NOTICE)
        add_row_once(DAEMON_ROW, session, ENABLE, "no permanent codebase-memory-mcp daemon: graphs lose their watch when the last session ends",
                     ["Enable=run the command; one permanent daemon keeps every graph watched", "Per session=graphs lose their watch when the last session ends"])
    else:
        messages.append(NOTICE_NO_UNIT)
    return messages


def hook_event() -> tuple[str, dict] | None:
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return None
    session = event.get("session_id") if isinstance(event, dict) else None
    return (session, event) if isinstance(session, str) and session else None


def claim(state_file: Path, roots: list[str], now: float) -> tuple[bool, list[str]]:
    """Returns:
        Whether this call owes the session's notices, and the roots the
        session neither handled nor deferred within DEFER_SECONDS.
    """
    with locked_json(state_file) as state:
        notify = not state.get("checked") and not alive(state.get("checking"))
        if notify:
            state["checking"] = os.getpid()
        handled, deferred = state.get("roots", []), state.get("deferred", {})
        return notify, [root for root in roots if root not in handled and now - deferred.get(root, 0) >= DEFER_SECONDS]


def record(state_file: Path, outcomes: dict[str, str], now: float) -> None:
    with locked_json(state_file) as state:
        handled, deferred = state.setdefault("roots", []), state.setdefault("deferred", {})
        for root, outcome in outcomes.items():
            if outcome == "deferred":
                deferred[root] = now
            elif outcome != "held" and root not in handled:
                deferred.pop(root, None)
                handled.append(root)


def launch_all(roots: list[str], session: str, settings: dict) -> dict[str, str]:
    outcomes = {}
    for root in roots:
        if indexed(root):
            continue
        if remaining() < LAUNCH_SECONDS:
            note(root, "defer (hook budget)")
            outcomes[root] = "deferred"
        else:
            outcomes[root] = launch(root, session, settings)
    return outcomes


def announce(state_file: Path, session: str, settings: dict | None) -> None:
    messages = notices(session, settings) if remaining() >= NOTICE_SECONDS else None
    if messages:
        print(json.dumps({"systemMessage": "\n".join(messages)}), flush=True)
    with locked_json(state_file) as state:
        state.pop("checking", None)
        if messages is not None:
            state["checked"] = True


def cmd_hook() -> int:
    parsed = hook_event()
    if parsed is None:
        return 0
    session, event = parsed
    settings = config()
    roots = sorted({root for root in map(git_root, touched(event)) if root}) if settings else []
    state_file = state_dir() / "sessions" / f"{session_key(session)}.json"
    now = time.time()
    notify, pending = claim(state_file, roots, now)
    outcomes = launch_all(pending, session, settings)
    if outcomes:
        record(state_file, outcomes, now)
    if notify:
        announce(state_file, session, settings)
    return 0


class Session:
    def __init__(self, executable: str, root: str) -> None:
        self.process = subprocess.Popen([executable], cwd=root, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        self.buffer = b""
        self.next_id = 0

    def readline(self, deadline: float) -> bytes:
        while b"\n" not in self.buffer:
            remaining = deadline - time.monotonic()
            ready = select.select([self.process.stdout], [], [], remaining)[0] if remaining > 0 else []
            if not ready:
                raise TimeoutError("no reply before the call timeout or the deadline")
            chunk = os.read(self.process.stdout.fileno(), 65536)
            if not chunk:
                raise RuntimeError("the server closed the session")
            self.buffer += chunk
        line, _, self.buffer = self.buffer.partition(b"\n")
        return line

    def send(self, message: dict) -> None:
        self.process.stdin.write((json.dumps(message) + "\n").encode())
        self.process.stdin.flush()

    def request(self, method: str, params: dict, deadline: float) -> dict:
        self.next_id += 1
        self.send({"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params})
        while True:
            try:
                message = json.loads(self.readline(deadline))
            except json.JSONDecodeError:
                continue
            if isinstance(message, dict) and message.get("id") == self.next_id:
                return message

    def tool(self, name: str, arguments: dict, deadline: float) -> dict:
        reply = self.request("tools/call", {"name": name, "arguments": arguments}, deadline)
        texts = [item.get("text", "") for item in reply.get("result", {}).get("content", [])]
        try:
            return json.loads("".join(texts))
        except json.JSONDecodeError:
            return {"text": "".join(texts), "error": reply.get("error")}

    def close(self) -> None:
        try:
            self.process.stdin.close()
        except BrokenPipeError:
            pass
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()


def job_state(reply: dict) -> str:
    state = reply.get("state") if isinstance(reply, dict) else None
    return state if isinstance(state, str) else ""


def poll(session: Session, root: str, mode: str, call_timeout: float, end: float) -> str:
    def call() -> float:
        return min(time.monotonic() + call_timeout, end)

    session.request("initialize", {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "kvb-code-graph", "version": "1"},
    }, call())
    session.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
    reply = session.tool("index_repository", {"repo_path": root, "async": True, "mode": mode}, call())
    print(f"graph: {root} started: {json.dumps(reply)[:400]}", flush=True)
    while job_state(reply) in RUNNING:
        if time.monotonic() >= end:
            raise TimeoutError("the overall deadline passed")
        time.sleep(max(0.0, min(POLL_SECONDS, end - time.monotonic())))
        reply = session.tool("index_repository", {"repo_path": root, "status": True}, call())
    if job_state(reply) in TERMINAL:
        return job_state(reply)
    print(f"graph: {root} refused: {json.dumps(reply)[:400]}", flush=True)
    return "refused"


@contextmanager
def index_slot(end: float):
    path = state_dir() / "index.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= end:
                    raise TimeoutError("another index helper held the slot until the deadline") from None
                time.sleep(max(0.0, min(POLL_SECONDS, end - time.monotonic())))
        yield


def cmd_index(root: str, mode: str, call_timeout: float, deadline: float) -> int:
    executable = binary()
    if not executable:
        print("graph: codebase-memory-mcp not on PATH", file=sys.stderr)
        return 1
    end = time.monotonic() + deadline
    try:
        with index_slot(end):
            session = Session(executable, root)
            try:
                state = poll(session, root, mode, call_timeout, end)
            finally:
                session.close()
    except (TimeoutError, RuntimeError, OSError, ValueError) as error:
        print(f"graph: {root} gave up: {error}; an index the daemon already accepted keeps running there", flush=True)
        state = "timeout" if isinstance(error, TimeoutError) else "error"
    settle(root, None if state == "succeeded" else {"failed_at": time.time(), "state": state})
    print(f"graph: {root} {state}", flush=True)
    return 0 if state == "succeeded" else 1


def start_daemon(executable: str) -> None:
    try:
        subprocess.run(
            [executable, "daemon", "start"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=60, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def cmd_supervise(rounds: int, pause: float) -> int:
    executable = binary()
    last, failures, retry_at = None, 0, 0.0
    for number in itertools.count(1):
        kind = daemon_kind(executable)
        if executable and kind in ("none", "other") and time.monotonic() >= retry_at:
            start_daemon(executable)
            kind = daemon_kind(executable)
            failures = 0 if kind == "permanent" else failures + 1
            retry_at = time.monotonic() + min(pause * 2 ** min(failures - 1, 16), SUPERVISE_CEILING) if failures else 0.0
        elif kind in ("permanent", "session-managed"):
            failures, retry_at = 0, 0.0
        if kind != last:
            print(f"graph: supervise: daemon {kind}", flush=True)
            last = kind
        if number == rounds:
            return 0
        time.sleep(pause)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("hook")
    index = sub.add_parser("index")
    index.add_argument("--root", required=True)
    index.add_argument("--mode", choices=("full", "moderate", "fast"), default=MODE)
    index.add_argument("--call-timeout", type=float, default=CALL_TIMEOUT)
    index.add_argument("--deadline", type=float, default=INDEX_DEADLINE)
    supervise = sub.add_parser("supervise")
    supervise.add_argument("--rounds", type=int, default=0)
    supervise.add_argument("--pause", type=float, default=SUPERVISE_SECONDS)
    enqueue = sub.add_parser("enqueue")
    for flag in ("--root", "--task", "--session"):
        enqueue.add_argument(flag, required=True)
    args = parser.parse_args()
    if args.command == "hook":
        try:
            return cmd_hook()
        except (OSError, subprocess.SubprocessError) as error:
            print(f"graph: hook skipped: {error}", file=sys.stderr)
            return 0
    if args.command == "supervise":
        return cmd_supervise(args.rounds, args.pause)
    if args.command == "enqueue":
        return cmd_enqueue(os.path.realpath(args.root), args.task, args.session)
    return cmd_index(os.path.realpath(args.root), args.mode, args.call_timeout, args.deadline)


if __name__ == "__main__":
    sys.exit(main())
