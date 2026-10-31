#!/usr/bin/env python3
"""Log subagent spawns with their quality feedback, and evaluate the table.

Usage:
    log.py spawn      hook (PreToolUse on Agent): append the spawn line
    log.py feedback --description D --completed yes|no --tests pass|fail|none --redo yes|no
                      rate the latest spawn with this Agent description
    log.py followup --description D --text T
                      record an operator follow-up question or correction on it
    log.py persist    hook (PostToolUse on Bash): append the one line a sandboxed
                      feedback or followup printed as `pending: <json>`, only
                      when the command was that bare call and the line is
                      well-formed and from the hook's own session
    log.py report     runs, rated runs and same-result rate per task class,
                      model and effort; a row qualifies at >= 90 % over >= 20

Environment:
    SUBAGENT_MODEL_LOG: the log shared by every session;
        ~/.local/state/agents-council/subagent-model.jsonl unless set.
    CLAUDE_CODE_SESSION_ID: the session that rates its spawns.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shlex
import sys
from pathlib import Path

LOG = Path(
    os.environ.get(
        "SUBAGENT_MODEL_LOG",
        str(Path.home() / ".local" / "state" / "agents-council" / "subagent-model.jsonl"),
    )
)
TASK_CLASS = re.compile(r"^task-class:\s*(\S+)", re.MULTILINE)
PENDING = "pending: "
SCRIPT = "kvb-org-perform/scripts/log.py"
CONTROL = re.compile(r"^[();<>|&]+$")
KEYS = {
    "feedback": {"kind", "time", "session", "description", "completed", "tests", "redo"},
    "followup": {"kind", "time", "session", "description", "text"},
}
QUALIFY_RUNS = 20
QUALIFY_RATE = 0.9


def now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")


def append(line: dict) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(line, sort_keys=True) + "\n")


def record(line: dict) -> int:
    try:
        append(line)
    except OSError:
        print(PENDING + json.dumps(line, sort_keys=True))
    return 0


def cmd_spawn() -> int:
    payload = json.load(sys.stdin)
    tool = payload.get("tool_input") or {}
    match = TASK_CLASS.search(tool.get("prompt", ""))
    append({
        "kind": "spawn",
        "time": now(),
        "session": payload.get("session_id", ""),
        "description": tool.get("description", ""),
        "subagent_type": tool.get("subagent_type") or "general-purpose",
        "task_class": match.group(1) if match else "unclassified",
        "model": tool.get("model") or "default",
        "effort": tool.get("effort") or "default",
    })
    return 0


def rated(kind: str, args: argparse.Namespace, **fields: object) -> dict:
    session = os.environ.get("CLAUDE_CODE_SESSION_ID")
    if not session:
        sys.exit("log.py: CLAUDE_CODE_SESSION_ID is not set")
    return {"kind": kind, "time": now(), "session": session, "description": args.description, **fields}


def invoked_kind(command: str) -> str | None:
    if "$(" in command or "`" in command:
        return None
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        return None
    if any(CONTROL.match(token) for token in tokens):
        return None
    if tokens[:1] in (["python3"], ["python"]):
        tokens = tokens[1:]
    if len(tokens) < 2 or not tokens[0].endswith(SCRIPT) or tokens[1] not in KEYS:
        return None
    return tokens[1]


def well_formed(line: object, kind: str, session: str) -> bool:
    if not isinstance(line, dict) or set(line) != KEYS[kind] or line["kind"] != kind or line["session"] != session:
        return False
    if not all(isinstance(line[key], str) for key in ("time", "description")):
        return False
    if kind == "feedback":
        return isinstance(line["completed"], bool) and isinstance(line["redo"], bool) and line["tests"] in ("pass", "fail", "none")
    return isinstance(line["text"], str)


def cmd_persist() -> int:
    payload = json.load(sys.stdin)
    kind = invoked_kind((payload.get("tool_input") or {}).get("command", ""))
    if not kind:
        return 0
    response = payload.get("tool_response")
    stdout = response.get("stdout", "") if isinstance(response, dict) else str(response or "")
    pending = [text[len(PENDING):] for text in stdout.splitlines() if text.startswith(PENDING)]
    if len(pending) != 1:
        return 0
    try:
        line = json.loads(pending[0])
    except json.JSONDecodeError:
        return 0
    if well_formed(line, kind, payload.get("session_id", "")):
        append(line)
    return 0


def runs() -> list[dict]:
    current: dict[tuple[str, str], dict] = {}
    found: list[dict] = []
    for text in LOG.read_text(encoding="utf-8").splitlines() if LOG.exists() else []:
        line = json.loads(text)
        key = (line["session"], line["description"])
        if line["kind"] == "spawn":
            current[key] = {**line, "feedback": None, "followups": 0}
            found.append(current[key])
        elif key in current and line["kind"] == "feedback":
            current[key]["feedback"] = line
        elif key in current and line["kind"] == "followup":
            current[key]["followups"] += 1
    return found


def same_result(run: dict) -> bool:
    feedback = run["feedback"]
    return feedback["completed"] and not feedback["redo"] and feedback["tests"] != "fail" and not run["followups"]


def cmd_report() -> int:
    rows: dict[tuple[str, str, str], list[dict]] = {}
    for run in runs():
        rows.setdefault((run["task_class"], run["model"], run["effort"]), []).append(run)
    print("task_class\tmodel\teffort\truns\trated\tsame\trate\tqualifies")
    for (task_class, model, effort), group in sorted(rows.items()):
        rated_runs = [r for r in group if r["feedback"]]
        same = sum(map(same_result, rated_runs))
        rate = same / len(rated_runs) if rated_runs else 0.0
        qualifies = len(rated_runs) >= QUALIFY_RUNS and rate >= QUALIFY_RATE
        print(f"{task_class}\t{model}\t{effort}\t{len(group)}\t{len(rated_runs)}\t{same}\t{rate:.0%}\t{'yes' if qualifies else 'no'}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("spawn")
    feedback = sub.add_parser("feedback")
    feedback.add_argument("--description", required=True)
    feedback.add_argument("--completed", required=True, choices=("yes", "no"))
    feedback.add_argument("--tests", required=True, choices=("pass", "fail", "none"))
    feedback.add_argument("--redo", required=True, choices=("yes", "no"))
    followup = sub.add_parser("followup")
    followup.add_argument("--description", required=True)
    followup.add_argument("--text", required=True)
    sub.add_parser("persist")
    sub.add_parser("report")
    args = parser.parse_args()
    if args.command == "spawn":
        return cmd_spawn()
    if args.command == "feedback":
        return record(rated(
            "feedback", args, completed=args.completed == "yes", tests=args.tests, redo=args.redo == "yes"
        ))
    if args.command == "followup":
        return record(rated("followup", args, text=args.text))
    if args.command == "persist":
        return cmd_persist()
    return cmd_report()


if __name__ == "__main__":
    sys.exit(main())
