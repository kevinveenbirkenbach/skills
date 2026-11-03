#!/usr/bin/env python3
"""Keep the organisation's night mode: one active session, the others relaxed or asleep.

Environment:
    AGENTS_COUNCIL_ROOT: council directory shared by every agent on the host;
        the state is <root>/night.json. /tmp/agents-council unless set.
    CLAUDE_CODE_SESSION_ID: the calling session.

Args:
    set evening|sunset [--session <id>]: start the mode with the caller as the
        active session; prints every other live session as "<id>\t<name>".
    status [--session <id>]: print the mode, the active session, since when,
        and the caller's part (active, awake, relax or sleep).
    wake [--session <id>]: wake the caller alone while the others stay in the
        mode; it then works like the active session.
    clear [--session <id>]: end the mode (sunrise); prints every other live
        session as "<id>\t<name>".

A missing, unreadable or invalid state means day: every agent works.

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
PARTS = {"evening": "relax (kvb-agent-relax)", "sunset": "sleep (kvb-agent-sleep)"}


def council() -> ModuleType:
    spec = importlib.util.spec_from_file_location("council", COUNCIL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load() -> dict | None:
    try:
        state = json.loads(STATE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        state = None
    if (
        not isinstance(state, dict)
        or state.get("mode") not in PARTS
        or not state.get("active")
        or not isinstance(state.get("awake", []), list)
    ):
        print(f"night: {STATE} is unreadable or invalid; treated as day", file=sys.stderr)
        return None
    return state


def peers(live: dict[str, str | None], own: str) -> None:
    for sid, name in sorted(live.items(), key=lambda item: (item[1] or "", item[0])):
        if sid != own:
            print(f"{sid}\t{name or '-'}")


def cmd_set(args: argparse.Namespace, cn: ModuleType) -> int:
    sid, _ = cn.caller(args.session)
    live = cn.live_sessions()
    save(
        {
            "mode": args.mode,
            "active": sid,
            "name": live.get(sid),
            "since": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
            "awake": [],
        }
    )
    peers(live, sid)
    return 0


def save(state: dict) -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=ROOT, delete=False, encoding="utf-8") as handle:
        json.dump(state, handle)
    os.replace(handle.name, STATE)


def cmd_wake(args: argparse.Namespace, cn: ModuleType) -> int:
    sid, _ = cn.caller(args.session)
    state = load()
    if state is None:
        print("mode: day")
        return 0
    if sid != state["active"] and sid not in state.get("awake", []):
        state["awake"] = [*state.get("awake", []), sid]
        save(state)
    print(f"awake: {sid}")
    return 0


def cmd_status(args: argparse.Namespace, _: ModuleType) -> int:
    state = load()
    if state is None:
        print("mode: day")
        return 0
    print(f"mode: {state['mode']}")
    print(f"active: {state.get('name') or '-'} {state['active']}")
    print(f"since: {state.get('since') or '-'}")
    sid = args.session or os.environ.get("CLAUDE_CODE_SESSION_ID")
    if sid == state["active"]:
        print("you: active")
    elif sid in state.get("awake", []):
        print("you: awake")
    elif sid:
        print(f"you: {PARTS[state['mode']]}")
    return 0


def cmd_clear(args: argparse.Namespace, cn: ModuleType) -> int:
    sid, _ = cn.caller(args.session)
    STATE.unlink(missing_ok=True)
    peers(cn.live_sessions(), sid)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("set")
    p.add_argument("mode", choices=sorted(PARTS))
    p.set_defaults(func=cmd_set)
    p = sub.add_parser("status")
    p.set_defaults(func=cmd_status)
    p = sub.add_parser("clear")
    p.set_defaults(func=cmd_clear)
    p = sub.add_parser("wake")
    p.set_defaults(func=cmd_wake)
    for p in sub.choices.values():
        p.add_argument("--session")
    args = parser.parse_args()
    return args.func(args, council())


if __name__ == "__main__":
    sys.exit(main())
