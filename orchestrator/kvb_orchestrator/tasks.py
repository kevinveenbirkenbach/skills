from __future__ import annotations

import itertools
import statistics

from .council import HUMAN, agent
from .crons import outcome_of
from .records import epoch, iso_epoch, shown
from .register import ENDED, OPERATOR, parties, register_row, status_of
from .signed import signing
from .tree import inside

ENDED_SHOWN = 100
OPEN_SHOWN = 300
QUEUE_SHOWN = 100
PARTIES_SHOWN = 40
AFTER_SHOWN = 40
TEXT_SHOWN = 500
FIBONACCI = (1, 2, 3, 5, 8, 13, 21, 34, 55, 89)
LETTERS = "RASCI"
HOTFIX = "hotfix/"
QUEUE = "queue/"
HOUR = 3600


def kind_of(task: str) -> str:
    if task.startswith(OPERATOR):
        return "command"
    return "hotfix" if task.startswith(HOTFIX) else "task"


def movable(task: str) -> bool:
    shown_whole = len(task) <= TEXT_SHOWN and signing.TASK.fullmatch(task) is not None
    return shown_whole and kind_of(task) == "task"


def editable(task: str, row: dict) -> bool:
    return movable(task) and status_of(row) not in ENDED


def fibonacci(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value in FIBONACCI


def estimates_of(row: dict) -> dict[str, dict]:
    """Returns:
        Each party's Fibonacci business value and complexity; the
        Operator's complexity is None where it recorded a business value
        alone.
    """
    raw = row.get("estimates")
    found = {}
    for party, entry in itertools.islice(raw.items(), PARTIES_SHOWN) if isinstance(raw, dict) else ():
        alone = party == HUMAN and isinstance(entry, dict) and "complexity" not in entry
        if isinstance(entry, dict) and fibonacci(entry.get("value")) and (alone or fibonacci(entry.get("complexity"))):
            found[str(party)[:TEXT_SHOWN]] = {"value": entry["value"], "complexity": entry.get("complexity")}
    return found


def business_value(estimates: dict[str, dict]) -> float | None:
    if HUMAN in estimates:
        return estimates[HUMAN]["value"]
    return statistics.median(entry["value"] for entry in estimates.values()) if estimates else None


def points(estimates: dict[str, dict]) -> float | None:
    sized = [entry["complexity"] for entry in estimates.values() if entry["complexity"] is not None]
    return statistics.median(sized) if sized else None


def wsjf(estimates: dict[str, dict]) -> dict | None:
    """Returns:
        Business value, median complexity and their quotient, the same
        reading as rasci.py's wsjf(): the Operator's business value where
        it gave one, else the median; None while no estimate carries a
        complexity.
    """
    complexity = points(estimates)
    if complexity is None:
        return None
    value = business_value(estimates)
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


def after_of(row: dict) -> list[str]:
    raw = row.get("after")
    return [other for other in raw[:AFTER_SHOWN] if isinstance(other, str) and len(other) <= TEXT_SHOWN] if isinstance(raw, list) else []


def task_row(task: str, row: dict, trees: list[dict]) -> dict:
    estimates = estimates_of(row)
    ended = status_of(row) in ENDED
    shown_row = {key: value[:TEXT_SHOWN] if isinstance(value, str) else value for key, value in register_row(task, row).items()}
    return {
        **shown_row,
        "kind": kind_of(task),
        "ended": ended,
        "editable": editable(task, row),
        "movable": movable(task),
        "prio": prio_of(row),
        "estimates": estimates,
        "wsjf": wsjf(estimates),
        "value": business_value(estimates),
        "points": points(estimates),
        "start": iso_epoch(row.get("start")),
        "end": iso_epoch(row.get("end")) if ended else None,
        "updated": iso_epoch(row.get("updated")),
        "after": after_of(row),
        "base": shown(row.get("base"))[:TEXT_SHOWN],
        "roles": roles_of(row),
        "queue": None,
        **located(row, trees, not ended),
    }


def queue_status(entry: dict, found: dict | None) -> str:
    if found is not None:
        return "done" if found.get("state") == "ended" and found.get("exit") == 0 else "stopped"
    return "running" if entry.get("status") == "active" else "awaiting"


def queue_row(entry: dict, created: float, trees: list[dict]) -> dict:
    text = {name: shown(entry.get(name))[:TEXT_SHOWN] for name in ("id", "cmd", "kind", "task", "workdir")}
    found = outcome_of(entry)
    ended = found is not None
    granted = entry.get("status") == "active" or ended
    return {
        "task": f"{QUEUE}{text['id']}",
        "title": text["cmd"],
        "status": queue_status(entry, found),
        "worker": agent(entry.get("name"))[:TEXT_SHOWN] or "-",
        "responsible": "-",
        "accountable": "-",
        "objective": "-",
        "branch": "-",
        "workdir": text["workdir"],
        "met": 0,
        "total": 0,
        "kind": "queue",
        "ended": ended,
        "editable": False,
        "movable": False,
        "prio": None,
        "estimates": {},
        "wsjf": None,
        "value": None,
        "points": None,
        "start": (epoch(entry.get("granted")) or created) if granted else None,
        "end": epoch(found.get("end")) if found is not None else None,
        "updated": None,
        "after": [],
        "base": "-",
        "roles": {},
        "queue": {"kind": text["kind"], "parent": text["task"], "enqueued": created, "exit": found.get("exit") if found is not None else None},
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


def register_ranks(tasks: dict[str, dict], agents: list[str]) -> dict[str, int]:
    """Returns:
        Each open task's index in rasci.py's ranked(): pin, WSJF, the
        worker's place in the operator's agent order, then the name.
    """
    order = {name: index for index, name in enumerate(agents)}

    def key(task: str) -> tuple:
        worker = tasks[task].get("worker")
        return (*rank(task, tasks[task])[:4], order.get(worker, len(order)) if isinstance(worker, str) else len(order), task)

    current = sorted((task for task, row in tasks.items() if status_of(row) not in ENDED), key=key)
    return {task: index for index, task in enumerate(current)}


def queue_chain(queue: list[tuple[dict, float]], tasks: dict[str, dict], agents: list[str], now: float) -> list[tuple[str, bool]]:
    """Args:
        queue: the kvb-org-queue entries with their enqueue time.
        tasks: the register rows by task.
        agents: the operator's agent order.
        now: epoch seconds.

    Returns:
        The entry ids in grant order, each with whether it waits: the
        active ones by grant time, then the waiting ones as queue.py's
        ordered() sorts them (hotfix first, then the register rank less one
        per whole hour waited, then the holder's agent order, then the
        enqueue sequence).
    """
    ranks = register_ranks(tasks, agents)
    order = {name: index for index, name in enumerate(agents)}

    def waiting_key(pair: tuple[dict, float]) -> tuple:
        entry, created = pair
        task, name, seq = entry.get("task"), entry.get("name"), entry.get("seq")
        hours = int((now - created) // HOUR)
        place = ranks[task] if isinstance(task, str) and task in ranks else len(ranks)
        holder = order[name] if isinstance(name, str) and name in order else len(order)
        return (not entry.get("hotfix"), place - hours, holder, seq if isinstance(seq, int) and not isinstance(seq, bool) else 0)

    active = sorted((pair for pair in queue if pair[0].get("status") == "active" and outcome_of(pair[0]) is None), key=lambda pair: epoch(pair[0].get("granted")) or pair[1])
    waiting = sorted((pair for pair in queue if pair[0].get("status") == "waiting"), key=waiting_key)
    return [(shown(entry.get("id"))[:TEXT_SHOWN], entry.get("status") == "waiting") for entry, _ in [*active, *waiting]]


def queue_line(chain: list[tuple[str, bool]], queue: list[tuple[dict, float]]) -> list[str]:
    """Args:
        chain: queue_chain().
        queue: the kvb-org-queue entries with their enqueue time.

    Returns:
        The tasks holding a live queue entry, each once, in the grant order
        of their first entry.
    """
    owners = {shown(entry.get("id"))[:TEXT_SHOWN]: entry.get("task") for entry, _ in queue}
    line: list[str] = []
    for job, _ in chain:
        task = owners.get(job)
        if isinstance(task, str) and len(task) <= TEXT_SHOWN and task not in line:
            line.append(task)
    return line


def branch_of(row: dict) -> str:
    return row["branch"] if row["branch"] != "-" else row["worktree_branch"]


def task_edges(rows: list[dict], chain: list[tuple[str, bool]]) -> list[dict]:
    """Args:
        rows: the shown task rows of task_rows().
        chain: queue_chain().

    Returns:
        One {"from", "to", "kind"} edge per predecessor among the shown
        rows: kind after for an explicit `rasci.py set --after`, base for a
        task whose base branch is another task's branch, queue for each
        waiting queue job and the job ahead of it.
    """
    shown_tasks = {row["task"] for row in rows}
    edges = [{"from": other, "to": row["task"], "kind": "after"} for row in rows for other in row["after"] if other in shown_tasks and other != row["task"]]
    branches: dict[str, list[str]] = {}
    for row in rows:
        if row["kind"] != "queue" and branch_of(row):
            branches.setdefault(branch_of(row), []).append(row["task"])
    edges += [{"from": other, "to": row["task"], "kind": "base"} for row in rows if row["kind"] != "queue" for other in branches.get(row["base"], []) if other != row["task"]]
    jobs = [(f"{QUEUE}{job}", waits) for job, waits in chain]
    edges += [{"from": ahead, "to": job, "kind": "queue"} for (ahead, _), (job, waits) in itertools.pairwise(jobs) if waits and {ahead, job} <= shown_tasks]
    return edges
