#!/usr/bin/env python3
"""Record which account each session works on, for the Agent Orchestrator.

Usage:
    account.py hook: the SessionStart hook; reads the hook payload on stdin.

Environment:
    AGENTS_COUNCIL_ROOT, XDG_STATE_HOME, HOME: the council directory
        councilroot.py resolves.
    HOME: ~/.claude.json, whose oauthAccount.emailAddress is the only field
        read.

Returns:
    Appends {"session", "email"} to <council>/session-accounts.jsonl, mode
    0600, unless the session's last line there already names that email;
    a subagent, a payload without session_id or a ~/.claude.json without
    the field writes nothing. The exit code is 0, so a session never fails
    to start on it.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from types import ModuleType

SESSION_ACCOUNTS = "session-accounts.jsonl"
MODE = 0o600
PROFILE_LIMIT = 32 << 20
EMAIL = re.compile(r"[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63})*\.[A-Za-z]{2,24}")


def sibling(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"kvb_account_{name}", Path(__file__).resolve().parent / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def email_of(profile: Path) -> str | None:
    try:
        with profile.open("rb") as handle:
            raw = handle.read(PROFILE_LIMIT + 1)
        data = json.loads(raw) if len(raw) <= PROFILE_LIMIT else None
    except (OSError, ValueError, RecursionError):
        return None
    account = data.get("oauthAccount") if isinstance(data, dict) else None
    email = account.get("emailAddress") if isinstance(account, dict) else None
    return email if isinstance(email, str) and EMAIL.fullmatch(email) else None


def recorded(nofollow: ModuleType, root: Path, path: Path, session: str) -> str | None:
    try:
        text = nofollow.read_text(root, path)
    except OSError:
        return None
    last = None
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("session") == session:
            last = row.get("email")
    return last


def record(root: Path, payload: object, profile: Path) -> bool:
    """Returns:
        True when a mapping line was appended.
    """
    if not isinstance(payload, dict) or payload.get("agent_id") or not isinstance(payload.get("session_id"), str) or not payload["session_id"]:
        return False
    email = email_of(profile)
    if email is None:
        return False
    nofollow = sibling("nofollow")
    path = root / SESSION_ACCOUNTS
    session = payload["session_id"]
    if recorded(nofollow, root, path, session) == email:
        return False
    root.mkdir(parents=True, exist_ok=True)
    nofollow.append(root, path, json.dumps({"session": session, "email": email}) + "\n", MODE)
    return True


def main() -> int:
    if sys.argv[1:] != ["hook"]:
        print("usage: account.py hook", file=sys.stderr)
        return 2
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0
    try:
        record(sibling("councilroot").root(), payload, Path(os.environ.get("HOME", str(Path.home()))) / ".claude.json")
    except OSError as error:
        print(f"account: {error}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
