#!/usr/bin/env python3
"""Find scripts, tests and skills worth carrying over, and remember every decision.

Exit codes:
    0 done, 2 usage error.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import sys
from pathlib import Path

SCRIPT_SUFFIXES = {".py", ".sh", ".bash", ".js", ".mjs", ".ts", ".rb", ".pl"}
TEST_NAME = re.compile(r"(^test_.+|.+_test|.+\.(spec|test))\.[a-z]+$")
SECRET_NAME = re.compile(
    r"(secret|token|credential|passw|auth|\.env$|id_[a-z0-9]+$|\.pem$|\.key$)", re.IGNORECASE
)
MAX_BYTES = 1_000_000
MAX_DEPTH = 1
REPO_MARKERS = {".git", "roles", "plugins", "pyproject.toml", "package.json", "Makefile"}
HOME_SOURCES = {
    ".claude/skills": "skill",
    ".agents/skills": "skill",
    ".codex/skills": "skill",
    ".claude/commands": "command",
    ".claude/agents": "agent",
    ".claude/hooks": "script",
    ".claude/scripts": "script",
    ".codex/rules": "rule",
}
SETTLED = ("carried", "dropped")
VERDICTS = (*SETTLED, "later")


def fail(message: str) -> None:
    print(f"transcend: {message}", file=sys.stderr)
    sys.exit(2)


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    files = sorted(p for p in path.rglob("*") if p.is_file()) if path.is_dir() else [path]
    for file in files:
        sha.update(str(file.relative_to(path) if path.is_dir() else file.name).encode())
        sha.update(file.read_bytes())
    return sha.hexdigest()


def file_kind(path: Path) -> str | None:
    if SECRET_NAME.search(path.name) or path.stat().st_size > MAX_BYTES:
        return None
    if TEST_NAME.match(path.name):
        return "test"
    if path.suffix in SCRIPT_SUFFIXES or os.access(path, os.X_OK):
        return "script"
    return None


def session_names(home: Path) -> dict[str, str]:
    names = {}
    for path in (home / ".claude" / "sessions").glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if data.get("sessionId"):
            names[data["sessionId"]] = data.get("name") or data["sessionId"]
    return names


def scratch_candidates(root: Path, source: str, owner: str) -> list[dict]:
    found = []
    for current, dirs, files in os.walk(root):
        here = Path(current)
        depth = len(here.relative_to(root).parts)
        if depth and REPO_MARKERS & {*dirs, *files}:
            dirs.clear()
            continue
        if depth >= MAX_DEPTH:
            dirs.clear()
        for name in files:
            kind = file_kind(here / name)
            if kind:
                found.append(
                    {"source": source, "owner": owner, "kind": kind, "path": str(here / name)}
                )
    return sorted(found, key=lambda item: item["path"])


def shipped(skills_repo: Path) -> set[str]:
    names = {p.name for p in (skills_repo / "skills").iterdir() if p.is_dir()}
    lock = json.loads((skills_repo / "skills-lock.json").read_text(encoding="utf-8"))
    return names | set(lock.get("skills", {}))


def home_candidates(home: Path, skills_repo: Path) -> list[dict]:
    known = shipped(skills_repo)
    found = []
    for sub, kind in HOME_SOURCES.items():
        base = home / sub
        if not base.is_dir():
            continue
        for entry in sorted(base.iterdir()):
            if entry.name.startswith(".") or SECRET_NAME.search(entry.name):
                continue
            if kind == "skill" and (entry.name in known or not (entry / "SKILL.md").is_file()):
                continue
            if kind != "skill" and not entry.is_file():
                continue
            found.append({"source": "home", "owner": "operator", "kind": kind, "path": str(entry)})
    return found


def load_state(path: Path) -> dict[str, dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except ValueError:
        fail(f"{path} is not valid JSON")


def cmd_scan(args: argparse.Namespace) -> int:
    session = Path(args.session_dir).resolve()
    home = Path(args.home)
    names = session_names(home)
    candidates = scratch_candidates(session, "own", "self")
    for scratch in sorted(Path(args.peers_root).glob("*/*/scratchpad")):
        if scratch.resolve() == session:
            continue
        sid = scratch.parent.name
        candidates += scratch_candidates(scratch, "peer", names.get(sid, sid))
    candidates += home_candidates(home, Path(args.skills_repo))

    state = load_state(Path(args.state))
    offered = []
    for item in candidates:
        seen = state.get(item["path"])
        item["digest"] = digest(Path(item["path"]))
        if seen and seen["verdict"] in SETTLED and seen["digest"] == item["digest"]:
            continue
        item["previous"] = seen["verdict"] if seen else None
        offered.append(item)
    if args.json:
        print(json.dumps(offered, indent=1))
    else:
        for item in offered:
            note = f"\t(was {item['previous']})" if item["previous"] else ""
            print(f"{item['source']}\t{item['owner']}\t{item['kind']}\t{item['path']}{note}")
    return 0


def cmd_mark(args: argparse.Namespace) -> int:
    target = Path(args.path)
    if not target.exists():
        fail(f"{target} does not exist")
    state_path = Path(args.state)
    state = load_state(state_path)
    state[str(target)] = {
        "verdict": args.verdict,
        "digest": digest(target),
        "at": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
    }
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = state_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(state_path)
    print(f"{args.verdict} {target}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("scan")
    p.add_argument("--state", required=True)
    p.add_argument("--skills-repo", required=True)
    p.add_argument("--session-dir", required=True)
    p.add_argument("--peers-root", required=True)
    p.add_argument("--home", required=True)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_scan)
    p = sub.add_parser("mark")
    p.add_argument("--state", required=True)
    p.add_argument("path")
    p.add_argument("verdict", choices=VERDICTS)
    p.set_defaults(func=cmd_mark)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
