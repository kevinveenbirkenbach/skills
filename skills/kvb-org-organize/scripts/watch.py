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
                       stage is stop or critical, or while a kvb-org-radio mayday
                       holds radio silence (<root>/radio-silence.json, until > now)
    watch.py admit (--need-gb N | --kind KIND)
                       exit 0 when the grant leaves at least the stop threshold
                       free, 3 otherwise
    watch.py cleanup (--caches | --full)
                       trim caches to their budget; --full also runs the
                       configured low-risk cleanup commands
    watch.py status    print the last measurement

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
load_limits {cpu_percent, mem_percent, sample_seconds, kinds}: admit for a
kind listed in kinds also needs CPU busy and RAM used below the limits.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shlex
import stat
import subprocess
import sys
import time
from pathlib import Path

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
LOCK_TTL = 1800
GB = 1e9


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


def disk(cfg: dict) -> tuple[float, float]:
    st = os.statvfs(cfg["disk"])
    return st.f_bavail * st.f_frsize / GB, st.f_blocks * st.f_frsize / GB


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_json(path: Path, data: dict) -> None:
    # A full disk refuses the write; the stage must still act, so it is dropped.
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


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
        with ALERTS.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"id": time.time_ns(), "stage": stage, "text": text}) + "\n")
    except OSError:
        pass


def unseen_alerts(session: str) -> list[str]:
    seen_path = ROOT / "seen" / session
    try:
        seen = int(seen_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        seen = 0
    try:
        lines = ALERTS.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    cutoff = time.time_ns() - ALERT_TTL * 10**9
    fresh = [json.loads(line) for line in lines if line]
    fresh = [a for a in fresh if a["id"] > max(seen, cutoff)]
    if fresh:
        write_text(seen_path, str(fresh[-1]["id"]))
    return [a["text"] for a in fresh]


def write_text(path: Path, text: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
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
        [sys.executable, str(Path(__file__).resolve()), "cleanup", mode],
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


def history_rows(text: str) -> list[tuple[str, str]]:
    rows = []
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
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
            fcntl.flock(kept, fcntl.LOCK_EX)
            kept.seek(0)
            known = {row_id for row_id, _ in history_rows(kept.read())}
            for row_id, line in history_rows(origin.read_text(encoding="utf-8")):
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


def cmd_watch(cfg: dict) -> int:
    payload = json.load(sys.stdin)
    keep_history()
    now = time.time()
    state = read_json(STATE)
    if now - state.get("checked", 0) >= cfg["interval_seconds"]:
        free, _ = disk(cfg)
        samples = [s for s in state.get("samples", []) if now - s[0] <= cfg["projection_minutes"] * 60]
        stage = stage_for(free, samples, cfg, now)
        previous = state.get("stage", "ok")
        samples.append([now, free])
        state.update(checked=now, free=free, stage=stage, samples=samples)
        due = now - state.get("caches_checked", 0) >= cfg["cache_interval_seconds"]
        if due:
            state["caches_checked"] = now
        write_json(STATE, state)
        if stage != previous:
            act(cfg, stage, previous, free)
        elif due:
            spawn_cleanup("--caches")
    texts = unseen_alerts(payload["session_id"])
    if texts:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": payload["hook_event_name"],
            "additionalContext": "\n".join(texts),
        }}))
    return 0


HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1[^\n]*\n.*?\n\s*\2(?=\s|\)|$)", re.DOTALL)
QUOTED = re.compile(r"'[^']*'|\"(?:\\.|[^\"\\])*\"")


def executable_text(command: str) -> str:
    return QUOTED.sub("''", HEREDOC.sub("", command))


def silence() -> dict | None:
    state = read_json(SILENCE)
    return state if state.get("until", 0) > time.time() else None


def cmd_block(cfg: dict) -> int:
    payload = json.load(sys.stdin)
    command = executable_text((payload.get("tool_input") or {}).get("command", ""))
    stage = read_json(STATE).get("stage", "ok")
    mayday = silence()
    if stage not in ("stop", "critical") and not mayday:
        return 0
    if any(re.search(p, command) for p in cfg["never_block"]):
        return 0
    if any(re.search(p, command) for p in cfg["heavy_commands"]):
        reason = (
            f"a mayday by {mayday.get('by', '?')} holds radio silence: {mayday.get('text', '')}; "
            "it ends with radio.py clear"
            if mayday
            else f"resource stage is {stage}; new heavy jobs are blocked until the disk recovers"
        )
        print(
            f"kvb-org-organize: {reason}. Teardown commands still run. Ask the resource chair.",
            file=sys.stderr,
        )
        return 2
    return 0


