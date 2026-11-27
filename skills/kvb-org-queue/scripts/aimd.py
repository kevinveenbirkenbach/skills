"""The self-tuning admission target of kvb-org-queue (requirement 083): additive increase, multiplicative decrease.

queue.py keeps the state in <root>/NAME, next to the kvb-org-organize limits
file: {ram, cpu: the target in percent, psi: the PSI some avg10 at the last
step or None, stepped: that step's epoch seconds, samples: [[epoch seconds,
CPU busy, RAM used], ...] of the last WINDOW_SECONDS}. Pure functions.
STEP and WINDOW_SECONDS are the 2 points and 10 minutes requirement 083
fixes; PSI_CALM is the calm bound while no limits file names psi lower:
below 1 % some avg10 no task waits on memory long enough to slow a job.
"""

from __future__ import annotations

import math

NAME = "limits-target.json"
RESOURCES = ("ram", "cpu")
STEP = 2
WINDOW_SECONDS = 600
PSI_CALM = 1.0


def number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def target(state: dict, band: dict[str, dict[str, float]]) -> dict[str, float]:
    """Args:
        state: the stored state, {} for none.
        band: {low, high} per resource: the lower and the upper limit.

    Returns:
        {ram, cpu}: the stored target kept between low and high, high where
        none is stored, so a fresh queue admits up to the upper limit until
        the host shows pressure.
    """
    return {r: min(band["high"][r], max(band["low"][r], state[r])) if number(state.get(r)) else band["high"][r] for r in RESOURCES}


def kept(samples: object, now: float) -> list[list[float]]:
    rows = samples if isinstance(samples, list) else []
    return [
        row for row in rows
        if isinstance(row, list) and len(row) == 3 and all(number(v) for v in row) and 0 <= now - row[0] <= WINDOW_SECONDS
    ]


def average(samples: list[list[float]]) -> dict[str, float]:
    return {"cpu": sum(row[1] for row in samples) / len(samples), "ram": sum(row[2] for row in samples) / len(samples)}


def stepped(state: dict, band: dict[str, dict[str, float]], load: dict[str, float], pressure: dict[str, float | None],
            psi_calm: float, now: float, every: float) -> dict:
    """Args:
        state: the stored state, {} for none.
        band: {low, high} per resource: the lower and the upper limit.
        load: {ram, cpu} measured now, in percent.
        pressure: the watch memory sample: psi_some (PSI some avg10, None
            without PSI) and swap_out_mb_min (None without a rate).
        psi_calm: the PSI some avg10 below which memory counts as calm (the
            limits file's psi lower, else PSI_CALM).
        now: epoch seconds.
        every: seconds from one step to the next; a pass sooner only adds
            its sample.

    Returns:
        The new state: this sample added, those older than WINDOW_SECONDS
        dropped. Once every seconds passed since the last step, per
        resource the target falls at once to the middle of low and itself
        when the load now passes high, PSI rises (at or above psi_calm and
        above the last step's, or without one) or swap goes out; else it
        rises by STEP, at most to high, while the WINDOW_SECONDS average
        lies below low and PSI is calm.
    """
    samples = [*kept(state.get("samples"), now), [now, load["cpu"], load["ram"]]]
    aim = target(state, band)
    last = state.get("stepped")
    if number(last) and 0 <= now - last < every:
        return {**state, **aim, "samples": samples}
    psi, before = pressure.get("psi_some"), state.get("psi")
    calm = psi is None or psi < psi_calm
    rising = not calm and (not number(before) or psi > before)
    swapping = (pressure.get("swap_out_mb_min") or 0) > 0
    mean = average(samples)
    for r in RESOURCES:
        low, high = band["low"][r], band["high"][r]
        if load[r] > high or rising or swapping:
            aim[r] = (low + aim[r]) / 2
        elif mean[r] < low and calm:
            aim[r] = min(high, aim[r] + STEP)
    return {**state, **aim, "samples": samples, "psi": psi, "stepped": now}
