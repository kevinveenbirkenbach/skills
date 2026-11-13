from __future__ import annotations

import json
import math
import re

from .errors import ToolError
from .signed import limits, signing

WAIT_CAP = 300
TEXT_LIMIT = 20_000
COMMAND_LIMIT = 4000
PATH_LIMIT = limits.PATH_LIMIT
NAME_LIMIT = 120
COUNT = re.compile(r"[0-9]{1,12}")
PATH = re.compile(rf"/[^\x00-\x1f\x7f]{{0,{PATH_LIMIT - 1}}}")
LINE = r"(?=[^\x00-\x1f\x7f]*\S)[^\x00-\x1f\x7f]{{1,{0}}}"
ORDER_NAME = re.compile(r"(?![\s-])[^,\x00-\x1f\x7f]{1,200}")
FIELDS = {
    "repo": (PATH, "an absolute path"),
    "worktree": (PATH, "an absolute path"),
    "page": (PATH, "an absolute path"),
    "branch": (re.compile(r"[\w./@+-]{1,255}"), "a branch name"),
    "tree": (re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}"), "the hash git write-tree prints"),
    "title": (re.compile(LINE.format(200)), "one line of 1 to 200 characters"),
    "agent": (re.compile(LINE.format(200)), "one line of 1 to 200 characters"),
    "to": (re.compile(LINE.format(200)), "an agent name, one line of 1 to 200 characters"),
    "label": (re.compile(LINE.format(NAME_LIMIT)), f"one line of 1 to {NAME_LIMIT} characters"),
    "tool": (re.compile(LINE.format(200)), "one line of 1 to 200 characters"),
    "id": (re.compile(r"[0-9a-f]{16}"), "an id the Agent Orchestrator returned"),
}


def expect(arguments: dict, names: tuple[str, ...]) -> None:
    problems = [f"missing argument {name}" for name in names if name not in arguments]
    problems += [f"unknown argument {key}" for key in sorted(map(str, arguments)) if key not in names]
    if problems:
        raise ToolError("; ".join(problems))


def field(arguments: dict, name: str) -> str:
    pattern, hint = FIELDS[name]
    value = arguments[name]
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ToolError(f"{name} must be {hint}")
    visible({name: value})
    return value


def visible(value: object) -> None:
    """Args:
        value: an object of named texts, or a list of them, that reaches a
            signed payload or the approval prompt.

    Raises:
        ToolError with the reason signing.hidden_problem() gives for the
        first text holding an invisible, format, control or look-alike
        character.
    """
    hidden = signing.hidden_problem(value, "value")
    if hidden:
        raise ToolError(hidden)


def bounded(arguments: dict, name: str, limit: int) -> str:
    value = arguments[name]
    if not isinstance(value, str) or len(value) > limit:
        raise ToolError(f"{name} must be text of at most {limit} characters")
    return value


def message_text(arguments: dict, name: str) -> str:
    value = bounded(arguments, name, TEXT_LIMIT)
    if not value.strip():
        raise ToolError(f"{name} must not be empty")
    return value.strip()


def seconds(arguments: dict, name: str, cap: float) -> float:
    value = arguments[name]
    if isinstance(value, bool) or not isinstance(value, int | float) or not 0 <= value < math.inf:
        raise ToolError(f"{name} must be a finite number of seconds, 0 or more")
    return float(min(value, cap))


def decode(body: bytes) -> dict:
    try:
        data = json.loads(body)
    except (ValueError, RecursionError):
        raise ToolError("body must be a JSON object") from None
    if not isinstance(data, dict):
        raise ToolError("body must be a JSON object")
    return data


def single(query: dict[str, list[str]], name: str) -> str | None:
    values = query.get(name)
    if values is None:
        return None
    if len(values) != 1:
        raise ToolError(f"{name} must be given once")
    return values[0]


def instant(query: dict[str, list[str]], name: str) -> float | None:
    text = single(query, name)
    if text is None or text == "":
        return None
    try:
        value = float(text)
    except ValueError:
        raise ToolError(f"{name} must be seconds since the epoch") from None
    if not 0 <= value < 1e11:
        raise ToolError(f"{name} must be seconds since the epoch")
    return value


def whole(query: dict[str, list[str]], name: str) -> int | None:
    text = single(query, name)
    if text is None or text == "":
        return None
    if not COUNT.fullmatch(text):
        raise ToolError(f"{name} must be a whole number")
    return int(text)