def cpu_times() -> tuple[int, int]:
    fields = [int(v) for v in Path("/proc/stat").read_text(encoding="utf-8").split("\n", 1)[0].split()[1:]]
    return sum(fields), fields[3] + fields[4]


def cpu_busy_percent(before: tuple[int, int], after: tuple[int, int]) -> float:
    total = after[0] - before[0]
    idle = after[1] - before[1]
    return 100.0 * (total - idle) / total


def mem_used_percent(meminfo: str) -> float:
    values = {}
    for line in meminfo.splitlines():
        key, _, rest = line.partition(":")
        if rest:
            values[key] = int(rest.split()[0])
    return 100.0 * (1 - values["MemAvailable"] / values["MemTotal"])


def load(cfg: dict) -> tuple[float, float]:
    before = cpu_times()
    time.sleep(cfg["load_limits"]["sample_seconds"])
    cpu = cpu_busy_percent(before, cpu_times())
    return cpu, mem_used_percent(Path("/proc/meminfo").read_text(encoding="utf-8"))


def cmd_admit(cfg: dict, args: argparse.Namespace) -> int:
    need = args.need_gb if args.need_gb is not None else cfg["slot_need_gb"][args.kind]
    free, _ = disk(cfg)
    left = free - need
    floor = cfg["thresholds_gb"]["stop"]
    passed = [left >= floor]
    report = [f"free {free:.1f} GB, need {need} GB, leaves {left:.1f} GB (floor {floor} GB)"]
    limits = cfg["load_limits"]
    if args.kind in limits["kinds"]:
        cpu, mem = load(cfg)
        passed += [cpu < limits["cpu_percent"], mem < limits["mem_percent"]]
        report.append(
            f"cpu {cpu:.0f} % (limit {limits['cpu_percent']}), ram {mem:.0f} % (limit {limits['mem_percent']})"
        )
    verdict = "grant" if all(passed) else "deny"
    print(f"{verdict}: {'; '.join(report)}")
    return 0 if verdict == "grant" else 3


def cache_files(dirs: list[str]) -> list[tuple[float, int, str]]:
    files = []
    for root in dirs:
        for base, _, names in os.walk(os.path.expanduser(root)):
            for name in names:
                path = os.path.join(base, name)
                try:
                    st = os.lstat(path)
                except OSError:
                    continue
                files.append((st.st_atime, st.st_size, path))
    return files


def trim_caches(cfg: dict) -> float:
    _, total = disk(cfg)
    budget = total * GB * cfg["cache_budget_percent"] / 100
    files = sorted(cache_files(cfg["cache_dirs"]))
    used = sum(size for _, size, _ in files)
    freed = 0
    for _, size, path in files:
        if used - freed <= budget:
            break
        try:
            os.remove(path)
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
    lock = ROOT / "cleanup.lock"
    ROOT.mkdir(parents=True, exist_ok=True)
    try:
        if time.time() - lock.stat().st_mtime > LOCK_TTL:
            lock.rmdir()
    except FileNotFoundError:
        pass
    try:
        lock.mkdir()
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
        lock.rmdir()
    return 0


def cmd_status(cfg: dict) -> int:
    state = read_json(STATE)
    free, total = disk(cfg)
    print(f"stage={state.get('stage', 'unmeasured')} free={free:.1f}GB total={total:.1f}GB samples={len(state.get('samples', []))}")
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
    refused = guard_root(hook=args.cmd in ("watch", "block"))
    if refused is not None:
        return refused
    cfg = load_config()
    if cfg is None:
        return 0
    if args.cmd == "watch":
        return cmd_watch(cfg)
    if args.cmd == "block":
        return cmd_block(cfg)
    if args.cmd == "admit":
        return cmd_admit(cfg, args)
    if args.cmd == "cleanup":
        return cmd_cleanup(cfg, args)
    return cmd_status(cfg)


if __name__ == "__main__":
    sys.exit(main())
