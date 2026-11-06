#!/usr/bin/env python3
"""Tell every agent which skills changed and how to use them: one newsletter per update.

Environment:
    AGENTS_COUNCIL_ROOT: council directory shared by every agent on the host;
        /tmp/agents-council unless set. The last announced revision per
        repository lives in <root>/skills-announced.json.
    CLAUDE_CODE_SESSION_ID: the sending session, passed on to radio.py.

Args:
    --repo <dir>: the skills repository whose skills/ changes are announced.
    --since <rev>: announce from this revision instead of the last announced
        one. Without either, the run only records HEAD as announced.
    --dry-run: print the newsletter without sending or recording it.
    --session <id>: the sending session for radio.py.

Exit codes:
    0 sent, recorded or nothing new; 1 radio.py failed; 2 usage error or a
    council directory others can write.
"""

from __future__ import annotations

import argparse
import functools
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(os.environ.get("AGENTS_COUNCIL_ROOT", "/tmp/agents-council"))
ANNOUNCED = ROOT / "skills-announced.json"
SKILLS = Path(__file__).resolve().parents[2]
RADIO = SKILLS / "kvb-org-radio" / "scripts" / "radio.py"
ORGANIZE = SKILLS / "kvb-org-organize" / "scripts"
GIT = ("git", "-c", "maintenance.auto=false")
SUBJECTS = 3


@functools.cache
def organize(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"kvb_update_{name}", ORGANIZE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(repo: Path, *args: str) -> str:
    return subprocess.run([*GIT, *args], cwd=repo, capture_output=True, text=True, check=True).stdout


def revision(repo: Path, rev: str) -> str:
    try:
        return git(repo, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}").strip()
    except subprocess.CalledProcessError:
        print(f"update: {rev} is no commit of {repo}; pass --since <rev>", file=sys.stderr)
        sys.exit(2)


def marks() -> dict:
    try:
        data = json.loads(organize("nofollow").read_text(ROOT, ANNOUNCED))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def record(repo: Path, head: str) -> None:
    organize("nofollow").replace(ROOT, ANNOUNCED, json.dumps({**marks(), str(repo): head}), 0o600)


def changes(repo: Path, base: str) -> dict[str, list[str]]:
    paths = git(repo, "diff", "--name-only", f"{base}..HEAD", "--", "skills/").splitlines()
    names = sorted({Path(path).parts[1] for path in paths if len(Path(path).parts) > 2})
    return {name: git(repo, "log", "--format=%s", f"{base}..HEAD", "--", f"skills/{name}").splitlines() for name in names}


def summary(repo: Path, name: str, subjects: list[str]) -> str:
    if not (repo / "skills" / name).is_dir():
        return f"{name} (removed)"
    more = [f"+{len(subjects) - SUBJECTS} more"] if len(subjects) > SUBJECTS else []
    return f"{name} ({'; '.join(subjects[:SUBJECTS] + more)})"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--since")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--session")
    args = parser.parse_args()
    refused = organize("watch").guard_root(hook=False)
    if refused is not None:
        return refused
    repo = args.repo.resolve()
    head = revision(repo, "HEAD")
    base = revision(repo, args.since) if args.since else marks().get(str(repo))
    if base is None:
        if not args.dry_run:
            record(repo, head)
        print(f"recorded {head[:7]} as announced; nothing sent")
        return 0
    found = changes(repo, base)
    if not found:
        if not args.dry_run:
            record(repo, head)
        print("nothing new")
        return 0
    text = (
        f"Skills updated {base[:7]}..{head[:7]}: "
        f"{', '.join(summary(repo, name, subjects) for name, subjects in found.items())}. "
        "Re-read each changed SKILL.md before its next use."
    )
    print(text)
    if args.dry_run:
        return 0
    session = ["--session", args.session] if args.session else []
    if subprocess.run([sys.executable, str(RADIO), "post", text, *session], check=False).returncode != 0:
        return 1
    record(repo, head)
    return 0


if __name__ == "__main__":
    sys.exit(main())
