from __future__ import annotations

from collections import Counter

from .council import HUMAN, agent, ordered, subagent
from .names import Directory
from .orbits import affinity
from .records import shown
from .register import ENDED, parties, status_of

CHAIR = "Maintainer"


def parent_of(roles: dict[str, str], known: set[str], fallback: str) -> str:
    for letter in "AR":
        names = sorted(name for name, letters in roles.items() if letter in letters and name in known)
        if names:
            return names[0]
    return fallback


def duties(name: str, task: str, row: dict, holders: dict[str, dict[str, dict]]) -> dict:
    entry = {"task": task, "title": shown(row.get("title")), "status": status_of(row), "worker": False, "letters": ""}
    return holders.setdefault(name, {}).setdefault(task, entry)


def edges(radio: list[dict], grant_rows: list[dict], chair: str) -> list[dict]:
    counts: Counter[tuple[str, str, str]] = Counter()
    for row in (row for row in radio if row["source"]):
        for target in row["targets"] or ["*"]:
            counts[(row["source"], target, row["class"])] += 1
    for grant in grant_rows:
        counts[(chair, grant["target"], "grant")] += 1
    return [{"source": s, "target": t, "class": c, "count": n} for (s, t, c), n in sorted(counts.items())]


def graph(radio: list[dict], grant_rows: list[dict], tasks: dict[str, dict], claims: list[dict], end: float, directory: Directory) -> dict:
    current = {task: row for task, row in sorted(tasks.items()) if status_of(row) not in ENDED}
    chair = directory.key(CHAIR, end)
    workers = {task: agent(row.get("worker")) for task, row in current.items()}
    keys = {row["source"] for row in radio} | {key for row in radio for key in row["targets"]}
    keys |= {claim["session"] for claim in claims if claim["agent"] and claim["session"] != "-"}
    keys |= {directory.key(name, end) for name in workers.values() if not subagent(name)}
    found = sorted(keys - {"", HUMAN, chair}, key=lambda key: (directory.label(key, end).lower(), key))
    known = {chair, *found}
    moons: dict[str, tuple[str, str]] = {}
    holders: dict[str, dict[str, dict]] = {}
    for task, row in current.items():
        roles: dict[str, str] = {}
        for name, letters in parties(row).items():
            key = directory.key(name, end)
            roles[key] = roles.get(key, "") + letters
        worker = workers[task]
        holder = directory.key(worker, end)
        if subagent(worker):
            parent = parent_of(roles, known, chair)
            holder = f"{worker} @ {parent}"
            moons[holder] = (parent, worker)
        if holder:
            duties(holder, task, row, holders)["worker"] = True
        for key, letters in roles.items():
            duties(key, task, row, holders)["letters"] += letters
    plan = [(HUMAN, "operator", None, HUMAN), (chair, "chair", None, directory.label(chair, end))]
    plan += [(key, "session", None, directory.label(key, end)) for key in found]
    plan += [(moon, "subagent", *moons[moon]) for moon in ordered(set(moons))]
    nodes = [
        {
            "id": key,
            "kind": node_kind,
            "parent": parent,
            "label": label,
            "names": directory.names(key) or [label],
            "timeline": directory.timeline(key) or [{"name": label, "since": end}],
            "tasks": list(holders.get(key, {}).values()),
            "claims": [claim for claim in claims if claim["session"] == key],
        }
        for key, node_kind, parent, label in plan
    ]
    layout = affinity(nodes, radio, tasks, claims, end, lambda name: directory.key(name, end))
    return {"nodes": nodes, "edges": edges(radio, grant_rows, chair), "layout": layout}
