#!/usr/bin/env python3
"""Watch disk, Docker and caches for the democracy resource chair.

Usage:
    watch.py watch     hook (UserPromptSubmit, PostToolUse): measure at most once
                       per interval machine-wide, act on the stage, show alerts
    watch.py block     hook (PreToolUse on Bash): exit 2 for a heavy job while the
                       stage is stop or critical
    watch.py admit (--need-gb N | --kind KIND)
                       exit 0 when the grant leaves at least the stop threshold
                       free, 3 otherwise
    watch.py cleanup (--caches | --full)
                       trim caches to their budget; --full also runs the
                       configured low-risk cleanup commands
    watch.py status    print the last measurement

Environment:
    AGENTS_COUNCIL_ROOT: shared state directory; /tmp/agents-council unless set,
        because every agent on the host must agree on it.
    AGENTS_COUNCIL_CONFIG: config file; ~/.config/agents-council/config.json
        unless set. Without a config file every command exits 0 and does nothing.

Config keys, all required: disk, thresholds_gb {warn, stop, critical},
projection_minutes, interval_seconds, cache_interval_seconds, heavy_commands,
never_block (regexes), cleanup (shell commands), worktree_cleanup (shell
commands with {worktree}), worktrees (globs), cache_dirs, cache_budget_percent,
slot_need_gb {kind: GB}, notify (argv the alert text is appended to).
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get("AGENTS_COUNCIL_ROOT", "/tmp/agents-council"))
CONFIG = Path(
    os.environ.get(
        "AGENTS_COUNCIL_CONFIG",
        str(Path.home() / ".config" / "agents-council" / "config.json"),
    )
)
STAGES = ("ok", "warn", "stop", "critical")
STATE = ROOT / "watch.json"
ALERTS = ROOT / "alerts.jsonl"
ALERT_TTL = 3600
LOCK_TTL = 1800
GB = 1e9


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


def cmd_watch(cfg: dict) -> int:
    payload = json.load(sys.stdin)
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


def cmd_block(cfg: dict) -> int:
    payload = json.load(sys.stdin)
    command = (payload.get("tool_input") or {}).get("command", "")
    stage = read_json(STATE).get("stage", "ok")
    if stage not in ("stop", "critical"):
        return 0
    if any(re.search(p, command) for p in cfg["never_block"]):
        return 0
    if any(re.search(p, command) for p in cfg["heavy_commands"]):
        print(
            f"democracy: resource stage is {stage}; new heavy jobs are blocked until "
            "the disk recovers. Teardown commands still run. Ask the resource chair.",
            file=sys.stderr,
        )
        return 2
    return 0


def cmd_admit(cfg: dict, args: argparse.Namespace) -> int:
    need = args.need_gb if args.need_gb is not None else cfg["slot_need_gb"][args.kind]
    free, _ = disk(cfg)
    left = free - need
    floor = cfg["thresholds_gb"]["stop"]
    verdict = "grant" if left >= floor else "deny"
    print(f"{verdict}: free {free:.1f} GB, need {need} GB, leaves {left:.1f} GB (floor {floor} GB)")
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


def run_cleanup(cfg: dict) -> list[str]:
    commands = list(cfg["cleanup"])
    for pattern in cfg["worktrees"]:
        for tree in sorted(glob.glob(os.path.expanduser(pattern))):
            if os.path.isdir(tree):
                commands += [t.format(worktree=shlex.quote(tree)) for t in cfg["worktree_cleanup"]]
    results = []
    for command in commands:
        try:
            code = subprocess.run(command, shell=True, capture_output=True, timeout=900, check=False).returncode
        except subprocess.TimeoutExpired:
            code = "timeout"
        results.append(f"{'ok' if code == 0 else f'failed ({code})'}: {command}")
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
