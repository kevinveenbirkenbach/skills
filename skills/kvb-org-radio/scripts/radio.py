#!/usr/bin/env python3
"""Reach other agents by radio: five classes, from a board line to a wake, in one shared store.

Environment:
    AGENTS_COUNCIL_ROOT: council directory shared by every agent on the host;
        /tmp/agents-council unless set. Rows live in <root>/news.jsonl under
        <root>/news.lock, the store the old news.py reads and writes too.
    AGENTS_COUNCIL_CONFIG: config file whose "notify" argv tells the operator
        of a mayday; ~/.claude/agents-council/config.json unless set.
    CLAUDE_CODE_SESSION_ID: the calling session; hooks read the payload's
        session_id first, other runtimes pass --session.
    PATH: filtered to the directories the kvb-org-organize hookpath.py
        trusts before the notify argv runs.

Args:
    send <class> "<text>" [--to <name> ...] [--wake] [--session <id>]: add a
        row. broadcast, security, pan-pan and mayday go to all and take no
        --to; direct needs --to; --wake only with direct. mayday also sets
        radio silence (<root>/radio-silence.json) for two hours. A wake
        (mayday, direct --wake) then prints `wake: SendMessage to <name>`
        for every addressee without a live listener.
    post "<text>" [--to <name> ...] [--session <id>]: send broadcast, or
        direct with --to.
    clear [--force] [--session <id>]: end radio silence; its sender may,
        anyone else only with --force.
    hook: UserPromptSubmit hook; prints the active silence and the unseen
        rows, mayday, pan-pan and security first, at most 10, and marks them
        seen. Never fails the prompt.
    tool: PostToolBatch hook; prints the unseen urgent rows as
        additionalContext. Never fails.
    listen: Stop hook with asyncRewake; polls every POLL_SECONDS until a
        mayday or a direct --wake reaches this session, prints it to stderr
        and exits 2; exits 0 once a newer listener of the session took over.
    show [--all] [--session <id>]: print the active silence and the unseen
        rows, or every kept row, without marking them.

Exit codes:
    0 done, 2 usage error (listen: wake the session), 3 radio silence held
    by another session.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime
import functools
import importlib.util
import json
import math
import os
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

# Every agent on the host must agree on one council directory and one config without being told.
ROOT = Path(os.environ.get("AGENTS_COUNCIL_ROOT", "/tmp/agents-council"))
CONFIG = Path(
    os.environ.get("AGENTS_COUNCIL_CONFIG", str(Path.home() / ".claude" / "agents-council" / "config.json"))
)
NEWS = ROOT / "news.jsonl"
LOCK = ROOT / "news.lock"
SEEN = ROOT / "news-seen"
STATE = ROOT / "radio-seen"
LISTEN = ROOT / "radio-listen"
SILENCE = ROOT / "radio-silence.json"
NOTIFIED = ROOT / "radio-notified"
ORGANIZE = Path(__file__).resolve().parents[2] / "kvb-org-organize" / "scripts"
CLASSES = ("broadcast", "direct", "security", "pan-pan", "mayday")
URGENT = ("mayday", "pan-pan", "security")
WINDOW = 86400
SHOWN = 10
SESSION_WAIT = 2
KEPT = 500
SILENCE_SECONDS = 7200
NOTIFY_SECONDS = 10
POLL_SECONDS = 15
NEVER = 0.0


def fail(message: str) -> None:
    print(f"radio: {message}", file=sys.stderr)
    sys.exit(2)


@functools.cache
def organize(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"kvb_radio_{name}", ORGANIZE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def council() -> ModuleType:
    return organize("council")


def name_of(sid: str) -> str:
    return council().live_sessions().get(sid) or sid


def items() -> list[dict]:
    try:
        lines = organize("nofollow").read_text(ROOT, NEWS).splitlines()
    except OSError:
        return []
    rows = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and isinstance(row.get("ts"), int | float):
            rows.append(row)
    return rows


def kind(row: dict) -> str:
    if row.get("class") in CLASSES:
        return row["class"]
    return "direct" if row.get("to") else "broadcast"


def urgent(row: dict) -> bool:
    return kind(row) in URGENT


def rank(row: dict) -> int:
    return URGENT.index(kind(row)) if urgent(row) else len(URGENT)


def ordered(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda row: (rank(row), row["ts"]))


def clock(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts).strftime("%H:%M")


def clip(value: object) -> str:
    return organize("watch").clip(value)


def line(row: dict) -> str:
    target = f" to {', '.join(clip(name) for name in row['to'])}" if row.get("to") else ""
    return f"RADIO {kind(row).upper()} {clock(row['ts'])} {clip(row.get('from'))}{target}: {clip(row.get('text'))}"


def capped(rows: list[dict]) -> list[str]:
    picked = sorted(rows, key=lambda row: (rank(row), -row["ts"]))[:SHOWN]
    more = [f"RADIO {len(rows) - SHOWN} more items: radio.py show --all"] if len(rows) > SHOWN else []
    return [line(row) for row in ordered(picked)] + more


def for_me(row: dict, name: str) -> bool:
    return row.get("from") != name and (not row.get("to") or name in row["to"])


def read_json(path: Path) -> dict:
    try:
        data = json.loads(organize("nofollow").read_text(ROOT, path))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_atomic(path: Path, text: str) -> None:
    organize("nofollow").replace(ROOT, path, text, 0o600)


def prompt_mark(sid: str) -> float:
    try:
        return float(organize("nofollow").read_text(ROOT, SEEN / sid))
    except (OSError, ValueError):
        return NEVER


def mark(state: dict, key: str) -> float:
    value = state.get(key)
    return NEVER if value is None else value


def news_mtime() -> float | None:
    try:
        return NEWS.stat().st_mtime
    except FileNotFoundError:
        return None


@contextlib.contextmanager
def session(sid: str) -> Iterator[dict]:
    with organize("nofollow").locked(ROOT, STATE / f"{sid}.lock", 0o600, SESSION_WAIT):
        yield read_json(STATE / f"{sid}.json")


def save(sid: str, state: dict) -> None:
    write_atomic(STATE / f"{sid}.json", json.dumps(state))


def hook_session() -> str | None:
    payload = json.load(sys.stdin)
    if payload.get("agent_id"):
        return None
    return payload.get("session_id") or os.environ.get("CLAUDE_CODE_SESSION_ID")


def silence() -> dict | None:
    state = read_json(SILENCE)
    until = state.get("until")
    return state if isinstance(until, int | float) and until > time.time() else None


def silence_line(active: dict) -> str:
    return (
        f"MAYDAY ACTIVE since {clock(active['since'])} by {clip(active['by'])}: {clip(active['text'])}; "
        "no new heavy jobs until radio.py clear"
    )


def notify_once(active: dict | None) -> None:
    if active is None:
        return
    try:
        argv = json.loads(CONFIG.read_text(encoding="utf-8"))["notify"]
        marker = NOTIFIED / str(active["since"])
        os.close(organize("nofollow").open_below(ROOT, marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
        subprocess.run(
            [*argv, f"Agents radio MAYDAY by {active['by']}: {active['text']}"],
            capture_output=True,
            timeout=NOTIFY_SECONDS,
            check=False,
        )
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired):
        return


def listening(sid: str) -> bool:
    try:
        pid = int(organize("nofollow").read_text(ROOT, LISTEN / f"{sid}.pid"))
    except (OSError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def unreached(cls: str, to: list[str], sender: str) -> list[str]:
    live = council().live_sessions()
    if cls == "mayday":
        targets = [(name or sid, [sid]) for sid, name in live.items() if sid != sender]
    else:
        targets = [(name, [sid for sid, label in live.items() if name in (label, sid)]) for name in to]
    return [name for name, sids in targets if not any(map(listening, sids))]


def cmd_send(args: argparse.Namespace) -> int:
    to = args.to or []
    if args.cls == "direct" and not to:
        fail("direct needs --to")
    if args.cls != "direct" and to:
        fail(f"{args.cls} goes to all; drop --to")
    if args.wake and args.cls != "direct":
        fail("--wake only with direct")
    text = " ".join(args.text.split())
    if not text:
        fail(f"{args.cls} needs a text")
    sid, _ = council().caller(args.session)
    sender = name_of(sid)
    ROOT.mkdir(parents=True, exist_ok=True)
    with organize("nofollow").locked(ROOT, LOCK, 0o600, None):
        rows = items()
        ts = time.time()
        if rows:
            ts = max(ts, math.nextafter(max(row["ts"] for row in rows), math.inf))
        entry = {"ts": ts, "from": sender, "to": to, "text": text, "class": args.cls}
        if args.wake:
            entry["wake"] = True
        write_atomic(NEWS, "".join(json.dumps(row) + "\n" for row in [*rows[-(KEPT - 1):], entry]))
        if args.cls == "mayday":
            write_atomic(
                SILENCE,
                json.dumps({"since": ts, "until": ts + SILENCE_SECONDS, "by": sender, "text": text}),
            )
    print(f"sent {args.cls} to {', '.join(to) or 'all'}")
    if args.wake or args.cls == "mayday":
        for name in unreached(args.cls, to, sid):
            print(f"wake: SendMessage to {name}")
    return 0


def cmd_post(args: argparse.Namespace) -> int:
    args.cls = "direct" if args.to else "broadcast"
    args.wake = False
    return cmd_send(args)


def cmd_clear(args: argparse.Namespace) -> int:
    sid, _ = council().caller(args.session)
    me = name_of(sid)
    ROOT.mkdir(parents=True, exist_ok=True)
    with organize("nofollow").locked(ROOT, LOCK, 0o600, None):
        active = silence()
        if active is None:
            print("no radio silence active")
            return 0
        if active["by"] != me and not args.force:
            print(f"radio silence held by {active['by']}; only they clear it, anyone else with --force")
            return 3
        SILENCE.unlink(missing_ok=True)
    forced = f", forced by {me}" if active["by"] != me else ""
    print(f"cleared radio silence by {active['by']}{forced}")
    return 0


def unseen(sid: str, name: str) -> list[dict]:
    floor = max(prompt_mark(sid), time.time() - WINDOW)
    return [row for row in items() if row["ts"] > floor and for_me(row, name)]


def delivered(row: dict, state: dict) -> bool:
    if urgent(row):
        return row["ts"] <= mark(state, "urgent")
    return bool(row.get("wake")) and row["ts"] <= mark(state, "listen")


def cmd_hook(_: argparse.Namespace) -> int:
    try:
        sid = hook_session()
        if not sid:
            return 0
        active = silence()
        out = [silence_line(active)] if active else []
        name = name_of(sid)
        with session(sid) as state:
            rows = unseen(sid, name)
            out += capped([row for row in rows if not delivered(row, state)])
            if rows:
                write_atomic(SEEN / sid, str(max(row["ts"] for row in rows)))
        if out:
            print("\n".join(out))
        notify_once(active)
    except Exception:  # noqa: BLE001
        return 0
    return 0


def cmd_tool(_: argparse.Namespace) -> int:
    try:
        sid = hook_session()
        if not sid:
            return 0
        with session(sid) as state:
            mtime = news_mtime()
            if mtime is None or mtime <= mark(state, "mtime"):
                return 0
            name = name_of(sid)
            floor = max(mark(state, "urgent"), prompt_mark(sid), time.time() - WINDOW)
            rows = ordered([row for row in items() if urgent(row) and row["ts"] > floor and for_me(row, name)])
            state["mtime"] = mtime
            if rows:
                state["urgent"] = max(row["ts"] for row in rows)
            save(sid, state)
        if rows:
            context = "\n".join(capped(rows))
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolBatch", "additionalContext": context}}))
            if any(kind(row) == "mayday" for row in rows):
                notify_once(silence())
    except Exception:  # noqa: BLE001
        return 0
    return 0


def calls(sid: str) -> list[str]:
    name = name_of(sid)
    with session(sid) as state:
        floor = max(prompt_mark(sid), time.time() - WINDOW)
        heard = max(mark(state, "listen"), floor)
        loud = max(mark(state, "urgent"), floor)
        rows = [row for row in items() if row["ts"] > floor and for_me(row, name)]
        wakes = [
            row
            for row in rows
            if row["ts"] > heard
            and ((kind(row) == "direct" and row.get("wake")) or (kind(row) == "mayday" and row["ts"] > loud))
        ]
        if not wakes:
            return []
        alarms = [row for row in rows if urgent(row) and row["ts"] > loud]
        state["listen"] = max(row["ts"] for row in wakes)
        if alarms:
            state["urgent"] = max(row["ts"] for row in alarms)
        save(sid, state)
    return [line(row) for row in ordered(alarms + [row for row in wakes if not urgent(row)])]


def cmd_listen(_: argparse.Namespace) -> int:
    try:
        sid = hook_session()
        if not sid:
            return 0
        pidfile = LISTEN / f"{sid}.pid"
        mine = str(os.getpid())
        write_atomic(pidfile, mine)
        parent = os.getppid()
        known: float | None = None
        # A listener outliving its session would poll forever; the session exiting changes its parent.
        while organize("nofollow").read_text(ROOT, pidfile) == mine and os.getppid() == parent:
            mtime = news_mtime()
            if mtime != known:
                known = mtime
                lines = calls(sid)
                if lines:
                    print("\n".join(lines), file=sys.stderr)
                    notify_once(silence())
                    return 2
            time.sleep(POLL_SECONDS)
    except Exception:  # noqa: BLE001
        return 0
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    active = silence()
    if active:
        print(silence_line(active))
    if args.all:
        rows = items()
    else:
        sid, _ = council().caller(args.session)
        rows = ordered(unseen(sid, name_of(sid)))
    for row in rows:
        print(line(row))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("send")
    p.add_argument("cls", metavar="class", choices=CLASSES)
    p.add_argument("text")
    p.add_argument("--to", action="append")
    p.add_argument("--wake", action="store_true")
    p.add_argument("--session")
    p.set_defaults(func=cmd_send)
    p = sub.add_parser("post")
    p.add_argument("text")
    p.add_argument("--to", action="append")
    p.add_argument("--session")
    p.set_defaults(func=cmd_post)
    p = sub.add_parser("clear")
    p.add_argument("--force", action="store_true")
    p.add_argument("--session")
    p.set_defaults(func=cmd_clear)
    sub.add_parser("hook").set_defaults(func=cmd_hook)
    sub.add_parser("tool").set_defaults(func=cmd_tool)
    sub.add_parser("listen").set_defaults(func=cmd_listen)
    p = sub.add_parser("show")
    p.add_argument("--all", action="store_true")
    p.add_argument("--session")
    p.set_defaults(func=cmd_show)
    args = parser.parse_args()
    os.environ["PATH"] = organize("hookpath").trusted(os.environ.get("PATH", ""))
    refused = organize("watch").guard_root(hook=args.command in ("hook", "tool", "listen"))
    if refused is not None:
        return refused
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
