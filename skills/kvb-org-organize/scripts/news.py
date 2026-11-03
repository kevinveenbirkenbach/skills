#!/usr/bin/env python3
"""Share status news between agents without waking them: each session sees it with its next turn.

Environment:
    AGENTS_COUNCIL_ROOT: council directory; the news is <root>/news.jsonl and
        each session's read mark <root>/news-seen/<session id>.
        /tmp/agents-council unless set.
    CLAUDE_CODE_SESSION_ID: the calling session.

Args:
    post "<text>" [--to <name> ...] [--session <id>]: add one item, for every
        session or only the named ones.
    hook: UserPromptSubmit hook; reads the hook JSON on stdin, prints the items
        of the last 24 hours this session has not seen (at most 10, own posts
        left out) and marks them seen. Never fails the prompt.
    show [--all] [--session <id>]: print the unseen items, or every kept one,
        without marking them.

Exit codes:
    0 done, 2 usage error.
"""

from __future__ import annotations

import argparse
import datetime
import fcntl
import importlib.util
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from types import ModuleType

ROOT = Path(os.environ.get("AGENTS_COUNCIL_ROOT", "/tmp/agents-council"))
NEWS = ROOT / "news.jsonl"
SEEN = ROOT / "news-seen"
LOCK = ROOT / "news.lock"
COUNCIL = Path(__file__).resolve().with_name("council.py")
WINDOW = 86400
SHOWN = 10
KEPT = 500


def fail(message: str) -> None:
    print(f"news: {message}", file=sys.stderr)
    sys.exit(2)


def council() -> ModuleType:
    spec = importlib.util.spec_from_file_location("council", COUNCIL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def items() -> list[dict]:
    try:
        lines = NEWS.read_text(encoding="utf-8").splitlines()
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


def unseen(sid: str, name: str | None) -> list[dict]:
    try:
        mark = float((SEEN / sid).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        mark = 0.0
    floor = max(mark, time.time() - WINDOW)
    return [
        row
        for row in items()
        if row["ts"] > floor
        and row.get("from") != name
        and (not row.get("to") or name in row["to"])
    ]


def line(row: dict) -> str:
    stamp = datetime.datetime.fromtimestamp(row["ts"]).strftime("%H:%M")
    target = f" to {', '.join(row['to'])}" if row.get("to") else ""
    return f"NEWS {stamp} {row.get('from', '?')}{target}: {row.get('text', '')}"


def cmd_post(args: argparse.Namespace, cn: ModuleType) -> int:
    sid, _ = cn.caller(args.session)
    text = " ".join(args.text.split())
    if not text:
        fail("post needs a text")
    entry = {"ts": time.time(), "from": cn.live_sessions().get(sid) or sid, "to": args.to or [], "text": text}
    ROOT.mkdir(parents=True, exist_ok=True)
    with LOCK.open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        rows = [*items()[-(KEPT - 1):], entry]
        with tempfile.NamedTemporaryFile("w", dir=ROOT, delete=False, encoding="utf-8") as handle:
            handle.write("".join(json.dumps(row) + "\n" for row in rows))
        os.replace(handle.name, NEWS)
    print(f"posted to {', '.join(entry['to']) or 'all'}")
    return 0


def cmd_hook(_: argparse.Namespace, cn: ModuleType) -> int:
    try:
        payload = json.load(sys.stdin)
        sid = payload.get("session_id") or os.environ.get("CLAUDE_CODE_SESSION_ID")
        if not sid:
            return 0
        rows = unseen(sid, cn.live_sessions().get(sid))
        if not rows:
            return 0
        for row in rows[-SHOWN:]:
            print(line(row))
        if len(rows) > SHOWN:
            print(f"NEWS {len(rows) - SHOWN} older items: news.py show")
        SEEN.mkdir(parents=True, exist_ok=True)
        (SEEN / sid).write_text(str(rows[-1]["ts"]), encoding="utf-8")
    except (OSError, ValueError, AttributeError):
        return 0
    return 0


def cmd_show(args: argparse.Namespace, cn: ModuleType) -> int:
    if args.all:
        rows = items()
    else:
        sid, _ = cn.caller(args.session)
        rows = unseen(sid, cn.live_sessions().get(sid))
    for row in rows:
        print(line(row))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("post")
    p.add_argument("text")
    p.add_argument("--to", action="append")
    p.add_argument("--session")
    p.set_defaults(func=cmd_post)
    sub.add_parser("hook").set_defaults(func=cmd_hook)
    p = sub.add_parser("show")
    p.add_argument("--all", action="store_true")
    p.add_argument("--session")
    p.set_defaults(func=cmd_show)
    args = parser.parse_args()
    return args.func(args, council())


if __name__ == "__main__":
    sys.exit(main())
