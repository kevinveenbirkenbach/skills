"""Returns:
    LIMITS_SCRIPT: the installed limits.py the hub reads, checks and writes
        <council>/limits.json with (requirement 084), so it refuses exactly
        what queue.py and watch.py refuse.
    TARGET_SCRIPT: the installed aimd.py naming the live target file.
    PROFILE_TABLE: the profiles of decision 3, per metric (lower, upper,
        stop, mayday); cpu and ram hold the profile's band (Calm 50 to 70,
        Balanced 70 to 90, Max 80 to 95), and every value grows from Calm
        over Balanced to Max, so a calmer profile is never looser. Balanced
        keeps the limits.py example but for the ram band.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from types import ModuleType

from .errors import ToolError
from .fields import decode, expect
from .records import read_json
from .signed import signing
from .skill_scripts import script_module

LIMITS_SCRIPT = "kvb-org-organize/scripts/limits.py"
TARGET_SCRIPT = "kvb-org-queue/scripts/aimd.py"
PROFILE_TABLE = {
    "calm": {"cpu": (50, 70, 85, 95), "ram": (50, 70, 85, 95), "swap": (10, 40, 75, 90), "disk": (60, 75, 90, 95), "psi": (1, 5, 20, 40)},
    "balanced": {"cpu": (70, 90, 95, 99), "ram": (70, 90, 94, 97), "swap": (20, 60, 90, 97), "disk": (70, 85, 95, 98), "psi": (1, 10, 30, 60)},
    "max": {"cpu": (80, 95, 98, 99), "ram": (80, 95, 97, 99), "swap": (30, 70, 93, 98), "disk": (75, 90, 96, 99), "psi": (2, 15, 40, 70)},
}
FILE_MODE = 0o600
SAVING = threading.Lock()


def limits_module(skills: Path) -> ModuleType:
    """Returns:
        The installed limits.py; ToolError while it is missing or lacks the
        reader and the check, so the hub never writes a file it cannot check.
    """
    module = script_module(skills / LIMITS_SCRIPT)
    if module is None or not all(callable(getattr(module, name, None)) for name in ("problem", "read")):
        raise ToolError(f"{LIMITS_SCRIPT} is not installed: the hub checks the limits with it")
    return module


def profiles(module: ModuleType) -> dict[str, dict[str, dict[str, float]]]:
    return {name: {metric: dict(zip(module.LEVELS, row[metric], strict=True)) for metric in module.METRICS} for name, row in PROFILE_TABLE.items()}


def checked(module: ModuleType, value: object) -> dict:
    """Returns:
        value, once limits.py problem() finds no fault in it; ToolError
        naming the fault otherwise.
    """
    why = module.problem(value)
    if why is not None:
        raise ToolError(why)
    return value


def loosened(module: ModuleType, value: dict, held: dict | None) -> list[str]:
    """Args:
        value: checked limits.
        held: the limits in force (limits.py read()), None while the config
            applies, which the hub cannot compare against.

    Returns:
        `<metric>.<level>` of every value above the one in force: a higher
        lower or upper admits more load, a higher stop or mayday raises an
        alarm threshold; every value while none is in force.
    """
    pairs = [(metric, level) for metric in module.METRICS for level in module.LEVELS]
    return [f"{metric}.{level}" for metric, level in pairs if held is None or value[metric][level] > held[metric][level]]


def live_target(skills: Path, council: Path) -> dict[str, float] | None:
    """Returns:
        {cpu, ram}: the AIMD target queue.py last stored, each a finite
        number or None; None while aimd.py is missing or no target is stored.
    """
    aimd = script_module(skills / TARGET_SCRIPT)
    if aimd is None or not isinstance(getattr(aimd, "NAME", None), str) or not callable(getattr(aimd, "number", None)):
        return None
    stored = read_json(council / aimd.NAME)
    if not isinstance(stored, dict):
        return None
    return {resource: stored[resource] if aimd.number(stored.get(resource)) else None for resource in aimd.RESOURCES}


class Limiting:
    def limits_view(self) -> dict:
        """Returns:
            {limits, why, target, profiles, metrics, levels}: the limits in
            force (None while the config applies), why limits.json was
            refused (None when it was not), the live target (live_target()),
            the profiles of PROFILE_TABLE and the metric and level names.
        """
        module = limits_module(self.scripts.skills)
        held, why = module.read(self.council)
        return {"limits": held, "why": why, "target": live_target(self.scripts.skills, self.council), "profiles": profiles(module),
                "metrics": list(module.METRICS), "levels": list(module.LEVELS)}

    def limits_items(self, module: ModuleType, value: dict) -> list[dict]:
        held, _ = module.read(self.council)
        return [signing.limits_item(value)] if loosened(module, value, held) else []

    def sign_limits(self, body: bytes) -> dict:
        """Args:
            body: {limits}: the whole limits object the page wants to save.

        Returns:
            challenge_for() over the limits item when a value loosens, with
            payload None when every value stays or tightens.
        """
        payload = decode(body)
        expect(payload, ("limits",))
        module = limits_module(self.scripts.skills)
        return self.challenge_for(self.limits_items(module, checked(module, payload["limits"])))

    def save_limits(self, body: bytes) -> dict:
        """Args:
            body: {limits, proof}: the whole limits object, which carries a
                batch of staged changes at once (requirement 091), and,
                when any value of it loosens against the limits in force at
                this save, one passkey proof over signing.limits_item() of
                exactly it, which covers every looser value of the batch.

        Returns:
            limits_view() after the write; ToolError (400) for limits
            limits.py refuses or a looser save without a valid proof, which
            writes nothing.
        """
        payload = decode(body)
        expect(payload, ("limits", "proof"))
        module = limits_module(self.scripts.skills)
        value = checked(module, payload["limits"])
        with SAVING:
            for item in self.limits_items(module, value):
                self.operator_proven(payload["proof"], item)
            self.council.mkdir(parents=True, exist_ok=True)
            module.nofollow.replace(self.council, self.council / module.NAME, json.dumps(value, indent=1, sort_keys=True) + "\n", FILE_MODE)
        return self.limits_view()
