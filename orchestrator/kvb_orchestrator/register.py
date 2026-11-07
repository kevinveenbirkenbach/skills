from __future__ import annotations

from pathlib import Path

from .council import HUMAN, agent, ordered
from .fields import ORDER_NAME
from .records import read_json, shown

REGISTER = "rasci.json"
AGENT_ORDER = "agent-order.json"
OPERATOR = "operator/"
ENDED = ("done", "stopped")


def read_register(path: Path) -> dict[str, dict]:
    data = read_json(path)
    if not isinstance(data, dict):
        return {}
    return {task: row for task, row in data.items() if isinstance(row, dict)}


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


def operator_rows(tasks: dict[str, dict]) -> list[dict]:
    return [
        {
            "task": task,
            "command": shown(row.get("title")),
            "directory": shown(row.get("workdir")),
            "why": shown(row.get("description")),
            "check": shown(row.get("check")),
            "status": status_of(row),
        }
        for task, row in sorted(tasks.items())
        if is_open(task, row, True)
    ]


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


def register_rows(tasks: dict[str, dict]) -> list[dict]:
    return [register_row(task, row) for task, row in sorted(tasks.items(), key=pinned) if is_open(task, row, False)]


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
