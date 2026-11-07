from __future__ import annotations

import itertools
import statistics

from .council import agent
from .records import iso_epoch, shown
from .register import ENDED, OPERATOR, parties, register_row, status_of
from .signed import signing
from .tree import inside

ENDED_SHOWN = 100
OPEN_SHOWN = 300
QUEUE_SHOWN = 100
PARTIES_SHOWN = 40
TEXT_SHOWN = 500
FIBONACCI = (1, 2, 3, 5, 8, 13, 21, 34, 55, 89)
LETTERS = "RASCI"
HOTFIX = "hotfix/"
QUEUE = "queue/"


def kind_of(task: str) -> str:
    if task.startswith(OPERATOR):
        return "command"
    return "hotfix" if task.startswith(HOTFIX) else "task"


def editable(task: str, row: dict) -> bool:
    shown_whole = len(task) <= TEXT_SHOWN and signing.TASK.fullmatch(task) is not None
    return shown_whole and kind_of(task) == "task" and status_of(row) not in ENDED


def fibonacci(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value in FIBONACCI


def estimates_of(row: dict) -> dict[str, dict]:
    raw = row.get("estimates")
    found = {}
    for party, entry in itertools.islice(raw.items(), PARTIES_SHOWN) if isinstance(raw, dict) else ():
        if isinstance(entry, dict) and fibonacci(entry.get("value")) and fibonacci(entry.get("complexity")):
            found[str(party)[:TEXT_SHOWN]] = {"value": entry["value"], "complexity": entry["complexity"]}
    return found


def wsjf(estimates: dict[str, dict]) -> dict | None:
    """Returns:
        Median business value, median complexity and their quotient, the
        same reading as rasci.py's wsjf(); None without an estimate.
    """
    if not estimates:
        return None
    value = statistics.median(entry["value"] for entry in estimates.values())
    complexity = statistics.median(entry["complexity"] for entry in estimates.values())
    return {"value": value, "complexity": complexity, "score": round(value / complexity, 2)}


def prio_of(row: dict) -> int | None:
    prio = row.get("prio")
    return prio if isinstance(prio, int) and not isinstance(prio, bool) else None


def roles_of(row: dict) -> dict[str, str]:
    letters = {party[:TEXT_SHOWN]: "".join(letter for letter in LETTERS if letter in held) for party, held in itertools.islice(parties(row).items(), PARTIES_SHOWN)}
    return {party: held for party, held in letters.items() if held}


def worktrees(scan: dict) -> list[dict]:
    found = []
    for repo in scan["repos"]:
        trees = [(entry["name"], tree) for entry in repo["branches"] for tree in entry["worktrees"]] + [("", tree) for tree in repo["detached"]]
        found += [{"path": tree["path"], "branch": name, "repo": repo["name"], "flow": tree["flow"], "open_work": tree["open_work"]} for name, tree in trees]
    return found


def placed(row: dict, trees: list[dict]) -> dict | None:
    """Returns:
        The worktree a register row or queue entry works in: the innermost
        one holding its workdir, else the only one on its branch.
    """
    workdir, name = row.get("workdir"), row.get("branch")
    if isinstance(workdir, str) and workdir.startswith("/"):
        holding = [tree for tree in trees if inside(workdir, tree["path"])]
        if holding:
            return max(holding, key=lambda tree: len(tree["path"]))
    named = [tree for tree in trees if isinstance(name, str) and name and tree["branch"] == name]
    return named[0] if len(named) == 1 else None


def located(row: dict, trees: list[dict], open_task: bool) -> dict:
    tree = placed(row, trees)
    own = ["task"] if open_task else []
    if tree is None:
        return {"worktree": "", "worktree_branch": "", "repo": "", "flow": None, "open_work": own}
    return {"worktree": tree["path"], "worktree_branch": tree["branch"], "repo": tree["repo"], "flow": tree["flow"], "open_work": [*own, *tree["open_work"]]}


def task_row(task: str, row: dict, trees: list[dict]) -> dict:
    estimates = estimates_of(row)
    ended = status_of(row) in ENDED
    shown_row = {key: value[:TEXT_SHOWN] if isinstance(value, str) else value for key, value in register_row(task, row).items()}
    return {
        **shown_row,
        "kind": kind_of(task),
        "ended": ended,
        "editable": editable(task, row),
        "prio": prio_of(row),
        "estimates": estimates,
        "wsjf": wsjf(estimates),
        "roles": roles_of(row),
        "queue": None,
        **located(row, trees, not ended),
    }


def queue_row(entry: dict, created: float, trees: list[dict]) -> dict:
    text = {name: shown(entry.get(name))[:TEXT_SHOWN] for name in ("id", "cmd", "kind", "task", "workdir")}
    return {
        "task": f"{QUEUE}{text['id']}",
        "title": text["cmd"],
        "status": "running" if entry.get("status") == "active" else "awaiting",
        "worker": agent(entry.get("name"))[:TEXT_SHOWN] or "-",
        "responsible": "-",
        "accountable": "-",
        "objective": "-",
        "branch": "-",
        "workdir": text["workdir"],
        "met": 0,
        "total": 0,
        "kind": "queue",
        "ended": False,
        "editable": False,
        "prio": None,
        "estimates": {},
        "wsjf": None,
        "roles": {},
        "queue": {"kind": text["kind"], "parent": text["task"], "enqueued": created},
        **located(entry, trees, False),
    }


def rank(task: str, row: dict) -> tuple:
    prio, score = prio_of(row), wsjf(estimates_of(row))
    return (prio is None, prio or 0, score is None, -(score["score"] if score else 0), task)


def task_rows(tasks: dict[str, dict], queue: list[tuple[dict, float]], scan: dict) -> list[dict]:
    """Args:
        tasks: the register rows by task.
        queue: the kvb-org-queue entries with their enqueue time.
        scan: the pkgmgr tree as read_tree() maps it.

    Returns:
        The OPEN_SHOWN first open tasks in register rank (pin, then WSJF,
        then name), the QUEUE_SHOWN oldest queue jobs, then the ENDED_SHOWN
        most recently ended tasks; each with its worktree's flow and open work.
    """
    trees = worktrees(scan)
    current = sorted((task for task, row in tasks.items() if status_of(row) not in ENDED), key=lambda task: rank(task, tasks[task]))
    ended = sorted((task for task, row in tasks.items() if status_of(row) in ENDED), key=lambda task: (-(iso_epoch(tasks[task].get("end")) or 0), task))
    jobs = sorted(queue, key=lambda pair: pair[1])[:QUEUE_SHOWN]
    return [
        *(task_row(task, tasks[task], trees) for task in current[:OPEN_SHOWN]),
        *(queue_row(entry, created, trees) for entry, created in jobs),
        *(task_row(task, tasks[task], trees) for task in ended[:ENDED_SHOWN]),
    ]
