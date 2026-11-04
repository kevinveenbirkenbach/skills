#!/usr/bin/env python3
"""Forward the old news.py calls to radio.py of the kvb-org-radio skill, which owns the same store.

Args:
    post "<text>" [--to <name> ...] [--session <id>], hook, show [--all]
        [--session <id>]: passed to radio.py unchanged; see its docstring.

Exit codes:
    radio.py's; when radio.py is missing, 0 for hook and 2 for the rest.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

RADIO = Path(__file__).resolve().parents[2] / "kvb-org-radio" / "scripts" / "radio.py"


def main() -> int:
    if not RADIO.is_file():
        # A UserPromptSubmit hook exiting 2 blocks every prompt of the session.
        if sys.argv[1:2] == ["hook"]:
            return 0
        print(f"news: {RADIO} is missing; install the kvb-org-radio skill", file=sys.stderr)
        return 2
    os.execv(sys.executable, [sys.executable, str(RADIO), *sys.argv[1:]])


if __name__ == "__main__":
    sys.exit(main())
