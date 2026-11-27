from __future__ import annotations

import json
import math
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path

from .crons import outcome_of
from .records import shown
from .skill_scripts import script_env
from .tasks import QUEUE_SHOWN, TEXT_SHOWN, prio_of

QUEUE_SCRIPT = "kvb-org-queue/scripts/queue.py"
ORDER_ARGS = ("list", "--json")
ORDER_SECONDS = 20
ORDER_TIMEOUT = 10
ORDER_LIMIT = 1 << 20
TRACE_SHOWN = 20
POSITION_SHOWN = 32
CLASSES = ("hotfix", "fix", "feature", "main")
STATUSES = ("waiting", "active")
LEARNED_ARGS = ("learned", "--json")
LEARNED_KEYS = {"kinds": dict, "signatures": list, "budget_percent": dict, "ram_cap_percent": dict, "load_limits": dict, "slot_limits": dict, "history": list}


def amount(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value) or value < 0:
        return None
    return float(value)


def text(value: object) -> str:
    return value[:TEXT_SHOWN] if isinstance(value, str) else ""


def position_of(value: object) -> int | str | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return value[:POSITION_SHOWN] if isinstance(value, str) and value else None


def steps_of(value: object) -> list[str]:
    return [step[:TEXT_SHOWN] for step in value[:TRACE_SHOWN] if isinstance(step, str)] if isinstance(value, list) else []


def bounded(value: object) -> str | None:
    return value if isinstance(value, str) and len(value) <= TEXT_SHOWN else None


def score_of(value: object) -> float | None:
    return amount(value.get("score") if isinstance(value, dict) else value)


def queue_job(raw: object) -> dict | None:
    """Args:
        raw: one row of `queue.py list --json`.

    Returns:
        The row as the board shows it, each field of one type and bounded:
        position an int or a word such as run, class one of CLASSES, prio an
        int, wsjf (a number or {"score"}), waited_s and eta_s non-negative
        numbers, status one of STATUSES, each else None; trace at most
        TRACE_SHOWN strings; agent falls back to name; override true only
        for a row queue.py marked overridden. None for a row without a
        string id.
    """
    if not isinstance(raw, dict) or not isinstance(raw.get("id"), str) or not raw["id"]:
        return None
    klass = bounded(raw.get("class"))
    return {
        "position": position_of(raw.get("position")),
        "id": raw["id"][:TEXT_SHOWN],
        "kind": text(raw.get("kind")),
        "task": bounded(raw.get("task")),
        "session": text(raw.get("session")),
        "agent": text(raw.get("agent", raw.get("name"))),
        "class": klass if klass in CLASSES else None,
        "prio": prio_of(raw),
        "wsjf": score_of(raw.get("wsjf")),
        "waited_s": amount(raw.get("waited_s")),
        "eta_s": amount(raw.get("eta_s")),
        "reason": text(raw.get("reason")),
        "trace": steps_of(raw.get("trace")),
        "status": raw["status"] if raw.get("status") in STATUSES else None,
        "override": raw.get("override") is True,
    }


def lines_of(stdout: str) -> list | None:
    try:
        return [json.loads(line) for line in stdout.splitlines() if line.strip()] or None
    except (ValueError, RecursionError):
        return None


def parsed(stdout: str) -> object:
    try:
        return json.loads(stdout)
    except (ValueError, RecursionError):
        return lines_of(stdout)


def rows_of(stdout: str) -> list | None:
    data = parsed(stdout)
    if isinstance(data, dict):
        data = data.get("entries") if "entries" in data else [data] if "id" in data else None
    return data if isinstance(data, list) else None


def queue_jobs(stdout: str) -> list[dict] | None:
    """Args:
        stdout: what `queue.py list --json` printed: a JSON list of rows,
            an object holding them under entries, or one row object per
            line.

    Returns:
        queue_job() of each row in grant order, each id once, at most
        QUEUE_SHOWN; None when the output holds no such rows.
    """
    rows = rows_of(stdout)
    if rows is None:
        return None
    found: dict[str, dict] = {}
    for job in map(queue_job, rows):
        if job is not None and job["id"] not in found:
            found[job["id"]] = job
    return list(found.values())[:QUEUE_SHOWN]


def live_ids(queue: list[tuple[dict, float]]) -> frozenset[str]:
    return frozenset(shown(entry.get("id")) for entry, _ in queue if outcome_of(entry) is None)


def grant_order(chain: list[tuple[str, bool]], jobs: list[dict] | None) -> list[tuple[str, bool]]:
    """Args:
        chain: queue_chain(), the hub's own grant order.
        jobs: queue_jobs() of the installed queue.py, None without them.

    Returns:
        The chain in queue.py's order: the ids jobs lists in its order, the
        others after them in the chain's; the chain itself without jobs.
    """
    if jobs is None:
        return chain
    place = {job["id"]: index for index, job in enumerate(jobs)}
    return sorted(chain, key=lambda pair: place.get(pair[0], len(place)))


def queue_output(script: Path, args: tuple[str, ...], home: Path, council: Path) -> str | None:
    """Returns:
        What the installed queue.py printed for args, run read-only with
        script_env(); None when it fails, overruns ORDER_TIMEOUT or prints
        more than ORDER_LIMIT bytes.
    """
    try:
        done = subprocess.run(
            [sys.executable, str(script), *args],
            capture_output=True,
            timeout=ORDER_TIMEOUT,
            env=script_env(home, council),
            stdin=subprocess.DEVNULL,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if done.returncode != 0 or len(done.stdout) > ORDER_LIMIT:
        return None
    return done.stdout.decode("utf-8", errors="replace")


def learned_of(stdout: str | None) -> dict | None:
    """Returns:
        What `queue.py learned --json` printed when it is an object holding
        every key of LEARNED_KEYS with its type, else None.
    """
    data = None if stdout is None else parsed(stdout)
    if not isinstance(data, dict) or not all(isinstance(data.get(key), kind) for key, kind in LEARNED_KEYS.items()):
        return None
    return {key: data[key] for key in LEARNED_KEYS}


@dataclass
class QueueOrder:
    script: Path
    council: Path
    home: Path
    lock: threading.Lock = field(default_factory=threading.Lock)
    cached: list[dict] | None = None
    live: frozenset[str] | None = None
    at: float = 0.0

    def run(self) -> list[dict] | None:
        stdout = queue_output(self.script, ORDER_ARGS, self.home, self.council)
        return None if stdout is None else queue_jobs(stdout)

    def learned(self) -> dict:
        """Returns:
            {"learned": learned_of() of a `queue.py learned --json` run, None
            while the installed queue.py prints none}; the hub never writes
            the queue config, the host runner does (`queue.py config set`).
        """
        return {"learned": learned_of(queue_output(self.script, LEARNED_ARGS, self.home, self.council))}

    def get(self, live: frozenset[str], now: float) -> list[dict] | None:
        """Args:
            live: live_ids() of the queue entries the hub reads.
            now: epoch seconds.

        Returns:
            [] while no entry is live, without a run. Else queue_jobs() of a
            `queue.py list --json` run, run again once ORDER_SECONDS passed
            or the live ids changed; while another request runs it, the rows
            read before. None while the installed queue.py lists no JSON,
            fails or overruns ORDER_TIMEOUT, so the board keeps the hub's own
            order and the page says why.
        """
        if not live:
            return []
        if not self.lock.acquire(blocking=False):
            return self.cached
        try:
            if live != self.live or now - self.at >= ORDER_SECONDS:
                self.cached, self.live, self.at = self.run(), live, now
            return self.cached
        finally:
            self.lock.release()
