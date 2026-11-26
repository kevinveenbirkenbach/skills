from __future__ import annotations

import os
import threading
from pathlib import Path

from .council import HUMAN, agent, ordered
from .fields import DESCRIPTION_LIMIT, OPTION_LIMIT, ORDER_NAME
from .records import read_json, shown

LABEL_LIMIT = 80

REGISTER = "rasci.json"
AGENT_ORDER = "agent-order.json"
OPERATOR = "operator/"
ENDED = ("done", "stopped")
PARSED_KEPT = 8
parsed: dict[Path, tuple[tuple[int, int, int], dict[str, dict]]] = {}
parsed_lock = threading.Lock()


def read_register(path: Path) -> dict[str, dict]:
    """Returns:
        The task rows of the register, parsed again only when its inode, size
        or mtime changed; a fresh top-level dict per call whose rows are
        shared between callers and read only.
    """
    try:
        info = os.lstat(path)
    except OSError:
        return {}
    stamp = (info.st_ino, info.st_size, info.st_mtime_ns)
    with parsed_lock:
        found = parsed.get(path)
        if found is not None and found[0] == stamp:
            return dict(found[1])
    data = read_json(path)
    rows = {task: row for task, row in data.items() if isinstance(row, dict)} if isinstance(data, dict) else {}
    with parsed_lock:
        parsed.pop(path, None)
        parsed[path] = (stamp, rows)
        while len(parsed) > PARSED_KEPT:
            parsed.pop(next(iter(parsed)))
    return dict(rows)


def status_of(row: dict) -> str:
    if "status" not in row:
        return "queued"
    return str(row["status"])


def holders(row: dict, letter: str) -> str:
    roles = row.get("roles")
    if not isinstance(roles, dict):
        return "-"
    names = sorted((str(p) for p, v in roles.items() if isinstance(v, str) and letter in v), key=str.lower)
    return shown(", ".join(names))


def parties(row: dict) -> dict[str, str]:
    roles = row.get("roles")
    if not isinstance(roles, dict):
        return {}
    found: dict[str, str] = {}
    for party, letters in roles.items():
        name = agent(party)
        if name and isinstance(letters, str):
            found[name] = found.get(name, "") + letters
    return found


def adder(row: dict) -> str:
    return next((name for name, letters in parties(row).items() if "A" in letters and name != HUMAN), "")


def is_open(task: str, row: dict, operator: bool) -> bool:
    return task.startswith(OPERATOR) == operator and status_of(row) not in ENDED


def row_options(row: dict) -> list[dict]:
    """Args:
        row: an operator row of the register, which agents write.

    Returns:
        A decision row's options as {"label", "description"}, at most
        OPTION_LIMIT, each label one non-empty line of at most LABEL_LIMIT
        characters and unique; [] for any other row or malformed options.
    """
    raw = row.get("options")
    if row.get("check") != "decision" or not isinstance(raw, list):
        return []
    options = []
    for option in raw[:OPTION_LIMIT]:
        label = option.get("label") if isinstance(option, dict) else None
        description = option.get("description", "") if isinstance(option, dict) else None
        if isinstance(label, str) and isinstance(description, str) and label.strip() and label.isprintable() and len(label) <= LABEL_LIMIT:
            options.append({"label": label.strip(), "description": " ".join(description.split())[:DESCRIPTION_LIMIT]})
    labels = [option["label"] for option in options]
    return options if len(set(labels)) == len(labels) else []


def operator_rows(tasks: dict[str, dict]) -> list[dict]:
    rows = []
    for task, row in sorted(tasks.items()):
        if not is_open(task, row, True):
            continue
        options = row_options(row)
        recommended = row.get("recommended")
        rows.append({
            "task": task,
            "command": shown(row.get("title")),
            "directory": shown(row.get("workdir")),
            "why": shown(row.get("description")),
            "check": shown(row.get("check")),
            "status": status_of(row),
            "options": options,
            "recommended": recommended if recommended in [option["label"] for option in options] else "",
        })
    return rows


def runnable(row: dict) -> bool:
    return row["command"] != "-" and row["directory"].startswith("/") and row["check"] != "decision"


def pinned(item: tuple[str, dict]) -> tuple[bool, int, str]:
    task, row = item
    prio = row.get("prio")
    if isinstance(prio, int) and not isinstance(prio, bool):
        return False, prio, task
    return True, 0, task


def register_row(task: str, row: dict) -> dict:
    results = row.get("key_results")
    if not isinstance(results, list):
        results = []
    return {
        "task": task,
        "title": shown(row.get("title")),
        "status": status_of(row),
        "worker": shown(row.get("worker")),
        "responsible": holders(row, "R"),
        "accountable": holders(row, "A"),
        "objective": shown(row.get("objective")),
        "branch": shown(row.get("branch")),
        "workdir": shown(row.get("workdir")),
        "met": sum(1 for kr in results if isinstance(kr, dict) and kr.get("met") is True),
        "total": len(results),
    }


def stored_order(path: Path) -> list[str]:
    data = read_json(path)
    names = data.get("agents") if isinstance(data, dict) else None
    if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
        return []
    return names


def agent_order(tasks: dict[str, dict], claims: list[dict], stored: list[str]) -> list[str]:
    """Args:
        tasks: the register.
        claims: every office claim; its holder is an agent too.
        stored: the operator's agent order, as `rasci.py agents order` wrote it.

    Returns:
        The agents `rasci.py agents order` accepts: the stored ones it still
        knows first, in their order, then the workers of open tasks by pin,
        then the remaining office holders by name.
    """
    names: list[str] = []
    for _, row in sorted(tasks.items(), key=pinned):
        worker = row.get("worker")
        if status_of(row) not in ENDED and isinstance(worker, str) and worker not in names:
            names.append(worker)
    names += [name for name in ordered({claim["address"] or claim["session"] for claim in claims}) if name not in names]
    known = [name for name in names if ORDER_NAME.fullmatch(name)]
    listed = [name for name in dict.fromkeys(stored) if name in known]
    return [*listed, *(name for name in known if name not in listed)]
