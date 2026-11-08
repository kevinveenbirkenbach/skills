#!/usr/bin/env python3
"""Watch disk, Docker and caches for the kvb-org-organize resource chair.

Usage:
    watch.py watch     hook (UserPromptSubmit, PostToolUse): measure at most once
                       per interval machine-wide, act on the stage, show alerts,
                       and append the rows of <root>/queue-history.jsonl
                       (kvb-org-queue) and <root>/security-accepted.jsonl
                       (kvb-check-security) whose id it lacks to the same name
                       under ~/.local/state/agents-council/
    watch.py block     hook (PreToolUse on Bash): exit 2 for a heavy job while the
                       disk stage is stop or critical, the memory stage is stop
                       or cannot be judged without memory_limits, or a
                       kvb-org-radio mayday holds radio silence
                       (<root>/radio-silence.json, until > now)
    watch.py admit (--need-gb N | --kind KIND)
                       exit 0 when the grant leaves at least the stop threshold
                       free, CPU busy and RAM used stay below load_limits and
                       the memory stage is not stop, 3 otherwise
    watch.py cleanup (--caches | --full)
                       trim caches to their budget; --full also runs the
                       configured low-risk cleanup commands
    watch.py status    print the stage computed from the live free space and the
                       stored samples, and the stored measurement's age in seconds

Environment:
    AGENTS_COUNCIL_ROOT: shared state directory; /tmp/agents-council unless set,
        because every agent on the host must agree on it. Every command creates
        it with mode 700; while it is a symlink, another uid's, or group or
        other writable, a hook mode prints why and exits 0 doing nothing and
        any other mode exits 2. queue.py and radio.py check it the same way.
    AGENTS_COUNCIL_CONFIG: config file; ~/.claude/agents-council/config.json
        unless set, a path the install denies to Claude Code's file tools and
        the sandbox's file rules do not let it write, because the hooks run
        its commands outside the sandbox; a Docker daemon the sandbox can
        reach still writes it. Without a config file every command exits 0 and does
        nothing.
    PATH: filtered to the directories hookpath.py trusts before any command
        runs, the config's commands included.

Config keys, all required: disk, thresholds_gb {warn, stop, critical},
projection_minutes, interval_seconds, cache_interval_seconds, heavy_commands,
never_block (regexes), cleanup (shell commands), worktree_cleanup (argv lists
with {project}, run without a shell in /, so no worktree file is read),
worktrees_command (shell command printing per running stack its worktree path
and compose project, tab-separated, one per line; a project that is not a
compose project name is skipped), worktree_marker (path relative
to a worktree that must exist), busy_processes (process names; a worktree
where one of them runs is skipped), cache_dirs, cache_budget_percent,
slot_need_gb {kind: GB}, notify (argv the alert text is appended to),
load_limits {cpu_percent, mem_percent, sample_seconds}: every admit and every
queue grant needs CPU busy and RAM used below them, memory_limits {warn, stop},
each {available, swap_free, psi_full, container_swap_gb}: the memory stage is
the first of stop and warn whose MemAvailable or SwapFree percentage lies below
its bound, whose /proc/pressure/memory full avg10 reaches its bound, or where
one container (a docker-*.scope cgroup under system.slice, nested groups
counted) holds at least container_swap_gb GB of swap, else ok; a host without
swap or PSI skips that bound. heavy_commands extend the built-in rules of
heavy().
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import importlib.util
import json
import math
import os
import re
import shlex
import stat
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType


def sibling(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"kvb_watch_{name}", Path(__file__).resolve().parent / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


nofollow = sibling("nofollow")
hookpath = sibling("hookpath")
ROOT = Path(os.environ.get("AGENTS_COUNCIL_ROOT", "/tmp/agents-council"))
CONFIG = Path(
    os.environ.get(
        "AGENTS_COUNCIL_CONFIG",
        str(Path.home() / ".claude" / "agents-council" / "config.json"),
    )
)
PROJECT = re.compile(r"[a-z0-9][a-z0-9_-]*")
STAGES = ("ok", "warn", "stop", "critical")
STATE = ROOT / "watch.json"
SILENCE = ROOT / "radio-silence.json"
ALERTS = ROOT / "alerts.jsonl"
KEPT = Path.home() / ".local" / "state" / "agents-council"
HISTORY = ROOT / "queue-history.jsonl"
KEPT_HISTORY = KEPT / "queue-history.jsonl"
ACCEPTED = ROOT / "security-accepted.jsonl"
KEPT_ACCEPTED = KEPT / "security-accepted.jsonl"
MIRRORED = ((HISTORY, KEPT_HISTORY), (ACCEPTED, KEPT_ACCEPTED))
ALERT_TTL = 3600
CLIP = 1000
CLEANUP_LOCK = "cleanup.lock"
LOCK_TTL = 1800
GB = 1e9
MEMINFO = Path("/proc/meminfo")
PRESSURE = Path("/proc/pressure/memory")
CGROUPS = Path("/sys/fs/cgroup/system.slice")
SWAP_HOLDERS = 3
NEST_DEPTH = 8
MEMORY_STAGES = ("ok", "warn", "stop")
MEMORY_BOUNDS = ("available", "swap_free", "psi_full", "container_swap_gb")
MEMORY_KEYS = tuple(f"memory_limits.{stage}.{bound}" for stage in MEMORY_STAGES[1:] for bound in MEMORY_BOUNDS)
CONTAINER_ID = re.compile(r"[0-9a-f]{64}")
COMPOSE_VALUES = frozenset({
    "-f", "--file", "-p", "--project-name", "--project-directory", "--env-file", "--profile", "--ansi", "--parallel",
    "--progress",
})
BUILDING = frozenset({"up", "run", "create"})
SEPARATOR = re.compile(r"[();<>|&\n]+")
PUNCTUATION = "();<>|&\n"
WORD_BREAK = " \t\n;&|()<>"
ASSIGNMENT = re.compile(r"[A-Za-z_]\w*=.*", re.DOTALL)
WRAPPERS = frozenset({
    "env", "sudo", "nice", "nohup", "timeout", "exec", "xargs", "stdbuf", "ionice", "uv", "uvx", "poetry", "pdm",
    "pipenv", "coverage", "time", "command",
})
UV_VALUES = frozenset({
    "--with", "--extra", "--group", "--python", "-p", "--project", "--directory", "--package", "--env-file", "--from",
})
WRAPPER_VALUES = {
    "sudo": frozenset({
        "-u", "-g", "-h", "-p", "-C", "-D", "-r", "-t", "-U", "-T", "--user", "--group", "--host", "--chdir", "--role",
        "--type", "--prompt", "--other-user", "--command-timeout", "--close-from",
    }),
    "timeout": frozenset({"-s", "-k", "--signal", "--kill-after"}),
    "env": frozenset({"-u", "-C", "--unset", "--chdir"}),
    "nice": frozenset({"-n", "--adjustment"}),
    "ionice": frozenset({"-c", "-n", "-p", "--class", "--classdata"}),
    "xargs": frozenset({"-a", "-d", "-E", "-I", "-L", "-n", "-P", "-s"}),
    "stdbuf": frozenset({"-i", "-o", "-e"}),
    "time": frozenset({"-f", "-o", "--format", "--output"}),
    "exec": frozenset({"-a"}),
    "uv": UV_VALUES,
    "uvx": UV_VALUES,
    "poetry": frozenset({"-C", "-P", "--directory", "--project"}),
    "pdm": frozenset({"-p", "--project"}),
    "coverage": frozenset({"--source", "--include", "--omit", "--rcfile", "--context", "--data-file"}),
}
WRAPPER_WORDS = frozenset({"run", "tool"})
RESERVED = frozenset({"!", "{", "if", "then", "else", "elif", "do", "while", "until"})
WRAPPER_ARGUMENT = re.compile(r"-.*|\d+(\.\d+)?[smhd]?", re.DOTALL)
SHELLS = frozenset({"bash", "sh", "zsh", "dash"})
INLINE = re.compile(r"-[A-Za-z]*c[A-Za-z]*")
REDIRECT = re.compile(r"&?[<>]+&?")
TRAILING_REDIRECT = re.compile(r"[<>]+&?$")
PAREN = {"(": 1, ")": -1}
PYTHON = re.compile(r"python[\d.]*")
PYTHON_VALUE_OPTIONS = frozenset({"-X", "-W", "-Q"})
DRY_RUN = frozenset({"-n", "--dry-run", "--just-print", "--recon", "-q", "--question"})
SHORT_DRY = re.compile(r"-(?:(?![CfIoOWjl])[A-Za-z])*[nq][A-Za-z]*")
SHELL_VALUE = re.compile(r"[-+][A-Za-z]*[oO]|--rcfile|--init-file")
STDIN_FLAG = re.compile(r"-[A-Za-z]*s[A-Za-z]*")
SPACE = re.compile(r"\s")
ESCAPED = re.compile(r"\\[`$]")
OPENER = re.compile(r"`|\$\(")
PLACEHOLDER = "-_"
HEREDOC_MARK = "kvbheredoc"
MARK_WORD = re.compile(rf"{HEREDOC_MARK}((?:[0-9a-f]{{2}})*)")
HELP = frozenset({"-h", "--help", "--version"})
PYTEST_LIGHT = HELP | {"--collect-only", "--co"}
TEST_FILE = re.compile(r"[^*?\[\]]+\.py(::.*)?", re.DOTALL)
PYTEST_VALUE_OPTIONS = frozenset({
    "-p", "-k", "-m", "-c", "-o", "-W", "-n", "--numprocesses", "-r", "--maxfail", "--tb", "--rootdir", "--basetemp", "--deselect",
    "--ignore", "--ignore-glob", "--confcutdir", "--durations", "--junitxml", "--log-level", "--dist", "--cov",
    "--cov-report", "--cov-config", "--timeout", "--import-mode", "--capture", "--color", "--log-cli-level",
    "--log-file", "--reruns", "--tx", "--max-worker-restart",
})
UNITTEST_VALUE_OPTIONS = frozenset({"-k"})
DISCOVER_VALUE_OPTIONS = frozenset({"-s", "-p", "-t", "-k", "--start-directory", "--pattern", "--top-level-directory"})
PATTERN_OPTIONS = frozenset({"-p", "--pattern"})
MAKE_VALUE_OPTIONS = frozenset({
    "-C", "-f", "-I", "-o", "-W", "--directory", "--file", "--makefile", "--include-dir", "--old-file", "--assume-old",
    "--what-if", "--new-file", "--assume-new",
})


def guard_root(hook: bool) -> int | None:
    try:
        ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    except FileExistsError:
        pass
    st = ROOT.lstat()
    if stat.S_ISDIR(st.st_mode) and st.st_uid == os.getuid() and not st.st_mode & 0o022:
        return None
    print(
        f"agents council: {ROOT} must be a directory of uid {os.getuid()} that group and others cannot write; "
        "the council hooks stay off until it is",
        file=sys.stdout if hook else sys.stderr,
    )
    return 0 if hook else 2


def load_config() -> dict | None:
    if not CONFIG.is_file():
        return None
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def absent_part(cfg: dict, key: str) -> str | None:
    node: object = cfg
    parts = key.split(".")
    for depth, part in enumerate(parts, 1):
        if not isinstance(node, dict) or part not in node:
            return ".".join(parts[:depth])
        node = node[part]
    return None if isinstance(node, (int, float)) and not isinstance(node, bool) and math.isfinite(node) else key


def missing(cfg: dict, keys: tuple[str, ...]) -> str | None:
    """Args:
        cfg: the config.
        keys: required number keys, nested ones dotted
            (`memory_limits.stop.psi_full`).

    Returns:
        None when every key holds a number, else the error naming the
        shortest missing part of each, or the key whose value is no number.
    """
    absent = list(dict.fromkeys(part for key in keys if (part := absent_part(cfg, key)) is not None))
    if not absent:
        return None
    return (
        f"agents council: {CONFIG} lacks {', '.join(absent)}; add them as numbers as the watch.py and queue.py "
        "docstrings document"
    )


def disk(cfg: dict) -> tuple[float, float]:
    st = os.statvfs(cfg["disk"])
    return st.f_bavail * st.f_frsize / GB, st.f_blocks * st.f_frsize / GB


def clip(value: object) -> str:
    return " ".join(str(value).split()).replace("<", "<\\")[:CLIP]


def read_json(path: Path) -> dict:
    try:
        data = json.loads(nofollow.read_text(ROOT, path))
    except (OSError, ValueError, RecursionError):
        return {}
    return data if isinstance(data, dict) else {}


def write_json(path: Path, data: dict) -> None:
    write_text(path, json.dumps(data))


def stage_for(free: float, samples: list[list[float]], cfg: dict, now: float) -> str:
    limits = cfg["thresholds_gb"]
    level = 0
    for index, name in ((1, "warn"), (2, "stop"), (3, "critical")):
        if free < limits[name]:
            level = index
    window = cfg["projection_minutes"] * 60
    recent = [s for s in samples if now - s[0] <= window and now > s[0]]
    if recent and level < 3:
        then, before = recent[0]
        rate = (before - free) / (now - then)
        if rate > 0 and (free - limits["critical"]) / rate < window:
            level += 1
    return STAGES[level]


def alert(stage: str, text: str) -> None:
    try:
        ROOT.mkdir(parents=True, exist_ok=True)
        nofollow.append(ROOT, ALERTS, json.dumps({"id": time.time_ns(), "stage": stage, "text": text}) + "\n", 0o600)
    except OSError:
        pass


def unseen_alerts(session: str) -> list[str]:
    seen_path = ROOT / "seen" / session
    try:
        seen = int(nofollow.read_text(ROOT, seen_path))
    except (OSError, ValueError):
        seen = 0
    try:
        text = nofollow.read_text(ROOT, ALERTS)
    except OSError:
        return []
    cutoff = time.time_ns() - ALERT_TTL * 10**9
    fresh = [json.loads(line) for _, line in history_rows(text)]
    fresh = [
        a for a in fresh
        if isinstance(a["id"], int) and isinstance(a.get("text"), str) and a["id"] > max(seen, cutoff)
    ]
    if fresh:
        write_text(seen_path, str(fresh[-1]["id"]))
    return [clip(a["text"]) for a in fresh]


def write_text(path: Path, text: str) -> None:
    try:
        nofollow.replace(ROOT, path, text, 0o600)
    except OSError:
        pass


def consumers() -> str:
    try:
        out = subprocess.run(
            ["docker", "system", "df", "--format", "{{.Type}}: {{.Size}} ({{.Reclaimable}} reclaimable)"],
            capture_output=True, text=True, timeout=30, check=False,
        ).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return "docker system df unavailable"
    return "; ".join(out.splitlines()) or "docker system df printed nothing"


def notify(cfg: dict, text: str) -> None:
    try:
        subprocess.run([*cfg["notify"], text], capture_output=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        alert("critical", f"RESOURCE: desktop notification failed: {cfg['notify'][0]}")


def spawn_cleanup(mode: str) -> None:
    subprocess.Popen(
        [sys.executable, "-I", str(Path(__file__).resolve()), "cleanup", mode],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def act(cfg: dict, stage: str, previous: str, free: float) -> None:
    limits = cfg["thresholds_gb"]
    head = f"/ has {free:.1f} GB free (warn < {limits['warn']}, stop < {limits['stop']}, critical < {limits['critical']} GB)"
    if STAGES.index(stage) < STAGES.index(previous):
        alert(stage, f"RESOURCE {stage.upper()}: recovered, {head}.")
        return
    if stage == "warn":
        alert(stage, f"RESOURCE WARN: {head}. Biggest consumers: {consumers()}. Chair: plan a cleanup; peers: request no large slot.")
    elif stage in ("stop", "critical"):
        alert(stage, f"RESOURCE {stage.upper()}: {head}. New heavy jobs are blocked; low-risk cleanup is running. {consumers()}")
        spawn_cleanup("--full")
        if stage == "critical":
            notify(cfg, f"Agents council: {head}. Heavy jobs blocked; a running stack needs the operator's OK to go.")


def act_memory(cfg: dict, stage: str, previous: str, sample: dict[str, float | None]) -> None:
    head = memory_text(sample)
    if MEMORY_STAGES.index(stage) < MEMORY_STAGES.index(previous):
        alert(stage, f"RESOURCE MEMORY {stage.upper()}: recovered, {head}.")
        return
    holders = "; ".join(swap_holders(CGROUPS, container_names())) or "no container holds swap"
    if stage == "warn":
        alert(stage, f"RESOURCE MEMORY WARN: {head}. Top swap holders: {holders}. Chair: find the holder; peers: start nothing heavy.")
    else:
        alert(stage, f"RESOURCE MEMORY STOP: {head}. New heavy jobs are blocked. Top swap holders: {holders}.")
        notify(cfg, f"Agents council: memory nearly exhausted ({head}). Heavy jobs blocked; top swap holders: {holders}.")


def history_rows(text: str) -> list[tuple[str, str]]:
    rows = []
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except (ValueError, RecursionError):
            continue
        if isinstance(row, dict) and "id" in row:
            rows.append((row["id"], line))
    return rows


def keep_rows(origin: Path, target: Path) -> None:
    # The agents' sandbox cannot write ~/.local/state and /tmp is wiped on reboot, so this hook keeps the rows.
    # The kept file takes the source's mtime: an unchanged source is skipped without parsing.
    try:
        source = origin.stat().st_mtime_ns
        if target.exists() and target.stat().st_mtime_ns == source:
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a+", encoding="utf-8") as kept:
            fcntl.flock(kept, fcntl.LOCK_EX | fcntl.LOCK_NB)
            kept.seek(0)
            known = {row_id for row_id, _ in history_rows(kept.read())}
            for row_id, line in history_rows(nofollow.read_text(ROOT, origin)):
                if row_id not in known:
                    known.add(row_id)
                    kept.write(line + "\n")
            kept.flush()
            os.utime(target, ns=(source, source))
    except (OSError, ValueError, TypeError):
        pass


def keep_history() -> None:
    for origin, target in MIRRORED:
        keep_rows(origin, target)


def stale(state: dict, cfg: dict, now: float) -> bool:
    return now - state.get("checked", 0) >= cfg["interval_seconds"]


def measure_and_act(cfg: dict, state: dict, now: float, problem: str | None) -> None:
    free, _ = disk(cfg)
    samples = [s for s in state.get("samples", []) if now - s[0] <= cfg["projection_minutes"] * 60]
    stage = stage_for(free, samples, cfg, now)
    previous = state.get("stage", "ok")
    samples.append([now, free])
    state.update(checked=now, free=free, stage=stage, samples=samples)
    sample = None if problem else memory()
    was_short = state.get("memory_stage", "ok")
    if sample is not None:
        state["memory_stage"] = memory_stage(sample, cfg)
    due = now - state.get("caches_checked", 0) >= cfg["cache_interval_seconds"]
    if due:
        state["caches_checked"] = now
    write_json(STATE, state)
    if stage != previous:
        act(cfg, stage, previous, free)
    elif due:
        spawn_cleanup("--caches")
    if sample is not None and state["memory_stage"] != was_short:
        act_memory(cfg, state["memory_stage"], was_short, sample)


def cmd_watch(cfg: dict, problem: str | None) -> int:
    """Args:
        cfg: the config.
        problem: why the memory stage cannot be judged, None when it can; the
            disk part still runs and every session sees the problem.
    """
    payload = json.load(sys.stdin)
    now = time.time()
    state = read_json(STATE)
    if stale(state, cfg, now):
        measure_and_act(cfg, state, now, problem)
    keep_history()
    texts = unseen_alerts(payload["session_id"]) + ([] if problem is None else [problem])
    if texts:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": payload["hook_event_name"],
            "additionalContext": "\n".join(texts),
        }}))
    return 0


HEREDOC = re.compile(
    r"<<-?\s*(?P<quote>['\"]?)(?P<escape>\\?)(?P<tag>[\w.-]+)(?P=quote)(?P<rest>[^\n]*)\n(?P<body>.*?)\n\s*(?P=tag)(?=\s|\)|$)",
    re.DOTALL,
)
QUOTED = re.compile(r"'[^']*'|\"(?:\\.|[^\"\\])*\"")


def executable_text(command: str) -> str:
    return QUOTED.sub("''", HEREDOC.sub("", command))


def silence() -> dict | None:
    state = read_json(SILENCE)
    return state if state.get("until", 0) > time.time() else None


def uncommented(command: str) -> str:
    kept: list[str] = []
    quote = ""
    escaped = skipping = False
    word_start = True
    for char in command:
        if skipping and char != "\n":
            continue
        skipping = False
        if escaped:
            escaped = False
        elif quote == "'":
            quote = "" if char == "'" else quote
        elif char == "\\":
            escaped = True
        elif quote == '"':
            quote = "" if char == '"' else quote
        elif char in "'\"":
            quote = char
        elif char == "#" and word_start:
            skipping = True
            continue
        kept.append(char)
        word_start = not quote and not escaped and char in WORD_BREAK
    return "".join(kept)


def segments(command: str) -> list[list[str]]:
    """Args:
        command: a shell command line.

    Returns:
        The words of each simple command, split at newlines, `;`, `&`, `|`
        and parentheses; a redirection, its target and a file descriptor
        number in front of it are dropped and the command goes on.

    Raises:
        ValueError: on an unbalanced quote.
    """
    lexer = shlex.shlex(uncommented(command.replace("\\\n", "")), posix=True, punctuation_chars=PUNCTUATION)
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = ""
    parts: list[list[str]] = [[]]
    target = False
    for token in lexer:
        if REDIRECT.fullmatch(token):
            if parts[-1] and parts[-1][-1].isdigit():
                parts[-1].pop()
            target = True
        elif SEPARATOR.fullmatch(token):
            parts.append([])
            target = TRAILING_REDIRECT.search(token) is not None
        elif target:
            target = False
        else:
            parts[-1].append(token)
    return parts


def program(words: list[str]) -> list[str]:
    """Returns:
        The words from the program on: shell reserved words, VAR=value,
        wrappers such as env, sudo, time, timeout or `uv run`, their options,
        the values of their options and their numbers dropped; the split
        string of `env -S`, nothing for the lookup `command -v`.
    """
    at, wrapper = 0, ""
    while at < len(words):
        word = words[at]
        if os.path.basename(word) in WRAPPERS:
            wrapper = os.path.basename(word)
        elif word in WRAPPER_VALUES.get(wrapper, ()):
            at += 1
        elif word in WRAPPER_TURNS.get(wrapper, {}):
            return WRAPPER_TURNS[wrapper][word](words[at + 1 :])
        elif not (word in RESERVED or ASSIGNMENT.fullmatch(word) or (wrapper and wrapped_word(word))):
            break
        at += 1
    return words[at:]


def lookup(rest: list[str]) -> list[str]:
    return []


def split_string(rest: list[str]) -> list[str]:
    return program(" ".join(rest[:1]).split() + rest[1:])


WRAPPER_TURNS = {
    "command": {"-v": lookup, "-V": lookup},
    "env": {"-S": split_string, "--split-string": split_string},
}


def wrapped_word(word: str) -> bool:
    return word in WRAPPER_WORDS or WRAPPER_ARGUMENT.fullmatch(word) is not None


def inline_code(words: list[str]) -> str | None:
    """Args:
        words: a simple command from its program on.

    Returns:
        The code a shell runs with -c (also clustered, such as -lc or -ic,
        and after a `--`), else None.
    """
    if not words or os.path.basename(words[0]) not in SHELLS:
        return None
    rest = words[1:]
    for at, word in enumerate(rest):
        if INLINE.fullmatch(word):
            code = [later for later in rest[at + 1 :] if later != "--"][:1]
            return code[0] if code else None
    return None


def operands(args: list[str], value_options: frozenset[str]) -> list[str]:
    found, skip = [], False
    for word in args:
        if skip:
            skip = False
        elif word in value_options:
            skip = True
        elif not word.startswith("-"):
            found.append(word)
    return found


def python_module(args: list[str]) -> tuple[str, list[str]]:
    skip = False
    for at, word in enumerate(args):
        if skip:
            skip = False
        elif word == "-m":
            return (args[at + 1], args[at + 2 :]) if at + 1 < len(args) else ("", [])
        elif word.startswith("-m"):
            return word[2:], args[at + 1 :]
        elif word in PYTHON_VALUE_OPTIONS:
            skip = True
        elif not word.startswith("-"):
            return os.path.basename(word), args[at + 1 :]
    return "", []


def light_unittest(args: list[str]) -> bool:
    if args[:1] != ["discover"]:
        return len(operands(args, UNITTEST_VALUE_OPTIONS)) == 1
    rest = args[1:]
    patterns = [rest[at + 1] for at, word in enumerate(rest[:-1]) if word in PATTERN_OPTIONS]
    patterns = patterns or operands(rest, DISCOVER_VALUE_OPTIONS)[1:2]
    return bool(patterns) and TEST_FILE.fullmatch(patterns[-1]) is not None


def heavy_pytest(args: list[str]) -> bool:
    files = operands(args, PYTEST_VALUE_OPTIONS)
    return not (PYTEST_LIGHT.intersection(args) or (len(files) == 1 and TEST_FILE.fullmatch(files[0])))


def heavy_unittest(args: list[str]) -> bool:
    return not (HELP.intersection(args) or light_unittest(args))


def make_targets(args: list[str]) -> list[str]:
    return [word for word in operands(args, MAKE_VALUE_OPTIONS) if "=" not in word and not word.isdigit()]


def dry_run(args: list[str]) -> bool:
    return bool(DRY_RUN.intersection(args)) or any(SHORT_DRY.fullmatch(word) for word in args)


def heavy_make(args: list[str]) -> bool:
    return not dry_run(args) and any(target == "install" or target.startswith("verify-") for target in make_targets(args))


def heavy_compose(args: list[str]) -> bool:
    words = operands(args, COMPOSE_VALUES)
    command = words[0] if words else ""
    return command == "build" or (command in BUILDING and "--build" in args)


def heavy_docker(args: list[str]) -> bool:
    return args[:1] == ["compose"] and heavy_compose(args[1:])


HEAVY_TOOLS = {
    "pytest": heavy_pytest, "py.test": heavy_pytest, "unittest": heavy_unittest, "make": heavy_make,
    "docker": heavy_docker, "docker-compose": heavy_compose,
}


def heavy_words(run: list[str], cfg: dict, exempt: tuple[str, ...]) -> bool:
    if not run:
        return False
    code = inline_code(run)
    if code is not None:
        return heavy(code, cfg, exempt)
    name, args = os.path.basename(run[0]), run[1:]
    if PYTHON.fullmatch(name):
        name, args = python_module(args)
        if name in WRAPPERS:
            return heavy_words(program([name, *args]), cfg, exempt)
    return name in HEAVY_TOOLS and HEAVY_TOOLS[name](args)


def segment_texts(words: list[str], run: list[str]) -> list[str]:
    return list(dict.fromkeys(" ".join("''" if SPACE.search(word) else word for word in part) for part in (words, run)))


def judged(texts: list[str], run: list[str], cfg: dict, exempt: tuple[str, ...]) -> bool:
    if any(re.search(pattern, text) for pattern in exempt for text in texts):
        return False
    if any(re.search(pattern, text) for pattern in cfg["heavy_commands"] for text in texts):
        return True
    return heavy_words(run, cfg, exempt)


def heavy_part(words: list[str], cfg: dict, exempt: tuple[str, ...]) -> bool:
    """Returns:
        Whether one simple command is heavy; a make call is judged per target
        as `make <target>`, so an exempt target never covers the next one.
    """
    run = program(words)
    if run and os.path.basename(run[0]) == "make" and not dry_run(run[1:]):
        return any(judged([f"make {target}"], ["make", target], cfg, exempt) for target in make_targets(run[1:]))
    return judged(segment_texts(words, run), run, cfg, exempt)


def marked_heredocs(command: str) -> tuple[str, list[re.Match[str]]]:
    """Returns:
        The command with each heredoc replaced by the word HEREDOC_MARK
        followed by its body in hex, so a nested call still reads it, the
        rest of its first line kept, and the heredoc matches.
    """
    found: list[re.Match[str]] = []

    def mark(match: re.Match[str]) -> str:
        found.append(match)
        return f" {HEREDOC_MARK}{match['body'].encode(errors='surrogatepass').hex()} {match['rest']}"

    return HEREDOC.sub(mark, command), found


def shell_operands(args: list[str]) -> list[str]:
    found, skip = [], False
    for word in args:
        if skip:
            skip = False
        elif word.startswith(("-", "+")):
            skip = SHELL_VALUE.fullmatch(word) is not None
        else:
            found.append(word)
    return found


def reads_stdin(run: list[str]) -> bool:
    """Returns:
        Whether a simple command from its program on is a shell that runs the
        code on its stdin: no -c code, and -s or no operand but heredoc marks.
    """
    if not run or os.path.basename(run[0]) not in SHELLS or inline_code(run) is not None:
        return False
    args = run[1:]
    return any(STDIN_FLAG.fullmatch(word) for word in args) or all(MARK_WORD.fullmatch(word) for word in shell_operands(args))


def expanded_codes(heredocs: list[re.Match[str]]) -> list[str]:
    """Returns:
        The command substitutions in the bodies of heredocs whose delimiter
        is unquoted, which the shell expands.
    """
    return [code for match in heredocs if not (match["quote"] or match["escape"]) for code in substituted(match["body"])[1]]


def fed_bodies(parts: list[list[str]]) -> list[str]:
    marks = [MARK_WORD.fullmatch(word) for words in parts if reads_stdin(program(words)) for word in words]
    return [bytes.fromhex(mark[1]).decode(errors="ignore") for mark in marks if mark]


def closing(text: str, start: int) -> int:
    depth = 1
    for at in range(start, len(text)):
        depth += PAREN.get(text[at], 0)
        if depth == 0:
            return at
    return len(text)


def blanked_single(quoted: re.Match[str]) -> str:
    text = quoted[0]
    return text if text.startswith('"') else "'" + " " * (len(text) - 2) + "'"


def substitution_end(shown: str, found: re.Match[str]) -> int:
    if found[0] == "`":
        end = shown.find("`", found.end())
        return len(shown) if end < 0 else end
    return closing(shown, found.end())


def substituted(text: str) -> tuple[str, list[str]]:
    """Returns:
        The text with every `...` and $(...) outside single quotes and
        escapes replaced by the option-like word PLACEHOLDER, so a wrapper
        around it still parses, and the code of each, which the shell runs
        first; nested ones stay inside their code.
    """
    shown = QUOTED.sub(blanked_single, ESCAPED.sub("  ", text))
    kept: list[str] = []
    codes: list[str] = []
    at = 0
    found = OPENER.search(shown)
    while found:
        end = substitution_end(shown, found)
        kept.append(text[at : found.start()] + PLACEHOLDER)
        codes.append(text[found.end() : end])
        at = end + 1
        found = OPENER.search(shown, at)
    return "".join(kept) + text[at:], codes


def cmd_block(cfg: dict, problem: str | None) -> int:
    """Args:
        cfg: the config.
        problem: why the memory stage cannot be judged, None when it can; a
            heavy job is then refused with it.
    """
    payload = json.load(sys.stdin)
    raw = (payload.get("tool_input") or {}).get("command", "")
    if not heavy(raw, cfg, tuple(cfg["never_block"])):
        return 0
    reason = block_reason(cfg, problem)
    if reason is None:
        return 0
    print(f"kvb-org-organize: {reason}. Teardown commands still run. Ask the resource chair.", file=sys.stderr)
    return 2


def disk_stage(cfg: dict) -> str:
    state = read_json(STATE)
    now = time.time()
    if stale(state, cfg, now):
        return stage_for(disk(cfg)[0], state.get("samples", []), cfg, now)
    return state.get("stage", "ok")


def block_reason(cfg: dict, problem: str | None) -> str | None:
    mayday = silence()
    if mayday:
        return (
            f"a mayday by {clip(mayday.get('by', '?'))} holds radio silence: {clip(mayday.get('text', ''))}; "
            "it ends with radio.py clear"
        )
    stage = disk_stage(cfg)
    if stage in ("stop", "critical"):
        return f"resource stage is {stage}; new heavy jobs are blocked until the disk recovers"
    if problem is not None:
        return f"{problem}; new heavy jobs are blocked until it does"
    sample = memory()
    if memory_stage(sample, cfg) == "stop":
        return f"memory stage is stop ({memory_text(sample)}); new heavy jobs are blocked until memory recovers"
    return None


def cpu_times() -> tuple[int, int]:
    fields = [int(v) for v in Path("/proc/stat").read_text(encoding="utf-8").split("\n", 1)[0].split()[1:]]
    return sum(fields), fields[3] + fields[4]


def cpu_busy_percent(before: tuple[int, int], after: tuple[int, int]) -> float:
    total = after[0] - before[0]
    idle = after[1] - before[1]
    return 100.0 * (total - idle) / total


def meminfo_kb(meminfo: str) -> dict[str, int]:
    values = {}
    for line in meminfo.splitlines():
        key, _, rest = line.partition(":")
        if rest:
            values[key] = int(rest.split()[0])
    return values


def mem_used_percent(meminfo: str) -> float:
    values = meminfo_kb(meminfo)
    return 100.0 * (1 - values["MemAvailable"] / values["MemTotal"])


def load(cfg: dict) -> tuple[float, float]:
    before = cpu_times()
    time.sleep(cfg["load_limits"]["sample_seconds"])
    cpu = cpu_busy_percent(before, cpu_times())
    return cpu, mem_used_percent(MEMINFO.read_text(encoding="utf-8"))


def psi_full(pressure: str) -> float | None:
    for line in pressure.splitlines():
        if line.startswith("full "):
            return float(dict(field.split("=", 1) for field in line.split()[1:])["avg10"])
    return None


def memory_sample(meminfo: str, pressure: str | None, container_swap_gb: float) -> dict[str, float | None]:
    """Args:
        meminfo: the text of /proc/meminfo.
        pressure: the text of /proc/pressure/memory, None without PSI.
        container_swap_gb: the swap of the container holding the most, in GB.

    Returns:
        {available, swap_free, psi_full, container_swap_gb}: MemAvailable and
        SwapFree in percent of their totals, the full avg10 stall percentage
        and container_swap_gb unchanged; swap_free is None without swap,
        psi_full None without PSI.
    """
    values = meminfo_kb(meminfo)
    swap = values["SwapTotal"]
    return {
        "available": 100.0 * values["MemAvailable"] / values["MemTotal"],
        "swap_free": 100.0 * values["SwapFree"] / swap if swap else None,
        "psi_full": None if pressure is None else psi_full(pressure),
        "container_swap_gb": container_swap_gb,
    }


def memory() -> dict[str, float | None]:
    try:
        pressure = PRESSURE.read_text(encoding="utf-8")
    except OSError:
        pressure = None
    largest = max((size for size, _ in container_swaps(CGROUPS)), default=0)
    return memory_sample(MEMINFO.read_text(encoding="utf-8"), pressure, largest / GB)


def memory_stage(sample: dict[str, float | None], cfg: dict) -> str:
    for name in ("stop", "warn"):
        bound = cfg["memory_limits"][name]
        if (
            sample["available"] < bound["available"]
            or (sample["swap_free"] is not None and sample["swap_free"] < bound["swap_free"])
            or (sample["psi_full"] is not None and sample["psi_full"] >= bound["psi_full"])
            or sample["container_swap_gb"] >= bound["container_swap_gb"]
        ):
            return name
    return "ok"


def memory_text(sample: dict[str, float | None]) -> str:
    swap = "no swap" if sample["swap_free"] is None else f"swap free {sample['swap_free']:.0f} %"
    psi = "no PSI" if sample["psi_full"] is None else f"PSI full avg10 {sample['psi_full']:.1f}"
    return f"MemAvailable {sample['available']:.0f} %, {swap}, {psi}, largest container swap {sample['container_swap_gb']:.1f} GB"


def swap_bytes(cgroup: Path) -> int:
    try:
        return int((cgroup / "memory.swap.current").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0


def container_swaps(base: Path) -> list[tuple[int, Path]]:
    try:
        return [(swap_bytes(scope), scope) for scope in base.glob("docker-*.scope")]
    except OSError:
        return []


def cgroup_label(name: str, names: dict[str, str]) -> str:
    bare = name.removeprefix("docker-").removesuffix(".scope")
    if CONTAINER_ID.fullmatch(bare):
        return names[bare] if bare in names else bare[:12]
    return bare


def container_names() -> dict[str, str]:
    try:
        out = subprocess.run(
            ["docker", "ps", "--no-trunc", "--format", "{{.ID}}\t{{.Names}}"],
            capture_output=True, text=True, timeout=30, check=False,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return {}
    return dict(line.split("\t", 1) for line in out.splitlines() if "\t" in line)


def swap_chain(cgroup: Path, held: int, names: dict[str, str]) -> list[str]:
    chain = [cgroup_label(cgroup.name, names)]
    for _ in range(NEST_DEPTH):
        try:
            children = [(swap_bytes(child), child) for child in cgroup.iterdir() if child.is_dir()]
        except OSError:
            break
        if not children:
            break
        size, child = max(children)
        if size * 2 < held:
            break
        chain.append(cgroup_label(child.name, names))
        cgroup, held = child, size
    return chain


def swap_holders(base: Path, names: dict[str, str]) -> list[str]:
    """Args:
        base: the cgroup directory holding the docker-<id>.scope groups.
        names: {full container id: name} for the labels.

    Returns:
        Up to SWAP_HOLDERS lines, the largest swap first: the container, then
        each nested group holding at least half of its parent's swap, and the
        container's memory.swap.current in GB.
    """
    ranked = sorted((pair for pair in container_swaps(base) if pair[0] > 0), reverse=True)[:SWAP_HOLDERS]
    return [f"{' > '.join(swap_chain(scope, size, names))} {size / GB:.1f} GB" for size, scope in ranked]


def heavy(command: str, cfg: dict, exempt: tuple[str, ...]) -> bool:
    """Args:
        command: the shell command line as typed, quotes included.
        cfg: the config; its heavy_commands search each simple command with
            quoted text blanked, and a make call also as `make <targets>`.
        exempt: regexes; a simple command one of them finds is never heavy
            (never_block, the queue's own hold), the others still count.

    Returns:
        Whether one simple command is a heavy job: an image build through
        docker compose (build, or up, run or create with --build), a
        heavy_commands match, make install or verify-* (not as a dry run), or
        pytest or unittest on anything but exactly one test file or module,
        help and version aside. Wrappers (program()), the code of `sh -c`,
        command substitutions (substituted(), also in heredocs the shell
        expands) and heredocs a shell reads as its code count the same. A
        command with an unbalanced quote, which no shell runs, counts by the
        regexes on its whole text alone. A guard against accidental heavy
        runs, not a sandbox: a shell reading code from a pipe or a
        here-string, a script of its own, a program named by a substitution,
        quotes inside an expanding heredoc and an escaped backslash in front
        of a substitution are not looked into.
    """
    marked, heredocs = marked_heredocs(command)
    plain, codes = substituted(uncommented(marked))
    try:
        parts = segments(plain)
    except ValueError:
        text = executable_text(command)
        return not any(re.search(p, text) for p in exempt) and any(re.search(p, text) for p in cfg["heavy_commands"])
    nested = codes + expanded_codes(heredocs) + fed_bodies(parts)
    return any(heavy_part(words, cfg, exempt) for words in parts) or any(heavy(code, cfg, exempt) for code in nested)


def cmd_admit(cfg: dict, args: argparse.Namespace) -> int:
    need = args.need_gb if args.need_gb is not None else cfg["slot_need_gb"][args.kind]
    free, _ = disk(cfg)
    left = free - need
    floor = cfg["thresholds_gb"]["stop"]
    passed = [left >= floor]
    report = [f"free {free:.1f} GB, need {need} GB, leaves {left:.1f} GB (floor {floor} GB)"]
    limits = cfg["load_limits"]
    cpu, mem = load(cfg)
    sample = memory()
    stage = memory_stage(sample, cfg)
    passed += [cpu < limits["cpu_percent"], mem < limits["mem_percent"], stage != "stop"]
    report.append(f"cpu {cpu:.0f} % (limit {limits['cpu_percent']}), ram {mem:.0f} % (limit {limits['mem_percent']})")
    report.append(f"memory stage {stage} ({memory_text(sample)})")
    verdict = "grant" if all(passed) else "deny"
    print(f"{verdict}: {'; '.join(report)}")
    return 0 if verdict == "grant" else 3


def cache_files(dirs: list[str]) -> list[tuple[float, int, str, str]]:
    files = []
    seen: set[tuple[int, int]] = set()
    for root in map(os.path.expanduser, dirs):
        for base, _, names, fd in os.fwalk(root, follow_symlinks=False):
            for name in names:
                try:
                    st = os.stat(name, dir_fd=fd, follow_symlinks=False)
                except OSError:
                    continue
                if (st.st_dev, st.st_ino) in seen:
                    continue
                seen.add((st.st_dev, st.st_ino))
                files.append((st.st_atime, st.st_blocks * 512, os.path.join(base, name), root))
    return files


def trim_caches(cfg: dict) -> float:
    _, total = disk(cfg)
    budget = total * GB * cfg["cache_budget_percent"] / 100
    files = sorted(cache_files(cfg["cache_dirs"]))
    used = sum(size for _, size, _, _ in files)
    freed = 0
    for _, size, path, root in files:
        if used - freed <= budget:
            break
        try:
            nofollow.unlink(Path(root), Path(path))
            freed += size
        except OSError:
            continue
    return freed / GB


def running_worktrees(cfg: dict) -> list[tuple[str, str]]:
    try:
        out = subprocess.run(
            cfg["worktrees_command"], shell=True, capture_output=True, text=True, timeout=60, check=False
        ).stdout
    except subprocess.TimeoutExpired:
        return []
    pairs = {tuple(line.split("\t")) for line in out.splitlines()}
    return sorted(
        (tree, project)
        for tree, project in (pair for pair in pairs if len(pair) == 2)
        if PROJECT.fullmatch(project) and os.path.exists(os.path.join(tree, cfg["worktree_marker"]))
    )


def busy(tree: str, names: list[str]) -> bool:
    root = os.path.realpath(tree)
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            if Path(f"/proc/{pid}/comm").read_text(encoding="utf-8").strip() not in names:
                continue
            cwd = os.readlink(f"/proc/{pid}/cwd")
        except OSError:
            continue
        if cwd == root or cwd.startswith(root + os.sep):
            return True
    return False


def run_cleanup(cfg: dict) -> list[str]:
    commands = [(command, True) for command in cfg["cleanup"]]
    for tree, project in running_worktrees(cfg):
        if busy(tree, cfg["busy_processes"]):
            continue
        commands += [([arg.format(project=project) for arg in argv], False) for argv in cfg["worktree_cleanup"]]
    results = []
    for command, shell in commands:
        try:
            code = subprocess.run(command, shell=shell, cwd="/", capture_output=True, timeout=900, check=False).returncode
        except subprocess.TimeoutExpired:
            code = "timeout"
        results.append(f"{'ok' if code == 0 else f'failed ({code})'}: {command if shell else shlex.join(command)}")
    return results


def cmd_cleanup(cfg: dict, args: argparse.Namespace) -> int:
    root = nofollow.directory(ROOT, (), True)
    try:
        with contextlib.suppress(FileNotFoundError, NotADirectoryError):
            if time.time() - os.stat(CLEANUP_LOCK, dir_fd=root, follow_symlinks=False).st_mtime > LOCK_TTL:
                os.rmdir(CLEANUP_LOCK, dir_fd=root)
        try:
            os.mkdir(CLEANUP_LOCK, 0o700, dir_fd=root)
        except FileExistsError:
            return 0
        try:
            before, _ = disk(cfg)
            results = run_cleanup(cfg) if args.full else []
            cache_gb = trim_caches(cfg)
            after, _ = disk(cfg)
            failed = [r for r in results if not r.startswith("ok")]
            if args.full or cache_gb:
                alert(
                    "cleanup",
                    f"RESOURCE CLEANUP: freed {after - before:.1f} GB ({cache_gb:.1f} GB caches), "
                    f"/ now {after:.1f} GB free; {len(results) - len(failed)} commands ok"
                    + (f", failed: {' | '.join(failed)}" if failed else "."),
                )
        finally:
            os.rmdir(CLEANUP_LOCK, dir_fd=root)
    finally:
        os.close(root)
    return 0


def cmd_status(cfg: dict) -> int:
    state = read_json(STATE)
    free, total = disk(cfg)
    now = time.time()
    samples = state.get("samples", [])
    age = f"{now - state['checked']:.0f}s" if "checked" in state else "unmeasured"
    sample = memory()
    print(
        f"stage={stage_for(free, samples, cfg, now)} free={free:.1f}GB total={total:.1f}GB samples={len(samples)} age={age}"
        f" memory={memory_stage(sample, cfg)} ({memory_text(sample)})"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="watch")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("watch")
    sub.add_parser("block")
    admit = sub.add_parser("admit")
    need = admit.add_mutually_exclusive_group(required=True)
    need.add_argument("--need-gb", type=float)
    need.add_argument("--kind")
    cleanup = sub.add_parser("cleanup")
    mode = cleanup.add_mutually_exclusive_group(required=True)
    mode.add_argument("--caches", action="store_true")
    mode.add_argument("--full", action="store_true")
    sub.add_parser("status")
    args = parser.parse_args()
    os.environ["PATH"] = hookpath.trusted(os.environ.get("PATH", ""))
    refused = guard_root(hook=args.cmd in ("watch", "block"))
    if refused is not None:
        return refused
    cfg = load_config()
    if cfg is None:
        return 0
    problem = missing(cfg, MEMORY_KEYS)
    if args.cmd == "watch":
        return cmd_watch(cfg, problem)
    if args.cmd == "block":
        return cmd_block(cfg, problem)
    if problem is not None:
        print(problem, file=sys.stderr)
        return 2
    if args.cmd == "admit":
        return cmd_admit(cfg, args)
    if args.cmd == "cleanup":
        return cmd_cleanup(cfg, args)
    return cmd_status(cfg)


if __name__ == "__main__":
    sys.exit(main())
