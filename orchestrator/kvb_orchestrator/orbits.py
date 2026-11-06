from __future__ import annotations

import bisect
import functools
import itertools
import math
from collections.abc import Callable

from .council import agent
from .names import Directory
from .register import ENDED, parties, status_of

HALF_LIFE = 1800.0
INNER = 150.0
OUTER = 300.0
TRACK_STEPS = 12


def pair_weight(weights: dict[tuple[str, str], float], first: str, second: str) -> float:
    return weights.get((min(first, second), max(first, second)), 0.0)


def chain(names: list[str], weights: dict[tuple[str, str], float], activity: dict[str, float]) -> list[str]:
    left = sorted(names, key=lambda name: (name.lower(), name))
    if not left:
        return []
    current = max(left, key=lambda name: activity[name])
    order = [current]
    left.remove(current)
    while left:
        last = current
        current = max(left, key=lambda name: (pair_weight(weights, last, name), activity[name]))
        order.append(current)
        left.remove(current)
    return order


def affinity(nodes: list[dict], radio: list[dict], tasks: dict[str, dict], claims: list[dict], end: float, key_of: Callable[[str], str]) -> dict:
    """Args:
        nodes: graph nodes keyed by session; chair and session nodes take part.
        radio: rows with ts, source and targets as node keys.
        tasks: register rows; workers and role holders are names.
        claims: claims; their session is a node key.
        end: the moment the decay counts back from.
        key_of: maps a name to its node key.

    Returns:
        orbit: {key: {angle, radius}}, closer and inner for agents that talk
            or work together recently; order: the keys around the circle.
    """
    names = [node["id"] for node in nodes if node["kind"] in ("chair", "session")]
    activity = dict.fromkeys(names, 0.0)
    weights: dict[tuple[str, str], float] = {}

    def link(first: str, second: str, amount: float) -> None:
        if first != second and first in activity and second in activity:
            pair = (min(first, second), max(first, second))
            weights[pair] = weights.get(pair, 0.0) + amount
            activity[first] += amount
            activity[second] += amount

    for row in radio:
        fade = 0.5 ** (max(end - row["ts"], 0.0) / HALF_LIFE)
        if row["source"] in activity and not row["targets"]:
            activity[row["source"]] += fade
        for target in row["targets"]:
            link(row["source"], target, fade)
    places: dict[str, set[str]] = {}
    for task, row in sorted(tasks.items()):
        if status_of(row) in ENDED:
            continue
        members = {key_of(agent(row.get("worker"))), *map(key_of, parties(row))} | {claim["session"] for claim in claims if claim["office"] == task}
        members.discard("")
        for first, second in itertools.combinations(sorted(members), 2):
            link(first, second, 1.0)
        for place in (row.get("workdir"), row.get("branch")):
            if isinstance(place, str) and place.strip():
                places.setdefault(place.strip(), set()).update(members)
    for members in places.values():
        for first, second in itertools.combinations(sorted(members), 2):
            link(first, second, 1.0)
    for node in nodes:
        if node["kind"] == "subagent" and node["parent"] in activity:
            activity[node["parent"]] += 1.0
    order = chain(names, weights, activity)
    gaps = [1.0 / (1.0 + pair_weight(weights, first, second)) for first, second in zip(order, order[1:] + order[:1], strict=True)]
    total = sum(gaps) or 1.0
    top = max(activity.values(), default=0.0)
    angle = -math.pi / 2
    orbit = {}
    for name, gap in zip(order, gaps, strict=True):
        share = activity[name] / top if top > 0 else 0.0
        orbit[name] = {"angle": round(angle, 4), "radius": round(OUTER - (OUTER - INNER) * share, 2)}
        angle += 2 * math.pi * gap / total
    return {"orbit": orbit, "order": order}


def track(nodes: list[dict], radio: list[dict], tasks: dict[str, dict], claims: list[dict], span: tuple[float, float], directory: Directory, steps: int) -> list[dict]:
    """Args:
        nodes: graph nodes as affinity takes them.
        radio: rows with ts, source and targets as node keys, sorted by ts.
        tasks: register rows.
        claims: claims.
        span: the first and the last moment to sample.
        directory: resolves a name to its node key at a moment.
        steps: the intervals between the samples; 0 samples nothing.

    Returns:
        steps + 1 samples {ts, orbit}, evenly spaced over span, each orbit the
        affinity layout of the radio heard up to its moment.
    """
    if steps <= 0:
        return []
    start, end = span
    stamps = [row["ts"] for row in radio]
    samples = []
    for moment in [start + (end - start) * index / steps for index in range(steps)] + [end]:
        heard = radio[: bisect.bisect_right(stamps, moment)]
        layout = affinity(nodes, heard, tasks, claims, moment, functools.partial(directory.key, ts=moment))
        samples.append({"ts": moment, "orbit": layout["orbit"]})
    return samples
