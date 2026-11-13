#!/usr/bin/env python3
"""Reach other agents: the radio is immediate, the post waits until a turn ends; one shared store.

Environment:
    AGENTS_COUNCIL_ROOT: council directory shared by every agent on the host;
        /tmp/agents-council unless set. Rows live in <root>/news.jsonl under
        <root>/news.lock, the store the old news.py reads and writes too.
    AGENTS_COUNCIL_CONFIG: config file; its "notify" argv tells the operator
        of a mayday, its "never_block" and "mayday_allow" regexes name the
        Bash commands a mayday lets through;
        ~/.claude/agents-council/config.json unless set.
    CLAUDE_CODE_SESSION_ID: the calling session; hooks read the payload's
        session_id first, other runtimes pass --session.
    PATH: filtered to the directories the kvb-org-organize hookpath.py
        trusts before the notify argv runs.

Args:
    send <class> "<text>" [--to <name> ...] [--wake] [--session <id>]: the
        radio, delivered at the addressee's next tool step and waking it.
        call needs --to; broadcast, security, pan-pan and mayday go to all
        and take no --to. direct is the old alias: with --wake a call,
        without it a post. mayday also sets radio silence
        (<root>/radio-silence.json) for two hours. Prints `ts: <ts>`, the
        stored row's ts, flushed right after it is stored, then `sent ...`
        and `wake: SendMessage to <name>` for every addressee without a live
        listener.
    post "<text>" [--to <name> ...] [--session <id>]: the post, delivered
        when the addressee's turn ends, never waking it: post with --to,
        newsletter without; prints `ts: <ts>` as send does.
    clear [--force] [--session <id>]: end radio silence; its sender may,
        anyone else only with --force.
    assist [--session <id>]: join the active mayday as a helper, whom the
        block lets through like its sender.
    hook: UserPromptSubmit hook; prints the active silence and the
        undelivered radio rows, mayday first, at most 10. Never fails.
    tool: PostToolBatch hook; adds the undelivered radio rows as
        additionalContext. Never fails.
    mailbox: Stop hook; prints the undelivered post, newsletters and call
        receipts to stderr, at most 10, and exits 2 so the agent reads them
        before it idles. Never fails.
    listen: Stop hook with asyncRewake; polls every POLL_SECONDS until a
        radio row reaches this session, prints it to stderr and exits 2;
        exits 0 once a newer listener of the session took over.
    block: PreToolUse hook; while a mayday holds, exits 2 for Edit, Write,
        MultiEdit, NotebookEdit and every Bash command but a plain call of
        this radio.py by absolute or ~/ path and a command a never_block or
        mayday_allow regex matches from its start; a shell operator, double
        quote or backslash outside single quotes, or any parse error, blocks.
        The mayday's sender and its helpers pass. Never fails.
    show [--all] [--session <id>]: print the active silence and the
        undelivered rows, or every kept row, without delivering them.
    feedback set post|call [--session <id>]: store how outcomes of the
        session's queued operator commands reach it, in <root>/feedback.json;
        post unless set.
    feedback show [--session <id>]: print the session's channel.
    feedback send "<text>" --to <name> ... [--sid <id>] [--session <id>]: send
        text to each name as a call when the session --sid names, else the
        name, set call, else as a post. --sid, with a single --to, pins that
        session: the row keeps the name in `to` and the id in `to_sessions`
        and reaches both, the session under any later name and whoever holds
        the name, with no liveness check; its wake line adds `(session <id>)`.

    Delivering a call stores a receipt in the caller's post.

Exit codes:
    0 done, 2 usage error (listen and mailbox: wake the session; block:
    refuse the tool call), 3 radio silence held by another session.
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
import re
import shlex
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
FEEDBACK = ROOT / "feedback.json"
ORGANIZE = Path(__file__).resolve().parents[2] / "kvb-org-organize" / "scripts"
SELF = Path(__file__).resolve()
RADIO = ("mayday", "pan-pan", "security", "call", "broadcast")
MAIL = ("post", "newsletter", "receipt")
ALARMS = ("mayday", "pan-pan", "security")
ADDRESSED = ("call", "post", "receipt")
SEND = ("call", "broadcast", "security", "pan-pan", "mayday", "direct")
FEEDBACKS = ("post", "call")
VERSION = 2
STORED = "ts: "
WRITERS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
SHELL = re.compile(r"[;&|`$()<>\n\r\\\"]")
SINGLE_QUOTED = re.compile(r"'[^']*'")
INTERPRETER = re.compile(r"(?:(?:/usr(?:/local)?)?/bin/)?python3?(?:\.\d+)?")
BARE_FLAGS = re.compile(r"-[bBdEIOPqsSuv]+")
SCRIPT = re.compile(r"~?/[\w./-]+")
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
        except (ValueError, RecursionError):
            continue
        if isinstance(row, dict) and isinstance(row.get("ts"), int | float):
            rows.append(row)
    return rows


def kind(row: dict) -> str:
    cls = row.get("class")
    if row.get("v") == VERSION and cls in RADIO + MAIL:
        return cls
    if cls in ALARMS:
        return cls
    if cls == "direct" or (cls != "broadcast" and targets(row)):
        return "call" if row.get("wake") else "post"
    return "newsletter"


def channel(row: dict) -> str:
    return "radio" if kind(row) in RADIO else "mail"


def rank(row: dict) -> int:
    return RADIO.index(kind(row)) if channel(row) == "radio" else len(RADIO)


def ordered(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda row: (rank(row), row["ts"]))


def clock(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts).strftime("%H:%M")


def clip(value: object) -> str:
    return organize("watch").clip(value)


def line(row: dict) -> str:
    if kind(row) == "receipt":
        return f"MAIL CALL {clip(row.get('from'))} read {clock(row['ts'])}: {clip(row.get('text'))}"
    target = f" to {', '.join(clip(name) for name in targets(row))}" if targets(row) else ""
    return (
        f"{channel(row).upper()} {kind(row).upper()} {clock(row['ts'])} "
        f"{clip(row.get('from'))}{target}: {clip(row.get('text'))}"
    )


def capped(rows: list[dict]) -> list[str]:
    picked = sorted(rows, key=lambda row: (rank(row), -row["ts"]))[:SHOWN]
    more = (
        [f"{channel(rows[0]).upper()} {len(rows) - SHOWN} more items: radio.py show --all"]
        if len(rows) > SHOWN
        else []
    )
    return [line(row) for row in ordered(picked)] + more


def targets(row: dict) -> list:
    return row["to"] if isinstance(row.get("to"), list) else []


def sessions_of(row: dict) -> list[str]:
    return listed(row.get("to_sessions"))


def for_me(row: dict, name: str, sid: str) -> bool:
    return row.get("from") != name and (not targets(row) or name in targets(row) or sid in sessions_of(row))


def read_json(path: Path) -> dict:
    try:
        data = json.loads(organize("nofollow").read_text(ROOT, path))
    except (OSError, ValueError, RecursionError):
        return {}
    return data if isinstance(data, dict) else {}


def config() -> dict:
    try:
        data = json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def listed(value: object) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def write_atomic(path: Path, text: str) -> None:
    organize("nofollow").replace(ROOT, path, text, 0o600)


def prompt_mark(sid: str) -> float:
    try:
        return float(organize("nofollow").read_text(ROOT, SEEN / sid))
    except (OSError, ValueError):
        return NEVER


def mark(state: dict, key: str) -> float:
    value = state.get(key)
    return value if isinstance(value, int | float) else NEVER


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


def responders(active: dict) -> list[str]:
    return [active.get("by"), *listed(active.get("helpers"))]


def silence_line(active: dict) -> str:
    helpers = listed(active.get("helpers"))
    helping = f"; helping: {', '.join(clip(name) for name in helpers)}" if helpers else ""
    return (
        f"MAYDAY ACTIVE since {clock(active['since'])} by {clip(active['by'])}: {clip(active['text'])}{helping}; "
        "writing actions wait until radio.py clear unless you help with radio.py assist"
    )


def notify_once(active: dict | None) -> None:
    if active is None:
        return
    try:
        argv = config()["notify"]
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


def unreached(cls: str, to: list[str], sender: str, sessions: list[str]) -> list[str]:
    """Returns:
        Each addressee no live listener of its name or of the row's sessions
        takes the row for, followed by `(session <id>)` when it has sessions.
    """
    live = council().live_sessions()
    if cls in ADDRESSED:
        targets = [(name, [*sessions, *(sid for sid, label in live.items() if name in (label, sid))]) for name in to]
    else:
        targets = [(name or sid, [sid]) for sid, name in live.items() if sid != sender]
    pinned = f" (session {', '.join(sessions)})" if sessions else ""
    return [f"{name}{pinned}" for name, sids in targets if not any(map(listening, sids))]


def store(entries: list[dict]) -> float:
    rows = items()
    ts = time.time()
    if rows:
        ts = max(ts, math.nextafter(max(row["ts"] for row in rows), math.inf))
    for entry in entries:
        entry["ts"] = ts
        ts = math.nextafter(ts, math.inf)
    write_atomic(NEWS, "".join(json.dumps(row) + "\n" for row in [*rows[-(KEPT - len(entries)):], *entries]))
    return entries[-1]["ts"]


def transmit(cls: str, to: list[str], text: str, caller: str | None, sessions: list[str]) -> int:
    """Args:
        sessions: the session ids of the addressees, kept under
            `to_sessions` beside their names; none keeps the row as before.
    """
    if cls in ADDRESSED and not to:
        fail(f"{cls} needs --to")
    if cls not in ADDRESSED and to:
        fail(f"{cls} goes to all; drop --to")
    text = " ".join(text.split())
    if not text:
        fail(f"{cls} needs a text")
    sid, _ = council().caller(caller)
    sender = name_of(sid)
    ROOT.mkdir(parents=True, exist_ok=True)
    with organize("nofollow").locked(ROOT, LOCK, 0o600, None):
        ts = store([{"from": sender, "to": to, "text": text, "class": cls, "v": VERSION, **({"to_sessions": sessions} if sessions else {})}])
        print(f"{STORED}{ts!r}", flush=True)
        if cls == "mayday":
            write_atomic(
                SILENCE,
                json.dumps({"since": ts, "until": ts + SILENCE_SECONDS, "by": sender, "text": text}),
            )
    print(f"sent {cls} to {', '.join(clip(name) for name in to) or 'all'}")
    if cls in RADIO:
        for name in unreached(cls, to, sid, sessions):
            print(f"wake: SendMessage to {clip(name)}")
    return 0


def cmd_send(args: argparse.Namespace) -> int:
    cls = args.cls
    if cls == "direct":
        cls = "call" if args.wake else "post"
    elif args.wake:
        fail("--wake only with direct; a call always wakes")
    return transmit(cls, args.to or [], args.text, args.session, [])


def cmd_post(args: argparse.Namespace) -> int:
    return transmit("post" if args.to else "newsletter", args.to or [], args.text, args.session, [])


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
            print(f"radio silence held by {clip(active['by'])}; only they clear it, anyone else with --force")
            return 3
        SILENCE.unlink(missing_ok=True)
    forced = f", forced by {me}" if active["by"] != me else ""
    print(f"cleared radio silence by {clip(active['by'])}{forced}")
    return 0


def cmd_assist(args: argparse.Namespace) -> int:
    sid, _ = council().caller(args.session)
    me = name_of(sid)
    ROOT.mkdir(parents=True, exist_ok=True)
    with organize("nofollow").locked(ROOT, LOCK, 0o600, None):
        active = silence()
        if active is None:
            print("no radio silence active")
            return 0
        if me not in responders(active):
            active["helpers"] = [*listed(active.get("helpers")), me]
            write_atomic(SILENCE, json.dumps(active))
    print(f"assisting the MAYDAY by {clip(active['by'])}: {clip(active['text'])}")
    return 0


def seen(row: dict, name: str, sid: str, prompt: float, state: dict, since: float) -> bool:
    """Args:
        row: a news.jsonl row with a numeric ts.
        name: the session's name, as name_of() gives it.
        sid: the session's id; a row pinned to it in to_sessions is for it
            under any name.
        prompt: the session's prompt mark, as prompt_mark() gives it.
        state: the session's radio-seen state; the mark of the row's channel
            holds the ts of the newest row the session took on it.
        since: rows at or before it count as taken; the hooks pass the start
            of WINDOW, a reader of the marks alone NEVER.

    Returns:
        Whether the session has taken the row: it is for the session and its
        ts is not after the prompt mark, since or the mark of its channel.
    """
    return for_me(row, name, sid) and not row["ts"] > max(prompt, since, mark(state, channel(row)))


def pending(sid: str, name: str, state: dict, family: str) -> list[dict]:
    prompt, since = prompt_mark(sid), time.time() - WINDOW
    return [row for row in items() if channel(row) == family and for_me(row, name, sid) and not seen(row, name, sid, prompt, state, since)]


def take(sid: str, family: str) -> list[dict]:
    name = name_of(sid)
    with session(sid) as state:
        rows = pending(sid, name, state, family)
        if rows:
            state[family] = max(row["ts"] for row in rows)
            save(sid, state)
    return rows


def acknowledge(sid: str, rows: list[dict]) -> None:
    calls = [
        row
        for row in rows
        if kind(row) == "call" and isinstance(row.get("from"), str) and isinstance(row.get("text"), str)
    ]
    if not calls:
        return
    me = name_of(sid)
    receipts = [
        {"from": me, "to": [row["from"]], "text": row["text"], "class": "receipt", "v": VERSION, "call": row["ts"]}
        for row in calls
    ]
    try:
        with organize("nofollow").locked(ROOT, LOCK, 0o600, SESSION_WAIT):
            store(receipts)
    except OSError:
        return


def cmd_hook(_: argparse.Namespace) -> int:
    try:
        sid = hook_session()
        if not sid:
            return 0
        active = silence()
        rows = take(sid, "radio")
        out = ([silence_line(active)] if active else []) + capped(rows)
        if out:
            print("\n".join(out))
        notify_once(active)
        acknowledge(sid, rows)
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
            rows = pending(sid, name_of(sid), state, "radio")
            state["mtime"] = mtime
            if rows:
                state["radio"] = max(row["ts"] for row in rows)
            save(sid, state)
        if rows:
            context = "\n".join(capped(rows))
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolBatch", "additionalContext": context}}))
            if any(kind(row) == "mayday" for row in rows):
                notify_once(silence())
            acknowledge(sid, rows)
    except Exception:  # noqa: BLE001
        return 0
    return 0


def cmd_mailbox(_: argparse.Namespace) -> int:
    try:
        sid = hook_session()
        rows = take(sid, "mail") if sid else []
    except Exception:  # noqa: BLE001
        return 0
    if not rows:
        return 0
    print("\n".join(capped(rows)), file=sys.stderr)
    return 2


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
                rows = take(sid, "radio")
                if rows:
                    print("\n".join(capped(rows)), file=sys.stderr)
                    notify_once(silence())
                    acknowledge(sid, rows)
                    return 2
            time.sleep(POLL_SECONDS)
    except Exception:  # noqa: BLE001
        return 0
    return 0


def passes(command: str) -> bool:
    if SHELL.search(SINGLE_QUOTED.sub("", command)):
        return False
    try:
        cfg = config()
        if any(re.match(pattern, command) for key in ("never_block", "mayday_allow") for pattern in listed(cfg.get(key))):
            return True
        argv = shlex.split(command)
        if argv and INTERPRETER.fullmatch(argv[0]):
            argv = argv[1:]
            while argv and BARE_FLAGS.fullmatch(argv[0]):
                argv = argv[1:]
        return bool(argv) and bool(SCRIPT.fullmatch(argv[0])) and Path(argv[0]).expanduser().resolve() == SELF
    except (ValueError, RuntimeError, OSError, re.error):
        return False


def cmd_block(_: argparse.Namespace) -> int:
    try:
        payload = json.load(sys.stdin)
        active = silence()
        if active is None:
            return 0
        sid = payload.get("session_id") or os.environ.get("CLAUDE_CODE_SESSION_ID")
        if sid and name_of(sid) in responders(active):
            return 0
        tool = payload.get("tool_name")
        if tool == "Bash" and passes(str((payload.get("tool_input") or {}).get("command") or "")):
            return 0
        if tool != "Bash" and tool not in WRITERS:
            return 0
        reason = (
            f"kvb-org-radio: MAYDAY by {clip(active.get('by'))} holds radio silence: {clip(active.get('text'))}; "
            "writing actions wait until radio.py clear. Read tools, the config's allowed commands and bare "
            "radio.py calls (text in single quotes, no shell operators) still run; "
            "to help fix it, join with radio.py assist first."
        )
    except Exception:  # noqa: BLE001
        return 0
    print(reason, file=sys.stderr)
    return 2


def cmd_show(args: argparse.Namespace) -> int:
    active = silence()
    if active:
        print(silence_line(active))
    if args.all:
        rows = items()
    else:
        sid, _ = council().caller(args.session)
        name = name_of(sid)
        with session(sid) as state:
            rows = ordered(pending(sid, name, state, "radio") + pending(sid, name, state, "mail"))
    for row in rows:
        print(line(row))
    return 0


def feedback_of(chosen: dict, sid: str) -> str:
    return "call" if chosen.get(sid) == "call" else "post"


def cmd_feedback_set(args: argparse.Namespace) -> int:
    sid, _ = council().caller(args.session)
    ROOT.mkdir(parents=True, exist_ok=True)
    with organize("nofollow").locked(ROOT, LOCK, 0o600, None):
        chosen = read_json(FEEDBACK)
        chosen[sid] = args.channel
        write_atomic(FEEDBACK, json.dumps(chosen, sort_keys=True))
    print(f"feedback: {args.channel}")
    return 0


def cmd_feedback_show(args: argparse.Namespace) -> int:
    sid, _ = council().caller(args.session)
    print(feedback_of(read_json(FEEDBACK), sid))
    return 0


def cmd_feedback_send(args: argparse.Namespace) -> int:
    if args.sid and len(args.to) != 1:
        fail("--sid takes a single --to")
    chosen = read_json(FEEDBACK)
    for name in args.to:
        transmit(feedback_of(chosen, args.sid or name), [name], args.text, args.session, [args.sid] if args.sid else [])
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("send")
    p.add_argument("cls", metavar="class", choices=SEND)
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
    p = sub.add_parser("assist")
    p.add_argument("--session")
    p.set_defaults(func=cmd_assist)
    for name, func in (
        ("hook", cmd_hook),
        ("tool", cmd_tool),
        ("mailbox", cmd_mailbox),
        ("listen", cmd_listen),
        ("block", cmd_block),
    ):
        sub.add_parser(name).set_defaults(func=func)
    p = sub.add_parser("show")
    p.add_argument("--all", action="store_true")
    p.add_argument("--session")
    p.set_defaults(func=cmd_show)
    feedback = sub.add_parser("feedback").add_subparsers(dest="action", required=True)
    p = feedback.add_parser("set")
    p.add_argument("channel", choices=FEEDBACKS)
    p.add_argument("--session")
    p.set_defaults(func=cmd_feedback_set)
    p = feedback.add_parser("show")
    p.add_argument("--session")
    p.set_defaults(func=cmd_feedback_show)
    p = feedback.add_parser("send")
    p.add_argument("text")
    p.add_argument("--to", action="append", required=True)
    p.add_argument("--sid")
    p.add_argument("--session")
    p.set_defaults(func=cmd_feedback_send)
    args = parser.parse_args()
    os.environ["PATH"] = organize("hookpath").trusted(os.environ.get("PATH", ""))
    refused = organize("watch").guard_root(hook=args.command in ("hook", "tool", "mailbox", "listen", "block"))
    if refused is not None:
        return refused
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
