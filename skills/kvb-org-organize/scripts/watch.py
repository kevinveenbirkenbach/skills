#!/usr/bin/env python3
"""Watch disk, Docker and caches for the kvb-org-organize resource chair.

Usage:
    watch.py watch     hook (UserPromptSubmit; PostToolUse on Bash through
                       hooks.py post-bash): measure at most once
                       per interval machine-wide, act on the stage, show alerts,
                       and append the rows of <root>/queue-history.jsonl
                       (kvb-org-queue), <root>/security-accepted.jsonl
                       (kvb-check-security), <root>/gate-receipts.jsonl and
                       <root>/gate-parents.jsonl (kvb-check-gate) whose id it
                       lacks to the same name in the host-only root
                       (councilroot.py durable), never through a link
    watch.py block     hook (PreToolUse on Bash through hooks.py pre-bash): exit 2
                       for a heavy job while the
                       disk stage is stop or critical, the memory stage is stop
                       or cannot be judged without memory_limits, or a
                       kvb-org-radio mayday holds radio silence
                       (<root>/radio-silence.json, until > now)
    watch.py admit (--need-gb N | --kind KIND) -- CMD...
                       exit 0 when the grant leaves at least the stop threshold
                       free, the memory stage is not stop and queue.py admit()
                       keeps CPU and RAM below load_limits, 3 otherwise; 3 at
                       once for a CMD light() does not recognise, which
                       queue_hold() runs
    watch.py preflight exit 2 naming every missing memory_limits key while the
                       config lacks one this code needs, else 0, touching no
                       state
    watch.py cleanup (--caches | --full)
                       trim caches to their budget; --full also runs the
                       configured low-risk cleanup commands
    watch.py status    print the stage computed from the live free space and the
                       stored samples, and the stored measurement's age in seconds
    watch.py guard REAL REPORT ARGS...
                       the docker and docker-compose shim of the cleanup shell
                       lines: an image prune becomes the leftover step on the
                       same daemon, a system prune, rmi, image rm, image
                       remove or compose --rmi is refused with exit 3,
                       anything else execs REAL; result lines are appended to
                       REPORT

Environment:
    AGENTS_COUNCIL_ROOT, XDG_STATE_HOME, HOME: the shared state directory
        councilroot.py resolves, which survives a reboot and on which every
        agent on the host agrees. Every command creates
        it with mode 700; while it is a symlink, another uid's, or group or
        other writable, a hook mode prints why and exits 0 doing nothing and
        any other mode exits 2. queue.py and radio.py check it the same way.
    AGENTS_COUNCIL_CONFIG: config file; ~/.claude/agents-council/config.json
        unless set, a path the install denies to Claude Code's file tools and
        the sandbox's file rules do not let it write, because the hooks run
        its commands outside the sandbox; a Docker daemon the sandbox can
        reach still writes it. Without a config file every command exits 0 and does
        nothing; an unusable one makes every command warn and use
        ../config.default.json, cleanup and preflight exit 2.
    PATH: filtered to the directories hookpath.py trusts before any command
        runs, the config's commands included.

Config keys, all required: disk, thresholds_gb {warn, stop, critical},
projection_minutes, interval_seconds, cache_interval_seconds, heavy_commands,
never_block (regexes), cleanup (shell commands; a plain `docker image prune`
with nothing but -a, -f, --all, --force or --filter X never runs: the first
stands for the built-in step that lists the dangling images and removes,
without force, each whose repository and digest are both <none>, so tagged
images, pulls by digest and images a container uses stay; every other line
runs with the guard shims of docker and docker-compose first on PATH, which
turn each image prune into that step on the same daemon and refuse system
prune, rmi, image rm, image remove and compose --rmi; a line that would reach
docker past the shims, by a path in command position, a PATH reset or a
privilege switch, is refused and none of it runs; this guards operator-written
lines against accidents, and a computed docker path, a script resetting PATH
or the docker API socket are out of its scope),
worktree_cleanup (argv lists with {project}, run without a shell in /, so no
worktree file is read; `docker compose -p {project} exec -T <service> docker
image prune` with prune flags runs the leftover step inside that daemon, any
other entry naming an image removal is refused),
worktrees_command (shell command printing per running stack its worktree path
and compose project, tab-separated, one per line; a project that is not a
compose project name is skipped), worktree_marker (path relative
to a worktree that must exist), busy_processes (process names; a worktree
where one of them runs is skipped), cache_dirs, cache_budget_percent,
slot_need_gb {kind: GB}, notify (argv the alert text is appended to),
load_limits {cpu_percent, mem_percent, sample_seconds}: every admit and every
queue grant needs CPU busy and RAM used below them, memory_limits {warn:
{available, swap_free, psi_some, psi_full, swap_out_mb_min, container_swap_gb},
stop: the same without psi_some}: the memory stage is the first of stop and warn whose
MemAvailable or SwapFree percentage lies below its bound, whose
/proc/pressure/memory some or full avg10 reaches its bound, whose swap-out
rate (pswpout of /proc/vmstat since the newest reading in
<root>/swap-out.json SWAP_SPAN seconds old, in MB per minute) reaches its
bound, or where one container (a docker-*.scope cgroup under system.slice,
nested groups counted) holds at least container_swap_gb GB of swap, else ok;
a host without swap, PSI or such a reading skips that bound. heavy_commands
extend the built-in rules of heavy().
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import fcntl
import fnmatch
import functools
import importlib.util
import itertools
import json
import math
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import time
from collections.abc import Iterable
from pathlib import Path
from types import ModuleType
from typing import TextIO


def loaded(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"kvb_watch_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sibling(name: str) -> ModuleType:
    return loaded(name, Path(__file__).resolve().parent / f"{name}.py")


nofollow = sibling("nofollow")
hookpath = sibling("hookpath")
councilroot = sibling("councilroot")
popups = sibling("popups")
QUEUE = Path(__file__).resolve().parents[2] / "kvb-org-queue" / "scripts" / "queue.py"
ROOT = councilroot.root()
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
KEPT = councilroot.durable()
HISTORY = ROOT / "queue-history.jsonl"
KEPT_HISTORY = KEPT / "queue-history.jsonl"
ACCEPTED = ROOT / "security-accepted.jsonl"
KEPT_ACCEPTED = KEPT / "security-accepted.jsonl"
RECEIPTS = ROOT / "gate-receipts.jsonl"
KEPT_RECEIPTS = KEPT / "gate-receipts.jsonl"
PARENTS = ROOT / "gate-parents.jsonl"
KEPT_PARENTS = KEPT / "gate-parents.jsonl"
MIRRORED = (
    (HISTORY, KEPT_HISTORY), (ACCEPTED, KEPT_ACCEPTED), (RECEIPTS, KEPT_RECEIPTS), (PARENTS, KEPT_PARENTS),
)
ALERT_TTL = 3600
CHAIR = ROOT / "chair" / "claim.json"
MEMORY_SETTLE = 2
CLIP = 1000
CLEANUP_LOCK = "cleanup.lock"
LOCK_TTL = 1800
GB = 1e9
MEMINFO = Path("/proc/meminfo")
PRESSURE = Path("/proc/pressure/memory")
VMSTAT = Path("/proc/vmstat")
SWAP_OUT = ROOT / "swap-out.json"
SWAP_SPAN = (5, 900)
PAGE_BYTES = os.sysconf("SC_PAGE_SIZE")
MB = 1e6
CGROUPS = Path("/sys/fs/cgroup/system.slice")
SWAP_HOLDERS = 3
NEST_DEPTH = 8
MEMORY_STAGES = ("ok", "warn", "stop")
PRESSURES = {"warn": ("psi_some", "psi_full", "swap_out_mb_min"), "stop": ("psi_full", "swap_out_mb_min")}
MEMORY_KEYS = tuple(
    f"memory_limits.{stage}.{bound}"
    for stage in MEMORY_STAGES[1:] for bound in ("available", "swap_free", *PRESSURES[stage], "container_swap_gb")
)
CONTAINER_ID = re.compile(r"[0-9a-f]{64}")
COMPOSE_VALUES = frozenset({
    "-f", "--file", "-p", "--project-name", "--project-directory", "--env-file", "--profile", "--ansi", "--parallel",
    "--progress",
})
BUILDING = frozenset({"up", "run", "create"})
LEFTOVERS = ["images", "--filter", "dangling=true", "--format", "{{.ID}} {{.Repository}} {{.Digest}}"]
IMAGE_ID = re.compile(r"(?:sha256:)?[0-9a-f]{12,64}")
NONE = "<none>"
PRUNE_COMMANDS = (["image", "prune"], ["images", "prune"])
PRUNE_FLAG = re.compile(r"-[af]+|--force|--all|--filter=.+", re.DOTALL)
DOCKER_GLOBALS = frozenset({
    "-H", "--host", "-c", "--context", "--config", "-l", "--log-level", "--tlscacert", "--tlscert", "--tlskey",
})
SPARING = "a plain docker image prune removes the build leftovers and keeps them"
REMOVALS = {
    ("system", "prune"): f"docker system prune also removes digest-pinned images; {SPARING}",
    ("rmi",): f"docker rmi can remove digest-pinned images; {SPARING}",
    ("image", "rm"): f"docker image rm can remove digest-pinned images; {SPARING}",
    ("image", "remove"): f"docker image remove can remove digest-pinned images; {SPARING}",
}
COMPOSE_RMI = f"compose down --rmi removes the services' images, digest-pinned ones included; {SPARING}"
GUARDED_BINARIES = ("docker", "docker-compose")
INNER_REMOVAL = re.compile(r"\bdocker\b.*\b(?:images? (?:prune|rm|remove)|system prune|rmi)\b", re.DOTALL)
WORKTREE_REMOVAL = re.compile(r"\b(?:images? (?:prune|rm|remove)|system prune|rmi)\b")
QUOTING = re.compile(r"[\"'`\\]")
UNGUARDED = re.compile(r"\bPATH=|\bcommand\s+-p\b|\benv\b[^;&|\n]*\s(?:-i|--ignore-environment)\b")
PRIVILEGED = re.compile(r"\b(?:sudo|doas|su|pkexec|run0|systemd-run)\b")
IN_USE = re.compile(
    r"^Error response from daemon: conflict: unable to delete \S+ \((?:must|cannot) be forced\) - "
    r"image is being used by (?:running|stopped) container \S+$",
    re.MULTILINE,
)
OK, KEPT_LINE = "ok: ", "kept (in use): "
GUARD_REFUSED = 3
SHIM = '#!/bin/sh\nexec {python} -I {watch} guard {real} {report} "$@"\n'
REFUSALS = {
    "unguarded": (
        "docker run by a path, PATH=, env -i, command -p, sudo, doas, su, pkexec, run0 or systemd-run would "
        "bypass the docker guard; call docker by name"
    ),
    "nested": (
        "it would remove images in the worktree's daemon; only docker compose -p {project} exec -T <service> "
        "docker image prune [-a|--all] [-f|--force] [--filter X] is supported"
    ),
}
SEPARATOR = re.compile(r"[();<>|&\n]+")
PUNCTUATION = "();<>|&\n"
WORD_BREAK = " \t\n;&|()<>"
ASSIGNMENT = re.compile(r"[A-Za-z_]\w*=.*", re.DOTALL)
WRAPPERS = frozenset({
    "env", "sudo", "nice", "nohup", "timeout", "exec", "xargs", "stdbuf", "ionice", "uv", "uvx", "poetry", "pdm",
    "pipenv", "coverage", "time", "command", "npx", "pnpx", "bunx",
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
    "npx": frozenset({"-p", "--package", "-c", "--call"}),
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
PYTESTS = frozenset({"pytest", "py.test"})
TEST_FILE = re.compile(r"[^*?\[\]]+\.py(::.*)?", re.DOTALL)
E2E = ("tests", "e2e")
PLAYWRIGHT = "playwright"
BROWSER_MODULES = frozenset({
    "playwright", "pytest_playwright", "selenium", "webdriver", "@playwright", "playwright-core", "playwright-chromium",
    "playwright-firefox", "playwright-webkit", "puppeteer", "puppeteer-core", "selenium-webdriver", "webdriverio",
    "pyppeteer", "undetected_chromedriver", "puppeteer-extra", "cypress", "seleniumbase", "nodriver", "DrissionPage",
    "splinter", "helium", "camoufox", "nightwatch", "testcafe", "@wdio",
})
BROWSER_CLIS = frozenset({"playwright", "cypress", "nightwatch", "testcafe", "wdio"})
DYNAMIC_IMPORTS = frozenset({"import_module", "__import__"})
PLUGIN_LIST = "pytest_plugins"
REQUESTS = frozenset({"getfixturevalue", "usefixtures"})
INI_SECTIONS = {"pytest.ini": "pytest", "tox.ini": "pytest", "setup.cfg": "tool:pytest"}
LOAD_TESTS = frozenset({"load_tests", "*"})
FIXTURES = frozenset({
    "playwright", "browser_type", "browser_type_launch_args", "launch_browser", "browser", "browser_context_args",
    "context", "new_context", "page", "browser_name", "browser_channel", "is_chromium", "is_firefox", "is_webkit",
    "device", "connect_options", "output_path", "browser_context", "selenium",
})
FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
CONFIGS = ("pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini")
ADDOPTS = re.compile(r"addopts.*(?:-n\b|--numprocesses|--dist|-p\b|playwright)", re.IGNORECASE)
REACH_FILES = 2000
REACH_BYTES = 4 * 2**20
SHIPPED = Path(__file__).resolve().parents[1] / "config.default.json"
REFUSE_ALL = {"heavy_commands": [r"[\s\S]"], "never_block": [], "queue_enforce": True}
UNUSABLE = (OSError, ValueError, TypeError, RecursionError)
SCRIPT = re.compile(r"\.(?:py|[cm]?[jt]sx?)$")
JS_SCRIPT = re.compile(r"\.[cm]?[jt]sx?$")
JS_TOKEN = re.compile(r"//|/\*|['\"`]")
JS_IMPORTER = re.compile(r"(?:\bfrom|\bimport|\brequire\s*\(|\bimport\s*\()\s*$")
JS_TAIL = 64
SOURCE_BYTES = 1 << 20
JS_RUNNERS = frozenset({"node", "deno", "bun"})
JS_VALUE_OPTIONS = frozenset({"-r", "--require", "--import", "--loader", "-e", "--eval", "-p", "--print", "-c", "--config"})
NODE_CHECK = frozenset({"--check", "-c"})
PACKAGE_RUNNERS = frozenset({"npm", "pnpm", "yarn", "bun"})
FOLDER_OPTIONS = frozenset({"--cwd", "-C", "--dir", "--prefix"})
PACKAGE_OPTIONS = {
    runner: frozenset({"--filter", "-F", "--workspace", *(["-w"] if runner == "npm" else [])}) for runner in PACKAGE_RUNNERS
}
ALL_PACKAGES = frozenset({"-r", "--recursive", "--workspaces", "-ws"})
PACKAGE_COMMANDS = frozenset({
    "add", "install", "i", "ci", "remove", "rm", "uninstall", "upgrade", "update", "up", "init", "info", "view", "why",
    "list", "ls", "outdated", "audit", "config", "cache", "version", "help", "link", "unlink", "pack", "dedupe",
})
SCRIPT_PREFIX = re.compile(r"^(?:npm|yarn|pnpm|bun):")
RESOLVING: set[tuple[str, str]] = set()
RUN_WORDS = frozenset({"run", "run-script", "test", "t", "tst", "exec", "x", "dlx", "start"}) | BROWSER_CLIS
MAKES = frozenset({"make", "gmake"})
BACKGROUND = re.compile(r"(?<![&>|])&(?![&>])")
PYTEST_FLAGS = frozenset({
    "-q", "-qq", "-v", "-vv", "-vvv", "-x", "-s", "-l", "-ra", "-rA", "--quiet", "--verbose", "--exitfirst", "--no-header",
    "--showlocals", "--strict-markers",
})
PYTEST_VALUES = frozenset({"-k", "-m", "--tb", "-r", "--maxfail", "--durations", "--color"})
UNITTEST_FLAGS = frozenset({"-v", "-q", "-f", "-b", "-c", "--verbose", "--quiet", "--failfast", "--buffer", "--catch", "--locals"})
UNITTEST_VALUES = frozenset({"-k", "--durations"})
INERT_ENV = frozenset({
    "LANG", "LANGUAGE", "TZ", "NO_COLOR", "FORCE_COLOR", "TERM", "COLUMNS", "CARGO_BUILD_JOBS", "PYTHONDONTWRITEBYTECODE",
    "PYTHONUNBUFFERED",
})
LOCALE = "LC_"
EXPORTS = frozenset({"export", "declare", "typeset", "readonly", "local"})
CARGO_LIGHT = frozenset({"fmt", "metadata"})
CARGO_CAPPED = frozenset({"build", "check", "clippy", "test"})
CARGO_JOBS = 4
CARGO_JOB_FLAGS = re.compile(r"-j.*|--jobs.*", re.DOTALL)
FIND_EXEC = frozenset({"-exec", "-execdir", "-ok", "-okdir"})
LINTERS = frozenset({
    "ruff", "shellcheck", "markdownlint", "markdownlint-cli2", "lizard", "jq", "yamllint", "actionlint", "codespell",
})
INERT = frozenset({
    "grep", "egrep", "fgrep", "rg", "echo", "printf", "cat", "head", "tail", "wc", "ls", "sort", "uniq", "tee", "true",
    "which", "type", "kill", "pkill", "killall", "pgrep", "pidof", "find", "man", "readlink", "whereis", "ps", "stat",
    "file",
})
LIGHT_TOOLS = LINTERS | INERT
LIGHT_MODULES = frozenset({"py_compile", "json.tool"})
SAFE_PREFIXES = frozenset({"env", "nice", "ionice", "timeout", "time"})
DIRECTORY_CHANGES = frozenset({"cd", "pushd", "popd"})
KNOWN = INERT | DIRECTORY_CHANGES | frozenset({
    "git", "gh", "pip", "pip3", "pipx", "apt", "apt-get", "pacman", "brew", "dnf", "bash", "sh", "zsh", "dash",
})
HEAVY_MAKE = ("test", "quality", "verify-")
TEARDOWN_MAKE = "-down"
LIGHT_KIND = "test-nostack"
HEAVY_KIND = "test"
PYTEST_VALUE_OPTIONS = frozenset({
    "-p", "-k", "-m", "-c", "-o", "-W", "-n", "--numprocesses", "-r", "--maxfail", "--tb", "--rootdir", "--basetemp", "--deselect",
    "--ignore", "--ignore-glob", "--confcutdir", "--durations", "--junitxml", "--log-level", "--dist", "--cov",
    "--cov-report", "--cov-config", "--timeout", "--import-mode", "--capture", "--color", "--log-cli-level",
    "--log-file", "--reruns", "--tx", "--max-worker-restart",
})
UNITTEST_VALUE_OPTIONS = frozenset({"-k"})
DISCOVER_VALUE_OPTIONS = frozenset({"-s", "-p", "-t", "-k", "--start-directory", "--pattern", "--top-level-directory"})
PATTERN_OPTIONS = frozenset({"-p", "--pattern"})
START_OPTIONS = frozenset({"-s", "--start-directory"})
CHDIR_OPTIONS = frozenset({"-C", "--chdir"})
CHDIR_LONG = "--chdir="
MAKE_VALUE_OPTIONS = frozenset({
    "-C", "-f", "-I", "-o", "-W", "--directory", "--file", "--makefile", "--include-dir", "--old-file", "--assume-old",
    "--what-if", "--new-file", "--assume-new",
})


def guard_root(hook: bool) -> int | None:
    return councilroot.guard(ROOT, hook)


def load_config() -> dict | None:
    """Returns:
        The parsed config; None only when its path does not exist in any
        form.

    Raises:
        OSError: when the path exists but is no readable regular file (a
            dangling or looping link, a directory).
        ValueError: when it holds no JSON.
    """
    return read_regular(CONFIG) if os.path.lexists(CONFIG) else None


def read_regular(path: Path) -> object:
    if not path.is_file():
        raise OSError(f"{path} is no readable regular file")
    return json.loads(path.read_text(encoding="utf-8"))


def checked_config(cfg: object) -> dict:
    """Returns:
        cfg when it is a JSON object whose PATTERN_PROBES keys are lists of
        valid regexes none of which matches one of that key's probe commands,
        and whose queue_enforce, when set, is a bool.

    Raises:
        TypeError: naming the first part of the wrong type.
        ValueError: naming the first broken regex or one matching a probe.
    """
    if not isinstance(cfg, dict):
        raise TypeError("the config is no JSON object")
    for key, probes in PATTERN_PROBES.items():
        patterns = cfg.get(key)
        if not isinstance(patterns, list) or not all(isinstance(pattern, str) for pattern in patterns):
            raise TypeError(f"{key} is no list of regexes")
        for pattern in patterns:
            checked_pattern(key, pattern, probes)
    if not isinstance(cfg.get("queue_enforce", False), bool):
        raise TypeError("queue_enforce is no true or false")
    return cfg


def checked_pattern(key: str, pattern: str, probes: tuple[str, ...]) -> None:
    try:
        found = [probe for probe in probes if re.search(pattern, probe)]
    except re.error as error:
        raise ValueError(f"{key} holds the broken regex {pattern!r}: {error}") from error
    if found:
        raise ValueError(f"{key} holds {pattern!r}, which matches the probe command {found[0]!r}")


def settled_config() -> tuple[dict | None, str | None]:
    """Returns:
        The config and None; None and None without a config file (every
        command stays off); the SHIPPED config and one warning naming the
        file when it cannot be read or checked (checked_config());
        REFUSE_ALL, which counts every command heavy, when SHIPPED cannot be
        read or checked either.
    """
    try:
        cfg = load_config()
        return (None if cfg is None else checked_config(cfg)), None
    except UNUSABLE as error:
        problem = f"agents council: {CONFIG} is unusable ({error})"
    try:
        return checked_config(read_regular(SHIPPED)), (
            f"{problem}; the built-in defaults of {SHIPPED} apply until it is fixed: light commands pass, heavy ones are refused"
        )
    except UNUSABLE as error:
        return dict(REFUSE_ALL), f"{problem} and so is {SHIPPED} ({error}); every command is refused until one is fixed"


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


def alert(stage: str, text: str, chair_only: bool) -> None:
    """Args:
        stage: the stage the alert reports.
        text: what each session sees.
        chair_only: whether only the session holding the office chair sees it.
    """
    now = time.time_ns()
    cutoff = now - ALERT_TTL * 10**9
    row = json.dumps({"id": now, "stage": stage, "text": text, "chair": chair_only}) + "\n"
    try:
        ROOT.mkdir(parents=True, exist_ok=True)
        with open(nofollow.open_below(ROOT, ALERTS, os.O_RDWR | os.O_CREAT, 0o600), "r+", encoding="utf-8") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            kept = [line + "\n" for row_id, line in history_rows(handle.read()) if isinstance(row_id, int) and row_id > cutoff]
            handle.seek(0)
            handle.truncate()
            handle.write("".join(kept) + row)
    except OSError:
        pass


def seen_mark(path: Path) -> tuple[int, list[int] | None]:
    """Args:
        path: a session's seen marker: the id of the newest alert it saw and
            the [inode, size, mtime_ns] of alerts.jsonl at that read, or a
            bare id as older hooks wrote it.

    Returns:
        (id, file); 0 and None for a missing or unreadable marker.
    """
    try:
        mark = json.loads(nofollow.read_text(ROOT, path))
    except (OSError, ValueError, RecursionError):
        return 0, None
    if isinstance(mark, int):
        return mark, None
    if isinstance(mark, dict) and isinstance(mark.get("id"), int):
        return mark["id"], mark.get("file")
    return 0, None


def chairs(session: str) -> bool:
    try:
        claim = json.loads(nofollow.read_text(ROOT, CHAIR))
    except (OSError, ValueError, RecursionError):
        return False
    return isinstance(claim, dict) and claim.get("session") == session


def changed_alerts(marked: list[int] | None) -> tuple[list[int], str] | None:
    """Args:
        marked: the [inode, size, mtime_ns] of alerts.jsonl at the session's
            last read, or None.

    Returns:
        (its [inode, size, mtime_ns] now, its text), None while it is
        unreadable or still as marked.
    """
    try:
        with open(nofollow.open_below(ROOT, ALERTS, os.O_RDONLY, 0), "rb") as handle:
            info = os.fstat(handle.fileno())
            file = [info.st_ino, info.st_size, info.st_mtime_ns]
            if file == marked:
                return None
            return file, handle.read(nofollow.READ_LIMIT).decode("utf-8", errors="replace")
    except OSError:
        return None


def unseen_alerts(session: str) -> list[str]:
    seen_path = ROOT / "seen" / session
    seen, marked = seen_mark(seen_path)
    changed = changed_alerts(marked)
    if changed is None:
        return []
    file, text = changed
    fresh = fresh_alerts(text, max(seen, time.time_ns() - ALERT_TTL * 10**9))
    write_text(seen_path, json.dumps({"id": fresh[-1]["id"] if fresh else seen, "file": file}))
    shown = [a for a in fresh if a.get("chair") is not True or chairs(session)]
    return [clip(a["text"]) for a in shown]


def fresh_alerts(text: str, after: int) -> list[dict]:
    rows = [json.loads(line) for _, line in history_rows(text)]
    return [a for a in rows if isinstance(a["id"], int) and isinstance(a.get("text"), str) and a["id"] > after]


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
    if not popups.allowed(ROOT, "resources", time.time()):
        return
    try:
        subprocess.run([*cfg["notify"], text], capture_output=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        alert("critical", f"RESOURCE: desktop notification failed: {cfg['notify'][0]}", False)


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
        alert(stage, f"RESOURCE {stage.upper()}: recovered, {head}.", True)
        return
    if stage == "warn":
        alert(stage, f"RESOURCE WARN: {head}. Biggest consumers: {consumers()}. Chair: plan a cleanup; peers: request no large slot.", False)
    elif stage in ("stop", "critical"):
        alert(stage, f"RESOURCE {stage.upper()}: {head}. New heavy jobs are blocked; low-risk cleanup is running. {consumers()}", False)
        spawn_cleanup("--full")
        if stage == "critical":
            notify(cfg, f"Agents council: {head}. Heavy jobs blocked; a running stack needs the operator's OK to go.")


def act_memory(cfg: dict, stage: str, previous: str, sample: dict[str, float | None]) -> None:
    head = memory_text(sample)
    if MEMORY_STAGES.index(stage) < MEMORY_STAGES.index(previous):
        alert(stage, f"RESOURCE MEMORY {stage.upper()}: recovered, {head}.", True)
        return
    holders = "; ".join(swap_holders(CGROUPS, container_names())) or "no container holds swap"
    if stage == "warn":
        alert(stage, f"RESOURCE MEMORY WARN: {head}. Top swap holders: {holders}. Chair: find the holder; peers: start nothing heavy.", False)
    else:
        alert(stage, f"RESOURCE MEMORY STOP: {head}. New heavy jobs are blocked. Top swap holders: {holders}.", False)
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


def mirror_mark(target: Path) -> Path:
    return target.with_name(f".{target.name}.mirrored")


def whole_lines(data: bytes) -> tuple[str, int]:
    """Returns:
        The complete lines of data as text and their byte length; a line still
        being written stays for the next mirror.
    """
    end = data.rfind(b"\n") + 1
    return data[:end].decode("utf-8", errors="replace"), end


def keep_rows(origin: Path, target: Path) -> None:
    """Mirror the rows of origin into target.

    Args:
        origin: the agents' file below ROOT.
        target: its kept copy below KEPT. Its marker holds the source's
            [inode, offset] of the last mirror: the same inode at its marked
            size is skipped without reading the source, past that offset only
            the rows after it are appended, any other source merges every row
            whose id the copy lacks. An mtime match is no skip: a copy created
            or a row appended in the source's timestamp tick shares its mtime.
    """
    try:
        with open(nofollow.open_below(ROOT, origin, os.O_RDONLY, 0), "rb") as source:
            info = os.fstat(source.fileno())
            KEPT.mkdir(mode=0o700, parents=True, exist_ok=True)
            with open(nofollow.open_below(KEPT, target, os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o600), "a+", encoding="utf-8") as kept:
                own = os.fstat(kept.fileno())
                if (own.st_dev, own.st_ino) == (info.st_dev, info.st_ino):
                    return
                fcntl.flock(kept, fcntl.LOCK_EX | fcntl.LOCK_NB)
                offset = mirror_offset(target, info)
                if offset == info.st_size:
                    return
                source.seek(offset or 0)
                text, length = whole_lines(source.read(nofollow.READ_LIMIT))
                if offset is None:
                    merge_rows(kept, text)
                else:
                    kept.write("".join(line + "\n" for _, line in history_rows(text)))
                kept.flush()
                nofollow.replace(KEPT, mirror_mark(target), json.dumps([info.st_ino, (offset or 0) + length]), 0o600)
    except (OSError, ValueError, TypeError):
        pass


def mirror_offset(target: Path, info: os.stat_result) -> int | None:
    """Args:
        target: the kept copy.
        info: the source's stat.

    Returns:
        The source offset its tail starts at, None when the source has
        another inode or is shorter than marked and takes the full merge.
    """
    try:
        inode, offset = json.loads(nofollow.read_text(KEPT, mirror_mark(target)))
    except (OSError, ValueError, TypeError, RecursionError):
        return None
    return offset if inode == info.st_ino and isinstance(offset, int) and 0 <= offset <= info.st_size else None


def merge_rows(kept: TextIO, text: str) -> None:
    kept.seek(0)
    known = {row_id for row_id, _ in history_rows(kept.read())}
    for row_id, line in history_rows(text):
        if row_id not in known:
            known.add(row_id)
            kept.write(line + "\n")


def keep_history() -> None:
    for origin, target in MIRRORED:
        keep_rows(origin, target)


def stale(state: dict, cfg: dict, now: float) -> bool:
    return now - state.get("checked", 0) >= cfg["interval_seconds"]


def settled_memory(held: str, measured: str, below: int) -> tuple[str, int]:
    """Args:
        held: the memory stage the alerts last reported.
        measured: the stage of this sample.
        below: samples in a row so far that measured below held.

    Returns:
        (the stage to report, the new below count): a higher stage at once, a
        lower one only on the MEMORY_SETTLE-th sample in a row below held.
    """
    rank = MEMORY_STAGES.index
    if rank(measured) >= rank(held):
        return (measured, 0)
    below += 1
    return (measured, 0) if below >= MEMORY_SETTLE else (held, below)


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
        state["memory_stage"], state["memory_below"] = settled_memory(
            was_short, memory_stage(sample, cfg), state.get("memory_below", 0)
        )
    due =now - state.get("caches_checked", 0) >= cfg["cache_interval_seconds"]
    if due:
        state["caches_checked"] = now
    write_json(STATE, state)
    if stage != previous:
        act(cfg, stage, previous, free)
    elif due:
        spawn_cleanup("--caches")
    if sample is not None and state["memory_stage"] != was_short:
        act_memory(cfg, state["memory_stage"], was_short, sample)


def cmd_watch(cfg: dict, problem: str | None, unsettled: bool) -> int:
    """Args:
        cfg: the config.
        problem: why the memory stage cannot be judged, None when it can; the
            disk part still runs and every session sees the problem.
        unsettled: whether cfg stands in for an unusable config file
            (settled_config()); nothing is measured then, the alerts still reach the
            session and problem names the file.
    """
    payload = json.load(sys.stdin)
    now = time.time()
    state = read_json(STATE)
    if not unsettled and stale(state, cfg, now):
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


def python_target(args: list[str]) -> tuple[str, list[str]]:
    """Returns:
        The module of `python -m` or the script path as typed, and its
        arguments; ("", []) for code given with -c or for neither.
    """
    skip = False
    for at, word in enumerate(args):
        if skip:
            skip = False
        elif word == "-m":
            return (args[at + 1], args[at + 2 :]) if at + 1 < len(args) else ("", [])
        elif word.startswith("-m"):
            return word[2:], args[at + 1 :]
        elif INLINE.fullmatch(word):
            return "", []
        elif word in PYTHON_VALUE_OPTIONS:
            skip = True
        elif not word.startswith("-"):
            return word, args[at + 1 :]
    return "", []


def bare(word: str) -> str:
    """Returns:
        The program name of word: its basename, a scoped npm package as
        typed, an `@version` suffix dropped.
    """
    name = word if word.startswith("@") else os.path.basename(word)
    return name[:1] + name[1:].split("@", 1)[0]


def tool(run: list[str]) -> tuple[str, list[str]]:
    """Returns:
        The program's name (bare()) and arguments, the module and its
        arguments for `python -m` or a Python script.
    """
    name, args = bare(run[0]), run[1:]
    if not PYTHON.fullmatch(name):
        return name, args
    target, rest = python_target(args)
    return os.path.basename(target), rest


def node_check(run: list[str]) -> bool:
    """Returns:
        Whether run is `node --check FILE` or `node -c FILE`: node only
        parses the file and runs none of it.
    """
    return os.path.basename(run[0]) == "node" and len(run) == 3 and run[1] in NODE_CHECK and not run[2].startswith("-")


def launched(run: list[str]) -> str:
    """Returns:
        The script or `-m` module a python call starts, or the script of a
        node, deno or bun call (after a `run`); "" for none and for
        node_check().
    """
    if node_check(run):
        return ""
    name = os.path.basename(run[0])
    if PYTHON.fullmatch(name):
        return python_target(run[1:])[0]
    found = operands(run[1:], JS_VALUE_OPTIONS) if name in JS_RUNNERS else []
    if found[:1] == ["run"]:
        found = found[1:]
    return found[0] if found else ""


def discover_patterns(rest: list[str]) -> list[str]:
    """Returns:
        The file patterns `unittest discover` gets after `discover`: -p or
        --pattern values, else the second operand; empty for the default.
    """
    patterns = [rest[at + 1] for at, word in enumerate(rest[:-1]) if word in PATTERN_OPTIONS]
    return patterns or operands(rest, DISCOVER_VALUE_OPTIONS)[1:2]


def started_in(prefix: list[str], cwd: str | None) -> str | None:
    """Args:
        prefix: the words in front of a command's program.
        cwd: the directory the shell runs the command line in, None when
            unknown.

    Returns:
        The directory the command starts in: cwd joined with every `env
        -C|--chdir` value of prefix in order, each relative to the one
        before; None when cwd is None.
    """
    if cwd is None:
        return None
    dirs = [word[len(CHDIR_LONG):] if word.startswith(CHDIR_LONG) else prefix[at + 1]
            for at, word in enumerate(prefix)
            if word.startswith(CHDIR_LONG) or (word in CHDIR_OPTIONS and at + 1 < len(prefix))]
    return os.path.join(cwd, *dirs)


def one_discovered(rest: list[str], base: str | None) -> bool:
    return discovered_file(rest, base) is not None


def discover_start(rest: list[str]) -> str:
    """Returns:
        The start directory of `unittest discover` with these arguments: the
        last -s/--start-directory value, else the first operand, else `.`.
    """
    starts = [rest[at + 1] for at, word in enumerate(rest[:-1]) if word in START_OPTIONS]
    return (starts or operands(rest, DISCOVER_VALUE_OPTIONS)[:1] or ["."])[-1]

def discovered_file(rest: list[str], base: str | None) -> str | None:
    """Args:
        rest: the arguments after `unittest discover`.
        base: the directory the command starts in (started_in()), None when
            unknown.

    Returns:
        The one file below the start directory that matches the pattern, a
        plain name matching a file in every package of a tree counting as
        several; None for none or several. Without base or start directory
        the start directory joined with the pattern when that is one file
        name (TEST_FILE), so an unknown tree never blocks a single file.
    """
    patterns = discover_patterns(rest)
    if not patterns:
        return None
    start = discover_start(rest)
    if base is None or not os.path.isdir(os.path.join(base, start)):
        return os.path.join(start, patterns[-1]) if TEST_FILE.fullmatch(patterns[-1]) else None
    found = (os.path.join(top, name) for top, _, files in os.walk(os.path.join(base, start)) for name in files
             if fnmatch.fnmatchcase(name, patterns[-1]))
    first = [*itertools.islice(found, 2)]
    return first[0] if len(first) == 1 else None


def source(path: str) -> str | None:
    try:
        with open(os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC), "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                return None
            data = handle.read(SOURCE_BYTES + 1)
    except OSError:
        return None
    return None if len(data) > SOURCE_BYTES else data.decode("utf-8", "replace")


def parsed(path: str) -> ast.Module | None:
    text = source(path)
    try:
        return None if text is None else ast.parse(text)
    except (SyntaxError, ValueError, RecursionError):
        return None


def dynamic_import(node: ast.AST) -> str | None:
    """Returns:
        The literal module name an importlib.import_module or __import__
        call imports, else None.
    """
    if not isinstance(node, ast.Call) or not node.args:
        return None
    first = node.args[0]
    literal = isinstance(first, ast.Constant) and isinstance(first.value, str)
    return first.value if call_name(node) in DYNAMIC_IMPORTS and literal else None


def call_name(node: ast.Call) -> str:
    return node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")


def strings(node: ast.AST) -> list[str]:
    return [found.value for found in ast.walk(node) if isinstance(found, ast.Constant) and isinstance(found.value, str)]


def plugin_names(tree: ast.Module) -> list[str]:
    """Returns:
        The module names a top-level pytest_plugins assignment of tree
        lists.
    """
    return [name for node in tree.body if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == PLUGIN_LIST for target in node.targets)
            for name in strings(node.value)]


def import_refs(tree: ast.Module) -> list[tuple[str, int]]:
    """Returns:
        (module, level) per module tree imports: Import nodes, ImportFrom
        nodes with each imported name also as a submodule,
        dynamic_import() calls and pytest_plugins entries (plugin_names()).
    """
    refs: list[tuple[str, int]] = [(name, 0) for name in plugin_names(tree)]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            refs += [(alias.name, 0) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            refs += [(".".join(filter(None, (node.module, alias.name))), node.level) for alias in node.names]
            refs.append((node.module or "", node.level))
        elif (name := dynamic_import(node)) is not None:
            refs.append((name, 0))
    return refs


def ancestors(path: str) -> list[Path]:
    """Returns:
        The directories from the one holding path up to the repository
        root: the first holding .git or a pytest config (CONFIGS), else the
        filesystem root.
    """
    found = []
    for folder in Path(os.path.abspath(path)).parents:
        found.append(folder)
        if any((folder / name).exists() for name in (".git", *CONFIGS)):
            break
    return found


def browser_module(name: str) -> bool:
    """Returns:
        Whether an imported module or package specifier is a browser driver
        (BROWSER_MODULES) by its top-level name or npm scope:
        `playwright.sync_api` and `@playwright/experimental-ct-react` count,
        `playwright_report` does not.
    """
    return re.split(r"[./]", name)[0] in BROWSER_MODULES


def file_bytes(path: str) -> int:
    try:
        return os.stat(path).st_size
    except OSError:
        return REACH_BYTES + 1


@functools.cache
def module_refs(path: str) -> tuple[tuple[str, int], ...] | None:
    tree = parsed(path)
    return None if tree is None else tuple(import_refs(tree))


@functools.cache
def rooted_files(module: str, roots: tuple[str, ...]) -> frozenset[str]:
    """Returns:
        The module files and package __init__.py files below roots that
        importing module runs; below a root the look stops at the first
        part that is no folder.
    """
    parts = module.split(".") if module else []
    found: set[str] = set()
    for folder in roots:
        prefix = folder
        for part in parts:
            prefix = os.path.join(prefix, part)
            files, deeper = module_files(prefix)
            found |= files
            if not deeper:
                break
    return frozenset(found)


@functools.cache
def module_files(prefix: str) -> tuple[frozenset[str], bool]:
    """Returns:
        prefix.py and prefix/__init__.py where they are files, and whether
        prefix is a folder a deeper module part can lie in.
    """
    files = frozenset(path for path in (prefix + ".py", os.path.join(prefix, "__init__.py")) if os.path.isfile(path))
    return files, os.path.isdir(prefix)


def local_files(ref: tuple[str, int], here: str, roots: tuple[str, ...]) -> frozenset[str]:
    """Returns:
        rooted_files() of the module of ref below roots, for a relative
        import below here moved up level - 1 directories.
    """
    module, level = ref
    return rooted_files(module, (os.path.normpath(os.path.join(here, *[".."] * (level - 1))),) if level else roots)


def imports_reach(seeds: list[str], roots: list[str]) -> bool:
    """Returns:
        Whether a seed file or a local module they import (local_files(),
        recursively) imports a browser driver (browser_module()); a file
        that cannot be read or parsed (over SOURCE_BYTES too) or a walk past
        REACH_FILES files or REACH_BYTES bytes counts as one.
    """
    seen, todo, bases, spent = set(seeds), list(seeds), tuple(roots), 0
    while todo:
        current = todo.pop()
        spent += file_bytes(current)
        if len(seen) > REACH_FILES or spent > REACH_BYTES:
            return True
        refs = module_refs(current)
        if refs is None or any(browser_module(module) for module, _ in refs):
            return True
        found = {path for ref in refs for path in local_files(ref, os.path.dirname(current), bases)} - seen
        seen |= found
        todo += sorted(found)
    return False


def top_names(tree: ast.Module) -> set[str]:
    """Returns:
        The names a module binds at its top: functions, assigned names and
        names from ImportFrom (`*` for a star import).
    """
    names = {node.name for node in tree.body if isinstance(node, FUNCTIONS)}
    names |= {target.id for node in tree.body if isinstance(node, ast.Assign) for target in node.targets
              if isinstance(target, ast.Name)}
    return names | imported_names(tree)


def imported_names(tree: ast.Module) -> set[str]:
    return {alias.asname or alias.name for node in tree.body if isinstance(node, ast.ImportFrom) for alias in node.names}


def parameters(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    return {arg.arg for arg in [*node.args.args, *node.args.kwonlyargs]}


def asked_fixtures(tree: ast.Module) -> set[str]:
    """Returns:
        The fixtures a test module asks for: the parameters of its test
        functions and the strings its getfixturevalue and usefixtures calls
        name.
    """
    asked = {name for node in ast.walk(tree) if isinstance(node, FUNCTIONS) and node.name.startswith("test")
             for name in parameters(node)}
    return asked | requested_fixtures(tree)


def requested_fixtures(tree: ast.Module) -> set[str]:
    """Returns:
        The fixture names the getfixturevalue and usefixtures calls of tree
        request; all FIXTURES when an argument is no string literal (a
        built name such as `'pa' + 'ge'`).
    """
    arguments = [argument for node in ast.walk(tree) if isinstance(node, ast.Call) and call_name(node) in REQUESTS
                 for argument in node.args]
    literal = {argument.value for argument in arguments
               if isinstance(argument, ast.Constant) and isinstance(argument.value, str)}
    return literal | (FIXTURES if any(not isinstance(argument, ast.Constant) for argument in arguments) else set())


def builds_on_browser(tree: ast.Module) -> bool:
    return any(parameters(node) & FIXTURES for node in ast.walk(tree) if isinstance(node, FUNCTIONS))


def browser_fixtures(trees: list[ast.Module]) -> set[str]:
    """Returns:
        FIXTURES and every function of trees whose parameters reach one of
        them, transitively: a fixture built on page, browser or context.
    """
    params = [(node.name, parameters(node)) for tree in trees for node in ast.walk(tree) if isinstance(node, FUNCTIONS)]
    found, size = set(FIXTURES), 0
    while size != len(found):
        size = len(found)
        found |= {name for name, args in params if args & found}
    return found


def own_risk(tree: ast.Module, conftests: list[ast.Module]) -> bool:
    """Returns:
        Whether a test module defines or imports load_tests (a star import
        too), or a test function asks for a browser fixture
        (browser_fixtures() of the module and its conftest files).
    """
    return bool(LOAD_TESTS & top_names(tree) or browser_fixtures([tree, *conftests]) & asked_fixtures(tree))


def context_risk(folders: list[Path], conftests: list[str]) -> bool:
    """Returns:
        Whether a conftest.py names playwright or cannot be read, or a
        pytest config in folders adds workers, plugins or playwright to
        addopts (ADDOPTS).
    """
    configs = [source(str(folder / name)) or "" for folder in folders for name in CONFIGS]
    named = any(PLAYWRIGHT in (source(conftest) or PLAYWRIGHT).lower() for conftest in conftests)
    return named or any(ADDOPTS.search(text) for text in configs)


def pythonpath_entries(config: Path) -> list[str]:
    """Returns:
        The directories the pytest `pythonpath` setting of one config file
        (CONFIGS) lists, as written; none when it has none or does not
        parse.
    """
    text = source(str(config))
    if text is None:
        return []
    import configparser
    import tomllib

    try:
        if config.name == "pyproject.toml":
            value = tomllib.loads(text).get("tool", {}).get("pytest", {}).get("ini_options", {}).get("pythonpath", [])
            return [value] if isinstance(value, str) else [entry for entry in value if isinstance(entry, str)]
        parser = configparser.ConfigParser(interpolation=None)
        parser.read_string(text)
        return parser.get(INI_SECTIONS[config.name], "pythonpath", fallback="").split()
    except (tomllib.TOMLDecodeError, configparser.Error, AttributeError, TypeError):
        return []


def search_roots(folders: list[Path]) -> list[str]:
    """Returns:
        Where a test's imports resolve: the directories from the test up to
        the repository root and every pytest `pythonpath` entry of a config
        there, relative to that config.
    """
    added = [os.path.normpath(folder / entry) for folder in folders for name in CONFIGS
             for entry in pythonpath_entries(folder / name)]
    return [str(folder) for folder in folders] + added


def context_files(tree: ast.Module, conftests: list[str], roots: list[str]) -> list[str]:
    """Returns:
        The conftest files and the local modules the pytest_plugins of the
        test module or of those conftest files name (plugin_names()).
    """
    trees = [tree, *(found for found in map(parsed, conftests) if found is not None)]
    named = {path for found in trees for name in plugin_names(found) for path in rooted_files(name, tuple(roots))}
    return [*conftests, *sorted(named - set(conftests))]


def runner_reach(path: str) -> bool:
    """Returns:
        Whether a test runner running the Python file at path runs more
        than one light test file. The context of a test is every conftest.py
        from its directory up to the repository root (ancestors()) and every
        module their pytest_plugins name (context_files()); the file is heavy
        when it does not parse, own_risk(), context_risk(), a context file
        does not parse or builds a fixture on page, browser or context
        (builds_on_browser(), autouse ones too), or imports_reach() from the
        file and its context through search_roots().
    """
    tree = parsed(path)
    if tree is None:
        return True
    folders = ancestors(path)
    roots = search_roots(folders)
    conftests = [str(folder / "conftest.py") for folder in folders if (folder / "conftest.py").exists()]
    context = context_files(tree, conftests, roots)
    if context_heavy(tree, context) or context_risk(folders, conftests):
        return True
    return imports_reach([path, *context], roots)


def context_heavy(tree: ast.Module, context: list[str]) -> bool:
    """Returns:
        Whether a context file (context_files()) does not parse, builds a
        fixture on a browser fixture (builds_on_browser()) or requests one
        by name (requested_fixtures()), autouse ones too, or the test module
        is own_risk() with those files.
    """
    trees = [parsed(found) for found in context]
    if any(found is None or builds_on_browser(found) for found in trees):
        return True
    browser = browser_fixtures([tree, *trees])
    return own_risk(tree, trees) or any(requested_fixtures(found) & browser for found in trees)


def reached(path: str, runner: bool) -> bool:
    """Returns:
        For a Python file runner_reach() when a test runner runs it, else
        imports_reach() from it alone; playwright_file() for other files,
        where an unreadable one counts as reached.
    """
    if not path.endswith(".py"):
        return playwright_file(path) is not False
    return runner_reach(path) if runner else imports_reach([path], [str(folder) for folder in ancestors(path)])


def string_end(text: str, start: int) -> int:
    quote, at = text[start], start + 1
    while at < len(text) and text[at] != quote:
        at += 2 if text[at] == "\\" else 1
    return at


def js_imports(text: str) -> list[str]:
    """Returns:
        The string literals of text that follow `from`, `import`, `require(`
        or `import(` in code; comments and every other string are skipped.
    """
    found: list[str] = []
    tail, at = "", 0
    while (match := JS_TOKEN.search(text, at)) is not None:
        tail = (tail + text[at : match.start()])[-JS_TAIL:]
        if match.group() == "//":
            end = text.find("\n", match.end())
            at = len(text) if end < 0 else end
        elif match.group() == "/*":
            end = text.find("*/", match.end())
            at = len(text) if end < 0 else end + 2
        else:
            end = string_end(text, match.start())
            if JS_IMPORTER.search(tail):
                found.append(text[match.start() + 1 : end])
            tail, at = tail + " ", end + 1
    return found


def playwright_file(path: str) -> bool | None:
    """Returns:
        Whether the Python (module_refs()) or JavaScript/TypeScript
        (js_imports()) file at path itself imports a browser driver
        (browser_module()); None when it cannot be read as a regular file
        or, for Python, parsed.
    """
    if JS_SCRIPT.search(path):
        text = source(path)
        names = None if text is None else js_imports(text)
    else:
        refs = module_refs(path)
        names = None if refs is None else [module for module, _ in refs]
    return None if names is None else any(browser_module(name) for name in names)


def named_parts(test: str) -> tuple[str, list[str] | None]:
    """Returns:
        The file or module part of a test name (a pytest node id loses
        `::...`) and its dotted parts when it is a module, else None.
    """
    name = test.split("::", 1)[0]
    return name, name.split(".") if not SCRIPT.search(name) and os.sep not in name else None


def test_file(test: str, base: str | None) -> str | None:
    """Returns:
        The regular file a test name runs, relative to base: the path, or
        the first dotted prefix that is a .py file; None when there is none
        or neither base nor an absolute path places it.
    """
    name, module = named_parts(os.path.expanduser(test))
    paths = [os.path.join(*module[:end]) + ".py" for end in range(1, len(module) + 1)] if module else [name]
    found = [
        os.path.join(base or "", path) for path in paths
        if (base is not None or os.path.isabs(path)) and os.path.isfile(os.path.join(base or "", path))
    ]
    return found[0] if found else None


def e2e_path(test: str, base: str | None) -> bool:
    name, module = named_parts(test)
    named = Path(*(module or [name])).parts
    parts = Path(os.path.join(base or "", *named)).parts
    return E2E[1] in named[:-1] or any(parts[at : at + 2] == E2E for at in range(len(parts)))


def browser_test(test: str, base: str | None, runner: bool) -> bool:
    """Args:
        test: a test file or script, a pytest node id (`file::name`) or a
            dotted module name.
        base: the directory the command starts in, None when unknown.
        runner: whether a test runner runs it (reached()).

    Returns:
        Whether it lies under a tests/e2e/ directory, passes an e2e
        directory itself, or its file (test_file()) reaches playwright or
        more tests (reached()).
    """
    found = test_file(test, base)
    return e2e_path(test, base) or (found is not None and reached(found, runner))


def clean_test(test: str, base: str | None) -> bool:
    found = test_file(test, base)
    return found is not None and not e2e_path(test, base) and not reached(found, True)


def light_unittest(args: list[str], base: str | None) -> bool:
    if args[:1] == ["discover"]:
        found = discovered_file(args[1:], base)
    else:
        named = operands(args, UNITTEST_VALUE_OPTIONS)
        found = named[0] if len(named) == 1 else None
    return found is not None and not browser_test(found, base, True)


def heavy_pytest(args: list[str], base: str | None) -> bool:
    files = operands(args, PYTEST_VALUE_OPTIONS)
    if PYTEST_LIGHT.intersection(args):
        return False
    return not (len(files) == 1 and TEST_FILE.fullmatch(files[0])) or browser_test(files[0], base, True)


def plain_operands(args: list[str], flags: frozenset[str], values: frozenset[str]) -> list[str] | None:
    """Returns:
        The operands of args when each option is one of flags or values (a
        value option with its value, also as --option=value), else None.
    """
    found, skip = [], False
    for word in args:
        if skip:
            skip = False
        elif not word.startswith("-"):
            found.append(word)
        elif word.split("=", 1)[0] in values:
            skip = "=" not in word
        elif word not in flags:
            return None
    return found


def single_pytest(args: list[str], base: str | None) -> bool:
    """Returns:
        Whether pytest runs help, collects with plain options only, or runs
        exactly one clean test file (clean_test()) with plain options only
        (PYTEST_FLAGS, PYTEST_VALUES).
    """
    files = plain_operands(args, PYTEST_FLAGS | PYTEST_LIGHT, PYTEST_VALUES)
    if HELP.intersection(args) or (files is not None and PYTEST_LIGHT.intersection(args)):
        return True
    return files is not None and len(files) == 1 and bool(TEST_FILE.fullmatch(files[0])) and clean_test(files[0], base)


def single_unittest(args: list[str], base: str | None) -> bool:
    """Returns:
        Whether unittest runs help, or exactly one clean test file or module
        (clean_test()) with plain options only (UNITTEST_FLAGS,
        UNITTEST_VALUES) and without discovery.
    """
    named = plain_operands(args, UNITTEST_FLAGS, UNITTEST_VALUES)
    if HELP.intersection(args):
        return True
    return named is not None and args[:1] != ["discover"] and len(named) == 1 and clean_test(named[0], base)


def light_test(name: str, args: list[str], base: str | None) -> bool:
    """Returns:
        Whether pytest or unittest runs a light form (single_pytest(),
        single_unittest()).
    """
    if name in PYTESTS:
        return single_pytest(args, base)
    return name == "unittest" and single_unittest(args, base)


def heavy_unittest(args: list[str], base: str | None) -> bool:
    return not (HELP.intersection(args) or light_unittest(args, base))


def make_targets(args: list[str]) -> list[str]:
    return [word for word in operands(args, MAKE_VALUE_OPTIONS) if "=" not in word and not word.isdigit()]


def dry_run(args: list[str]) -> bool:
    return bool(DRY_RUN.intersection(args)) or any(SHORT_DRY.fullmatch(word) for word in args)


def heavy_make(args: list[str]) -> bool:
    targets = make_targets(args)
    return not dry_run(args) and (not targets or any(
        target == "install" or (target.startswith(HEAVY_MAKE) and not target.endswith(TEARDOWN_MAKE)) for target in targets
    ))


def heavy_compose(args: list[str]) -> bool:
    words = operands(args, COMPOSE_VALUES)
    command = words[0] if words else ""
    return command == "build" or (command in BUILDING and "--build" in args)


def heavy_docker(args: list[str]) -> bool:
    return args[:1] == ["compose"] and heavy_compose(args[1:])


def heavy_runner(args: list[str]) -> bool:
    return not HELP.intersection(args)


def heavy_test_word(args: list[str]) -> bool:
    return operands(args, frozenset())[:1] == ["test"]


def package_call(runner: str, args: list[str]) -> tuple[list[str], list[str], bool, list[str]]:
    """Args:
        runner: npm, pnpm, yarn or bun.
        args: the words after it.

    Returns:
        The folders FOLDER_OPTIONS name, the packages PACKAGE_OPTIONS or
        `yarn workspace NAME` name, whether ALL_PACKAGES or `yarn
        workspaces` asks for every package, and the words from the first
        operand on; options before it and their values are skipped.
    """
    folders: list[str] = []
    packages: list[str] = []
    every, rest, words = False, [], iter(args)
    for word in words:
        option, equals, value = word.partition("=")
        if rest or not word.startswith("-"):
            rest.append(word)
        elif option in FOLDER_OPTIONS or option in PACKAGE_OPTIONS[runner]:
            (folders if option in FOLDER_OPTIONS else packages).append(value if equals else next(words, ""))
        else:
            every = every or word in ALL_PACKAGES
    return workspace_call(folders, packages, every, rest)


def workspace_call(folders: list[str], packages: list[str], every: bool,
                   rest: list[str]) -> tuple[list[str], list[str], bool, list[str]]:
    if rest[:1] == ["workspace"]:
        return folders, [*packages, *rest[1:2]], every, rest[2:]
    return folders, packages, every or rest[:1] == ["workspaces"], rest


def heavy_packages(runner: str, args: list[str]) -> bool:
    found = package_call(runner, args)[3]
    return bool(found) and found[0] in RUN_WORDS


def heavy_node(args: list[str]) -> bool:
    return "--test" in args


HEAVY_TOOLS = {
    "make": heavy_make, "gmake": heavy_make, "docker": heavy_docker, "docker-compose": heavy_compose, "tox": heavy_runner,
    "nox": heavy_runner, "hatch": heavy_test_word, "deno": heavy_test_word, "@playwright/test": heavy_runner,
    "cargo": heavy_runner, "node": heavy_node,
    **dict.fromkeys(BROWSER_CLIS, heavy_runner),
    **{runner: functools.partial(heavy_packages, runner) for runner in PACKAGE_RUNNERS},
}
OWN_RULE = KNOWN | PYTESTS | JS_RUNNERS | (HEAVY_TOOLS.keys() - {"docker", "docker-compose"})
TRIGGERS = PYTESTS | JS_RUNNERS | HEAVY_TOOLS.keys() | WRAPPERS | SHELLS
HEAVY_TARGETS = (
    "test", "test-unit", "test-integration", "quality", "quality-high", "verify-x", "compose-deploy", "compose-up",
    "compose-playwright", "roundtrip", "swarm-deploy", "act-workflow", "act-runner-image", "build", "worktree-up", "store-up",
)
PATTERN_PROBES = {
    "heavy_commands": (
        "", "true", "git status", "ruff check .", "python3 -m pytest tests/test_x.py", "cat a/b.md", f"cat {'a/' * 150}b.md",
        *sorted(LIGHT_TOOLS), *(f"{tool} -n x a/b.md" for tool in sorted(LIGHT_TOOLS)),
    ),
    "never_block": (
        "", "pytest tests/", "pytest a.py b.py", "python3 -m pytest", "python3 -m unittest", "npx playwright test",
        "docker build .", "docker buildx build .", "docker compose build", "docker pull nginx", "docker load -i x.tar",
        "bash scripts/run.sh local", "npm run e2e", "pnpm exec cypress run",
        *(f"{tool} run" for tool in sorted(HEAVY_TOOLS)), *(f"make {target}" for target in HEAVY_TARGETS),
    ),
}


def package_scripts(base: str | None) -> tuple[str | None, dict]:
    """Returns:
        The folder of the package.json nearest above base (ancestors()) and
        its scripts, {} when they are no object; base and {} without one.
    """
    for folder in ancestors(os.path.join(base, "package.json")) if base else []:
        text = source(str(folder / "package.json"))
        if text is None:
            continue
        try:
            scripts = json.loads(text).get("scripts")
        except (ValueError, AttributeError):
            scripts = None
        return str(folder), scripts if isinstance(scripts, dict) else {}
    return base, {}


def heavy_tool(name: str, args: list[str], cfg: dict, exempt: tuple[str, ...], base: str | None) -> bool:
    """Returns:
        HEAVY_TOOLS' rule for name, for a package runner also
        heavy_script_call().
    """
    if name in HEAVY_TOOLS and HEAVY_TOOLS[name](args):
        return True
    return name in PACKAGE_RUNNERS and heavy_script_call(name, args, cfg, exempt, base)


def heavy_script_call(runner: str, args: list[str], cfg: dict, exempt: tuple[str, ...], base: str | None) -> bool:
    """Returns:
        Whether the package script a package-runner call names is heavy
        (scripts_heavy()) in the folder its options lead to from base; a
        PACKAGE_COMMANDS word such as add or install is no script. Without
        base, for every package or for a named package without a folder of
        that name it counts heavy.
    """
    folders, packages, every, rest = package_call(runner, args)
    if not rest or rest[0] in PACKAGE_COMMANDS:
        return False
    if base is None or every:
        return True
    folder = os.path.join(base, *folders, *packages[-1:])
    if packages and not os.path.isfile(os.path.join(folder, "package.json")):
        return True
    root, scripts = package_scripts(folder)
    return scripts_heavy(scripts, rest[0], root or folder, cfg, exempt)


def scripts_heavy(scripts: dict, name: str, folder: str, cfg: dict, exempt: tuple[str, ...]) -> bool:
    """Returns:
        Whether script name or its pre or post script is heavy
        (script_heavy()).
    """
    return any(script_heavy(scripts, found, folder, cfg, exempt) for found in (f"pre{name}", name, f"post{name}")
               if isinstance(scripts.get(found), str))


def script_heavy(scripts: dict, name: str, folder: str, cfg: dict, exempt: tuple[str, ...]) -> bool:
    """Returns:
        Whether the body of script name is heavy() in folder, or a quoted
        command in it (`concurrently "cypress run"`) or a script it names
        (`start-server-and-test dev URL cy:run`, `npm:dev`) is; a script
        reached again through a runner call while it is judged, a loop,
        counts heavy.
    """
    if (folder, name) in RESOLVING:
        return True
    RESOLVING.add((folder, name))
    try:
        return body_heavy(scripts, scripts[name], folder, cfg, exempt)
    finally:
        RESOLVING.discard((folder, name))


def body_heavy(scripts: dict, body: str, folder: str, cfg: dict, exempt: tuple[str, ...]) -> bool:
    words = body_words(body)
    named = {SCRIPT_PREFIX.sub("", word) for word in words} & scripts.keys()
    return (heavy(body, cfg, exempt, folder) or any(heavy(word, cfg, exempt, folder) for word in words if SPACE.search(word))
            or any(scripts_heavy(scripts, found, folder, cfg, exempt) for found in named if (folder, found) not in RESOLVING))


def body_words(body: str) -> list[str]:
    try:
        return [word for part in segments(body) for word in part]
    except ValueError:
        return []


def heavy_words(run: list[str], cfg: dict, exempt: tuple[str, ...], base: str | None) -> bool:
    """Args:
        base: the directory the command starts in (started_in()), None when
            unknown.
    """
    if not run:
        return False
    code = inline_code(run)
    if code is not None:
        return heavy(code, cfg, exempt, base)
    name, args = tool(run)
    if PYTHON.fullmatch(os.path.basename(run[0])) and name in WRAPPERS:
        return heavy_words(program([name, *args]), cfg, exempt, base)
    if name == "unittest":
        return heavy_unittest(args, base)
    if name in PYTESTS:
        return heavy_pytest(args, base)
    script = launched(run)
    if script and browser_test(script, base, False):
        return True
    return heavy_tool(name, args, cfg, exempt, base)


def segment_texts(words: list[str], run: list[str]) -> list[str]:
    return list(dict.fromkeys(" ".join("''" if SPACE.search(word) else word for word in part) for part in (words, run)))


def judged(texts: list[str], run: list[str], cfg: dict, exempt: tuple[str, ...], base: str | None) -> bool:
    if any(re.search(pattern, text) for pattern in exempt for text in texts):
        return False
    if any(re.search(pattern, text) for pattern in cfg["heavy_commands"] for text in texts):
        return True
    return heavy_words(run, cfg, exempt, base)


def inner_start(run: list[str]) -> int | None:
    """Returns:
        For a program without a rule of its own (not OWN_RULE, docker
        included), the first later word naming a runner, wrapper or shell
        (TRIGGERS, python): what an unknown wrapper such as systemd-run,
        taskset or xvfb-run may start, or the command after a find -exec,
        -execdir, -ok or -okdir; None otherwise.
    """
    if run and bare(run[0]) == "find":
        return find_exec(run)
    if not run or bare(run[0]) in OWN_RULE or PYTHON.fullmatch(bare(run[0])):
        return None
    return next((at for at in range(1, len(run)) if bare(run[at]) in TRIGGERS or PYTHON.fullmatch(bare(run[at]))), None)


def find_exec(run: list[str]) -> int | None:
    return next((at + 1 for at, word in enumerate(run[:-1]) if word in FIND_EXEC), None)


def heavy_targets(args: list[str], cfg: dict, exempt: tuple[str, ...], base: str | None) -> bool:
    """Returns:
        Whether a make call with these arguments is heavy, judged per target
        as `make <target>` and without a target as `make`.
    """
    calls = [["make", target] for target in make_targets(args)] or [["make"]]
    return any(judged([" ".join(call)], call, cfg, exempt, base) for call in calls)


def exempted(words: list[str], run: list[str], exempt: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text) for pattern in exempt for text in segment_texts(words, run))


def assignments(words: list[str]) -> dict[str, str]:
    """Returns:
        The variables a simple command sets: VAR=value words in front of
        its program (program()), after export or declare, or anywhere when
        the program is no tail of the words (env -S).
    """
    run = program(words)
    tail = bool(run) and words[len(words) - len(run) :] == run
    prefix = words[1:] if words[:1] and words[0] in EXPORTS else words[: len(words) - len(run)] if tail else words
    return dict(word.split("=", 1) for word in prefix if ASSIGNMENT.fullmatch(word))


def stirring(names: Iterable[str]) -> bool:
    """Returns:
        Whether one of the variables can change what a command runs: any
        outside INERT_ENV and the LC_* locale.
    """
    return any(name not in INERT_ENV and not name.startswith(LOCALE) for name in names)


def cargo_allowed(run: list[str], names: dict[str, str]) -> bool:
    """Returns:
        Whether a cargo call needs no queue: help, version, fmt or metadata,
        or build, check, clippy or test with CARGO_BUILD_JOBS between 1 and
        CARGO_JOBS set in front and no -j or --jobs.
    """
    args = run[1:]
    found = [word for word in operands(args, frozenset()) if not word.startswith("+")]
    command = found[0] if found else ""
    jobs = names.get("CARGO_BUILD_JOBS", "")
    capped = jobs.isdecimal() and 1 <= int(jobs) <= CARGO_JOBS and not any(CARGO_JOB_FLAGS.fullmatch(word) for word in args)
    return bool(HELP.intersection(args)) or command in CARGO_LIGHT or (command in CARGO_CAPPED and capped)


def runs_tests(run: list[str]) -> bool:
    """Returns:
        Whether a simple command starts pytest, unittest or cargo, also
        behind a program without a rule of its own (inner_start()).
    """
    while run:
        if tool(run)[0] in PYTESTS | {"unittest"} or bare(run[0]) == "cargo":
            return True
        at = inner_start(run)
        run = run[at:] if at is not None else []
    return False


def test_runs(command: str, exempt: tuple[str, ...]) -> int:
    """Returns:
        How many simple commands of command, the code of its `sh -c` calls
        and substitutions included, start tests (runs_tests()), exempt ones
        aside; 2 for an unbalanced quote.
    """
    plain, codes = substituted(uncommented(marked_heredocs(command)[0]))
    try:
        parts = [words for words in segments(plain) if words]
    except ValueError:
        return 2
    count = sum(test_runs(code, exempt) for code in codes)
    for words in parts:
        run = program(words)
        if run and not exempted(words, run, exempt):
            code = inline_code(run)
            count += test_runs(code, exempt) if code is not None else int(runs_tests(run))
    return count


def unparsed_heavy(command: str, cfg: dict, exempt: tuple[str, ...]) -> bool:
    text = executable_text(command)
    return not any(re.search(p, text) for p in exempt) and any(re.search(p, text) for p in cfg["heavy_commands"])


def crowded(command: str, parts: list[list[str]], exempt: tuple[str, ...]) -> bool:
    """Returns:
        Whether command starts two test runs (test_runs()), or one beside
        an assignment of its simple commands parts that can change it
        (stirring()).
    """
    runs = test_runs(command, exempt)
    return runs > 1 or (runs == 1 and stirring(name for words in parts for name in assignments(words)))


def heavy_part(words: list[str], cfg: dict, exempt: tuple[str, ...], cwd: str | None) -> bool:
    """Returns:
        Whether one simple command is heavy; a make or gmake call is judged
        per target as `make <target>`, so an exempt target never covers the
        next one, and without a target as `make`; a cargo_allowed() call is
        light; behind a program without a rule of its own the command from
        inner_start() on counts too.
    """
    run = program(words)
    base = started_in(words[: len(words) - len(run)], cwd)
    if run and bare(run[0]) in MAKES and not dry_run(run[1:]):
        return heavy_targets(run[1:], cfg, exempt, base)
    texts = segment_texts(words, run)
    if exempted(words, run, exempt) or (run and bare(run[0]) == "cargo" and cargo_allowed(run, assignments(words))):
        return False
    if judged(texts, run, cfg, exempt, base):
        return True
    at = inner_start(run)
    return at is not None and heavy_part(run[at:], cfg, exempt, base)


def segment_bases(parts: list[list[str]], cwd: str | None) -> list[str | None]:
    """Returns:
        The directory each simple command of parts starts in: cwd, moved by
        every cd or pushd before it to its target (None for a target with a
        substitution, a variable or none) and unknown after popd.
    """
    bases = []
    for words in parts:
        bases.append(cwd)
        if words[:1] == ["popd"]:
            cwd = None
        elif words[:1] in (["cd"], ["pushd"]):
            target = [word for word in words[1:] if not word.startswith("-")][:1]
            known = cwd is not None and target and "$" not in target[0]
            cwd = os.path.join(cwd, os.path.expanduser(target[0])) if known else None
    return bases


def safe_run(words: list[str]) -> list[str] | None:
    """Returns:
        The program part of words (program()) when nothing but
        SAFE_PREFIXES, their options and VAR=value words precede it, else
        None.
    """
    run = program(words)
    prefix = words[: len(words) - len(run)]
    if not run or words[len(prefix) :] != run or any(os.path.basename(word) in WRAPPERS - SAFE_PREFIXES for word in prefix):
        return None
    return run


def light_program(run: list[str], words: list[str], base: str | None) -> bool:
    name, args = bare(run[0]), run[1:]
    if name == "cargo":
        return cargo_allowed(run, assignments(words))
    if name == "find":
        return not FIND_EXEC.intersection(args)
    return name in LIGHT_TOOLS or node_check(run) or light_test(name, args, base)


def light_python(run: list[str], base: str | None) -> bool:
    name, args = tool(run)
    target = python_target(run[1:])[0]
    module = target == name and os.sep not in target and not SCRIPT.search(target)
    return module and (name in LIGHT_MODULES or light_test(name, args, base))


def light_part(words: list[str], base: str | None) -> bool:
    if bare(words[0]) in DIRECTORY_CHANGES:
        return True
    run = safe_run(words)
    if run is None or stirring(assignments(words)):
        return False
    base = started_in(words[: len(words) - len(run)], base)
    code = inline_code(run)
    if code is not None:
        return light(code, base)
    return light_python(run, base) if PYTHON.fullmatch(bare(run[0])) else light_program(run, words, base)


def light(command: str, cwd: str | None) -> bool:
    """Args:
        command: the shell command line as typed.
        cwd: the directory it starts in, None when unknown.

    Returns:
        Whether every simple command of it is a recognised small form: cd,
        pushd or popd, or behind nothing but SAFE_PREFIXES and INERT_ENV or
        LC_* assignments a LIGHT_TOOLS program (find without -exec), a
        cargo_allowed() call, node_check(), `python -m` of LIGHT_MODULES, `sh -c` of a
        light command, or light_test(); test files resolve relative to cwd
        moved by every cd and env -C. A substitution, heredoc, background
        job, unbalanced quote or second test run (test_runs()) makes it not
        light.
    """
    marked, heredocs = marked_heredocs(command)
    plain, codes = substituted(uncommented(marked))
    if heredocs or codes or BACKGROUND.search(plain) or test_runs(command, ()) > 1:
        return False
    try:
        parts = [words for words in segments(plain) if words]
    except ValueError:
        return False
    return bool(parts) and all(light_part(words, base) for words, base in zip(parts, segment_bases(parts, cwd)))


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


def payload_cwd(payload: dict) -> str | None:
    """Returns:
        The hook payload's cwd when it is an absolute path, else None
        (unknown, heavy()).
    """
    cwd = payload.get("cwd")
    return cwd if isinstance(cwd, str) and os.path.isabs(cwd) else None


def cmd_block(cfg: dict, problem: str | None, unsettled: bool) -> int:
    """Args:
        cfg: the config.
        problem: why the memory stage cannot be judged, None when it can; a
            heavy job is then refused with it.
        unsettled: whether cfg stands in for an unusable config file
            (settled_config()); a heavy job is then refused with problem alone.
    """
    payload = json.load(sys.stdin)
    raw = (payload.get("tool_input") or {}).get("command", "")
    if not heavy(raw, cfg, tuple(cfg["never_block"]), payload_cwd(payload)):
        return 0
    reason = problem if unsettled else block_reason(cfg, problem)
    if reason is None:
        return 0
    still = " Teardown commands still run." if cfg["never_block"] else ""
    print(f"kvb-org-organize: {reason}.{still} Ask the resource chair.", file=sys.stderr)
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


def psi_avg10(pressure: str, kind: str) -> float | None:
    for line in pressure.splitlines():
        if line.startswith(f"{kind} "):
            return float(dict(field.split("=", 1) for field in line.split()[1:])["avg10"])
    return None


def swap_pages(vmstat: str) -> int | None:
    for line in vmstat.splitlines():
        key, _, value = line.partition(" ")
        if key == "pswpout" and value.strip().isdigit():
            return int(value)
    return None


def swap_out_rate(before: list[float] | None, after: list[float], page_bytes: int) -> float | None:
    """Args:
        before: [epoch seconds, pswpout] of the earlier reading, None without
            one.
        after: [epoch seconds, pswpout] of this reading.
        page_bytes: the size of one swapped page.

    Returns:
        The MB swapped out per minute between both; None without an earlier
        reading, after a counter reset and when they lie outside SWAP_SPAN
        seconds apart.
    """
    if before is None:
        return None
    span, pages = after[0] - before[0], after[1] - before[1]
    if pages < 0 or not SWAP_SPAN[0] <= span <= SWAP_SPAN[1]:
        return None
    return pages * page_bytes / MB * 60 / span


def swap_readings(stored: list[list[float]], reading: list[float]) -> tuple[list[float] | None, list[list[float]]]:
    """Args:
        stored: the kept [epoch seconds, pswpout] readings, oldest first.
        reading: this one.

    Returns:
        The newest stored reading at least SWAP_SPAN[0] seconds older than
        reading, None without one, and the readings to keep: the newest
        stored one and reading once that is SWAP_SPAN[0] seconds old, else
        the last two stored. A reading from the future or above the count of
        reading (a counter reset) is dropped.
    """
    valid = [kept for kept in stored if kept[0] < reading[0] and kept[1] <= reading[1]]
    older = [kept for kept in valid if reading[0] - kept[0] >= SWAP_SPAN[0]]
    baseline = older[-1] if older else None
    if valid and reading[0] - valid[-1][0] < SWAP_SPAN[0]:
        return baseline, valid[-2:]
    return baseline, [*valid[-1:], reading]


def stored_readings() -> list[list[float]]:
    readings = read_json(SWAP_OUT).get("readings")
    return [
        reading for reading in (readings if isinstance(readings, list) else [])
        if isinstance(reading, list) and len(reading) == 2
        and all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in reading)
    ]


def swap_out() -> float | None:
    try:
        pages = swap_pages(VMSTAT.read_text(encoding="utf-8"))
    except OSError:
        return None
    if pages is None:
        return None
    reading = [time.time(), pages]
    stored = stored_readings()
    baseline, kept = swap_readings(stored, reading)
    if kept != stored:
        write_json(SWAP_OUT, {"readings": kept})
    return swap_out_rate(baseline, reading, PAGE_BYTES)


def memory_sample(meminfo: str, pressure: str | None, container_swap_gb: float,
                  swap_out_mb_min: float | None) -> dict[str, float | None]:
    """Args:
        meminfo: the text of /proc/meminfo.
        pressure: the text of /proc/pressure/memory, None without PSI.
        container_swap_gb: the swap of the container holding the most, in GB.
        swap_out_mb_min: the swap-out rate in MB per minute (swap_out()),
            None without one.

    Returns:
        {available, swap_free, psi_some, psi_full, swap_out_mb_min,
        container_swap_gb}: MemAvailable and SwapFree in percent of their
        totals, the some and full avg10 stall percentages, the rate and
        container_swap_gb unchanged; swap_free is None without swap, psi_some
        and psi_full None without PSI.
    """
    values = meminfo_kb(meminfo)
    swap = values["SwapTotal"]
    return {
        "available": 100.0 * values["MemAvailable"] / values["MemTotal"],
        "swap_free": 100.0 * values["SwapFree"] / swap if swap else None,
        "psi_some": None if pressure is None else psi_avg10(pressure, "some"),
        "psi_full": None if pressure is None else psi_avg10(pressure, "full"),
        "swap_out_mb_min": swap_out_mb_min,
        "container_swap_gb": container_swap_gb,
    }


def memory() -> dict[str, float | None]:
    try:
        pressure = PRESSURE.read_text(encoding="utf-8")
    except OSError:
        pressure = None
    largest = max((size for size, _ in container_swaps(CGROUPS)), default=0)
    return memory_sample(MEMINFO.read_text(encoding="utf-8"), pressure, largest / GB, swap_out())


def memory_stage(sample: dict[str, float | None], cfg: dict) -> str:
    for name in ("stop", "warn"):
        bound = cfg["memory_limits"][name]
        if (
            sample["available"] < bound["available"]
            or (sample["swap_free"] is not None and sample["swap_free"] < bound["swap_free"])
            or any(sample[key] is not None and sample[key] >= bound[key] for key in PRESSURES[name])
            or sample["container_swap_gb"] >= bound["container_swap_gb"]
        ):
            return name
    return "ok"


def measured(value: float | None, unit: str) -> str:
    return "unmeasured" if value is None else f"{value:.1f}{unit}"


def memory_text(sample: dict[str, float | None]) -> str:
    swap = "no swap" if sample["swap_free"] is None else f"swap free {sample['swap_free']:.0f} %"
    psi = f"PSI avg10 some {measured(sample['psi_some'], '')} full {measured(sample['psi_full'], '')}"
    return (
        f"MemAvailable {sample['available']:.0f} %, {swap}, {psi}, swap-out {measured(sample['swap_out_mb_min'], ' MB/min')}, "
        f"largest container swap {sample['container_swap_gb']:.1f} GB"
    )


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


def heavy(command: str, cfg: dict, exempt: tuple[str, ...], cwd: str | None) -> bool:
    """Args:
        command: the shell command line as typed, quotes included.
        cfg: the config; its heavy_commands search each simple command with
            quoted text blanked, and a make call also as `make <targets>`.
        exempt: regexes; a simple command one of them finds is never heavy
            (never_block, the queue's own hold), the others still count.
        cwd: the directory the shell runs it in (the hook payload's cwd),
            None when unknown; each simple command starts where the cd and
            pushd before it lead (segment_bases()), nested code where none
            leads.

    Returns:
        Whether one simple command is a heavy job: an image build through
        docker compose (build, or up, run or create with --build), a
        heavy_commands match, make or gmake without a target or with
        install, test*, quality* or verify-* (not as a dry run), tox, nox,
        hatch or deno test, playwright, cargo, node --test, npm, pnpm, yarn
        or bun with a RUN_WORDS command, pytest or unittest on anything but
        exactly one test file or module (a discover pattern only when
        one_discovered()), or a test, python script or module, or node, deno
        or bun script that is a browser_test(), help and version aside; also
        two test runs in one command line (test_runs()), or one beside an
        assignment that can change it (stirring()); a cargo_allowed() call
        is light. Wrappers (program(), npx included), whatever follows a
        program without a rule of its own (inner_start()), the code of `sh -c`,
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
        return unparsed_heavy(command, cfg, exempt)
    if crowded(command, parts, exempt):
        return True
    nested = codes + expanded_codes(heredocs) + fed_bodies(parts)
    bases = segment_bases(parts, cwd)
    if any(words[:1] in (["cd"], ["pushd"], ["popd"]) for words in parts):
        cwd = None
    return (any(heavy_part(words, cfg, exempt, base) for words, base in zip(parts, bases))
            or any(heavy(code, cfg, exempt, cwd) for code in nested))


def queue_hold(command: str) -> str:
    return f"queue.py hold --kind {HEAVY_KIND} --task <register task> -- {command}"


def admit_sample(cfg: dict) -> tuple[float, float, dict[str, float | None]]:
    """Returns:
        CPU busy and RAM used over the load window (load()) and the memory
        sample after it.
    """
    swap_out()
    cpu, mem = load(cfg)
    return cpu, mem, memory()


def admit_need(cfg: dict, args: argparse.Namespace) -> float | None:
    return args.need_gb if args.need_gb is not None else cfg["slot_need_gb"].get(args.kind)


def cmd_admit(cfg: dict, args: argparse.Namespace) -> int:
    command = shlex.join(args.command)
    if not light(command, os.getcwd()):
        print(f"deny: {command} is no light run and never self-admits; run it as `{queue_hold(command)}`")
        return 3
    need = admit_need(cfg, args)
    if need is None:
        print(f"deny: kind {args.kind!r} is not in slot_need_gb of {CONFIG}")
        return 3
    free, _ = disk(cfg)
    left = free - need
    floor = cfg["thresholds_gb"]["stop"]
    report = [f"free {free:.1f} GB, need {need} GB, leaves {left:.1f} GB (floor {floor} GB)"]
    limits = cfg["load_limits"]
    cpu, mem, sample = admit_sample(cfg)
    stage = memory_stage(sample, cfg)
    passed = left >= floor and stage != "stop"
    reason = loaded("queue", QUEUE).admit(cfg, args.kind or LIGHT_KIND, args.command, cpu, mem, stage == "ok") if passed else None
    report.append(f"cpu {cpu:.0f} % (limit {limits['cpu_percent']}), ram {mem:.0f} % (limit {limits['mem_percent']})")
    report.append(f"memory stage {stage} ({memory_text(sample)})")
    report.append(reason or "RAM used plus the job and the queue's still to come fits")
    verdict = "grant" if passed and reason is None else "deny"
    print(f"{verdict}: {'; '.join(report)}")
    return 0 if verdict == "grant" else 3


def cache_files(dirs: list[str]) -> list[tuple[float, int, str, str]]:
    files = []
    seen: set[tuple[int, int]] = set()
    for root in map(os.path.expanduser, dirs):
        try:
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
        except OSError:
            continue
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


def prune_flags(words: list[str]) -> bool:
    flags = iter(words)
    return all(PRUNE_FLAG.fullmatch(word) or (word == "--filter" and next(flags, None) is not None) for word in flags)


def plain_prune(command: str) -> bool:
    """Returns:
        Whether the line parses to exactly `docker image prune` or `docker
        images prune` followed by nothing but -a, -f, --all, --force and
        --filter X.
    """
    try:
        words = shlex.split(command)
    except ValueError:
        return False
    return words[:1] == ["docker"] and words[1:3] in PRUNE_COMMANDS and prune_flags(words[3:])


def prune_verdict(command: str) -> str:
    """Returns:
        "prune" for a plain_prune() line, run in process; "unguarded" for a
        line whose text, with whitespace collapsed and with or without its
        quotes, backslashes and backticks, would reach docker past the guard
        shim (an absolute docker path, a PATH reset, or docker with a
        privilege switch); else "run", through the shell with the shim first
        on PATH.
    """
    if plain_prune(command):
        return "prune"
    texts = {" ".join(text.split()) for text in (command, QUOTING.sub("", command))}
    if absolute_docker(command) or any(
        UNGUARDED.search(text) or ("docker" in text and PRIVILEGED.search(text)) for text in texts
    ):
        return "unguarded"
    return "run"


def absolute_docker(command: str) -> bool:
    """Returns:
        Whether a simple command of the line, or of a shell's -c code in it,
        runs a program named by a path ending in /docker or /docker-compose;
        a path in an argument, such as /var/lib/docker, does not count.
    """
    try:
        parts = segments(command)
    except ValueError:
        return False
    for part in parts:
        run = program(part)
        code = inline_code(run)
        if code is not None and absolute_docker(code):
            return True
        if run and run[0].endswith(tuple(f"/{name}" for name in GUARDED_BINARIES)):
            return True
    return False


def docker_split(args: list[str]) -> tuple[list[str], list[str]]:
    """Returns:
        docker's global options with their values, and the subcommand with
        its arguments.
    """
    at = 0
    while at < len(args) and args[at].startswith("-"):
        at += 2 if args[at] in DOCKER_GLOBALS else 1
    return args[:at], args[at:]


def guard_verdict(rest: list[str]) -> str | None:
    """Returns:
        "prune" for an image prune, the reason a removal is refused, or None
        for a command docker runs as asked.
    """
    if rest[:2] in PRUNE_COMMANDS:
        return "prune"
    for words, reason in REMOVALS.items():
        if tuple(rest[: len(words)]) == words:
            return reason
    if rest[:1] == ["compose"] and any(arg == "--rmi" or arg.startswith("--rmi=") for arg in rest):
        return COMPOSE_RMI
    if INNER_REMOVAL.search(" ".join(rest[1:])):
        return REFUSALS["nested"]
    return None


def cmd_guard(real: str, report: str, args: list[str]) -> int:
    """Args:
        real: the docker or docker-compose binary the shim stands in for.
        report: the file the result lines are appended to.
        args: its arguments as the shell expanded them.

    Returns:
        0 after a clean leftover step, 1 after one with failures,
        GUARD_REFUSED for a refused removal; any other command replaces this
        process with the real binary.
    """
    name = os.path.basename(real)
    options, rest = docker_split(args) if name == "docker" else ([], ["compose", *args])
    verdict = guard_verdict(rest)
    if verdict is None:
        os.execv(real, [real, *args])
    if verdict == "prune":
        lines = remove_leftovers([real, *options])
    else:
        lines = [f"refused ({verdict}): {shlex.join([name, *args])}".replace("\n", " ")]
        print(f"docker guard: {lines[0]}", file=sys.stderr)
    with open(report, "a", encoding="utf-8") as handle:
        handle.writelines(f"{line}\n" for line in lines)
    if verdict != "prune":
        return GUARD_REFUSED
    return 1 if cleanup_failures(lines) else 0


def run_step(command: str | list[str], shell: bool, env: dict[str, str] | None = None) -> tuple[int | str, bytes, bytes]:
    """Returns:
        The exit code, or "timeout" or the OS error that kept the command from
        running, and its standard output and standard error.
    """
    try:
        done = subprocess.run(command, shell=shell, cwd="/", env=env, capture_output=True, timeout=900, check=False)
    except subprocess.TimeoutExpired:
        return "timeout", b"", b""
    except OSError as error:
        return error.strerror or type(error).__name__, b"", b""
    return done.returncode, done.stdout, done.stderr


def result_line(code: int | str, shown: str) -> str:
    return f"{OK if code == 0 else f'failed ({code}): '}{shown}"


def shown(prefix: list[str], args: list[str]) -> str:
    return shlex.join([os.path.basename(prefix[0]), *prefix[1:], *args])


def remove_leftovers(prefix: list[str]) -> list[str]:
    """Args:
        prefix: the argv that reaches the daemon, up to and including its
            docker binary and global options.

    Returns:
        The result lines of listing the dangling images and of removing each
        one, without force, whose repository and digest are both <none>; a
        pull by digest keeps both and stays, an image a container uses is
        `kept (in use)`.
    """
    code, out, _ = run_step([*prefix, *LEFTOVERS], False)
    lines = [result_line(code, shown(prefix, LEFTOVERS))]
    rows = (row.split() for row in out.decode(errors="replace").splitlines()) if code == 0 else ()
    for image in dict.fromkeys(fields[0] for fields in rows if fields[1:] == [NONE, NONE] and IMAGE_ID.fullmatch(fields[0])):
        code, _, err = run_step([*prefix, "rmi", image], False)
        in_use = code != 0 and IN_USE.search(err.decode(errors="replace")) is not None
        lines.append(KEPT_LINE + shown(prefix, ["rmi", image]) if in_use else result_line(code, shown(prefix, ["rmi", image])))
    return lines


def cleanup_failures(results: list[str]) -> list[str]:
    return [line for line in results if not line.startswith((OK, KEPT_LINE))]


def guard_env(directory: Path, report: Path, binaries: dict[str, str | None]) -> dict[str, str]:
    """Args:
        binaries: the real path of each of GUARDED_BINARIES, None when absent.

    Returns:
        The environment of the cleanup shell lines: per binary found, a shim
        of its name in the private directory, first on PATH, that hands every
        call to `watch.py guard`.
    """
    env = dict(os.environ)
    found = {name: real for name, real in binaries.items() if real is not None}
    for name, real in found.items():
        shim = directory / name
        quoted = {key: shlex.quote(value) for key, value in (
            ("python", sys.executable), ("watch", str(Path(__file__).resolve())), ("real", real),
            ("report", str(report)),
        )}
        shim.write_text(SHIM.format(**quoted), encoding="utf-8")
        shim.chmod(0o700)
    if found:
        env["PATH"] = os.pathsep.join(filter(None, (str(directory), env.get("PATH", ""))))
    return env


def guarded(command: str, env: dict[str, str], report: Path) -> list[str]:
    report.unlink(missing_ok=True)
    code = run_step(command, True, env)[0]
    return [result_line(code, command), *(report.read_text(encoding="utf-8").splitlines() if report.exists() else ())]


def worktree_prune(argv: list[str]) -> bool:
    return (
        argv[:3] == ["docker", "compose", "-p"] and argv[4:6] == ["exec", "-T"] and len(argv) > 9
        and not argv[6].startswith("-") and argv[7] == "docker" and argv[8:10] in PRUNE_COMMANDS
        and prune_flags(argv[10:])
    )


def worktree_step(argv: list[str]) -> list[str]:
    """Returns:
        The result lines of one worktree command: the leftover step inside the
        worktree's daemon for the exact `docker compose -p <project> exec -T
        <service> docker image prune` form, a refusal for any other command
        naming an image removal, else its own result.
    """
    if worktree_prune(argv):
        return remove_leftovers(argv[:8])
    text = " ".join(argv)
    if WORKTREE_REMOVAL.search(text) or WORKTREE_REMOVAL.search(QUOTING.sub("", text)):
        return [f"refused ({REFUSALS['nested']}): {shlex.join(argv)}"]
    return [result_line(run_step(argv, False)[0], shlex.join(argv))]


def run_cleanup(cfg: dict) -> list[str]:
    """Returns:
        The result lines of the configured cleanup commands, every plain
        `docker image prune` among them replaced by one remove_leftovers() in
        the first one's place, every line prune_verdict() refuses reported as
        `refused (<reason>): <command>` with none of it run and every other
        line followed by the lines its guarded docker calls reported, then
        those of the worktree commands.
    """
    worktree_commands = [
        [arg.format(project=project) for arg in argv]
        for tree, project in running_worktrees(cfg)
        if not busy(tree, cfg["busy_processes"])
        for argv in cfg["worktree_cleanup"]
    ]
    binaries = {name: shutil.which(name) for name in GUARDED_BINARIES}
    real = binaries["docker"]
    results: list[str] = []
    pruned = False
    import tempfile

    with tempfile.TemporaryDirectory(prefix="kvb-docker-guard-") as directory:
        report = Path(directory) / "report"
        env = guard_env(Path(directory), report, binaries)
        for command in cfg["cleanup"]:
            verdict = prune_verdict(command)
            if verdict == "run":
                results += guarded(command, env, report)
            elif verdict in REFUSALS:
                results.append(f"refused ({REFUSALS[verdict]}): {command}")
            elif not pruned:
                pruned = True
                results += remove_leftovers([real or "docker"])
    return results + [line for argv in worktree_commands for line in worktree_step(argv)]


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
            failed = cleanup_failures(results)
            if args.full or cache_gb:
                alert(
                    "cleanup",
                    f"RESOURCE CLEANUP: freed {after - before:.1f} GB ({cache_gb:.1f} GB caches), "
                    f"/ now {after:.1f} GB free; {len(results) - len(failed)} commands ok"
                    + (f", failed: {' | '.join(failed)}" if failed else "."),
                    False,
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


def cmd_preflight() -> int:
    cfg, warning = settled_config()
    problem = warning or (None if cfg is None else missing(cfg, MEMORY_KEYS))
    if problem is None:
        return 0
    print(problem, file=sys.stderr)
    return 2


def main() -> int:
    if sys.argv[1:2] == ["guard"] and len(sys.argv) > 3:
        return cmd_guard(sys.argv[2], sys.argv[3], sys.argv[4:])
    if sys.argv[1:2] != ["block"]:
        return run()
    try:
        return run()
    except Exception as error:
        print(f"kvb-org-organize: the block hook failed ({error!r}), so the command counts as heavy and is refused.",
              file=sys.stderr)
        return 2


def announced_config() -> tuple[dict | None, str | None]:
    """Returns:
        settled_config(), its warning printed to stderr.
    """
    cfg, warning = settled_config()
    if warning is not None:
        print(warning, file=sys.stderr)
    return cfg, warning


def watch_hook() -> int:
    cfg, warning = settled_config()
    if cfg is None:
        return 0
    return cmd_watch(cfg, warning or missing(cfg, MEMORY_KEYS), warning is not None)


def block_hook() -> int:
    cfg, warning = announced_config()
    if cfg is None:
        return 0
    return cmd_block(cfg, warning or missing(cfg, MEMORY_KEYS), warning is not None)


def run() -> int:
    hooked = sys.argv[1:] in (["block"], ["watch"])
    args = argparse.Namespace(cmd=sys.argv[1]) if hooked else cli().parse_args()
    os.environ["PATH"] = hookpath.trusted(os.environ.get("PATH", ""))
    if args.cmd == "preflight":
        return cmd_preflight()
    refused = guard_root(hook=hooked)
    if refused is not None:
        return refused
    if hooked:
        return {"block": block_hook, "watch": watch_hook}[args.cmd]()
    cfg, warning = announced_config()
    if cfg is None:
        return 0
    if warning is not None and args.cmd == "cleanup":
        return 2
    problem = missing(cfg, MEMORY_KEYS)
    if problem is not None:
        print(problem, file=sys.stderr)
        return 2
    handlers = {"admit": cmd_admit, "cleanup": cmd_cleanup}
    if args.cmd in handlers:
        return handlers[args.cmd](cfg, args)
    return cmd_status(cfg)


def cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="watch")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("watch")
    sub.add_parser("block")
    admit = sub.add_parser("admit")
    need = admit.add_mutually_exclusive_group(required=True)
    need.add_argument("--need-gb", type=float)
    need.add_argument("--kind")
    admit.add_argument("command", nargs="+")
    cleanup = sub.add_parser("cleanup")
    mode = cleanup.add_mutually_exclusive_group(required=True)
    mode.add_argument("--caches", action="store_true")
    mode.add_argument("--full", action="store_true")
    sub.add_parser("status")
    sub.add_parser("preflight")
    return parser


if __name__ == "__main__":
    sys.exit(main())
