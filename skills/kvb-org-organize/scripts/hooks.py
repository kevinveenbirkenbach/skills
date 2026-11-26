#!/usr/bin/env python3
"""Run the skills' Bash hooks in one interpreter.

pre-bash   radio.py block, watch.py block, queue.py block, graph.py hook
post-bash  watch.py watch, log.py persist

Every handler reads the same hook event; exit 2 of any handler blocks with the
stderr of each handler that exited 2, otherwise their JSON answers merge.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import traceback
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
BLOCK = 2
HANDLERS = {
    "pre-bash": (
        ("kvb-org-radio/scripts/radio.py", "block"),
        ("kvb-org-organize/scripts/watch.py", "block"),
        ("kvb-org-queue/scripts/queue.py", "block"),
        ("kvb-agent-optimize/scripts/graph.py", "hook"),
    ),
    "post-bash": (
        ("kvb-org-organize/scripts/watch.py", "watch"),
        ("kvb-org-perform/scripts/log.py", "persist"),
    ),
}
RANK = {"allow": 0, "ask": 1, "deny": 2}
JOINED = ("additionalContext", "systemMessage")


def exit_code(stop: SystemExit) -> int:
    if stop.code is None or isinstance(stop.code, int):
        return stop.code or 0
    print(stop.code, file=sys.stderr)
    return 1


def handle(script: str, sub: str, raw: str) -> tuple[int, str, str]:
    """Args:
        script: the handler's path below SKILLS.
        sub: the subcommand its main() parses.
        raw: the hook event, given to the handler as its stdin.

    Returns:
        The handler's exit code, stdout and stderr; a missing script answers
        0 without output, a crash 1 with its traceback.
    """
    path = SKILLS / script
    if not path.is_file():
        return 0, "", ""
    out, err = io.StringIO(), io.StringIO()
    sys.argv, sys.stdin = [str(path), sub], io.StringIO(raw)
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            name = f"kvb_hook_{path.parent.parent.name.replace('-', '_')}_{path.stem}"
            spec = importlib.util.spec_from_file_location(name, path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
            code = module.main()
        except SystemExit as stop:
            code = exit_code(stop)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            code = 1
    return code if isinstance(code, int) else 1, out.getvalue(), err.getvalue()


def merge_specific(into: dict, given: dict) -> None:
    decision = given.get("permissionDecision")
    held = into.get("permissionDecision")
    if decision in RANK and (held not in RANK or RANK[decision] > RANK[held]):
        into["permissionDecision"], into["permissionDecisionReason"] = decision, given.get("permissionDecisionReason", "")
    elif decision in RANK and decision == held and given.get("permissionDecisionReason"):
        into["permissionDecisionReason"] = "\n".join(filter(None, (into.get("permissionDecisionReason"), given["permissionDecisionReason"])))
    for key, value in given.items():
        if key in ("permissionDecision", "permissionDecisionReason"):
            continue
        if key in JOINED and isinstance(value, str) and isinstance(into.get(key), str):
            into[key] = f"{into[key]}\n{value}"
        else:
            into.setdefault(key, value)


def merged(outputs: list[str]) -> tuple[dict, list[str]]:
    """Returns:
        One hook answer from the handlers' JSON objects, and every other
        non-empty stdout text, which a hook answer cannot carry.
    """
    answer: dict = {}
    loose = []
    for text in filter(None, (output.strip() for output in outputs)):
        try:
            given = json.loads(text)
        except ValueError:
            given = None
        if not isinstance(given, dict):
            loose.append(text)
            continue
        for key, value in given.items():
            if key == "hookSpecificOutput" and isinstance(value, dict) and isinstance(answer.get(key, {}), dict):
                merge_specific(answer.setdefault(key, {}), value)
            elif key in JOINED and isinstance(value, str) and isinstance(answer.get(key), str):
                answer[key] = f"{answer[key]}\n{value}"
            else:
                answer.setdefault(key, value)
    return answer, loose


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in HANDLERS:
        print(f"usage: hooks.py {'|'.join(HANDLERS)}", file=sys.stderr)
        return 1
    stdin, stdout, stderr = sys.stdin, sys.stdout, sys.stderr
    raw = stdin.read()
    results = [handle(script, sub, raw) for script, sub in HANDLERS[sys.argv[1]]]
    sys.stdin = stdin
    blocked = [err for code, _, err in results if code == BLOCK]
    if blocked:
        stderr.write("".join(blocked))
        return BLOCK
    answer, loose = merged([out for _, out, _ in results])
    stderr.write("".join(err for _, _, err in results) + "".join(f"{text}\n" for text in loose))
    if answer:
        stdout.write(json.dumps(answer) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
