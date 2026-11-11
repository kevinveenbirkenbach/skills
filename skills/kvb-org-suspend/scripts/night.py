#!/usr/bin/env python3
"""Keep the organisation's night mode: one active session, the others drained or suspended.

Environment:
    AGENTS_COUNCIL_ROOT: council directory shared by every agent on the host;
        the state is <root>/night.json. /tmp/agents-council unless set.
    CLAUDE_CODE_SESSION_ID: the calling session.

Args:
    drain|suspend [--session <id>]: start the mode with the caller as the
        active session; prints every other live session as "<id>\t<name>".
    drain|suspend --target=<id> [--target=<id> ...] [--session <id>]: put
        only these sessions into the part, by day too; the mode and every
        other session keep theirs. Prints the targets as "<id>\t<name>".
    status [--session <id>]: print the mode, the active session, since when,
        and the caller's part (active, resumed, drain or suspend); a session
        without a part by day gets no "you:" line.
    resume [--session <id>]: end the mode and every part; prints every other
        live session as "<id>\t<name>".
    resume --target=<id> [--target=<id> ...] [--session <id>]: lift these
        sessions' parts; during a mode they work like the active session.
    resume --alone [--session <id>]: resume the caller alone while the others
        stay in the mode; it then works like the active session.

A missing, unreadable or invalid state means day: every agent works. A
session's own part (night.json "parts") outranks the mode. A state written
before the rename (mode evening or sunset, resumed sessions under awake)
reads as drain or suspend.

Exit codes:
    0 done, 2 usage error.
"""

from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path
from types import ModuleType

ROOT = Path(os.environ.get("AGENTS_COUNCIL_ROOT", "/tmp/agents-council"))
STATE = ROOT / "night.json"
COUNCIL = Path(__file__).resolve().parents[2] / "kvb-org-organize" / "scripts" / "council.py"
PARTS = {"drain": "drain (kvb-agent-drain)", "suspend": "suspend (kvb-agent-suspend)"}
RENAMED = {"evening": "drain", "sunset": "suspend"}


def council() -> ModuleType:
    spec = importlib.util.spec_from_file_location("council", COUNCIL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def migrated(state: object) -> object:
    if not isinstance(state, dict):
        return state
    state = dict(state)
    if isinstance(state.get("mode"), str):
        state["mode"] = RENAMED.get(state["mode"], state["mode"])
    if "awake" in state:
        state.setdefault("resumed", state.pop("awake"))
    return state


def valid(state: object) -> bool:
    if not isinstance(state, dict):
        return False
    parts = state.get("parts", {})
    if not isinstance(parts, dict) or not all(isinstance(mode, str) and mode in PARTS for mode in parts.values()):
        return False
    if "mode" not in state:
        return bool(parts)
    return (
        isinstance(state["mode"], str)
        and state["mode"] in PARTS
        and bool(state.get("active"))
        and isinstance(state.get("resumed", []), list)
    )


def load() -> dict | None:
    try:
        state = migrated(json.loads(STATE.read_text(encoding="utf-8")))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        state = None
    if not valid(state):
        print(f"night: {STATE} is unreadable or invalid; treated as day", file=sys.stderr)
        return None
    return state


def part_of(state: dict, sid: str) -> str | None:
    if sid in state.get("parts", {}):
        return state["parts"][sid]
    if "mode" not in state:
        return None
    if sid == state["active"]:
        return "active"
    if sid in state.get("resumed", []):
        return "resumed"
    return state["mode"]


def released(state: dict, sids: list[str]) -> dict:
    state = {**state, "parts": {sid: mode for sid, mode in state.get("parts", {}).items() if sid not in sids}}
    if "mode" in state:
        resumed = state.get("resumed", [])
        state["resumed"] = [*resumed, *(sid for sid in dict.fromkeys(sids) if sid != state["active"] and sid not in resumed)]
    return state


def peers(live: dict[str, str | None], own: str) -> None:
    for sid, name in sorted(live.items(), key=lambda item: (item[1] or "", item[0])):
        if sid != own:
            print(f"{sid}\t{name or '-'}")


def cmd_set(args: argparse.Namespace, cn: ModuleType) -> int:
    sid, _ = cn.caller(args.session)
    live = cn.live_sessions()
    if args.target:
        state = load() or {}
        save({**state, "parts": {**state.get("parts", {}), **dict.fromkeys(args.target, args.command)}})
        peers({target: live.get(target) for target in args.target}, "")
        return 0
    save(
        {
            "mode": args.command,
            "active": sid,
            "name": live.get(sid),
            "since": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
            "resumed": [],
        }
    )
    peers(live, sid)
    return 0


def save(state: dict) -> None:
    if "mode" not in state and not state.get("parts"):
        STATE.unlink(missing_ok=True)
        return
    ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=ROOT, delete=False, encoding="utf-8") as handle:
        json.dump(state, handle)
    os.replace(handle.name, STATE)


def resume_alone(sid: str) -> int:
    state = load()
    if state is None:
        print("mode: day")
        return 0
    save(released(state, [sid]))
    print(f"resumed: {sid}")
    return 0


def cmd_status(args: argparse.Namespace, _: ModuleType) -> int:
    state = load() or {}
    print(f"mode: {state.get('mode', 'day')}")
    if "mode" in state:
        print(f"active: {state.get('name') or '-'} {state['active']}")
        print(f"since: {state.get('since') or '-'}")
    sid = args.session or os.environ.get("CLAUDE_CODE_SESSION_ID")
    part = part_of(state, sid) if sid else None
    if part:
        print(f"you: {PARTS.get(part, part)}")
    return 0


def cmd_resume(args: argparse.Namespace, cn: ModuleType) -> int:
    sid, _ = cn.caller(args.session)
    if args.alone:
        return resume_alone(sid)
    if args.target:
        save(released(load() or {}, args.target))
        peers({target: cn.live_sessions().get(target) for target in args.target}, "")
        return 0
    STATE.unlink(missing_ok=True)
    peers(cn.live_sessions(), sid)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for mode in PARTS:
        p = sub.add_parser(mode)
        p.add_argument("--target", action="append")
        p.set_defaults(func=cmd_set)
    p = sub.add_parser("status")
    p.set_defaults(func=cmd_status)
    p = sub.add_parser("resume")
    alone = p.add_mutually_exclusive_group()
    alone.add_argument("--alone", action="store_true")
    alone.add_argument("--target", action="append")
    p.set_defaults(func=cmd_resume)
    for p in sub.choices.values():
        p.add_argument("--session")
    args = parser.parse_args()
    return args.func(args, council())


if __name__ == "__main__":
    sys.exit(main())
