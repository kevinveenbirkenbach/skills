#!/usr/bin/env python3
"""Usage:
    popups.py allowed SOURCE

Args:
    allowed: exit 0 when SOURCE may show a desktop popup now, MUTED (3) when
        the operator switched it off or snoozed it in the hub's radio Device
        card. A missing, linked, unreadable or malformed notify.json, or one
        that names SOURCE wrongly, allows it, so a broken file never silences
        an alarm; a caller treats every status but MUTED, a crash included,
        as allowed.
    SOURCE: resources (watch.py), mayday (radio.py) or dream
        (kvb-dream/hooks/notify.sh).

Environment:
    AGENTS_COUNCIL_ROOT, XDG_STATE_HOME, HOME: the council directory
        councilroot.py resolves; the hub writes notify.json into it on every
        signed settings save.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path
from types import ModuleType

SOURCES = ("resources", "mayday", "dream")
NOTIFY = "notify.json"
MUTED = 3


def sibling(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"kvb_popups_{name}", Path(__file__).resolve().parent / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def allowed(root: Path, source: str, now: float) -> bool:
    """Args:
        root: the council directory holding notify.json.
        source: one of SOURCES.
        now: the current time in epoch seconds.

    Returns:
        False only while notify.json names source off, or snoozed until a
        time after now; True for every unreadable or malformed state.
    """
    try:
        entry = json.loads(sibling("nofollow").read_text(root, root / NOTIFY))[source]
        on, until = entry["on"], entry["until"]
    except (OSError, ValueError, KeyError, TypeError):
        return True
    if not isinstance(on, bool) or isinstance(until, bool) or not isinstance(until, int | float):
        return True
    return on and until <= now


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] != "allowed" or argv[1] not in SOURCES:
        print(__doc__, file=sys.stderr)
        return 2
    return 0 if allowed(sibling("councilroot").root(), argv[1], time.time()) else MUTED


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
